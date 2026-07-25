"""CLIP 视觉向量化：可独立重试的 outbox 任务（topic=frame.vectorize）。

为什么要从帧处理里拆出来单独重试：
visual_embedding 是「东西掉哪里」视觉检索的唯一入口——没有它，这帧在视觉路上
就等于不存在。而它原本只在 process_evidence_item 里编码一次，失败就是 None：
CLIP 首次加载权重要十几秒、sidecar 可能没起、vision_provider 当时可能还是 none。
这些都是暂时的，可这帧却永久失明了，而且没有任何地方会报错——caption 有、
帧也在列表里，只是视觉检索永远搜不到它。

拆成独立 topic 后：暂时性失败走 outbox 的退避重试，历史遗留的空向量走 backfill。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import EvidenceItem, FrameAsset, OutboxEvent
from ..vision.base import VisionEncoder

TOPIC = "frame.vectorize"


class VectorizeRetryable(RuntimeError):
    """暂时性失败：交给 outbox 退避重试（编码器没就绪 / 网络抖动）。"""


def enqueue_vectorize(session: AsyncSession, frame_asset_id: uuid.UUID) -> None:
    session.add(OutboxEvent(topic=TOPIC, payload={"frame_asset_id": str(frame_asset_id)}))


async def vectorize_frame_asset(
    session: AsyncSession,
    *,
    frame_asset_id: uuid.UUID,
    vision: VisionEncoder | None,
) -> bool:
    """给单帧补 CLIP 视觉向量。返回是否写入了新向量。

    幂等：已有向量直接返回。媒体已删/不可读属于永久失败（重试再多次也没有输入），
    直接消费掉不再重试；编码器返回 None 属于暂时失败，抛 VectorizeRetryable 走退避。
    """
    frame = await session.get(FrameAsset, frame_asset_id)
    if frame is None or frame.visual_embedding is not None:
        return False
    if vision is None:
        return False  # 视觉路整体关闭（vision_provider=none），不是错误

    item = await session.get(EvidenceItem, frame.evidence_item_id)
    if item is None or item.retention_state != "ACTIVE" or not item.storage_ref:
        return False
    path = Path(item.storage_ref)
    if not path.exists():
        return False  # TTL 已物理删除：永久没有输入了，别再重试

    vectors = await vision.embed_images([path.read_bytes()])
    if not vectors or not vectors[0]:
        # 编码器按契约不抛异常、失败返回 None——所以这里必须自己把它变成可重试信号，
        # 否则任务会被当成「成功但没结果」消费掉，这帧就再也没人管了。
        raise VectorizeRetryable(f"视觉编码器未返回向量：frame={frame_asset_id}")

    frame.visual_embedding = vectors[0]
    await session.commit()
    return True


async def enqueue_missing_visual_embeddings(
    session: AsyncSession, *, limit: int = 500
) -> list[uuid.UUID]:
    """把「媒体还在但没有视觉向量」的帧补进 outbox，返回本次入队的帧 id。

    用于回填：上线视觉编码器之前入库的帧、以及重试次数耗尽被丢弃的帧。
    """
    pending = set(
        (
            await session.scalars(
                select(OutboxEvent.payload["frame_asset_id"].astext).where(
                    OutboxEvent.topic == TOPIC, OutboxEvent.processed_at.is_(None)
                )
            )
        ).all()
    )

    rows = (
        await session.execute(
            select(FrameAsset.id, EvidenceItem.storage_ref)
            .join(EvidenceItem, FrameAsset.evidence_item_id == EvidenceItem.id)
            .where(
                FrameAsset.visual_embedding.is_(None),
                EvidenceItem.retention_state == "ACTIVE",
                EvidenceItem.storage_ref.is_not(None),
            )
            .order_by(FrameAsset.created_at.desc())
            .limit(limit)
        )
    ).all()

    queued: list[uuid.UUID] = []
    for frame_id, storage_ref in rows:
        if str(frame_id) in pending or not Path(storage_ref).exists():
            continue
        enqueue_vectorize(session, frame_id)
        queued.append(frame_id)
    if queued:
        await session.commit()
    return queued
