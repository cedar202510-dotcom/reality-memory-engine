"""HTTPVisionEncoder：调用可配置的 HTTP CLIP sidecar。

适配边缘部署：CLIP 作为独立服务跑在 RDK X5 / Orange Pi 等设备上，
本平台只通过 HTTP 取向量，本机不装 torch。

Sidecar 契约（简洁 JSON，base64 传图）：
- POST {base_url}/embed/texts
  请求 {"texts": ["红色水杯", ...]}
  响应 {"embeddings": [[0.01, ...], ...]}（与 texts 等长，建议已 L2 归一化）
- POST {base_url}/embed/images
  请求 {"images_base64": ["<base64>", ...]}
  响应 {"embeddings": [[0.01, ...], ...]}（与 images 等长）
- 认证：vision_api_key 非空时带 `Authorization: Bearer <key>`。
- 任何超时/网络错误/契约不符 → 返回 None，调用方降级。
"""
from __future__ import annotations

import base64

import httpx


class HTTPVisionEncoder:
    """HTTP CLIP sidecar 客户端。所有失败静默降级为 None。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        dim: int = 512,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._dim = dim
        self._timeout = timeout

    @property
    def dim(self) -> int:
        return self._dim

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    async def _post_embeddings(self, path: str, payload: dict) -> list[list[float]] | None:
        """统一请求/校验；任何异常或契约不符都返回 None。"""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}{path}", json=payload, headers=self._headers()
                )
                resp.raise_for_status()
                data = resp.json()
            embeddings = data.get("embeddings")
            if not isinstance(embeddings, list):
                return None
            return [[float(x) for x in vec] for vec in embeddings]
        except Exception:  # noqa: BLE001 - 网络/超时/契约问题一律降级
            return None

    async def embed_images(self, images: list[bytes]) -> list[list[float]] | None:
        if not images:
            return []
        payload = {"images_base64": [base64.b64encode(b).decode() for b in images]}
        return await self._post_embeddings("/embed/images", payload)

    async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        if not texts:
            return []
        return await self._post_embeddings("/embed/texts", {"texts": texts})
