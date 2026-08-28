"""项目唯一的 OpenAI-compatible 大模型客户端。"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from time import perf_counter
from typing import Protocol

import httpx
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from llm.types import JsonChatRequest, JsonChatResponse

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class LLMConfigurationError(RuntimeError):
    """大模型调用所需环境变量缺失。"""


class LLMProviderError(RuntimeError):
    """大模型供应商请求失败或返回格式不正确。"""


class LLMClient(Protocol):
    """Offline、Query、Risk 共用的最小 JSON 调用接口。"""

    @property
    def model_name(self) -> str: ...

    async def complete_json(self, request: JsonChatRequest) -> JsonChatResponse: ...


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """DeepSeek/OpenAI-compatible 服务连接参数。"""

    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    thinking: str = "disabled"
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 90.0
    max_retries: int = 2
    max_concurrency: int = 6
    retry_base_seconds: float = 0.6


class _ProviderMessage(BaseModel):
    content: str


class _ProviderChoice(BaseModel):
    message: _ProviderMessage
    finish_reason: str | None = None


class _ProviderResponse(BaseModel):
    model: str
    choices: list[_ProviderChoice] = Field(min_length=1)
    usage: dict[str, object] | None = None


class OpenAICompatibleLLMClient:
    """通过连接池复用、限流和短重试调用 DeepSeek JSON 接口。"""

    def __init__(self, settings: LLMSettings) -> None:
        if settings.thinking not in {"enabled", "disabled"}:
            raise LLMConfigurationError("FINRISK_LLM_THINKING 只能是 enabled 或 disabled")
        if settings.max_retries < 0 or settings.max_concurrency < 1:
            raise LLMConfigurationError("LLM 重试次数和最大并发配置不合法")
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrency)
        timeout = httpx.Timeout(
            settings.read_timeout_seconds,
            connect=settings.connect_timeout_seconds,
        )
        limits = httpx.Limits(
            max_connections=max(4, settings.max_concurrency * 2),
            max_keepalive_connections=max(2, settings.max_concurrency),
            keepalive_expiry=30.0,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "FinRisk/1.1",
            },
        )

    @property
    def model_name(self) -> str:
        return self._settings.model

    async def aclose(self) -> None:
        """关闭共享连接池。"""

        await self._client.aclose()

    async def complete_json(self, request: JsonChatRequest) -> JsonChatResponse:
        """关闭思考模式并严格解析 JSON，瞬时故障最多短重试两次。"""

        body: dict[str, object] = {
            "model": self._settings.model,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": self._settings.thinking},
        }
        body.update(request.extra_body)
        started = perf_counter()
        async with self._semaphore:
            for attempt in range(1, self._settings.max_retries + 2):
                provider_response: _ProviderResponse | None = None
                try:
                    response = await self._client.post(
                        f"{self._settings.base_url.rstrip('/')}/chat/completions",
                        json=body,
                    )
                    response.raise_for_status()
                    provider_response = _ProviderResponse.model_validate(response.json())
                    parsed = json.loads(provider_response.choices[0].message.content)
                    data = TypeAdapter(dict[str, object]).validate_python(parsed)
                    return JsonChatResponse(
                        data=data,
                        model=provider_response.model,
                        usage=provider_response.usage or {},
                        finish_reason=provider_response.choices[0].finish_reason,
                        latency_seconds=round(perf_counter() - started, 6),
                        attempts=attempt,
                    )
                except httpx.TimeoutException as error:
                    if attempt <= self._settings.max_retries:
                        await self._backoff(attempt)
                        continue
                    raise LLMProviderError("大模型请求超时") from error
                except httpx.HTTPStatusError as error:
                    if (
                        error.response.status_code in _RETRYABLE_STATUS_CODES
                        and attempt <= self._settings.max_retries
                    ):
                        await self._backoff(attempt)
                        continue
                    raise LLMProviderError(
                        f"大模型服务返回 HTTP {error.response.status_code}"
                    ) from error
                except (
                    httpx.HTTPError,
                    json.JSONDecodeError,
                    ValidationError,
                    ValueError,
                ) as error:
                    if self._hit_length_limit(provider_response):
                        raise LLMProviderError("大模型输出达到 max_tokens 上限被截断") from error
                    raise LLMProviderError("大模型服务返回了无法解析的响应") from error
        raise LLMProviderError("大模型请求未返回结果")  # pragma: no cover

    async def _backoff(self, attempt: int) -> None:
        await asyncio.sleep(self._settings.retry_base_seconds * (2 ** (attempt - 1)))

    @staticmethod
    def _hit_length_limit(provider_response: _ProviderResponse | None) -> bool:
        """JSON 解析失败时区分输出截断与普通格式错误。"""

        if provider_response is None or not provider_response.choices:
            return False
        return provider_response.choices[0].finish_reason == "length"


def create_llm_client_from_env() -> OpenAICompatibleLLMClient | None:
    """从环境变量创建客户端；未配置密钥时返回 None。"""

    api_key = os.getenv("FINRISK_LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    settings = LLMSettings(
        api_key=api_key,
        base_url=os.getenv("FINRISK_LLM_BASE_URL", DEFAULT_BASE_URL),
        model=os.getenv("FINRISK_LLM_MODEL", DEFAULT_MODEL),
        thinking=os.getenv("FINRISK_LLM_THINKING", "disabled"),
        connect_timeout_seconds=float(os.getenv("FINRISK_LLM_CONNECT_TIMEOUT", "10")),
        read_timeout_seconds=float(os.getenv("FINRISK_LLM_READ_TIMEOUT", "90")),
        max_retries=int(os.getenv("FINRISK_LLM_MAX_RETRIES", "2")),
        max_concurrency=int(os.getenv("FINRISK_LLM_MAX_CONCURRENCY", "6")),
        retry_base_seconds=float(os.getenv("FINRISK_LLM_RETRY_BASE_SECONDS", "0.6")),
    )
    return OpenAICompatibleLLMClient(settings)