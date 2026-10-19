"""Fit the local candidate classifier on 400 development queries, without reading test labels."""

import hashlib

from build_competition_dataset import DATA, ROOT, read_rows, save

from risk.local_calibration import train_model
from risk.taxonomy import load_taxonomy_descriptions
from settings import AppSettings


def main():
    rows = read_rows(DATA / "development.jsonl")
    ids = {r["query_id"] for r in rows}
    labels = {
        r["query_id"]: r for r in read_rows(DATA / "reference/labels.jsonl") if r["query_id"] in ids
    }
    settings = AppSettings.from_env()
    taxonomy = list(load_taxonomy_descriptions(settings.risk_dictionary_path))
    path = ROOT / "data/risk/calibration/competition500.npz"
    train_model(
        [r["text"] for r in rows],
        [labels[r["query_id"]]["decision_state"] for r in rows],
        [labels[r["query_id"]]["risk_labels"] for r in rows],
        taxonomy,
        path,
    )
    save(
        path.with_suffix(".json"),
        {
            "training_queries": len(rows),
            "training_ids": sorted(ids),
            "taxonomy_size": len(taxonomy),
            "test_queries_used": 0,
            "method": "hashed character 2/3-gram, softmax states and 27 sigmoid labels",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        },
    )
    print("Local candidate model trained on development queries only.")


if __name__ == "__main__":
    main()
