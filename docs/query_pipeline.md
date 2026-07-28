# Query 分类增强与风险查询网站

## 数据流

    文字输入 ───────────────────────────────┐
                                           v
    文件输入 -> FileExtractionResult -> 合并完整文本
                                           |
                                           v
                          文件级 Query 场景分类
                                           |
                                           v
                             按句末标点和换行切句
                                           |
                                           v
                      每句继承统一分类、词条和全文偏移
                                           |
                                           v
                         EnhancedQuery.sentences -> Risk

Risk 后续只需要读取 `EnhancedQuery.sentences`，不需要重新读取 PDF、图片、TXT 或
DOCX。`original_text` 仍保留在结果中，用于审计和根据句子偏移追溯原文。

## 场景分类

分类只描述 Query 的使用场景，不表示风险类型：

- `marketing_content`：营销宣传材料；
- `formal_document`：正式业务文件；
- `customer_communication`：客户沟通话术；
- `unknown_or_mixed`：低置信度或混合内容的运行时回退类别。

没有人工标注数据时使用可解释规则。`data/interim/train_data` 中三个主要类别各至少有
5 条数据后，服务会训练字符级 TF-IDF + Logistic Regression，并按 65% 模型概率和
35% 规则概率进行融合。最低 5 条仅用于验证流程，真实模型应继续增加多来源标注数据。

## 逐句输出

每个 `EnhancedQuerySentence` 包含：

- `sentence_id` 和从 1 开始的 `sentence_index`；
- 原句 `text`；
- 原句在抽取全文中的 `start_offset` 和 `end_offset`；
- 继承的文件级 `category`；
- 不包含风险结论的 `augmentation_terms`；
- 可以直接交给 Risk 的 `enhanced_text`。

Risk 后续可以在每个句子对象上追加或关联：

- 风险概率；
- 风险标签；
- 判断依据；
- 相似案例和相似度；
- 原文证据位置。

## 启动网站

安装依赖：

    uv sync --dev

启动 FastAPI 和网站：

    uv run python scripts/run_web.py

浏览器访问：

    http://127.0.0.1:8000

接口文档：

    http://127.0.0.1:8000/docs

## API

### 文字输入

`POST /api/query/analyze/text`

请求：

```json
{
  "text": "客户：这款产品可以赎回吗？顾问：您好，我帮您查询。",
  "metadata": {
    "source_channel": "chat"
  }
}
```

### 文件输入

`POST /api/query/analyze/file`

使用 `multipart/form-data` 的 `file` 字段上传文件，最大 25 MB。支持格式与共享文件
抽取模块一致。

### 分类器状态与重新加载

- `GET /api/query/classifier`
- `POST /api/query/classifier/reload`

人工标注数据更新后可以重新加载，不必修改代码。
