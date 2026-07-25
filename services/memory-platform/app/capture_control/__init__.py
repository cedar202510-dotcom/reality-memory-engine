"""采集控制面：控制台下发 CAPTURE_REQUEST，connector 负责送到设备。

    前端控制台
      -> POST /internal/v1/devices/{id}/capture-requests
      -> 落库为 CAPTURE_REQUEST 消息（与提醒共用 device_messages）
      -> connector 分发（adb：翻成 intent / inbox：等设备来拉）
      -> 设备本地 PolicyCheck 决定执不执行
      -> 回执 EXECUTED / REJECTED
      -> 控制台轮询 GET .../capture-requests 看到结果

**这里下发的是请求，不是命令。** 通信架构 §8 明确「云端消息不能绕过眼镜本地策略远程
强制打开相机或麦克风……只能生成需要用户确认或本地策略允许的 CaptureIntent，不能直接
调用媒体 API」。所以本模块提供的全部能力就是「把一个 CaptureIntent 草案递给设备」，
设备端有完整的拒绝权，拒绝走 REJECTED 回执，不是静默丢弃。

adb 通道是这条约束的边缘情况：后端直接对着运行时发 intent，看起来更像「命令」。它仍然
落在约束内，因为 intent 只是唤起 App 的调试入口，采不采仍由设备端的权限、佩戴状态和
会话状态决定——但这也正是它只能是联调通道、不能进生产的原因。

鉴权：沿用 `/internal/v1` 现状（本机/内网可信域）。这个前提对采集控制比对提醒更要命——
任何能访问该端口的人都能让眼镜拍照。上生产前必须补设备 token 与 owner 鉴权。
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..connectors import CaptureCommand, build_connector, resolve_transport
from ..db import get_session
from ..downlink import DeviceHub, _apply_receipt, _load_device, _mark_sent, get_hub
from ..memory.events import record_audit
from ..models import Device, DeviceDeliveryReceipt, DeviceMessage, utcnow
from ..schemas import (
    CAPTURE_REQUEST_SCHEMA_REF,
    CaptureRequestCreate,
    CaptureRequestListResponse,
    CaptureRequestOut,
    CaptureRequestRecord,
    DeliveryReceiptIn,
    DeviceBindingUpdate,
    DeviceListResponse,
    DeviceMessageOut,
    DeviceOut,
    DispatchOut,
    ReceiptRecord,
)

router = APIRouter(prefix="/internal/v1/devices", tags=["capture-control"])

CAPTURE_REQUEST_TYPE = "CAPTURE_REQUEST"


def get_adb_runner(request: Request):
    """生产为 None（走真 adb）；测试注入假执行器，避免真去动本机 USB。"""
    return getattr(request.app.state, "adb_runner", None)


# ---------------------------------------------------------------- 设备与绑定


@router.get("", response_model=DeviceListResponse)
async def list_devices_endpoint(
    session: AsyncSession = Depends(get_session),
) -> DeviceListResponse:
    """设备列表：控制台据此选目标设备，并看到它绑了哪个 App、走哪条通道。"""
    devices = (await session.scalars(select(Device).order_by(Device.name))).all()
    return DeviceListResponse(devices=[DeviceOut.of(d) for d in devices])


@router.patch("/{device_id}/binding", response_model=DeviceOut)
async def update_device_binding_endpoint(
    device_id: uuid.UUID,
    req: DeviceBindingUpdate,
    session: AsyncSession = Depends(get_session),
) -> DeviceOut:
    """绑定设备到某个眼镜 App 运行时与控制通道。

    做成接口而不是让人手改数据库，是因为联调时会频繁在探针与正式 App、adb 与 inbox
    之间来回切；改一次要重启后端的话没人会用。
    """
    device = await _load_device(session, device_id)
    if req.runtime_package is not None:
        device.runtime_package = req.runtime_package or None
    if req.control_transport is not None:
        device.control_transport = req.control_transport
    await record_audit(
        session,
        actor="user:owner",
        action="device_binding_update",
        target=f"device:{device.id}",
        detail={
            "runtime_package": device.runtime_package,
            "control_transport": device.control_transport,
        },
    )
    await session.commit()
    return DeviceOut.of(device)


# ---------------------------------------------------------------- 下发采集请求


@router.post("/{device_id}/capture-requests", response_model=CaptureRequestOut)
async def create_capture_request_endpoint(
    device_id: uuid.UUID,
    req: CaptureRequestCreate,
    session: AsyncSession = Depends(get_session),
    hub: DeviceHub = Depends(get_hub),
    adb_runner=Depends(get_adb_runner),
) -> CaptureRequestOut:
    settings = get_settings()
    device = await _load_device(session, device_id)
    transport = resolve_transport(device, req.transport)

    payload = req.to_payload()
    # 记进载荷，历史列表才能显示这条请求当初走的哪条通道（事后排障的第一个问题）
    payload["transport"] = transport

    ttl = req.ttl_seconds or settings.device_message_ttl_seconds
    msg = DeviceMessage(
        household_id=device.household_id,
        target_device_id=device.id,
        message_type=CAPTURE_REQUEST_TYPE,
        payload_schema_ref=CAPTURE_REQUEST_SCHEMA_REF,
        payload=payload,
        priority="NORMAL",
        allow_text=True,
        # 采集请求不需要设备播报，TTS 只会在采集瞬间制造噪音
        allow_tts=False,
        expires_at=utcnow() + timedelta(seconds=ttl),
    )
    session.add(msg)
    await session.flush()
    await record_audit(
        session,
        actor="user:owner",
        action="capture_request_create",
        target=f"device_message:{msg.id}",
        detail={
            "device_id": str(device.id),
            "action": req.action,
            "transport": transport,
            "runtime_package": device.runtime_package,
            "reason": req.reason,
        },
    )
    # 先落库再分发：分发过程中进程挂掉时，宁可留下一条没送出的请求，也不要设备已经
    # 拍了照而云端没有任何记录——审计要能覆盖每一次真实采集。
    await session.commit()

    envelope = DeviceMessageOut.of(msg)
    connector = build_connector(transport, hub=hub, adb_runner=adb_runner)
    result = await connector.dispatch(
        device=device,
        command=CaptureCommand(
            action=req.action,
            interval_seconds=req.interval_seconds,
            duration_seconds=req.duration_seconds,
            reason=req.reason,
        ),
        message_id=msg.id,
        envelope=envelope.model_dump(mode="json"),
    )

    if result.delivered:
        _mark_sent(msg)
    if result.terminal_status is not None:
        # connector 已经能确定终局（adb 送达/失败、动作不支持）：以 connector 身份写回执。
        # actor 写 connector:<transport> 而不是 device:<id>，因为这不是设备的自述——
        # 审计里必须能看出「这条 EXECUTED 是后端推断的，不是眼镜确认的」。
        await _apply_receipt(
            session,
            msg,
            DeliveryReceiptIn(
                message_id=msg.id, status=result.terminal_status, detail=result.detail
            ),
        )
        await record_audit(
            session,
            actor=f"connector:{transport}",
            action="capture_request_dispatch",
            target=f"device_message:{msg.id}",
            detail={"status": result.terminal_status, "accepted": result.accepted},
        )
    await session.commit()

    return CaptureRequestOut(
        message=DeviceMessageOut.of(msg),
        dispatch=DispatchOut(
            transport=result.transport, accepted=result.accepted, detail=result.detail
        ),
        pushed_connections=result.pushed_connections,
    )


@router.get("/{device_id}/capture-requests", response_model=CaptureRequestListResponse)
async def list_capture_requests_endpoint(
    device_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> CaptureRequestListResponse:
    """近期采集请求与它们的回执（控制台轮询）。倒序：最新一条在最上面。"""
    await _load_device(session, device_id)
    messages = list(
        (
            await session.scalars(
                select(DeviceMessage)
                .where(
                    DeviceMessage.target_device_id == device_id,
                    DeviceMessage.message_type == CAPTURE_REQUEST_TYPE,
                )
                .order_by(DeviceMessage.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    if not messages:
        return CaptureRequestListResponse()

    receipts = (
        await session.scalars(
            select(DeviceDeliveryReceipt)
            .where(DeviceDeliveryReceipt.message_id.in_([m.id for m in messages]))
            .order_by(DeviceDeliveryReceipt.created_at.asc())
        )
    ).all()
    by_message: dict[uuid.UUID, list[DeviceDeliveryReceipt]] = {}
    for r in receipts:
        by_message.setdefault(r.message_id, []).append(r)

    return CaptureRequestListResponse(
        requests=[
            CaptureRequestRecord(
                message=DeviceMessageOut.of(m),
                action=(m.payload or {}).get("action", "UNKNOWN"),
                transport=(m.payload or {}).get("transport", "unknown"),
                receipts=[ReceiptRecord.of(r) for r in by_message.get(m.id, [])],
            )
            for m in messages
        ]
    )


__all__ = ["router", "CAPTURE_REQUEST_TYPE"]
