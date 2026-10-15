"""Validate the files required for a runnable FinRisk delivery package."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_ROOT = (
    PROJECT_ROOT / "data" / "processed" / "knowledge" / "case_kb_v2_1_2026-08-23"
)
MANIFEST_PATH = KNOWLEDGE_ROOT / "manifest.json"
REQUIRED_PATHS = (
    PROJECT_ROOT / ".env.example",
    PROJECT_ROOT / "pyproject.toml",
    PROJECT_ROOT / "requirements.lock.txt",
    PROJECT_ROOT / "src" / "api" / "app.py",
    PROJECT_ROOT / "src" / "web" / "static" / "index.html",
    PROJECT_ROOT / "src" / "web" / "static" / "source-map.js",
    PROJECT_ROOT / "src" / "web" / "static" / "fonts" / "InterVariable.woff2",
    PROJECT_ROOT / "src" / "web" / "static" / "fonts" / "OFL.txt",
    PROJECT_ROOT / "agent_runtime" / "package.json",
    PROJECT_ROOT / "agent_runtime" / "package-lock.json",
    PROJECT_ROOT / "agent_runtime" / "worker.mjs",
    PROJECT_ROOT / "agent_runtime" / "runtime.mjs",
    PROJECT_ROOT / "data" / "risk" / "keyword_db" / "risk_keyword_db.json",
    MANIFEST_PATH,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _line_count(path: Path) -> int:
    with path.open("rb") as source:
        return sum(1 for _ in source)


def main() -> None:
    """Check required assets, knowledge-base integrity, and the app import."""

    missing = [str(path.relative_to(PROJECT_ROOT)) for path in REQUIRED_PATHS if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing delivery files: {', '.join(missing)}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if not manifest.get("valid"):
        raise SystemExit("Knowledge-base manifest is not marked valid.")

    for name, metadata in manifest["files"].items():
        path = KNOWLEDGE_ROOT / metadata["path"]
        if not path.is_file():
            raise SystemExit(f"Missing knowledge-base file: {path.relative_to(PROJECT_ROOT)}")
        actual_bytes = path.stat().st_size
        if actual_bytes != metadata["bytes"]:
            raise SystemExit(f"Byte-size mismatch for {name}: {actual_bytes}")
        actual_hash = _sha256(path)
        if actual_hash != metadata["sha256"]:
            raise SystemExit(f"SHA-256 mismatch for {name}: {actual_hash}")
        actual_rows = _line_count(path)
        if actual_rows != metadata["rows"]:
            raise SystemExit(f"Row-count mismatch for {name}: {actual_rows}")

    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    from api.app import app  # noqa: PLC0415

    if app.version != "1.0.0":
        raise SystemExit(f"Unexpected application version: {app.version}")

    print(
        "FinRisk delivery integrity check passed: "
        f"{manifest['counts']['cases']} cases, app version {app.version}."
    )


if __name__ == "__main__":
    main()
