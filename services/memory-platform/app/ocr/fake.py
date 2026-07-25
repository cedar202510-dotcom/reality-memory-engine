"""FakeTextRecognizer：不依赖真实 OCR 模型，注入式确定性识别。

模仿 FakeTranscriber / FakeVisionEncoder 的风格：
- blocks_by_digest 注入"图片 sha256 → 文本块 dict 列表"，测试可精确控制识别结果。
- 未命中时返回 default_blocks（默认空列表 = 这张图没字）。
- enabled=False 时返回 None（模拟未配置，验证降级路径）。
"""
from __future__ import annotations

import hashlib

from .base import TextBlock


class FakeTextRecognizer:
    """注入式假 OCR。"""

    def __init__(
        self,
        *,
        blocks_by_digest: dict[str, list[dict]] | None = None,
        default_blocks: list[dict] | None = None,
        enabled: bool = True,
    ) -> None:
        self.blocks_by_digest = blocks_by_digest or {}
        self.default_blocks = default_blocks if default_blocks is not None else []
        self.enabled = enabled
        self.calls: list[int] = []  # 便于测试断言（记录每次调用的字节数）

    @staticmethod
    def image_digest(data: bytes) -> str:
        """图片字节 → blocks_by_digest 的查询键（sha256 hex）。"""
        return hashlib.sha256(data).hexdigest()

    async def recognize(self, image_bytes: bytes) -> list[TextBlock] | None:
        if not self.enabled:
            return None
        self.calls.append(len(image_bytes))
        raw = self.blocks_by_digest.get(self.image_digest(image_bytes), self.default_blocks)
        return [TextBlock.model_validate(b) for b in raw]
