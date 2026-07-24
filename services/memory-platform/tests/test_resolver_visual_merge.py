"""实体解析器的视觉辅助物体级合并测试。

构造 512 维可控向量验证四条规则：
1. 视觉高相似 + 名称过低门槛 → 合并（"黑色智能手机"并入"智能手机"，记别名）
2. 视觉不相似 → 不合并（保守新建）
3. 视觉高相似但名称完全无关 → 不合并（同帧异物防护）
4. 合并/新建时滑动平均维护实例代表视觉向量
"""
from __future__ import annotations

import math

import pytest

from app.memory.resolver import resolve_entity
from app.memory.seed import get_default_household_id
from app.models import Entity

DIM = 512


def _vec(*pairs: tuple[int, float]) -> list[float]:
    v = [0.0] * DIM
    for i, val in pairs:
        v[i] = val
    return v


# base 与 similar 的 cosine = 0.9；orth 与 base 正交
BASE = _vec((0, 1.0))
SIMILAR = _vec((0, 0.9), (1, math.sqrt(0.19)))
ORTH = _vec((1, 1.0))


async def _mk_entity(session, household_id, name: str, vec: list[float]) -> Entity:
    e = Entity(
        household_id=household_id,
        canonical_name=name,
        visual_embedding=list(vec),
        visual_embedding_count=1,
    )
    session.add(e)
    await session.flush()
    return e


@pytest.mark.asyncio
async def test_visual_merge_same_instance(db_session):
    """视觉高相似 + 名称相关 → 合并，别名记录新叫法。"""
    hid = await get_default_household_id(db_session)
    phone = await _mk_entity(db_session, hid, "智能手机", BASE)

    entity, created = await resolve_entity(
        db_session, household_id=hid, name="黑色智能手机", frame_visual_embedding=SIMILAR
    )
    assert not created
    assert entity.id == phone.id
    assert "黑色智能手机" in entity.aliases


@pytest.mark.asyncio
async def test_no_merge_when_visually_different(db_session):
    """视觉不相似 → 保守新建。"""
    hid = await get_default_household_id(db_session)
    await _mk_entity(db_session, hid, "智能手机", BASE)

    entity, created = await resolve_entity(
        db_session, household_id=hid, name="黑色智能手机", frame_visual_embedding=ORTH
    )
    assert created
    assert entity.canonical_name == "黑色智能手机"


@pytest.mark.asyncio
async def test_no_merge_same_frame_different_object(db_session):
    """同帧异物防护：视觉完全一致（同一帧）但名称无关 → 不合并。"""
    hid = await get_default_household_id(db_session)
    await _mk_entity(db_session, hid, "智能手机", BASE)

    entity, created = await resolve_entity(
        db_session, household_id=hid, name="水杯", frame_visual_embedding=list(BASE)
    )
    assert created
    assert entity.canonical_name == "水杯"


@pytest.mark.asyncio
async def test_visual_average_updated_on_match(db_session):
    """匹配合并时滑动平均更新代表向量；新建时初始化为帧向量。"""
    hid = await get_default_household_id(db_session)
    phone = await _mk_entity(db_session, hid, "智能手机", BASE)

    entity, _ = await resolve_entity(
        db_session, household_id=hid, name="智能手机", frame_visual_embedding=ORTH
    )
    assert entity.visual_embedding_count == 2
    assert abs(entity.visual_embedding[0] - 0.5) < 1e-6
    assert abs(entity.visual_embedding[1] - 0.5) < 1e-6

    entity2, created = await resolve_entity(
        db_session, household_id=hid, name="钥匙", frame_visual_embedding=ORTH
    )
    assert created
    assert entity2.visual_embedding_count == 1
    assert entity2.visual_embedding[1] == 1.0


@pytest.mark.asyncio
async def test_no_visual_vector_keeps_legacy_behavior(db_session):
    """不带视觉向量时行为与旧版一致（名称弱相似不合并）。"""
    hid = await get_default_household_id(db_session)
    await _mk_entity(db_session, hid, "智能手机", BASE)

    entity, created = await resolve_entity(
        db_session, household_id=hid, name="黑色智能手机", frame_visual_embedding=None
    )
    assert created
