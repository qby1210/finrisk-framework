# FinRisk 保险营销合规工作台

当前源码包含 **2026-10-15 的 Pi Agent、上下文、原文高亮与界面改进**。左上角图标与页签
图标已采用参考图中的利安人寿红色。本次源码同步不更新线上部署，具体改动、运行要求与
验证记录见 [改进说明](docs/local_upgrade_20261015.md)。

FinRisk 是面向保险营销材料和监管处罚案例的合规审查 Web 系统，提供材料解析、六场景识别、
逐句风险判断、相似案例检索、案例管理、人工复核留痕和工程评测能力。

## 公网部署

项目已经完成服务器部署，可直接通过公网访问：

**[http://156.239.2.239/](http://156.239.2.239/)**

- 工作台：<http://156.239.2.239/>
- OpenAPI 文档：<http://156.239.2.239/docs>
- 健康检查：<http://156.239.2.239/api/health>

2026-08-31 核查时，公网首页返回 HTTP 200，健康接口返回 `status: ok`，在线实例已加载
7,630 条案例并启用 `deepseek-v4-flash`。在线案例数量会随案例录入而变化，应以健康接口的
实时结果为准。

## 案例数据来源与打包说明

项目使用的监管处罚案例来自**赛事方提供的数据集**。项目组在赛事数据基础上完成了解析、
清洗、结构化、标签规范化、证据切片和检索扩展，形成系统运行时的案例知识库。

仓库已携带当前演示所需的结构化运行知识库，共 **7,628 条案例**。本次源码同步沿用现有
数据版本，未新增或改写案例数据。本地上传材料、历史压缩包、密钥及运行缓存不随本次提交上传。

如需在本地恢复完整案例能力，请将赛事数据处理产物放到：

```text
data/processed/knowledge/case_kb_v2_1_2026-08-23/
├─ data/
│  ├─ cases.jsonl
│  ├─ case_chunks.jsonl
│  ├─ case_expansions.jsonl
│  ├─ review_queue.jsonl
│  └─ excluded_records.jsonl
├─ dictionary/
├─ reports/
└─ manifest.json
```

也可以在 `.env` 中通过 `FINRISK_CASE_KB_ROOT` 指向其他完整知识库目录。

## 主要能力

- **多格式材料解析**：支持 PDF、扫描图片、DOCX、TXT、Markdown、CSV、XLSX，保留页码、
  坐标、全文偏移、文件哈希和抽取置信度；
- **六场景路由**：覆盖海报/短信/社交平台、短视频/直播、产品介绍/详情页、说明会材料、
  培训材料/话术、电话销售/回访等 ST1–ST6 场景；
- **合规风险识别**：本地组合规则与 DeepSeek 动态复核结合，外部模型不可用时自动回退；
- **相似案例检索**：BM25、中文 unigram/bigram TF-IDF、RRF 融合及本地轻量重排；
- **可解释结果**：展示原文高亮、风险标签、理由、分数、证据位置和相似处罚案例；
- **案例管理**：支持案例录入、搜索、筛选、详情查看、停用和恢复；
- **人工复核**：保存审核人、修正标签、修正场景和意见，历史记录只追加、不覆盖；
- **工程评测**：提供 160 条人工审核测试基准、开发集、长尾增强集和统一评测脚本。

## 快速开始

### 直接体验线上系统

浏览器访问 [http://156.239.2.239/](http://156.239.2.239/)，无需本地安装。

### Windows 本地安装

要求 Python 3.11+、Node.js 22.19+ 和 npm。解压后依次运行：

```powershell
./install.ps1
./start.ps1
```

也可以直接双击 `install.bat` 和 `start.bat`。安装脚本使用标准 `venv + pip`，不要求预装 uv。

### Linux 本地安装

```bash
bash install.sh
bash start.sh
```

### 使用 uv 安装

```powershell
uv sync --all-groups
npm ci --prefix agent_runtime --ignore-scripts --cache agent_runtime/.cache/npm
Copy-Item .env.example .env
# DEEPSEEK_API_KEY 可留空，系统会使用本地回退
uv run python scripts/run_web.py
```

本地默认地址：

- 工作台：<http://127.0.0.1:8000>
- OpenAPI：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

`.env.example` 是配置模板。真实 API Key 不得写入前端、日志、Git 或交付文件。

## 系统处理流程

```text
文本或文件
  → 原生解析 / OCR / 表格还原
  → ST1–ST6 场景识别或用户指定场景
  → 可逆切句、说话人和作用域上下文、原文位置映射
  → 本地强规则和场景加权初判
  → 中低置信及上下文敏感句由 Pi Agent 批量语义复核（可选）
  → 风险分、等级和 27 类标签
  → 达到门槛后检索相似案例
  → BM25 + TF-IDF + RRF + 轻量重排
  → 逐句结果、文档结论、Top 案例和复核建议
```

案例相似度只用于提供佐证，不会独立触发风险，也不会覆盖规则或模型作出的风险结论。

## 项目结构总览

```text
FinRisk/
├─ src/                         核心应用源码
│  ├─ api/                     FastAPI 路由和依赖装配
│  ├─ application/             业务用例编排层
│  ├─ domain/                  跨模块数据契约
│  ├─ extraction/              文档、图片、OCR 和表格解析
│  ├─ llm/                     外部大模型客户端
│  ├─ offline/                 案例离线结构化和监管网站采集
│  ├─ query/                   Query 场景识别与文本增强
│  ├─ retrieval/               BM25/TF-IDF 混合检索
│  ├─ risk/                    风险规则、校准和分析流水线
│  ├─ storage/                 案例知识库持久化
│  └─ web/static/              浏览器端演示界面
├─ scripts/                     启动、评测、更新和打包脚本
├─ tests/                       自动化测试及测试数据
├─ data/                        数据目录；赛事案例不进入提交包
├─ outputs/                     固化评测结果
├─ docs/                        架构、契约、标注和交付文档
├─ deploy/                      systemd 与 Nginx 部署配置
├─ configs/                     配置项说明
├─ pyproject.toml               项目元数据和依赖声明
├─ uv.lock                      uv 精确依赖锁
├─ requirements*.lock.txt       pip 精确依赖锁
├─ .env.example                 环境变量模板
├─ install.*                    Windows/Linux 安装入口
├─ start.*                      Windows/Linux 启动入口
└─ verify.*                     Windows/Linux 验收入口
```

## 目录与文件详细说明

### 根目录

| 文件 | 作用 |
| --- | --- |
| `README.md` | 项目总说明、部署地址、运行方法、结构和接口说明。 |
| `DELIVERY_README.md` | 面向赛事提交的交付范围、排除项和验收说明。 |
| `pyproject.toml` | 项目名称、Python 版本、运行依赖、开发依赖及 Ruff/Mypy/Pytest 配置。 |
| `uv.lock` | uv 使用的完整依赖锁文件。 |
| `requirements.lock.txt` | 由 `uv.lock` 导出的运行依赖，供标准 pip 安装。 |
| `requirements-dev.lock.txt` | 包含测试、代码检查工具的完整 pip 依赖。 |
| `.env.example` | DeepSeek、阈值、知识库路径、上传目录等环境变量模板。 |
| `.gitignore` | 排除密钥、虚拟环境、缓存、模型权重和本地数据。 |
| `.gitattributes` | Git 文本属性设置。 |
| `install.ps1` / `install.bat` | Windows 创建虚拟环境、安装锁定依赖并执行交付检查。 |
| `start.ps1` / `start.bat` | Windows 启动本地 FastAPI 服务。 |
| `verify.ps1` / `verify.bat` | Windows 执行数据检查、Ruff、Mypy、Pytest 和前端语法检查。 |
| `install.sh` | Linux 创建虚拟环境并安装依赖。 |
| `start.sh` | Linux 启动本地服务。 |
| `verify.sh` | Linux 执行完整工程验收。 |

### `src/`：核心应用源码

| 文件 | 作用 |
| --- | --- |
| `src/settings.py` | 统一读取项目根目录、知识库、风险词库、上传目录和阈值配置。 |
| `src/api/__init__.py` | API 包标记。 |
| `src/api/app.py` | FastAPI 应用入口；定义首页、健康检查、风险分析、案例管理和人工复核接口。 |
| `src/application/__init__.py` | 应用层包标记及公共导出。 |
| `src/application/analysis_service.py` | 编排 Query 处理、风险检测和案例检索的完整分析用例。 |
| `src/application/case_service.py` | 编排案例列表、详情、统计、上传入库和状态变更。 |
| `src/application/query_service.py` | 处理文本/文件 Query、场景识别、切句和原文映射。 |
| `src/application/retrieval_service.py` | 组合筛选、双路召回、RRF 融合、重排和命中理由生成。 |
| `src/application/review_service.py` | 校验并追加保存人工复核记录。 |
| `src/domain/__init__.py` | 领域契约包标记。 |
| `src/domain/common.py` | Pydantic 公共基类和通用字段约束。 |
| `src/domain/file_models.py` | 文件抽取结果、页、表格、区域和来源位置模型。 |
| `src/domain/knowledge_models.py` | 案例摘要、详情、证据、统计和检索结果模型。 |
| `src/domain/query_models.py` | Query 场景、句子、映射、分类和处理结果模型。 |
| `src/domain/review_models.py` | 人工复核请求与留痕记录模型。 |
| `src/domain/risk_models.py` | 逐句风险、文档汇总和最终分析结果模型。 |
| `src/extraction/__init__.py` | 对外导出统一文件抽取接口。 |
| `src/extraction/assembler.py` | 将多页、多块文本、表格和位置组装为统一文档结果。 |
| `src/extraction/config.py` | OCR、PDF 和文件解析参数。 |
| `src/extraction/docx_reader.py` | 读取 DOCX 段落和表格。 |
| `src/extraction/errors.py` | 文件抽取异常类型。 |
| `src/extraction/geometry.py` | 页面坐标和区域归一化工具。 |
| `src/extraction/image_reader.py` | 图片输入读取入口。 |
| `src/extraction/ocr_reader.py` | RapidOCR 调用、结果清洗和坐标转换。 |
| `src/extraction/pdf_reader.py` | PDF 文本层、原生表格、逐页 OCR 回退和跨页处理。 |
| `src/extraction/reader.py` | 按扩展名分派 PDF、图片、文本、DOCX 和表格读取器。 |
| `src/extraction/spreadsheet_reader.py` | 读取 CSV/XLSX 并还原工作表结构。 |
| `src/extraction/text_reader.py` | 读取 TXT 和 Markdown，处理编码与行位置。 |
| `src/extraction/types.py` | 抽取模块内部协议和中间类型。 |
| `src/llm/__init__.py` | 对外导出 LLM 客户端、错误和响应类型。 |
| `src/llm/client.py` | Python 到 Pi Agent 的工作进程适配器，管理并发、超时、重试和结构化响应。 |
| `src/llm/types.py` | LLM 请求、消息、响应和使用量类型。 |
| `src/offline/__init__.py` | 离线处理包标记。 |
| `src/offline/case_ingestion.py` | 将处罚材料构建为 cases/chunks/expansions 三类记录并校验证据。 |
| `src/offline/extraction.py` | 离线案例文件抽取适配器。 |
| `src/offline/penalty_crawler/__init__.py` | 处罚采集包公共导出。 |
| `src/offline/penalty_crawler/common.py` | 请求、状态、台账、文件保存和去重公共逻辑。 |
| `src/offline/penalty_crawler/filter.py` | 保险相关处罚记录筛选。 |
| `src/offline/penalty_crawler/nfra.py` | 国家金融监督管理总局处罚栏目增量采集。 |
| `src/offline/penalty_crawler/pbc.py` | 中国人民银行处罚栏目采集适配。 |
| `src/offline/penalty_crawler/table_split.py` | 拆分和规范化处罚信息表。 |
| `src/offline/penalty_crawler/README.md` | 采集模块的使用方式、状态文件和边界说明。 |
| `src/query/__init__.py` | Query 处理包公共导出。 |
| `src/query/classification.py` | ST1–ST6 场景规则分类与可选 LLM 分类。 |
| `src/query/enhancement.py` | 可逆切句、上下文增强和原文偏移映射。 |
| `src/query/extraction.py` | Query 文件抽取入口。 |
| `src/retrieval/__init__.py` | 检索组件公共导出。 |
| `src/retrieval/sparse.py` | BM25、TF-IDF、RRF 和检索文档索引实现。 |
| `src/retrieval/tokenization.py` | 中文 unigram/bigram 规范化与切词。 |
| `src/risk/__init__.py` | 风险模块公共导出。 |
| `src/risk/calibration.py` | 风险分数、等级和阈值校准。 |
| `src/risk/detection.py` | 本地关键词、组合证据、保护语境和场景规则。 |
| `src/risk/pipeline.py` | 本地初判、LLM 复核、标签合并、检索门控和文档汇总。 |
| `src/risk/taxonomy.py` | 加载 27 类风险标签及描述。 |
| `src/storage/__init__.py` | 存储层公共导出。 |
| `src/storage/case_repository.py` | JSONL 案例库读取、查询、增量写入、停用恢复和 manifest 刷新。 |
| `src/web/__init__.py` | Web 资源包标记。 |
| `src/web/static/index.html` | 单页工作台的页面结构。 |
| `src/web/static/styles.css` | 红、白、灰、蓝比赛演示主题和响应式布局。 |
| `src/web/static/app.js` | 前端 API 调用、页面切换、表单、结果渲染、复核和报告导出。 |

### `scripts/`：工程脚本

| 文件 | 作用 |
| --- | --- |
| `scripts/run_web.py` | 从项目根目录加载 `.env` 并启动 Uvicorn。 |
| `scripts/build_query_datasets.py` | 重建开发 Query 和长尾增强数据。 |
| `scripts/evaluate_query_test_set_160.py` | 对 160 条正式基准执行 full/local 评测并生成报告。 |
| `scripts/evaluate_real_queries.py` | 对真实 Query 金标准执行评估。 |
| `scripts/update_cases_from_web.py` | 增量采集监管处罚并写入统一案例库。 |
| `scripts/verify_delivery.py` | 检查交付必需文件、知识库 manifest、哈希、行数和应用导入。 |
| `scripts/package_submission.ps1` | 按交付白名单生成压缩包和 SHA-256 文件清单。 |

### `data/`：数据与运行资产

| 路径 | 作用 | 提交包 |
| --- | --- | --- |
| `data/raw/cases/` | 赛事方原始处罚案例和采集状态。 | 不包含 |
| `data/raw/query/` | Query 测试集、开发集、长尾集和演示材料。 | 包含小型评测资产 |
| `data/interim/` | 抽取、规范化等中间数据目录。 | 不包含中间产物 |
| `data/processed/knowledge/.../data/` | cases、chunks、expansions 等处理后案例表。 | 不包含完整案例记录 |
| `data/processed/knowledge/.../dictionary/` | 风险标签字典和领域映射。 | 可保留字典与结构说明 |
| `data/processed/knowledge/.../manifest.json` | 数据版本、数量、文件哈希和校验指标。 | 完整数据恢复后使用 |
| `data/processed/reviews/` | Web 人工复核追加记录。 | 运行时生成 |
| `data/risk/keyword_db/risk_keyword_db.json` | 本地规则使用的唯一风险关键词资产。 | 包含 |

### `tests/`：自动化测试

| 文件/目录 | 作用 |
| --- | --- |
| `tests/README.md` | 测试分层、运行方式和数据依赖说明。 |
| `tests/api/test_case_api.py` | 完整案例库的统计、列表和详情 API 冒烟测试。 |
| `tests/api/test_query_api.py` | 首页、分类器、文本和文件分析 API 测试。 |
| `tests/api/test_review_api.py` | 人工复核校验和追加留痕测试。 |
| `tests/application/test_query_service.py` | Query 应用服务和文件处理测试。 |
| `tests/extraction/test_file_extractor.py` | PDF、图片、文本、DOCX、OCR 和偏移测试。 |
| `tests/offline/test_real_sample_ingestion.py` | 真实案例材料的三表构建测试；缺少赛事数据时跳过。 |
| `tests/query/test_query_processing.py` | 六场景分类、切句和原文映射测试。 |
| `tests/query/test_social_splitting.py` | 社交平台项目符号和复杂分段测试。 |
| `tests/risk/test_pipeline_order.py` | 风险流程顺序、LLM 输入隔离和检索门控测试。 |
| `tests/risk/test_real_query_evaluation.py` | Query 金标准结构和评测边界测试。 |
| `tests/risk/test_real_query_smoke.py` | 真实文案与完整案例库的本地匹配冒烟测试。 |
| `tests/risk/test_retrieval_gate.py` | 不同风险分数下的案例检索门槛测试。 |
| `tests/risk/test_risk_rules.py` | 风险规则、保护语境、标签和阈值测试。 |
| `tests/storage/test_case_repository.py` | 临时案例库写入、查询、停用和混合检索测试。 |
| `tests/data/real_query_gold.json` | 真实 Query 的人工标注测试数据。 |

### `docs/`、`deploy/`、`configs/` 与 `outputs/`

| 文件 | 作用 |
| --- | --- |
| `docs/architecture.md` | 分层架构、依赖方向、案例流程、Query 流程和安全设计。 |
| `docs/data_contracts.md` | 数据表、Pydantic 模型和 API 字段契约。 |
| `docs/query_pipeline.md` | Query 识别、切句、规则、LLM、检索和结果聚合细节。 |
| `docs/annotation_guideline.md` | 场景、风险标签和人工审核标注规范。 |
| `docs/dataset_card.md` | Query 数据集来源、拆分、用途和限制。 |
| `docs/competition_delivery.md` | 比赛任务与系统实现、指标和交付成果映射。 |
| `docs/collaboration.md` | 团队分工、分支、接口和数据协作约定。 |
| `docs/CHANGELOG.md` | 功能变更和验证记录。 |
| `deploy/finrisk.service` | Linux systemd 服务配置，定义工作目录、环境文件和 Uvicorn 命令。 |
| `deploy/nginx-finrisk.conf` | Nginx 反向代理、上传限制、超时和安全响应头配置。 |
| `configs/README.md` | 可配置环境变量及唯一配置来源说明。 |
| `outputs/query_test_set_160/evaluation_full.json` | DeepSeek 完整流程的机器可读评测结果。 |
| `outputs/query_test_set_160/evaluation_full.md` | DeepSeek 完整流程的评测报告。 |
| `outputs/query_test_set_160/evaluation_local.json` | 本地回退流程的机器可读评测结果。 |
| `outputs/query_test_set_160/evaluation_local.md` | 本地回退流程的评测报告。 |

## 主要 API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | 服务、案例数量、数据版本和 LLM 状态。 |
| POST | `/api/query/analyze/text` | 分析文本营销材料。 |
| POST | `/api/query/analyze/file` | 分析 PDF、图片、DOCX、文本或表格文件。 |
| POST | `/api/query/reviews` | 保存人工复核留痕。 |
| GET | `/api/knowledge/search` | 混合检索相似处罚案例。 |
| GET | `/api/cases` | 案例分页和组合筛选。 |
| GET | `/api/cases/{case_id}` | 获取案例详情和证据。 |
| POST | `/api/cases/upload` | 上传并增量结构化新案例。 |
| PATCH | `/api/cases/{case_id}/status` | 停用或恢复案例。 |

## 评测结果

评测日期：2026-08-28；两种模式均为 160/160 成功、0 错误。

| 模式 | 场景准确率 | 二分类 P / R / F1 | 多标签 Micro / Macro-F1 | 平均 / P95 |
| --- | ---: | ---: | ---: | ---: |
| DeepSeek 完整流程 | 90.00% | 100.00% / 100.00% / 100.00% | 68.88% / 71.76% | 4.04s / 9.73s |
| 本地回退 | 80.00% | 98.67% / 58.27% / 73.27% | 49.93% / 46.18% | 0.48s / 1.77s |

完整报告位于 `outputs/query_test_set_160/`。

## 验证

```powershell
./verify.ps1
```

或分别运行：

```powershell
uv run ruff check .
uv run mypy src
uv run pytest -q
node --check src/web/static/app.js
```

其中案例 API、真实案例入库和真实文案案例匹配测试依赖赛事案例数据；提交包未包含数据时，
应在恢复完整知识库后运行这些测试。其余规则、文件抽取、Query 处理和临时案例库测试不依赖
完整赛事数据。

## 已知限制

- 仓库携带当前演示所需的运行知识库，历史版本与本地新增上传材料需按各自环境另行维护；
- RapidOCR 适合清晰印刷体和常见扫描件，复杂手写材料需要人工复核；
- 本地规则回退速度快，但召回率低于 DeepSeek 完整流程；
- 当前中文向量通道为本地 TF-IDF，不需要 CUDA 或独立模型权重；
- 自动结果只用于风险筛查，正式结论必须回看原文证据并经人工复核。
