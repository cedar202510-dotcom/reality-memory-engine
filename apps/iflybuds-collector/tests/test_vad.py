"""VAD 状态机：把连续音频切成「一句话」。

全部喂合成 PCM，不碰麦克风。这层的失败模式很具体：切太碎（句中停顿被当成句尾）、
切太粗（两句粘一起）、把咳嗽当成话、把第一个字吃掉。
"""
from __future__ import annotations

import array
import wave

import pytest

from collector.vad import Segment, VadConfig, VadSegmenter, frame_rms

SAMPLE_RATE = 16000


def pcm_frame(amplitude: int, samples: int = 480) -> bytes:
    """一帧恒定幅度的 PCM。正负交替，避免直流分量把 RMS 算歪。"""
    data = array.array("h", [amplitude if i % 2 == 0 else -amplitude for i in range(samples)])
    return data.tobytes()


SILENCE = pcm_frame(30)      # 本底噪声
SPEECH = pcm_frame(6000)     # 说话


def _config(**kw) -> VadConfig:
    base = dict(
        sample_rate=SAMPLE_RATE,
        frame_ms=30,
        start_frames=2,
        end_silence_ms=150,      # 5 帧
        pre_roll_ms=60,          # 2 帧
        min_speech_ms=150,
        max_segment_ms=600,
        calibration_frames=5,
    )
    base.update(kw)
    return VadConfig(**base)


def feed(segmenter: VadSegmenter, frame: bytes, count: int) -> list[Segment]:
    out = []
    for _ in range(count):
        segment = segmenter.push(frame)
        if segment is not None:
            out.append(segment)
    return out


def calibrate(segmenter: VadSegmenter) -> None:
    feed(segmenter, SILENCE, segmenter.config.calibration_frames)
    assert segmenter.calibrated


# ---------------------------------------------------------------- 电平


def test_frame_rms_distinguishes_silence_from_speech():
    assert frame_rms(SILENCE) < 0.01
    assert frame_rms(SPEECH) > 0.1
    assert frame_rms(b"") == 0.0


def test_threshold_is_calibrated_from_the_noise_floor():
    """阈值跟着环境走：安静房间和咖啡馆的本底差一个数量级，写死会在一头失效。"""
    segmenter = VadSegmenter(_config())
    assert not segmenter.calibrated
    calibrate(segmenter)
    assert segmenter.threshold >= segmenter.config.absolute_floor


# ---------------------------------------------------------------- 断句


def test_a_sentence_is_emitted_after_the_trailing_silence():
    segmenter = VadSegmenter(_config())
    calibrate(segmenter)

    assert feed(segmenter, SPEECH, 10) == []      # 说话中不吐东西
    assert segmenter.speaking is True
    out = feed(segmenter, SILENCE, 6)             # 静音超过 150ms → 收尾
    assert len(out) == 1
    segment = out[0]
    assert segment.reason == "silence"
    assert segment.duration_seconds > 0.3
    assert segment.peak > 0.1


def test_pre_roll_keeps_the_first_syllable():
    """触发时第一个字往往已经出口了，不回补的话每句都缺头。"""
    segmenter = VadSegmenter(_config(pre_roll_ms=150))  # 5 帧
    calibrate(segmenter)
    feed(segmenter, SPEECH, 5)
    out = feed(segmenter, SILENCE, 6)
    assert len(out) == 1
    # 5 帧语音 + 回补的 5 帧 ≈ 300ms，明显长于纯语音的 150ms
    assert out[0].duration_seconds > 0.25


def test_a_pause_inside_a_sentence_does_not_split_it():
    """中文句中停顿常有 100-200ms，短于 end_silence_ms 的静音不该断句。"""
    segmenter = VadSegmenter(_config(end_silence_ms=300))
    calibrate(segmenter)
    feed(segmenter, SPEECH, 6)
    assert feed(segmenter, SILENCE, 3) == []   # 90ms 停顿：不断
    feed(segmenter, SPEECH, 6)
    out = feed(segmenter, SILENCE, 12)         # 360ms：断
    assert len(out) == 1
    assert out[0].duration_seconds > 0.5       # 两段语音在同一句里


def test_short_blips_are_dropped():
    """咳嗽、鼠标点击、椅子响都长这样。传上去只会污染记忆。"""
    segmenter = VadSegmenter(_config(min_speech_ms=300))
    calibrate(segmenter)
    feed(segmenter, SPEECH, 3)                 # 90ms
    assert feed(segmenter, SILENCE, 6) == []
    assert segmenter.speaking is False         # 状态确实回到了静默


def test_long_noise_is_cut_at_the_limit_and_says_so():
    """持续噪声不能录成一条巨大的证据；被截断的片段要标出来。"""
    segmenter = VadSegmenter(_config(max_segment_ms=300))
    calibrate(segmenter)
    out = feed(segmenter, SPEECH, 30)
    assert out, "超过上限必须强制收尾"
    assert out[0].reason == "max_length"


def test_flush_keeps_the_last_half_sentence():
    """会话停止时不能把正在说的半句丢掉。"""
    segmenter = VadSegmenter(_config())
    calibrate(segmenter)
    feed(segmenter, SPEECH, 10)
    segment = segmenter.flush()
    assert segment is not None
    assert segment.reason == "flush"
    assert segmenter.flush() is None  # 收过一次就没有了


def test_silence_alone_never_produces_a_segment():
    segmenter = VadSegmenter(_config())
    calibrate(segmenter)
    assert feed(segmenter, SILENCE, 100) == []


# ---------------------------------------------------------------- 输出格式


def test_segment_wav_is_readable_and_has_the_right_shape():
    segmenter = VadSegmenter(_config())
    calibrate(segmenter)
    feed(segmenter, SPEECH, 10)
    segment = segmenter.flush()
    assert segment is not None

    import io

    with wave.open(io.BytesIO(segment.to_wav()), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == SAMPLE_RATE
        assert handle.getnframes() > 0


def test_mic_stream_argv_targets_the_resolved_device():
    """录音命令必须指向解析出来的那个设备索引，且输出裸 PCM 供逐帧判定。"""
    from collector.vad import MicStream

    argv = MicStream(device_index=3, sample_rate=SAMPLE_RATE).argv()
    assert ":3" in argv
    assert "s16le" in argv
    assert argv[-1] == "-"
