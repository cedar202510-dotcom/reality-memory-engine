"""语音处理器：消费 outbox(audio.process)。

两步式音频解析（ASR 层 → 语义层）：
1) Transcriber 转写 → audio_assets（媒体删除后的长期表示；可选 transcript embedding）
2) AudioExtractor 语义抽取（偏好/意图/使用/消耗）→ AtomicObservation（挂 audio_asset_id）
3) 每条观察生成 MemoryCandidate → 候选门评估（与帧流水线共用同一套门/投影机制）

任何阶段失败都不抛出（worker 语义：记审计、弃本条但继续）。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..asr.base import Transcriber
from ..llm.base import LLMClient
from ..memory.events import record_audit
from ..memory.gate import PREDICATE_TO_EVENT_TYPE, evaluate_candidate
from ..memory.seed import get_default_household_id
from ..models import (
    AtomicObservation,
    AudioAsset,
    EvidenceItem,
    MemoryCandidate,
    SourceEnvelope,
)
from .stages import (
    AUDIO_ALLOWED_PREDICATES,
    AUDIO_PARSER_VERSION,
    AudioExtractInput,
    build_audio_extractor,
)


async def process_audio_item(
    session: AsyncSession,
    *,
    evidence_item_id: uuid.UUID,
    llm: LLMClient,
    transcriber: Transcriber,
) -> AudioAsset | None:
    """处理单个音频证据；ASR/抽取失败都优雅降级（记审计后返回 None）。"""
    item = await session.get(EvidenceItem, evidence_item_id)
    if item is None or item.retention_state != "ACTIVE":
        return None
    envelope = await session.get(SourceEnvelope, item.envelope_id)
    if envelope is None:
        return None

    async def _skip(reason: str) -> None:
        await record_audit(
            session,
            actor="system/audio-worker",
            action="audio_skip",
            target=f"evidence:{item.id}",
            detail={"reason": reason},
        )
        await session.commit()

    media_readable = bool(item.storage_ref and Path(item.storage_ref).exists())
    if not media_readable:
        await _skip("media_missing")
        return None

    # ---- 阶段 1：ASR 转写 ----
    data = Path(item.storage_ref).read_bytes()
    segments = await transcriber.transcribe(data, media_kind=item.media_kind)
    if segments is None:
        await _skip("asr_unavailable")  # 未配置/转写失败：降级不阻塞
        return None
    transcript = " ".join(seg.text for seg in segments).strip()
    if not transcript:
        await _skip("empty_transcript")
        return None

    vectors = await llm.embed([transcript])
    embedding = vectors[0] if vectors else None
    duration = max((seg.end for seg in segments), default=None)

    asset = AudioAsset(
        evidence_item_id=item.id,
        transcript=transcript,
        segments=[seg.model_dump() for seg in segments],
        duration_seconds=duration,
        embedding=embedding,
        captured_at=envelope.occurred_at,
    )
    session.add(asset)
    await session.flush()

    # ---- 阶段 2：语义抽取（偏好/意图/使用/消耗） ----
    extractor = build_audio_extractor(llm)
    ext = await extractor.run(
        AudioExtractInput(
            file_name=Path(item.storage_ref).name,
            transcript=transcript,
            captured_at=envelope.occurred_at.isoformat(),
        )
    )
    if ext is None:
        await session.commit()
        return asset

    household_id = await get_default_household_id(session)
    for obs_in in ext.observations:
        if obs_in.predicate not in AUDIO_ALLOWED_PREDICATES:
            continue  # 语音白名单外谓词直接丢弃
        obs = AtomicObservation(
            audio_asset_id=asset.id,
            predicate=obs_in.predicate,
            subject_text=obs_in.subject_text,
            object_text=obs_in.object_text,
            value=obs_in.value,
            phenomenon_time=envelope.occurred_at,
            observed_at=envelope.observed_at,
            confidence=obs_in.confidence.model_dump(),
            parser_version=AUDIO_PARSER_VERSION,
        )
        session.add(obs)
        await session.flush()

        candidate = MemoryCandidate(
            observation_ids=[str(obs.id)],
            event_type=PREDICATE_TO_EVENT_TYPE[obs_in.predicate],
            payload={"object_text": obs_in.object_text, **obs_in.value},
            confidence=obs_in.confidence.model_dump(),
            status="PENDING",
            source="perception",
        )
        session.add(candidate)
        await session.flush()

        obj_vec = await llm.embed([obs_in.object_text])
        await evaluate_candidate(
            session,
            candidate=candidate,
            household_id=household_id,
            phenomenon_time=envelope.occurred_at,
            observed_at=envelope.observed_at,
            ingested_at=envelope.ingested_at,
            object_embedding=obj_vec[0] if obj_vec else None,
        )

    await session.commit()
    return asset
