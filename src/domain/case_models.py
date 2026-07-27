"""标准化案例和最终案例记录的统一字段。"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from domain.common import (
    ContractModel,
    EvidenceSpan,
    LabelResolutionStatus,
    LabelSource,
)


class InvolvedInstitution(ContractModel):
    """案例涉及的机构。"""

    name: str = Field(description="机构名称")
    institution_type: str | None = Field(default=None, description="银行、保险、证券等类型")
    role: str | None = Field(default=None, description="被处罚方、相关方等角色")


class NormalizedCase(ContractModel):
    """文件基础提取完成后形成的标准化案例事实，不包含风险标签。"""

    schema_version: str = Field(default="1.0", description="当前字段结构版本")
    case_id: str = Field(description="案例稳定标识")
    document_id: str = Field(description="来源 FileExtractionResult 的文件标识")
    case_title: str | None = Field(default=None, description="案例或处罚决定标题")
    case_number: str | None = Field(default=None, description="处罚决定书文号或案例编号")
    institutions: list[InvolvedInstitution] = Field(
        default_factory=list,
        description="案例涉及的机构",
    )
    involved_people: list[str] = Field(default_factory=list, description="案例涉及的个人")
    regulator: str | None = Field(default=None, description="作出处罚或认定的监管机构")
    decision_date: date | None = Field(default=None, description="处罚或决定日期")
    violation_facts: str = Field(description="从原文提取并整理的违法违规事实")
    penalty_result: str | None = Field(default=None, description="警告、罚款等处理结果")
    penalty_amount: Decimal | None = Field(default=None, ge=0, description="罚款总金额")
    currency: str = Field(default="CNY", description="罚款金额币种")
    legal_basis: list[str] = Field(default_factory=list, description="涉及的法律法规或条款")
    source_text: str = Field(description="用于形成案例字段的可追溯原文")
    evidence_spans: list[EvidenceSpan] = Field(
        default_factory=list,
        description="各基础字段对应的原文证据",
    )
    normalizer_version: str = Field(description="案例标准化模块版本")
    normalized_at: datetime = Field(description="标准化完成时间，必须包含时区")


class CaseRiskLabelPrediction(ContractModel):
    """分类模型、大模型复核器或融合器输出的单个案例风险标签。"""

    label_code: str = Field(description="风险标签稳定英文代码")
    label_name: str = Field(description="风险标签中文名称")
    category_code: str = Field(description="上级风险类别代码")
    probability: float = Field(ge=0, le=1, description="当前来源给出的标签概率")
    evidence: list[EvidenceSpan] = Field(default_factory=list, description="标签判断证据")
    rationale: str | None = Field(default=None, description="可读的判断理由")
    source: LabelSource = Field(description="分类模型、大模型复核器或融合器")
    model_version: str = Field(description="产生该结果的模型或规则版本")
    taxonomy_version: str = Field(description="风险标签体系版本")


class CaseRiskLabelingResult(ContractModel):
    """独立分类模型和大模型双重确定后的案例标签结果。"""

    classifier_predictions: list[CaseRiskLabelPrediction] = Field(
        default_factory=list,
        description="独立训练分类模型的原始预测",
    )
    reviewer_predictions: list[CaseRiskLabelPrediction] = Field(
        default_factory=list,
        description="大模型独立复核结果",
    )
    final_labels: list[CaseRiskLabelPrediction] = Field(
        default_factory=list,
        description="融合后写入最终案例的标签",
    )
    resolution_status: LabelResolutionStatus = Field(description="双重结果融合状态")
    needs_human_review: bool = Field(description="当前结果是否需要人工确认")
    resolution_notes: str | None = Field(default=None, description="分歧和融合处理说明")
    classifier_model_version: str = Field(description="独立分类模型版本")
    reviewer_model_version: str = Field(description="大模型版本")
    reviewer_prompt_version: str = Field(description="大模型复核提示词版本")
    resolver_version: str = Field(description="结果融合规则版本")
    taxonomy_version: str = Field(description="风险标签体系版本")
    labeled_at: datetime = Field(description="标签确定时间，必须包含时区")


class CaseEnrichment(ContractModel):
    """案例完成标签确定后的检索增强字段。"""

    summary: str = Field(description="案例摘要")
    keywords: list[str] = Field(default_factory=list, description="案例检索关键词")
    retrieval_text: str = Field(description="用于分块和 Embedding 的完整增强文本")
    hypothetical_expressions: list[str] = Field(
        default_factory=list,
        description="由案例事实扩展出的可能风险表达",
    )
    enrichment_version: str = Field(description="案例增强模块版本")


class FinalCaseRecord(ContractModel):
    """最终落盘并可加入知识库的完整案例记录。"""

    schema_version: str = Field(default="1.0", description="最终案例字段结构版本")
    case: NormalizedCase = Field(description="标准化案例事实")
    risk_labeling: CaseRiskLabelingResult = Field(description="双模型案例风险标签结果")
    enrichment: CaseEnrichment = Field(description="案例检索增强内容")
    knowledge_entry_ids: list[str] = Field(
        default_factory=list,
        description="该案例在向量知识库中的条目标识",
    )
    pipeline_version: str = Field(description="生成该记录的离线流程版本")
    created_at: datetime = Field(description="最终案例首次生成时间，必须包含时区")
    updated_at: datetime = Field(description="最终案例最后更新时间，必须包含时区")