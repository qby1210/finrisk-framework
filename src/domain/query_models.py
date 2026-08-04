"""Query 六类场景、逐句 Risk 输入与原文定位字段。"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from domain.common import ContractModel, QueryInputType
from domain.file_models import NormalizedPoint


class QueryScene(StrEnum):
    """Query 文件级使用场景。"""

    ST1_POSTER_SMS_SOCIAL = "ST1_poster_sms_social"
    ST2_LIVE_SHORT_VIDEO = "ST2_live_short_video"
    ST3_PRODUCT_INTRO_DETAIL = "ST3_product_intro_detail"
    ST4_MEETING_MATERIAL = "ST4_meeting_material"
    ST5_TRAINING_TELEMARKETING_CALLBACK = "ST5_training_telemarketing_callback"
    ST6_PENALTY_BACKEND_FACT = "ST6_penalty_backend_fact"


class QueryClassificationMethod(StrEnum):
    """文件级场景分类的产生方式。"""

    RULE = "rule"
    LLM = "llm"


class SceneRuleCandidate(ContractModel):
    """规则阶段的一个候选场景及可解释证据。"""

    scene: QueryScene
    score: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class QuerySceneClassification(ContractModel):
    """整份 Query 的统一场景分类结果。"""

    scene: QueryScene
    confidence: float = Field(ge=0, le=1)
    method: QueryClassificationMethod
    evidence: list[str] = Field(default_factory=list)
    rule_candidates: list[SceneRuleCandidate] = Field(default_factory=list)
    classifier_version: str
    taxonomy_version: str
    llm_model: str | None = None


class RiskQuerySentence(ContractModel):
    """交给 Risk 模块的严格四字段单句输入。"""

    query_id: str
    sentence_id: str
    scene: QueryScene
    text: str = Field(min_length=1)


class QuerySourceRegion(ContractModel):
    """句子与 PDF/图片页面文本块的相交区域。"""

    page_number: int = Field(ge=1)
    block_id: str
    word_ids: list[str] = Field(default_factory=list)
    text: str
    document_start_offset: int = Field(ge=0)
    document_end_offset: int = Field(ge=1)
    polygon: list[NormalizedPoint] | None = Field(default=None, min_length=4, max_length=4)

    @model_validator(mode="after")
    def validate_offsets(self) -> "QuerySourceRegion":
        if self.document_end_offset <= self.document_start_offset:
            raise ValueError("document_end_offset 必须大于 document_start_offset")
        return self


class SentenceSourceMapping(ContractModel):
    """通过 sentence_id 将 Risk 结果映射回输入原文。"""

    query_id: str
    sentence_id: str
    input_type: QueryInputType
    source_document_id: str | None = None
    source_filename: str | None = None
    document_start_offset: int = Field(ge=0)
    document_end_offset: int = Field(ge=1)
    regions: list[QuerySourceRegion] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_offsets(self) -> "SentenceSourceMapping":
        if self.document_end_offset <= self.document_start_offset:
            raise ValueError("document_end_offset 必须大于 document_start_offset")
        return self


class QueryProcessingResult(ContractModel):
    """Query 分类、切句及原文映射的完整输出。"""

    schema_version: str = "2.0"
    query_id: str
    input_type: QueryInputType
    source_text: str = Field(description="文件抽取后的全文或文字输入，用于偏移映射")
    source_document_id: str | None = None
    source_filename: str | None = None
    classification: QuerySceneClassification
    sentences: list[RiskQuerySentence] = Field(min_length=1)
    source_mappings: list[SentenceSourceMapping] = Field(min_length=1)
    created_at: datetime
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_sentence_mappings(self) -> "QueryProcessingResult":
        sentence_ids = [sentence.sentence_id for sentence in self.sentences]
        mapping_ids = [mapping.sentence_id for mapping in self.source_mappings]
        if sentence_ids != mapping_ids:
            raise ValueError("sentences 与 source_mappings 必须按 sentence_id 一一对应")
        if any(sentence.query_id != self.query_id for sentence in self.sentences):
            raise ValueError("句子的 query_id 必须与结果 query_id 一致")
        return self
