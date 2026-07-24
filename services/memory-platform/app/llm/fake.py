"""FakeLLMClient：不依赖真实 API key，按提示词内容返回可配置的确定性结果。

规则驱动：
- caption_rules / extract_rules / answer_rules 是 (匹配子串, 返回值) 列表，
  按序匹配 prompt 文本，第一个命中生效。
- 未命中时返回可预测的兜底结果，保证流水线不崩。
- embed 用 SHA-256 生成确定性伪向量（同一文本永远同一向量，可用于检索测试）。
"""
from __future__ import annotations

import hashlib
from typing import Any

EMBEDDING_DIM = 1024


def _hash_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """确定性伪向量：按块 sha256 展开，归一化到 [-1, 1]。"""
    out: list[float] = []
    counter = 0
    while len(out) < dim:
        digest = hashlib.sha256(f"{text}::{counter}".encode()).digest()
        out.extend((b / 127.5) - 1.0 for b in digest)
        counter += 1
    return out[:dim]


class FakeLLMClient:
    def __init__(
        self,
        *,
        caption_rules: list[tuple[str, dict[str, Any]]] | None = None,
        extract_rules: list[tuple[str, list[dict[str, Any]]]] | None = None,
        answer_rules: list[tuple[str, dict[str, Any]]] | None = None,
        audio_extract_rules: list[tuple[str, list[dict[str, Any]]]] | None = None,
        translate_rules: list[tuple[str, str]] | None = None,
        embedding_enabled: bool = True,
    ) -> None:
        self.caption_rules = caption_rules or []
        self.extract_rules = extract_rules or []
        self.answer_rules = answer_rules or []
        self.audio_extract_rules = audio_extract_rules  # None 时回退 extract_rules
        self.translate_rules = translate_rules or []
        self.embedding_enabled = embedding_enabled
        self.calls: list[dict[str, Any]] = []  # 便于测试断言

    async def complete_json(
        self,
        *,
        task: str,
        prompt: str,
        images: list[str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"task": task, "prompt": prompt, "n_images": len(images or [])})
        if task == "caption":
            return self._match(self.caption_rules, prompt) or {
                "caption": "一张室内场景照片",
                "scene_tags": [],
            }
        if task == "extract":
            return {"observations": self._match(self.extract_rules, prompt) or []}
        if task == "audio_extract":
            rules = self.audio_extract_rules if self.audio_extract_rules is not None else self.extract_rules
            return {"observations": self._match(rules, prompt) or []}
        if task == "translate":
            # 默认空串 → 调用方降级为仅原文向量（测试无需配置翻译规则）
            return {"english": self._match(self.translate_rules, prompt) or ""}
        if task == "answer":
            return self._match(self.answer_rules, prompt) or {
                "found": False,
                "location": None,
                "confidence": 0.1,
                "answer_text": "没有在用过的场景里找到它。",
            }
        raise ValueError(f"FakeLLMClient: 未知 task={task}")

    async def embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self.embedding_enabled:
            return None
        return [_hash_embedding(t) for t in texts]

    @staticmethod
    def _match(rules: list[tuple[str, Any]], prompt: str) -> Any:
        for needle, value in rules:
            if needle in prompt:
                return value
        return None
