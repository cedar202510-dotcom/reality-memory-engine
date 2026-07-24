"""Agent 授权（AgentGrant）：token 签发/解析 + FastAPI 鉴权依赖（Phase 1）。

- token 是不透明 bearer：`secrets.token_urlsafe(32)`，库里只存 sha256，原始 token 只在创建时返回一次。
- 401：缺 token / 无效 / 过期 / 已撤销；403：token 有效但缺所需 scope。
- 跨家庭访问在鉴权层拒绝：grant.household_ids 是查询侧唯一的家庭来源（§11）。
- 本模块是服务层显式函数，不经过任何模型/LLM 路径（模型永不直写库）。
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..memory.events import record_audit
from ..models import AgentGrant, utcnow

# 首版 scope 全集（设计文档 §10）
SCOPES_V1 = (
    "memory.query.objects",
    "memory.query.consumables",
    "memory.query.preferences",
    "memory.query.tasks",
    "memory.query.activities",
    "memory.timeline.read",
    "memory.signal.subscribe",
    "memory.correction.submit",
    "memory.forget.submit",
    "memory.audit.self.read",
)

DEFAULT_GRANT_TTL_DAYS = 30


def hash_token(token: str) -> str:
    """bearer token 的 sha256（落库值，绝不存原文）。"""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_grant(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    agent_client_id: str,
    scopes: list[str],
    household_ids: list[uuid.UUID],
    purpose: str = "",
    expires_at: datetime | None = None,
    allowed_entity_types: list[str] | None = None,
    revocable: bool = True,
) -> tuple[AgentGrant, str]:
    """创建授权：生成不透明 token，落库哈希，返回 (grant, 原始 token)。

    原始 token 只在此返回值里出现一次，之后无法从库里恢复。
    """
    raw_token = secrets.token_urlsafe(32)
    grant = AgentGrant(
        owner_id=owner_id,
        agent_client_id=agent_client_id,
        scopes=list(scopes),
        household_ids=[str(h) for h in household_ids],
        allowed_entity_types=allowed_entity_types,
        purpose=purpose,
        token_hash=hash_token(raw_token),
        expires_at=expires_at or (utcnow() + timedelta(days=DEFAULT_GRANT_TTL_DAYS)),
        revocable=revocable,
    )
    session.add(grant)
    await session.flush()
    return grant, raw_token


async def resolve_token(session: AsyncSession, token: str) -> AgentGrant | None:
    """token → grant：哈希查找 + 过期 + 撤销检查；任一不满足返回 None（→ 401）。"""
    grant = await session.scalar(
        select(AgentGrant).where(AgentGrant.token_hash == hash_token(token))
    )
    if grant is None:
        return None
    if grant.revoked_at is not None:
        return None
    expires_at = grant.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= utcnow():
        return None
    return grant


def has_scope(grant: AgentGrant, scope: str) -> bool:
    return scope in (grant.scopes or [])


@dataclass
class GrantContext:
    """一次已鉴权调用的上下文：审计 actor 与家庭隔离都从这里取。"""

    grant_id: uuid.UUID
    agent_client_id: str
    owner_id: uuid.UUID
    household_ids: list[uuid.UUID]
    scopes: list[str]

    @property
    def actor(self) -> str:
        """审计操作者：agent:<client_id>（取代旧的硬编码 user:owner）。"""
        return f"agent:{self.agent_client_id}"

    def household_id(self) -> uuid.UUID:
        """Phase 1 简化：一个 grant 只服务一个家庭，取 household_ids 第一个。

        多家庭授权与逐请求家庭选择属于后续阶段；届时这里改为按请求显式选择
        并校验 ∈ household_ids（跨家庭访问必须在鉴权层拒绝）。
        """
        if not self.household_ids:
            raise HTTPException(status_code=403, detail="grant 未绑定任何家庭")
        return self.household_ids[0]

    def require_household(self, household_id: uuid.UUID) -> None:
        """校验目标家庭在授权范围内，否则 404（不泄露资源是否存在）。"""
        if household_id not in self.household_ids:
            raise HTTPException(status_code=404, detail="资源不存在")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def require_scope(ctx: GrantContext, scope: str) -> None:
    """端点内的动态 scope 检查（如统一查询按解析出的 intent 检查）。"""
    if scope not in ctx.scopes:
        raise HTTPException(status_code=403, detail=f"缺少授权 scope：{scope}")


def require_grant(required_scope: str | None = None):
    """FastAPI 依赖工厂：Bearer token → GrantContext。

    required_scope 为 None 时只要求 token 有效（用于 scope 取决于请求体的端点，
    由端点内部用 require_scope 做二次检查）。
    """

    async def dependency(
        request: Request, session: AsyncSession = Depends(get_session)
    ) -> GrantContext:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise _unauthorized("缺少 Authorization: Bearer <token>")
        token = auth[len("Bearer ") :].strip()
        if not token:
            raise _unauthorized("Bearer token 为空")
        grant = await resolve_token(session, token)
        if grant is None:
            raise _unauthorized("token 无效、已过期或已撤销")
        if required_scope is not None and not has_scope(grant, required_scope):
            raise HTTPException(status_code=403, detail=f"缺少授权 scope：{required_scope}")
        return GrantContext(
            grant_id=grant.grant_id,
            agent_client_id=grant.agent_client_id,
            owner_id=grant.owner_id,
            household_ids=[uuid.UUID(str(h)) for h in (grant.household_ids or [])],
            scopes=list(grant.scopes or []),
        )

    return dependency


def grant_or_owner(required_scope: str | None = None):
    """双模式鉴权依赖：请求带 Bearer token → 完整 grant 鉴权（401/403 语义同 require_grant）；
    不带 Authorization 头 → 返回 None，表示 owner 直通（Phase 1 单租户：本机 App/脚本
    与平台同信任域，边界靠部署网络隔离；Agent 必须走 token）。

    带了 token 但无效时必须 401，绝不静默降级为 owner —— 否则撤销失去意义。
    """
    strict = require_grant(required_scope)

    async def dependency(
        request: Request, session: AsyncSession = Depends(get_session)
    ) -> GrantContext | None:
        if "Authorization" not in request.headers:
            return None
        return await strict(request, session)

    return dependency


def actor_of(ctx: GrantContext | None) -> str:
    """审计 actor：agent 调用记 agent:<client_id>，owner 直通记 user:owner。"""
    return ctx.actor if ctx is not None else "user:owner"


async def record_grant_audit(
    session: AsyncSession,
    ctx: GrantContext,
    *,
    action: str,
    target: str,
    detail: dict | None = None,
) -> None:
    """按 §11 记录一次 Agent 调用：哪个 client、哪个 grant、用了哪些 scope。

    不保存完整自然语言查询文本或敏感结构化值（调用方只传 hash/query_id/计数）。
    """
    await record_audit(
        session,
        actor=ctx.actor,
        action=action,
        target=target,
        detail={
            "grant_id": str(ctx.grant_id),
            "agent_client_id": ctx.agent_client_id,
            **(detail or {}),
        },
    )
