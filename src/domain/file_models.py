"""文件读取模块的统一输出字段。

案例文件和 Query 文件都使用 FileExtractionResult，利用 file_purpose 区分用途。
"""

from datetime import datetime

from pydantic import Field

from domain.common import ContractModel, ExtractionStatus, FilePurpose


class PageContent(ContractModel):
    """文件单页的读取结果。"""

    page_number: int = Field(ge=1, description="页码，从 1 开始")
    text: str = Field(description="该页提取出的文本")
    used_ocr: bool = Field(default=False, description="该页是否使用了 OCR")


class ExtractedTable(ContractModel):
    """文件中提取出的一个表格。"""

    page_number: int | None = Field(default=None, ge=1, description="表格所在页码")
    title: str | None = Field(default=None, description="表格标题")
    rows: list[list[str]] = Field(default_factory=list, description="按行保存的单元格文本")


class FileExtractionResult(ContractModel):
    """文件读取完成后交给后续模块的统一结果。"""

    schema_version: str = Field(default="1.0", description="当前字段结构版本")
    document_id: str = Field(description="文件稳定标识，建议根据文件哈希生成")
    file_purpose: FilePurpose = Field(description="文件用途：案例或 Query")
    source_filename: str = Field(description="上传或批量导入时的原始文件名")
    source_uri: str = Field(description="原始文件的项目内相对位置或逻辑 URI")
    media_type: str = Field(description="文件 MIME 类型，例如 application/pdf")
    checksum_sha256: str = Field(description="原始文件的 SHA-256")
    file_size_bytes: int = Field(ge=0, description="原始文件大小")
    full_text: str = Field(description="按阅读顺序合并后的完整文本")
    pages: list[PageContent] = Field(default_factory=list, description="分页文本")
    tables: list[ExtractedTable] = Field(default_factory=list, description="提取出的表格")
    extraction_method: str = Field(description="主要读取方式，例如 text_layer、ocr、docx")
    extraction_status: ExtractionStatus = Field(description="读取成功、部分成功或失败")
    quality_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="读取质量分数，无法计算时为空",
    )
    warnings: list[str] = Field(default_factory=list, description="缺页、乱码等读取警告")
    extracted_at: datetime = Field(description="完成读取的时间，必须包含时区")
    extractor_version: str = Field(description="文件读取模块版本")
    metadata: dict[str, object] = Field(default_factory=dict, description="可选来源信息")