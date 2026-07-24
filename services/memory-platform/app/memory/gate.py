"""候选门：唯一能把 MemoryCandidate 升级为 MemoryEvent 的地方。

v0 自动接受条件（简化版）：
  aggregate 置信度 ≥ 阈值(默认 0.85，可配) 且 无未决冲突 → ACCEPTED
低于阈值 → 保持 PENDING（保留，查询通道 2 可用）
互斥（同一物体在同一时间段有两个不同位置的待定候选）→ CONFLICTED + conflict_set_id
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import MemoryCandidate, utcnow
from .events import append_event, record_audit
from .normalize import locations_compatible, names_alias_match
from .resolver import resolve_entity

PREDICATE_TO_EVENT_TYPE = {
    "OBSERVED_AT": "OBJECT_OBSERVED_AT",
    "PLACED": "OBJECT_OBSERVED_AT",
    "OPENED": "OBJECT_OBSERVED_AT",
    "CLOSED": "OBJECT_OBSERVED_AT",
    "USED": "OBJECT_OBSERVED_AT",
    "MOVED": "OBJECT_MOVED",
    "TAKEN": "OBJECT_MOVED",
    "PUT_IN": "OBJECT_MOVED",
    "TAKEN_OUT": "OBJECT_MOVED",
    "CONSUMED": "CONSUMABLE_LEVEL_OBSERVED",
    "PREFERENCE_EXPRESSED": "PREFERENCE_STATED",
    "INTENT_CREATED": "TASK_STATED",
}


async def _find_conflict(
    session: AsyncSession, candidate: MemoryCandidate
) -> list[MemoryCandidate]:
    """同一物体、位置不兼容的未决候选视为互斥。

    位置判定用 locations_compatible 而非字符串相等：VLM 对同一地点的叫法
    帧间不稳定（「白桌」vs「白色办公桌」），裸字符串不等会把同一张桌子
    误判为两个互斥位置，导致高置信候选被 CONFLICTED、物体永远沉淀不成实体。
    """
    obj = candidate.payload.get("object_text")
    loc = candidate.payload.get("location")
    if not obj or not loc:
        return []
    pendings = list(
        (
            await session.scalars(
                select(MemoryCandidate).where(
                    MemoryCandidate.status == "PENDING",
                    MemoryCandidate.id != candidate.id,
                )
            )
        ).all()
    )
    return [
        c
        for c in pendings
        if names_alias_match(c.payload.get("object_text") or "", obj)
        and c.payload.get("location")
        and not locations_compatible(c.payload.get("location"), loc)
    ]


async def evaluate_candidate(
    session: AsyncSession,
    *,
    candidate: MemoryCandidate,
    household_id: uuid.UUID,
    phenomenon_time: datetime,
    observed_at: datetime,
    ingested_at: datetime | None = None,
    object_embedding: list[float] | None = None,
    frame_visual_embedding: list[float] | None = None,
) -> MemoryCandidate:
    """评估单个候选；接受时同事务写事件 + outbox。调用方负责最终 commit。

    frame_visual_embedding：候选来源帧的 CLIP 向量，供实体解析做物体级合并。
    """
    settings = get_settings()
    aggregate = float((candidate.confidence or {}).get("aggregate", 0.0))

    conflicts = await _find_conflict(session, candidate)
    if conflicts:
        conflict_set_id = uuid.uuid4()
        candidate.status = "CONFLICTED"
        candidate.conflict_set_id = conflict_set_id
        candidate.resolved_at = utcnow()
        for c in conflicts:
            c.status = "CONFLICTED"
            c.conflict_set_id = conflict_set_id
            c.resolved_at = utcnow()
        return candidate

    if aggregate < settings.candidate_accept_threshold:
        return candidate  # 保持 PENDING

    candidate.status = "ACCEPTED"
    candidate.resolved_at = utcnow()

    object_text = candidate.payload.get("object_text", "未知物体")
    entity, _ = await resolve_entity(
        session,
        household_id=household_id,
        name=object_text,
        embedding=object_embedding,
        frame_visual_embedding=frame_visual_embedding,
        created_from="query" if candidate.source == "query" else "observation",
    )
    candidate.entity_id = entity.id

    event = await append_event(
        session,
        entity_id=entity.id,
        event_type=candidate.event_type,
        payload={k: v for k, v in candidate.payload.items() if k != "object_text"},
        event_time_from=phenomenon_time,
        observed_at=observed_at,
        ingested_at=ingested_at or utcnow(),
        confidence=candidate.confidence,
        source_candidate_ids=[str(candidate.id)],
    )
    await record_audit(
        session,
        actor="system/candidate-gate",
        action="event_accepted",
        target=f"event:{event.id}",
        detail={
            "candidate_id": str(candidate.id),
            "entity": entity.canonical_name,
            "event_type": candidate.event_type,
            "aggregate": aggregate,
        },
    )
    return candidate
