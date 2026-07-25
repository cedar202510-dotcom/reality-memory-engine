"""语音活动检测：把连续的麦克风流切成「一句话」。

为什么需要它：定时录 8 秒会录到大量没人说话的空白，而人说话的边界不在时钟上。
真机实测过——不说话的 8 秒片段，ASR 返回 `segments: []`，白跑一趟转写。

为什么是能量 VAD 而不是模型 VAD（Silero/WebRTC）：这一层要判断的是「有没有人在说话」，
不是「说了什么」。能量+静音时长在耳机麦克风这种近场、单说话人的场景下足够，而且不引入
原生依赖——这个采集器要能被扔到任意一台机器上跑。噪声环境下会误触发，代价是多传几段
空音频，由云端 ASR 兜底（空转写会被 `empty_transcript` 丢掉），不会产生错误的记忆。

状态机与 ffmpeg 刻意分开：`VadSegmenter` 只吃 PCM 帧、吐句子，不碰子进程，所以能在
没有麦克风的机器上完整单测。`MicStream` 才负责把 ffmpeg 的 stdout 变成帧。
"""
from __future__ import annotations

import array
import io
import math
import subprocess
import wave
from collections import deque
from dataclasses import dataclass, field
from typing import Iterator

DEFAULT_SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # s16le


@dataclass
class VadConfig:
    sample_rate: int = DEFAULT_SAMPLE_RATE
    frame_ms: int = 30
    # 连续多少帧超过阈值才算「开始说话」。1 帧就触发会被键盘敲击、桌子磕碰骗到。
    start_frames: int = 3
    # 说完多久算「这句结束」。太短会把句中停顿切成两句，太长会把两句粘成一句；
    # 800ms 大致是中文自然停顿的上界。
    end_silence_ms: int = 800
    # 触发前回补的音频。人耳判定「开始说话」时，第一个字往往已经出口了——
    # 不回补的话每句话都会缺头一个音节。
    pre_roll_ms: int = 300
    # 短于这个时长的片段直接丢弃：咳嗽、椅子响、鼠标点击都长这样
    min_speech_ms: int = 600
    # 单句上限，防止持续噪声把一整段录成一条巨大的证据
    max_segment_ms: int = 30000
    # 阈值 = max(本底噪声 × factor, absolute_floor)
    threshold_factor: float = 3.0
    absolute_floor: float = 0.012
    # 用前多少帧估本底噪声。耳机刚连上时链路会有一小段爆音，别把它算进本底。
    calibration_frames: int = 20


@dataclass
class Segment:
    """一句话。"""

    pcm: bytes
    sample_rate: int
    peak: float
    # 相对于流开始的偏移，单位秒。绝对时间由调用方在拿到片段时补（它才知道流何时开始）。
    offset_seconds: float
    duration_seconds: float
    reason: str = "silence"  # silence=正常收尾 / max_length=被上限截断 / flush=流结束

    def to_wav(self) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(BYTES_PER_SAMPLE)
            handle.setframerate(self.sample_rate)
            handle.writeframes(self.pcm)
        return buf.getvalue()


def frame_rms(frame: bytes) -> float:
    """一帧的均方根电平（0.0-1.0）。"""
    if len(frame) < BYTES_PER_SAMPLE:
        return 0.0
    samples = array.array("h")
    samples.frombytes(frame[: len(frame) - (len(frame) % BYTES_PER_SAMPLE)])
    if not samples:
        return 0.0
    total = sum(float(s) * float(s) for s in samples)
    return math.sqrt(total / len(samples)) / 32768.0


class VadSegmenter:
    """喂 PCM 帧，吐完整句子。纯状态机，无 IO。"""

    def __init__(self, config: VadConfig | None = None) -> None:
        self.config = config or VadConfig()
        self.frame_bytes = int(
            self.config.sample_rate * self.config.frame_ms / 1000 * BYTES_PER_SAMPLE
        )
        pre_roll_frames = max(1, self.config.pre_roll_ms // self.config.frame_ms)
        self._pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames)
        self._noise_samples: list[float] = []
        self._threshold = self.config.absolute_floor
        self._speaking = False
        self._above = 0
        self._below = 0
        self._buffer = bytearray()
        self._peak = 0.0
        self._frames_seen = 0
        self._segment_start_frame = 0

    # ---------------------------------------------------------------- 观测

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def calibrated(self) -> bool:
        return len(self._noise_samples) >= self.config.calibration_frames

    @property
    def speaking(self) -> bool:
        return self._speaking

    # ---------------------------------------------------------------- 主逻辑

    def push(self, frame: bytes) -> Segment | None:
        """喂一帧，返回刚刚说完的那句（如果有）。"""
        self._frames_seen += 1
        level = frame_rms(frame)

        if not self.calibrated:
            # 标定期只估本底噪声，不判语音：这段时间说的话会被吞掉，
            # 但它只有 0.6 秒，且发生在会话刚开始、用户还没开口的时候。
            self._noise_samples.append(level)
            if self.calibrated:
                floor = sorted(self._noise_samples)[len(self._noise_samples) // 2]
                self._threshold = max(
                    floor * self.config.threshold_factor, self.config.absolute_floor
                )
            self._pre_roll.append(frame)
            return None

        if not self._speaking:
            self._pre_roll.append(frame)
            if level >= self._threshold:
                self._above += 1
                if self._above >= self.config.start_frames:
                    self._start_segment()
            else:
                self._above = 0
            return None

        # 说话中
        self._buffer.extend(frame)
        self._peak = max(self._peak, level)
        if level >= self._threshold:
            self._below = 0
        else:
            self._below += 1

        if self._silence_ms() >= self.config.end_silence_ms:
            return self._finish("silence")
        if self._buffered_ms() >= self.config.max_segment_ms:
            return self._finish("max_length")
        return None

    def flush(self) -> Segment | None:
        """流结束时收尾。会话停止时不能把最后半句丢掉。"""
        if not self._speaking:
            return None
        return self._finish("flush")

    # ---------------------------------------------------------------- 内部

    def _start_segment(self) -> None:
        self._speaking = True
        self._below = 0
        self._peak = 0.0
        # pre-roll 回补：把触发之前的几帧也算进这句话
        self._buffer = bytearray(b"".join(self._pre_roll))
        self._segment_start_frame = self._frames_seen - len(self._pre_roll)
        self._pre_roll.clear()

    def _buffered_ms(self) -> float:
        frames = len(self._buffer) / max(1, self.frame_bytes)
        return frames * self.config.frame_ms

    def _silence_ms(self) -> float:
        return self._below * self.config.frame_ms

    def _finish(self, reason: str) -> Segment | None:
        pcm = bytes(self._buffer)
        peak = self._peak
        start_frame = self._segment_start_frame
        self._speaking = False
        self._above = 0
        self._below = 0
        self._buffer = bytearray()
        self._peak = 0.0
        self._pre_roll.clear()

        duration_ms = len(pcm) / max(1, self.frame_bytes) * self.config.frame_ms
        if duration_ms < self.config.min_speech_ms:
            # 太短：咳嗽、鼠标点击、椅子响。丢掉且不上报——把这些传上去只会污染记忆。
            return None
        return Segment(
            pcm=pcm,
            sample_rate=self.config.sample_rate,
            peak=peak,
            offset_seconds=start_frame * self.config.frame_ms / 1000,
            duration_seconds=duration_ms / 1000,
            reason=reason,
        )


# ---------------------------------------------------------------- 麦克风流


@dataclass
class MicStream:
    """把 ffmpeg 的 stdout 变成定长 PCM 帧。

    用长驻子进程而不是每次录一段起一个 ffmpeg：耳机的 SCO 链路建立要几百毫秒，
    每句话都重建一次会把每句的开头吃掉。
    """

    device_index: int
    sample_rate: int = DEFAULT_SAMPLE_RATE
    frame_bytes: int = 960
    ffmpeg_binary: str = "ffmpeg"
    _proc: subprocess.Popen | None = field(default=None, init=False, repr=False)

    def argv(self) -> list[str]:
        return [
            self.ffmpeg_binary,
            "-hide_banner",
            "-loglevel", "error",
            "-f", "avfoundation",
            "-i", f":{self.device_index}",
            "-ac", "1",
            "-ar", str(self.sample_rate),
            "-f", "s16le",
            "-",
        ]

    def __enter__(self) -> "MicStream":
        self._proc = subprocess.Popen(
            self.argv(), stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    def frames(self) -> Iterator[bytes]:
        """阻塞地产出定长帧，直到流结束或被 close()。"""
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("MicStream 未启动（用 with 语句）")
        stdout = self._proc.stdout
        while True:
            chunk = stdout.read(self.frame_bytes)
            if not chunk or len(chunk) < self.frame_bytes:
                return
            yield chunk

    def stderr_text(self) -> str:
        if self._proc is None or self._proc.stderr is None:
            return ""
        try:
            return (self._proc.stderr.read() or b"").decode(errors="replace")
        except (OSError, ValueError):
            return ""


__all__ = [
    "MicStream",
    "Segment",
    "VadConfig",
    "VadSegmenter",
    "frame_rms",
]
