"""LocalRapidOCR：本机 RapidOCR（ONNXRuntime）推理，模型只在本机加载，不出网。

选它而不是 PaddleOCR：同一套 PP-OCR 权重，但依赖只有 onnxruntime（~50MB 权重、
纯 CPU 就能跑），不用把整个 Paddle 拖进来。中文识别是这条通道的主要场景。

- rapidocr 为可选依赖：此处 lazy import，未安装时构造抛错，
  由 build_text_recognizer 工厂捕获并降级为 NullTextRecognizer。
- 推理是 CPU 密集同步调用，一律包 asyncio.to_thread，避免阻塞事件循环。
"""
from __future__ import annotations

import asyncio
import io
from typing import Any

from .base import TextBlock


def _create_engine() -> Any:
    """构造 RapidOCR 引擎。新旧包名都试：rapidocr（2.x）/ rapidocr_onnxruntime（1.x）。"""
    try:
        from rapidocr import RapidOCR  # noqa: PLC0415
    except ImportError:
        from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
    return RapidOCR()


def _quad_to_bbox(quad: Any, width: int, height: int) -> dict[str, float]:
    """OCR 给的是四点多边形（文字可能是斜的），转成归一化外接矩形。"""
    xs = [float(p[0]) for p in quad]
    ys = [float(p[1]) for p in quad]
    x0, x1 = max(min(xs), 0.0), min(max(xs), float(width))
    y0, y1 = max(min(ys), 0.0), min(max(ys), float(height))
    if width <= 0 or height <= 0:
        return {}
    return {
        "x": round(x0 / width, 6),
        "y": round(y0 / height, 6),
        "w": round(max(x1 - x0, 0.0) / width, 6),
        "h": round(max(y1 - y0, 0.0) / height, 6),
    }


class LocalRapidOCR:
    """本机 RapidOCR 识别器。max_side>0 时先把长边缩到该值再识别。

    缩图上限比 VLM 那边（vlm_image_max_side=1024）更高是有原因的：VLM 看的是场景，
    OCR 看的是笔画。身份证上的小字缩到 1024 宽的整图里就剩几个像素，识别率会塌掉。
    """

    def __init__(self, *, max_side: int = 1600, min_score: float = 0.5) -> None:
        self._engine = _create_engine()
        self._max_side = max_side
        self._min_score = min_score

    def _run(self, image_bytes: bytes) -> list[TextBlock]:
        import numpy as np  # noqa: PLC0415

        from ..media import open_image  # noqa: PLC0415

        with open_image(io.BytesIO(image_bytes).getvalue()) as raw:
            image = raw.convert("RGB")
            if self._max_side > 0 and max(image.size) > self._max_side:
                image.thumbnail((self._max_side, self._max_side))
            width, height = image.size
            array = np.array(image)

        result = self._engine(array)
        # rapidocr 1.x 返回 (results, elapse)；2.x 返回带 .boxes/.txts/.scores 的对象
        raw_items: list[tuple[Any, str, float]] = []
        if isinstance(result, tuple):
            items = result[0] or []
            raw_items = [(it[0], str(it[1]), float(it[2])) for it in items]
        elif getattr(result, "boxes", None) is not None:
            boxes = result.boxes or []
            txts = result.txts or []
            scores = result.scores or []
            raw_items = [
                (boxes[i], str(txts[i]), float(scores[i])) for i in range(len(boxes))
            ]

        blocks: list[TextBlock] = []
        for quad, text, score in raw_items:
            text = text.strip()
            if not text or score < self._min_score:
                continue
            blocks.append(
                TextBlock(text=text, bbox=_quad_to_bbox(quad, width, height), score=score)
            )
        return blocks

    async def recognize(self, image_bytes: bytes) -> list[TextBlock] | None:
        try:
            return await asyncio.to_thread(self._run, image_bytes)
        except Exception:  # noqa: BLE001 - 协议契约：失败返回 None，绝不抛给调用方
            return None
