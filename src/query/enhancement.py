"""Query 文件级分类、句子切分和逐句增强。"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from domain.common import QueryInputType
from domain.query_models import EnhancedQuery, EnhancedQuerySentence, QueryClassification
from query.classification import QuerySceneClassifier

_SENTENCE_BOUNDARY = re.compile(r"(?:[。！？!?；;]+[”’」』】》）)]*)|(?:\.(?=\s+|$))|(?:\r?\n+)")


@dataclass(frozen=True, slots=True)
class SentenceSpan:
    """从完整 Query 中切分出、保留原文偏移的一句话。"""

    text: str
    start_offset: int
    end_offset: int


def split_sentences(text: str) -> list[SentenceSpan]:
    """按中文标点、英文句末标点和换行切句，并保留全文偏移。"""

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


def enhance_query(
    text: str,
    classifier: QuerySceneClassifier,
    *,
    input_type: QueryInputType,
    source_document_id: str | None = None,
    source_filename: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> EnhancedQuery:
    """整体分类后，把同一文件级分类附到每个切分句子上。"""

    classification = classifier.classify(text, metadata)
    query_id = _query_id(text, source_document_id)
    sentence_models = [
        _enhance_sentence(query_id, index, span, classification)
        for index, span in enumerate(split_sentences(text), start=1)
    ]

    return EnhancedQuery(
        query_id=query_id,
        input_type=input_type,
        original_text=text,
        source_document_id=source_document_id,
        source_filename=source_filename,
        classification=classification,
        sentences=sentence_models,
        enhanced_text="\n\n".join(sentence.enhanced_text for sentence in sentence_models),
        created_at=datetime.now(UTC),
        metadata=dict(metadata or {}),
    )


def _append_sentence(
    sentences: list[SentenceSpan],
    full_text: str,
    raw_start: int,
    raw_end: int,
) -> None:
    """去除句子两端空白，同时把偏移调整到真实原文范围。"""

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


def _enhance_sentence(
    query_id: str,
    sentence_index: int,
    span: SentenceSpan,
    classification: QueryClassification,
) -> EnhancedQuerySentence:
    """生成一条不注入风险判断的场景增强句子。"""

    selected_category = classification.selected_category
    header = f"[QUERY_SCENE={selected_category.category_code.value}]"
    if classification.augmentation_terms:
        context = "；".join(classification.augmentation_terms)
        enhanced_text = f"{header}\n[SCENE_CONTEXT={context}]\n{span.text}"
    else:
        enhanced_text = f"{header}\n{span.text}"

    return EnhancedQuerySentence(
        sentence_id=f"{query_id}-s{sentence_index:04d}",
        sentence_index=sentence_index,
        text=span.text,
        start_offset=span.start_offset,
        end_offset=span.end_offset,
        category=selected_category,
        augmentation_terms=list(classification.augmentation_terms),
        enhanced_text=enhanced_text,
    )


def _query_id(text: str, source_document_id: str | None) -> str:
    """根据文件身份和抽取文本生成可复现的 Query 标识。"""

    identity_source = f"{source_document_id or ''}\0{text}".encode()
    return f"query_{sha256(identity_source).hexdigest()[:20]}"
