"""frame_regions 增加 ocr_text：带字小物体的检索入口

身份证、银行卡、快递单、药盒——这类物体的身份印在它自己身上。OCR 命中的是字面量，
不需要模型"认出"它是什么，而切片/检测/caption 都做不到这件事。

⚠️ 入库的是**脱敏后**的文本（见 app/ocr/redact.py）：证件号/卡号/手机号在写库前
已换成〔身份证号〕这类占位符。原始媒体 15 分钟后就被 TTL 删了，这张表却是长期的，
不能让最敏感的那 18 位数字比照片活得还久。

Revision ID: 0013_frame_region_ocr
Create Date: 2026-07-25 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_frame_region_ocr"
down_revision = "0012_entity_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "frame_regions",
        sa.Column(
            "ocr_text",
            sa.Text,
            nullable=True,
            comment="OCR 识别文本（已脱敏；source=ocr 的区域才有）",
        ),
    )
    # trgm 模糊与 ilike 包含都吃这个索引；只索引有文本的行（绝大多数区域是瓦片/检测框）
    op.execute(
        "CREATE INDEX ix_frame_regions_ocr_trgm ON frame_regions"
        " USING gin (ocr_text gin_trgm_ops) WHERE ocr_text IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_frame_regions_ocr_trgm")
    op.drop_column("frame_regions", "ocr_text")
