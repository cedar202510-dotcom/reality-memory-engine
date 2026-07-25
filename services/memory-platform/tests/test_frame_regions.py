"""帧切片 / 区域级视觉检索测试。

覆盖：
- 纯逻辑（不依赖 DB）：切法的覆盖性、小图跳过、瓦片数封顶时不丢尾部覆盖
- 端到端：摄入后自动切片、重复消费幂等、编码器不可用时抛可重试信号
- 检索：小物体只在区域向量里有信号时，能不能把帧捞出来（这条是整个改动的目的）
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select

from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import EvidenceItem, FrameAsset, FrameRegion
from app.perception.regions import (
    RegionizeRetryable,
    crop_tiles,
    load_display_image,
    plan_tiles,
    regionize_frame_asset,
)
from app.query.visual import visual_search_frames
from app.vision.fake import FakeVisionEncoder
from app.workers import process_outbox_once

DIM = 512


def _one_hot(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def _patterned_jpeg(width: int, height: int, seed: int) -> bytes:
    """有图案的测试图：纯色图 phash 全相同会触发入库去重。"""
    img = Image.new("RGB", (width, height))
    img.putdata(
        [
            ((x * seed) % 256, (y * 7 * seed) % 256, (x * y * seed) % 256)
            for y in range(height)
            for x in range(width)
        ]
    )
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------- 纯逻辑（不依赖 DB）


def test_plan_tiles_is_square_and_covers_edges():
    """瓦片是方的、彼此重叠、且贴到右边和底边——最后一条边不能永远进不了索引。"""
    tiles = plan_tiles(4000, 3000, grid=2, overlap=0.25, min_side=640, max_tiles=64)
    assert tiles

    widths = {t.box[2] - t.box[0] for t in tiles}
    heights = {t.box[3] - t.box[1] for t in tiles}
    assert widths == heights == {1500}  # 边长由短边 3000/2 决定，且是方的

    assert max(t.box[2] for t in tiles) == 4000  # 贴右
    assert max(t.box[3] for t in tiles) == 3000  # 贴底

    xs = sorted({t.box[0] for t in tiles})
    assert xs[1] - xs[0] < 1500  # 步长 < 边长 ⇒ 相邻瓦片有重叠

    # bbox 是归一化坐标，供前端框选
    first = tiles[0]
    assert first.bbox["x"] == 0.0 and first.bbox["w"] == pytest.approx(1500 / 4000)
    assert len({t.key for t in tiles}) == len(tiles)  # key 唯一 ⇒ 可做幂等键


def test_plan_tiles_skips_when_nothing_to_gain():
    """短边太小、或一块瓦片就覆盖全图（= 帧级向量的重复），都不切。"""
    assert plan_tiles(320, 240, grid=2, overlap=0.25, min_side=640, max_tiles=12) == []
    assert plan_tiles(800, 800, grid=1, overlap=0.25, min_side=640, max_tiles=12) == []


def test_plan_tiles_cap_keeps_global_coverage():
    """超过上限时均匀抽稀，而不是截前 N——否则全景图右半张永远搜不到。"""
    tiles = plan_tiles(8000, 800, grid=2, overlap=0.25, min_side=640, max_tiles=6)
    assert len(tiles) == 6
    assert max(t.box[0] for t in tiles) > 3000  # 右半张仍有瓦片入选


def test_crop_tiles_matches_plan(tmp_path):
    """裁图数量/尺寸与规划一致，且缩到编码尺寸（不会把 1500px 原样发给编码器）。"""
    path = tmp_path / "big.jpg"
    path.write_bytes(_patterned_jpeg(1024, 768, seed=3))
    image = load_display_image(path)
    tiles = plan_tiles(image.width, image.height, grid=2, overlap=0.25, min_side=640, max_tiles=12)

    crops = crop_tiles(image, tiles)
    assert len(crops) == len(tiles)
    for data in crops:
        with Image.open(io.BytesIO(data)) as im:
            assert max(im.size) <= 448


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
        "idempotency_key": f"regions-{name}-{uuid.uuid4()}",
        "trigger": "auto",
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


async def test_ingest_writes_regions_and_is_idempotent(db_session):
    """摄入大图 → 自动切片入库；再跑一次不重复编码（region_key 幂等）。"""
    fake = FakeLLMClient()
    vision = FakeVisionEncoder(dim=DIM)
    async with _client(fake, vision) as client:
        await _ingest(client, "big.jpg", _patterned_jpeg(1024, 768, seed=5))
        await _drain_outbox(fake, vision)

    frame = (await db_session.scalars(select(FrameAsset))).one()
    regions = (
        await db_session.scalars(
            select(FrameRegion).where(
                FrameRegion.frame_asset_id == frame.id, FrameRegion.source == "tile"
            )
        )
    ).all()
    assert len(regions) == 12  # 1024x768 / grid=2 / overlap=0.25 → 4x3
    assert all(r.visual_embedding is not None for r in regions)
    assert len({r.region_key for r in regions}) == len(regions)

    calls_before = len(vision.calls)
    assert await regionize_frame_asset(db_session, frame_asset_id=frame.id, vision=vision) == 0
    assert len(vision.calls) == calls_before  # 幂等：压根没再调编码器


async def test_regionize_skips_when_media_gone_but_retries_encoder_failure(db_session):
    """媒体已删 = 永久失败（消费掉）；编码器返回 None = 暂时失败（抛出走退避）。"""
    fake = FakeLLMClient()
    vision = FakeVisionEncoder(dim=DIM)
    async with _client(fake, vision) as client:
        await _ingest(client, "big.jpg", _patterned_jpeg(1024, 768, seed=7))
        await _drain_outbox(fake, vision)

    frame = (await db_session.scalars(select(FrameAsset))).one()
    await db_session.execute(
        FrameRegion.__table__.delete().where(FrameRegion.frame_asset_id == frame.id)
    )
    await db_session.commit()

    # 编码器不可用：必须抛出，否则任务被当成「成功但没结果」消费掉，这帧永远没有区域
    with pytest.raises(RegionizeRetryable):
        await regionize_frame_asset(
            db_session, frame_asset_id=frame.id, vision=FakeVisionEncoder(enabled=False)
        )

    # TTL 删掉原件之后就没有输入了：安静返回 0，不该无限重试
    item = await db_session.get(EvidenceItem, frame.evidence_item_id)
    item.storage_ref = None
    await db_session.commit()
    assert await regionize_frame_asset(db_session, frame_asset_id=frame.id, vision=vision) == 0


async def test_region_rollup_surfaces_small_object(db_session):
    """整图向量看不见的小物体，靠区域向量把帧捞出来——这条就是本改动的目的。

    构造：两帧整图都"是地毯"，其中一帧有一块区域"是身份证"。
    查询「身份证」时，只有并搜区域向量才能把那一帧排到第一。
    """
    fake = FakeLLMClient()
    vision = FakeVisionEncoder(
        dim=DIM, token_basis={"身份证": _one_hot(0), "地毯": _one_hot(1)}
    )
    async with _client(fake, vision) as client:
        await _ingest(client, "a.jpg", _patterned_jpeg(64, 64, seed=11))
        await _ingest(client, "b.jpg", _patterned_jpeg(64, 64, seed=13))
        await _drain_outbox(fake, vision)

    frames = (await db_session.scalars(select(FrameAsset).order_by(FrameAsset.created_at))).all()
    assert len(frames) == 2
    for f in frames:
        f.visual_embedding = _one_hot(1)  # 两帧整图都只"看得见地毯"
    target = frames[0]
    db_session.add(
        FrameRegion(
            frame_asset_id=target.id,
            region_key="tile:32:1,1",
            source="tile",
            bbox={"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5},
            visual_embedding=_one_hot(0),  # 只有这一小块是身份证
        )
    )
    await db_session.commit()

    with_regions = await visual_search_frames(
        db_session, vision=vision, query_text="身份证在哪", top_k=8, include_regions=True
    )
    assert with_regions[0][0].id == target.id
    assert with_regions[0][1] == pytest.approx(1.0)  # max 取的是命中那块，没被无关瓦片稀释

    without_regions = await visual_search_frames(
        db_session, vision=vision, query_text="身份证在哪", top_k=8, include_regions=False
    )
    assert all(score == pytest.approx(0.0, abs=1e-6) for _, score in without_regions)
