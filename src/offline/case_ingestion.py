"""新案例 PDF 的增量标准化、标签、切片和检索扩展流程。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from domain.file_models import FileExtractionResult
from llm import ChatMessage, JsonChatRequest, LLMClient, LLMProviderError
from risk.detection import RuleRiskDetector


@dataclass(frozen=True, slots=True)
class CaseIngestionArtifacts:
    record: dict[str, object]
    chunks: list[dict[str, object]]
    expansions: list[dict[str, object]]
    llm_used: bool
    warnings: list[str]


class _RiskBasis(BaseModel):
    risk_tag: str
    reason: str = Field(min_length=1, max_length=300)
    quote: str = Field(min_length=1, max_length=500)


class _RelatedParty(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str | None = Field(default=None, max_length=100)


class _LegalBasis(BaseModel):
    law_name: str = Field(min_length=1, max_length=200)
    article: str | None = Field(default=None, max_length=100)


class _CaseLLMOutput(BaseModel):
    case_title: str | None = Field(default=None, max_length=500)
    party_name: str | None = Field(default=None, max_length=300)
    institution_type: str | None = Field(default=None, max_length=100)
    penalty_doc_no: str | None = Field(default=None, max_length=200)
    violation_behavior: str = Field(min_length=1, max_length=6000)
    penalty_content: str | None = Field(default=None, max_length=3000)
    regulator: str | None = Field(default=None, max_length=300)
    penalty_date: str | None = None
    related_parties: list[_RelatedParty] = Field(default_factory=list, max_length=20)
    legal_basis_refs: list[_LegalBasis] = Field(default_factory=list, max_length=30)
    risk_tags: list[str] = Field(default_factory=list, max_length=2)
    risk_tag_basis: list[_RiskBasis] = Field(default_factory=list, max_length=2)
    case_summary: str = Field(min_length=1, max_length=1000)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    marketing_expressions: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0, le=1)


class IncrementalCaseBuilder:
    """把已有 FileExtractionResult 转成案例库三表兼容记录。"""

    def __init__(
        self,
        *,
        taxonomy: tuple[str, ...],
        risk_domain_mapping: dict[str, str],
        rule_detector: RuleRiskDetector,
        llm_client: LLMClient | None,
        data_version: str,
    ) -> None:
        self.taxonomy = taxonomy
        self._taxonomy_set = set(taxonomy)
        self.risk_domain_mapping = risk_domain_mapping
        self.rule_detector = rule_detector
        self.llm_client = llm_client
        self.data_version = data_version

    async def build(
        self,
        extraction: FileExtractionResult,
        *,
        source_file: str,
    ) -> CaseIngestionArtifacts:
        text = extraction.full_text.strip()
        if not text:
            raise ValueError("案例文件未抽取到文字，不能入库")
        warnings = list(extraction.warnings)
        llm_used = False
        output: _CaseLLMOutput
        if self.llm_client is not None:
            try:
                output = await self._call_llm(text)
                llm_used = True
            except LLMProviderError as error:
                warnings.append(f"DeepSeek 案例标准化失败，已使用规则降级：{error}")
                output = self._fallback(text)
        else:
            warnings.append("未配置 DeepSeek API Key，案例以规则降级模式入库")
            output = self._fallback(text)

        case_id = f"U{extraction.checksum_sha256[:15].upper()}"
        file_id = f"F_{extraction.checksum_sha256[:16].upper()}"
        risk_tags = [label for label in output.risk_tags if label in self._taxonomy_set]
        if not risk_tags:
            risk_tags = [
                label
                for label in self.rule_detector.detect(text).risk_labels
                if label in self._taxonomy_set
            ]
        if not risk_tags:
            risk_tags = ["其他"] if "其他" in self._taxonomy_set else []
        valid_basis = [
            basis
            for basis in output.risk_tag_basis
            if basis.risk_tag in risk_tags and basis.quote in text
        ]
        risk_domains = list(
            dict.fromkeys(
                self.risk_domain_mapping[label]
                for label in risk_tags
                if label in self.risk_domain_mapping
            )
        )
        chunks = _build_chunks(
            case_id=case_id,
            file_id=file_id,
            extraction=extraction,
            violation_behavior=output.violation_behavior,
            penalty_content=output.penalty_content,
            legal_basis=output.legal_basis_refs,
            risk_tags=risk_tags,
            data_version=self.data_version,
        )
        expansions = _build_expansions(
            case_id=case_id,
            values=[*output.marketing_expressions, *output.keywords],
            risk_tags=risk_tags,
            risk_domains=risk_domains,
            data_version=self.data_version,
        )
        today = datetime.now(UTC).date().isoformat()
        title = output.case_title or extraction.source_filename
        record: dict[str, object] = {
            "schema_version": "case_kb_v1",
            "case_id": case_id,
            "file_id": file_id,
            "case_origin": "web_ingestion",
            "atomic_case_index": 1,
            "is_insurance_related": True,
            "party_name": output.party_name,
            "institution_type": output.institution_type,
            "penalty_doc_no": output.penalty_doc_no,
            "violation_behavior": output.violation_behavior,
            "penalty_content": output.penalty_content,
            "regulator": output.regulator,
            "case_summary": output.case_summary,
            "risk_tags": risk_tags,
            "risk_tag_schema": "official_27_v1",
            "risk_domains": risk_domains,
            "primary_evidence_chunk_ids": [chunks[0]["chunk_id"]],
            "parse_status": "ok" if llm_used else "degraded",
            "review_status": "auto_checked" if llm_used else "manual_review_required",
            "retrieval_status": "active",
            "evidence_status": "verified" if valid_basis else "limited",
            "official_retrieval_protected": False,
            "data_version": self.data_version,
            "case_title": title,
            "region": None,
            "penalty_date": _valid_date(output.penalty_date),
            "publish_date": None,
            "related_parties": [value.model_dump() for value in output.related_parties],
            "penalty_amounts": [],
            "legal_basis_refs": [value.model_dump() for value in output.legal_basis_refs],
            "case_scene": None,
            "scene_subtype": None,
            "scene_source": None,
            "keywords": list(dict.fromkeys(output.keywords)),
            "marketing_relevance_score": 8 if output.marketing_expressions else 5,
            "marketing_relevance_reason": "Web 增量流程根据处罚事实与营销表达生成",
            "original_risk_tags": risk_tags,
            "risk_tag_basis": [
                {
                    **basis.model_dump(),
                    "link_source": "web_llm_evidence",
                    "evidence_chunk_ids": [chunks[0]["chunk_id"]],
                }
                for basis in valid_basis
            ],
            "risk_tag_confidence": output.confidence,
            "quality_flags": [
                "web_incremental",
                *("llm_structured" if llm_used else "rule_fallback",),
            ],
            "source_file": source_file,
            "source_type": extraction.media_type,
            "raw_text_path": None,
            "source_url": None,
            "source_sha256": extraction.checksum_sha256,
            "field_confidence": {"overall": output.confidence},
            "field_sources": {"method": "deepseek_v4_flash" if llm_used else "rule_fallback"},
            "created_at": today,
            "updated_at": today,
        }
        return CaseIngestionArtifacts(record, chunks, expansions, llm_used, warnings)

    async def _call_llm(self, text: str) -> _CaseLLMOutput:
        if self.llm_client is None:
            raise LLMProviderError("大模型未配置")
        excerpt = text if len(text) <= 40_000 else f"{text[:25_000]}\n[中间省略]\n{text[-15_000:]}"
        response = await self.llm_client.complete_json(
            JsonChatRequest(
                messages=[
                    ChatMessage(
                        role="system",
                        content=(
                            "你是保险监管处罚案例结构化专家。只能提取原文明确存在的事实；"
                            "不确定字段必须为null。risk_tags只能从给定标签选0到2个；"
                            "risk_tag_basis.quote必须是原文逐字片段。输出单个JSON对象，字段为："
                            "case_title,party_name,institution_type,penalty_doc_no,violation_behavior,"
                            "penalty_content,regulator,penalty_date(YYYY-MM-DD或null),related_parties,"
                            "legal_basis_refs,risk_tags,risk_tag_basis,case_summary,keywords,"
                            "marketing_expressions,confidence。"
                        ),
                    ),
                    ChatMessage(
                        role="user",
                        content=(
                            f"风险标签：{json.dumps(self.taxonomy, ensure_ascii=False)}\n"
                            f"处罚材料原文：\n{excerpt}"
                        ),
                    ),
                ],
                temperature=0.0,
                max_tokens=3000,
            )
        )
        try:
            return _CaseLLMOutput.model_validate(response.data)
        except ValidationError as error:
            raise LLMProviderError("DeepSeek 案例输出不符合字段契约") from error

    def _fallback(self, text: str) -> _CaseLLMOutput:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        title = lines[0][:500] if lines else None
        document_number = _first_match(
            r"[^\s，。]{0,16}(?:罚决字|罚字)[〔\[]?\d{4}[〕\]]?\d+号", text
        )
        regulator = _first_match(r"[^\n，。]{2,40}(?:金融监管局|银保监局|银保监分局)", text)
        penalty_date = _extract_date(text)
        penalty = _first_match(
            r"[^。；\n]{0,100}(?:警告|罚款|没收|责令)[^。；\n]{0,200}[。；]?", text
        )
        facts = _extract_facts(text)
        rule_result = self.rule_detector.detect(text)
        labels = [label for label in rule_result.risk_labels if label in self._taxonomy_set][:2]
        return _CaseLLMOutput(
            case_title=title,
            penalty_doc_no=document_number,
            violation_behavior=facts,
            penalty_content=penalty,
            regulator=regulator,
            penalty_date=penalty_date,
            risk_tags=labels,
            case_summary=facts[:900],
            keywords=labels,
            confidence=0.45,
        )


def load_risk_domain_mapping(path: str) -> dict[str, str]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("风险归口映射必须是 JSON 对象")
    return {str(key): str(domain) for key, domain in value.items()}


def _build_chunks(
    *,
    case_id: str,
    file_id: str,
    extraction: FileExtractionResult,
    violation_behavior: str,
    penalty_content: str | None,
    legal_basis: list[_LegalBasis],
    risk_tags: list[str],
    data_version: str,
) -> list[dict[str, object]]:
    values: list[tuple[str, str, float]] = [("fact", violation_behavior, 1.0)]
    if penalty_content:
        values.append(("penalty", penalty_content, 0.8))
    if legal_basis:
        legal_text = "；".join(f"{item.law_name}{item.article or ''}" for item in legal_basis)
        values.append(("legal_basis", legal_text, 0.65))
    chunks: list[dict[str, object]] = []
    for index, (chunk_type, chunk_text, weight) in enumerate(values, start=1):
        start = extraction.full_text.find(chunk_text)
        source_span = {
            "start_char": start if start >= 0 else None,
            "end_char": start + len(chunk_text) if start >= 0 else None,
            "page_no": None,
            "table_row": None,
            "section_title": None,
        }
        chunk_id = f"CHK_{case_id}_{chunk_type.upper()}_{index:03d}"
        chunks.append(
            {
                "schema_version": "case_chunk_v1",
                "chunk_id": chunk_id,
                "case_id": case_id,
                "file_id": file_id,
                "chunk_type": chunk_type,
                "chunk_text": chunk_text,
                "chunk_order": index,
                "retrieval_roles": [chunk_type, "evidence"]
                if chunk_type == "fact"
                else [chunk_type],
                "evidence_level": "direct" if start >= 0 else "normalized",
                "supports_risk_tags": risk_tags if chunk_type == "fact" else [],
                "is_verbatim": start >= 0,
                "source_span": source_span,
                "retrieval_enabled": True,
                "retrieval_modes": ["dense", "sparse"] if chunk_type == "fact" else ["sparse"],
                "retrieval_weight": weight,
                "extraction_method": extraction.extraction_method.value,
                "extraction_confidence": extraction.quality_score or 0.5,
                "quality_flags": [],
                "text_sha256": sha256(chunk_text.encode()).hexdigest(),
                "data_version": data_version,
            }
        )
    return chunks


def _build_expansions(
    *,
    case_id: str,
    values: list[str],
    risk_tags: list[str],
    risk_domains: list[str],
    data_version: str,
) -> list[dict[str, object]]:
    expansions: list[dict[str, object]] = []
    for value in dict.fromkeys(text.strip() for text in values if text.strip()):
        digest = sha256(f"{case_id}\0{value}".encode()).hexdigest().upper()
        expansions.append(
            {
                "schema_version": "case_expansion_v1",
                "expansion_id": f"EXP_{digest[:16]}",
                "expansion_text": value,
                "expansion_type": "marketing_expression",
                "case_links": [
                    {
                        "case_id": case_id,
                        "relevance": "high",
                        "link_source": "web_incremental",
                        "link_reason": "增量案例结构化流程生成",
                        "grounding_chunk_ids": [f"CHK_{case_id}_FACT_001"],
                    }
                ],
                "risk_tags": risk_tags,
                "risk_domains": risk_domains,
                "coarse_scene": None,
                "scene_subtype": None,
                "speaker_role": None,
                "communication_channel": None,
                "text_origin": "llm_or_rule",
                "fact_grounding": "case_fact",
                "synthetic_details": [],
                "prompt_version": "case-ingestion-v1",
                "source_ref": case_id,
                "quality_status": "generated_clean",
                "quality_flags": ["web_incremental"],
                "retrieval_enabled": True,
                "retrieval_modes": ["sparse"],
                "retrieval_weight": 0.35,
                "specificity_score": 0.7,
                "dataset_split": "none",
                "allowed_usage": "retrieval",
                "text_sha256": sha256(value.encode()).hexdigest(),
                "data_version": data_version,
            }
        )
    return expansions


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(0).strip() if match else None


def _extract_date(text: str) -> str | None:
    match = re.search(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?", text)
    if not match:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
    except ValueError:
        return None


def _valid_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def _extract_facts(text: str) -> str:
    match = re.search(
        r"(?:主要违法违规事实|违法违规事实|违法事实|案由)[：:\s]*(.{20,5000}?)(?=处罚依据|处罚决定|行政处罚|$)",
        text,
        re.DOTALL,
    )
    return (match.group(1) if match else text[:5000]).strip()
