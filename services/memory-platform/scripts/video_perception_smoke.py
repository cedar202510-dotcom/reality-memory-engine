"""视频感知冒烟：对着库里已有的视频证据跑一遍 video.process，用真实 LLM/ASR/CLIP。

用法：
    .venv/bin/python scripts/video_perception_smoke.py [evidence_item_id]

不传 id 就挑最新一条 ACTIVE 的视频证据。跑完打印关键帧 caption、转写、
以及抽出来的偏好/意图观察，用于确认跨模态那一步真的对上了同一个物体。
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import select  # noqa: E402

from app.asr import build_transcriber  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, ensure_extensions  # noqa: E402
from app.llm import build_llm_client  # noqa: E402
from app.models import (  # noqa: E402
    AtomicObservation,
    AudioAsset,
    EvidenceItem,
    FrameAsset,
)
from app.perception.video import process_video_item  # noqa: E402
from app.vision import build_vision_encoder  # noqa: E402


async def main() -> None:
    settings = get_settings()
    await ensure_extensions()
    llm = build_llm_client()
    vision = build_vision_encoder(settings)
    asr = build_transcriber(settings)
    print(
        f"llm={type(llm).__name__} vision={type(vision).__name__} asr={type(asr).__name__}"
    )

    async with SessionLocal() as session:
        if len(sys.argv) > 1:
            item_id = uuid.UUID(sys.argv[1])
        else:
            item_id = await session.scalar(
                select(EvidenceItem.id)
                .where(
                    EvidenceItem.media_kind == "video",
                    EvidenceItem.retention_state == "ACTIVE",
                )
                .order_by(EvidenceItem.created_at.desc())
                .limit(1)
            )
        if item_id is None:
            print("没有可处理的视频证据")
            return
        print(f"processing evidence_item={item_id}")

        stats = await process_video_item(
            session, evidence_item_id=item_id, llm=llm, vision=vision, transcriber=asr
        )
        print(f"stats={stats}")

        children = list(
            (
                await session.scalars(
                    select(EvidenceItem)
                    .where(EvidenceItem.parent_evidence_item_id == item_id)
                    .order_by(EvidenceItem.offset_seconds)
                )
            ).all()
        )
        print(f"\n---- 关键帧 {len(children)} 张 ----")
        for child in children:
            frame = await session.scalar(
                select(FrameAsset).where(FrameAsset.evidence_item_id == child.id)
            )
            tag = "?" if frame is None else ",".join(frame.scene_tags or [])
            cap = "(无)" if frame is None else frame.caption
            vec = "-" if frame is None or frame.visual_embedding is None else "clip"
            print(f"  [{child.offset_seconds:>6.2f}s] {vec} {cap}")
            print(f"            tags: {tag}")

        audio = await session.scalar(
            select(AudioAsset).where(AudioAsset.evidence_item_id == item_id)
        )
        print("\n---- 音轨 ----")
        if audio is None:
            print("  (无 AudioAsset)")
        else:
            print(f"  duration={audio.duration_seconds}s")
            print(f"  transcript: {audio.transcript}")

        print("\n---- 抽出的观察 ----")
        frame_ids = []
        for child in children:
            fa = await session.scalar(
                select(FrameAsset.id).where(FrameAsset.evidence_item_id == child.id)
            )
            if fa:
                frame_ids.append(fa)
        obs = list(
            (
                await session.scalars(
                    select(AtomicObservation).where(
                        (AtomicObservation.audio_asset_id == (audio.id if audio else None))
                        | (AtomicObservation.frame_asset_id.in_(frame_ids or [uuid.uuid4()]))
                    )
                )
            ).all()
        )
        for o in obs:
            src = "audio" if o.audio_asset_id else "frame"
            print(f"  [{src}] {o.predicate:<22} {o.object_text:<12} {o.value}")


if __name__ == "__main__":
    asyncio.run(main())
