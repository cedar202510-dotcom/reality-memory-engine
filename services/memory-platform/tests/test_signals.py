"""Signal 测试：规则派生（确定性）、冷却去重、订阅过滤、每日上限、过期不投递、ack。"""
from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.memory.events import append_event
from app.memory.projections import recompute_projection
from app.memory.seed import get_default_household_id
from app.models import Entity, MemorySignal, utcnow
from app.signals.rules import evaluate_signals_for_entity

ADMIN = {"Authorization": "Bearer test-admin-token"}


def _client() -> AsyncClient:
    app = create_app(fake_llm=FakeLLMClient(), with_workers=False)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _entity(db_session, name: str) -> Entity:
    household_id = await get_default_household_id(db_session)
    e = Entity(household_id=household_id, canonical_name=name, created_from="observation")
    db_session.add(e)
    await db_session.flush()
    return e


async def _event(db_session, entity_id, event_type, payload, hours_ago=0, conf=0.9):
    t = utcnow() - timedelta(hours=hours_ago)
    return await append_event(
        db_session,
        entity_id=entity_id,
        event_type=event_type,
        payload=payload,
        event_time_from=t,
        observed_at=t,
        ingested_at=t,
        confidence={"aggregate": conf},
    )


async def test_low_consumable_rule_and_cooldown(db_session):
    entity = await _entity(db_session, "洗衣液")
    await _event(db_session, entity.id, "CONSUMABLE_LEVEL_OBSERVED", {"level": "LOW"})
    await db_session.commit()
    await recompute_projection(db_session, entity_id=entity.id)

    emitted = await evaluate_signals_for_entity(db_session, entity_id=entity.id)
    await db_session.commit()
    assert len(emitted) == 1
    assert emitted[0].signal_type == "LOW_CONSUMABLE"
    assert emitted[0].payload["entity_name"] == "洗衣液"

    # 冷却窗口内重复评估不再生成
    again = await evaluate_signals_for_entity(db_session, entity_id=entity.id)
    await db_session.commit()
    assert again == []
    n = len((await db_session.scalars(select(MemorySignal))).all())
    assert n == 1


async def test_stale_location_rule(db_session):
    entity = await _entity(db_session, "钥匙")
    await _event(db_session, entity.id, "OBJECT_OBSERVED_AT", {"location": "玄关"}, hours_ago=100)
    await db_session.commit()
    await recompute_projection(db_session, entity_id=entity.id)

    emitted = await evaluate_signals_for_entity(db_session, entity_id=entity.id)
    await db_session.commit()
    assert [s.signal_type for s in emitted] == ["STALE_LOCATION"]
    assert emitted[0].payload["age_hours"] >= 100


async def test_signal_delivery_flow(db_session):
    """订阅过滤 + 投递 + ack + 无订阅 404 + 撤销 grant 后 401。"""
    entity = await _entity(db_session, "洗衣液")
    await _event(db_session, entity.id, "CONSUMABLE_LEVEL_OBSERVED", {"level": 0.1})
    await db_session.commit()
    await recompute_projection(db_session, entity_id=entity.id)
    await evaluate_signals_for_entity(db_session, entity_id=entity.id)
    await db_session.commit()

    async with _client() as client:
        resp = await client.post(
            "/v1/agent/grants",
            headers=ADMIN,
            json={
                "agent_client_id": "signal-agent",
                "scopes": ["memory.signal.subscribe"],
            },
        )
        token = resp.json()["token"]
        grant_id = resp.json()["grant"]["grant_id"]
        headers = {"Authorization": f"Bearer {token}"}

        # 无订阅先拉取 → 404
        resp = await client.get("/v1/signals", headers=headers)
        assert resp.status_code == 404

        resp = await client.post(
            "/v1/signal-subscriptions",
            headers=headers,
            json={"signal_types": ["LOW_CONSUMABLE"], "min_confidence": 0.5, "daily_cap": 5},
        )
        assert resp.status_code == 200, resp.text

        resp = await client.get("/v1/signals", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["signals"]) == 1
        sig = body["signals"][0]
        assert sig["signal_type"] == "LOW_CONSUMABLE"
        assert sig["status"] == "DELIVERED"

        # 再拉：已 DELIVERED 不重复投递
        resp = await client.get("/v1/signals", headers=headers)
        assert resp.json()["signals"] == []

        # ack
        resp = await client.post(f"/v1/signals/{sig['id']}/ack", headers=headers)
        assert resp.json()["status"] == "ACKED"

        # 撤销 grant → 停投（401）
        await client.delete(f"/v1/agent/grants/{grant_id}", headers=ADMIN)
        resp = await client.get("/v1/signals", headers=headers)
        assert resp.status_code == 401


async def test_expired_signal_not_delivered(db_session):
    entity = await _entity(db_session, "牛奶")
    household_id = await get_default_household_id(db_session)
    sig = MemorySignal(
        household_id=household_id,
        signal_type="LOW_CONSUMABLE",
        entity_id=entity.id,
        payload={"entity_name": "牛奶"},
        confidence=0.9,
        cooldown_key=f"LOW_CONSUMABLE:{entity.id}",
        expires_at=utcnow() - timedelta(minutes=1),  # 已过期
    )
    db_session.add(sig)
    await db_session.commit()

    async with _client() as client:
        resp = await client.post(
            "/v1/agent/grants",
            headers=ADMIN,
            json={"agent_client_id": "signal-agent-2", "scopes": ["memory.signal.subscribe"]},
        )
        headers = {"Authorization": f"Bearer {resp.json()['token']}"}
        await client.post(
            "/v1/signal-subscriptions",
            headers=headers,
            json={"signal_types": ["LOW_CONSUMABLE"]},
        )
        resp = await client.get("/v1/signals", headers=headers)
        assert resp.json()["signals"] == []  # 过期不投递（§13）

    refreshed = await db_session.get(MemorySignal, sig.id)
    await db_session.refresh(refreshed)
    assert refreshed.status == "EXPIRED"


async def test_min_confidence_suppression(db_session):
    entity = await _entity(db_session, "纸巾")
    await _event(db_session, entity.id, "CONSUMABLE_LEVEL_OBSERVED", {"level": "LOW"}, conf=0.3)
    await db_session.commit()
    await recompute_projection(db_session, entity_id=entity.id)
    await evaluate_signals_for_entity(db_session, entity_id=entity.id)
    await db_session.commit()

    async with _client() as client:
        resp = await client.post(
            "/v1/agent/grants",
            headers=ADMIN,
            json={"agent_client_id": "signal-agent-3", "scopes": ["memory.signal.subscribe"]},
        )
        headers = {"Authorization": f"Bearer {resp.json()['token']}"}
        await client.post(
            "/v1/signal-subscriptions",
            headers=headers,
            json={"signal_types": ["LOW_CONSUMABLE"], "min_confidence": 0.8},
        )
        resp = await client.get("/v1/signals", headers=headers)
        body = resp.json()
        assert body["signals"] == []
        assert body["suppressed"] == 1  # 抑制可观测，不是丢失
