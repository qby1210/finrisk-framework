"""Query 场景分类的公开入口和人工标注数据契约。

人工标注固定使用 ``sample_id``、``text``、``scene``、``risk_label`` 四个字段。
当前场景分类器只消费 ``text`` 和 ``scene``；``risk_label`` 保留给后续 Risk 模块。
"""

import json
from collections.abc import Mapping
from pathlib import Path

from pydantic import Field, field_validator

from domain.common import ContractModel
from domain.query_models import QueryClassification, QuerySceneLabel
from query import _classification_core as _core

ClassifierStatus = _core.ClassifierStatus
HYBRID_CLASSIFIER_VERSION = _core.HYBRID_CLASSIFIER_VERSION
RULE_CLASSIFIER_VERSION = _core.RULE_CLASSIFIER_VERSION
TAXONOMY_VERSION = _core.TAXONOMY_VERSION
category_name = _core.category_name


class QueryTrainingExample(ContractModel):
    """固定四字段的人工标注 Query。"""

    sample_id: str = Field(min_length=1, description="训练样本稳定标识")
    text: str = Field(min_length=1, description="已经完成读取和清洗的完整 Query 文本")
    scene: QuerySceneLabel = Field(description="Query 使用场景分类")
    risk_label: str = Field(
        min_length=1,
        description="整段 Query 的风险标签，当前仅保留给 Risk 模块",
    )

    @field_validator("scene")
    @classmethod
    def reject_unknown_training_scene(cls, value: QuerySceneLabel) -> QuerySceneLabel:
        """未知/混合是运行时回退场景，不作为模型训练类别。"""

        if value is QuerySceneLabel.UNKNOWN_OR_MIXED:
            raise ValueError("unknown_or_mixed 不用于训练，请保留为人工复核样本")
        return value

    @property
    def label(self) -> QuerySceneLabel:
        """兼容内部分类核心使用的场景字段名称。"""

        return self.scene


class TrainingDataError(ValueError):
    """训练数据文件格式不符合四字段约定。"""


def load_training_examples(training_dir: str | Path) -> list[QueryTrainingExample]:
    """读取四字段 JSONL 标注数据，并忽略 ``*.example.jsonl`` 模板。"""

    directory = Path(training_dir)
    if not directory.exists():
        return []

    examples: list[QueryTrainingExample] = []
    seen_ids: set[str] = set()
    for path in sorted(directory.glob("*.jsonl")):
        if ".example." in path.name:
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw_value = json.loads(line)
                example = QueryTrainingExample.model_validate(raw_value)
            except (json.JSONDecodeError, ValueError) as error:
                raise TrainingDataError(
                    f"{path.name} 第 {line_number} 行格式错误：{error}"
                ) from error
            if example.sample_id in seen_ids:
                raise TrainingDataError(f"训练样本 sample_id 重复：{example.sample_id}")
            seen_ids.add(example.sample_id)
            examples.append(example)
    return examples


setattr(_core, "load_training_examples", load_training_examples)


class QuerySceneClassifier(_core.QuerySceneClassifier):
    """只根据合并后的 Query 文本进行规则或模型场景分类。"""

    def classify(
        self,
        text: str,
        metadata: Mapping[str, object] | None = None,
    ) -> QueryClassification:
        """分类时忽略来源元数据，避免未知来源影响场景判断。"""

        del metadata
        return super().classify(text, None)


__all__ = [
    "ClassifierStatus",
    "HYBRID_CLASSIFIER_VERSION",
    "QuerySceneClassifier",
    "QueryTrainingExample",
    "RULE_CLASSIFIER_VERSION",
    "TAXONOMY_VERSION",
    "TrainingDataError",
    "category_name",
    "load_training_examples",
]
