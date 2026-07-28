"""Query 文件级分类、句子切分和增强测试。"""

import json
from pathlib import Path

import pytest

from domain.common import QueryInputType
from domain.query_models import QueryClassificationMethod, QuerySceneLabel
from query.classification import (
    QuerySceneClassifier,
    TrainingDataError,
    load_training_examples,
)
from query.enhancement import enhance_query, split_sentences


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "限时专享活动火热开启，立即扫码了解产品详情。",
            QuerySceneLabel.MARKETING_CONTENT,
        ),
        (
            "第一条 为规范业务办理制定本办法，各机构应当遵照执行。",
            QuerySceneLabel.FORMAL_DOCUMENT,
        ),
        (
            "客户：这款产品可以赎回吗？顾问：您好，我帮您查看相关约定。",
            QuerySceneLabel.CUSTOMER_COMMUNICATION,
        ),
    ],
)
def test_rule_classifier_recognizes_primary_scenes(
    tmp_path: Path,
    text: str,
    expected: QuerySceneLabel,
) -> None:
    """强场景特征应在没有训练数据时由规则准确分类。"""

    result = QuerySceneClassifier(tmp_path).classify(text)

    assert result.selected_category.category_code is expected
    assert result.classification_method is QueryClassificationMethod.RULE
    assert result.is_abstained is False
    assert result.classification_evidence


def test_classifier_abstains_when_scene_evidence_is_missing(tmp_path: Path) -> None:
    """没有可靠场景证据时不得强行三选一。"""

    result = QuerySceneClassifier(tmp_path).classify("今天更新了一些内容")

    assert result.selected_category.category_code is QuerySceneLabel.UNKNOWN_OR_MIXED
    assert result.classification_method is QueryClassificationMethod.ABSTAINED
    assert result.is_abstained is True
    assert result.augmentation_terms == []


def test_classifier_ignores_unknown_source_metadata(tmp_path: Path) -> None:
    """场景分类必须只使用文本，不依赖无法确定的来源字段。"""

    classifier = QuerySceneClassifier(tmp_path)
    without_metadata = classifier.classify("今天更新了一些内容")
    with_metadata = classifier.classify(
        "今天更新了一些内容",
        metadata={"source_channel": "poster"},
    )

    assert with_metadata == without_metadata


def test_sentence_split_preserves_text_and_offsets() -> None:
    """切句后应能用偏移从原文精确还原每句话。"""

    text = "您好！\n第二句话； 第三句话。"
    sentences = split_sentences(text)

    assert [sentence.text for sentence in sentences] == ["您好！", "第二句话；", "第三句话。"]
    assert [text[sentence.start_offset : sentence.end_offset] for sentence in sentences] == [
        sentence.text for sentence in sentences
    ]


def test_enhancement_repeats_file_classification_for_each_sentence(tmp_path: Path) -> None:
    """同一文件切出的所有句子必须继承统一文件级分类。"""

    classifier = QuerySceneClassifier(tmp_path)
    result = enhance_query(
        "第一条 本办法自发布之日起生效。第二条 各部门应当遵照执行。",
        classifier,
        input_type=QueryInputType.TEXT,
    )

    assert len(result.sentences) == 2
    assert {sentence.category.category_code for sentence in result.sentences} == {
        QuerySceneLabel.FORMAL_DOCUMENT
    }
    assert all("[QUERY_SCENE=formal_document]" in item.enhanced_text for item in result.sentences)


def test_training_loader_uses_exact_four_field_schema(tmp_path: Path) -> None:
    """真实训练数据固定使用 sample_id、text、scene、risk_label。"""

    template = tmp_path / "query_scene_train.example.jsonl"
    template.write_text(
        json.dumps(
            {
                "sample_id": "template",
                "text": "模板内容",
                "scene": "formal_document",
                "risk_label": "no_obvious_risk",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    training = tmp_path / "query_scene_train.jsonl"
    training.write_text(
        json.dumps(
            {
                "sample_id": "real_001",
                "text": "第一条 本办法自发布之日起生效。",
                "scene": "formal_document",
                "risk_label": "no_obvious_risk",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    examples = load_training_examples(tmp_path)

    assert [example.sample_id for example in examples] == ["real_001"]
    assert examples[0].scene is QuerySceneLabel.FORMAL_DOCUMENT
    assert examples[0].risk_label == "no_obvious_risk"
    assert set(examples[0].model_dump()) == {"sample_id", "text", "scene", "risk_label"}


def test_training_loader_rejects_source_and_notes_fields(tmp_path: Path) -> None:
    """来源和备注等额外字段不得进入新的训练数据契约。"""

    (tmp_path / "query_scene_train.jsonl").write_text(
        json.dumps(
            {
                "sample_id": "invalid_001",
                "text": "限时活动立即参与。",
                "scene": "marketing_content",
                "risk_label": "no_obvious_risk",
                "source_channel": "poster",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TrainingDataError):
        load_training_examples(tmp_path)


def test_classifier_trains_model_when_each_scene_has_enough_data(tmp_path: Path) -> None:
    """三类 scene 数据达到下限后应启用轻量分类模型。"""

    rows: list[str] = []
    texts_by_scene = {
        "marketing_content": [
            "夏日活动立即参与",
            "专属优惠点击领取",
            "产品亮点火热发布",
            "扫码查看营销海报",
            "名额有限欢迎预约",
        ],
        "formal_document": [
            "第一条制定本办法",
            "本协议经双方签署生效",
            "各机构应当遵照执行",
            "关于流程调整的正式通知",
            "甲乙双方约定权利义务",
        ],
        "customer_communication": [
            "客户：我可以办理吗",
            "客服：您好我帮您查询",
            "请问您现在方便吗",
            "顾问与客户聊天记录",
            "电话沟通标准话术",
        ],
    }
    index = 0
    for scene, texts in texts_by_scene.items():
        for text in texts:
            index += 1
            rows.append(
                json.dumps(
                    {
                        "sample_id": f"sample_{index:03d}",
                        "text": text,
                        "scene": scene,
                        "risk_label": "no_obvious_risk",
                    },
                    ensure_ascii=False,
                )
            )
    (tmp_path / "query_scene_train.jsonl").write_text("\n".join(rows), encoding="utf-8")

    classifier = QuerySceneClassifier(tmp_path)
    result = classifier.classify("这是顾问与具体客户的一段沟通记录")

    assert classifier.status.model_ready is True
    assert classifier.status.training_example_count == 15
    assert result.classifier_version.startswith("query-scene-hybrid")


def test_training_loader_rejects_unknown_scene(tmp_path: Path) -> None:
    """未知或混合不能作为场景模型训练类别。"""

    (tmp_path / "query_scene_train.jsonl").write_text(
        json.dumps(
            {
                "sample_id": "unknown_001",
                "text": "无法判断",
                "scene": "unknown_or_mixed",
                "risk_label": "no_obvious_risk",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(TrainingDataError):
        load_training_examples(tmp_path)
