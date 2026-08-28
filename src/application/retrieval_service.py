"""案例 BM25 + 本地向量 + RRF + 轻量重排应用服务。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from threading import RLock

from domain.knowledge_models import CaseSummary, MatchedCase
from retrieval import SparseRetrievalIndex, SparseSearchHit
from retrieval.tokenization import chinese_unigram_bigram
from storage.case_repository import CaseRepository

_RRF_K = 60


@dataclass(slots=True)
class _ChannelAggregate:
    score: float
    best_hit: SparseSearchHit


class CaseRetrievalService:
    """从同一案例库执行双路召回、RRF融合和确定性轻量重排。"""

    def __init__(self, repository: CaseRepository) -> None:
        self.repository = repository
        self._index: SparseRetrievalIndex | None = None
        self._summaries: dict[str, CaseSummary] = {}
        self._indexed_revision = -1
        self._lock = RLock()

    @property
    def ready(self) -> bool:
        return self._index is not None and self._indexed_revision == self.repository.revision

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        risk_tags: set[str] | None = None,
    ) -> list[MatchedCase]:
        if not 1 <= top_k <= 20:
            raise ValueError("top_k 必须在 1 到 20 之间")
        normalized_tags = {tag for tag in (risk_tags or set()) if tag and tag != "其他"}
        index = self._ensure_index()
        recall_size = max(120, top_k * 40)
        bm25 = self._aggregate_cases(
            index.search(query, top_k=recall_size),
            normalized_tags,
        )
        vector = self._aggregate_cases(
            index.vector_search(query, top_k=recall_size),
            normalized_tags,
        )
        bm25_ranks = self._ranks(bm25)
        vector_ranks = self._ranks(vector)
        candidate_ids = set(bm25) | set(vector)
        query_tokens = _meaningful_tokens(query)

        ranked: list[tuple[float, float, str, MatchedCase]] = []
        for case_id in candidate_ids:
            summary = self._summaries[case_id]
            bm25_item = bm25.get(case_id)
            vector_item = vector.get(case_id)
            best_hit = _choose_hit(bm25_item, vector_item)
            bm25_score = _normalize_bm25(bm25_item.score) if bm25_item else 0.0
            vector_score = min(1.0, vector_item.score) if vector_item else 0.0
            rrf_raw = (
                (1 / (_RRF_K + bm25_ranks[case_id])) if case_id in bm25_ranks else 0.0
            ) + (
                (1 / (_RRF_K + vector_ranks[case_id])) if case_id in vector_ranks else 0.0
            )
            rrf_score = min(1.0, rrf_raw / (2 / (_RRF_K + 1)))
            lexical_score = _token_overlap(query_tokens, best_hit.document.text)
            source_score = 1.0 if best_hit.document.source == "case_chunk" else 0.65
            rerank_score = (
                0.28 * rrf_score
                + 0.30 * bm25_score
                + 0.26 * vector_score
                + 0.11 * lexical_score
                + 0.05 * source_score
            )
            if _contains_phrase(query, best_hit.document.text):
                rerank_score += 0.06
            rerank_score = min(1.0, rerank_score)
            matched_tags = sorted(normalized_tags.intersection(summary.risk_tags))
            matched = MatchedCase(
                case_id=case_id,
                case_title=summary.case_title,
                violation_behavior=summary.violation_behavior,
                penalty_content=summary.penalty_content,
                regulator=summary.regulator,
                risk_tags=summary.risk_tags,
                score=round(rerank_score, 6),
                bm25_score=round(bm25_score, 6),
                vector_score=round(vector_score, 6),
                rrf_score=round(rrf_score, 6),
                rerank_score=round(rerank_score, 6),
                matched_risk_tags=matched_tags,
                matched_text=best_hit.document.text,
                matched_source=best_hit.document.source,
                matched_unit_id=best_hit.document.unit_id,
            )
            ranked.append((rerank_score, rrf_score, case_id, matched))

        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [item[3] for item in ranked[:top_k]]

    def rebuild(self) -> None:
        """重建共享倒排表以及BM25/向量统计。"""

        with self._lock:
            self._summaries = self._load_summaries()
            self._index = SparseRetrievalIndex(self.repository.iter_retrieval_documents())
            self._indexed_revision = self.repository.revision

    def _ensure_index(self) -> SparseRetrievalIndex:
        if self._index is not None and self._indexed_revision == self.repository.revision:
            return self._index
        self.rebuild()
        if self._index is None:  # pragma: no cover
            raise RuntimeError("案例索引初始化失败")
        return self._index

    def _load_summaries(self) -> dict[str, CaseSummary]:
        return {item.case_id: item for item in self.repository.summaries()}

    def _aggregate_cases(
        self,
        hits: tuple[SparseSearchHit, ...],
        risk_tags: set[str],
    ) -> dict[str, _ChannelAggregate]:
        aggregates: dict[str, _ChannelAggregate] = {}
        for hit in hits:
            for case_id in hit.document.case_ids:
                summary = self._summaries.get(case_id)
                if summary is None:
                    continue
                if risk_tags and not risk_tags.intersection(summary.risk_tags):
                    continue
                current = aggregates.get(case_id)
                if current is None:
                    aggregates[case_id] = _ChannelAggregate(hit.score, hit)
                    continue
                current.score += hit.score * 0.12
                if hit.score > current.best_hit.score:
                    current.best_hit = hit
        return aggregates

    @staticmethod
    def _ranks(values: dict[str, _ChannelAggregate]) -> dict[str, int]:
        ordered = sorted(values.items(), key=lambda item: (-item[1].score, item[0]))
        return {case_id: rank for rank, (case_id, _) in enumerate(ordered, start=1)}


def _choose_hit(
    bm25: _ChannelAggregate | None,
    vector: _ChannelAggregate | None,
) -> SparseSearchHit:
    if bm25 is None and vector is None:  # pragma: no cover
        raise RuntimeError("混合召回候选缺少来源命中")
    if bm25 is None:
        return vector.best_hit  # type: ignore[union-attr]
    if vector is None:
        return bm25.best_hit
    bm25_strength = _normalize_bm25(bm25.best_hit.score)
    return bm25.best_hit if bm25_strength >= vector.best_hit.score else vector.best_hit


def _meaningful_tokens(text: str) -> set[str]:
    return {token for token in chinese_unigram_bigram(text) if len(token) >= 2}


def _token_overlap(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    document_tokens = _meaningful_tokens(text)
    return len(query_tokens.intersection(document_tokens)) / len(query_tokens)


def _contains_phrase(query: str, text: str) -> bool:
    compact_query = "".join(query.split())
    compact_text = "".join(text.split())
    if min(len(compact_query), len(compact_text)) < 6:
        return False
    return compact_query in compact_text or compact_text in compact_query


def _normalize_bm25(score: float) -> float:
    if score <= 0:
        return 0.0
    return 1 - math.exp(-score / 18.0)
