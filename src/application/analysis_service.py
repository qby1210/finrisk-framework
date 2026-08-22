"""Query 准备与风险判断的统一应用接口。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from application.query_service import QueryProcessingService
from domain.risk_models import QueryAnalysisResult
from query.classification import ClassifierStatus
from risk.pipeline import RiskAssessmentPipeline


class QueryAnalysisService:
    def __init__(
        self,
        *,
        query_service: QueryProcessingService,
        risk_pipeline: RiskAssessmentPipeline,
    ) -> None:
        self.query_service = query_service
        self.risk_pipeline = risk_pipeline

    @property
    def classifier_status(self) -> ClassifierStatus:
        return self.query_service.classifier_status

    async def process_text(
        self,
        text: str,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> QueryAnalysisResult:
        prepared = await self.query_service.process_text(text, metadata=metadata)
        return await self.risk_pipeline.analyze(prepared)

    async def process_file(
        self,
        file_path: str | Path,
        *,
        source_uri: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> QueryAnalysisResult:
        prepared = await self.query_service.process_file(
            file_path,
            source_uri=source_uri,
            metadata=metadata,
        )
        return await self.risk_pipeline.analyze(prepared)
