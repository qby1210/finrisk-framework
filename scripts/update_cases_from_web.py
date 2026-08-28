"""金监总局处罚案例定期采集 + 复用统一入库链的增量更新。

每天一条命令：采集 NFRA 三栏目（4113 总局/4114 省局/4115 分局）→ 汇总表拆单案
→ 保险筛选（排除银行当事人）→ 复用 CaseManagementService.ingest_file 逐案入统一
案例库（与 Web 上传完全同一条链：同一 builder、同一三表追加、同一回滚）。

去重三级：state.json（已见 docId）→ ingested.jsonl 台账（正文 sha1）→
case_id 哈希（与入库链同一算法，重复时仓储层抛 DuplicateCaseError 兜底）。
可重复运行；无新案时零模型调用。

用法：
  uv run python scripts/update_cases_from_web.py                 # 日常更新
  uv run python scripts/update_cases_from_web.py --dry-run       # 只采集汇报，不调模型（纯标准库）
  uv run python scripts/update_cases_from_web.py --limit 5       # 本次最多入 5 案（控模型额度）
  uv run python scripts/update_cases_from_web.py --crawl-mode full --max-pages 10  # 补历史页
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from offline.penalty_crawler import nfra  # noqa: E402
from offline.penalty_crawler.filter import (  # noqa: E402
    collect_pending,
    load_existing_case_ids,
    load_ingested_sha1,
)
from settings import AppSettings  # noqa: E402  (纯标准库模块，dry-run 也可用)

DEFAULT_CRAWL_DIR = PROJECT_ROOT / "data" / "raw" / "cases" / "crawl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NFRA 处罚案例采集 + 统一入库链增量更新")
    parser.add_argument("--columns", type=int, nargs="*", default=[4113, 4114, 4115],
                        help="NFRA 栏目（4113/4114/4115），默认三个全采")
    parser.add_argument("--crawl-mode", choices=["incremental", "full"], default="incremental",
                        help="incremental 撞整页已见即停；补历史页用 full")
    parser.add_argument("--max-pages", type=int, default=0, help="每栏目最多翻页数（0=不限）")
    parser.add_argument("--delay", type=float, default=1.5, help="请求间隔秒数，不得低于 1.5")
    parser.add_argument("--crawl-dir", type=Path, default=DEFAULT_CRAWL_DIR,
                        help="采集暂存区（state.json/index.jsonl/拆分 txt）")
    parser.add_argument("--include-all", action="store_true",
                        help="不做保险相关筛选（默认只入含「保险」且当事人非银行的文书）")
    parser.add_argument("--limit", type=int, default=0, help="本次最多入库几案（0=不限）")
    parser.add_argument("--dry-run", action="store_true", help="只采集 + 汇报，不入库不调模型")
    return parser.parse_args()


async def ingest_pending(
    args: argparse.Namespace,
    pending: list[dict[str, object]],
) -> list[dict[str, object]]:
    """逐案复用统一入库链；第三方依赖延迟到此函数内导入，--dry-run 保持纯标准库。"""
    from dotenv import load_dotenv

    from application.case_service import CaseManagementService
    from llm import create_llm_client_from_env
    from risk.detection import RuleRiskDetector
    from storage.case_repository import CaseRepository, DuplicateCaseError

    load_dotenv(PROJECT_ROOT / ".env")
    settings = AppSettings.from_env()
    service = CaseManagementService(
        settings=settings,
        repository=CaseRepository(settings),
        rule_detector=RuleRiskDetector(settings.risk_keyword_path),
        llm_client=create_llm_client_from_env(),
    )

    ledger_path = args.crawl_dir / "ingested.jsonl"
    results: list[dict[str, object]] = []
    for item in pending:
        txt = Path(str(item["txt_path"]))
        try:
            outcome = await service.ingest_file(txt, original_filename=txt.name)
        except DuplicateCaseError:
            print(f"[跳过] {txt.name} 案例库已存在同文案件")
            results.append({"txt": txt.name, "status": "duplicate"})
            continue
        case_id = outcome.case.case_id
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "sha1": item["sha1"], "case_id": case_id,
                "txt_path": str(txt), "title": item["title"],
                "source_url": item["source_url"],
            }, ensure_ascii=False) + "\n")
        results.append({
            "txt": txt.name, "status": "ingested", "case_id": case_id,
            "llm_used": outcome.llm_used, "warnings": outcome.warnings,
        })
        print(f"[入库] {case_id} <- {txt.name} "
              f"(llm={outcome.llm_used}, 警告 {len(outcome.warnings)})")
    return results


def main() -> None:
    args = parse_args()
    if args.delay < 1.5:
        raise SystemExit("采集 delay 不得低于 1.5 秒（抓取礼仪纪律）")
    crawl_dir = args.crawl_dir if args.crawl_dir.is_absolute() else PROJECT_ROOT / args.crawl_dir
    crawl_dir.mkdir(parents=True, exist_ok=True)

    # ── 第 1 步：采集 ─────────────────────────────────────────────
    crawl_stats = nfra.crawl_all(
        crawl_dir,
        full=args.crawl_mode == "full",
        max_pages=args.max_pages,
        delay=args.delay,
        columns=args.columns,
    )

    # ── 第 2 步：筛选待入案件 ─────────────────────────────────────
    settings = AppSettings.from_env()
    existing_case_ids = load_existing_case_ids(settings.cases_path)
    ingested_sha1 = load_ingested_sha1(crawl_dir)
    pending, filter_stats = collect_pending(
        crawl_dir,
        ingested_sha1=ingested_sha1,
        existing_case_ids=existing_case_ids,
        include_all=args.include_all,
    )
    if args.limit:
        pending = pending[: args.limit]

    summary: dict[str, object] = {
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "crawl": crawl_stats,
        "filter": filter_stats,
        "pending": len(pending),
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    # ── 第 3 步：逐案走统一入库链 ─────────────────────────────────
    results = asyncio.run(ingest_pending(args, pending))
    summary["ingest"] = {
        "ingested": sum(1 for r in results if r["status"] == "ingested"),
        "duplicate": sum(1 for r in results if r["status"] == "duplicate"),
        "llm_used": sum(1 for r in results if r.get("llm_used")),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    log_path = crawl_dir / "update_log.jsonl"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
