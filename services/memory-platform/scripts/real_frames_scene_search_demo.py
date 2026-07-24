"""真实场景帧 + 真实 CLIP + 真实 k3 VLM 的端到端物件查找演示。

数据：仓库 data/frames/ 下 7 张第一视角场景帧（咖啡馆实拍，含手机位置变化）。
流程：ingest 7 帧 → perception worker（k3 caption/抽取 + CLIP 视觉向量落库）
     → where-is（实体记忆通道）+ scene-search（CLIP 跨模态检索）。

前置：.env 配置 LLM_PROVIDER=kimi-coding + KIMI_API_KEY，VISION_PROVIDER=local。
用法：
    cd services/memory-platform
    .venv/bin/python scripts/real_frames_scene_search_demo.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent.parent

# ---- 必须在任何 app 模块导入前设置环境（demo 独占 rme_demo 库）----
os.environ["DATABASE_URL"] = "postgresql+asyncpg://rme:rme@localhost:5432/rme_demo"
os.environ["EVIDENCE_DIR"] = str(BASE_DIR / "data" / "evidence-demo")

sys.path.insert(0, str(BASE_DIR))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from app.db import SessionLocal, ensure_extensions  # noqa: E402
from app.main import create_app  # noqa: E402
from app.memory.seed import ensure_seed  # noqa: E402
from app.models import (
    AtomicObservation,
    Entity,
    EvidenceItem,
    FrameAsset,
    OutboxEvent,
    StateProjection,
)  # noqa: E402
from app.workers import start_workers, stop_workers  # noqa: E402

FRAMES_DIR = REPO_ROOT / "data" / "frames"

# (文件名, 内容标注[ground truth], 距现在秒数)
FRAMES = [
    ("IMG_3625.png", "手机在木桌上（笔记本左侧）", 180),
    ("IMG_3626.png", "手机在木桌上（靠近粉色饮料杯）", 150),
    ("IMG_3627.png", "手机在木桌上（正视角）", 120),
    ("IMG_3628.png", "空木桌（手机已不在桌面）", 90),
    ("IMG_3629.png", "手机在黑色圆凳上", 60),
    ("IMG_3630.png", "粉色饮料杯在吧台（无手机）", 30),
    ("IMG_3631.png", "笔记本特写（无手机）", 0),
]

QUERIES = [
    ("a smartphone on a wooden desk", "应命中 IMG_3625/3626/3627"),
    ("a smartphone on a black round stool", "应命中 IMG_3629"),
    ("a plastic cup with a drink", "应命中 IMG_3630"),
    ("a set of keys", "场景中没有钥匙 → 各帧分数应普遍偏低且接近"),
]


def step(title: str) -> None:
    print(f"\n{'=' * 68}\n▶ {title}\n{'=' * 68}")


async def wait_outbox_drained(timeout: float = 120.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        async with SessionLocal() as s:
            pending = await s.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.processed_at.is_(None))
            )
        if pending == 0:
            return
        await asyncio.sleep(0.5)
    raise TimeoutError("outbox 未在超时内消费完")


async def main() -> None:
    keep = os.environ.get("DEMO_KEEP_DB") == "1"
    step("0. 初始化：" + ("保留现有数据（续跑）" if keep else "清库（rme_demo）") + " + 真实 k3 VLM + 真实 CLIP（均从 .env 装配）")
    await ensure_extensions()
    async with SessionLocal() as s:
        if not keep:
            await s.execute(text(
                "TRUNCATE households, actors, devices, source_envelopes, evidence_items,"
                " frame_assets, atomic_observations, entities, memory_candidates,"
                " memory_events, state_projections, deletion_requests, deletion_jobs,"
                " deletion_tombstones, audit_records, outbox_events CASCADE"
            ))
            await s.commit()
        await ensure_seed(s)

    app = create_app(with_workers=False)
    print(f"  LLM: {type(app.state.llm).__name__}  Vision: {type(app.state.vision).__name__}")
    stop, tasks = start_workers(app.state.llm, vision=app.state.vision)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://demo")

    try:
        step("1. Ingest：7 张真实场景帧（相隔 30 秒，模拟一段连续采集）")
        now = datetime.now(timezone.utc)
        evidence_to_name: dict[str, str] = {}
        for fname, _desc, seconds_ago in FRAMES:
            ts = (now - timedelta(seconds=seconds_ago)).isoformat()
            envelope = {
                "occurred_at": ts, "observed_at": ts,
                "idempotency_key": f"real-demo-{fname}", "trigger": "auto", "modality": "image",
                "source_session_id": "real-demo-session-001",
            }
            resp = await client.post(
                "/internal/v1/envelopes",
                data={"envelope": json.dumps(envelope)},
                files=[("files", (fname, (FRAMES_DIR / fname).read_bytes(), "image/png"))],
            )
            body = resp.json()
            if body.get("duplicate_evidence_ids"):
                print(f"  {fname:15s} → 被判为重复帧（phash 去重）")
            else:
                for eid in body["evidence_item_ids"]:
                    evidence_to_name[eid] = fname
                print(f"  {fname:15s} → 已入库（{seconds_ago}s 前）")

        step("2. 等待 perception worker：k3 caption/抽取 + CLIP 视觉向量落库")
        await wait_outbox_drained(timeout=900.0)
        frame_rows: dict[str, str] = {}  # frame_asset_id → filename
        async with SessionLocal() as s:
            rows = (await s.scalars(select(FrameAsset).order_by(FrameAsset.captured_at))).all()
            for row in rows:
                item = await s.get(EvidenceItem, row.evidence_item_id)
                fname = evidence_to_name.get(str(item.id) if item else "", "?")
                frame_rows[str(row.id)] = fname
                has_vec = "✓ CLIP" if row.visual_embedding is not None else "✗"
                print(f"  [{fname}] [{has_vec}] {row.caption}")
            print("\n  -- k3 抽取的原子观察 --")
            for obs in (await s.scalars(select(AtomicObservation))).all():
                print(
                    f"  [obs] {obs.object_text} {obs.predicate} → {obs.value}"
                    f"  agg={obs.confidence.get('aggregate')}"
                )
            print("\n  -- 实体与位置投影 --")
            for ent in (await s.scalars(select(Entity))).all():
                proj = await s.scalar(
                    select(StateProjection).where(
                        StateProjection.entity_id == ent.id,
                        StateProjection.projection_type == "last_seen",
                    )
                )
                print(f"  [entity] {ent.canonical_name} aliases={ent.aliases} → {proj.state if proj else None}")

        step("3. where-is：实体记忆通道（O(1) 投影直答）")
        for name in ["手机", "智能手机", "笔记本电脑"]:
            r = (await client.get("/v1/memory/objects/where-is", params={"name": name})).json()
            print(f"\n  查询：{name!r} → channel={r['channel']} confidence={r['confidence']}")
            print(f"    {r['answer_text']}")

        step("4. scene-search：CLIP 跨模态检索（排序完全由视觉向量决定）")
        truth = {f: d for f, d, _ in FRAMES}
        for query, expect in QUERIES:
            r = (
                await client.post(
                    "/v1/memory/scene-search",
                    json={"query_text": query, "top_k": 7},
                )
            ).json()
            print(f"\n  查询：{query!r}  （期望：{expect}）")
            for i, hit in enumerate(r["hits"], 1):
                fname = frame_rows.get(hit["frame_asset_id"], "?")
                print(
                    f"    {i}. {fname:15s} score={hit['score']:.4f}  "
                    f"{hit['captured_at'][:19]}  {truth.get(fname, '')}"
                )

        print("\n✅ 演示完成")
    finally:
        await client.aclose()
        await stop_workers(stop, tasks)


if __name__ == "__main__":
    asyncio.run(main())
