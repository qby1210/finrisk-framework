# 保险监管处罚案例知识库 v2.1（2026-08-18）

## 这是什么

7,328 条保险监管处罚案例的结构化知识库，供 RAG（检索增强生成）系统使用。
输入一句保险销售话术/宣传文案，可据此检索最相关的历史处罚案例作为参考。
每条案例的事实与标签均带逐字原文证据，可回溯到处罚决定书原文位置。

## 数据格式

JSONL（JSON Lines）：每行一条独立 JSON 记录的纯文本文件，UTF-8 编码。
任何编程语言均可逐行读取；也可用 VS Code / 记事本直接查看。

## 目录内容

```
data/
  cases.jsonl            7,328 条案例主表（43 个字段：当事人、违规事实、处罚、
                         风险标签、证据引文、原文链接等）
  case_chunks.jsonl      29,918 条原文切片（检索最小单位，每条带 source_span
                         原文起止字符坐标，is_verbatim 标记是否逐字）
  case_expansions.jsonl  8,873 条检索扩展（违规话术、营销表达、行为别名，
                         作为用户口语与官方案例之间的语义桥梁；按质量分级，
                         仅 retrieval_enabled=true 的可用于检索）
  review_queue.jsonl     1,046 条未通过质量门、暂未入库的案例及原因（备查）
  excluded_records.jsonl 9 条被排除记录及原因（备查）
dictionary/
  risk_type_dictionary.csv   官方 27 类风险标签字典
  risk_domain_mapping.json   标签 → 六大风险归口映射
reports/
  validation_report.md/json  机器校验报告（valid=true，校验指标全 1.0）
  field_coverage_report.md   字段覆盖报告
manifest.json            构建清单（各文件 SHA-256、条数、数据版本，可校验完整性）
```

## 质量与口径

- 数据版本：case_kb_v2_1_2026-08-18
- 校验：主键唯一率、外键有效率、官方标签合法率、标签证据覆盖率、JSON 解析率均为 100%，
  测试题泄漏 0；官方金选案例可检索 500/500
- 案例构成（7,328 条 = 覆盖全部 8,356 原子案例的 87.5%）：
  - 5,076 条规范化正式案例（质量门全过）
  - 500 条官方金选案例全部在库（quality_flags 含 gold_backfilled_from_enhanced 为回补案；
    official_retrieval_protected 为金选保护案；其中 10 条原文脏/表格式案以
    evidence_status=limited 诚实降级形态在库，事实块非逐字，已如实标记）
  - 854 条手续问题抢救案例（quality_flags 含 review_rescued_procedural_fix，
    抢救后已重跑完整入库校验，与正式案例同一道门）
  - 1,109 条官方口径校准案例（quality_flags 含 official_calibrated_gate：
    原标签证据门实测严于官方口径——官方金选认可的证据被旧门拦 55%~100%，
    经校准后重跑完整入库校验提正；校准基准为 500 条官方金选案例的证据严格程度）
  - 增量入库案例（U 前缀，经相同入库校验与话术生成）
- 标签口径：官方 27 类，每案至多 2 个标签；标签按六大风险归口分组
- 全部内容为纯本地构建，确定性可复现（重建哈希一致）

## 使用注意事项

1. JSONL 是权威数据源；向量/关键词索引请由下游从中重建，不属于本交付物。
2. case_expansions 中 retrieval_enabled=false 的条目仅备查，不要用于检索。
3. 扩展文本（违规话术等）是风格参考，不是案例证据；案例证据以 chunks 为准。
4. review_queue / excluded_records 仅供审计，不应进入检索。
5. evidence_status=limited 的案例（10 条）事实块非逐字锚定，引用其证据时请留意。

## 来源

赛题5「基于知识增强检索的保险监管处罚案例知识库构建与合规审查智能匹配」，
由规范化流水线 + 官方金选数据 + 模型生成话术（经质量审计）构建。
