"""inbox connector：只落库 + 尝试即时推送，执行与否完全由设备决定。

这是通信架构 §5.3 的目标形态：设备在线就走长连即时推，离线就留在 `device_messages` 里
等设备下次 `GET /internal/v1/devices/{id}/inbox` 拉走。后端不需要和眼镜插在同一台机器上。

与 adb 通道最本质的区别：**这里不写终态**。云端不知道设备有没有采，只有设备自己回执
EXECUTED / REJECTED 才算数。adb 通道之所以能自己写终态，是因为它的终态说的是「intent 送
到运行时了」这件云端确实知道的事，不是「照片拍到了」。
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from ..models import Device
from .base import CaptureCommand, DispatchResult

if TYPE_CHECKING:  # 只为类型标注，避免与 downlink 形成导入环
    from ..downlink import DeviceHub


class InboxConnector:
    """把请求交给下行通道，等设备来拿。"""

    transport = "inbox"

    def __init__(self, hub: DeviceHub) -> None:
        self._hub = hub

    async def dispatch(
        self,
        *,
        device: Device,
        command: CaptureCommand,
        message_id: uuid.UUID,
        envelope: dict[str, Any],
    ) -> DispatchResult:
        pushed = await self._hub.publish(device.id, envelope)
        return DispatchResult(
            transport=self.transport,
            # 落库即视为已受理：设备离线不是错误，消息会在下次 inbox 拉取或重连时补投。
            accepted=True,
            delivered=pushed > 0,
            detail={
                "action": command.action,
                "delivery": "websocket" if pushed else "queued_for_inbox",
                "pushed_connections": pushed,
                "execution_evidence": "awaiting_device_receipt",
            },
            pushed_connections=pushed,
            terminal_status=None,
        )
