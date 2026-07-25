"""视觉编码器工厂：按 settings.vision_provider 构造，失败一律降级 NullVisionEncoder。

provider：
- none  → NullVisionEncoder（默认；视觉检索整体关闭，系统行为与旧版一致）
- fake  → FakeVisionEncoder（演示/冒烟；测试一般直接注入实例）
- local → LocalCLIPEncoder（本机 open_clip；未装可选依赖时降级 none）
- http  → HTTPVisionEncoder（边缘 sidecar；未配 base_url 时降级 none）
"""
from __future__ import annotations

from ..config import Settings
from .base import NullVisionEncoder, VisionEncoder
from .detect import DetectedBox, NullObjectDetector, ObjectDetector
from .fake import FakeVisionEncoder
from .http_client import HTTPVisionEncoder


def build_vision_encoder(settings: Settings) -> VisionEncoder:
    """按配置构造视觉编码器；none 或构造失败时返回恒 None 的降级实现。"""
    provider = (settings.vision_provider or "none").lower()
    if provider == "fake":
        return FakeVisionEncoder(dim=settings.vision_dim)
    if provider == "local":
        try:
            from .clip_local import LocalCLIPEncoder

            return LocalCLIPEncoder(
                model_name=settings.vision_model,
                pretrained=settings.vision_pretrained,
                prefer_hf_hub=settings.vision_prefer_hf_hub,
            )
        except Exception:  # noqa: BLE001 - 可选依赖缺失/模型加载失败 → 降级
            return NullVisionEncoder(dim=settings.vision_dim)
    if provider == "http":
        if not settings.vision_base_url:
            return NullVisionEncoder(dim=settings.vision_dim)
        return HTTPVisionEncoder(
            base_url=settings.vision_base_url,
            api_key=settings.vision_api_key,
            dim=settings.vision_dim,
            timeout=settings.vision_timeout_seconds,
        )
    return NullVisionEncoder(dim=settings.vision_dim)


def build_object_detector(settings: Settings) -> ObjectDetector:
    """按配置构造开放词表检测器；none 或构造失败时返回恒空的降级实现。

    与 build_vision_encoder 同一套语义：可选依赖（transformers）缺失不是错误，
    只是「这套部署没有物件缩略图」——全览页照旧显示纯色球。
    """
    provider = (settings.detector_provider or "none").lower()
    if provider == "local":
        try:
            from .owl_local import LocalOwlDetector

            return LocalOwlDetector(
                model_name=settings.detector_model,
                score_threshold=settings.detector_score_threshold,
                device=settings.detector_device,
            )
        except Exception:  # noqa: BLE001 - 可选依赖缺失/模型加载失败 → 降级
            return NullObjectDetector()
    return NullObjectDetector()


_detector_cache: dict[tuple[str, str, str], ObjectDetector] = {}


def get_object_detector(settings: Settings) -> ObjectDetector:
    """进程内单例检测器（按 provider/model/device 缓存）。

    必须是单例：OWLv2 权重 1.4GB，按任务构造等于每帧重新加载一次模型——
    那不是慢一点，是彻底跑不动。这也是它不像 vision 那样一路当参数传的原因：
    传参会让每个调用点都有机会构造出第二份权重。
    """
    key = (
        (settings.detector_provider or "none").lower(),
        settings.detector_model,
        settings.detector_device,
    )
    if key not in _detector_cache:
        _detector_cache[key] = build_object_detector(settings)
    return _detector_cache[key]


__all__ = [
    "DetectedBox",
    "FakeVisionEncoder",
    "HTTPVisionEncoder",
    "NullObjectDetector",
    "NullVisionEncoder",
    "ObjectDetector",
    "VisionEncoder",
    "build_object_detector",
    "build_vision_encoder",
    "get_object_detector",
]
