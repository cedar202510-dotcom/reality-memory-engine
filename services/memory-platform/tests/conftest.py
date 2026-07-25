"""pytest 配置：独立测试库 rme_test + FakeLLM，不依赖任何 API key。"""
from __future__ import annotations

import asyncio
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ---- 必须在任何 app 模块导入前设置环境 ----
os.environ["DATABASE_URL"] = "postgresql+asyncpg://rme:rme@localhost:5432/rme_test"
os.environ["EVIDENCE_DIR"] = tempfile.mkdtemp(prefix="rme-test-evidence-")
os.environ["LLM_PROVIDER"] = "fake"
os.environ["ADMIN_TOKEN"] = "test-admin-token"  # grants 管理端点（tests/test_agent_access.py）
# Settings 的 env_file 指向仓库里的 .env，测试进程会把开发机的真实配置一并继承。
# 检测器必须在这里按死成 none：.env 里是 local，于是测试会真的加载 OWLv2 权重，
# 而帧处理是多线程调它的——真机实测 torch 在线程池里并发前向会直接段错误，
# 整个 pytest 进程崩掉（不是失败，是 Fatal Python error）。
# 单测本来也不该依赖一个几百 MB 的检测模型：要测检测逻辑就注入 fake。
os.environ["DETECTOR_PROVIDER"] = "none"
# 同理：OCR 引擎也会加载权重。要测 OCR 逻辑就注入 FakeTextRecognizer。
os.environ["OCR_PROVIDER"] = "none"
# 同理：.env 里 VISION_PROVIDER=local 会让每个 create_app() 都去加载 CLIP 权重。
# 需要视觉的用例一律显式注入 FakeVisionEncoder，没有一个用例依赖真实 CLIP，
# 所以这里按死成 fake——否则整个套件的耗时被权重加载而不是被测试逻辑主导。
os.environ["VISION_PROVIDER"] = "fake"

import pytest
import pytest_asyncio
from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

TEST_DB = "rme_test"
ADMIN_URL = "postgresql://rme:rme@localhost:5432/rme"


def _make_image_bytes(color: tuple[int, int, int], text: str = "") -> bytes:
    img = Image.new("RGB", (64, 64), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(scope="session", autouse=True)
def _setup_test_database():
    """建测试库并跑 alembic 迁移（每个测试会话一次）。"""
    import asyncpg

    async def _recreate():
        conn = await asyncpg.connect(ADMIN_URL)
        await conn.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        await conn.execute(f"CREATE DATABASE {TEST_DB}")
        await conn.close()

    asyncio.run(_recreate())
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BASE_DIR,
        env={**os.environ},
        check=True,
        capture_output=True,
    )
    yield
    from app.db import engine

    asyncio.run(engine.dispose())


@pytest_asyncio.fixture
async def db_session():
    """每个测试一个干净的数据库状态。"""
    from app.db import SessionLocal, ensure_extensions
    from app.memory.seed import ensure_seed

    await ensure_extensions()
    async with SessionLocal() as session:
        await session.execute(
            __import__("sqlalchemy").text(
                "TRUNCATE households, actors, devices, source_envelopes, evidence_items,"
                " frame_assets, frame_regions, audio_assets, atomic_observations, entities,"
                " memory_candidates,"
                " memory_events, state_projections, deletion_requests, deletion_jobs,"
                " deletion_tombstones, audit_records, outbox_events, agent_grants,"
                " memory_signals, signal_subscriptions, device_messages,"
                " device_delivery_receipts CASCADE"
            )
        )
        await session.commit()
        await ensure_seed(session)
        yield session


@pytest.fixture
def make_image():
    return _make_image_bytes
