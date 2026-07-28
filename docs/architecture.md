# 架构边界

## 当前原则

当前项目采用字段契约优先。Domain 只描述模块之间传递什么数据，不描述数据如何产生。

依赖方向：

    scripts
       |
       v
    application
       |
       +----------+----------+
       v          v          v
    offline     query       risk
                 |          /
                 |         /
         +------ domain ----+

所有模块都可以依赖 Domain。Domain 不依赖其他业务模块。


## 共享文件读取

extraction 是 Offline 和 Query 共同依赖的基础模块，负责 PDF、图片、文本和 DOCX 读取。它只能依赖 Domain 和第三方文件解析库，不能依赖 Offline、Query、Risk 或 Application。

Offline 和 Query 入口只设置 file_purpose、source_uri 和业务元数据，不复制文件解析逻辑。
## 离线案例链路

Offline 负责：

- 读取案例文件；
- 提取和标准化案例基础事实；
- 使用独立训练的分类模型判断案例风险类型；
- 使用大模型独立复核风险类型；
- 融合两份结果并标记分歧；
- 生成检索增强文本；
- 分块、Embedding 并写入知识库；
- 生成最终案例记录。

Offline 禁止调用 Risk 中的 Query 风险判断逻辑给案例打标签。

## Query 风险链路

Query 负责输入处理、Query 分类和词条增强。分类结果只是增强信息，不决定风险检测路由，也不查询知识库。

Risk 负责多层次判断、风险概率、风险标签和解释。Risk 可以通过 Application 检索已构建的案例知识库，但不能修改案例标签。

## Application 边界

Application 未来只组织以下后端用例：

- 录入、查询和删除案例；
- 查询向量知识库；
- 连接 Offline、Query 和 Risk 流程。

当前 Application 文件仅为占位，不定义接口。

## 数据目录

raw 保存原始输入，禁止流程覆盖。

interim 保存可重建的中间产物。

processed/cases 保存符合 FinalCaseRecord 的最终记录。

processed/knowledge 保存向量和索引产物，不与最终案例 JSON 混放。