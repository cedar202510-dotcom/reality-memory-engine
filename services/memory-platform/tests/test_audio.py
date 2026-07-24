"""语音/音频全链路测试：FakeTranscriber + FakeLLM + 真实 PG。

覆盖：
- 纯逻辑（不依赖 DB）：fake 转写注入、工厂降级、HTTP 失败降级、三路融合打分
- 端到端：音频信封 ingest（内容哈希去重）、audio.process worker 全链路、
  转写检索路与 where-is 融合、forget-recent 覆盖 audio 子系统
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.asr import NullTranscriber, build_transcriber
from app.asr.fake import FakeTranscriber
from app.asr.http_client import HTTPTranscriber
from app.config import get_settings
from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import (
    AtomicObservation,
    AudioAsset,
    Entity,
    EvidenceItem,
    MemoryCandidate,
    MemoryEvent,
    OutboxEvent,
    StateProjection,
)
from app.query.visual import fuse_rankings
from app.query.where_is import _retrieve_transcripts
from app.workers import process_outbox_once

AUDIO_BYTES = b"fake-audio-bytes-preference"
AUDIO_BYTES_2 = b"fake-audio-bytes-task"

PREFERENCE_SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "我喜欢用蓝色杯子喝咖啡", "speaker": "S1"},
]
TASK_SEGMENTS = [
    {"start": 0.0, "end": 3.0, "text": "提醒我明天买牛奶"},
]

PREFERENCE_OBS = [
    {
        "predicate": "PREFERENCE_EXPRESSED",
        "object_text": "蓝色杯子",
        "value": {"preference": "喝咖啡用"},
        "confidence": {"aggregate": 0.95},
    }
]
TASK_OBS = [
    {
        "predicate": "INTENT_CREATED",
        "object_text": "牛奶",
        "value": {"task": "明天买牛奶"},
        "confidence": {"aggregate": 0.9},
    }
]


def _fake_asr() -> FakeTranscriber:
    """注入式 FakeTranscriber：按音频 sha256 返回预定转写。"""
    return FakeTranscriber(
        segments_by_digest={
            FakeTranscriber.audio_digest(AUDIO_BYTES): PREFERENCE_SEGMENTS,
            FakeTranscriber.audio_digest(AUDIO_BYTES_2): TASK_SEGMENTS,
        }
    )


def _fake_llm(**kw) -> FakeLLMClient:
    return FakeLLMClient(
        audio_extract_rules=[
            ("蓝色杯子", PREFERENCE_OBS),
            ("买牛奶", TASK_OBS),
        ],
        **kw,
    )


def _client(fake: FakeLLMClient, asr: FakeTranscriber | None) -> AsyncClient:
    app = create_app(fake_llm=fake, fake_asr=asr, with_workers=False)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _ingest_audio(client: AsyncClient, name: str, data: bytes, key: str | None = None) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    envelope = {
        "occurred_at": ts,
        "observed_at": ts,
        "idempotency_key": key or f"audio-{name}-{uuid.uuid4()}",
        "trigger": "explicit",
        "modality": "audio",
    }
    resp = await client.post(
        "/internal/v1/envelopes",
        data={"envelope": json.dumps(envelope)},
        files=[("files", (name, data, "audio/m4a"))],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _drain_outbox(fake: FakeLLMClient, asr: FakeTranscriber | None = None) -> int:
    total = 0
    while True:
        n = await process_outbox_once(fake, asr=asr)
        total += n
        if n == 0:
            return total


# ---------------------------------------------------------------- 纯逻辑（不依赖 DB）


async def test_fake_transcriber_injection():
    """注入命中返回预定分段；未命中返回兜底；disabled 返回 None。"""
    asr = _fake_asr()
    segs = await asr.transcribe(AUDIO_BYTES, media_kind="audio")
    assert [s.text for s in segs] == ["我喜欢用蓝色杯子喝咖啡"]
    assert segs[0].speaker == "S1"

    fallback = await asr.transcribe(b"unknown-audio", media_kind="audio")
    assert [s.text for s in fallback] == ["一段中文语音"]

    disabled = FakeTranscriber(enabled=False)
    assert await disabled.transcribe(AUDIO_BYTES, media_kind="audio") is None


def test_build_transcriber_degradation():
    """none / http 无 base_url → NullTranscriber；http 配齐 → HTTPTranscriber。"""
    settings = get_settings()

    none_asr = build_transcriber(settings.model_copy(update={"asr_provider": "none"}))
    assert isinstance(none_asr, NullTranscriber)

    http_no_url = build_transcriber(
        settings.model_copy(update={"asr_provider": "http", "asr_base_url": ""})
    )
    assert isinstance(http_no_url, NullTranscriber)

    http_ok = build_transcriber(
        settings.model_copy(update={"asr_provider": "http", "asr_base_url": "http://127.0.0.1:1"})
    )
    assert isinstance(http_ok, HTTPTranscriber)


async def test_http_transcriber_error_returns_none():
    """sidecar 不可达时返回 None（连接拒绝，超时短，不会卡住）。"""
    asr = HTTPTranscriber(base_url="http://127.0.0.1:1", timeout=1.0)
    assert await asr.transcribe(b"x", media_kind="audio") is None


async def test_fuse_rankings_with_transcript_route():
    """三路融合：转写路命中按 transcript_weight 加权；双路命中分数相加。"""
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fused = fuse_rankings(
        text_hits=[(a, 1.0), (b, 0.5)],
        visual_hits=[],
        visual_weight=0.6,
        transcript_hits=[(b, 1.0), (c, 0.5)],
        transcript_weight=0.5,
        top_k=10,
    )
    scores = dict(fused)
    # 无视觉路 → w_text = 1 - 0.5 = 0.5；b 双路命中（text 归一化 0.5 + transcript 1.0）最高
    assert scores[b] == pytest.approx(0.5 * 0.5 + 0.5 * 1.0)
    assert scores[a] == pytest.approx(0.5 * 1.0)
    assert scores[c] == pytest.approx(0.5 * 0.5)
    assert fused[0][0] == b

    # 无转写路时与旧两路行为完全一致
    fused2 = fuse_rankings(
        text_hits=[(a, 0.5), (b, 1.0)],
        visual_hits=[(a, 2.0), (c, 1.0)],
        visual_weight=0.6,
        top_k=10,
    )
    assert dict(fused2)[a] == pytest.approx(0.6 * 1.0 + 0.4 * 0.5)


# ---------------------------------------------------------------- 端到端（真实 PG + API）


async def test_gateway_accepts_audio_and_dedups_by_content_hash(db_session):
    """音频信封不崩（跳过 aHash）；同内容音频在窗口内去重；outbox 路由 audio.process。"""
    fake = _fake_llm()
    async with _client(fake, None) as client:
        body = await _ingest_audio(client, "voice.m4a", AUDIO_BYTES)
        assert len(body["evidence_item_ids"]) == 1
        assert body["duplicate_evidence_ids"] == []

        # 同内容、不同幂等键 → 命中内容哈希去重，只刷新 TTL
        dup = await _ingest_audio(client, "voice2.m4a", AUDIO_BYTES)
        assert dup["evidence_item_ids"] == []
        assert dup["duplicate_evidence_ids"] == body["evidence_item_ids"]

        # 不同内容 → 新建证据
        other = await _ingest_audio(client, "voice3.m4a", AUDIO_BYTES_2)
        assert len(other["evidence_item_ids"]) == 1

    items = (await db_session.scalars(select(EvidenceItem))).all()
    assert len(items) == 2
    assert all(i.media_kind == "audio" for i in items)
    assert all(i.phash is not None for i in items)  # 内容哈希复用 phash 列

    topics = (await db_session.scalars(select(OutboxEvent.topic))).all()
    assert topics == ["audio.process", "audio.process"]


async def test_audio_worker_full_pipeline(db_session):
    """audio.process：转写 → AudioAsset + 观察 + 候选门 → PREFERENCE_STATED 事件 + preferences 投影。"""
    fake = _fake_llm()
    asr = _fake_asr()
    async with _client(fake, asr) as client:
        await _ingest_audio(client, "voice.m4a", AUDIO_BYTES)
    await _drain_outbox(fake, asr)

    # AudioAsset：转写全文 + 分段 + embedding + 时长
    asset = (await db_session.scalars(select(AudioAsset))).one()
    assert asset.transcript == "我喜欢用蓝色杯子喝咖啡"
    assert asset.segments[0]["speaker"] == "S1"
    assert asset.duration_seconds == pytest.approx(2.5)
    assert asset.embedding is not None and len(asset.embedding) == 1024

    # 观察挂 audio_asset_id，frame_asset_id 为空
    obs = (await db_session.scalars(select(AtomicObservation))).one()
    assert obs.audio_asset_id == asset.id
    assert obs.frame_asset_id is None
    assert obs.predicate == "PREFERENCE_EXPRESSED"
    assert obs.parser_version == "audio-extractor-v0.1"

    # 候选门接受（aggregate 0.95 ≥ 0.85）→ PREFERENCE_STATED 事件
    candidate = (await db_session.scalars(select(MemoryCandidate))).one()
    assert candidate.status == "ACCEPTED"
    event = (await db_session.scalars(select(MemoryEvent))).one()
    assert event.event_type == "PREFERENCE_STATED"
    assert event.payload["preference"] == "喝咖啡用"

    # preferences 投影已由 projection.recompute 重算
    proj = await db_session.scalar(
        select(StateProjection).where(
            StateProjection.entity_id == event.entity_id,
            StateProjection.projection_type == "preferences",
        )
    )
    assert proj is not None
    assert proj.state["preference"] == "喝咖啡用"
    assert proj.state["stated_time"]

    entity = await db_session.scalar(select(Entity).where(Entity.id == event.entity_id))
    assert entity.canonical_name == "蓝色杯子"


async def test_audio_worker_asr_unavailable_degrades(db_session):
    """ASR 不可用（None）：不写 AudioAsset、不崩、outbox 标记消费、留审计。"""
    fake = _fake_llm()
    asr = FakeTranscriber(enabled=False)
    async with _client(fake, asr) as client:
        await _ingest_audio(client, "voice.m4a", AUDIO_BYTES)
    n = await _drain_outbox(fake, asr)
    assert n == 1

    assert (await db_session.scalars(select(AudioAsset))).all() == []
    pending = await db_session.scalar(
        select(func.count()).select_from(OutboxEvent).where(OutboxEvent.processed_at.is_(None))
    )
    assert pending == 0

    from app.models import AuditRecord

    audits = (
        await db_session.scalars(select(AuditRecord).where(AuditRecord.action == "audio_skip"))
    ).all()
    assert len(audits) == 1
    assert audits[0].detail["reason"] == "asr_unavailable"


async def test_transcript_retrieval_route_and_scene_search(db_session):
    """转写检索路：trgm 降级命中音频；scene-search 返回 audio_hits；where-is 精判上下文含转写。"""
    fake = _fake_llm(embedding_enabled=False)  # 强制走 trgm 降级，断言确定性命中
    asr = _fake_asr()
    async with _client(fake, asr) as client:
        await _ingest_audio(client, "voice.m4a", AUDIO_BYTES)
        await _drain_outbox(fake, asr)

        # 转写路直接命中
        hits = await _retrieve_transcripts(db_session, llm=fake, name="蓝色杯子", top_k=5)
        assert len(hits) == 1
        audio, score = hits[0]
        assert "蓝色杯子" in audio.transcript
        assert score > 0

        # scene-search：audio_hits 返回同一条语音
        resp = await client.post("/v1/memory/scene-search", json={"query_text": "蓝色杯子", "top_k": 5})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["audio_hits"]) == 1
        assert body["audio_hits"][0]["audio_asset_id"] == str(audio.id)
        assert body["audio_hits"][0]["evidence_available"] is True

        # where-is 通道 2（deep 强制）：Answerer 的候选上下文包含语音转写
        await client.get("/v1/memory/objects/where-is", params={"name": "蓝色杯子", "deep": "true"})
        answer_calls = [c for c in fake.calls if c["task"] == "answer"]
        assert len(answer_calls) == 1
        assert "语音转写" in answer_calls[0]["prompt"]
        assert "我喜欢用蓝色杯子喝咖啡" in answer_calls[0]["prompt"]


async def test_forget_recent_covers_audio_subsystem(db_session):
    """forget-recent：audio 子系统删除窗口内 AudioAsset + 其观察，留 tombstone 与审计。"""
    fake = _fake_llm()
    asr = _fake_asr()
    async with _client(fake, asr) as client:
        await _ingest_audio(client, "voice.m4a", AUDIO_BYTES)
        await _drain_outbox(fake, asr)

        assert (await db_session.scalars(select(AudioAsset))).all() != []

        resp = await client.post("/v1/memory/forget-recent", json={"minutes": 60})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "DONE"
        jobs = {j["subsystem"]: j["status"] for j in body["jobs"]}
        assert jobs["audio"] == "DONE"

    assert (await db_session.scalars(select(AudioAsset))).all() == []
    assert (await db_session.scalars(select(AtomicObservation))).all() == []


async def test_task_stated_projection(db_session):
    """INTENT_CREATED → TASK_STATED 事件 → tasks 投影（status=open）。"""
    fake = _fake_llm()
    asr = _fake_asr()
    async with _client(fake, asr) as client:
        await _ingest_audio(client, "todo.m4a", AUDIO_BYTES_2)
    await _drain_outbox(fake, asr)

    event = (await db_session.scalars(select(MemoryEvent))).one()
    assert event.event_type == "TASK_STATED"

    proj = await db_session.scalar(
        select(StateProjection).where(
            StateProjection.entity_id == event.entity_id,
            StateProjection.projection_type == "tasks",
        )
    )
    assert proj is not None
    assert proj.state["task"] == "明天买牛奶"
    assert proj.state["status"] == "open"
