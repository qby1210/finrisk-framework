"""项目唯一的 OpenAI-compatible 大模型客户端。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from llm.types import JsonChatRequest, JsonChatResponse

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


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


class _ProviderMessage(BaseModel):
    content: str


class _ProviderChoice(BaseModel):
    message: _ProviderMessage


class _ProviderResponse(BaseModel):
    model: str
    choices: list[_ProviderChoice] = Field(min_length=1)
    usage: dict[str, object] | None = None


class OpenAICompatibleLLMClient:
    """通过 Chat Completions 协议调用 DeepSeek V4 Flash。"""

    def __init__(self, settings: LLMSettings) -> None:
        if settings.thinking not in {"enabled", "disabled"}:
            raise LLMConfigurationError("FINRISK_LLM_THINKING 只能是 enabled 或 disabled")
        self._settings = settings

    @property
    def model_name(self) -> str:
        return self._settings.model

    async def complete_json(self, request: JsonChatRequest) -> JsonChatResponse:
        """关闭思考模式并严格解析 JSON，防止推理文本混入业务字段。"""

        body: dict[str, object] = {
            "model": self._settings.model,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": self._settings.thinking},
        }
        body.update(request.extra_body)
        timeout = httpx.Timeout(
            self._settings.read_timeout_seconds,
            connect=self._settings.connect_timeout_seconds,
        )
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "FinRisk/1.0",
        }
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    f"{self._settings.base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
                provider_response = _ProviderResponse.model_validate(response.json())
            parsed = json.loads(provider_response.choices[0].message.content)
            data = TypeAdapter(dict[str, object]).validate_python(parsed)
        except httpx.TimeoutException as error:
            raise LLMProviderError("大模型请求超时") from error
        except httpx.HTTPStatusError as error:
            raise LLMProviderError(f"大模型服务返回 HTTP {error.response.status_code}") from error
        except (httpx.HTTPError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise LLMProviderError("大模型服务返回了无法解析的响应") from error
        return JsonChatResponse(
            data=data,
            model=provider_response.model,
            usage=provider_response.usage or {},
        )


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
    )
    return OpenAICompatibleLLMClient(settings)
