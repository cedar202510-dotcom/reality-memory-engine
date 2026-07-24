"""查询与纠正 API。"""
from __future__ import annotations

import base64
import binascii
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import timedelta

from ..auth import GrantContext, actor_of, grant_or_owner
from ..config import get_settings
from ..db import get_session
from ..llm.base import LLMClient
from ..memory.events import append_event, latest_valid_event, record_audit
from ..memory.projections import recompute_projection
from ..memory.seed import get_default_household_id
from ..models import (
    Entity,
    EvidenceItem,
    FrameAsset,
    MemoryEvent,
    OutboxEvent,
    StateProjection,
    utcnow,
)
from ..schemas import (
    AudioSearchHit,
    CorrectRequest,
    CorrectResponse,
    EntityRef,
    FindObjectResponse,
    PreferenceHit,
    PreferenceResponse,
    RecentFrameEntry,
    RecentFramesResponse,
    SceneSearchHit,
    SceneSearchRequest,
    SceneSearchResponse,
    TimelineEntry,
    TimelineResponse,
)
from ..vision.base import VisionEncoder
from .visual import visual_search_frames
from .where_is import _match_entity, _retrieve_transcripts, translate_query_for_clip, where_is

router = APIRouter(prefix="/v1/memory", tags=["query"])


async def _household_of(session: AsyncSession, ctx: GrantContext | None):
    """请求的家庭范围：agent 从 grant 取（鉴权层隔离），owner 直通用默认家庭。"""
    if ctx is not None:
        return ctx.household_id()
    return await get_default_household_id(session)


def get_llm(request: Request) -> LLMClient:
    return request.app.state.llm


def get_vision(request: Request) -> VisionEncoder:
    return request.app.state.vision


async def _evidence_item_of(session: AsyncSession, frame: FrameAsset) -> EvidenceItem | None:
    return await session.get(EvidenceItem, frame.evidence_item_id)


def _evidence_alive(item: EvidenceItem | None) -> bool:
    """证据媒体是否仍可读（TTL 未删、路径存在）。"""
    return bool(
        item
        and item.retention_state == "ACTIVE"
        and item.storage_ref
        and Path(item.storage_ref).exists()
    )


@router.get("/objects/where-is", response_model=FindObjectResponse)
async def where_is_endpoint(
    name: str = Query(min_length=1),
    deep: bool = False,
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
    vision: VisionEncoder = Depends(get_vision),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.query.objects")),
) -> FindObjectResponse:
    household_id = await _household_of(session, ctx)
    resp = await where_is(
        session, name=name, deep=deep, llm=llm, vision=vision, household_id=household_id
    )
    await record_audit(
        session,
        actor=actor_of(ctx),
        action="query",
        target=f"where-is:{name}",
        detail={
            "channel": resp.channel,
            "confidence": resp.confidence,
            "deep": deep,
            **({"grant_id": str(ctx.grant_id)} if ctx else {}),
        },
    )
    await session.commit()
    return resp


@router.post("/scene-search", response_model=SceneSearchResponse)
async def scene_search_endpoint(
    req: SceneSearchRequest,
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
    vision: VisionEncoder = Depends(get_vision),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.query.objects")),
) -> SceneSearchResponse:
    """通用场景物件查找：文本/图片跨模态检索 frame_assets 的 CLIP 视觉向量；
    文本 query 同时检索 audio_assets 的语音转写（audio_hits）。"""
    query_image: bytes | None = None
    if req.query_image_base64:
        try:
            query_image = base64.b64decode(req.query_image_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="query_image_base64 不是合法的 base64")

    english = await translate_query_for_clip(llm, req.query_text) if req.query_text else None
    hits = await visual_search_frames(
        session,
        vision=vision,
        query_text=req.query_text,
        query_image=query_image,
        top_k=req.top_k,
        extra_query_texts=[english] if english else None,
    )

    items: list[SceneSearchHit] = []
    for frame, score in hits:
        item = await _evidence_item_of(session, frame)
        alive = _evidence_alive(item)
        items.append(
            SceneSearchHit(
                frame_asset_id=frame.id,
                captured_at=frame.captured_at,
                caption=frame.caption,
                scene_tags=frame.scene_tags or [],
                score=round(score, 6),
                evidence_available=alive,
                # 原始媒体默认不暴露给 Agent（§5）：agent 调用不给 evidence_url
                evidence_url=(
                    f"/v1/memory/frames/{frame.id}/evidence" if alive and ctx is None else None
                ),
            )
        )

    audio_items: list[AudioSearchHit] = []
    if req.query_text:
        transcript_hits = await _retrieve_transcripts(
            session, llm=llm, name=req.query_text, top_k=req.top_k
        )
        for audio, score in transcript_hits:
            item = await session.get(EvidenceItem, audio.evidence_item_id)
            audio_items.append(
                AudioSearchHit(
                    audio_asset_id=audio.id,
                    captured_at=audio.captured_at,
                    transcript=audio.transcript,
                    score=round(score, 6),
                    evidence_available=_evidence_alive(item),
                )
            )

    await record_audit(
        session,
        actor=actor_of(ctx),
        action="query",
        target=f"scene-search:{req.query_text or '<image>'}",
        detail={
            "has_image_query": query_image is not None,
            "top_k": req.top_k,
            "n_hits": len(items),
            "n_audio_hits": len(audio_items),
            **({"grant_id": str(ctx.grant_id)} if ctx else {}),
        },
    )
    await session.commit()
    return SceneSearchResponse(
        query_text=req.query_text,
        has_image_query=query_image is not None,
        hits=items,
        audio_hits=audio_items,
    )


@router.get("/frames/recent", response_model=RecentFramesResponse)
async def recent_frames_endpoint(
    limit: int = Query(default=12, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner()),
) -> RecentFramesResponse:
    """联调面板：最近摄入的帧（按拍摄时间倒序）+ 感知积压量。

    与原始证据同边界：仅 owner 可用，Agent token 一律 403（§5）。
    """
    if ctx is not None:
        raise HTTPException(status_code=403, detail="摄入明细默认不暴露给 Agent（§5）")
    frames = list(
        (
            await session.scalars(
                select(FrameAsset).order_by(FrameAsset.captured_at.desc()).limit(limit)
            )
        ).all()
    )
    entries: list[RecentFrameEntry] = []
    for frame in frames:
        alive = _evidence_alive(await _evidence_item_of(session, frame))
        entries.append(
            RecentFrameEntry(
                frame_asset_id=frame.id,
                captured_at=frame.captured_at,
                caption=frame.caption,
                scene_tags=frame.scene_tags or [],
                evidence_available=alive,
                evidence_url=f"/v1/memory/frames/{frame.id}/evidence" if alive else None,
            )
        )
    pending = (
        await session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.processed_at.is_(None), OutboxEvent.topic == "frame.process")
        )
    ) or 0
    return RecentFramesResponse(frames=entries, pending_outbox=int(pending))


@router.get("/frames/{frame_asset_id}/evidence")
async def frame_evidence_endpoint(
    frame_asset_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner()),
) -> Response:
    """读取帧的原始证据媒体（TTL 删除后 404；长期表示 caption/向量不受影响）。

    原始 Evidence 默认不暴露给 Agent（§5）：调试查看需单独短期授权，不复用 Agent token。
    """
    if ctx is not None:
        raise HTTPException(status_code=403, detail="原始证据媒体默认不暴露给 Agent（§5）")
    frame = await session.get(FrameAsset, frame_asset_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="frame 不存在")
    item = await _evidence_item_of(session, frame)
    if not _evidence_alive(item):
        raise HTTPException(status_code=404, detail="证据媒体已过期删除")
    return Response(content=Path(item.storage_ref).read_bytes(), media_type="image/jpeg")


@router.get("/objects/{entity_id}/timeline", response_model=TimelineResponse)
async def timeline_endpoint(
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.timeline.read")),
) -> TimelineResponse:
    entity = await session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="entity 不存在")
    if ctx is not None:
        ctx.require_household(entity.household_id)  # 跨家庭在鉴权层拒绝（404 不泄露存在性）
    events = list(
        (
            await session.scalars(
                select(MemoryEvent)
                .where(MemoryEvent.entity_id == entity_id)
                .order_by(MemoryEvent.event_time_from.asc(), MemoryEvent.accepted_at.asc())
            )
        ).all()
    )
    superseded_by = {e.supersedes_event_id: e.id for e in events if e.supersedes_event_id}
    proj = await session.scalar(
        select(StateProjection).where(
            StateProjection.entity_id == entity_id,
            StateProjection.projection_type == "last_seen",
        )
    )
    return TimelineResponse(
        entity=EntityRef(id=entity.id, canonical_name=entity.canonical_name, aliases=entity.aliases),
        projection=proj.state if proj else None,
        events=[
            TimelineEntry(
                event_id=e.id,
                event_type=e.event_type,
                event_time_from=e.event_time_from,
                accepted_at=e.accepted_at,
                valid_to=e.valid_to,
                payload=e.payload,
                confidence=e.confidence,
                superseded_by=superseded_by.get(e.id),
            )
            for e in events
        ],
    )


@router.post("/correct", response_model=CorrectResponse)
async def correct_endpoint(
    req: CorrectRequest,
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.correction.submit")),
) -> CorrectResponse:
    """纠正不改历史：写 USER_CORRECTION 事件（supersedes 旧事件）→ 重算投影。"""
    entity = await session.get(Entity, req.entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="entity 不存在")
    if ctx is not None:
        ctx.require_household(entity.household_id)

    old = await latest_valid_event(session, entity_id=req.entity_id)
    event = await append_event(
        session,
        entity_id=req.entity_id,
        event_type="USER_CORRECTION",
        payload={"field": req.field, "value": req.value, "reason": req.reason},
        event_time_from=utcnow(),
        observed_at=utcnow(),
        ingested_at=utcnow(),
        confidence={"model": 1.0, "identity": 1.0, "spatial": 1.0, "temporal": 1.0, "policy": 1.0, "aggregate": 0.99},
        supersedes_event_id=old.id if old else None,
    )
    await record_audit(
        session,
        actor=actor_of(ctx),
        action="correct",
        target=f"entity:{req.entity_id}",
        detail={
            "field": req.field,
            "value": req.value,
            "reason": req.reason,
            "supersedes_event_id": str(old.id) if old else None,
            **({"grant_id": str(ctx.grant_id)} if ctx else {}),
        },
    )
    await session.commit()
    proj = await recompute_projection(session, entity_id=req.entity_id)
    return CorrectResponse(
        event_id=event.id,
        superseded_event_id=old.id if old else None,
        projection=proj.state,
    )


@router.get("/preferences", response_model=PreferenceResponse)
async def preferences_endpoint(
    subject: str = Query(min_length=1),
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.query.preferences")),
) -> PreferenceResponse:
    """偏好查询：subject 匹配实体 → 该实体的 PREFERENCE_STATED 事件（含被纠正标记）。

    没有订单等外部数据源时，归因范围只到"当前实体/类别"（§8.2）——
    limitations 里明确说明，Agent 不得把类别偏好说成对具体商家的偏好。
    """
    settings = get_settings()
    household_id = await _household_of(session, ctx)
    entity = await _match_entity(session, household_id=household_id, name=subject)
    hits: list[PreferenceHit] = []
    limitations: list[str] = []
    if entity is not None:
        events = list(
            (
                await session.scalars(
                    select(MemoryEvent)
                    .where(
                        MemoryEvent.entity_id == entity.id,
                        MemoryEvent.event_type == "PREFERENCE_STATED",
                    )
                    .order_by(MemoryEvent.event_time_from.desc())
                )
            ).all()
        )
        ref = EntityRef(id=entity.id, canonical_name=entity.canonical_name, aliases=entity.aliases)
        hits = [
            PreferenceHit(
                entity=ref,
                event_id=e.id,
                payload=e.payload,
                stated_at=e.event_time_from,
                confidence=float((e.confidence or {}).get("aggregate", 0.5)),
                superseded=e.valid_to is not None,
            )
            for e in events
        ]
    if not hits:
        limitations.append(f"没有关于「{subject}」的偏好记忆。")
    else:
        limitations.append("偏好归因范围仅到该物品/类别本身，无法区分具体商家或品牌（无订单数据源）。")
    await record_audit(
        session,
        actor=actor_of(ctx),
        action="query",
        target=f"preferences:{subject}",
        detail={"n_hits": len(hits), **({"grant_id": str(ctx.grant_id)} if ctx else {})},
    )
    await session.commit()
    return PreferenceResponse(
        subject=subject,
        hits=hits,
        limitations=limitations,
        cache_until=utcnow() + timedelta(seconds=settings.query_cache_ttl_seconds),
    )
