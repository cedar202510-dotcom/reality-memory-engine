"""ASR sidecar：faster-whisper 语音转写服务。

契约（与 memory-platform `app/asr/http_client.py` 对应）：
- POST /transcribe
  请求 {"audio_base64": "<base64>", "media_kind": "audio"}
  响应 {"segments": [{"start": 0.0, "end": 1.2, "text": "..."}, ...],
        "language": "zh", "duration_seconds": 1.2}
- 认证：ASR_API_KEY 非空时要求 `Authorization: Bearer <key>`，否则 401。
- GET /healthz：{"status": "ok", "model": ..., "model_loaded": true}

音频格式：接受常见容器格式（wav/mp3/m4a/ogg/flac 等，由 PyAV 按容器嗅探解码）；
不接受裸 PCM 流（无容器无法判定采样率/声道，请采集端封装为 WAV）。
"""
from __future__ import annotations

import base64
import binascii
import contextlib
import io
import os

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------- 配置（全部环境变量注入）

MODEL_SIZE = os.environ.get("ASR_MODEL_SIZE", "small")   # tiny/base/small/medium/large-v3
DEVICE = os.environ.get("ASR_DEVICE", "cpu")             # cpu | cuda
COMPUTE_TYPE = os.environ.get("ASR_COMPUTE_TYPE", "int8")
MODEL_DIR = os.environ.get("ASR_MODEL_DIR", "/models")   # 模型下载缓存目录（挂卷持久化）
API_KEY = os.environ.get("ASR_API_KEY", "")
BEAM_SIZE = int(os.environ.get("ASR_BEAM_SIZE", "5"))

_model = None  # faster_whisper.WhisperModel，lifespan 中加载


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    from faster_whisper import WhisperModel  # 延迟导入：无模型环境也能 import 本模块

    _model = WhisperModel(
        MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE, download_root=MODEL_DIR
    )
    yield
    _model = None


app = FastAPI(title="RME ASR Sidecar", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------- 契约


class TranscribeRequest(BaseModel):
    audio_base64: str = Field(min_length=1)
    media_kind: str = "audio"


class TranscriptSegmentOut(BaseModel):
    start: float
    end: float
    text: str
    speaker: str | None = None  # faster-whisper 不做说话人分离，占位字段


class TranscribeResponse(BaseModel):
    segments: list[TranscriptSegmentOut]
    language: str | None = None
    duration_seconds: float | None = None


async def _check_auth(authorization: str | None = Header(default=None)) -> None:
    """ASR_API_KEY 非空时要求 Bearer 认证；未配置则放行（本地/内网部署）。"""
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="缺少或错误的 Bearer token")


@app.post("/transcribe", response_model=TranscribeResponse, dependencies=[Depends(_check_auth)])
async def transcribe(req: TranscribeRequest) -> TranscribeResponse:
    if _model is None:
        raise HTTPException(status_code=503, detail="模型尚未加载完成")
    try:
        audio_bytes = base64.b64decode(req.audio_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=422, detail="audio_base64 不是合法的 base64") from exc
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="音频内容为空")

    # VAD 过滤：输入本就是 0.4–15s 的 VAD 片段，仍开启 Silero VAD 过滤静音/噪声段
    try:
        segments_iter, info = _model.transcribe(
            io.BytesIO(audio_bytes),
            beam_size=BEAM_SIZE,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        segments = [
            TranscriptSegmentOut(
                start=round(seg.start, 3), end=round(seg.end, 3), text=seg.text.strip()
            )
            for seg in segments_iter
            if seg.text.strip()
        ]
    except Exception as exc:  # noqa: BLE001 - 解码失败（不支持的格式/损坏字节）→ 422
        raise HTTPException(
            status_code=422,
            detail=f"音频解码/转写失败（支持 wav/mp3/m4a/ogg/flac 等容器格式）: {exc}",
        ) from exc

    return TranscribeResponse(
        segments=segments,
        language=info.language,
        duration_seconds=round(info.duration, 3) if info.duration is not None else None,
    )


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "model": MODEL_SIZE, "model_loaded": _model is not None}
