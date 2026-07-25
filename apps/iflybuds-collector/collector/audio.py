"""宿主机音频进出口：从耳机麦克风录一段，或把一段声音送进耳机。

为什么是 ffmpeg 而不是 PortAudio/sounddevice：耳机接进来的是一个普通 CoreAudio 输入
设备，录音这件事本身没有难度，难的是**按名字**稳定选中它——耳机断连重连后设备索引会
变，而 avfoundation 的设备列表能拿到名字。ffmpeg 在开发机上通常已经有了，比让每个人
都去装一个带 PortAudio 的 wheel 更省事。

输出方向有个绕不开的限制：macOS 的 `afplay` 不能指定输出设备，`say` 可以（-a）。所以
播放前先核对系统默认输出设备是不是耳机，不是就拒绝——把一条私人提醒从笔记本外放出去，
比不播报严重得多。这是 04 号文档「策略在边缘执行」在输出方向上的对应物。

平台边界：v0 只实现 macOS（avfoundation + afplay + say）。Linux/Windows 会在解析设备
时明确报错，而不是假装能录。
"""
from __future__ import annotations

import array
import io
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

IS_MACOS = sys.platform == "darwin"

# ffmpeg 设备列表里的一行：[AVFoundation indev @ 0x...] [2] Jason Microphone
_DEVICE_LINE = re.compile(r"\[(\d+)\]\s+(.+?)\s*$")
_AUDIO_HEADER = "AVFoundation audio devices:"


class AudioError(RuntimeError):
    """音频子系统的可预期失败：设备找不到、没权限、外部命令不存在。

    与 bug 区分开：这些都要变成一条能直接看懂的回执原因，而不是堆栈。
    """


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str

    def __str__(self) -> str:  # 打印给人看
        return f"[{self.index}] {self.name}"


def _require_macos(what: str) -> None:
    if not IS_MACOS:
        raise AudioError(f"{what} 目前只实现了 macOS（当前 {platform.system()}）")


def _require_binary(binary: str) -> str:
    path = shutil.which(binary)
    if path is None:
        raise AudioError(f"找不到可执行文件：{binary}")
    return path


def list_input_devices(ffmpeg_binary: str = "ffmpeg") -> list[AudioDevice]:
    """列出 avfoundation 音频输入设备。

    ffmpeg 把设备列表写在 stderr，并且以非 0 退出（它确实没有输入文件可处理），
    所以这里不看 returncode，只解析文本。
    """
    _require_macos("音频设备枚举")
    binary = _require_binary(ffmpeg_binary)
    proc = subprocess.run(
        [binary, "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""],
        capture_output=True,
        text=True,
        timeout=20,
    )
    devices: list[AudioDevice] = []
    in_audio = False
    for line in proc.stderr.splitlines():
        if _AUDIO_HEADER in line:
            in_audio = True
            continue
        if not in_audio:
            continue
        # 音频段之后就是真正的错误行（"Error opening input"），到此为止
        match = _DEVICE_LINE.search(line)
        if match is None:
            if "devices:" in line:
                break
            continue
        devices.append(AudioDevice(index=int(match.group(1)), name=match.group(2)))
    return devices


def resolve_input_device(name_substring: str, ffmpeg_binary: str = "ffmpeg") -> AudioDevice:
    """按名字子串（不区分大小写）选中输入设备。

    匹配不到就报错并把候选列表带上——耳机没连上时这是最常见的失败，错误信息里直接
    给出「现在能看到哪些设备」比让人再去跑一次 devices 子命令有用。
    """
    devices = list_input_devices(ffmpeg_binary)
    if not devices:
        raise AudioError("系统里一个音频输入设备都没有；确认终端已获得麦克风权限")
    needle = (name_substring or "").lower()
    if not needle:
        raise AudioError("未配置 RME_EARBUDS_INPUT_DEVICE，不知道该录哪个设备")
    for device in devices:
        if needle in device.name.lower():
            return device
    listing = "、".join(d.name for d in devices)
    raise AudioError(f"没有名字包含「{name_substring}」的输入设备；当前可见：{listing}")


def default_output_device() -> str | None:
    """当前系统默认输出设备名。拿不到时返回 None（调用方据此降级为「未知」）。"""
    if not IS_MACOS:
        return None
    try:
        proc = subprocess.run(
            ["system_profiler", "SPAudioDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        payload = json.loads(proc.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    for group in payload.get("SPAudioDataType", []):
        for item in group.get("_items", []):
            if item.get("coreaudio_default_audio_output_device") == "spaudio_yes":
                return item.get("_name")
    return None


def record_wav(
    *,
    device_index: int,
    seconds: float,
    sample_rate: int,
    channels: int,
    ffmpeg_binary: str = "ffmpeg",
) -> bytes:
    """从指定输入设备录一段 WAV，返回文件字节。

    落临时文件再读回来，而不是从 stdout 收流：WAV 头里的长度字段要求可回写，管道模式下
    ffmpeg 会写一个长度为 -1 的头，某些解码器（含部分 ASR 前端）会读不出时长。
    """
    _require_macos("录音")
    binary = _require_binary(ffmpeg_binary)
    if seconds <= 0:
        raise AudioError(f"录音时长必须为正：{seconds}")
    with tempfile.TemporaryDirectory(prefix="rme-earbuds-") as tmp:
        out = Path(tmp) / "capture.wav"
        argv = [
            binary,
            "-hide_banner",
            "-loglevel", "error",
            "-f", "avfoundation",
            # avfoundation 的输入串是 "视频:音频"，前面留空 = 只录音
            "-i", f":{device_index}",
            "-t", f"{seconds:g}",
            "-ac", str(channels),
            "-ar", str(sample_rate),
            "-y", str(out),
        ]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=seconds + 30)
        if proc.returncode != 0 or not out.exists():
            raise AudioError(_explain_ffmpeg_failure(proc.stderr))
        data = out.read_bytes()
    if not data:
        raise AudioError("录音结果为空文件")
    return data


def _explain_ffmpeg_failure(stderr: str) -> str:
    """把 ffmpeg 的报错翻译成一句能直接贴进回执的中文。"""
    text = (stderr or "").strip()
    lowered = text.lower()
    if "operation not permitted" in lowered or "abort trap" in lowered:
        return "录音被系统拒绝：需要在「系统设置 → 隐私与安全性 → 麦克风」里授权当前终端"
    if "input/output error" in lowered:
        return "打开输入设备失败：耳机可能刚断连，或被别的 App 独占"
    return f"ffmpeg 录音失败：{text[-400:] or '无输出'}"


def wav_duration_seconds(data: bytes) -> float | None:
    """读 WAV 头拿真实时长。录到的秒数与请求的秒数不一致时要如实上报。"""
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            rate = handle.getframerate()
            return handle.getnframes() / rate if rate else None
    except (wave.Error, EOFError, ValueError):
        return None


def wav_peak_level(data: bytes) -> float | None:
    """16bit PCM 的峰值电平（0.0-1.0）。selftest 用它回答「到底录到声音没有」。

    只看峰值不看均值：验证链路通不通时，一次拍手就足以把峰值顶起来，而均值会被大段
    静音稀释成看不出区别的小数。
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            if handle.getsampwidth() != 2:
                return None
            frames = handle.readframes(handle.getnframes())
    except (wave.Error, EOFError, ValueError):
        return None
    if not frames:
        return 0.0
    samples = array.array("h")
    samples.frombytes(frames[: len(frames) - (len(frames) % 2)])
    if not samples:
        return 0.0
    return max(abs(s) for s in samples) / 32768.0


# ---------------------------------------------------------------- 输出方向


def play_wav_bytes(data: bytes) -> None:
    """把一段音频放给当前默认输出设备。

    afplay 不能选设备，所以调用方必须先用 default_output_device() 核对过。这个函数
    不做核对，是为了让「核对」这件事留在策略层，而不是散落在播放代码里。
    """
    _require_macos("音频播放")
    binary = _require_binary("afplay")
    with tempfile.TemporaryDirectory(prefix="rme-earbuds-play-") as tmp:
        path = Path(tmp) / "message.wav"
        path.write_bytes(data)
        proc = subprocess.run([binary, str(path)], capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise AudioError(f"afplay 播放失败：{(proc.stderr or '').strip()[-200:]}")


CJK = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
# `say -v '?'` 的一行：名字（可能带空格和括号）+ 语言标签 + # 示例句
_VOICE_LINE = re.compile(r"^(?P<name>.*?)\s+(?P<locale>[a-z]{2}_[A-Z]{2})\s*#")
# 中文音色偏好：Tingting 是各版本 macOS 上最稳定存在的一个，其余按系统给的顺序
_PREFERRED_ZH = ("Tingting", "Meijia", "Sinji")


def list_voices(timeout: float = 15.0) -> list[tuple[str, str]]:
    """(音色名, 语言标签) 列表。拿不到时返回空列表，调用方降级为系统默认音色。"""
    if not IS_MACOS:
        return []
    try:
        proc = subprocess.run(
            ["say", "-v", "?"], capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError):
        return []
    voices: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        match = _VOICE_LINE.match(line)
        if match:
            voices.append((match.group("name").strip(), match.group("locale")))
    return voices


def resolve_voice(text: str, configured: str = "") -> str:
    """按正文语言挑音色。返回空串表示用系统默认。

    这条不是锦上添花：系统默认音色通常是英文的，用它念中文提醒出来的是一串听不懂的
    音节——而 `say` 照样返回 0，回执照样是 SPOKEN。真机实测踩过，所以选音色这件事
    必须由采集器自己负责，不能指望系统默认是对的。
    """
    if configured:
        return configured
    if not CJK.search(text or ""):
        return ""  # 非中文正文：系统默认音色就是合适的
    voices = list_voices()
    by_name = {name: locale for name, locale in voices}
    for preferred in _PREFERRED_ZH:
        if preferred in by_name:
            return preferred
    for name, locale in voices:
        if locale.startswith("zh"):
            return name
    # 一个中文音色都没有：宁可用默认音色念出乱码，也不要静默丢掉提醒——
    # 但调用方会把「用了什么音色」写进回执，这样乱码是可追的。
    return ""


def speak(text: str, *, output_device: str = "", voice: str = "", timeout: float = 120.0) -> str:
    """本机 TTS 播报，返回实际使用的音色名（空串 = 系统默认）。

    `say -a` 能指定输出设备，是这条链路上唯一能显式把声音钉在耳机上的入口——所以文本
    提醒优先走 TTS 而不是先合成文件再 afplay。
    """
    _require_macos("语音播报")
    binary = _require_binary("say")
    if not text.strip():
        raise AudioError("播报内容为空")
    chosen = resolve_voice(text, voice)
    argv = [binary]
    if output_device:
        argv += ["-a", output_device]
    if chosen:
        argv += ["-v", chosen]
    # `--` 之后的一律当正文：提醒里出现 "-v" 之类的开头不该被解析成参数
    argv += ["--", text]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if "audio device" in stderr.lower():
            raise AudioError(f"指定的输出设备不可用：{output_device}（{stderr[-200:]}）")
        if "voice" in stderr.lower():
            raise AudioError(f"音色不可用：{chosen}（{stderr[-200:]}）")
        raise AudioError(f"say 播报失败：{stderr[-200:]}")
    return chosen


__all__ = [
    "AudioDevice",
    "AudioError",
    "default_output_device",
    "list_input_devices",
    "list_voices",
    "play_wav_bytes",
    "record_wav",
    "resolve_input_device",
    "resolve_voice",
    "speak",
    "wav_duration_seconds",
    "wav_peak_level",
]
