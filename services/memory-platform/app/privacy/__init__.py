"""Privacy API：forget-recent / 审计查询。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import AuditRecord
from ..schemas import AuditRecordOut, ForgetRecentRequest, ForgetRecentResponse
from .deletion import execute_forget_recent

router = APIRouter(prefix="/v1/memory", tags=["privacy"])


@router.post("/forget-recent", response_model=ForgetRecentResponse)
async def forget_recent_endpoint(
    req: ForgetRecentRequest, session: AsyncSession = Depends(get_session)
) -> ForgetRecentResponse:
    request, jobs, tombstone = await execute_forget_recent(
        session, minutes=req.minutes, scope=req.scope
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
) -> list[AuditRecordOut]:
    rows = (
        await session.scalars(
            select(AuditRecord).order_by(AuditRecord.created_at.desc()).limit(limit)
        )
    ).all()
    return [AuditRecordOut.model_validate(r) for r in rows]
