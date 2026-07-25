"""devices.runtime_package + devices.control_transport：采集控制面绑定

connector 需要知道命令发给哪个眼镜 App（探针与正式 App 的 intent 契约不同）以及
走哪条通道（adb 本机 USB / inbox 设备自拉）。两列都可空：未绑定的设备按 inbox
处理，与本次改动之前的行为一致。

Revision ID: 0008_device_control_binding
Create Date: 2026-07-25 20:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_device_control_binding"
down_revision = "0007_device_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "devices",
        sa.Column(
            "runtime_package",
            sa.String(128),
            nullable=True,
            comment="设备端 App 包名：com.realitymemory.glassprobe / com.realitymemory.glasses",
        ),
    )
    op.add_column(
        "devices",
        sa.Column(
            "control_transport",
            sa.String(16),
            nullable=True,
            comment="控制通道：adb（本机 USB 联调）/ inbox（设备自拉，架构目标形态）",
        ),
    )


def downgrade() -> None:
    op.drop_column("devices", "control_transport")
    op.drop_column("devices", "runtime_package")
