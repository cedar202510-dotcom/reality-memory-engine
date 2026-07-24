"""Signal 规则引擎：从事实/投影确定性派生信号（§7 触发链的"Signal Rule"一步）。

规则全部是代码判断，不经 LLM：
- LOW_CONSUMABLE：该实体最新有效 CONSUMABLE_LEVEL_OBSERVED 的 level 为 LOW/EMPTY
  或数值 ≤ 阈值。
- STALE_LOCATION：last_seen 投影的位置超过 N 小时未更新。
冷却：同一 cooldown_key 在冷却窗口内已生成过（或仍有未终态信号）则不再生成。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Entity, MemoryEvent, MemorySignal, StateProjection, utcnow


def _is_low_level(level: object, threshold: float) -> bool:
    if isinstance(level, str):
        return level.strip().upper() in {"LOW", "EMPTY", "低", "快用完"}
    if isinstance(level, (int, float)):
        return float(level) <= threshold
    return False


async def _cooldown_active(session: AsyncSession, cooldown_key: str) -> bool:
    settings = get_settings()
    since = utcnow() - timedelta(seconds=settings.signal_cooldown_seconds)
    recent = await session.scalar(
        select(MemorySignal)
        .where(
            MemorySignal.cooldown_key == cooldown_key,
            (MemorySignal.created_at >= since)
            | (MemorySignal.status.in_(("PENDING", "DELIVERED"))),
        )
        .limit(1)
    )
    return recent is not None


async def _emit(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    signal_type: str,
    entity: Entity,
    payload: dict,
    confidence: float,
) -> MemorySignal | None:
    settings = get_settings()
    cooldown_key = f"{signal_type}:{entity.id}"
    if await _cooldown_active(session, cooldown_key):
        return None
    signal = MemorySignal(
        household_id=household_id,
        signal_type=signal_type,
        entity_id=entity.id,
        payload={"entity_name": entity.canonical_name, **payload},
        confidence=confidence,
        cooldown_key=cooldown_key,
        expires_at=utcnow() + timedelta(hours=settings.signal_ttl_hours),
    )
    session.add(signal)
    return signal


async def evaluate_signals_for_entity(
    session: AsyncSession, *, entity_id: uuid.UUID
) -> list[MemorySignal]:
    """投影重算后调用（worker 内、同事务）；返回本次新生成的信号。"""
    settings = get_settings()
    entity = await session.get(Entity, entity_id)
    if entity is None:
        return []
    emitted: list[MemorySignal] = []

    # --- LOW_CONSUMABLE：最新有效耗材水位事件 ---
    level_event = await session.scalar(
        select(MemoryEvent)
        .where(
            MemoryEvent.entity_id == entity_id,
            MemoryEvent.event_type == "CONSUMABLE_LEVEL_OBSERVED",
            MemoryEvent.valid_to.is_(None),
        )
        .order_by(MemoryEvent.event_time_from.desc())
        .limit(1)
    )
    if level_event is not None:
        level = (level_event.payload or {}).get("level", (level_event.payload or {}).get("remaining"))
        if _is_low_level(level, settings.signal_low_consumable_level):
            sig = await _emit(
                session,
                household_id=entity.household_id,
                signal_type="LOW_CONSUMABLE",
                entity=entity,
                payload={"level": level, "observed_at": level_event.event_time_from.isoformat()},
                confidence=float((level_event.confidence or {}).get("aggregate", 0.5)),
            )
            if sig:
                emitted.append(sig)

    # --- STALE_LOCATION：位置长时间未更新 ---
    proj = await session.scalar(
        select(StateProjection).where(
            StateProjection.entity_id == entity_id,
            StateProjection.projection_type == "last_seen",
        )
    )
    state = (proj.state if proj else {}) or {}
    last_seen_raw = state.get("last_seen_time")
    if state.get("location") and last_seen_raw:
        last_seen = datetime.fromisoformat(last_seen_raw)
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        age_hours = (utcnow() - last_seen).total_seconds() / 3600
        if age_hours >= settings.signal_stale_location_hours:
            sig = await _emit(
                session,
                household_id=entity.household_id,
                signal_type="STALE_LOCATION",
                entity=entity,
                payload={
                    "location": state.get("location"),
                    "last_seen_time": last_seen_raw,
                    "age_hours": round(age_hours, 1),
                },
                confidence=float(state.get("confidence", 0.5)),
            )
            if sig:
                emitted.append(sig)

    return emitted
