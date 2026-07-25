"""设备下行通道（通信架构 §5）：DeviceMessage 投递 + DeliveryReceipt 回执。

三条路径共用同一张 `device_messages` 表和同一套过期/去重语义：

- `WS  /internal/v1/devices/{id}/stream`   长连，低延迟主路径；连上先冲积压再实时推
- `GET /internal/v1/devices/{id}/inbox`    轮询兜底（§5.3 的首版通道），离线期补投
- `POST /internal/v1/devices/{id}/receipts` 回执，按 (message_id, status) 幂等

投递语义是**至少一次**：长连推送成功不等于设备呈现成功，只有回执算数。设备必须
按 `message_id` 幂等处理重复消息——这正是 §7 要求的「眼镜直连与手机中继同时收到
也只产生一条最终投递状态」。

边界（§5.1）：下行只传结果和控制，不传记忆数据库本身。云端消息也不能绕过眼镜
本地策略远程强制打开相机或麦克风（§5.5）——本模块不提供任何媒体控制消息类型。

鉴权：沿用 `/internal/v1` 现状（本机/内网可信域，见 API-Reference §鉴权）。设备
token 绑定与「设备只能读发给自己的消息」属于通信 review 范围，尚未实现。
"""
from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import SessionLocal, get_session
from ..memory.events import record_audit
from ..models import Device, DeviceDeliveryReceipt, DeviceMessage, utcnow
from ..schemas import (
    TERMINAL_RECEIPT_STATUSES,
    DeliveryReceiptIn,
    DeliveryReceiptOut,
    DeviceInboxResponse,
    DeviceMessageCreateRequest,
    DeviceMessageCreateResponse,
    DeviceMessageOut,
)

router = APIRouter(prefix="/internal/v1/devices", tags=["downlink"])

# 关闭码：设备不存在（4000+ 为应用自定义区间，设备侧据此决定是否重连）
WS_CLOSE_UNKNOWN_DEVICE = 4404


class DeviceHub:
    """进程内设备连接注册表：device_id → 活跃 WebSocket 集合。

    单进程假设，与 agent-gateway 的进程内 session 是同一级别的 Phase 1 简化。多副本
    部署时换成 Redis pub/sub 或粘性路由即可，替换范围限于本类——路由层只依赖
    `publish()` 的返回值（送达连接数），不关心底层怎么广播。

    一台设备允许多条连接（重连瞬间的新旧连接重叠、眼镜直连 + 手机中继并存），
    因此 publish 是广播；重复送达由设备侧 message_id 幂等兜住。
    """

    def __init__(self) -> None:
        self._conns: dict[uuid.UUID, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def register(self, device_id: uuid.UUID, ws: WebSocket) -> None:
        async with self._lock:
            self._conns[device_id].add(ws)

    async def unregister(self, device_id: uuid.UUID, ws: WebSocket) -> None:
        async with self._lock:
            self._conns.get(device_id, set()).discard(ws)
            if not self._conns.get(device_id):
                self._conns.pop(device_id, None)

    async def online_connections(self, device_id: uuid.UUID) -> int:
        async with self._lock:
            return len(self._conns.get(device_id, set()))

    async def publish(self, device_id: uuid.UUID, envelope: dict) -> int:
        """向该设备所有活跃连接广播一条信封，返回成功送达的连接数。

        发送在锁外进行（避免慢连接阻塞注册/注销）；发送失败的连接就地摘除，
        由设备重连后走 inbox 补投，不在这里重试。
        """
        async with self._lock:
            targets = list(self._conns.get(device_id, set()))
        if not targets:
            return 0
        delivered = 0
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(envelope)
                delivered += 1
            except Exception:  # noqa: BLE001 — 连接已断/正在断，摘除即可
                dead.append(ws)
        for ws in dead:
            await self.unregister(device_id, ws)
        return delivered


def get_hub(request: Request) -> DeviceHub:
    return request.app.state.device_hub


async def _load_device(session: AsyncSession, device_id: uuid.UUID) -> Device:
    device = await session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


async def _expire_stale(session: AsyncSession, device_id: uuid.UUID) -> int:
    """懒惰过期：读取/投递前把到期未终态的消息标记 EXPIRED，绝不投递迟到提醒（§5.4）。"""
    stale = (
        await session.scalars(
            select(DeviceMessage).where(
                DeviceMessage.target_device_id == device_id,
                DeviceMessage.status.in_(("PENDING", "SENT", "RECEIVED")),
                DeviceMessage.expires_at <= utcnow(),
            )
        )
    ).all()
    now = utcnow()
    for msg in stale:
        msg.status = "EXPIRED"
        msg.closed_at = now
    return len(stale)


async def _pending_messages(
    session: AsyncSession, device_id: uuid.UUID, limit: int
) -> list[DeviceMessage]:
    """待投递队列：未终态且未过期，按创建时间正序（提醒的先后顺序有意义）。

    含 SENT/RECEIVED 是有意的——设备重连后应重新拿到尚未终结的消息，投递语义是
    至少一次；设备按 message_id 幂等去重。
    """
    return list(
        (
            await session.scalars(
                select(DeviceMessage)
                .where(
                    DeviceMessage.target_device_id == device_id,
                    DeviceMessage.status.in_(("PENDING", "SENT", "RECEIVED")),
                    DeviceMessage.expires_at > utcnow(),
                )
                .order_by(DeviceMessage.created_at.asc())
                .limit(limit)
            )
        ).all()
    )


def _mark_sent(msg: DeviceMessage) -> None:
    if msg.status == "PENDING":
        msg.status = "SENT"
    if msg.sent_at is None:
        msg.sent_at = utcnow()


# ---------------------------------------------------------------- 注入


@router.post("/{device_id}/messages", response_model=DeviceMessageCreateResponse)
async def create_device_message_endpoint(
    device_id: uuid.UUID,
    req: DeviceMessageCreateRequest,
    session: AsyncSession = Depends(get_session),
    hub: DeviceHub = Depends(get_hub),
) -> DeviceMessageCreateResponse:
    """手动注入一条下行消息（第一版触发源）。

    落库与推送是两件事：先提交，再尝试即时推送。设备离线时消息留在库里等 inbox
    或重连补投——所以推送失败不是错误，`pushed_connections=0` 是正常返回。
    """
    settings = get_settings()
    device = await _load_device(session, device_id)
    ttl = req.ttl_seconds or settings.device_message_ttl_seconds
    msg = DeviceMessage(
        household_id=device.household_id,
        target_device_id=device.id,
        message_type=req.message_type,
        payload_schema_ref=req.payload_schema_ref,
        payload=req.payload,
        priority=req.priority,
        allow_text=req.delivery_policy.allow_text,
        allow_tts=req.delivery_policy.allow_tts,
        expires_at=utcnow() + timedelta(seconds=ttl),
    )
    session.add(msg)
    await session.flush()
    await record_audit(
        session,
        actor="user:owner",
        action="device_message_create",
        target=f"device_message:{msg.id}",
        detail={
            "device_id": str(device.id),
            "message_type": msg.message_type,
            "allow_tts": msg.allow_tts,
            "ttl_seconds": ttl,
        },
    )
    await session.commit()

    envelope = DeviceMessageOut.of(msg)
    pushed = await hub.publish(device.id, envelope.model_dump(mode="json"))
    if pushed:
        _mark_sent(msg)
        await session.commit()
        envelope = DeviceMessageOut.of(msg)
    return DeviceMessageCreateResponse(message=envelope, pushed_connections=pushed)


# ---------------------------------------------------------------- 轮询兜底


@router.get("/{device_id}/inbox", response_model=DeviceInboxResponse)
async def device_inbox_endpoint(
    device_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> DeviceInboxResponse:
    """设备收件箱（§5.3 首版轮询通道，也是长连断开期的补投路径）。

    这里没有 cursor：待投递集合本身就由 `status` 收敛——设备回执 RECEIVED 之后
    消息不再出现在队列里，比游标更难用错。
    """
    settings = get_settings()
    await _load_device(session, device_id)
    expired = await _expire_stale(session, device_id)
    messages = await _pending_messages(session, device_id, settings.device_inbox_limit)
    for msg in messages:
        _mark_sent(msg)
    await session.commit()
    return DeviceInboxResponse(
        messages=[DeviceMessageOut.of(m) for m in messages], expired=expired
    )


# ---------------------------------------------------------------- 回执


async def _apply_receipt(
    session: AsyncSession, msg: DeviceMessage, receipt: DeliveryReceiptIn
) -> bool:
    """记录一条回执并推进消息状态，返回该 (message_id, status) 是否为重复上报。

    回执只说明设备投递结果，不代表用户接受了提醒内容，也不能修改记忆事实（§5.4）。
    """
    existing = await session.scalar(
        select(DeviceDeliveryReceipt).where(
            DeviceDeliveryReceipt.message_id == msg.id,
            DeviceDeliveryReceipt.status == receipt.status,
        )
    )
    duplicate = existing is not None
    if not duplicate:
        session.add(
            DeviceDeliveryReceipt(
                message_id=msg.id,
                status=receipt.status,
                detail=receipt.detail,
                device_reported_at=receipt.device_reported_at,
            )
        )

    now = utcnow()
    msg.last_receipt_status = receipt.status
    if receipt.status == "RECEIVED":
        if msg.received_at is None:
            msg.received_at = now
        if msg.status in ("PENDING", "SENT"):
            msg.status = "RECEIVED"
    elif receipt.status == "PRESENTED":
        msg.presented_at = msg.presented_at or now
        if msg.status in ("PENDING", "SENT"):
            msg.status = "RECEIVED"
    elif receipt.status == "SPOKEN":
        msg.spoken_at = msg.spoken_at or now
        if msg.status in ("PENDING", "SENT"):
            msg.status = "RECEIVED"
    elif receipt.status in TERMINAL_RECEIPT_STATUSES:
        # 终态只认第一条：眼镜直连与手机中继同时上报不产生两条终态（§7）
        if msg.status not in ("CLOSED", "EXPIRED"):
            msg.status = "EXPIRED" if receipt.status == "EXPIRED" else "CLOSED"
            msg.closed_at = now
    return duplicate


@router.post("/{device_id}/receipts", response_model=DeliveryReceiptOut)
async def device_receipt_endpoint(
    device_id: uuid.UUID,
    receipt: DeliveryReceiptIn,
    session: AsyncSession = Depends(get_session),
) -> DeliveryReceiptOut:
    await _load_device(session, device_id)
    msg = await session.get(DeviceMessage, receipt.message_id)
    if msg is None or msg.target_device_id != device_id:
        raise HTTPException(status_code=404, detail="消息不存在")
    duplicate = await _apply_receipt(session, msg, receipt)
    await record_audit(
        session,
        actor=f"device:{device_id}",
        action="device_message_receipt",
        target=f"device_message:{msg.id}",
        detail={"status": receipt.status, "duplicate": duplicate},
    )
    await session.commit()
    return DeliveryReceiptOut(
        message_id=msg.id,
        status=receipt.status,
        duplicate=duplicate,
        message_status=msg.status,
    )


# ---------------------------------------------------------------- 长连


@router.websocket("/{device_id}/stream")
async def device_stream_endpoint(websocket: WebSocket, device_id: uuid.UUID) -> None:
    """设备长连：连上先冲积压，之后由 hub 实时推送。

    上行帧（设备 → 云端）只接受两种，长连不承载证据上传：
      {"type": "ping"}                                        → {"type": "pong"}
      {"type": "receipt", "message_id": ..., "status": ...}   → {"type": "receipt_ack", ...}

    空闲超过 device_ws_idle_timeout_seconds 服务端主动断开，把重连责任交回设备——
    半开连接比断开更危险，它会让 publish 静默成功而设备什么也没收到。
    """
    settings = get_settings()
    hub: DeviceHub = websocket.app.state.device_hub

    async with SessionLocal() as session:
        device = await session.get(Device, device_id)
        if device is None:
            await websocket.close(code=WS_CLOSE_UNKNOWN_DEVICE, reason="设备不存在")
            return

    await websocket.accept()
    # 先注册再冲积压：注册与补投之间新到的消息会被 publish 直接推走，设备可能
    # 收到重复（补投一次 + 实时一次），这是有意的——宁可重复也不能丢，去重靠
    # message_id。反过来先补投再注册就会真丢消息。
    await hub.register(device_id, websocket)
    try:
        async with SessionLocal() as session:
            await _expire_stale(session, device_id)
            backlog = await _pending_messages(session, device_id, settings.device_inbox_limit)
            for msg in backlog:
                _mark_sent(msg)
            envelopes = [DeviceMessageOut.of(m).model_dump(mode="json") for m in backlog]
            await session.commit()
        for envelope in envelopes:
            await websocket.send_json(envelope)

        while True:
            try:
                frame = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=settings.device_ws_idle_timeout_seconds,
                )
            except asyncio.TimeoutError:
                await websocket.close(code=1000, reason="空闲超时")
                return
            await _handle_client_frame(websocket, device_id, frame)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unregister(device_id, websocket)


async def _handle_client_frame(websocket: WebSocket, device_id: uuid.UUID, frame: dict) -> None:
    kind = (frame or {}).get("type")
    if kind == "ping":
        await websocket.send_json({"type": "pong"})
        return
    if kind != "receipt":
        await websocket.send_json({"type": "error", "detail": f"未知帧类型：{kind}"})
        return

    try:
        receipt = DeliveryReceiptIn.model_validate(frame)
    except Exception as exc:  # noqa: BLE001 — 设备上报格式错误不应断连
        await websocket.send_json({"type": "error", "detail": f"回执格式错误：{exc}"})
        return

    async with SessionLocal() as session:
        msg = await session.get(DeviceMessage, receipt.message_id)
        if msg is None or msg.target_device_id != device_id:
            await websocket.send_json({"type": "error", "detail": "消息不存在"})
            return
        duplicate = await _apply_receipt(session, msg, receipt)
        await record_audit(
            session,
            actor=f"device:{device_id}",
            action="device_message_receipt",
            target=f"device_message:{msg.id}",
            detail={"status": receipt.status, "duplicate": duplicate, "via": "ws"},
        )
        await session.commit()
        message_status = msg.status
    await websocket.send_json(
        {
            "type": "receipt_ack",
            "message_id": str(receipt.message_id),
            "status": receipt.status,
            "duplicate": duplicate,
            "message_status": message_status,
        }
    )
