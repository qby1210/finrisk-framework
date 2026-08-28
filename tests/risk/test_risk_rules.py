"""队员风险词库与修复后阈值的最小行为测试。"""

from pathlib import Path

from domain.risk_models import RiskLevel
from risk.calibration import RiskScorer, RiskThresholder
from risk.detection import RuleRiskDetector

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
