"""面向当前案例库的内存 BM25 索引。"""

from __future__ import annotations

import heapq
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from retrieval.tokenization import chinese_unigram_bigram


@dataclass(frozen=True, slots=True)
class RetrievalDocument:
    """参与检索的案例切片或扩展表达。"""

    unit_id: str
    case_ids: tuple[str, ...]
    text: str
    source: str
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class SparseSearchHit:
    document: RetrievalDocument
    score: float
    rank: int


class SparseRetrievalIndex:
    """倒排表驱动的 BM25，只为包含 Query 词的文档计分。"""

    def __init__(self, documents: Iterable[RetrievalDocument], *, k1: float = 1.5, b: float = 0.75):
        if k1 <= 0 or not 0 <= b <= 1:
            raise ValueError("BM25 参数不合法")
        self.k1 = k1
        self.b = b
        self.documents = tuple(documents)
        self._document_lengths: list[int] = []
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self._build()

    def _build(self) -> None:
        seen_ids: set[str] = set()
        total_length = 0
        for document_index, document in enumerate(self.documents):
            if not document.unit_id or document.unit_id in seen_ids:
                raise ValueError(f"重复或为空的检索单元 ID: {document.unit_id}")
            if not document.case_ids or not document.text.strip():
                raise ValueError(f"检索单元缺少案例或正文: {document.unit_id}")
            if not 0 < document.weight <= 1:
                raise ValueError(f"检索权重不合法: {document.unit_id}")
            seen_ids.add(document.unit_id)
            frequencies = Counter(chinese_unigram_bigram(document.text))
            length = sum(frequencies.values())
            if length == 0:
                raise ValueError(f"检索单元无法分词: {document.unit_id}")
            self._document_lengths.append(length)
            total_length += length
            for token, frequency in frequencies.items():
                self._postings[token].append((document_index, frequency))
        self._average_document_length = (
            total_length / len(self.documents) if self.documents else 0.0
        )

    def search(self, query: str, *, top_k: int = 50) -> tuple[SparseSearchHit, ...]:
        """返回文档级候选；同案例聚合由应用层完成。"""

        if not query.strip():
            raise ValueError("检索文字不能为空")
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        query_terms = tuple(dict.fromkeys(chinese_unigram_bigram(query)))
        scores: dict[int, float] = defaultdict(float)
        document_count = len(self.documents)
        if not document_count:
            return ()

        for term in query_terms:
            postings = self._postings.get(term)
            if not postings:
                continue
            document_frequency = len(postings)
            idf = math.log(
                1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            for document_index, term_frequency in postings:
                length_ratio = (
                    self._document_lengths[document_index] / self._average_document_length
                )
                denominator = term_frequency + self.k1 * (1 - self.b + self.b * length_ratio)
                scores[document_index] += idf * term_frequency * (self.k1 + 1) / denominator

        ranked = heapq.nlargest(
            min(top_k, len(scores)),
            scores.items(),
            key=lambda item: (item[1] * self.documents[item[0]].weight, -item[0]),
        )
        return tuple(
            SparseSearchHit(
                document=self.documents[document_index],
                score=raw_score * self.documents[document_index].weight,
                rank=rank,
            )
            for rank, (document_index, raw_score) in enumerate(ranked, start=1)
        )
