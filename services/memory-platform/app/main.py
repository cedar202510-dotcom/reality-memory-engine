"""FastAPI 装配：模块化单体（gateway/perception/memory-core/query/privacy 共享 PG）。

启动：建扩展 → seed 默认家庭 → 启动后台 worker（outbox + TTL）。
"""
from __future__ import annotations

import contextlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .asr import build_transcriber
from .asr.base import Transcriber
from .asr.fake import FakeTranscriber
from .auth.router import router as grants_router
from .auth.seed import ensure_dev_agent_grant
from .capture_control import router as capture_control_router
from .config import get_settings
from .db import SessionLocal, ensure_extensions
from .downlink import DeviceHub
from .downlink import agent_router as agent_downlink_router
from .downlink import router as downlink_router
from .gateway import router as gateway_router
from .llm import build_llm_client
from .llm.base import LLMClient
from .llm.fake import FakeLLMClient
from .memory.seed import ensure_seed
from .privacy import router as privacy_router
from .query import router as query_router
from .signals import router as signals_router
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
    adb_runner=None,
) -> FastAPI:
    """fake_llm / fake_vision / fake_asr 注入后全程使用 Fake 实现（测试/冒烟无需 API key 与模型）。

    adb_runner 注入后，采集控制的 adb 通道不会真去调本机 adb——测试不该依赖插着的眼镜。
    """

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        await ensure_extensions()
        async with SessionLocal() as session:
            await ensure_seed(session)
            if get_settings().seed_dev_agent_grant:
                token = await ensure_dev_agent_grant(session)
                if token:
                    print(f"[dev] Agent grant token（仅本次打印）：{token}")  # noqa: T201
        stop = None
        tasks = []
        if with_workers:
            stop, tasks = start_workers(app.state.llm, vision=app.state.vision, asr=app.state.asr)
        yield
        if stop is not None:
            await stop_workers(stop, tasks)

    app = FastAPI(title="RME Memory Platform", version="0.1.0", lifespan=lifespan)
    cors_origins = [o.strip() for o in get_settings().cors_allow_origins.split(",") if o.strip()]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.state.llm: LLMClient = build_llm_client(fake_llm)
    app.state.vision: VisionEncoder = (
        fake_vision if fake_vision is not None else build_vision_encoder(get_settings())
    )
    app.state.asr: Transcriber = (
        fake_asr if fake_asr is not None else build_transcriber(get_settings())
    )
    # OCR 不挂在 app.state：识别器要加载权重，走 app/ocr 的进程内单例
    # （与 detector 同样的理由），worker 里按需取，不一路当参数传。
    # 设备长连注册表随 app 实例走（不是模块全局），测试里每个 create_app 互不串扰
    app.state.device_hub = DeviceHub()
    app.state.adb_runner = adb_runner
    app.include_router(gateway_router)
    app.include_router(query_router)
    app.include_router(privacy_router)
    app.include_router(grants_router)
    app.include_router(signals_router)
    app.include_router(downlink_router)
    app.include_router(agent_downlink_router)
    app.include_router(capture_control_router)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
