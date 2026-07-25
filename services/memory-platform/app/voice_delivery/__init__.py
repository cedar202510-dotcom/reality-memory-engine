"""信号 → 耳机里的一句话：主动播报的投递桥。

这是闭环里原先缺掉的一段。在此之前 `MemorySignal` 只能被 Agent 用
`GET /v1/memory/signals` 拉走，没有任何代码会把它变成设备消息——耳机里那句话只能靠
人手动 `POST /devices/{id}/messages`。

    投影重算 → signals/rules.py 产出信号 → 【本模块】打扰预算 + 措辞 → DeviceMessage
                                                                        → 耳机播报

三条刻意的边界：

1. **默认关闭。** `voice_delivery_enabled` 默认 False。主动在人耳边说话是产品决定，
   不该因为装了这个模块就自动发生。
2. **不改信号状态。** 本模块不把 signal 标成 DELIVERED——那是 Agent 订阅通道的语义，
   占用它会让语音播报把 Agent 的信号吃掉。语音侧的去重键是「有没有一条引用该
   signal_id 的设备消息」，两条消费路径互不干扰。
3. **规则决定说不说，LLM 只决定怎么说。** 见 wording.py 顶部。

打扰预算（安静时段、每小时上限、置信度下限）属于这一层而不是规则层：同一条信号
在白天值得说、凌晨三点不值得，这跟信号本身对不对没有关系。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..llm.base import LLMClient
from ..memory.events import record_audit
from ..models import Device, DeviceMessage, MemorySignal, utcnow
from ..schemas import DEVICE_MESSAGE_SCHEMA_REF
from .wording import compose

# 能把文字变成声音的设备类型。眼镜也有扬声器，但它的提醒呈现走 HUD + TTS 两条路，
# 语义与耳机不同（耳机只有声音这一条通道），先只接耳机，别过早统一。
VOICE_DEVICE_KINDS = ("earbuds",)

VOICE_SIGNAL_SCHEMA_REF = "rme.voice-reminder.v0"
REMINDER_TYPE = "REMINDER_SIGNAL"


@dataclass
class DeliveryOutcome:
    signal_id: uuid.UUID
    signal_type: str
    device_id: uuid.UUID | None
    delivered: bool
    reason: str
    text: str = ""
    wording_source: str = ""


@dataclass
class DeliveryReport:
    delivered: list[DeliveryOutcome] = field(default_factory=list)
    suppressed: list[DeliveryOutcome] = field(default_factory=list)

    def add(self, outcome: DeliveryOutcome) -> None:
        (self.delivered if outcome.delivered else self.suppressed).append(outcome)

    @property
    def counts(self) -> dict[str, int]:
        return {"delivered": len(self.delivered), "suppressed": len(self.suppressed)}


# ---------------------------------------------------------------- 打扰预算


def parse_quiet_hours(raw: str) -> tuple[time, time] | None:
    """"22:00-08:00" → (22:00, 08:00)。格式不对就当没配，而不是让 worker 崩掉。"""
    try:
        start_raw, end_raw = (raw or "").split("-", 1)
        start_h, start_m = (int(x) for x in start_raw.strip().split(":", 1))
        end_h, end_m = (int(x) for x in end_raw.strip().split(":", 1))
        return time(start_h, start_m), time(end_h, end_m)
    except (AttributeError, TypeError, ValueError):
        return None


def in_quiet_hours(now: datetime, window: tuple[time, time] | None) -> bool:
    """跨午夜的窗口（22:00-08:00）是常态，不是边界情况。"""
    if window is None:
        return False
    start, end = window
    current = now.time()
    if start <= end:
        return start <= current < end
    return current >= start or current < end


async def _spoken_in_last_hour(session: AsyncSession, device_id: uuid.UUID, now: datetime) -> int:
    """近一小时自动播报条数。

    只数带 signal_id 的消息：人工 `push` 是操作者的明确动作，不该挤占自动播报的预算，
    反过来自动播报也不该因为有人手动推过一条就闭嘴。
    """
    return int(
        await session.scalar(
            select(func.count(DeviceMessage.id)).where(
                DeviceMessage.target_device_id == device_id,
                DeviceMessage.message_type == REMINDER_TYPE,
                DeviceMessage.payload["signal_id"].astext.is_not(None),
                DeviceMessage.created_at >= now - timedelta(hours=1),
            )
        )
        or 0
    )


async def _already_spoken(session: AsyncSession, signal_id: uuid.UUID) -> bool:
    """这条信号是否已经被播报过。

    去重键放在设备消息上而不是 signal.status 上：signal 的状态归 Agent 订阅通道，
    两条消费路径要能各自独立地消费同一条信号。
    """
    hit = await session.scalar(
        select(DeviceMessage.id)
        .where(
            DeviceMessage.message_type == REMINDER_TYPE,
            DeviceMessage.payload["signal_id"].astext == str(signal_id),
        )
        .limit(1)
    )
    return hit is not None


# ---------------------------------------------------------------- 投递


async def _voice_devices(session: AsyncSession, household_id: uuid.UUID) -> list[Device]:
    return list(
        (
            await session.scalars(
                select(Device)
                .where(Device.household_id == household_id, Device.kind.in_(VOICE_DEVICE_KINDS))
                .order_by(Device.name)
            )
        ).all()
    )


async def _pending_signals(session: AsyncSession, now: datetime, limit: int) -> list[MemorySignal]:
    return list(
        (
            await session.scalars(
                select(MemorySignal)
                .where(MemorySignal.status == "PENDING", MemorySignal.expires_at > now)
                .order_by(MemorySignal.created_at.asc())
                .limit(limit)
            )
        ).all()
    )


async def deliver_pending_signals(
    session: AsyncSession,
    *,
    llm: LLMClient | None = None,
    now: datetime | None = None,
) -> DeliveryReport:
    """把够格的待投信号变成耳机上的播报消息。

    调用方负责提交事务边界之外的事（worker 每轮一个 session）。本函数内部会 commit：
    消息落库与信号消费必须一起生效，中途崩溃时宁可少播一条也不要出现「库里有消息、
    审计里没有」的悬空状态。
    """
    settings = get_settings()
    report = DeliveryReport()
    if not settings.voice_delivery_enabled:
        return report

    now = now or utcnow()
    quiet = parse_quiet_hours(settings.voice_quiet_hours)
    signals = await _pending_signals(session, now, settings.voice_delivery_batch)
    if not signals:
        return report

    # 安静时段整批跳过，但不消费信号：它们会在窗口结束后照常投递（只要还没过期）。
    # 过期就过期了——迟到的提醒不该播，这与下行通道对过期消息的处理是同一条原则。
    if in_quiet_hours(now.astimezone(), quiet):
        for signal in signals:
            report.add(
                DeliveryOutcome(
                    signal_id=signal.id,
                    signal_type=signal.signal_type,
                    device_id=None,
                    delivered=False,
                    reason="quiet_hours",
                )
            )
        return report

    budget: dict[uuid.UUID, int] = {}
    for signal in signals:
        outcome = await _deliver_one(
            session, signal=signal, llm=llm, now=now, settings=settings, budget=budget
        )
        report.add(outcome)

    await session.commit()
    return report


async def _deliver_one(
    session: AsyncSession,
    *,
    signal: MemorySignal,
    llm: LLMClient | None,
    now: datetime,
    settings: Any,
    budget: dict[uuid.UUID, int],
) -> DeliveryOutcome:
    def _no(reason: str, device_id: uuid.UUID | None = None) -> DeliveryOutcome:
        return DeliveryOutcome(
            signal_id=signal.id,
            signal_type=signal.signal_type,
            device_id=device_id,
            delivered=False,
            reason=reason,
        )

    if signal.confidence < settings.voice_min_confidence:
        return _no("below_confidence")
    if await _already_spoken(session, signal.id):
        return _no("already_spoken")

    devices = await _voice_devices(session, signal.household_id)
    if not devices:
        return _no("no_voice_device")
    device = devices[0]  # v0：一个家庭一副耳机。多设备要先定义「该对谁说」，不在本轮范围

    if device.id not in budget:
        budget[device.id] = await _spoken_in_last_hour(session, device.id, now)
    if budget[device.id] >= settings.voice_max_per_hour:
        return _no("hourly_budget_exhausted", device.id)

    text, source = await compose(
        llm=llm, signal_type=signal.signal_type, payload=signal.payload or {}
    )

    message = DeviceMessage(
        household_id=signal.household_id,
        target_device_id=device.id,
        message_type=REMINDER_TYPE,
        payload_schema_ref=VOICE_SIGNAL_SCHEMA_REF,
        payload={
            "schema_ref": VOICE_SIGNAL_SCHEMA_REF,
            "text": text,
            # 回指信号：设备回执之后能追到「这句话是哪条事实推出来的」
            "signal_id": str(signal.id),
            "signal_type": signal.signal_type,
            "entity_id": str(signal.entity_id) if signal.entity_id else None,
            "wording_source": source,
        },
        priority="NORMAL",
        allow_text=True,
        # 耳机只有声音这一条通道，不许 TTS 等于这条消息到了也没用
        allow_tts=True,
        # 语音提醒的存活期比默认更短：过了这段时间人早就换了场景，
        # 迟到的提醒比没有提醒更烦人。
        expires_at=now + timedelta(seconds=settings.voice_message_ttl_seconds),
    )
    session.add(message)
    await session.flush()
    budget[device.id] += 1

    await record_audit(
        session,
        actor="system/voice-delivery",
        action="voice_reminder_create",
        target=f"device_message:{message.id}",
        detail={
            "signal_id": str(signal.id),
            "signal_type": signal.signal_type,
            "device_id": str(device.id),
            "wording_source": source,
            "text_length": len(text),
        },
    )
    return DeliveryOutcome(
        signal_id=signal.id,
        signal_type=signal.signal_type,
        device_id=device.id,
        delivered=True,
        reason="delivered",
        text=text,
        wording_source=source,
    )


__all__ = [
    "DEVICE_MESSAGE_SCHEMA_REF",
    "DeliveryOutcome",
    "DeliveryReport",
    "VOICE_DEVICE_KINDS",
    "VOICE_SIGNAL_SCHEMA_REF",
    "deliver_pending_signals",
    "in_quiet_hours",
    "parse_quiet_hours",
]
