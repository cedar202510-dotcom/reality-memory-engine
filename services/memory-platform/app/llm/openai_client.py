"""OpenAI 兼容客户端：chat completions（支持 image_url base64 data URL）+ embeddings。

通过环境变量配置：
  LLM_BASE_URL / LLM_API_KEY / LLM_VISION_MODEL / LLM_TEXT_MODEL
  EMBEDDING_BASE_URL / EMBEDDING_API_KEY / EMBEDDING_MODEL（可空）
"""
from __future__ import annotations

import json
from typing import Any

import httpx


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        vision_model: str,
        text_model: str,
        embedding_base_url: str = "",
        embedding_api_key: str = "",
        embedding_model: str = "",
        timeout: float = 60.0,
        temperature: float | None = 0.0,
        user_agent: str | None = None,
        trust_env: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.vision_model = vision_model
        self.text_model = text_model
        self.embedding_base_url = embedding_base_url.rstrip("/")
        self.embedding_api_key = embedding_api_key
        self.embedding_model = embedding_model
        self.temperature = temperature
        headers = {"User-Agent": user_agent} if user_agent else None
        # trust_env=False：忽略 macOS 系统代理/代理环境变量，直连 API（代理不稳定时表现为随机连接失败）
        self._http = httpx.AsyncClient(timeout=timeout, headers=headers, trust_env=trust_env)

    async def complete_json(
        self,
        *,
        task: str,
        prompt: str,
        images: list[str] | None = None,
    ) -> dict[str, Any]:
        model = self.vision_model if images else self.text_model
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for url in images or []:
            content.append({"type": "image_url", "image_url": {"url": url}})
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "response_format": {"type": "json_object"},
        }
        if self.temperature is not None:  # None = 由服务端默认（k3 只允许 temperature=1）
            payload["temperature"] = self.temperature
        resp = await self._http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        return json.loads(text)

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not (self.embedding_base_url and self.embedding_model):
            return None
        resp = await self._http.post(
            f"{self.embedding_base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.embedding_api_key}"},
            json={"model": self.embedding_model, "input": texts},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return [row["embedding"] for row in sorted(data, key=lambda r: r["index"])]

    async def aclose(self) -> None:
        await self._http.aclose()
