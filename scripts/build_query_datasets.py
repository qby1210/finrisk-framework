"""构建六场景 Query 基准、开发集和长尾增强集。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEST_SET = ROOT / "data/raw/query/query_test_set_160.json"
DEFAULT_TRAIN_QUERIES = ROOT / "data/raw/query/retrieval_train_queries.jsonl"
DEFAULT_DEV_SET = ROOT / "data/raw/query/query_dev_set.json"
DEFAULT_LONG_TAIL_SET = ROOT / "data/raw/query/query_long_tail_enhancement.json"

SCENES = (
    "ST1_poster_sms_social",
    "ST2_live_short_video",
    "ST3_product_intro_detail",
    "ST4_meeting_material",
    "ST5_training_telemarketing_callback",
    "ST6_penalty_backend_fact",
)

LABEL_ALIASES = {
    "误导": "销售误导",
    "夸大宣传": "虚假宣传",
    "错误解释保险责任": "销售误导",
    "隐藏重要信息": "隐瞒重要信息",
    "夸大服务": "虚假宣传",
}

SCENE_RULES = (
    ("ST6_penalty_backend_fact", re.compile(r"处罚|监管|经查|违法事实|系统记录|审计|台账")),
    ("ST5_training_telemarketing_callback", re.compile(r"培训|坐席|电销|电话|回访|异议处理|话术")),
    ("ST4_meeting_material", re.compile(r"说明会|答谢会|讲座|会议|主讲|嘉宾")),
    ("ST2_live_short_video", re.compile(r"直播|短视频|主播|口播|镜头|小黄车")),
    (
        "ST3_product_intro_detail",
        re.compile(r"产品详情|保障责任|保险责任|投保年龄|缴费|现金价值|免责"),
    ),
)

LONG_TAIL_TEMPLATES: dict[str, dict[str, Any]] = {
    "未按规定使用费率条款": {
        "scene": "ST6_penalty_backend_fact",
        "secondary": [],
        "clauses": [
            "系统抽查发现，该业务实际收取的保险费与经审批备案的费率条款不一致。",
            "为促成签单，机构自行下调保费，未按照报批报备的费率方案执行。",
            "业务台账显示，同类客户被采用两套未备案的费率口径计算保费。",
            "分支机构以活动折扣名义改变费率，相关方案未经规定程序审批。",
        ],
    },
    "虚列费用套取资金": {
        "scene": "ST6_penalty_backend_fact",
        "secondary": [],
        "clauses": [
            "财务凭证显示，机构虚列会议费后将资金转入个人账户用于业务维护。",
            "公司通过伪造宣传品采购合同虚增费用，套取资金支付渠道奖励。",
            "审计发现多笔并未实际发生的培训费，报销款被用于返还客户。",
            "分支机构虚构咨询服务项目列支费用，再将资金转给销售团队使用。",
        ],
    },
    "电销违规": {
        "scene": "ST5_training_telemarketing_callback",
        "secondary": ["销售误导"],
        "clauses": [
            "【材料载体：电销话术材料】坐席无需说明来电目的，直接把保险产品介绍成银行存款。",
            "【材料载体：电销话术材料】客户拒绝后仍连续拨打，并要求统一使用保证回本的促成说法。",
            "【材料载体：电销话术材料】通话中隐去保险公司名称，只强调这是银行客户专享收益。",
            "【材料载体：电销话术材料】未取得客户同意即可开始销售，录音不完整的通话也可提交承保。",
        ],
    },
    "委托无资质机构销售": {
        "scene": "ST6_penalty_backend_fact",
        "secondary": ["代理人管理不到位"],
        "clauses": [
            "机构将保险销售工作整体交给未取得相应业务许可的科技公司实施。",
            "后台记录显示，多笔保单由没有保险销售资质的第三方平台人员促成。",
            "分支机构与普通咨询公司签约，由该公司直接向客户讲解并销售保险。",
            "机构通过无资质的社区服务站代收投保资料并完成产品推荐。",
        ],
    },
    "回访违规": {
        "scene": "ST5_training_telemarketing_callback",
        "secondary": ["客户信息不真实"],
        "clauses": [
            "【材料载体：客户回访材料】销售人员先把标准答案发给客户，再由回访人员照表确认。",
            "【材料载体：客户回访材料】客户明确表示不了解免责条款，坐席仍将该项记录为已知晓。",
            "【材料载体：客户回访材料】未完成电话回访，系统中却被人工勾选为回访成功。",
            "【材料载体：客户回访材料】回访录音由销售人员代答，客户本人并未参加。",
        ],
    },
    "避债避税": {
        "scene": "ST3_product_intro_detail",
        "secondary": ["销售误导"],
        "clauses": [
            "产品详情宣称购买该保险后任何债权人都无法追索，资产绝对安全。",
            "宣传页写明保单收益完全免税，不受未来税收政策变化影响。",
            "销售材料称只要把资金放进保单，就能合法隔离全部婚姻和债务风险。",
            "页面承诺保险金不会进入遗产处理程序，可以无条件规避税费。",
        ],
    },
    "虚构收益率": {
        "scene": "ST3_product_intro_detail",
        "secondary": ["夸大收益", "虚假宣传", "销售误导"],
        "clauses": [
            "产品页面展示并不存在的年化12%历史收益率，且未说明计算来源。",
            "宣传材料把演示数据写成过去五年每年固定增长8%，实际没有对应记录。",
            "详情页虚构同类账户连续十年正收益，并将其作为未来回报依据。",
            "产品介绍引用未经证实的复利回报表，声称三年收益可达到本金的40%。",
        ],
    },
    "欺骗投保人": {
        "scene": "ST1_poster_sms_social",
        "secondary": ["销售误导"],
        "clauses": [
            "营销短信把保险说成银行定期存款，并声称到期可随时取回全部本金。",
            "朋友圈文案故意隐瞒保险产品属性，让客户误以为是监管部门推出的福利。",
            "海报伪称该产品由政府兜底，实际合同中不存在任何此类保证。",
            "短文案将十年缴费期说成一次存款，诱使客户在不知情时完成投保。",
        ],
    },
    "贬低竞品": {
        "scene": "ST2_live_short_video",
        "secondary": ["不当比较"],
        "clauses": [
            "直播口播称其他公司的同类保险都是骗人的，只有本公司产品可靠。",
            "主播没有提供数据便断言竞品理赔最差、服务完全没有保障。",
            "短视频脚本要求直接点名竞争公司，并称其产品购买后一定会后悔。",
            "直播材料把同业产品描述为毫无价值，以此突出本产品优势。",
        ],
    },
}


def _normalized_text(value: str) -> str:
    value = re.sub(r"^【材料载体：[^】]+】\s*", "", value.strip())
    return re.sub(r"\s+", "", value)


def _bucket(value: str) -> str:
    length = len(re.sub(r"\s+", "", value))
    if length <= 50:
        return "short"
    if length <= 300:
        return "medium"
    return "long"


def _infer_scene(text: str) -> str:
    for scene, pattern in SCENE_RULES:
        if pattern.search(text):
            return scene
    direct_address = len(re.findall(r"您|先生|女士|大哥|大姐|姐|哥", text))
    if direct_address >= 2 or re.search(r"^(?:您好|喂|李姐|王先生)", text):
        return "ST5_training_telemarketing_callback"
    if len(text) <= 120:
        return "ST1_poster_sms_social"
    return "ST3_product_intro_detail"


def _normalize_labels(raw_value: str, allowed: set[str]) -> list[str]:
    labels: list[str] = []
    for value in raw_value.split("/"):
        label = LABEL_ALIASES.get(value.strip(), value.strip())
        if label in allowed and label not in labels:
            labels.append(label)
    return labels


def _st5_carrier(sample: dict[str, Any]) -> str:
    del sample
    return "内部销售培训、电销与客户回访流程材料"


def revise_test_set(path: Path) -> tuple[dict[str, Any], dict[str, int]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    counts = Counter()
    for sample in payload["samples"]:
        scene = sample["scene"]
        query = str(sample["query"])
        body = re.sub(r"^【材料载体：[^】]+】\s*", "", query)
        desired_prefix: str | None = None
        counter_key: str | None = None
        if scene == "ST4_meeting_material":
            desired_prefix = "【材料载体：产品说明会讲师材料】"
            counter_key = "ST4"
        elif scene == "ST5_training_telemarketing_callback":
            desired_prefix = f"【材料载体：{_st5_carrier(sample)}】"
            counter_key = "ST5"
        if desired_prefix is None:
            continue
        revised_query = f"{desired_prefix}\n{body}"
        if revised_query != query:
            sample["query"] = revised_query
            counts[counter_key] += 1
    payload["schema_version"] = "query_test_set_v1.1"
    generation = payload.setdefault("generation", {})
    previous_revision = generation.get("scene_context_revision", {})
    generation["scene_context_revision"] = {
        "date": date.today().isoformat(),
        "policy": "仅增加材料载体上下文，不增加风险结论或答案提示",
        "modified_samples": {
            **{"ST4": 30, "ST5": 25},
            **previous_revision.get("modified_samples", {}),
            **dict(counts),
        },
    }
    policy = payload.setdefault("annotation_policy", [])
    statement = "ST4/ST5 的材料载体前缀属于可观测输入上下文，不作为风险标签答案。"
    if statement not in policy:
        policy.append(statement)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload, dict(counts)


def build_dev_set(
    train_path: Path,
    test_payload: dict[str, Any],
) -> dict[str, Any]:
    allowed = set(test_payload["risk_label_vocabulary"])
    test_hashes = {
        hashlib.sha256(_normalized_text(row["query"]).encode("utf-8")).hexdigest()
        for row in test_payload["samples"]
    }
    samples: list[dict[str, Any]] = []
    skipped_duplicates = 0
    for line in train_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        query = str(row["query_text"]).strip()
        digest = hashlib.sha256(_normalized_text(query).encode("utf-8")).hexdigest()
        if digest in test_hashes:
            skipped_duplicates += 1
            continue
        labels = _normalize_labels(str(row.get("expected_risk_type", "")), allowed)
        samples.append(
            {
                "query_id": f"DEV-{row['query_id']}",
                "source_query_id": row["query_id"],
                "scene": _infer_scene(query),
                "length_bucket": _bucket(query),
                "query": query,
                "overall_risk": "有风险" if labels else "待人工复核",
                "risk_labels": labels,
                "evidence": [],
                "rationale": f"来源标签规范化为：{'、'.join(labels)}"
                if labels
                else "原标签无法映射，待人工复核",
                "relevant_cases": row.get("relevant_cases", []),
                "annotation_status": "derived_pending_human_review",
            }
        )
    return {
        "schema_version": "query_dev_set_v1",
        "created_at": date.today().isoformat(),
        "language": "zh-CN",
        "purpose": "风险识别、场景路由和案例检索的开发调试；不得作为最终盲测集",
        "source": str(train_path.relative_to(ROOT)).replace("\\", "/"),
        "leakage_control": {
            "normalized_exact_match_excluded_against": "data/raw/query/query_test_set_160.json",
            "skipped_duplicates": skipped_duplicates,
        },
        "annotation_status": "标签由已有训练 Query 规范化映射，使用前需人工抽检",
        "risk_label_vocabulary": test_payload["risk_label_vocabulary"],
        "statistics": _statistics(samples),
        "samples": samples,
    }


def build_long_tail_set(test_payload: dict[str, Any]) -> dict[str, Any]:
    frequencies = test_payload["statistics"]["risk_label_distribution"]
    samples: list[dict[str, Any]] = []
    for label, config in LONG_TAIL_TEMPLATES.items():
        for index, clause in enumerate(config["clauses"], start=1):
            labels = [label, *config["secondary"]]
            samples.append(
                {
                    "query_id": f"LT-{len(samples) + 1:03d}",
                    "target_long_tail_label": label,
                    "source_test_frequency": int(frequencies.get(label, 0)),
                    "scene": config["scene"],
                    "length_bucket": _bucket(clause),
                    "query": clause,
                    "overall_risk": "有风险",
                    "risk_labels": labels,
                    "evidence": [re.sub(r"^【材料载体：[^】]+】", "", clause)],
                    "rationale": f"围绕低频标签“{label}”构造的定向增强样本。",
                    "annotation_status": "synthetic_pending_human_review",
                }
            )
    return {
        "schema_version": "query_long_tail_v1",
        "created_at": date.today().isoformat(),
        "language": "zh-CN",
        "purpose": "补强 160 基准中频次不超过 10 的明确风险标签",
        "selection_policy": (
            "不增强兜底类‘其他’；每个目标标签 4 条；所有样本须人工复核后才能进入训练"
        ),
        "target_labels": list(LONG_TAIL_TEMPLATES),
        "annotation_status": "synthetic_pending_human_review",
        "statistics": _statistics(samples),
        "samples": samples,
    }


def _statistics(samples: list[dict[str, Any]]) -> dict[str, Any]:
    labels = Counter(label for row in samples for label in row.get("risk_labels", []))
    return {
        "total": len(samples),
        "scene_distribution": dict(Counter(row["scene"] for row in samples)),
        "length_distribution": dict(Counter(row["length_bucket"] for row in samples)),
        "risk_label_distribution": dict(labels),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-set", type=Path, default=DEFAULT_TEST_SET)
    parser.add_argument("--train-queries", type=Path, default=DEFAULT_TRAIN_QUERIES)
    parser.add_argument("--dev-output", type=Path, default=DEFAULT_DEV_SET)
    parser.add_argument("--long-tail-output", type=Path, default=DEFAULT_LONG_TAIL_SET)
    args = parser.parse_args()

    test_payload, modified = revise_test_set(args.test_set)
    dev_payload = build_dev_set(args.train_queries, test_payload)
    long_tail_payload = build_long_tail_set(test_payload)
    args.dev_output.parent.mkdir(parents=True, exist_ok=True)
    args.dev_output.write_text(
        json.dumps(dev_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.long_tail_output.write_text(
        json.dumps(long_tail_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "test_context_added": modified,
                "dev_samples": len(dev_payload["samples"]),
                "long_tail_samples": len(long_tail_payload["samples"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
