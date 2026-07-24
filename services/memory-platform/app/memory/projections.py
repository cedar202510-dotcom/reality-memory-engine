"""投影引擎：fold 该实体全部有效事件，确定性重算 state_projections。

规则：
- 只取有效事件（valid_to 为空；superseded 链因旧事件被关闭而自然只保留最新，天然 supersede-aware）。
- OBJECT_OBSERVED_AT / OBJECT_MOVED → last_seen 投影：location / last_seen_time。
- PREFERENCE_STATED → preferences 投影：最新一条有效偏好陈述。
- TASK_STATED → tasks 投影：最新一条有效任务意图（status=open，完成/取消类事件 v0 未建模）。
- USER_CORRECTION → 按 payload.field 覆盖投影字段（纠正永远最后生效，因为 event_time/accepted 最新）。
- 遗忘后没有有效事件 → 投影清空（state={}），版本继续递增。
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MemoryEvent, StateProjection, utcnow

LOCATION_EVENTS = ("OBJECT_OBSERVED_AT", "OBJECT_MOVED")


def _sorted(events: list[MemoryEvent]) -> list[MemoryEvent]:
    return sorted(events, key=lambda e: (e.event_time_from, e.accepted_at))


def fold_events(events: list[MemoryEvent]) -> dict:
    """last_seen 投影 fold（纯函数）：按 (event_time_from, accepted_at) 升序 fold。"""
    state: dict = {}
    for ev in _sorted(events):
        if ev.event_type in LOCATION_EVENTS:
            loc = ev.payload.get("location")
            if loc:
                state["location"] = loc
                state["last_seen_time"] = ev.event_time_from.isoformat()
                state["confidence"] = (ev.confidence or {}).get("aggregate", 0.5)
        elif ev.event_type == "USER_CORRECTION":
            field = ev.payload.get("field")
            if field:
                state[field] = ev.payload.get("value")
                if field == "location":
                    state["last_seen_time"] = ev.event_time_from.isoformat()
                    state["confidence"] = (ev.confidence or {}).get("aggregate", 0.99)
                state["corrected"] = True
    return state


def fold_preference_events(events: list[MemoryEvent]) -> dict:
    """preferences 投影 fold（纯函数）：最新一条有效 PREFERENCE_STATED 生效。"""
    state: dict = {}
    for ev in _sorted(events):
        if ev.event_type == "PREFERENCE_STATED":
            payload = ev.payload or {}
            state["preference"] = payload.get("preference") or payload.get("value") or payload
            state["stated_time"] = ev.event_time_from.isoformat()
            state["confidence"] = (ev.confidence or {}).get("aggregate", 0.5)
    return state


def fold_task_events(events: list[MemoryEvent]) -> dict:
    """tasks 投影 fold（纯函数）：最新一条有效 TASK_STATED 生效（v0 一律视为 open）。"""
    state: dict = {}
    for ev in _sorted(events):
        if ev.event_type == "TASK_STATED":
            payload = ev.payload or {}
            state["task"] = payload.get("task") or payload.get("intent") or payload
            state["status"] = "open"
            state["stated_time"] = ev.event_time_from.isoformat()
            state["confidence"] = (ev.confidence or {}).get("aggregate", 0.5)
    return state


async def _upsert_projection(
    session: AsyncSession, *, entity_id: uuid.UUID, projection_type: str, state: dict
) -> StateProjection:
    """按 (entity_id, projection_type) upsert 投影，版本单调递增。"""
    proj = await session.scalar(
        select(StateProjection).where(
            StateProjection.entity_id == entity_id,
            StateProjection.projection_type == projection_type,
        )
    )
    if proj is None:
        proj = StateProjection(
            entity_id=entity_id, projection_type=projection_type, as_of=utcnow()
        )
        session.add(proj)
    proj.version = (proj.version or 0) + 1
    proj.as_of = utcnow()
    proj.state = state
    proj.conflicts = []
    return proj


async def recompute_projection(session: AsyncSession, *, entity_id: uuid.UUID) -> StateProjection:
    """重算单个实体的全部投影（last_seen/preferences/tasks）并 upsert；返回 last_seen 投影。"""
    events = list(
        (
            await session.scalars(
                select(MemoryEvent).where(
                    MemoryEvent.entity_id == entity_id,
                    MemoryEvent.valid_to.is_(None),
                    MemoryEvent.branch_id == "main",
                )
            )
        ).all()
    )
    last_seen = await _upsert_projection(
        session, entity_id=entity_id, projection_type="last_seen", state=fold_events(events)
    )
    await _upsert_projection(
        session,
        entity_id=entity_id,
        projection_type="preferences",
        state=fold_preference_events(events),
    )
    await _upsert_projection(
        session, entity_id=entity_id, projection_type="tasks", state=fold_task_events(events)
    )
    await session.commit()
    return last_seen
