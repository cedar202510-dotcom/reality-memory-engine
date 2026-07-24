"""初始 schema：扩展 + 全部 v0 表

Revision ID: 0001_initial
Create Date: 2026-01-01 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "households",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, comment="家庭名称"),
    )
    op.create_table(
        "actors",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("household_id", UUID(as_uuid=True), sa.ForeignKey("households.id"), nullable=False, comment="所属家庭"),
        sa.Column("role", sa.String(32), nullable=False, comment="角色：owner/member/guest"),
    )
    op.create_table(
        "devices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("household_id", UUID(as_uuid=True), sa.ForeignKey("households.id"), nullable=False, comment="所属家庭"),
        sa.Column("kind", sa.String(32), nullable=False, comment="设备类型：glasses/ring/phone"),
        sa.Column("name", sa.String(128), nullable=False, comment="设备名"),
    )
    op.create_table(
        "source_envelopes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("device_id", UUID(as_uuid=True), sa.ForeignKey("devices.id"), nullable=True, comment="采集设备"),
        sa.Column("source_session_id", sa.String(128), nullable=True, comment="采集端 session id"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, comment="事件发生时间"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, comment="观察时间"),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, comment="服务端接收时间"),
        sa.Column("idempotency_key", sa.String(256), nullable=False, unique=True, comment="幂等键"),
        sa.Column("trigger", sa.String(32), nullable=False, comment="采集触发方式"),
        sa.Column("modality", sa.String(32), nullable=False, comment="模态"),
        sa.Column("meta", JSONB, nullable=False, comment="扩展元数据"),
    )
    op.create_table(
        "evidence_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("envelope_id", UUID(as_uuid=True), sa.ForeignKey("source_envelopes.id"), nullable=False, comment="所属信封"),
        sa.Column("storage_ref", sa.Text, nullable=True, comment="本地文件路径"),
        sa.Column("media_kind", sa.String(32), nullable=False, comment="媒体类型"),
        sa.Column("phash", sa.BigInteger, nullable=True, comment="感知哈希(64bit)"),
        sa.Column("ttl_until", sa.DateTime(timezone=True), nullable=False, comment="TTL 截止时间"),
        sa.Column("retention_state", sa.String(32), nullable=False, comment="ACTIVE/DELETED/DUPLICATE"),
        sa.Column("encryption_key_id", sa.String(128), nullable=True, comment="加密密钥 id 占位"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evidence_ttl", "evidence_items", ["ttl_until"])
    op.create_index("ix_evidence_created", "evidence_items", ["created_at"])

    op.create_table(
        "frame_assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("evidence_item_id", UUID(as_uuid=True), sa.ForeignKey("evidence_items.id"), nullable=False, unique=True, comment="来源证据"),
        sa.Column("caption", sa.Text, nullable=False, comment="一句话场景描述"),
        sa.Column("scene_tags", JSONB, nullable=False, comment="显著物体列表"),
        sa.Column("embedding", Vector(1024), nullable=True, comment="caption+tags 向量"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, comment="帧捕获时间"),
        sa.Column("quality", JSONB, nullable=False, comment="质量信息"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "atomic_observations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("frame_asset_id", UUID(as_uuid=True), sa.ForeignKey("frame_assets.id"), nullable=False, comment="来源帧"),
        sa.Column("predicate", sa.String(64), nullable=False, comment="谓词"),
        sa.Column("subject_text", sa.String(256), nullable=True, comment="主体"),
        sa.Column("object_text", sa.String(256), nullable=False, comment="客体"),
        sa.Column("value", JSONB, nullable=False, comment="谓词参数"),
        sa.Column("phenomenon_time", sa.DateTime(timezone=True), nullable=False, comment="现象发生时间"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, comment="观察时间"),
        sa.Column("confidence", JSONB, nullable=False, comment="置信度分量"),
        sa.Column("parser_version", sa.String(64), nullable=False, comment="抽取器版本"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_obs_object", "atomic_observations", ["object_text"])

    op.create_table(
        "entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("household_id", UUID(as_uuid=True), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("type", sa.String(64), nullable=False, comment="实体类型"),
        sa.Column("canonical_name", sa.String(256), nullable=False, comment="规范名"),
        sa.Column("aliases", JSONB, nullable=False, comment="别名列表"),
        sa.Column("class", sa.String(64), nullable=False, comment="instance/class"),
        sa.Column("embedding", Vector(1024), nullable=True, comment="名称向量"),
        sa.Column("created_from", sa.String(32), nullable=False, comment="来源"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_entities_name_trgm",
        "entities",
        ["canonical_name"],
        postgresql_using="gin",
        postgresql_ops={"canonical_name": "gin_trgm_ops"},
    )

    op.create_table(
        "memory_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("observation_ids", JSONB, nullable=False, comment="支撑观察 id 列表"),
        sa.Column("entity_id", UUID(as_uuid=True), sa.ForeignKey("entities.id"), nullable=True),
        sa.Column("event_type", sa.String(64), nullable=False, comment="拟写入的事件类型"),
        sa.Column("payload", JSONB, nullable=False, comment="事件负载草稿"),
        sa.Column("confidence", JSONB, nullable=False, comment="置信度分量"),
        sa.Column("status", sa.String(32), nullable=False, comment="PENDING/ACCEPTED/REJECTED/CONFLICTED/EXPIRED"),
        sa.Column("conflict_set_id", UUID(as_uuid=True), nullable=True, comment="冲突集 id"),
        sa.Column("source", sa.String(32), nullable=False, comment="perception/query"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_candidates_status", "memory_candidates", ["status"])

    op.create_table(
        "memory_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("stream_id", sa.String(128), nullable=False, comment="事件流 id"),
        sa.Column("branch_id", sa.String(64), nullable=False, comment="分支"),
        sa.Column("event_type", sa.String(64), nullable=False, comment="事件类型"),
        sa.Column("entity_id", UUID(as_uuid=True), sa.ForeignKey("entities.id"), nullable=True),
        sa.Column("event_time_from", sa.DateTime(timezone=True), nullable=False, comment="发生时间起"),
        sa.Column("event_time_to", sa.DateTime(timezone=True), nullable=True, comment="发生时间止"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, comment="观察时间"),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, comment="接收时间"),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False, comment="入库时间"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False, comment="语义有效期起"),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True, comment="语义有效期止"),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("source_candidate_ids", JSONB, nullable=False),
        sa.Column("confidence", JSONB, nullable=False),
        sa.Column("supersedes_event_id", UUID(as_uuid=True), nullable=True, comment="被取代的旧事件"),
    )
    op.create_index("ix_events_entity", "memory_events", ["entity_id"])
    op.create_index("ix_events_stream", "memory_events", ["stream_id"])

    op.create_table(
        "state_projections",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_id", UUID(as_uuid=True), sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("projection_type", sa.String(64), nullable=False, comment="投影类型"),
        sa.Column("version", sa.Integer, nullable=False, comment="重算版本号"),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False, comment="投影截止时间"),
        sa.Column("state", JSONB, nullable=False, comment="投影状态"),
        sa.Column("conflicts", JSONB, nullable=False, comment="未决冲突"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("entity_id", "projection_type", name="uq_projection"),
    )

    op.create_table(
        "deletion_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", JSONB, nullable=False, comment="删除范围"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "deletion_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("deletion_requests.id"), nullable=False),
        sa.Column("subsystem", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer, nullable=False),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "deletion_tombstones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("deletion_requests.id"), nullable=False),
        sa.Column("audit_hash", sa.String(128), nullable=False, comment="删除回执哈希"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("actor", sa.String(128), nullable=False, comment="操作者"),
        sa.Column("action", sa.String(64), nullable=False, comment="动作"),
        sa.Column("target", sa.String(256), nullable=False, comment="目标对象"),
        sa.Column("detail", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_created", "audit_records", ["created_at"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("topic", sa.String(64), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_outbox_pending", "outbox_events", ["processed_at"])


def downgrade() -> None:
    for table in (
        "outbox_events", "audit_records", "deletion_tombstones", "deletion_jobs",
        "deletion_requests", "state_projections", "memory_events", "memory_candidates",
        "entities", "atomic_observations", "frame_assets", "evidence_items",
        "source_envelopes", "devices", "actors", "households",
    ):
        op.drop_table(table)
