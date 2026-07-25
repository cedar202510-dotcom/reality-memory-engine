"""回填物件缩略图（检测框裁切）：给全览页每个节点补一张实拍图。

前提：帧的原始媒体还在。EVIDENCE_TTL_MINUTES 默认 15 分钟就把原件删了，
过期帧永远补不回来——想给存量物品补图，正路是重新摄入一遍原始照片
（scripts/ingest_phone_media.py），让它们在 TTL 之内重走一次感知。

只处理「有观察、媒体还在、还没检测过」的帧：没有观察就没有 prompt 可用，
拿全库物品名去撒网既贵又会误检。

用法：
    cd services/memory-platform
    .venv/bin/python scripts/backfill_object_crops.py            # 入队 + 消费
    .venv/bin/python scripts/backfill_object_crops.py --dry-run  # 只报告缺多少
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
from app.models import AtomicObservation, EvidenceItem, FrameAsset, FrameRegion  # noqa: E402
from app.perception.detect import detect_frame_objects  # noqa: E402
from app.vision import build_vision_encoder  # noqa: E402


def _candidate_frames_query():
    """有观察、媒体仍可读、还没有任何检测裁切的帧。"""
    detected = (
        select(FrameRegion.frame_asset_id)
        .where(FrameRegion.crop_ref.is_not(None))
        .distinct()
        .scalar_subquery()
    )
    observed = (
        select(AtomicObservation.frame_asset_id)
        .where(AtomicObservation.object_text.is_not(None))
        .distinct()
        .scalar_subquery()
    )
    return (
        select(FrameAsset.id, EvidenceItem.storage_ref)
        .join(EvidenceItem, FrameAsset.evidence_item_id == EvidenceItem.id)
        .where(
            EvidenceItem.retention_state == "ACTIVE",
            EvidenceItem.storage_ref.is_not(None),
            FrameAsset.id.in_(observed),
            FrameAsset.id.not_in(detected),
        )
        .order_by(FrameAsset.created_at.desc())
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="只统计，不入队不消费")
    parser.add_argument("--limit", type=int, default=200, help="单次最多回填多少帧")
    args = parser.parse_args()

    settings = get_settings()
    if settings.detector_provider.lower() == "none":
        print("DETECTOR_PROVIDER=none，物件检测未启用，无需回填")  # noqa: T201
        return 0

    async with SessionLocal() as session:
        crops = await session.scalar(
            select(func.count()).select_from(FrameRegion).where(FrameRegion.crop_ref.is_not(None))
        )
        rows = list((await session.execute(_candidate_frames_query().limit(args.limit))).all())
        # 路径存在性只能逐个查：retention_state 还是 ACTIVE 但文件已被 TTL 删掉的窗口是有的
        rows = [(fid, ref) for fid, ref in rows if Path(ref).exists()]
        print(f"已有裁切图 {crops} 张，媒体仍可读但未检测 {len(rows)} 帧")  # noqa: T201
        if args.dry_run or not rows:
            return 0

    # 直接在本进程做，不走 outbox。走 outbox 的话，正在跑的服务端 worker 会先把任务抢走，
    # 而那个进程的 settings 是启动时缓存的——刚打开 DETECTOR_PROVIDER 的话它拿到的仍是
    # NullObjectDetector，检不出任何东西还把任务标记成功消费掉，外部完全看不出来。
    vision = build_vision_encoder(settings)
    llm = build_llm_client(None)
    written = 0
    for index, (frame_id, _) in enumerate(rows, 1):
        async with SessionLocal() as session:
            n = await detect_frame_objects(session, frame_asset_id=frame_id, llm=llm, vision=vision)
        written += n
        print(f"  [{index}/{len(rows)}] {frame_id} → {n} 张")  # noqa: T201

    async with SessionLocal() as session:
        crops = await session.scalar(
            select(func.count()).select_from(FrameRegion).where(FrameRegion.crop_ref.is_not(None))
        )
    print(f"回填完成，共 {crops} 张裁切图")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
