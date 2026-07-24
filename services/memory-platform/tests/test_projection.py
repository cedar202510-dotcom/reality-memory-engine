"""投影重算与纠正测试：fold 确定性、supersede 链只取最新有效。"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.memory.events import append_event, latest_valid_event
from app.memory.projections import fold_events, recompute_projection
from app.memory.seed import get_default_household_id
from app.models import Entity, MemoryEvent, utcnow

CONF = {"aggregate": 0.9}


async def _entity(db_session) -> Entity:
    household_id = await get_default_household_id(db_session)
    e = Entity(household_id=household_id, canonical_name="手机", created_from="observation")
    db_session.add(e)
    await db_session.flush()
    return e


async def _obs_event(db_session, entity_id, location, minutes_ago, **kw):
    t = utcnow() - timedelta(minutes=minutes_ago)
    return await append_event(
        db_session,
        entity_id=entity_id,
        event_type="OBJECT_OBSERVED_AT",
        payload={"location": location},
        event_time_from=t,
        observed_at=t,
        ingested_at=t,
        confidence=CONF,
        **kw,
    )


async def test_projection_folds_latest_valid_event(db_session):
    entity = await _entity(db_session)
    await _obs_event(db_session, entity.id, "木桌", minutes_ago=10)
    await _obs_event(db_session, entity.id, "黑色圆凳", minutes_ago=2)
    await db_session.commit()

    proj = await recompute_projection(db_session, entity_id=entity.id)
    assert proj.state["location"] == "黑色圆凳"
    assert proj.version == 1

    # 重算是确定性的：再算一次结果不变，版本递增
    proj2 = await recompute_projection(db_session, entity_id=entity.id)
    assert proj2.state["location"] == "黑色圆凳"
    assert proj2.version == 2


async def test_correction_supersedes_and_recomputes(db_session):
    entity = await _entity(db_session)
    old = await _obs_event(db_session, entity.id, "黑色圆凳", minutes_ago=5)
    await db_session.commit()

    latest = await latest_valid_event(db_session, entity_id=entity.id)
    assert latest.id == old.id

    now = utcnow()
    corr = await append_event(
        db_session,
        entity_id=entity.id,
        event_type="USER_CORRECTION",
        payload={"field": "location", "value": "床头柜", "reason": "我明明放床头"},
        event_time_from=now,
        observed_at=now,
        ingested_at=now,
        confidence={"aggregate": 0.99},
        supersedes_event_id=old.id,
    )
    await db_session.commit()

    await db_session.refresh(old)
    assert old.valid_to is not None  # 旧事件被关闭，但行还在（不改历史）
    assert corr.supersedes_event_id == old.id

    proj = await recompute_projection(db_session, entity_id=entity.id)
    assert proj.state["location"] == "床头柜"
    assert proj.state["corrected"] is True

    # fold 是幂等的：多次重算状态一致
    proj2 = await recompute_projection(db_session, entity_id=entity.id)
    assert proj2.state == proj.state


async def test_fold_events_is_pure_and_sorted(db_session):
    entity = await _entity(db_session)
    e1 = await _obs_event(db_session, entity.id, "木桌", minutes_ago=30)
    e2 = await _obs_event(db_session, entity.id, "圆凳", minutes_ago=1)
    # 乱序输入结果一致
    assert fold_events([e2, e1]) == fold_events([e1, e2])
    assert fold_events([e2, e1])["location"] == "圆凳"


async def test_forgetting_invalidates_projection(db_session):
    """所有事件失效后投影清空（供 forget 流程断言）。"""
    entity = await _entity(db_session)
    ev = await _obs_event(db_session, entity.id, "木桌", minutes_ago=3)
    await db_session.commit()
    proj = await recompute_projection(db_session, entity_id=entity.id)
    assert proj.state["location"] == "木桌"

    ev.valid_to = utcnow()
    await db_session.commit()
    proj = await recompute_projection(db_session, entity_id=entity.id)
    assert proj.state == {}

    count = len((await db_session.scalars(select(MemoryEvent))).all())
    assert count == 1  # 事件行仍在，只是失效
