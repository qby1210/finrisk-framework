# FinRisk 后端框架

这是金融风险识别比赛项目的后端目录骨架。当前阶段只确认目录、模块边界和四类跨模块字段，不实现 API、Web、文件读取、模型推理、向量数据库或业务流程。

## 当前确认范围

只在 src/domain 中定义以下共享字段：

1. 文件读取输出：FileExtractionResult
2. 标准化案例：NormalizedCase
3. 最终案例记录：FinalCaseRecord
4. Query 分类增强结果：EnhancedQuery

其余 Python 文件只有中文用途说明，没有函数、接口或算法实现。

## 目录

    code/
    ├─ configs/                     # 路径、文件读取器和模型配置
    ├─ data/
    │  ├─ raw/
    │  │  ├─ cases/                 # 原始案例文件
    │  │  └─ query/                 # 原始 Query 文件
    │  ├─ interim/
    │  │  ├─ extracted_cases/       # 案例文件读取结果
    │  │  ├─ extracted_query/       # Query 文件读取结果
    │  │  └─ normalized_cases/      # 标准化案例
    │  └─ processed/
    │     ├─ cases/                 # 最终案例记录
    │     └─ knowledge/             # 向量知识库
    ├─ docs/                        # 架构、字段和协作约定
    ├─ scripts/
    │  ├─ run_offline_pipeline.py   # 离线流程脚本占位
    │  └─ run_risk_pipeline.py      # Query 风险流程脚本占位
    ├─ src/
    │  ├─ domain/                   # 全项目共享字段
    │  ├─ offline/                  # 案例离线构建
    │  ├─ query/                    # Query 输入、分类和增强
    │  ├─ risk/                     # Query 多层次风险检测
    │  └─ application/              # 案例管理和向量检索入口
    └─ tests/                       # 按模块存放后续测试

## 两条独立链路

离线案例链路：

    案例文件
      -> 文件读取
      -> 标准化案例
      -> 独立分类模型识别案例风险类型
      -> 大模型独立复核
      -> 双重结果融合
      -> 案例增强
      -> Embedding
      -> 最终案例和向量知识库

Query 风险链路：

    Query 文本或文件
      -> 文件读取（仅文件输入）
      -> Query 分类
      -> 增加分类词条
      -> 多层次风险判断
      -> 风险概率和风险标签

案例风险标签不得由 Query 风险判断模块生成。两条链路只共享 Domain 字段和风险标签体系。

## 字段文档

- src/domain/file_models.py：文件读取结果
- src/domain/case_models.py：标准化案例、双模型标签结果和最终案例
- src/domain/query_models.py：Query 分类及增强结果
- src/domain/common.py：公共枚举和证据字段
- docs/data_contracts.md：字段含义和团队约定

所有跨模块数据必须使用 Domain 模型。不得在 Offline、Query、Risk 或 Application 中重新定义同义字段。

## 使用 uv

安装最小开发环境：

    uv sync --dev

检查字段模型：

    uv run ruff check src scripts
    uv run mypy src/domain

当前没有业务实现和测试代码，因此两个脚本不能处理真实文件。

## 开发顺序

1. 团队共同确认 docs/data_contracts.md 中的字段。
2. 确认风险标签体系和版本规则。
3. 为 Domain 字段补充契约测试。
4. 各负责人在自己的模块中实现算法。
5. 最后实现 Application、脚本以及未来的 API 或 Web。