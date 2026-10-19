"""Carry literal document-level quotation/correction framing into split review batches."""

from __future__ import annotations

import re

from domain.query_models import QueryProcessingResult, RiskSentenceContext

_FRAME = re.compile(
    r"反面(?:教材|示例|案例)|错误(?:示例|示范)|教学立场|"
    r"仅(?:作|作为|供).{0,8}(?:警示|教学|反面)|"
    r"(?:做法|方案|提案).{0,16}(?:已被否决|已经否决|未被采纳)|"
    r"请(?:先)?停止.{0,8}方案执行|(?:一旦执行|如果执行).{0,40}属于|"
    r"(?:错误|不当)(?:说法|口径|示例).{0,16}(?:不能照讲|不得模仿|不得照做)"
)


def rejected_proposal_only(text: str) -> bool:
    """A rejected, unexecuted proposal is a corrective review, not an active instruction."""
    return bool(
        re.search(r"方案[（(]待审[）)]|(?:方案|提案).{0,10}尚未执行", text)
        and re.search(r"请先停止该方案执行|该方案已被否决|该提案未被采纳", text)
        and not re.search(r"已开始(?:执行|投放)|正在执行|已经实施|仍在执行|照此继续", text)
    )


def carry_document_frame(
    query: QueryProcessingResult,
    contexts: dict[str, RiskSentenceContext],
) -> dict[str, RiskSentenceContext]:
    """Add bounded, verbatim framing as context, without changing any risk decision.

    Blank paragraphs still isolate products and speakers. These additional source
    sentences only explain whether a passage is a quotation or a corrective task;
    they do not transfer another paragraph's business facts to the target.
    """
    rejected = rejected_proposal_only(query.source_text)
    anchors = [sentence for sentence in query.sentences if _FRAME.search(sentence.text)]
    if not anchors:
        return contexts
    chosen = [anchors[0]] if len(anchors) == 1 else [anchors[0], anchors[-1]]
    selected = []
    used = 0
    for sentence in chosen:
        if used + len(sentence.text) > 650:
            continue
        selected.append(sentence)
        used += len(sentence.text)
    mappings = {mapping.sentence_id: mapping for mapping in query.source_mappings}
    from domain.query_models import ContextSourceSentence

    framed = {}
    for sid, context in contexts.items():
        existing = {source.sentence_id for source in context.source_sentences}
        additions = [
            ContextSourceSentence(
                sentence_id=sentence.sentence_id,
                text=sentence.text,
                document_start_offset=mappings[sentence.sentence_id].document_start_offset,
                document_end_offset=mappings[sentence.sentence_id].document_end_offset,
                speaker_role="unknown",
                is_target=False,
            )
            for sentence in selected
            if sentence.sentence_id not in existing
        ]
        framed[sid] = context.model_copy(
            update={
                "source_sentences": sorted(
                    [*context.source_sentences, *additions],
                    key=lambda source: source.document_start_offset,
                ),
                "requires_review": False if rejected else True,
                "stance": "negative_example" if rejected else context.stance,
                "review_reasons": [
                    *context.review_reasons,
                    "全文含引述或纠错立场；仅解释目标句立场，不借用其他段落事实",
                    *(["rejected_proposal_only"] if rejected else []),
                ],
            }
        )
    return framed
