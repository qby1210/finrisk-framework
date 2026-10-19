# Competition500 冻结结果

`evaluation.json`供Web效果页和下载使用，比较同一200条冻结Query上的优化前后表现。`baseline_20261019.json`是前版本完整指标快照，`selection_development.json`记录仅依据开发集冻结默认策略的过程。

`predictions_test200.jsonl`保留逐条预测、耗时和未复核数；`submission.jsonl`为比赛输出格式。两个中文CSV分别给出总体指标与27类FP/FN对照。`dataset_hashes.json`绑定本次输入及参考文件，`dataset_audit.json`和`verification.json`记录数据隔离与最终功能验收。

测试范围为500案例闭集，Query和参考为模型银标。100条validation为开发子集，200条test与开发集源文书隔离。没有为本轮修复改写测试答案。独立检索表沿用前轮相同200Query对照，排序代码未改动；当前风险与长文本结果来自本轮真实API回归。

本轮F1提升主要来自FP减少，FN仍有增加；具体数字和耗时见evaluation.json及docs/competition_upgrade_20261019.md。
