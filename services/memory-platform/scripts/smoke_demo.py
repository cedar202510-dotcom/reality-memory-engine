"""端到端冒烟演示（FakeLLM，无需任何 API key）。

用法：
    cd services/memory-platform
    python scripts/smoke_demo.py

流程：生成 6 张占位图 → ingest → 等 worker 处理 → 通道 1 查"手机" → 通道 2 查"眼镜"
→ 纠正 → 再查验证投影 → forget-recent 10 分钟 → 验证删除/投影/tombstone/audit。
"""
from __future__ import annotations

import asyncio
import io
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from httpx import ASGITransport, AsyncClient
from PIL import Image, ImageDraw
from sqlalchemy import func, select, text

from app.db import SessionLocal, ensure_extensions
from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.memory.seed import ensure_seed
from app.models import (
    AuditRecord,
    DeletionTombstone,
    EvidenceItem,
    OutboxEvent,
    StateProjection,
)
from app.workers import start_workers, stop_workers

HIGH = {"model": 0.95, "identity": 0.95, "spatial": 0.95, "temporal": 0.95, "policy": 1.0, "aggregate": 0.95}

# ---------------------------------------------------------------- 占位图

SCENES = [
    # (文件名, 噪声种子, 图上文字, 距现在分钟, trigger)
    ("phone_on_wood_desk.jpg", 101, "手机 在 木桌", 12, "explicit"),
    ("empty_desk.jpg", 202, "空桌面", 10, "auto"),
    ("phone_on_black_stool.jpg", 303, "手机 在 黑色圆凳", 8, "explicit"),
    ("keys_on_hook.jpg", 404, "钥匙 在 门后挂钩", 6, "explicit"),
    ("empty_table.jpg", 505, "空茶几", 4, "auto"),
    ("phone_on_black_stool_dup.jpg", 303, "手机 在 黑色圆凳", 2, "auto"),  # 与第 3 张同种子同内容 → phash 去重
]


def make_image(seed: int, label: str) -> bytes:
    """8x8 种子图案放大成图：aHash 在 8x8 尺度恢复图案，不同种子距离远、同种子同图。"""
    rng = random.Random(seed)
    small = Image.new("L", (8, 8))
    small.putdata([rng.randrange(256) for _ in range(64)])
    img = small.convert("RGB").resize((320, 240), Image.NEAREST)
    draw = ImageDraw.Draw(img)
    draw.rectangle((10, 100, 200, 130), fill=(0, 0, 0))
    draw.text((20, 110), label, fill=(255, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------- FakeLLM 规则

FAKE = FakeLLMClient(
    caption_rules=[
        ("phone_on_wood_desk", {"caption": "一部黑色手机放在木桌上", "scene_tags": ["手机", "木桌"]}),
        ("empty_desk", {"caption": "一张空无一物的桌面", "scene_tags": []}),
        ("phone_on_black_stool", {"caption": "一部黑色手机放在黑色圆凳上", "scene_tags": ["手机", "圆凳"]}),
        ("keys_on_hook", {"caption": "一串钥匙挂在门后挂钩上", "scene_tags": ["钥匙", "挂钩"]}),
        ("empty_table", {"caption": "一张空茶几", "scene_tags": []}),
    ],
    extract_rules=[
        ("phone_on_wood_desk", [
            {"predicate": "OBSERVED_AT", "object_text": "手机", "value": {"location": "木桌"}, "confidence": HIGH},
        ]),
        ("phone_on_black_stool", [
            {"predicate": "OBSERVED_AT", "object_text": "手机", "value": {"location": "黑色圆凳"}, "confidence": HIGH},
        ]),
        ("keys_on_hook", [
            {"predicate": "OBSERVED_AT", "object_text": "钥匙", "value": {"location": "门后挂钩"}, "confidence": HIGH},
        ]),
    ],
    # answer_rules 为空 → 通道 2 对未知物体返回低置信 not_found（演示兜底行为）
)


def step(title: str) -> None:
    print(f"\n{'=' * 64}\n▶ {title}\n{'=' * 64}")


async def wait_outbox_drained(timeout: float = 30.0) -> None:
    """等后台 worker 把 outbox 消费完。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with SessionLocal() as s:
            pending = await s.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.processed_at.is_(None))
            )
        if pending == 0:
            return
        await asyncio.sleep(0.3)
    raise TimeoutError("outbox 未在超时内消费完")


async def main() -> None:
    step("0. 初始化：建扩展、seed、清库（演示独占 dev 库 rme）")
    await ensure_extensions()
    async with SessionLocal() as s:
        await s.execute(text(
            "TRUNCATE households, actors, devices, source_envelopes, evidence_items,"
            " frame_assets, atomic_observations, entities, memory_candidates,"
            " memory_events, state_projections, deletion_requests, deletion_jobs,"
            " deletion_tombstones, audit_records, outbox_events CASCADE"
        ))
        await s.commit()
        await ensure_seed(s)

    app = create_app(fake_llm=FAKE, with_workers=False)
    stop, tasks = start_workers(app.state.llm)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://smoke")

    try:
        step("1. Ingest：6 张占位图（含 1 张重复帧验证 phash 去重）")
        now = datetime.now(timezone.utc)
        for name, color, label, minutes_ago, trigger in SCENES:
            ts = (now - timedelta(minutes=minutes_ago)).isoformat()
            envelope = {
                "occurred_at": ts, "observed_at": ts,
                "idempotency_key": f"smoke-{name}", "trigger": trigger, "modality": "image",
                "source_session_id": "smoke-session-001",
            }
            resp = await client.post(
                "/internal/v1/envelopes",
                data={"envelope": json.dumps(envelope)},
                files=[("files", (name, make_image(color, label), "image/jpeg"))],
            )
            body = resp.json()
            dup = f"（重复帧，仅刷新 TTL: {body['duplicate_evidence_ids']}）" if body["duplicate_evidence_ids"] else ""
            print(f"  {name:36s} → {len(body['evidence_item_ids'])} 个证据 {dup}")

        step("2. 等待 perception worker：caption → 抽取 → 候选门 → 事件 → 投影")
        await wait_outbox_drained()
        async with SessionLocal() as s:
            from app.models import FrameAsset, MemoryEvent, MemoryCandidate, AtomicObservation
            for row in (await s.scalars(select(FrameAsset).order_by(FrameAsset.captured_at))).all():
                print(f"  [frame] {row.caption}  tags={row.scene_tags}")
            for row in (await s.scalars(select(AtomicObservation))).all():
                print(f"  [obs]   {row.object_text} {row.predicate} → {row.value} agg={row.confidence.get('aggregate')}")
            for row in (await s.scalars(select(MemoryCandidate))).all():
                print(f"  [cand]  {row.payload.get('object_text')} status={row.status}")
            for row in (await s.scalars(select(MemoryEvent))).all():
                print(f"  [event] {row.event_type} entity={row.entity_id} payload={row.payload}")

        step("3. 通道 1：查询已知实体「手机」（应命中投影：黑色圆凳）")
        r = (await client.get("/v1/memory/objects/where-is", params={"name": "手机"})).json()
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        assert r["channel"] == "projection" and r["location"] == "黑色圆凳"
        assert any(a["location"] == "木桌" for a in r["alternatives"])
        phone_entity_id = r["entity"]["id"]

        step("4. 通道 2：查询从未见过的「眼镜」（不应崩溃，低置信/not_found）")
        r2 = (await client.get("/v1/memory/objects/where-is", params={"name": "眼镜"})).json()
        print(json.dumps(r2, ensure_ascii=False, indent=2, default=str))
        assert r2["channel"] in ("deep_retrieval", "not_found")

        step("5. 用户纠正：手机其实在「白色书架」")
        corr = (
            await client.post(
                "/v1/memory/correct",
                json={"entity_id": phone_entity_id, "field": "location",
                      "value": "白色书架", "reason": "我刚刚放到书架上了"},
            )
        ).json()
        print(json.dumps(corr, ensure_ascii=False, indent=2, default=str))
        await wait_outbox_drained()
        r3 = (await client.get("/v1/memory/objects/where-is", params={"name": "手机"})).json()
        print(f"  纠正后再查 → location={r3['location']} confidence={r3['confidence']}")
        assert r3["location"] == "白色书架"

        step("6. 时间线（验证 supersedes 链）")
        tl = (await client.get(f"/v1/memory/objects/{phone_entity_id}/timeline")).json()
        for e in tl["events"]:
            mark = "（已被取代）" if e["superseded_by"] else ""
            print(f"  {e['event_type']:20s} {e['payload']} {mark}")

        step("7. forget-recent 10 分钟：物理删除 + 投影重算 + tombstone + audit")
        fr = (await client.post("/v1/memory/forget-recent", json={"minutes": 10})).json()
        print(json.dumps(fr, ensure_ascii=False, indent=2, default=str))
        assert fr["status"] == "DONE"

        async with SessionLocal() as s:
            items = (await s.scalars(select(EvidenceItem))).all()
            remaining_files = [i.storage_ref for i in items if i.storage_ref and Path(i.storage_ref).exists()]
            projs = (await s.scalars(select(StateProjection))).all()
            tombs = (await s.scalars(select(DeletionTombstone))).all()
            audits = (await s.scalars(select(AuditRecord).order_by(AuditRecord.created_at))).all()
        print(f"  残留证据文件: {remaining_files}（应为空）")
        print(f"  投影状态: {[p.state for p in projs]}（应为空 dict 或已删除）")
        print(f"  tombstone: {len(tombs)} 条, audit_hash={tombs[0].audit_hash[:16]}…")
        print(f"  audit 动作序列: {[a.action for a in audits]}")
        assert not remaining_files
        assert all(p.state == {} for p in projs)
        assert len(tombs) == 1
        assert "forget" in [a.action for a in audits]

        step("8. 遗忘后再查「手机」（不应再给出旧位置）")
        r4 = (await client.get("/v1/memory/objects/where-is", params={"name": "手机"})).json()
        print(f"  channel={r4['channel']} location={r4['location']} answer={r4['answer_text']}")
        assert r4["location"] is None

        print("\n✅ 冒烟演示全部通过")
    finally:
        await client.aclose()
        await stop_workers(stop, tasks)


if __name__ == "__main__":
    asyncio.run(main())
