"""把某个视频证据的感知产物清干净，以便用新版流水线重跑。

只删「从这段视频派生出来的东西」：关键帧子证据、它们的帧资产/区域/观察、
音频资产及其观察，以及仅由这些观察支撑的候选。源视频本身和它的信封不动。

给开发期重跑用（换了 prompt / 换了抽帧策略想看新结果），不是产品功能。
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import delete, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AtomicObservation,
    AudioAsset,
    EvidenceItem,
    FrameAsset,
    MemoryCandidate,
    MemoryEvent,
)


async def main() -> None:
    async with SessionLocal() as session:
        if len(sys.argv) > 1:
            video_id = uuid.UUID(sys.argv[1])
        else:
            video_id = await session.scalar(
                select(EvidenceItem.id)
                .where(
                    EvidenceItem.media_kind == "video",
                    EvidenceItem.retention_state == "ACTIVE",
                )
                .order_by(EvidenceItem.created_at.desc())
                .limit(1)
            )
        if video_id is None:
            print("没有视频证据")
            return

        children = list(
            (
                await session.scalars(
                    select(EvidenceItem).where(
                        EvidenceItem.parent_evidence_item_id == video_id
                    )
                )
            ).all()
        )
        child_ids = [c.id for c in children]
        frame_ids = (
            list(
                (
                    await session.scalars(
                        select(FrameAsset.id).where(
                            FrameAsset.evidence_item_id.in_(child_ids)
                        )
                    )
                ).all()
            )
            if child_ids
            else []
        )
        audio_ids = list(
            (
                await session.scalars(
                    select(AudioAsset.id).where(AudioAsset.evidence_item_id == video_id)
                )
            ).all()
        )

        obs_ids = list(
            (
                await session.scalars(
                    select(AtomicObservation.id).where(
                        AtomicObservation.frame_asset_id.in_(frame_ids or [uuid.uuid4()])
                        | AtomicObservation.audio_asset_id.in_(audio_ids or [uuid.uuid4()])
                    )
                )
            ).all()
        )
        obs_str = {str(o) for o in obs_ids}

        # 候选与观察是 JSONB 列表关联，没法用 SQL join，取回来在 Python 里筛
        cands = list((await session.scalars(select(MemoryCandidate))).all())
        doomed = [
            c for c in cands if obs_str and set(map(str, c.observation_ids or [])) <= obs_str
            and set(map(str, c.observation_ids or []))
        ]
        cand_str = {str(c.id) for c in doomed}

        events = list((await session.scalars(select(MemoryEvent))).all())
        doomed_events = [
            e
            for e in events
            if cand_str
            and set(map(str, e.source_candidate_ids or [])) <= cand_str
            and set(map(str, e.source_candidate_ids or []))
        ]

        print(
            f"video={video_id}\n  关键帧子证据 {len(child_ids)}\n  帧资产 {len(frame_ids)}"
            f"\n  音频资产 {len(audio_ids)}\n  观察 {len(obs_ids)}"
            f"\n  候选 {len(doomed)}\n  事件 {len(doomed_events)}"
        )

        for e in doomed_events:
            await session.delete(e)
        await session.flush()
        for c in doomed:
            await session.delete(c)
        await session.flush()
        if obs_ids:
            await session.execute(
                delete(AtomicObservation).where(AtomicObservation.id.in_(obs_ids))
            )
        if audio_ids:
            await session.execute(delete(AudioAsset).where(AudioAsset.id.in_(audio_ids)))
        if frame_ids:
            # frame_regions 有 ondelete=CASCADE，跟着帧资产一起走
            await session.execute(delete(FrameAsset).where(FrameAsset.id.in_(frame_ids)))
        for child in children:
            if child.storage_ref:
                Path(child.storage_ref).unlink(missing_ok=True)
            await session.delete(child)
        await session.commit()
        print("已清空，可以重跑 video_perception_smoke.py")


if __name__ == "__main__":
    asyncio.run(main())
