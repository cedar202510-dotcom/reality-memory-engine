"""where-is 双通道查询。

通道 1（已知实体，O(1)）：名称/别名/trgm 命中实体 → 读 state_projections.last_seen。
通道 2（首次被问）：多路混合召回（文本向量/trgm 降级 + CLIP 视觉跨模态 + 语音转写，加权融合）
  top-K → Answerer 精判 → 回答并回写 MemoryCandidate(source=query)；
  置信度足够则经候选门升级为实体。无视觉/转写路时自动退回纯文本路（旧行为）。
"""
from __future__ import annotations

import base64
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Text, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..llm.base import LLMClient
from ..memory.gate import evaluate_candidate
from ..memory.seed import get_default_household_id
from ..models import (
    AudioAsset,
    Entity,
    EvidenceItem,
    FrameAsset,
    MemoryCandidate,
    MemoryEvent,
    StateProjection,
    utcnow,
)
from ..schemas import EntityRef, FindObjectResponse, LocationAlternative
from ..vision.base import VisionEncoder
from .answerer import AnswerInput, build_answerer
from .visual import fuse_rankings, visual_search_frames


def freshness_text(last_seen: datetime | None) -> str | None:
    """"最后一次看到是 … 前"式新鲜度表述。"""
    if last_seen is None:
        return None
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    delta = utcnow() - last_seen
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        human = f"{seconds} 秒"
    elif seconds < 3600:
        human = f"{seconds // 60} 分钟"
    elif seconds < 86400:
        human = f"{seconds // 3600} 小时"
    else:
        human = f"{seconds // 86400} 天"
    return f"最后一次看到是 {human}前"


async def _match_entity(
    session: AsyncSession, *, household_id: uuid.UUID, name: str
) -> Entity | None:
    exact = await session.scalar(
        select(Entity).where(
            Entity.household_id == household_id,
            or_(
                func.lower(Entity.canonical_name) == name.lower(),
                Entity.aliases.contains([name]),
            ),
        )
    )
    if exact is not None:
        return exact
    # trgm 模糊兜底
    row = (
        await session.execute(
            select(Entity, func.similarity(Entity.canonical_name, name).label("sim"))
            .where(Entity.household_id == household_id, Entity.canonical_name.op("%")(name))
            .order_by(func.similarity(Entity.canonical_name, name).desc())
            .limit(1)
        )
    ).first()
    return row[0] if row else None


async def _channel_projection(
    session: AsyncSession, *, household_id: uuid.UUID, name: str
) -> FindObjectResponse | None:
    entity = await _match_entity(session, household_id=household_id, name=name)
    if entity is None:
        return None
    proj = await session.scalar(
        select(StateProjection).where(
            StateProjection.entity_id == entity.id,
            StateProjection.projection_type == "last_seen",
        )
    )
    state = (proj.state if proj else {}) or {}
    location = state.get("location")
    last_seen_raw = state.get("last_seen_time")
    last_seen = datetime.fromisoformat(last_seen_raw) if last_seen_raw else None
    confidence = float(state.get("confidence", 0.0))

    # alternatives：该实体历史上的其它位置（最多 3 个）
    events = list(
        (
            await session.scalars(
                select(MemoryEvent)
                .where(MemoryEvent.entity_id == entity.id)
                .order_by(MemoryEvent.event_time_from.desc())
            )
        ).all()
    )
    seen: set[str] = set()
    alternatives: list[LocationAlternative] = []
    for ev in events:
        loc = (ev.payload or {}).get("location")
        if loc and loc != location and loc not in seen:
            seen.add(loc)
            alternatives.append(
                LocationAlternative(
                    location=loc,
                    last_seen_time=ev.event_time_from,
                    confidence=float((ev.confidence or {}).get("aggregate", 0.5)),
                )
            )
        if len(alternatives) >= 3:
            break

    ref = EntityRef(id=entity.id, canonical_name=entity.canonical_name, aliases=entity.aliases)
    fresh = freshness_text(last_seen)
    if location is None:
        return FindObjectResponse(
            query=name,
            channel="projection",
            entity=ref,
            confidence=confidence,
            answer_text=f"认识「{entity.canonical_name}」，但当前没有有效的位置记忆（可能刚被遗忘）。",
            timeline_url=f"/v1/memory/objects/{entity.id}/timeline",
        )
    return FindObjectResponse(
        query=name,
        channel="projection",
        entity=ref,
        location=location,
        last_seen_time=last_seen,
        freshness=fresh,
        confidence=confidence,
        answer_text=f"{entity.canonical_name}{fresh or ''}，在{location}。",
        alternatives=alternatives,
        timeline_url=f"/v1/memory/objects/{entity.id}/timeline",
    )


async def _retrieve_frames_text(
    session: AsyncSession, *, llm: LLMClient, name: str, top_k: int
) -> list[tuple[FrameAsset, float]]:
    """文本路召回：向量检索优先（分数=余弦相似度）；无 embedding 配置时降级
    pg_trgm word_similarity（分数即相似度，天然 ∈ [0,1]）。"""
    vectors = await llm.embed([name])
    if vectors:
        distance = FrameAsset.embedding.cosine_distance(vectors[0]).label("dist")
        rows = (
            await session.execute(
                select(FrameAsset, distance)
                .where(FrameAsset.embedding.is_not(None))
                .order_by(distance)
                .limit(top_k)
            )
        ).all()
        return [(frame, 1.0 - float(dist)) for frame, dist in rows]
    # 降级：pg_trgm word_similarity 模糊匹配为主，ilike 包含兜底保证命中率
    text_expr = FrameAsset.caption + " " + func.cast(FrameAsset.scene_tags, Text)
    similarity = func.word_similarity(name, text_expr).label("sim")
    rows = (
        await session.execute(
            select(FrameAsset, similarity)
            .where(
                (func.word_similarity(name, text_expr) > 0)
                | text_expr.ilike(f"%{name}%")
            )
            .order_by(func.word_similarity(name, text_expr).desc())
            .limit(top_k)
        )
    ).all()
    return [(frame, float(sim)) for frame, sim in rows]


async def _retrieve_transcripts(
    session: AsyncSession, *, llm: LLMClient, name: str, top_k: int
) -> list[tuple[AudioAsset, float]]:
    """语音转写路召回：向量检索优先（分数=余弦相似度）；无 embedding 配置时降级
    pg_trgm word_similarity（分数即相似度，天然 ∈ [0,1]）。"""
    vectors = await llm.embed([name])
    if vectors:
        distance = AudioAsset.embedding.cosine_distance(vectors[0]).label("dist")
        rows = (
            await session.execute(
                select(AudioAsset, distance)
                .where(AudioAsset.embedding.is_not(None))
                .order_by(distance)
                .limit(top_k)
            )
        ).all()
        return [(audio, 1.0 - float(dist)) for audio, dist in rows]
    # 降级：pg_trgm word_similarity 模糊匹配为主，ilike 包含兜底保证命中率
    similarity = func.word_similarity(name, AudioAsset.transcript).label("sim")
    rows = (
        await session.execute(
            select(AudioAsset, similarity)
            .where(
                (func.word_similarity(name, AudioAsset.transcript) > 0)
                | AudioAsset.transcript.ilike(f"%{name}%")
            )
            .order_by(func.word_similarity(name, AudioAsset.transcript).desc())
            .limit(top_k)
        )
    ).all()
    return [(audio, float(sim)) for audio, sim in rows]


async def _recall_channel2(
    session: AsyncSession,
    *,
    llm: LLMClient,
    name: str,
    top_k: int,
    vision: VisionEncoder | None = None,
) -> tuple[list[FrameAsset], list[AudioAsset]]:
    """通道 2 多路混合召回：帧文本路 + 视觉路（CLIP 跨模态）+ 语音转写路。

    三路分数各自归一化到 [0,1] 后按配置权重加权融合，合并去重取 top_k；
    按融合顺序拆回帧与语音两类资产。无视觉/转写命中时行为与旧版纯文本路一致。
    """
    settings = get_settings()
    text_hits = await _retrieve_frames_text(session, llm=llm, name=name, top_k=top_k)

    visual_hits: list[tuple[FrameAsset, float]] = []
    if vision is not None:
        visual_hits = await visual_search_frames(
            session,
            vision=vision,
            query_text=name,
            top_k=settings.retrieval_visual_top_k,
        )
    transcript_hits = await _retrieve_transcripts(session, llm=llm, name=name, top_k=top_k)

    if not visual_hits and not transcript_hits:
        return [frame for frame, _ in text_hits], []  # 仅文本路（旧行为）

    fused = fuse_rankings(
        text_hits=[(f.id, s) for f, s in text_hits],
        visual_hits=[(f.id, s) for f, s in visual_hits],
        visual_weight=settings.retrieval_fusion_visual_weight,
        transcript_hits=[(a.id, s) for a, s in transcript_hits],
        transcript_weight=settings.retrieval_fusion_transcript_weight,
        top_k=top_k,
    )
    frame_by_id = {f.id: f for f, _ in text_hits + visual_hits}
    audio_by_id = {a.id: a for a, _ in transcript_hits}
    frames = [frame_by_id[fid] for fid, _ in fused if fid in frame_by_id]
    audios = [audio_by_id[fid] for fid, _ in fused if fid in audio_by_id]
    return frames, audios


async def _retrieve_frames(
    session: AsyncSession,
    *,
    llm: LLMClient,
    name: str,
    top_k: int,
    vision: VisionEncoder | None = None,
) -> list[FrameAsset]:
    """多路混合检索（帧部分）：文本路（embedding/trgm 降级）+ 视觉路 + 语音转写路融合。"""
    frames, _ = await _recall_channel2(
        session, llm=llm, name=name, top_k=top_k, vision=vision
    )
    return frames


async def _channel_deep_retrieval(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    name: str,
    llm: LLMClient,
    vision: VisionEncoder | None = None,
) -> FindObjectResponse:
    settings = get_settings()
    frames, audios = await _recall_channel2(
        session, llm=llm, name=name, top_k=settings.retrieval_top_k, vision=vision
    )
    if not frames and not audios:
        return FindObjectResponse(
            query=name,
            channel="not_found",
            confidence=0.0,
            answer_text=f"没有任何场景或语音记录，暂时无法回答「{name}」在哪里。",
        )

    # 证据未删的帧带图精判（媒体短命：删了就只剩 caption/转写）
    images: list[str] = []
    lines: list[str] = []
    for f in frames:
        item = await session.get(EvidenceItem, f.evidence_item_id)
        has_image = bool(
            item
            and item.retention_state == "ACTIVE"
            and item.storage_ref
            and Path(item.storage_ref).exists()
        )
        lines.append(
            f"- [{f.captured_at.isoformat()}] {f.caption}（tags: {'、'.join(f.scene_tags or [])}）"
            + ("【附图】" if has_image else "")
        )
        if has_image and len(images) < 4:
            images.append(
                "data:image/jpeg;base64,"
                + base64.b64encode(Path(item.storage_ref).read_bytes()).decode()
            )
    for a in audios:
        lines.append(f"- [{a.captured_at.isoformat()}] 语音转写：「{a.transcript}」")

    answerer = build_answerer(llm)
    ans = await answerer.run(
        AnswerInput(query_name=name, candidates_text="\n".join(lines)),
        images=images or None,
    )
    if ans is None:
        return FindObjectResponse(
            query=name,
            channel="deep_retrieval",
            confidence=0.0,
            answer_text="精判阶段输出不合契约，本次无法给出答案。",
        )

    # 回写候选（被查询过的物体 → 候选；aggregate 足够则经候选门升级为实体）
    latest_frame_time = max([f.captured_at for f in frames] + [a.captured_at for a in audios])
    confidence = {
        "model": ans.confidence,
        "identity": ans.confidence,
        "spatial": ans.confidence if ans.found else 0.0,
        "temporal": 0.8,
        "policy": 1.0,
        "aggregate": ans.confidence,
    }
    candidate = MemoryCandidate(
        observation_ids=[],
        event_type="OBJECT_OBSERVED_AT",
        payload={"object_text": name, "location": ans.location} if ans.found else {"object_text": name},
        confidence=confidence,
        status="PENDING",
        source="query",
    )
    session.add(candidate)
    await session.flush()
    obj_vec = await llm.embed([name])
    # 取最相关且带视觉向量的帧，供实体解析做物体级合并
    frame_vec = next((f.visual_embedding for f in frames if f.visual_embedding is not None), None)
    await evaluate_candidate(
        session,
        candidate=candidate,
        household_id=household_id,
        phenomenon_time=latest_frame_time,
        observed_at=latest_frame_time,
        object_embedding=obj_vec[0] if obj_vec else None,
        frame_visual_embedding=frame_vec,
    )
    await session.commit()

    if not ans.found:
        return FindObjectResponse(
            query=name,
            channel="not_found",
            confidence=ans.confidence,
            answer_text=ans.answer_text or f"没有在用过的场景里找到「{name}」。",
        )

    entity_ref = None
    if candidate.entity_id:
        ent = await session.get(Entity, candidate.entity_id)
        if ent:
            entity_ref = EntityRef(id=ent.id, canonical_name=ent.canonical_name, aliases=ent.aliases)
    fresh = freshness_text(latest_frame_time)
    return FindObjectResponse(
        query=name,
        channel="deep_retrieval",
        entity=entity_ref,
        location=ans.location,
        last_seen_time=latest_frame_time,
        freshness=fresh,
        confidence=ans.confidence,
        answer_text=ans.answer_text or f"{name}{fresh or ''}，在{ans.location}。",
        timeline_url=(
            f"/v1/memory/objects/{candidate.entity_id}/timeline" if candidate.entity_id else None
        ),
    )


async def where_is(
    session: AsyncSession,
    *,
    name: str,
    deep: bool,
    llm: LLMClient,
    vision: VisionEncoder | None = None,
) -> FindObjectResponse:
    household_id = await get_default_household_id(session)
    if not deep:
        resp = await _channel_projection(session, household_id=household_id, name=name)
        if resp is not None and resp.location is not None:
            return resp
        if resp is not None and resp.entity is not None:
            return resp  # 认识实体但无有效位置（如刚遗忘）→ 不走通道 2，避免"遗忘后又想起来"
    return await _channel_deep_retrieval(
        session, household_id=household_id, name=name, llm=llm, vision=vision
    )
