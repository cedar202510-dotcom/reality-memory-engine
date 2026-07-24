"""双通道检索测试（FakeLLM + 真实 PG，走 API + outbox worker）。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import MemoryCandidate
from app.workers import process_outbox_once

HIGH = {"model": 0.95, "identity": 0.95, "spatial": 0.95, "temporal": 0.95, "policy": 1.0, "aggregate": 0.95}

PHONE_FAKE = FakeLLMClient(
    caption_rules=[
        ("phone_on_stool", {"caption": "一部黑色手机放在黑色圆凳上", "scene_tags": ["手机", "圆凳"]}),
    ],
    extract_rules=[
        (
            "phone_on_stool",
            [
                {
                    "predicate": "OBSERVED_AT",
                    "object_text": "手机",
                    "value": {"location": "黑色圆凳"},
                    "confidence": HIGH,
                }
            ],
        )
    ],
)


async def _drain_outbox(fake: FakeLLMClient) -> int:
    """循环消费直到 outbox 清空（frame.process 会产生新的 projection.recompute）。"""
    total = 0
    while True:
        n = await process_outbox_once(fake)
        total += n
        if n == 0:
            return total


async def _ingest(client: AsyncClient, name: str, data: bytes, minutes_ago: int = 1) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    envelope = {
        "occurred_at": ts,
        "observed_at": ts,
        "idempotency_key": f"test-{name}",
        "trigger": "explicit",
        "modality": "image",
    }
    resp = await client.post(
        "/internal/v1/envelopes",
        data={"envelope": json.dumps(envelope)},
        files=[("files", (name, data, "image/jpeg"))],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _client(fake: FakeLLMClient) -> AsyncClient:
    app = create_app(fake_llm=fake, with_workers=False)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_channel1_known_entity_hits_projection(db_session, make_image):
    fake = PHONE_FAKE
    async with await _client(fake) as client:
        await _ingest(client, "phone_on_stool.jpg", make_image((10, 10, 10)))
        assert await _drain_outbox(fake) >= 2  # frame.process + projection.recompute

        resp = await client.get("/v1/memory/objects/where-is", params={"name": "手机"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["channel"] == "projection"
        assert body["location"] == "黑色圆凳"
        assert body["entity"]["canonical_name"] == "手机"
        assert body["confidence"] >= 0.85
        assert "最后一次看到" in body["freshness"]
        assert body["timeline_url"].endswith("/timeline")


async def test_channel2_unknown_object_not_found(db_session, make_image):
    fake = PHONE_FAKE  # answer_rules 为空 → 兜底 found=false
    async with await _client(fake) as client:
        await _ingest(client, "phone_on_stool.jpg", make_image((10, 10, 10)))
        await _drain_outbox(fake)

        resp = await client.get("/v1/memory/objects/where-is", params={"name": "眼镜"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["channel"] == "not_found"
        assert body["confidence"] < 0.5
        # 回写了 source=query 的低置信候选，保持 PENDING
        cand = (
            await db_session.scalars(
                select(MemoryCandidate).where(MemoryCandidate.source == "query")
            )
        ).all()
        assert len(cand) == 1
        assert cand[0].status == "PENDING"
        assert cand[0].payload["object_text"] == "眼镜"


async def test_channel2_answer_promotes_to_entity(db_session, make_image):
    fake = FakeLLMClient(
        caption_rules=[
            ("glasses_scene", {"caption": "一副眼镜放在书架上", "scene_tags": ["眼镜", "书架"]}),
        ],
        answer_rules=[
            (
                "眼镜",
                {
                    "found": True,
                    "location": "书架",
                    "confidence": 0.95,
                    "answer_text": "眼镜最后一次看到是在书架上。",
                },
            )
        ],
    )
    async with await _client(fake) as client:
        # scene_tags 非空 → 高价值帧，但 extract_rules 为空 → 无观察 → 无实体
        await _ingest(client, "glasses_scene.jpg", make_image((200, 100, 50)))
        await _drain_outbox(fake)

        resp = await client.get("/v1/memory/objects/where-is", params={"name": "眼镜"})
        body = resp.json()
        assert body["channel"] == "deep_retrieval"
        assert body["location"] == "书架"
        assert body["entity"]["canonical_name"] == "眼镜"  # 被查询过的物体升级为实体

        await _drain_outbox(fake)  # worker 异步重算投影

        # 再查一次：走通道 1（越用越强）
        resp2 = await client.get("/v1/memory/objects/where-is", params={"name": "眼镜"})
        assert resp2.json()["channel"] == "projection"
        assert resp2.json()["location"] == "书架"


async def test_channel2_trgm_fallback_without_embedding(db_session, make_image):
    """无 embedding 配置时检索降级 pg_trgm，系统完整运行。"""
    fake = FakeLLMClient(
        caption_rules=[
            ("glasses_scene", {"caption": "一副眼镜放在书架上", "scene_tags": ["眼镜"]}),
        ],
        answer_rules=[
            ("眼镜", {"found": True, "location": "书架", "confidence": 0.95, "answer_text": "在书架上。"})
        ],
        embedding_enabled=False,
    )
    async with await _client(fake) as client:
        await _ingest(client, "glasses_scene.jpg", make_image((1, 2, 3)))
        await _drain_outbox(fake)

        resp = await client.get("/v1/memory/objects/where-is", params={"name": "眼镜"})
        body = resp.json()
        assert body["channel"] == "deep_retrieval"
        assert body["location"] == "书架"


async def test_ingest_idempotency_and_phash_dedup(db_session, make_image):
    fake = FakeLLMClient()
    async with await _client(fake) as client:
        img = make_image((128, 128, 128))
        r1 = await _ingest(client, "same.jpg", img)
        # 相同幂等键重放
        r2 = await _ingest(client, "same.jpg", img)
        assert r2["idempotent_replay"] is True
        assert r1["envelope"]["id"] == r2["envelope"]["id"]

        # 不同幂等键但图片内容几乎相同 → phash 去重，不新建证据
        ts = datetime.now(timezone.utc).isoformat()
        envelope = {
            "occurred_at": ts, "observed_at": ts,
            "idempotency_key": "test-same-2", "trigger": "auto", "modality": "image",
        }
        resp = await client.post(
            "/internal/v1/envelopes",
            data={"envelope": json.dumps(envelope)},
            files=[("files", ("same2.jpg", img, "image/jpeg"))],
        )
        body = resp.json()
        assert body["evidence_item_ids"] == []
        assert len(body["duplicate_evidence_ids"]) == 1
