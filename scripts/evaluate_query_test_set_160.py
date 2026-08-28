"""评估人工审核后的 data/raw/query/query_test_set_160.json 完整 Query 分析链。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import fmean, median
from time import perf_counter

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

DEFAULT_DATASET = PROJECT_ROOT / "data" / "raw" / "query" / "query_test_set_160.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "query_test_set_160"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="评估160条人工审核六场景、多标签Query测试集")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--mode", choices=("full", "local"), default="full")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="保留现有报告中的成功样本，仅重试失败或缺失样本",
    )
    return parser.parse_args()


def load_dataset(path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("samples"), list):
        raise ValueError("测试集必须是包含 samples 数组的 JSON 对象")
    samples: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in payload["samples"]:
        if not isinstance(raw, dict):
            raise ValueError("samples 中存在非对象记录")
        sample = dict(raw)
        sample_id = str(sample.get("query_id") or "")
        if not sample_id or sample_id in seen:
            raise ValueError(f"测试集存在空或重复 query_id: {sample_id}")
        seen.add(sample_id)
        sample["query"] = str(sample.get("query") or "")
        sample["risk_labels"] = [str(label) for label in sample.get("risk_labels", [])]
        samples.append(sample)
    expected = int(dict(payload.get("statistics") or {}).get("total") or 0)
    if expected and expected != len(samples):
        raise ValueError(f"测试集声明 {expected} 条，实际 {len(samples)} 条")
    return payload, samples


def build_service(mode: str) -> tuple[QueryAnalysisService, CaseRetrievalService, tuple[str, ...]]:
    load_dotenv(PROJECT_ROOT / ".env")
    settings = AppSettings.from_env()
    repository = CaseRepository(settings)
    llm_client = create_llm_client_from_env() if mode == "full" else None
    if mode == "full" and llm_client is None:
        raise RuntimeError("full 模式需要在 .env 配置 DEEPSEEK_API_KEY")
    retrieval = CaseRetrievalService(repository)
    taxonomy = repository.risk_dictionary()
    pipeline = RiskAssessmentPipeline(
        rule_detector=RuleRiskDetector(settings.risk_keyword_path),
        retrieval_service=retrieval,
        taxonomy=taxonomy,
        llm_client=llm_client,
        taxonomy_descriptions=load_taxonomy_descriptions(settings.risk_dictionary_path),
        risk_display_threshold=settings.risk_display_threshold,
        retrieval_threshold=settings.retrieval_risk_threshold,
    )
    service = QueryAnalysisService(
        query_service=QueryProcessingService(classifier=QuerySceneClassifier(llm_client)),
        risk_pipeline=pipeline,
    )
    return service, retrieval, taxonomy


async def evaluate_sample(
    sample: dict[str, object],
    service: QueryAnalysisService,
    semaphore: asyncio.Semaphore,
) -> dict[str, object]:
    queued_at = perf_counter()
    processing_started: float | None = None
    try:
        async with semaphore:
            processing_started = perf_counter()
            result = await service.process_text(
                str(sample["query"]),
                metadata={"evaluation_id": str(sample["query_id"])},
            )
        return {
            "query_id": sample["query_id"],
            "length_bucket": sample.get("length_bucket"),
            "query": sample["query"],
            "gold_scene": sample["scene"],
            "predicted_scene": result.classification.scene.value,
            "scene_method": result.classification.method.value,
            "scene_confidence": result.classification.confidence,
            "gold_risk": sample["overall_risk"],
            "predicted_risk": (
                "有风险"
                if result.risk_summary.overall_score >= result.risk_summary.risk_display_threshold
                else "无风险"
            ),
            "overall_score": result.risk_summary.overall_score,
            "overall_level": result.risk_summary.overall_level.value,
            "gold_labels": sample["risk_labels"],
            "predicted_labels": result.risk_summary.risk_labels,
            "llm_used": result.risk_summary.llm_used,
            "llm_reviewed_sentences": result.risk_summary.llm_reviewed_sentence_count,
            "local_direct_sentences": result.risk_summary.local_direct_sentence_count,
            "retrieval_sentences": result.risk_summary.retrieval_sentence_count,
            "top_case_ids": [case.case_id for case in result.risk_summary.top_matched_cases],
            "sentence_count": result.risk_summary.sentence_count,
            "stage_timings_ms": result.stage_timings_ms,
            "risk_stage_timings_ms": result.risk_summary.stage_timings_ms,
            "processing_seconds": round(perf_counter() - processing_started, 4),
            "queue_wait_seconds": round(processing_started - queued_at, 4),
            "total_seconds": round(perf_counter() - queued_at, 4),
            "error": None,
        }
    except Exception as error:  # noqa: BLE001 - 评测需要保留单条错误并继续
        return {
            "query_id": sample.get("query_id"),
            "length_bucket": sample.get("length_bucket"),
            "query": sample.get("query"),
            "gold_scene": sample.get("scene"),
            "predicted_scene": None,
            "gold_risk": sample.get("overall_risk"),
            "predicted_risk": None,
            "gold_labels": sample.get("risk_labels", []),
            "predicted_labels": [],
            "stage_timings_ms": {},
            "risk_stage_timings_ms": {},
            "processing_seconds": round(perf_counter() - (processing_started or queued_at), 4),
            "queue_wait_seconds": round((processing_started or queued_at) - queued_at, 4),
            "total_seconds": round(perf_counter() - queued_at, 4),
            "error": f"{type(error).__name__}: {error}",
        }


def safe_div(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def prf(tp: int, fp: int, fn: int) -> dict[str, float | int]:
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": safe_div(2 * precision * recall, precision + recall),
    }


def compute_metrics(rows: list[dict[str, object]], taxonomy: tuple[str, ...]) -> dict[str, object]:
    valid = [row for row in rows if not row.get("error")]
    errors = [row for row in rows if row.get("error")]
    scene_correct = sum(row["gold_scene"] == row["predicted_scene"] for row in valid)
    scene_confusion: dict[str, Counter[str]] = defaultdict(Counter)
    binary_tp = binary_fp = binary_fn = binary_tn = 0
    total_tp = total_fp = total_fn = 0
    exact = 0
    jaccards: list[float] = []
    per_label_counts: dict[str, Counter[str]] = {label: Counter() for label in taxonomy}

    for row in valid:
        scene_confusion[str(row["gold_scene"])][str(row["predicted_scene"])] += 1
        gold_risk = row["gold_risk"] == "有风险"
        predicted_risk = row["predicted_risk"] == "有风险"
        binary_tp += int(gold_risk and predicted_risk)
        binary_fp += int(not gold_risk and predicted_risk)
        binary_fn += int(gold_risk and not predicted_risk)
        binary_tn += int(not gold_risk and not predicted_risk)

        gold = set(str(value) for value in row.get("gold_labels", []))
        predicted = set(str(value) for value in row.get("predicted_labels", []))
        exact += int(gold == predicted)
        union = gold | predicted
        jaccards.append(len(gold & predicted) / len(union) if union else 1.0)
        total_tp += len(gold & predicted)
        total_fp += len(predicted - gold)
        total_fn += len(gold - predicted)
        for label in taxonomy:
            per_label_counts[label]["tp"] += int(label in gold and label in predicted)
            per_label_counts[label]["fp"] += int(label not in gold and label in predicted)
            per_label_counts[label]["fn"] += int(label in gold and label not in predicted)
            per_label_counts[label]["support"] += int(label in gold)

    per_label = []
    for label in taxonomy:
        counts = per_label_counts[label]
        metric = prf(counts["tp"], counts["fp"], counts["fn"])
        metric.update({"label": label, "support": counts["support"]})
        per_label.append(metric)
    supported = [item for item in per_label if int(item["support"]) > 0]
    latencies = sorted(float(row["processing_seconds"]) for row in valid)
    queue_waits = [float(row["queue_wait_seconds"]) for row in valid]
    p95_index = max(0, math_ceil(0.95 * len(latencies)) - 1) if latencies else 0
    stage_keys = (
        "query_preparation",
        "local_rules",
        "llm_review",
        "case_retrieval",
        "aggregate",
        "total",
    )
    mean_stage_ms: dict[str, float] = {}
    for key in stage_keys:
        values = []
        for row in valid:
            container_name = (
                "stage_timings_ms" if key == "query_preparation" else "risk_stage_timings_ms"
            )
            container = dict(row.get(container_name) or {})
            if key in container:
                values.append(float(container[key]))
        mean_stage_ms[key] = fmean(values) if values else 0.0
    return {
        "requested_samples": len(rows),
        "successful_samples": len(valid),
        "error_count": len(errors),
        "errors": [{"query_id": row["query_id"], "error": row["error"]} for row in errors],
        "scene": {
            "accuracy": safe_div(scene_correct, len(valid)),
            "correct": scene_correct,
            "confusion": {gold: dict(values) for gold, values in scene_confusion.items()},
        },
        "binary_risk": {
            **prf(binary_tp, binary_fp, binary_fn),
            "tn": binary_tn,
            "accuracy": safe_div(binary_tp + binary_tn, len(valid)),
        },
        "multilabel": {
            "micro": prf(total_tp, total_fp, total_fn),
            "macro_supported_f1": (
                fmean(float(item["f1"]) for item in supported) if supported else 0.0
            ),
            "exact_match": safe_div(exact, len(valid)),
            "mean_jaccard": fmean(jaccards) if jaccards else 0.0,
            "per_label": per_label,
        },
        "runtime": {
            "mean_seconds": fmean(latencies) if latencies else 0.0,
            "median_seconds": median(latencies) if latencies else 0.0,
            "p95_seconds": latencies[p95_index] if latencies else 0.0,
            "mean_queue_wait_seconds": fmean(queue_waits) if queue_waits else 0.0,
            "mean_stage_ms": mean_stage_ms,
            "llm_used_samples": sum(bool(row.get("llm_used")) for row in valid),
            "retrieval_sentences": sum(int(row.get("retrieval_sentences") or 0) for row in valid),
        },
    }


def math_ceil(value: float) -> int:
    integer = int(value)
    return integer if value == integer else integer + 1


def render_markdown(report: dict[str, object]) -> str:
    metrics = dict(report["metrics"])
    scene = dict(metrics["scene"])
    binary = dict(metrics["binary_risk"])
    multilabel = dict(metrics["multilabel"])
    micro = dict(multilabel["micro"])
    runtime = dict(metrics["runtime"])
    rows = list(report["rows"])
    lines = [
        "# Query Test Set 160 评测报告",
        "",
        f"- 模式：`{report['mode']}`",
        f"- 样本：{metrics['successful_samples']} / {metrics['requested_samples']}",
        f"- 场景准确率：{float(scene['accuracy']):.2%}",
        (
            f"- 风险二分类：Precision {float(binary['precision']):.2%} / "
            f"Recall {float(binary['recall']):.2%} / F1 {float(binary['f1']):.2%}"
        ),
        f"- 多标签 Micro-F1：{float(micro['f1']):.2%}",
        f"- 多标签完全匹配：{float(multilabel['exact_match']):.2%}",
        (
            f"- 平均 / P95 延迟：{float(runtime['mean_seconds']):.2f}s / "
            f"{float(runtime['p95_seconds']):.2f}s"
        ),
        (
            "- 平均阶段耗时：准备 {preparation:.0f}ms / 本地规则 {local:.0f}ms / "
            "LLM {llm:.0f}ms / 检索 {retrieval:.0f}ms"
        ).format(
            preparation=float(dict(runtime["mean_stage_ms"])["query_preparation"]),
            local=float(dict(runtime["mean_stage_ms"])["local_rules"]),
            llm=float(dict(runtime["mean_stage_ms"])["llm_review"]),
            retrieval=float(dict(runtime["mean_stage_ms"])["case_retrieval"]),
        ),
        f"- 索引预热：{float(report['index_build_seconds']):.2f}s",
        f"- 160条整批墙钟时间：{float(report['evaluation_wall_seconds']):.2f}s",
        f"- 错误数：{metrics['error_count']}",
        "",
        "## 样本明细",
        "",
        "| ID | 场景 | 风险 | 分数 | 标签命中 | 延迟 | 错误 |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        gold = set(str(value) for value in row.get("gold_labels", []))
        predicted = set(str(value) for value in row.get("predicted_labels", []))
        label_hits = len(gold & predicted)
        lines.append(
            (
                "| {query_id} | {scene} | {risk} | {score} | {hits}/{total} | "
                "{latency:.2f}s | {error} |"
            ).format(
                query_id=row.get("query_id"),
                scene="✓" if row.get("gold_scene") == row.get("predicted_scene") else "✗",
                risk="✓" if row.get("gold_risk") == row.get("predicted_risk") else "✗",
                score=f"{float(row.get('overall_score') or 0):.2f}",
                hits=label_hits,
                total=len(gold),
                latency=float(row.get("processing_seconds") or 0),
                error=str(row.get("error") or ""),
            )
        )
    return "\n".join(lines) + "\n"


async def async_main(args: argparse.Namespace) -> int:
    dataset_meta, selected_samples = load_dataset(args.dataset)
    if args.limit > 0:
        selected_samples = selected_samples[: args.limit]
    if args.concurrency < 1 or args.concurrency > 8:
        raise ValueError("concurrency 必须在1到8之间")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"evaluation_{args.mode}.json"
    markdown_path = args.output_dir / f"evaluation_{args.mode}.md"
    dataset_path = args.dataset.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    previous_report: dict[str, object] | None = None
    preserved_rows: dict[str, dict[str, object]] = {}
    if args.resume and json_path.exists():
        loaded_report = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(loaded_report, dict) or loaded_report.get("dataset") != dataset_path:
            raise ValueError("现有报告的数据集与本次评测不一致，不能断点续跑")
        loaded_rows = loaded_report.get("rows")
        if not isinstance(loaded_rows, list):
            raise ValueError("现有报告缺少 rows 数组，不能断点续跑")
        previous_report = loaded_report
        preserved_rows = {
            str(row["query_id"]): row
            for row in loaded_rows
            if isinstance(row, dict) and row.get("query_id") and not row.get("error")
        }

    samples = [
        sample for sample in selected_samples if str(sample["query_id"]) not in preserved_rows
    ]
    if args.resume:
        print(f"断点续跑：保留 {len(preserved_rows)} 条成功结果，重试 {len(samples)} 条")

    service, retrieval, taxonomy = build_service(args.mode)
    index_started = perf_counter()
    await asyncio.to_thread(retrieval.rebuild)
    index_seconds = perf_counter() - index_started
    semaphore = asyncio.Semaphore(args.concurrency)
    evaluation_started = perf_counter()
    new_rows = await asyncio.gather(
        *(evaluate_sample(sample, service, semaphore) for sample in samples)
    )
    evaluation_wall_seconds = perf_counter() - evaluation_started
    rows_by_id = dict(preserved_rows)
    rows_by_id.update({str(row["query_id"]): row for row in new_rows})
    rows = [rows_by_id[str(sample["query_id"])] for sample in selected_samples]
    previous_wall_seconds = (
        float(str(previous_report.get("evaluation_wall_seconds") or 0.0))
        if previous_report
        else 0.0
    )
    report = {
        "schema_version": "query_test_set_evaluation_v2",
        "mode": args.mode,
        "dataset": dataset_path,
        "dataset_schema_version": dataset_meta.get("schema_version"),
        "index_build_seconds": round(index_seconds, 4),
        "evaluation_wall_seconds": round(previous_wall_seconds + evaluation_wall_seconds, 4),
        "resume_count": (
            int(str(previous_report.get("resume_count") or 0)) + 1 if previous_report else 0
        ),
        "metrics": compute_metrics(rows, taxonomy),
        "rows": rows,
    }
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")
    return 0 if not dict(report["metrics"])["error_count"] else 1


def main() -> int:
    return asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
