"""LocalOwlDetector：本机 OWLv2 开放词表检测（中文注释；模型只在本机加载，不出网）。

- transformers 为可选依赖：此处 lazy import，未安装时构造抛错，
  由 build_object_detector 工厂捕获并降级为 NullObjectDetector。
- 推理是 CPU/GPU 密集同步调用，一律包 asyncio.to_thread，避免阻塞事件循环。
- 权重按 detector_model 从 HF 缓存加载；首次需要联网拉一次（~1.4GB），之后离线可用。
"""
from __future__ import annotations

import asyncio
import io
from typing import Any

from .detect import DetectedBox


def _pick_device(preferred: str) -> str:
    """自动挑设备：mps → cuda → cpu。显式配了就用配的（调试时要能强制 cpu）。"""
    import torch  # noqa: PLC0415

    if preferred:
        return preferred
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class LocalOwlDetector:
    """本机 OWLv2 检测器。模型懒加载（第一次 detect 时才付加载代价）。"""

    def __init__(self, *, model_name: str, score_threshold: float, device: str = "") -> None:
        # 构造时就 import，让缺依赖在工厂里当场暴露并降级，
        # 而不是拖到第一帧进来时才发现——那时候已经在 worker 里了，失败很难看见。
        import transformers  # noqa: F401, PLC0415

        self._model_name = model_name
        self._threshold = score_threshold
        self._device = device
        self._loaded: tuple[Any, Any, str] | None = None
        self._lock = asyncio.Lock()

    def _load(self) -> tuple[Any, Any, str]:
        import torch  # noqa: PLC0415
        from transformers import Owlv2ForObjectDetection, Owlv2Processor  # noqa: PLC0415

        device = _pick_device(self._device)
        processor = Owlv2Processor.from_pretrained(self._model_name)
        model = Owlv2ForObjectDetection.from_pretrained(self._model_name)
        model = model.to(device).eval()
        torch.set_grad_enabled(False)
        return processor, model, device

    def _detect_sync(self, image: bytes, prompts: list[str]) -> list[DetectedBox]:
        import torch  # noqa: PLC0415
        from PIL import Image, ImageOps  # noqa: PLC0415

        processor, model, device = self._loaded  # type: ignore[misc]
        with Image.open(io.BytesIO(image)) as raw:
            # 与 regions.load_display_image 同一套：先把 EXIF 方向烘进像素，
            # 否则竖拍照片出的框套到前端看到的图上是横竖颠倒的。
            pil = (ImageOps.exif_transpose(raw) or raw).convert("RGB")
        width, height = pil.size
        if width <= 0 or height <= 0:
            return []

        inputs = processor(text=[prompts], images=pil, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)

        # 不走 post_process_*：那几个 API 在 transformers 各版本间改过签名和返回结构，
        # 而这里要的只是「每个 prompt 的最佳框」，从原始输出算三行就够，还免了版本漂移。
        probs = outputs.logits[0].sigmoid()      # (num_patches, num_prompts)
        boxes = outputs.pred_boxes[0]            # (num_patches, 4) 归一化 cxcywh

        # OWLv2 的预处理会先把图**补成正方形**（右/下补灰）再缩到 960——所以模型输出的
        # 归一化坐标是相对边长 max(w,h) 的方图，不是相对原图。直接乘 w/h 会把框压扁，
        # 而且只在非正方形照片上错，正方形测试图完全看不出来。
        side = float(max(width, height))
        out: list[DetectedBox] = []
        for index, prompt in enumerate(prompts):
            column = probs[:, index]
            best = int(torch.argmax(column))
            score = float(column[best])
            if score < self._threshold:
                continue
            cx, cy, bw, bh = (float(v) for v in boxes[best].tolist())
            left = (cx - bw / 2) * side
            top = (cy - bh / 2) * side
            out.append(
                DetectedBox(
                    label=prompt,
                    score=score,
                    bbox={
                        "x": round(max(left, 0.0) / width, 6),
                        "y": round(max(top, 0.0) / height, 6),
                        "w": round(min(bw * side, width) / width, 6),
                        "h": round(min(bh * side, height) / height, 6),
                    },
                )
            )
        return out

    async def detect(self, image: bytes, prompts: list[str]) -> list[DetectedBox]:
        if not prompts:
            return []
        try:
            async with self._lock:  # 权重只加载一次；并发首帧不会各加载一份
                if self._loaded is None:
                    self._loaded = await asyncio.to_thread(self._load)
            return await asyncio.to_thread(self._detect_sync, image, prompts)
        except Exception:  # noqa: BLE001 - 按协议：检测失败降级为「这帧没框」，不阻塞感知
            return []
