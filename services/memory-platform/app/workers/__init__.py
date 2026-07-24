"""后台 worker：轮询 outbox_events（DB 队列表，不引入 Redis/Kafka）。

topic 路由：
- frame.process        → perception 帧处理（批内并发：VLM 调用是延迟大头）
- audio.process        → perception 语音处理（ASR → 语义抽取，批内并发）
- projection.recompute → 投影确定性重算（串行：避免同实体并发重算竞态）

失败语义：单条失败记 attempts + 退避重试（payload 内计数），超过
outbox_max_attempts 才标记消费并写审计——真机实测 k3 瞬时超时会静默丢帧，
必须让瞬时失败可自愈、最终失败可追查。

另起 TTL 清理循环（每分钟扫过期证据）。
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from ..asr.base import Transcriber
from ..config import get_settings
from ..db import SessionLocal
from ..llm.base import LLMClient
from ..memory.projections import recompute_projection
from ..models import AuditRecord, OutboxEvent, utcnow
from ..perception import process_evidence_item
from ..perception.audio import process_audio_item
from ..privacy.ttl import sweep_expired_evidence
from ..signals.rules import evaluate_signals_for_entity
from ..vision.base import VisionEncoder

_HEAVY_TOPICS = {"frame.process", "audio.process"}  # 感知任务：VLM/ASR 调用，可并发


async def _dispatch(
    session, row: OutboxEvent, *, llm: LLMClient, vision: VisionEncoder | None, asr: Transcriber | None
) -> None:
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
        entity_id = uuid.UUID(str(row.payload["entity_id"]))
        await recompute_projection(session, entity_id=entity_id)
        # 投影更新后走确定性规则派生信号（§7：Projection → Signal Rule → MemorySignal）
        await evaluate_signals_for_entity(session, entity_id=entity_id)


async def _handle_one(
    row_id: int, *, llm: LLMClient, vision: VisionEncoder | None, asr: Transcriber | None
) -> None:
    """独立 session 处理单条 outbox：成功标记消费；失败记 attempts + 退避，超限审计。"""
    settings = get_settings()
    async with SessionLocal() as session:
        row = await session.get(OutboxEvent, row_id)
        if row is None or row.processed_at is not None:
            return
        try:
            await _dispatch(session, row, llm=llm, vision=vision, asr=asr)
            row.processed_at = utcnow()
            await session.commit()
        except Exception as exc:  # noqa: BLE001 - 单条失败不阻塞队列
            await session.rollback()
            row = await session.get(OutboxEvent, row_id)
            if row is None:
                return
            attempts = int((row.payload or {}).get("attempts", 0)) + 1
            not_before = utcnow() + timedelta(
                seconds=settings.outbox_retry_backoff_seconds * attempts
            )
            row.payload = {
                **(row.payload or {}),
                "attempts": attempts,
                "not_before": not_before.isoformat(),
                "last_error": f"{type(exc).__name__}: {exc}"[:500],
            }
            if attempts >= settings.outbox_max_attempts:
                row.processed_at = utcnow()  # 放弃：标记消费避免毒消息循环
                session.add(
                    AuditRecord(
                        actor="system/outbox-worker",
                        action="process_failed",
                        target=f"outbox:{row.id}",
                        detail={
                            "topic": row.topic,
                            "attempts": attempts,
                            "error": row.payload.get("last_error"),
                            "payload": {
                                k: v for k, v in row.payload.items() if k not in {"last_error"}
                            },
                        },
                    )
                )
            await session.commit()


def _ready(row: OutboxEvent, now: datetime) -> bool:
    raw = (row.payload or {}).get("not_before")
    if not raw:
        return True
    try:
        return datetime.fromisoformat(raw) <= now
    except ValueError:
        return True


async def process_outbox_once(
    llm: LLMClient,
    *,
    vision: VisionEncoder | None = None,
    asr: Transcriber | None = None,
    batch_size: int | None = None,
) -> int:
    """处理一批待消费 outbox 事件，返回处理数。vision/asr 可空（空则对应模态跳过）。

    感知类 topic（帧/音频）批内并发（worker_concurrency），projection 串行。
    """
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
                )
            ).all()
        )
        now = utcnow()
        ready = [(r.id, r.topic) for r in rows if _ready(r, now)]

    if not ready:
        return 0

    heavy_ids = [rid for rid, topic in ready if topic in _HEAVY_TOPICS]
    light_ids = [rid for rid, topic in ready if topic not in _HEAVY_TOPICS]

    if heavy_ids:
        sem = asyncio.Semaphore(max(settings.worker_concurrency, 1))

        async def _guarded(rid: int) -> None:
            async with sem:
                await _handle_one(rid, llm=llm, vision=vision, asr=asr)

        await asyncio.gather(*(_guarded(rid) for rid in heavy_ids))
    for rid in light_ids:
        await _handle_one(rid, llm=llm, vision=vision, asr=asr)
    return len(ready)


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
