"""测试夹具：全部替身，不碰麦克风、不碰扬声器、不碰网络。

这个采集器的价值在于「策略判断 + 回执语义 + 离线续传」，这三件事都不需要真实音频
硬件就能测。真机部分由 `python -m collector selftest` 覆盖，那是人肉验收，不是单测。
"""
from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from collector.client import IngestResult  # noqa: E402
from collector.config import Config  # noqa: E402


def make_wav(seconds: float = 1.0, sample_rate: int = 16000, amplitude: int = 8000) -> bytes:
    """一段可解析的真 WAV。测 peak_level / duration 时需要真实的头，不能拿随机字节糊弄。"""
    frames = int(seconds * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"".join(int(amplitude).to_bytes(2, "little", signed=True) for _ in range(frames)))
    return buf.getvalue()


class FakeBackend:
    """替身后端：记录上传与回执，可按需让上传失败。"""

    def __init__(self) -> None:
        self.uploads: list[tuple[dict, bytes]] = []
        self.receipts: list[tuple[str, str, dict]] = []
        self.inbox: list[dict] = []
        self.upload_error: Exception | None = None

    async def upload_envelope(self, *, envelope, media, filename, content_type):
        if self.upload_error is not None:
            raise self.upload_error
        self.uploads.append((envelope, media))
        return IngestResult(
            envelope_id=f"env-{len(self.uploads)}",
            evidence_item_ids=[f"ev-{len(self.uploads)}"],
            duplicate_evidence_ids=[],
            idempotent_replay=False,
        )

    async def post_receipt(self, *, device_id, message_id, status, detail):
        self.receipts.append((str(message_id), status, detail))
        return {"message_id": message_id, "status": status}

    async def fetch_inbox(self, device_id):
        messages, self.inbox = self.inbox, []
        return messages

    # --- 测试便利方法 ---

    def statuses(self, message_id: str | None = None) -> list[str]:
        return [s for mid, s, _ in self.receipts if message_id is None or mid == str(message_id)]

    def detail_of(self, status: str) -> dict:
        for _, s, detail in self.receipts:
            if s == status:
                return detail
        raise AssertionError(f"没有 {status} 回执，实际收到：{self.statuses()}")


class FakeRecorder:
    """记录被要求录多少秒，返回一段固定的 WAV。"""

    def __init__(self, wav: bytes | None = None) -> None:
        self.calls: list[float] = []
        self.wav = wav if wav is not None else make_wav()
        self.error: Exception | None = None

    def __call__(self, seconds: float) -> bytes:
        self.calls.append(seconds)
        if self.error is not None:
            raise self.error
        return self.wav


class FakeSpeaker:
    def __init__(self, voice: str = "Tingting") -> None:
        self.spoken: list[str] = []
        self.voice = voice
        self.error: Exception | None = None

    def __call__(self, text: str) -> str:
        if self.error is not None:
            raise self.error
        self.spoken.append(text)
        return self.voice


@pytest.fixture
def config(tmp_path) -> Config:
    cfg = Config()
    cfg.device_id = "11111111-2222-3333-4444-555555555555"
    cfg.spool_dir = str(tmp_path / "spool")
    cfg.input_device = "IFLYBUDS"
    cfg.output_device = "IFLYBUDS"
    cfg.allow_any_output = False
    cfg.max_duration_seconds = 60
    cfg.default_duration_seconds = 8
    cfg.poll_interval_seconds = 0.05
    return cfg


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def recorder() -> FakeRecorder:
    return FakeRecorder()


@pytest.fixture
def speaker() -> FakeSpeaker:
    return FakeSpeaker()
