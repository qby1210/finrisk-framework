# 数据字段约定

代码定义位于 src/domain。本文件用于团队确认字段语义，代码和文档必须同步修改。

## 通用约定

- 字段名统一使用英文 snake_case。
- 标识符统一使用字符串，不使用数据库自增编号作为跨模块标识。
- 日期时间使用包含时区的 ISO 8601。
- 金额使用 Decimal，禁止使用 float。
- 概率范围为 0 到 1。
- 文件位置使用项目相对路径或逻辑 URI，不保存开发者本机绝对路径。
- 不确定字段使用 None，不使用空字符串代替未知。
- 原始文本、标准化文本和增强文本必须分别保存，禁止覆盖原文。
- 风险类别和标签使用稳定英文 code，中文名称只用于展示。
- 模型输出必须保存模型版本，风险标签必须保存标签体系版本。
- 所有模型使用 schema_version 标记字段结构版本。

## 1. 文件读取输出

代码模型：FileExtractionResult

案例文件和 Query 文件共用这一结构，通过 file_purpose 区分用途。

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| schema_version | str | 是 | 文件读取结果的字段结构版本 |
| document_id | str | 是 | 文件稳定标识，建议根据哈希生成 |
| file_purpose | enum | 是 | case 或 query |
| source_filename | str | 是 | 原始文件名 |
| source_uri | str | 是 | 原始文件相对路径或逻辑 URI |
| media_type | str | 是 | 文件 MIME 类型 |
| checksum_sha256 | str | 是 | 文件 SHA-256 |
| file_size_bytes | int | 是 | 文件字节数 |
| full_text | str | 是 | 按页码和阅读顺序合并的完整文本 |
| page_count | int | 是 | 文件总页数 |
| ocr_page_count | int | 是 | 实际使用 OCR 的页数 |
| pages | list | 否 | 每页文本、位置、置信度和读取状态 |
| tables | list | 否 | 提取表格的页码、标题和行数据 |
| extraction_method | enum | 是 | pdf_text、rapidocr、hybrid、plain_text 或 docx |
| extraction_status | enum | 是 | succeeded、partial 或 failed |
| quality_score | float | 否 | 读取质量分数 |
| warnings | list[str] | 否 | 缺页、乱码、OCR 失败等警告 |
| extracted_at | datetime | 是 | 完成读取的时间 |
| extractor_version | str | 是 | 文件读取模块版本 |
| metadata | dict | 否 | 来源渠道等非核心附加信息 |

约定：

- 即使读取失败，也应保留文件身份、状态和 warnings。
- 案例读取结果存放在 data/interim/extracted_cases。
- Query 文件读取结果存放在 data/interim/extracted_query。
- 原始文件不得因读取过程被修改。


### PageContent 和原文定位字段

每个 PageContent 保存：

- page_number：从 1 开始的页码；
- width、height：原始页面尺寸；
- text：该页按阅读顺序合并的文本；
- blocks：行或段落级 TextBlock；
- words：字词级 WordContent；
- used_ocr：该页是否调用 RapidOCR；
- average_confidence：OCR 平均置信度；
- quality_score：页面综合读取质量；
- extraction_method：该页实际读取方式；
- warnings：页面级警告。

TextBlock 和 WordContent 都保存：

- 页面内稳定标识、页码、文本和阅读顺序；
- OCR confidence，原生文本层对应值为空；
- polygon：四个 NormalizedPoint 组成的四边形；
- page_start_offset、page_end_offset：页文本中的字符范围；
- document_start_offset、document_end_offset：full_text 中的字符范围；
- extraction_method：该元素来自原生文本层还是 RapidOCR。

polygon 坐标已经除以页面宽高，x 和 y 均在 0 到 1 之间。网页展示时分别乘以当前渲染宽高，不得当作原始像素使用。字词无法与合并文本可靠对齐时，偏移允许为空，但坐标仍保留。

PDF 使用原生文本层优先策略。只有字符数或质量分数低于配置阈值时，才把该页渲染为图片并调用 RapidOCR。混合 PDF 可以同时包含 pdf_text 和 rapidocr 页面，文件级 extraction_method 记录为 hybrid。
## 2. 标准化案例

代码模型：NormalizedCase

NormalizedCase 只保存从案例文件中提取的事实，不包含任何风险标签。

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| schema_version | str | 是 | 标准化案例字段版本 |
| case_id | str | 是 | 案例稳定标识 |
| document_id | str | 是 | 来源文件标识 |
| case_title | str | 否 | 案例或处罚决定标题 |
| case_number | str | 否 | 处罚决定书文号或案例编号 |
| institutions | list | 否 | 涉及机构的名称、类型和角色 |
| involved_people | list[str] | 否 | 涉及个人 |
| regulator | str | 否 | 监管或处罚机构 |
| decision_date | date | 否 | 处罚或决定日期 |
| violation_facts | str | 是 | 整理后的违法违规事实 |
| penalty_result | str | 否 | 警告、没收、罚款等处理结果 |
| penalty_amount | Decimal | 否 | 罚款总金额 |
| currency | str | 是 | 金额币种，默认 CNY |
| legal_basis | list[str] | 否 | 法律法规和条款 |
| source_text | str | 是 | 形成案例字段所依据的原文 |
| evidence_spans | list | 否 | 基础字段对应的原文证据位置 |
| normalizer_version | str | 是 | 案例标准化模块版本 |
| normalized_at | datetime | 是 | 标准化完成时间 |

约定：

- violation_facts 是案例标准化的最低必需事实字段。
- 无法从文件确定的信息保持为空，不能由模型臆造。
- 标准化案例存放在 data/interim/normalized_cases。
- 风险分类在标准化之后进行，禁止提前写入风险标签。

## 3. 最终案例记录

代码模型：FinalCaseRecord

最终案例由标准化事实、双模型风险标签结果、检索增强内容和知识库引用组成。

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| schema_version | str | 是 | 最终案例字段版本 |
| case | NormalizedCase | 是 | 标准化案例事实 |
| risk_labeling | CaseRiskLabelingResult | 是 | 独立分类模型和大模型复核结果 |
| enrichment | CaseEnrichment | 是 | 摘要、关键词和检索文本 |
| knowledge_entry_ids | list[str] | 否 | 对应向量知识库条目标识 |
| pipeline_version | str | 是 | 离线流程版本 |
| created_at | datetime | 是 | 首次生成时间 |
| updated_at | datetime | 是 | 最后更新时间 |

CaseRiskLabelingResult 包含：

| 字段 | 含义 |
| --- | --- |
| classifier_predictions | 独立训练分类模型的原始预测 |
| reviewer_predictions | 大模型独立复核结果 |
| final_labels | 融合后最终风险标签 |
| resolution_status | agreed、resolved 或 human_review |
| needs_human_review | 是否需要人工确认 |
| resolution_notes | 分歧和处理说明 |
| classifier_model_version | 分类模型版本 |
| reviewer_model_version | 大模型版本 |
| reviewer_prompt_version | 复核提示词版本 |
| resolver_version | 融合规则版本 |
| taxonomy_version | 风险标签体系版本 |
| labeled_at | 标签确定时间 |

每个 CaseRiskLabelPrediction 包含 label_code、label_name、category_code、probability、
evidence、rationale、source、model_version 和 taxonomy_version。

CaseEnrichment 包含 summary、keywords、retrieval_text、hypothetical_expressions 和
enrichment_version。

约定：

- 案例风险标签只能来自独立案例分类模型、大模型复核器和融合器。
- 禁止调用 Query 风险判断结果生成或覆盖案例标签。
- 最终案例记录存放在 data/processed/cases。
- 向量和索引存放在 data/processed/knowledge，不直接塞入案例 JSON。
- knowledge_entry_ids 只保存关联标识。

## 4. Query 分类增强结果（2.0）

代码模型：QueryProcessingResult（本节旧字段已由 docs/query_pipeline.md 的 2.0 契约替代）

当前唯一有效契约是 docs/query_pipeline.md 中的逐句四字段输入和独立原文映射。下表为旧版历史字段，仅供迁移，禁止新模块继续使用。

| 字段 | 类型 | 必填 | 含义 |
| --- | --- | --- | --- |
| schema_version | str | 是 | Query 字段结构版本 |
| query_id | str | 是 | 一次 Query 的稳定标识 |
| input_type | enum | 是 | text 或 file |
| original_text | str | 是 | 原始句子或文件读取文本 |
| source_document_id | str | 否 | 文件 Query 的文件标识 |
| source_filename | str | 否 | 文件 Query 的原始文件名 |
| classification | QueryClassification | 是 | Query 分类结果和增强词条 |
| enhanced_text | str | 是 | 原文与增强词条组合后的文本 |
| created_at | datetime | 是 | 增强完成时间 |
| metadata | dict | 否 | 可选请求来源信息 |

QueryClassification 包含：

| 字段 | 含义 |
| --- | --- |
| selected_category | 最终采用类别的 code、name 和 probability |
| candidates | 其他候选类别 |
| augmentation_terms | 根据类别产生的增强词条 |
| classifier_version | Query 分类模型版本 |

约定：

- original_text 永远保留且不可被增强文本覆盖。
- enhanced_text 只在原文基础上增加分类词条。
- Query 分类不查询案例知识库。
- Query 分类不决定采用哪一层风险模型。
- 风险判断模块同时可以读取 original_text 和 enhanced_text。