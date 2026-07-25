"""回填缺失的 OCR 文本。

前提：帧的原始媒体还在。EVIDENCE_TTL_MINUTES 默认 15 分钟就把原件删了，
过期帧永远补不回来（这也是为什么 OCR 要放在摄入期，而不是等查不到再回头扫）。

用法：
    cd services/memory-platform
    .venv/bin/python scripts/backfill_frame_ocr.py            # 入队 + 消费
    .venv/bin/python scripts/backfill_frame_ocr.py --dry-run  # 只报告缺多少
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import func, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.llm import build_llm_client  # noqa: E402
from app.models import EvidenceItem, FrameAsset, FrameRegion  # noqa: E402
from app.perception.ocr import enqueue_missing_ocr  # noqa: E402
from app.workers import process_outbox_once  # noqa: E402


def _missing_query():
    """媒体仍可读、但没跑过 OCR 的帧。"""
    done = select(FrameRegion.frame_asset_id).where(FrameRegion.source == "ocr").scalar_subquery()
    return (
        select(func.count())
        .select_from(FrameAsset)
        .join(EvidenceItem, FrameAsset.evidence_item_id == EvidenceItem.id)
        .where(
            EvidenceItem.retention_state == "ACTIVE",
            EvidenceItem.storage_ref.is_not(None),
            FrameAsset.id.not_in(done),
        )
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计，不入队不消费")
    parser.add_argument("--limit", type=int, default=200, help="单次最多回填多少帧")
    args = parser.parse_args()

    settings = get_settings()
    if (settings.ocr_provider or "none").lower() == "none":
        print("OCR_PROVIDER=none，OCR 通道未启用，无需回填")  # noqa: T201
        return 0
    if not settings.ocr_redact_pii:
        print("⚠️ OCR_REDACT_PII=false：识别文本将明文入库，包括证件号/卡号")  # noqa: T201

    async with SessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(FrameAsset))
        done = await session.scalar(
            select(func.count()).select_from(FrameRegion).where(FrameRegion.source == "ocr")
        )
        missing = await session.scalar(_missing_query())
        print(f"帧总数 {total}，已有 OCR {done} 帧，媒体仍可读但未识别 {missing} 帧")  # noqa: T201
        if args.dry_run or not missing:
            return 0

        queued = await enqueue_missing_ocr(session, limit=args.limit)
        print(f"已入队 {len(queued)} 个 frame.ocr 任务")  # noqa: T201

    if not queued:
        return 0

    llm = build_llm_client(None)
    consumed = 0
    while True:  # process_outbox_once 每轮取 worker_batch_size 条，循环到排空
        n = await process_outbox_once(llm)
        if n == 0:
            break
        consumed += n
        print(f"  已消费 {consumed} 条…")  # noqa: T201

    async with SessionLocal() as session:
        still = await session.scalar(_missing_query())
    print(f"回填完成，仍未识别 {still} 帧")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
