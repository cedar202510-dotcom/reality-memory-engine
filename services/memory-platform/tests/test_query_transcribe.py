"""在场页的语音输入：一次性转写端点。

这条路径与音频摄入流水线（app/perception/audio.py）刻意分开：那条是「把听到的话变成
记忆」，这条只是「把用户对着界面说的话变成字」。所以本文件的断言重点是**它不留下任何
东西**——不落盘、不进 evidence_items、审计里不记内容。
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.asr.fake import FakeTranscriber
from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.models import AuditRecord, EvidenceItem

AUDIO = b"fake-webm-bytes"


def _app(**asr_kwargs):
    return create_app(
        fake_llm=FakeLLMClient(),
        fake_asr=FakeTranscriber(**asr_kwargs),
        with_workers=False,
    )


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _upload(data: bytes = AUDIO, mime: str = "audio/webm"):
    return {"audio": ("clip.webm", data, mime)}


@pytest.mark.asyncio
async def test_transcribe_returns_text_and_stores_nothing(db_session):
    app = _app(
        segments_by_digest={
            FakeTranscriber.audio_digest(AUDIO): [
                {"start": 0.0, "end": 1.0, "text": "我的充电器"},
                {"start": 1.0, "end": 2.0, "text": "在哪里"},
            ]
        }
    )
    before = len((await db_session.execute(select(EvidenceItem))).scalars().all())

    async with _client(app) as client:
        resp = await client.post("/v1/memory/transcribe", files=_upload())

    assert resp.status_code == 200
    assert resp.json()["text"] == "我的充电器 在哪里"

    # 这段音频不是证据：证据表条数必须一条都没多
    after = len((await db_session.execute(select(EvidenceItem))).scalars().all())
    assert after == before


@pytest.mark.asyncio
async def test_audit_records_the_call_but_not_the_words(db_session):
    """审计要能证明「转写发生过」，但不能变成转写内容的第二个存储点。"""
    app = _app(default_segments=[{"start": 0.0, "end": 1.0, "text": "冰箱里还有牛奶吗"}])

    async with _client(app) as client:
        resp = await client.post("/v1/memory/transcribe", files=_upload())
    assert resp.status_code == 200

    rows = (
        (await db_session.execute(select(AuditRecord).where(AuditRecord.action == "transcribe")))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].detail["chars"] == len("冰箱里还有牛奶吗")
    assert "牛奶" not in str(rows[0].detail)


@pytest.mark.asyncio
async def test_asr_unavailable_is_503_not_empty_text():
    """ASR 没配起来时必须报错。返回空串会被界面显示成「你没说话」，那是在撒谎。"""
    app = _app(enabled=False)

    async with _client(app) as client:
        resp = await client.post("/v1/memory/transcribe", files=_upload())

    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_empty_audio_rejected():
    app = _app()
    async with _client(app) as client:
        resp = await client.post("/v1/memory/transcribe", files=_upload(data=b""))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_agent_token_forbidden():
    """带 token 的调用一律 403：转写不是记忆访问，外部 agent 没有理由借这台机器当 ASR 用。"""
    app = _app()
    async with _client(app) as client:
        resp = await client.post(
            "/v1/memory/transcribe",
            files=_upload(),
            headers={"Authorization": "Bearer whatever"},
        )
    assert resp.status_code in (401, 403)
