"""entities 增加实例代表视觉向量（物体级合并）

Revision ID: 0004_entity_visual_embedding
Create Date: 2026-07-24 22:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0004_entity_visual_embedding"
down_revision = "0003_audio_assets"
branch_labels = None
depends_on = None

VISUAL_EMBEDDING_DIM = 512


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column(
            "visual_embedding",
            Vector(VISUAL_EMBEDDING_DIM),
            nullable=True,
            comment="实例代表视觉向量（成员帧 CLIP 向量的滑动平均，物体级合并用）",
        ),
    )
    op.add_column(
        "entities",
        sa.Column(
            "visual_embedding_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="visual_embedding 滑动平均的样本数",
        ),
    )


def downgrade() -> None:
    op.drop_column("entities", "visual_embedding_count")
    op.drop_column("entities", "visual_embedding")
