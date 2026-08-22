"""多层证据融合与风险等级校准。"""

from __future__ import annotations

from dataclasses import dataclass

from domain.risk_models import RiskLevel


@dataclass(frozen=True, slots=True)
class RiskDecision:
    level: RiskLevel
    level_name: str
    action: str


class RiskScorer:
    """沿用 risk_src 的 0.2/0.2/0.6 设计，并为无 LLM 模式重新归一化。"""

    def fuse(self, rule_score: float, retrieval_score: float, llm_score: float | None) -> float:
        if llm_score is None:
            score = (
                retrieval_score * 0.15
                if rule_score <= 0
                else rule_score * 0.65 + retrieval_score * 0.35
            )
        else:
            score = rule_score * 0.2 + retrieval_score * 0.2 + llm_score * 0.6
            if max(rule_score, llm_score) < 0.2:
                score = min(score, 0.19)
        return round(max(0.0, min(1.0, score)), 4)


class RiskThresholder:
    """输出五档 Web 风险等级并修复原包低风险分支不可达的问题。"""

    def judge(self, score: float) -> RiskDecision:
        if score >= 0.85:
            return RiskDecision(RiskLevel.HIGH, "高风险", "拦截并人工复审")
        if score >= 0.60:
            return RiskDecision(RiskLevel.MEDIUM, "中风险", "标记并提示修改")
        if score >= 0.40:
            return RiskDecision(RiskLevel.REVIEW, "疑似风险", "建议人工复查")
        if score >= 0.20:
            return RiskDecision(RiskLevel.LOW, "低风险", "记录并观察")
        return RiskDecision(RiskLevel.NONE, "无明显风险", "放行")
