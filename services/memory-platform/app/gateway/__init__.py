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
from ..media import normalize_image
from ..models import (
    AuditRecord,
    EvidenceItem,
    OutboxEvent,
    SourceEnvelope,
    utcnow,
)
from ..schemas import (
    DeviceCaptureIntentIn,
    DeviceCaptureWindowIn,
    DeviceEvidenceIngestResponse,
    DeviceEvidenceItemIn,
    DeviceSourceEnvelopeIn,
    IngestResponse,
    SourceEnvelopeIn,
    SourceEnvelopeOut,
)
from .phash import compute_phash, hamming_distance

router = APIRouter(prefix="/internal/v1", tags=["gateway"])


@router.post("/envelopes", response_model=IngestResponse)
async def ingest_envelope(
    envelope: str = Form(..., description="SourceEnvelopeIn JSON"),
    files: list[UploadFile] = File(default=[]),
    session: AsyncSession = Depends(get_session),
) -> IngestResponse:
    try:
        env_in = SourceEnvelopeIn.model_validate(json.loads(envelope))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"envelope 校验失败: {exc}") from exc
    return await _ingest_envelope(env_in=env_in, files=files, session=session)


@router.post("/device-evidence", response_model=DeviceEvidenceIngestResponse)
async def ingest_device_evidence(
    source_envelope: str = Form(..., description="rme.source-envelope.v1 JSON"),
    evidence_item: str = Form(..., description="rme.evidence-item.v1 JSON"),
    capture_intent: str | None = Form(default=None, description="rme.capture-intent.v1 JSON"),
    capture_window: str | None = Form(default=None, description="rme.capture-window.v1 JSON"),
    file: UploadFile = File(..., description="Debug 联调阶段上传的明文证据"),
    session: AsyncSession = Depends(get_session),
) -> DeviceEvidenceIngestResponse:
    """接收正式设备契约并映射到 v0 内部模型。

    当前端点只用于本机或受控局域网联调。生产版本必须改为可由服务端解封装的数据密钥，
    不能依赖 Android Keystore 密钥，也不能长期上传明文。
    """
    try:
        source_raw = json.loads(source_envelope)
        evidence_raw = json.loads(evidence_item)
        source = DeviceSourceEnvelopeIn.model_validate(source_raw)
        evidence = DeviceEvidenceItemIn.model_validate(evidence_raw)
        intent_raw = json.loads(capture_intent) if capture_intent else None
        window_raw = json.loads(capture_window) if capture_window else None
        intent = DeviceCaptureIntentIn.model_validate(intent_raw) if intent_raw else None
        window = DeviceCaptureWindowIn.model_validate(window_raw) if window_raw else None
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"设备契约校验失败: {exc}") from exc

    if source.payload_kind != "EVIDENCE_ITEM":
        raise HTTPException(status_code=422, detail="device-evidence 只接收 EVIDENCE_ITEM")
    if source.payload_ref != evidence.evidence_item_id:
        raise HTTPException(status_code=422, detail="payload_ref 与 evidence_item_id 不一致")
    if source.source_envelope_id != evidence.source_envelope_id:
        raise HTTPException(status_code=422, detail="source_envelope_id 关联不一致")
    if source.capture_window_id != evidence.capture_window_id:
        raise HTTPException(status_code=422, detail="capture_window_id 关联不一致")
    if source.modality != evidence.modality:
        raise HTTPException(status_code=422, detail="来源信封与证据的 modality 不一致")
    if intent is not None:
        if source.capture_intent_id != intent.capture_intent_id:
            raise HTTPException(status_code=422, detail="capture_intent_id 关联不一致")
        if source.capture_session_id != intent.capture_session_id:
            raise HTTPException(status_code=422, detail="采集意图的 session 关联不一致")
    if window is not None:
        if source.capture_window_id != window.capture_window_id:
            raise HTTPException(status_code=422, detail="采集窗口编号关联不一致")
        if source.capture_session_id != window.capture_session_id:
            raise HTTPException(status_code=422, detail="采集窗口的 session 关联不一致")
        if source.capture_intent_id != window.capture_intent_id:
            raise HTTPException(status_code=422, detail="采集窗口的 intent 关联不一致")
        if window.state != "FINALIZED":
            raise HTTPException(status_code=422, detail="只接收 FINALIZED 采集窗口")

    uploaded = await file.read()
    if not uploaded:
        raise HTTPException(status_code=422, detail="证据文件为空")
    await file.seek(0)

    warnings: list[str] = []
    actual_hash = hashlib.sha256(uploaded).hexdigest()
    if evidence.byte_count != len(uploaded):
        warnings.append(
            f"byte_count 元数据为 {evidence.byte_count}，上传明文为 {len(uploaded)}；"
            "旧 APK 可能记录了密文字节数"
        )
    if evidence.sha256.lower() != actual_hash:
        warnings.append("sha256 与上传明文不一致；旧 APK 可能记录了密文摘要")

    trigger = _map_device_trigger(intent_raw)
    meta = {
        "contract_version": "rme-device-ingest.v1-debug",
        "transport_mode": "DEBUG_PLAINTEXT",
        "source_envelope": source_raw,
        "evidence_item": evidence_raw,
        "capture_intent": intent_raw,
        "capture_window": window_raw,
        "uploaded_plaintext": {
            "byte_count": len(uploaded),
            "sha256": actual_hash,
            "content_type": file.content_type,
        },
        "validation_warnings": warnings,
    }
    legacy = SourceEnvelopeIn(
        device_id=None,
        source_session_id=source.capture_session_id,
        occurred_at=source.occurred_at,
        observed_at=source.observed_at,
        idempotency_key=source.idempotency_key,
        trigger=trigger,
        modality=source.modality.lower(),
        meta=meta,
    )
    ingest = await _ingest_envelope(env_in=legacy, files=[file], session=session)
    return DeviceEvidenceIngestResponse(
        source_envelope_id=source.source_envelope_id,
        evidence_item_id=evidence.evidence_item_id,
        ingest=ingest,
        validation_warnings=warnings,
    )


def _map_device_trigger(capture_intent: dict | None) -> str:
    signal = str((capture_intent or {}).get("signal_kind", ""))
    if signal == "USER_EXPLICIT":
        return "explicit"
    return "auto"


async def _ingest_envelope(
    *,
    env_in: SourceEnvelopeIn,
    files: list[UploadFile],
    session: AsyncSession,
) -> IngestResponse:
    settings = get_settings()
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

    is_image = env.modality == "image"
    item_ids: list = []
    dup_ids: list = []
    n_converted = 0
    for f in files:
        data = await f.read()
        if not data:
            continue
        file_name = f.filename
        if is_image:
            # HEIC/HEIF 在入库边界就转成 JPEG：落盘之后 phash/VLM/CLIP/前端四个消费者
            # 各自解码，漏一个就是一种沉默的坏法（详见 app/media/images.py）。
            normalized = normalize_image(
                data,
                filename=file_name,
                jpeg_quality=settings.image_normalize_jpeg_quality,
                max_side=settings.image_normalize_max_side,
            )
            data = normalized.data
            file_name = normalized.filename
            n_converted += 1 if normalized.converted else 0
        if is_image and normalized.decodable:
            phash = compute_phash(data)
            match = next(
                (e for e in recent if hamming_distance(phash, e.phash or 0) <= settings.phash_hamming_threshold),
                None,
            )
        else:
            # 音频、视频、传感器，以及解不开的「图片」：用内容摘要做精确去重
            # （v0 暂复用 phash 列）。坏图不能让整个信封 500，证据先留住。
            phash = int.from_bytes(hashlib.sha256(data).digest()[:8], "big", signed=True)
            match = next((e for e in recent if e.phash == phash), None)
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
        default_name = {
            "image": "frame.jpg",
            "audio": "audio.bin",
            "video": "video.mp4",
            "sensor": "sensor.ndjson",
        }.get(env.modality, "evidence.bin")
        safe_name = Path(file_name or default_name).name.replace("/", "_")
        path = evidence_dir / f"{item.id}-{safe_name}"
        path.write_bytes(data)
        item.storage_ref = str(path)
        item_ids.append(item.id)
        # 传感器仍然只可靠落盘（没有解析器）；视频由 video.process 拆成关键帧+音轨。
        topic = {
            "image": "frame.process",
            "audio": "audio.process",
            "video": "video.process",
        }.get(env.modality)
        if topic is not None:
            session.add(OutboxEvent(topic=topic, payload={"evidence_item_id": str(item.id)}))

    session.add(
        AuditRecord(
            actor=f"device:{env.device_id}" if env.device_id else "device:unknown",
            action="ingest",
            target=f"envelope:{env.id}",
            detail={
                "n_files": len(item_ids),
                "n_duplicates": len(dup_ids),
                "n_normalized": n_converted,
                "trigger": env.trigger,
            },
        )
    )
    await session.commit()
    return IngestResponse(
        envelope=SourceEnvelopeOut.model_validate(env),
        evidence_item_ids=item_ids,
        duplicate_evidence_ids=dup_ids,
    )
