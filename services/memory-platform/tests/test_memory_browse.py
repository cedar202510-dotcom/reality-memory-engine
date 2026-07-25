"""记忆浏览读侧：事件流、按位置聚类的物品分布、线索确认中心。

这三个端点撑起前端的「上下文」「全览」「线索确认」三个页面。它们全部确定性、
不经 LLM——同一份数据查两次必须一样，这是「记忆可信」的最低要求。
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.llm.fake import FakeLLMClient
from app.main import create_app
from app.memory.events import append_event
from app.memory.projections import recompute_projection
from app.memory.seed import get_default_household_id
from app.models import Entity, MemoryCandidate, MemoryEvent, utcnow

CONF = {"model": 0.9, "identity": 0.9, "spatial": 0.9, "temporal": 0.9, "policy": 1.0, "aggregate": 0.9}
# 刚好卡在默认阈值 0.85 之下：这就是线索确认中心里那批候选的真实分布
CONF_UNDER_GATE = {**CONF, "aggregate": 0.8}


def _app():
    return create_app(fake_llm=FakeLLMClient(), with_workers=False)


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _entity(db_session, name: str) -> Entity:
    household_id = await get_default_household_id(db_session)
    entity = Entity(household_id=household_id, canonical_name=name, aliases=[])
    db_session.add(entity)
    # 必须 commit：端点走自己的 session，只 flush 的话它看不见这个实体
    await db_session.commit()
    return entity


async def _observed(db_session, entity: Entity, location: str, *, minutes_ago: int = 0) -> MemoryEvent:
    when = utcnow() - timedelta(minutes=minutes_ago)
    event = await append_event(
        db_session,
        entity_id=entity.id,
        event_type="OBJECT_OBSERVED_AT",
        payload={"location": location},
        event_time_from=when,
        observed_at=when,
        ingested_at=when,
        confidence=CONF,
    )
    await db_session.commit()
    await recompute_projection(db_session, entity_id=entity.id)
    return event


async def _candidate(db_session, payload: dict, *, confidence=None, status="PENDING") -> MemoryCandidate:
    c = MemoryCandidate(
        observation_ids=[],
        event_type="OBJECT_OBSERVED_AT",
        payload=payload,
        confidence=confidence or CONF_UNDER_GATE,
        status=status,
    )
    db_session.add(c)
    await db_session.flush()
    await db_session.commit()
    return c


# ---------------------------------------------------------------- 事件流


@pytest.mark.asyncio
async def test_recent_events_names_the_entity_and_lifts_location(db_session):
    """事件流要自带实体名和位置——界面不该为了显示一行字再去查 25 次实体。"""
    phone = await _entity(db_session, "手机")
    await _observed(db_session, phone, "办公桌")

    async with _client(_app()) as client:
        resp = await client.get("/v1/memory/events/recent")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    entry = body["events"][0]
    assert entry["entity_name"] == "手机"
    assert entry["location"] == "办公桌"
    assert entry["confidence"] == pytest.approx(0.9)
    assert entry["superseded"] is False
    assert entry["user_confirmed"] is False


@pytest.mark.asyncio
async def test_recent_events_marks_superseded_and_reads_correction_location(db_session):
    """纠正过的记忆：旧事件要标 superseded，新事件的位置在 payload.value 而不是 location。

    两件事都不能省。不标 superseded，界面会同时摆出「办公桌」和「抽屉里」两个位置；
    不特判 USER_CORRECTION 的 payload 形状，纠正那条会显示成「没有位置信息」——
    正好是用户刚刚亲手告诉系统的那个位置。
    """
    keys = await _entity(db_session, "钥匙")
    old = await _observed(db_session, keys, "办公桌", minutes_ago=30)

    async with _client(_app()) as client:
        resp = await client.post(
            "/v1/memory/correct",
            json={"entity_id": str(keys.id), "field": "location", "value": "抽屉里", "reason": "我放进去了"},
        )
        assert resp.status_code == 200
        events = (await client.get("/v1/memory/events/recent")).json()["events"]

    by_id = {e["event_id"]: e for e in events}
    assert by_id[str(old.id)]["superseded"] is True

    correction = next(e for e in events if e["event_type"] == "USER_CORRECTION")
    assert correction["location"] == "抽屉里"
    assert correction["user_confirmed"] is True


@pytest.mark.asyncio
async def test_recent_events_never_resurfaces_forgotten_memories(db_session):
    """被遗忘的记忆不能重新出现在流里。

    valid_to 有两个来源：被后续事件取代（旧事实，要显示并标记）和被 forget-recent
    遗忘（用户明确要求它消失）。只看 valid_to 会把两者混成一件事，等于在界面上
    撤销一次隐私操作——比文案标错严重得多。
    """
    cup = await _entity(db_session, "水杯")
    await _observed(db_session, cup, "茶几")

    async with _client(_app()) as client:
        before = (await client.get("/v1/memory/events/recent")).json()
        assert before["total"] == 1

        forget = await client.post(
            "/v1/memory/forget-recent", json={"minutes": 60, "scope": ["event", "projection"]}
        )
        assert forget.status_code == 200

        after = (await client.get("/v1/memory/events/recent")).json()

    assert after["total"] == 0
    assert after["events"] == []
    # 事件本身还在库里（遗忘不改历史，只关闭语义有效期）——只是不再对外呈现
    assert len((await db_session.scalars(select(MemoryEvent))).all()) == 1


# ---------------------------------------------------------------- 物品分布


@pytest.mark.asyncio
async def test_objects_groups_only_locations_holding_more_than_one_thing(db_session):
    """分组是「放在一起」的意思，所以只有 2 件以上才成组。

    单件物品自成一组的话，全览里会挂满一堆只有一个节点的孤环——既没有信息量，
    又把真正有意义的聚集（办公桌上那 6 件）淹没了。
    """
    for name in ("手机", "键盘", "纸巾"):
        await _observed(db_session, await _entity(db_session, name), "办公桌")
    await _observed(db_session, await _entity(db_session, "雨伞"), "玄关")
    lonely = await _entity(db_session, "没见过的东西")  # 有实体但没有事件 → 没有位置

    async with _client(_app()) as client:
        body = (await client.get("/v1/memory/objects")).json()

    assert body["total"] == 5
    groups = {g["location"]: g["entity_ids"] for g in body["groups"]}
    assert set(groups) == {"办公桌"}
    assert len(groups["办公桌"]) == 3

    nodes = {n["canonical_name"]: n for n in body["nodes"]}
    assert nodes["雨伞"]["location"] == "玄关"
    assert nodes["没见过的东西"]["location"] is None
    assert nodes["手机"]["event_count"] == 1
    # 没有位置的排在最后，界面按这个顺序渲染就不用自己再排
    assert body["nodes"][-1]["entity_id"] == str(lonely.id)


@pytest.mark.asyncio
async def test_objects_located_only_drops_unlocated(db_session):
    await _observed(db_session, await _entity(db_session, "手机"), "办公桌")
    await _entity(db_session, "没位置的东西")

    async with _client(_app()) as client:
        body = (await client.get("/v1/memory/objects", params={"located_only": True})).json()

    assert [n["canonical_name"] for n in body["nodes"]] == ["手机"]


# ---------------------------------------------------------------- 线索确认中心


@pytest.mark.asyncio
async def test_clues_hide_candidates_with_nothing_to_confirm(db_session):
    """没有位置的候选不是线索：确认它不会改变任何记忆。

    这类候选大多是 where-is 找不到东西时留下的失败痕迹（payload 只有 object_text）。
    摆进确认中心，用户看到的是一排「充电器 / 位置未知 / 要确认吗？」——点了什么都不会变。
    """
    await _candidate(db_session, {"object_text": "座椅", "location": "桌子旁边"})
    await _candidate(db_session, {"object_text": "充电器"})           # 失败的查询
    await _candidate(db_session, {"object_text": "充电器"})

    async with _client(_app()) as client:
        body = (await client.get("/v1/memory/clues")).json()

    assert body["total"] == 1
    assert [c["object_text"] for c in body["clues"]] == ["座椅"]
    assert body["clues"][0]["confidence"] == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_confirming_a_clue_writes_the_event_the_gate_refused(db_session):
    """用户确认 = 替候选门拍板：绕过阈值升级，并在事件上留下「人确认的」痕迹。"""
    clue = await _candidate(db_session, {"object_text": "键盘", "location": "办公桌"})

    async with _client(_app()) as client:
        resp = await client.post(
            f"/v1/memory/clues/{clue.id}/resolve", json={"decision": "CONFIRM", "reason": "对，就在那"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ACCEPTED"
    assert body["projection"]["location"] == "办公桌"

    await db_session.refresh(clue)
    assert clue.status == "ACCEPTED"
    assert clue.entity_id is not None

    event = await db_session.get(MemoryEvent, uuid.UUID(body["event_id"]))
    assert event.payload["location"] == "办公桌"
    # aggregate 仍是当初那个不够格的分数：确认不篡改模型的置信度，只额外记下「人拍板了」
    assert event.confidence["aggregate"] == pytest.approx(0.8)
    assert event.confidence["user_confirmed"] == 1.0
    assert str(clue.id) in event.source_candidate_ids


@pytest.mark.asyncio
async def test_rejecting_a_clue_writes_no_event(db_session):
    clue = await _candidate(db_session, {"object_text": "调料包", "location": "办公桌"})

    async with _client(_app()) as client:
        resp = await client.post(f"/v1/memory/clues/{clue.id}/resolve", json={"decision": "REJECT"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "REJECTED"
    await db_session.refresh(clue)
    assert clue.status == "REJECTED"
    assert (await db_session.scalars(select(MemoryEvent))).all() == []


@pytest.mark.asyncio
async def test_clue_cannot_be_resolved_twice(db_session):
    """重复确认要明确报错。静默成功会让界面显示「已记住」两次，而记忆只变了一次。"""
    clue = await _candidate(db_session, {"object_text": "纸巾", "location": "办公桌"})

    async with _client(_app()) as client:
        first = await client.post(f"/v1/memory/clues/{clue.id}/resolve", json={"decision": "CONFIRM"})
        second = await client.post(f"/v1/memory/clues/{clue.id}/resolve", json={"decision": "CONFIRM"})

    assert first.status_code == 200
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_confirming_a_locationless_candidate_is_refused(db_session):
    """没有位置就没有可确认的内容——宁可报错，也不要给一个骗人的成功。"""
    clue = await _candidate(db_session, {"object_text": "充电器"})

    async with _client(_app()) as client:
        confirm = await client.post(f"/v1/memory/clues/{clue.id}/resolve", json={"decision": "CONFIRM"})
        reject = await client.post(f"/v1/memory/clues/{clue.id}/resolve", json={"decision": "REJECT"})

    assert confirm.status_code == 422
    assert reject.status_code == 200  # 忽略始终允许：用户想清掉这条痕迹是合理的


@pytest.mark.asyncio
async def test_confirming_one_side_of_a_conflict_settles_the_others(db_session):
    """冲突由人一次裁决完：确认一条，同集里的其它候选一并判否。

    不然它们会永远停在 CONFLICTED，界面反复弹出同一个已经解决的矛盾，
    而用户再点只会拿到 409。
    """
    conflict = uuid.uuid4()
    keep = await _candidate(db_session, {"object_text": "手机", "location": "办公桌"}, status="CONFLICTED")
    drop = await _candidate(db_session, {"object_text": "手机", "location": "床头柜"}, status="CONFLICTED")
    for c in (keep, drop):
        c.conflict_set_id = conflict
    await db_session.commit()

    async with _client(_app()) as client:
        resp = await client.post(f"/v1/memory/clues/{keep.id}/resolve", json={"decision": "CONFIRM"})

    assert resp.status_code == 200
    assert resp.json()["rejected_sibling_ids"] == [str(drop.id)]
    await db_session.refresh(drop)
    assert drop.status == "REJECTED"
