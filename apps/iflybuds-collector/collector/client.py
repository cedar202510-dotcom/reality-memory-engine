"""后端 HTTP 客户端：Ingest、设备注册、inbox、回执。

只封装这个采集器真正用到的四个端点，不做通用 SDK。端点路径写在这一个文件里，
后端改路由时只有这里要改。

鉴权：`/internal/v1` 当前是本机/内网可信域（API-Reference §鉴权），所以这里没有
token。后端补上设备 token 后，改动范围就是这个类的 headers。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


class BackendError(RuntimeError):
    """后端返回了非 2xx。`permanent` 区分「重试有用」和「重试永远没用」。"""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    @property
    def permanent(self) -> bool:
        """4xx = 请求本身不对（契约不兼容、设备不存在），重投多少次都是同一个结果。"""
        return self.status_code is not None and 400 <= self.status_code < 500


@dataclass
class IngestResult:
    envelope_id: str
    evidence_item_ids: list[str]
    duplicate_evidence_ids: list[str]
    idempotent_replay: bool

    @classmethod
    def of(cls, payload: dict[str, Any]) -> "IngestResult":
        return cls(
            envelope_id=str(payload.get("envelope", {}).get("id", "")),
            evidence_item_ids=[str(x) for x in payload.get("evidence_item_ids", [])],
            duplicate_evidence_ids=[str(x) for x in payload.get("duplicate_evidence_ids", [])],
            idempotent_replay=bool(payload.get("idempotent_replay", False)),
        )


class BackendClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "BackendClient":
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self._timeout)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("BackendClient 未进入上下文（async with）")
        return self._client

    async def _json(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise BackendError(
                f"{response.request.method} {response.request.url.path} → "
                f"{response.status_code}：{response.text[:300]}",
                status_code=response.status_code,
            )
        return response.json()

    # ---------------------------------------------------------------- 设备

    async def register_device(
        self, *, kind: str, name: str, runtime_package: str | None, control_transport: str
    ) -> dict[str, Any]:
        """注册设备并拿回 device_id（04 §5.5 第 4 步）。按 name 幂等。"""
        return await self._json(
            await self.http.post(
                "/internal/v1/devices",
                json={
                    "kind": kind,
                    "name": name,
                    "runtime_package": runtime_package,
                    "control_transport": control_transport,
                },
            )
        )

    async def list_devices(self) -> list[dict[str, Any]]:
        payload = await self._json(await self.http.get("/internal/v1/devices"))
        return list(payload.get("devices", []))

    # ---------------------------------------------------------------- 上行

    async def upload_envelope(
        self, *, envelope: dict[str, Any], media: bytes, filename: str, content_type: str
    ) -> IngestResult:
        payload = await self._json(
            await self.http.post(
                "/internal/v1/envelopes",
                data={"envelope": json.dumps(envelope, ensure_ascii=False)},
                files=[("files", (filename, media, content_type))],
            )
        )
        return IngestResult.of(payload)

    # ---------------------------------------------------------------- 下行

    async def fetch_inbox(self, device_id: str) -> list[dict[str, Any]]:
        payload = await self._json(
            await self.http.get(f"/internal/v1/devices/{device_id}/inbox")
        )
        return list(payload.get("messages", []))

    async def post_receipt(
        self, *, device_id: str, message_id: str, status: str, detail: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._json(
            await self.http.post(
                f"/internal/v1/devices/{device_id}/receipts",
                json={"message_id": message_id, "status": status, "detail": detail},
            )
        )

    # ---------------------------------------------------------------- 操作者侧辅助

    async def push_voice_message(
        self,
        *,
        device_id: str,
        text: str,
        allow_tts: bool = True,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        """从操作者这边注入一条待播报的提醒。

        放在采集器仓库里是为了本机联调顺手，但它扮演的是**云端**角色，不是设备能力：
        真实链路里这条消息由记忆平台的信号规则产生。
        """
        body: dict[str, Any] = {
            "message_type": "REMINDER_SIGNAL",
            "payload": {"text": text},
            "delivery_policy": {"allow_text": True, "allow_tts": allow_tts},
        }
        if ttl_seconds is not None:
            body["ttl_seconds"] = ttl_seconds
        return await self._json(
            await self.http.post(f"/internal/v1/devices/{device_id}/messages", json=body)
        )


__all__ = ["BackendClient", "BackendError", "IngestResult"]
