"""同一案例知识库的读取、增量写入与状态管理。"""

from __future__ import annotations

import csv
import json
import math
import os
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from threading import RLock

from domain.knowledge_models import (
    CaseDetail,
    CaseListPage,
    CaseStatistics,
    CaseSummary,
    EvidenceChunk,
)
from retrieval import RetrievalDocument
from settings import AppSettings


class CaseNotFoundError(KeyError):
    """案例不存在。"""


class DuplicateCaseError(RuntimeError):
    """相同 ID 的案例已经存在。"""


class CaseRepository:
    """直接管理案例主库的三份 JSONL。

    现有 7,628 条记录不会重新生成。新 PDF 处理完成后按相同 schema 增量写入
    cases、case_chunks 和 case_expansions，并刷新 manifest。停用案例只修改
    retrieval_status，原始 PDF、记录和证据均保留，可随时恢复。
    """

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._lock = RLock()
        self._records: dict[str, dict[str, object]] = {}
        self._chunks_by_case: dict[str, list[dict[str, object]]] = {}
        self._risk_tags: set[str] = set()
        self._data_version: str | None = None
        self._latest_crawl_at: str | None = None
        self._latest_penalty_date: str | None = None
        self._revision = 0
        self.reload()

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def risk_tags(self) -> tuple[str, ...]:
        return tuple(sorted(self._risk_tags))

    def reload(self) -> None:
        if not self.settings.cases_path.is_file():
            raise FileNotFoundError(f"案例主表不存在: {self.settings.cases_path}")
        records = {
            str(record["case_id"]): record for record in _read_jsonl(self.settings.cases_path)
        }
        with self._lock:
            self._records = records
            self._chunks_by_case = {}
            self._risk_tags = {
                str(tag)
                for record in records.values()
                for tag in _as_list(record.get("risk_tags"))
                if tag
            }
            manifest_meta = _read_manifest_meta(self.settings.manifest_path)
            self._data_version = manifest_meta.get("data_version")
            self._latest_crawl_at = manifest_meta.get("latest_crawl_at")
            self._latest_penalty_date = manifest_meta.get("latest_penalty_date")
            self._revision += 1

    def list_cases(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        query: str | None = None,
        risk_tag: str | None = None,
        status: str | None = None,
        origin: str | None = None,
        regulator: str | None = None,
        party_name: str | None = None,
        institution_type: str | None = None,
        penalty_date_from: date | None = None,
        penalty_date_to: date | None = None,
    ) -> CaseListPage:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("分页参数不合法")
        normalized_query = (query or "").strip().casefold()
        records = list(self._records.values())
        if normalized_query:
            records = [record for record in records if _record_contains(record, normalized_query)]
        if risk_tag:
            records = [
                record for record in records if risk_tag in _as_list(record.get("risk_tags"))
            ]
        if status:
            records = [record for record in records if record.get("retrieval_status") == status]
        if origin:
            records = [record for record in records if record.get("case_origin") == origin]
        if regulator:
            needle = regulator.strip().casefold()
            records = [
                record
                for record in records
                if needle in str(record.get("regulator") or "").casefold()
            ]
        if party_name:
            needle = party_name.strip().casefold()
            records = [
                record
                for record in records
                if needle in str(record.get("party_name") or "").casefold()
            ]
        if institution_type:
            needle = institution_type.strip().casefold()
            records = [
                record
                for record in records
                if needle in str(record.get("institution_type") or "").casefold()
            ]
        if penalty_date_from:
            records = [
                record
                for record in records
                if (value := _as_date(record.get("penalty_date"))) is not None
                and value >= penalty_date_from
            ]
        if penalty_date_to:
            records = [
                record
                for record in records
                if (value := _as_date(record.get("penalty_date"))) is not None
                and value <= penalty_date_to
            ]
        records.sort(key=_case_sort_key)
        total = len(records)
        start = (page - 1) * page_size
        return CaseListPage(
            items=[self._to_summary(record) for record in records[start : start + page_size]],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

    def get_case(self, case_id: str) -> CaseDetail:
        record = self._record(case_id)
        return self._to_detail(record, self._case_chunks(case_id))

    def get_summary(self, case_id: str) -> CaseSummary:
        return self._to_summary(self._record(case_id))

    def summaries(self) -> tuple[CaseSummary, ...]:
        """一次性生成检索所需摘要，避免通过分页反复排序主表。"""

        records = tuple(self._records.values())
        return tuple(self._to_summary(record) for record in records)

    def statistics(self) -> CaseStatistics:
        records = list(self._records.values())
        return CaseStatistics(
            total_cases=len(records),
            base_cases=sum(1 for record in records if record.get("case_origin") != "web_ingestion"),
            user_cases=sum(1 for record in records if record.get("case_origin") == "web_ingestion"),
            active_cases=sum(1 for record in records if record.get("retrieval_status") == "active"),
            risk_tag_count=len(self._risk_tags),
            data_version=self._data_version,
            latest_crawl_at=self._latest_crawl_at,
            latest_penalty_date=self._latest_penalty_date,
        )

    def add_case(
        self,
        record: dict[str, object],
        chunks: list[dict[str, object]],
        expansions: list[dict[str, object]],
    ) -> CaseDetail:
        case_id = str(record.get("case_id") or "")
        if not case_id:
            raise ValueError("案例缺少 case_id")
        with self._lock:
            if case_id in self._records:
                raise DuplicateCaseError(case_id)
            paths = (
                self.settings.chunks_path,
                self.settings.expansions_path,
                self.settings.cases_path,
            )
            snapshots = {
                path: (path.is_file(), path.stat().st_size if path.is_file() else 0)
                for path in paths
            }
            manifest_original = (
                self.settings.manifest_path.read_bytes()
                if self.settings.manifest_path.is_file()
                else None
            )
            try:
                _append_jsonl(self.settings.chunks_path, chunks)
                _append_jsonl(self.settings.expansions_path, expansions)
                _append_jsonl(self.settings.cases_path, [record])
                self._refresh_manifest()
            except Exception:
                for path, (existed, size) in snapshots.items():
                    _restore_file(path, existed=existed, size=size)
                if manifest_original is not None:
                    self.settings.manifest_path.write_bytes(manifest_original)
                self.settings.manifest_path.with_suffix(".json.tmp").unlink(missing_ok=True)
                raise
            self._records[case_id] = dict(record)
            self._chunks_by_case[case_id] = [dict(chunk) for chunk in chunks]
            self._risk_tags.update(str(tag) for tag in _as_list(record.get("risk_tags")) if tag)
            self._revision += 1
        return self._to_detail(record, chunks)

    def set_retrieval_status(self, case_id: str, *, active: bool) -> CaseDetail:
        """停用或恢复案例，不删除任何记录与原始材料。"""

        with self._lock:
            record = dict(self._record(case_id))
            record["retrieval_status"] = "active" if active else "inactive"
            record["updated_at"] = datetime.now(UTC).date().isoformat()
            flags = [str(value) for value in _as_list(record.get("quality_flags"))]
            marker = "web_reactivated" if active else "web_deactivated"
            record["quality_flags"] = list(dict.fromkeys([*flags, marker]))
            updated = dict(self._records)
            updated[case_id] = record
            _write_jsonl_atomic(self.settings.cases_path, updated.values())
            self._records = updated
            self._revision += 1
            self._refresh_manifest()
        return self.get_case(case_id)

    def iter_retrieval_documents(self) -> Iterator[RetrievalDocument]:
        active_ids = {
            case_id
            for case_id, record in self._records.items()
            if record.get("retrieval_status") == "active"
        }
        for chunk in _read_jsonl(self.settings.chunks_path):
            case_id = str(chunk.get("case_id") or "")
            if case_id not in active_ids or not chunk.get("retrieval_enabled", True):
                continue
            if chunk.get("chunk_type") not in {"fact", "evidence"}:
                continue
            text = str(chunk.get("chunk_text") or "").strip()
            if text:
                yield RetrievalDocument(
                    unit_id=str(chunk.get("chunk_id")),
                    case_ids=(case_id,),
                    text=text,
                    source="case_chunk",
                    weight=_as_float(chunk.get("retrieval_weight"), 1.0),
                )
        for expansion in _read_jsonl(self.settings.expansions_path):
            if not expansion.get("retrieval_enabled", False):
                continue
            case_ids = tuple(
                dict.fromkeys(
                    str(link.get("case_id"))
                    for link in _as_dict_list(expansion.get("case_links"))
                    if str(link.get("case_id") or "") in active_ids
                )
            )
            text = str(expansion.get("expansion_text") or "").strip()
            if text and case_ids:
                yield RetrievalDocument(
                    unit_id=str(expansion.get("expansion_id")),
                    case_ids=case_ids,
                    text=text,
                    source="case_expansion",
                    weight=_as_float(expansion.get("retrieval_weight"), 0.35),
                )

    def risk_dictionary(self) -> tuple[str, ...]:
        if not self.settings.risk_dictionary_path.is_file():
            return self.risk_tags
        labels: list[str] = []
        with self.settings.risk_dictionary_path.open("r", encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                value = next(
                    (
                        row.get(key)
                        for key in ("risk_type", "risk_tag", "label_name", "风险类型", "标签名称")
                        if row.get(key)
                    ),
                    None,
                )
                if value:
                    labels.append(value.strip())
        return tuple(dict.fromkeys(labels)) or self.risk_tags

    def _record(self, case_id: str) -> dict[str, object]:
        record = self._records.get(case_id)
        if record is None:
            raise CaseNotFoundError(case_id)
        return record

    def _case_chunks(self, case_id: str) -> list[dict[str, object]]:
        cached = self._chunks_by_case.get(case_id)
        if cached is not None:
            return cached
        chunks = [
            chunk
            for chunk in _read_jsonl(self.settings.chunks_path)
            if chunk.get("case_id") == case_id
        ]
        self._chunks_by_case[case_id] = chunks
        return chunks

    def _to_summary(self, record: dict[str, object]) -> CaseSummary:
        case_id = str(record["case_id"])
        return CaseSummary(
            case_id=case_id,
            case_title=_optional_string(record.get("case_title")),
            party_name=_optional_string(record.get("party_name")),
            penalty_doc_no=_optional_string(record.get("penalty_doc_no")),
            violation_behavior=str(record.get("violation_behavior") or "未提供违规事实"),
            penalty_content=_optional_string(record.get("penalty_content")),
            regulator=_optional_string(record.get("regulator")),
            penalty_date=_as_date(record.get("penalty_date")),
            institution_type=_optional_string(record.get("institution_type")),
            source_url=_optional_string(record.get("source_url")),
            risk_tags=[str(value) for value in _as_list(record.get("risk_tags"))],
            risk_domains=[str(value) for value in _as_list(record.get("risk_domains"))],
            case_origin=str(record.get("case_origin") or "unknown"),
            retrieval_status=str(record.get("retrieval_status") or "inactive"),
            evidence_status=str(record.get("evidence_status") or "limited"),
            is_user_managed=record.get("case_origin") == "web_ingestion",
        )

    def _to_detail(
        self,
        record: dict[str, object],
        chunks: list[dict[str, object]],
    ) -> CaseDetail:
        return CaseDetail(
            **self._to_summary(record).model_dump(),
            case_summary=_optional_string(record.get("case_summary")),
            related_parties=_as_dict_list(record.get("related_parties")),
            entity_relations=_as_dict_list(record.get("entity_relations")),
            legal_basis_refs=_as_dict_list(record.get("legal_basis_refs")),
            source_file=_optional_string(record.get("source_file")),
            source_sha256=_optional_string(record.get("source_sha256")),
            quality_flags=[str(value) for value in _as_list(record.get("quality_flags"))],
            data_version=str(record.get("data_version") or "case_kb_incremental_v1"),
            evidence_chunks=[
                EvidenceChunk(
                    chunk_id=str(chunk.get("chunk_id")),
                    chunk_type=str(chunk.get("chunk_type") or "fact"),
                    chunk_text=str(chunk.get("chunk_text") or ""),
                    supports_risk_tags=[
                        str(value) for value in _as_list(chunk.get("supports_risk_tags"))
                    ],
                    is_verbatim=bool(chunk.get("is_verbatim", False)),
                    source_span=_as_dict(chunk.get("source_span")),
                )
                for chunk in chunks
            ],
        )

    def _refresh_manifest(self) -> None:
        if not self.settings.manifest_path.is_file():
            return
        manifest = json.loads(self.settings.manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return
        counts = manifest.setdefault("counts", {})
        files = manifest.setdefault("files", {})
        for key, path in (
            ("cases", self.settings.cases_path),
            ("case_chunks", self.settings.chunks_path),
            ("case_expansions", self.settings.expansions_path),
        ):
            rows = _line_count(path)
            counts[key.removeprefix("case_") if key != "cases" else key] = rows
            files[key] = {
                "path": path.relative_to(self.settings.case_kb_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
                "rows": rows,
            }
        manifest["locally_extended"] = True
        manifest["updated_at"] = datetime.now(UTC).isoformat()
        temporary = self.settings.manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.settings.manifest_path)


def _read_jsonl(path: Path) -> Iterator[dict[str, object]]:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} 不是 JSON 对象")
            yield value


def _append_jsonl(path: Path, records: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            file.write("\n")
        file.flush()
        os.fsync(file.fileno())


def _write_jsonl_atomic(path: Path, records: Iterable[dict[str, object]]) -> None:
    temporary = path.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as file:
        for record in sorted(records, key=_case_sort_key):
            file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            file.write("\n")
    os.replace(temporary, path)


def _read_manifest_meta(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return {}
    return {
        key: str(text)
        for key in ("data_version", "latest_crawl_at", "latest_penalty_date")
        if (text := value.get(key)) not in (None, "")
    }


def _record_contains(record: dict[str, object], normalized_query: str) -> bool:
    values = (
        record.get("case_id"),
        record.get("case_title"),
        record.get("party_name"),
        record.get("penalty_doc_no"),
        record.get("violation_behavior"),
        record.get("penalty_content"),
        record.get("regulator"),
        " ".join(str(value) for value in _as_list(record.get("risk_tags"))),
    )
    return any(normalized_query in str(value or "").casefold() for value in values)


def _case_sort_key(record: dict[str, object]) -> tuple[int, str]:
    case_id = str(record.get("case_id") or "")
    return (0 if record.get("case_origin") == "web_ingestion" else 1, case_id)


def _optional_string(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _as_dict_list(value: object) -> list[dict[str, object]]:
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _as_dict(value: object) -> dict[str, object] | None:
    return value if isinstance(value, dict) else None


def _as_float(value: object, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _line_count(path: Path) -> int:
    with path.open("rb") as file:
        return sum(1 for line in file if line.strip())


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _restore_file(path: Path, *, existed: bool, size: int) -> None:
    """把一次多文件追加恢复到写入前大小。"""

    if not existed:
        path.unlink(missing_ok=True)
        return
    with path.open("r+b") as file:
        file.truncate(size)
        os.fsync(file.fileno())
