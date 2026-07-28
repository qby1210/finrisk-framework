# 测试目录

后续测试按源码模块放置：

- domain：字段合法性和序列化契约测试；
- extraction：共享文件读取、OCR 解析和坐标偏移测试；
- offline：案例读取、标准化、标签、增强和 Embedding 测试；
- query：Query 文件读取、分类和增强测试；
- risk：多层风险判断和概率融合测试；
- application：案例管理和向量检索联调测试。

当前已实现 extraction 测试；OCR 测试使用假引擎，不下载模型或访问网络。