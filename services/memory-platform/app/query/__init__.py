"""查询与纠正 API。"""
from __future__ import annotations

import base64
import binascii
import mimetypes
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import timedelta

from ..asr.base import Transcriber
from ..auth import GrantContext, actor_of, grant_or_owner
from ..config import get_settings
from ..db import get_session
from ..insight import compute_household_affinities
from ..llm.base import LLMClient
from ..memory.events import append_event, latest_valid_event, record_audit
from ..memory.gate import accept_candidate
from ..memory.projections import recompute_projection
from ..memory.seed import get_default_household_id
from ..models import (
    AtomicObservation,
    AudioAsset,
    Entity,
    EvidenceItem,
    FrameAsset,
    FrameRegion,
    MemoryCandidate,
    MemoryEvent,
    OutboxEvent,
    StateProjection,
    utcnow,
)
from ..schemas import (
    AudioSearchHit,
    ClueResolveRequest,
    ClueResolveResponse,
    CorrectRequest,
    CorrectResponse,
    EntityRef,
    FindObjectResponse,
    MemoryClueOut,
    MemoryCluesResponse,
    MemoryEventEntry,
    MemoryEventsResponse,
    ObjectGraphResponse,
    ObjectGroupOut,
    ObjectNodeOut,
    AffinityChannelOut,
    AffinityEvidenceOut,
    PreferenceHit,
    PreferenceInsightOut,
    PreferenceInsightsResponse,
    PreferenceResponse,
    MEDIA_KINDS,
    MediaItemOut,
    MediaListResponse,
    RecentFrameEntry,
    RecentFramesResponse,
    SceneSearchHit,
    SceneSearchRequest,
    SceneSearchResponse,
    TimelineEntry,
    TimelineResponse,
    TranscribeResponse,
)
from ..vision.base import VisionEncoder
from .visual import visual_search_frames
from .where_is import _match_entity, _retrieve_transcripts, translate_query_for_clip, where_is

router = APIRouter(prefix="/v1/memory", tags=["query"])

# 一次提问的语音撑死几十秒；给到 10MB 已经很宽。上限存在的意义是别让一次
# 手滑上传把整个 sidecar 拖住 60 秒（ASR 请求超时就是 60s）。
MAX_TRANSCRIBE_BYTES = 10 * 1024 * 1024


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


async def _attach_answer_frame(
    session: AsyncSession, resp: FindObjectResponse, *, ctx: GrantContext | None
) -> None:
    """给答案补上来源帧：投影通道顺支撑事件回溯，精判通道 where_is 已经填好了。

    放在端点层而不是 where_is 里，是因为事件→帧的批量解析（`_source_frames`）住在这个
    模块，而 where_is 被本模块导入——反向导入会成环。

    `evidence_url` 只给 owner 直通。原始媒体默认不暴露给 Agent（§5），规则与 scene-search
    保持一致：同一份数据不能因为换了个端点就换一套暴露口径。
    """
    if resp.frame_asset_id is None:
        # 投影通道：支撑事件按时间从新到旧，取第一条追得到帧的——答案说的是最后一次
        # 看到，配的图就必须是那一次，不能拿更早的凑。
        event_ids = [str(i) for i in resp.provenance_summary.supporting_event_ids]
        if event_ids:
            events = list(
                (await session.scalars(select(MemoryEvent).where(MemoryEvent.id.in_(event_ids)))).all()
            )
            by_id = {str(e.id): e for e in events}
            ordered = [by_id[i] for i in event_ids if i in by_id]
            frames = await _source_frames(session, ordered)
            for ev in ordered:
                hit = frames.get(ev.id)
                if hit is not None:
                    resp.frame_asset_id, resp.evidence_available = hit[0].id, hit[1]
                    break

    if resp.frame_asset_id is not None and resp.evidence_available and ctx is None:
        resp.evidence_url = f"/v1/memory/frames/{resp.frame_asset_id}/evidence"


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
    await _attach_answer_frame(session, resp, ctx=ctx)
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


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_endpoint(
    request: Request,
    audio: UploadFile = File(..., description="浏览器录的一段话（webm/ogg/wav/mp4 皆可）"),
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.query.objects")),
) -> TranscribeResponse:
    """把一段话转成字。**只转写，不入库**：音频不落盘、不进 evidence_items、不生成候选。

    仅限 owner 直通（本机界面）。带 token 的 agent 一律拒绝——转写不是记忆访问，
    没有理由让外部 agent 借这台机器当通用 ASR 服务用。
    """
    if ctx is not None:
        raise HTTPException(status_code=403, detail="转写仅限 owner 本机界面调用")

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=422, detail="音频内容为空")
    if len(data) > MAX_TRANSCRIBE_BYTES:
        raise HTTPException(
            status_code=413, detail=f"音频超过 {MAX_TRANSCRIBE_BYTES // (1024 * 1024)}MB"
        )

    transcriber: Transcriber = request.app.state.asr
    # 浏览器录的是带容器的 webm/ogg/mp4，sidecar 按容器嗅探解码，不需要 prepare_audio_for_asr
    # （那一步是给 RV101 的裸 PCM 补 WAV 头用的）。
    segments = await transcriber.transcribe(data, media_kind=audio.content_type or "audio")
    if segments is None:
        # 这里绝不能静默返回空串：界面会把它当成「你没说话」，而真实原因是 ASR 没配起来。
        raise HTTPException(
            status_code=503,
            detail="语音转写不可用：检查 ASR_PROVIDER 与 asr-sidecar 是否在跑",
        )
    text = " ".join(seg.text for seg in segments).strip()

    # 审计只记「转写发生过」和长度，不记内容：既然承诺了不入库，就不能从审计表偷偷留一份。
    await record_audit(
        session,
        actor=actor_of(ctx),
        action="transcribe",
        target="query-voice",
        detail={"bytes": len(data), "chars": len(text), "mime": audio.content_type},
    )
    await session.commit()
    return TranscribeResponse(text=text)


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
        include_regions=get_settings().retrieval_region_search,
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
    return Response(content=Path(item.storage_ref).read_bytes(), media_type=_media_type_of(item))


# ---------------------------------------------------------------- 采集媒体总览


def _media_type_of(item: EvidenceItem) -> str:
    """按真实扩展名判断 Content-Type，猜不出就 octet-stream。

    绝不按 media_kind 硬套（比如 audio 一律回 audio/wav）：正式 App 传的是裸 PCM，
    贴上 wav 头部的 MIME 会让浏览器把它当 wav 解析并播出一段噪音——比直接说
    「这个格式浏览器放不了」糟糕得多。
    """
    return mimetypes.guess_type(item.storage_ref or "")[0] or "application/octet-stream"


def _perception_state(item: EvidenceItem, frame: FrameAsset | None, audio: AudioAsset | None) -> str:
    if frame is not None or audio is not None:
        return "READY"
    # 传感器只可靠落盘，没有解析器（见 gateway 的 outbox 分发注释），不会变成 READY。
    # 视频自 video.process 起有解析器了，所以走下面的 PENDING/ABANDONED 判定。
    if item.media_kind == "sensor":
        return "UNSUPPORTED"
    # 原始字节没了而解析从未完成：解析器再也没有输入可读，这条永远不会有结果。
    # 报成 PENDING 会让界面显示「处理中…」，对着一批死条目一直等。
    if item.retention_state != "ACTIVE":
        return "ABANDONED"
    return "PENDING"


def _as_utc(value: datetime | None) -> datetime | None:
    """把 naive 的查询参数当 UTC 处理：列上是 timestamptz，混用会直接报错。"""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@router.get("/media", response_model=MediaListResponse)
async def media_list_endpoint(
    kind: str | None = Query(default=None, description="image/audio/video/sensor，留空为全部"),
    since: datetime | None = Query(default=None, description="摄入时间下界（含）"),
    until: datetime | None = Query(default=None, description="摄入时间上界（含）"),
    available_only: bool = Query(default=False, description="只看原始文件还在的"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner()),
) -> MediaListResponse:
    """采集媒体总览：所有模态、带时间过滤与分页。

    建在 `evidence_items` 上而不是 `frame_assets`：后者只有走完感知的图片才有行，
    看不到音频、看不到排队中的、更看不到视频。要回答「我刚采的东西呢」，必须从证据出发。

    与原始证据同边界：仅 owner 可用，Agent token 一律 403（§5）。
    """
    if ctx is not None:
        raise HTTPException(status_code=403, detail="摄入明细默认不暴露给 Agent（§5）")
    if kind is not None and kind not in MEDIA_KINDS:
        raise HTTPException(status_code=422, detail=f"未知媒体类型：{kind}（可用：{list(MEDIA_KINDS)}）")

    filters = []
    if kind is not None:
        filters.append(EvidenceItem.media_kind == kind)
    if (lower := _as_utc(since)) is not None:
        filters.append(EvidenceItem.created_at >= lower)
    if (upper := _as_utc(until)) is not None:
        filters.append(EvidenceItem.created_at <= upper)
    if available_only:
        filters.append(EvidenceItem.retention_state == "ACTIVE")

    total = (
        await session.scalar(select(func.count()).select_from(EvidenceItem).where(*filters))
    ) or 0

    rows = (
        await session.execute(
            select(EvidenceItem, FrameAsset, AudioAsset)
            .outerjoin(FrameAsset, FrameAsset.evidence_item_id == EvidenceItem.id)
            .outerjoin(AudioAsset, AudioAsset.evidence_item_id == EvidenceItem.id)
            .where(*filters)
            # 按摄入时间排序而不是 captured_at：后者只有解析出资产的条目才有，
            # 用它排序会让排队中的和视频条目乱序甚至排到最后。
            .order_by(EvidenceItem.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    items: list[MediaItemOut] = []
    for item, frame, audio in rows:
        alive = _evidence_alive(item)
        items.append(
            MediaItemOut(
                evidence_item_id=item.id,
                media_kind=item.media_kind,
                created_at=item.created_at,
                captured_at=(frame.captured_at if frame else audio.captured_at if audio else None),
                ttl_until=item.ttl_until,
                retention_state=item.retention_state,
                perception_state=_perception_state(item, frame, audio),
                available=alive,
                raw_url=f"/v1/memory/media/{item.id}/raw" if alive else None,
                media_type=_media_type_of(item) if alive else None,
                frame_asset_id=frame.id if frame else None,
                caption=frame.caption if frame else None,
                scene_tags=(frame.scene_tags or []) if frame else [],
                audio_asset_id=audio.id if audio else None,
                transcript=audio.transcript if audio else None,
                language=audio.language if audio else None,
                duration_seconds=audio.duration_seconds if audio else None,
            )
        )
    return MediaListResponse(items=items, total=int(total), limit=limit, offset=offset)


@router.get("/media/{evidence_item_id}/raw")
async def media_raw_endpoint(
    evidence_item_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner()),
) -> Response:
    """按证据读原始字节，任意模态。

    `/frames/{id}/evidence` 只服务图片；这个端点覆盖全部模态，音频和视频
    才能在浏览器里直接播。两边都按真实扩展名给出 Content-Type。
    """
    if ctx is not None:
        raise HTTPException(status_code=403, detail="原始证据媒体默认不暴露给 Agent（§5）")
    item = await session.get(EvidenceItem, evidence_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="证据不存在")
    if not _evidence_alive(item):
        raise HTTPException(status_code=404, detail="证据媒体已过期删除")
    return Response(
        content=Path(item.storage_ref).read_bytes(),
        media_type=_media_type_of(item),
        # 不支持 Range：整段一次性返回。短音频（8~20s）够用，真要放长视频再补 206。
        headers={"Cache-Control": "private, max-age=60"},
    )


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
    frames = await _source_frames(session, events)
    entries = []
    for e in events:
        frame, alive = frames.get(e.id, (None, False))
        entries.append(
            TimelineEntry(
                event_id=e.id,
                event_type=e.event_type,
                event_time_from=e.event_time_from,
                accepted_at=e.accepted_at,
                valid_to=e.valid_to,
                payload=e.payload,
                confidence=e.confidence,
                superseded_by=superseded_by.get(e.id),
                frame_asset_id=frame.id if frame else None,
                evidence_available=alive,
                # 原始媒体默认不给 Agent（§5）：只有 owner 直通才给 URL
                evidence_url=(
                    f"/v1/memory/frames/{frame.id}/evidence" if frame and alive and ctx is None else None
                ),
            )
        )
    return TimelineResponse(
        entity=EntityRef(id=entity.id, canonical_name=entity.canonical_name, aliases=entity.aliases),
        projection=proj.state if proj else None,
        events=entries,
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


CHANNEL_LABELS = {
    "verbal": "口头评价",
    "intent": "行动意图",
    "behavior": "实际使用",
    "attention": "画面停留",
}


@router.get("/insights/preferences", response_model=PreferenceInsightsResponse)
async def preference_insights_endpoint(
    limit: int = Query(default=20, ge=1, le=100),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    with_verdict_only: bool = Query(default=False, description="只要证据足够下结论的"),
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.query.preferences")),
) -> PreferenceInsightsResponse:
    """喜好度全览：跨模态融合出「对哪些东西有态度、有多强」，按信息量排序。

    与 /preferences 的分工：那个按名字查单个物体的原始陈述，这个是聚合视图。
    分数只由过了候选门的事件产生——PENDING 的线索只报数量（pending_count），
    不参与打分。ASR 错听和 VLM 幻觉都会先落成候选，让它们直接改画像等于没有门。
    """
    settings = get_settings()
    household_id = await _household_of(session, ctx)
    affinities = await compute_household_affinities(session, household_id=household_id)

    filtered = [
        a
        for a in affinities
        if a.score.confidence >= min_confidence
        and (a.score.has_verdict if with_verdict_only else True)
    ]
    total = len(filtered)
    page = filtered[:limit]

    items = [
        PreferenceInsightOut(
            entity=EntityRef(
                id=a.entity_id, canonical_name=a.entity_name, aliases=a.aliases
            ),
            score=a.score.score,
            level=a.score.level,
            polarity=a.score.polarity,
            confidence=a.score.confidence,
            channels=[
                AffinityChannelOut(
                    channel=c.channel,
                    label=CHANNEL_LABELS.get(c.channel, c.channel),
                    value=round(c.value, 4),
                    weight=round(c.weight, 4),
                    evidence_count=c.evidence_count,
                )
                for c in a.score.channels
            ],
            evidence=[
                AffinityEvidenceOut(
                    kind=e.kind,
                    text=e.text,
                    at=e.at,
                    event_id=e.event_id,
                    confidence=round(e.confidence, 4),
                    superseded=e.superseded,
                )
                for e in a.evidence[:8]
            ],
            use_count=a.signals.use_count,
            frame_count=a.signals.frame_count,
            dwell_seconds=a.signals.dwell_seconds,
            pending_count=a.pending_count,
            last_signal_at=a.last_signal_at,
        )
        for a in page
    ]

    limitations: list[str] = []
    if not items:
        limitations.append("还没有足够的跨模态证据算出喜好度。")
    else:
        limitations.append(
            "喜好度归因范围仅到物品/类别本身，无法区分具体商家或品牌（无订单数据源）。"
        )
        n_pending = sum(a.pending_count for a in page)
        if n_pending:
            limitations.append(
                f"另有 {n_pending} 条相关线索未过候选门，尚未计入分数（可在线索确认中心处理）。"
            )

    await record_audit(
        session,
        actor=actor_of(ctx),
        action="query",
        target="insights:preferences",
        detail={
            "n_items": len(items),
            "total": total,
            **({"grant_id": str(ctx.grant_id)} if ctx else {}),
        },
    )
    await session.commit()
    return PreferenceInsightsResponse(
        items=items,
        total=total,
        generated_at=utcnow(),
        limitations=limitations,
        cache_until=utcnow() + timedelta(seconds=settings.query_cache_ttl_seconds),
    )


# ---------------------------------------------------------------- 记忆浏览读侧
#
# 上面几个端点回答「某件事」，下面三个是「翻记忆本身」：事件流、物品分布、待确认线索。
# 全部确定性、不经 LLM。


async def _source_frames(
    session: AsyncSession, events: list[MemoryEvent]
) -> dict[uuid.UUID, tuple[FrameAsset, bool]]:
    """事件 → 它出自的帧，批量解析。

    链路是 event.source_candidate_ids → candidate.observation_ids → observation.frame_asset_id。
    一条条查是 4 次往返 × N 条事件——limit 能到 200，那就是 800 次查询。所以按层批量取，
    总共 5 条 SQL，跟事件数无关。
    """
    cand_ids = {str(c) for e in events for c in (e.source_candidate_ids or [])}
    if not cand_ids:
        return {}

    candidates = list(
        (
            await session.scalars(
                select(MemoryCandidate).where(MemoryCandidate.id.in_(cand_ids))
            )
        ).all()
    )
    obs_ids = {str(o) for c in candidates for o in (c.observation_ids or [])}
    if not obs_ids:
        return {}

    obs_rows = list(
        (
            await session.execute(
                select(AtomicObservation.id, AtomicObservation.frame_asset_id).where(
                    AtomicObservation.id.in_(obs_ids),
                    AtomicObservation.frame_asset_id.is_not(None),
                )
            )
        ).all()
    )
    frame_by_obs = {str(oid): fid for oid, fid in obs_rows}
    if not frame_by_obs:
        return {}

    frames = {
        f.id: f
        for f in (
            await session.scalars(
                select(FrameAsset).where(FrameAsset.id.in_(set(frame_by_obs.values())))
            )
        ).all()
    }
    evidence = {
        item.id: item
        for item in (
            await session.scalars(
                select(EvidenceItem).where(
                    EvidenceItem.id.in_({f.evidence_item_id for f in frames.values()})
                )
            )
        ).all()
    }

    frame_by_cand: dict[str, uuid.UUID] = {}
    for c in candidates:
        for oid in c.observation_ids or []:
            fid = frame_by_obs.get(str(oid))
            if fid is not None:
                frame_by_cand[str(c.id)] = fid
                break

    out: dict[uuid.UUID, tuple[FrameAsset, bool]] = {}
    for e in events:
        for cid in e.source_candidate_ids or []:
            fid = frame_by_cand.get(str(cid))
            frame = frames.get(fid) if fid else None
            if frame is not None:
                out[e.id] = (frame, _evidence_alive(evidence.get(frame.evidence_item_id)))
                break
    return out


async def _entity_thumbs(
    session: AsyncSession, entity_ids: list[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """实体 → 它的最佳缩略图区域 id，批量解析。

    链路和 _source_frames 同源，多带一个 object_text：
    event → candidate → observation(frame_asset_id, object_text) → frame_regions(帧, 标签)。
    多带这一个字段是必须的——一帧上有好几件物品，只按帧匹配会把茶叶盒的框配给手机。

    不在 Entity 上存一列 thumb_region_id：那需要在实体合并、纠正、遗忘时都同步维护，
    而这里 4 条 SQL 就够，且永远不会和实际数据不一致。
    """
    if not entity_ids:
        return {}

    event_rows = list(
        (
            await session.execute(
                select(MemoryEvent.entity_id, MemoryEvent.source_candidate_ids).where(
                    MemoryEvent.entity_id.in_(entity_ids)
                )
            )
        ).all()
    )
    entity_by_cand: dict[str, uuid.UUID] = {}
    for entity_id, cand_ids in event_rows:
        for cid in cand_ids or []:
            entity_by_cand.setdefault(str(cid), entity_id)
    if not entity_by_cand:
        return {}

    cand_rows = list(
        (
            await session.execute(
                select(MemoryCandidate.id, MemoryCandidate.observation_ids).where(
                    MemoryCandidate.id.in_(set(entity_by_cand))
                )
            )
        ).all()
    )
    entity_by_obs: dict[str, uuid.UUID] = {}
    for cand_id, obs_ids in cand_rows:
        entity_id = entity_by_cand.get(str(cand_id))
        if entity_id is None:
            continue
        for oid in obs_ids or []:
            entity_by_obs.setdefault(str(oid), entity_id)
    if not entity_by_obs:
        return {}

    obs_rows = list(
        (
            await session.execute(
                select(
                    AtomicObservation.id,
                    AtomicObservation.frame_asset_id,
                    AtomicObservation.object_text,
                ).where(
                    AtomicObservation.id.in_(set(entity_by_obs)),
                    AtomicObservation.frame_asset_id.is_not(None),
                    AtomicObservation.object_text.is_not(None),
                )
            )
        ).all()
    )
    # (帧, 物品名) → 是哪些实体在等这张图
    wanted: dict[tuple[uuid.UUID, str], set[uuid.UUID]] = {}
    for obs_id, frame_id, object_text in obs_rows:
        entity_id = entity_by_obs.get(str(obs_id))
        if entity_id is not None:
            wanted.setdefault((frame_id, object_text), set()).add(entity_id)
    if not wanted:
        return {}

    region_rows = list(
        (
            await session.execute(
                select(
                    FrameRegion.id,
                    FrameRegion.frame_asset_id,
                    FrameRegion.label,
                    FrameRegion.score,
                ).where(
                    FrameRegion.frame_asset_id.in_({f for f, _ in wanted}),
                    FrameRegion.source == "detect",
                    FrameRegion.crop_ref.is_not(None),
                )
            )
        ).all()
    )

    # 同一件东西可能在好几帧里都被检出：取检测分最高的那张，而不是最新的一张。
    # 最新的常常是随手一拍的糊图，而节点上就那么几十像素，清晰度比新鲜度值钱。
    best: dict[uuid.UUID, tuple[float, uuid.UUID]] = {}
    for region_id, frame_id, label, score in region_rows:
        for entity_id in wanted.get((frame_id, label), ()):
            current = best.get(entity_id)
            if current is None or float(score or 0.0) > current[0]:
                best[entity_id] = (float(score or 0.0), region_id)
    return {entity_id: region_id for entity_id, (_, region_id) in best.items()}


@router.get("/regions/{region_id}/crop")
async def region_crop_endpoint(
    region_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.query.objects")),
) -> Response:
    """物件缩略图字节流（全览页节点贴图）。

    与 /frames/{id}/evidence 不同，这里**不查证据存活**：裁切图是独立落盘的一份小图，
    本来就该活得比原件长——原件 15 分钟就被 TTL 删了，缩略图删了全览页就永远是纯色球。
    也正因为它长期存在，同样按 owner-only 处理，不对 Agent 开放原始像素。
    """
    if ctx is not None:
        raise HTTPException(status_code=403, detail="原始像素不对 Agent 开放")
    region = await session.get(FrameRegion, region_id)
    if region is None or not region.crop_ref:
        raise HTTPException(status_code=404, detail="没有这张缩略图")
    path = Path(region.crop_ref)
    if not path.exists():
        raise HTTPException(status_code=404, detail="缩略图文件已丢失")
    return Response(
        content=path.read_bytes(),
        media_type="image/jpeg",
        # 缩略图内容按 region_id 不可变（重新检测会写新行），可以放心长缓存
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/events/recent", response_model=MemoryEventsResponse)
async def recent_events_endpoint(
    limit: int = Query(default=30, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.timeline.read")),
) -> MemoryEventsResponse:
    """跨实体的近期事件流（上下文页）。含已被取代的事件，但打上 superseded 标记；
    已被遗忘的事件不返回。

    valid_to 有两个来源，含义完全相反，绝不能混：
      · 被后续事件取代（supersedes_event_id 指向它）——旧事实，要显示并标记，
        因为用户需要看到「这条记忆被改过」，而不是让它凭空消失；
      · 被 forget-recent 遗忘——用户明确要求它消失。把它摆回界面上是在撤销一次
        隐私操作，比标错文案严重得多。
    区分方法：有没有后继事件指向它。两条写 valid_to 的路径只有这一处差别。
    """
    household_id = await _household_of(session, ctx)
    superseded_ids = select(MemoryEvent.supersedes_event_id).where(
        MemoryEvent.supersedes_event_id.is_not(None)
    )
    scope = (
        Entity.household_id == household_id,
        MemoryEvent.branch_id == "main",
        # 仍然有效，或者虽已关闭但确实是被取代的（= 不是被遗忘的）
        MemoryEvent.valid_to.is_(None) | MemoryEvent.id.in_(superseded_ids),
    )
    rows = list(
        (
            await session.execute(
                select(MemoryEvent, Entity)
                .join(Entity, MemoryEvent.entity_id == Entity.id)
                .where(*scope)
                .order_by(MemoryEvent.event_time_from.desc(), MemoryEvent.accepted_at.desc())
                .limit(limit)
            )
        ).all()
    )
    total = (
        await session.scalar(
            select(func.count(MemoryEvent.id))
            .join(Entity, MemoryEvent.entity_id == Entity.id)
            .where(*scope)
        )
    ) or 0

    frames = await _source_frames(session, [event for event, _ in rows])
    events = []
    for event, entity in rows:
        frame, alive = frames.get(event.id, (None, False))
        events.append(
            MemoryEventEntry(
                event_id=event.id,
                entity_id=entity.id,
                entity_name=entity.canonical_name,
                event_type=event.event_type,
                event_time_from=event.event_time_from,
                accepted_at=event.accepted_at,
                # USER_CORRECTION 的位置在 payload.value 里（payload 是 {field,value,reason}），
                # 跟观察事件的 payload.location 不同构。不分开取，纠正过的物品在流里会显示成空位置。
                location=(
                    event.payload.get("value")
                    if event.event_type == "USER_CORRECTION"
                    and event.payload.get("field") == "location"
                    else event.payload.get("location")
                ),
                payload=event.payload or {},
                confidence=float((event.confidence or {}).get("aggregate", 0.0)),
                superseded=event.valid_to is not None,
                user_confirmed=bool((event.confidence or {}).get("user_confirmed"))
                or event.event_type == "USER_CORRECTION",
                frame_asset_id=frame.id if frame else None,
                evidence_available=alive,
                # 原始媒体默认不给 Agent（§5）：只有 owner 直通才给 URL
                evidence_url=(
                    f"/v1/memory/frames/{frame.id}/evidence" if frame and alive and ctx is None else None
                ),
            )
        )
    return MemoryEventsResponse(events=events, total=total)


@router.get("/objects", response_model=ObjectGraphResponse)
async def objects_graph_endpoint(
    located_only: bool = False,
    category: str | None = Query(
        default=None,
        description="按粗分类过滤，逗号分隔（PORTABLE/FIXTURE/PERSON/CONSUMABLE/UNCLASSIFIED）；留空为全部",
    ),
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.query.objects")),
) -> ObjectGraphResponse:
    """全部物品 + 当前位置，并按位置聚成组（全览页）。

    组 = 「这些东西放在一起」，只按 last_seen.location 字符串聚类。这里刻意不做
    locations_compatible 那种模糊归并：全览是给人看分布的，把「办公桌」和「黄色桌面」
    合成一个组需要判断它们是不是同一张桌子，判断错了就是凭空编造空间关系。
    """
    household_id = await _household_of(session, ctx)
    rows = list(
        (
            await session.execute(
                select(Entity, StateProjection)
                .outerjoin(
                    StateProjection,
                    (StateProjection.entity_id == Entity.id)
                    & (StateProjection.projection_type == "last_seen"),
                )
                .where(Entity.household_id == household_id)
            )
        ).all()
    )
    counts = dict(
        (
            await session.execute(
                select(MemoryEvent.entity_id, func.count(MemoryEvent.id))
                .join(Entity, MemoryEvent.entity_id == Entity.id)
                .where(Entity.household_id == household_id)
                .group_by(MemoryEvent.entity_id)
            )
        ).all()
    )

    # 过滤在这里做而不是在 SQL 里：分组必须只在**筛后**的集合上算，否则「办公桌 6 件」
    # 会把已经被过滤掉的墙面和地板也数进去，界面上的数字跟看到的节点对不上。
    wanted = {c.strip().upper() for c in category.split(",") if c.strip()} if category else None

    nodes: list[ObjectNodeOut] = []
    by_location: dict[str, list[uuid.UUID]] = {}
    for entity, proj in rows:
        state = (proj.state if proj else None) or {}
        location = state.get("location") or None
        if located_only and not location:
            continue
        if wanted is not None and entity.category not in wanted:
            continue
        last_seen = state.get("last_seen_time")
        nodes.append(
            ObjectNodeOut(
                entity_id=entity.id,
                canonical_name=entity.canonical_name,
                aliases=entity.aliases or [],
                entity_class=entity.class_,
                location=location,
                last_seen_time=_parse_iso(last_seen),
                confidence=float(state.get("confidence") or 0.0),
                event_count=int(counts.get(entity.id, 0)),
                corrected=bool(state.get("corrected")),
                category=entity.category,
                category_source=entity.category_source,
            )
        )
        if location:
            by_location.setdefault(location, []).append(entity.id)

    # 缩略图在筛完之后一次性解析：按筛前的全量去查，等于给一堆压根不显示的
    # 墙面地板白算一遍。与 evidence_url 同规矩——原始像素不给 Agent（§5）。
    if ctx is None:
        thumbs = await _entity_thumbs(session, [n.entity_id for n in nodes])
        for node in nodes:
            region_id = thumbs.get(node.entity_id)
            if region_id is not None:
                node.thumb_url = f"/v1/memory/regions/{region_id}/crop"

    groups = [
        ObjectGroupOut(location=loc, entity_ids=ids)
        for loc, ids in sorted(by_location.items(), key=lambda kv: -len(kv[1]))
        if len(ids) >= 2
    ]
    # 最近看到的排前面，没有位置的沉到最后
    nodes.sort(
        key=lambda n: (
            n.last_seen_time is None,
            -(n.last_seen_time.timestamp() if n.last_seen_time else 0.0),
        )
    )
    return ObjectGraphResponse(nodes=nodes, groups=groups, total=len(nodes))


def _parse_iso(value: Any) -> datetime | None:
    """投影里的时间是 isoformat 字符串（fold 的产物），读回来要还原成 datetime。"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


async def _clue_frame(
    session: AsyncSession, candidate: MemoryCandidate
) -> tuple[FrameAsset | None, bool]:
    """线索出自哪一帧：candidate.observation_ids → observation.frame_asset_id。"""
    obs_ids = [str(i) for i in (candidate.observation_ids or [])]
    if not obs_ids:
        return None, False
    frame_id = await session.scalar(
        select(AtomicObservation.frame_asset_id)
        .where(AtomicObservation.id.in_(obs_ids), AtomicObservation.frame_asset_id.is_not(None))
        .limit(1)
    )
    if frame_id is None:
        return None, False
    frame = await session.get(FrameAsset, frame_id)
    if frame is None:
        return None, False
    return frame, _evidence_alive(await _evidence_item_of(session, frame))


@router.get("/clues", response_model=MemoryCluesResponse)
async def clues_endpoint(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.timeline.read")),
) -> MemoryCluesResponse:
    """待确认线索：候选门没敢自动接受的候选（PENDING / CONFLICTED）。

    这是「记忆线索待确认」的真实来源。数量本身有意义——它等于系统看到了东西但
    不敢当成事实的次数，写死成常数就把这个信号抹掉了。
    """
    household_id = await _household_of(session, ctx)
    # 候选自己没有 household 列：已解析实体的按实体过滤，未解析的（entity_id 为空）
    # 属于本次摄入尚未落到实体的观察，一律归本家庭——单家庭部署下这是安全的近似。
    household_entity_ids = select(Entity.id).where(Entity.household_id == household_id)
    # 必须有 location 才算「线索」。没有位置的候选确认了也没用：fold_events 只在
    # payload.location 存在时才更新投影，所以确认它是个空操作。这类候选大多是
    # where-is 找不到东西时留下的失败记录（payload 只有 object_text），把它们摆进
    # 确认中心，用户看到的是一排「充电器 / 位置未知 / 要确认吗？」——无从下手，
    # 点了也什么都不会变。它们作为「问过但没找到」的痕迹有价值，但不在这个界面里。
    condition = (
        MemoryCandidate.status.in_(("PENDING", "CONFLICTED"))
        & MemoryCandidate.payload.has_key("location")  # noqa: W601 — JSONB ? 运算符
    )
    scope = MemoryCandidate.entity_id.is_(None) | MemoryCandidate.entity_id.in_(
        household_entity_ids
    )
    candidates = list(
        (
            await session.scalars(
                select(MemoryCandidate)
                .where(condition, scope)
                .order_by(MemoryCandidate.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    total = (
        await session.scalar(select(func.count(MemoryCandidate.id)).where(condition, scope))
    ) or 0

    clues: list[MemoryClueOut] = []
    for c in candidates:
        frame, alive = await _clue_frame(session, c)
        clues.append(
            MemoryClueOut(
                candidate_id=c.id,
                entity_id=c.entity_id,
                object_text=c.payload.get("object_text") or "未知物体",
                location=c.payload.get("location"),
                event_type=c.event_type,
                payload=c.payload or {},
                confidence=float((c.confidence or {}).get("aggregate", 0.0)),
                status=c.status,
                source=c.source,
                created_at=c.created_at,
                conflict_set_id=c.conflict_set_id,
                frame_asset_id=frame.id if frame else None,
                frame_caption=frame.caption if frame else None,
                evidence_available=alive,
                # 原始媒体默认不暴露给 Agent（§5）：只有 owner 直通才给 URL
                evidence_url=(
                    f"/v1/memory/frames/{frame.id}/evidence" if frame and alive and ctx is None else None
                ),
            )
        )
    return MemoryCluesResponse(clues=clues, total=total)


@router.post("/clues/{candidate_id}/resolve", response_model=ClueResolveResponse)
async def resolve_clue_endpoint(
    candidate_id: uuid.UUID,
    req: ClueResolveRequest,
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.correction.submit")),
) -> ClueResolveResponse:
    """确认或忽略一条线索。

    确认 = 用户替候选门拍板：绕过置信度阈值，直接升级成事件（走 gate.accept_candidate，
    跟自动门同一实现），事件 confidence 带 user_confirmed=1.0 留痕。模型永远不能这样
    绕过阈值——能绕过的是人，不是模型给自己打的分。

    忽略 = REJECTED，不写事件。候选记录保留，因为「用户说这不对」本身是要留档的信息。
    """
    candidate = await session.get(MemoryCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate 不存在")
    if candidate.status not in ("PENDING", "CONFLICTED"):
        raise HTTPException(
            status_code=409,
            detail=f"该线索已处理（status={candidate.status}），不能重复确认",
        )
    household_id = await _household_of(session, ctx)
    if candidate.entity_id is not None:
        entity = await session.get(Entity, candidate.entity_id)
        if entity is not None and ctx is not None:
            ctx.require_household(entity.household_id)

    if req.decision == "REJECT":
        candidate.status = "REJECTED"
        candidate.resolved_at = utcnow()
        await record_audit(
            session,
            actor=actor_of(ctx),
            action="clue_rejected",
            target=f"candidate:{candidate.id}",
            detail={
                "object_text": candidate.payload.get("object_text"),
                "reason": req.reason,
                **({"grant_id": str(ctx.grant_id)} if ctx else {}),
            },
        )
        await session.commit()
        return ClueResolveResponse(
            candidate_id=candidate.id, status=candidate.status, entity_id=candidate.entity_id
        )

    if not candidate.payload.get("location"):
        # 没有位置就没有可确认的内容：升级后 fold 出来的投影跟现在一样，界面会显示
        # 「已确认」但记忆没有任何变化。宁可明确报错，也不要给一个骗人的成功。
        raise HTTPException(
            status_code=422,
            detail="该候选没有位置信息，确认它不会改变任何记忆；只能忽略",
        )

    # 观察时间：候选自己不存现象时间，从支撑观察里取，取不到才退回创建时间。
    # 这个时间决定投影 fold 的先后，拿错了会让旧观察盖掉新位置。
    observed = await session.scalar(
        select(func.min(AtomicObservation.phenomenon_time)).where(
            AtomicObservation.id.in_([str(i) for i in (candidate.observation_ids or [])])
        )
    )
    phenomenon_time = observed or candidate.created_at

    siblings: list[MemoryCandidate] = []
    if candidate.conflict_set_id is not None:
        # 用户确认其中一条 = 冲突已由人裁决，同集里的其它候选一并判否，
        # 否则它们会永远停在 CONFLICTED，界面上反复出现同一个已解决的矛盾
        siblings = list(
            (
                await session.scalars(
                    select(MemoryCandidate).where(
                        MemoryCandidate.conflict_set_id == candidate.conflict_set_id,
                        MemoryCandidate.id != candidate.id,
                        MemoryCandidate.status.in_(("PENDING", "CONFLICTED")),
                    )
                )
            ).all()
        )
        for s in siblings:
            s.status = "REJECTED"
            s.resolved_at = utcnow()

    event = await accept_candidate(
        session,
        candidate=candidate,
        household_id=household_id,
        phenomenon_time=phenomenon_time,
        observed_at=observed or candidate.created_at,
        actor=actor_of(ctx),
        confidence_overlay={"user_confirmed": 1.0},
        audit_detail={
            "via": "clue_confirm",
            "reason": req.reason,
            **({"grant_id": str(ctx.grant_id)} if ctx else {}),
        },
    )
    await session.commit()
    proj = await recompute_projection(session, entity_id=candidate.entity_id)
    return ClueResolveResponse(
        candidate_id=candidate.id,
        status=candidate.status,
        event_id=event.id,
        entity_id=candidate.entity_id,
        projection=proj.state,
        rejected_sibling_ids=[s.id for s in siblings],
    )
