# 数据契约

跨模块数据模型只定义在 `src/domain`。JSON 字段使用英文 snake_case，日期使用 ISO 8601，
分数范围为 0–1，未知值使用 `null`。业务数据不得保存开发者本机绝对路径。

## 1. 文件提取

`FileExtractionResult` 是案例和 Query 的共享输入，关键字段：

| 字段 | 含义 |
| --- | --- |
| `document_id` | 由文件内容确定的稳定 ID |
| `file_purpose` | `case` 或 `query` |
| `source_filename / source_uri` | 原始文件名和逻辑来源 |
| `checksum_sha256 / file_size_bytes` | 文件完整性信息 |
| `full_text` | 按阅读顺序合并的全文 |
| `pages / tables` | 页、块、词和表格 |
| `extraction_method` | pdf_text、rapidocr、hybrid、plain_text、docx |
| `quality_score / warnings` | 质量与异常说明 |

`TextBlock` 和 `WordContent` 保存页内/全文字符偏移与归一化 polygon。原生 PDF 文本优先，
低质量或无文本层页面才使用 RapidOCR。原始文件不能被提取过程覆盖。

## 2. 案例知识库物理表

主库 schema 沿用队员构建包，避免重建 7,328 条数据。

### `cases.jsonl`

一行一个案例。运行时重点字段：

| 字段 | 含义 |
| --- | --- |
| `case_id` | 主键；Web 新增为 `U` + 文件哈希前缀 |
| `file_id / source_sha256` | 来源文件身份 |
| `case_origin` | 构建批次来源或 `web_ingestion` |
| `case_title / party_name / penalty_doc_no` | 案例身份字段 |
| `violation_behavior / penalty_content` | 违法事实和处罚内容 |
| `regulator / penalty_date` | 处罚机关和日期 |
| `risk_tags / risk_domains` | 案例标签和风险归口 |
| `risk_tag_basis` | 标签的原文证据 |
| `retrieval_status` | `active` 或 `inactive` |
| `evidence_status` | `verified` 或 `limited` |
| `source_file / source_url` | 可追溯来源 |
| `quality_flags / review_status` | 自动化质量与复核状态 |
| `data_version` | 数据版本 |

历史值 `official_gold` 是旧流程内部质量层，不代表官方权威。Web 新增记录若使用规则降级，
必须标记 `manual_review_required / limited / rule_fallback`。

### `case_chunks.jsonl`

| 字段 | 含义 |
| --- | --- |
| `chunk_id / case_id / file_id` | 切片主键和外键 |
| `chunk_type` | fact、evidence、penalty、legal_basis、party |
| `chunk_text` | 可展示或检索的文本 |
| `supports_risk_tags` | 本切片支持的案例标签 |
| `is_verbatim / source_span` | 是否逐字原文及位置 |
| `retrieval_enabled / retrieval_weight` | 是否入索引及权重 |

当前 BM25 只索引启用案例的 fact/evidence 切片。

### `case_expansions.jsonl`

扩展是检索召回辅助，不是案例事实证据。`case_links` 关联一个或多个案例，
`retrieval_enabled` 控制是否入索引。生成扩展不能在 UI 中伪装成原文。

### 增量一致性

新案例必须同时产生一个 cases 记录、至少一个 chunk、零到多个 expansion。仓库在同一锁内
追加三表并刷新 manifest；失败按原字节长度回滚。三表都使用 `case_id` 关联，不建立第二套
“用户案例库”。

## 3. 案例 Web/API 模型

- `CaseSummary`：列表和检索共用摘要；
- `CaseDetail`：摘要 + 来源、相关方、法律依据、质量标记和证据切片；
- `CaseListPage`：`items / total / page / page_size / total_pages`；
- `CaseStatistics`：总数、原批次数、Web 新增数、启用数、标签数和数据版本；
- `CaseIngestionResult`：新案例详情、提取方式、是否使用 LLM、警告；
- `MatchedCase`：案例 ID、违法事实、标签、0–1 展示分、命中文本和命中单元。

`is_user_managed` 只表示 `case_origin=web_ingestion`，不是不同数据库。

## 4. Query 契约

`QueryProcessingResult` 2.0：

- 文件身份和全文；
- `classification`：六类场景、置信度、方法、证据、版本；
- `sentences[]`：Risk 唯一四字段输入；
- `source_mappings[]`：与句子一一对应的原文偏移和页面区域；
- `metadata`：渠道和提取质量等附加信息。

`RiskQuerySentence` 严格只有：

```json
{
  "query_id": "query_...",
  "sentence_id": "query_..._s0001",
  "scene": "ST1_poster_sms_social",
  "text": "待判断原句"
}
```

Risk 不修改这四个字段，使用 `sentence_id` 回写结果。

## 5. 风险输出

`QueryAnalysisResult` 3.0 继承 Query 2.0 并增加：

### `risk_summary`

| 字段 | 含义 |
| --- | --- |
| `overall_score / overall_level` | 全文最高句风险与等级 code |
| `overall_level_name / action` | 中文显示和建议动作 |
| `risk_labels` | 风险句标签频次汇总 |
| `sentence_count / risky_sentence_count` | 总句数和分数不低于 0.20 的句数 |
| `llm_used / llm_model` | 本次是否真正使用 LLM |
| `warnings` | 降级或供应商异常 |

### `risk_assessments[]`

每项与一个 `sentence_id` 对应，包含 `text / risk_score / risk_level / risk_labels /
reasoning / method / evidence / matched_cases`。模型验证器强制与原句顺序完全一致。

## 6. LLM 协议

所有调用方只依赖 `LLMClient.complete_json(JsonChatRequest) -> JsonChatResponse`。
客户端负责鉴权、超时、HTTP 状态、JSON 解码和供应商响应校验；业务模块负责各自的输出
Pydantic schema。API Key 不属于任何业务模型，也不能写入日志或返回值。

## 7. 版本与变更

- 案例物理表：`case_kb_v1`，数据版本 `case_kb_v2_1_2026-08-18`；
- Query：2.0；
- Query + Risk 聚合输出：3.0；
- 风险阈值和词库变更必须新增回归测试；
- 删除/重命名字段前确认现有 JSONL 是否需要迁移，不静默重建主库。
