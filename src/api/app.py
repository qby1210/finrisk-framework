"""FinRisk FastAPI 应用和本地 Web 工作台入口。"""

from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from application.analysis_service import QueryAnalysisService
from application.case_service import CaseManagementService
from application.query_service import QueryProcessingService
from application.retrieval_service import CaseRetrievalService
from domain.common import ContractModel
from domain.knowledge_models import (
    CaseDetail,
    CaseIngestionResult,
    CaseListPage,
    CaseStatistics,
    MatchedCase,
)
from domain.risk_models import QueryAnalysisResult
from extraction import ExtractionError
from llm import (
    LLMProviderError,
    OpenAICompatibleLLMClient,
    create_llm_client_from_env,
)
from query.classification import LLMRequiredError
from risk.detection import RuleRiskDetector
from risk.pipeline import RiskAssessmentPipeline
from settings import AppSettings
from storage.case_repository import CaseNotFoundError, CaseRepository, DuplicateCaseError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = PROJECT_ROOT / "src" / "web" / "static"

app = FastAPI(
    title="FinRisk 保险合规风险工作台",
    description="案例增量入库、案例管理、Query 风险判断与相似案例匹配",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class TextQueryRequest(ContractModel):
    text: str = Field(min_length=1, max_length=1_000_000, description="待分析完整文本")


class ClassifierStatusResponse(ContractModel):
    taxonomy_version: str
    classifier_version: str
    rule_version: str
    llm_configured: bool
    llm_model: str | None


class CaseStatusRequest(ContractModel):
    active: bool


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings.from_env()


@lru_cache(maxsize=1)
def get_repository() -> CaseRepository:
    return CaseRepository(get_settings())


@lru_cache(maxsize=1)
def get_llm_client() -> OpenAICompatibleLLMClient | None:
    return create_llm_client_from_env()


@lru_cache(maxsize=1)
def get_rule_detector() -> RuleRiskDetector:
    return RuleRiskDetector(get_settings().risk_keyword_path)


@lru_cache(maxsize=1)
def get_retrieval_service() -> CaseRetrievalService:
    return CaseRetrievalService(get_repository())


@lru_cache(maxsize=1)
def get_query_service() -> QueryProcessingService:
    return QueryProcessingService(llm_client=get_llm_client())


@lru_cache(maxsize=1)
def get_analysis_service() -> QueryAnalysisService:
    repository = get_repository()
    pipeline = RiskAssessmentPipeline(
        rule_detector=get_rule_detector(),
        retrieval_service=get_retrieval_service(),
        taxonomy=repository.risk_dictionary(),
        llm_client=get_llm_client(),
    )
    return QueryAnalysisService(query_service=get_query_service(), risk_pipeline=pipeline)


@lru_cache(maxsize=1)
def get_case_service() -> CaseManagementService:
    return CaseManagementService(
        settings=get_settings(),
        repository=get_repository(),
        rule_detector=get_rule_detector(),
        llm_client=get_llm_client(),
    )


AnalysisDependency = Annotated[QueryAnalysisService, Depends(get_analysis_service)]
CaseDependency = Annotated[CaseManagementService, Depends(get_case_service)]
RetrievalDependency = Annotated[CaseRetrievalService, Depends(get_retrieval_service)]


@app.get("/", include_in_schema=False)
async def index_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/api/health")
async def health(case_service: CaseDependency) -> dict[str, object]:
    statistics = case_service.statistics()
    llm_client = get_llm_client()
    return {
        "status": "ok",
        "case_count": statistics.total_cases,
        "active_case_count": statistics.active_cases,
        "data_version": statistics.data_version,
        "llm_model": llm_client.model_name if llm_client else None,
    }


@app.get("/api/query/classifier", response_model=ClassifierStatusResponse)
async def classifier_status(service: AnalysisDependency) -> ClassifierStatusResponse:
    current = service.classifier_status
    return ClassifierStatusResponse(
        taxonomy_version=current.taxonomy_version,
        classifier_version=current.classifier_version,
        rule_version=current.rule_version,
        llm_configured=current.llm_configured,
        llm_model=current.llm_model,
    )


@app.post("/api/query/analyze/text", response_model=QueryAnalysisResult)
async def analyze_text_query(
    payload: TextQueryRequest,
    service: AnalysisDependency,
) -> QueryAnalysisResult:
    try:
        return await service.process_text(payload.text, metadata={"channel": "web"})
    except Exception as error:
        _raise_query_error(error)
        raise


@app.post("/api/query/analyze/file", response_model=QueryAnalysisResult)
async def analyze_file_query(
    file: Annotated[UploadFile, File(description="PDF、图片、TXT、Markdown 或 DOCX")],
    service: AnalysisDependency,
) -> QueryAnalysisResult:
    safe_filename = _safe_filename(file.filename)
    try:
        with TemporaryDirectory(prefix="finrisk-query-") as temporary_directory:
            temporary_path = Path(temporary_directory) / safe_filename
            await _save_upload(file, temporary_path, get_settings().max_upload_size_bytes)
            return await service.process_file(
                temporary_path,
                source_uri=f"upload://{safe_filename}",
                metadata={"upload_content_type": file.content_type or "application/octet-stream"},
            )
    except HTTPException:
        raise
    except Exception as error:
        _raise_query_error(error)
        raise
    finally:
        await file.close()


@app.get("/api/cases/statistics", response_model=CaseStatistics)
async def case_statistics(service: CaseDependency) -> CaseStatistics:
    return service.statistics()


@app.get("/api/cases", response_model=CaseListPage)
async def list_cases(
    service: CaseDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    q: Annotated[str | None, Query(max_length=200)] = None,
    risk_tag: Annotated[str | None, Query(max_length=100)] = None,
    retrieval_status: Annotated[str | None, Query(pattern="^(active|inactive)$")] = None,
    origin: Annotated[str | None, Query(max_length=100)] = None,
) -> CaseListPage:
    return service.list_cases(
        page=page,
        page_size=page_size,
        query=q,
        risk_tag=risk_tag,
        status=retrieval_status,
        origin=origin,
    )


@app.get("/api/cases/{case_id}", response_model=CaseDetail)
async def get_case(case_id: str, service: CaseDependency) -> CaseDetail:
    try:
        return service.get_case(case_id)
    except CaseNotFoundError as error:
        raise HTTPException(status_code=404, detail="案例不存在") from error


@app.post("/api/cases/upload", response_model=CaseIngestionResult, status_code=201)
async def upload_case(
    file: Annotated[UploadFile, File(description="待增量入库的案例 PDF 或文档")],
    service: CaseDependency,
) -> CaseIngestionResult:
    safe_filename = _safe_filename(file.filename)
    try:
        with TemporaryDirectory(prefix="finrisk-case-") as temporary_directory:
            temporary_path = Path(temporary_directory) / safe_filename
            await _save_upload(file, temporary_path, get_settings().max_upload_size_bytes)
            return await service.ingest_file(temporary_path, original_filename=safe_filename)
    except HTTPException:
        raise
    except DuplicateCaseError as error:
        raise HTTPException(status_code=409, detail="该文件对应的案例已经入库") from error
    except LLMProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (ExtractionError, OSError, UnicodeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    finally:
        await file.close()


@app.patch("/api/cases/{case_id}/status", response_model=CaseDetail)
async def set_case_status(
    case_id: str,
    payload: CaseStatusRequest,
    service: CaseDependency,
) -> CaseDetail:
    try:
        return service.set_active(case_id, active=payload.active)
    except CaseNotFoundError as error:
        raise HTTPException(status_code=404, detail="案例不存在") from error


@app.delete("/api/cases/{case_id}", response_model=CaseDetail)
async def deactivate_case(case_id: str, service: CaseDependency) -> CaseDetail:
    """兼容管理 UI 的删除动作，实际执行可恢复停用。"""

    try:
        return service.set_active(case_id, active=False)
    except CaseNotFoundError as error:
        raise HTTPException(status_code=404, detail="案例不存在") from error


@app.get("/api/knowledge/search", response_model=list[MatchedCase])
async def search_cases(
    service: RetrievalDependency,
    q: Annotated[str, Query(min_length=1, max_length=5000)],
    top_k: Annotated[int, Query(ge=1, le=20)] = 5,
    risk_tag: Annotated[str | None, Query(max_length=100)] = None,
) -> list[MatchedCase]:
    return service.search(q, top_k=top_k, risk_tags={risk_tag} if risk_tag else None)


def _raise_query_error(error: Exception) -> None:
    if isinstance(error, LLMRequiredError):
        raise HTTPException(status_code=503, detail=str(error)) from error
    if isinstance(error, LLMProviderError):
        raise HTTPException(status_code=502, detail=str(error)) from error
    if isinstance(error, (ExtractionError, OSError, UnicodeError, ValueError)):
        raise HTTPException(status_code=422, detail=str(error)) from error


def _safe_filename(filename: str | None) -> str:
    normalized = (filename or "").replace("\\", "/")
    safe_name = Path(normalized).name
    if not safe_name or safe_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="上传文件缺少有效文件名")
    return safe_name


async def _save_upload(upload: UploadFile, destination: Path, maximum_size: int) -> int:
    total_size = 0
    with destination.open("wb") as output_file:
        while chunk := await upload.read(1024 * 1024):
            total_size += len(chunk)
            if total_size > maximum_size:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"文件不能超过 {maximum_size // 1024 // 1024} MB",
                )
            output_file.write(chunk)
    if total_size == 0:
        raise HTTPException(status_code=400, detail="上传文件不能为空")
    return total_size
