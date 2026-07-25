"""唤醒词问答：对着耳机问一句，答案念回耳朵里。

唤醒词识别放在**转写之后**，不在设备上。原因很实际：真正的离线唤醒词要额外的模型和
原生依赖，而这个采集器的立身之本是「扔到任意一台机器上都能跑」。放在云端的代价是
唤醒词只在会话进行时才起作用（设备得先听见才有转写）——这与会话制的隐私默认恰好一致：
没开会话时它本来就不该听见任何东西。

与主动播报（app/voice_delivery/）的关键区别：**回答问题不走打扰预算**。安静时段、
每小时上限管的是「系统主动开口」，用户自己问的问题当然要答——半夜问一句却被静音策略
吞掉，那是 bug 不是克制。

转写被判定为问句时不进记忆抽取：「小忆我钥匙在哪」是一次查询，不是一条关于世界的陈述，
把它当成事实抽取会往记忆里塞进一堆用户其实是在提问的句子。
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..llm.base import LLMClient
from ..memory.events import record_audit
from ..models import Device, DeviceMessage, SourceEnvelope, utcnow

VOICE_ANSWER_SCHEMA_REF = "rme.voice-answer.v0"
REMINDER_TYPE = "REMINDER_SIGNAL"

# 「X 在哪」的口语说法。放在这里而不是交给 LLM：位置提问占了语音查询的绝大多数，
# 一条正则就能确定性地命中，没必要为它承担一次模型调用的延迟和不确定性。
_WHERE_PATTERNS = (
    re.compile(r"^(?P<target>.{1,20}?)\s*(?:在|放|搁)(?:在)?(?:哪儿|哪里|哪)"),
    re.compile(r"(?:我的?|那个)?\s*(?P<target>.{1,20}?)\s*(?:去|到)(?:哪儿|哪里|哪)了?"),
    re.compile(r"(?:找不到|忘了)\s*(?P<target>.{1,20}?)(?:放|在)?(?:哪儿|哪里|哪)?$"),
)
# 目标名前后常见的口水词，留着会让实体匹配对不上
_NOISE_PREFIX = re.compile(r"^(?:我的|我|那个|这个|请问|帮我看看|看看)\s*")
_NOISE_SUFFIX = re.compile(r"\s*(?:呢|啊|吗|了|呀)+$")


@dataclass
class VoiceAnswer:
    question: str
    answer_text: str
    intent: str
    target: str = ""


def wake_words() -> tuple[str, ...]:
    raw = get_settings().voice_wake_words or ""
    return tuple(w.strip() for w in raw.split(",") if w.strip())


def strip_wake_word(transcript: str, words: tuple[str, ...] | None = None) -> str | None:
    """命中唤醒词则返回去掉唤醒词后的问句，否则 None。

    只看开头一小段：唤醒词出现在句子中间（"我跟小忆说过这事"）是陈述不是呼叫，
    把它当成提问会把正常对话误判成查询。
    """
    text = (transcript or "").strip()
    if not text:
        return None
    for word in words if words is not None else wake_words():
        if not word:
            continue
        head = text[: len(word) + 2]
        index = head.find(word)
        if index == -1:
            continue
        rest = text[index + len(word) :]
        # 去掉唤醒词后紧跟的标点与语气词
        rest = re.sub(r"^[\s,，。、!！?？~～]+", "", rest)
        return rest.strip()
    return None


def parse_intent(question: str) -> tuple[str, str]:
    """(intent, target)。确定性解析，认不出来就老实说不认识。"""
    text = (question or "").strip()
    for pattern in _WHERE_PATTERNS:
        match = pattern.search(text)
        if match:
            target = _NOISE_SUFFIX.sub("", _NOISE_PREFIX.sub("", match.group("target"))).strip()
            if target:
                return "WHERE_IS", target
    return "UNKNOWN", ""


async def answer_question(
    session: AsyncSession,
    *,
    question: str,
    llm: LLMClient,
    household_id: uuid.UUID | None = None,
) -> VoiceAnswer:
    """回答一句语音提问。复用现成的找物链路，不新建一套检索。"""
    intent, target = parse_intent(question)
    if intent != "WHERE_IS":
        return VoiceAnswer(
            question=question,
            # 不猜、不圆场：答不上来就说答不上来，比编一个听起来合理的答案好
            answer_text="这个我还答不上来",
            intent=intent,
        )

    from ..query.where_is import where_is

    resp = await where_is(
        session, name=target, deep=False, llm=llm, vision=None, household_id=household_id
    )
    text = (resp.answer_text or "").strip() or f"我不知道{target}在哪"
    return VoiceAnswer(question=question, answer_text=text, intent=intent, target=target)


async def reply_to_device(
    session: AsyncSession,
    *,
    envelope: SourceEnvelope,
    answer: VoiceAnswer,
) -> DeviceMessage | None:
    """把答案作为一条 TTS 消息发回提问的那台设备。

    发回**信封来源的那台设备**而不是家庭里任意一台能说话的设备：谁问的谁听见，
    这是问答与主动播报的另一个区别。
    """
    if envelope.device_id is None:
        return None
    device = await session.get(Device, envelope.device_id)
    if device is None:
        return None

    settings = get_settings()
    message = DeviceMessage(
        household_id=device.household_id,
        target_device_id=device.id,
        message_type=REMINDER_TYPE,
        payload_schema_ref=VOICE_ANSWER_SCHEMA_REF,
        payload={
            "schema_ref": VOICE_ANSWER_SCHEMA_REF,
            "text": answer.answer_text,
            "in_reply_to_question": answer.question,
            "intent": answer.intent,
            "target": answer.target,
            "source_envelope_id": str(envelope.id),
        },
        priority="HIGH",  # 用户在等回答，排在主动提醒前面
        allow_text=True,
        allow_tts=True,
        # 答案比主动提醒更短命：人问完一句话，十几秒后才响的答案已经没用了
        expires_at=utcnow() + timedelta(seconds=settings.voice_answer_ttl_seconds),
    )
    session.add(message)
    await session.flush()
    await record_audit(
        session,
        actor="system/voice-qa",
        action="voice_answer_create",
        target=f"device_message:{message.id}",
        detail={
            "device_id": str(device.id),
            "intent": answer.intent,
            "target": answer.target,
            "answered": answer.intent != "UNKNOWN",
        },
    )
    return message


async def handle_transcript(
    session: AsyncSession,
    *,
    transcript: str,
    envelope: SourceEnvelope,
    llm: LLMClient,
) -> VoiceAnswer | None:
    """转写进来先过这里。命中唤醒词就回答并返回结果，否则返回 None（交给记忆抽取）。"""
    if not get_settings().voice_qa_enabled:
        return None
    question = strip_wake_word(transcript)
    if question is None:
        return None
    if not question:
        # 只喊了唤醒词没说别的
        answer = VoiceAnswer(question="", answer_text="我在", intent="WAKE_ONLY")
    else:
        answer = await answer_question(session, question=question, llm=llm)
    await reply_to_device(session, envelope=envelope, answer=answer)
    return answer


__all__ = [
    "VOICE_ANSWER_SCHEMA_REF",
    "VoiceAnswer",
    "answer_question",
    "handle_transcript",
    "parse_intent",
    "reply_to_device",
    "strip_wake_word",
    "wake_words",
]
