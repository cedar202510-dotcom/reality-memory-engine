"""把 Agent 结果转换成受约束的 RV101 呈现消息并交给记忆平台投递。

模型只负责回答或提醒措辞。本模块确定目标设备、呈现意图、交互类型、TTL 和字段长度，
不允许模型生成样式、图标名或系统/隐私消息。
"""
from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .memory_client import MemoryClient

TITLE_LIMIT = 42
BODY_LIMIT = 80
SPEECH_LIMIT = 100
REFERENCE_LIMIT = 128


@dataclass
class DeliveryResult:
    status: str
    target_device_id: str | None = None
    message_id: str | None = None
    transport: str | None = None
    error: str | None = None
    intent: str | None = None
    source_reference_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return f"{text[: limit - 1]}…"


def split_for_glasses(text: str) -> tuple[str, str | None]:
    """把自然语言结果稳定拆成眼镜标题和补充正文，不改变原始顺序。"""
    value = _compact(text) or "暂时没有可显示的回答"
    if len(value) <= TITLE_LIMIT:
        return value, None

    split_at = 0
    for index, char in enumerate(value[:TITLE_LIMIT], start=1):
        if char in "。！？!?；;":
            split_at = index
    if split_at < 8:
        split_at = TITLE_LIMIT

    title = value[:split_at]
    remainder = value[split_at:].lstrip()
    body = _truncate(remainder, BODY_LIMIT) if remainder else None
    return title, body


def _safe_id(value: str, *, fallback_prefix: str) -> str:
    compact = _compact(value)
    if compact:
        return compact[:REFERENCE_LIMIT]
    return f"{fallback_prefix}:{uuid.uuid4()}"


async def resolve_glasses_device(
    memory: MemoryClient,
    *,
    requested_device_id: str | None,
    configured_device_id: str | None,
) -> tuple[str | None, str | None]:
    """明确解析目标眼镜；多副眼镜时拒绝猜测。"""
    candidate = _compact(requested_device_id or configured_device_id or "")
    if candidate:
        try:
            return str(uuid.UUID(candidate)), None
        except ValueError:
            return None, "目标眼镜 device_id 不是合法 UUID"

    response = await memory.list_agent_devices()
    if "error" in response:
        return None, f"无法读取目标设备：{response['error']}"
    glasses = [
        device for device in response.get("devices", [])
        if str(device.get("kind", "")).lower() == "glasses"
    ]
    if not glasses:
        return None, "当前授权家庭没有已登记的眼镜"
    if len(glasses) > 1:
        return None, "当前家庭有多副眼镜，请明确提供 target device_id"
    return str(glasses[0]["device_id"]), None


async def _send(
    memory: MemoryClient,
    *,
    device_id: str,
    intent: str,
    text: str,
    source_kind: str,
    source_reference_id: str,
    correlation_id: str,
    interaction: str | dict[str, str],
    priority: str,
    allow_tts: bool,
    ttl_seconds: int,
) -> DeliveryResult:
    title, body = split_for_glasses(text)
    payload: dict[str, Any] = {
        "presentation": {
            "intent": intent,
            "title": title,
            "interaction": interaction,
        },
        "source": {
            "kind": source_kind,
            "reference_id": _safe_id(
                source_reference_id, fallback_prefix=source_kind.lower()
            ),
        },
        "correlation_id": _safe_id(correlation_id, fallback_prefix="delivery"),
    }
    if body:
        payload["presentation"]["body"] = body
    if allow_tts:
        payload["presentation"]["speech_text"] = _truncate(_compact(text), SPEECH_LIMIT)

    response = await memory.send_glasses_presentation(
        device_id=device_id,
        payload=payload,
        priority=priority,
        allow_tts=allow_tts,
        ttl_seconds=ttl_seconds,
    )
    if "error" in response:
        return DeliveryResult(
            status="FAILED",
            target_device_id=device_id,
            error=str(response["error"]),
            intent=intent,
            source_reference_id=source_reference_id,
        )

    message = response.get("message") or {}
    pushed = int(response.get("pushed_connections", 0) or 0)
    return DeliveryResult(
        status="QUEUED",
        target_device_id=device_id,
        message_id=str(message.get("message_id") or "") or None,
        transport="websocket" if pushed > 0 else "inbox",
        intent=intent,
        source_reference_id=source_reference_id,
    )


async def deliver_agent_reply(
    memory: MemoryClient,
    *,
    reply: str,
    session_id: str,
    requested_device_id: str | None = None,
    configured_device_id: str | None = None,
    allow_tts: bool = False,
    ttl_seconds: int = 90,
) -> DeliveryResult:
    device_id, error = await resolve_glasses_device(
        memory,
        requested_device_id=requested_device_id,
        configured_device_id=configured_device_id,
    )
    if error or device_id is None:
        return DeliveryResult(status="FAILED", error=error or "无法确定目标眼镜", intent="ANSWER")

    turn_id = str(uuid.uuid4())
    return await _send(
        memory,
        device_id=device_id,
        intent="ANSWER",
        text=reply,
        source_kind="AGENT_REPLY",
        source_reference_id=session_id,
        correlation_id=f"agent-turn:{turn_id}",
        interaction="NONE",
        priority="NORMAL",
        allow_tts=allow_tts,
        ttl_seconds=ttl_seconds,
    )


def _suggestion_presentation(suggestion: Any) -> tuple[str, str | dict[str, str], str]:
    signal_type = str(getattr(suggestion, "signal_type", ""))
    signal_id = _safe_id(str(getattr(suggestion, "signal_id", "")), fallback_prefix="signal")
    if signal_type == "LOW_CONSUMABLE":
        return (
            "CONSUMABLE",
            {
                "type": "ADD_TO_SHOPPING_LIST",
                "action_id": _safe_id(f"shopping:{signal_id}", fallback_prefix="shopping"),
            },
            "NORMAL",
        )
    if signal_type.startswith("TASK_"):
        return (
            "TASK",
            {
                "type": "COMPLETE_TASK",
                "action_id": _safe_id(f"task:{signal_id}", fallback_prefix="task"),
            },
            "NORMAL",
        )
    return (
        "REMINDER",
        {
            "type": "ACKNOWLEDGE",
            "action_id": _safe_id(f"ack:{signal_id}", fallback_prefix="ack"),
        },
        "HIGH",
    )


async def deliver_proactive_suggestions(
    memory: MemoryClient,
    *,
    suggestions: Iterable[Any],
    requested_device_id: str | None = None,
    configured_device_id: str | None = None,
    allow_tts: bool = False,
    ttl_seconds: int = 300,
) -> list[DeliveryResult]:
    items = list(suggestions)
    if not items:
        return []
    device_id, error = await resolve_glasses_device(
        memory,
        requested_device_id=requested_device_id,
        configured_device_id=configured_device_id,
    )
    if error or device_id is None:
        return [
            DeliveryResult(
                status="FAILED",
                error=error or "无法确定目标眼镜",
                intent=_suggestion_presentation(item)[0],
                source_reference_id=str(getattr(item, "signal_id", "")),
            )
            for item in items
        ]

    results: list[DeliveryResult] = []
    for suggestion in items:
        signal_id = str(getattr(suggestion, "signal_id", ""))
        intent, interaction, priority = _suggestion_presentation(suggestion)
        results.append(
            await _send(
                memory,
                device_id=device_id,
                intent=intent,
                text=str(getattr(suggestion, "text", "")),
                source_kind="MEMORY_SIGNAL",
                source_reference_id=signal_id,
                correlation_id=f"memory-signal:{signal_id}",
                interaction=interaction,
                priority=priority,
                allow_tts=allow_tts,
                ttl_seconds=ttl_seconds,
            )
        )
    return results


__all__ = [
    "DeliveryResult",
    "deliver_agent_reply",
    "deliver_proactive_suggestions",
    "resolve_glasses_device",
    "split_for_glasses",
]
