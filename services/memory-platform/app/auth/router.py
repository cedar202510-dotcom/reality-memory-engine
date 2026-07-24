"""grants 管理端点：签发/列出/撤销（owner 侧操作，admin token 保护）。

Phase 1 单用户简化：管理凭证是环境变量 ADMIN_TOKEN；未配置时端点 503，
避免"忘了配就是裸奔"。Agent 侧鉴权（bearer grant token）在 __init__.py。
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..memory.events import record_audit
from ..memory.seed import get_default_household_id
from ..models import Actor, AgentGrant, utcnow
from ..schemas import AgentGrantCreateRequest, AgentGrantCreateResponse, AgentGrantOut
from . import SCOPES_V1, create_grant

router = APIRouter(prefix="/v1/agent/grants", tags=["agent-grants"])


def require_admin(request: Request) -> None:
    settings = get_settings()
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="未配置 ADMIN_TOKEN，grants 管理端点不可用")
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {settings.admin_token}":
        raise HTTPException(
            status_code=401,
            detail="需要 owner 管理凭证（Authorization: Bearer <ADMIN_TOKEN>）",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("", response_model=AgentGrantCreateResponse, dependencies=[Depends(require_admin)])
async def create_grant_endpoint(
    req: AgentGrantCreateRequest, session: AsyncSession = Depends(get_session)
) -> AgentGrantCreateResponse:
    unknown = [s for s in req.scopes if s not in SCOPES_V1]
    if unknown:
        raise HTTPException(status_code=422, detail=f"未知 scope：{unknown}")
    household_id = await get_default_household_id(session)
    owner = await session.scalar(
        select(Actor).where(Actor.household_id == household_id, Actor.role == "owner")
    )
    grant, raw_token = await create_grant(
        session,
        owner_id=owner.id if owner else household_id,
        agent_client_id=req.agent_client_id,
        scopes=req.scopes,
        household_ids=[household_id],
        purpose=req.purpose,
        expires_at=utcnow() + timedelta(days=req.ttl_days),
        allowed_entity_types=req.allowed_entity_types,
    )
    await record_audit(
        session,
        actor="user:owner",
        action="grant_issued",
        target=f"grant:{grant.grant_id}",
        detail={"agent_client_id": req.agent_client_id, "scopes": req.scopes},
    )
    await session.commit()
    return AgentGrantCreateResponse(grant=AgentGrantOut.model_validate(grant), token=raw_token)


@router.get("", response_model=list[AgentGrantOut], dependencies=[Depends(require_admin)])
async def list_grants_endpoint(
    session: AsyncSession = Depends(get_session),
) -> list[AgentGrantOut]:
    rows = (
        await session.scalars(select(AgentGrant).order_by(AgentGrant.issued_at.desc()))
    ).all()
    return [AgentGrantOut.model_validate(r) for r in rows]


@router.delete("/{grant_id}", response_model=AgentGrantOut, dependencies=[Depends(require_admin)])
async def revoke_grant_endpoint(
    grant_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> AgentGrantOut:
    grant = await session.get(AgentGrant, grant_id)
    if grant is None:
        raise HTTPException(status_code=404, detail="grant 不存在")
    if not grant.revocable:
        raise HTTPException(status_code=409, detail="该 grant 不可撤销")
    if grant.revoked_at is None:
        grant.revoked_at = utcnow()
        await record_audit(
            session,
            actor="user:owner",
            action="grant_revoked",
            target=f"grant:{grant.grant_id}",
            detail={"agent_client_id": grant.agent_client_id},
        )
        await session.commit()
    return AgentGrantOut.model_validate(grant)
