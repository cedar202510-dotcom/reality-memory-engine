"""frame_regions：区域级 CLIP 向量，让小物体在视觉检索里存在

帧级一个向量的物理上限：CLIP 把整图缩到 224，4000px 宽的照片缩放比 ~0.056，
桌上 400px 的身份证只剩 22px，不到一个 32x32 patch——它在帧向量里根本没有信号。
切成重叠子图各编一次向量，检索时按 max 上卷回帧，小物体才第一次可被搜到。

Revision ID: 0010_frame_regions
Create Date: 2026-07-25 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0010_frame_regions"
down_revision = "0009_video_keyframes"
branch_labels = None
depends_on = None

VISUAL_EMBEDDING_DIM = 512


def upgrade() -> None:
    op.create_table(
        "frame_regions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "frame_asset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("frame_assets.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属帧",
        ),
        sa.Column(
            "region_key",
            sa.String(64),
            nullable=False,
            comment="切法的确定性标识（幂等键），如 tile:1500:2,1",
        ),
        sa.Column(
            "source",
            sa.String(16),
            nullable=False,
            server_default="tile",
            comment="区域来源：tile（切片）/ detect（检测框）",
        ),
        sa.Column(
            "bbox",
            JSONB,
            nullable=False,
            server_default="{}",
            comment="归一化坐标 {x,y,w,h} ∈ [0,1]",
        ),
        sa.Column("label", sa.String(128), nullable=True, comment="区域标签（检测器给的物体名）"),
        sa.Column(
            "visual_embedding",
            Vector(VISUAL_EMBEDDING_DIM),
            nullable=True,
            comment="该区域的 CLIP 图像向量",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_frame_regions_frame", "frame_regions", ["frame_asset_id"])
    op.create_index(
        "uq_frame_regions_key", "frame_regions", ["frame_asset_id", "region_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_frame_regions_key", table_name="frame_regions")
    op.drop_index("ix_frame_regions_frame", table_name="frame_regions")
    op.drop_table("frame_regions")
