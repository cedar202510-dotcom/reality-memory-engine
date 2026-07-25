"""采集媒体总览：跨模态列表、过滤分页、TTL 墓碑与真实 Content-Type。"""
from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import AudioAsset, EvidenceItem, FrameAsset, SourceEnvelope, utcnow


def _app():
    return create_app(fake_llm=FakeLLMClient(), with_workers=False)


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _envelope(db_session) -> SourceEnvelope:
    now = utcnow()
    env = SourceEnvelope(
        occurred_at=now, observed_at=now, idempotency_key=f"test-{uuid.uuid4()}"
    )
    db_session.add(env)
    await db_session.flush()
    return env


async def _evidence(db_session, tmp_path: Path, *, kind: str, name: str, data: bytes) -> EvidenceItem:
    """落一条证据 + 真文件。文件名带真实扩展名，Content-Type 才有的可判。"""
    env = await _envelope(db_session)
    path = tmp_path / name
    path.write_bytes(data)
    item = EvidenceItem(
        envelope_id=env.id,
        storage_ref=str(path),
        media_kind=kind,
        ttl_until=utcnow() + timedelta(minutes=60),
        retention_state="ACTIVE",
    )
    db_session.add(item)
    await db_session.flush()
    return item


@pytest.mark.asyncio
async def test_media_list_covers_every_modality(db_session, tmp_path, make_image):
    """图片、音频、视频要在同一个列表里都能看到。

    这正是 frames/recent 做不到的事——它建在 frame_assets 上，音频和视频根本不在那张表里。
    """
    img = await _evidence(db_session, tmp_path, kind="image", name="a.jpg", data=make_image((10, 20, 30)))
    db_session.add(
        FrameAsset(
            evidence_item_id=img.id, caption="桌上有一杯水",
            scene_tags=["室内", "桌面"], captured_at=utcnow(),
        )
    )
    aud = await _evidence(db_session, tmp_path, kind="audio", name="b.wav", data=b"RIFF....WAVE")
    db_session.add(
        AudioAsset(
            evidence_item_id=aud.id, transcript="这家胡辣汤不好喝",
            segments=[], language="zh", duration_seconds=8.0, captured_at=utcnow(),
        )
    )
    vid = await _evidence(db_session, tmp_path, kind="video", name="c.mp4", data=b"\x00\x00\x00\x18ftyp")
    await db_session.commit()

    async with _client(_app()) as client:
        body = (await client.get("/v1/memory/media")).json()

    by_id = {i["evidence_item_id"]: i for i in body["items"]}
    assert body["total"] == 3
    assert set(by_id) == {str(img.id), str(aud.id), str(vid.id)}

    assert by_id[str(img.id)]["caption"] == "桌上有一杯水"
    assert by_id[str(img.id)]["perception_state"] == "READY"
    assert by_id[str(aud.id)]["transcript"] == "这家胡辣汤不好喝"
    assert by_id[str(aud.id)]["duration_seconds"] == 8.0
    # 视频自 video.process 起有解析器了（拆成关键帧 + 音轨），所以这条还没跑完的
    # 视频是 PENDING 而不是 UNSUPPORTED——它会等到结果。UNSUPPORTED 现在只留给
    # 真正没有解析器的传感器数据：那种才需要和「还在排队」区分开，
    # 否则界面会让人一直等一个不会到来的结果。
    assert by_id[str(vid.id)]["perception_state"] == "PENDING"
    assert by_id[str(vid.id)]["caption"] is None


@pytest.mark.asyncio
async def test_content_type_follows_real_extension(db_session, tmp_path, make_image):
    """音频按真实扩展名给 Content-Type，不是按 media_kind 硬套。"""
    wav = await _evidence(db_session, tmp_path, kind="audio", name="ok.wav", data=b"RIFF....WAVE")
    # 正式 App 传的是裸 PCM：贴 audio/wav 会让浏览器播出一段噪音，
    # 老老实实回 octet-stream，让 UI 显示「这个格式放不了」
    pcm = await _evidence(db_session, tmp_path, kind="audio", name="raw.pcm", data=b"\x01\x02\x03\x04")
    img = await _evidence(db_session, tmp_path, kind="image", name="p.jpg", data=make_image((1, 2, 3)))
    await db_session.commit()

    async with _client(_app()) as client:
        listed = {i["evidence_item_id"]: i for i in (await client.get("/v1/memory/media")).json()["items"]}
        wav_resp = await client.get(f"/v1/memory/media/{wav.id}/raw")
        pcm_resp = await client.get(f"/v1/memory/media/{pcm.id}/raw")
        img_resp = await client.get(f"/v1/memory/media/{img.id}/raw")

    assert wav_resp.headers["content-type"].startswith("audio/")
    assert pcm_resp.headers["content-type"] == "application/octet-stream"
    assert img_resp.headers["content-type"] == "image/jpeg"
    assert img_resp.content == Path(str(tmp_path / "p.jpg")).read_bytes()
    # 列表里也要带上，UI 才能决定用 <img> / <audio> 还是只给下载
    assert listed[str(pcm.id)]["media_type"] == "application/octet-stream"


@pytest.mark.asyncio
async def test_ttl_deleted_media_stays_listed_as_tombstone(db_session, tmp_path, make_image):
    """TTL 删除后条目仍在列表里，但没有 raw_url——派生数据还在，原始字节没了。

    这不是错误状态，是隐私设计的正常结果：把它从列表里抹掉会让人以为采集从没发生过。
    """
    item = await _evidence(db_session, tmp_path, kind="image", name="gone.jpg", data=make_image((9, 9, 9)))
    db_session.add(
        FrameAsset(evidence_item_id=item.id, caption="已经删掉的原图", scene_tags=[], captured_at=utcnow())
    )
    await db_session.commit()

    # 模拟 TTL worker：删文件 + 置空 storage_ref + 标 DELETED
    Path(str(tmp_path / "gone.jpg")).unlink()
    item.storage_ref = None
    item.retention_state = "DELETED"
    await db_session.commit()

    async with _client(_app()) as client:
        body = (await client.get("/v1/memory/media")).json()
        raw = await client.get(f"/v1/memory/media/{item.id}/raw")
        only_alive = (await client.get("/v1/memory/media", params={"available_only": True})).json()

    entry = body["items"][0]
    assert entry["available"] is False
    assert entry["raw_url"] is None
    assert entry["media_type"] is None
    assert entry["caption"] == "已经删掉的原图"  # 派生表示不受 TTL 影响
    assert entry["perception_state"] == "READY"  # 解析在删除前已完成
    assert raw.status_code == 404
    assert only_alive["total"] == 0


@pytest.mark.asyncio
async def test_deleted_before_perception_is_abandoned_not_pending(db_session, tmp_path, make_image):
    """原始字节删了而解析从未完成 → ABANDONED，不能报 PENDING。

    解析器再也没有输入可读，这条永远不会有结果。报 PENDING 会让界面一直显示
    「处理中…」，对着一批死条目干等——真实库里就有 11 条这样的图片。
    """
    item = await _evidence(db_session, tmp_path, kind="image", name="never.jpg", data=make_image((4, 4, 4)))
    await db_session.commit()
    Path(str(tmp_path / "never.jpg")).unlink()
    item.storage_ref = None
    item.retention_state = "DELETED"
    await db_session.commit()

    async with _client(_app()) as client:
        entry = (await client.get("/v1/memory/media")).json()["items"][0]

    assert entry["perception_state"] == "ABANDONED"
    assert entry["caption"] is None


@pytest.mark.asyncio
async def test_kind_filter_and_pagination(db_session, tmp_path, make_image):
    """按模态过滤 + 分页；total 反映过滤后的总数而不是当页条数。"""
    for i in range(5):
        await _evidence(db_session, tmp_path, kind="image", name=f"i{i}.jpg", data=make_image((i, i, i)))
    await _evidence(db_session, tmp_path, kind="audio", name="only.wav", data=b"RIFF")
    await db_session.commit()

    async with _client(_app()) as client:
        images = (await client.get("/v1/memory/media", params={"kind": "image"})).json()
        page1 = (await client.get("/v1/memory/media", params={"kind": "image", "limit": 2})).json()
        page2 = (
            await client.get("/v1/memory/media", params={"kind": "image", "limit": 2, "offset": 2})
        ).json()
        bad = await client.get("/v1/memory/media", params={"kind": "hologram"})

    assert images["total"] == 5
    assert page1["total"] == 5 and len(page1["items"]) == 2
    # 翻页不能重复：offset 生效且排序稳定
    assert not {i["evidence_item_id"] for i in page1["items"]} & {
        i["evidence_item_id"] for i in page2["items"]
    }
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_time_range_filter(db_session, tmp_path, make_image):
    """按摄入时间过滤——「给我看昨天那次采集」是这个页面的核心用法。"""
    old = await _evidence(db_session, tmp_path, kind="image", name="old.jpg", data=make_image((1, 1, 1)))
    old.created_at = utcnow() - timedelta(days=3)
    fresh = await _evidence(db_session, tmp_path, kind="image", name="new.jpg", data=make_image((2, 2, 2)))
    await db_session.commit()

    cutoff = (utcnow() - timedelta(days=1)).isoformat()
    async with _client(_app()) as client:
        recent = (await client.get("/v1/memory/media", params={"since": cutoff})).json()
        older = (await client.get("/v1/memory/media", params={"until": cutoff})).json()

    assert [i["evidence_item_id"] for i in recent["items"]] == [str(fresh.id)]
    assert [i["evidence_item_id"] for i in older["items"]] == [str(old.id)]


@pytest.mark.asyncio
async def test_media_is_not_exposed_to_agents(db_session, tmp_path, make_image):
    """原始证据默认不给 Agent（§5）：列表和字节都要 403，不能只挡一个。"""
    item = await _evidence(db_session, tmp_path, kind="image", name="x.jpg", data=make_image((3, 3, 3)))
    await db_session.commit()

    async with _client(_app()) as client:
        issued = await client.post(
            "/v1/agent/grants",
            headers={"Authorization": "Bearer test-admin-token"},
            json={"agent_client_id": "media-test", "scopes": ["memory.query.objects"], "purpose": "test"},
        )
        assert issued.status_code == 200, issued.text
        headers = {"Authorization": f"Bearer {issued.json()['token']}"}
        listed = await client.get("/v1/memory/media", headers=headers)
        raw = await client.get(f"/v1/memory/media/{item.id}/raw", headers=headers)

    assert listed.status_code == 403
    assert raw.status_code == 403


@pytest.mark.asyncio
async def test_unknown_evidence_is_404(db_session):
    async with _client(_app()) as client:
        assert (await client.get(f"/v1/memory/media/{uuid.uuid4()}/raw")).status_code == 404
