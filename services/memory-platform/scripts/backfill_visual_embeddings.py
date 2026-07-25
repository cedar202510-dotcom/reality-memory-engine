"""回填缺失的 CLIP 视觉向量。

哪些帧会缺：上线视觉编码器之前入库的、编码器当时没就绪的、重试次数耗尽被丢的。
这些帧在「东西掉哪里」的视觉检索里等于不存在，而界面上完全看不出异常。

用法：
    cd services/memory-platform
    .venv/bin/python scripts/backfill_visual_embeddings.py            # 入队 + 消费
    .venv/bin/python scripts/backfill_visual_embeddings.py --dry-run  # 只报告缺多少
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
from app.models import EvidenceItem, FrameAsset  # noqa: E402
from app.perception.vectorize import enqueue_missing_visual_embeddings  # noqa: E402
from app.vision import build_vision_encoder  # noqa: E402
from app.workers import process_outbox_once  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计，不入队不消费")
    parser.add_argument("--limit", type=int, default=500, help="单次最多回填多少帧")
    args = parser.parse_args()

    settings = get_settings()
    async with SessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(FrameAsset))
        missing = await session.scalar(
            select(func.count())
            .select_from(FrameAsset)
            .join(EvidenceItem, FrameAsset.evidence_item_id == EvidenceItem.id)
            .where(
                FrameAsset.visual_embedding.is_(None),
                EvidenceItem.retention_state == "ACTIVE",
                EvidenceItem.storage_ref.is_not(None),
            )
        )
        print(f"帧总数 {total}，媒体仍可读但缺视觉向量 {missing}")  # noqa: T201
        if args.dry_run or not missing:
            return 0

        queued = await enqueue_missing_visual_embeddings(session, limit=args.limit)
        print(f"已入队 {len(queued)} 个 {'frame.vectorize'} 任务")  # noqa: T201

    if not queued:
        return 0

    vision = build_vision_encoder(settings)
    llm = build_llm_client(None)
    done = 0
    # process_outbox_once 每轮取 worker_batch_size 条，循环到排空
    while True:
        n = await process_outbox_once(llm, vision=vision)
        if n == 0:
            break
        done += n
        print(f"  已消费 {done} 条…")  # noqa: T201

    async with SessionLocal() as session:
        still = await session.scalar(
            select(func.count())
            .select_from(FrameAsset)
            .join(EvidenceItem, FrameAsset.evidence_item_id == EvidenceItem.id)
            .where(
                FrameAsset.visual_embedding.is_(None),
                EvidenceItem.retention_state == "ACTIVE",
                EvidenceItem.storage_ref.is_not(None),
            )
        )
    print(f"回填完成，仍缺 {still}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
