"""设备 connector 注册表（设备接入架构 04）。

选择顺序：请求显式指定的 transport > 设备绑定的 control_transport > 默认 inbox。

默认落在 inbox 而不是 adb 是有意的：inbox 不需要任何本机前提条件，最坏结果是消息躺在
库里等设备来拉；adb 会去动本机进程，不该是「没配置」时的默认行为。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Device
from .adb import AdbConnector
from .base import CaptureCommand, DeviceConnector, DispatchResult
from .inbox import InboxConnector

if TYPE_CHECKING:
    from ..downlink import DeviceHub

DEFAULT_TRANSPORT = "inbox"

__all__ = [
    "AdbConnector",
    "CaptureCommand",
    "DeviceConnector",
    "DispatchResult",
    "InboxConnector",
    "DEFAULT_TRANSPORT",
    "resolve_transport",
    "build_connector",
]


def resolve_transport(device: Device, requested: str | None) -> str:
    return requested or device.control_transport or DEFAULT_TRANSPORT


def build_connector(
    transport: str, *, hub: DeviceHub, adb_runner=None
) -> DeviceConnector:
    """按通道名构造 connector。adb_runner 供测试注入假执行器，生产留空走真 adb。"""
    if transport == "adb":
        return AdbConnector(runner=adb_runner)
    if transport == "inbox":
        return InboxConnector(hub)
    raise ValueError(f"未知控制通道：{transport}")
