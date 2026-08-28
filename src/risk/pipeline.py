"""Query 两阶段本地初判、动态LLM复核、门控检索和文档聚合流水线。"""

from __future__ import annotations

import asyncio
import json
import math
from collections import defaultdict
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from application.retrieval_service import CaseRetrievalService
from domain.knowledge_models import MatchedCase
from domain.query_models import (
    QueryProcessingResult,
    QueryScene,
    RiskQuerySentence,
    SentenceSourceMapping,
)
from domain.risk_models import (
    QueryAnalysisResult,
    QueryRiskSummary,
    RiskEvidence,
    RiskLabelFinding,
    RiskLevel,
    SentenceRiskAssessment,
)
from llm import ChatMessage, JsonChatRequest, LLMClient, LLMProviderError
from risk.calibration import RiskScorer, RiskThresholder
from risk.detection import RuleDetectionResult, RuleRiskDetector
from risk.taxonomy import expand_related_labels, taxonomy_prompt


@dataclass(frozen=True, slots=True)
class _PreliminaryAssessment:
    sentence: RiskQuerySentence
    mapping: SentenceSourceMapping
    rules: RuleDetectionResult


class _LLMItem(BaseModel):
    sentence_id: str
    risk_score: float = Field(ge=0, le=1)
    risk_labels: list[str] = Field(default_factory=list, max_length=10)
    evidence: list[str] = Field(default_factory=list, max_length=5)
    reasoning: str = Field(min_length=1, max_length=500)


class _LLMBatch(BaseModel):
    items: list[_LLMItem]


class RiskAssessmentPipeline:
    """先判断当前文本风险，再按阈值和标签检索案例。"""

    def __init__(
        self,
        *,
        rule_detector: RuleRiskDetector,
        retrieval_service: CaseRetrievalService,
        taxonomy: tuple[str, ...],
        llm_client: LLMClient | None,
        taxonomy_descriptions: dict[str, str] | None = None,
        risk_display_threshold: float = 0.20,
        retrieval_threshold: float = 0.40,
        local_direct_confidence: float = 0.90,
        whole_query_llm_chars: int = 6_000,
        llm_batch_chars: int = 6_000,
        llm_batch_items: int = 12,
        llm_concurrency: int = 2,
    ) -> None:
        if not 0 <= risk_display_threshold <= retrieval_threshold <= 1:
            raise ValueError("风险展示阈值和检索阈值不合法")
        self.rule_detector = rule_detector
        self.retrieval_service = retrieval_service
        self.taxonomy = tuple(label for label in taxonomy if label)
        self._taxonomy_set = set(self.taxonomy)
        self.taxonomy_descriptions = taxonomy_descriptions or {}
        self.llm_client = llm_client
        self.risk_display_threshold = risk_display_threshold
        self.retrieval_threshold = retrieval_threshold
        self.local_direct_confidence = local_direct_confidence
        self.whole_query_llm_chars = whole_query_llm_chars
        self.llm_batch_chars = llm_batch_chars
        self.llm_batch_items = llm_batch_items
        self.llm_concurrency = llm_concurrency
        self.scorer = RiskScorer()
        self.thresholder = RiskThresholder()

    async def analyze(self, query: QueryProcessingResult) -> QueryAnalysisResult:
        mappings = {mapping.sentence_id: mapping for mapping in query.source_mappings}
        preliminary = tuple(
            _PreliminaryAssessment(
                sentence=sentence,
                mapping=mappings[sentence.sentence_id],
                rules=self.rule_detector.detect(sentence.text, sentence.scene),
            )
            for sentence in query.sentences
        )
        review_ids = {
            item.sentence.sentence_id
            for item in preliminary
            if not self._local_direct(item.rules)
        }
        warnings: list[str] = []
        llm_outputs: dict[str, _LLMItem] = {}
        if self.llm_client is not None and review_ids:
            llm_outputs, llm_warnings = await self._llm_assess(preliminary, review_ids)
            warnings.extend(llm_warnings)
        elif self.llm_client is None and review_ids:
            warnings.append(
                f"未配置大模型，{len(review_ids)}个中低置信句子已使用本地两阶段结果降级"
            )

        assessments = [
            self._finalize(item, llm_outputs.get(item.sentence.sentence_id))
            for item in preliminary
        ]
        assessments = await self._retrieve_eligible(assessments)
        summary = self._summarize(
            assessments,
            llm_outputs=llm_outputs,
            review_ids=review_ids,
            warnings=warnings,
        )
        return QueryAnalysisResult(
            **query.model_dump(exclude={"schema_version"}),
            schema_version="4.0",
            risk_summary=summary,
            risk_assessments=assessments,
        )

    def _local_direct(self, rules: RuleDetectionResult) -> bool:
        return rules.strong_signal and rules.confidence >= self.local_direct_confidence

    async def _llm_assess(
        self,
        preliminary: tuple[_PreliminaryAssessment, ...],
        review_ids: set[str],
    ) -> tuple[dict[str, _LLMItem], list[str]]:
        if self.llm_client is None:
            return {}, []
        batches = self._llm_batches(preliminary, review_ids)
        semaphore = asyncio.Semaphore(self.llm_concurrency)

        async def run_batch(
            batch: tuple[_PreliminaryAssessment, ...],
            target_ids: set[str],
        ) -> tuple[dict[str, _LLMItem], str | None]:
            async with semaphore:
                try:
                    return await self._llm_batch(batch, target_ids), None
                except LLMProviderError as error:
                    return {}, str(error)

        responses = await asyncio.gather(
            *(run_batch(batch, target_ids) for batch, target_ids in batches)
        )
        outputs: dict[str, _LLMItem] = {}
        warnings: list[str] = []
        for batch_outputs, error in responses:
            outputs.update(batch_outputs)
            if error:
                warnings.append(f"大模型批次复核失败，已对该批使用本地结果：{error}")
        missing = review_ids - set(outputs)
        if missing:
            warnings.append(f"{len(missing)}个待复核句子未取得有效大模型输出")
        return outputs, warnings

    def _llm_batches(
        self,
        preliminary: tuple[_PreliminaryAssessment, ...],
        review_ids: set[str],
    ) -> list[tuple[tuple[_PreliminaryAssessment, ...], set[str]]]:
        total_chars = sum(len(item.sentence.text) for item in preliminary)
        if total_chars <= self.whole_query_llm_chars:
            return [(preliminary, set(review_ids))]

        batches: list[tuple[tuple[_PreliminaryAssessment, ...], set[str]]] = []
        current: list[_PreliminaryAssessment] = []
        current_chars = 0
        for item in preliminary:
            if item.sentence.sentence_id not in review_ids:
                continue
            item_chars = len(item.sentence.text) + len(item.mapping.context_before) + len(
                item.mapping.context_after
            )
            if current and (
                len(current) >= self.llm_batch_items
                or current_chars + item_chars > self.llm_batch_chars
            ):
                batch = tuple(current)
                batches.append((batch, {value.sentence.sentence_id for value in batch}))
                current = []
                current_chars = 0
            current.append(item)
            current_chars += item_chars
        if current:
            batch = tuple(current)
            batches.append((batch, {value.sentence.sentence_id for value in batch}))
        return batches

    async def _llm_batch(
        self,
        batch: tuple[_PreliminaryAssessment, ...],
        target_ids: set[str],
    ) -> dict[str, _LLMItem]:
        if self.llm_client is None:
            return {}
        batch_payload = json.dumps([_llm_input(item) for item in batch], ensure_ascii=False)
        response = await self.llm_client.complete_json(
            JsonChatRequest(
                messages=[
                    ChatMessage(
                        role="system",
                        content=(
                            "你是保险营销与经营合规审查员。只判断待审文本本身，不得使用或猜测历史案例。"
                            "逐句给出0到1风险分、风险标签、原文证据短语和简短理由。"
                            "标签存在语义重复、上下位和包含关系，不要求互斥；只要语义明确相关可同时选择，"
                            "但不得仅因词面命中而堆砌标签。无明显风险时risk_score应低于0.20且标签为空。"
                            "带有明确条件、风险提示、合同限定、个人经历限定或正常流程描述时不要误判。"
                            "只输出JSON对象："
                            '{"items":[{"sentence_id":"...","risk_score":0.0,'
                            '"risk_labels":[],"evidence":[],"reasoning":"简短中文理由"}]}。\n'
                            "允许的27类标签及定义：\n"
                            f"{taxonomy_prompt(self.taxonomy, self.taxonomy_descriptions)}"
                        ),
                    ),
                    ChatMessage(
                        role="user",
                        content=(
                            "只需输出这些待复核句子的结果："
                            f"{json.dumps(sorted(target_ids), ensure_ascii=False)}\n"
                            "同批其余句子只用于理解全文上下文，不要输出。"
                            "本地规则是可质疑的初筛证据，不是最终结论。\n"
                            f"材料句子：{batch_payload}"
                        ),
                    ),
                ],
                temperature=0.0,
                max_tokens=max(1200, min(5000, 450 * len(target_ids))),
            )
        )
        try:
            parsed = _LLMBatch.model_validate(response.data)
        except ValidationError as error:
            raise LLMProviderError("大模型风险输出不符合批量字段契约") from error
        outputs: dict[str, _LLMItem] = {}
        for item in parsed.items:
            if item.sentence_id not in target_ids or item.sentence_id in outputs:
                continue
            valid_labels = [label for label in item.risk_labels if label in self._taxonomy_set]
            outputs[item.sentence_id] = item.model_copy(update={"risk_labels": valid_labels})
        return outputs

    def _finalize(
        self,
        item: _PreliminaryAssessment,
        llm_output: _LLMItem | None,
    ) -> SentenceRiskAssessment:
        final_score = self.scorer.fuse(
            item.rules.risk_score,
            llm_score=llm_output.risk_score if llm_output else None,
            local_confidence=item.rules.confidence,
            strong_signal=item.rules.strong_signal,
        )
        decision = self.thresholder.judge(final_score)
        labels = self._resolve_labels(item, llm_output, final_score)
        evidence = list(item.rules.evidence)
        if llm_output:
            for quote in llm_output.evidence:
                evidence.append(
                    RiskEvidence(source="llm_semantic_evidence", description=f"原文证据：{quote}")
                )
            evidence.append(
                RiskEvidence(
                    source="llm_semantic_review",
                    description=llm_output.reasoning,
                )
            )
        reasoning = (
            llm_output.reasoning if llm_output else _fallback_reasoning(item.rules, decision.level)
        )
        return SentenceRiskAssessment(
            query_id=item.sentence.query_id,
            sentence_id=item.sentence.sentence_id,
            text=item.sentence.text,
            risk_score=final_score,
            risk_level=decision.level,
            risk_level_name=decision.level_name,
            action=decision.action,
            risk_labels=labels,
            reasoning=reasoning,
            method="local_two_stage+llm" if llm_output else "local_two_stage",
            local_score=item.rules.risk_score,
            local_confidence=item.rules.confidence,
            llm_reviewed=llm_output is not None,
            evidence=evidence,
        )

    def _resolve_labels(
        self,
        item: _PreliminaryAssessment,
        llm_output: _LLMItem | None,
        final_score: float,
    ) -> list[str]:
        if final_score < self.risk_display_threshold:
            return []
        candidates: list[str] = []
        if llm_output:
            candidates.extend(llm_output.risk_labels)
        if item.rules.risk_score >= self.risk_display_threshold or item.rules.strong_signal:
            candidates.extend(item.rules.risk_labels)
        candidates.extend(_scene_channel_labels(item.sentence, final_score))
        return expand_related_labels(candidates, self._taxonomy_set, limit=10)

    async def _retrieve_eligible(
        self,
        assessments: list[SentenceRiskAssessment],
    ) -> list[SentenceRiskAssessment]:
        eligible = [
            item
            for item in assessments
            if item.risk_score >= self.retrieval_threshold and item.risk_labels
        ]
        if not eligible:
            return assessments
        semaphore = asyncio.Semaphore(4)

        async def retrieve(item: SentenceRiskAssessment) -> tuple[str, list[MatchedCase]]:
            async with semaphore:
                matches = await asyncio.to_thread(
                    self.retrieval_service.search,
                    item.text,
                    top_k=3,
                    risk_tags=set(item.risk_labels),
                )
                return item.sentence_id, matches

        retrieved = dict(await asyncio.gather(*(retrieve(item) for item in eligible)))
        results: list[SentenceRiskAssessment] = []
        for item in assessments:
            matches = retrieved.get(item.sentence_id)
            if matches is None:
                results.append(item)
                continue
            evidence = list(item.evidence)
            if matches:
                top = matches[0]
                evidence.append(
                    RiskEvidence(
                        source="hybrid_case_retrieval",
                        description=(
                            f"标签对齐案例 {top.case_id}，混合重排分 {top.score:.2f}"
                        ),
                    )
                )
            results.append(
                item.model_copy(
                    update={
                        "method": f"{item.method}+bm25_vector_rrf_rerank",
                        "retrieval_performed": True,
                        "evidence": evidence,
                        "matched_cases": matches,
                    }
                )
            )
        return results

    def _summarize(
        self,
        assessments: list[SentenceRiskAssessment],
        *,
        llm_outputs: dict[str, _LLMItem],
        review_ids: set[str],
        warnings: list[str],
    ) -> QueryRiskSummary:
        scores = sorted((item.risk_score for item in assessments), reverse=True)
        maximum = scores[0]
        if maximum < self.risk_display_threshold:
            overall_score = maximum
        else:
            support = sum(scores[1:4])
            overall_score = min(1.0, maximum + (1 - maximum) * (1 - math.exp(-0.18 * support)))
        overall_score = round(overall_score, 4)
        decision = self.thresholder.judge(overall_score)

        label_sentences: dict[str, list[SentenceRiskAssessment]] = defaultdict(list)
        for item in assessments:
            if item.risk_score < self.risk_display_threshold:
                continue
            for label in item.risk_labels:
                label_sentences[label].append(item)
        findings = [
            RiskLabelFinding(
                label=label,
                max_score=max(item.risk_score for item in items),
                sentence_count=len(items),
                sentence_ids=[item.sentence_id for item in items],
            )
            for label, items in label_sentences.items()
        ]
        findings.sort(key=lambda item: (-item.max_score, -item.sentence_count, item.label))

        best_cases: dict[str, MatchedCase] = {}
        for item in assessments:
            for case in item.matched_cases:
                current = best_cases.get(case.case_id)
                if current is None or case.score > current.score:
                    best_cases[case.case_id] = case
        top_cases = sorted(best_cases.values(), key=lambda case: (-case.score, case.case_id))[:5]
        return QueryRiskSummary(
            overall_score=overall_score,
            overall_level=decision.level,
            overall_level_name=decision.level_name,
            action=decision.action,
            risk_labels=[finding.label for finding in findings],
            risk_findings=findings,
            top_matched_cases=top_cases,
            risk_display_threshold=self.risk_display_threshold,
            retrieval_threshold=self.retrieval_threshold,
            max_sentence_score=maximum,
            sentence_count=len(assessments),
            risky_sentence_count=sum(
                item.risk_score >= self.risk_display_threshold for item in assessments
            ),
            llm_used=bool(llm_outputs),
            llm_model=self.llm_client.model_name if llm_outputs and self.llm_client else None,
            llm_reviewed_sentence_count=len(llm_outputs),
            local_direct_sentence_count=len(assessments) - len(review_ids),
            retrieval_sentence_count=sum(item.retrieval_performed for item in assessments),
            warnings=warnings,
        )


def _llm_input(item: _PreliminaryAssessment) -> dict[str, object]:
    return {
        "sentence_id": item.sentence.sentence_id,
        "scene": item.sentence.scene.value,
        "text": item.sentence.text,
        "context_before": item.mapping.context_before[-400:],
        "context_after": item.mapping.context_after[:400],
        "local_stage1_score": item.rules.stage1_score,
        "local_stage2_score": item.rules.stage2_score,
        "local_labels": list(item.rules.risk_labels),
        "local_evidence": [value.description for value in item.rules.evidence[:5]],
    }


def _fallback_reasoning(rules: RuleDetectionResult, level: RiskLevel) -> str:
    if rules.evidence:
        return "；".join(value.description for value in rules.evidence[:2])
    if level is RiskLevel.NONE:
        return "本地两阶段规则未发现明确风险信号；建议在完整模式下进行语义复核。"
    return "本地规则发现弱风险信号，当前为未取得大模型结果时的降级判断。"


def _scene_channel_labels(sentence: RiskQuerySentence, score: float) -> list[str]:
    if score < 0.40:
        return []
    text = sentence.text
    if sentence.scene is QueryScene.ST4_MEETING_MATERIAL:
        return ["产品说明会违规"]
    if sentence.scene is QueryScene.ST5_TRAINING_TELEMARKETING_CALLBACK:
        labels: list[str] = []
        if any(keyword in text for keyword in ("培训", "课件", "内部话术")):
            labels.append("培训材料违规")
        if "回访" in text:
            labels.append("回访违规")
        if any(keyword in text for keyword in ("电销", "电话", "坐席", "致电")):
            labels.append("电销违规")
        return labels
    return []
