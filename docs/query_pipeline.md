# Query 六分类增强与 Risk 输入契约

## 目标

Query 模块只负责读取输入、判断整份材料的使用场景、切分句子并保留原文定位。
它不生成风险标签，也不读取案例库。Risk 模块只消费逐句四字段输入，不需要再次解析
PDF、图片、DOCX 或文本。

## 六类场景

| 编码 | 含义 |
| --- | --- |
| `ST1_poster_sms_social` | 海报、短信、朋友圈短文案 |
| `ST2_live_short_video` | 直播、短视频、口播话术 |
| `ST3_product_intro_detail` | 产品介绍、产品详情页 |
| `ST4_meeting_material` | 产品说明会、客户答谢会材料 |
| `ST5_training_telemarketing_callback` | 培训、电销、回访流程话术 |
| `ST6_penalty_backend_fact` | 监管处罚文书、后台业务事实 |

`scene` 只表达材料场景；风险类别仍由 Risk 模块判断。

## 分类策略

1. 合并文件读取器得到的全文，整份文件只分类一次。
2. 规则分类器同时检查关键词、结构和格式，生成六类候选分数。
3. 第一名达到高分阈值、领先第二名且归一化置信度足够时，直接返回规则结果。
4. 无法分类、多类冲突或置信度不足时，调用统一 LLM 接口复核。
5. LLM 仍只能从上述六类中选择，不得增加运行时兜底类别。

当前高置信度门槛为：规则分数至少 `6.0`、领先第二名至少 `2.5`、
归一化置信度至少 `0.65`。门槛集中在 `src/query/classification.py`，后续可用真实
Query 验证集校准。

统一 LLM 抽象位于 `src/llm`。当前默认使用 DeepSeek 的 OpenAI 兼容接口和
`deepseek-v4-flash`；后续本地模型只需实现同一个 `LLMClient.complete_json`
协议。DeepSeek V4 模型名见[官方更新日志](https://api-docs.deepseek.com/updates/)，
结构化输出方式见[JSON Output 文档](https://api-docs.deepseek.com/guides/json_mode/)。

## 环境变量

不要把密钥写入源码或提交到 Git。启动服务前配置：

```powershell
$env:DEEPSEEK_API_KEY="<your-new-key>"
$env:FINRISK_LLM_BASE_URL="https://api.deepseek.com"
$env:FINRISK_LLM_MODEL="deepseek-v4-flash"
```

也可以用 `FINRISK_LLM_API_KEY` 代替 `DEEPSEEK_API_KEY`。切换兼容服务时只需修改
`FINRISK_LLM_BASE_URL` 和 `FINRISK_LLM_MODEL`。

## Risk 唯一输入

`QueryProcessingResult.sentences` 是交给 Risk 的业务输入，每项严格只有四个字段：

```json
{
  "query_id": "query_a1b2c3d4e5f6",
  "sentence_id": "query_a1b2c3d4e5f6_s0001",
  "scene": "ST1_poster_sms_social",
  "text": "夏日专享理财活动火热开启。"
}
```

字段含义：

- `query_id`：一次 Query 请求内稳定的文档标识；
- `sentence_id`：稳定句子标识，也是 Risk 结果回写和前端联表键；
- `scene`：整份文件统一的六分类场景；
- `text`：Risk 实际判断的原句。

Risk 的风险概率、风险标签、相似案例和判断依据应按 `query_id + sentence_id` 关联，
不要直接修改上述四字段契约。

## 原文定位

`QueryProcessingResult.source_mappings` 与 `sentences` 顺序和 ID 一一对应，但不传给
Risk 模型。每条定位记录包含：

- `query_id`、`sentence_id`；
- `input_type`、`document_id`、`filename`；
- `document_start_offset`、`document_end_offset`；
- `regions[]`：`page_number`、`block_id`、`word_ids`、`polygon`、
  `document_start_offset`、`document_end_offset`、`text`。

网页后续拿 Risk 返回的 `sentence_id` 查找 `source_mappings`，即可定位原文。PDF/图片
优先使用页码和多边形高亮；TXT、Markdown、DOCX 可使用全文字符偏移定位。OCR 句子跨越
多个文本块时，一条映射会包含多个 region。

## API

### 分类器状态

`GET /api/query/classifier`

返回分类体系版本、分类器版本、规则版本、LLM 是否配置和当前模型名；不会返回密钥。

### 文字输入

`POST /api/query/analyze/text`

```json
{
  "text": "现在下单即可领取积分好礼，点击链接了解详情。"
}
```

### 文件输入

`POST /api/query/analyze/file`

使用 `multipart/form-data` 的 `file` 字段上传文件，最大 25 MB。支持 PDF、常见图片、
TXT、Markdown 和 DOCX。

如果规则结果置信度不足且没有配置 LLM，接口返回 HTTP 503，不会假装给出一个分类；
LLM 服务异常则返回 HTTP 502。

## 启动与验证

```powershell
uv sync --dev
uv run python scripts/run_web.py
```

网站地址：`http://127.0.0.1:8000`；接口文档：`http://127.0.0.1:8000/docs`。

```powershell
uv run ruff check src tests scripts
uv run mypy src
uv run pytest -q
```
