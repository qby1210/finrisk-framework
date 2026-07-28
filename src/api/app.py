"""FinRisk FastAPI 应用和本地网站入口。"""

from collections.abc import Mapping
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
from domain.query_models import EnhancedQuery
from extraction import ExtractionError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "src" / "web" / "static"
MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024

app = FastAPI(
    title="FinRisk 风险识别工作台",
    description="Query 文件读取、场景分类和逐句增强接口",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class TextQueryRequest(ContractModel):
    """文字 Query 接口请求。"""

    text: str = Field(min_length=1, max_length=1_000_000, description="待处理完整文本")
    metadata: dict[str, object] = Field(default_factory=dict, description="可选来源信息")


class ClassifierStatusResponse(ContractModel):
    """前端展示的场景分类器状态。"""

    model_ready: bool
    training_example_count: int = Field(ge=0)
    examples_per_label: dict[str, int]
    classifier_version: str


@lru_cache(maxsize=1)
def get_query_service() -> QueryProcessingService:
    """创建并复用 Query 应用服务。"""

    return QueryProcessingService()


QueryServiceDependency = Annotated[QueryProcessingService, Depends(get_query_service)]


@app.get("/", include_in_schema=False)
async def index_page() -> FileResponse:
    """返回风险识别工作台首页。"""

    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    """用于本地启动检查的健康接口。"""

    return {"status": "ok"}


@app.get("/api/query/classifier", response_model=ClassifierStatusResponse)
async def classifier_status(
    service: QueryServiceDependency,
) -> ClassifierStatusResponse:
    """查看人工标注模型是否已经启用。"""

    current = service.classifier_status
    return ClassifierStatusResponse(
        model_ready=current.model_ready,
        training_example_count=current.training_example_count,
        examples_per_label=current.examples_per_label,
        classifier_version=current.classifier_version,
    )


@app.post("/api/query/classifier/reload", response_model=ClassifierStatusResponse)
async def reload_classifier(
    service: QueryServiceDependency,
) -> ClassifierStatusResponse:
    """重新读取 train_data 并训练场景分类器。"""

    current = service.reload_classifier()
    return ClassifierStatusResponse(
        model_ready=current.model_ready,
        training_example_count=current.training_example_count,
        examples_per_label=current.examples_per_label,
        classifier_version=current.classifier_version,
    )


@app.post("/api/query/analyze/text", response_model=EnhancedQuery)
async def analyze_text_query(
    payload: TextQueryRequest,
    service: QueryServiceDependency,
) -> EnhancedQuery:
    """对文字输入执行文件级场景分类和逐句增强。"""

    try:
        return service.process_text(payload.text, metadata=payload.metadata)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error


@app.post("/api/query/analyze/file", response_model=EnhancedQuery)
async def analyze_file_query(
    file: Annotated[UploadFile, File(description="PDF、图片、TXT、Markdown 或 DOCX")],
    service: QueryServiceDependency,
) -> EnhancedQuery:
    """读取上传文件后执行文件级场景分类和逐句增强。"""

    safe_filename = _safe_filename(file.filename)
    try:
        with TemporaryDirectory(prefix="finrisk-query-") as temporary_directory:
            temporary_path = Path(temporary_directory) / safe_filename
            await _save_upload(file, temporary_path)
            metadata: Mapping[str, object] = {
                "source_channel": "web_upload",
                "upload_content_type": file.content_type or "application/octet-stream",
            }
            return service.process_file(
                temporary_path,
                source_uri=f"upload://{safe_filename}",
                metadata=metadata,
            )
    except HTTPException:
        raise
    except (ExtractionError, OSError, UnicodeError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    finally:
        await file.close()


def _safe_filename(filename: str | None) -> str:
    """去除浏览器伪路径并拒绝空文件名。"""

    normalized = (filename or "").replace("\\", "/")
    safe_name = Path(normalized).name
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传文件缺少有效文件名",
        )
    return safe_name


async def _save_upload(upload: UploadFile, destination: Path) -> int:
    """分块保存上传文件，并限制单文件大小。"""

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
