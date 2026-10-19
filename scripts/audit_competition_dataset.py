"""Validate source-disjoint splits, fixed taxonomy and closed-pool references."""

import hashlib
import json
from collections import Counter

from build_competition_dataset import DATA, ROOT, read_rows, save

from risk.taxonomy import load_taxonomy_descriptions
from settings import AppSettings


def main():
    pool = read_rows(DATA / "cases.jsonl")
    development = read_rows(DATA / "development.jsonl")
    validation = read_rows(DATA / "validation.jsonl")
    test = read_rows(DATA / "test.jsonl")
    assert (
        len(pool) == len({r["case_id"] for r in pool}) == len({r["file_id"] for r in pool}) == 500
    )
    assert len(development) == 400 and len(test) == 200
    assert len(validation) == 100 and validation == development[:100]
    assert len({r["source_sha256"] for r in pool}) == 500
    ids = {r["query_id"] for r in development}
    test_ids = {r["query_id"] for r in test}
    assert not ids & test_ids
    assert not {"".join(r["text"].split()) for r in development} & {
        "".join(r["text"].split()) for r in test
    }
    plan = read_rows(DATA / "reference/generation_plan.jsonl")
    seed_by_id = {r["query_id"]: r["seed_case_id"] for r in plan}
    assert not {seed_by_id[q] for q in ids} & {seed_by_id[q] for q in test_ids}
    source_by_case = {r["case_id"]: r["source_sha256"] for r in pool}
    assert not {source_by_case[seed_by_id[q]] for q in ids} & {
        source_by_case[seed_by_id[q]] for q in test_ids
    }
    labels = read_rows(DATA / "reference/labels.jsonl")
    taxonomy = load_taxonomy_descriptions(AppSettings.from_env().risk_dictionary_path)
    assert len(taxonomy) == 27
    assert {r["query_id"] for r in labels} == ids | test_ids and len(labels) == 600
    assert all(set(r["risk_labels"]) <= set(taxonomy) for r in labels)
    assert all(not r["risk_labels"] for r in labels if r["decision_state"] != "risk")
    report = {
        "cases": 500,
        "development": 400,
        "development_validation_subset": 100,
        "validation_is_independent": False,
        "test": 200,
        "seed_case_overlap": 0,
        "source_sha256_overlap": 0,
        "duplicate_text_overlap": 0,
        "fixed_label_count": 27,
        "old_evaluation_data_used": False,
        "annotation": "model_silver",
        "nonliteral_label_quote_rows": sum(
            bool(r.get("nonliteral_evidence_count")) for r in labels
        ),
        "test_scene_counts": dict(Counter(r["scene"] for r in labels if r["query_id"] in test_ids)),
        "qrels": {},
    }
    pool_ids = {r["case_id"] for r in pool}
    pool_by_id = {r["case_id"]: r for r in pool}
    query_by_id = {r["query_id"]: r["text"] for r in [*development, *test]}
    for split, expected in [("development", 60), ("test", 200)]:
        path = DATA / f"reference/qrels_{split}.jsonl"
        if not path.exists():
            continue
        rows = read_rows(path)
        assert len(rows) == expected
        assert all(set(r["grades"]) == pool_ids for r in rows)
        assert all(g in (0, 1, 2, 3) for r in rows for g in r["grades"].values())
        for row in rows:
            positives = {cid for cid, grade in row["grades"].items() if grade >= 2}
            assert set(row["positive_evidence"]) == positives
            for cid, proof in row["positive_evidence"].items():
                assert proof["grade"] == row["grades"][cid]
                assert proof["query_quote"] in query_by_id[row["query_id"]]
                assert proof["case_quote"] in pool_by_id[cid]["violation_behavior"][:450]
        report["qrels"][split] = {
            "queries": len(rows),
            "explicit_pairs": len(rows) * 500,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "protocol": "paired-behavior-evidence-v2",
        }
    save(ROOT / "outputs/competition_upgrade_20261019/dataset_audit.json", report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
