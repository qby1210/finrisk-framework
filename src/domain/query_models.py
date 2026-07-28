"""Query 场景分类、句子切分和增强完成后的统一字段。

场景分类只为 Query 增加使用场景，不产生风险标签，也不决定 Risk 的检测路由。
Risk 模块直接消费 EnhancedQuery.sentences，并逐句输出风险概率和相似案例。
"""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from domain.common import ContractModel, QueryInputType


class QuerySceneLabel(StrEnum):
    """Query 的使用场景分类，不表示风险类型。"""

    MARKETING_CONTENT = "marketing_content"
    FORMAL_DOCUMENT = "formal_document"
    CUSTOMER_COMMUNICATION = "customer_communication"
    UNKNOWN_OR_MIXED = "unknown_or_mixed"


class QueryClassificationMethod(StrEnum):
    """Query 场景分类结果的产生方式。"""

    RULE = "rule"
    MODEL = "model"
    HYBRID = "hybrid"
    ABSTAINED = "abstained"


class QueryCategoryPrediction(ContractModel):
    """Query 场景分类器输出的一个候选类别。"""

    category_code: QuerySceneLabel = Field(description="Query 场景类别稳定英文代码")
    category_name: str = Field(description="Query 场景类别中文名称")
    probability: float = Field(ge=0, le=1, description="分类概率")


class QueryClassification(ContractModel):
    """文件或整段文本的场景分类结果。"""

    selected_category: QueryCategoryPrediction = Field(description="最终采用的场景类别")
    candidates: list[QueryCategoryPrediction] = Field(
        default_factory=list,
        description="三个主要场景的候选概率，按概率从高到低排列",
    )
    augmentation_terms: list[str] = Field(
        default_factory=list,
        description="根据场景生成并加入 Query 的非风险增强词条",
    )
    classification_method: QueryClassificationMethod = Field(
        description="规则、模型、混合或低置信放弃分类",
    )
    classification_evidence: list[str] = Field(
        default_factory=list,
        description="支持文件级场景分类的规则或结构证据",
    )
    is_abstained: bool = Field(description="是否因低置信或类别冲突而放弃三分类")
    classifier_version: str = Field(description="场景分类器版本")
    taxonomy_version: str = Field(description="Query 场景分类体系版本")


class EnhancedQuerySentence(ContractModel):
    """Risk 模块可以直接消费的逐句增强结果。"""

    sentence_id: str = Field(description="Query 内稳定句子标识")
    sentence_index: int = Field(ge=1, description="句子顺序，从 1 开始")
    text: str = Field(min_length=1, description="从完整 Query 中切分出的原句")
    start_offset: int = Field(ge=0, description="原句在 original_text 中的起始位置")
    end_offset: int = Field(ge=1, description="原句在 original_text 中的结束位置")
    category: QueryCategoryPrediction = Field(description="继承的文件级场景分类")
    augmentation_terms: list[str] = Field(
        default_factory=list,
        description="继承的文件级场景增强词条",
    )
    enhanced_text: str = Field(description="带显式场景标签、可直接交给 Risk 的单句文本")

    @model_validator(mode="after")
    def validate_offsets(self) -> "EnhancedQuerySentence":
        """句子结束位置必须晚于起始位置。"""

        if self.end_offset <= self.start_offset:
            raise ValueError("end_offset 必须大于 start_offset")
        return self


class EnhancedQuery(ContractModel):
    """文件级分类后按句增强、可以直接交给 Risk 的 Query。"""

    schema_version: str = Field(default="1.1", description="当前字段结构版本")
    query_id: str = Field(description="一次 Query 的稳定标识")
    input_type: QueryInputType = Field(description="原始输入是文本还是文件")
    original_text: str = Field(description="文件抽取后的完整文本或文字输入，不得覆盖")
    source_document_id: str | None = Field(
        default=None,
        description="文件 Query 对应的 FileExtractionResult 标识",
    )
    source_filename: str | None = Field(default=None, description="文件 Query 的原始文件名")
    classification: QueryClassification = Field(description="文件级场景分类结果")
    sentences: list[EnhancedQuerySentence] = Field(
        min_length=1,
        description="切分后的逐句增强内容，Risk 按此列表逐句判断",
    )
    enhanced_text: str = Field(description="全部逐句增强文本的合并结果")
    created_at: datetime = Field(description="Query 增强完成时间，必须包含时区")
    metadata: dict[str, object] = Field(default_factory=dict, description="可选请求来源信息")
