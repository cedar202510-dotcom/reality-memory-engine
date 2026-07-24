"""VisionEncoder 协议：视觉跨模态（CLIP 风格）编码的统一抽象。

与 LLMClient 同风格：业务代码不直接碰模型/HTTP，只依赖此协议。
两类能力：
- embed_images：图片字节 → 向量；返回 None 表示未配置/不可用（调用方必须能降级）
- embed_texts：文本 → 向量（与图片向量同一语义空间，支持跨模态检索）；None 同上
"""
from __future__ import annotations

from typing import Protocol


class VisionEncoder(Protocol):
    """视觉编码器协议。实现方保证：未配置/推理失败时返回 None，绝不抛出。"""

    @property
    def dim(self) -> int:
        """输出向量维度（须与 frame_assets.visual_embedding 列维度一致）。"""
        ...

    async def embed_images(self, images: list[bytes]) -> list[list[float]] | None:
        """图片字节列表 → 向量列表；未配置或失败时返回 None。"""
        ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        """文本列表 → 向量列表（与图片向量同空间）；未配置或失败时返回 None。"""
        ...


class NullVisionEncoder:
    """恒返回 None 的视觉编码器：vision_provider=none 或构造失败时的降级实现。"""

    def __init__(self, dim: int = 512) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    async def embed_images(self, images: list[bytes]) -> list[list[float]] | None:
        return None

    async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        return None
