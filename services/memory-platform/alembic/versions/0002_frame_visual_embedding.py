"""frame_assets 增加 CLIP 视觉向量列

Revision ID: 0002_frame_visual_embedding
Create Date: 2026-01-02 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0002_frame_visual_embedding"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

VISUAL_EMBEDDING_DIM = 512


def upgrade() -> None:
    op.add_column(
        "frame_assets",
        sa.Column(
            "visual_embedding",
            Vector(VISUAL_EMBEDDING_DIM),
            nullable=True,
            comment="CLIP 图像向量（媒体删除后仍可用于视觉检索）",
        ),
    )


def downgrade() -> None:
    op.drop_column("frame_assets", "visual_embedding")
