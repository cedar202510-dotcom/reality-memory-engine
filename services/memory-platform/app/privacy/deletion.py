"""forget-recent 删除流水线：deletion_request → jobs → 执行 → tombstone + audit。

窗口内：删证据文件、frame_assets、audio_assets、observations、candidates；事件标记失效
（valid_to=now，不改历史）；重算受影响投影；清理孤儿实体（清向量）。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..memory.events import record_audit
from ..memory.projections import recompute_projection
from ..models import (
    AtomicObservation,
    AudioAsset,
    DeletionJob,
    DeletionRequest,
    DeletionTombstone,
    Entity,
    EvidenceItem,
    FrameAsset,
    MemoryCandidate,
    MemoryEvent,
    StateProjection,
    utcnow,
)

JOB_SUBSYSTEMS = ("evidence", "frame", "audio", "observation", "candidate", "event", "vector", "projection")


async def execute_forget_recent(
    session: AsyncSession, *, minutes: int, scope: list[str]
) -> tuple[DeletionRequest, list[DeletionJob], DeletionTombstone]:
    since = utcnow() - timedelta(minutes=minutes)
    request = DeletionRequest(
        scope={"minutes": minutes, "scope": scope, "since": since.isoformat()}, status="RUNNING"
    )
    session.add(request)
    await session.flush()
    jobs = [DeletionJob(request_id=request.id, subsystem=s) for s in scope if s in JOB_SUBSYSTEMS]
    session.add_all(jobs)
    await session.flush()

    summary: dict[str, int] = {}
    affected_entities: set[uuid.UUID] = set()

    async def run_job(name: str, fn) -> None:
        job = next((j for j in jobs if j.subsystem == name), None)
        if job is None:
            return
        job.attempt_count += 1
        try:
            summary[name] = await fn()
            job.status = "DONE"
        except Exception as exc:  # noqa: BLE001 - job 语义：记录错误继续其它子系统
            job.status = "FAILED"
            job.last_error = str(exc)
        job.finished_at = utcnow()

    # ---- evidence：物理删文件 ----
    window_items = list(
        (
            await session.scalars(
                select(EvidenceItem).where(EvidenceItem.created_at >= since)
            )
        ).all()
    )
    window_item_ids = [i.id for i in window_items]

    async def _evidence() -> int:
        n = 0
        for item in window_items:
            if item.storage_ref and Path(item.storage_ref).exists():
                Path(item.storage_ref).unlink()
            item.storage_ref = None
            item.retention_state = "DELETED"
            n += 1
        return n

    # ---- frame / audio / observation：删长期结构化表示 ----
    window_frames = (
        list(
            (
                await session.scalars(
                    select(FrameAsset).where(FrameAsset.evidence_item_id.in_(window_item_ids))
                )
            ).all()
        )
        if window_item_ids
        else []
    )
    window_frame_ids = [f.id for f in window_frames]

    window_audios = (
        list(
            (
                await session.scalars(
                    select(AudioAsset).where(AudioAsset.evidence_item_id.in_(window_item_ids))
                )
            ).all()
        )
        if window_item_ids
        else []
    )
    window_audio_ids = [a.id for a in window_audios]

    async def _observation() -> int:
        clauses = []
        if window_frame_ids:
            clauses.append(AtomicObservation.frame_asset_id.in_(window_frame_ids))
        if window_audio_ids:
            clauses.append(AtomicObservation.audio_asset_id.in_(window_audio_ids))
        if not clauses:
            return 0
        res = await session.execute(delete(AtomicObservation).where(or_(*clauses)))
        return res.rowcount or 0

    async def _frame() -> int:
        if not window_frame_ids:
            return 0
        res = await session.execute(delete(FrameAsset).where(FrameAsset.id.in_(window_frame_ids)))
        return res.rowcount or 0

    async def _audio() -> int:
        if not window_audio_ids:
            return 0
        res = await session.execute(delete(AudioAsset).where(AudioAsset.id.in_(window_audio_ids)))
        return res.rowcount or 0

    # ---- candidate：窗口内的候选直接删除 ----
    async def _candidate() -> int:
        res = await session.execute(
            delete(MemoryCandidate).where(MemoryCandidate.created_at >= since)
        )
        return res.rowcount or 0

    # ---- event：标记失效（valid_to=now），不改历史 ----
    async def _event() -> int:
        events = list(
            (
                await session.scalars(
                    select(MemoryEvent).where(
                        MemoryEvent.ingested_at >= since, MemoryEvent.valid_to.is_(None)
                    )
                )
            ).all()
        )
        for ev in events:
            ev.valid_to = utcnow()
            if ev.entity_id:
                affected_entities.add(ev.entity_id)
        return len(events)

    # ---- projection：重算受影响实体 ----
    async def _projection() -> int:
        for entity_id in affected_entities:
            await recompute_projection(session, entity_id=entity_id)
        return len(affected_entities)

    # ---- vector：清理窗口内创建的实体；无事件引用的删除，有事件（已失效）的清向量 ----
    async def _vector() -> int:
        orphans = list(
            (
                await session.scalars(
                    select(Entity).where(Entity.created_at >= since)
                )
            ).all()
        )
        n = 0
        for ent in orphans:
            any_event = await session.scalar(
                select(MemoryEvent.id).where(MemoryEvent.entity_id == ent.id).limit(1)
            )
            if any_event is None:
                await session.execute(
                    delete(StateProjection).where(StateProjection.entity_id == ent.id)
                )
                await session.delete(ent)
            else:
                ent.embedding = None  # 事件行保留作历史，向量清除
            n += 1
        return n

    await run_job("event", _event)          # 先关事件，收集受影响实体
    await run_job("observation", _observation)
    await run_job("frame", _frame)
    await run_job("audio", _audio)
    await run_job("evidence", _evidence)
    await run_job("candidate", _candidate)
    await run_job("projection", _projection)
    await run_job("vector", _vector)

    failed = [j for j in jobs if j.status == "FAILED"]
    request.status = "FAILED" if failed else "DONE"

    audit_hash = hashlib.sha256(
        json.dumps({"request_id": str(request.id), "summary": summary}, sort_keys=True).encode()
    ).hexdigest()
    tombstone = DeletionTombstone(request_id=request.id, audit_hash=audit_hash)
    session.add(tombstone)
    await session.flush()
    await record_audit(
        session,
        actor="user:owner",
        action="forget",
        target=f"deletion_request:{request.id}",
        detail={"minutes": minutes, "summary": summary, "audit_hash": audit_hash},
    )
    await session.commit()
    return request, jobs, tombstone
