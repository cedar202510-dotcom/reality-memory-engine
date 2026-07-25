"""下行通道测试：注入 → 长连/轮询投递 → 回执，以及过期、幂等、离线补投。

WebSocket 用直连 ASGI 的极简客户端驱动（httpx 不支持 ws，starlette 的同步
TestClient 会和 async fixture 抢事件循环）。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import Device, DeviceDeliveryReceipt, DeviceMessage, utcnow


def _app():
    return create_app(fake_llm=FakeLLMClient(), with_workers=False)


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _device_id(db_session) -> uuid.UUID:
    device = await db_session.scalar(select(Device).limit(1))
    return device.id


class ASGIWebSocket:
    """直接驱动 ASGI websocket 协议的测试客户端。"""

    def __init__(self, app, path: str) -> None:
        self._app = app
        self._path = path
        self._to_app: asyncio.Queue = asyncio.Queue()
        self._from_app: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self.close_code: int | None = None

    async def __aenter__(self) -> ASGIWebSocket:
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "scheme": "ws",
            "path": self._path,
            "raw_path": self._path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"test")],
            "client": ("test", 123),
            "server": ("test", 80),
            "subprotocols": [],
        }
        self._task = asyncio.create_task(
            self._app(scope, self._to_app.get, self._from_app.put)
        )
        await self._to_app.put({"type": "websocket.connect"})
        msg = await asyncio.wait_for(self._from_app.get(), timeout=5)
        if msg["type"] == "websocket.close":
            self.close_code = msg.get("code")
        else:
            assert msg["type"] == "websocket.accept", msg
        return self

    async def __aexit__(self, *exc) -> None:
        await self._to_app.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._task, timeout=5)

    async def receive_json(self, timeout: float = 5) -> dict:
        msg = await asyncio.wait_for(self._from_app.get(), timeout=timeout)
        if msg["type"] == "websocket.close":
            self.close_code = msg.get("code")
            raise AssertionError(f"连接被关闭：{msg}")
        return json.loads(msg["text"])

    async def send_json(self, data: dict) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": json.dumps(data)})

    async def expect_nothing(self, timeout: float = 0.3) -> None:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(self._from_app.get(), timeout=timeout)


async def test_ws_receives_injected_message_and_acks(db_session):
    """长连在线时注入 → 秒级收到信封 → 回执经 ws 回传 → 消息状态推进。"""
    app = _app()
    device_id = await _device_id(db_session)

    async with ASGIWebSocket(app, f"/internal/v1/devices/{device_id}/stream") as ws:
        await ws.expect_nothing()  # 无积压时连上不该收到任何东西

        async with _client(app) as client:
            resp = await client.post(
                f"/internal/v1/devices/{device_id}/messages",
                json={
                    "message_type": "REMINDER_SIGNAL",
                    "payload": {"text": "钥匙上次在玄关柜上"},
                    "delivery_policy": {"allow_text": True, "allow_tts": True},
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["pushed_connections"] == 1
        assert body["message"]["status"] == "SENT"
        message_id = body["message"]["message_id"]

        envelope = await ws.receive_json()
        assert envelope["schema_ref"] == "rme.device-message.v0"
        assert envelope["message_id"] == message_id
        assert envelope["payload"]["text"] == "钥匙上次在玄关柜上"
        assert envelope["delivery_policy"] == {"allow_text": True, "allow_tts": True}

        await ws.send_json({"type": "receipt", "message_id": message_id, "status": "SPOKEN"})
        ack = await ws.receive_json()
        assert ack == {
            "type": "receipt_ack",
            "message_id": message_id,
            "status": "SPOKEN",
            "duplicate": False,
            "message_status": "RECEIVED",
        }

        await ws.send_json({"type": "receipt", "message_id": message_id, "status": "DISMISSED"})
        ack = await ws.receive_json()
        assert ack["message_status"] == "CLOSED"

    msg = await db_session.get(DeviceMessage, uuid.UUID(message_id))
    await db_session.refresh(msg)
    assert msg.status == "CLOSED"
    assert msg.spoken_at is not None and msg.closed_at is not None


async def test_offline_message_is_backfilled_on_reconnect(db_session):
    """设备离线时注入不丢：落库等重连，连上先冲积压。"""
    app = _app()
    device_id = await _device_id(db_session)

    async with _client(app) as client:
        resp = await client.post(
            f"/internal/v1/devices/{device_id}/messages",
            json={"message_type": "REMINDER_SIGNAL", "payload": {"text": "离线期的提醒"}},
        )
    assert resp.json()["pushed_connections"] == 0  # 没人在线不是错误
    assert resp.json()["message"]["status"] == "PENDING"
    message_id = resp.json()["message"]["message_id"]

    async with ASGIWebSocket(app, f"/internal/v1/devices/{device_id}/stream") as ws:
        envelope = await ws.receive_json()
        assert envelope["message_id"] == message_id


async def test_inbox_polling_is_equivalent_fallback(db_session):
    """轮询兜底：inbox 拿到同一条消息，回执后不再重复出现。"""
    app = _app()
    device_id = await _device_id(db_session)

    async with _client(app) as client:
        created = await client.post(
            f"/internal/v1/devices/{device_id}/messages",
            json={"message_type": "REMINDER_SIGNAL", "payload": {"text": "走轮询的提醒"}},
        )
        message_id = created.json()["message"]["message_id"]

        inbox = await client.get(f"/internal/v1/devices/{device_id}/inbox")
        assert [m["message_id"] for m in inbox.json()["messages"]] == [message_id]

        # 未回执前重复轮询仍会拿到（至少一次投递，设备按 message_id 去重）
        again = await client.get(f"/internal/v1/devices/{device_id}/inbox")
        assert len(again.json()["messages"]) == 1

        await client.post(
            f"/internal/v1/devices/{device_id}/receipts",
            json={"message_id": message_id, "status": "DISMISSED"},
        )
        after = await client.get(f"/internal/v1/devices/{device_id}/inbox")
        assert after.json()["messages"] == []


async def test_expired_message_is_never_delivered(db_session):
    """过期消息不投递、不播报（§5.4）：inbox 不返回，长连也不补投。"""
    app = _app()
    device_id = await _device_id(db_session)

    async with _client(app) as client:
        created = await client.post(
            f"/internal/v1/devices/{device_id}/messages",
            json={
                "message_type": "REMINDER_SIGNAL",
                "payload": {"text": "已经无关的建议"},
                "ttl_seconds": 1,
            },
        )
        message_id = uuid.UUID(created.json()["message"]["message_id"])

        # 直接把过期时间拨到过去，避免测试里真的 sleep
        msg = await db_session.get(DeviceMessage, message_id)
        msg.expires_at = utcnow() - timedelta(seconds=1)
        await db_session.commit()

        inbox = await client.get(f"/internal/v1/devices/{device_id}/inbox")
        assert inbox.json()["messages"] == []
        assert inbox.json()["expired"] == 1

    async with ASGIWebSocket(app, f"/internal/v1/devices/{device_id}/stream") as ws:
        await ws.expect_nothing()

    await db_session.refresh(msg)
    assert msg.status == "EXPIRED"


async def test_receipt_is_idempotent_across_paths(db_session):
    """同一 message_id 的同一状态重复上报只落一条，终态只认第一条（§7 去重）。"""
    app = _app()
    device_id = await _device_id(db_session)

    async with _client(app) as client:
        created = await client.post(
            f"/internal/v1/devices/{device_id}/messages",
            json={"message_type": "REMINDER_SIGNAL", "payload": {"text": "去重测试"}},
        )
        message_id = created.json()["message"]["message_id"]

        first = await client.post(
            f"/internal/v1/devices/{device_id}/receipts",
            json={"message_id": message_id, "status": "PRESENTED"},
        )
        second = await client.post(
            f"/internal/v1/devices/{device_id}/receipts",
            json={"message_id": message_id, "status": "PRESENTED"},
        )
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True

    n = await db_session.scalar(
        select(func.count(DeviceDeliveryReceipt.id)).where(
            DeviceDeliveryReceipt.message_id == uuid.UUID(message_id)
        )
    )
    assert n == 1

    msg = await db_session.get(DeviceMessage, uuid.UUID(message_id))
    await db_session.refresh(msg)
    assert msg.presented_at is not None
    assert msg.status == "RECEIVED"


async def test_unknown_device_and_bad_payload_are_rejected(db_session):
    app = _app()
    ghost = uuid.uuid4()
    device_id = await _device_id(db_session)

    async with _client(app) as client:
        missing = await client.post(
            f"/internal/v1/devices/{ghost}/messages",
            json={"message_type": "REMINDER_SIGNAL", "payload": {}},
        )
        assert missing.status_code == 404

        bad_type = await client.post(
            f"/internal/v1/devices/{device_id}/messages",
            json={"message_type": "BUY_MILK", "payload": {}},
        )
        assert bad_type.status_code == 422

        bad_receipt = await client.post(
            f"/internal/v1/devices/{device_id}/receipts",
            json={"message_id": str(uuid.uuid4()), "status": "NOT_A_STATUS"},
        )
        assert bad_receipt.status_code == 422

    async with ASGIWebSocket(app, f"/internal/v1/devices/{ghost}/stream") as ws:
        assert ws.close_code == 4404


async def test_tts_defaults_to_off(db_session):
    """语音是更硬的打断：不显式开启就只给文字。"""
    app = _app()
    device_id = await _device_id(db_session)

    async with _client(app) as client:
        created = await client.post(
            f"/internal/v1/devices/{device_id}/messages",
            json={"message_type": "REMINDER_SIGNAL", "payload": {"text": "默认不播报"}},
        )
    assert created.json()["message"]["delivery_policy"] == {
        "allow_text": True,
        "allow_tts": False,
    }


async def test_glasses_presentation_payload_is_validated_and_normalized(db_session):
    app = _app()
    device_id = await _device_id(db_session)

    async with _client(app) as client:
        created = await client.post(
            f"/internal/v1/devices/{device_id}/messages",
            json={
                "message_type": "REMINDER_SIGNAL",
                "payload_schema_ref": "rme.glasses-presentation.v0",
                "payload": {
                    "presentation": {
                        "intent": "TASK",
                        "title": "记得把资料给小王",
                        "body": "你已经到公司了",
                        "speech_text": "这段文字不应在 TTS 关闭时继续下发",
                        "interaction": "ACKNOWLEDGE",
                    },
                    "source": {
                        "kind": "MEMORY_SIGNAL",
                        "reference_id": "signal-1",
                    },
                    "correlation_id": "turn-1",
                },
            },
        )

    assert created.status_code == 200
    presentation = created.json()["message"]["payload"]["presentation"]
    assert presentation["intent"] == "TASK"
    assert "speech_text" not in presentation


@pytest.mark.parametrize(
    ("intent", "source_kind"),
    [
        ("PRIVACY", "AGENT_REPLY"),
        ("CONSUMABLE", "AGENT_REPLY"),
        ("ANSWER", "SYSTEM_POLICY"),
    ],
)
async def test_glasses_presentation_rejects_spoofed_source(
    db_session,
    intent: str,
    source_kind: str,
):
    app = _app()
    device_id = await _device_id(db_session)

    async with _client(app) as client:
        response = await client.post(
            f"/internal/v1/devices/{device_id}/messages",
            json={
                "message_type": "REMINDER_SIGNAL",
                "payload_schema_ref": "rme.glasses-presentation.v0",
                "payload": {
                    "presentation": {
                        "intent": intent,
                        "title": "不应通过",
                        "interaction": "NONE",
                    },
                    "source": {"kind": source_kind},
                    "correlation_id": "invalid-source",
                },
            },
        )

    assert response.status_code == 422


async def test_glasses_presentation_rejects_free_style_and_overflow(db_session):
    app = _app()
    device_id = await _device_id(db_session)

    async with _client(app) as client:
        response = await client.post(
            f"/internal/v1/devices/{device_id}/messages",
            json={
                "message_type": "REMINDER_SIGNAL",
                "payload_schema_ref": "rme.glasses-presentation.v0",
                "payload": {
                    "presentation": {
                        "intent": "REMINDER",
                        "title": "过长" * 30,
                        "interaction": "ACKNOWLEDGE",
                        "icon": "<svg>not allowed</svg>",
                    },
                    "source": {"kind": "MEMORY_SIGNAL"},
                    "correlation_id": "invalid-style",
                },
            },
        )

    assert response.status_code == 422
