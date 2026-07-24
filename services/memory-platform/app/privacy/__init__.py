"""Privacy API：forget-recent / 审计查询。

Agent 访问：forget-recent 需 memory.forget.submit；audit 需 memory.audit.self.read
且只能看到自己（actor=agent:<client_id>）的记录（§10 "self"语义）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import GrantContext, actor_of, grant_or_owner
from ..db import get_session
from ..models import AuditRecord
from ..schemas import AuditRecordOut, ForgetRecentRequest, ForgetRecentResponse
from .deletion import execute_forget_recent

router = APIRouter(prefix="/v1/memory", tags=["privacy"])


@router.post("/forget-recent", response_model=ForgetRecentResponse)
async def forget_recent_endpoint(
    req: ForgetRecentRequest,
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.forget.submit")),
) -> ForgetRecentResponse:
    request, jobs, tombstone = await execute_forget_recent(
        session, minutes=req.minutes, scope=req.scope, actor=actor_of(ctx)
    )
    return ForgetRecentResponse(
        request_id=request.id,
        status=request.status,
        jobs=[
            {"subsystem": j.subsystem, "status": j.status, "last_error": j.last_error}
            for j in jobs
        ],
        tombstone_id=tombstone.id,
    )


@router.get("/audit", response_model=list[AuditRecordOut])
async def audit_endpoint(
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.audit.self.read")),
) -> list[AuditRecordOut]:
    stmt = select(AuditRecord).order_by(AuditRecord.created_at.desc()).limit(limit)
    if ctx is not None:
        stmt = stmt.where(AuditRecord.actor == ctx.actor)  # agent 只能看自己的调用记录
    rows = (await session.scalars(stmt)).all()
    return [AuditRecordOut.model_validate(r) for r in rows]
