"""采集控制测试：控制台下发 CAPTURE_REQUEST → connector 分发 → 回执。

adb 通道注入假执行器，测试不依赖插着的眼镜，也不会真去动本机 USB。
"""
from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import AuditRecord, Device, DeviceMessage

PROBE = "com.realitymemory.glassprobe"
GLASSES = "com.realitymemory.glasses"


class FakeAdb:
    """记录 argv 的假 adb。returncode/stdout 可调，用来演练失败路径。"""

    def __init__(self, returncode: int = 0, stdout: str = "Starting: Intent{...}") -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.stdout = stdout

    async def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.calls.append(argv)
        return self.returncode, self.stdout, ""


def _app(adb: FakeAdb | None = None):
    return create_app(fake_llm=FakeLLMClient(), with_workers=False, adb_runner=adb)


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _device_id(db_session) -> uuid.UUID:
    device = await db_session.scalar(select(Device).limit(1))
    return device.id


async def _bind(client, device_id, *, package: str, transport: str) -> None:
    resp = await client.patch(
        f"/internal/v1/devices/{device_id}/binding",
        json={"runtime_package": package, "control_transport": transport},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_adb_photo_request_is_translated_to_intent(db_session):
    """探针 + adb：拍照请求变成 capture_once intent，并以 EXECUTED 终结。"""
    adb = FakeAdb()
    app = _app(adb)
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        await _bind(client, device_id, package=PROBE, transport="adb")

        resp = await client.post(
            f"/internal/v1/devices/{device_id}/capture-requests",
            json={"action": "CAPTURE_PHOTO"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

    assert body["dispatch"]["transport"] == "adb"
    assert body["dispatch"]["accepted"] is True
    # 命令送到运行时 ≠ 照片拍到了，响应必须如实标注结论强度
    assert body["dispatch"]["detail"]["execution_evidence"] == "intent_delivered_only"
    # adb 通道拿不到设备回执，所以自己写终态；消息随之 CLOSED
    assert body["message"]["status"] == "CLOSED"
    assert body["message"]["last_receipt_status"] == "EXECUTED"
    assert body["pushed_connections"] == 0

    # 唤醒在前、intent 在后：熄屏时 Android 12 会挡掉 camera 前台服务的启动，
    # `am start` 却照样返回成功（真机实测不唤醒时探针一条日志都不落）
    assert adb.calls == [
        ["adb", "shell", "input", "keyevent", "224"],
        ["adb", "shell", "am", "start", "-n", f"{PROBE}/.MainActivity",
         "--ez", "capture_once", "true"],
    ]
    assert body["dispatch"]["detail"]["wake_sent"] is True


@pytest.mark.asyncio
async def test_formal_app_uses_its_own_debug_command(db_session):
    """正式 App 的调试契约是 rme_debug_command 字符串，不是探针的 boolean extra。"""
    adb = FakeAdb()
    app = _app(adb)
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        await _bind(client, device_id, package=GLASSES, transport="adb")
        resp = await client.post(
            f"/internal/v1/devices/{device_id}/capture-requests",
            json={"action": "CAPTURE_PHOTO"},
        )
        assert resp.status_code == 200, resp.text

    assert adb.calls[-1][-3:] == ["--es", "rme_debug_command", "remember_now"]


@pytest.mark.asyncio
async def test_unsupported_action_is_rejected_and_never_reaches_inbox(db_session):
    """动作在该运行时上不存在 → REJECTED 终态。

    这是双通道设计最危险的坑：如果失败的 adb 请求停在 PENDING，设备哪天从 inbox 拉一次，
    一条控制台上显示为失败的请求就会被真正执行。终态必须当场落。
    """
    adb = FakeAdb()
    app = _app(adb)
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        await _bind(client, device_id, package=PROBE, transport="adb")
        resp = await client.post(
            f"/internal/v1/devices/{device_id}/capture-requests",
            json={"action": "CAPTURE_AUDIO", "duration_seconds": 8},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        inbox = (await client.get(f"/internal/v1/devices/{device_id}/inbox")).json()

    assert body["dispatch"]["accepted"] is False
    assert body["dispatch"]["detail"]["reason"] == "unsupported_action"
    assert body["message"]["status"] == "CLOSED"
    assert body["message"]["last_receipt_status"] == "REJECTED"
    # 不支持的动作根本没发出去
    assert adb.calls == []
    # 关键回归：这条请求不能出现在设备待投递队列里
    assert [m["message_id"] for m in inbox["messages"]] == []


@pytest.mark.asyncio
async def test_adb_failure_lands_failed_and_is_not_left_pending(db_session):
    """adb 报错 → FAILED 终态，同样不留在 inbox 队列里。"""
    adb = FakeAdb(returncode=1, stdout="Error: Activity not started")
    app = _app(adb)
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        await _bind(client, device_id, package=PROBE, transport="adb")
        resp = await client.post(
            f"/internal/v1/devices/{device_id}/capture-requests",
            json={"action": "CAPTURE_PHOTO"},
        )
        body = resp.json()
        inbox = (await client.get(f"/internal/v1/devices/{device_id}/inbox")).json()

    assert body["dispatch"]["accepted"] is False
    assert body["dispatch"]["detail"]["reason"] == "adb_dispatch_failed"
    assert body["message"]["last_receipt_status"] == "FAILED"
    assert inbox["messages"] == []


@pytest.mark.asyncio
async def test_probe_hardcoded_interval_is_reported_not_silently_dropped(db_session):
    """探针周期写死 30s，intent 传不进去——必须如实回报，别让控制台以为设置生效了。"""
    adb = FakeAdb()
    app = _app(adb)
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        await _bind(client, device_id, package=PROBE, transport="adb")
        resp = await client.post(
            f"/internal/v1/devices/{device_id}/capture-requests",
            json={"action": "START_PERIODIC", "interval_seconds": 10},
        )
        body = resp.json()

    assert body["dispatch"]["accepted"] is True
    assert "interval_seconds" in body["dispatch"]["detail"]["ignored"]


@pytest.mark.asyncio
async def test_inbox_transport_waits_for_device_receipt(db_session):
    """inbox 通道：云端不替设备宣布执行成功，终态只能由设备回执产生。"""
    app = _app()
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        await _bind(client, device_id, package=PROBE, transport="inbox")
        created = (
            await client.post(
                f"/internal/v1/devices/{device_id}/capture-requests",
                json={"action": "CAPTURE_PHOTO"},
            )
        ).json()
        assert created["dispatch"]["accepted"] is True
        assert created["dispatch"]["detail"]["delivery"] == "queued_for_inbox"
        # 设备没回执之前不能是终态
        assert created["message"]["status"] == "PENDING"
        assert created["message"]["last_receipt_status"] is None

        message_id = created["message"]["message_id"]
        inbox = (await client.get(f"/internal/v1/devices/{device_id}/inbox")).json()
        assert [m["message_id"] for m in inbox["messages"]] == [message_id]
        payload = inbox["messages"][0]["payload"]
        assert payload["action"] == "CAPTURE_PHOTO"
        # 设备必须知道这是请求不是命令
        assert payload["requires_local_policy_check"] is True

        receipt = (
            await client.post(
                f"/internal/v1/devices/{device_id}/receipts",
                json={"message_id": message_id, "status": "EXECUTED"},
            )
        ).json()
        assert receipt["message_status"] == "CLOSED"


@pytest.mark.asyncio
async def test_device_can_reject_by_local_policy(db_session):
    """设备本地策略拒绝 → REJECTED，理由留在回执 detail 里供审计区分。

    REJECTED 和 FAILED 分开的意义就在这里：前者是隐私设计在正常工作，后者是链路坏了。
    """
    app = _app()
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        await _bind(client, device_id, package=PROBE, transport="inbox")
        created = (
            await client.post(
                f"/internal/v1/devices/{device_id}/capture-requests",
                json={"action": "CAPTURE_PHOTO"},
            )
        ).json()
        message_id = created["message"]["message_id"]

        resp = await client.post(
            f"/internal/v1/devices/{device_id}/receipts",
            json={
                "message_id": message_id,
                "status": "REJECTED",
                "detail": {"policy": "privacy_paused", "message": "用户已暂停采集"},
            },
        )
        assert resp.json()["message_status"] == "CLOSED"

        history = (
            await client.get(f"/internal/v1/devices/{device_id}/capture-requests")
        ).json()

    record = history["requests"][0]
    assert record["action"] == "CAPTURE_PHOTO"
    assert record["transport"] == "inbox"
    assert [r["status"] for r in record["receipts"]] == ["REJECTED"]
    assert record["receipts"][0]["detail"]["policy"] == "privacy_paused"


@pytest.mark.asyncio
async def test_request_transport_overrides_device_binding(db_session):
    """请求里显式指定通道时压过设备默认绑定（同一台设备上对比两条链路）。"""
    adb = FakeAdb()
    app = _app(adb)
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        await _bind(client, device_id, package=PROBE, transport="inbox")
        body = (
            await client.post(
                f"/internal/v1/devices/{device_id}/capture-requests",
                json={"action": "CAPTURE_PHOTO", "transport": "adb"},
            )
        ).json()

    assert body["dispatch"]["transport"] == "adb"
    assert adb.calls[-1][3] == "start"  # 走到了 am start，说明用的是 adb 不是 inbox


@pytest.mark.asyncio
async def test_unbound_device_fails_loudly(db_session):
    """没绑运行时就走 adb → 明确报错，而不是发一条谁也收不到的 intent。"""
    adb = FakeAdb()
    app = _app(adb)
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        body = (
            await client.post(
                f"/internal/v1/devices/{device_id}/capture-requests",
                json={"action": "CAPTURE_PHOTO", "transport": "adb"},
            )
        ).json()

    assert body["dispatch"]["accepted"] is False
    assert body["dispatch"]["detail"]["reason"] == "device_not_bound"
    assert adb.calls == []


@pytest.mark.asyncio
async def test_contract_violations_are_rejected(db_session):
    """契约校验：未知动作、参数与动作不匹配、未知通道、未知设备。"""
    app = _app()
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        bad_action = await client.post(
            f"/internal/v1/devices/{device_id}/capture-requests",
            json={"action": "RECORD_SCREEN"},
        )
        # 参数静默忽略会让控制台以为设置生效了，所以配错动作直接 422
        mismatched = await client.post(
            f"/internal/v1/devices/{device_id}/capture-requests",
            json={"action": "CAPTURE_PHOTO", "interval_seconds": 30},
        )
        bad_transport = await client.post(
            f"/internal/v1/devices/{device_id}/capture-requests",
            json={"action": "CAPTURE_PHOTO", "transport": "carrier_pigeon"},
        )
        unknown_device = await client.post(
            f"/internal/v1/devices/{uuid.uuid4()}/capture-requests",
            json={"action": "CAPTURE_PHOTO"},
        )

    assert bad_action.status_code == 422
    assert mismatched.status_code == 422
    assert bad_transport.status_code == 422
    assert unknown_device.status_code == 404


@pytest.mark.asyncio
async def test_devices_are_listable_and_bindable(db_session):
    """控制台需要能列设备并改绑定，不然联调要手改数据库。"""
    app = _app()
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        before = (await client.get("/internal/v1/devices")).json()
        assert before["devices"][0]["control_transport"] == "inbox"  # 未绑定时的默认

        await _bind(client, device_id, package=PROBE, transport="adb")
        after = (await client.get("/internal/v1/devices")).json()

    assert after["devices"][0]["runtime_package"] == PROBE
    assert after["devices"][0]["control_transport"] == "adb"


@pytest.mark.asyncio
async def test_every_request_is_audited(db_session):
    """每一次采集请求都要能在审计里查到——这是远程触发相机的最低要求。"""
    adb = FakeAdb()
    app = _app(adb)
    device_id = await _device_id(db_session)
    async with _client(app) as client:
        await _bind(client, device_id, package=PROBE, transport="adb")
        await client.post(
            f"/internal/v1/devices/{device_id}/capture-requests",
            json={"action": "CAPTURE_PHOTO", "reason": "demo_rehearsal"},
        )

    msg = await db_session.scalar(select(DeviceMessage))
    actions = (
        await db_session.scalars(
            select(AuditRecord.action).where(AuditRecord.target == f"device_message:{msg.id}")
        )
    ).all()
    assert "capture_request_create" in actions
    # 分发是独立一条：控制台点下去了、和命令真的送出去了，是两件事
    assert "capture_request_dispatch" in actions
