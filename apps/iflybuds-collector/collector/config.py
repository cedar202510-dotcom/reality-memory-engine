"""宿主侧采集器配置。全部走环境变量（前缀 RME_EARBUDS_），无配置也能跑 selftest。

为什么不用 pydantic-settings：这个采集器要能被扔到任意一台连着耳机的机器上跑，
依赖越少越好。后端有 pydantic 是因为它本来就是 FastAPI 应用；这里只有 httpx 和
websockets 两个必需依赖，配置用标准库解析就够。
"""
from __future__ import annotations

import os
import platform
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# 设备身份三件套（设备接入架构 04 §2）。device_kind / device_adapter 会原样写进
# 每一条信封的 meta，后端据此统计与排障，但记忆平台内部不认识这两个值。
DEVICE_KIND = "IFLYBUDS_AIR2"
ADAPTER_VERSION = "0.1.0"
DEVICE_ADAPTER = f"iflybuds-host-collector/{ADAPTER_VERSION}"

DEFAULT_BASE_URL = "http://127.0.0.1:8765"
# 耳机麦克风走 HFP，链路本身就是 16k 单声道；再往上采样只是把带宽浪费在插值上，
# 而 16k 单声道恰好是 ASR sidecar 最省事的输入格式。
DEFAULT_SAMPLE_RATE = 16000


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"RME_EARBUDS_{name}", default).strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    return int(_env_float(name, float(default)))


@dataclass
class Config:
    """一次运行的全部可调项。"""

    api_base_url: str = field(default_factory=lambda: _env("API_BASE_URL", DEFAULT_BASE_URL))
    # 后端注册后下发。为空时信封仍会被接收（审计记为 device:unknown），便于第一次联调，
    # 但下行通道拿不到 device_id 就无从订阅，所以 run 子命令要求非空。
    device_id: str = field(default_factory=lambda: _env("DEVICE_ID"))

    # --- 音频输入 ---
    # 按名字子串匹配 ffmpeg avfoundation 的输入设备。写死索引是不行的：耳机断连重连后
    # 索引会变，而名字不会。
    input_device: str = field(default_factory=lambda: _env("INPUT_DEVICE", "IFLYBUDS"))
    sample_rate: int = field(default_factory=lambda: _env_int("SAMPLE_RATE", DEFAULT_SAMPLE_RATE))
    channels: int = field(default_factory=lambda: _env_int("CHANNELS", 1))
    default_duration_seconds: int = field(
        default_factory=lambda: _env_int("DEFAULT_DURATION_SECONDS", 8)
    )
    # 本地采集预算：云端请求超过这个时长就按上限截断并在回执里如实说明。
    # 这是设备侧策略，不是云端参数——云端不能通过调大 duration 让耳机一直录下去。
    max_duration_seconds: int = field(
        default_factory=lambda: _env_int("MAX_DURATION_SECONDS", 60)
    )

    # --- 音频输出（推送）---
    # 期望的播放设备名。macOS 的 afplay/say 默认走系统默认输出设备，我们无法替调用方
    # 切换它，所以只能在播放前核对：不是耳机就拒绝，而不是把提醒外放出去。
    output_device: str = field(default_factory=lambda: _env("OUTPUT_DEVICE", "IFLYBUDS"))
    # True = 默认输出设备不是耳机也照播（自己一个人在房间里调试时用）
    allow_any_output: bool = field(default_factory=lambda: _env_bool("ALLOW_ANY_OUTPUT", False))
    tts_voice: str = field(default_factory=lambda: _env("TTS_VOICE"))

    # --- 本地队列与通道 ---
    spool_dir: str = field(
        default_factory=lambda: _env("SPOOL_DIR", str(Path.home() / ".rme-earbuds-spool"))
    )
    # 长连断开后的轮询兜底间隔（后端 inbox 是 §5.3 的首版通道）
    poll_interval_seconds: float = field(
        default_factory=lambda: _env_float("POLL_INTERVAL_SECONDS", 5.0)
    )
    # 服务端 device_ws_idle_timeout_seconds 默认 90s，心跳必须显著小于它
    ping_interval_seconds: float = field(
        default_factory=lambda: _env_float("PING_INTERVAL_SECONDS", 30.0)
    )
    http_timeout_seconds: float = field(
        default_factory=lambda: _env_float("HTTP_TIMEOUT_SECONDS", 30.0)
    )
    ffmpeg_binary: str = field(default_factory=lambda: _env("FFMPEG_BINARY", "ffmpeg"))
    # 启动时就处于隐私暂停：这台机器上先不采集，直到操作者显式解除或云端下发 RESUME
    start_paused: bool = field(default_factory=lambda: _env_bool("START_PAUSED", False))
    # 周期采集的默认间隔（START_PERIODIC 未带 interval 时）
    default_interval_seconds: int = field(
        default_factory=lambda: _env_int("DEFAULT_INTERVAL_SECONDS", 60)
    )

    # --- 采集会话 ---
    # vad      = 监听麦克风，按「一句话」自动分段上传（默认）
    # periodic = 每 interval 秒录一段定长音频（老行为，会录到大量无人说话的空白）
    #
    # 会话制是刻意的：默认不监听，必须显式开启一段「记忆会话」（CLI 的 listen 或云端
    # 下发 START_PERIODIC），STOP 即停。默认常开听会让「有没有在录」变成一个用户看不见
    # 的状态，那是这类产品最不该有的东西。
    capture_mode: str = field(default_factory=lambda: _env("CAPTURE_MODE", "vad"))
    vad_silence_ms: int = field(default_factory=lambda: _env_int("VAD_SILENCE_MS", 800))
    vad_min_speech_ms: int = field(default_factory=lambda: _env_int("VAD_MIN_SPEECH_MS", 600))
    vad_max_segment_ms: int = field(default_factory=lambda: _env_int("VAD_MAX_SEGMENT_MS", 30000))
    vad_threshold_factor: float = field(
        default_factory=lambda: _env_float("VAD_THRESHOLD_FACTOR", 3.0)
    )

    def session_id(self) -> str:
        """一次进程生命周期 = 一个采集会话（04 §5.1）。"""
        return f"earbuds-{uuid.uuid4().hex[:12]}"

    @property
    def ws_url(self) -> str:
        base = self.api_base_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base.rstrip('/')}/internal/v1/devices/{self.device_id}/stream"

    def host_label(self) -> str:
        return f"{platform.node()}/{platform.system().lower()}"


__all__ = [
    "ADAPTER_VERSION",
    "Config",
    "DEVICE_ADAPTER",
    "DEVICE_KIND",
    "DEFAULT_SAMPLE_RATE",
]
