# FinRisk 保险营销合规工作台

FinRisk 是本次金融科技创新大赛的本地 Web 系统，现已打通三项核心功能：

- 案例录入：上传处罚 PDF/图片/TXT/DOCX，抽取并追加到统一案例库；
- 案例管理：分页检索、查看原文证据、停用和恢复已有案例；
- 风险查询：Query 六类场景分类、逐句风险判断、解释和相似案例匹配。

系统整合了队员提供的案例构建包、7,328 条案例数据、风险判断代码和 Query
分类/切分框架。运行时没有重复的案例库、文件提取器或 LLM 客户端。

> 数据性质：当前案例库由队员根据原始监管案例 PDF 生成，不是赛事官方下发或经监管机构
> 逐条确认的权威数据库。清单中的 `official_gold` 是旧构建流程的内部质量分层名称，不代表
> “官方认证”。正式结论仍应回看原始 PDF 和证据片段。

## 快速启动

要求 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```powershell
uv sync --all-groups
Copy-Item .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
uv run python scripts/run_web.py
```

- 工作台：<http://127.0.0.1:8000>
- OpenAPI：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

`.env` 已被 Git 忽略。不要把密钥提交、打印到日志或写进前端。未配置 DeepSeek 时，
明确的 Query 可使用规则与案例检索降级；需要大模型复核的模糊场景会返回明确错误。

## 一套案例数据

现成数据直接放在：

```text
data/processed/knowledge/case_kb_v2_1_2026-08-18/
├─ data/
│  ├─ cases.jsonl              # 7,328 条案例主记录
│  ├─ case_chunks.jsonl        # 29,918 条证据/事实等切片
│  ├─ case_expansions.jsonl    # 8,873 条检索扩展
│  ├─ review_queue.jsonl
│  └─ excluded_records.jsonl
├─ dictionary/                 # 风险标签和归口映射
├─ reports/                    # 原构建包质量报告
└─ manifest.json               # 版本、行数和 SHA-256
```

系统启动不会重新生成这些数据。Web 新增案例走相同概念流程，然后追加到上述同一组
`cases / case_chunks / case_expansions` 文件；`case_origin=web_ingestion` 仅用于追溯来源，
不表示另一套数据库。新增原始文件保存在 `data/raw/cases/uploads/`。

停用案例只把 `retrieval_status` 改为 `inactive`，不会删除结构化记录、证据或原始文件；
恢复后重新参与检索。三表追加带失败回滚，避免只写入部分文件。

风险关键词唯一资产位于 `data/risk/keyword_db/risk_keyword_db.json`。原始压缩包保留作
审计输入，但系统运行不依赖压缩包。

## 风险判断流程

```text
Query 文本/文件
  → 共用文件提取（文件输入）
  → 六类场景分类（规则高置信直出，DeepSeek 复核模糊场景）
  → 可逆偏移切句（支持社交平台项目符号）
  → 风险词库与组合正则
  → 同一案例库 BM25 检索
  → DeepSeek JSON 逐句判断
  → 0.2/0.2/0.6 融合与五档阈值
  → 逐句风险、依据、相似案例和整篇概览
```

案例相似度是佐证，不是定性。没有规则或大模型的独立风险信号时，检索分被限制在风险
阈值以下，历史案例标签也不会直接污染当前 Query。

当前统一 LLM 模块在 `src/llm/`，默认使用：

- Base URL：`https://api.deepseek.com`
- Model：`deepseek-v4-flash`
- API：OpenAI-compatible Chat Completions
- JSON 输出：`response_format=json_object`
- Thinking：默认关闭

## 项目结构

```text
src/
├─ api/             # FastAPI 路由、依赖装配、静态站点
├─ application/     # Query 分析、案例管理、案例检索用例
├─ domain/          # 唯一跨模块 Pydantic 契约
├─ extraction/      # PDF/图片/TXT/Markdown/DOCX 共用提取器
├─ llm/             # 唯一 DeepSeek/OpenAI-compatible 客户端
├─ offline/         # 新案例增量结构化和三表产物构建
├─ query/           # Query 场景分类、切句和原文映射
├─ retrieval/       # 可直接运行的中文 unigram/bigram BM25
├─ risk/            # 规则检测、融合校准、风险流水线
├─ storage/         # 统一案例库持久化与 manifest 刷新
└─ web/static/      # 三功能 Web UI
```

原案例检索复现包的完整 GPU/BGE 训练与实验代码没有复制进运行项目，因为其模型权重和
CUDA 环境不属于本次可交付运行依赖。当前保留了可解释、无外部权重的稀疏检索思路，接口
已隔离，后续可以在 `retrieval` 内替换为 BGE-M3/reranker 而不改 Web 和业务契约。

## 主要 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 数据和 LLM 状态 |
| POST | `/api/query/analyze/text` | 文本 Query 完整风险分析 |
| POST | `/api/query/analyze/file` | 文件 Query 完整风险分析 |
| GET | `/api/cases` | 案例分页与筛选 |
| GET | `/api/cases/{case_id}` | 案例详情和证据切片 |
| POST | `/api/cases/upload` | 新案例增量入库 |
| PATCH | `/api/cases/{case_id}/status` | 停用或恢复案例 |
| GET | `/api/knowledge/search` | 直接检索相似案例 |

详细字段见 [docs/data_contracts.md](docs/data_contracts.md)，流程见
[docs/architecture.md](docs/architecture.md) 和 [docs/query_pipeline.md](docs/query_pipeline.md)。

## 验证

```powershell
uv run ruff check .
uv run mypy src
uv run pytest -q
node --check src/web/static/app.js
```

真实样本测试不会写主库：处罚 PDF 只构建内存三表产物；小红书文案测试显式禁用 LLM，
避免把用户提供的数据外发。联调记录见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。

## 维护约定

- 算法放在对应业务模块，脚本只做启动；
- 跨模块字段只放 `src/domain`，不重复定义同义模型；
- 所有业务路径从 `AppSettings` 获取，不写开发者绝对路径；
- 原始文档不可覆盖，模型抽取字段必须能回到原文或标记为低证据；
- 修改风险阈值、标签体系或数据 schema 时，同步测试和文档。
