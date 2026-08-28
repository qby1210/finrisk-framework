# 变更与验证日志

## 2026-08-28：人工审核 Query 160 测试集成为新基准

- 评测基准切换为人工审核后的 `data/raw/query/query_test_set_160.json`，原 60 条测试集不再作为后续标准；
- 评测入口更新为 `scripts/evaluate_query_test_set_160.py`，结果写入 `outputs/query_test_set_160/`；
- ST4/ST5 增加不泄露风险答案的材料载体上下文，Web/API 支持用户直接指定六类场景，未配置 LLM 时自动使用本地规则回退；
- 新增 300 条开发集与 36 条九类低频标签长尾增强集，并提供标注规范、数据卡和可重复构建脚本；
- 检索升级为 BM25 + TF-IDF 向量 + RRF + 轻量重排，增加监管机构、主体、机构类型和日期组合筛选及中文命中理由；
- 新增 CSV/XLSX 提取、PDF 原生表格与跨页表格合并、逐字段置信度/来源、主体关系表、人工复核留痕和 HTML 审查报告；
- DeepSeek 客户端使用共享连接池、并发上限和短退避重试；Web 使用主办方红 `#C41E21`、蓝 `#4994DF`、灰 `#D8D9DC`、白四色；
- 160 条 full 实测：场景准确率 88.75%，二分类 P/R/F1 96.30%/81.89%/88.51%，多标签 Micro/Macro-F1 56.04%/56.71%，平均/P95 4.61s/12.45s，0 错误；
- 160 条 local 实测：场景准确率 79.38%，二分类 F1 57.29%，多标签 Micro/Macro-F1 28.14%/21.47%，平均/P95 0.20s/1.54s，0 错误；
- 低频标签 full 实测：培训材料违规 F1 92.31%（12/14、0 误报），虚构收益率 F1 100%（7/7、0 误报）；
- 全量质量门：Ruff、mypy、Node 语法检查通过，pytest 49 项通过。检索 Recall@K/MRR/nDCG@K 按项目安排等待队友人工金标准，不使用训练集相关案例冒充最终测试。

## 2026-08-26：Query 4.0 风险链路与浅色演示工作台

- Query文件抽取摘要新增哈希、页数、OCR、质量与块/字词统计；句子映射增加前后文、
  OCR置信度和抽取方式；
- 风险初判改为强组合规则与场景加权关键词两阶段，高置信本地直出，中低置信动态批量
  DeepSeek复核；LLM提示词不再包含任何案例，并允许27标签的相关/包含标签并存；
- 案例检索后移到最终句分达到门槛后，强制标签相交，使用BM25 + 本地TF-IDF向量 +
  RRF + 轻量重排；案例分不参与当前Query定性；
- QueryAnalysisResult升级4.0，增加文档级风险集合、Top案例、本地/LLM/检索计数；
- Web改为浅色后台布局，新增原文高亮、逐句定位、检索分解和整体结论，案例功能保留；

## 2026-08-25：案例库升级 2026-08-25（每日自动更新首跑验证）

- 定时任务真实触发全链验证通过：4115 栏目新增 13 文书，5 案保险相关入库
  （摘要案落 review），正式版 **7,628 案**（+5），
  `data_version=case_kb_v2_1_2026-08-25`，valid 全绿；
  latest_crawl_at=2026-08-25、latest_penalty_date=2026-08-24；
- 修复案例库侧打戳顺序：从重建函数内移到 update_log 追加之后
  （否则 latest_crawl_at 读到上一次运行日期）；
- 修复每日任务 ps1 编码：补 UTF-8 BOM（Windows PowerShell 5.1 对无 BOM
  脚本按 ANSI 误读中文路径，导致 08-25 08:00 首次计划运行失败）。

## 2026-08-24：案例库每日自动更新（Windows 定时任务）

- 案例库侧新增 `scripts/sync_kb_to_finrisk.py`：以 cases.sha256 比对检测变化，
  有变化才把主库 full/ 覆盖同步到本目录并相对化 manifest；源 valid 不为真时
  拒绝覆盖；
- 案例库侧 `scripts/daily_auto_update.ps1` + Windows 任务计划
  `CaseKB-DailyUpdate`：每天 08:00 自动 采集→入库→重建→打戳→同步本项目
  （登录后运行，错过补跑，3 小时限额；日志在案例库项目 logs/ 下）；
- 注意：同步只更新磁盘数据，运行中的服务仍持旧数据内存副本，
  **重启服务后**健康接口与检索才反映新库；GitHub 推送仍手动。

## 2026-08-24：顶栏徽章显示案例库采集/处罚日期

- manifest 新增 `latest_crawl_at` / `latest_penalty_date`（案例库侧
  `scripts/stamp_kb_crawl_meta.py` 打戳：采集时间取自一键更新日志，
  最新处罚日期为库内 penalty_date 最大值；只改 manifest 不动数据文件，
  `_refresh_manifest` 保留式更新不会冲掉；已挂入自动重建链路）；
- `/api/health` 与 `/api/cases/statistics` 透出两字段，旧版库缺失时为 null；
- 顶栏徽章追加「最近采集 YYYY-MM-DD · 最新处罚 YYYY-MM-DD」分段，
  字段缺失自动省略（兼容旧库）；
- 验证：两接口返回 2026-08-22 / 2026-08-21；pytest 32 通过（另 2 项
  query_api 失败为本机环境变量 DEEPSEEK_API_KEY 已设置所致， unset 后全过，
  与本次改动无关）。

## 2026-08-24：案例库标题/当事人确定性清理（同目录覆盖 08-23 版）

- 案例库 `case_kb_v2_1_2026-08-23` 同目录覆盖更新（仍 7,623 案，valid 全绿、
  金选 500/500、泄漏 0）——标题与当事人名称确定性清理，口径不变：
  - party_name：37 案去"被处罚当事人"前缀、63 案去"（时任…职务）"、
    39 案括号配对补齐、2 案截断尾部按原文补字（…中心支/…支公→公司）；
  - case_title 随构建自动重生成（标题由 party+标签组成，party 修复后
    标题前缀/括号残留同步清零）；
  - 验证：标题 前缀=0 括号=0；party 前缀=0 职务=0 括号=0；
  - kb_increments 96 案既存记录 party 修正（案例库侧"只增不改"原则的唯一
    批量例外，经用户 2026-08-24 批准，记录已打
    `party_name_manual_fix_2026_08_24` 审计标记）。

## 2026-08-23：案例入库 LLM 契约容错 + 真实联调通过

- **真实联调发现**：此前 LLM 结构化在真实文书上 100% 落入正则降级——模型常把
  `legal_basis_refs` 输出成纯字符串列表、`risk_tag_basis` 返回 null 或单个残缺对象，
  整单 Pydantic 校验失败。此前"真实 PDF 入库测试"均用 `llm_client=None`，
  该路径从未真正走通过；
- 修复（`src/offline/case_ingestion.py`）：`_CaseLLMOutput` 增加 before 校验器——
  法条字符串自动包成 `{law_name, article}`；列表字段 null→[]、单对象→列表、
  缺 risk_tag/quote 的证据项丢弃（build 阶段本就按引文原文命中再过滤）；
  提示词同步明确 legal_basis_refs 对象结构与"列表空时输出 [] 禁止 null"；
- 验证：两份此前出问题的长文书（多人处罚/旧 party 错位案）真实 DeepSeek 调用——
  llm_used=True，party/violation/penalty 完整句子收尾、与案例库修复版一致，
  completeness warnings 为空；`llm_client=None` 降级路径回归通过；
- 注意：增量案 fact 切片 `is_verbatim=False`（LLM 对案由做句式整理，非原文逐字
  子串）——本侧无案例库侧的逐字证据门，retrieval_enabled 不受影响，属口径差异；
- 本机已建 `.venv`（最小依赖：pydantic/httpx/dotenv/docx/pymupdf/pillow/pytest），
  全量测试仍需 `uv sync` 安装 onnxruntime/rapidocr 等完整依赖。

## 2026-08-23：案例库升级 2026-08-23（历史字段修复版）

- 案例库升级为 `case_kb_v2_1_2026-08-23`（7,623 案，valid 全绿、金选 500/500 可检索、
  测试集泄漏 0；`src/settings.py` 默认路径、README/architecture/data_contracts/
  测试同步切换，08-22/08-18 目录保留可回退）；
- 修复历史 C/R 案字段缺陷（案例库侧 `scripts/repair_case_fields.py`，DeepSeek 重抽
  约 1,500 案 + 确定性清理，全部对齐回原文连续片段）：
  - party_name：269 案去除"当事人"前缀/地址/身份证混入，15 案错位文本块由模型
    重抽主被处罚方；
  - violation_behavior：1,369 案半句截断重抽并逐字对齐原文，40 案沿原文顺延至
    句号收尾；
  - penalty_content：144 案错位（混入当事人身份信息）/截断重抽，金额逐一对照
    原文防幻觉；
  - 金选层同步修复 192 案摘要与字段，official_gold 口径不变；
- 检索侧收益：此前截断/错位文本直接进入 BM25 索引污染相似案例排序，本版数据
  修复 + 索引重建后该噪声消除；
- 已知残留：U000440 的 party_name 含职务说明（源自官网增量采集记录，修改需
  案例库侧批准）；17 案案由以"等"字收尾，为金监总局摘要表自然格式，非截断。

## 2026-08-23：案例入库字段截断加固

- 案例结构化 `max_tokens` 3000→8000，命中 length 上限时按 16000 自动重试一次；
  此前长处罚文书的 JSON 输出被静默截断、落入正则降级，是"字段半句话就断"的来源之一；
- LLM 客户端透出 `finish_reason`，JSON 解析失败时能区分"输出被截断"与普通格式错误；
- 案例结构化提示词补充完整性要求：party_name 只取主要被处罚方完整名称（不含标签
  前缀/地址/职务），violation_behavior 与 penalty_content 必须完整句子收尾、不得
  混入当事人身份信息；
- 入库后新增 `_field_completeness_warnings` 事后检查：案由/处罚内容虚词收尾、处罚内容
  混入身份信息、party_name 含前缀或地址时写入 warnings（不阻断入库，便于前端提示复核）。

## 2026-08-23：官网定期采集入库管线 + 主库升级 2026-08-22

### 数据

- 案例库升级为 `case_kb_v2_1_2026-08-22`（7,617 案，含官网增量 U 案；
  `src/settings.py` 默认路径同步切换，旧 08-18 目录保留可回退）；
- `data/raw/cases/crawl/` 预置采集状态（state.json + ingested.jsonl 台账 +
  已抓拆分件），保证首次运行不会把已在库中的 353 条官网案重复入库——**勿删**。

### 采集入库管线（新增）

- `src/offline/penalty_crawler/`：金监总局 NFRA 三栏目（4113 总局/4114 省局/4115 分局）
  采集器——CDN 静态 JSON 优先动态接口回退、GBK/UTF-8 探测、rowspan 汇总表拆单案、
  1.5s 限速、state.json 增量去重；人民银行源备用未启用；
- `src/offline/penalty_crawler/filter.py`：保险关键字筛选 + 银行当事人排除
  （银行代销保险被罚不入库；寿险银保渠道个人案不误伤；保险资管放行）+
  三级去重（state/台账 sha1/案例库 case_id 哈希）；
- `scripts/update_cases_from_web.py`：日常一条命令，采集→筛选→复用
  `CaseManagementService.ingest_file` 统一入库链（与 Web 上传同 builder、同三表追加、
  同回滚），`--dry-run` 只采集汇报不调模型（纯标准库可跑）；
- 与案例库侧口径差异说明：本链无入库门，LLM 成功即 auto_checked 进检索，
  不像案例库侧有 validate_candidate + 三级抢救——薄摘要案会直接 active，属已知取舍；
- 验证：`--dry-run` 播种后 pending=0（765 indexed = 353 台账拦 + 412 非保险），
  跨机器路径重定位、py_compile 通过；真实入库需 `uv sync` + .env 配置 DEEPSEEK_API_KEY。

## 2026-08-22：三包整合与可运行 Web 系统

### 数据

- 将 `case_kb_v2_1_2026-08-18.zip` 的完整案例数据放入
  `data/processed/knowledge/case_kb_v2_1_2026-08-18/`；
- 未重新生成案例；核验 cases 7,328、chunks 29,918、expansions 8,873、review queue
  1,046、excluded 9，五个文件的 SHA-256 均与原 manifest 一致；
- 只从 `risk_src.zip` 保留唯一风险词库资产，没有复制其重复案例 JSONL；
- 明确案例库是队员根据 PDF 生成的数据，不是官方权威数据；
- Web 新增案例使用 `case_origin=web_ingestion` 追加到同一三表，不建立第二个数据库。

### 后端

- 新增统一 `AppSettings`、案例仓库、事务式三表追加、manifest 刷新、停用/恢复；
- 新增可直接运行的中文 unigram/bigram BM25 与案例聚合检索；
- 合并风险词库、正则、语义证据、DeepSeek 判断、0.2/0.2/0.6 融合和阈值；
- 修复旧阈值中低风险分支不可达；
- 修复“案例相似即判风险/继承案例标签”的误判，加入独立信号门控；
- 补充“从不/绝不/保证不 + 拒赔/扯皮/拖延”绝对服务承诺规则；
- 新增案例 PDF 结构化、证据切片、扩展、重复检测和原文件保存；
- 统一 DeepSeek 模块，默认 `deepseek-v4-flash`，JSON 输出、关闭 thinking；
- Query 社交平台 Emoji 项目符号切分，同时保留 OCR 软换行；
- 完成案例、Query、检索、风险和健康 API。

### Web UI

- 风险查询：文本/文件输入、整体风险、逐句筛选、证据和案例详情；
- 案例录入：文件拖放、处理状态、警告和新案例详情；
- 案例管理：统计、搜索、标签/状态/来源筛选、分页、详情、停用和恢复；
- 响应式布局、加载态、错误态、空状态、抽屉和消息提示。

### 清理

- 删除 offline 的 embedding/enrichment/labeling/normalization/pipeline 占位文件；
- 删除两个未实现批处理脚本；
- 不复制复现包中的 GPU server、训练、实验和未交付权重；
- 删除未被运行代码使用的旧案例模型，文档切换到实际 JSONL/API 契约；
- 保留原始压缩包作审计输入，运行不依赖。

### 验证结果

- Ruff：通过；
- mypy strict：通过；
- pytest：36 项全部通过；
- JavaScript `node --check`：通过；
- 首页、静态 JS、健康接口 HTTP 200；健康接口识别 7,328 条启用案例和
  `deepseek-v4-flash`；
- 真实处罚 PDF：不写主库的抽取和三表构建通过；
- 真实小红书第一条：完全本地模式下识别 ST3；普通保障字段低于 0.20，无风险标签；
  “从不扯皮”中风险 0.8148，标签“绝对化表述、虚假宣传”；
- 人工无敏感测试句：DeepSeek 真实联调成功，高风险 0.9406，命中 5 条案例；
- 真实小红书文案未发送给 DeepSeek；在线外发测试因缺少针对该样本的单独授权而未执行；
- 桌面浏览器控制进程受当前沙箱初始化故障影响，未完成截图级视觉自动化；HTTP、静态资源、
  JavaScript 和 API 联动已验证。
