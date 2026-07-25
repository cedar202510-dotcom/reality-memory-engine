"""取数层：把库里散落的证据拼成 AffinitySignals，交给纯函数打分。

一条原则贯穿这里：**只有过了候选门的事件才参与打分**。
偏好陈述和别的记忆一样要经过 candidate gate——置信度不够就停在 PENDING，
等人在线索确认中心拍板。绕过门直接拿 PENDING 候选算分，等于让 ASR 的
错听（「自己好戏也不老实」这种）直接变成用户的口味画像。

但也不能假装那些待确认的不存在：响应里带 pending_count，
让前端能说「还有 N 条待确认」，而不是让用户对着一个空面板猜。
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    AtomicObservation,
    Entity,
    EvidenceItem,
    FrameAsset,
    MemoryCandidate,
    MemoryEvent,
    utcnow,
)
from .affinity import (
    AffinitySignals,
    AffinityScore,
    IntentStatement,
    VerbalStatement,
    score_affinity,
)

# 参与行为通道的谓词。OBSERVED_AT/PLACED 这些不算「用过」，只算看见过。
BEHAVIOR_PREDICATES = {"USED", "CONSUMED"}


@dataclass
class EvidenceRef:
    """一条可点开回溯的证据。前端用它把分数落回到具体那句话/那一帧。"""

    kind: str                      # verbal / intent / behavior / attention
    text: str
    at: datetime | None = None
    event_id: uuid.UUID | None = None
    confidence: float = 0.5
    superseded: bool = False


@dataclass
class EntityAffinity:
    entity_id: uuid.UUID
    entity_name: str
    aliases: list[str]
    score: AffinityScore
    signals: AffinitySignals
    evidence: list[EvidenceRef] = field(default_factory=list)
    pending_count: int = 0
    last_signal_at: datetime | None = None


async def compute_household_affinities(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    now: datetime | None = None,
) -> list[EntityAffinity]:
    """算出该家庭下所有「有喜好证据」的实体，按分数排序返回。

    没有任何 verbal/intent/behavior/attention 证据的实体不会出现在结果里——
    全览面板要回答的是「你对什么有态度」，不是「库里有哪些物体」（那是物品图谱的活）。
    """
    now = now or utcnow()

    entities = {
        e.id: e
        for e in (
            await session.scalars(select(Entity).where(Entity.household_id == household_id))
        ).all()
    }
    if not entities:
        return []

    events = list(
        (
            await session.scalars(
                select(MemoryEvent)
                .where(
                    MemoryEvent.entity_id.in_(list(entities)),
                    MemoryEvent.event_type.in_(("PREFERENCE_STATED", "TASK_STATED")),
                )
                .order_by(MemoryEvent.event_time_from.desc())
            )
        ).all()
    )

    behavior, attention, pending = await _observation_signals(
        session, entity_ids=list(entities)
    )

    grouped: dict[uuid.UUID, list[MemoryEvent]] = defaultdict(list)
    for ev in events:
        if ev.entity_id is not None:
            grouped[ev.entity_id].append(ev)

    results: list[EntityAffinity] = []
    touched = set(grouped) | set(behavior) | set(attention)
    for entity_id in touched:
        entity = entities.get(entity_id)
        if entity is None:
            continue
        item = _build_one(
            entity=entity,
            events=grouped.get(entity_id, []),
            behavior=behavior.get(entity_id, (0, [])),
            attention=attention.get(entity_id, (0, 0.0)),
            pending_count=pending.get(entity_id, 0),
            now=now,
        )
        if item is not None:
            results.append(item)

    # 主排序是分数距离中性的绝对值——「非常讨厌」和「非常喜欢」一样值得被看见，
    # 按分数从高到低排会把强烈负面的评价埋在列表最底下，那恰恰是最该提醒的信息。
    results.sort(
        key=lambda r: (
            r.score.has_verdict,
            abs(r.score.score - 50) * r.score.confidence,
        ),
        reverse=True,
    )
    return results


def _build_one(
    *,
    entity: Entity,
    events: list[MemoryEvent],
    behavior: tuple[int, list[EvidenceRef]],
    attention: tuple[int, float],
    pending_count: int,
    now: datetime,
) -> EntityAffinity | None:
    verbal: list[VerbalStatement] = []
    intents: list[IntentStatement] = []
    evidence: list[EvidenceRef] = []
    last_at: datetime | None = None

    for ev in events:
        payload = ev.payload or {}
        conf = float((ev.confidence or {}).get("aggregate", 0.5))
        superseded = ev.valid_to is not None
        at = ev.event_time_from
        age_days = _age_days(at, now)
        if at is not None and (last_at is None or at > last_at):
            last_at = at

        if ev.event_type == "PREFERENCE_STATED":
            text = str(payload.get("preference") or payload.get("state") or "").strip()
            verbal.append(
                VerbalStatement(
                    sentiment=str(payload.get("sentiment") or _infer_sentiment(text)),
                    intensity=_as_float(payload.get("intensity"), 0.5),
                    confidence=conf,
                    age_days=age_days,
                    superseded=superseded,
                    text=text,
                )
            )
            evidence.append(
                EvidenceRef(
                    kind="verbal",
                    text=text or "（未记录原话）",
                    at=at,
                    event_id=ev.id,
                    confidence=conf,
                    superseded=superseded,
                )
            )
        elif ev.event_type == "TASK_STATED":
            text = str(payload.get("task") or "").strip()
            intents.append(
                IntentStatement(
                    intent_kind=str(payload.get("intent_kind") or "OTHER"),
                    confidence=conf,
                    age_days=age_days,
                    superseded=superseded,
                    text=text,
                )
            )
            evidence.append(
                EvidenceRef(
                    kind="intent",
                    text=text or "（未记录任务）",
                    at=at,
                    event_id=ev.id,
                    confidence=conf,
                    superseded=superseded,
                )
            )

    use_count, use_evidence = behavior
    frame_count, dwell_seconds = attention
    evidence.extend(use_evidence)

    signals = AffinitySignals(
        entity_name=entity.canonical_name,
        verbal=verbal,
        intents=intents,
        use_count=use_count,
        frame_count=frame_count,
        dwell_seconds=dwell_seconds,
    )
    if not (verbal or intents or use_count or frame_count):
        return None

    return EntityAffinity(
        entity_id=entity.id,
        entity_name=entity.canonical_name,
        aliases=list(entity.aliases or []),
        score=score_affinity(signals),
        signals=signals,
        evidence=evidence,
        pending_count=pending_count,
        last_signal_at=last_at,
    )


async def _observation_signals(
    session: AsyncSession, *, entity_ids: list[uuid.UUID]
) -> tuple[
    dict[uuid.UUID, tuple[int, list[EvidenceRef]]],
    dict[uuid.UUID, tuple[int, float]],
    dict[uuid.UUID, int],
]:
    """行为（USED/CONSUMED）与视觉注意力（帧数/停留秒数），外加待确认候选计数。

    走候选而不是直接走事件：事件的 event_type 已经把 USED 和 OBSERVED_AT 合并成了
    OBJECT_OBSERVED_AT，从事件里再也分不出「用过」和「只是看见」。谓词只在
    AtomicObservation 上，而候选是观察与实体之间唯一的桥。
    """
    behavior: dict[uuid.UUID, tuple[int, list[EvidenceRef]]] = {}
    attention: dict[uuid.UUID, tuple[int, float]] = {}
    pending: dict[uuid.UUID, int] = defaultdict(int)
    if not entity_ids:
        return behavior, attention, pending

    candidates = list(
        (
            await session.scalars(
                select(MemoryCandidate).where(MemoryCandidate.entity_id.in_(entity_ids))
            )
        ).all()
    )
    # 候选里存的是 str(uuid)，取回观察要转回 UUID
    obs_to_entity: dict[uuid.UUID, uuid.UUID] = {}
    for cand in candidates:
        if cand.entity_id is None:
            continue
        if cand.status in ("PENDING", "CONFLICTED"):
            pending[cand.entity_id] += 1
            continue
        if cand.status != "ACCEPTED":
            continue
        for raw in cand.observation_ids or []:
            try:
                obs_to_entity[uuid.UUID(str(raw))] = cand.entity_id
            except (ValueError, TypeError):
                continue

    if not obs_to_entity:
        return behavior, attention, pending

    observations = list(
        (
            await session.scalars(
                select(AtomicObservation).where(
                    AtomicObservation.id.in_(list(obs_to_entity))
                )
            )
        ).all()
    )

    use_counts: dict[uuid.UUID, int] = defaultdict(int)
    use_refs: dict[uuid.UUID, list[EvidenceRef]] = defaultdict(list)
    frames_by_entity: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for obs in observations:
        entity_id = obs_to_entity.get(obs.id)
        if entity_id is None:
            continue
        if obs.predicate in BEHAVIOR_PREDICATES:
            use_counts[entity_id] += 1
            if len(use_refs[entity_id]) < 5:
                use_refs[entity_id].append(
                    EvidenceRef(
                        kind="behavior",
                        text=f"{obs.predicate}：{obs.object_text}",
                        at=obs.phenomenon_time,
                        confidence=float((obs.confidence or {}).get("aggregate", 0.5)),
                    )
                )
        if obs.frame_asset_id is not None:
            frames_by_entity[entity_id].add(obs.frame_asset_id)

    dwell = await _dwell_seconds(session, frames_by_entity)
    for entity_id, frames in frames_by_entity.items():
        attention[entity_id] = (len(frames), dwell.get(entity_id, 0.0))
    for entity_id, n in use_counts.items():
        behavior[entity_id] = (n, use_refs[entity_id])
    return behavior, attention, dict(pending)


async def _dwell_seconds(
    session: AsyncSession, frames_by_entity: dict[uuid.UUID, set[uuid.UUID]]
) -> dict[uuid.UUID, float]:
    """把「物体出现在某视频的 k 张关键帧里」换算成画面停留秒数。

    关键帧是等间隔采样的，所以每一帧代表它前后各半个间隔的时间段——
    k 帧 ≈ k × 间隔 秒。间隔按每个视频自己的实际 offset 中位数算，
    而不是读配置：历史数据可能是用别的间隔抽的，配置改了不该让旧数据的停留时长跟着变。

    只有视频来源的帧（有 parent 和 offset）计入停留时长；独立照片没有时长概念。
    """
    all_frames = {f for frames in frames_by_entity.values() for f in frames}
    if not all_frames:
        return {}

    rows = list(
        (
            await session.execute(
                select(
                    FrameAsset.id,
                    EvidenceItem.parent_evidence_item_id,
                    EvidenceItem.offset_seconds,
                )
                .join(EvidenceItem, FrameAsset.evidence_item_id == EvidenceItem.id)
                .where(
                    FrameAsset.id.in_(list(all_frames)),
                    EvidenceItem.parent_evidence_item_id.is_not(None),
                )
            )
        ).all()
    )
    if not rows:
        return {}

    frame_to_video: dict[uuid.UUID, uuid.UUID] = {}
    offsets_by_video: dict[uuid.UUID, list[float]] = defaultdict(list)
    for frame_id, video_id, offset in rows:
        if offset is None:
            continue
        frame_to_video[frame_id] = video_id
        offsets_by_video[video_id].append(float(offset))

    interval_by_video: dict[uuid.UUID, float] = {}
    for video_id, offsets in offsets_by_video.items():
        ordered = sorted(set(offsets))
        gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b > a]
        interval_by_video[video_id] = median(gaps) if gaps else 0.0

    result: dict[uuid.UUID, float] = {}
    for entity_id, frames in frames_by_entity.items():
        total = 0.0
        for frame_id in frames:
            video_id = frame_to_video.get(frame_id)
            if video_id is None:
                continue
            total += interval_by_video.get(video_id, 0.0)
        if total > 0:
            result[entity_id] = round(total, 2)
    return result


def _age_days(at: datetime | None, now: datetime) -> float | None:
    if at is None:
        return None
    delta = (now - at).total_seconds() / 86400.0
    return max(delta, 0.0)


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


# v0.1 抽的偏好没有 sentiment 字段，只有一句自由文本。为了让旧数据也能进面板，
# 这里做一次最保守的兜底：只认明确的褒贬词，认不出就记 NEUTRAL（贡献 0），
# 绝不猜——猜错的方向比没有分数更糟。
_POSITIVE_HINTS = ("好吃", "不错", "喜欢", "好喝", "香", "赞", "爱吃", "满意", "好用")
_NEGATIVE_HINTS = ("难吃", "不喜欢", "难喝", "差", "糟", "腻", "软了", "不好用", "失望")


def _infer_sentiment(text: str) -> str:
    if not text:
        return "NEUTRAL"
    has_pos = any(h in text for h in _POSITIVE_HINTS)
    has_neg = any(h in text for h in _NEGATIVE_HINTS)
    if has_pos and not has_neg:
        return "LIKE"
    if has_neg and not has_pos:
        return "DISLIKE"
    return "NEUTRAL"
