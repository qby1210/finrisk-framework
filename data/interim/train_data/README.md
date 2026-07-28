# Query 场景与风险人工标注数据

这里保存已经完成文件读取和文本清洗的 Query 标注数据。标注单位是“一整个 Query
文件或一整段文字”，不是切分后的单句。文件级 `scene` 会统一附加到该 Query 的每个
句子上，`risk_label` 留给后续 Risk 模块训练或评估。

## 使用方法

1. 参考 `query_scene_train.example.jsonl`。
2. 新建 `query_scene_train.jsonl`，每行填写一个 JSON 对象。
3. 三个场景都至少有 5 条时，服务启动会训练字符级 TF-IDF 场景分类模型；数据不足时
   自动使用规则分类。
4. 修改训练数据后重启服务，或调用 `POST /api/query/classifier/reload`。

文件名包含 `.example.` 的 JSONL 只是格式模板，不会进入模型训练。

## 固定四字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| sample_id | string | 不重复的训练样本标识 |
| text | string | 已经抽取、清洗并合并好的完整文本 |
| scene | string | Query 使用场景，供当前场景分类模型训练 |
| risk_label | string | 整段 Query 的风险标签，供后续 Risk 模块使用 |

不接受 `source_channel`、`notes` 或其他额外字段。

`scene` 允许的训练值：

- `marketing_content`：面向批量或不特定客户的单向营销宣传；
- `formal_document`：规定权利义务、流程、审批、通知或留痕的正式业务文件；
- `customer_communication`：面向具体客户的一对一、问答式沟通。

`unknown_or_mixed` 只用于运行时低置信回退，不作为训练场景。无法可靠判断场景的样本
应先留待人工复核，不要强行放进三类训练集。

`risk_label` 应使用团队最终确定的稳定风险代码。当前场景分类器不会读取
`risk_label`，避免风险结果反向影响材料场景分类。

## 数据切分注意事项

- 同一模板的改写版本必须放在同一个训练、验证或测试分组，避免准确率虚高；
- 去除完全重复和高度相似文本；
- `scene` 根据材料使用场景标注，`risk_label` 根据风险事实单独标注；
- 金融数据中的姓名、手机号、证件号和账号应先脱敏，但保留对话或文件结构。
