"""候选门测试：阈值接受 / 低于阈值 PENDING / 互斥 CONFLICTED。"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.memory.gate import evaluate_candidate
from app.memory.seed import get_default_household_id
from app.models import MemoryCandidate, MemoryEvent, OutboxEvent, utcnow

CONF_HIGH = {"model": 0.9, "identity": 0.9, "spatial": 0.9, "temporal": 0.9, "policy": 1.0, "aggregate": 0.9}
CONF_LOW = {"model": 0.5, "identity": 0.5, "spatial": 0.5, "temporal": 0.5, "policy": 1.0, "aggregate": 0.5}


def _candidate(payload: dict, confidence: dict) -> MemoryCandidate:
    return MemoryCandidate(
        observation_ids=[],
        event_type="OBJECT_OBSERVED_AT",
        payload=payload,
        confidence=confidence,
        status="PENDING",
    )


async def test_high_confidence_candidate_accepted(db_session):
    household_id = await get_default_household_id(db_session)
    c = _candidate({"object_text": "手机", "location": "黑色圆凳"}, CONF_HIGH)
    db_session.add(c)
    await db_session.flush()

    await evaluate_candidate(
        db_session,
        candidate=c,
        household_id=household_id,
        phenomenon_time=utcnow(),
        observed_at=utcnow(),
    )
    await db_session.commit()

    assert c.status == "ACCEPTED"
    assert c.entity_id is not None
    events = (await db_session.scalars(select(MemoryEvent))).all()
    assert len(events) == 1
    assert events[0].payload["location"] == "黑色圆凳"
    # outbox 同事务写入 projection.recompute
    outbox = (await db_session.scalars(select(OutboxEvent))).all()
    assert any(o.topic == "projection.recompute" for o in outbox)


async def test_low_confidence_candidate_stays_pending(db_session):
    household_id = await get_default_household_id(db_session)
    c = _candidate({"object_text": "钥匙", "location": "茶几"}, CONF_LOW)
    db_session.add(c)
    await db_session.flush()

    await evaluate_candidate(
        db_session,
        candidate=c,
        household_id=household_id,
        phenomenon_time=utcnow(),
        observed_at=utcnow(),
    )
    await db_session.commit()

    assert c.status == "PENDING"
    assert (await db_session.scalars(select(MemoryEvent))).all() == []


async def test_conflicting_candidates_marked(db_session):
    household_id = await get_default_household_id(db_session)
    c1 = _candidate({"object_text": "手机", "location": "木桌"}, CONF_LOW)  # 先留 PENDING
    db_session.add(c1)
    await db_session.flush()
    await evaluate_candidate(
        db_session, candidate=c1, household_id=household_id,
        phenomenon_time=utcnow(), observed_at=utcnow(),
    )
    assert c1.status == "PENDING"

    c2 = _candidate({"object_text": "手机", "location": "沙发"}, CONF_HIGH)
    db_session.add(c2)
    await db_session.flush()
    await evaluate_candidate(
        db_session, candidate=c2, household_id=household_id,
        phenomenon_time=utcnow(), observed_at=utcnow(),
    )
    await db_session.commit()

    assert c1.status == "CONFLICTED"
    assert c2.status == "CONFLICTED"
    assert c1.conflict_set_id == c2.conflict_set_id != None  # noqa: E711
    assert isinstance(c1.conflict_set_id, uuid.UUID)
