"""语音主动播报：信号 → 打扰预算 → 措辞 → 耳机消息。

这条链路上最容易出的两类错都不是「功能不work」，而是：
  1. 该闭嘴的时候说话（安静时段、频次超限、置信度不够、同一条信号说两遍）
  2. 该说的时候没说（LLM 挂了就静默吞掉）
所以下面的用例大半在测抑制，而不是在测投递。
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.llm.fake import FakeLLMClient
from app.memory.seed import get_default_household_id
from app.models import Device, DeviceMessage, Entity, MemorySignal, utcnow
from app.voice_delivery import (
    deliver_pending_signals,
    in_quiet_hours,
    parse_quiet_hours,
)


@pytest.fixture(autouse=True)
def _enable_voice(monkeypatch):
    """默认关闭是有意的，测试里显式打开，并把预算调成好推理的值。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_delivery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "voice_quiet_hours", "", raising=False)
    monkeypatch.setattr(settings, "voice_max_per_hour", 3, raising=False)
    monkeypatch.setattr(settings, "voice_min_confidence", 0.6, raising=False)
    yield


async def _earbuds(session) -> Device:
    household_id = await get_default_household_id(session)
    device = Device(
        household_id=household_id,
        kind="earbuds",
        name="IFLYBUDS Air 2",
        runtime_package="iflybuds-host-collector/0.1.0",
        control_transport="inbox",
    )
    session.add(device)
    await session.flush()
    return device


async def _signal(session, *, signal_type="LOW_CONSUMABLE", confidence=0.9, payload=None):
    household_id = await get_default_household_id(session)
    entity = Entity(household_id=household_id, canonical_name="牛奶", type="consumable")
    session.add(entity)
    await session.flush()
    signal = MemorySignal(
        household_id=household_id,
        signal_type=signal_type,
        entity_id=entity.id,
        payload={"entity_name": "牛奶", **(payload or {"level": "LOW"})},
        confidence=confidence,
        status="PENDING",
        cooldown_key=f"{signal_type}:{entity.id}",
        expires_at=utcnow() + timedelta(hours=12),
    )
    session.add(signal)
    await session.flush()
    return signal


# ---------------------------------------------------------------- 安静时段


def test_quiet_hours_parsing_survives_garbage():
    assert parse_quiet_hours("22:00-08:00") == (time(22, 0), time(8, 0))
    # 配错了当没配，而不是让 worker 每轮崩一次
    assert parse_quiet_hours("晚上别说话") is None
    assert parse_quiet_hours("") is None


def test_quiet_window_crossing_midnight():
    """22:00-08:00 跨午夜是常态，不是边界情况。"""
    window = parse_quiet_hours("22:00-08:00")
    at = lambda h: datetime(2026, 7, 25, h, 30, tzinfo=timezone.utc)  # noqa: E731
    assert in_quiet_hours(at(23), window) is True
    assert in_quiet_hours(at(3), window) is True
    assert in_quiet_hours(at(7), window) is True
    assert in_quiet_hours(at(9), window) is False
    assert in_quiet_hours(at(21), window) is False


def test_same_day_window():
    window = parse_quiet_hours("13:00-14:00")
    assert in_quiet_hours(datetime(2026, 7, 25, 13, 30), window) is True
    assert in_quiet_hours(datetime(2026, 7, 25, 15, 0), window) is False


# ---------------------------------------------------------------- 投递


@pytest.mark.asyncio
async def test_signal_becomes_a_spoken_reminder(db_session):
    await _earbuds(db_session)
    signal = await _signal(db_session)
    await db_session.commit()

    report = await deliver_pending_signals(db_session, llm=FakeLLMClient())

    assert report.counts == {"delivered": 1, "suppressed": 0}
    message = await db_session.scalar(
        select(DeviceMessage).where(DeviceMessage.message_type == "REMINDER_SIGNAL")
    )
    assert message is not None
    assert message.allow_tts is True  # 耳机只有声音这一条通道
    assert message.payload["signal_id"] == str(signal.id)
    assert message.payload["signal_type"] == "LOW_CONSUMABLE"
    assert message.payload["text"]
    # 回指信号：设备回执后能追到这句话是哪条事实推出来的
    assert message.payload["entity_id"] == str(signal.entity_id)


@pytest.mark.asyncio
async def test_signal_status_is_left_to_the_agent_channel(db_session):
    """语音播报不消费 signal.status——否则它会把 Agent 订阅通道的信号吃掉。"""
    await _earbuds(db_session)
    signal = await _signal(db_session)
    await db_session.commit()

    await deliver_pending_signals(db_session, llm=FakeLLMClient())
    await db_session.refresh(signal)
    assert signal.status == "PENDING"


@pytest.mark.asyncio
async def test_the_same_signal_is_never_spoken_twice(db_session):
    await _earbuds(db_session)
    await _signal(db_session)
    await db_session.commit()

    first = await deliver_pending_signals(db_session, llm=FakeLLMClient())
    second = await deliver_pending_signals(db_session, llm=FakeLLMClient())

    assert first.counts["delivered"] == 1
    assert second.counts["delivered"] == 0
    assert second.suppressed[0].reason == "already_spoken"


@pytest.mark.asyncio
async def test_low_confidence_signal_does_not_interrupt(db_session):
    await _earbuds(db_session)
    await _signal(db_session, confidence=0.3)
    await db_session.commit()

    report = await deliver_pending_signals(db_session, llm=FakeLLMClient())
    assert report.counts["delivered"] == 0
    assert report.suppressed[0].reason == "below_confidence"


@pytest.mark.asyncio
async def test_quiet_hours_defer_rather_than_consume(db_session, monkeypatch):
    """安静时段跳过但不消费：窗口结束后（只要没过期）照常播报。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_quiet_hours", "00:00-23:59", raising=False)
    await _earbuds(db_session)
    await _signal(db_session)
    await db_session.commit()

    quiet = await deliver_pending_signals(db_session, llm=FakeLLMClient())
    assert quiet.counts["delivered"] == 0
    assert quiet.suppressed[0].reason == "quiet_hours"

    monkeypatch.setattr(settings, "voice_quiet_hours", "", raising=False)
    later = await deliver_pending_signals(db_session, llm=FakeLLMClient())
    assert later.counts["delivered"] == 1


@pytest.mark.asyncio
async def test_hourly_budget_caps_interruptions(db_session, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "voice_max_per_hour", 2, raising=False)
    await _earbuds(db_session)
    for _ in range(4):
        await _signal(db_session)
    await db_session.commit()

    report = await deliver_pending_signals(db_session, llm=FakeLLMClient())
    assert report.counts["delivered"] == 2
    assert {o.reason for o in report.suppressed} == {"hourly_budget_exhausted"}


@pytest.mark.asyncio
async def test_expired_signals_are_never_spoken(db_session):
    """迟到的提醒不播——与下行通道对过期消息的处理是同一条原则。"""
    await _earbuds(db_session)
    signal = await _signal(db_session)
    signal.expires_at = utcnow() - timedelta(minutes=1)
    await db_session.commit()

    report = await deliver_pending_signals(db_session, llm=FakeLLMClient())
    assert report.counts == {"delivered": 0, "suppressed": 0}


@pytest.mark.asyncio
async def test_no_earbuds_means_no_message(db_session):
    await _signal(db_session)
    await db_session.commit()

    report = await deliver_pending_signals(db_session, llm=FakeLLMClient())
    assert report.suppressed[0].reason == "no_voice_device"


@pytest.mark.asyncio
async def test_disabled_by_default(db_session, monkeypatch):
    """主动打扰默认关闭：装了这个模块不等于同意它在耳边说话。"""
    monkeypatch.setattr(get_settings(), "voice_delivery_enabled", False, raising=False)
    await _earbuds(db_session)
    await _signal(db_session)
    await db_session.commit()

    report = await deliver_pending_signals(db_session, llm=FakeLLMClient())
    assert report.counts == {"delivered": 0, "suppressed": 0}
    assert await db_session.scalar(select(DeviceMessage.id)) is None


@pytest.mark.asyncio
async def test_wording_falls_back_to_template_when_llm_is_down(db_session):
    """LLM 挂了也必须把话说出去——已经判定该说的提醒不能被静默吞掉。"""
    await _earbuds(db_session)
    await _signal(db_session, payload={"level": "LOW"})
    await db_session.commit()

    report = await deliver_pending_signals(db_session, llm=None)

    assert report.counts["delivered"] == 1
    outcome = report.delivered[0]
    assert outcome.wording_source == "template"
    assert "牛奶" in outcome.text
