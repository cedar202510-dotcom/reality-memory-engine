"""遗忘（forget-recent）与 TTL 清理测试。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import get_settings
from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import (
    AuditRecord,
    DeletionTombstone,
    EvidenceItem,
    FrameAsset,
    MemoryEvent,
    StateProjection,
)
from app.privacy.ttl import sweep_expired_evidence
from app.workers import process_outbox_once

HIGH = {"model": 0.95, "identity": 0.95, "spatial": 0.95, "temporal": 0.95, "policy": 1.0, "aggregate": 0.95}

PHONE_FAKE = FakeLLMClient(
    caption_rules=[
        ("phone", {"caption": "一部黑色手机放在黑色圆凳上", "scene_tags": ["手机"]}),
    ],
    extract_rules=[
        (
            "phone",
            [
                {
                    "predicate": "OBSERVED_AT",
                    "object_text": "手机",
                    "value": {"location": "黑色圆凳"},
                    "confidence": HIGH,
                }
            ],
        )
    ],
)


async def _setup_memory(client: AsyncClient, fake: FakeLLMClient, make_image) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    envelope = {
        "occurred_at": ts, "observed_at": ts,
        "idempotency_key": "forget-test-1", "trigger": "explicit", "modality": "image",
    }
    resp = await client.post(
        "/internal/v1/envelopes",
        data={"envelope": json.dumps(envelope)},
        files=[("files", ("phone.jpg", make_image((10, 10, 10)), "image/jpeg"))],
    )
    assert resp.status_code == 200
    while await process_outbox_once(fake):
        pass


async def test_forget_recent_full_pipeline(db_session, make_image):
    fake = PHONE_FAKE
    app = create_app(fake_llm=fake, with_workers=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _setup_memory(client, fake, make_image)

        # 确认记忆已建立
        where = (await client.get("/v1/memory/objects/where-is", params={"name": "手机"})).json()
        assert where["location"] == "黑色圆凳"
        items = (await db_session.scalars(select(EvidenceItem))).all()
        evidence_paths = [Path(i.storage_ref) for i in items if i.storage_ref]
        assert evidence_paths and all(p.exists() for p in evidence_paths), "证据文件应已落盘"

        resp = await client.post("/v1/memory/forget-recent", json={"minutes": 10})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "DONE"
        assert body["tombstone_id"] is not None
        assert all(j["status"] == "DONE" for j in body["jobs"])

    # 证据文件物理删除
    assert all(not p.exists() for p in evidence_paths)
    # frame/事件全部失效或删除
    assert (await db_session.scalars(select(FrameAsset))).all() == []
    events = (await db_session.scalars(select(MemoryEvent))).all()
    assert all(e.valid_to is not None for e in events)
    # 投影重算为空
    projs = (await db_session.scalars(select(StateProjection))).all()
    assert projs == [] or all(p.state == {} for p in projs)
    # tombstone + audit
    tombs = (await db_session.scalars(select(DeletionTombstone))).all()
    assert len(tombs) == 1 and tombs[0].audit_hash
    audits = (await db_session.scalars(select(AuditRecord).where(AuditRecord.action == "forget"))).all()
    assert len(audits) == 1

    # 遗忘后 where-is 不应再给出旧位置（记忆被真正抹除）
    app2 = create_app(fake_llm=fake, with_workers=False)
    async with AsyncClient(transport=ASGITransport(app=app2), base_url="http://test") as client2:
        where2 = (await client2.get("/v1/memory/objects/where-is", params={"name": "手机"})).json()
        assert where2["location"] is None or where2["channel"] != "projection"


async def test_ttl_sweep_deletes_expired_evidence(db_session, make_image):
    fake = PHONE_FAKE
    app = create_app(fake_llm=fake, with_workers=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _setup_memory(client, fake, make_image)

    # 手动把 TTL 拨到过去，模拟过期
    items = (await db_session.scalars(select(EvidenceItem))).all()
    assert len(items) == 1
    file_path = Path(items[0].storage_ref)
    assert file_path.exists()
    items[0].ttl_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()

    deleted = await sweep_expired_evidence(db_session)
    assert deleted == 1
    await db_session.refresh(items[0])
    assert items[0].retention_state == "DELETED"
    assert items[0].storage_ref is None
    assert not file_path.exists()

    audits = (
        await db_session.scalars(select(AuditRecord).where(AuditRecord.action == "ttl_delete"))
    ).all()
    assert len(audits) == 1
