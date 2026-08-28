# FinRisk 保险营销合规工作台

FinRisk 是面向保险监管处罚材料与营销材料的本地 Web 系统，覆盖比赛要求的五条主线：

- 处罚材料解析：PDF、扫描图片、RapidOCR、DOCX、TXT、Markdown、CSV、XLSX、表格与跨页表格；
- 案例结构化：主体、监管机构、机构类型、相关人员、处罚事实、标签、字段置信度与原文证据；
- 相似案例检索：BM25 + 本地 TF-IDF 向量 + RRF + 轻量重排和组合筛选；
- 材料合规审查：六场景路由、逐句风险判断、DeepSeek 复核、案例佐证和人工复核留痕；
- 样本与评测：160 条人工审核测试基准、300 条开发集、36 条长尾增强集和统一评测脚本。

系统使用一套包含 7,628 条案例的知识库，不重复维护案例库、文件提取器或 LLM 客户端。
当前案例数据由项目组依据监管材料构建，不代表监管机构逐条确认；正式结论必须回看原文证据并经人工复核。

## 当前状态

| 项目 | 状态 |
| --- | --- |
| Web/API、案例录入、案例管理、风险查询 | 已完成 |
| 用户指定 ST1–ST6 场景、无 LLM 本地回退 | 已完成 |
| 人工复核界面、JSONL 审核留痕、HTML 报告导出 | 已完成 |
| PDF 原生表格、跨页合并、CSV/XLSX 表格读取 | 已完成 |
| 主体关系、字段置信度、原文来源 | 已完成 |
| 独立人工检索评测集及 Recall@K/MRR/nDCG@K | 等待项目组人工金标准 |
| 专用手写识别模型 | 未实现，进入人工复核 |

## 快速启动

要求 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```powershell
uv sync --all-groups
Copy-Item .env.example .env
# 编辑 .env，填写 DEEPSEEK_API_KEY；不填写也可使用本地回退
uv run python scripts/run_web.py
```

- 工作台：<http://127.0.0.1:8000>
- OpenAPI：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

`.env` 已被 Git 忽略。禁止将 API Key 写入前端、日志或提交记录。DeepSeek 不可用时，
系统会返回本地规则结果并继续案例检索，不会中断请求。

## Web 使用

### 风险查询与人工复核

1. 进入“风险查询”，粘贴文本或上传文件；
2. 选择“自动判断”或手动指定 ST1–ST6，手动指定可跳过场景模型调用；
3. 点击分析，查看原文高亮、逐句风险、标签、理由、耗时和相似处罚案例；
4. 分析完成后，在结果底部找到“人工复核留痕”面板；
5. 选择确认、人工修正或退回，填写审核人、修正场景、修正标签与意见后保存。

审核记录追加到 `data/processed/reviews/query_reviews.jsonl`，包含 Query ID、输入哈希、
原结果、修正内容、审核人和审核时间，不覆盖历史记录。页面还可导出独立 HTML 审查报告，
再由浏览器打印为 PDF。

### 案例录入与管理

- “案例录入”支持 PDF、图片、TXT、Markdown、DOCX、CSV、XLSX；
- 新案例写入统一 `cases / case_chunks / case_expansions` 三表；
- “案例管理”支持搜索、筛选、查看证据、停用与恢复；
- 停用只修改 `retrieval_status`，不会删除原始文件和结构化记录。

## 160 条正式评测

评测日期：2026-08-28。两种模式均为 160/160 成功、0 错误。

| 模式 | 场景准确率 | 二分类 P / R / F1 | 多标签 Micro / Macro-F1 | 平均 / P95 |
| --- | ---: | ---: | ---: | ---: |
| DeepSeek 完整流程 | 90.00% | 100.00% / 100.00% / 100.00% | 68.88% / 71.76% | 4.04s / 9.73s |
| 本地回退 | 80.00% | 98.67% / 58.27% / 73.27% | 49.93% / 46.18% | 0.48s / 1.77s |

DeepSeek 完整流程的二分类 Accuracy 为 100.00%；多标签 Precision / Recall 为
63.83% / 74.79%，Exact Match 为 30.63%，Mean Jaccard 为 65.88%。本地回退的
二分类 Accuracy 为 66.25%，适合 API 不可用时保持高精度告警和可用性，但召回低于完整模式。

完整模式平均阶段耗时：Query 准备 743ms、本地规则 1ms、LLM 3039ms、案例检索 260ms；
133/160 条使用了 DeepSeek，另外 27 条由高置信本地证据直接完成。主要瓶颈仍是 LLM，
不是相似案例查询；完整 160 条墙钟时间为 109.57s。

本轮准确率改进均为可泛化证据，不按测试编号特判：

- 合规语境保护：识别“不得承诺、必须披露、不会承诺”等禁止性或正向规范，避免反向误报；
- 长尾强证据：覆盖代签、签名与验证码时序、批量假回访、无资质会务、费用回流和混口径竞品比较；
- 标签关系校准：依据人工集共现和标签定义移除低可靠自动扩展，减少标签堆叠；
- 通道证据门控：回访违规、电销违规仅在 ST5/ST6 且存在明确行为证据时输出；
- DeepSeek 对比提示：显式区分合规禁止语句与规避披露、先投保后看条款等风险指引。

正式报告：

- `outputs/query_test_set_160/evaluation_full.md`
- `outputs/query_test_set_160/evaluation_local.md`

## Query 数据资产

| 文件 | 数量 | 用途 |
| --- | ---: | --- |
| `data/raw/query/query_test_set_160.json` | 160 | 六场景最终人工审核测试基准 |
| `data/raw/query/query_dev_set.json` | 300 | 开发调试，来自既有训练 Query 规范化 |
| `data/raw/query/query_long_tail_enhancement.json` | 36 | 九类低频标签增强，待逐条人工复核 |
| `data/raw/query/retrieval_train_queries.jsonl` | 300 | 开发集构建源和检索弱监督来源 |

重新构建开发集与长尾集：

```powershell
uv run python scripts/build_query_datasets.py
```

160 条测试集是唯一正式 Query 基准。旧 60 条数据和报告已经移除。

## 案例知识库

```text
data/processed/knowledge/case_kb_v2_1_2026-08-23/
├─ data/
│  ├─ cases.jsonl              # 7,628 条案例
│  ├─ case_chunks.jsonl        # 可追溯事实/证据切片
│  ├─ case_expansions.jsonl    # 检索扩展表达
│  ├─ review_queue.jsonl
│  └─ excluded_records.jsonl
├─ dictionary/                 # 27 类风险标签及映射
├─ reports/
└─ manifest.json               # 版本、行数和 SHA-256
```

系统启动不会重建主库。风险关键词唯一资产位于
`data/risk/keyword_db/risk_keyword_db.json`。

金监总局处罚栏目增量更新：

```powershell
uv run python scripts/update_cases_from_web.py
uv run python scripts/update_cases_from_web.py --dry-run
```

采集使用 state、台账 SHA-1、案例 ID 三级去重。`data/raw/cases/crawl/` 是增量状态目录，
不可作为缓存删除，否则可能造成重复入库。

## 分析与检索流程

```text
文本/文件
  → 原生解析或OCR、表格还原、坐标/页码/哈希/置信度
  → 用户指定或自动六场景分类
  → 可逆切句与原文映射
  → 两阶段本地风险初判
  → 中低置信句批量DeepSeek复核
  → 风险分、等级和27类标签
  → 达门槛后按标签和元数据检索案例
  → BM25 + TF-IDF向量 + RRF + 轻量重排
  → 逐句结果、文档结论、Top案例和复核建议
```

案例相似度只作佐证，不参与当前材料风险分，也不会被放入 LLM 提示词。检索支持自然语言、
风险标签、监管机构、处罚主体、机构类型和处罚日期范围组合过滤，并返回中文命中理由。

当前向量通道是中文 unigram/bigram TF-IDF 余弦相似度，无需下载权重或 CUDA，适合离线演示。
独立检索金标准完成前，不使用训练 Query 的 `relevant_cases` 冒充最终测试结果。

## 主要 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 数据版本和 LLM 状态 |
| POST | `/api/query/analyze/text` | 文本完整风险分析 |
| POST | `/api/query/analyze/file` | 文件完整风险分析 |
| POST | `/api/query/reviews` | 保存人工复核留痕 |
| GET | `/api/knowledge/search` | Top-K 混合案例检索 |
| GET | `/api/cases` | 案例分页与组合筛选 |
| GET | `/api/cases/{case_id}` | 案例详情、主体关系和证据 |
| POST | `/api/cases/upload` | 新处罚材料入库 |
| PATCH | `/api/cases/{case_id}/status` | 停用或恢复案例 |

## 项目结构

```text
src/
├─ api/             # FastAPI 路由与依赖装配
├─ application/     # Query、案例、检索、复核用例
├─ domain/          # 唯一跨模块 Pydantic 契约
├─ extraction/      # 文件、OCR、表格和位置提取
├─ llm/             # 共享 DeepSeek/OpenAI-compatible 客户端
├─ offline/         # 案例结构化、官网增量采集
├─ query/           # 场景分类、切句、原文映射
├─ retrieval/       # BM25 与本地向量索引
├─ risk/            # 规则、校准、LLM复核、检索门控
├─ storage/         # 统一案例库持久化
└─ web/static/      # 红、白、灰、蓝比赛演示UI
```

## 验证

```powershell
uv run ruff check .
uv run mypy src
uv run pytest -q
node --check src/web/static/app.js

uv run python scripts/evaluate_query_test_set_160.py --mode local
uv run python scripts/evaluate_query_test_set_160.py --mode full --concurrency 6

# 改动期间只回归指定样本；--query-id 可重复
uv run python scripts/evaluate_query_test_set_160.py --mode full --query-id GQ-001 --query-id ST56-QT-045
```

完整模式会调用 DeepSeek API。测试中的真实营销文案显式禁用 LLM，避免把用户数据外发。

## 文档

- [比赛任务交付映射](docs/competition_delivery.md)
- [系统架构](docs/architecture.md)
- [Query处理流水线](docs/query_pipeline.md)
- [数据与API契约](docs/data_contracts.md)
- [标注规范](docs/annotation_guideline.md)
- [数据集说明](docs/dataset_card.md)
- [变更与验证日志](docs/CHANGELOG.md)
- [团队协作约定](docs/collaboration.md)

## 已知限制

- RapidOCR适合清晰印刷体和常见扫描件，复杂手写材料需要人工复核；
- 保险案例预筛与主体关系抽取属于可解释轻量实现，不是独立训练的NER/关系模型；
- 本地回退速度快但召回低于完整模式；
- 长尾增强集在人工确认前不能作为最终金标准；
- 检索 Recall@K、MRR、nDCG@K 等待独立人工相关性集合。

## 维护约定

- 算法放在业务模块，脚本只负责启动与离线编排；
- 跨模块字段只放 `src/domain`，不建立第二套案例库或 LLM 客户端；
- 路径统一从 `AppSettings` 获取，不写个人绝对路径；
- 原始材料不可覆盖，抽取字段必须能回到原文或明确标记低证据；
- 修改阈值、标签、schema或数据版本时，同步更新测试、报告和文档。