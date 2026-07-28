# 团队协作约定

## 文件负责人

Offline 负责人主要修改：

    src/offline/
    scripts/run_offline_pipeline.py
    tests/offline/

负责消费统一文件读取结果，并实现案例标准化、独立分类模型、大模型复核、标签融合、增强和 Embedding。

共享文件读取负责人主要修改：

    src/extraction/
    src/domain/file_models.py
    configs/extraction.example.yaml
    tests/extraction/

负责 PDF、图片、TXT、DOCX、RapidOCR、坐标和文本偏移。Offline 与 Query 负责人不得复制格式解析代码。
风险负责人主要修改：

    src/query/
    src/risk/
    scripts/run_risk_pipeline.py
    tests/query/
    tests/risk/

负责 Query 文件输入、分类增强、多层次风险判断、概率和风险标签。

项目集成人主要修改：

    src/domain/
    src/application/
    configs/
    docs/
    tests/domain/
    tests/application/

负责共享字段、案例管理边界、向量检索边界和跨模块联调。

## 共享字段变更

以下文件属于共享契约，不能由单个模块静默修改：

- src/domain/common.py
- src/domain/file_models.py
- src/domain/case_models.py
- src/domain/query_models.py
- docs/data_contracts.md

修改字段前必须说明：

1. 为什么修改；
2. 哪些模块受到影响；
3. 历史中间数据或最终案例是否需要重建；
4. 模型训练数据是否需要更新；
5. 字段结构版本是否需要升级。

代码和字段文档必须在同一次提交中更新。

## 实现约定

- 不在脚本中实现算法。
- 不在 Application 中直接写模型推理代码。
- 不在各模块重复创建相同含义的数据类。
- 原始文本和增强文本必须使用不同字段。
- 所有模型输出记录模型版本。
- 所有风险标签记录标签体系版本和原文证据。
- 配置文件不提交密钥、真实凭据或本机绝对路径。

## 建议分支

    feature/file-extraction
    feature/offline-case-labeling
    feature/offline-embedding
    feature/query-classification
    feature/risk-detection
    feature/application-services

每次提交尽量只修改一个模块。涉及 Domain 的提交应先由其他模块负责人确认。