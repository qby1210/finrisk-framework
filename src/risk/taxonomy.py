"""27类风险标签定义、关系扩展与提示词格式化。"""

from __future__ import annotations

import csv
from pathlib import Path

_RELATED_LABELS: dict[str, tuple[str, ...]] = {
    "欺骗投保人": ("销售误导",),
    "夸大收益": ("销售误导", "虚假宣传"),
    "承诺收益": ("销售误导",),
    "保证收益": ("承诺收益", "夸大收益", "销售误导"),
    "虚构收益率": ("夸大收益", "虚假宣传", "销售误导"),
    "弱化风险提示": ("隐瞒重要信息", "销售误导"),
    "隐瞒重要信息": ("销售误导",),
    "赠送利益": ("合同外利益", "诱导投保"),
    "合同外利益": ("赠送利益",),
    "回扣返佣": ("合同外利益",),
    "贬低竞品": ("不当比较",),
}


def load_taxonomy_descriptions(path: Path) -> dict[str, str]:
    """读取风险字典说明；缺列时安全降级为标签名。"""

    if not path.is_file():
        return {}
    descriptions: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            label = next(
                (
                    str(row[key]).strip()
                    for key in ("risk_tag", "risk_type", "label_name", "风险类型", "标签名称")
                    if row.get(key)
                ),
                "",
            )
            if not label:
                continue
            description = next(
                (
                    str(row[key]).strip()
                    for key in ("description", "definition", "说明", "定义")
                    if row.get(key)
                ),
                label,
            )
            descriptions[label] = description
    return descriptions


def taxonomy_prompt(
    labels: tuple[str, ...],
    descriptions: dict[str, str],
) -> str:
    return "\n".join(f"- {label}：{descriptions.get(label, label)}" for label in labels)


def expand_related_labels(
    labels: list[str],
    allowed: set[str],
    *,
    limit: int = 10,
) -> list[str]:
    """补全明确的上下位或紧密相关标签，保留原始标签优先顺序。"""

    expanded = list(dict.fromkeys(label for label in labels if label in allowed))
    for label in tuple(expanded):
        expanded.extend(
            related for related in _RELATED_LABELS.get(label, ()) if related in allowed
        )
    expanded = list(dict.fromkeys(expanded))
    if len(expanded) > 1 and "其他" in expanded:
        expanded.remove("其他")
    return expanded[:limit]
