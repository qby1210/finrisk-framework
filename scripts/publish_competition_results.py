"""Publish the frozen 200-query label regression and GitHub deliverables."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json

from benchmark_competition500 import risk_metrics
from build_competition_dataset import DATA, ROOT, read_rows, save, write_rows

from risk.taxonomy import LABEL_BOUNDARIES

PUBLIC = ROOT / "reports/competition500"
LOCAL = ROOT / "outputs/competition_upgrade_20261019"
MODE = "deepseek_adaptive"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(name, rows):
    with (PUBLIC / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="label_precision_v2")
    args = parser.parse_args()
    run = LOCAL / "runs" / args.run
    baseline = json.loads((PUBLIC / "baseline_20261019.json").read_text("utf-8"))
    samples = read_rows(DATA / "test.jsonl")
    ids = {r["query_id"] for r in samples}
    gold = {r["query_id"]: r for r in read_rows(DATA / "reference/labels.jsonl")}
    predictions = json.loads((run / f"test_{MODE}.json").read_text("utf-8"))
    assert len(predictions) == 200 and {r["query_id"] for r in predictions} == ids
    current = risk_metrics(predictions, gold, list(LABEL_BOUNDARIES))
    previous = baseline["risk"][MODE]
    longtext = json.loads((run / "longtext_summary.json").read_text("utf-8"))
    assert sha(run / "longtext_inputs.jsonl") == baseline["longtext"]["input_sha256"]
    gate = {
        "label_f1_improved": current["label_micro_f1"] > previous["label_micro_f1"],
        "no_unreviewed_targets": current["missing_model_targets"] == 0,
        "no_request_errors": current["errors"] == 0,
        "all_longtext_risks_detected": all(
            r["risk_queries_detected"] == r["queries"] and r["missing_model_targets"] == 0
            for r in longtext["results"][MODE].values()
        ),
    }
    if not all(gate.values()):
        raise SystemExit("Release checks failed: " + json.dumps(gate))
    by_id = {r["query_id"]: r for r in predictions}
    replay_ids = ["TEST001", "TEST039", "TEST047", "TEST149"]
    report = {
        "available": True,
        "version": "competition500-label-precision-v2-20261019",
        "scope": "closed_500_cases_frozen_reference_regression",
        "selected_mode": MODE,
        "default_config": baseline["default_config"],
        "dataset": {**baseline["dataset"], "development_validation_queries": 100},
        "risk": {"previous": previous, MODE: current},
        "risk_names": {"previous": "优化前 · DeepSeek＋自适应", MODE: "优化后 · DeepSeek＋自适应"},
        "retrieval": baseline["retrieval"],
        "retrieval_measurement_note": "前轮同一200Query的独立检索对照，排序实现未改动。",
        "longtext": {"baseline": baseline["longtext"]["cascade"], "cascade": longtext},
        "release_gate": gate,
        "previous_15_targets": {
            "queries": replay_ids,
            "before_unreviewed": 15,
            "remaining_unreviewed": sum(by_id[q]["missing_model_targets"] for q in replay_ids),
        },
        "timing": baseline["timing"],
        "provenance": {
            "run": args.run,
            "label_reference_sha256": sha(DATA / "reference/labels.jsonl"),
            "test_input_sha256": sha(DATA / "test.jsonl"),
            "test_references_modified_for_this_upgrade": False,
            "test_used_for_training": False,
            "validation_is_development_subset": True,
        },
    }
    save(PUBLIC / "evaluation.json", report)
    save(LOCAL / "public_report.json", report)
    save(run / "test_summary.json", {MODE: current})
    write_rows(
        PUBLIC / "predictions_test200.jsonl",
        [
            {
                k: r.get(k)
                for k in [
                    "query_id",
                    "scene",
                    "decision_state",
                    "risk_labels",
                    "seconds",
                    "missing_model_targets",
                    "error",
                ]
            }
            for r in sorted(predictions, key=lambda r: r["query_id"])
        ],
    )
    write_csv(
        "风险分类前后对照.csv",
        [
            {
                "版本": name,
                "风险准确率": r["risk_binary_accuracy"],
                "三态准确率": r["state_accuracy"],
                "标签MicroF1": r["label_micro_f1"],
                "标签MacroF1": r["label_macro_f1"],
                "中位秒": r["median_seconds"],
                "P95秒": r["p95_seconds"],
                "未复核句": r["missing_model_targets"],
            }
            for name, r in [("优化前", previous), ("优化后", current)]
        ],
    )
    label_rows = []
    for label, values in current["per_label"].items():
        old = previous["per_label"][label]
        label_rows.append(
            {
                "标签": label,
                "支持数": values["support"],
                "原FP": old["fp"],
                "新FP": values["fp"],
                "原FN": old["fn"],
                "新FN": values["fn"],
                "原F1": old["f1"],
                "新F1": values["f1"],
            }
        )
    write_csv("27标签漏判误判对照.csv", label_rows)
    submissions = []
    for sample in samples:
        row = by_id[sample["query_id"]]
        result = row.get("result", {})
        suggestions = list(
            dict.fromkeys(
                text
                for a in result.get("risk_assessments", [])
                for text in a.get("remediation_suggestions", [])
            )
        )
        cases = result.get("risk_summary", {}).get("top_matched_cases", [])
        submissions.append(
            {
                "question_id": sample["query_id"],
                "risk_type": "；".join(row["risk_labels"]),
                "retrieved_cases": [
                    {"case_id": c["case_id"], "rank": i + 1, "reason": c["match_reason"]}
                    for i, c in enumerate(cases)
                ],
                "suggestion": "；".join(suggestions),
            }
        )
    write_rows(PUBLIC / "submission.jsonl", submissions)
    lines = [
        "# FinRisk 27标签优化与真实API复测（2026-10-19）",
        "",
        "固定27标签、六Query场景及Pi底层；默认DeepSeek重排＋自适应Pre/Post。",
        "",
        "本轮扩大结构化输出预算，约束证据编号，增加启动超时受限重试；补查只重送未完成目标。",
        "区分未涉及机制与需事实支撑的负向结论。27类分别给出成立与排除条件，"
        "停止把近义/上位标签自动并入结论；强规则命中多个候选时仍由模型核准标签。",
        "增加未经批准设立职场的明确事实规则。",
        "运行依赖精简为25份固定P0数据，去除旧Python、旧查询及重复reader；"
        "补齐24条依赖条文缺少顶层位置字段时的原文回源。",
        "",
        "## 固定200Query回归",
        "",
        "同一500案例池、同一200Query和冻结银标参考，没有改写答案。400开发Query用于拟合和调试；"
        "100条validation是开发子集，独立效果以200条源文书分离的test为准。",
        "",
        "| 版本 | 风险准确率 | 三态准确率 | 标签Micro-F1 | 标签Macro-F1 | "
        "中位秒 | P95秒 | 未复核句 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, v in [("优化前", previous), ("优化后", current)]:
        lines.append(
            f"| {name} | {v['risk_binary_accuracy']:.1%} | {v['state_accuracy']:.1%} | "
            f"{v['label_micro_f1']:.3f} | {v['label_macro_f1']:.3f} | {v['median_seconds']:.2f} | "
            f"{v['p95_seconds']:.2f} | {v['missing_model_targets']} |"
        )
    old_fp = sum(r["fp"] for r in previous["per_label"].values())
    new_fp = sum(r["fp"] for r in current["per_label"].values())
    old_fn = sum(r["fn"] for r in previous["per_label"].values())
    new_fn = sum(r["fn"] for r in current["per_label"].values())
    lines += [
        "",
        f"标签误判FP：{old_fp}→{new_fp}；漏判FN：{old_fn}→{new_fn}，按标签计数。",
        "本轮F1提升主要来自误判减少，标签漏判并未同步下降，尚未解决全部27类识别问题。"
        "逐条核对也发现银标存在漏标和边界不一致，因此保留原答案和逐标签计数，"
        "不以改写参考答案提高回归分数。",
        "",
        "## 长文本回归",
        "",
        "同一12条合成长文覆盖六场景和风险首中尾位置，每档6条。",
        "",
        "| 版本 | 字数档 | 中位秒 | P95秒 | 风险检出 | 未复核句 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, part in [("优化前", baseline["longtext"]["cascade"]), ("优化后", longtext)]:
        for length, v in part["results"][MODE].items():
            lines.append(
                f"| {name} | {length} | {v['median_seconds']:.2f} | {v['p95_seconds']:.2f} | "
                f"{v['risk_queries_detected']}/{v['queries']} | {v['missing_model_targets']} |"
            )
    lines += [
        "",
        "## 数据、清理和交付",
        "",
        "新500案例、400开发、100开发核对子集、200测试及参考标注随项目发布。"
        "旧效果集、旧入口与无用历史报告已清理。源码、功能回归及公开评测摘要进入GitHub；"
        "密钥、原始PDF、全量索引、备份和API过程文件保留本地，服务器不部署。",
        "",
        "机器指标在reports/competition500/evaluation.json，逐标签FP/FN及预测JSONL在同目录。"
        "排序实现未改动，页面独立检索表沿用前轮固定Query对照。",
    ]
    (ROOT / "docs/competition_upgrade_20261019.md").write_text("\n".join(lines) + "\n", "utf-8")
    save(
        PUBLIC / "dataset_hashes.json",
        {
            name: sha(DATA / name)
            for name in [
                "cases.jsonl",
                "development.jsonl",
                "validation.jsonl",
                "test.jsonl",
                "reference/labels.jsonl",
                "reference/qrels_development.jsonl",
                "reference/qrels_test.jsonl",
            ]
        },
    )
    print(
        json.dumps(
            {
                "before_f1": previous["label_micro_f1"],
                "after_f1": current["label_micro_f1"],
                "before_fp": old_fp,
                "after_fp": new_fp,
                "before_fn": old_fn,
                "after_fn": new_fn,
                "release_gate": gate,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
