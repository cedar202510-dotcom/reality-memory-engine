"""语音 sidecar 端到端冒烟：真实 faster-whisper sidecar + memory-platform 音频流水线。

前置：
  1. Postgres 已启动（infra/docker-compose.yml）
  2. ASR sidecar 已启动（services/asr-sidecar/README.md；冒烟可用 ASR_MODEL_SIZE=tiny + ASR_API_KEY=dev-key）

流程：专用库 rme_asr_smoke → ingest 音频信封（合成的 2 秒 WAV）→ outbox worker（HTTPTranscriber
     走真实 sidecar）→ 打印 AudioAsset / 观察 / 候选 / 事件并断言 AudioAsset 落库。

用法：
    cd services/memory-platform
    .venv/bin/python scripts/audio_sidecar_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import struct
import subprocess
import sys
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ---- 必须在任何 app 模块导入前设置环境 ----
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://rme:rme@localhost:5432/rme_asr_smoke")
os.environ.setdefault("EVIDENCE_DIR", str(BASE_DIR / "data" / "evidence-asr-smoke"))
os.environ.setdefault("LLM_PROVIDER", "fake")
os.environ.setdefault("ASR_PROVIDER", "http")
os.environ.setdefault("ASR_BASE_URL", "http://localhost:8100")
os.environ.setdefault("ASR_API_KEY", "dev-key")

sys.path.insert(0, str(BASE_DIR))

import asyncpg  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, ensure_extensions  # noqa: E402
from app.main import create_app  # noqa: E402
from app.memory.seed import ensure_seed  # noqa: E402
from app.models import AtomicObservation, AudioAsset, MemoryCandidate, MemoryEvent  # noqa: E402
from app.workers import process_outbox_once  # noqa: E402

DB_NAME = "rme_asr_smoke"
ADMIN_URL = "postgresql://rme:rme@localhost:5432/rme"


def _make_tone_wav(path: Path, seconds: float = 2.0) -> bytes:
    """合成 2 秒语音样测试音（基频+谐波，4Hz 音节节律），16kHz 单声道 WAV。"""
    sr = 16000
    frames = []
    for i in range(int(sr * seconds)):
        t = i / sr
        env = 0.5 + 0.5 * math.sin(2 * math.pi * 4 * t)
        v = env * (
            0.6 * math.sin(2 * math.pi * 220 * t)
            + 0.3 * math.sin(2 * math.pi * 440 * t)
            + 0.1 * math.sin(2 * math.pi * 880 * t)
        )
        frames.append(struct.pack("<h", int(v * 32767 * 0.7)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(frames))
    return path.read_bytes()


async def _ensure_db() -> None:
    """重建专用库并跑迁移（每次冒烟都是干净状态，避免内容哈希去重命中上次证据）。"""
    conn = await asyncpg.connect(ADMIN_URL)
    await conn.execute(f"DROP DATABASE IF EXISTS {DB_NAME} WITH (FORCE)")
    await conn.execute(f"CREATE DATABASE {DB_NAME}")
    await conn.close()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BASE_DIR,
        env={**os.environ},
        check=True,
        capture_output=True,
    )


async def main() -> None:
    await _ensure_db()
    await ensure_extensions()
    async with SessionLocal() as session:
        await ensure_seed(session)

    # ASR_PROVIDER=http → app.state.asr 为 HTTPTranscriber（真实 sidecar）
    app = create_app(with_workers=False)
    wav = _make_tone_wav(Path(os.environ["EVIDENCE_DIR"]).parent / "smoke-tone.wav")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ts = datetime.now(timezone.utc).isoformat()
        envelope = {
            "occurred_at": ts,
            "observed_at": ts,
            "idempotency_key": f"asr-smoke:{uuid.uuid4()}",
            "trigger": "explicit",
            "modality": "audio",
        }
        resp = await client.post(
            "/internal/v1/envelopes",
            data={"envelope": json.dumps(envelope)},
            files=[("files", ("tone.wav", wav, "audio/wav"))],
        )
        resp.raise_for_status()
        print("ingest:", resp.json()["evidence_item_ids"])

    while await process_outbox_once(app.state.llm, asr=app.state.asr):
        pass

    async with SessionLocal() as session:
        asset = (await session.scalars(select(AudioAsset))).first()
        assert asset is not None, "AudioAsset 未落库：sidecar 是否在运行？契约是否匹配？"
        print(f"AudioAsset: transcript={asset.transcript!r}")
        print(f"  segments={asset.segments} duration={asset.duration_seconds}s")
        print(f"  embedding={'1024d' if asset.embedding is not None else None}")
        observations = (await session.scalars(select(AtomicObservation))).all()
        candidates = (await session.scalars(select(MemoryCandidate))).all()
        events = (await session.scalars(select(MemoryEvent))).all()
        print(f"  observations={len(observations)} candidates={len(candidates)} events={len(events)}")
        print("PASS: 音频信封 → sidecar 转写 → AudioAsset 全链路贯通")


if __name__ == "__main__":
    asyncio.run(main())
