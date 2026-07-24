"""开发用 Agent 授权 seed：仅 SEED_DEV_AGENT_GRANT=true 时生效。

为默认家庭创建一个带首版全部 scope 的开发 grant 并打印原始 token（仅创建时一次）。
测试/生产默认关闭，避免静默引入后门 grant。
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..memory.seed import get_default_household_id
from ..models import Actor, AgentGrant
from . import SCOPES_V1, create_grant

logger = logging.getLogger(__name__)

DEV_AGENT_CLIENT_ID = "proactive-agent-demo"


async def ensure_dev_agent_grant(session: AsyncSession) -> str | None:
    """确保开发 grant 存在；新建时返回原始 token（只此一次），已存在返回 None。"""
    existing = await session.scalar(
        select(AgentGrant).where(AgentGrant.agent_client_id == DEV_AGENT_CLIENT_ID)
    )
    if existing is not None:
        return None
    household_id = await get_default_household_id(session)
    owner = await session.scalar(
        select(Actor).where(Actor.household_id == household_id, Actor.role == "owner")
    )
    grant, raw_token = await create_grant(
        session,
        owner_id=owner.id if owner else household_id,
        agent_client_id=DEV_AGENT_CLIENT_ID,
        scopes=list(SCOPES_V1),
        household_ids=[household_id],
        purpose="PERSONAL_ASSISTANCE（开发 seed）",
    )
    await session.commit()
    logger.warning("开发 Agent grant 已创建（grant_id=%s），原始 token 仅本次打印", grant.grant_id)
    return raw_token
