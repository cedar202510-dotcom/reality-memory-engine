"""事件写入器：唯一允许写 memory_events 的地方。

与 outbox(projection.recompute) 同事务提交，保证投影最终一致。
事件不可变；纠正/遗忘通过 supersedes / valid_to 关闭旧事件，绝不改历史。
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditRecord, MemoryEvent, OutboxEvent, utcnow


async def append_event(
    session: AsyncSession,
    *,
    entity_id: uuid.UUID | None,
    event_type: str,
    payload: dict,
    event_time_from: datetime,
    observed_at: datetime,
    ingested_at: datetime,
    confidence: dict,
    source_candidate_ids: list[str] | None = None,
    supersedes_event_id: uuid.UUID | None = None,
    stream_id: str | None = None,
) -> MemoryEvent:
    """追加事件；若 supersedes，同事务关闭旧事件的语义有效期。"""
    if supersedes_event_id is not None:
        old = await session.get(MemoryEvent, supersedes_event_id)
        if old is not None and old.valid_to is None:
            old.valid_to = utcnow()

    event = MemoryEvent(
        stream_id=stream_id or (f"entity:{entity_id}" if entity_id else "stream:global"),
        event_type=event_type,
        entity_id=entity_id,
        event_time_from=event_time_from,
        observed_at=observed_at,
        ingested_at=ingested_at,
        payload=payload,
        source_candidate_ids=source_candidate_ids or [],
        confidence=confidence,
        supersedes_event_id=supersedes_event_id,
    )
    session.add(event)
    await session.flush()
    if entity_id is not None:
        session.add(
            OutboxEvent(topic="projection.recompute", payload={"entity_id": str(entity_id)})
        )
    return event


async def latest_valid_event(
    session: AsyncSession, *, entity_id: uuid.UUID
) -> MemoryEvent | None:
    """该实体最新一条有效事件（未被取代、语义有效期未关闭）。"""
    return await session.scalar(
        select(MemoryEvent)
        .where(MemoryEvent.entity_id == entity_id, MemoryEvent.valid_to.is_(None))
        .order_by(MemoryEvent.event_time_from.desc(), MemoryEvent.accepted_at.desc())
        .limit(1)
    )


async def record_audit(
    session: AsyncSession, *, actor: str, action: str, target: str, detail: dict
) -> None:
    session.add(AuditRecord(actor=actor, action=action, target=target, detail=detail))
