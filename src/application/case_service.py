"""案例录入、查看、检索状态管理的应用服务。"""

from __future__ import annotations

import asyncio
import shutil
from datetime import date
from pathlib import Path

from domain.common import FilePurpose
from domain.knowledge_models import CaseDetail, CaseIngestionResult, CaseListPage, CaseStatistics
from extraction import FileExtractor
from llm import LLMClient
from offline.case_ingestion import IncrementalCaseBuilder, load_risk_domain_mapping
from risk.detection import RuleRiskDetector
from settings import AppSettings
from storage.case_repository import CaseRepository


class CaseManagementService:
    """组织文件抽取与增量入库，算法细节保留在 offline。"""

    def __init__(
        self,
        *,
        settings: AppSettings,
        repository: CaseRepository,
        rule_detector: RuleRiskDetector,
        llm_client: LLMClient | None,
        extractor: FileExtractor | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.extractor = extractor or FileExtractor()
        mapping_path = settings.case_kb_root / "dictionary" / "risk_domain_mapping.json"
        mapping = load_risk_domain_mapping(str(mapping_path))
        data_version = repository.statistics().data_version or "case_kb_incremental_v1"
        self.builder = IncrementalCaseBuilder(
            taxonomy=repository.risk_dictionary(),
            risk_domain_mapping=mapping,
            rule_detector=rule_detector,
            llm_client=llm_client,
            data_version=data_version,
        )

    async def ingest_file(self, file_path: Path, *, original_filename: str) -> CaseIngestionResult:
        extraction = await asyncio.to_thread(
            self.extractor.extract,
            file_path,
            FilePurpose.CASE,
            source_uri=f"upload://{original_filename}",
            metadata={"ingestion_channel": "web"},
        )
        case_id = f"U{extraction.checksum_sha256[:15].upper()}"
        destination = self.settings.raw_case_upload_dir / f"{case_id}_{original_filename}"
        try:
            logical_path = destination.relative_to(self.settings.project_root).as_posix()
        except ValueError:
            logical_path = f"upload://{destination.name}"
        artifacts = await self.builder.build_many(extraction, source_file=logical_path)
        if not artifacts:
            raise ValueError("未识别到保险相关处罚案例")
        destination.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, file_path, destination)
        try:
            details = await asyncio.to_thread(
                self.repository.add_cases,
                [(a.record, a.chunks, a.expansions) for a in artifacts],
                source_text=extraction.full_text,
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return CaseIngestionResult(
            case=details[0],
            cases=details,
            extraction_method=extraction.extraction_method.value,
            llm_used=any(a.llm_used for a in artifacts),
            warnings=list(dict.fromkeys(w for a in artifacts for w in a.warnings)),
        )

    def list_cases(
        self,
        *,
        page: int,
        page_size: int,
        query: str | None,
        risk_tag: str | None,
        status: str | None,
        origin: str | None,
        regulator: str | None = None,
        party_name: str | None = None,
        institution_type: str | None = None,
        penalty_date_from: date | None = None,
        penalty_date_to: date | None = None,
    ) -> CaseListPage:
        return self.repository.list_cases(
            page=page,
            page_size=page_size,
            query=query,
            risk_tag=risk_tag,
            status=status,
            origin=origin,
            regulator=regulator,
            party_name=party_name,
            institution_type=institution_type,
            penalty_date_from=penalty_date_from,
            penalty_date_to=penalty_date_to,
        )

    def get_case(self, case_id: str) -> CaseDetail:
        return self.repository.get_case(case_id)

    def set_active(self, case_id: str, *, active: bool) -> CaseDetail:
        return self.repository.set_retrieval_status(case_id, active=active)

    def statistics(self) -> CaseStatistics:
        return self.repository.statistics()
