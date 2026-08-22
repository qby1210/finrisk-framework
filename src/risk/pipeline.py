"""Query 规则、案例检索、DeepSeek 和分数校准的一体化流水线。"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError

from application.retrieval_service import CaseRetrievalService
from domain.knowledge_models import MatchedCase
from domain.query_models import QueryProcessingResult, QueryScene, RiskQuerySentence
from domain.risk_models import (
    QueryAnalysisResult,
    QueryRiskSummary,
    RiskEvidence,
    RiskLevel,
    SentenceRiskAssessment,
)
from llm import ChatMessage, JsonChatRequest, LLMClient, LLMProviderError
from risk.calibration import RiskScorer, RiskThresholder
from risk.detection import RuleDetectionResult, RuleRiskDetector


@dataclass(frozen=True, slots=True)
class _PreliminaryAssessment:
    sentence: RiskQuerySentence
    rules: RuleDetectionResult
    matches: tuple[MatchedCase, ...]
    retrieval_score: float


class _LLMItem(BaseModel):
    sentence_id: str
    risk_score: float = Field(ge=0, le=1)
    risk_labels: list[str] = Field(default_factory=list, max_length=2)
    reasoning: str = Field(min_length=1, max_length=500)


class _LLMBatch(BaseModel):
    items: list[_LLMItem]


class RiskAssessmentPipeline:
    """Risk 模块唯一入口；不修改案例标签或 Query 四字段。"""

    def __init__(
        self,
        *,
        rule_detector: RuleRiskDetector,
        retrieval_service: CaseRetrievalService,
        taxonomy: tuple[str, ...],
        llm_client: LLMClient | None,
    ) -> None:
        self.rule_detector = rule_detector
        self.retrieval_service = retrieval_service
        self.taxonomy = tuple(label for label in taxonomy if label)
        self._taxonomy_set = set(self.taxonomy)
        self.llm_client = llm_client
        self.scorer = RiskScorer()
        self.thresholder = RiskThresholder()

    async def analyze(self, query: QueryProcessingResult) -> QueryAnalysisResult:
        preliminary = tuple(self._preliminary(sentence) for sentence in query.sentences)
        warnings: list[str] = []
        llm_outputs: dict[str, _LLMItem] = {}
        if self.llm_client is not None:
            try:
                llm_outputs = await self._llm_assess(preliminary)
            except LLMProviderError as error:
                warnings.append(f"DeepSeek 调用失败，已使用规则与案例检索降级：{error}")
        else:
            warnings.append("未配置 DeepSeek API Key，风险结果使用规则与案例检索降级")
        assessments = [
            self._finalize(item, llm_outputs.get(item.sentence.sentence_id)) for item in preliminary
        ]
        summary = self._summarize(assessments, bool(llm_outputs), warnings)
        return QueryAnalysisResult(
            **query.model_dump(exclude={"schema_version"}),
            schema_version="3.0",
            risk_summary=summary,
            risk_assessments=assessments,
        )

    def _preliminary(self, sentence: RiskQuerySentence) -> _PreliminaryAssessment:
        rules = self.rule_detector.detect(sentence.text)
        matches = tuple(self.retrieval_service.search(sentence.text, top_k=3))
        specific_matches = [case for case in matches if set(case.risk_tags) - {"其他"}]
        retrieval_score = specific_matches[0].score * 0.85 if specific_matches else 0.0
        return _PreliminaryAssessment(sentence, rules, matches, retrieval_score)

    async def _llm_assess(
        self,
        preliminary: tuple[_PreliminaryAssessment, ...],
    ) -> dict[str, _LLMItem]:
        if self.llm_client is None:
            return {}
        outputs: dict[str, _LLMItem] = {}
        for start in range(0, len(preliminary), 10):
            batch = preliminary[start : start + 10]
            batch_payload = json.dumps([_llm_input(item) for item in batch], ensure_ascii=False)
            response = await self.llm_client.complete_json(
                JsonChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "你是保险营销合规审查员。逐句判断文本本身是否存在风险，"
                                "历史案例和规则只作为证据，不得因相似案例本身就判违规。"
                                "risk_score 为0到1；risk_labels只能从给定标签中选择0到2个；"
                                "无明显风险时标签为空。只输出JSON对象："
                                '{"items":[{"sentence_id":"...","risk_score":0.0,'
                                '"risk_labels":[],"reasoning":"简短、可核验的中文理由"}]}。'
                            ),
                        ),
                        ChatMessage(
                            role="user",
                            content=(
                                "允许标签："
                                f"{json.dumps(self.taxonomy, ensure_ascii=False)}\n"
                                "待判断句子及前两层证据：\n"
                                f"{batch_payload}"
                            ),
                        ),
                    ],
                    temperature=0.0,
                    max_tokens=3000,
                )
            )
            try:
                parsed = _LLMBatch.model_validate(response.data)
            except ValidationError as error:
                raise LLMProviderError("DeepSeek 风险输出不符合批量字段契约") from error
            expected_ids = {item.sentence.sentence_id for item in batch}
            for item in parsed.items:
                if item.sentence_id not in expected_ids or item.sentence_id in outputs:
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
            item.retrieval_score,
            llm_output.risk_score if llm_output else None,
        )
        decision = self.thresholder.judge(final_score)
        labels = self._resolve_labels(item, llm_output, final_score)
        matches = self._label_aligned_matches(item.sentence.text, labels, item.matches)
        evidence = list(item.rules.evidence)
        if item.matches:
            top = item.matches[0]
            evidence.append(
                RiskEvidence(
                    source="case_retrieval",
                    description=f"相似案例 {top.case_id}，检索证据强度 {top.score:.2f}",
                )
            )
        if llm_output:
            evidence.append(RiskEvidence(source="deepseek", description=llm_output.reasoning))
        reasoning = (
            llm_output.reasoning
            if llm_output
            else _fallback_reasoning(item.rules, item.matches, decision.level)
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
            method="rule+bm25+deepseek" if llm_output else "rule+bm25_fallback",
            evidence=evidence,
            matched_cases=matches,
        )

    def _resolve_labels(
        self,
        item: _PreliminaryAssessment,
        llm_output: _LLMItem | None,
        final_score: float,
    ) -> list[str]:
        if final_score < 0.2:
            return []
        candidates: list[str] = []
        if llm_output:
            candidates.extend(llm_output.risk_labels)
        candidates.extend(item.rules.risk_labels)
        independent_score = max(item.rules.risk_score, llm_output.risk_score if llm_output else 0.0)
        if independent_score >= 0.4 and not candidates:
            for match in item.matches:
                candidates.extend(tag for tag in match.risk_tags if tag != "其他")
        labels = [label for label in dict.fromkeys(candidates) if label in self._taxonomy_set]
        if item.sentence.scene == QueryScene.ST4_MEETING_MATERIAL and final_score >= 0.4:
            labels.append("产品说明会违规")
        return list(dict.fromkeys(_backfill_labels(labels)))[:3]

    def _label_aligned_matches(
        self,
        text: str,
        labels: list[str],
        initial: tuple[MatchedCase, ...],
    ) -> list[MatchedCase]:
        if not labels:
            return list(initial[:2])
        aligned = self.retrieval_service.search(text, top_k=3, risk_tags=set(labels))
        combined = [*aligned, *initial]
        return list({case.case_id: case for case in combined}.values())[:3]

    def _summarize(
        self,
        assessments: list[SentenceRiskAssessment],
        llm_used: bool,
        warnings: list[str],
    ) -> QueryRiskSummary:
        overall_score = max(item.risk_score for item in assessments)
        decision = self.thresholder.judge(overall_score)
        label_counts = Counter(
            label for item in assessments if item.risk_score >= 0.2 for label in item.risk_labels
        )
        return QueryRiskSummary(
            overall_score=overall_score,
            overall_level=decision.level,
            overall_level_name=decision.level_name,
            action=decision.action,
            risk_labels=[label for label, _ in label_counts.most_common(6)],
            sentence_count=len(assessments),
            risky_sentence_count=sum(1 for item in assessments if item.risk_score >= 0.2),
            llm_used=llm_used,
            llm_model=self.llm_client.model_name if llm_used and self.llm_client else None,
            warnings=warnings,
        )


def _llm_input(item: _PreliminaryAssessment) -> dict[str, object]:
    return {
        "sentence_id": item.sentence.sentence_id,
        "scene": item.sentence.scene.value,
        "text": item.sentence.text,
        "rule_score": item.rules.risk_score,
        "rule_labels": list(item.rules.risk_labels),
        "matched_cases": [
            {
                "case_id": case.case_id,
                "risk_tags": case.risk_tags,
                "score": case.score,
                "violation": case.violation_behavior[:300],
            }
            for case in item.matches[:2]
        ],
    }


def _fallback_reasoning(
    rules: RuleDetectionResult,
    matches: tuple[MatchedCase, ...],
    level: RiskLevel,
) -> str:
    if rules.evidence:
        return "；".join(value.description for value in rules.evidence[:2])
    if matches and level != RiskLevel.NONE:
        return f"与历史案例 {matches[0].case_id} 的违规事实存在文本相似性，建议结合语境复核。"
    return "未发现明确规则命中；当前为未调用大模型时的降级判断。"


def _backfill_labels(labels: list[str]) -> list[str]:
    current = list(dict.fromkeys(labels))
    umbrella = {
        "欺骗投保人",
        "夸大收益",
        "承诺收益",
        "保证收益",
        "弱化风险提示",
        "隐瞒重要信息",
        "虚构收益率",
    }
    if umbrella.intersection(current):
        current.append("销售误导")
    if "弱化风险提示" in current:
        current.append("隐瞒重要信息")
    if "承诺收益" in current and "夸大收益" in current:
        current.append("虚构收益率")
    if "合同外利益" in current:
        current.append("赠送利益")
    return list(dict.fromkeys(current))
