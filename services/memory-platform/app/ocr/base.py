"""TextRecognizer 协议：图像文字识别（OCR）的统一抽象。

与 LLMClient / VisionEncoder / Transcriber 同风格：业务代码不直接碰模型，只依赖此协议。
- recognize：图片字节 → 文本块列表；返回 None 表示未配置/不可用（调用方必须能降级）

为什么 OCR 值得单独占一条通道，而不是指望 caption 把字念出来：
身份证、银行卡、快递单、书脊、药盒——这类小物体的身份**印在它自己身上**。
「身份证」三个字就写在卡面上，OCR 命中的是字面量，不需要模型"认出"这是身份证。
而 caption 只会说"桌上有一些卡片"，帧向量里它更是不足一个 patch。
"""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class TextBlock(BaseModel):
    """一块识别出来的文字：文本 + 归一化位置 + 置信度。"""

    text: str = Field(description="识别文本（尚未脱敏）")
    bbox: dict[str, float] = Field(
        default_factory=dict, description="归一化坐标 {x,y,w,h} ∈ [0,1]"
    )
    score: float = Field(default=0.0, description="识别置信度 ∈ [0,1]")


class TextRecognizer(Protocol):
    """OCR 协议。实现方保证：未配置/推理失败时返回 None，绝不抛出。"""

    async def recognize(self, image_bytes: bytes) -> list[TextBlock] | None:
        """图片字节 → 文本块列表（无文字时返回空列表）；未配置或失败时返回 None。"""
        ...


class NullTextRecognizer:
    """恒返回 None 的 OCR：ocr_provider=none 或构造失败时的降级实现。"""

    async def recognize(self, image_bytes: bytes) -> list[TextBlock] | None:
        return None
