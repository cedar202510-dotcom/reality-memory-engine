"""视频全链路测试：ffmpeg 解复用 + 关键帧子证据 + 音轨 ASR + 喜好度洞察。

覆盖：
- 纯逻辑：probe / 抽音轨 / 抽帧 / 采样点规划（对着现生成的小视频跑真 ffmpeg）
- 端到端：video 信封 ingest → video.process worker → 子证据 + FrameAsset + AudioAsset
- 跨模态：画面 scene_tags 作为指代消解上下文喂进语音抽取
- 幂等：重复处理不会重复抽帧、不会重复转写
- 读侧：媒体库不再把视频报成 UNSUPPORTED；喜好度端点能出分
"""
from __future__ import annotations

import json
import subprocess
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.asr.fake import FakeTranscriber
from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import (
    AtomicObservation,
    AudioAsset,
    EvidenceItem,
    FrameAsset,
    MemoryEvent,
    OutboxEvent,
)
from app.perception.video_media import (
    ASR_SAMPLE_RATE,
    _plan_offsets,
    extract_audio_track,
    extract_keyframes,
    ffmpeg_available,
    probe_video,
)
from app.vision.fake import FakeVisionEncoder
from app.workers import process_outbox_once

pytestmark = pytest.mark.skipif(
    not ffmpeg_available(), reason="本机没有 ffmpeg/ffprobe，视频链路整体跳过"
)

# 一段 6 秒、有画面也有声音的测试视频。用 ffmpeg 现生成而不是塞二进制进仓库：
# 仓库里放 MP4 会让 clone 变重，而且这段素材的全部意义就是「能被 ffmpeg 拆开」。
VIDEO_DURATION = 6.0

TRANSCRIPT_SEGMENTS = [
    {"start": 0.5, "end": 2.0, "text": "这个花生一般般"},
    {"start": 2.0, "end": 4.5, "text": "这个橙皮不错，下次还买"},
]

# FakeLLM 按 prompt 子串匹配。视频帧的 caption/extract 走 caption_rules/extract_rules，
# 音轨的语义抽取走 audio_extract_rules。
CAPTION_RESULT = {"caption": "桌上摆着花生和橙皮", "scene_tags": ["花生", "橙皮"]}
FRAME_OBS = [
    {
        "predicate": "OBSERVED_AT",
        "object_text": "花生",
        "value": {"location": "桌上"},
        "confidence": {"aggregate": 0.95},
    }
]
AUDIO_OBS = [
    {
        "predicate": "PREFERENCE_EXPRESSED",
        "object_text": "花生",
        "value": {"preference": "一般般", "sentiment": "LIKE", "intensity": 0.2},
        "confidence": {"aggregate": 0.95},
    },
    {
        "predicate": "PREFERENCE_EXPRESSED",
        "object_text": "橙皮",
        "value": {"preference": "不错", "sentiment": "LIKE", "intensity": 0.65},
        "confidence": {"aggregate": 0.95},
    },
    {
        "predicate": "INTENT_CREATED",
        "object_text": "橙皮",
        "value": {"task": "下次还买", "intent_kind": "REPEAT"},
        "confidence": {"aggregate": 0.95},
    },
]


@pytest.fixture(scope="module")
def video_bytes(tmp_path_factory) -> bytes:
    path = tmp_path_factory.mktemp("video") / "tv.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc=duration={VIDEO_DURATION:g}:size=320x240:rate=10",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={VIDEO_DURATION:g}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path.read_bytes()


@pytest.fixture(scope="module")
def silent_video_bytes(tmp_path_factory) -> bytes:
    """没有音轨的视频：验证「只有画面」也能正常出结果。"""
    path = tmp_path_factory.mktemp("video") / "silent.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path.read_bytes()


@pytest.fixture
def video_path(tmp_path, video_bytes) -> str:
    p = tmp_path / "clip.mp4"
    p.write_bytes(video_bytes)
    return str(p)


def _fake_llm() -> FakeLLMClient:
    return FakeLLMClient(
        caption_rules=[("", CAPTION_RESULT)],
        extract_rules=[("", FRAME_OBS)],
        audio_extract_rules=[("", AUDIO_OBS)],
    )


def _fake_asr(enabled: bool = True) -> FakeTranscriber:
    return FakeTranscriber(default_segments=TRANSCRIPT_SEGMENTS, enabled=enabled)


def _client(llm, asr, vision) -> AsyncClient:
    app = create_app(fake_llm=llm, fake_asr=asr, fake_vision=vision, with_workers=False)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _ingest_video(client: AsyncClient, data: bytes, name: str = "clip.mp4") -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    envelope = {
        "occurred_at": ts,
        "observed_at": ts,
        "idempotency_key": f"video-{uuid.uuid4()}",
        "trigger": "explicit",
        "modality": "video",
    }
    resp = await client.post(
        "/internal/v1/envelopes",
        data={"envelope": json.dumps(envelope)},
        files=[("files", (name, data, "video/mp4"))],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _drain(llm, asr, vision) -> int:
    total = 0
    while True:
        n = await process_outbox_once(llm, vision=vision, asr=asr)
        total += n
        if n == 0:
            return total


# ---------------------------------------------------------------- 纯逻辑：ffmpeg 解复用层


def test_probe_reads_duration_and_streams(video_path):
    probe = probe_video(video_path)
    assert probe is not None
    assert probe.has_video and probe.has_audio
    assert probe.duration_seconds == pytest.approx(VIDEO_DURATION, abs=0.5)
    assert (probe.width, probe.height) == (320, 240)


def test_probe_on_garbage_returns_none(tmp_path):
    junk = tmp_path / "not-a-video.mp4"
    junk.write_bytes(b"definitely not a container")
    assert probe_video(junk) is None


def test_extract_audio_track_yields_mono_16k_wav(video_path):
    """必须是单声道 16kHz：ASR sidecar 的入参是整段 base64，声道数和采样率直接决定体积。

    这里不断言「wav 比源视频小」——对这段合成测试片并不成立（testsrc 画面压缩率极高，
    而 PCM 是无压缩的）。真正的契约是格式参数，不是相对大小。
    """
    import io
    import wave

    wav = extract_audio_track(video_path)
    assert wav is not None
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == ASR_SAMPLE_RATE
        assert w.getsampwidth() == 2


def test_extract_audio_track_returns_none_without_audio_stream(tmp_path, silent_video_bytes):
    p = tmp_path / "silent.mp4"
    p.write_bytes(silent_video_bytes)
    assert extract_audio_track(p) is None


def test_extract_keyframes_are_jpegs_with_known_offsets(video_path):
    frames = extract_keyframes(
        video_path, interval_seconds=2.0, max_frames=5, duration_seconds=VIDEO_DURATION
    )
    assert 2 <= len(frames) <= 5
    for kf in frames:
        assert kf.data[:2] == b"\xff\xd8", "应当是 JPEG（SOI 魔数）"
        assert 0 <= kf.offset_seconds <= VIDEO_DURATION
    offsets = [k.offset_seconds for k in frames]
    assert offsets == sorted(offsets), "偏移必须递增，停留时长的计算依赖这个顺序"
    assert len(set(offsets)) == len(offsets), "不能有重复采样点"


def test_keyframe_cap_is_respected_on_long_video():
    """长视频不该按间隔无限抽帧——每帧都是一次 VLM 调用，成本必须封顶。"""
    offsets = _plan_offsets(duration_seconds=3600, interval_seconds=5, max_frames=12)
    assert len(offsets) == 12
    # 且要铺满全片，而不是只覆盖开头 60 秒
    assert offsets[-1] > 3000


def test_plan_offsets_handles_unknown_and_tiny_durations():
    assert _plan_offsets(duration_seconds=None, interval_seconds=5, max_frames=12) == [0, 5, 10]
    tiny = _plan_offsets(duration_seconds=2.0, interval_seconds=5, max_frames=12)
    assert len(tiny) == 1 and 0 < tiny[0] < 2.0


# ---------------------------------------------------------------- 端到端


@pytest.mark.asyncio
async def test_ingest_video_enqueues_video_process(db_session, video_bytes):
    llm, asr, vision = _fake_llm(), _fake_asr(), FakeVisionEncoder()
    async with _client(llm, asr, vision) as client:
        await _ingest_video(client, video_bytes)
    topics = list((await db_session.scalars(select(OutboxEvent.topic))).all())
    assert topics == ["video.process"], "视频必须投给 video.process，不能误投帧解析器"


@pytest.mark.asyncio
async def test_video_worker_produces_keyframes_and_transcript(db_session, video_bytes):
    llm, asr, vision = _fake_llm(), _fake_asr(), FakeVisionEncoder()
    async with _client(llm, asr, vision) as client:
        resp = await _ingest_video(client, video_bytes)
    video_id = uuid.UUID(resp["evidence_item_ids"][0])

    await _drain(llm, asr, vision)

    # ---- 关键帧成了子证据，并且各自跑完了帧流水线 ----
    children = list(
        (
            await db_session.scalars(
                select(EvidenceItem)
                .where(EvidenceItem.parent_evidence_item_id == video_id)
                .order_by(EvidenceItem.offset_seconds)
            )
        ).all()
    )
    assert len(children) >= 2
    assert all(c.media_kind == "image" for c in children)
    assert all(c.offset_seconds is not None for c in children)
    offsets = [c.offset_seconds for c in children]
    assert offsets == sorted(offsets)

    frames = list(
        (
            await db_session.scalars(
                select(FrameAsset).where(
                    FrameAsset.evidence_item_id.in_([c.id for c in children])
                )
            )
        ).all()
    )
    assert len(frames) == len(children), "每张关键帧都应产出 FrameAsset"
    assert all(f.caption for f in frames)
    assert all(f.visual_embedding is not None for f in frames), "CLIP 向量应已写入"

    # ---- 音轨转写挂在视频证据本身上 ----
    audio = await db_session.scalar(
        select(AudioAsset).where(AudioAsset.evidence_item_id == video_id)
    )
    assert audio is not None
    assert "花生" in audio.transcript and "橙皮" in audio.transcript
    assert len(audio.segments) == len(TRANSCRIPT_SEGMENTS)

    # ---- 两路观察都落库了 ----
    audio_obs = list(
        (
            await db_session.scalars(
                select(AtomicObservation).where(
                    AtomicObservation.audio_asset_id == audio.id
                )
            )
        ).all()
    )
    assert {o.predicate for o in audio_obs} == {
        "PREFERENCE_EXPRESSED",
        "INTENT_CREATED",
    }
    assert {o.object_text for o in audio_obs} == {"花生", "橙皮"}


@pytest.mark.asyncio
async def test_visual_context_is_fed_into_audio_extraction(db_session, video_bytes):
    """画面里的物体必须作为指代消解上下文进到语音抽取的 prompt 里。

    这是跨模态融合真正发生的地方：没有它，「这个一般般」抽不出物体名。
    """
    llm, asr, vision = _fake_llm(), _fake_asr(), FakeVisionEncoder()
    async with _client(llm, asr, vision) as client:
        await _ingest_video(client, video_bytes)
    await _drain(llm, asr, vision)

    audio_prompts = [c["prompt"] for c in llm.calls if c["task"] == "audio_extract"]
    assert audio_prompts, "应当调用过语音语义抽取"
    prompt = audio_prompts[0]
    assert "同时段画面里出现的物体" in prompt
    assert "花生" in prompt and "橙皮" in prompt, "scene_tags 应当出现在语音抽取上下文里"


@pytest.mark.asyncio
async def test_transcript_is_fed_into_keyframe_captioning(db_session, video_bytes):
    """反向：语音转写必须先于抽帧拿到，并作为命名依据进到每一帧的 caption prompt。

    这是「画面里那团黄色颗粒状食物其实是鸡米花」能被学到的唯一途径——
    纯视觉命名到「黄色颗粒状食物」就到顶了，而说话的人已经报出了名字。
    命名对齐同时也是跨模态指向同一实体的前提：视觉侧和语音侧必须落到同一个 object_text，
    否则实体解析会把它们当成两个物体，喜好度永远合不到一起。
    """
    llm, asr, vision = _fake_llm(), _fake_asr(), FakeVisionEncoder()
    async with _client(llm, asr, vision) as client:
        await _ingest_video(client, video_bytes)
    await _drain(llm, asr, vision)

    tasks = [c["task"] for c in llm.calls]
    caption_calls = [c for c in llm.calls if c["task"] == "caption"]
    assert caption_calls, "应当调用过帧描述器"
    for call in caption_calls:
        assert "同一段视频中说的话" in call["prompt"]
        assert "花生" in call["prompt"], "转写内容应当出现在 caption 上下文里"

    extract_calls = [c for c in llm.calls if c["task"] == "extract"]
    assert extract_calls
    assert all("同一段视频中说的话" in c["prompt"] for c in extract_calls)

    # 顺序契约：ASR 必须在第一次 caption 之前完成，否则前几帧拿不到命名线索
    assert tasks.index("caption") < tasks.index("audio_extract")
    assert len(asr.calls) == 1, "整段视频只应转写一次"


@pytest.mark.asyncio
async def test_standalone_photo_gets_no_audio_context(db_session, make_image):
    """独立照片没有同源语音，audio_context 必须是空占位而不是别的视频的转写。"""
    llm, asr, vision = _fake_llm(), _fake_asr(), FakeVisionEncoder()
    ts = datetime.now(timezone.utc).isoformat()
    async with _client(llm, asr, vision) as client:
        resp = await client.post(
            "/internal/v1/envelopes",
            data={
                "envelope": json.dumps(
                    {
                        "occurred_at": ts,
                        "observed_at": ts,
                        "idempotency_key": f"photo-{uuid.uuid4()}",
                        "trigger": "explicit",
                        "modality": "image",
                    }
                )
            },
            files=[("files", ("a.jpg", make_image((10, 20, 30)), "image/jpeg"))],
        )
        assert resp.status_code == 200
    await _drain(llm, asr, vision)

    caption_calls = [c for c in llm.calls if c["task"] == "caption"]
    assert caption_calls
    assert "（无）" in caption_calls[0]["prompt"]
    assert "花生" not in caption_calls[0]["prompt"]


@pytest.mark.asyncio
async def test_silent_video_still_yields_keyframes(db_session, silent_video_bytes):
    llm, asr, vision = _fake_llm(), _fake_asr(), FakeVisionEncoder()
    async with _client(llm, asr, vision) as client:
        resp = await _ingest_video(client, silent_video_bytes, name="silent.mp4")
    video_id = uuid.UUID(resp["evidence_item_ids"][0])
    await _drain(llm, asr, vision)

    n_children = len(
        list(
            (
                await db_session.scalars(
                    select(EvidenceItem).where(
                        EvidenceItem.parent_evidence_item_id == video_id
                    )
                )
            ).all()
        )
    )
    assert n_children >= 1
    assert (
        await db_session.scalar(
            select(AudioAsset).where(AudioAsset.evidence_item_id == video_id)
        )
    ) is None


@pytest.mark.asyncio
async def test_asr_unavailable_does_not_block_keyframes(db_session, video_bytes):
    """ASR 挂了不该连画面一起丢——两路是独立降级的。"""
    llm, asr, vision = _fake_llm(), _fake_asr(enabled=False), FakeVisionEncoder()
    async with _client(llm, asr, vision) as client:
        resp = await _ingest_video(client, video_bytes)
    video_id = uuid.UUID(resp["evidence_item_ids"][0])
    await _drain(llm, asr, vision)

    children = list(
        (
            await db_session.scalars(
                select(EvidenceItem).where(EvidenceItem.parent_evidence_item_id == video_id)
            )
        ).all()
    )
    assert len(children) >= 2
    assert (
        await db_session.scalar(
            select(AudioAsset).where(AudioAsset.evidence_item_id == video_id)
        )
    ) is None


@pytest.mark.asyncio
async def test_reprocessing_is_idempotent(db_session, video_bytes):
    """重试不能重复抽帧/重复转写——那会重复付 VLM 和 ASR 的钱。"""
    from app.perception.video import process_video_item

    llm, asr, vision = _fake_llm(), _fake_asr(), FakeVisionEncoder()
    async with _client(llm, asr, vision) as client:
        resp = await _ingest_video(client, video_bytes)
    video_id = uuid.UUID(resp["evidence_item_ids"][0])
    await _drain(llm, asr, vision)

    async def _counts() -> tuple[int, int]:
        children = list(
            (
                await db_session.scalars(
                    select(EvidenceItem).where(
                        EvidenceItem.parent_evidence_item_id == video_id
                    )
                )
            ).all()
        )
        audios = list(
            (
                await db_session.scalars(
                    select(AudioAsset).where(AudioAsset.evidence_item_id == video_id)
                )
            ).all()
        )
        return len(children), len(audios)

    before = await _counts()
    n_asr_before = len(asr.calls)

    await process_video_item(
        db_session, evidence_item_id=video_id, llm=llm, vision=vision, transcriber=asr
    )

    assert await _counts() == before, "重跑不应新增关键帧或音频资产"
    assert len(asr.calls) == n_asr_before, "重跑不应再调一次 ASR"


# ---------------------------------------------------------------- 读侧


@pytest.mark.asyncio
async def test_media_library_reports_video_ready_not_unsupported(db_session, video_bytes):
    llm, asr, vision = _fake_llm(), _fake_asr(), FakeVisionEncoder()
    async with _client(llm, asr, vision) as client:
        await _ingest_video(client, video_bytes)
        await _drain(llm, asr, vision)

        resp = await client.get("/v1/memory/media", params={"kind": "video"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["media_kind"] == "video"
        assert item["perception_state"] == "READY", "视频现在有解析器了"
        assert item["transcript"] and "花生" in item["transcript"]


@pytest.mark.asyncio
async def test_preference_insights_from_video(db_session, video_bytes):
    """全链路终点：一段视频进去，喜好度榜单出来。"""
    llm, asr, vision = _fake_llm(), _fake_asr(), FakeVisionEncoder()
    async with _client(llm, asr, vision) as client:
        await _ingest_video(client, video_bytes)
        await _drain(llm, asr, vision)

        resp = await client.get("/v1/memory/insights/preferences")
        assert resp.status_code == 200
        body = resp.json()

    by_name = {i["entity"]["canonical_name"]: i for i in body["items"]}
    assert "橙皮" in by_name and "花生" in by_name

    orange, peanut = by_name["橙皮"], by_name["花生"]
    # 「不错 + 下次还买」应当明显强于「一般般」
    assert orange["score"] > peanut["score"]
    assert orange["level"] in ("喜欢", "强烈喜欢")
    assert {c["channel"] for c in orange["channels"]} >= {"verbal", "intent"}
    assert any(e["kind"] == "verbal" for e in orange["evidence"])

    # 花生同时被画面看到过 → 应当有 attention 通道和停留时长
    assert peanut["frame_count"] > 0
    assert peanut["dwell_seconds"] > 0
    assert any(c["channel"] == "attention" for c in peanut["channels"])


@pytest.mark.asyncio
async def test_insights_filters(db_session, video_bytes):
    llm, asr, vision = _fake_llm(), _fake_asr(), FakeVisionEncoder()
    async with _client(llm, asr, vision) as client:
        await _ingest_video(client, video_bytes)
        await _drain(llm, asr, vision)

        everything = (await client.get("/v1/memory/insights/preferences")).json()
        verdicts = (
            await client.get(
                "/v1/memory/insights/preferences", params={"with_verdict_only": True}
            )
        ).json()
        assert verdicts["total"] <= everything["total"]
        assert all(i["level"] != "证据不足" for i in verdicts["items"])

        strict = (
            await client.get(
                "/v1/memory/insights/preferences", params={"min_confidence": 0.99}
            )
        ).json()
        assert strict["total"] <= everything["total"]

        paged = (
            await client.get("/v1/memory/insights/preferences", params={"limit": 1})
        ).json()
        assert len(paged["items"]) <= 1
