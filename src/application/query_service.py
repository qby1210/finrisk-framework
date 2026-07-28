"""文件/文本 Query 的应用层处理入口。"""

from collections.abc import Mapping
from pathlib import Path

from domain.common import FilePurpose, QueryInputType
from domain.file_models import FileExtractionResult
from domain.query_models import EnhancedQuery
from extraction import FileExtractor
from query.classification import ClassifierStatus, QuerySceneClassifier
from query.enhancement import enhance_query

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRAINING_DIR = PROJECT_ROOT / "data" / "interim" / "train_data"


class QueryProcessingService:
    """组织文件抽取、文件级场景分类和逐句增强。"""

    def __init__(
        self,
        *,
        training_dir: str | Path = DEFAULT_TRAINING_DIR,
        extractor: FileExtractor | None = None,
        min_samples_per_label: int = 5,
    ) -> None:
        """创建服务并加载人工标注数据。"""

        self.extractor = extractor or FileExtractor()
        self.classifier = QuerySceneClassifier(
            training_dir,
            min_samples_per_label=min_samples_per_label,
        )

    @property
    def classifier_status(self) -> ClassifierStatus:
        """返回当前规则/模型分类器状态。"""

        return self.classifier.status

    def reload_classifier(self) -> ClassifierStatus:
        """人工标注数据更新后重新训练分类器。"""

        return self.classifier.reload()

    def process_text(
        self,
        text: str,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> EnhancedQuery:
        """分类并逐句增强文字输入。"""

        return enhance_query(
            text,
            self.classifier,
            input_type=QueryInputType.TEXT,
            metadata=metadata,
        )

    def process_file(
        self,
        file_path: str | Path,
        *,
        source_uri: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> EnhancedQuery:
        """读取文件后，对完整抽取文本进行一次分类和逐句增强。"""

        extraction = self.extractor.extract(
            file_path,
            FilePurpose.QUERY,
            source_uri=source_uri,
            metadata=metadata,
        )
        return self.process_extraction(extraction, metadata=metadata)

    def process_extraction(
        self,
        extraction: FileExtractionResult,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> EnhancedQuery:
        """消费已有 FileExtractionResult，不再重复解析原始文件。"""

        if not extraction.full_text.strip():
            raise ValueError("文件未抽取到可处理文字")

        output_metadata: dict[str, object] = dict(metadata or {})
        output_metadata.update(
            {
                "source_uri": extraction.source_uri,
                "media_type": extraction.media_type,
                "extraction_status": extraction.extraction_status.value,
                "extraction_method": extraction.extraction_method.value,
                "extraction_quality_score": extraction.quality_score,
                "extraction_warnings": extraction.warnings,
                "page_count": extraction.page_count,
                "ocr_page_count": extraction.ocr_page_count,
            }
        )
        return enhance_query(
            extraction.full_text,
            self.classifier,
            input_type=QueryInputType.FILE,
            source_document_id=extraction.document_id,
            source_filename=extraction.source_filename,
            metadata=output_metadata,
        )
