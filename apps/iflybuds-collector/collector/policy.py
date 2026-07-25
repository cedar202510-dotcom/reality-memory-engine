"""设备侧本地策略：耳机保留拒绝权。

通信架构 §8 的硬约束——云端下发的是**请求**不是命令，设备本地策略决定执不执行，拒绝
必须走 REJECTED 回执而不是静默丢弃。这个模块就是那条约束在宿主采集器上的实现：所有
「能不能做」的判断集中在这里，`downlink.py` 只负责把判断结果翻成回执。

判断结果分三种，对应三种回执：

- allowed=True                → 执行，成功后 EXECUTED
- allowed=False, policy 原因   → REJECTED（正常拒绝，控制台该显示原因而不是报错）
- 执行过程中抛异常              → FAILED（链路坏了，与「策略不让做」是两回事）

不做「就近替代」：请求拍照就如实回答耳机没有摄像头，绝不悄悄换成录一段音频——
adb connector 的 UNSUPPORTED_REASON 表也是同一条规矩。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 耳机运行时确实做不到的动作 → 一句能直接显示在控制台上的原因
UNSUPPORTED_ACTIONS: dict[str, str] = {
    "CAPTURE_PHOTO": "IFLYBUDS 是耳机，没有摄像头；要图像请改用眼镜设备",
}

SUPPORTED_ACTIONS = ("CAPTURE_AUDIO", "START_PERIODIC", "PAUSE", "RESUME", "STOP")


@dataclass(frozen=True)
class Decision:
    """一次本地策略判断。detail 会原样进回执，控制台据此区分拒绝与故障。"""

    allowed: bool
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, **detail: Any) -> "Decision":
        return cls(allowed=True, detail=detail)

    @classmethod
    def no(cls, reason: str, **detail: Any) -> "Decision":
        return cls(allowed=False, reason=reason, detail={"policy": reason, **detail})


class LocalPolicy:
    """采集器的本地策略状态机。

    `paused` 是真正的开关而不是标记：暂停期间采集请求被拒绝，麦克风根本不会被打开。
    「采集了但不上传」不算暂停——04 号文档原则 4 说的是摘下眼镜等于停止采集。
    """

    def __init__(self, *, max_duration_seconds: int, paused: bool = False) -> None:
        self.max_duration_seconds = max_duration_seconds
        self.paused = paused
        # 暂停原因留给回执用：区分「操作者按了暂停」和「云端下发了 PRIVACY_PAUSE」
        self.pause_reason: str | None = "启动时即处于隐私暂停" if paused else None

    def pause(self, reason: str) -> None:
        self.paused = True
        self.pause_reason = reason

    def resume(self) -> None:
        self.paused = False
        self.pause_reason = None

    # ---------------------------------------------------------------- 采集

    def check_capture(self, action: str, duration_seconds: float | None) -> Decision:
        unsupported = UNSUPPORTED_ACTIONS.get(action)
        if unsupported is not None:
            return Decision.no(unsupported, action=action)
        if action not in SUPPORTED_ACTIONS:
            return Decision.no(
                f"耳机运行时不认识动作 {action}（支持：{list(SUPPORTED_ACTIONS)}）", action=action
            )

        # PAUSE/RESUME/STOP 是会话控制，本身不打开麦克风，暂停期间也应当被执行——
        # 否则一旦暂停就再也没法通过云端恢复。
        if action in ("PAUSE", "RESUME", "STOP"):
            return Decision.ok(action=action)

        if self.paused:
            return Decision.no(
                f"本地隐私暂停中：{self.pause_reason or '操作者已暂停采集'}", action=action
            )

        if action == "CAPTURE_AUDIO":
            return self._check_duration(duration_seconds)
        return Decision.ok(action=action)

    def _check_duration(self, duration_seconds: float | None) -> Decision:
        """采集预算：超过上限按上限截断，并在回执里如实说明被截了。

        不静默执行原始时长，也不直接拒绝——控制台的诉求是「录一段」，给它 60 秒比
        什么都不给有用，但必须让它知道自己要的 300 秒没有生效。
        """
        if duration_seconds is None:
            return Decision.ok()
        if duration_seconds <= 0:
            return Decision.no(f"录音时长必须为正：{duration_seconds}")
        if duration_seconds > self.max_duration_seconds:
            return Decision.ok(
                clamped_duration_seconds=self.max_duration_seconds,
                requested_duration_seconds=duration_seconds,
                clamp_reason=f"本地采集预算上限 {self.max_duration_seconds}s",
            )
        return Decision.ok()

    # ---------------------------------------------------------------- 播放

    def check_playback(
        self, *, allow_tts: bool, expected_device: str, actual_device: str | None, allow_any: bool
    ) -> Decision:
        """播放前核对声音会从哪儿出来。

        这是输出方向的「策略在边缘执行」：云端不知道这台机器当前的默认输出设备是什么，
        只有采集器知道。默认输出设备不是耳机时宁可拒绝——一条私人提醒从笔记本外放出去，
        比漏掉一条提醒严重得多。
        """
        if not allow_tts:
            return Decision.no("消息未授权语音播报（delivery_policy.allow_tts=false）")
        if allow_any:
            return Decision.ok(output_device=actual_device or "unknown", output_check="skipped")
        if actual_device is None:
            return Decision.no("拿不到当前默认输出设备，无法确认声音会从耳机出来")
        if expected_device and expected_device.lower() not in actual_device.lower():
            return Decision.no(
                f"当前默认输出设备是「{actual_device}」，不是「{expected_device}」，"
                "播报会从外放出去",
                output_device=actual_device,
            )
        return Decision.ok(output_device=actual_device)


__all__ = ["Decision", "LocalPolicy", "SUPPORTED_ACTIONS", "UNSUPPORTED_ACTIONS"]
