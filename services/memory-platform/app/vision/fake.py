"""FakeVisionEncoder：不依赖真实模型，输出可控的确定性伪向量。

模仿 FakeLLMClient 的注入式风格：
- token_basis 注入"token → 向量基"映射。embed_texts 时，文本中出现哪些
  token，就把对应向量基叠加；embed_images 时，按图片 sha256 在 image_tokens
  里查 token 列表再叠加。于是共享 token 的文本与图片向量相似度天然很高，
  测试可精确控制跨模态检索结果。
- 未注入时用稳定 hash（同输入永远同向量），保证流水线可跑通。
"""
from __future__ import annotations

import hashlib
import math

VISUAL_EMBEDDING_DIM = 512


def _hash_embedding(key: str, dim: int = VISUAL_EMBEDDING_DIM) -> list[float]:
    """确定性伪向量：按块 sha256 展开，归一化到 [-1, 1]（与 FakeLLMClient 同法）。"""
    out: list[float] = []
    counter = 0
    while len(out) < dim:
        digest = hashlib.sha256(f"{key}::{counter}".encode()).digest()
        out.extend((b / 127.5) - 1.0 for b in digest)
        counter += 1
    return out[:dim]


def _l2_normalize(vec: list[float]) -> list[float]:
    """L2 归一化；零向量原样返回。"""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


class FakeVisionEncoder:
    """注入式假视觉编码器。

    参数：
    - dim：输出维度（默认 512，与 Vector 列一致）
    - token_basis：token → 向量基（建议单位向量且互相正交，便于断言相似度）
    - image_tokens：图片 sha256 hex → token 列表；图片命中后按其 token 叠加向量基
    - enabled：False 时两个方法都返回 None（模拟未配置，验证降级路径）
    """

    def __init__(
        self,
        *,
        dim: int = VISUAL_EMBEDDING_DIM,
        token_basis: dict[str, list[float]] | None = None,
        image_tokens: dict[str, list[str]] | None = None,
        enabled: bool = True,
    ) -> None:
        self._dim = dim
        self.token_basis = token_basis or {}
        self.image_tokens = image_tokens or {}
        self.enabled = enabled
        self.calls: list[dict[str, int]] = []  # 便于测试断言（记录调用次数/批量大小）

    @staticmethod
    def image_digest(data: bytes) -> str:
        """图片字节 → image_tokens 的查询键（sha256 hex）。测试用它构造注入映射。"""
        return hashlib.sha256(data).hexdigest()

    @property
    def dim(self) -> int:
        return self._dim

    def _embed_tokens(self, tokens: list[str], fallback_key: str) -> list[float]:
        """token 列表 → 向量：命中向量基的叠加并归一化；无命中时退回稳定 hash。"""
        hits = [self.token_basis[t] for t in tokens if t in self.token_basis]
        if not hits:
            return _l2_normalize(_hash_embedding(fallback_key, self._dim))
        out = [sum(basis[i] for basis in hits) for i in range(self._dim)]
        return _l2_normalize(out)

    async def embed_images(self, images: list[bytes]) -> list[list[float]] | None:
        if not self.enabled:
            return None
        self.calls.append({"n_images": len(images)})
        return [
            self._embed_tokens(
                self.image_tokens.get(self.image_digest(img), []),
                fallback_key=f"image:{self.image_digest(img)}",
            )
            for img in images
        ]

    async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        if not self.enabled:
            return None
        self.calls.append({"n_texts": len(texts)})
        return [
            self._embed_tokens([t for t in self.token_basis if t in text], fallback_key=f"text:{text}")
            for text in texts
        ]
