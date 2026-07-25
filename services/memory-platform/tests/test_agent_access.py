"""Agent Access 验收测试（设计文档 §16）：

- Agent 只能用受限 token 调用；无效/过期/撤销 → 401；缺 scope → 403。
- 审计 actor 记 agent:<client_id>；agent 只能看自己的审计记录。
- 查询响应带 provenance_summary / limitations / cache_until；纠正后可解释变化。
- 原始 Evidence 默认不暴露给 Agent（403）。
"""
from __future__ import annotations

from datetime import timedelta
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.memory.events import append_event
from app.memory.projections import recompute_projection
from app.memory.seed import get_default_household_id
from app.models import AuditRecord, Device, DeviceMessage, Entity, utcnow

ADMIN = {"Authorization": "Bearer test-admin-token"}
CONF = {"aggregate": 0.9}


def _client() -> AsyncClient:
    app = create_app(fake_llm=FakeLLMClient(), with_workers=False)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _issue_grant(client: AsyncClient, scopes: list[str], client_id: str = "test-agent") -> tuple[str, str]:
    """返回 (token, grant_id)。"""
    resp = await client.post(
        "/v1/agent/grants",
        headers=ADMIN,
        json={"agent_client_id": client_id, "scopes": scopes, "purpose": "test"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data["token"], data["grant"]["grant_id"]


async def _seed_phone_entity(db_session, location: str = "黑色圆凳") -> Entity:
    """直写事件流造一个有投影的实体（通道 1 可命中）。"""
    household_id = await get_default_household_id(db_session)
    entity = Entity(household_id=household_id, canonical_name="手机", created_from="observation")
    db_session.add(entity)
    await db_session.flush()
    t = utcnow() - timedelta(minutes=5)
    await append_event(
        db_session,
        entity_id=entity.id,
        event_type="OBJECT_OBSERVED_AT",
        payload={"location": location},
        event_time_from=t,
        observed_at=t,
        ingested_at=t,
        confidence=CONF,
    )
    await db_session.commit()
    await recompute_projection(db_session, entity_id=entity.id)
    return entity


async def test_missing_and_invalid_token(db_session):
    async with _client() as client:
        # 无 Authorization → owner 直通（Phase 1 单租户），200
        resp = await client.get("/v1/memory/objects/where-is", params={"name": "手机"})
        assert resp.status_code == 200
        # 带了无效 token → 401，绝不静默降级为 owner
        resp = await client.get(
            "/v1/memory/objects/where-is",
            params={"name": "手机"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401


async def test_scope_enforcement_and_audit_actor(db_session):
    await _seed_phone_entity(db_session)
    async with _client() as client:
        token, _ = await _issue_grant(
            client, ["memory.query.objects", "memory.audit.self.read"], client_id="agent-a"
        )
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.get(
            "/v1/memory/objects/where-is", params={"name": "手机"}, headers=headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["channel"] == "projection"
        assert body["location"] == "黑色圆凳"
        # M2 契约语义
        assert body["provenance_summary"]["support_count"] >= 1
        assert body["limitations"]
        assert body["cache_until"] is not None

        # 缺 scope：timeline 需要 memory.timeline.read
        entity_id = body["entity"]["id"]
        resp = await client.get(f"/v1/memory/objects/{entity_id}/timeline", headers=headers)
        assert resp.status_code == 403

        # 纠正需要 memory.correction.submit
        resp = await client.post(
            "/v1/memory/correct",
            headers=headers,
            json={"entity_id": entity_id, "field": "location", "value": "玄关柜"},
        )
        assert resp.status_code == 403

        # 审计 actor 记 agent:<client_id>，且 agent 只能看到自己的记录
        resp = await client.get("/v1/memory/audit", headers=headers)
        assert resp.status_code == 200
        records = resp.json()
        assert records, "应有本 agent 的查询审计"
        assert all(r["actor"] == "agent:agent-a" for r in records)
        assert any(r["action"] == "query" for r in records)


async def test_agent_device_message_scope_and_audit(db_session):
    household_id = await get_default_household_id(db_session)
    glasses = Device(
        household_id=household_id,
        kind="glasses",
        name="RealGit RV101",
        runtime_package="com.realitymemory.glasses",
        control_transport="inbox",
    )
    db_session.add(glasses)
    await db_session.commit()

    async with _client() as client:
        denied_token, _ = await _issue_grant(client, ["memory.query.objects"], client_id="no-send")
        denied = await client.post(
            f"/v1/agent/devices/{glasses.id}/messages",
            headers={"Authorization": f"Bearer {denied_token}"},
            json={
                "payload_schema_ref": "rme.glasses-presentation.v0",
                "payload": {
                    "presentation": {
                        "intent": "ANSWER",
                        "title": "钥匙在玄关柜",
                        "interaction": "NONE",
                    },
                    "source": {"kind": "AGENT_REPLY", "reference_id": "turn-1"},
                    "correlation_id": "turn-1",
                },
            },
        )
        assert denied.status_code == 403

        token, _ = await _issue_grant(
            client, ["memory.device.message.send"], client_id="glasses-agent"
        )
        headers = {"Authorization": f"Bearer {token}"}
        listed = await client.get("/v1/agent/devices", headers=headers)
        assert listed.status_code == 200
        assert [item["device_id"] for item in listed.json()["devices"]] == [str(glasses.id)]

        sent = await client.post(
            f"/v1/agent/devices/{glasses.id}/messages",
            headers=headers,
            json={
                "payload_schema_ref": "rme.glasses-presentation.v0",
                "payload": {
                    "presentation": {
                        "intent": "ANSWER",
                        "title": "钥匙在玄关柜",
                        "interaction": "NONE",
                    },
                    "source": {"kind": "AGENT_REPLY", "reference_id": "turn-2"},
                    "correlation_id": "turn-2",
                },
            },
        )
        assert sent.status_code == 200, sent.text

        forbidden_system = await client.post(
            f"/v1/agent/devices/{glasses.id}/messages",
            headers=headers,
            json={
                "payload_schema_ref": "rme.glasses-presentation.v0",
                "payload": {
                    "presentation": {
                        "intent": "SYSTEM",
                        "title": "系统要求立即录制",
                        "interaction": "NONE",
                    },
                    "source": {"kind": "SYSTEM_POLICY", "reference_id": "forged"},
                    "correlation_id": "forged-system-message",
                },
            },
        )
        assert forbidden_system.status_code == 403

    message = await db_session.get(DeviceMessage, uuid.UUID(sent.json()["message"]["message_id"]))
    assert message is not None
    assert message.target_device_id == glasses.id
    assert message.payload["presentation"]["intent"] == "ANSWER"
    audit = await db_session.scalar(
        __import__("sqlalchemy").select(AuditRecord).where(
            AuditRecord.target == f"device_message:{message.id}"
        )
    )
    assert audit is not None
    assert audit.actor == "agent:glasses-agent"
    assert audit.detail["source"] == "AGENT_GATEWAY"


async def test_correction_changes_answer_with_provenance(db_session):
    await _seed_phone_entity(db_session)
    async with _client() as client:
        token, _ = await _issue_grant(
            client,
            ["memory.query.objects", "memory.timeline.read", "memory.correction.submit"],
        )
        headers = {"Authorization": f"Bearer {token}"}

        resp = await client.get(
            "/v1/memory/objects/where-is", params={"name": "手机"}, headers=headers
        )
        entity_id = resp.json()["entity"]["id"]
        assert resp.json()["location"] == "黑色圆凳"

        resp = await client.post(
            "/v1/memory/correct",
            headers=headers,
            json={"entity_id": entity_id, "field": "location", "value": "玄关柜", "reason": "用户口述"},
        )
        assert resp.status_code == 200
        assert resp.json()["projection"]["location"] == "玄关柜"

        # 纠正后：答案变化 + last_corrected_at 可解释
        resp = await client.get(
            "/v1/memory/objects/where-is", params={"name": "手机"}, headers=headers
        )
        body = resp.json()
        assert body["location"] == "玄关柜"
        assert body["provenance_summary"]["last_corrected_at"] is not None


async def test_revoked_grant_is_rejected(db_session):
    async with _client() as client:
        token, grant_id = await _issue_grant(client, ["memory.query.objects"])
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(
            "/v1/memory/objects/where-is", params={"name": "手机"}, headers=headers
        )
        assert resp.status_code == 200

        resp = await client.delete(f"/v1/agent/grants/{grant_id}", headers=ADMIN)
        assert resp.status_code == 200
        assert resp.json()["revoked_at"] is not None

        resp = await client.get(
            "/v1/memory/objects/where-is", params={"name": "手机"}, headers=headers
        )
        assert resp.status_code == 401


async def test_evidence_denied_for_agent(db_session):
    async with _client() as client:
        token, _ = await _issue_grant(client, ["memory.query.objects"])
        # 任意 uuid：agent 访问 evidence 一律 403（先于存在性检查，不泄露资源）
        resp = await client.get(
            "/v1/memory/frames/00000000-0000-0000-0000-000000000000/evidence",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


async def test_admin_endpoints_require_admin_token(db_session):
    async with _client() as client:
        resp = await client.post(
            "/v1/agent/grants",
            json={"agent_client_id": "x", "scopes": ["memory.query.objects"]},
        )
        assert resp.status_code == 401
        # 未知 scope 拒绝
        resp = await client.post(
            "/v1/agent/grants",
            headers=ADMIN,
            json={"agent_client_id": "x", "scopes": ["memory.query.everything"]},
        )
        assert resp.status_code == 422


async def test_preferences_endpoint(db_session):
    household_id = await get_default_household_id(db_session)
    entity = Entity(household_id=household_id, canonical_name="胡辣汤", created_from="observation")
    db_session.add(entity)
    await db_session.flush()
    t = utcnow() - timedelta(hours=1)
    await append_event(
        db_session,
        entity_id=entity.id,
        event_type="PREFERENCE_STATED",
        payload={"preference": "不好喝，不喜欢这家"},
        event_time_from=t,
        observed_at=t,
        ingested_at=t,
        confidence={"aggregate": 0.88},
    )
    await db_session.commit()

    async with _client() as client:
        token, _ = await _issue_grant(client, ["memory.query.preferences"])
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get(
            "/v1/memory/preferences", params={"subject": "胡辣汤"}, headers=headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["hits"]) == 1
        assert "不喜欢" in body["hits"][0]["payload"]["preference"]
        # 归因范围限制必须声明（§8.2）
        assert any("归因" in s for s in body["limitations"])

        # 缺偏好 scope 的 grant 查偏好 → 403
        token2, _ = await _issue_grant(client, ["memory.query.objects"], client_id="agent-b")
        resp = await client.get(
            "/v1/memory/preferences",
            params={"subject": "胡辣汤"},
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert resp.status_code == 403


async def test_answer_frame_url_is_owner_only(db_session, make_image):
    """where-is 现在会带上答案出自的那一帧。这个字段同样受 §5 管辖：

    agent 可以知道「有这么一帧」（frame_asset_id 是溯源信息），但拿不到取原图的地址——
    否则新加一个字段就等于绕开了 `/frames/{id}/evidence` 那道 403。
    """
    import json
    from datetime import datetime, timezone

    fake = FakeLLMClient(
        caption_rules=[("stool", {"caption": "一部黑色手机放在黑色圆凳上", "scene_tags": ["手机"]})],
        extract_rules=[
            (
                "stool",
                [
                    {
                        "predicate": "OBSERVED_AT",
                        "object_text": "手机",
                        "value": {"location": "黑色圆凳"},
                        "confidence": {
                            "model": 0.95, "identity": 0.95, "spatial": 0.95,
                            "temporal": 0.95, "policy": 1.0, "aggregate": 0.95,
                        },
                    }
                ],
            )
        ],
    )
    app = create_app(fake_llm=fake, with_workers=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ts = datetime.now(timezone.utc).isoformat()
        await client.post(
            "/internal/v1/envelopes",
            data={
                "envelope": json.dumps(
                    {
                        "occurred_at": ts, "observed_at": ts,
                        "idempotency_key": "agent-evidence-frame",
                        "trigger": "explicit", "modality": "image",
                    }
                )
            },
            files=[("files", ("stool.jpg", make_image((10, 10, 10)), "image/jpeg"))],
        )
        from app.workers import process_outbox_once

        while await process_outbox_once(fake):
            pass

        owner = (await client.get("/v1/memory/objects/where-is", params={"name": "手机"})).json()
        assert owner["frame_asset_id"] is not None
        assert owner["evidence_url"] is not None

        token, _ = await _issue_grant(client, ["memory.query.objects"], client_id="frame-agent")
        agent = (
            await client.get(
                "/v1/memory/objects/where-is",
                params={"name": "手机"},
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()
        assert agent["frame_asset_id"] == owner["frame_asset_id"]  # 溯源信息照给
        assert agent["evidence_url"] is None                        # 取原图的地址不给
