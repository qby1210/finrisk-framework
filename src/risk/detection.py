"""场景感知的两阶段本地风险初判。"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from domain.query_models import QueryScene
from domain.risk_models import RiskEvidence

REGEX_LABEL_MAP: dict[str, tuple[str, ...]] = {
    "absolute_guarantee": ("承诺收益", "保证收益", "绝对化表述", "销售误导"),
    "bank_comparison": ("不当比较", "销售误导"),
    "deposit_disguise": ("欺骗投保人", "销售误导", "隐瞒重要信息"),
    "no_risk_claim": ("承诺收益", "绝对化表述", "销售误导"),
    "urgency_pressure": ("诱导投保",),
    "gift_inducement": ("赠送利益", "合同外利益", "诱导投保"),
    "tax_debt_evasion": ("避债避税", "虚假宣传"),
    "fake_endorsement": ("虚假宣传", "欺骗投保人"),
    "exaggerated_return": ("夸大收益", "虚构收益率", "销售误导"),
    "absolute_service_claim": ("绝对化表述", "虚假宣传"),
    "false_expense": ("虚列费用套取资金",),
    "fake_callback": ("回访违规", "客户信息不真实"),
    "unfiled_rate_terms": ("未按规定使用费率条款", "隐瞒重要信息"),
    "unauthorized_sales": ("委托无资质机构销售",),
    "agent_mismanagement": ("代理人管理不到位",),
    "customer_data_fabrication": ("客户信息不真实",),
    "kickback_rebate": ("回扣返佣", "合同外利益"),
    "concealed_terms": ("弱化风险提示", "隐瞒重要信息", "销售误导"),
    "competitor_denigration": ("贬低竞品", "不当比较"),
    "unsolicited_telemarketing": ("电销违规",),
}

_STRONG_PATTERNS: dict[str, re.Pattern[str]] = {
    "false_expense": re.compile(
        r"(?:虚构|虚假|伪造).{0,10}(?:发票|会务费|宣传费|业务费|费用).{0,20}(?:列支|报销|套取|转入)"
    ),
    "fake_callback": re.compile(
        r"(?:业务员|代理人|销售人员).{0,12}(?:代接|冒充).{0,12}(?:客户|投保人)|"
        r"(?:代接回访|统一回答[‘'\"“]?(?:已了解|是|确认))"
    ),
    "unfiled_rate_terms": re.compile(
        r"(?:未经备案|未按备案|擅自|私自).{0,16}(?:费率|条款|特别约定)|"
        r"(?:费率|条款).{0,12}(?:未经备案|未按规定使用)"
    ),
    "unauthorized_sales": re.compile(
        r"(?:委托|交由).{0,12}(?:无资质|未取得资质|不具备资质).{0,12}(?:机构|人员|平台).{0,8}(?:销售|推介)"
    ),
    "agent_mismanagement": re.compile(
        r"(?:代理人|营销员).{0,12}(?:管理不到位|失管|违规销售)|"
        r"(?:未对|未能).{0,12}(?:代理人|营销员).{0,8}(?:培训|管理|监督)"
    ),
    "customer_data_fabrication": re.compile(
        r"(?:虚构|伪造|篡改|代填).{0,10}(?:客户|投保人).{0,8}(?:信息|签名|资料)|"
        r"(?:客户|投保人).{0,8}(?:信息|资料).{0,8}(?:不真实|虚假)"
    ),
    "kickback_rebate": re.compile(
        r"(?:返还|返现|返佣|回扣).{0,8}(?:保费|佣金|现金|红包)|"
        r"(?:保费|佣金).{0,8}(?:返还|返现|回扣)"
    ),
    "concealed_terms": re.compile(
        r"(?:不展示|未展示|不告知|未告知|刻意隐瞒|故意隐瞒).{0,18}"
        r"(?:免责|除外|等待期|退保|费用|风险|条款|费率|现金价值)"
    ),
    "competitor_denigration": re.compile(
        r"(?:其他|别家|竞品|同业).{0,10}(?:都是|全是|根本|一定).{0,8}(?:骗人|垃圾|不赔|不靠谱|差)"
    ),
    "unsolicited_telemarketing": re.compile(
        r"(?:未经同意|非法购买|违规获取).{0,16}(?:名单|手机号|联系方式).{0,16}"
        r"(?:拨打|呼叫|电销)|(?:明确拒绝|拒接).{0,16}(?:更换号码|继续呼叫|反复拨打)"
    ),
    "absolute_service_claim": re.compile(r"(?:从不|绝不|保证不).{0,8}(?:拒赔|扯皮|拖延)"),
}

_NEGATION_PREFIX = re.compile(r"(?:不|并非|不是|不得|严禁|禁止|不可|切勿|避免|杜绝)$")
_COMPLIANCE_QUALIFIERS = re.compile(
    r"(?:以(?:保险)?合同|条款为准|不构成(?:收益)?承诺|收益存在不确定|可能亏损|"
    r"须经审核|具体责任.{0,8}以条款为准|不得承诺|严禁宣传)"
)

_LABEL_HINTS: dict[str, re.Pattern[str]] = {
    "欺骗投保人": re.compile(r"骗|冒充|虚假|伪造|存单|储蓄"),
    "销售误导": re.compile(r"误导|存款|存单|稳赚|保本|无风险|不亏|隐瞒"),
    "夸大收益": re.compile(r"收益|回报|分红|翻倍|暴涨"),
    "虚假宣传": re.compile(r"虚假|唯一|首选|国家|监管|万能|全能"),
    "合同外利益": re.compile(r"送|赠|返|补贴|礼品|红包|返现|回扣"),
    "赠送利益": re.compile(r"送|赠|礼品|红包|补贴|体检|加油卡"),
    "回扣返佣": re.compile(r"返佣|回扣|返现|返还保费|佣金"),
    "产品说明会违规": re.compile(r"说明会|答谢会|现场签单"),
    "培训材料违规": re.compile(r"培训|课件|内部话术"),
    "回访违规": re.compile(r"回访|代接|冒充客户"),
    "电销违规": re.compile(r"电销|电话销售|坐席|致电"),
    "不当比较": re.compile(r"比较|超过|碾压|完胜|比银行|比存款"),
    "贬低竞品": re.compile(r"竞品|别家|其他公司|垃圾|骗人|不靠谱"),
    "绝对化表述": re.compile(r"绝对|唯一|百分之百|100%|任何|永远|从不|全部|都赔"),
    "承诺收益": re.compile(r"收益|回报|稳赚|保本|兑付"),
    "保证收益": re.compile(r"保证|确保|保底|最低收益"),
    "弱化风险提示": re.compile(r"零风险|无风险|不亏|不用看|忽略风险"),
    "隐瞒重要信息": re.compile(r"隐瞒|不告知|未告知|不展示|免责|等待期|退保损失"),
    "虚构收益率": re.compile(r"虚构|编造|年化|收益率|演示值"),
    "诱导投保": re.compile(r"限时|仅剩|马上|立即|闭眼|名额|停售|下架|签单"),
    "避债避税": re.compile(r"避债|避税|免税|资产隔离|法院|债权人"),
    "虚列费用套取资金": re.compile(r"发票|列支|套取|会务费|费用|资金"),
    "代理人管理不到位": re.compile(r"代理人|营销员|管理不到位|失管"),
    "委托无资质机构销售": re.compile(r"无资质|未取得资质|委托销售"),
    "未按规定使用费率条款": re.compile(r"备案|费率|条款|特别约定"),
    "客户信息不真实": re.compile(r"客户信息|投保人信息|代签|代填|冒充|虚假资料"),
}

_SCENE_CHANNEL_LABELS: dict[QueryScene, set[str]] = {
    QueryScene.ST1_POSTER_SMS_SOCIAL: {
        "虚假宣传", "绝对化表述", "诱导投保", "赠送利益", "合同外利益"
    },
    QueryScene.ST2_LIVE_SHORT_VIDEO: {
        "虚假宣传", "绝对化表述", "诱导投保", "夸大收益", "承诺收益"
    },
    QueryScene.ST3_PRODUCT_INTRO_DETAIL: {
        "销售误导", "弱化风险提示", "隐瞒重要信息", "夸大收益", "承诺收益"
    },
    QueryScene.ST4_MEETING_MATERIAL: {"产品说明会违规", "诱导投保", "赠送利益"},
    QueryScene.ST5_TRAINING_TELEMARKETING_CALLBACK: {
        "培训材料违规", "回访违规", "电销违规", "客户信息不真实"
    },
    QueryScene.ST6_PENALTY_BACKEND_FACT: {
        "虚列费用套取资金", "代理人管理不到位", "委托无资质机构销售",
        "未按规定使用费率条款", "客户信息不真实",
    },
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
    confidence: float
    stage1_score: float
    stage2_score: float
    risk_labels: tuple[str, ...]
    evidence: tuple[RiskEvidence, ...]
    strong_signal: bool


class RuleRiskDetector:
    """第一阶段组合强规则，第二阶段场景加权关键词累积。"""

    def __init__(self, keyword_path: Path) -> None:
        if not keyword_path.is_file():
            raise FileNotFoundError(f"风险关键词库不存在: {keyword_path}")
        payload = json.loads(keyword_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("风险关键词库必须是 JSON 对象")
        self.version = str(payload.get("version") or "unknown")
        self._keywords = _parse_keyword_rules(payload.get("keywords"))
        self._patterns = _parse_patterns(payload.get("regex_patterns"))
        self._patterns.update(_STRONG_PATTERNS)

    def detect(
        self,
        text: str,
        scene: QueryScene | None = None,
    ) -> RuleDetectionResult:
        normalized = unicodedata.normalize("NFKC", text).casefold()
        if not normalized.strip():
            return RuleDetectionResult(0.0, 0.0, 0.0, 0.0, (), (), False)

        label_scores: dict[str, float] = {}
        stage1_strengths: list[float] = []
        stage2_strengths: list[float] = []
        evidence: list[RiskEvidence] = []
        for name, pattern in self._patterns.items():
            match = pattern.search(normalized)
            if match is None or _is_negated(normalized, match.start()):
                continue
            strength = 0.88 * _scene_factor(REGEX_LABEL_MAP.get(name, ()), scene)
            stage1_strengths.append(min(0.96, strength))
            for label in REGEX_LABEL_MAP.get(name, ("其他",)):
                if label != "其他":
                    label_scores[label] = label_scores.get(label, 0.0) + strength
            evidence.append(
                RiskEvidence(
                    source="rule_regex",
                    description=f"强规则“{name}”命中：{match.group(0)[:80]}",
                )
            )

        seen_keywords: set[str] = set()
        for rule in self._keywords:
            position = normalized.find(rule.keyword)
            if position < 0 or rule.keyword in seen_keywords or _is_negated(normalized, position):
                continue
            seen_keywords.add(rule.keyword)
            base = (
                0.16 + 0.06 * min(rule.priority, 3)
                if rule.source == "curated"
                else 0.06 + 0.025 * min(rule.priority, 3)
            )
            labels = _select_labels(rule)
            if not labels:
                continue
            strength = min(0.45, base * _scene_factor(labels, scene))
            stage2_strengths.append(strength)
            divisor = math.sqrt(len(labels))
            for label in labels:
                label_scores[label] = label_scores.get(label, 0.0) + strength / divisor
            evidence.append(
                RiskEvidence(
                    source="local_stage2",
                    description=(
                        f"场景加权词“{rule.keyword}”（{rule.source}，权重{strength:.2f}）"
                    ),
                )
            )

        stage1_score = _noisy_or(stage1_strengths)
        stage2_score = _noisy_or(sorted(stage2_strengths, reverse=True)[:6])
        qualifier_count = len(_COMPLIANCE_QUALIFIERS.findall(normalized))
        if qualifier_count and not stage1_strengths:
            stage2_score *= max(0.35, 1 - 0.25 * qualifier_count)
        combined = 1 - (1 - stage1_score) * (1 - 0.78 * stage2_score)
        labels = tuple(
            label
            for label, _ in sorted(label_scores.items(), key=lambda item: (-item[1], item[0]))
            if label != "其他"
        )[:8]
        strong_signal = bool(stage1_strengths) or (
            stage2_score >= 0.68 and len(stage2_strengths) >= 3
        )
        confidence = _confidence(stage1_strengths, stage2_strengths, combined, qualifier_count)
        return RuleDetectionResult(
            risk_score=round(min(0.99, combined), 6),
            confidence=round(confidence, 6),
            stage1_score=round(stage1_score, 6),
            stage2_score=round(stage2_score, 6),
            risk_labels=labels,
            evidence=tuple(evidence[:10]),
            strong_signal=strong_signal,
        )


def _confidence(
    stage1: list[float],
    stage2: list[float],
    combined: float,
    qualifier_count: int,
) -> float:
    if stage1:
        return min(0.99, 0.88 + 0.035 * len(stage1))
    if len(stage2) >= 3 and combined >= 0.65:
        return min(0.88, 0.72 + 0.035 * len(stage2))
    if not stage2 and qualifier_count:
        return min(0.88, 0.72 + 0.04 * qualifier_count)
    if not stage2:
        return 0.30
    return min(0.72, 0.45 + 0.06 * len(stage2))


def _scene_factor(labels: tuple[str, ...] | list[str], scene: QueryScene | None) -> float:
    if scene is None:
        return 1.0
    channel_labels = _SCENE_CHANNEL_LABELS[scene]
    return 1.18 if channel_labels.intersection(labels) else 0.92


def _is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 8) : start].rstrip()
    return _NEGATION_PREFIX.search(prefix) is not None


def _noisy_or(strengths: list[float]) -> float:
    remaining = 1.0
    for strength in strengths:
        remaining *= 1 - max(0.0, min(0.99, strength))
    return 1 - remaining


def _select_labels(rule: _KeywordRule) -> tuple[str, ...]:
    if len(rule.risk_labels) <= 4:
        return tuple(label for label in rule.risk_labels if label != "其他")
    inferred = tuple(
        label
        for label in rule.risk_labels
        if label != "其他"
        and (pattern := _LABEL_HINTS.get(label)) is not None
        and pattern.search(rule.keyword)
    )
    if inferred:
        return inferred[:5]
    return rule.risk_labels[:2] if rule.source == "curated" else ()


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
