"""统一案例库的增量写入、状态管理和检索回归测试。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from application.retrieval_service import CaseRetrievalService, CaseSearchFilters
from settings import AppSettings
from storage.case_repository import CaseRepository, DuplicateCaseError


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{json.dumps(value, ensure_ascii=False)}\n" for value in values),
        encoding="utf-8",
    )


def _settings(tmp_path: Path) -> AppSettings:
    root = tmp_path / "case_kb"
    data = root / "data"
    dictionary = root / "dictionary"
    dictionary.mkdir(parents=True)
    record = {
        "case_id": "C001",
        "case_title": "保证收益销售误导案例",
        "case_origin": "batch_build",
        "violation_behavior": "销售人员向客户承诺保本并保证年化收益。",
        "penalty_content": "责令改正并处罚款。",
        "party_name": "甲保险公司某分公司",
        "regulator": "国家金融监督管理总局甲监管分局",
        "institution_type": "保险公司分支机构",
        "penalty_date": "2026-06-18",
        "source_url": "https://example.test/C001",
        "risk_tags": ["承诺收益", "销售误导"],
        "risk_domains": ["销售行为"],
        "retrieval_status": "active",
        "evidence_status": "verified",
        "data_version": "test-v1",
    }
    chunk = {
        "chunk_id": "C001_fact_001",
        "case_id": "C001",
        "chunk_type": "fact",
        "chunk_text": "向客户承诺保本，保证年化收益百分之十。",
        "retrieval_enabled": True,
        "retrieval_weight": 1.0,
        "supports_risk_tags": ["承诺收益"],
        "is_verbatim": True,
    }
    _write_jsonl(data / "cases.jsonl", [record])
    _write_jsonl(data / "case_chunks.jsonl", [chunk])
    _write_jsonl(data / "case_expansions.jsonl", [])
    (root / "manifest.json").write_text(
        json.dumps({"data_version": "test-v1", "counts": {}, "files": {}}),
        encoding="utf-8",
    )
    (dictionary / "risk_type_dictionary.csv").write_text(
        "risk_type\n承诺收益\n销售误导\n", encoding="utf-8"
    )
    keyword_path = tmp_path / "risk.json"
    keyword_path.write_text('{"keywords": [], "regex_patterns": {}}', encoding="utf-8")
    return AppSettings(
        project_root=tmp_path,
        case_kb_root=root,
        risk_keyword_path=keyword_path,
        raw_case_upload_dir=tmp_path / "uploads",
    )


def test_repository_reads_and_retrieves_existing_case(tmp_path: Path) -> None:
    repository = CaseRepository(_settings(tmp_path))
    service = CaseRetrievalService(repository)

    assert repository.statistics().total_cases == 1
    assert repository.get_case("C001").evidence_chunks[0].is_verbatim is True
    matches = service.search("保证收益百分之十", top_k=3)
    assert matches
    assert matches[0].case_id == "C001"
    assert 0 < matches[0].score <= 1
    assert matches[0].bm25_score > 0
    assert matches[0].vector_score > 0
    assert matches[0].rrf_score > 0
    aligned = service.search("保证收益百分之十", top_k=3, risk_tags={"承诺收益"})
    assert aligned[0].matched_risk_tags == ["承诺收益"]
    assert service.search("保证收益百分之十", top_k=3, risk_tags={"赠送利益"}) == []


def test_retrieval_and_repository_support_combined_metadata_filters(tmp_path: Path) -> None:
    repository = CaseRepository(_settings(tmp_path))
    service = CaseRetrievalService(repository)
    filters = CaseSearchFilters(
        risk_tags=frozenset({"承诺收益"}),
        regulator="甲监管分局",
        party_name="甲保险公司",
        institution_type="分支机构",
        penalty_date_from=date(2026, 1, 1),
        penalty_date_to=date(2026, 12, 31),
    )

    matches = service.search("保证收益百分之十", top_k=3, filters=filters)

    assert matches[0].party_name == "甲保险公司某分公司"
    assert matches[0].institution_type == "保险公司分支机构"
    assert matches[0].source_url == "https://example.test/C001"
    assert "风险标签一致" in matches[0].match_reason
    assert "过滤条件" in matches[0].match_reason
    assert (
        service.search(
            "保证收益百分之十",
            filters=CaseSearchFilters(regulator="不存在的监管机构"),
        )
        == []
    )
    page = repository.list_cases(
        regulator="甲监管分局",
        party_name="甲保险公司",
        institution_type="分支机构",
        penalty_date_from=date(2026, 6, 1),
        penalty_date_to=date(2026, 6, 30),
    )
    assert page.total == 1
    assert page.items[0].institution_type == "保险公司分支机构"


def test_incremental_case_joins_same_files_and_can_be_deactivated(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    repository = CaseRepository(settings)
    record = {
        "case_id": "U002",
        "case_title": "Web 新增案例",
        "case_origin": "web_ingestion",
        "violation_behavior": "通过赠送礼品诱导投保。",
        "risk_tags": ["赠送利益"],
        "risk_domains": ["销售行为"],
        "retrieval_status": "active",
        "evidence_status": "limited",
        "data_version": "test-v1",
    }
    chunks = [
        {
            "chunk_id": "U002_fact_001",
            "case_id": "U002",
            "chunk_type": "fact",
            "chunk_text": "赠送礼品诱导投保",
            "retrieval_enabled": True,
        }
    ]
    expansions = [
        {
            "expansion_id": "U002_exp_001",
            "expansion_text": "送礼投保",
            "case_links": [{"case_id": "U002"}],
            "retrieval_enabled": True,
        }
    ]

    repository.add_case(record, chunks, expansions)

    assert repository.statistics().total_cases == 2
    assert repository.statistics().user_cases == 1
    assert sum(1 for _ in settings.cases_path.open(encoding="utf-8")) == 2
    assert sum(1 for _ in settings.chunks_path.open(encoding="utf-8")) == 2
    assert sum(1 for _ in settings.expansions_path.open(encoding="utf-8")) == 1
    assert repository.set_retrieval_status("U002", active=False).retrieval_status == "inactive"
    assert all(
        "U002" not in document.case_ids for document in repository.iter_retrieval_documents()
    )
    with pytest.raises(DuplicateCaseError):
        repository.add_case(record, chunks, expansions)
