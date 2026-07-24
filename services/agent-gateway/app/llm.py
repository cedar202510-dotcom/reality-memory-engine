"""对话 LLM 客户端：OpenAI tools 协议的多轮 chat。

与 memory-platform 的 LLMClient（complete_json 单次契约调用）是刻意不同的
编程模型：harness 需要 tool-calling 循环。两边只共享配置约定，不共享代码。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantTurn:
    """一轮模型输出：要么带 tool_calls（继续循环），要么是最终 content。"""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatLLM(Protocol):
    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AssistantTurn: ...


class OpenAIChatClient:
    """任意 OpenAI 兼容端点（含 kimi-coding，k3 只接受 temperature=1）。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        temperature: float | None = None,
        user_agent: str | None = None,
        trust_env: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        headers = {"User-Agent": user_agent} if user_agent else None
        self._http = httpx.AsyncClient(timeout=timeout, headers=headers, trust_env=trust_env)

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AssistantTurn:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        resp = await self._http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        message = resp.json()["choices"][0]["message"]
        calls = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args))
        return AssistantTurn(content=message.get("content"), tool_calls=calls)

    async def aclose(self) -> None:
        await self._http.aclose()


class FakeChatLLM:
    """测试用：按脚本依次返回 AssistantTurn；耗尽后返回固定收尾语。"""

    def __init__(self, script: list[AssistantTurn] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[list[dict[str, Any]]] = []  # 每次收到的 messages（断言用）

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AssistantTurn:
        self.calls.append(messages)
        if self.script:
            return self.script.pop(0)
        return AssistantTurn(content="（脚本耗尽）")


def build_chat_llm(settings) -> ChatLLM:
    if settings.llm_provider == "fake":
        return FakeChatLLM()
    if settings.llm_provider == "kimi-coding":
        return OpenAIChatClient(
            base_url=settings.llm_base_url or "https://api.kimi.com/coding/v1",
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature if settings.llm_temperature is not None else 1.0,
            user_agent="rme-agent-gateway/0.1",
            trust_env=settings.llm_trust_env,
        )
    return OpenAIChatClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
        temperature=settings.llm_temperature,
        trust_env=settings.llm_trust_env,
    )
