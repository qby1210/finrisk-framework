"""案例知识库、案例管理与检索结果的共享字段。"""

from __future__ import annotations

from datetime import date

from pydantic import Field

from domain.common import ContractModel


class CaseSummary(ContractModel):
    """案例列表和检索结果共用的稳定摘要。"""

    case_id: str
    case_title: str | None = None
    party_name: str | None = None
    penalty_doc_no: str | None = None
    violation_behavior: str
    penalty_content: str | None = None
    regulator: str | None = None
    penalty_date: date | None = None
    risk_tags: list[str] = Field(default_factory=list)
    risk_domains: list[str] = Field(default_factory=list)
    case_origin: str
    retrieval_status: str
    evidence_status: str
    is_user_managed: bool = False


class EvidenceChunk(ContractModel):
    """案例详情中的可追溯知识库切片。"""

    chunk_id: str
    chunk_type: str
    chunk_text: str
    supports_risk_tags: list[str] = Field(default_factory=list)
    is_verbatim: bool = False
    source_span: dict[str, object] | None = None


class CaseDetail(CaseSummary):
    """案例详情；保留权威 JSONL 中对日常管理有用的字段。"""

    institution_type: str | None = None
    case_summary: str | None = None
    related_parties: list[dict[str, object]] = Field(default_factory=list)
    legal_basis_refs: list[dict[str, object]] = Field(default_factory=list)
    source_file: str | None = None
    source_url: str | None = None
    source_sha256: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    data_version: str
    evidence_chunks: list[EvidenceChunk] = Field(default_factory=list)


class CaseListPage(ContractModel):
    """案例分页结果。"""

    items: list[CaseSummary]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)


class CaseStatistics(ContractModel):
    """Web 首页和案例管理页使用的数据概览。"""

    total_cases: int = Field(ge=0)
    base_cases: int = Field(ge=0)
    user_cases: int = Field(ge=0)
    active_cases: int = Field(ge=0)
    risk_tag_count: int = Field(ge=0)
    data_version: str | None = None


class MatchedCase(ContractModel):
    """一条 Query 命中的案例证据。"""

    case_id: str
    case_title: str | None = None
    violation_behavior: str
    penalty_content: str | None = None
    regulator: str | None = None
    risk_tags: list[str] = Field(default_factory=list)
    score: float = Field(ge=0, le=1)
    matched_text: str
    matched_source: str
    matched_unit_id: str


class CaseIngestionResult(ContractModel):
    """Web 案例录入结果。"""

    case: CaseDetail
    extraction_method: str
    llm_used: bool
    warnings: list[str] = Field(default_factory=list)
