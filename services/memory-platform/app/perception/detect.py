"""帧内物件检测 → 落盘缩略图：可独立重试的 outbox 任务（topic=frame.detect）。

这一步回答的问题是「这件东西占了哪几个像素」，而不是「这张图里有什么」。
后者 caption 和帧向量早就有了；前者没有的话，全览页每个节点只能配纯色球——
或者退而求其次配整帧/几何瓦片，可缩到节点那么小时，一张桌子的全景和另一张
桌子的全景长得一模一样，等于没配。

为什么必须在摄入期做完：证据 TTL 默认 15 分钟就把原图物理删了。裁切图是另存的
一份小图，不受 TTL 管辖，但它的**输入**受——过期之后没有原件，任何回填都补不回来。

prompt 走英文：OWLv2 的文本塔和 CLIP 一样是英文模型，中文 prompt 出的框基本是噪声。
物品名先过一遍翻译（与视觉检索复用同一个缓存），检出后 label 仍存中文原名，
因为下游是拿实体名去匹配的。
"""
from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..llm.base import LLMClient
from ..models import AtomicObservation, EvidenceItem, FrameAsset, FrameRegion, OutboxEvent
from ..vision.base import VisionEncoder
from ..vision.detect import DetectedBox
from .regions import load_display_image

TOPIC = "frame.detect"


def region_key_for(name: str) -> str:
    """物品名 → 幂等键。取哈希而不是原名：region_key 只有 64 字符，
    中文物品名 UTF-8 编码后很容易超，超了就是插入报错而不是降级。"""
    return f"detect:{hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]}"


def square_crop_box(
    bbox: dict[str, float], width: int, height: int, *, padding: float
) -> tuple[int, int, int, int]:
    """归一化框 → 正方形像素裁剪框（纯函数，便于单测）。

    补成正方形是因为节点上要套圆形遮罩：非方图套圆等于按短边中心裁一刀，
    一个横放的遥控器会被裁成中间一截，看不出是什么。先补方再套圆才是「圆形照片」。

    贴边的物体不能靠拉伸解决——超出画面就是没拍到，只能把方框整体推回画内，
    宁可背景多一点，也不能让主体偏出圆心。
    """
    x = max(float(bbox.get("x", 0.0)), 0.0)
    y = max(float(bbox.get("y", 0.0)), 0.0)
    w = max(float(bbox.get("w", 0.0)), 0.0)
    h = max(float(bbox.get("h", 0.0)), 0.0)

    left, top = x * width, y * height
    box_w, box_h = w * width, h * height
    if box_w <= 1 or box_h <= 1:
        return (0, 0, width, height)

    cx, cy = left + box_w / 2, top + box_h / 2
    side = max(box_w, box_h) * (1.0 + 2 * max(padding, 0.0))
    side = min(side, float(min(width, height)))  # 不能比画面本身还大

    half = side / 2
    cx = min(max(cx, half), width - half)   # 推回画内而不是裁掉
    cy = min(max(cy, half), height - half)
    return (
        int(round(cx - half)),
        int(round(cy - half)),
        int(round(cx + half)),
        int(round(cy + half)),
    )


def render_crop(image: Image.Image, box: tuple[int, int, int, int], *, size: int, quality: int) -> bytes:
    """裁 + 缩到固定边长的 JPEG 字节。固定边长是为了前端贴图尺寸一致。"""
    crop = image.crop(box).resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def enqueue_detect(session: AsyncSession, frame_asset_id: uuid.UUID) -> None:
    session.add(OutboxEvent(topic=TOPIC, payload={"frame_asset_id": str(frame_asset_id)}))


async def _object_names(session: AsyncSession, frame_asset_id: uuid.UUID, limit: int) -> list[str]:
    """这一帧上抽出来的物品名，去重保序。

    只查这帧自己的观察，不拿全库物品名去撒网：后者既贵（prompt 数决定不了成本上限）
    又会误检——「钥匙」在任何一张桌面照上都能被检测器凑出一个低分框。
    """
    rows = (
        await session.scalars(
            select(AtomicObservation.object_text)
            .where(
                AtomicObservation.frame_asset_id == frame_asset_id,
                AtomicObservation.object_text.is_not(None),
            )
            # confidence 是 JSONB 不是标量，排不出「更可信的排前面」；同一帧的观察
            # 时间也全一样。按名字排至少让 max_prompts 截断是确定性的（回填两次结果一致）。
            .order_by(AtomicObservation.object_text)
        )
    ).all()
    seen: dict[str, None] = {}
    for name in rows:
        cleaned = (name or "").strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)[:limit]


async def detect_frame_objects(
    session: AsyncSession,
    *,
    frame_asset_id: uuid.UUID,
    llm: LLMClient,
    vision: VisionEncoder | None,
) -> int:
    """检测单帧内的物品并落盘缩略图，返回新写入的区域数。

    幂等：已有 crop_ref 的 region_key 跳过。媒体已删/解不开属于永久失败，直接消费掉
    （与 regionize 同一套语义）——检测器不可用时同样返回 0 而不是抛，因为
    「这套部署没装检测器」不是错误，只是没有缩略图。
    """
    from ..vision import get_object_detector  # 局部 import：避免 worker 起进程就加载权重

    settings = get_settings()
    detector = get_object_detector(settings)

    frame = await session.get(FrameAsset, frame_asset_id)
    if frame is None:
        return 0
    item = await session.get(EvidenceItem, frame.evidence_item_id)
    if item is None or item.retention_state != "ACTIVE" or not item.storage_ref:
        return 0
    path = Path(item.storage_ref)
    if not path.exists():
        return 0  # TTL 已物理删除：永久没有输入了，别再重试

    names = await _object_names(session, frame_asset_id, settings.detector_max_prompts)
    if not names:
        return 0

    existing = set(
        (
            await session.scalars(
                select(FrameRegion.region_key).where(
                    FrameRegion.frame_asset_id == frame_asset_id,
                    FrameRegion.crop_ref.is_not(None),
                )
            )
        ).all()
    )
    pending = [n for n in names if region_key_for(n) not in existing]
    if not pending:
        return 0

    # 中文名 → 英文短语（失败的退回原文；检测器对中文基本无效，但空着更差）
    from ..query.where_is import translate_query_for_clip

    prompts: list[str] = []
    for name in pending:
        english = await translate_query_for_clip(llm, name)
        prompts.append(english or name)

    boxes: list[DetectedBox] = await detector.detect(path.read_bytes(), prompts)
    if not boxes:
        return 0
    # 检测器按 prompt 顺序回话，label 映射回中文原名
    by_prompt = {prompt: name for prompt, name in zip(prompts, pending)}

    try:
        image = load_display_image(path)
    except (UnidentifiedImageError, OSError, ValueError):
        return 0

    crop_root = Path(settings.crop_dir) / str(frame_asset_id)
    crop_root.mkdir(parents=True, exist_ok=True)

    written = 0
    for box in boxes:
        name = by_prompt.get(box.label, box.label)
        key = region_key_for(name)
        crop_box = square_crop_box(box.bbox, image.width, image.height, padding=settings.crop_padding)
        try:
            data = render_crop(
                image, crop_box, size=settings.crop_size, quality=settings.crop_jpeg_quality
            )
        except (OSError, ValueError):
            continue
        crop_path = crop_root / f"{key.split(':')[-1]}.jpg"
        crop_path.write_bytes(data)

        # 顺手把检测框也编一次 CLIP：它比几何瓦片更贴合物体，对小物体检索是净增益。
        # 编不出来不回滚——缩略图本身已经落盘了，向量只是附带收益。
        vector = None
        if vision is not None:
            vectors = await vision.embed_images([data])
            vector = vectors[0] if vectors else None

        session.add(
            FrameRegion(
                frame_asset_id=frame_asset_id,
                region_key=key,
                source="detect",
                bbox=box.bbox,
                label=name,
                visual_embedding=vector,
                crop_ref=str(crop_path),
                score=box.score,
            )
        )
        written += 1

    if written:
        await session.commit()
    return written
