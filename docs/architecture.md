# 系统架构

## 目标与边界

FinRisk 是单进程 FastAPI 本地工作台，服务三项用例：案例增量录入、统一案例库管理、
Query 风险判断与案例匹配。现有 7,628 条案例直接读取，不在启动时重建。

案例库是队员根据原始 PDF 构建的数据资产，并非官方权威库。系统保留来源、哈希、原文和
证据状态，允许复核；任何自动判断都不是监管或法律结论。

## 依赖方向

```text
Web / OpenAPI
      │
      ▼
api ──────── 只负责 HTTP、校验和依赖装配
      │
      ▼
application ─ 业务用例编排
   │      │
   │      ├──────────────┐
   ▼      ▼              ▼
offline  query          risk
   │      │              │
   ├──────┴──────┬───────┤
   ▼             ▼       ▼
extraction      storage  retrieval
         \        │       /
          └──── domain ──┘
                    ▲
                   llm（被 query/offline/risk 通过同一协议调用）
```

约束：

- `domain` 不依赖业务模块；
- `api` 不写算法，`application` 不复制持久化或模型推理；
- `extraction` 是案例和 Query 唯一文件解析实现；
- `llm` 是全项目唯一外部大模型客户端；
- `storage` 是案例三张 JSONL 主表的唯一写入口；
- Query 风险流程不修改案例标签，案例入库不调用 Query 风险结论打标签。

## 案例增量流程

```text
Web 上传原始文档
  → 安全文件名与 25 MB 限制
  → FileExtractor（PDF 文本层优先，必要时 OCR）
  → IncrementalCaseBuilder
      ├─ DeepSeek 严格 JSON 结构化
      ├─ 失败时规则降级并标记人工复核
      ├─ 原文逐字证据校验
      ├─ cases 记录
      ├─ case_chunks 证据/事实切片
      └─ case_expansions 检索扩展
  → 保存原始文件
  → CaseRepository 三表事务式追加
  → 刷新 manifest 与内存检索 revision
```

同一文件 SHA-256 生成同一 `U...` 案例 ID，重复上传返回 HTTP 409。写入中任一步失败时，
三张文件恢复到原长度，原始上传副本也回滚。

## Query 风险流程

```text
文字或文件
  → 多模态抽取与文件级六类场景分类
  → 逐句切分、原文偏移、页面坐标和上下文
  → 强组合规则 + 场景加权关键词两阶段初判
  → 中低置信句动态批量 DeepSeek 复核（无案例输入）
  → 最终风险分达到门槛后执行标签约束检索
  → BM25 + TF-IDF向量 + RRF + 本地重排
  → 文档级分数、标签和Top案例聚合
  → QueryAnalysisResult
```

案例检索首次调用时延迟构建内存索引；新增、停用或恢复案例会增加仓库 revision，下一次
检索自动重建。BM25与TF-IDF向量通道共用倒排表，不依赖CUDA或外部模型权重。

未来需要 BGE-M3/reranker 时，只替换 `retrieval` 的索引实现，保持
`CaseRetrievalService.search()` 和 `MatchedCase` 不变。

## 数据布局

```text
data/raw/cases/                       原始案例和 Web 上传文件
data/raw/query/                       仅测试样本
data/risk/keyword_db/                 唯一风险词库
data/processed/knowledge/
└─ case_kb_v2_1_2026-08-23/           唯一案例数据库
   ├─ data/*.jsonl
   ├─ dictionary/
   ├─ reports/
   └─ manifest.json
```

`case_origin` 区分数据来源但不分库。停用是可恢复状态，不做物理删除。

## 可靠性与安全

- 上传按块读取并限制体积，文件名去除路径片段；
- API Key 只从环境变量读取，响应和日志不返回密钥；
- LLM 强制 JSON 对象并用 Pydantic 二次校验；
- LLM 失败时可解释降级，不吞掉警告；
- 案例相似度不能独立触发风险，也不能覆盖独立规则/LLM 标签；
- 原始文件、原始文本和模型生成字段分开保存；
- `DELETE` 兼容接口实际执行停用，防止误删比赛数据。
