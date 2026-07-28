# FinRisk 后端框架

这是金融风险识别比赛项目的后端框架。当前已实现案例和 Query 共用的文件读取模块；API、Web、风险模型、案例标签模型和向量数据库仍未实现。

## 当前确认范围

只在 src/domain 中定义以下共享字段：

1. 文件读取输出：FileExtractionResult
2. 标准化案例：NormalizedCase
3. 最终案例记录：FinalCaseRecord
4. Query 分类增强结果：EnhancedQuery

src/extraction 已实现文件读取；Offline 和 Query 只提供对应用途的薄入口。其他业务模块仍只有中文用途说明。

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
    │  ├─ extraction/               # 文件读取处理
    │  ├─ offline/                  # 案例离线构建
    │  ├─ query/                    # Query 输入、分类和增强
    │  ├─ risk/                     # Query 多层次风险检测
    │  └─ application/              # 案例管理和向量检索入口
    └─ tests/                       # 按模块存放后续测试

## 文件读取

共享入口位于 src/extraction，当前支持：

- PDF：使用 PyMuPDF 优先读取原生文本层，低质量页面自动转图片并调用 RapidOCR；
- PNG、JPEG、BMP、TIFF、WebP：使用 RapidOCR；
- TXT、Markdown：按 UTF-8 或 GB18030 读取；
- DOCX：读取段落和表格，因格式限制不提供稳定物理页码。

RapidOCR 按官方文档使用 rapidocr 和 onnxruntime。默认延迟创建 OCR 引擎，只有实际需要 OCR 时才加载模型。

读取结果保存页级文本、行级文本块、字词、OCR 置信度、归一化四边形坐标以及页内和全文字符偏移，可用于后续网页原文风险位置展示。
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

    uv run ruff check src tests scripts
    uv run mypy src
    uv run pytest

当前可以直接调用 FileExtractor、extract_case_file 或 extract_query_file 读取文件；流程脚本仍未实现。

## 开发顺序

1. 团队共同确认 docs/data_contracts.md 中的字段。
2. 确认风险标签体系和版本规则。
3. 为 Domain 字段补充契约测试。
4. 各负责人在自己的模块中实现算法。
5. 最后实现 Application、脚本以及未来的 API 或 Web。