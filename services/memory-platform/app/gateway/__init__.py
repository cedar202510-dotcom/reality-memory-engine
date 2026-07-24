"""Ingest API：幂等接收信封 + 证据落盘 + 去重（图像 aHash / 音频内容哈希）+ outbox(frame.process/audio.process)。"""
from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi import File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..models import (
    AuditRecord,
    EvidenceItem,
    OutboxEvent,
    SourceEnvelope,
    utcnow,
)
from ..schemas import IngestResponse, SourceEnvelopeIn, SourceEnvelopeOut
from .phash import compute_phash, hamming_distance

router = APIRouter(prefix="/internal/v1", tags=["gateway"])


@router.post("/envelopes", response_model=IngestResponse)
async def ingest_envelope(
    envelope: str = Form(..., description="SourceEnvelopeIn JSON"),
    files: list[UploadFile] = File(default=[]),
    session: AsyncSession = Depends(get_session),
) -> IngestResponse:
    settings = get_settings()
    try:
        env_in = SourceEnvelopeIn.model_validate(json.loads(envelope))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"envelope 校验失败: {exc}") from exc

    # ---- 幂等：重复投递直接返回既有信封 ----
    existing = await session.scalar(
        select(SourceEnvelope).where(SourceEnvelope.idempotency_key == env_in.idempotency_key)
    )
    if existing is not None:
        item_ids = list(
            (
                await session.scalars(
                    select(EvidenceItem.id).where(EvidenceItem.envelope_id == existing.id)
                )
            ).all()
        )
        return IngestResponse(
            envelope=SourceEnvelopeOut.model_validate(existing),
            evidence_item_ids=item_ids,
            idempotent_replay=True,
        )

    env = SourceEnvelope(
        device_id=env_in.device_id,
        source_session_id=env_in.source_session_id,
        occurred_at=env_in.occurred_at,
        observed_at=env_in.observed_at,
        idempotency_key=env_in.idempotency_key,
        trigger=env_in.trigger,
        modality=env_in.modality,
        meta=env_in.meta,
    )
    session.add(env)
    await session.flush()

    evidence_dir = Path(settings.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ttl_until = utcnow() + timedelta(minutes=settings.evidence_ttl_minutes)
    dedup_since = utcnow() - timedelta(minutes=settings.phash_dedup_window_minutes)

    # 近 1 小时活跃证据的同模态哈希（用于"过相似/同内容→只更新持续证据不新建"）
    recent = (
        await session.scalars(
            select(EvidenceItem).where(
                EvidenceItem.created_at >= dedup_since,
                EvidenceItem.retention_state == "ACTIVE",
                EvidenceItem.media_kind == env.modality,
                EvidenceItem.phash.is_not(None),
            )
        )
    ).all()

    is_audio = env.modality == "audio"
    item_ids: list = []
    dup_ids: list = []
    for f in files:
        data = await f.read()
        if not data:
            continue
        if is_audio:
            # 音频无法做感知哈希：用内容 SHA-256 的前 8 字节做精确去重（复用 phash 列）
            phash = int.from_bytes(hashlib.sha256(data).digest()[:8], "big", signed=True)
            match = next((e for e in recent if e.phash == phash), None)
        else:
            phash = compute_phash(data)
            match = next(
                (e for e in recent if hamming_distance(phash, e.phash or 0) <= settings.phash_hamming_threshold),
                None,
            )
        if match is not None:
            # 持续证据：只刷新 TTL，不新建证据、不落盘
            match.ttl_until = ttl_until
            dup_ids.append(match.id)
            continue

        item = EvidenceItem(
            envelope_id=env.id,
            media_kind=env.modality,
            phash=phash,
            ttl_until=ttl_until,
        )
        session.add(item)
        await session.flush()
        # 保留原始文件名（采集端语义信息，Fake/真实模型都可利用）
        safe_name = Path(f.filename or ("audio.m4a" if is_audio else "frame.jpg")).name.replace("/", "_")
        path = evidence_dir / f"{item.id}-{safe_name}"
        path.write_bytes(data)
        item.storage_ref = str(path)
        item_ids.append(item.id)
        # 同事务写 outbox：perception worker 按模态异步消费
        topic = "audio.process" if is_audio else "frame.process"
        session.add(OutboxEvent(topic=topic, payload={"evidence_item_id": str(item.id)}))

    session.add(
        AuditRecord(
            actor=f"device:{env.device_id}" if env.device_id else "device:unknown",
            action="ingest",
            target=f"envelope:{env.id}",
            detail={"n_files": len(item_ids), "n_duplicates": len(dup_ids), "trigger": env.trigger},
        )
    )
    await session.commit()
    return IngestResponse(
        envelope=SourceEnvelopeOut.model_validate(env),
        evidence_item_ids=item_ids,
        duplicate_evidence_ids=dup_ids,
    )
