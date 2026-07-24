"""启动 seed：默认家庭 + owner + 默认设备（v0 单租户简化）。"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Actor, Device, Household

DEFAULT_HOUSEHOLD_NAME = "默认家庭"


async def ensure_seed(session: AsyncSession) -> uuid.UUID:
    """确保默认家庭/owner/设备存在，返回 household_id。"""
    household = await session.scalar(
        select(Household).where(Household.name == DEFAULT_HOUSEHOLD_NAME)
    )
    if household is None:
        household = Household(name=DEFAULT_HOUSEHOLD_NAME)
        session.add(household)
        await session.flush()
        session.add(Actor(household_id=household.id, role="owner"))
        session.add(Device(household_id=household.id, kind="phone", name="默认采集设备"))
        await session.commit()
    return household.id


async def get_default_household_id(session: AsyncSession) -> uuid.UUID:
    household = await session.scalar(
        select(Household).where(Household.name == DEFAULT_HOUSEHOLD_NAME)
    )
    if household is None:
        return await ensure_seed(session)
    return household.id
