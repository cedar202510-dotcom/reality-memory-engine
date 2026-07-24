"""audio_assets 表 + atomic_observations 支持语音来源

Revision ID: 0003_audio_assets
Create Date: 2026-01-03 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0003_audio_assets"
down_revision = "0002_frame_visual_embedding"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1024


def upgrade() -> None:
    op.create_table(
        "audio_assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "evidence_item_id",
            UUID(as_uuid=True),
            sa.ForeignKey("evidence_items.id"),
            nullable=False,
            unique=True,
            comment="来源证据",
        ),
        sa.Column("transcript", sa.Text, nullable=False, comment="ASR 全文转写"),
        sa.Column("segments", JSONB, nullable=False, comment="分段转写 [{start,end,text,speaker?}]"),
        sa.Column("language", sa.String(16), nullable=True, comment="识别语言"),
        sa.Column("duration_seconds", sa.Float, nullable=True, comment="音频时长（秒）"),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True, comment="转写文本向量"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, comment="录制时间"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "atomic_observations",
        sa.Column(
            "audio_asset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("audio_assets.id"),
            nullable=True,
            comment="来源语音资产（与 frame_asset_id 二选一）",
        ),
    )
    op.alter_column("atomic_observations", "frame_asset_id", nullable=True)


def downgrade() -> None:
    op.alter_column("atomic_observations", "frame_asset_id", nullable=False)
    op.drop_column("atomic_observations", "audio_asset_id")
    op.drop_table("audio_assets")
