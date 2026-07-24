"""FastAPI 装配：模块化单体（gateway/perception/memory-core/query/privacy 共享 PG）。

启动：建扩展 → seed 默认家庭 → 启动后台 worker（outbox + TTL）。
"""
from __future__ import annotations

import contextlib

from fastapi import FastAPI

from .asr import build_transcriber
from .asr.base import Transcriber
from .asr.fake import FakeTranscriber
from .config import get_settings
from .db import SessionLocal, ensure_extensions
from .gateway import router as gateway_router
from .llm import build_llm_client
from .llm.base import LLMClient
from .llm.fake import FakeLLMClient
from .memory.seed import ensure_seed
from .privacy import router as privacy_router
from .query import router as query_router
from .vision import build_vision_encoder
from .vision.base import VisionEncoder
from .vision.fake import FakeVisionEncoder
from .workers import start_workers, stop_workers


def create_app(
    *,
    fake_llm: FakeLLMClient | None = None,
    fake_vision: FakeVisionEncoder | None = None,
    fake_asr: FakeTranscriber | None = None,
    with_workers: bool = True,
) -> FastAPI:
    """fake_llm / fake_vision / fake_asr 注入后全程使用 Fake 实现（测试/冒烟无需 API key 与模型）。"""

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        await ensure_extensions()
        async with SessionLocal() as session:
            await ensure_seed(session)
        stop = None
        tasks = []
        if with_workers:
            stop, tasks = start_workers(app.state.llm, vision=app.state.vision, asr=app.state.asr)
        yield
        if stop is not None:
            await stop_workers(stop, tasks)

    app = FastAPI(title="RME Memory Platform", version="0.1.0", lifespan=lifespan)
    app.state.llm: LLMClient = build_llm_client(fake_llm)
    app.state.vision: VisionEncoder = (
        fake_vision if fake_vision is not None else build_vision_encoder(get_settings())
    )
    app.state.asr: Transcriber = (
        fake_asr if fake_asr is not None else build_transcriber(get_settings())
    )
    app.include_router(gateway_router)
    app.include_router(query_router)
    app.include_router(privacy_router)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
