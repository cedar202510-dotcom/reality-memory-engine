"""agent-gateway 装配：POST /v1/chat（会话式）+ 主动式提醒 + 健康检查。

本服务是记忆平台的第一个 AgentGrant 客户端：
只持受限 token 走 HTTP 契约，绝不直连平台数据库或 import 平台内部模块。
"""
from __future__ import annotations

import contextlib
import secrets
import uuid
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from .config import Settings, get_settings
from .glasses_delivery import deliver_agent_reply, deliver_proactive_suggestions
from .harness import run_turn
from .llm import FakeChatLLM, build_chat_llm
from .memory_client import MemoryClient
from .proactive import Suggestion, build_suggestions
from .rokid_agent import (
    RokidAgentRequest,
    answer_payload,
    sse_event,
)
from .sessions import SessionStore


class GlassesDeliveryTarget(BaseModel):
    device_id: uuid.UUID | None = None
    allow_tts: bool | None = None


class ChatSource(StrEnum):
    API = "API"
    WEB_APP = "WEB_APP"
    ROKID_AIUI = "ROKID_AIUI"
    ROKID_THIRD_PARTY = "ROKID_THIRD_PARTY"
    RV101_NATIVE = "RV101_NATIVE"


class ChatResponseChannel(StrEnum):
    CALLER = "CALLER"
    AIUI_CONVERSATION = "AIUI_CONVERSATION"
    RV101_OVERLAY = "RV101_OVERLAY"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    source: ChatSource = ChatSource.API
    response_channel: ChatResponseChannel | None = None
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)
    device_id: uuid.UUID | None = None
    delivery: GlassesDeliveryTarget | None = None

    @model_validator(mode="after")
    def validate_response_route(self) -> "ChatRequest":
        if self.source in {
            ChatSource.ROKID_AIUI,
            ChatSource.ROKID_THIRD_PARTY,
        }:
            if self.response_channel is None:
                self.response_channel = ChatResponseChannel.AIUI_CONVERSATION
            elif self.response_channel != ChatResponseChannel.AIUI_CONVERSATION:
                raise ValueError("Rokid 对话只能通过 AIUI_CONVERSATION 返回")

        if self.delivery is not None:
            if self.response_channel is None:
                self.response_channel = ChatResponseChannel.RV101_OVERLAY
            elif self.response_channel != ChatResponseChannel.RV101_OVERLAY:
                raise ValueError("delivery 只能与 RV101_OVERLAY 回答通道一起使用")
            if (
                self.device_id is not None
                and self.delivery.device_id is not None
                and self.device_id != self.delivery.device_id
            ):
                raise ValueError("device_id 与 delivery.device_id 不能指向不同设备")

        return self


class ToolTraceOut(BaseModel):
    tool: str
    arguments: dict[str, Any]
    result: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    source: ChatSource
    response_channel: ChatResponseChannel
    correlation_id: str
    tool_trace: list[ToolTraceOut] = Field(default_factory=list)
    delivery: dict[str, Any] | None = None


class ProactiveRequest(BaseModel):
    delivery: GlassesDeliveryTarget | None = None


class ProactiveResponse(BaseModel):
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    suppressed: int = 0
    deliveries: list[dict[str, Any]] = Field(default_factory=list)


def create_app(
    *,
    fake_llm: FakeChatLLM | None = None,
    memory_client: MemoryClient | None = None,
    settings_override: Settings | None = None,
) -> FastAPI:
    """fake_llm / memory_client 注入用于测试（不碰真实模型与平台）。"""
    settings = settings_override or get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        with contextlib.suppress(Exception):
            await app.state.memory.aclose()

    app = FastAPI(title="RME Agent Gateway", version="0.1.0", lifespan=lifespan)
    app.state.llm = fake_llm if fake_llm is not None else build_chat_llm(settings)
    app.state.memory = memory_client or MemoryClient(
        base_url=settings.memory_base_url,
        token=settings.memory_agent_token,
        timeout=settings.memory_timeout_seconds,
    )
    app.state.sessions = SessionStore(
        ttl_minutes=settings.session_ttl_minutes, max_sessions=settings.max_sessions
    )

    async def run_chat(req: ChatRequest) -> ChatResponse:
        session = app.state.sessions.get_or_create(req.session_id)
        result = await run_turn(
            llm=app.state.llm,
            memory=app.state.memory,
            history=session.messages,
            user_message=req.message,
            max_tool_turns=settings.max_tool_turns,
        )
        response_channel = req.response_channel
        if response_channel is None:
            response_channel = (
                ChatResponseChannel.RV101_OVERLAY
                if settings.glasses_auto_delivery_enabled
                else ChatResponseChannel.CALLER
            )
        correlation_id = req.correlation_id or f"agent-turn:{uuid.uuid4()}"
        delivery_target = req.delivery
        should_deliver = response_channel == ChatResponseChannel.RV101_OVERLAY
        delivery = None
        if should_deliver:
            outcome = await deliver_agent_reply(
                app.state.memory,
                reply=result.reply,
                session_id=session.id,
                requested_device_id=(
                    str(delivery_target.device_id)
                    if delivery_target and delivery_target.device_id
                    else str(req.device_id) if req.device_id else None
                ),
                configured_device_id=settings.glasses_default_device_id,
                allow_tts=(
                    delivery_target.allow_tts
                    if delivery_target and delivery_target.allow_tts is not None
                    else settings.glasses_default_allow_tts
                ),
                ttl_seconds=settings.glasses_answer_ttl_seconds,
                correlation_id=correlation_id,
            )
            delivery = outcome.to_dict()
        return ChatResponse(
            session_id=session.id,
            reply=result.reply,
            source=req.source,
            response_channel=response_channel,
            correlation_id=correlation_id,
            tool_trace=[
                ToolTraceOut(tool=t.tool, arguments=t.arguments, result=t.result)
                for t in result.tool_trace
            ],
            delivery=delivery,
        )

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(
        req: ChatRequest,
        x_realgit_client_token: str | None = Header(default=None),
    ) -> ChatResponse:
        if (
            req.source == ChatSource.ROKID_AIUI
            and settings.aiui_client_token
            and (
                x_realgit_client_token is None
                or not secrets.compare_digest(
                    x_realgit_client_token, settings.aiui_client_token
                )
            )
        ):
            raise HTTPException(status_code=401, detail="AIUI 客户端认证失败")
        return await run_chat(req)

    @app.post("/v1/rokid/agent/sse")
    async def rokid_agent_sse(
        req: RokidAgentRequest,
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        """把灵珠三方智能体协议转换为 RealGit 内部对话契约。"""
        expected_auth = (
            f"Bearer {settings.rokid_agent_ak}" if settings.rokid_agent_ak else ""
        )
        if (
            not expected_auth
            or authorization is None
            or not secrets.compare_digest(authorization, expected_auth)
        ):
            raise HTTPException(status_code=401, detail="Rokid 三方智能体鉴权失败")
        if settings.rokid_agent_id and not secrets.compare_digest(
            req.agent_id, settings.rokid_agent_id
        ):
            raise HTTPException(status_code=403, detail="Rokid 智能体 ID 不匹配")

        message = req.latest_user_text()
        if message is None:
            raise HTTPException(
                status_code=422,
                detail="当前 RealGit 三方智能体只支持文字输入",
            )

        result = await run_chat(
            ChatRequest(
                message=message,
                session_id=req.session_id(),
                source=ChatSource.ROKID_THIRD_PARTY,
                response_channel=ChatResponseChannel.AIUI_CONVERSATION,
                correlation_id=f"rokid:{req.message_id}"[:128],
            )
        )
        chunks = [
            sse_event(
                "message",
                answer_payload(
                    req,
                    answer_stream=result.reply,
                    is_finish=False,
                ),
            ),
            sse_event(
                "done",
                answer_payload(
                    req,
                    answer_stream="",
                    is_finish=True,
                ),
            ),
        ]
        return StreamingResponse(
            iter(chunks),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/v1/proactive/check", response_model=ProactiveResponse)
    async def proactive_check(req: ProactiveRequest | None = None) -> ProactiveResponse:
        """拉取待投递信号并措辞成建议。只建议：购买/发消息等现实动作永远不做。"""
        data = await app.state.memory.list_signals()
        if "error" in data:
            raise HTTPException(status_code=502, detail=data["error"])
        suggestions: list[Suggestion] = await build_suggestions(
            data.get("signals", []),
            llm=app.state.llm if settings.proactive_llm_wording else None,
        )
        delivery_target = req.delivery if req else None
        should_deliver = (
            delivery_target is not None or settings.glasses_auto_delivery_enabled
        )
        deliveries = []
        if should_deliver:
            outcomes = await deliver_proactive_suggestions(
                app.state.memory,
                suggestions=suggestions,
                requested_device_id=(
                    str(delivery_target.device_id)
                    if delivery_target and delivery_target.device_id
                    else None
                ),
                configured_device_id=settings.glasses_default_device_id,
                allow_tts=(
                    delivery_target.allow_tts
                    if delivery_target and delivery_target.allow_tts is not None
                    else settings.glasses_default_allow_tts
                ),
                ttl_seconds=settings.glasses_reminder_ttl_seconds,
            )
            deliveries = [outcome.to_dict() for outcome in outcomes]
        return ProactiveResponse(
            suggestions=[s.__dict__ for s in suggestions],
            suppressed=int(data.get("suppressed", 0)),
            deliveries=deliveries,
        )

    @app.post("/v1/signals/{signal_id}/ack")
    async def ack_signal(signal_id: str) -> dict[str, Any]:
        """用户确认/忽略提醒后回执（gateway 不代替用户 ack）。"""
        return await app.state.memory.ack_signal(signal_id)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
