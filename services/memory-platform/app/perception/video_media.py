"""视频解复用层：把一段视频拆成流水线已经会处理的两种东西——一条音轨、若干张图。

这一层刻意不碰数据库、不调 LLM，只做 ffmpeg 的进出。理由是视频是整个系统里
唯一需要外部二进制的环节，把它隔离成纯函数后，「ffmpeg 没装 / 这个文件是坏的 /
这段视频没有音轨」这三种失败都能在一个地方判掉，上层 worker 只需要处理
「拿到了」和「没拿到」。

失败一律返回 None/空列表，不抛异常：worker 语义是「记审计、弃本条、继续」，
一段拍坏的视频不该让 outbox 反复重试到耗尽 attempts。
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# ASR 侧要的是单声道 16k：识别模型基本都在这个采样率上训练，
# 也顺带把 iPhone 那种 48kHz 立体声 + 多余空间音频轨的体积压下来
# （实测 60s 的 1080p HEVC 是 71MB，抽出来的 wav 只有 ~1.9MB，
#  这很关键——HTTPTranscriber 是把整段 base64 塞进 JSON body 的）。
ASR_SAMPLE_RATE = 16000
ASR_MEDIA_KIND = "audio/wav"


@dataclass(frozen=True)
class VideoProbe:
    """ffprobe 的结果。duration 为 None 表示元数据里没写时长（流式录制常见）。"""

    duration_seconds: float | None
    has_audio: bool
    has_video: bool
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class Keyframe:
    """一张抽出来的关键帧。offset_seconds 是它在源视频时间轴上的位置。"""

    offset_seconds: float
    data: bytes
    index: int


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run(cmd: list[str], *, timeout: float) -> subprocess.CompletedProcess[bytes] | None:
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def probe_video(path: str | Path, *, timeout: float = 30.0) -> VideoProbe | None:
    """读容器元数据。返回 None = 文件压根不是 ffprobe 认得的媒体。"""
    if not ffmpeg_available():
        return None
    proc = _run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-show_entries", "stream=codec_type,width,height",
            "-of", "json",
            str(path),
        ],
        timeout=timeout,
    )
    if proc is None or proc.returncode != 0:
        return None
    try:
        info = json.loads(proc.stdout or b"{}")
    except (ValueError, TypeError):
        return None

    streams = info.get("streams") or []
    # iPhone 的 .MOV 里有多条 audio 流（立体声 AAC + 4 声道空间音频）和一堆
    # data 流，只需要知道「有没有」，选哪条交给 ffmpeg 的 -map 0:a:0。
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    duration_raw = (info.get("format") or {}).get("duration")
    try:
        duration = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration = None
    first_video = video_streams[0] if video_streams else {}
    return VideoProbe(
        duration_seconds=duration,
        has_audio=has_audio,
        has_video=bool(video_streams),
        width=first_video.get("width"),
        height=first_video.get("height"),
    )


def extract_audio_track(
    path: str | Path,
    *,
    sample_rate: int = ASR_SAMPLE_RATE,
    max_seconds: float = 0.0,
    timeout: float = 300.0,
) -> bytes | None:
    """抽音轨成单声道 WAV 字节。没有音轨（纯画面视频）返回 None。

    走 stdout 管道而不是临时文件：调用方拿到的就是要 base64 给 ASR 的那份字节，
    少一次落盘也少一个要清理的路径。
    """
    if not ffmpeg_available():
        return None
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if max_seconds > 0:
        cmd += ["-t", f"{max_seconds:.3f}"]
    cmd += [
        "-i", str(path),
        "-vn",                       # 丢掉画面
        "-map", "0:a:0",             # 只取第一条音轨（iPhone 的空间音频轨对 ASR 无用）
        "-ac", "1",
        "-ar", str(sample_rate),
        "-c:a", "pcm_s16le",
        "-f", "wav",
        "pipe:1",
    ]
    proc = _run(cmd, timeout=timeout)
    if proc is None or proc.returncode != 0 or not proc.stdout:
        return None
    # 一个只有 44 字节 RIFF 头的 wav 是「有轨但全空」，对 ASR 没有意义
    return proc.stdout if len(proc.stdout) > 44 else None


def extract_keyframes(
    path: str | Path,
    *,
    interval_seconds: float = 5.0,
    max_frames: int = 12,
    max_side: int = 1280,
    jpeg_quality: int = 3,
    duration_seconds: float | None = None,
    timeout: float = 300.0,
) -> list[Keyframe]:
    """按固定间隔采样关键帧。

    为什么是定间隔而不是 ffmpeg 的场景切变检测（`select='gt(scene,0.4)')`：
    场景检测的产出数量不可控——对着一个物体慢慢转一圈可能一帧都不触发，
    而走在路上能触发上百帧。喜好度里的「停留时长」通道需要的恰恰是
    均匀采样（每帧代表等长的一段时间），场景检测会把这个前提破坏掉。

    每帧单独调一次 ffmpeg 并用 `-ss` 精确定位。比一次 `fps=1/N` 出全部帧慢，
    但换来两件事：每帧的 offset_seconds 是确切已知的（不用靠序号反推），
    以及单帧解码失败不会带走整批。
    """
    if not ffmpeg_available() or max_frames <= 0 or interval_seconds <= 0:
        return []

    if duration_seconds is None:
        probe = probe_video(path)
        if probe is None or not probe.has_video:
            return []
        duration_seconds = probe.duration_seconds

    offsets = _plan_offsets(
        duration_seconds=duration_seconds,
        interval_seconds=interval_seconds,
        max_frames=max_frames,
    )

    frames: list[Keyframe] = []
    for idx, offset in enumerate(offsets):
        proc = _run(
            [
                "ffmpeg", "-v", "error",
                "-ss", f"{offset:.3f}",   # 放在 -i 前 = 快速定位
                "-i", str(path),
                "-frames:v", "1",
                "-vf", f"scale='min({max_side},iw)':-2",
                "-q:v", str(jpeg_quality),
                "-f", "image2",
                "-c:v", "mjpeg",
                "pipe:1",
            ],
            timeout=timeout,
        )
        if proc is None or proc.returncode != 0 or not proc.stdout:
            continue  # 单帧失败不影响其它帧（末尾越界、坏 GOP）
        frames.append(Keyframe(offset_seconds=offset, data=proc.stdout, index=idx))
    return frames


def _plan_offsets(
    *, duration_seconds: float | None, interval_seconds: float, max_frames: int
) -> list[float]:
    """算出要在哪些秒数上取帧。

    做法：把整段视频等分成 n 个桶，每桶取中点。n 由间隔决定，再被 max_frames 封顶——
    于是 60s 视频用 5s 间隔正好铺满 12 帧，10 分钟视频自动退化成 50s 间隔仍覆盖全片，
    而不是只覆盖开头 60 秒。

    取中点而不是取桶起点有两个原因：桶起点常常正好是切镜头的瞬间（运动模糊、黑场），
    更要紧的是最后一个采样点必须落在视频内部。早先的写法是按固定间隔外推再夹到
    `duration - 0.05`，结果最后一个点落在末帧之后——10fps 的 6 秒视频末帧在 5.9s，
    seek 到 5.95s 解不出任何东西，于是**每段视频都会静默少一张关键帧**。
    等分取中点让最后一个点天然落在 duration - step/2，永远有帧可解。
    """
    if duration_seconds is None or duration_seconds <= 0:
        return [i * interval_seconds for i in range(min(max_frames, 3))]

    n = math.ceil(duration_seconds / interval_seconds)
    n = max(1, min(n, max_frames))
    step = duration_seconds / n
    return [round((i + 0.5) * step, 3) for i in range(n)]
