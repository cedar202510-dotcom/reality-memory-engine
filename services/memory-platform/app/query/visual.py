"""视觉跨模态检索：文本/图片 query → 帧向量 + 区域向量 余弦 top-K。

- 文本走 vision.embed_texts、图片走 vision.embed_images（同一语义空间）。
- 无可用编码器（None / NullVisionEncoder）或无输入时返回空列表，调用方降级。
- 帧级向量看的是整张图的"氛围"，区域向量（frame_regions，切片而来）看的是局部——
  小物体只在后者里有信号。两路同在一个 CLIP 空间，按帧取 max 合并。
- fuse_rankings 为纯函数：多路召回的分数各自归一化到 [0,1] 后加权融合，便于单测。
"""
from __future__ import annotations

import math
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import FrameAsset, FrameRegion
from ..vision.base import VisionEncoder


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def _combine_vectors(vectors: list[list[float]]) -> list[float]:
    """多个 query 向量（文+图）取均值后再归一化，得到单一查询向量。"""
    dim = len(vectors[0])
    mean = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    return _l2_normalize(mean)


async def _search_regions(
    session: AsyncSession, *, query: list[float], top_k: int
) -> dict[uuid.UUID, float]:
    """区域向量检索 → 每帧取最好的那块区域的分数（帧 id → 相似度）。

    用 GROUP BY + min(distance) 而不是"取前 N 个区域再去重"：一张帧有十几块区域，
    先取 N 再去重会让少数几张"块块都像"的帧吃满名额，把真正命中的帧挤出榜。
    """
    distance = FrameRegion.visual_embedding.cosine_distance(query)
    rows = (
        await session.execute(
            select(FrameRegion.frame_asset_id, func.min(distance).label("dist"))
            .where(FrameRegion.visual_embedding.is_not(None))
            .group_by(FrameRegion.frame_asset_id)
            .order_by(func.min(distance))
            .limit(top_k)
        )
    ).all()
    return {frame_id: 1.0 - float(dist) for frame_id, dist in rows}


async def visual_search_frames(
    session: AsyncSession,
    *,
    vision: VisionEncoder | None,
    query_text: str | None = None,
    query_image: bytes | None = None,
    top_k: int,
    extra_query_texts: list[str] | None = None,
    include_regions: bool = True,
) -> list[tuple[FrameAsset, float]]:
    """跨模态视觉检索：返回 (frame, 余弦相似度) 列表，按相似度降序。

    extra_query_texts：附加查询文本（如中文查询的英文翻译），与主查询向量取均值。
    include_regions：并搜区域向量，帧分 = max(整图分, 该帧最好的区域分)。

    ⚠️ 已切片和未切片的帧不完全可比：裁出来的瓦片背景更干净，对同一 query 的相似度
    系统性地略高于整图。所以上线切片后要把存量帧回填（scripts/backfill_frame_regions.py），
    否则老帧会被新帧压着——而且表面上看不出来，只会以为"那天没拍到"。
    """
    if vision is None or (query_text is None and query_image is None) or top_k <= 0:
        return []

    query_vectors: list[list[float]] = []
    texts = [t for t in [query_text, *(extra_query_texts or [])] if t]
    if texts:
        text_vecs = await vision.embed_texts(texts)
        query_vectors.extend(text_vecs or [])
    if query_image is not None:
        image_vecs = await vision.embed_images([query_image])
        if image_vecs:
            query_vectors.append(image_vecs[0])
    if not query_vectors:
        return []

    query = _combine_vectors(query_vectors)
    distance = FrameAsset.visual_embedding.cosine_distance(query).label("dist")
    rows = (
        await session.execute(
            select(FrameAsset, distance)
            .where(FrameAsset.visual_embedding.is_not(None))
            .order_by(distance)
            .limit(top_k)
        )
    ).all()
    # pgvector cosine_distance ∈ [0, 2]；相似度 = 1 - 距离（归一化向量时 ∈ [-1, 1]）
    scored: dict[uuid.UUID, float] = {frame.id: 1.0 - float(dist) for frame, dist in rows}
    frame_by_id: dict[uuid.UUID, FrameAsset] = {frame.id: frame for frame, _ in rows}

    if include_regions:
        region_scores = await _search_regions(session, query=query, top_k=top_k)
        for frame_id, score in region_scores.items():
            # max 而不是均值：一帧里绝大多数瓦片本来就与 query 无关，取均值等于让
            # 无关区域把命中那块稀释掉——小物体刚被切出来又被平均没了。
            if score > scored.get(frame_id, float("-inf")):
                scored[frame_id] = score
        missing = [fid for fid in region_scores if fid not in frame_by_id]
        if missing:
            for frame in (
                await session.scalars(select(FrameAsset).where(FrameAsset.id.in_(missing)))
            ).all():
                frame_by_id[frame.id] = frame

    ranked = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return [(frame_by_id[fid], score) for fid, score in ranked if fid in frame_by_id]


def fuse_rankings(
    *,
    text_hits: list[tuple[uuid.UUID, float]],
    visual_hits: list[tuple[uuid.UUID, float]],
    visual_weight: float,
    top_k: int,
    transcript_hits: list[tuple[uuid.UUID, float]] | None = None,
    transcript_weight: float = 0.5,
) -> list[tuple[uuid.UUID, float]]:
    """多路混合检索融合（纯函数，便于单测）。

    各路分数各自按本路最大值归一化到 [0,1]，再加权求和：
        fused = w_text * norm(text) + w_v * norm(visual) + w_t * norm(transcript)
    文本路权重取剩余量：w_text = 1 - (有视觉命中 ? w_v : 0) - (有转写命中 ? w_t : 0)，
    因此无视觉/转写路时行为与纯文本路完全一致（向下兼容）。
    同一资产被多路命中时分数相加（天然提升多路都命中的资产），合并去重后取 top_k。
    """
    w_v = min(max(visual_weight, 0.0), 1.0)
    w_t = min(max(transcript_weight, 0.0), 1.0)

    def _normalize(hits: list[tuple[uuid.UUID, float]]) -> dict[uuid.UUID, float]:
        positives = {fid: max(score, 0.0) for fid, score in hits}
        peak = max(positives.values(), default=0.0)
        if peak <= 0:
            return {}
        return {fid: score / peak for fid, score in positives.items()}

    text_scores = _normalize(text_hits)
    visual_scores = _normalize(visual_hits)
    transcript_scores = _normalize(transcript_hits or [])

    w_text = 1.0 - (w_v if visual_scores else 0.0) - (w_t if transcript_scores else 0.0)
    w_text = min(max(w_text, 0.0), 1.0)

    fused: dict[uuid.UUID, float] = {}
    for fid, score in text_scores.items():
        fused[fid] = fused.get(fid, 0.0) + w_text * score
    for fid, score in visual_scores.items():
        fused[fid] = fused.get(fid, 0.0) + w_v * score
    for fid, score in transcript_scores.items():
        fused[fid] = fused.get(fid, 0.0) + w_t * score

    ranked = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    return ranked[:top_k]
