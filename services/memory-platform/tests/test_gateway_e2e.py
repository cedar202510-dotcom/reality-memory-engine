"""跨服务契约测试：agent-gateway harness ↔ 真实 memory-platform（进程内 ASGI，无网络）。

防止 gateway 测试里的平台 mock 与真实契约漂移：这里 MemoryClient 的 transport
直接挂平台 app，走完整鉴权（grant 签发 → Bearer token → scope 检查 → 审计）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.memory.events import append_event
from app.memory.projections import recompute_projection
from app.memory.seed import get_default_household_id
from app.models import Device, Entity, utcnow
from app.signals.rules import evaluate_signals_for_entity

# ---- 以独立包名加载 agent-gateway 的 app 包（两个服务都叫 app，不能直接 sys.path） ----
_GW_APP = Path(__file__).resolve().parents[2] / "agent-gateway" / "app"


def _load_gateway():
    if "gwapp" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "gwapp", _GW_APP / "__init__.py", submodule_search_locations=[str(_GW_APP)]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules["gwapp"] = module
        spec.loader.exec_module(module)
    from gwapp.harness import run_turn  # noqa: PLC0415
    from gwapp.llm import AssistantTurn, FakeChatLLM, ToolCall  # noqa: PLC0415
    from gwapp.main import create_app as create_gateway_app  # noqa: PLC0415
    from gwapp.memory_client import MemoryClient  # noqa: PLC0415
    from gwapp.proactive import build_suggestions  # noqa: PLC0415

    return (
        run_turn,
        AssistantTurn,
        FakeChatLLM,
        ToolCall,
        MemoryClient,
        build_suggestions,
        create_gateway_app,
    )


ADMIN = {"Authorization": "Bearer test-admin-token"}


async def _issue_grant(platform_app, scopes: list[str]) -> str:
    async with AsyncClient(
        transport=ASGITransport(app=platform_app), base_url="http://platform"
    ) as client:
        resp = await client.post(
            "/v1/agent/grants",
            headers=ADMIN,
            json={"agent_client_id": "gateway-e2e", "scopes": scopes},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["token"]


async def test_gateway_harness_against_real_platform(db_session):
    run_turn, AssistantTurn, FakeChatLLM, ToolCall, MemoryClient, _, _ = _load_gateway()

    # 平台侧真实数据：手机在黑色圆凳（事件 → 投影）
    household_id = await get_default_household_id(db_session)
    entity = Entity(household_id=household_id, canonical_name="手机", created_from="observation")
    db_session.add(entity)
    await db_session.flush()
    t = utcnow() - timedelta(minutes=3)
    await append_event(
        db_session,
        entity_id=entity.id,
        event_type="OBJECT_OBSERVED_AT",
        payload={"location": "黑色圆凳"},
        event_time_from=t,
        observed_at=t,
        ingested_at=t,
        confidence={"aggregate": 0.9},
    )
    await db_session.commit()
    await recompute_projection(db_session, entity_id=entity.id)

    platform_app = create_app(fake_llm=FakeLLMClient(), with_workers=False)
    token = await _issue_grant(platform_app, ["memory.query.objects"])
    memory = MemoryClient(
        base_url="http://platform", token=token, transport=ASGITransport(app=platform_app)
    )

    llm = FakeChatLLM(
        script=[
            AssistantTurn(tool_calls=[ToolCall(id="c1", name="find_object", arguments={"name": "手机"})]),
            AssistantTurn(content="手机最后一次看到是 3 分钟前，在黑色圆凳上。不保证还在原处。"),
        ]
    )
    result = await run_turn(llm=llm, memory=memory, history=[], user_message="我的手机在哪？")

    tool_result = json.loads(result.tool_trace[0].result)
    assert tool_result["channel"] == "projection"
    assert tool_result["location"] == "黑色圆凳"
    assert tool_result["limitations"]          # M2 契约字段真实存在
    assert tool_result["cache_until"] is not None
    assert "黑色圆凳" in result.reply
    await memory.aclose()

    # 平台审计里记的是 agent client，不是 owner
    async with AsyncClient(
        transport=ASGITransport(app=platform_app), base_url="http://platform"
    ) as client:
        resp = await client.get("/v1/memory/audit")
        assert any(r["actor"] == "agent:gateway-e2e" for r in resp.json())


async def test_gateway_proactive_against_real_platform(db_session):
    _, _, _, _, MemoryClient, build_suggestions, _ = _load_gateway()

    # 真实信号：洗衣液 LOW → 规则引擎生成
    household_id = await get_default_household_id(db_session)
    entity = Entity(household_id=household_id, canonical_name="洗衣液", created_from="observation")
    db_session.add(entity)
    await db_session.flush()
    t = utcnow() - timedelta(minutes=10)
    await append_event(
        db_session,
        entity_id=entity.id,
        event_type="CONSUMABLE_LEVEL_OBSERVED",
        payload={"level": "LOW"},
        event_time_from=t,
        observed_at=t,
        ingested_at=t,
        confidence={"aggregate": 0.9},
    )
    await db_session.commit()
    await recompute_projection(db_session, entity_id=entity.id)
    await evaluate_signals_for_entity(db_session, entity_id=entity.id)
    await db_session.commit()

    platform_app = create_app(fake_llm=FakeLLMClient(), with_workers=False)
    token = await _issue_grant(platform_app, ["memory.signal.subscribe"])
    memory = MemoryClient(
        base_url="http://platform", token=token, transport=ASGITransport(app=platform_app)
    )
    sub = await memory.subscribe_signals(["LOW_CONSUMABLE"])
    assert "error" not in sub

    data = await memory.list_signals()
    assert len(data["signals"]) == 1
    suggestions = await build_suggestions(data["signals"])
    assert "洗衣液" in suggestions[0].text
    assert "吗" in suggestions[0].text  # 只建议不执行

    # ack 后不再投递
    ack = await memory.ack_signal(suggestions[0].signal_id)
    assert ack["status"] == "ACKED"
    data = await memory.list_signals()
    assert data["signals"] == []
    await memory.aclose()


async def test_agent_reply_reaches_real_platform_device_inbox(db_session):
    (
        _,
        AssistantTurn,
        FakeChatLLM,
        _,
        MemoryClient,
        _,
        create_gateway_app,
    ) = _load_gateway()

    household_id = await get_default_household_id(db_session)
    glasses = Device(
        household_id=household_id,
        kind="glasses",
        name="RealGit RV101 E2E",
        runtime_package="com.realitymemory.glasses",
        control_transport="inbox",
    )
    db_session.add(glasses)
    await db_session.commit()

    platform_app = create_app(fake_llm=FakeLLMClient(), with_workers=False)
    token = await _issue_grant(
        platform_app,
        ["memory.query.objects", "memory.device.message.send"],
    )
    memory = MemoryClient(
        base_url="http://platform",
        token=token,
        transport=ASGITransport(app=platform_app),
    )
    gateway_app = create_gateway_app(
        fake_llm=FakeChatLLM(
            script=[AssistantTurn(content="钥匙最后一次看到是在玄关柜。")]
        ),
        memory_client=memory,
    )

    async with AsyncClient(
        transport=ASGITransport(app=gateway_app), base_url="http://gateway"
    ) as gateway:
        response = await gateway.post(
            "/v1/chat",
            json={
                "message": "钥匙在哪里？",
                "delivery": {"device_id": str(glasses.id)},
            },
        )
    assert response.status_code == 200, response.text
    delivered = response.json()["delivery"]
    assert delivered["status"] == "QUEUED"
    assert delivered["transport"] == "inbox"

    async with AsyncClient(
        transport=ASGITransport(app=platform_app), base_url="http://platform"
    ) as platform:
        inbox = await platform.get(f"/internal/v1/devices/{glasses.id}/inbox")
        assert inbox.status_code == 200
        messages = inbox.json()["messages"]
        assert len(messages) == 1
        message = messages[0]
        assert message["message_id"] == delivered["message_id"]
        assert message["payload"]["presentation"]["intent"] == "ANSWER"
        assert message["payload"]["presentation"]["title"] == "钥匙最后一次看到是在玄关柜。"
        assert message["payload"]["source"]["kind"] == "AGENT_REPLY"
