# 测试说明

测试按业务模块组织：

- `api`：首页、Query 与案例只读接口；
- `application`：Query 文件用例；
- `extraction`：PDF/图片/TXT/DOCX、OCR 假引擎和偏移；
- `offline`：真实案例 PDF 的不入库三表构建；
- `query`：六类分类、切句、社交平台项目符号和原文映射；
- `risk`：真实词库、五档阈值、检索门控和真实小红书本地冒烟；
- `storage`：同一案例库写入、停用和 BM25 检索。

```powershell
uv run pytest -q
```

测试默认不访问外网、不写正式案例库。真实 PDF 测试只生成内存产物；真实小红书样本显式
构造 `llm_client=None`。依赖交付数据或用户样本的测试在文件缺失时应跳过。
