"""帧 OCR → 脱敏文本区域：可独立重试的 outbox 任务（topic=frame.ocr）。

这条通道回答的是「这东西自己写着它是什么」。
身份证、银行卡、快递单、书脊、药盒——它们的身份印在自己身上，OCR 命中的是字面量。
另外两条路都够不着：卡面上的字在整图缩到 224 之后不足一个 patch（帧向量），
caption 只会说"桌上有一些卡片"（VLM 只报显著物体）。所以这不是锦上添花的第四路，
而是这一类物体唯一能被搜到的方式。

为什么必须在摄入期做完：证据 TTL 默认 15 分钟就把原图删了，过期帧补不回来。

⚠️ 写库的一律是脱敏文本（app/ocr/redact.py）。原图短命而这张表长期，
明文 PII 入库等于把整个隐私模型反过来。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import EvidenceItem, FrameAsset, FrameRegion, OutboxEvent
from ..ocr.base import TextRecognizer
from ..ocr.redact import redact_pii

TOPIC = "frame.ocr"

# 一帧只写一条 OCR 区域（整帧文本），region_key 固定 → 天然幂等。
# 不按文本块逐条建行是因为块的切分随模型版本漂移，键会跟着变，重跑就重复入库；
# 而检索要的本来就是"这一帧上有没有这些字"，块级 bbox 留给后续高亮再说。
REGION_KEY = "ocr:frame"


class OCRRetryable(RuntimeError):
    """暂时性失败：交给 outbox 退避重试（引擎没就绪 / 权重还在下载）。"""


def enqueue_ocr(session: AsyncSession, frame_asset_id: uuid.UUID) -> None:
    session.add(OutboxEvent(topic=TOPIC, payload={"frame_asset_id": str(frame_asset_id)}))


async def ocr_frame_asset(
    session: AsyncSession,
    *,
    frame_asset_id: uuid.UUID,
    recognizer: TextRecognizer | None = None,
) -> str | None:
    """给单帧跑 OCR，写入脱敏文本区域。返回写入的文本（无文字/跳过时 None）。

    recognizer 留空时取进程内单例（权重只加载一次）；测试可注入 Fake。
    幂等：已有 OCR 区域直接返回。媒体已删属于永久失败，直接消费掉；
    引擎返回 None 属于暂时失败，抛 OCRRetryable 走退避——与 vectorize/regionize 同语义。
    """
    settings = get_settings()
    if recognizer is None:
        from ..ocr import get_text_recognizer  # 局部 import：worker 起进程时不加载权重

        recognizer = get_text_recognizer(settings)

    frame = await session.get(FrameAsset, frame_asset_id)
    if frame is None:
        return None

    existing = await session.scalar(
        select(FrameRegion).where(
            FrameRegion.frame_asset_id == frame_asset_id,
            FrameRegion.region_key == REGION_KEY,
        )
    )
    if existing is not None:
        return existing.ocr_text

    item = await session.get(EvidenceItem, frame.evidence_item_id)
    if item is None or item.retention_state != "ACTIVE" or not item.storage_ref:
        return None
    path = Path(item.storage_ref)
    if not path.exists():
        return None  # TTL 已物理删除：永久没有输入了，别再重试

    blocks = await recognizer.recognize(path.read_bytes())
    if blocks is None:
        # 协议规定失败返回 None 而不是抛异常——这里必须自己把它转成可重试信号，
        # 否则任务会被当成「这张图没字」消费掉，而它其实只是引擎还没就绪。
        raise OCRRetryable(f"OCR 引擎未返回结果：frame={frame_asset_id}")

    raw = " ".join(b.text.strip() for b in blocks if b.text.strip())
    if not raw:
        return None  # 画面里确实没字：不写空行，省得把索引撑大

    text = redact_pii(raw).text if settings.ocr_redact_pii else raw
    text = text[: max(settings.ocr_max_chars, 0)]
    if not text:
        return None

    # bbox 取所有文本块的外接框：粗，但足够回答"字大概在画面哪一带"
    xs0 = [b.bbox.get("x", 0.0) for b in blocks if b.bbox]
    ys0 = [b.bbox.get("y", 0.0) for b in blocks if b.bbox]
    xs1 = [b.bbox.get("x", 0.0) + b.bbox.get("w", 0.0) for b in blocks if b.bbox]
    ys1 = [b.bbox.get("y", 0.0) + b.bbox.get("h", 0.0) for b in blocks if b.bbox]
    bbox = (
        {
            "x": round(min(xs0), 6),
            "y": round(min(ys0), 6),
            "w": round(max(xs1) - min(xs0), 6),
            "h": round(max(ys1) - min(ys0), 6),
        }
        if xs0 and ys0
        else {}
    )

    session.add(
        FrameRegion(
            frame_asset_id=frame_asset_id,
            region_key=REGION_KEY,
            source="ocr",
            bbox=bbox,
            ocr_text=text,
            score=max((b.score for b in blocks), default=None),
        )
    )
    await session.commit()
    return text


async def enqueue_missing_ocr(session: AsyncSession, *, limit: int = 200) -> list[uuid.UUID]:
    """把「媒体还在但没跑过 OCR」的帧补进 outbox，返回本次入队的帧 id。

    TTL 已删的帧补不回来——这也是为什么 OCR 要放在摄入期，而不是等查不到再回头扫。
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
    done = set(
        (
            await session.scalars(
                select(FrameRegion.frame_asset_id).where(FrameRegion.source == "ocr")
            )
        ).all()
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
        if frame_id in done or str(frame_id) in pending:
            continue
        if not Path(storage_ref).exists():
            continue
        enqueue_ocr(session, frame_id)
        queued.append(frame_id)
    if queued:
        await session.commit()
    return queued
