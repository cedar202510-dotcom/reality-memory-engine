"""adb connector：把采集请求翻译成 Android intent，经 USB 送到眼镜。

这是联调期通道，不是架构目标形态——它要求后端进程与眼镜插在同一台机器上。目标形态是
`inbox`（设备自己来拉，见 inbox.py）。保留 adb 的理由是它今天就能端到端跑通，且不需要
重新 build/install APK。

为什么是 intent 而不是 `adb shell input tap`：眼镜的输入通道会拦截 adb 注入的点击，
intent extra 是唯一可靠的脚本化触发方式（见探针 MainActivity.handleDebugExtras 的注释）。

动作映射直接对应两个眼镜 App 已有的调试入口，本模块不新增设备端能力：

- 探针 `com.realitymemory.glassprobe`：MainActivity 只认 capture_once / start_periodic /
  stop_capture 三个 boolean extra
- 正式 App `com.realitymemory.glasses`：MainActivity 只认 rme_debug_command 字符串 extra，
  且被 `if (!BuildConfig.DEBUG) return` 门禁挡住——release 包上这条通道整体无效

映射表里没有的动作一律如实报 unsupported，不做「就近替代」。把 CAPTURE_AUDIO 悄悄映射成
START_PERIODIC 会让控制台以为录了一段音频，实际却开了一个持续采集会话。
"""
from __future__ import annotations

import asyncio
import shutil
import uuid
from typing import Any, Awaitable, Callable

from ..config import get_settings
from ..models import Device
from .base import CaptureCommand, DispatchResult

PROBE_PACKAGE = "com.realitymemory.glassprobe"
GLASSES_PACKAGE = "com.realitymemory.glasses"

# runtime_package → {action: intent extra 参数}
INTENT_EXTRAS: dict[str, dict[str, list[str]]] = {
    PROBE_PACKAGE: {
        "CAPTURE_PHOTO": ["--ez", "capture_once", "true"],
        "START_PERIODIC": ["--ez", "start_periodic", "true"],
        "STOP": ["--ez", "stop_capture", "true"],
    },
    GLASSES_PACKAGE: {
        "CAPTURE_PHOTO": ["--es", "rme_debug_command", "remember_now"],
        "STOP": ["--es", "rme_debug_command", "end_session"],
    },
}

# 该运行时上确实做不到的动作 → 给控制台一句能直接看懂的原因
UNSUPPORTED_REASON: dict[str, dict[str, str]] = {
    PROBE_PACKAGE: {
        "CAPTURE_AUDIO": "探针的录音只随周期采集会话启停，没有单次短音频入口",
        "PAUSE": "探针 MainActivity 未暴露 pause extra（服务内有 ACTION_PAUSE，需设备端补 extra）",
        "RESUME": "探针 MainActivity 未暴露 resume extra（服务内有 ACTION_RESUME，需设备端补 extra）",
    },
    GLASSES_PACKAGE: {
        "CAPTURE_AUDIO": "正式 App 的音频由 CaptureIntent 内部编排，无独立调试入口",
        "START_PERIODIC": "正式 App 的会话由佩戴与 IMU 触发，调试通道只有 remember_now / end_session",
        "PAUSE": "正式 App 调试通道未暴露 pause",
        "RESUME": "正式 App 调试通道未暴露 resume",
    },
}

# argv → (returncode, stdout, stderr)。测试注入 fake 用。
AdbRunner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]


async def _run(argv: list[str], timeout: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


class AdbConnector:
    """通过本机 adb 驱动眼镜 App。

    命令用 exec 传参数组，不经 shell：extras 的值全部来自本文件的固定映射表，请求里的
    自由文本（reason 等）不进 argv。
    """

    transport = "adb"

    def __init__(self, runner: AdbRunner | None = None) -> None:
        self._runner = runner

    async def dispatch(
        self,
        *,
        device: Device,
        command: CaptureCommand,
        message_id: uuid.UUID,
        envelope: dict[str, Any],
    ) -> DispatchResult:
        settings = get_settings()
        package = device.runtime_package

        if not package:
            return self._reject(
                "device_not_bound",
                f"设备 {device.id} 未绑定 runtime_package，不知道该驱动哪个眼镜 App",
            )
        if package not in INTENT_EXTRAS:
            return self._reject(
                "unknown_runtime",
                f"未知运行时 {package}（已支持：{list(INTENT_EXTRAS)}）",
            )

        extras = INTENT_EXTRAS[package].get(command.action)
        if extras is None:
            reason = UNSUPPORTED_REASON.get(package, {}).get(
                command.action, f"{package} 未提供 {command.action} 的调试入口"
            )
            return self._reject("unsupported_action", reason, status="REJECTED")

        binary = settings.adb_binary
        if self._runner is None and shutil.which(binary) is None:
            return self._reject("adb_missing", f"找不到 adb 可执行文件：{binary}")

        prefix = [binary]
        if settings.adb_serial:
            prefix += ["-s", settings.adb_serial]
        argv = [*prefix, "shell", "am", "start", "-n", f"{package}/.MainActivity", *extras]

        runner = self._runner or (lambda a: _run(a, settings.adb_timeout_seconds))

        # 先唤醒屏幕再发 intent。眼镜熄屏时 MainActivity 处于 paused，`am start` 会返回
        # 「intent has been delivered to currently running top-most instance」看起来成功，
        # 但 Android 12 禁止后台启动 camera/microphone 类型的前台服务，采集根本不会发生——
        # 真机实测：不唤醒时探针日志一条不落，唤醒后才出现 CAPTURED_LOCAL。
        # session-viewer 的 wake_start 命令用的也是这个 keyevent。
        wake_sent = False
        if settings.adb_wake_before_dispatch:
            try:
                await runner([*prefix, "shell", "input", "keyevent", "224"])  # KEYCODE_WAKEUP
                wake_sent = True
            except (asyncio.TimeoutError, OSError):
                # 唤醒失败不阻断：设备可能本来就亮着，让真正的 intent 去暴露问题
                pass

        try:
            code, stdout, stderr = await runner(argv)
        except asyncio.TimeoutError:
            return self._reject("adb_timeout", f"adb 超过 {settings.adb_timeout_seconds}s 未返回")
        except OSError as exc:
            return self._reject("adb_error", f"调用 adb 失败：{exc}")

        detail = {
            "package": package,
            "action": command.action,
            "argv": argv,
            "wake_sent": wake_sent,
            "returncode": code,
            "stdout": stdout.strip()[:500],
            "stderr": stderr.strip()[:500],
        }
        # `am start` 起不来时 returncode 仍可能是 0，错误只写在 stdout 里
        failed_text = "Error" in stdout or "Exception" in stdout
        if code != 0 or failed_text:
            detail["reason"] = "adb_dispatch_failed"
            return DispatchResult(
                transport=self.transport, accepted=False, detail=detail, terminal_status="FAILED"
            )

        ignored = self._ignored_params(package, command)
        if ignored:
            detail["ignored"] = ignored
        # 命令送到了，但设备端是否真拍取决于本地策略（权限、佩戴、会话状态）。
        # adb 通道拿不到设备的执行回执，所以这里只写 EXECUTED 表示「已投递到运行时」，
        # detail 里明确标注该结论的强度，避免控制台把它读成「照片一定拍到了」。
        detail["execution_evidence"] = "intent_delivered_only"
        return DispatchResult(
            transport=self.transport,
            accepted=True,
            delivered=True,
            detail=detail,
            terminal_status="EXECUTED",
        )

    def _ignored_params(self, package: str, command: CaptureCommand) -> dict[str, str]:
        """设备端写死、intent 传不进去的参数——如实回报，别让控制台以为设置生效了。"""
        ignored: dict[str, str] = {}
        if package == PROBE_PACKAGE and command.action == "START_PERIODIC":
            if command.interval_seconds is not None and command.interval_seconds != 30:
                ignored["interval_seconds"] = (
                    "探针周期固定 30s（PERIODIC_INTERVAL_MS），intent 无法覆盖"
                )
        return ignored

    def _reject(self, reason: str, message: str, *, status: str = "FAILED") -> DispatchResult:
        """所有失败路径都落终态。

        不能让失败的 adb 请求停在 PENDING：它会留在 inbox 待投递集合里，设备一旦从
        inbox 拉一次，一条已经在控制台上显示为失败的请求就会被真正执行。同一条请求
        走两条通道各执行一次，是这套双通道设计最容易踩的坑。
        """
        return DispatchResult(
            transport=self.transport,
            accepted=False,
            detail={"reason": reason, "message": message},
            terminal_status=status,
        )
