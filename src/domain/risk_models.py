"""Query 风险判断与匹配案例的共享输出契约。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from domain.common import ContractModel
from domain.knowledge_models import MatchedCase
from domain.query_models import QueryProcessingResult


class RiskLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    REVIEW = "review"
    LOW = "low"
    NONE = "none"


class RiskEvidence(ContractModel):
    """规则、检索或大模型提供的一条判断依据。"""

    source: str
    description: str


class SentenceRiskAssessment(ContractModel):
    """与 RiskQuerySentence 通过 sentence_id 一一对应的判断结果。"""

    query_id: str
    sentence_id: str
    text: str
    risk_score: float = Field(ge=0, le=1)
    risk_level: RiskLevel
    risk_level_name: str
    action: str
    risk_labels: list[str] = Field(default_factory=list, max_length=3)
    reasoning: str
    method: str
    evidence: list[RiskEvidence] = Field(default_factory=list)
    matched_cases: list[MatchedCase] = Field(default_factory=list)


class QueryRiskSummary(ContractModel):
    """整份 Query 的风险概览。"""

    overall_score: float = Field(ge=0, le=1)
    overall_level: RiskLevel
    overall_level_name: str
    action: str
    risk_labels: list[str] = Field(default_factory=list)
    sentence_count: int = Field(ge=1)
    risky_sentence_count: int = Field(ge=0)
    llm_used: bool
    llm_model: str | None = None
    warnings: list[str] = Field(default_factory=list)


class QueryAnalysisResult(QueryProcessingResult):
    """分类、切句、风险判断、案例匹配的一体化 Web/API 输出。"""

    schema_version: str = "3.0"
    risk_summary: QueryRiskSummary
    risk_assessments: list[SentenceRiskAssessment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_risk_assessments(self) -> QueryAnalysisResult:
        sentence_ids = [sentence.sentence_id for sentence in self.sentences]
        assessment_ids = [item.sentence_id for item in self.risk_assessments]
        if sentence_ids != assessment_ids:
            raise ValueError("risk_assessments 必须与 sentences 按 sentence_id 一一对应")
        return self
