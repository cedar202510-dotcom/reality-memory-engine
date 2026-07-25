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

from sqlalchemy import Text, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..llm.base import LLMClient
from ..memory.gate import evaluate_candidate
from ..memory.normalize import has_cjk, names_alias_match
from ..memory.seed import get_default_household_id
from ..perception import _to_data_url
from ..models import (
    AudioAsset,
    Entity,
    EvidenceItem,
    FrameAsset,
    FrameRegion,
    MemoryCandidate,
    MemoryEvent,
    StateProjection,
    utcnow,
)
from ..schemas import EntityRef, FindObjectResponse, LocationAlternative, ProvenanceSummary
from ..vision.base import VisionEncoder
from .answerer import AnswerInput, build_answerer
from .visual import fuse_rankings, visual_search_frames


def _cache_until() -> datetime:
    """Agent 侧缓存上限（§12）；纠正/遗忘后以平台重新查询为准。"""
    from datetime import timedelta

    return utcnow() + timedelta(seconds=get_settings().query_cache_ttl_seconds)


def _staleness_limitations(last_seen: datetime | None, confidence: float) -> list[str]:
    """规则生成的不确定性声明（§4.1 limitations），不经 LLM。"""
    notes = ["这是最后一次可靠观察，不保证物品仍在原处。"]
    if last_seen is not None:
        ls = last_seen if last_seen.tzinfo else last_seen.replace(tzinfo=timezone.utc)
        age_hours = (utcnow() - ls).total_seconds() / 3600
        if age_hours >= 24:
            notes.append(f"该位置信息已超过 {int(age_hours // 24)} 天未更新，期间可能被移动过。")
    if confidence < 0.6:
        notes.append("本次判断置信度较低，建议向用户确认。")
    return notes


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
    # 中文包含式别名（「手机」↔「智能手机」）：trgm 对中文短名几乎无效
    candidates = (
        await session.scalars(select(Entity).where(Entity.household_id == household_id))
    ).all()
    for entity in candidates:
        all_names = [entity.canonical_name, *(entity.aliases or [])]
        if any(names_alias_match(n, name) for n in all_names):
            return entity
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

    # 来源摘要：支撑当前位置的有效事件 + 最近一次纠正时间（§4.1）
    supporting = [
        ev.id
        for ev in events
        if ev.valid_to is None and (ev.payload or {}).get("location") == location
    ]
    corrections = [ev.accepted_at for ev in events if ev.event_type == "USER_CORRECTION"]
    provenance = ProvenanceSummary(
        supporting_event_ids=supporting[:10],
        support_count=len(supporting),
        last_corrected_at=max(corrections) if corrections else None,
    )

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
            provenance_summary=provenance,
            limitations=["当前没有有效的位置记忆，可能刚被纠正或遗忘。"],
            cache_until=_cache_until(),
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
        provenance_summary=provenance,
        limitations=_staleness_limitations(last_seen, confidence),
        cache_until=_cache_until(),
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


async def _retrieve_frames_ocr(
    session: AsyncSession, *, name: str, top_k: int
) -> list[tuple[FrameAsset, float]]:
    """OCR 路召回：帧上印着的字面量。包含命中给满分，否则退回 trgm 相似度。

    为什么包含命中就给 1.0：这不是"描述里提到了身份证"，是身份证本人把
    「居民身份证」这几个字印在了自己身上。字面量出现在画面里，是这条链路上
    最硬的证据，比 caption 的转述和向量的近似都强。

    一帧可能有多条 OCR 区域，按 max 上卷——与区域视觉向量同一套逻辑。
    """
    like = f"%{name}%"
    similarity = func.word_similarity(name, FrameRegion.ocr_text)
    score = func.max(
        case((FrameRegion.ocr_text.ilike(like), 1.0), else_=similarity)
    ).label("score")
    rows = (
        await session.execute(
            select(FrameRegion.frame_asset_id, score)
            .where(
                FrameRegion.ocr_text.is_not(None),
                (similarity > 0) | FrameRegion.ocr_text.ilike(like),
            )
            .group_by(FrameRegion.frame_asset_id)
            .order_by(score.desc())
            .limit(top_k)
        )
    ).all()
    if not rows:
        return []
    by_id = {fid: float(s) for fid, s in rows}
    frames = (
        await session.scalars(select(FrameAsset).where(FrameAsset.id.in_(list(by_id))))
    ).all()
    return sorted(
        ((f, by_id[f.id]) for f in frames), key=lambda kv: kv[1], reverse=True
    )


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


# 中文查询 → 英文短语翻译缓存（CLIP 文本塔是英文模型，中文向量近似噪声）
_clip_translate_cache: dict[str, str] = {}


async def translate_query_for_clip(llm: LLMClient, name: str) -> str | None:
    """含 CJK 的查询翻译成简短英文名词短语（进程内缓存）；失败/空返回 None 降级。"""
    if not get_settings().clip_query_translate or not has_cjk(name):
        return None
    if name in _clip_translate_cache:
        return _clip_translate_cache[name] or None
    english = ""
    try:
        raw = await llm.complete_json(
            task="translate",
            prompt=(
                f"把这个物品查询词翻译成简短的英文名词短语（用于图像检索）：「{name}」。"
                '只输出一个 JSON 对象：{"english": "<英文短语>"}'
            ),
        )
        english = str(raw.get("english") or "").strip()
    except Exception:  # noqa: BLE001 - 翻译失败一律降级为仅中文向量
        english = ""
    _clip_translate_cache[name] = english
    return english or None


async def _recall_channel2(
    session: AsyncSession,
    *,
    llm: LLMClient,
    name: str,
    top_k: int,
    vision: VisionEncoder | None = None,
) -> tuple[list[FrameAsset], list[AudioAsset]]:
    """通道 2 多路混合召回：帧文本路（caption+OCR）+ 视觉路（CLIP 跨模态）+ 语音转写路。

    三路分数各自归一化到 [0,1] 后按配置权重加权融合，合并去重取 top_k；
    按融合顺序拆回帧与语音两类资产。无视觉/转写命中时行为与旧版纯文本路一致。
    """
    settings = get_settings()
    text_hits = await _retrieve_frames_text(session, llm=llm, name=name, top_k=top_k)

    # OCR 并入文本路取 max，而不是当第四路：caption 和 OCR 都是"这一帧的文字表示"，
    # 同属一路。另起一路要重算 fuse_rankings 的权重分配（w_text 是剩余量），
    # 那套逻辑是有测试的，不该为了加一个数据源就动它。
    if settings.retrieval_ocr_search:
        ocr_hits = await _retrieve_frames_ocr(session, name=name, top_k=top_k)
        if ocr_hits:
            merged = {f.id: (f, s) for f, s in text_hits}
            for frame, score in ocr_hits:
                prev = merged.get(frame.id)
                if prev is None or score > prev[1]:
                    merged[frame.id] = (frame, score)
            text_hits = sorted(merged.values(), key=lambda kv: kv[1], reverse=True)[:top_k]

    visual_hits: list[tuple[FrameAsset, float]] = []
    if vision is not None:
        english = await translate_query_for_clip(llm, name)
        visual_hits = await visual_search_frames(
            session,
            vision=vision,
            query_text=name,
            top_k=settings.retrieval_visual_top_k,
            extra_query_texts=[english] if english else None,
            include_regions=settings.retrieval_region_search,
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


async def _frame_data_url(session: AsyncSession, frame: FrameAsset) -> str | None:
    """帧证据媒体仍可读时返回 base64 data URL，否则 None（TTL 已删只剩 caption）。"""
    item = await session.get(EvidenceItem, frame.evidence_item_id)
    if not (
        item
        and item.retention_state == "ACTIVE"
        and item.storage_ref
        and Path(item.storage_ref).exists()
    ):
        return None
    # 复用感知侧的缩图逻辑：手机原图是 4284x5712，裸 base64 单张就 4MB+，
    # 一个精判批次两张、最多三批——直接把原图丢给 VLM 既慢又容易超限。
    # 顺带修掉 Content-Type：老数据里的 HEIC 不会再被贴上 image/jpeg。
    return _to_data_url(item.storage_ref)


async def _channel_deep_retrieval(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    name: str,
    llm: LLMClient,
    vision: VisionEncoder | None = None,
) -> FindObjectResponse:
    """通道 2：混合召回 → 按时间从新到旧分批 VLM 验证，命中即早停。

    找物语义下最新一次目击就是答案，更早的目击只影响 alternatives/时间线，
    因此无需一次性精判全部召回帧：每批验证 verify_batch_size 帧（附图），
    置信度达标即停；期望情况 1 次小调用即出答案，比一次性 4 图精判更快。
    """
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
            limitations=["没有可靠记忆，不作猜测。"],
            cache_until=_cache_until(),
        )

    # 语音转写少且廉价：作为上下文附在每一批验证里
    audio_lines = [f"- [{a.captured_at.isoformat()}] 语音转写：「{a.transcript}」" for a in audios]

    # 按目击时间从新到旧验证（召回顺序只决定谁有资格进验证，不决定验证顺序）
    ordered = sorted(frames, key=lambda f: f.captured_at, reverse=True)
    batch_size = max(settings.retrieval_verify_batch_size, 1)
    batches = [ordered[i : i + batch_size] for i in range(0, len(ordered), batch_size)]
    batches = batches[: settings.retrieval_verify_max_batches]
    if not batches:
        batches = [[]]  # 纯语音召回：单批、仅转写上下文

    answerer = build_answerer(llm)
    ans = None
    chosen_frame: FrameAsset | None = None
    found_ok = False
    evidence_alive_by_frame: dict[uuid.UUID, bool] = {}
    for batch in batches:
        lines: list[str] = []
        images: list[str] = []
        for i, f in enumerate(batch):
            data_url = await _frame_data_url(session, f)
            evidence_alive_by_frame[f.id] = data_url is not None
            lines.append(
                f"{i}. [{f.captured_at.isoformat()}] {f.caption}"
                f"（tags: {'、'.join(f.scene_tags or [])}）" + ("【附图】" if data_url else "")
            )
            if data_url:
                images.append(data_url)
        batch_ans = await answerer.run(
            AnswerInput(query_name=name, candidates_text="\n".join(lines + audio_lines)),
            images=images or None,
        )
        if batch_ans is None:
            continue  # 本批输出不合契约 → 继续验证更早的批
        ans = batch_ans
        if ans.found and ans.confidence >= settings.retrieval_verify_min_confidence:
            found_ok = True
            if batch:
                idx = ans.chosen_index if ans.chosen_index is not None else 0
                chosen_frame = batch[idx] if 0 <= idx < len(batch) else batch[0]
            break  # 早停：最新的确认目击就是答案
        # found 但低置信 → 不采纳，继续往更早的批找

    if ans is None:
        return FindObjectResponse(
            query=name,
            channel="deep_retrieval",
            confidence=0.0,
            answer_text="精判阶段输出不合契约，本次无法给出答案。",
            limitations=["模型输出未通过契约校验，结果被拒绝而非猜测。"],
            cache_until=_cache_until(),
        )

    # 目击时间取 Answerer 选中的那一帧（修复：不再用召回集合最大时间冒充目击时间）
    if chosen_frame is not None:
        seen_time = chosen_frame.captured_at
    else:
        seen_time = max(
            [f.captured_at for f in frames] + [a.captured_at for a in audios]
        )

    # 回写候选（被查询过的物体 → 候选；aggregate 足够则经候选门升级为实体）
    confidence = {
        "model": ans.confidence,
        "identity": ans.confidence,
        "spatial": ans.confidence if found_ok else 0.0,
        "temporal": 0.8,
        "policy": 1.0,
        "aggregate": ans.confidence,
    }
    candidate = MemoryCandidate(
        observation_ids=[],
        event_type="OBJECT_OBSERVED_AT",
        payload={"object_text": name, "location": ans.location} if found_ok else {"object_text": name},
        confidence=confidence,
        status="PENDING",
        source="query",
    )
    session.add(candidate)
    await session.flush()
    obj_vec = await llm.embed([name])
    # 供实体解析做物体级合并：优先选中帧的视觉向量，其次任一召回帧
    frame_vec = chosen_frame.visual_embedding if chosen_frame is not None else None
    if frame_vec is None:
        frame_vec = next((f.visual_embedding for f in frames if f.visual_embedding is not None), None)
    await evaluate_candidate(
        session,
        candidate=candidate,
        household_id=household_id,
        phenomenon_time=seen_time,
        observed_at=seen_time,
        object_embedding=obj_vec[0] if obj_vec else None,
        frame_visual_embedding=frame_vec,
    )
    await session.commit()

    if not found_ok:
        return FindObjectResponse(
            query=name,
            channel="not_found",
            confidence=ans.confidence,
            answer_text=ans.answer_text or f"没有在用过的场景里找到「{name}」。",
            limitations=["召回的场景片段中未确认目标，不作猜测。"],
            cache_until=_cache_until(),
        )

    # 来源摘要：候选门若已升级为事件，用该事件；否则以候选 id 记录（未成为事实）
    accepted_event = await session.scalar(
        select(MemoryEvent).where(
            MemoryEvent.source_candidate_ids.contains([str(candidate.id)])
        )
    )
    provenance = ProvenanceSummary(
        supporting_event_ids=[accepted_event.id] if accepted_event else [],
        support_count=1 if accepted_event else 0,
        last_corrected_at=None,
    )
    limitations = _staleness_limitations(seen_time, ans.confidence)
    if chosen_frame is not None and not evidence_alive_by_frame.get(chosen_frame.id, False):
        limitations.append("原始画面已按 TTL 删除，判断基于长期文字与向量表示。")
    if accepted_event is None:
        limitations.append("该结论尚未通过候选门成为事实事件，属于检索推断。")

    entity_ref = None
    if candidate.entity_id:
        ent = await session.get(Entity, candidate.entity_id)
        if ent:
            entity_ref = EntityRef(id=ent.id, canonical_name=ent.canonical_name, aliases=ent.aliases)
    fresh = freshness_text(seen_time)
    return FindObjectResponse(
        query=name,
        channel="deep_retrieval",
        entity=entity_ref,
        location=ans.location,
        last_seen_time=seen_time,
        freshness=fresh,
        confidence=ans.confidence,
        answer_text=ans.answer_text or f"{name}{fresh or ''}，在{ans.location}。",
        # 精判就是看着这一帧下的结论，把它一并交出来——界面上那张图和这句话必须是同一眼
        frame_asset_id=chosen_frame.id if chosen_frame is not None else None,
        evidence_available=(
            evidence_alive_by_frame.get(chosen_frame.id, False) if chosen_frame is not None else False
        ),
        timeline_url=(
            f"/v1/memory/objects/{candidate.entity_id}/timeline" if candidate.entity_id else None
        ),
        provenance_summary=provenance,
        limitations=limitations,
        cache_until=_cache_until(),
    )


async def where_is(
    session: AsyncSession,
    *,
    name: str,
    deep: bool,
    llm: LLMClient,
    vision: VisionEncoder | None = None,
    household_id: uuid.UUID | None = None,
) -> FindObjectResponse:
    """household_id：agent 调用时来自 grant（鉴权层隔离）；owner 直通为 None → 默认家庭。"""
    if household_id is None:
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
