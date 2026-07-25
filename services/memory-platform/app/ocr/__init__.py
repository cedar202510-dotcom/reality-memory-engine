"""OCR 工厂：按 settings.ocr_provider 构造，失败一律降级 NullTextRecognizer。

provider：
- none  → NullTextRecognizer（默认；OCR 通道整体关闭，系统行为与旧版一致）
- fake  → FakeTextRecognizer（演示/冒烟；测试一般直接注入实例）
- local → LocalRapidOCR（本机 onnxruntime；未装可选依赖时降级 none）

和 detector 一样走进程内单例、而不是像 vision/asr 那样一路当参数传：
OCR 引擎构造时要加载权重，按任务构造等于每帧重新 load 一遍模型。
"""
from __future__ import annotations

from ..config import Settings
from .base import NullTextRecognizer, TextBlock, TextRecognizer
from .fake import FakeTextRecognizer
from .redact import RedactionResult, redact_pii


def build_text_recognizer(settings: Settings) -> TextRecognizer:
    """按配置构造 OCR；none 或构造失败时返回恒 None 的降级实现。"""
    provider = (settings.ocr_provider or "none").lower()
    if provider == "fake":
        return FakeTextRecognizer(default_blocks=[{"text": "示例文本", "score": 1.0}])
    if provider == "local":
        try:
            from .rapidocr_local import LocalRapidOCR

            return LocalRapidOCR(
                max_side=settings.ocr_max_side, min_score=settings.ocr_min_score
            )
        except Exception:  # noqa: BLE001 - 可选依赖缺失/模型加载失败 → 降级
            return NullTextRecognizer()
    return NullTextRecognizer()


_recognizer_cache: dict[tuple[str, int, float], TextRecognizer] = {}


def get_text_recognizer(settings: Settings) -> TextRecognizer:
    """进程内单例 OCR（按 provider/尺寸/阈值缓存）。"""
    key = (
        (settings.ocr_provider or "none").lower(),
        settings.ocr_max_side,
        settings.ocr_min_score,
    )
    if key not in _recognizer_cache:
        _recognizer_cache[key] = build_text_recognizer(settings)
    return _recognizer_cache[key]


__all__ = [
    "FakeTextRecognizer",
    "NullTextRecognizer",
    "RedactionResult",
    "TextBlock",
    "TextRecognizer",
    "build_text_recognizer",
    "get_text_recognizer",
    "redact_pii",
]
