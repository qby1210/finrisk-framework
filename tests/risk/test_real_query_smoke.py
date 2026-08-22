"""真实小红书样本的纯本地风险与案例匹配冒烟测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from application.analysis_service import QueryAnalysisService
from application.query_service import QueryProcessingService
from application.retrieval_service import CaseRetrievalService
from query.classification import QuerySceneClassifier
from risk.detection import RuleRiskDetector
from risk.pipeline import RiskAssessmentPipeline
from settings import AppSettings
from storage.case_repository import CaseRepository

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_first_real_xiaohongshu_copy_runs_locally_with_case_matches() -> None:
    source_path = PROJECT_ROOT / "data" / "raw" / "query" / "小红书文案原文.txt"
    if not source_path.is_file():
        pytest.skip("未提供真实小红书 Query 样本")
    source = source_path.read_text(encoding="utf-8")
    sample = source.split("\n2\n", maxsplit=1)[0].strip()
    settings = AppSettings.from_env()
    repository = CaseRepository(settings)
    retrieval = CaseRetrievalService(repository)
    pipeline = RiskAssessmentPipeline(
        rule_detector=RuleRiskDetector(settings.risk_keyword_path),
        retrieval_service=retrieval,
        taxonomy=repository.risk_dictionary(),
        llm_client=None,
    )
    service = QueryAnalysisService(
        query_service=QueryProcessingService(classifier=QuerySceneClassifier(None)),
        risk_pipeline=pipeline,
    )

    result = asyncio.run(service.process_text(sample, metadata={"test": "local_only"}))

    assert result.risk_summary.llm_used is False
    assert result.risk_summary.sentence_count >= 8
    assert result.risk_summary.risky_sentence_count >= 1
    assert any(item.matched_cases for item in result.risk_assessments)
    service_claim = next(item for item in result.risk_assessments if "从不扯皮" in item.text)
    ordinary_benefit = next(item for item in result.risk_assessments if "医疗费用" in item.text)
    assert service_claim.risk_score >= 0.4
    assert "绝对化表述" in service_claim.risk_labels
    assert ordinary_benefit.risk_score < 0.2
    assert ordinary_benefit.risk_labels == []
    diagnostic = {
        "scene": result.classification.scene,
        "overall_level": result.risk_summary.overall_level_name,
        "overall_score": result.risk_summary.overall_score,
        "risk_labels": result.risk_summary.risk_labels,
        "top_sentences": [
            {
                "score": item.risk_score,
                "labels": item.risk_labels,
                "text": item.text,
                "reasoning": item.reasoning,
            }
            for item in sorted(
                result.risk_assessments, key=lambda value: value.risk_score, reverse=True
            )[:5]
        ],
    }
    print(json.dumps(diagnostic, ensure_ascii=False, indent=2))
