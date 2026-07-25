"""唤醒词问答：对着耳机问一句，答案念回耳朵里。

唤醒词识别在转写之后做，所以这里测的是「一段中文转写进来之后发生了什么」。
最容易错的两处都不在检索上：把普通对话误判成提问（唤醒词出现在句中），
以及把提问当成事实抽进记忆。
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.llm.fake import FakeLLMClient
from app.memory.seed import get_default_household_id
from app.models import Device, DeviceMessage, SourceEnvelope, utcnow
from app.voice_qa import (
    answer_question,
    handle_transcript,
    parse_intent,
    strip_wake_word,
)

WAKE = ("小忆", "小意")


# ---------------------------------------------------------------- 唤醒词


def test_wake_word_at_the_start_yields_the_question():
    assert strip_wake_word("小忆，我钥匙放哪了", WAKE) == "我钥匙放哪了"
    assert strip_wake_word("小忆 我的手机在哪", WAKE) == "我的手机在哪"


def test_common_asr_homophones_still_wake_it():
    """ASR 把「小忆」听成「小意」是常态，只认一个写法等于一半时间叫不醒。"""
    assert strip_wake_word("小意，我钥匙在哪", WAKE) == "我钥匙在哪"


def test_wake_word_in_the_middle_is_not_a_question():
    """「我跟小忆说过这事」是陈述。误判成提问会把正常对话变成查询。"""
    assert strip_wake_word("我昨天跟小忆说过这事了", WAKE) is None


def test_no_wake_word_returns_none():
    assert strip_wake_word("牛奶放冰箱了", WAKE) is None
    assert strip_wake_word("", WAKE) is None


def test_wake_word_only_returns_empty_question():
    """只喊了唤醒词：要能区分「没叫我」和「叫了但没说事」。"""
    assert strip_wake_word("小忆", WAKE) == ""
    assert strip_wake_word("小忆？", WAKE) == ""


# ---------------------------------------------------------------- 意图


@pytest.mark.parametrize(
    "question,target",
    [
        ("我钥匙放哪了", "钥匙"),
        ("我的手机在哪", "手机"),
        ("钱包在哪儿", "钱包"),
        ("那个充电器去哪了", "充电器"),
    ],
)
def test_where_is_questions_are_parsed_deterministically(question, target):
    """位置提问占语音查询的绝大多数，一条正则就能确定性命中，不必为它调模型。"""
    intent, parsed = parse_intent(question)
    assert intent == "WHERE_IS"
    assert parsed == target


def test_unrecognized_question_is_admitted_not_guessed():
    intent, target = parse_intent("今天天气怎么样")
    assert intent == "UNKNOWN"
    assert target == ""


@pytest.mark.asyncio
async def test_unknown_intent_answers_honestly(db_session):
    """答不上来就说答不上来，不编一个听起来合理的答案。"""
    answer = await answer_question(db_session, question="帮我订张机票", llm=FakeLLMClient())
    assert answer.intent == "UNKNOWN"
    assert "答不上来" in answer.answer_text


# ---------------------------------------------------------------- 回话


async def _envelope_from_earbuds(session) -> SourceEnvelope:
    household_id = await get_default_household_id(session)
    device = Device(household_id=household_id, kind="earbuds", name="IFLYBUDS Air 2")
    session.add(device)
    await session.flush()
    envelope = SourceEnvelope(
        device_id=device.id,
        source_session_id="earbuds-test",
        occurred_at=utcnow(),
        observed_at=utcnow(),
        idempotency_key="voice-qa-test-1",
        trigger="auto",
        modality="audio",
        meta={"device_kind": "IFLYBUDS_AIR2"},
    )
    session.add(envelope)
    await session.flush()
    return envelope


@pytest.mark.asyncio
async def test_answer_goes_back_to_the_device_that_asked(db_session):
    envelope = await _envelope_from_earbuds(db_session)

    answer = await handle_transcript(
        db_session, transcript="小忆，我钥匙在哪", envelope=envelope, llm=FakeLLMClient()
    )
    assert answer is not None
    assert answer.intent == "WHERE_IS"
    assert answer.target == "钥匙"

    message = await db_session.scalar(select(DeviceMessage))
    assert message is not None
    assert message.target_device_id == envelope.device_id  # 谁问的谁听见
    assert message.allow_tts is True
    assert message.priority == "HIGH"  # 用户在等回答，排在主动提醒前面
    assert message.payload["in_reply_to_question"] == "我钥匙在哪"


@pytest.mark.asyncio
async def test_a_plain_statement_is_not_answered(db_session):
    """没叫唤醒词的话不回话，交给记忆抽取。"""
    envelope = await _envelope_from_earbuds(db_session)
    answer = await handle_transcript(
        db_session, transcript="我把钥匙放玄关柜子上了", envelope=envelope, llm=FakeLLMClient()
    )
    assert answer is None
    assert await db_session.scalar(select(DeviceMessage.id)) is None


@pytest.mark.asyncio
async def test_wake_only_gets_an_acknowledgement(db_session):
    envelope = await _envelope_from_earbuds(db_session)
    answer = await handle_transcript(
        db_session, transcript="小忆", envelope=envelope, llm=FakeLLMClient()
    )
    assert answer is not None
    assert answer.intent == "WAKE_ONLY"
    message = await db_session.scalar(select(DeviceMessage))
    assert message.payload["text"] == "我在"


@pytest.mark.asyncio
async def test_answer_expires_fast(db_session):
    """问完十几秒才响的答案已经没用了，TTL 要比主动提醒短得多。"""
    envelope = await _envelope_from_earbuds(db_session)
    await handle_transcript(
        db_session, transcript="小忆，钱包在哪", envelope=envelope, llm=FakeLLMClient()
    )
    message = await db_session.scalar(select(DeviceMessage))
    ttl = (message.expires_at - message.created_at).total_seconds()
    assert ttl <= get_settings().voice_answer_ttl_seconds + 5


@pytest.mark.asyncio
async def test_disabled_switch_turns_the_whole_thing_off(db_session, monkeypatch):
    monkeypatch.setattr(get_settings(), "voice_qa_enabled", False, raising=False)
    envelope = await _envelope_from_earbuds(db_session)
    assert (
        await handle_transcript(
            db_session, transcript="小忆，钥匙在哪", envelope=envelope, llm=FakeLLMClient()
        )
        is None
    )
