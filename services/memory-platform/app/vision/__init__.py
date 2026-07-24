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


__all__ = [
    "FakeVisionEncoder",
    "HTTPVisionEncoder",
    "NullVisionEncoder",
    "VisionEncoder",
    "build_vision_encoder",
]
