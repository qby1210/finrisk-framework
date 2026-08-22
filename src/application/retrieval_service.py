"""案例 BM25 检索应用服务。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from threading import RLock

from domain.knowledge_models import CaseSummary, MatchedCase
from retrieval import SparseRetrievalIndex, SparseSearchHit
from storage.case_repository import CaseRepository


@dataclass(slots=True)
class _CaseAggregate:
    score: float
    best_hit: SparseSearchHit


class CaseRetrievalService:
    """把离线检索包的稀疏通道接到当前案例仓库。

    首次查询时延迟建索引；Web 新增或删除案例后，通过仓库 revision 自动重建，调用方
    不需要了解索引生命周期。
    """

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
        index = self._ensure_index()
        unit_hits = index.search(query, top_k=max(100, top_k * 30))
        aggregates: dict[str, _CaseAggregate] = {}
        for hit in unit_hits:
            for case_id in hit.document.case_ids:
                summary = self._summaries.get(case_id)
                if summary is None:
                    continue
                if risk_tags and not risk_tags.intersection(summary.risk_tags):
                    continue
                current = aggregates.get(case_id)
                if current is None:
                    aggregates[case_id] = _CaseAggregate(score=hit.score, best_hit=hit)
                    continue
                current.score += hit.score * 0.15
                if hit.score > current.best_hit.score:
                    current.best_hit = hit

        ranked = sorted(aggregates.items(), key=lambda item: (-item[1].score, item[0]))
        results: list[MatchedCase] = []
        for case_id, aggregate in ranked[:top_k]:
            summary = self._summaries[case_id]
            results.append(
                MatchedCase(
                    case_id=case_id,
                    case_title=summary.case_title,
                    violation_behavior=summary.violation_behavior,
                    penalty_content=summary.penalty_content,
                    regulator=summary.regulator,
                    risk_tags=summary.risk_tags,
                    score=_normalize_bm25(aggregate.score),
                    matched_text=aggregate.best_hit.document.text,
                    matched_source=aggregate.best_hit.document.source,
                    matched_unit_id=aggregate.best_hit.document.unit_id,
                )
            )
        return results

    def rebuild(self) -> None:
        """重建内存索引和摘要映射。"""

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


def _normalize_bm25(score: float) -> float:
    """将非负 BM25 聚合分压缩为只用于 UI/融合的 0-1 证据强度。"""

    if score <= 0:
        return 0.0
    return round(1 - math.exp(-score / 18.0), 6)
