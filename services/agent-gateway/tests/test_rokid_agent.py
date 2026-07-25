"""Rokid 灵珠三方智能体 SSE 协议适配测试。"""
from __future__ import annotations

import json

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.llm import AssistantTurn, FakeChatLLM
from app.main import create_app

from test_harness import _memory


def _request_payload(
    *,
    message_id: str = "conversation-1",
    agent_id: str = "realgit-agent",
    text: str = "我的钥匙在哪里？",
) -> dict:
    return {
        "message_id": message_id,
        "agent_id": agent_id,
        "message": [
            {"role": "agent", "type": "text", "text": "你想查询什么？"},
            {"role": "user", "type": "text", "text": text},
        ],
        "user_id": "rokid-user-1",
        "metadata": {
            "context": {
                "location": "杭州",
                "latitude": "30.2",
                "longitude": "120.2",
                "weather": "晴",
                "battery": "80",
            }
        },
    }


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(line[7:] for line in lines if line.startswith("event: "))
        raw_data = next(line[6:] for line in lines if line.startswith("data: "))
        events.append((event, json.loads(raw_data)))
    return events


async def test_rokid_sse_requires_bearer_ak():
    settings = Settings(_env_file=None, rokid_agent_ak="rokid-secret")
    app = create_app(
        fake_llm=FakeChatLLM(script=[AssistantTurn(content="不会执行")]),
        memory_client=_memory(),
        settings_override=settings,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://gw",
    ) as client:
        missing = await client.post(
            "/v1/rokid/agent/sse",
            json=_request_payload(),
        )
        wrong = await client.post(
            "/v1/rokid/agent/sse",
            json=_request_payload(),
            headers={"Authorization": "Bearer wrong"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401


async def test_rokid_sse_returns_message_and_done_events():
    settings = Settings(
        _env_file=None,
        rokid_agent_ak="rokid-secret",
        rokid_agent_id="realgit-agent",
    )
    app = create_app(
        fake_llm=FakeChatLLM(
            script=[AssistantTurn(content="钥匙最后一次看到是在玄关柜。")]
        ),
        memory_client=_memory(),
        settings_override=settings,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://gw",
    ) as client:
        response = await client.post(
            "/v1/rokid/agent/sse",
            json=_request_payload(),
            headers={"Authorization": "Bearer rokid-secret"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = _parse_sse(response.text)
    assert [event for event, _ in events] == ["message", "done"]

    message = events[0][1]
    assert message == {
        "role": "agent",
        "message_id": "conversation-1",
        "agent_id": "realgit-agent",
        "answer_stream": "钥匙最后一次看到是在玄关柜。",
        "is_finish": False,
        "type": "answer",
    }
    assert events[1][1]["is_finish"] is True
    assert events[1][1]["answer_stream"] == ""


async def test_rokid_sse_rejects_unregistered_agent_id():
    settings = Settings(
        _env_file=None,
        rokid_agent_ak="rokid-secret",
        rokid_agent_id="realgit-agent",
    )
    app = create_app(
        fake_llm=FakeChatLLM(script=[AssistantTurn(content="不会执行")]),
        memory_client=_memory(),
        settings_override=settings,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://gw",
    ) as client:
        response = await client.post(
            "/v1/rokid/agent/sse",
            json=_request_payload(agent_id="other-agent"),
            headers={"Authorization": "Bearer rokid-secret"},
        )

    assert response.status_code == 403


async def test_rokid_sse_rejects_image_only_input():
    settings = Settings(_env_file=None, rokid_agent_ak="rokid-secret")
    app = create_app(
        fake_llm=FakeChatLLM(script=[AssistantTurn(content="不会执行")]),
        memory_client=_memory(),
        settings_override=settings,
    )
    payload = _request_payload()
    payload["message"] = [
        {
            "role": "user",
            "type": "image",
            "image_url": "https://example.test/image.jpg",
        }
    ]
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://gw",
    ) as client:
        response = await client.post(
            "/v1/rokid/agent/sse",
            json=payload,
            headers={"Authorization": "Bearer rokid-secret"},
        )

    assert response.status_code == 422
    assert "只支持文字" in response.json()["detail"]


async def test_rokid_sse_reuses_platform_message_id_as_session():
    settings = Settings(_env_file=None, rokid_agent_ak="rokid-secret")
    llm = FakeChatLLM(
        script=[
            AssistantTurn(content="钥匙在玄关柜。"),
            AssistantTurn(content="刚才说过，在玄关柜。"),
        ]
    )
    app = create_app(
        fake_llm=llm,
        memory_client=_memory(),
        settings_override=settings,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://gw",
    ) as client:
        first = await client.post(
            "/v1/rokid/agent/sse",
            json=_request_payload(text="钥匙在哪里？"),
            headers={"Authorization": "Bearer rokid-secret"},
        )
        second = await client.post(
            "/v1/rokid/agent/sse",
            json=_request_payload(text="再说一次？"),
            headers={"Authorization": "Bearer rokid-secret"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert any(
        item["role"] == "user" and "钥匙在哪里" in str(item["content"])
        for item in llm.calls[-1]
    )
