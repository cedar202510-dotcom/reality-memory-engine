"""帧切片 → 区域级 CLIP 向量：可独立重试的 outbox 任务（topic=frame.regionize）。

为什么必须切片，而不是换个更强的模型：
CLIP 把整图缩到 224 再切 32x32 patch。一张 4032x3024 的手机照片缩放比 ~0.056——
桌上一张 400px 的身份证进模型时只剩 22px，不到一个 patch。它在帧向量里的信号被
地毯、窗帘、圈椅这些占了几十万像素的东西彻底淹没。这不是"模型不认识身份证"，
是它根本没看见；换 prompt、换更大的 VLM 都不解决，只有把检索粒度从帧降到区域才行。

切法是 SAHI（Slicing Aided Hyper Inference）那套搬到检索上：按短边等分出方形瓦片、
相邻瓦片留重叠（否则物体正好被切缝劈成两半，两片都认不出），每片单独编码。
同一张身份证在瓦片里的占比放大一个量级，才第一次跨过可辨识门槛。

全图向量不在这里存——它已经是 frame_assets.visual_embedding，检索时两者按 max 合并。
"""
from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import EvidenceItem, FrameAsset, FrameRegion, OutboxEvent
from ..vision.base import VisionEncoder

TOPIC = "frame.regionize"

# 瓦片送编码器前的长边上限：CLIP 最终只吃 224，但留一档余量（重采样质量 + 兼容
# 更高分辨率的 backbone）。1500px 的瓦片直接 base64 发 HTTP sidecar 纯属浪费。
TILE_ENCODE_MAX_SIDE = 448
TILE_ENCODE_QUALITY = 85


class RegionizeRetryable(RuntimeError):
    """暂时性失败：交给 outbox 退避重试（编码器没就绪 / 网络抖动）。"""


@dataclass(frozen=True)
class Tile:
    """一块瓦片：key 是幂等标识，box 是像素裁剪框，bbox 是归一化坐标（前端框选用）。"""

    key: str
    box: tuple[int, int, int, int]  # (left, top, right, bottom)
    bbox: dict[str, float]


def plan_tiles(
    width: int,
    height: int,
    *,
    grid: int,
    overlap: float,
    min_side: int,
    max_tiles: int,
) -> list[Tile]:
    """规划瓦片（纯函数，便于单测）。返回空列表表示这张图不值得切。

    瓦片是**方形**且边长由短边决定，而不是简单地把宽高各切 N 份：CLIP 输入是方的，
    长宽比夸张的瓦片会被压扁，反而伤语义。
    """
    if width <= 0 or height <= 0 or grid < 1:
        return []
    short = min(width, height)
    if short < min_side:
        return []  # 本来就没有分辨率可挖，切了只是把噪声编码 N 遍

    overlap = min(max(overlap, 0.0), 0.9)
    tile = max(1, round(short / grid))
    if tile >= width and tile >= height:
        return []  # 一块瓦片就覆盖全图 = 帧级向量的重复，白花一次编码

    step = max(1, round(tile * (1.0 - overlap)))

    def _starts(extent: int) -> list[int]:
        if tile >= extent:
            return [0]
        out = list(range(0, extent - tile + 1, step))
        if out[-1] != extent - tile:
            out.append(extent - tile)  # 收尾贴右/贴底，避免最后一条边永远进不了索引
        return out

    xs, ys = _starts(width), _starts(height)
    tiles = [
        Tile(
            key=f"tile:{tile}:{ix},{iy}",
            box=(x, y, min(x + tile, width), min(y + tile, height)),
            bbox={
                "x": round(x / width, 6),
                "y": round(y / height, 6),
                "w": round(min(tile, width - x) / width, 6),
                "h": round(min(tile, height - y) / height, 6),
            },
        )
        for iy, y in enumerate(ys)
        for ix, x in enumerate(xs)
    ]

    if len(tiles) > max_tiles:
        # 均匀抽稀而不是截前 N：全景图截前 N 会让右半张永远进不了索引，
        # 而且外部完全看不出来——搜不到时只会以为"没拍到"。
        stride = len(tiles) / max_tiles
        tiles = [tiles[int(i * stride)] for i in range(max_tiles)]
    return tiles


def load_display_image(path: Path) -> Image.Image:
    """读图并把 EXIF 方向烘进像素，得到"用户看到的那张图"。

    为什么必须转正：入库归一化只对**转码过**的图烘方向，原样透传的 JPEG 仍带
    orientation 标签，而前端 <img> 是会应用它的。不转正的话 bbox 坐标系和用户
    看到的画面不一致——框会画在错误的位置，而且横竖颠倒时切法本身都是错的。
    """
    from ..media import open_image

    with open_image(path) as raw:
        return (ImageOps.exif_transpose(raw) or raw).convert("RGB")


def crop_tiles(image: Image.Image, tiles: list[Tile]) -> list[bytes]:
    """按瓦片裁图并缩到编码尺寸，返回 JPEG 字节（顺序与 tiles 一致）。"""
    out: list[bytes] = []
    for tile in tiles:
        crop = image.crop(tile.box)
        crop.thumbnail((TILE_ENCODE_MAX_SIDE, TILE_ENCODE_MAX_SIDE))
        buf = io.BytesIO()
        crop.save(buf, format="JPEG", quality=TILE_ENCODE_QUALITY)
        out.append(buf.getvalue())
    return out


def enqueue_regionize(session: AsyncSession, frame_asset_id: uuid.UUID) -> None:
    session.add(OutboxEvent(topic=TOPIC, payload={"frame_asset_id": str(frame_asset_id)}))


async def regionize_frame_asset(
    session: AsyncSession,
    *,
    frame_asset_id: uuid.UUID,
    vision: VisionEncoder | None,
) -> int:
    """给单帧切片并写区域向量，返回新写入的区域数。

    幂等：已存在的 region_key 跳过（重复入队/回填不会重复编码）。
    媒体已删/解不开属于永久失败，直接消费掉；编码器返回 None 属于暂时失败，
    抛 RegionizeRetryable 走 outbox 退避——与 vectorize 同一套语义。
    """
    settings = get_settings()
    if vision is None or not settings.vision_tiling_enabled:
        return 0

    frame = await session.get(FrameAsset, frame_asset_id)
    if frame is None:
        return 0

    item = await session.get(EvidenceItem, frame.evidence_item_id)
    if item is None or item.retention_state != "ACTIVE" or not item.storage_ref:
        return 0
    path = Path(item.storage_ref)
    if not path.exists():
        return 0  # TTL 已物理删除：永久没有输入了，别再重试

    try:
        image = load_display_image(path)
    except (UnidentifiedImageError, OSError, ValueError):
        return 0  # 解不开就是永久失败，重试多少次都一样

    tiles = plan_tiles(
        image.width,
        image.height,
        grid=settings.vision_tile_grid,
        overlap=settings.vision_tile_overlap,
        min_side=settings.vision_tile_min_side,
        max_tiles=settings.vision_tile_max,
    )
    if not tiles:
        return 0

    existing = set(
        (
            await session.scalars(
                select(FrameRegion.region_key).where(
                    FrameRegion.frame_asset_id == frame_asset_id,
                    FrameRegion.visual_embedding.is_not(None),
                )
            )
        ).all()
    )
    pending = [t for t in tiles if t.key not in existing]
    if not pending:
        return 0

    try:
        crops = crop_tiles(image, pending)
    except (UnidentifiedImageError, OSError, ValueError):
        return 0

    vectors = await vision.embed_images(crops)
    if not vectors or len(vectors) != len(pending):
        # 编码器按契约不抛异常、失败返回 None——不自己转成可重试信号的话，这个任务
        # 会被当成「成功但没结果」消费掉，这帧的小物体就永远搜不到了。
        raise RegionizeRetryable(f"视觉编码器未返回完整区域向量：frame={frame_asset_id}")

    written = 0
    for tile, vector in zip(pending, vectors):
        if not vector:
            continue
        session.add(
            FrameRegion(
                frame_asset_id=frame_asset_id,
                region_key=tile.key,
                source="tile",
                bbox=tile.bbox,
                visual_embedding=vector,
            )
        )
        written += 1
    if written:
        await session.commit()
    return written


async def enqueue_missing_regions(session: AsyncSession, *, limit: int = 200) -> list[uuid.UUID]:
    """把「媒体还在但一个区域都没有」的帧补进 outbox，返回本次入队的帧 id。

    用于回填：切片上线之前入库的帧、以及重试次数耗尽被丢弃的帧。
    注意 TTL——默认 15 分钟就把原件删了，回填只对还留着媒体的帧有意义，
    过期帧永远补不回来（这也是为什么摄入期就该把切片做完）。
    """
    pending = set(
        (
            await session.scalars(
                select(OutboxEvent.payload["frame_asset_id"].astext).where(
                    OutboxEvent.topic == TOPIC, OutboxEvent.processed_at.is_(None)
                )
            )
        ).all()
    )
    has_regions = set(
        (await session.scalars(select(FrameRegion.frame_asset_id).distinct())).all()
    )

    rows = (
        await session.execute(
            select(FrameAsset.id, EvidenceItem.storage_ref)
            .join(EvidenceItem, FrameAsset.evidence_item_id == EvidenceItem.id)
            .where(
                EvidenceItem.retention_state == "ACTIVE",
                EvidenceItem.storage_ref.is_not(None),
            )
            .order_by(FrameAsset.created_at.desc())
            .limit(limit)
        )
    ).all()

    queued: list[uuid.UUID] = []
    for frame_id, storage_ref in rows:
        if frame_id in has_regions or str(frame_id) in pending:
            continue
        if not Path(storage_ref).exists():
            continue
        enqueue_regionize(session, frame_id)
        queued.append(frame_id)
    if queued:
        await session.commit()
    return queued
