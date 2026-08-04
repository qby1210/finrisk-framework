"""FinRisk FastAPI 应用和本地网站入口。"""

from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from application.query_service import QueryProcessingService
from domain.common import ContractModel
from domain.query_models import QueryProcessingResult
from extraction import ExtractionError
from llm import LLMProviderError
from query.classification import LLMRequiredError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "src" / "web" / "static"
MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024

app = FastAPI(
    title="FinRisk 风险识别工作台",
    description="Query 文件读取、六类场景分类、逐句 Risk 输入和原文映射接口",
    version="0.2.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class TextQueryRequest(ContractModel):
    """文字 Query 接口请求。"""

    text: str = Field(min_length=1, max_length=1_000_000, description="待处理完整文本")


class ClassifierStatusResponse(ContractModel):
    """规则和 LLM 场景分类器状态。"""

    taxonomy_version: str
    classifier_version: str
    rule_version: str
    llm_configured: bool
    llm_model: str | None


@lru_cache(maxsize=1)
def get_query_service() -> QueryProcessingService:
    """创建并复用 Query 应用服务。"""

    return QueryProcessingService()


QueryServiceDependency = Annotated[QueryProcessingService, Depends(get_query_service)]


@app.get("/", include_in_schema=False)
async def index_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/query/classifier", response_model=ClassifierStatusResponse)
async def classifier_status(
    service: QueryServiceDependency,
) -> ClassifierStatusResponse:
    current = service.classifier_status
    return ClassifierStatusResponse(
        taxonomy_version=current.taxonomy_version,
        classifier_version=current.classifier_version,
        rule_version=current.rule_version,
        llm_configured=current.llm_configured,
        llm_model=current.llm_model,
    )


@app.post("/api/query/analyze/text", response_model=QueryProcessingResult)
async def analyze_text_query(
    payload: TextQueryRequest,
    service: QueryServiceDependency,
) -> QueryProcessingResult:
    try:
        return await service.process_text(payload.text)
    except LLMRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except LLMProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error


@app.post("/api/query/analyze/file", response_model=QueryProcessingResult)
async def analyze_file_query(
    file: Annotated[UploadFile, File(description="PDF、图片、TXT、Markdown 或 DOCX")],
    service: QueryServiceDependency,
) -> QueryProcessingResult:
    safe_filename = _safe_filename(file.filename)
    try:
        with TemporaryDirectory(prefix="finrisk-query-") as temporary_directory:
            temporary_path = Path(temporary_directory) / safe_filename
            await _save_upload(file, temporary_path)
            return await service.process_file(
                temporary_path,
                source_uri=f"upload://{safe_filename}",
                metadata={"upload_content_type": file.content_type or "application/octet-stream"},
            )
    except HTTPException:
        raise
    except LLMRequiredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except LLMProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error
    except (ExtractionError, OSError, UnicodeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    finally:
        await file.close()


def _safe_filename(filename: str | None) -> str:
    normalized = (filename or "").replace("\\", "/")
    safe_name = Path(normalized).name
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传文件缺少有效文件名",
        )
    return safe_name


async def _save_upload(upload: UploadFile, destination: Path) -> int:
    total_size = 0
    with destination.open("wb") as output_file:
        while chunk := await upload.read(1024 * 1024):
            total_size += len(chunk)
            if total_size > MAX_UPLOAD_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail="文件不能超过 25 MB",
                )
            output_file.write(chunk)

    if total_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传文件不能为空",
        )
    return total_size
