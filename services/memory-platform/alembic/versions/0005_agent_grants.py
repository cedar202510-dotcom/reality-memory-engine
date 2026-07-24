"""agent_grants 表：Agent 授权（Agent Access Phase 1）

Revision ID: 0005_agent_grants
Create Date: 2026-07-25 10:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0005_agent_grants"
down_revision = "0004_entity_visual_embedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_grants",
        sa.Column("grant_id", UUID(as_uuid=True), primary_key=True, comment="授权 id"),
        sa.Column("owner_id", UUID(as_uuid=True), nullable=False, comment="授权用户（对应 actors.id，弱引用）"),
        sa.Column("agent_client_id", sa.String(128), nullable=False, comment="Agent Client 标识，如 proactive-agent-demo"),
        sa.Column("scopes", JSONB, nullable=False, server_default="[]", comment="授权 scope 列表（§10）"),
        sa.Column("household_ids", JSONB, nullable=False, server_default="[]", comment="可访问家庭 id 列表（uuid 字符串）"),
        sa.Column("allowed_entity_types", JSONB, nullable=True, comment="允许的实体类型（可空=不限制）"),
        sa.Column("purpose", sa.String(256), nullable=False, server_default="", comment="用途说明"),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True, comment="opaque bearer token 的 sha256（绝不存原文）"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="签发时间"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, comment="过期时间"),
        sa.Column("revocable", sa.Boolean(), nullable=False, server_default=sa.true(), comment="是否可撤销"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True, comment="撤销时间（未撤销为空）"),
    )


def downgrade() -> None:
    op.drop_table("agent_grants")
