"""基于风险词库和正则模式的刚性层检测。"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from domain.risk_models import RiskEvidence

REGEX_LABEL_MAP: dict[str, tuple[str, ...]] = {
    "absolute_guarantee": ("承诺收益", "绝对化表述"),
    "bank_comparison": ("不当比较", "销售误导"),
    "deposit_disguise": ("欺骗投保人", "销售误导"),
    "no_risk_claim": ("承诺收益", "绝对化表述"),
    "urgency_pressure": ("诱导投保",),
    "gift_inducement": ("赠送利益", "合同外利益"),
    "tax_debt_evasion": ("避债避税",),
    "fake_endorsement": ("虚假宣传", "欺骗投保人"),
    "exaggerated_return": ("夸大收益", "虚构收益率"),
    "absolute_service_claim": ("绝对化表述", "虚假宣传"),
}


@dataclass(frozen=True, slots=True)
class _KeywordRule:
    keyword: str
    source: str
    priority: int
    risk_labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuleDetectionResult:
    risk_score: float
    risk_labels: tuple[str, ...]
    evidence: tuple[RiskEvidence, ...]


class RuleRiskDetector:
    """读取 risk_src 的唯一关键词资产，不复制案例回溯或模型检索逻辑。"""

    def __init__(self, keyword_path: Path) -> None:
        if not keyword_path.is_file():
            raise FileNotFoundError(f"风险关键词库不存在: {keyword_path}")
        payload = json.loads(keyword_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("风险关键词库必须是 JSON 对象")
        self.version = str(payload.get("version") or "unknown")
        self._keywords = _parse_keyword_rules(payload.get("keywords"))
        self._patterns = _parse_patterns(payload.get("regex_patterns"))
        self._patterns.setdefault(
            "absolute_service_claim", re.compile(r"(?:从不|绝不|保证不).{0,8}(?:拒赔|扯皮|拖延)")
        )

    def detect(self, text: str) -> RuleDetectionResult:
        normalized = unicodedata.normalize("NFKC", text).casefold()
        if not normalized.strip():
            return RuleDetectionResult(0.0, (), ())
        label_scores: dict[str, float] = {}
        signal_strengths: list[float] = []
        evidence: list[RiskEvidence] = []
        for rule in self._keywords:
            if rule.keyword not in normalized:
                continue
            source_factor = 1.0 if rule.source == "curated" else 0.55
            strength = min(0.78, 0.38 + 0.1 * rule.priority) * source_factor
            signal_strengths.append(strength)
            divisor = math.sqrt(max(1, len(rule.risk_labels)))
            for label in rule.risk_labels:
                if label != "其他":
                    label_scores[label] = label_scores.get(label, 0.0) + strength / divisor
            evidence.append(
                RiskEvidence(
                    source="rule_keyword",
                    description=f"命中风险表达“{rule.keyword}”（{rule.source}）",
                )
            )
        for name, pattern in self._patterns.items():
            match = pattern.search(normalized)
            if match is None:
                continue
            strength = 0.82
            signal_strengths.append(strength)
            for label in REGEX_LABEL_MAP.get(name, ("其他",)):
                if label != "其他":
                    label_scores[label] = label_scores.get(label, 0.0) + strength
            evidence.append(
                RiskEvidence(
                    source="rule_regex",
                    description=f"命中组合规则“{name}”：{match.group(0)[:80]}",
                )
            )
        combined = 1.0
        for strength in sorted(signal_strengths, reverse=True)[:5]:
            combined *= 1 - strength
        labels = tuple(
            label
            for label, _ in sorted(label_scores.items(), key=lambda item: (-item[1], item[0]))[:3]
        )
        return RuleDetectionResult(
            risk_score=round(min(0.98, 1 - combined), 6) if signal_strengths else 0.0,
            risk_labels=labels,
            evidence=tuple(evidence[:8]),
        )


def _parse_keyword_rules(value: object) -> tuple[_KeywordRule, ...]:
    if not isinstance(value, list):
        raise ValueError("风险关键词库缺少 keywords 数组")
    rules: list[_KeywordRule] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        keyword = unicodedata.normalize("NFKC", str(item.get("keyword") or "")).casefold()
        labels = item.get("risk_labels")
        if len(keyword) < 2 or not isinstance(labels, list):
            continue
        rules.append(
            _KeywordRule(
                keyword=keyword,
                source=str(item.get("source") or "unknown"),
                priority=int(item.get("priority") or 1),
                risk_labels=tuple(str(label) for label in labels if label),
            )
        )
    return tuple(sorted(rules, key=lambda rule: (-len(rule.keyword), rule.keyword)))


def _parse_patterns(value: object) -> dict[str, re.Pattern[str]]:
    if not isinstance(value, dict):
        return {}
    patterns: dict[str, re.Pattern[str]] = {}
    for name, expression in value.items():
        try:
            patterns[str(name)] = re.compile(str(expression), re.IGNORECASE)
        except re.error as error:
            raise ValueError(f"风险正则无法编译: {name}") from error
    return patterns
