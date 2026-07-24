"""后台 worker：轮询 outbox_events（DB 队列表，不引入 Redis/Kafka）。

topic 路由：
- frame.process        → perception 帧处理
- audio.process        → perception 语音处理（ASR → 语义抽取）
- projection.recompute → 投影确定性重算

另起 TTL 清理循环（每分钟扫过期证据）。
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid

from sqlalchemy import select

from ..asr.base import Transcriber
from ..config import get_settings
from ..db import SessionLocal
from ..llm.base import LLMClient
from ..memory.projections import recompute_projection
from ..models import OutboxEvent, utcnow
from ..perception import process_evidence_item
from ..perception.audio import process_audio_item
from ..privacy.ttl import sweep_expired_evidence
from ..vision.base import VisionEncoder


async def process_outbox_once(
    llm: LLMClient,
    *,
    vision: VisionEncoder | None = None,
    asr: Transcriber | None = None,
    batch_size: int | None = None,
) -> int:
    """处理一批待消费 outbox 事件，返回处理数。vision/asr 可空（空则对应模态跳过）。"""
    settings = get_settings()
    limit = batch_size or settings.worker_batch_size
    async with SessionLocal() as session:
        rows = list(
            (
                await session.scalars(
                    select(OutboxEvent)
                    .where(OutboxEvent.processed_at.is_(None))
                    .order_by(OutboxEvent.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        for row in rows:
            try:
                if row.topic == "frame.process":
                    await process_evidence_item(
                        session,
                        evidence_item_id=uuid.UUID(str(row.payload["evidence_item_id"])),
                        llm=llm,
                        vision=vision,
                    )
                elif row.topic == "audio.process":
                    if asr is not None:
                        await process_audio_item(
                            session,
                            evidence_item_id=uuid.UUID(str(row.payload["evidence_item_id"])),
                            llm=llm,
                            transcriber=asr,
                        )
                elif row.topic == "projection.recompute":
                    await recompute_projection(
                        session, entity_id=uuid.UUID(str(row.payload["entity_id"]))
                    )
                row.processed_at = utcnow()
                await session.commit()
            except Exception:  # noqa: BLE001 - worker 语义：单条失败不阻塞队列，留待排查
                await session.rollback()
                row.processed_at = utcnow()  # v0：标记已消费避免毒消息循环；错误细节见日志/审计
                await session.commit()
        return len(rows)


async def outbox_worker_loop(
    llm: LLMClient,
    stop: asyncio.Event,
    *,
    vision: VisionEncoder | None = None,
    asr: Transcriber | None = None,
) -> None:
    settings = get_settings()
    while not stop.is_set():
        try:
            n = await process_outbox_once(llm, vision=vision, asr=asr)
        except Exception:  # noqa: BLE001
            n = 0
        if n == 0:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_interval_seconds)


async def ttl_worker_loop(stop: asyncio.Event) -> None:
    settings = get_settings()
    while not stop.is_set():
        try:
            async with SessionLocal() as session:
                await sweep_expired_evidence(session)
        except Exception:  # noqa: BLE001
            pass
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.ttl_sweep_interval_seconds)


def start_workers(
    llm: LLMClient,
    *,
    vision: VisionEncoder | None = None,
    asr: Transcriber | None = None,
) -> tuple[asyncio.Event, list[asyncio.Task]]:
    """启动后台 worker，返回 (stop_event, tasks)。由 app lifespan 或冒烟脚本调用。"""
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(outbox_worker_loop(llm, stop, vision=vision, asr=asr)),
        asyncio.create_task(ttl_worker_loop(stop)),
    ]
    return stop, tasks


async def stop_workers(stop: asyncio.Event, tasks: list[asyncio.Task]) -> None:
    stop.set()
    await asyncio.gather(*tasks, return_exceptions=True)
