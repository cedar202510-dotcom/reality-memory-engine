"""frame_regions 增加 crop_ref / score：物件缩略图落盘，全览页每个节点配一张实拍图

crop_ref 必须是独立落盘的文件，不能指回 evidence 原件：证据 TTL 默认 15 分钟就把
原图物理删了，缩略图要活得比原件长。所以裁切必须在摄入期做完（过期后没有输入，
任何回填都补不回来），裁出来的小图另存一份，只按物品维度存一张，不占多少空间。

score 是检测器给这个框的置信度，用来在同一件物品的多张候选图里挑最好的那张。

Revision ID: 0011_region_crops
Create Date: 2026-07-25 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_region_crops"
down_revision = "0010_frame_regions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "frame_regions",
        sa.Column(
            "crop_ref",
            sa.String(512),
            nullable=True,
            comment="裁切图落盘路径（不受证据 TTL 管辖；tile 区域为空）",
        ),
    )
    op.add_column(
        "frame_regions",
        sa.Column(
            "score",
            sa.Float,
            nullable=True,
            comment="检测器置信度（tile 区域为空）；同一物品多张候选图时按它择优",
        ),
    )
    # 择优查询是「按 (帧, 标签) 找有图的检测区域」，label 上没索引就得全表扫
    op.create_index(
        "ix_frame_regions_label",
        "frame_regions",
        ["frame_asset_id", "label"],
        postgresql_where=sa.text("label IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_frame_regions_label", table_name="frame_regions")
    op.drop_column("frame_regions", "score")
    op.drop_column("frame_regions", "crop_ref")
