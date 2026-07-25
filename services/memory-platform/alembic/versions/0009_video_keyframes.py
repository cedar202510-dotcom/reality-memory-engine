"""evidence_items 支持视频抽帧：父子关系 + 时间偏移

视频抽出来的关键帧要变成能走既有帧流水线的一等证据（caption/CLIP/观察都免费复用），
但又必须能追溯回源视频——否则媒体库里会平白多出 N 张来路不明的图，
而且「这两帧来自同一段视频的第 3 秒和第 8 秒」这种停留时长信息会彻底丢失，
喜好度里的「视觉注意力」通道就无从算起。

Revision ID: 0009_video_keyframes
Create Date: 2026-07-25 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0009_video_keyframes"
down_revision = "0008_device_control_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evidence_items",
        sa.Column(
            "parent_evidence_item_id",
            UUID(as_uuid=True),
            sa.ForeignKey("evidence_items.id"),
            nullable=True,
            comment="源证据（视频关键帧指回源视频；顶层证据为空）",
        ),
    )
    op.add_column(
        "evidence_items",
        sa.Column(
            "offset_seconds",
            sa.Float,
            nullable=True,
            comment="相对源证据起点的偏移秒数（视频关键帧）",
        ),
    )
    op.create_index(
        "ix_evidence_parent", "evidence_items", ["parent_evidence_item_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_parent", table_name="evidence_items")
    op.drop_column("evidence_items", "offset_seconds")
    op.drop_column("evidence_items", "parent_evidence_item_id")
