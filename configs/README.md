# 配置说明

运行配置统一由 `src/settings.py` 和根目录 `.env` 管理；示例见 `.env.example`。不再保留未被
代码加载的 YAML 占位配置，避免出现“文档有配置、运行时不生效”的双重来源。

可覆盖项：

- `FINRISK_CASE_KB_ROOT`：统一案例库根目录；
- `FINRISK_RISK_KEYWORD_PATH`：风险词库 JSON；
- `FINRISK_RAW_CASE_UPLOAD_DIR`：Web 新案例原文件目录；
- `FINRISK_MAX_UPLOAD_SIZE_BYTES`：上传上限；
- `FINRISK_LLM_*` / `DEEPSEEK_API_KEY`：大模型连接参数。

文件抽取默认参数由 `ExtractionConfig` 定义。需要新增可外部调整的参数时，先实现真实加载
和校验，再补示例；不要只添加未使用的配置文件。
