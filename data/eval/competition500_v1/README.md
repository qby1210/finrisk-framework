# Competition500 数据集

本目录随项目上传GitHub。案例来自500份不同的公开处罚文书，Query由DeepSeek改写，场景/三态/27标签与相关性由Qwen辅助标注，口径为模型银标。

| 文件 | 数量 | 用途 |
|---|---:|---|
| cases.jsonl | 500 | 固定候选案例池与来源SHA |
| development.jsonl | 400 | 本地候选模型拟合、示例与开发调试 |
| validation.jsonl | 100 | 开发核对输入，是development前100条的显式子集 |
| test.jsonl | 200 | 与开发源文书分离的冻结效果测试输入 |
| reference/labels.jsonl | 600 | 六场景、三态、27标签参考；评分器读取 |
| reference/qrels_development.jsonl | 60×500 | 开发相关性参考与原文证据 |
| reference/qrels_test.jsonl | 200×500 | 测试相关性参考与原文证据 |
| reference/generation_plan.jsonl | 600 | 种子案例及制作审计 |
| manifest.json | — | 来源、版本和SHA256 |

100条validation用于开发核对，包含在400条轻量模型拟合数据中；独立效果以200条test为准。开发Query来自300份文书，测试来自其余200份，源文书无交集。model_inputs.jsonl是开发与测试合并的制作记录。

本轮修复没有改写冻结测试答案。预测、误判漏判和前后对照在reports/competition500；原始PDF、API密钥、全量索引及调用日志留在本地。

验证数据完整性：`python scripts/audit_competition_dataset.py`。重跑效果：设置FINRISK_BENCH_RUN后运行`python scripts/benchmark_competition500.py test --mode deepseek_adaptive`。
