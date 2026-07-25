"""耳机（IFLYBUDS）接入：设备注册 + inbox 通道上的采集请求与语音推送。

设备侧跑的是 `apps/iflybuds-collector`（宿主机 Collector），后端这边没有为它新增任何
通道——这组测试要证明的正是这一点：一副蓝牙耳机接进来，走的是与眼镜完全相同的
inbox + 回执语义，后端只多了一个「注册设备」的入口。

设备侧的录音、播报和本地策略在 `apps/iflybuds-collector/tests/` 里测，那边不需要
数据库；这里只测后端契约。
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import Device, DeviceMessage

COLLECTOR = "iflybuds-host-collector/0.1.0"
EARBUDS_NAME = "IFLYBUDS Air 2"


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=create_app(fake_llm=FakeLLMClient(), with_workers=False)),
        base_url="http://test",
    )


async def _register(client: AsyncClient, **overrides) -> dict:
    body = {
        "kind": "earbuds",
        "name": EARBUDS_NAME,
        "runtime_package": COLLECTOR,
        "control_transport": "inbox",
        **overrides,
    }
    resp = await client.post("/internal/v1/devices", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_register_earbuds_is_idempotent_by_name(db_session):
    """采集器每次启动都会注册一次，不能因此攒出一堆同名设备。"""
    async with _client() as client:
        first = await _register(client)
        second = await _register(client, runtime_package="iflybuds-host-collector/0.2.0")

    assert first["device_id"] == second["device_id"]
    assert second["kind"] == "earbuds"
    # 重复注册顺带刷新绑定：升级 collector 后 runtime_package 会跟着走
    assert second["runtime_package"] == "iflybuds-host-collector/0.2.0"
    assert second["control_transport"] == "inbox"

    devices = (
        await db_session.scalars(select(Device).where(Device.name == EARBUDS_NAME))
    ).all()
    assert len(devices) == 1


@pytest.mark.asyncio
async def test_register_rejects_unknown_kind(db_session):
    """kind 是枚举：拼错的设备类型要当场报错，而不是安静地建一台没人认识的设备。"""
    async with _client() as client:
        resp = await client.post(
            "/internal/v1/devices", json={"kind": "headphone", "name": "拼错的耳机"}
        )
    assert resp.status_code == 422
    assert "未知设备类型" in resp.text


@pytest.mark.asyncio
async def test_capture_audio_request_reaches_earbuds_through_inbox(db_session):
    """录一段：控制台下发 → 排队等采集器来拉 → 采集器回 EXECUTED。

    inbox 通道下后端不写终态（云端不替设备宣布采集成功），所以下发后消息应停在
    PENDING，直到采集器自己回执。
    """
    async with _client() as client:
        device_id = (await _register(client))["device_id"]

        created = await client.post(
            f"/internal/v1/devices/{device_id}/capture-requests",
            json={"action": "CAPTURE_AUDIO", "duration_seconds": 8, "reason": "operator_console"},
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["dispatch"]["transport"] == "inbox"
        assert body["dispatch"]["accepted"] is True
        assert body["dispatch"]["detail"]["delivery"] == "queued_for_inbox"
        # 关键：云端没有替耳机宣布执行成功
        assert body["message"]["status"] == "PENDING"
        assert body["message"]["last_receipt_status"] is None
        message_id = body["message"]["message_id"]

        inbox = await client.get(f"/internal/v1/devices/{device_id}/inbox")
        messages = inbox.json()["messages"]
        assert [m["message_id"] for m in messages] == [message_id]
        payload = messages[0]["payload"]
        assert payload["action"] == "CAPTURE_AUDIO"
        assert payload["duration_seconds"] == 8
        assert payload["requires_local_policy_check"] is True

        # 采集器录完并上传后回执
        receipt = await client.post(
            f"/internal/v1/devices/{device_id}/receipts",
            json={
                "message_id": message_id,
                "status": "EXECUTED",
                "detail": {"peak_level": 0.42, "actual_duration_seconds": 8.0, "uploaded": 1},
            },
        )
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["message_status"] == "CLOSED"

        listed = await client.get(f"/internal/v1/devices/{device_id}/capture-requests")
        record = listed.json()["requests"][0]
        assert record["action"] == "CAPTURE_AUDIO"
        assert record["transport"] == "inbox"
        assert [r["status"] for r in record["receipts"]] == ["EXECUTED"]
        # 终结后不再出现在待投递集合里，采集器重连也不会再收到一次
        assert (await client.get(f"/internal/v1/devices/{device_id}/inbox")).json()["messages"] == []


@pytest.mark.asyncio
async def test_photo_request_to_earbuds_is_rejected_by_device(db_session):
    """耳机没有摄像头：后端照发不误，拒绝权在设备侧，理由回到控制台。

    后端不按 kind 猜设备能做什么——它不知道 earbuds 没有摄像头，也不该知道。
    """
    async with _client() as client:
        device_id = (await _register(client))["device_id"]
        created = await client.post(
            f"/internal/v1/devices/{device_id}/capture-requests", json={"action": "CAPTURE_PHOTO"}
        )
        assert created.status_code == 200
        message_id = created.json()["message"]["message_id"]

        await client.post(
            f"/internal/v1/devices/{device_id}/receipts",
            json={
                "message_id": message_id,
                "status": "REJECTED",
                "detail": {"policy": "IFLYBUDS 是耳机，没有摄像头；要图像请改用眼镜设备"},
            },
        )

        listed = await client.get(f"/internal/v1/devices/{device_id}/capture-requests")
        record = listed.json()["requests"][0]
        assert record["receipts"][-1]["status"] == "REJECTED"
        assert "没有摄像头" in record["receipts"][-1]["detail"]["policy"]


@pytest.mark.asyncio
async def test_voice_push_closes_after_spoken(db_session):
    """语音推送：下发提醒 → 采集器拉到 → PRESENTED/SPOKEN → DISMISSED 终结。

    耳机上没有「用户点掉提醒」这个动作，播完就是终局；不落终态的话消息会一直留在
    待投递集合里被反复重推。
    """
    async with _client() as client:
        device_id = (await _register(client))["device_id"]

        pushed = await client.post(
            f"/internal/v1/devices/{device_id}/messages",
            json={
                "message_type": "REMINDER_SIGNAL",
                "payload": {"text": "牛奶还有两天过期"},
                "delivery_policy": {"allow_text": True, "allow_tts": True},
            },
        )
        assert pushed.status_code == 200, pushed.text
        message = pushed.json()["message"]
        assert message["delivery_policy"]["allow_tts"] is True
        assert pushed.json()["pushed_connections"] == 0  # 没有长连，排队等 inbox
        message_id = message["message_id"]

        inbox = await client.get(f"/internal/v1/devices/{device_id}/inbox")
        assert inbox.json()["messages"][0]["payload"]["text"] == "牛奶还有两天过期"

        for status in ("RECEIVED", "PRESENTED", "SPOKEN"):
            resp = await client.post(
                f"/internal/v1/devices/{device_id}/receipts",
                json={"message_id": message_id, "status": status, "detail": {}},
            )
            assert resp.status_code == 200
            # 过程回执不终结消息
            assert resp.json()["message_status"] == "RECEIVED"

        closed = await client.post(
            f"/internal/v1/devices/{device_id}/receipts",
            json={
                "message_id": message_id,
                "status": "DISMISSED",
                "detail": {"output_device": "IFLYBUDS Air 2", "closed_by": "playback_finished"},
            },
        )
        assert closed.json()["message_status"] == "CLOSED"
        assert (await client.get(f"/internal/v1/devices/{device_id}/inbox")).json()["messages"] == []


@pytest.mark.asyncio
async def test_playback_rejected_when_output_is_not_the_earbuds(db_session):
    """默认输出设备不是耳机时采集器拒播，理由必须能回到控制台。

    这是输出方向的「策略在边缘执行」：云端不知道那台机器当前的默认输出设备是什么。
    """
    async with _client() as client:
        device_id = (await _register(client))["device_id"]
        pushed = await client.post(
            f"/internal/v1/devices/{device_id}/messages",
            json={
                "message_type": "REMINDER_SIGNAL",
                "payload": {"text": "该喝水了"},
                "delivery_policy": {"allow_text": True, "allow_tts": True},
            },
        )
        message_id = pushed.json()["message"]["message_id"]

        rejected = await client.post(
            f"/internal/v1/devices/{device_id}/receipts",
            json={
                "message_id": message_id,
                "status": "REJECTED",
                "detail": {
                    "policy": "当前默认输出设备是「MacBook Pro Speakers」，不是「IFLYBUDS」，播报会从外放出去",
                    "output_device": "MacBook Pro Speakers",
                },
            },
        )
        assert rejected.json()["message_status"] == "CLOSED"

        stored = await db_session.get(DeviceMessage, uuid.UUID(message_id))
        assert stored.last_receipt_status == "REJECTED"
