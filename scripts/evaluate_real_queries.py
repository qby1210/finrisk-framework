"""在人工语义金标准上评估 FinRisk 文档级多标签风险识别。"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from statistics import fmean

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from application.analysis_service import QueryAnalysisService  # noqa: E402
from application.query_service import QueryProcessingService  # noqa: E402
from application.retrieval_service import CaseRetrievalService  # noqa: E402
from llm import create_llm_client_from_env  # noqa: E402
from query.classification import QuerySceneClassifier  # noqa: E402
from risk.detection import RuleRiskDetector  # noqa: E402
from risk.pipeline import RiskAssessmentPipeline  # noqa: E402
from risk.taxonomy import load_taxonomy_descriptions  # noqa: E402
from settings import AppSettings  # noqa: E402
from storage.case_repository import CaseRepository  # noqa: E402

DEFAULT_GOLD_PATH = PROJECT_ROOT / "tests" / "data" / "real_query_gold.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "real_query_evaluation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="评估 21 条真实文案的文档级多标签风险识别")
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD_PATH)
    parser.add_argument("--mode", choices=("local", "full"), default="full")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def load_gold_samples(gold_path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    payload = json.loads(gold_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
        raise ValueError("金标准必须是包含 samples 数组的 JSON 对象")
    source_path = PROJECT_ROOT / str(payload["source_file"])
    source_lines = source_path.read_text(encoding="utf-8").splitlines()
    samples: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for raw_sample in payload["samples"]:
        if not isinstance(raw_sample, dict):
            raise ValueError("samples 中存在非对象记录")
        sample = dict(raw_sample)
        sample_id = str(sample["sample_id"])
        if sample_id in seen_ids:
            raise ValueError(f"重复 sample_id: {sample_id}")
        seen_ids.add(sample_id)
        start = int(sample["source_start_line"])
        end = int(sample["source_end_line"])
        text = "\n".join(source_lines[start - 1 : end]).strip()
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest != sample["text_sha256"]:
            raise ValueError(f"{sample_id} 原文 SHA-256 与金标准不一致")
        sample["text"] = text
        sample["gold_labels"] = [str(label) for label in sample.get("gold_labels", [])]
        samples.append(sample)
    expected_count = int(payload.get("source_case_count") or 0)
    if expected_count and len(samples) != expected_count:
        raise ValueError(f"金标准样本数应为 {expected_count}，实际 {len(samples)}")
    return payload, samples


def load_label_order(dictionary_path: Path) -> list[str]:
    with dictionary_path.open(encoding="utf-8-sig", newline="") as handle:
        labels = [str(row["risk_tag"]) for row in csv.DictReader(handle) if row.get("risk_tag")]
    if not labels:
        raise ValueError(f"风险类型字典为空: {dictionary_path}")
    return labels


def build_service(mode: str) -> tuple[QueryAnalysisService, list[str]]:
    load_dotenv(PROJECT_ROOT / ".env")
    settings = AppSettings.from_env()
    repository = CaseRepository(settings)
    llm_client = create_llm_client_from_env() if mode == "full" else None
    if mode == "full" and llm_client is None:
        raise RuntimeError("full 模式需要在 .env 配置 DEEPSEEK_API_KEY")
    retrieval = CaseRetrievalService(repository)
    pipeline = RiskAssessmentPipeline(
        rule_detector=RuleRiskDetector(settings.risk_keyword_path),
        retrieval_service=retrieval,
        taxonomy=repository.risk_dictionary(),
        llm_client=llm_client,
        taxonomy_descriptions=load_taxonomy_descriptions(settings.risk_dictionary_path),
        risk_display_threshold=settings.risk_display_threshold,
        retrieval_threshold=settings.retrieval_risk_threshold,
    )
    service = QueryAnalysisService(
        query_service=QueryProcessingService(classifier=QuerySceneClassifier(llm_client)),
        risk_pipeline=pipeline,
    )
    return service, list(repository.risk_dictionary())


def _safe_div(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": _safe_div(2 * precision * recall, precision + recall),
    }


def compute_metrics(
    rows: Iterable[dict[str, object]],
    label_order: list[str],
) -> dict[str, object]:
    materialized = list(rows)
    if not materialized:
        raise ValueError("没有可评估样本")
    label_set = set(label_order)
    per_label: list[dict[str, object]] = []
    total_tp = total_fp = total_fn = 0
    sample_precisions: list[float] = []
    sample_recalls: list[float] = []
    sample_f1s: list[float] = []
    exact_matches = 0
    hamming_errors = 0
    binary_tp = binary_fp = binary_fn = binary_tn = 0

    for row in materialized:
        gold = set(str(label) for label in row.get("gold_labels", []))
        predicted = set(str(label) for label in row.get("predicted_labels", []))
        unknown = (gold | predicted) - label_set
        if unknown:
            raise ValueError(f"出现字典外标签: {sorted(unknown)}")
        tp = len(gold & predicted)
        fp = len(predicted - gold)
        fn = len(gold - predicted)
        sample_metric = _prf(tp, fp, fn)
        if not gold and not predicted:
            sample_metric.update({"precision": 1.0, "recall": 1.0, "f1": 1.0})
        sample_precisions.append(float(sample_metric["precision"]))
        sample_recalls.append(float(sample_metric["recall"]))
        sample_f1s.append(float(sample_metric["f1"]))
        exact_matches += int(gold == predicted and not row.get("error"))
        hamming_errors += len(gold ^ predicted)
        gold_risky = bool(gold)
        predicted_risky = bool(predicted)
        binary_tp += int(gold_risky and predicted_risky)
        binary_fp += int(not gold_risky and predicted_risky)
        binary_fn += int(gold_risky and not predicted_risky)
        binary_tn += int(not gold_risky and not predicted_risky)

    for label in label_order:
        support = sum(label in set(row.get("gold_labels", [])) for row in materialized)
        predicted_count = sum(
            label in set(row.get("predicted_labels", [])) for row in materialized
        )
        tp = sum(
            label in set(row.get("gold_labels", []))
            and label in set(row.get("predicted_labels", []))
            for row in materialized
        )
        metric = _prf(tp, predicted_count - tp, support - tp)
        metric.update({"label": label, "support": support, "predicted": predicted_count})
        per_label.append(metric)
        total_tp += int(metric["tp"])
        total_fp += int(metric["fp"])
        total_fn += int(metric["fn"])

    supported = [row for row in per_label if int(row["support"]) > 0]
    micro = _prf(total_tp, total_fp, total_fn)
    binary = _prf(binary_tp, binary_fp, binary_fn)
    binary.update(
        {
            "tn": binary_tn,
            "accuracy": _safe_div(binary_tp + binary_tn, len(materialized)),
        }
    )
    return {
        "sample_count": len(materialized),
        "label_count": len(label_order),
        "supported_label_count": len(supported),
        "micro": micro,
        "macro_supported": {
            "precision": fmean(float(row["precision"]) for row in supported),
            "recall": fmean(float(row["recall"]) for row in supported),
            "f1": fmean(float(row["f1"]) for row in supported),
        },
        "samples_average": {
            "precision": fmean(sample_precisions),
            "recall": fmean(sample_recalls),
            "f1": fmean(sample_f1s),
        },
        "exact_match_ratio": _safe_div(exact_matches, len(materialized)),
        "hamming_loss": _safe_div(hamming_errors, len(materialized) * len(label_order)),
        "binary_risk_detection": binary,
        "per_label": per_label,
    }


def _ordered_labels(values: Iterable[str], label_order: list[str]) -> list[str]:
    selected = set(values)
    return [label for label in label_order if label in selected]


def _failed_row(
    sample: dict[str, object],
    gold_labels: list[str],
    error: Exception,
) -> dict[str, object]:
    message = str(error)
    return {
        "sample_id": sample["sample_id"],
        "title": sample["title"],
        "source_start_line": sample["source_start_line"],
        "source_end_line": sample["source_end_line"],
        "text_sha256": sample["text_sha256"],
        "gold_labels": gold_labels,
        "predicted_labels": [],
        "missing_labels": gold_labels,
        "extra_labels": [],
        "exact_match": False,
        "gold_is_risky": bool(gold_labels),
        "predicted_is_risky": False,
        "scene": None,
        "overall_score": None,
        "overall_level": None,
        "llm_used": False,
        "warnings": [message],
        "risky_sentences": [],
        "error": {"type": type(error).__name__, "message": message},
    }


async def evaluate(
    *,
    gold_path: Path,
    mode: str,
    output_path: Path,
    limit: int = 0,
) -> dict[str, object]:
    gold_meta, samples = load_gold_samples(gold_path)
    if limit:
        samples = samples[:limit]
    service, runtime_labels = build_service(mode)
    dictionary_path = PROJECT_ROOT / str(gold_meta["label_dictionary_snapshot"])
    label_order = load_label_order(dictionary_path)
    if set(runtime_labels) != set(label_order):
        raise ValueError("系统运行标签与金标准标签字典不一致")

    results: list[dict[str, object]] = []
    for index, sample in enumerate(samples, start=1):
        gold_labels = _ordered_labels(sample["gold_labels"], label_order)
        try:
            result = await service.process_text(
                str(sample["text"]),
                metadata={
                    "evaluation": "real_query_gold_v1",
                    "sample_id": sample["sample_id"],
                },
            )
        except Exception as error:
            row = _failed_row(sample, gold_labels, error)
            results.append(row)
            print(
                f"[{index:02d}/{len(samples):02d}] {sample['sample_id']} "
                f"ERROR {type(error).__name__}: {error}"
            )
            continue
        risky_sentences = [
            {
                "sentence_id": item.sentence_id,
                "text": item.text,
                "risk_score": item.risk_score,
                "risk_labels": _ordered_labels(item.risk_labels, label_order),
                "reasoning": item.reasoning,
            }
            for item in result.risk_assessments
            if item.risk_score >= 0.2 or item.risk_labels
        ]
        predicted_labels = _ordered_labels(
            (
                label
                for item in result.risk_assessments
                if item.risk_score >= 0.2
                for label in item.risk_labels
            ),
            label_order,
        )
        row = {
            "sample_id": sample["sample_id"],
            "title": sample["title"],
            "source_start_line": sample["source_start_line"],
            "source_end_line": sample["source_end_line"],
            "text_sha256": sample["text_sha256"],
            "gold_labels": gold_labels,
            "predicted_labels": predicted_labels,
            "missing_labels": _ordered_labels(
                set(gold_labels) - set(predicted_labels),
                label_order,
            ),
            "extra_labels": _ordered_labels(
                set(predicted_labels) - set(gold_labels),
                label_order,
            ),
            "exact_match": set(gold_labels) == set(predicted_labels),
            "gold_is_risky": bool(gold_labels),
            "predicted_is_risky": bool(predicted_labels),
            "scene": result.classification.scene.value,
            "overall_score": result.risk_summary.overall_score,
            "overall_level": result.risk_summary.overall_level.value,
            "llm_used": result.risk_summary.llm_used,
            "warnings": result.risk_summary.warnings,
            "risky_sentences": risky_sentences,
        }
        results.append(row)
        print(
            f"[{index:02d}/{len(samples):02d}] {sample['sample_id']} "
            f"gold={len(gold_labels)} pred={len(predicted_labels)} "
            f"missing={len(row['missing_labels'])} extra={len(row['extra_labels'])}"
        )

    metrics = compute_metrics(results, label_order)
    metrics["failed_sample_count"] = sum(bool(row.get("error")) for row in results)
    report = {
        "schema_version": "real_query_evaluation_v1",
        "mode": mode,
        "gold_path": str(gold_path.relative_to(PROJECT_ROOT)),
        "ignored_outputs": ["matched_cases", "case_retrieval_answers"],
        "metrics": metrics,
        "samples": results,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main() -> None:
    args = parse_args()
    output = args.output or DEFAULT_OUTPUT_DIR / f"evaluation_{args.mode}.json"
    report = asyncio.run(
        evaluate(
            gold_path=args.gold.resolve(),
            mode=args.mode,
            output_path=output.resolve(),
            limit=args.limit,
        )
    )
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"报告已写入: {output.resolve()}")


if __name__ == "__main__":
    main()
