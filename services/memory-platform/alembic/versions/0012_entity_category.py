"""entities.category：粗分类，把「我会去找的东西」跟场景/人/耗材分开

感知会把 人、手臂、木地板、墙面、空调 一并认成实体（它们确实出现在画面里），
但「我的东西在哪」只关心其中一小部分。没有这一刀，全览和找物会被固定物和身体部位
淹没——97 个实体里真正算随身物品的不到一半。

category_source 不是冗余：类别是推断出来的，用户改过之后绝不能被下一轮自动分类覆盖。

Revision ID: 0012_entity_category

注：本迁移原本编号 0011，与并行开发的 0011_region_crops 同时从 0010 分叉，
形成双 head。两者改的表不重叠（那边是 frame_regions 裁图，这边是 entities 加列），
所以直接线性接在其后，不另造 merge revision。
Create Date: 2026-07-25 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_entity_category"
down_revision = "0011_region_crops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column(
            "category",
            sa.String(32),
            nullable=False,
            server_default="UNCLASSIFIED",
            comment="PORTABLE/FIXTURE/PERSON/CONSUMABLE/UNCLASSIFIED",
        ),
    )
    op.add_column(
        "entities",
        sa.Column(
            "category_source",
            sa.String(16),
            nullable=False,
            server_default="unset",
            comment="谁定的：llm/user/unset",
        ),
    )
    op.create_index("ix_entities_category", "entities", ["category"])


def downgrade() -> None:
    op.drop_index("ix_entities_category", table_name="entities")
    op.drop_column("entities", "category_source")
    op.drop_column("entities", "category")
