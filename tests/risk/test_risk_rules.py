"""队员风险词库与修复后阈值的最小行为测试。"""

from pathlib import Path

from domain.risk_models import RiskLevel
from risk.calibration import RiskScorer, RiskThresholder
from risk.detection import RuleRiskDetector
from risk.pipeline import _explicit_content_labels, _looks_like_noncompliant_training_guidance

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_real_keyword_database_detects_guaranteed_return() -> None:
    detector = RuleRiskDetector(
        PROJECT_ROOT / "data" / "risk" / "keyword_db" / "risk_keyword_db.json"
    )

    result = detector.detect("这款产品百分之百保证收益，不存在任何亏损风险。")

    assert result.risk_score >= 0.8
    assert "承诺收益" in result.risk_labels
    assert any(value.source == "rule_regex" for value in result.evidence)


def test_fallback_fusion_and_all_threshold_branches_are_reachable() -> None:
    scorer = RiskScorer()
    thresholder = RiskThresholder()

    assert scorer.fuse(1.0, 0.0, None) == 1.0
    assert thresholder.judge(0.90).level == RiskLevel.HIGH
    assert thresholder.judge(0.70).level == RiskLevel.MEDIUM
    assert thresholder.judge(0.50).level == RiskLevel.REVIEW
    assert thresholder.judge(0.25).level == RiskLevel.LOW
    assert thresholder.judge(0.10).level == RiskLevel.NONE


def test_explicit_content_labels_detect_fabricated_yield_without_overlabeling() -> None:
    positives = (
        "收益直接按12%写进合同，今天确认即可。",
        "过去三年平均收益8.8%，未来也会保持同样区间。",
        "年度补贴默认当成产品收益。",
        "内部加息名额实际上并不存在。",
        "复利滚存预计可达5.6%。",
        "5.6%由销售团队手工测算，并非产品历史结算利率。",
    )

    assert all(_explicit_content_labels(text) == ["虚构收益率"] for text in positives)
    assert _explicit_content_labels("合同载明保证利率2.5%，非保证利益可能波动。") == []
    assert _explicit_content_labels("历史结算利率为3.0%，不代表未来收益。") == []


def test_training_channel_requires_noncompliant_guidance_evidence() -> None:
    risky = "话术不要直接说百分之八，可以改成几年后通常能多出一套家电钱。"
    compliant = "坐席必须使用已审批脚本，如实说明演示收益不代表未来结果。"

    assert _looks_like_noncompliant_training_guidance(risky)
    assert not _looks_like_noncompliant_training_guidance(compliant)