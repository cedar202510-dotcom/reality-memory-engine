"""记忆平台 HTTP 客户端：gateway 访问记忆的唯一通道。

- 永远带 AgentGrant token；401/403 不重试、结构化返回给 harness（§13：
  Scope 不足 → 请求用户授权，不尝试绕过）。
- 不缓存查询结果（§12 最小实现：会话即上下文，无副本可失效）。
"""
from __future__ import annotations

import uuid
from typing import Any

import httpx


class MemoryClient:
    def __init__(
        self, *, base_url: str, token: str, timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
            trust_env=False,
        )

    async def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, json: dict | None = None) -> dict[str, Any]:
        return await self._request("POST", path, json=json)

    async def _request(self, method: str, path: str, **kw) -> dict[str, Any]:
        """成功返回响应 JSON；失败返回 {"error", "status"}（harness 转达而非崩溃）。"""
        try:
            resp = await self._http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            return {"error": f"记忆平台暂时不可用：{type(exc).__name__}", "status": 0}
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            return {"error": str(detail), "status": resp.status_code}
        return resp.json()

    # ---- §14 工具映射的四个高层命令 + 信号 ----

    async def find_object(self, name: str, deep: bool = False) -> dict[str, Any]:
        return await self._get("/v1/memory/objects/where-is", params={"name": name, "deep": deep})

    async def get_object_timeline(self, entity_id: str) -> dict[str, Any]:
        try:
            uuid.UUID(entity_id)
        except ValueError:
            return {"error": f"entity_id 不是合法 uuid：{entity_id}", "status": 422}
        return await self._get(f"/v1/memory/objects/{entity_id}/timeline")

    async def get_preference(self, subject: str) -> dict[str, Any]:
        return await self._get("/v1/memory/preferences", params={"subject": subject})

    async def submit_correction(
        self, entity_id: str, field: str, value: Any, reason: str = ""
    ) -> dict[str, Any]:
        return await self._post(
            "/v1/memory/correct",
            json={"entity_id": entity_id, "field": field, "value": value, "reason": reason},
        )

    async def list_signals(self) -> dict[str, Any]:
        return await self._get("/v1/signals")

    async def ack_signal(self, signal_id: str) -> dict[str, Any]:
        return await self._post(f"/v1/signals/{signal_id}/ack")

    async def subscribe_signals(
        self, signal_types: list[str], *, min_confidence: float = 0.0, daily_cap: int = 10
    ) -> dict[str, Any]:
        return await self._post(
            "/v1/signal-subscriptions",
            json={
                "signal_types": signal_types,
                "min_confidence": min_confidence,
                "daily_cap": daily_cap,
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()
