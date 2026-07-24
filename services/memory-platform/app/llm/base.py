"""LLMClient 协议：所有模型调用都经过这一层，业务代码不直接碰 HTTP。

三类能力：
- complete_json：限定 JSON schema 的结构化输出（caption/抽取/精判）
- embed：文本向量，返回 None 表示未配置（调用方降级 trgm）
"""
from __future__ import annotations

from typing import Any, Protocol


class LLMClient(Protocol):
    async def complete_json(
        self,
        *,
        task: str,
        prompt: str,
        images: list[str] | None = None,
    ) -> dict[str, Any]:
        """task 用于路由/日志；prompt 为纯文本指令；images 为 base64 data URL 列表。
        实现必须返回 JSON 对象；解析失败由 StageAgent 重试/拒绝。"""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        """返回向量列表；未配置 embedding 时返回 None。"""
        ...
