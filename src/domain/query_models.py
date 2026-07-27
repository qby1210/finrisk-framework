"""Query 分类及增强完成后的统一字段。

Query 分类只给原文增加类别词条，不负责知识库查询，也不负责风险路由。
"""

from datetime import datetime

from pydantic import Field

from domain.common import ContractModel, QueryInputType


class QueryCategoryPrediction(ContractModel):
    """Query 分类模型输出的一个候选类别。"""

    category_code: str = Field(description="Query 类别稳定英文代码")
    category_name: str = Field(description="Query 类别中文名称")
    probability: float = Field(ge=0, le=1, description="分类概率")


class QueryClassification(ContractModel):
    """Query 分类模型的完整输出。"""

    selected_category: QueryCategoryPrediction = Field(description="最终采用的类别")
    candidates: list[QueryCategoryPrediction] = Field(
        default_factory=list,
        description="可选的其他候选类别",
    )
    augmentation_terms: list[str] = Field(
        default_factory=list,
        description="根据类别生成并加入 Query 的增强词条",
    )
    classifier_version: str = Field(description="Query 分类模型版本")


class EnhancedQuery(ContractModel):
    """完成文件读取、分类和词条增强后交给风险模块的 Query。"""

    schema_version: str = Field(default="1.0", description="当前字段结构版本")
    query_id: str = Field(description="一次 Query 的稳定标识")
    input_type: QueryInputType = Field(description="原始输入是文本还是文件")
    original_text: str = Field(description="原始查询句子或文件提取文本，不得覆盖")
    source_document_id: str | None = Field(
        default=None,
        description="文件 Query 对应的 FileExtractionResult 标识",
    )
    source_filename: str | None = Field(default=None, description="文件 Query 的原始文件名")
    classification: QueryClassification = Field(description="Query 分类及增强词条")
    enhanced_text: str = Field(description="原文与增强词条组合后的风险判断输入")
    created_at: datetime = Field(description="Query 增强完成时间，必须包含时区")
    metadata: dict[str, object] = Field(default_factory=dict, description="可选请求来源信息")