# 处罚文书采集器（penalty_crawler）

从官方监管网站自动采集行政处罚文书，产出与知识库增量管线兼容的纯文本 txt。

**一键更新（推荐入口）**：`scripts/update_kb_from_web.py` = 本采集器 + 保险筛选 +
`kb_ingest` 入库门串成的完整管线，按文书 sha1 去重，可重复运行：

```powershell
python scripts/update_kb_from_web.py                    # 日常：增量采集 + 入库新保险案
python scripts/update_kb_from_web.py --dry-run          # 只采集汇报，不调模型
python scripts/update_kb_from_web.py --rebuild          # 入库后顺带重建主库（默认关）
python scripts/update_kb_from_web.py --crawl-mode full  # 首次全量回溯
```


## 数据源（均已实测打通）

| 源 | 栏目 | 量级 | 单条形态 |
|---|---|---|---|
| 金监总局 nfra.gov.cn | 4113 总局机关 | ~660 | 批量公示列表（一案一行摘要，无文号） |
| 金监总局 nfra.gov.cn | 4114 省监管局 | ~32,800 | 汇总列表 + 单案信息公开表 |
| 金监总局 nfra.gov.cn | 4115 监管分局 | ~41,600 | 单案信息公开表（有文号，主力） |
| 人民银行 pbc.gov.cn | 行政处罚公示（银罚决字） | ~53 批 | 批次汇总表（银行/支付/征信为主） |

## 用法

```powershell
# 日常增量（默认）：撞到一整页已见文书即停，适合每周定时跑
python -m scripts.penalty_crawler.run_crawl --source all --mode incremental

# 首次全量回溯（约 7.5 万条，按 1.5s/请求需数小时，可断点续跑）
python -m scripts.penalty_crawler.run_crawl --source all --mode full

# 只抓指定 NFRA 栏目 / 冒烟测试
python -m scripts.penalty_crawler.run_crawl --source nfra --columns 4115 --max-pages 2
```

断点续跑：状态存于 `outputs/penalty_crawl/state.json`，中断后原命令重跑自动跳过已抓文书。

## 产出

```
outputs/penalty_crawl/
  nfra/<itemId>/<docId>.txt   # 金监总局文书纯文本
  pbc/<slug>.txt              # 人民银行批次纯文本
  index.jsonl                 # 每条一行元数据：标题/发布日期/文号/source_url/sha1/txt_path
  state.json                  # 已见文书键（增量去重）
  errors.jsonl                # 抓取失败记录（不中断整体）
```

## 入库

采集目录是 staging，确认质量后经现有增量管线入库（自动分配 U 前缀编号）：

```powershell
python scripts/add_penalty_case.py --file outputs/penalty_crawl/nfra/4115/<docId>.txt --no-rebuild
# 批量确认后再统一重建（去掉 --no-rebuild 即逐份重建，较慢）
```

## 定时更新

Windows 任务计划程序建一个每周任务，命令：

```powershell
python -m scripts.penalty_crawler.run_crawl --source all --mode incremental
```

处罚文书只增不改，增量模式每次只抓新增部分。

## 已知事项

1. **NFRA 列表 JSON 的 pageSize 只能是 18**（CDN 预生成静态文件，自定义值 404）。
2. **CDN 只预生成前 3 页**：第 4 页起自动回退动态接口
   （`GET /cbircweb/DocInfo/SelectDocByItemIdAndChild?itemId=..&pageIndex=N`），已实现无缝回退。
3. **编码不统一**：各栏目/站点 JSON 与 HTML 混用 UTF-8 / GBK，`common.decode_text` 自动探测。
4. **汇总公示表自动拆行**：金监总局现行公示口径以摘要表为主（一案一行），
   `table_split.py` 从 HTML 表格按行拆成单案 txt，字段标签排版对齐下游
   parser.py（事实/处罚字段标签与值分行）与 field_extraction.py（当事人同行冒号）。
   实测 108 个网页文档拆出 204 条单案，其中保险相关约一半，入库门可直接给 formal。
5. **人民银行表格字段名与 KB parser 不完全匹配**：PBC 用"违法行为类型"，parser 认
   "主要违法违规事实"，入库时这类文书可能落 review_queue，属预期行为，必要时再扩 parser。
6. **官网摘要不等于决定书全文**：现行公开表只有 当事人/行为一句话/处罚/机关（部分有文号），
   与比赛原始 9,999 份全文决定书的信息密度不同；重要案件如需全文可走商业库回填。
7. 抓取礼仪：默认 1.5s/请求、3 次指数退避重试，勿调太低。
