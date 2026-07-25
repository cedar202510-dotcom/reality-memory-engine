"""Harness 测试：工具循环、limitations 透传、403 降级、轮数上限、主动式措辞。

平台用 httpx.MockTransport 模拟（契约以 memory-platform schemas 为准），
模型用 FakeChatLLM 脚本驱动。
"""
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.harness import run_turn
from app.llm import AssistantTurn, FakeChatLLM, ToolCall
from app.main import create_app
from app.memory_client import MemoryClient
from app.proactive import build_suggestions, template_wording

FIND_OBJECT_RESPONSE = {
    "query": "钥匙",
    "channel": "projection",
    "entity": {"id": "8b0d2c68-0000-0000-0000-000000000001", "canonical_name": "钥匙", "aliases": []},
    "location": "玄关柜",
    "last_seen_time": "2026-07-25T09:30:00Z",
    "freshness": "最后一次看到是 30 分钟前",
    "confidence": 0.81,
    "answer_text": "钥匙最后一次看到是 30 分钟前，在玄关柜。",
    "alternatives": [],
    "timeline_url": "/v1/memory/objects/8b0d2c68-0000-0000-0000-000000000001/timeline",
    "provenance_summary": {"supporting_event_ids": [], "support_count": 2, "last_corrected_at": None},
    "limitations": ["这是最后一次可靠观察，不保证物品仍在原处。"],
    "cache_until": "2026-07-25T10:05:00Z",
}


def _platform_transport(handler=None) -> httpx.MockTransport:
    def default_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/memory/objects/where-is":
            return httpx.Response(200, json=FIND_OBJECT_RESPONSE)
        if request.url.path == "/v1/signals":
            return httpx.Response(
                200,
                json={
                    "signals": [
                        {
                            "id": "sig-1",
                            "signal_type": "LOW_CONSUMABLE",
                            "entity_id": None,
                            "payload": {"entity_name": "洗衣液", "level": "LOW"},
                            "confidence": 0.9,
                            "status": "DELIVERED",
                            "created_at": "2026-07-25T09:00:00Z",
                            "expires_at": "2026-07-26T09:00:00Z",
                        }
                    ],
                    "suppressed": 1,
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler or default_handler)


def _memory(handler=None) -> MemoryClient:
    return MemoryClient(
        base_url="http://platform.test", token="grant-token", transport=_platform_transport(handler)
    )


async def test_tool_loop_and_limitation_passthrough():
    llm = FakeChatLLM(
        script=[
            AssistantTurn(tool_calls=[ToolCall(id="c1", name="find_object", arguments={"name": "钥匙"})]),
            AssistantTurn(
                content="我最后一次可靠看到钥匙是在 30 分钟前，位置是玄关柜（置信度 0.81）。"
                "不过这是最后一次观察，不保证还在原处。"
            ),
        ]
    )
    memory = _memory()
    history: list[dict] = []
    result = await run_turn(llm=llm, memory=memory, history=history, user_message="我的钥匙在哪？")

    assert "玄关柜" in result.reply
    assert len(result.tool_trace) == 1
    assert result.tool_trace[0].tool == "find_object"
    tool_payload = json.loads(result.tool_trace[0].result)
    assert tool_payload["limitations"]  # limitations 到达模型可见的工具结果里

    # 会话历史完整：system + user + assistant(tool_calls) + tool + assistant
    roles = [m["role"] for m in history]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    # 第二轮模型收到的消息里包含工具结果（模型能引用 limitations）
    assert any(m["role"] == "tool" and "不保证物品仍在原处" in m["content"] for m in llm.calls[-1])


async def test_scope_denied_becomes_structured_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "缺少授权 scope：memory.query.objects"})

    llm = FakeChatLLM(
        script=[
            AssistantTurn(tool_calls=[ToolCall(id="c1", name="find_object", arguments={"name": "钥匙"})]),
            AssistantTurn(content="我目前没有查询物品位置的授权，需要你先授权我访问位置记忆。"),
        ]
    )
    result = await run_turn(
        llm=llm, memory=_memory(handler), history=[], user_message="钥匙在哪？"
    )
    err = json.loads(result.tool_trace[0].result)
    assert err["status"] == 403
    assert "scope" in err["error"]
    assert "授权" in result.reply


async def test_tool_turn_limit_degrades():
    """模型每轮都调工具 → 达到上限后收尾，不无限循环。"""
    endless = [
        AssistantTurn(tool_calls=[ToolCall(id=f"c{i}", name="find_object", arguments={"name": "钥匙"})])
        for i in range(10)
    ]
    llm = FakeChatLLM(script=endless)
    result = await run_turn(
        llm=llm, memory=_memory(), history=[], user_message="钥匙在哪？", max_tool_turns=2
    )
    assert len(result.tool_trace) == 2  # 只执行了 2 轮
    assert result.reply  # 有收尾回复而非挂死


async def test_platform_unavailable_is_reported_not_fabricated():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    llm = FakeChatLLM(
        script=[
            AssistantTurn(tool_calls=[ToolCall(id="c1", name="find_object", arguments={"name": "钥匙"})]),
            AssistantTurn(content="记忆平台暂时不可用，稍后我再帮你查，先不猜测位置。"),
        ]
    )
    result = await run_turn(llm=llm, memory=_memory(handler), history=[], user_message="钥匙在哪？")
    err = json.loads(result.tool_trace[0].result)
    assert err["status"] == 0
    assert "不可用" in err["error"]


async def test_chat_endpoint_and_session_continuity():
    llm = FakeChatLLM(
        script=[
            AssistantTurn(tool_calls=[ToolCall(id="c1", name="find_object", arguments={"name": "钥匙"})]),
            AssistantTurn(content="钥匙在玄关柜，30 分钟前看到的。"),
            AssistantTurn(content="刚才说过啦：在玄关柜。"),
        ]
    )
    app = create_app(fake_llm=llm, memory_client=_memory())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gw") as client:
        resp = await client.post("/v1/chat", json={"message": "钥匙在哪？"})
        assert resp.status_code == 200
        body = resp.json()
        assert "玄关柜" in body["reply"]
        sid = body["session_id"]

        # 同会话第二问：历史延续（FakeChatLLM 收到的消息含上一轮对话）
        resp = await client.post("/v1/chat", json={"message": "再说一遍？", "session_id": sid})
        assert resp.json()["session_id"] == sid
        assert any(m["role"] == "user" and "钥匙在哪" in str(m["content"]) for m in llm.calls[-1])


async def test_chat_result_is_converted_and_sent_to_glasses():
    device_id = str(uuid.uuid4())
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/agent/devices/{device_id}/messages":
            body = json.loads(request.content)
            captured.append(body)
            return httpx.Response(
                200,
                json={
                    "message": {
                        "message_id": str(uuid.uuid4()),
                        "status": "PENDING",
                    },
                    "pushed_connections": 0,
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    llm = FakeChatLLM(script=[AssistantTurn(content="钥匙最后一次看到是在玄关柜。")])
    app = create_app(fake_llm=llm, memory_client=_memory(handler))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gw") as client:
        resp = await client.post(
            "/v1/chat",
            json={
                "message": "钥匙在哪？",
                "delivery": {"device_id": device_id, "allow_tts": False},
            },
        )

    assert resp.status_code == 200
    result = resp.json()
    assert result["delivery"]["status"] == "QUEUED"
    assert result["delivery"]["transport"] == "inbox"
    assert len(captured) == 1
    request = captured[0]
    assert request["payload_schema_ref"] == "rme.glasses-presentation.v0"
    assert request["payload"]["presentation"]["intent"] == "ANSWER"
    assert request["payload"]["presentation"]["interaction"] == "NONE"
    assert request["payload"]["source"]["kind"] == "AGENT_REPLY"
    assert "style" not in request["payload"]


async def test_aiui_chat_returns_to_aiui_without_duplicate_glasses_message():
    device_id = str(uuid.uuid4())
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/v1/agent/devices/{device_id}/messages":
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"detail": "not found"})

    settings = Settings(
        _env_file=None,
        glasses_auto_delivery_enabled=True,
        glasses_default_device_id=device_id,
    )
    app = create_app(
        fake_llm=FakeChatLLM(script=[AssistantTurn(content="钥匙最后一次在玄关柜。")]),
        memory_client=_memory(handler),
        settings_override=settings,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gw") as client:
        resp = await client.post(
            "/v1/chat",
            json={
                "message": "我的钥匙在哪？",
                "source": "ROKID_AIUI",
                "response_channel": "AIUI_CONVERSATION",
                "device_id": device_id,
                "correlation_id": "aiui:test-turn",
            },
        )

    assert resp.status_code == 200
    result = resp.json()
    assert result["source"] == "ROKID_AIUI"
    assert result["response_channel"] == "AIUI_CONVERSATION"
    assert result["correlation_id"] == "aiui:test-turn"
    assert result["delivery"] is None
    assert captured == []


async def test_aiui_chat_rejects_conflicting_native_delivery():
    app = create_app(
        fake_llm=FakeChatLLM(script=[AssistantTurn(content="不会执行")]),
        memory_client=_memory(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gw") as client:
        resp = await client.post(
            "/v1/chat",
            json={
                "message": "测试",
                "source": "ROKID_AIUI",
                "response_channel": "AIUI_CONVERSATION",
                "delivery": {"device_id": str(uuid.uuid4())},
            },
        )

    assert resp.status_code == 422


async def test_aiui_client_token_is_checked_when_configured():
    settings = Settings(_env_file=None, aiui_client_token="test-aiui-token")
    app = create_app(
        fake_llm=FakeChatLLM(
            script=[
                AssistantTurn(content="认证后的回答"),
                AssistantTurn(content="认证后的第二次回答"),
            ]
        ),
        memory_client=_memory(),
        settings_override=settings,
    )
    payload = {
        "message": "测试认证",
        "source": "ROKID_AIUI",
        "response_channel": "AIUI_CONVERSATION",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gw") as client:
        denied = await client.post("/v1/chat", json=payload)
        allowed = await client.post(
            "/v1/chat",
            json=payload,
            headers={"X-RealGit-Client-Token": "test-aiui-token"},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200


async def test_proactive_check_templates():
    app = create_app(fake_llm=FakeChatLLM(), memory_client=_memory())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gw") as client:
        resp = await client.post("/v1/proactive/check")
        assert resp.status_code == 200
        body = resp.json()
        assert body["suppressed"] == 1
        assert len(body["suggestions"]) == 1
        s = body["suggestions"][0]
        assert s["signal_type"] == "LOW_CONSUMABLE"
        assert "洗衣液" in s["text"]
    assert "吗" in s["text"]  # 只建议（问句），不执行


async def test_proactive_result_is_sent_as_purchase_reminder():
    device_id = str(uuid.uuid4())
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/signals":
            return httpx.Response(
                200,
                json={
                    "signals": [
                        {
                            "id": "sig-low-detergent",
                            "signal_type": "LOW_CONSUMABLE",
                            "payload": {"entity_name": "洗衣液", "level": "LOW"},
                            "confidence": 0.9,
                        }
                    ],
                    "suppressed": 0,
                },
            )
        if request.url.path == f"/v1/agent/devices/{device_id}/messages":
            body = json.loads(request.content)
            captured.append(body)
            return httpx.Response(
                200,
                json={
                    "message": {
                        "message_id": str(uuid.uuid4()),
                        "status": "PENDING",
                    },
                    "pushed_connections": 0,
                },
            )
        return httpx.Response(404, json={"detail": "not found"})

    app = create_app(fake_llm=FakeChatLLM(), memory_client=_memory(handler))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gw") as client:
        resp = await client.post(
            "/v1/proactive/check",
            json={"delivery": {"device_id": device_id}},
        )

    assert resp.status_code == 200
    result = resp.json()
    assert result["deliveries"][0]["status"] == "QUEUED"
    presentation = captured[0]["payload"]["presentation"]
    assert presentation["intent"] == "CONSUMABLE"
    assert presentation["interaction"]["type"] == "ADD_TO_SHOPPING_LIST"
    assert captured[0]["payload"]["source"] == {
        "kind": "MEMORY_SIGNAL",
        "reference_id": "sig-low-detergent",
    }


def test_template_wording_missing_fields_fallback():
    assert "提醒" in template_wording({"signal_type": "UNKNOWN_TYPE", "payload": {}})
    text = template_wording({"signal_type": "STALE_LOCATION", "payload": {"entity_name": "钥匙"}})
    assert "钥匙" in text
