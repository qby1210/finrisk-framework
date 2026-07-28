"""Query 文件级场景分类。

分类器优先使用可解释的结构和关键词规则；当 ``data/interim/train_data`` 中
存在足够人工标注数据时，会训练字符级 TF-IDF + Logistic Regression，并与规则融合。
该分类只描述 Query 的使用场景，不产生任何风险类别。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, field_validator
from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]

from domain.common import ContractModel
from domain.query_models import (
    QueryCategoryPrediction,
    QueryClassification,
    QueryClassificationMethod,
    QuerySceneLabel,
)

TAXONOMY_VERSION = "query-scene-1.0"
RULE_CLASSIFIER_VERSION = "query-scene-rules-1.0"
HYBRID_CLASSIFIER_VERSION = "query-scene-hybrid-char-tfidf-1.0"

_PRIMARY_LABELS = (
    QuerySceneLabel.MARKETING_CONTENT,
    QuerySceneLabel.FORMAL_DOCUMENT,
    QuerySceneLabel.CUSTOMER_COMMUNICATION,
)

_CATEGORY_NAMES = {
    QuerySceneLabel.MARKETING_CONTENT: "营销宣传材料",
    QuerySceneLabel.FORMAL_DOCUMENT: "正式业务文件",
    QuerySceneLabel.CUSTOMER_COMMUNICATION: "客户沟通话术",
    QuerySceneLabel.UNKNOWN_OR_MIXED: "未知或混合",
}

_AUGMENTATION_TERMS = {
    QuerySceneLabel.MARKETING_CONTENT: [
        "面向客户的单向传播",
        "产品或服务推介",
        "营销材料语境",
    ],
    QuerySceneLabel.FORMAL_DOCUMENT: [
        "正式业务文件",
        "权利义务或流程约定",
        "书面留痕语境",
    ],
    QuerySceneLabel.CUSTOMER_COMMUNICATION: [
        "一对一客户沟通",
        "问答或话术语境",
        "具体客户交互",
    ],
    QuerySceneLabel.UNKNOWN_OR_MIXED: [],
}


class QueryTrainingExample(ContractModel):
    """人工标注的一条 Query 场景训练数据。"""

    sample_id: str = Field(min_length=1, description="训练样本稳定标识")
    text: str = Field(min_length=1, description="已经完成文件读取和文本清洗的完整内容")
    label: QuerySceneLabel = Field(description="人工标注的三个主要场景之一")
    source_channel: str | None = Field(default=None, description="可选的来源渠道")
    notes: str | None = Field(default=None, description="可选的标注理由或边界说明")

    @field_validator("label")
    @classmethod
    def reject_unknown_training_label(cls, value: QuerySceneLabel) -> QuerySceneLabel:
        """未知/混合是运行时回退类别，不作为模型训练类别。"""

        if value is QuerySceneLabel.UNKNOWN_OR_MIXED:
            raise ValueError("unknown_or_mixed 不用于训练，请保留为人工复核样本")
        return value


class TrainingDataError(ValueError):
    """训练数据文件格式不符合约定。"""


class _ProbabilityModel(Protocol):
    """分类模型在运行时需要提供的最小接口。"""

    classes_: Sequence[str]

    def predict_proba(self, raw_documents: list[str]) -> NDArray[np.float64]:
        """返回每个类别的预测概率。"""

        ...


@dataclass(frozen=True, slots=True)
class _Rule:
    """单条可解释场景规则。"""

    label: QuerySceneLabel
    pattern: re.Pattern[str]
    weight: float
    description: str


@dataclass(frozen=True, slots=True)
class ClassifierStatus:
    """用于接口和测试查看分类器是否加载了人工标注数据。"""

    model_ready: bool
    training_example_count: int
    examples_per_label: dict[str, int]
    classifier_version: str


_RULES = (
    _Rule(
        QuerySceneLabel.MARKETING_CONTENT,
        re.compile(r"(?:限时|限量|立即参与|立即购买|扫码|点击领取|优惠|活动期间)"),
        1.5,
        "出现营销行动号召",
    ),
    _Rule(
        QuerySceneLabel.MARKETING_CONTENT,
        re.compile(r"(?:产品亮点|重磅|火热|尊享|专属|全新升级|诚邀|名额有限)"),
        1.3,
        "出现宣传推介表达",
    ),
    _Rule(
        QuerySceneLabel.MARKETING_CONTENT,
        re.compile(r"(?:海报|宣传页|宣传文案|推广文案|营销短信)"),
        1.8,
        "明确说明为宣传材料",
    ),
    _Rule(
        QuerySceneLabel.FORMAL_DOCUMENT,
        re.compile(r"第[零一二三四五六七八九十百千万\d]+[编章节条款项]"),
        2.0,
        "出现正式文件条款结构",
    ),
    _Rule(
        QuerySceneLabel.FORMAL_DOCUMENT,
        re.compile(r"(?:特此通知|本办法|本制度|本合同|本协议|甲方|乙方|签署|盖章)"),
        1.6,
        "出现正式文件固定表达",
    ),
    _Rule(
        QuerySceneLabel.FORMAL_DOCUMENT,
        re.compile(r"(?:应当|不得|依据|有效期|生效之日|违约责任|权利义务)"),
        0.9,
        "出现规范性或权利义务表达",
    ),
    _Rule(
        QuerySceneLabel.CUSTOMER_COMMUNICATION,
        re.compile(r"(?:客户|客服|坐席|顾问|经理|销售)[：:]"),
        2.1,
        "出现明确对话角色",
    ),
    _Rule(
        QuerySceneLabel.CUSTOMER_COMMUNICATION,
        re.compile(r"(?:您好|请问|方便吗|您看|我帮您|可以吗|好的[，。]|没问题)"),
        1.0,
        "出现一对一沟通表达",
    ),
    _Rule(
        QuerySceneLabel.CUSTOMER_COMMUNICATION,
        re.compile(r"(?:话术|聊天记录|通话记录|客服问答|沟通记录)"),
        1.8,
        "明确说明为客户沟通内容",
    ),
)


class QuerySceneClassifier:
    """规则优先、人工标注模型补充的 Query 文件级场景分类器。"""

    def __init__(
        self,
        training_dir: str | Path,
        *,
        min_samples_per_label: int = 5,
        model_confidence_threshold: float = 0.55,
        ambiguity_margin: float = 0.10,
    ) -> None:
        """加载训练数据；数据不足时自动退回纯规则模式。"""

        self.training_dir = Path(training_dir)
        self.min_samples_per_label = min_samples_per_label
        self.model_confidence_threshold = model_confidence_threshold
        self.ambiguity_margin = ambiguity_margin
        self._model: _ProbabilityModel | None = None
        self._training_examples: list[QueryTrainingExample] = []
        self.reload()

    @property
    def status(self) -> ClassifierStatus:
        """返回当前分类器和训练数据状态。"""

        counts = Counter(example.label.value for example in self._training_examples)
        return ClassifierStatus(
            model_ready=self._model is not None,
            training_example_count=len(self._training_examples),
            examples_per_label=dict(counts),
            classifier_version=(
                HYBRID_CLASSIFIER_VERSION if self._model is not None else RULE_CLASSIFIER_VERSION
            ),
        )

    def reload(self) -> ClassifierStatus:
        """重新读取人工标注数据并在满足条件时训练轻量模型。"""

        self._training_examples = load_training_examples(self.training_dir)
        counts = Counter(example.label for example in self._training_examples)
        has_enough_data = all(
            counts[label] >= self.min_samples_per_label for label in _PRIMARY_LABELS
        )
        if not has_enough_data:
            self._model = None
            return self.status

        model = Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        analyzer="char",
                        ngram_range=(2, 4),
                        min_df=1,
                        max_features=20_000,
                        sublinear_tf=True,
                    ),
                ),
                (
                    "classifier",
                    LogisticRegression(
                        max_iter=1_000,
                        class_weight="balanced",
                        random_state=42,
                    ),
                ),
            ]
        )
        texts = [example.text for example in self._training_examples]
        labels = [example.label.value for example in self._training_examples]
        model.fit(texts, labels)
        self._model = cast(_ProbabilityModel, model)
        return self.status

    def classify(
        self,
        text: str,
        metadata: Mapping[str, object] | None = None,
    ) -> QueryClassification:
        """对文件抽取后的完整文本进行一次场景分类。"""

        normalized_text = text.strip()
        if not normalized_text:
            raise ValueError("Query 文本不能为空")

        rule_scores, evidence = _score_rules(normalized_text, metadata)
        rule_probabilities = _softmax(rule_scores)
        active_probabilities = rule_probabilities
        method = QueryClassificationMethod.RULE

        if self._model is not None:
            model_probabilities = self._predict_model_probabilities(normalized_text)
            if max(rule_scores.values()) > 0:
                active_probabilities = {
                    label: 0.65 * model_probabilities[label] + 0.35 * rule_probabilities[label]
                    for label in _PRIMARY_LABELS
                }
                method = QueryClassificationMethod.HYBRID
            else:
                active_probabilities = model_probabilities
                method = QueryClassificationMethod.MODEL

        ranked = sorted(active_probabilities.items(), key=lambda item: item[1], reverse=True)
        top_label, top_probability = ranked[0]
        second_probability = ranked[1][1]
        margin = top_probability - second_probability

        if self._model is None:
            accepted = (
                rule_scores[top_label] >= 1.5
                and top_probability >= 0.55
                and margin >= self.ambiguity_margin
            )
        else:
            accepted = (
                top_probability >= self.model_confidence_threshold
                and margin >= self.ambiguity_margin
            )

        candidates = [_prediction(label, probability) for label, probability in ranked]
        if accepted:
            selected = _prediction(top_label, top_probability)
            augmentation_terms = list(_AUGMENTATION_TERMS[top_label])
            is_abstained = False
            classification_method = method
        else:
            selected = _prediction(
                QuerySceneLabel.UNKNOWN_OR_MIXED,
                min(max(1.0 - margin, 0.0), 1.0),
            )
            augmentation_terms = []
            is_abstained = True
            classification_method = QueryClassificationMethod.ABSTAINED

        return QueryClassification(
            selected_category=selected,
            candidates=candidates,
            augmentation_terms=augmentation_terms,
            classification_method=classification_method,
            classification_evidence=evidence[top_label],
            is_abstained=is_abstained,
            classifier_version=self.status.classifier_version,
            taxonomy_version=TAXONOMY_VERSION,
        )

    def _predict_model_probabilities(self, text: str) -> dict[QuerySceneLabel, float]:
        """把 sklearn 概率映射到固定的三个场景类别。"""

        if self._model is None:
            raise RuntimeError("分类模型尚未训练")
        raw_probabilities = self._model.predict_proba([text])[0]
        by_code = {
            QuerySceneLabel(code): float(probability)
            for code, probability in zip(
                self._model.classes_,
                raw_probabilities,
                strict=True,
            )
        }
        return {label: by_code.get(label, 0.0) for label in _PRIMARY_LABELS}


def load_training_examples(training_dir: str | Path) -> list[QueryTrainingExample]:
    """读取目录中的 JSONL 标注数据，自动忽略 ``*.example.jsonl`` 模板。"""

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


def category_name(label: QuerySceneLabel) -> str:
    """返回场景分类的中文展示名。"""

    return _CATEGORY_NAMES[label]


def _score_rules(
    text: str,
    metadata: Mapping[str, object] | None,
) -> tuple[dict[QuerySceneLabel, float], dict[QuerySceneLabel, list[str]]]:
    """计算规则分数并保留可解释证据。"""

    scores = dict.fromkeys(_PRIMARY_LABELS, 0.0)
    evidence: dict[QuerySceneLabel, list[str]] = {label: [] for label in _PRIMARY_LABELS}

    for rule in _RULES:
        matches = rule.pattern.findall(text)
        if not matches:
            continue
        multiplier = min(len(matches), 3)
        scores[rule.label] += rule.weight * multiplier
        evidence[rule.label].append(f"{rule.description}（{len(matches)} 处）")

    metadata_text = " ".join(str(value) for value in (metadata or {}).values()).lower()
    metadata_hints = (
        (
            QuerySceneLabel.CUSTOMER_COMMUNICATION,
            ("chat", "call", "im", "客服", "通话", "聊天"),
            "来源渠道显示为客户沟通",
        ),
        (
            QuerySceneLabel.MARKETING_CONTENT,
            ("poster", "campaign", "marketing", "海报", "营销", "宣传"),
            "来源渠道显示为营销传播",
        ),
        (
            QuerySceneLabel.FORMAL_DOCUMENT,
            ("contract", "policy", "notice", "agreement", "合同", "制度", "通知"),
            "来源信息显示为正式文件",
        ),
    )
    for label, hints, description in metadata_hints:
        if any(hint in metadata_text for hint in hints):
            scores[label] += 2.0
            evidence[label].append(description)

    return scores, evidence


def _softmax(scores: Mapping[QuerySceneLabel, float]) -> dict[QuerySceneLabel, float]:
    """把规则分数转换为可比较的归一化概率。"""

    maximum = max(scores.values())
    exponentials = {label: math.exp(score - maximum) for label, score in scores.items()}
    total = sum(exponentials.values())
    return {label: value / total for label, value in exponentials.items()}


def _prediction(
    label: QuerySceneLabel,
    probability: float,
) -> QueryCategoryPrediction:
    """创建统一候选类别对象。"""

    return QueryCategoryPrediction(
        category_code=label,
        category_name=_CATEGORY_NAMES[label],
        probability=round(probability, 6),
    )
