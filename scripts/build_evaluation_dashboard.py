"""Build the public evaluation snapshot from frozen runs, without calling any model."""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from benchmark_competition500 import ranking_metrics, risk_metrics  # noqa: E402

RUNS = ROOT / "outputs/competition_upgrade_20261019/runs"
DEST = ROOT / "reports/evaluation_dashboard/evaluation.json"
SELECTED = "status_20261024_baseline"
STATES = ("risk", "no_clear_risk", "insufficient_information")


def read(path):
    return json.loads(path.read_text("utf-8"))


def rows(path):
    return [json.loads(line) for line in path.read_text("utf-8-sig").splitlines() if line]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    data = ROOT / "data/eval/competition500_v1"
    inputs = {row["query_id"]: row for row in rows(data / "test.jsonl")}
    gold = {row["query_id"]: row for row in rows(data / "reference/labels.jsonl")}
    qrels = {row["query_id"]: row["grades"] for row in rows(data / "reference/qrels_test.jsonl")}
    history = read(ROOT / "reports/competition500/evaluation.json")
    labels = list(history["risk"]["deepseek_adaptive"]["per_label"])
    specs = [
        ("query_optimization_20261024", "Query 优化", "baseline", "优化前基线", "historical"),
        (
            "query_optimization_20261024",
            "Query 优化",
            "candidate",
            "已发布版本 · 发布验收",
            "released",
        ),
        (
            "information_sufficiency_20261024",
            "信息不足识别",
            "baseline",
            "当前版本 · 最新复测",
            "current",
        ),
        (
            "information_sufficiency_20261024",
            "信息不足识别",
            "candidate",
            "信息不足候选 · 已回退",
            "rejected",
        ),
    ]
    comparisons = {}
    runs = []
    sources = {}
    for folder, title, side, name, status in specs:
        comparison_path = ROOT / "reports" / folder / "comparison.json"
        comparison = read(comparison_path)
        comparisons[folder] = {
            "title": title,
            "protocol": comparison["protocol"],
            "promote": comparison["promote"],
            "gate_checks": comparison["gate_checks"],
            "development": comparison["development"],
            "exposed_cases": comparison.get("exposed_cases", {}),
        }
        sources[comparison_path.relative_to(ROOT).as_posix()] = digest(comparison_path.read_bytes())
        original = comparison["runs"][side]
        run_dir = RUNS / original["run"]
        summaries = read(run_dir / "test_summary.json")
        assert summaries["deepseek_adaptive"] == original["risk"]
        rankings = read(run_dir / "retrieval_test_deepseek.json")
        assert ranking_metrics(rankings, qrels) == original["retrieval"]
        assert len(rankings) == 200 and {r["query_id"] for r in rankings} == set(inputs)
        ranked = {}
        for row in rankings:
            relevant = {cid for cid, grade in qrels[row["query_id"]].items() if grade >= 2}
            ranked[row["query_id"]] = {
                **row,
                "relevant_count": len(relevant),
                "grades": [qrels[row["query_id"]][cid] for cid in row["case_ids"]],
                "metrics": ranking_metrics([row], qrels) if relevant else None,
            }
        run = {
            "id": original["run"],
            "name": name,
            "status": status,
            "evaluated_on": "2026-10-24",
            "comparison": folder,
            "risk": summaries,
            "retrieval": original["retrieval"],
            "retrieval_verified": sum(r["literal_verified"] for r in rankings),
            "retrieval_warnings": sum(bool(r["warnings"]) for r in rankings),
            "rankings": ranked,
            "modes": {},
        }
        for mode, expected in summaries.items():
            predictions = read(run_dir / f"test_{mode}.json")
            assert len(predictions) == 200 and {r["query_id"] for r in predictions} == set(inputs)
            assert risk_metrics(predictions, gold, labels) == expected
            counts = Counter(
                (gold[r["query_id"]]["decision_state"], r["decision_state"]) for r in predictions
            )
            groups = {
                "scenes": {
                    s: [r for r in predictions if gold[r["query_id"]]["scene"] == s]
                    for s in sorted({gold[q]["scene"] for q in inputs})
                },
                "lengths": {
                    "少于 500 字": [r for r in predictions if r["chars"] < 500],
                    "500–899 字": [r for r in predictions if 500 <= r["chars"] < 900],
                    "900 字及以上": [r for r in predictions if r["chars"] >= 900],
                },
            }
            run["modes"][mode] = {
                "confusion": {a: {p: counts[a, p] for p in STATES} for a in STATES},
                **{
                    group: {
                        key: risk_metrics(value, gold, labels)
                        for key, value in values.items()
                        if value
                    }
                    for group, values in groups.items()
                },
                "predictions": [
                    {
                        key: r.get(key)
                        for key in (
                            "query_id",
                            "scene",
                            "decision_state",
                            "risk_labels",
                            "seconds",
                            "chars",
                            "missing_model_targets",
                            "unchecked_mechanisms",
                            "error",
                            "warnings",
                        )
                    }
                    for r in sorted(predictions, key=lambda r: r["query_id"])
                ],
            }
        runs.append(run)

    # Bind to the recorded evaluated bytes, never bless the current checkout as a new test.
    manifest = read(RUNS / SELECTED / "run_manifest.json")
    bindings = {}
    with ZipFile(RUNS / SELECTED / "source_snapshot.zip") as archive:
        for original, expected in manifest["source_hashes"].items():
            name = original.replace("\\", "/")
            if name.startswith("src/api/"):
                continue  # HTTP/report presentation is changed in this release, not the algorithm.
            frozen = (
                archive.read(name) if name in archive.namelist() else (ROOT / name).read_bytes()
            )
            assert digest(frozen) == expected, name
            bindings[name] = digest(
                frozen if name.endswith(".npz") else frozen.replace(b"\r\n", b"\n")
            )
    context = read(ROOT / "reports/information_sufficiency_20261024/comparison.json")[
        "context_bindings"
    ]
    payload = {
        "available": True,
        "version": "finrisk-evaluation-dashboard-20261024-v1",
        "evaluated_on": "2026-10-24",
        "selected_run": SELECTED,
        "selected_mode": "deepseek_adaptive",
        "algorithm_revision": "41f2765780c71d740eed57e17fe8b64885cfb9b4",
        "knowledge_version": "finrisk-full-20261024",
        "dataset": history["dataset"],
        "default_config": history["default_config"],
        "notes": [
            "顶部展示当前已部署算法的最新一次复测；同一算法的发布验收保留为单独记录。",
            "200 条测试输入、参考标签和 500 案例相关性判断保持不变；"
            "参考由 Codex 自复核，非专家金标。",
            "这是重复工程回归，每版单次真实 API 运行存在模型波动，"
            "不能视为独立测试、统计显著结论或赛事成绩。",
            "检索仅衡量 500 案例闭池；187 条有强相关案例、13 条无强相关案例，"
            "后者不计入排序质量均值。",
            "900 字及以上只有 1 条，无法据此判断长文本总体效果。",
            "开发集用于候选选择，其中原开发前 100 条参加过训练；开发结果与测试结果分别展示。",
            "信息不足候选未通过门槛，已回退；公开实验结果不代表部署该候选。",
        ],
        "runs": runs,
        "comparisons": comparisons,
        "inputs": {qid: {"text": inputs[qid]["text"], "reference": gold[qid]} for qid in inputs},
        "historical": {"evaluated_on": "2026-10-19", "report": history},
        "source_bindings": bindings,
        "context_bindings": context,
        "source_reports": sources,
    }
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"Verified and published {len(runs)} runs, 8 risk results, 800 rankings: {DEST}")


if __name__ == "__main__":
    main()
