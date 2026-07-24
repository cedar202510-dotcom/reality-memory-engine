"""FakeTranscriber：不依赖真实 ASR 模型，注入式确定性转写。

模仿 FakeVisionEncoder 的注入式风格：
- segments_by_digest 注入"音频 sha256 → 分段转写 dict 列表"映射，测试可精确控制转写结果。
- 未命中时返回 default_segments（默认一段占位文本），保证流水线可跑通。
- enabled=False 时返回 None（模拟未配置，验证降级路径）。
"""
from __future__ import annotations

import hashlib

from .base import TranscriptSegment


class FakeTranscriber:
    """注入式假转写器。

    参数：
    - segments_by_digest：音频 sha256 hex → 分段 dict 列表（键由 audio_digest 生成）
    - default_segments：未命中注入映射时的兜底分段（默认一段占位文本）
    - enabled：False 时 transcribe 返回 None（模拟 ASR 不可用，验证降级路径）
    """

    def __init__(
        self,
        *,
        segments_by_digest: dict[str, list[dict]] | None = None,
        default_segments: list[dict] | None = None,
        enabled: bool = True,
    ) -> None:
        self.segments_by_digest = segments_by_digest or {}
        self.default_segments = (
            default_segments
            if default_segments is not None
            else [{"start": 0.0, "end": 1.0, "text": "一段中文语音"}]
        )
        self.enabled = enabled
        self.calls: list[dict[str, int | str]] = []  # 便于测试断言（记录调用次数/字节数）

    @staticmethod
    def audio_digest(data: bytes) -> str:
        """音频字节 → segments_by_digest 的查询键（sha256 hex）。测试用它构造注入映射。"""
        return hashlib.sha256(data).hexdigest()

    async def transcribe(
        self, audio_bytes: bytes, *, media_kind: str
    ) -> list[TranscriptSegment] | None:
        if not self.enabled:
            return None
        self.calls.append({"n_bytes": len(audio_bytes), "media_kind": media_kind})
        raw = self.segments_by_digest.get(self.audio_digest(audio_bytes), self.default_segments)
        if raw is None:
            return []
        return [TranscriptSegment.model_validate(seg) for seg in raw]
