"""SQLAlchemy 2.x 模型。所有表字段命名英文 snake_case，附中文注释。

五段时间模型：
  event_time(发生) / observed_at(观察) / ingested_at(接收) / accepted_at(入库) / valid_from-valid_to(语义有效期)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 1024
VISUAL_EMBEDDING_DIM = 512  # CLIP 视觉向量维度（对应 config.vision_dim 默认值）


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UUIDPK:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="主键"
    )


# ---------------------------------------------------------------- 基础维度


class Household(Base, UUIDPK):
    __tablename__ = "households"
    name: Mapped[str] = mapped_column(String(128), comment="家庭名称")


class Actor(Base, UUIDPK):
    __tablename__ = "actors"
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id"), comment="所属家庭"
    )
    role: Mapped[str] = mapped_column(String(32), comment="角色：owner/member/guest")


class Device(Base, UUIDPK):
    __tablename__ = "devices"
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id"), comment="所属家庭"
    )
    kind: Mapped[str] = mapped_column(String(32), comment="设备类型：glasses/ring/phone")
    name: Mapped[str] = mapped_column(String(128), comment="设备名")
    # 控制面绑定：connector 靠这两列知道「命令该发给谁、怎么发」。
    # 一台眼镜上可能装探针也可能装正式 App，两者的 intent 契约不同，不能靠 kind 猜。
    runtime_package: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        comment="设备端 App 包名：com.realitymemory.glassprobe / com.realitymemory.glasses",
    )
    control_transport: Mapped[str | None] = mapped_column(
        String(16),
        nullable=True,
        comment="控制通道：adb（本机 USB 联调）/ inbox（设备自拉，架构目标形态）",
    )


# ---------------------------------------------------------------- 入口：信封与证据


class SourceEnvelope(Base, UUIDPK):
    """来源信封：回答"这条输入从哪来、何时来、在什么策略下产生"。不是事实。"""

    __tablename__ = "source_envelopes"
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id"), nullable=True, comment="采集设备"
    )
    source_session_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="采集端 session id（对应 iOS session.json）"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="事件发生时间（采集端上报）"
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="观察时间（采集完成时间）"
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, comment="服务端接收时间"
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(256), unique=True, comment="幂等键，重复投递去重"
    )
    trigger: Mapped[str] = mapped_column(
        String(32), default="auto", comment="采集触发方式：explicit/auto/ring_motion"
    )
    modality: Mapped[str] = mapped_column(
        String(32), default="image", comment="模态：image/video/audio/sensor"
    )
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, comment="扩展元数据")


class EvidenceItem(Base, UUIDPK):
    """短暂证据：原始媒体是短期证据，TTL 到期物理删除。持久资产是结构化表示。"""

    __tablename__ = "evidence_items"
    envelope_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_envelopes.id"), comment="所属信封"
    )
    storage_ref: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="本地文件路径（删除后置空）"
    )
    media_kind: Mapped[str] = mapped_column(String(32), default="image", comment="媒体类型")
    phash: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="感知哈希(64bit)")
    ttl_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="TTL 截止时间，过期物理删除"
    )
    retention_state: Mapped[str] = mapped_column(
        String(32), default="ACTIVE", comment="ACTIVE/DELETED/DUPLICATE"
    )
    encryption_key_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="加密密钥 id 占位（v0 本地删除模拟 crypto-shredding）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_evidence_ttl", EvidenceItem.ttl_until)
Index("ix_evidence_created", EvidenceItem.created_at)


# ---------------------------------------------------------------- 长期结构化表示


class FrameAsset(Base, UUIDPK):
    """帧资产：caption/tags/embedding 是媒体删除后的长期表示。"""

    __tablename__ = "frame_assets"
    evidence_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id"), unique=True, comment="来源证据"
    )
    caption: Mapped[str] = mapped_column(Text, comment="一句话场景描述（中文）")
    scene_tags: Mapped[list] = mapped_column(JSONB, default=list, comment="显著物体列表")
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True, comment="caption+tags 向量（可空，空则降级 trgm）"
    )
    visual_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(VISUAL_EMBEDDING_DIM),
        nullable=True,
        comment="CLIP 图像向量（媒体删除后仍可用于视觉检索）",
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="帧捕获时间（=信封 occurred_at）"
    )
    quality: Mapped[dict] = mapped_column(JSONB, default=dict, comment="质量信息（分辨率/模糊度等）")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AtomicObservation(Base, UUIDPK):
    """原子观察：模型看到的最小观察，例如"疑似手机在黑色圆凳上"。不是事实。"""

    __tablename__ = "atomic_observations"
    frame_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("frame_assets.id"), nullable=True, comment="来源帧（与 audio_asset_id 二选一）"
    )
    audio_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("audio_assets.id"), nullable=True, comment="来源语音资产（与 frame_asset_id 二选一）"
    )
    predicate: Mapped[str] = mapped_column(
        String(64),
        comment="OBSERVED_AT/PLACED/MOVED/TAKEN/PUT_IN/TAKEN_OUT/OPENED/CLOSED/USED/CONSUMED/PREFERENCE_EXPRESSED/INTENT_CREATED",
    )
    subject_text: Mapped[str | None] = mapped_column(String(256), nullable=True, comment="主体（通常为用户）")
    object_text: Mapped[str] = mapped_column(String(256), comment="客体（物体名，如 手机）")
    value: Mapped[dict] = mapped_column(
        JSONB, default=dict, comment="谓词参数，如 {location: 黑色圆凳}"
    )
    phenomenon_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="现象发生时间（=帧捕获时间）"
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="观察时间")
    confidence: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        comment="置信度分量 {model,identity,spatial,temporal,policy,aggregate}",
    )
    parser_version: Mapped[str] = mapped_column(String(64), comment="抽取器版本")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_obs_object", AtomicObservation.object_text)


class AudioAsset(Base, UUIDPK):
    """语音资产：transcript/segments/embedding 是音频媒体删除后的长期表示。"""

    __tablename__ = "audio_assets"
    evidence_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_items.id"), unique=True, comment="来源证据"
    )
    transcript: Mapped[str] = mapped_column(Text, comment="ASR 全文转写")
    segments: Mapped[list] = mapped_column(
        JSONB, default=list, comment="分段转写 [{start,end,text,speaker?}]"
    )
    language: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="识别语言")
    duration_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="音频时长（秒，未知可空）"
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True, comment="转写文本向量（可空，空则降级 trgm）"
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="录制时间（=信封 occurred_at）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- 记忆核心


class Entity(Base, UUIDPK):
    """实体：被查询过/被事件确认的物体。系统越用越强。"""

    __tablename__ = "entities"
    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"))
    type: Mapped[str] = mapped_column(String(64), default="object", comment="实体类型")
    canonical_name: Mapped[str] = mapped_column(String(256), comment="规范名，如 手机")
    aliases: Mapped[list] = mapped_column(JSONB, default=list, comment="别名列表")
    class_: Mapped[str] = mapped_column("class", String(64), default="instance", comment="instance/class")
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIM), nullable=True, comment="名称向量（可空）"
    )
    visual_embedding: Mapped[list[float] | None] = mapped_column(
        Vector(VISUAL_EMBEDDING_DIM),
        nullable=True,
        comment="实例代表视觉向量（成员帧 CLIP 向量的滑动平均，物体级合并用）",
    )
    visual_embedding_count: Mapped[int] = mapped_column(
        default=0, comment="visual_embedding 滑动平均的样本数"
    )
    created_from: Mapped[str] = mapped_column(
        String(32), default="observation", comment="来源：observation/query/correction"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_entities_name_trgm", Entity.canonical_name, postgresql_ops={"canonical_name": "gin_trgm_ops"}, postgresql_using="gin")


class MemoryCandidate(Base, UUIDPK):
    """记忆候选：模型输出只能写到这里。只有候选门能把它升级为事件。"""

    __tablename__ = "memory_candidates"
    observation_ids: Mapped[list] = mapped_column(JSONB, default=list, comment="支撑观察 id 列表")
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True, comment="解析到的实体（可空）"
    )
    event_type: Mapped[str] = mapped_column(String(64), comment="拟写入的事件类型")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, comment="事件负载草稿")
    confidence: Mapped[dict] = mapped_column(JSONB, default=dict, comment="置信度分量")
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", comment="PENDING/ACCEPTED/REJECTED/CONFLICTED/EXPIRED"
    )
    conflict_set_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="冲突集 id"
    )
    source: Mapped[str] = mapped_column(
        String(32), default="perception", comment="perception/query"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_candidates_status", MemoryCandidate.status)


class MemoryEvent(Base, UUIDPK):
    """记忆事件：追加式事实变化，长期事实源。不可变；纠正产生 supersedes 新事件。"""

    __tablename__ = "memory_events"
    stream_id: Mapped[str] = mapped_column(String(128), comment="事件流 id（如 entity:<uuid>）")
    branch_id: Mapped[str] = mapped_column(String(64), default="main", comment="分支，默认 main")
    event_type: Mapped[str] = mapped_column(
        String(64),
        comment="OBJECT_OBSERVED_AT/OBJECT_MOVED/CONSUMABLE_LEVEL_OBSERVED/PREFERENCE_STATED/TASK_STATED/USER_CORRECTION/FORGET_REQUESTED",
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True
    )
    event_time_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="发生时间起")
    event_time_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="发生时间止")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="观察时间")
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="接收时间")
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, comment="入库时间")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, comment="语义有效期起")
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="语义有效期止（被取代/遗忘时关闭）")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_candidate_ids: Mapped[list] = mapped_column(JSONB, default=list)
    confidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    supersedes_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="被本事件取代的旧事件 id（纠正链）"
    )


Index("ix_events_entity", MemoryEvent.entity_id)
Index("ix_events_stream", MemoryEvent.stream_id)


class StateProjection(Base, UUIDPK):
    """状态投影：由有效事件流确定性重算，可随时重建。"""

    __tablename__ = "state_projections"
    __table_args__ = (UniqueConstraint("entity_id", "projection_type", name="uq_projection"),)
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id"))
    projection_type: Mapped[str] = mapped_column(String(64), default="last_seen", comment="投影类型")
    version: Mapped[int] = mapped_column(Integer, default=1, comment="重算版本号，单调递增")
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="投影截止时间")
    state: Mapped[dict] = mapped_column(JSONB, default=dict, comment="投影状态，如 {location, last_seen_time}")
    conflicts: Mapped[list] = mapped_column(JSONB, default=list, comment="未决冲突")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------- Agent 授权（Agent Access）


class AgentGrant(Base):
    """Agent 授权：用户授予某个 Agent Client 的受限访问权限（设计文档 §2）。

    原始 token 永不落库：只存 sha256(token)，原始 token 仅在创建时返回一次。
    过期/撤销在鉴权层拒绝；跨家庭访问靠 household_ids 在鉴权层隔离。
    """

    __tablename__ = "agent_grants"
    grant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="授权 id"
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), comment="授权用户（对应 actors.id，弱引用）"
    )
    agent_client_id: Mapped[str] = mapped_column(
        String(128), comment="Agent Client 标识，如 proactive-agent-demo"
    )
    scopes: Mapped[list] = mapped_column(JSONB, default=list, comment="授权 scope 列表（§10）")
    household_ids: Mapped[list] = mapped_column(
        JSONB, default=list, comment="可访问家庭 id 列表（uuid 字符串）"
    )
    allowed_entity_types: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, comment="允许的实体类型（可空=不限制）"
    )
    purpose: Mapped[str] = mapped_column(String(256), default="", comment="用途说明")
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, comment="opaque bearer token 的 sha256（绝不存原文）"
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, comment="签发时间"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="过期时间")
    revocable: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否可撤销")
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="撤销时间（未撤销为空）"
    )


# ---------------------------------------------------------------- Signal（主动式）


class MemorySignal(Base, UUIDPK):
    """信号：从事实/投影按确定性规则派生的可过期通知候选（§3.3）。

    不是 MemoryEvent：信号可过期、可抑制、可忽略，不进事实流。
    生成走规则引擎（signals/rules.py），措辞归 Agent；平台绝不用 LLM 生成信号。
    """

    __tablename__ = "memory_signals"
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id"), comment="所属家庭（投递按家庭隔离）"
    )
    signal_type: Mapped[str] = mapped_column(
        String(64), comment="LOW_CONSUMABLE / STALE_LOCATION"
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True, comment="关联实体"
    )
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, comment="信号内容（结构化，供 Agent 措辞）")
    confidence: Mapped[float] = mapped_column(Float, default=0.5, comment="信号置信度")
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", comment="PENDING/DELIVERED/ACKED/EXPIRED"
    )
    cooldown_key: Mapped[str] = mapped_column(
        String(256), comment="去重键（signal_type:entity_id）：冷却窗口内不重复生成"
    )
    delivered_subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="投递到的订阅（每日上限按订阅统计）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="过期时间：过期信号不投递（§13）"
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_signals_status", MemorySignal.status)
Index("ix_signals_cooldown", MemorySignal.cooldown_key, MemorySignal.created_at)


class SignalSubscription(Base, UUIDPK):
    """信号订阅：Agent（经 grant）或 owner 声明要接收哪些信号及投递约束（§4.2）。"""

    __tablename__ = "signal_subscriptions"
    grant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, comment="所属 AgentGrant（owner 直订为空）"
    )
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id"), comment="订阅的家庭范围"
    )
    signal_types: Mapped[list] = mapped_column(JSONB, default=list, comment="允许的信号类型")
    min_confidence: Mapped[float] = mapped_column(Float, default=0.0, comment="最低置信度")
    cooldown_seconds: Mapped[int] = mapped_column(
        Integer, default=3600, comment="同一 cooldown_key 两次投递的最小间隔"
    )
    daily_cap: Mapped[int] = mapped_column(Integer, default=10, comment="每日投递上限")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="订阅过期时间")
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="撤销时间（grant 撤销时一并停投）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------- 下行：设备消息与回执


class DeviceMessage(Base, UUIDPK):
    """下行设备消息（通信架构 §5.2 `rme.device-message.v0`）。

    只传结果和控制，不传记忆数据库本身（§5.1）：payload 是提醒/策略/诊断的最小载荷，
    不是 MemoryEvent 或 StateProjection 的同步副本。

    状态机（至少一次投递 + 设备侧按 message_id 幂等）：
      PENDING  未推送
      SENT     已推给某条长连或已被 inbox 拉取，等待设备回执
      RECEIVED 设备确认收到（PRESENTED/SPOKEN 只更新时间戳，不改状态）
      CLOSED   收到终态回执（DISMISSED/FAILED）
      EXPIRED  到期仍未终态：过期消息不展示、不播报（§5.4）

    id 即对外的 message_id。
    """

    __tablename__ = "device_messages"
    household_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("households.id"), comment="所属家庭（下行按家庭隔离）"
    )
    target_device_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("devices.id"), comment="目标设备"
    )
    message_type: Mapped[str] = mapped_column(
        String(64),
        comment="REMINDER_SIGNAL/POLICY_UPDATE/PRIVACY_PAUSE/CAPTURE_BUDGET_UPDATE/CAPTURE_REQUEST/DIAGNOSTIC",
    )
    payload_schema_ref: Mapped[str] = mapped_column(
        String(128), default="rme.reminder-signal.draft", comment="载荷版本（业务字段待 review）"
    )
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, comment="业务载荷，字段尚未冻结")
    priority: Mapped[str] = mapped_column(String(16), default="NORMAL", comment="LOW/NORMAL/HIGH")
    allow_text: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="delivery_policy：允许文字呈现"
    )
    allow_tts: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="delivery_policy：允许 TTS 播报（打断更硬，默认关）"
    )
    signal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("memory_signals.id"), nullable=True, comment="来源信号（手动注入为空）"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", comment="PENDING/SENT/RECEIVED/CLOSED/EXPIRED"
    )
    last_receipt_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="最近一次回执状态（可观测性）"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), comment="过期时间：过期消息不投递、不播报"
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    presented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    spoken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_device_messages_pending", DeviceMessage.target_device_id, DeviceMessage.status)


class DeviceDeliveryReceipt(Base, UUIDPK):
    """投递回执（§5.4）。

    只说明设备投递结果，不代表用户接受了提醒内容，也不能直接修改记忆事实。
    (message_id, status) 唯一：同一消息的同一状态只落一条，眼镜直连与手机中继
    同时上报也不会产生两条终态（§7 去重要求）。
    """

    __tablename__ = "device_delivery_receipts"
    __table_args__ = (UniqueConstraint("message_id", "status", name="uq_receipt_message_status"),)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("device_messages.id", ondelete="CASCADE"), comment="对应下行消息"
    )
    status: Mapped[str] = mapped_column(
        String(32),
        comment="RECEIVED/PRESENTED/SPOKEN/DISMISSED/EXPIRED/FAILED/EXECUTED/REJECTED",
    )
    detail: Mapped[dict] = mapped_column(
        JSONB, default=dict, comment="失败原因、本地策略拒绝理由等附加信息"
    )
    device_reported_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="设备本地上报时间（不覆盖服务端接收时间）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, comment="服务端接收时间"
    )


# ---------------------------------------------------------------- 遗忘与审计


class DeletionRequest(Base, UUIDPK):
    __tablename__ = "deletion_requests"
    scope: Mapped[dict] = mapped_column(JSONB, default=dict, comment="删除范围 {minutes, scope[], since/until}")
    status: Mapped[str] = mapped_column(String(32), default="PENDING", comment="PENDING/RUNNING/DONE/FAILED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeletionJob(Base, UUIDPK):
    __tablename__ = "deletion_jobs"
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deletion_requests.id"))
    subsystem: Mapped[str] = mapped_column(String(64), comment="evidence/frame/audio/observation/candidate/event/vector/projection")
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeletionTombstone(Base, UUIDPK):
    """删除墓碑：证明"删过"，内容不可逆。"""

    __tablename__ = "deletion_tombstones"
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("deletion_requests.id"))
    audit_hash: Mapped[str] = mapped_column(String(128), comment="删除回执哈希")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditRecord(Base, UUIDPK):
    __tablename__ = "audit_records"
    actor: Mapped[str] = mapped_column(String(128), comment="操作者：user:<id>/system/<worker 名>")
    action: Mapped[str] = mapped_column(String(64), comment="动作：ingest/event_accepted/correct/forget/ttl_delete/query")
    target: Mapped[str] = mapped_column(String(256), comment="目标对象")
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_audit_created", AuditRecord.created_at)


# ---------------------------------------------------------------- 异步队列（DB 队列表，不引入 Redis/Kafka）


class OutboxEvent(Base):
    """事务性 outbox：与业务写入同事务落库，worker 异步消费。"""

    __tablename__ = "outbox_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    topic: Mapped[str] = mapped_column(String(64), comment="frame.process / projection.recompute")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index("ix_outbox_pending", OutboxEvent.processed_at)
