"""帧处理器：消费 outbox(frame.process)。

1) VLM caption + scene_tags → frame_assets（媒体删除后的长期表示；可选 embedding）
2) 媒体仍可读时可选编码 CLIP 视觉向量（visual_embedding；媒体删除后仍可视觉检索）
3) 高价值帧（trigger=explicit 或 scene_tags 非空）→ 结构化抽取 AtomicObservation（schema 外字段丢弃）
4) 每条观察生成 MemoryCandidate → 候选门评估
"""
from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.base import LLMClient
from ..memory.gate import PREDICATE_TO_EVENT_TYPE, evaluate_candidate
from ..memory.seed import get_default_household_id
from ..models import (
    AtomicObservation,
    EvidenceItem,
    FrameAsset,
    MemoryCandidate,
    SourceEnvelope,
)
from ..schemas import ALLOWED_PREDICATES
from ..vision.base import VisionEncoder
from .stages import PARSER_VERSION, ExtractInput, CaptionInput, build_captioner, build_extractor


def _to_data_url(path: str) -> str:
    """读图 → 长边缩到 vlm_image_max_side → JPEG base64 data URL。

    原始帧可能 10MB+（如 4032x3024 PNG），直接 base64 发 VLM 既慢又可能超限；
    缩图对 caption/精判质量影响可忽略。
    """
    import io

    from PIL import Image

    from ..config import get_settings

    settings = get_settings()
    img = Image.open(path).convert("RGB")
    img.thumbnail((settings.vlm_image_max_side, settings.vlm_image_max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=settings.vlm_image_jpeg_quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


async def process_evidence_item(
    session: AsyncSession,
    *,
    evidence_item_id: uuid.UUID,
    llm: LLMClient,
    vision: VisionEncoder | None = None,
) -> FrameAsset | None:
    """处理单个证据帧；任何阶段失败都不抛出（worker 语义：弃帧但继续）。"""
    item = await session.get(EvidenceItem, evidence_item_id)
    if item is None or item.retention_state != "ACTIVE":
        return None
    envelope = await session.get(SourceEnvelope, item.envelope_id)
    if envelope is None:
        return None

    file_name = Path(item.storage_ref).name if item.storage_ref else f"{item.id}.jpg"
    media_readable = bool(item.storage_ref and Path(item.storage_ref).exists())
    images = [_to_data_url(item.storage_ref)] if media_readable else None

    # ---- 阶段 1：caption ----
    captioner = build_captioner(llm)
    cap = await captioner.run(
        CaptionInput(
            file_name=file_name,
            captured_at=envelope.occurred_at.isoformat(),
            meta_hint=json.dumps(envelope.meta or {}, ensure_ascii=False),
        ),
        images=images,
    )
    if cap is None:
        return None  # 输出契约校验失败，重试后弃帧

    embed_text = f"{cap.caption} {' '.join(cap.scene_tags)}".strip()
    vectors = await llm.embed([embed_text])
    embedding = vectors[0] if vectors else None

    # ---- 可选：CLIP 视觉向量（仅在媒体仍可读时编码；失败/None 留空不阻塞） ----
    visual_embedding: list[float] | None = None
    if vision is not None and media_readable:
        visual_vectors = await vision.embed_images([Path(item.storage_ref).read_bytes()])
        visual_embedding = visual_vectors[0] if visual_vectors else None

    frame = FrameAsset(
        evidence_item_id=item.id,
        caption=cap.caption,
        scene_tags=cap.scene_tags,
        embedding=embedding,
        visual_embedding=visual_embedding,
        captured_at=envelope.occurred_at,
        quality={"file_name": file_name},
    )
    session.add(frame)
    await session.flush()

    # ---- 阶段 3：高价值帧结构化抽取 ----
    high_value = envelope.trigger == "explicit" or bool(cap.scene_tags)
    if not high_value:
        await session.commit()
        return frame

    extractor = build_extractor(llm)
    ext = await extractor.run(
        ExtractInput(
            file_name=file_name,
            caption=cap.caption,
            scene_tags="、".join(cap.scene_tags),
            captured_at=envelope.occurred_at.isoformat(),
        ),
        images=images,
    )
    if ext is None:
        await session.commit()
        return frame

    household_id = await get_default_household_id(session)
    for obs_in in ext.observations:
        if obs_in.predicate not in ALLOWED_PREDICATES:
            continue  # schema 外谓词直接丢弃
        obs = AtomicObservation(
            frame_asset_id=frame.id,
            predicate=obs_in.predicate,
            subject_text=obs_in.subject_text,
            object_text=obs_in.object_text,
            value=obs_in.value,
            phenomenon_time=envelope.occurred_at,
            observed_at=envelope.observed_at,
            confidence=obs_in.confidence.model_dump(),
            parser_version=PARSER_VERSION,
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
            frame_visual_embedding=visual_embedding,
        )

    await session.commit()
    return frame
