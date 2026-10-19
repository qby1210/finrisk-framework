# 保险处罚文书增量采集

正式入口为 `scripts/update_cases_from_web.py`。采集金监总局 4113、4114、4115 栏目，将汇总公示表拆成单案，筛选保险主体，再复用 Web 上传的统一入库链。

```powershell
python scripts/update_cases_from_web.py --dry-run --max-pages 1
python scripts/update_cases_from_web.py --limit 5
python scripts/update_cases_from_web.py --crawl-mode full --max-pages 10
```

采集缓存自动建立在 `data/raw/cases/crawl/`，包括原文 txt、`index.jsonl`、`state.json`、`ingested.jsonl` 和失败记录。它们属于本地增量运行数据，不随源码分发。已见文书、已入库正文 SHA1 和案例 ID 分别去重；没有新案时不调用大模型。

新增案例沿用 `CaseManagementService.ingest_file`，保留统一字段、原文位置和失败回滚。入库后运行 `python scripts/build_competition_index.py --qwen` 更新向量索引。默认请求间隔为 1.5 秒。
