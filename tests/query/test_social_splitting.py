"""社交平台多行文案的切分回归测试。"""

from query.enhancement import split_sentences


def test_social_media_bullets_start_new_risk_sentences() -> None:
    text = "产品介绍\n✅ 投保门槛\n⭐3人起投\n⭐保障有效期内可增减人员\n👉 点击立即咨询"

    sentences = split_sentences(text)

    assert [item.text for item in sentences] == [
        "产品介绍",
        "✅ 投保门槛",
        "⭐3人起投",
        "⭐保障有效期内可增减人员",
        "👉 点击立即咨询",
    ]
    assert all(text[item.start_offset : item.end_offset] == item.text for item in sentences)
