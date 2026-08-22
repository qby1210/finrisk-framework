"""FinRisk 运行路径配置。

所有业务模块通过 :class:`AppSettings` 获取数据位置，避免在案例、检索、风险和
API 层分别拼接路径。环境变量只用于覆盖部署路径，默认值均相对项目根目录。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolve_path(value: str | None, default: Path) -> Path:
    path = Path(value).expanduser() if value else default
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


@dataclass(frozen=True, slots=True)
class AppSettings:
    """应用共用的数据和上传限制配置。"""

    project_root: Path
    case_kb_root: Path
    risk_keyword_path: Path
    raw_case_upload_dir: Path
    max_upload_size_bytes: int = 25 * 1024 * 1024

    @classmethod
    def from_env(cls) -> AppSettings:
        """读取路径覆盖；不在此处加载或暴露任何 API 密钥。"""

        knowledge_root = PROJECT_ROOT / "data" / "processed" / "knowledge"
        return cls(
            project_root=PROJECT_ROOT,
            case_kb_root=_resolve_path(
                os.getenv("FINRISK_CASE_KB_ROOT"),
                knowledge_root / "case_kb_v2_1_2026-08-18",
            ),
            risk_keyword_path=_resolve_path(
                os.getenv("FINRISK_RISK_KEYWORD_PATH"),
                PROJECT_ROOT / "data" / "risk" / "keyword_db" / "risk_keyword_db.json",
            ),
            raw_case_upload_dir=_resolve_path(
                os.getenv("FINRISK_RAW_CASE_UPLOAD_DIR"),
                PROJECT_ROOT / "data" / "raw" / "cases" / "uploads",
            ),
            max_upload_size_bytes=int(
                os.getenv("FINRISK_MAX_UPLOAD_SIZE_BYTES", str(25 * 1024 * 1024))
            ),
        )

    @property
    def case_data_dir(self) -> Path:
        return self.case_kb_root / "data"

    @property
    def cases_path(self) -> Path:
        return self.case_data_dir / "cases.jsonl"

    @property
    def chunks_path(self) -> Path:
        return self.case_data_dir / "case_chunks.jsonl"

    @property
    def expansions_path(self) -> Path:
        return self.case_data_dir / "case_expansions.jsonl"

    @property
    def risk_dictionary_path(self) -> Path:
        return self.case_kb_root / "dictionary" / "risk_type_dictionary.csv"

    @property
    def manifest_path(self) -> Path:
        return self.case_kb_root / "manifest.json"
