"""图像归一化：iPhone 的 HEIC/HEIF 转成下游全链路都能读的 JPEG。

为什么要在入库边界就转，而不是各处按需解码：
落盘之后这份字节会被四个互不相干的消费者读到——phash 去重、VLM caption、
CLIP 视觉向量、前端 <img> 直接渲染。只要存的是 HEIC，这四处就得各自记得
「先注册 HEIF 解码器」，漏一处就是一种沉默的坏法（phash 抛 500 丢整个信封、
CLIP 静默返回 None 让这帧永远检索不到、浏览器显示裂图）。在边界转一次，
下游拿到的永远是 JPEG，四个消费者一个都不用改。

原图不会丢：设备端/数据集里的 HEIC 原件不归本服务管，这里存的是证据副本。
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

# 下游直接消费的格式：浏览器能渲染、PIL 能读、CLIP/VLM 能吃，无需转码。
PASSTHROUGH_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "GIF", "BMP"})

_heif_registered: bool | None = None


def register_heif_opener() -> bool:
    """幂等注册 pillow-heif。返回是否可解 HEIF。

    没装 pillow-heif 不算致命错误：JPEG/PNG 链路照常，只有 HEIC 走不通，
    而那种情况下 normalize_image 会退回原样落盘（见 UnidentifiedImageError 分支）。
    """
    global _heif_registered
    if _heif_registered is not None:
        return _heif_registered
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        _heif_registered = True
    except Exception:  # noqa: BLE001 - 缺依赖/装错平台都只降级，不该炸启动
        _heif_registered = False
    return _heif_registered


def is_heif_supported() -> bool:
    return register_heif_opener()


def open_image(source: str | Path | bytes) -> Image.Image:
    """统一的 Image.open 入口：保证 HEIF 解码器已注册。

    直接用 PIL.Image.open 的地方都应该换成它，否则 HEIC 会 UnidentifiedImageError。
    """
    register_heif_opener()
    if isinstance(source, bytes):
        return Image.open(io.BytesIO(source))
    return Image.open(source)


@dataclass(frozen=True)
class NormalizedImage:
    """归一化结果。converted=False 表示原样透传（本来就是通用格式，或压根解不开）。"""

    data: bytes
    filename: str
    media_type: str
    converted: bool
    source_format: str | None = None
    width: int | None = None
    height: int | None = None

    @property
    def decodable(self) -> bool:
        return self.source_format is not None


def _target_name(filename: str | None, *, suffix: str) -> str:
    stem = Path(filename).stem if filename else "frame"
    return f"{stem or 'frame'}{suffix}"


def normalize_image(
    data: bytes,
    *,
    filename: str | None = None,
    jpeg_quality: int = 90,
    max_side: int = 0,
) -> NormalizedImage:
    """把任意图片字节归一成下游通用格式。

    - 已是 JPEG/PNG/WEBP 等：原样返回（不重编码，避免无谓的代损）
    - HEIC/HEIF 等：转 JPEG，EXIF 方向烘进像素（CLIP/VLM 看的是像素，不看 EXIF 标签）
    - 解不开：原样返回且 source_format=None，由调用方决定怎么降级

    max_side>0 时长边缩到该值；默认 0 = 保留原分辨率（证据副本应保真，
    VLM 那侧另有 vlm_image_max_side 在发送时缩图）。
    """
    register_heif_opener()
    try:
        with Image.open(io.BytesIO(data)) as probe:
            source_format = (probe.format or "").upper()
            probe.load()
            image = ImageOps.exif_transpose(probe) or probe
            needs_resize = max_side > 0 and max(image.size) > max_side
            if source_format in PASSTHROUGH_FORMATS and not needs_resize:
                return NormalizedImage(
                    data=data,
                    filename=Path(filename).name if filename else "frame.jpg",
                    media_type=Image.MIME.get(source_format, "application/octet-stream"),
                    converted=False,
                    source_format=source_format,
                    width=image.width,
                    height=image.height,
                )
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            if needs_resize:
                image.thumbnail((max_side, max_side), Image.LANCZOS)
            buf = io.BytesIO()
            # exif_transpose 已把 orientation 归位，这里带上剩余 EXIF（拍摄时间/机型）不至于丢元数据
            save_kwargs = {"format": "JPEG", "quality": jpeg_quality, "optimize": True}
            exif = image.info.get("exif")
            if exif:
                save_kwargs["exif"] = exif
            image.save(buf, **save_kwargs)
            return NormalizedImage(
                data=buf.getvalue(),
                filename=_target_name(filename, suffix=".jpg"),
                media_type="image/jpeg",
                converted=True,
                source_format=source_format,
                width=image.width,
                height=image.height,
            )
    except (UnidentifiedImageError, OSError, ValueError):
        # 解不开就别自作主张改字节：原样落盘，让证据可事后取证，感知阶段自然会跳过。
        return NormalizedImage(
            data=data,
            filename=Path(filename).name if filename else "frame.bin",
            media_type="application/octet-stream",
            converted=False,
            source_format=None,
        )
