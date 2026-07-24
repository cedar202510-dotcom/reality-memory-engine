"""把设备原始音频转换为 ASR 可识别的临时输入，不改写原始证据。"""
from __future__ import annotations

import io
import sys
import wave
from array import array
from typing import Any


def prepare_audio_for_asr(
    data: bytes,
    envelope_meta: dict[str, Any],
) -> tuple[bytes, str]:
    """将 RV101 多通道 PCM 转为单声道 WAV；其他格式原样返回。"""
    evidence = envelope_meta.get("evidence_item")
    if not isinstance(evidence, dict):
        return data, "audio"
    media = evidence.get("media")
    if not isinstance(media, dict):
        return data, "audio"
    if media.get("container") != "RAW_PCM" or media.get("codec") != "PCM_S16LE":
        return data, str(evidence.get("mime_type") or "audio")

    sample_rate = int(media.get("sample_rate_hz") or 0)
    channel_count = int(media.get("channel_count") or 0)
    if sample_rate <= 0 or channel_count <= 0 or len(data) % (2 * channel_count) != 0:
        return data, str(evidence.get("mime_type") or "audio")

    layout = media.get("channel_layout")
    if not isinstance(layout, list) or len(layout) != channel_count:
        layout = [f"CHANNEL_{index}" for index in range(channel_count)]
    selected = [index for index, name in enumerate(layout) if str(name).startswith("RAW_MIC_")]
    if not selected:
        selected = [layout.index("PROCESSED_0")] if "PROCESSED_0" in layout else list(range(channel_count))

    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    frames = len(samples) // channel_count
    mono = array("h")
    mono.extend(
        int(sum(samples[frame * channel_count + channel] for channel in selected) / len(selected))
        for frame in range(frames)
    )
    if sys.byteorder != "little":
        mono.byteswap()

    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(mono.tobytes())
    return output.getvalue(), "audio/wav"
