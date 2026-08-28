"""真实 Query 金标准与多标签评估指标回归测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.evaluate_real_queries import compute_metrics, load_gold_samples  # noqa: E402

GOLD_PATH = PROJECT_ROOT / "tests" / "data" / "real_query_gold.json"


def test_real_query_gold_has_21_verified_samples_without_case_answers() -> None:
    metadata, samples = load_gold_samples(GOLD_PATH)

    assert len(samples) == 21
    assert [sample["sample_id"] for sample in samples] == [
        f"XHS-{index:02d}" for index in range(1, 22)
    ]
    assert sum(not sample["gold_labels"] for sample in samples) == 3
    assert "matched_cases" in metadata["excluded_from_annotation"]
    assert all("matched_cases" not in sample for sample in samples)


def test_multilabel_metrics_match_hand_calculated_example() -> None:
    rows = [
        {"gold_labels": ["A", "B"], "predicted_labels": ["A", "C"]},
        {"gold_labels": [], "predicted_labels": []},
    ]

    metrics = compute_metrics(rows, ["A", "B", "C"])

    assert metrics["micro"]["precision"] == pytest.approx(0.5)
    assert metrics["micro"]["recall"] == pytest.approx(0.5)
    assert metrics["micro"]["f1"] == pytest.approx(0.5)
    assert metrics["exact_match_ratio"] == pytest.approx(0.5)
    assert metrics["hamming_loss"] == pytest.approx(1 / 3)
    assert metrics["binary_risk_detection"]["f1"] == pytest.approx(1.0)
    assert metrics["binary_risk_detection"]["accuracy"] == pytest.approx(1.0)
