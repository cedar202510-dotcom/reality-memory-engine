"""agent-gateway 装配：POST /v1/chat（会话式）+ 主动式提醒 + 健康检查。

本服务是记忆平台的第一个 AgentGrant 客户端：
只持受限 token 走 HTTP 契约，绝不直连平台数据库或 import 平台内部模块。
"""
from __future__ import annotations

import contextlib
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import get_settings
from .harness import run_turn
from .llm import FakeChatLLM, build_chat_llm
from .memory_client import MemoryClient
from .proactive import Suggestion, build_suggestions
from .sessions import SessionStore


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None


class ToolTraceOut(BaseModel):
    tool: str
    arguments: dict[str, Any]
    result: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    tool_trace: list[ToolTraceOut] = Field(default_factory=list)


class ProactiveResponse(BaseModel):
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    suppressed: int = 0


def create_app(
    *,
    fake_llm: FakeChatLLM | None = None,
    memory_client: MemoryClient | None = None,
) -> FastAPI:
    """fake_llm / memory_client 注入用于测试（不碰真实模型与平台）。"""
    settings = get_settings()

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

    @app.post("/v1/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        session = app.state.sessions.get_or_create(req.session_id)
        result = await run_turn(
            llm=app.state.llm,
            memory=app.state.memory,
            history=session.messages,
            user_message=req.message,
            max_tool_turns=settings.max_tool_turns,
        )
        return ChatResponse(
            session_id=session.id,
            reply=result.reply,
            tool_trace=[
                ToolTraceOut(tool=t.tool, arguments=t.arguments, result=t.result)
                for t in result.tool_trace
            ],
        )

    @app.post("/v1/proactive/check", response_model=ProactiveResponse)
    async def proactive_check() -> ProactiveResponse:
        """拉取待投递信号并措辞成建议。只建议：购买/发消息等现实动作永远不做。"""
        data = await app.state.memory.list_signals()
        if "error" in data:
            raise HTTPException(status_code=502, detail=data["error"])
        suggestions: list[Suggestion] = await build_suggestions(
            data.get("signals", []),
            llm=app.state.llm if settings.proactive_llm_wording else None,
        )
        return ProactiveResponse(
            suggestions=[s.__dict__ for s in suggestions],
            suppressed=int(data.get("suppressed", 0)),
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
