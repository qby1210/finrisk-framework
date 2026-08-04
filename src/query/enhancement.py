"""Query 切句、Risk 四字段输入和原文映射。"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from domain.common import QueryInputType
from domain.file_models import FileExtractionResult, PageContent, TextBlock
from domain.query_models import (
    QueryProcessingResult,
    QuerySourceRegion,
    RiskQuerySentence,
    SentenceSourceMapping,
)
from query.classification import QueryClassificationContext, QuerySceneClassifier

_SENTENCE_BOUNDARY = re.compile(
    r"(?:[。！？!?；;]+[”’」』】》）)]*)"
    r"|(?:\.(?=\s+|$))"
    r"|(?:\r?\n[ \t]*\r?\n+)"
    r"|(?:\r?\n(?=[ \t]*(?:[·•●▪]|[-*][ \t]|\d+[.、])))"
)


@dataclass(frozen=True, slots=True)
class SentenceSpan:
    """从完整 Query 中切分出、保留全文偏移的一句话。"""

    text: str
    start_offset: int
    end_offset: int


def split_sentences(text: str) -> list[SentenceSpan]:
    """按句末标点、空行和项目符号切句，并保留可逆全文偏移。"""

    if not text.strip():
        raise ValueError("Query 文本不能为空")

    sentences: list[SentenceSpan] = []
    segment_start = 0
    for match in _SENTENCE_BOUNDARY.finditer(text):
        _append_sentence(sentences, text, segment_start, match.end())
        segment_start = match.end()
    _append_sentence(sentences, text, segment_start, len(text))
    if not sentences:
        raise ValueError("Query 文本未包含可处理句子")
    return sentences


async def prepare_query(
    text: str,
    classifier: QuerySceneClassifier,
    *,
    input_type: QueryInputType,
    extraction: FileExtractionResult | None = None,
    metadata: Mapping[str, object] | None = None,
) -> QueryProcessingResult:
    """整份材料分类后，生成逐句 Risk 输入和原文定位表。"""

    classification_context = (
        QueryClassificationContext(
            media_type=extraction.media_type,
            page_count=extraction.page_count,
        )
        if extraction
        else None
    )
    classification = await classifier.classify(text, classification_context)
    query_id = _query_id(text, extraction.document_id if extraction else None)
    spans = split_sentences(text)
    sentences: list[RiskQuerySentence] = []
    mappings: list[SentenceSourceMapping] = []

    for index, span in enumerate(spans, start=1):
        sentence_id = f"{query_id}_s{index:04d}"
        sentences.append(
            RiskQuerySentence(
                query_id=query_id,
                sentence_id=sentence_id,
                scene=classification.scene,
                text=span.text,
            )
        )
        mappings.append(
            _build_source_mapping(
                query_id=query_id,
                sentence_id=sentence_id,
                input_type=input_type,
                span=span,
                extraction=extraction,
            )
        )

    return QueryProcessingResult(
        query_id=query_id,
        input_type=input_type,
        source_text=text,
        source_document_id=extraction.document_id if extraction else None,
        source_filename=extraction.source_filename if extraction else None,
        classification=classification,
        sentences=sentences,
        source_mappings=mappings,
        created_at=datetime.now(UTC),
        metadata=dict(metadata or {}),
    )


def _append_sentence(
    sentences: list[SentenceSpan],
    full_text: str,
    raw_start: int,
    raw_end: int,
) -> None:
    raw_segment = full_text[raw_start:raw_end]
    if not raw_segment.strip():
        return
    leading_space_count = len(raw_segment) - len(raw_segment.lstrip())
    trailing_space_count = len(raw_segment) - len(raw_segment.rstrip())
    start_offset = raw_start + leading_space_count
    end_offset = raw_end - trailing_space_count
    sentences.append(
        SentenceSpan(
            text=full_text[start_offset:end_offset],
            start_offset=start_offset,
            end_offset=end_offset,
        )
    )


def _build_source_mapping(
    *,
    query_id: str,
    sentence_id: str,
    input_type: QueryInputType,
    span: SentenceSpan,
    extraction: FileExtractionResult | None,
) -> SentenceSourceMapping:
    regions: list[QuerySourceRegion] = []
    if extraction:
        for page in extraction.pages:
            for block in page.blocks:
                if not _overlaps(span, block):
                    continue
                overlap_start = max(span.start_offset, block.document_start_offset)
                overlap_end = min(span.end_offset, block.document_end_offset)
                regions.append(
                    QuerySourceRegion(
                        page_number=page.page_number,
                        block_id=block.block_id,
                        word_ids=_overlapping_word_ids(page, overlap_start, overlap_end),
                        text=extraction.full_text[overlap_start:overlap_end],
                        document_start_offset=overlap_start,
                        document_end_offset=overlap_end,
                        polygon=block.polygon,
                    )
                )

    return SentenceSourceMapping(
        query_id=query_id,
        sentence_id=sentence_id,
        input_type=input_type,
        source_document_id=extraction.document_id if extraction else None,
        source_filename=extraction.source_filename if extraction else None,
        document_start_offset=span.start_offset,
        document_end_offset=span.end_offset,
        regions=regions,
    )


def _overlaps(span: SentenceSpan, block: TextBlock) -> bool:
    return (
        block.document_start_offset < span.end_offset
        and block.document_end_offset > span.start_offset
    )


def _overlapping_word_ids(
    page: PageContent,
    start_offset: int,
    end_offset: int,
) -> list[str]:
    return [
        word.word_id
        for word in page.words
        if word.document_start_offset is not None
        and word.document_end_offset is not None
        and word.document_start_offset < end_offset
        and word.document_end_offset > start_offset
    ]


def _query_id(text: str, source_document_id: str | None) -> str:
    identity_source = f"{source_document_id or ''}\0{text}".encode()
    return f"query_{sha256(identity_source).hexdigest()[:20]}"


__all__ = ["SentenceSpan", "prepare_query", "split_sentences"]
