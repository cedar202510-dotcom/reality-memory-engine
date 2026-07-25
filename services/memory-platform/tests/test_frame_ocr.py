"""OCR 通道测试：脱敏规则 + 识别流水线 + 字面量检索。

覆盖：
- 纯逻辑（不依赖 DB）：证件号/卡号/手机号/邮箱脱敏，占位符仍可检索，误伤边界
- 端到端：摄入后写脱敏文本区域、幂等、引擎不可用时抛可重试信号、媒体已删不重试
- 检索：caption 里只字未提「身份证」时，能不能靠卡面上印的字把这一帧捞出来
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
from app.ocr.fake import FakeTextRecognizer
from app.ocr.redact import redact_pii
from app.perception.ocr import OCRRetryable, ocr_frame_asset
from app.query.where_is import _retrieve_frames, _retrieve_frames_ocr
from app.workers import process_outbox_once

# 合法结构的假号码（地区码+出生日期+顺序码+校验位），不对应任何真实证件
FAKE_ID = "310104199003077778"
FAKE_CARD = "6222021234567890123"
FAKE_PHONE = "13800001234"


def _patterned_jpeg(seed: int, size: int = 64) -> bytes:
    img = Image.new("RGB", (size, size))
    img.putdata(
        [
            ((x * seed) % 256, (y * 7 * seed) % 256, (x * y * seed) % 256)
            for y in range(size)
            for x in range(size)
        ]
    )
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------- 脱敏（纯逻辑）


def test_redact_replaces_identifiers_with_type_placeholders():
    """证件号/卡号/手机号/邮箱换成类型占位符，卡面上的品类文字原样保留。"""
    result = redact_pii(
        f"中华人民共和国居民身份证 公民身份号码 {FAKE_ID} 联系电话{FAKE_PHONE}"
    )
    assert FAKE_ID not in result.text
    assert FAKE_PHONE not in result.text
    assert "〔身份证号〕" in result.text and "〔手机号〕" in result.text
    assert "居民身份证" in result.text  # 品类文字是检索入口，不能一起抹掉
    assert set(result.kinds) == {"id_card", "phone"}
    assert result.redacted


def test_redact_id_card_wins_over_bank_card_overlap():
    """18 位身份证号同时落在银行卡的 16-19 位区间里，必须判成身份证。"""
    assert "〔身份证号〕" in redact_pii(FAKE_ID).text
    assert redact_pii(FAKE_ID).kinds == ("id_card",)
    # 真银行卡号（不符合身份证的日期结构）仍走卡号规则
    assert redact_pii(FAKE_CARD).kinds == ("bank_card",)


def test_redact_leaves_ordinary_text_alone():
    """普通文本和短数字不该被误伤，否则脱敏会把可用文本一起毁掉。"""
    text = "第 3 排 12 号 2026年7月25日 共 158 页"
    result = redact_pii(text)
    assert result.text == text
    assert not result.redacted


def test_placeholder_is_still_searchable():
    """占位符保留类型名的意义：银行卡卡面常常只有一串数字，没有品类文字。"""
    redacted = redact_pii(f"招商银行 {FAKE_CARD}").text
    assert "银行卡" in redacted  # 查「银行卡」时 ilike '%银行卡%' 仍能命中


# ---------------------------------------------------------------- 端到端（真实 PG + API）


async def _drain(fake: FakeLLMClient) -> int:
    total = 0
    while True:
        n = await process_outbox_once(fake)
        total += n
        if n == 0:
            return total


async def _ingest(client: AsyncClient, name: str, data: bytes) -> dict:
    ts = datetime.now(timezone.utc).isoformat()
    envelope = {
        "occurred_at": ts,
        "observed_at": ts,
        "idempotency_key": f"ocr-{name}-{uuid.uuid4()}",
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


def _client(fake: FakeLLMClient) -> AsyncClient:
    app = create_app(fake_llm=fake, with_workers=False)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _one_frame(db_session, data: bytes) -> FrameAsset:
    fake = FakeLLMClient()
    async with _client(fake) as client:
        await _ingest(client, "a.jpg", data)
        await _drain(fake)
    return (await db_session.scalars(select(FrameAsset))).one()


async def test_ocr_writes_redacted_text_and_is_idempotent(db_session):
    """识别 → 脱敏 → 落 source=ocr 区域；重跑不再调引擎。"""
    data = _patterned_jpeg(5)
    frame = await _one_frame(db_session, data)

    recognizer = FakeTextRecognizer(
        blocks_by_digest={
            FakeTextRecognizer.image_digest(data): [
                {"text": "中华人民共和国居民身份证", "bbox": {"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}, "score": 0.98},
                {"text": f"公民身份号码 {FAKE_ID}", "bbox": {"x": 0.1, "y": 0.35, "w": 0.4, "h": 0.08}, "score": 0.91},
            ]
        }
    )
    text = await ocr_frame_asset(db_session, frame_asset_id=frame.id, recognizer=recognizer)

    assert text is not None and FAKE_ID not in text
    assert "居民身份证" in text and "〔身份证号〕" in text

    region = (
        await db_session.scalars(
            select(FrameRegion).where(
                FrameRegion.frame_asset_id == frame.id, FrameRegion.source == "ocr"
            )
        )
    ).one()
    assert region.ocr_text == text
    assert FAKE_ID not in json.dumps(region.bbox)  # 号码不该从别的字段漏出去
    assert region.bbox["x"] == pytest.approx(0.1)  # 外接框覆盖两个文本块
    assert region.bbox["h"] == pytest.approx(0.43 - 0.2)

    calls_before = len(recognizer.calls)
    assert await ocr_frame_asset(
        db_session, frame_asset_id=frame.id, recognizer=recognizer
    ) == text
    assert len(recognizer.calls) == calls_before  # 幂等：没再调引擎


async def test_ocr_retries_engine_failure_but_not_missing_media(db_session):
    """引擎返回 None = 暂时失败（抛出走退避）；媒体已删 = 永久失败（安静消费）。"""
    frame = await _one_frame(db_session, _patterned_jpeg(7))

    with pytest.raises(OCRRetryable):
        await ocr_frame_asset(
            db_session,
            frame_asset_id=frame.id,
            recognizer=FakeTextRecognizer(enabled=False),
        )

    item = await db_session.get(EvidenceItem, frame.evidence_item_id)
    item.storage_ref = None
    await db_session.commit()
    assert (
        await ocr_frame_asset(
            db_session, frame_asset_id=frame.id, recognizer=FakeTextRecognizer()
        )
        is None
    )


async def test_blank_image_writes_nothing(db_session):
    """画面里确实没字：不写空行，省得把索引撑大。"""
    frame = await _one_frame(db_session, _patterned_jpeg(9))
    assert (
        await ocr_frame_asset(
            db_session, frame_asset_id=frame.id, recognizer=FakeTextRecognizer()
        )
        is None
    )
    assert not (
        await db_session.scalars(
            select(FrameRegion).where(FrameRegion.source == "ocr")
        )
    ).all()


async def test_ocr_recall_finds_frame_whose_caption_never_says_it(db_session):
    """caption 只字未提「身份证」，靠卡面上印的字把这一帧捞出来——这条就是本通道的目的。"""
    data = _patterned_jpeg(11)
    frame = await _one_frame(db_session, data)
    assert "身份证" not in frame.caption  # 前提：文本路本来搜不到

    await ocr_frame_asset(
        db_session,
        frame_asset_id=frame.id,
        recognizer=FakeTextRecognizer(
            blocks_by_digest={
                FakeTextRecognizer.image_digest(data): [
                    {"text": f"中华人民共和国居民身份证 {FAKE_ID}", "score": 0.95}
                ]
            }
        ),
    )

    hits = await _retrieve_frames_ocr(db_session, name="身份证", top_k=8)
    assert [f.id for f, _ in hits] == [frame.id]
    assert hits[0][1] == pytest.approx(1.0)  # 字面量包含 = 这条链路上最硬的证据

    assert await _retrieve_frames_ocr(db_session, name="遥控器", top_k=8) == []

    # 并且真的并进了通道 2 的文本路——单测 _retrieve_frames_ocr 通过、
    # 融合处却没接上，是这种"多加一路"改动最容易出的问题。
    # 关掉 embedding 走 trgm 降级路：caption 里没有「身份证」→ 文本路本身零命中，
    # 这时还能召回，就只可能来自 OCR（开着向量检索的话所有帧都会被返回，测不出东西）。
    no_embed = FakeLLMClient(embedding_enabled=False)
    assert [
        f.id for f in await _retrieve_frames(db_session, llm=no_embed, name="身份证", top_k=8)
    ] == [frame.id]
    assert await _retrieve_frames(db_session, llm=no_embed, name="遥控器", top_k=8) == []
