"""下行通道冒烟演示：真实 uvicorn + 真实 WebSocket，模拟一台眼镜。

用法：
    cd services/memory-platform
    python scripts/downlink_smoke.py

与 tests/test_downlink.py 的区别：那里直接驱动 ASGI 协议（快、无端口），这里起真
uvicorn、走真 TCP，验证的是设备侧将要面对的那套栈——ws 握手、帧编解码、心跳、
断连。真机接入前的最后一道本机验证。

流程：起服务 → 模拟设备连长连 → 注入一条 REMINDER_SIGNAL → 设备收到并回 RECEIVED
/ SPOKEN / DISMISSED → 断线期间再注入一条 → 重连验证补投 → 验证过期消息不投递。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn
import websockets
from httpx import AsyncClient
from sqlalchemy import select

from app.db import SessionLocal, ensure_extensions
from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.memory.seed import ensure_seed
from app.models import Device, DeviceMessage

HOST, PORT = "127.0.0.1", 8799
BASE = f"http://{HOST}:{PORT}"


def log(step: str, detail: str = "") -> None:
    print(f"  {step:<28} {detail}")


async def _serve() -> tuple[uvicorn.Server, asyncio.Task]:
    app = create_app(fake_llm=FakeLLMClient(), with_workers=False)
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            return server, task
        await asyncio.sleep(0.05)
    raise RuntimeError("uvicorn 未能在 5 秒内启动")


async def _device_id() -> str:
    await ensure_extensions()
    async with SessionLocal() as session:
        await ensure_seed(session)
        device = await session.scalar(select(Device).limit(1))
        return str(device.id)


async def _inject(client: AsyncClient, device_id: str, text: str, **kw) -> dict:
    resp = await client.post(
        f"/internal/v1/devices/{device_id}/messages",
        json={
            "message_type": "REMINDER_SIGNAL",
            "payload": {"text": text},
            "delivery_policy": {"allow_text": True, "allow_tts": True},
            **kw,
        },
    )
    resp.raise_for_status()
    return resp.json()


async def main() -> None:
    device_id = await _device_id()
    server, task = await _serve()
    ws_url = f"ws://{HOST}:{PORT}/internal/v1/devices/{device_id}/stream"
    print(f"\n下行通道冒烟：device_id={device_id}\n")

    try:
        async with AsyncClient(base_url=BASE, timeout=10) as client:
            # --- 1. 在线投递 + 回执全链路 ---
            print("[1] 设备在线 → 注入 → 播报 → 回执")
            async with websockets.connect(ws_url) as ws:
                created = await _inject(client, device_id, "钥匙上次在玄关柜上")
                log("注入", f"pushed_connections={created['pushed_connections']}")

                envelope = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                log("设备收到", f"{envelope['message_type']} / {envelope['payload']['text']}")
                log("投递策略", json.dumps(envelope["delivery_policy"], ensure_ascii=False))
                mid = envelope["message_id"]

                for status in ("RECEIVED", "PRESENTED", "SPOKEN", "DISMISSED"):
                    await ws.send(json.dumps({"type": "receipt", "message_id": mid, "status": status}))
                    ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                    log(f"回执 {status}", f"→ 消息状态 {ack['message_status']}")

                await ws.send(json.dumps({"type": "ping"}))
                pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                log("心跳", pong["type"])

            # --- 2. 离线注入 → 重连补投 ---
            print("\n[2] 设备离线 → 注入 → 重连补投")
            offline = await _inject(client, device_id, "离线期间产生的提醒")
            log("注入", f"pushed_connections={offline['pushed_connections']}（0 = 无人在线，落库等拉）")
            log("消息状态", offline["message"]["status"])

            async with websockets.connect(ws_url) as ws:
                envelope = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
                log("重连即收到", envelope["payload"]["text"])
                mid = envelope["message_id"]
                await ws.send(json.dumps({"type": "receipt", "message_id": mid, "status": "DISMISSED"}))
                await asyncio.wait_for(ws.recv(), timeout=5)

            # --- 3. 过期消息不投递 ---
            print("\n[3] 过期消息不投递、不播报")
            stale = await _inject(client, device_id, "已经无关的建议", ttl_seconds=1)
            stale_id = stale["message"]["message_id"]
            log("注入", f"ttl_seconds=1 → {stale_id[:8]}…")
            await asyncio.sleep(1.2)

            inbox = (await client.get(f"/internal/v1/devices/{device_id}/inbox")).json()
            log("轮询 inbox", f"messages={len(inbox['messages'])}  expired={inbox['expired']}")

            async with websockets.connect(ws_url) as ws:
                with contextlib.suppress(asyncio.TimeoutError):
                    leaked = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    raise SystemExit(f"过期消息被投递了：{leaked}")
                log("长连补投", "无（正确：过期不投递）")

            async with SessionLocal() as session:
                msg = await session.get(DeviceMessage, uuid.UUID(stale_id))
                log("库内状态", msg.status)

        print("\n下行链路本机跑通：注入 → 长连投递 → 回执 → 离线补投 → 过期抑制\n")
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=5)


if __name__ == "__main__":
    asyncio.run(main())
