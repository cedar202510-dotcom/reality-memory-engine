"""Connector 抽象：把一条 CAPTURE_REQUEST 送到某台设备上。

设备接入架构（04）里 connector 是「云端与某类设备运行时之间的适配层」。这里的两个
实现回答同一个问题的两种答案：

- `adb`   后端在本机把请求翻译成 Android intent（联调期，后端必须与眼镜同机）
- `inbox` 后端只落库，设备自己来拉（架构目标形态，脱离 USB）

两者共用 `device_messages` 一张表和同一套回执语义，所以控制台看到的状态流是一样的，
换通道不需要改前端。

**分发成功不等于采集成功。** `DispatchResult.accepted` 只说明命令送出去了；设备是否
真的采集，由设备本地 PolicyCheck 决定，并通过 EXECUTED / REJECTED 回执告诉云端（§8）。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models import Device


@dataclass(frozen=True)
class CaptureCommand:
    """一次采集请求的设备无关表示。"""

    action: str
    interval_seconds: int | None = None
    duration_seconds: int | None = None
    reason: str = "operator_console"


@dataclass(frozen=True)
class DispatchResult:
    """分发结果。

    accepted=False 不是异常：设备没插 USB、动作在该运行时上不存在、设备未绑定运行时，
    都是可预期的正常结果。调用方据此写回执，而不是抛 500——控制台需要看到「为什么没成」。
    """

    transport: str
    accepted: bool
    detail: dict[str, Any] = field(default_factory=dict)
    # 命令是否真的离开服务端到达了设备。与 accepted 不是一回事：inbox 通道下设备离线时
    # accepted=True（消息已受理、排队等拉取）但 delivered=False。消息状态 SENT 的含义是
    # 「已推给设备」，排队中的消息标成 SENT 会让 inbox 语义失真。
    delivered: bool = False
    # inbox 通道下本次即时推送到的长连数；adb 恒为 0
    pushed_connections: int = 0
    # 分发端已经能确定终局时给出的回执状态（adb 执行失败 → FAILED）。
    # inbox 留空：结果只能由设备回执，云端不替设备宣布执行成功。
    terminal_status: str | None = None


class DeviceConnector(Protocol):
    """设备控制通道。实现必须是幂等安全的：同一 message_id 重复分发不应造成二次采集。

    `envelope` 是已落库消息的 `rme.device-message.v0` 信封。inbox 通道原样推给设备；
    adb 通道用不到它（intent 传不了结构化载荷），只用 command 里的动作。
    """

    transport: str

    async def dispatch(
        self,
        *,
        device: Device,
        command: CaptureCommand,
        message_id: uuid.UUID,
        envelope: dict[str, Any],
    ) -> DispatchResult: ...
