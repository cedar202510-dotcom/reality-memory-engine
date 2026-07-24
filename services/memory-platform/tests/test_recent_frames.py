"""联调端点 GET /v1/memory/frames/recent：倒序列表、积压计数、Agent 403、CORS 头。"""
from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import EvidenceItem, FrameAsset, OutboxEvent, SourceEnvelope, utcnow

ADMIN = {"Authorization": "Bearer test-admin-token"}


def _client() -> AsyncClient:
    app = create_app(fake_llm=FakeLLMClient(), with_workers=False)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_frames(db_session, n: int = 3) -> list[FrameAsset]:
    env = SourceEnvelope(
        device_id=None,
        occurred_at=utcnow(),
        observed_at=utcnow(),
        idempotency_key=f"recent-frames-{utcnow().timestamp()}",
        trigger="auto",
        modality="image",
    )
    db_session.add(env)
    await db_session.flush()
    frames: list[FrameAsset] = []
    for i in range(n):
        item = EvidenceItem(
            envelope_id=env.id,
            media_kind="image",
            storage_ref=f"/nonexistent/frame-{i}.jpg",  # 路径不存在 → evidence_available=False
            retention_state="ACTIVE",
            ttl_until=utcnow() + timedelta(hours=1),
        )
        db_session.add(item)
        await db_session.flush()
        frame = FrameAsset(
            evidence_item_id=item.id,
            captured_at=utcnow() - timedelta(minutes=n - i),  # i 越大越新
            caption=f"测试帧 {i}",
            scene_tags=["测试"],
        )
        db_session.add(frame)
        frames.append(frame)
    db_session.add(OutboxEvent(topic="frame.process", payload={"evidence_item_id": "x"}))
    await db_session.commit()
    return frames


@pytest.mark.asyncio
async def test_recent_frames_order_and_backlog(db_session):
    await _seed_frames(db_session, n=3)
    async with _client() as client:
        resp = await client.get("/v1/memory/frames/recent", params={"limit": 2})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["frames"]) == 2
    times = [f["captured_at"] for f in data["frames"]]
    assert times == sorted(times, reverse=True)  # 倒序：最新在前
    assert data["frames"][0]["caption"] == "测试帧 2"
    assert data["frames"][0]["evidence_available"] is False
    assert data["frames"][0]["evidence_url"] is None
    assert data["pending_outbox"] >= 1


@pytest.mark.asyncio
async def test_recent_frames_denied_for_agent(db_session):
    async with _client() as client:
        grant = await client.post(
            "/v1/agent/grants",
            headers=ADMIN,
            json={"agent_client_id": "spy-agent", "scopes": ["memory.query.objects"], "purpose": "t"},
        )
        token = grant.json()["token"]
        resp = await client.get(
            "/v1/memory/frames/recent", headers={"Authorization": f"Bearer {token}"}
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_cors_preflight_allows_vite_dev_origin(db_session):
    async with _client() as client:
        resp = await client.options(
            "/v1/memory/frames/recent",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
