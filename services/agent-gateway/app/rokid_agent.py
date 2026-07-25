"""Rokid 三方智能体请求与 SSE 输出契约。

这里仅做平台协议适配，不承载记忆查询或 Agent 决策。业务仍由 harness 完成。
"""
from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RokidMessageRole(StrEnum):
    USER = "user"
    AGENT = "agent"


class RokidMessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"


class RokidMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: RokidMessageRole
    type: RokidMessageType
    text: str | None = None
    image_url: str | None = None


class RokidAgentRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    message_id: str = Field(min_length=1, max_length=256)
    agent_id: str = Field(min_length=1, max_length=256)
    message: list[RokidMessage] = Field(min_length=1)
    user_id: str | None = Field(default=None, max_length=256)
    metadata: dict[str, Any] | None = None

    def latest_user_text(self) -> str | None:
        for item in reversed(self.message):
            if item.role != RokidMessageRole.USER:
                continue
            if item.type == RokidMessageType.TEXT and item.text:
                value = item.text.strip()
                if value:
                    return value
        return None

    def session_id(self) -> str:
        """用平台的会话消息 ID 维持 Agent Gateway 短期上下文。"""
        return f"rokid:{self.agent_id}:{self.user_id or 'anonymous'}:{self.message_id}"


def sse_event(event: str, payload: dict[str, Any]) -> str:
    """按 SSE 标准编码单个事件；JSON 保留中文，方便联调日志阅读。"""
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


def answer_payload(
    request: RokidAgentRequest,
    *,
    answer_stream: str,
    is_finish: bool,
) -> dict[str, Any]:
    return {
        "role": "agent",
        "message_id": request.message_id,
        "agent_id": request.agent_id,
        "answer_stream": answer_stream,
        "is_finish": is_finish,
        "type": "answer",
    }
