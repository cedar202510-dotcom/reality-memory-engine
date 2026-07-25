"""视频处理器：消费 outbox(video.process)。

视频是本系统里唯一的双模态证据，处理方式是「拆成系统已经会处理的东西」而不是
新建一条平行流水线：

  视频 ──┬─ 关键帧 → 子 EvidenceItem(media_kind=image) → 既有帧流水线（caption/CLIP/观察）
         └─ 音轨   → ASR → AudioAsset → 既有语音语义抽取（偏好/意图/使用/消耗）

两路的产物落在同一批表里，物体名对得上就自动汇聚到同一个 Entity——
「画面里有花生」和「说花生好吃」于是变成同一个物体的两条证据，
喜好度打分要的就是这个交集。

执行顺序是刻意的：先跑完关键帧再做语音语义抽取。因为语音抽取需要把
「这个一般般」里的「这个」还原成具体物体，而那份物体列表只有帧跑完才有。
代价是这个 job 很重（N 次 VLM + 1 次 ASR），所以它按帧增量提交：
中途失败重试时已经处理过的帧会被跳过，不会把 VLM 调用重付一遍。
"""
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..asr.base import Transcriber
from ..config import get_settings
from ..llm.base import LLMClient
from ..memory.events import record_audit
from ..models import (
    AtomicObservation,
    AudioAsset,
    EvidenceItem,
    FrameAsset,
    SourceEnvelope,
)
from ..vision.base import VisionEncoder
from . import process_evidence_item
from .audio import extract_transcript_observations
from .video_media import (
    ASR_MEDIA_KIND,
    extract_audio_track,
    extract_keyframes,
    ffmpeg_available,
    probe_video,
)


async def process_video_item(
    session: AsyncSession,
    *,
    evidence_item_id: uuid.UUID,
    llm: LLMClient,
    vision: VisionEncoder | None = None,
    transcriber: Transcriber | None = None,
) -> dict[str, int]:
    """处理单个视频证据。返回 {n_keyframes, n_observations} 便于审计与测试断言。

    任何一路失败都不影响另一路：没有音轨的视频照样出关键帧，
    ffmpeg 抽帧失败的视频照样能出转写。
    """
    stats = {"n_keyframes": 0, "n_frame_assets": 0, "n_audio_observations": 0}
    item = await session.get(EvidenceItem, evidence_item_id)
    if item is None or item.retention_state != "ACTIVE":
        return stats
    envelope = await session.get(SourceEnvelope, item.envelope_id)
    if envelope is None:
        return stats

    async def _skip(reason: str) -> None:
        await record_audit(
            session,
            actor="system/video-worker",
            action="video_skip",
            target=f"evidence:{item.id}",
            detail={"reason": reason},
        )
        await session.commit()

    if not (item.storage_ref and Path(item.storage_ref).exists()):
        await _skip("media_missing")
        return stats
    if not ffmpeg_available():
        # 不装 ffmpeg 就整体降级：视频保持 PENDING，装上以后可以重新入队补跑，
        # 比在这里静默产出半个结果好。
        await _skip("ffmpeg_unavailable")
        return stats

    settings = get_settings()
    source = Path(item.storage_ref)
    probe = probe_video(source)
    if probe is None:
        await _skip("probe_failed")
        return stats

    # ---- 阶段 1：音轨 → ASR ----
    # 转写必须排在抽帧之前。ASR 只有一次调用，而抽帧是 N 次 VLM，顺序反过来
    # 成本一样，但把转写先拿到手，后面每一帧的 caption 都能用它来命名画面里的东西
    # （「黄色颗粒状食物」→「鸡米花」）。这一步是跨模态命名一致的前提。
    asset = None
    if transcriber is not None and probe.has_audio:
        asset = await _ensure_transcript(
            session,
            item=item,
            envelope=envelope,
            source=source,
            llm=llm,
            transcriber=transcriber,
            settings=settings,
        )
    transcript = asset.transcript if asset is not None else ""

    # ---- 阶段 2：关键帧 → 子证据 → 既有帧流水线（带语音上下文） ----
    keyframe_items = await _ensure_keyframes(
        session, item=item, envelope=envelope, probe=probe, settings=settings
    )
    stats["n_keyframes"] = len(keyframe_items)

    visual_terms: list[str] = []
    for child in keyframe_items:
        existing = await session.scalar(
            select(FrameAsset).where(FrameAsset.evidence_item_id == child.id)
        )
        if existing is None:
            # 复用帧流水线：caption + scene_tags + CLIP + 观察抽取全都免费拿到。
            # 它内部会自己 commit，所以这里天然是「每帧一个断点」。
            existing = await process_evidence_item(
                session,
                evidence_item_id=child.id,
                llm=llm,
                vision=vision,
                audio_context=transcript,
            )
        if existing is not None:
            stats["n_frame_assets"] += 1
            visual_terms.extend(existing.scene_tags or [])

    # ---- 阶段 3：语音语义抽取（带画面上下文，反向补全指代） ----
    # 到这里两个方向都通了：画面帮语音消解「这个」，语音帮画面命名「那团黄色的」。
    # （中间几个阶段各自 commit 过，但 SessionLocal 是 expire_on_commit=False，
    #   item/envelope/asset 这几个实例仍然可以直接用，不必重取。）
    already_extracted = asset is not None and bool(
        await session.scalar(
            select(AtomicObservation.id)
            .where(AtomicObservation.audio_asset_id == asset.id)
            .limit(1)
        )
    )
    if asset is not None and not already_extracted:
        stats["n_audio_observations"] = await extract_transcript_observations(
            session,
            llm=llm,
            asset=asset,
            envelope=envelope,
            file_name=source.name,
            visual_context=_visual_context(visual_terms),
        )

    await record_audit(
        session,
        actor="system/video-worker",
        action="video_processed",
        target=f"evidence:{item.id}",
        detail={
            "duration_seconds": probe.duration_seconds,
            "has_audio": probe.has_audio,
            **stats,
        },
    )
    await session.commit()
    return stats


async def _ensure_keyframes(
    session: AsyncSession,
    *,
    item: EvidenceItem,
    envelope: SourceEnvelope,
    probe,
    settings,
) -> list[EvidenceItem]:
    """抽帧并落成子 EvidenceItem；已经抽过就直接返回旧的（重试幂等）。"""
    existing = list(
        (
            await session.scalars(
                select(EvidenceItem)
                .where(EvidenceItem.parent_evidence_item_id == item.id)
                .order_by(EvidenceItem.offset_seconds)
            )
        ).all()
    )
    if existing:
        return existing
    if not probe.has_video:
        return []

    duration = probe.duration_seconds
    if duration and duration > settings.video_max_duration_seconds > 0:
        duration = float(settings.video_max_duration_seconds)

    frames = extract_keyframes(
        item.storage_ref,
        interval_seconds=settings.video_keyframe_interval_seconds,
        max_frames=settings.video_max_keyframes,
        max_side=settings.video_keyframe_max_side,
        duration_seconds=duration,
    )
    if not frames:
        return []

    evidence_dir = Path(settings.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(item.storage_ref).stem

    children: list[EvidenceItem] = []
    for kf in frames:
        child = EvidenceItem(
            envelope_id=item.envelope_id,
            media_kind="image",
            # 关键帧的 TTL 跟源视频一致：源片过期时抽出来的帧不该活得更久
            ttl_until=item.ttl_until,
            parent_evidence_item_id=item.id,
            offset_seconds=kf.offset_seconds,
        )
        session.add(child)
        await session.flush()
        path = evidence_dir / f"{child.id}-{stem}-kf{kf.index:03d}.jpg"
        path.write_bytes(kf.data)
        child.storage_ref = str(path)
        children.append(child)
    await session.commit()
    return children


async def _ensure_transcript(
    session: AsyncSession,
    *,
    item: EvidenceItem,
    envelope: SourceEnvelope,
    source: Path,
    llm: LLMClient,
    transcriber: Transcriber,
    settings,
) -> AudioAsset | None:
    """抽音轨 → 转写 → AudioAsset（挂在视频证据上）。已有就直接返回（重试幂等）。

    只做转写不做语义抽取：语义抽取要等关键帧跑完拿到画面上下文，
    而转写本身要尽早拿到，因为关键帧的 caption 反过来依赖它来命名物体。
    """
    existing = await session.scalar(
        select(AudioAsset).where(AudioAsset.evidence_item_id == item.id)
    )
    if existing is not None:
        return existing  # 重试时不重复转写

    wav = extract_audio_track(
        source, max_seconds=float(settings.video_max_duration_seconds or 0)
    )
    if wav is None:
        return None

    segments = await transcriber.transcribe(wav, media_kind=ASR_MEDIA_KIND)
    if segments is None:
        await record_audit(
            session,
            actor="system/video-worker",
            action="video_skip",
            target=f"evidence:{item.id}",
            detail={"reason": "asr_unavailable"},
        )
        return None
    transcript = " ".join(seg.text for seg in segments).strip()
    if not transcript:
        return None

    vectors = await llm.embed([transcript])
    asset = AudioAsset(
        evidence_item_id=item.id,
        transcript=transcript,
        segments=[seg.model_dump() for seg in segments],
        duration_seconds=max((seg.end for seg in segments), default=None),
        embedding=vectors[0] if vectors else None,
        captured_at=envelope.occurred_at,
    )
    session.add(asset)
    await session.commit()
    return asset


def _visual_context(terms: list[str]) -> str:
    """把各帧的 scene_tags 压成一行去重列表，喂给语音抽取器做指代消解。

    按出现频次排序并截断：一段 60s 视频 12 帧能攒出上百个标签，
    全塞进 prompt 既贵又会淹没真正反复出现的主体。
    """
    if not terms:
        return ""
    counts: dict[str, int] = {}
    for term in terms:
        key = str(term).strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return "、".join(name for name, _ in ranked[:30])
