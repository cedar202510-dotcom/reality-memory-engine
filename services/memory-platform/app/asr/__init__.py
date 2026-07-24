"""语音转写器工厂：按 settings.asr_provider 构造，失败一律降级 NullTranscriber。

provider：
- none  → NullTranscriber（默认；语音流水线整体关闭，音频证据仅落盘+TTL）
- fake  → FakeTranscriber（演示/冒烟；测试一般直接注入实例）
- http  → HTTPTranscriber（ASR sidecar，如 faster-whisper；未配 base_url 时降级 none）
"""
from __future__ import annotations

from ..config import Settings
from .base import NullTranscriber, Transcriber, TranscriptSegment
from .fake import FakeTranscriber
from .http_client import HTTPTranscriber


def build_transcriber(settings: Settings) -> Transcriber:
    """按配置构造语音转写器；none 或构造失败时返回恒 None 的降级实现。"""
    provider = (settings.asr_provider or "none").lower()
    if provider == "fake":
        return FakeTranscriber()
    if provider == "http":
        if not settings.asr_base_url:
            return NullTranscriber()
        return HTTPTranscriber(
            base_url=settings.asr_base_url,
            api_key=settings.asr_api_key,
            timeout=settings.asr_timeout_seconds,
        )
    return NullTranscriber()


__all__ = [
    "FakeTranscriber",
    "HTTPTranscriber",
    "NullTranscriber",
    "Transcriber",
    "TranscriptSegment",
    "build_transcriber",
]
