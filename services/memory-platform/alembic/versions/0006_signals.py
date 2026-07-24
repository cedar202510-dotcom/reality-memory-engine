"""memory_signals + signal_subscriptions：主动式 Signal（M4）

Revision ID: 0006_signals
Create Date: 2026-07-25 12:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006_signals"
down_revision = "0005_agent_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, comment="主键"),
        sa.Column("household_id", UUID(as_uuid=True), sa.ForeignKey("households.id"), nullable=False, comment="所属家庭（投递按家庭隔离）"),
        sa.Column("signal_type", sa.String(64), nullable=False, comment="LOW_CONSUMABLE / STALE_LOCATION"),
        sa.Column("entity_id", UUID(as_uuid=True), sa.ForeignKey("entities.id"), nullable=True, comment="关联实体"),
        sa.Column("payload", JSONB, nullable=False, server_default="{}", comment="信号内容（结构化，供 Agent 措辞）"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5", comment="信号置信度"),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING", comment="PENDING/DELIVERED/ACKED/EXPIRED"),
        sa.Column("cooldown_key", sa.String(256), nullable=False, comment="去重键（signal_type:entity_id）"),
        sa.Column("delivered_subscription_id", UUID(as_uuid=True), nullable=True, comment="投递到的订阅"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, comment="过期不投递（§13）"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_signals_status", "memory_signals", ["status"])
    op.create_index("ix_signals_cooldown", "memory_signals", ["cooldown_key", "created_at"])

    op.create_table(
        "signal_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, comment="主键"),
        sa.Column("grant_id", UUID(as_uuid=True), nullable=True, comment="所属 AgentGrant（owner 直订为空）"),
        sa.Column("household_id", UUID(as_uuid=True), sa.ForeignKey("households.id"), nullable=False, comment="订阅的家庭范围"),
        sa.Column("signal_types", JSONB, nullable=False, server_default="[]", comment="允许的信号类型"),
        sa.Column("min_confidence", sa.Float, nullable=False, server_default="0", comment="最低置信度"),
        sa.Column("cooldown_seconds", sa.Integer, nullable=False, server_default="3600", comment="同一 cooldown_key 投递最小间隔"),
        sa.Column("daily_cap", sa.Integer, nullable=False, server_default="10", comment="每日投递上限"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, comment="订阅过期时间"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True, comment="撤销时间"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("signal_subscriptions")
    op.drop_index("ix_signals_cooldown", table_name="memory_signals")
    op.drop_index("ix_signals_status", table_name="memory_signals")
    op.drop_table("memory_signals")
