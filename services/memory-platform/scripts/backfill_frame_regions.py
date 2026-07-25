"""回填缺失的区域级 CLIP 向量（帧切片）。

为什么必须回填而不是"新帧慢慢覆盖"：裁出来的瓦片背景干净，相似度系统性地略高于
整图。只给新帧切片的话，老帧在同一个 query 下会被新帧稳定压着——界面上完全看不出
异常，用户只会以为"那天没拍到"。

前提：帧的原始媒体还在。EVIDENCE_TTL_MINUTES 默认 15 分钟就把原件删了，
过期帧永远补不回来（这也是为什么切片要放在摄入期做，而不是等查不到再回头扫）。

用法：
    cd services/memory-platform
    .venv/bin/python scripts/backfill_frame_regions.py            # 入队 + 消费
    .venv/bin/python scripts/backfill_frame_regions.py --dry-run  # 只报告缺多少
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
from app.perception.regions import enqueue_missing_regions  # noqa: E402
from app.vision import build_vision_encoder  # noqa: E402
from app.workers import process_outbox_once  # noqa: E402


def _missing_query():
    """媒体仍可读、但一块区域都没有的帧。"""
    has_regions = select(FrameRegion.frame_asset_id).distinct().scalar_subquery()
    return (
        select(func.count())
        .select_from(FrameAsset)
        .join(EvidenceItem, FrameAsset.evidence_item_id == EvidenceItem.id)
        .where(
            EvidenceItem.retention_state == "ACTIVE",
            EvidenceItem.storage_ref.is_not(None),
            FrameAsset.id.not_in(has_regions),
        )
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计，不入队不消费")
    parser.add_argument("--limit", type=int, default=200, help="单次最多回填多少帧")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.vision_tiling_enabled:
        print("VISION_TILING_ENABLED=false，切片整体关闭，无需回填")  # noqa: T201
        return 0

    async with SessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(FrameAsset))
        regions = await session.scalar(select(func.count()).select_from(FrameRegion))
        missing = await session.scalar(_missing_query())
        print(f"帧总数 {total}，已有区域 {regions} 块，媒体仍可读但未切片 {missing} 帧")  # noqa: T201
        if args.dry_run or not missing:
            return 0

        queued = await enqueue_missing_regions(session, limit=args.limit)
        print(f"已入队 {len(queued)} 个 frame.regionize 任务")  # noqa: T201

    if not queued:
        return 0

    vision = build_vision_encoder(settings)
    llm = build_llm_client(None)
    done = 0
    while True:  # process_outbox_once 每轮取 worker_batch_size 条，循环到排空
        n = await process_outbox_once(llm, vision=vision)
        if n == 0:
            break
        done += n
        print(f"  已消费 {done} 条…")  # noqa: T201

    async with SessionLocal() as session:
        still = await session.scalar(_missing_query())
        regions = await session.scalar(select(func.count()).select_from(FrameRegion))
    print(f"回填完成，共 {regions} 块区域，仍未切片 {still} 帧")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
