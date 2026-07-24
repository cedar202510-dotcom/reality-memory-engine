"""Transcriber 协议：语音转写（ASR）的统一抽象。

与 LLMClient / VisionEncoder 同风格：业务代码不直接碰模型/HTTP，只依赖此协议。
- transcribe：音频字节 → 分段转写列表；返回 None 表示未配置/不可用（调用方必须能降级）
"""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    """一段转写：起止秒 + 文本 + 可选说话人。"""

    start: float = Field(default=0.0, description="段起始秒")
    end: float = Field(default=0.0, description="段结束秒")
    text: str = Field(description="段文本")
    speaker: str | None = Field(default=None, description="说话人标识（可空）")


class Transcriber(Protocol):
    """语音转写协议。实现方保证：未配置/推理失败时返回 None，绝不抛出。"""

    async def transcribe(
        self, audio_bytes: bytes, *, media_kind: str
    ) -> list[TranscriptSegment] | None:
        """音频字节 → 分段转写列表；未配置或失败时返回 None。"""
        ...


class NullTranscriber:
    """恒返回 None 的转写器：asr_provider=none 或构造失败时的降级实现。"""

    async def transcribe(
        self, audio_bytes: bytes, *, media_kind: str
    ) -> list[TranscriptSegment] | None:
        return None
