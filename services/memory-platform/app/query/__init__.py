"""查询与纠正 API。"""
from __future__ import annotations

import base64
import binascii
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..llm.base import LLMClient
from ..memory.events import append_event, latest_valid_event, record_audit
from ..memory.projections import recompute_projection
from ..models import Entity, EvidenceItem, FrameAsset, MemoryEvent, StateProjection, utcnow
from ..schemas import (
    AudioSearchHit,
    CorrectRequest,
    CorrectResponse,
    EntityRef,
    FindObjectResponse,
    SceneSearchHit,
    SceneSearchRequest,
    SceneSearchResponse,
    TimelineEntry,
    TimelineResponse,
)
from ..vision.base import VisionEncoder
from .visual import visual_search_frames
from .where_is import _retrieve_transcripts, translate_query_for_clip, where_is

router = APIRouter(prefix="/v1/memory", tags=["query"])


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
) -> FindObjectResponse:
    resp = await where_is(session, name=name, deep=deep, llm=llm, vision=vision)
    await record_audit(
        session,
        actor="user:owner",
        action="query",
        target=f"where-is:{name}",
        detail={"channel": resp.channel, "confidence": resp.confidence, "deep": deep},
    )
    await session.commit()
    return resp


@router.post("/scene-search", response_model=SceneSearchResponse)
async def scene_search_endpoint(
    req: SceneSearchRequest,
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
    vision: VisionEncoder = Depends(get_vision),
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
                evidence_url=f"/v1/memory/frames/{frame.id}/evidence" if alive else None,
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
        actor="user:owner",
        action="query",
        target=f"scene-search:{req.query_text or '<image>'}",
        detail={
            "has_image_query": query_image is not None,
            "top_k": req.top_k,
            "n_hits": len(items),
            "n_audio_hits": len(audio_items),
        },
    )
    await session.commit()
    return SceneSearchResponse(
        query_text=req.query_text,
        has_image_query=query_image is not None,
        hits=items,
        audio_hits=audio_items,
    )


@router.get("/frames/{frame_asset_id}/evidence")
async def frame_evidence_endpoint(
    frame_asset_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> Response:
    """读取帧的原始证据媒体（TTL 删除后 404；长期表示 caption/向量不受影响）。"""
    frame = await session.get(FrameAsset, frame_asset_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="frame 不存在")
    item = await _evidence_item_of(session, frame)
    if not _evidence_alive(item):
        raise HTTPException(status_code=404, detail="证据媒体已过期删除")
    return Response(content=Path(item.storage_ref).read_bytes(), media_type="image/jpeg")


@router.get("/objects/{entity_id}/timeline", response_model=TimelineResponse)
async def timeline_endpoint(
    entity_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> TimelineResponse:
    entity = await session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="entity 不存在")
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
    req: CorrectRequest, session: AsyncSession = Depends(get_session)
) -> CorrectResponse:
    """纠正不改历史：写 USER_CORRECTION 事件（supersedes 旧事件）→ 重算投影。"""
    entity = await session.get(Entity, req.entity_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="entity 不存在")

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
        actor="user:owner",
        action="correct",
        target=f"entity:{req.entity_id}",
        detail={
            "field": req.field,
            "value": req.value,
            "reason": req.reason,
            "supersedes_event_id": str(old.id) if old else None,
        },
    )
    await session.commit()
    proj = await recompute_projection(session, entity_id=req.entity_id)
    return CorrectResponse(
        event_id=event.id,
        superseded_event_id=old.id if old else None,
        projection=proj.state,
    )
