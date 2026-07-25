"""device_messages + device_delivery_receipts：云端下行通道（通信架构 §5）

Revision ID: 0007_device_messages
Create Date: 2026-07-25 18:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0007_device_messages"
down_revision = "0006_signals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, comment="主键，即对外 message_id"),
        sa.Column("household_id", UUID(as_uuid=True), sa.ForeignKey("households.id"), nullable=False, comment="所属家庭（下行按家庭隔离）"),
        sa.Column("target_device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=False, comment="目标设备"),
        sa.Column("message_type", sa.String(64), nullable=False, comment="REMINDER_SIGNAL/POLICY_UPDATE/PRIVACY_PAUSE/CAPTURE_BUDGET_UPDATE/DIAGNOSTIC"),
        sa.Column("payload_schema_ref", sa.String(128), nullable=False, server_default="rme.reminder-signal.draft", comment="载荷版本（业务字段待 review）"),
        sa.Column("payload", JSONB, nullable=False, server_default="{}", comment="业务载荷，字段尚未冻结"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="NORMAL", comment="LOW/NORMAL/HIGH"),
        sa.Column("allow_text", sa.Boolean, nullable=False, server_default=sa.true(), comment="delivery_policy：允许文字呈现"),
        sa.Column("allow_tts", sa.Boolean, nullable=False, server_default=sa.false(), comment="delivery_policy：允许 TTS 播报"),
        sa.Column("signal_id", UUID(as_uuid=True), sa.ForeignKey("memory_signals.id"), nullable=True, comment="来源信号（手动注入为空）"),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING", comment="PENDING/SENT/RECEIVED/CLOSED/EXPIRED"),
        sa.Column("last_receipt_status", sa.String(32), nullable=True, comment="最近一次回执状态"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, comment="过期不投递、不播报（§5.4）"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("presented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("spoken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_device_messages_pending", "device_messages", ["target_device_id", "status"]
    )

    op.create_table(
        "device_delivery_receipts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, comment="主键"),
        sa.Column("message_id", UUID(as_uuid=True), sa.ForeignKey("device_messages.id", ondelete="CASCADE"), nullable=False, comment="对应下行消息"),
        sa.Column("status", sa.String(32), nullable=False, comment="RECEIVED/PRESENTED/SPOKEN/DISMISSED/EXPIRED/FAILED"),
        sa.Column("detail", JSONB, nullable=False, server_default="{}", comment="失败原因等附加信息"),
        sa.Column("device_reported_at", sa.DateTime(timezone=True), nullable=True, comment="设备本地上报时间"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), comment="服务端接收时间"),
        sa.UniqueConstraint("message_id", "status", name="uq_receipt_message_status"),
    )


def downgrade() -> None:
    op.drop_table("device_delivery_receipts")
    op.drop_index("ix_device_messages_pending", table_name="device_messages")
    op.drop_table("device_messages")
