"""The public UI and download must share current, version-bound results."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.app import app
from application.evaluation_service import SNAPSHOT, file_digest, load_evaluation


def fixture(root):
    source = root / "src/risk/example.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"value = 1\n")
    pool = root / "data/eval/competition500_v1/cases.jsonl"
    pool.parent.mkdir(parents=True)
    pool.write_bytes(b"{}\n")
    payload = {
        "available": True,
        "source_bindings": {"src/risk/example.py": file_digest(source)},
        "context_bindings": {"case_pool": file_digest(pool)},
    }
    path = root / SNAPSHOT
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload), "utf-8")
    return source, pool


def test_evaluation_tracks_algorithm_and_data_changes_with_portable_newlines(tmp_path):
    source, pool = fixture(tmp_path)
    assert load_evaluation(tmp_path, tmp_path)["freshness"]["status"] == "current"
    source.write_bytes(b"value = 1\r\n")
    assert load_evaluation(tmp_path, tmp_path)["freshness"]["status"] == "current"
    source.write_bytes(b"value = 2\n")
    assert load_evaluation(tmp_path, tmp_path)["freshness"]["changed_sources"]
    source.write_bytes(b"value = 1\n")
    pool.write_bytes(b'{"changed": true}\n')
    assert load_evaluation(tmp_path, tmp_path)["freshness"]["changed_context"] == ["case_pool"]


def test_missing_snapshot_never_falls_back_to_undated_old_report(tmp_path, monkeypatch):
    monkeypatch.setattr("api.app.PROJECT_ROOT", tmp_path)
    client = TestClient(app)
    assert client.get("/api/evaluation").json() == {"available": False}
    assert client.get("/api/evaluation/report").status_code == 404


def test_page_and_download_match_and_both_disable_cache(tmp_path, monkeypatch):
    fixture(tmp_path)
    monkeypatch.setattr("api.app.PROJECT_ROOT", tmp_path)
    client = TestClient(app)
    page, download = client.get("/api/evaluation"), client.get("/api/evaluation/report")
    assert page.status_code == download.status_code == 200
    assert page.json() == download.json()
    assert page.headers["cache-control"] == download.headers["cache-control"] == "no-store"
    assert "attachment" in download.headers["content-disposition"]


def test_published_snapshot_keeps_all_runs_and_selects_latest_deployed_algorithm():
    root = Path(__file__).resolve().parents[2]
    value = load_evaluation(root, root / "data/processed/knowledge/finrisk_full_20261024")
    assert value["freshness"]["status"] == "current"
    selected = next(r for r in value["runs"] if r["id"] == value["selected_run"])
    assert selected["status"] == "current"
    assert selected["id"] == "status_20261024_baseline"
    assert selected["risk"]["deepseek_adaptive"]["risk_binary_accuracy"] == 0.91
    assert len(value["runs"]) == 4
    for run in value["runs"]:
        assert len(run["rankings"]) == 200
        for mode in run["modes"].values():
            assert len(mode["predictions"]) == 200
            assert {p["query_id"] for p in mode["predictions"]} == set(value["inputs"])
            assert sum(sum(row.values()) for row in mode["confusion"].values()) == 200
        assert len(run["risk"]["deepseek_adaptive"]["per_label"]) == 27
    assert not value["comparisons"]["information_sufficiency_20261024"]["promote"]
