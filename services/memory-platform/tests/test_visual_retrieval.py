"""视觉跨模态检索测试：FakeVisionEncoder 注入可控向量 + 真实 PG。

覆盖：
- 纯逻辑（不依赖 DB）：fake 编码器相似度可控、融合打分、工厂降级、HTTP 失败降级、请求校验
- 端到端：入库写视觉向量、scene-search 排序/跨模态命中、where-is 多路融合与无视觉降级
"""
from __future__ import annotations

import base64
import importlib.util
import json
import math
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import select

from app.config import get_settings
from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import AuditRecord, FrameAsset
from app.query.visual import fuse_rankings, visual_search_frames
from app.query.where_is import _retrieve_frames, _retrieve_frames_text
from app.schemas import SceneSearchRequest
from app.vision import NullVisionEncoder, build_vision_encoder
from app.vision.fake import FakeVisionEncoder
from app.vision.http_client import HTTPVisionEncoder
from app.workers import process_outbox_once

DIM = 512


def _one_hot(i: int) -> list[float]:
    """第 i 维为 1 的单位向量基（互相正交，便于断言相似度）。"""
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _make_fake_vision(image_bytes_by_token: dict[str, bytes]) -> FakeVisionEncoder:
    """构造注入式 FakeVisionEncoder：token→正交基，图片 sha256→token。"""
    tokens = list(image_bytes_by_token)
    return FakeVisionEncoder(
        dim=DIM,
        token_basis={t: _one_hot(i) for i, t in enumerate(tokens)},
        image_tokens={
            FakeVisionEncoder.image_digest(data): [t] for t, data in image_bytes_by_token.items()
        },
    )


def _scene_image(seed: int) -> bytes:
    """生成视觉内容不同的测试图（纯色图 phash 全相同会触发去重，必须用图案）。"""
    import io

    from PIL import Image

    img = Image.new("RGB", (64, 64))
    img.putdata([((x * seed) % 256, (y * 7 * seed) % 256, (x * y * seed) % 256)
                 for y in range(64) for x in range(64)])
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------- 纯逻辑（不依赖 DB）


async def test_fake_vision_shared_token_similarity():
    """共享 token 的文本与图片相似度≈1；正交 token ≈0；disabled 返回 None。"""
    vision = _make_fake_vision({"手机": b"fake-phone-bytes", "眼镜": b"fake-glasses-bytes"})

    text_vec = (await vision.embed_texts(["我的手机在哪"]))[0]
    phone_vec = (await vision.embed_images([b"fake-phone-bytes"]))[0]
    glasses_vec = (await vision.embed_images([b"fake-glasses-bytes"]))[0]

    assert _cosine(text_vec, phone_vec) == pytest.approx(1.0)
    assert _cosine(text_vec, glasses_vec) == pytest.approx(0.0, abs=1e-9)

    disabled = FakeVisionEncoder(enabled=False)
    assert await disabled.embed_texts(["手机"]) is None
    assert await disabled.embed_images([b"x"]) is None


async def test_fuse_rankings_weighted():
    """融合：各路按最大值归一化后加权；双路命中的帧分数相加；去重取 top_k。"""
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fused = fuse_rankings(
        text_hits=[(a, 0.5), (b, 1.0)],       # 归一化后 a=0.5, b=1.0
        visual_hits=[(a, 2.0), (c, 1.0)],     # 归一化后 a=1.0, c=0.5
        visual_weight=0.6,
        top_k=10,
    )
    scores = dict(fused)
    assert scores[a] == pytest.approx(0.6 * 1.0 + 0.4 * 0.5)   # 双路命中，最高
    assert scores[b] == pytest.approx(0.4 * 1.0)
    assert scores[c] == pytest.approx(0.6 * 0.5)
    assert fused[0][0] == a
    assert len(fused) == 3  # 去重

    # top_k 截断
    assert len(fuse_rankings(text_hits=[(a, 1.0), (b, 0.9)], visual_hits=[], visual_weight=0.6, top_k=1)) == 1


def test_build_vision_encoder_degradation():
    """none / http 无 base_url → NullVisionEncoder；local 缺 open_clip 时同样降级。"""
    settings = get_settings()

    none_enc = build_vision_encoder(settings.model_copy(update={"vision_provider": "none"}))
    assert isinstance(none_enc, NullVisionEncoder)

    http_no_url = build_vision_encoder(
        settings.model_copy(update={"vision_provider": "http", "vision_base_url": ""})
    )
    assert isinstance(http_no_url, NullVisionEncoder)

    if importlib.util.find_spec("open_clip") is None:
        local_missing = build_vision_encoder(
            settings.model_copy(update={"vision_provider": "local"})
        )
        assert isinstance(local_missing, NullVisionEncoder)


async def test_http_vision_encoder_error_returns_none():
    """sidecar 不可达时返回 None（连接拒绝，超时短，不会卡住）。"""
    enc = HTTPVisionEncoder(base_url="http://127.0.0.1:1", timeout=1.0)
    assert await enc.embed_texts(["手机"]) is None
    assert await enc.embed_images([b"x"]) is None


def test_scene_search_request_validation():
    """query_text 与 query_image_base64 至少一个。"""
    with pytest.raises(ValidationError):
        SceneSearchRequest()
    req = SceneSearchRequest(query_text="手机")
    assert req.top_k == 8
    SceneSearchRequest(query_image_base64=base64.b64encode(b"x").decode())


# ---------------------------------------------------------------- 端到端（真实 PG + API）


async def _drain_outbox(fake: FakeLLMClient, vision: FakeVisionEncoder | None = None) -> int:
    total = 0
    while True:
        n = await process_outbox_once(fake, vision=vision)
        total += n
        if n == 0:
            return total


async def _ingest(client: AsyncClient, name: str, data: bytes) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    envelope = {
        "occurred_at": ts,
        "observed_at": ts,
        "idempotency_key": f"visual-{name}-{uuid.uuid4()}",
        "trigger": "auto",  # 非 explicit + caption 兜底无 tags → 不产生观察，专注检索
        "modality": "image",
    }
    resp = await client.post(
        "/internal/v1/envelopes",
        data={"envelope": json.dumps(envelope)},
        files=[("files", (name, data, "image/jpeg"))],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _client(fake: FakeLLMClient, vision: FakeVisionEncoder | None) -> AsyncClient:
    app = create_app(fake_llm=fake, fake_vision=vision, with_workers=False)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _frames_by_caption(db_session) -> dict[str, FrameAsset]:
    frames = (await db_session.scalars(select(FrameAsset))).all()
    return {f.caption: f for f in frames}


# caption 规则：所有帧 caption 都不含查询词，保证命中只能来自视觉向量（跨模态）
CAPTION_RULES = [
    ("phone_scene", {"caption": "一张室内场景照片", "scene_tags": []}),
    ("glasses_scene", {"caption": "另一张室内场景照片", "scene_tags": []}),
    ("cup_scene", {"caption": "又一张室内场景照片", "scene_tags": []}),
]


async def _ingest_three_scenes(client: AsyncClient, make_image) -> dict[str, bytes]:
    images = {
        "手机": _scene_image(3),
        "眼镜": _scene_image(5),
        "水杯": _scene_image(11),
    }
    names = {"手机": "phone_scene.jpg", "眼镜": "glasses_scene.jpg", "水杯": "cup_scene.jpg"}
    for token, data in images.items():
        await _ingest(client, names[token], data)
    return images


async def test_perception_writes_visual_embedding(db_session, make_image):
    """入库：媒体活着时写入 CLIP 视觉向量；向量与注入的向量基一致。"""
    fake = FakeLLMClient(caption_rules=CAPTION_RULES)
    images = {"手机": make_image((10, 10, 10))}
    vision = _make_fake_vision(images)
    async with _client(fake, vision) as client:
        await _ingest(client, "phone_scene.jpg", images["手机"])
        await _drain_outbox(fake, vision)

    frame = (await db_session.scalars(select(FrameAsset))).one()
    assert frame.visual_embedding is not None
    assert len(frame.visual_embedding) == DIM
    assert _cosine(list(frame.visual_embedding), _one_hot(0)) == pytest.approx(1.0)


async def test_scene_search_cross_modal_ranking(db_session, make_image):
    """跨模态：文本 query 命中视觉向量的帧（caption/tags 均不含查询词），按相似度排序。"""
    fake = FakeLLMClient(caption_rules=CAPTION_RULES)
    async with _client(fake, None) as client:
        images = await _ingest_three_scenes(client, make_image)
    vision = _make_fake_vision(images)
    async with _client(fake, vision) as client:
        await _drain_outbox(fake, vision)

        resp = await client.post("/v1/memory/scene-search", json={"query_text": "手机", "top_k": 3})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["hits"]) == 3

        hits = body["hits"]
        top = hits[0]
        assert top["score"] == pytest.approx(1.0, abs=1e-6)      # 共享 token → 相似度 1
        assert hits[1]["score"] == pytest.approx(0.0, abs=1e-6)  # 正交 → 0
        assert top["evidence_available"] is True
        assert top["evidence_url"] == f"/v1/memory/frames/{top['frame_asset_id']}/evidence"

        # 顶部分数帧确实来自手机那张图：caption 是 phone_scene 的兜底文案
        frames = await _frames_by_caption(db_session)
        phone_frame = next(f for f in frames.values() if str(f.id) == top["frame_asset_id"])
        assert "手机" not in phone_frame.caption  # 证明命中来自视觉向量而非文本

        # 证据媒体活着时能读回原始字节
        ev = await client.get(top["evidence_url"])
        assert ev.status_code == 200
        assert ev.content == images["手机"]

        # 审计已记录
        audits = (
            await db_session.scalars(
                select(AuditRecord).where(AuditRecord.target == "scene-search:手机")
            )
        ).all()
        assert len(audits) == 1
        assert audits[0].detail["n_hits"] == 3


async def test_scene_search_with_image_query(db_session, make_image):
    """图片 query：以图搜图，命中同一物体的帧。"""
    fake = FakeLLMClient(caption_rules=CAPTION_RULES)
    async with _client(fake, None) as client:
        images = await _ingest_three_scenes(client, make_image)
    vision = _make_fake_vision(images)
    async with _client(fake, vision) as client:
        await _drain_outbox(fake, vision)

        payload = {
            "query_image_base64": base64.b64encode(images["眼镜"]).decode(),
            "top_k": 3,
        }
        resp = await client.post("/v1/memory/scene-search", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_image_query"] is True
        assert body["hits"][0]["score"] == pytest.approx(1.0, abs=1e-6)

        # 非法 base64 → 422
        bad = await client.post("/v1/memory/scene-search", json={"query_image_base64": "!!!"})
        assert bad.status_code == 422

        # 两个输入都缺 → 422（pydantic 校验）
        empty = await client.post("/v1/memory/scene-search", json={})
        assert empty.status_code == 422


async def test_scene_search_without_vision_returns_empty(db_session, make_image):
    """无视觉编码器（provider=none）时 scene-search 返回空列表，系统不报错。"""
    fake = FakeLLMClient(caption_rules=CAPTION_RULES)
    async with _client(fake, None) as client:  # 未注入 fake_vision → NullVisionEncoder
        await _ingest(client, "phone_scene.jpg", make_image((10, 10, 10)))
        await _drain_outbox(fake)

        resp = await client.post("/v1/memory/scene-search", json={"query_text": "手机"})
        assert resp.status_code == 200
        assert resp.json()["hits"] == []

        # 且帧的 visual_embedding 为空（未配置编码器不写向量）
        frame = (await db_session.scalars(select(FrameAsset))).one()
        assert frame.visual_embedding is None


async def test_where_is_fusion_prefers_visual_frame(db_session, make_image):
    """where-is 通道 2：视觉路（权重 0.6）压过文本路，视觉命中的帧排第一。"""
    fake = FakeLLMClient(caption_rules=CAPTION_RULES)
    async with _client(fake, None) as client:
        images = await _ingest_three_scenes(client, make_image)
    vision = _make_fake_vision(images)
    async with _client(fake, vision) as client:
        await _drain_outbox(fake, vision)

    frames = await _frames_by_caption(db_session)
    phone_frame = frames["一张室内场景照片"]  # phone_scene.jpg 的 caption

    # 有视觉：融合后手机帧第一（文本路 hash 向量与"手机"无相关性，压不过视觉 0.6 权重）
    fused = await _retrieve_frames(db_session, llm=fake, name="手机", top_k=3, vision=vision)
    assert fused[0].id == phone_frame.id

    # 无视觉：与纯文本路结果完全一致（降级后行为不变）
    text_only = await _retrieve_frames_text(db_session, llm=fake, name="手机", top_k=3)
    degraded = await _retrieve_frames(db_session, llm=fake, name="手机", top_k=3, vision=None)
    assert [f.id for f in degraded] == [f.id for f, _ in text_only]


async def test_where_is_degraded_behavior_unchanged(db_session, make_image):
    """无 vision 配置时 where-is 通道 2 行为不变：trgm 降级路径照常回答。"""
    fake = FakeLLMClient(
        caption_rules=[
            ("glasses_scene", {"caption": "一副眼镜放在书架上", "scene_tags": ["眼镜"]}),
        ],
        answer_rules=[
            ("眼镜", {"found": True, "location": "书架", "confidence": 0.95, "answer_text": "在书架上。"})
        ],
        embedding_enabled=False,  # 文本 embedding 也不可用 → trgm 降级
    )
    async with _client(fake, None) as client:  # vision_provider=none
        await _ingest(client, "glasses_scene.jpg", make_image((1, 2, 3)))
        await _drain_outbox(fake)

        resp = await client.get("/v1/memory/objects/where-is", params={"name": "眼镜"})
        body = resp.json()
        assert body["channel"] == "deep_retrieval"
        assert body["location"] == "书架"


async def test_visual_search_frames_no_input_returns_empty(db_session):
    """visual_search_frames 防御：无编码器/无输入/top_k<=0 均返回空。"""
    vision = _make_fake_vision({"手机": b"x"})
    assert await visual_search_frames(db_session, vision=None, query_text="手机", top_k=5) == []
    assert await visual_search_frames(db_session, vision=vision, top_k=5) == []
    assert await visual_search_frames(db_session, vision=vision, query_text="手机", top_k=0) == []
