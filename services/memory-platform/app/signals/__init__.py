"""Signal API：订阅管理 + 投递 + ack（§4.2）。

投递语义（§13）：过期信号懒惰标记 EXPIRED、绝不投递；冷却与每日上限在读取时
按订阅约束抑制（suppressed 计数返回，抑制不是丢失）；grant 撤销 → 401 自动停投。
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import GrantContext, actor_of, grant_or_owner
from ..db import get_session
from ..memory.events import record_audit
from ..memory.seed import get_default_household_id
from ..models import MemorySignal, SignalSubscription, utcnow
from ..schemas import (
    SignalListResponse,
    SignalOut,
    SignalSubscriptionCreateRequest,
    SignalSubscriptionOut,
)

router = APIRouter(prefix="/v1", tags=["signals"])


async def _household_of(session: AsyncSession, ctx: GrantContext | None) -> uuid.UUID:
    if ctx is not None:
        return ctx.household_id()
    return await get_default_household_id(session)


@router.post("/signal-subscriptions", response_model=SignalSubscriptionOut)
async def create_subscription_endpoint(
    req: SignalSubscriptionCreateRequest,
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.signal.subscribe")),
) -> SignalSubscriptionOut:
    household_id = await _household_of(session, ctx)
    sub = SignalSubscription(
        grant_id=ctx.grant_id if ctx else None,
        household_id=household_id,
        signal_types=req.signal_types,
        min_confidence=req.min_confidence,
        cooldown_seconds=req.cooldown_seconds,
        daily_cap=req.daily_cap,
        expires_at=utcnow() + timedelta(days=req.ttl_days),
    )
    session.add(sub)
    await session.flush()
    await record_audit(
        session,
        actor=actor_of(ctx),
        action="signal_subscribe",
        target=f"subscription:{sub.id}",
        detail={"signal_types": req.signal_types, "daily_cap": req.daily_cap},
    )
    await session.commit()
    return SignalSubscriptionOut.model_validate(sub)


@router.delete("/signal-subscriptions/{subscription_id}", response_model=SignalSubscriptionOut)
async def revoke_subscription_endpoint(
    subscription_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.signal.subscribe")),
) -> SignalSubscriptionOut:
    sub = await session.get(SignalSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    if ctx is not None and sub.grant_id != ctx.grant_id:
        raise HTTPException(status_code=404, detail="订阅不存在")  # 不泄露他人订阅
    if sub.revoked_at is None:
        sub.revoked_at = utcnow()
        await record_audit(
            session,
            actor=actor_of(ctx),
            action="signal_unsubscribe",
            target=f"subscription:{sub.id}",
            detail={},
        )
        await session.commit()
    return SignalSubscriptionOut.model_validate(sub)


async def _expire_stale(session: AsyncSession, household_id: uuid.UUID) -> None:
    """懒惰过期：读取时把过期未终态信号标记 EXPIRED（不投递迟到提醒）。"""
    stale = (
        await session.scalars(
            select(MemorySignal).where(
                MemorySignal.household_id == household_id,
                MemorySignal.status.in_(("PENDING", "DELIVERED")),
                MemorySignal.expires_at <= utcnow(),
            )
        )
    ).all()
    for s in stale:
        s.status = "EXPIRED"


@router.get("/signals", response_model=SignalListResponse)
async def list_signals_endpoint(
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.signal.subscribe")),
) -> SignalListResponse:
    """拉取待投递信号。agent：按其 grant 的有效订阅过滤并计投递；owner：全量查看（调试）。"""
    household_id = await _household_of(session, ctx)
    await _expire_stale(session, household_id)

    pending = list(
        (
            await session.scalars(
                select(MemorySignal)
                .where(
                    MemorySignal.household_id == household_id,
                    MemorySignal.status == "PENDING",
                )
                .order_by(MemorySignal.created_at.asc())
            )
        ).all()
    )

    if ctx is None:
        await session.commit()
        return SignalListResponse(signals=[SignalOut.model_validate(s) for s in pending])

    sub = await session.scalar(
        select(SignalSubscription)
        .where(
            SignalSubscription.grant_id == ctx.grant_id,
            SignalSubscription.revoked_at.is_(None),
            SignalSubscription.expires_at > utcnow(),
        )
        .order_by(SignalSubscription.created_at.desc())
        .limit(1)
    )
    if sub is None:
        await session.commit()
        raise HTTPException(status_code=404, detail="没有有效的信号订阅，请先 POST /v1/signal-subscriptions")

    # 每日上限：今天已投递给该订阅的数量
    today_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    delivered_today = (
        await session.scalar(
            select(func.count(MemorySignal.id)).where(
                MemorySignal.delivered_subscription_id == sub.id,
                MemorySignal.delivered_at >= today_start,
            )
        )
    ) or 0

    deliver: list[MemorySignal] = []
    suppressed = 0
    for sig in pending:
        if sig.signal_type not in (sub.signal_types or []):
            continue  # 未订阅类型：不算抑制，留给其它订阅
        if sig.confidence < sub.min_confidence:
            suppressed += 1
            continue
        if delivered_today + len(deliver) >= sub.daily_cap:
            suppressed += 1
            continue
        # 订阅级冷却：同 cooldown_key 距上次投递不足 cooldown_seconds → 抑制
        last_delivered = await session.scalar(
            select(MemorySignal.delivered_at)
            .where(
                MemorySignal.cooldown_key == sig.cooldown_key,
                MemorySignal.delivered_subscription_id == sub.id,
                MemorySignal.delivered_at.is_not(None),
            )
            .order_by(MemorySignal.delivered_at.desc())
            .limit(1)
        )
        if last_delivered is not None and (
            utcnow() - last_delivered
        ).total_seconds() < sub.cooldown_seconds:
            suppressed += 1
            continue
        deliver.append(sig)

    for sig in deliver:
        sig.status = "DELIVERED"
        sig.delivered_at = utcnow()
        sig.delivered_subscription_id = sub.id
    await record_audit(
        session,
        actor=ctx.actor,
        action="signal_deliver",
        target=f"subscription:{sub.id}",
        detail={"n_delivered": len(deliver), "n_suppressed": suppressed, "grant_id": str(ctx.grant_id)},
    )
    await session.commit()
    return SignalListResponse(
        signals=[SignalOut.model_validate(s) for s in deliver], suppressed=suppressed
    )


@router.post("/signals/{signal_id}/ack", response_model=SignalOut)
async def ack_signal_endpoint(
    signal_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    ctx: GrantContext | None = Depends(grant_or_owner("memory.signal.subscribe")),
) -> SignalOut:
    sig = await session.get(MemorySignal, signal_id)
    if sig is None:
        raise HTTPException(status_code=404, detail="信号不存在")
    if ctx is not None:
        ctx.require_household(sig.household_id)
    if sig.status in ("PENDING", "DELIVERED"):
        sig.status = "ACKED"
        sig.acked_at = utcnow()
        await session.commit()
    return SignalOut.model_validate(sig)
