"""multimodal-test-data 真机采集样本 → 后端请求 → 找物端到端验证。

数据：multimodal-test-data/ 下两个真机数据集
  - 2026-07-24-ios-cxrl-session-001：黑客松白桌场景，3 张 JPG + 5 段 PCM
  - 2026-07-24-glasses-mounted-ring-small-001：咖啡吧台场景，5 张 WEBP + 1 段 PCM
流程：全部经 POST /internal/v1/envelopes 走正式 ingest（幂等/去重/outbox）
     → perception worker（k3 caption/抽取 + CLIP 视觉向量）
     → GET /v1/memory/objects/where-is 找物（通道 1 投影 + 通道 2 深检索）。

前置：.env 配置 LLM_PROVIDER=kimi-coding + KIMI_API_KEY，VISION_PROVIDER=local。
用法：
    cd services/memory-platform
    .venv/bin/python scripts/multimodal_e2e_find_object.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent.parent
DATA_ROOT = REPO_ROOT / "multimodal-test-data" / "datasets"

# ---- 必须在任何 app 模块导入前设置环境（复用 rme_demo 库，避免污染主库）----
os.environ["DATABASE_URL"] = "postgresql+asyncpg://rme:rme@localhost:5432/rme_demo"
os.environ["EVIDENCE_DIR"] = str(BASE_DIR / "data" / "evidence-e2e")

sys.path.insert(0, str(BASE_DIR))

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from app.db import SessionLocal, ensure_extensions  # noqa: E402
from app.main import create_app  # noqa: E402
from app.memory.seed import ensure_seed  # noqa: E402
from app.models import (  # noqa: E402
    AtomicObservation,
    AudioAsset,
    Entity,
    EvidenceItem,
    FrameAsset,
    OutboxEvent,
    StateProjection,
)
from app.workers import start_workers, stop_workers  # noqa: E402

DS1 = DATA_ROOT / "2026-07-24-ios-cxrl-session-001"
DS1_SESSION = DS1 / "sessions" / "ce998edb-cc5f-4c18-a93f-55d6b97e7f9d"
DS2 = DATA_ROOT / "2026-07-24-glasses-mounted-ring-small-001"

TRIGGER_MAP = {
    "PERIODIC": "auto",
    "RING_MOTION": "ring_motion",
    "RING_MOTION_WINDOW": "ring_motion",
    "MANUAL": "explicit",
    "SESSION_VAD": "auto",
}

# (查询名, 期望，人工看图得到的 ground truth)
QUERIES = [
    ("手机", "两个场景都有手机；最近一次是吧台场景（水槽边/手持）"),
    ("笔记本电脑", "两个场景都有；最近是吧台上的 MacBook"),
    ("耳机", "吧台木桌上的黑色有线耳机（仅数据集 2）"),
    ("水瓶", "白桌上的外星人电解质水瓶（仅数据集 1）"),
    ("纸巾", "白桌上的蓝色纸巾包（仅数据集 1）"),
    ("钥匙", "两个场景都没有 → 应回答找不到"),
]


def step(title: str) -> None:
    print(f"\n{'=' * 68}\n▶ {title}\n{'=' * 68}")


async def wait_outbox_drained(timeout: float = 900.0) -> None:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        async with SessionLocal() as s:
            pending = await s.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.processed_at.is_(None))
            )
        if pending == 0:
            return
        await asyncio.sleep(1.0)
    raise TimeoutError("outbox 未在超时内消费完")


def load_ds1() -> list[dict]:
    """数据集 1：session.json → (图片 observations + 音频 audioObservations)。"""
    doc = json.loads((DS1_SESSION / "session.json").read_text())
    items = []
    for o in doc.get("observations", []):
        items.append({
            "dataset": "ds1-白桌",
            "file": DS1_SESSION / o["localMediaReference"],
            "occurred_at": o.get("scheduledAt") or o.get("completedAt"),
            "trigger": TRIGGER_MAP.get(o.get("trigger", ""), "auto"),
            "modality": "image",
            "idempotency_key": f"ios:{doc['id']}:{o['id']}",
            "session_id": doc["id"],
        })
    for o in doc.get("audioObservations", []):
        items.append({
            "dataset": "ds1-白桌",
            "file": DS1_SESSION / o["localMediaReference"],
            "occurred_at": o.get("startedAt"),
            "trigger": TRIGGER_MAP.get(o.get("trigger", ""), "auto"),
            "modality": "audio",
            "idempotency_key": f"ios:{doc['id']}:{o['id']}",
            "session_id": doc["id"],
        })
    return items


def load_ds2() -> list[dict]:
    """数据集 2：normalized/source-envelopes.ndjson（v1 契约）→ raw/evidence 媒体文件。"""
    items = []
    for line in (DS2 / "normalized" / "source-envelopes.ndjson").read_text().splitlines():
        env = json.loads(line)
        modality = env["modality"].lower()
        if modality == "sensor":
            print(f"  ⚠ 跳过 SENSOR 信封 {env['payload_ref']}（戒指 IMU 批次，后端暂无传感器处理链路）")
            continue
        orig_id = env["extensions"]["original_observation_id"].lower()
        ext = ".webp" if modality == "image" else ".pcm"
        items.append({
            "dataset": "ds2-吧台",
            "file": DS2 / "raw" / "evidence" / f"{orig_id}{ext}",
            "occurred_at": env["occurred_at"],
            "trigger": TRIGGER_MAP.get(env["extensions"].get("original_trigger", ""), "auto"),
            "modality": modality,
            "idempotency_key": env["idempotency_key"],
            "session_id": env["capture_session_id"],
        })
    return items


async def main() -> None:
    step("0. 初始化：清库（rme_demo）+ 真实 k3 VLM + 真实 CLIP（从 .env 装配）")
    await ensure_extensions()
    async with SessionLocal() as s:
        await s.execute(text(
            "TRUNCATE households, actors, devices, source_envelopes, evidence_items,"
            " frame_assets, audio_assets, atomic_observations, entities, memory_candidates,"
            " memory_events, state_projections, deletion_requests, deletion_jobs,"
            " deletion_tombstones, audit_records, outbox_events CASCADE"
        ))
        await s.commit()
        await ensure_seed(s)

    app = create_app(with_workers=False)
    print(f"  LLM: {type(app.state.llm).__name__}  Vision: {type(app.state.vision).__name__}"
          f"  ASR: {type(app.state.asr).__name__}")
    stop, tasks = start_workers(app.state.llm, vision=app.state.vision, asr=app.state.asr)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://e2e", timeout=120)

    try:
        step("1. Ingest：两个数据集全部媒体经 POST /internal/v1/envelopes 上传")
        all_items = load_ds1() + load_ds2()
        evidence_to_name: dict[str, str] = {}
        for it in sorted(all_items, key=lambda x: x["occurred_at"]):
            fname = it["file"].name
            if not it["file"].exists():
                print(f"  ✗ {fname} 文件缺失，跳过")
                continue
            envelope = {
                "occurred_at": it["occurred_at"], "observed_at": it["occurred_at"],
                "idempotency_key": it["idempotency_key"],
                "trigger": it["trigger"], "modality": it["modality"],
                "source_session_id": it["session_id"],
                "meta": {"dataset": it["dataset"]},
            }
            mime = {"image": "image/webp" if fname.endswith(".webp") else "image/jpeg",
                    "audio": "application/octet-stream"}[it["modality"]]
            resp = await client.post(
                "/internal/v1/envelopes",
                data={"envelope": json.dumps(envelope)},
                files=[("files", (fname, it["file"].read_bytes(), mime))],
            )
            if resp.status_code != 200:
                print(f"  ✗ {fname} HTTP {resp.status_code}: {resp.text[:200]}")
                continue
            body = resp.json()
            tag = f"[{it['dataset']}] {it['modality']:5s} {fname:45s} @{it['occurred_at']}"
            if body.get("duplicate_evidence_ids"):
                print(f"  ⚠ {tag} → 判为重复（去重命中，未新建证据）")
            elif not body.get("evidence_item_ids"):
                print(f"  ✗ {tag} → 未产生证据项")
            else:
                for eid in body["evidence_item_ids"]:
                    evidence_to_name[eid] = f"{it['dataset']}/{fname}"
                print(f"  ✓ {tag}")

        step("2. 等待 perception worker：k3 caption/抽取 + CLIP 向量 +（音频路：ASR 状态观察）")
        t_perception = time.perf_counter()
        await wait_outbox_drained()
        perception_seconds = time.perf_counter() - t_perception
        print(f"  ⏱ 感知流水线排空耗时：{perception_seconds:.1f}s")
        frame_rows: dict[str, str] = {}
        async with SessionLocal() as s:
            for row in (await s.scalars(select(FrameAsset).order_by(FrameAsset.captured_at))).all():
                item = await s.get(EvidenceItem, row.evidence_item_id)
                fname = evidence_to_name.get(str(item.id) if item else "", "?")
                frame_rows[str(row.id)] = fname
                has_vec = "✓CLIP" if row.visual_embedding is not None else "✗CLIP"
                print(f"  [{fname}] [{has_vec}]\n    caption: {row.caption}\n    tags: {row.scene_tags}")
            audio_rows = (await s.scalars(select(AudioAsset))).all()
            print(f"\n  -- audio_assets：{len(audio_rows)} 条（ASR_PROVIDER 未配置时应为 0，音频被跳过）--")
            for a in audio_rows:
                print(f"  [audio] {a.transcript}")
            print("\n  -- k3 抽取的原子观察 --")
            for obs in (await s.scalars(select(AtomicObservation))).all():
                print(f"  [obs] {obs.object_text} {obs.predicate} → {obs.value}"
                      f"  agg={obs.confidence.get('aggregate')}")
            print("\n  -- 实体与 last_seen 投影 --")
            for ent in (await s.scalars(select(Entity))).all():
                proj = await s.scalar(
                    select(StateProjection).where(
                        StateProjection.entity_id == ent.id,
                        StateProjection.projection_type == "last_seen",
                    )
                )
                print(f"  [entity] {ent.canonical_name} aliases={ent.aliases} → {proj.state if proj else None}")

        step("3. 找物：GET /v1/memory/objects/where-is（通道 1 投影优先，未命中走通道 2 深检索）")
        latencies: list[tuple[str, str, float]] = []
        for name, expect in QUERIES:
            t0 = time.perf_counter()
            r = (await client.get("/v1/memory/objects/where-is", params={"name": name})).json()
            dt = time.perf_counter() - t0
            latencies.append((name, r["channel"], dt))
            print(f"\n  查询「{name}」  （期望：{expect}）  ⏱ {dt:.2f}s")
            print(f"    channel={r['channel']}  confidence={r.get('confidence')}"
                  f"  location={r.get('location')}  freshness={r.get('freshness')}")
            print(f"    → {r['answer_text']}")

        step("4. 强制深检索复查（deep=true：绕过投影，验证通道 2 倒序早停验证）")
        for name in ["手机", "耳机", "钥匙"]:
            t0 = time.perf_counter()
            r = (await client.get("/v1/memory/objects/where-is", params={"name": name, "deep": "true"})).json()
            dt = time.perf_counter() - t0
            latencies.append((f"{name}(deep)", r["channel"], dt))
            print(f"\n  查询「{name}」 channel={r['channel']} confidence={r.get('confidence')}  ⏱ {dt:.2f}s")
            print(f"    → {r['answer_text']}")

        step("5. 延迟汇总")
        print(f"  感知流水线（{len(evidence_to_name)} 条证据 → 可查询）：{perception_seconds:.1f}s")
        for name, channel, dt in latencies:
            print(f"  {name:12s} channel={channel:15s} {dt:.2f}s")

        print("\n✅ 端到端验证完成")
    finally:
        await client.aclose()
        await stop_workers(stop, tasks)


if __name__ == "__main__":
    asyncio.run(main())
