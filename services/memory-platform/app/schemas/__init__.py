"""冻结契约（frozen contracts）：命名与字段即项目对外契约，改动需评审。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------- 常量

ALLOWED_PREDICATES = (
    "OBSERVED_AT",
    "PLACED",
    "MOVED",
    "TAKEN",
    "PUT_IN",
    "TAKEN_OUT",
    "OPENED",
    "CLOSED",
    "USED",
    "CONSUMED",
    "PREFERENCE_EXPRESSED",
    "INTENT_CREATED",
)

EVENT_TYPES = (
    "OBJECT_OBSERVED_AT",
    "OBJECT_MOVED",
    "CONSUMABLE_LEVEL_OBSERVED",
    "PREFERENCE_STATED",
    "TASK_STATED",
    "USER_CORRECTION",
    "FORGET_REQUESTED",
)

CANDIDATE_STATUSES = ("PENDING", "ACCEPTED", "REJECTED", "CONFLICTED", "EXPIRED")
DeviceModality = Literal["IMAGE", "VIDEO", "AUDIO", "SENSOR"]


# ---------------------------------------------------------------- SourceEnvelope


class SourceEnvelopeIn(BaseModel):
    """采集端上报的信封（对应 iOS 探针 session.json 的映射结果）。"""

    device_id: uuid.UUID | None = None
    source_session_id: str | None = None
    occurred_at: datetime
    observed_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=256)
    trigger: Literal["explicit", "auto", "ring_motion"] = "auto"
    modality: Literal["image", "video", "audio", "sensor"] = "image"
    meta: dict[str, Any] = Field(default_factory=dict)


class SourceEnvelopeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    device_id: uuid.UUID | None
    source_session_id: str | None
    occurred_at: datetime
    observed_at: datetime
    ingested_at: datetime
    idempotency_key: str
    trigger: str
    modality: str
    meta: dict[str, Any]


class IngestResponse(BaseModel):
    envelope: SourceEnvelopeOut
    evidence_item_ids: list[uuid.UUID]
    duplicate_evidence_ids: list[uuid.UUID] = Field(default_factory=list)
    idempotent_replay: bool = False


class DeviceSourceEnvelopeIn(BaseModel):
    """眼镜等设备直接上报的正式 rme.source-envelope.v1。"""

    model_config = ConfigDict(extra="forbid")

    schema_ref: Literal["rme.source-envelope.v1"]
    source_envelope_id: str = Field(min_length=6, max_length=128)
    device_id: str = Field(min_length=6, max_length=128)
    device_kind: str = Field(min_length=1, max_length=128)
    device_adapter: str = Field(min_length=1, max_length=128)
    capture_session_id: str | None
    capture_window_id: str | None = None
    capture_intent_id: str | None = None
    occurred_at: datetime
    observed_at: datetime
    monotonic_start_ns: int | None = Field(default=None, ge=0)
    monotonic_end_ns: int | None = Field(default=None, ge=0)
    clock_domain: str = Field(min_length=1, max_length=128)
    clock_sync_method: str = Field(min_length=1, max_length=128)
    time_uncertainty_ms: int = Field(ge=0)
    policy_snapshot_id: str = Field(min_length=1, max_length=128)
    modality: Literal[
        "IMAGE",
        "VIDEO",
        "AUDIO",
        "SENSOR",
        "DEVICE_EVENT",
        "USER_INPUT",
        "ONLINE_CONTEXT",
    ]
    payload_kind: Literal["EVIDENCE_ITEM", "STRUCTURED_EVENT"]
    payload_ref: str = Field(min_length=6, max_length=128)
    idempotency_key: str = Field(min_length=6, max_length=256)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_monotonic_range(self) -> DeviceSourceEnvelopeIn:
        if (
            self.monotonic_start_ns is not None
            and self.monotonic_end_ns is not None
            and self.monotonic_end_ns < self.monotonic_start_ns
        ):
            raise ValueError("monotonic_end_ns 不能早于 monotonic_start_ns")
        return self


class DeviceEvidenceItemIn(BaseModel):
    """设备证据元数据；媒体二进制通过同一 multipart 请求上传。"""

    model_config = ConfigDict(extra="forbid")

    schema_ref: Literal["rme.evidence-item.v1"]
    evidence_item_id: str = Field(min_length=6, max_length=128)
    source_envelope_id: str = Field(min_length=6, max_length=128)
    capture_window_id: str = Field(min_length=6, max_length=128)
    modality: DeviceModality
    mime_type: str = Field(min_length=3, max_length=128)
    captured_at: datetime
    duration_ms: int = Field(ge=0)
    byte_count: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    encryption: DeviceEncryptionIn
    retention: DeviceRetentionIn
    media: dict[str, Any]
    sensitivity_labels: list[str] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)


class DeviceEncryptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm: Literal["AES_256_GCM", "NONE_TEST_FIXTURE"]
    key_ref: str | None
    iv_base64: str | None


class DeviceRetentionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ttl_expires_at: datetime
    purpose: Literal[
        "STRUCTURE_EXTRACTION",
        "CROSS_MODAL_VALIDATION",
        "EXPLICIT_DEBUG_SAMPLE",
    ]
    debug_sample: bool


class DeviceCaptureIntentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_ref: Literal["rme.capture-intent.v1"]
    capture_intent_id: str = Field(min_length=6, max_length=128)
    capture_session_id: str = Field(min_length=6, max_length=128)
    signal_kind: Literal[
        "HEAD_MOTION_TRANSITION",
        "WEAR_CONFIRMED",
        "USER_EXPLICIT",
        "VOICE_ACTIVITY",
        "DEBUG_TEST",
    ]
    occurred_at: datetime
    monotonic_start_ns: int | None = Field(default=None, ge=0)
    monotonic_end_ns: int | None = Field(default=None, ge=0)
    detector_rule_version: str
    intensity: Literal["LOW", "MEDIUM", "STRONG"]
    metrics: dict[str, Any]
    requested_modalities: list[DeviceModality] = Field(min_length=1)
    extensions: dict[str, Any] = Field(default_factory=dict)


class DeviceCaptureWindowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_ref: Literal["rme.capture-window.v1"]
    capture_window_id: str = Field(min_length=6, max_length=128)
    capture_session_id: str = Field(min_length=6, max_length=128)
    capture_intent_id: str = Field(min_length=6, max_length=128)
    window_start: datetime
    window_end: datetime
    monotonic_start_ns: int | None = Field(default=None, ge=0)
    monotonic_end_ns: int | None = Field(default=None, ge=0)
    requested_modalities: list[DeviceModality] = Field(min_length=1)
    policy_snapshot_id: str = Field(min_length=1, max_length=128)
    state: Literal["OPEN", "FINALIZING", "FINALIZED", "CANCELLED"]
    extensions: dict[str, Any] = Field(default_factory=dict)


class DeviceEvidenceIngestResponse(BaseModel):
    """正式设备契约入口的确认响应。"""

    source_envelope_id: str
    evidence_item_id: str
    ingest: IngestResponse
    validation_warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- AtomicObservation


class ConfidenceParts(BaseModel):
    """五维置信度分量。"""

    model: float = 0.5
    identity: float = 0.5
    spatial: float = 0.5
    temporal: float = 0.5
    policy: float = 1.0
    aggregate: float = 0.5


class AtomicObservationIn(BaseModel):
    """VLM 结构化抽取输出（schema 外字段由解析层直接丢弃）。"""

    model_config = ConfigDict(extra="ignore")

    predicate: str
    object_text: str
    subject_text: str | None = None
    value: dict[str, Any] = Field(default_factory=dict)
    confidence: ConfidenceParts = Field(default_factory=ConfidenceParts)


class AtomicObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    frame_asset_id: uuid.UUID | None = None   # 与 audio_asset_id 二选一
    audio_asset_id: uuid.UUID | None = None
    predicate: str
    subject_text: str | None
    object_text: str
    value: dict[str, Any]
    phenomenon_time: datetime
    observed_at: datetime
    confidence: dict[str, Any]
    parser_version: str


# ---------------------------------------------------------------- MemoryCandidate


class MemoryCandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    observation_ids: list[Any]
    entity_id: uuid.UUID | None
    event_type: str
    payload: dict[str, Any]
    confidence: dict[str, Any]
    status: str
    conflict_set_id: uuid.UUID | None
    source: str
    created_at: datetime
    resolved_at: datetime | None


# ---------------------------------------------------------------- 查询契约


class EntityRef(BaseModel):
    id: uuid.UUID
    canonical_name: str
    aliases: list[Any] = Field(default_factory=list)


class LocationAlternative(BaseModel):
    location: str
    last_seen_time: datetime
    confidence: float


class ProvenanceSummary(BaseModel):
    """来源摘要（§4.1）：答案由哪些事件支撑、是否被纠正过。不含原始媒体。"""

    supporting_event_ids: list[uuid.UUID] = Field(default_factory=list)
    support_count: int = 0
    last_corrected_at: datetime | None = None


class FindObjectResponse(BaseModel):
    """where-is 统一响应。永远带置信度与新鲜度表述。"""

    query: str
    channel: Literal["projection", "deep_retrieval", "not_found"]
    entity: EntityRef | None = None
    location: str | None = None
    last_seen_time: datetime | None = None
    freshness: str | None = None          # 如 "最后一次看到是 3 分钟前"
    confidence: float = 0.0
    answer_text: str = ""
    alternatives: list[LocationAlternative] = Field(default_factory=list)
    timeline_url: str | None = None
    provenance_summary: ProvenanceSummary = Field(default_factory=ProvenanceSummary)
    # 平台对自身不确定性的机器可读声明（规则生成，不经 LLM）；Agent 必须转达给用户
    limitations: list[str] = Field(default_factory=list)
    # Agent 侧缓存上限；纠正/遗忘后不得继续使用缓存副本（§12）
    cache_until: datetime | None = None


class TimelineEntry(BaseModel):
    event_id: uuid.UUID
    event_type: str
    event_time_from: datetime
    accepted_at: datetime
    valid_to: datetime | None
    payload: dict[str, Any]
    confidence: dict[str, Any]
    superseded_by: uuid.UUID | None = None


class TimelineResponse(BaseModel):
    entity: EntityRef
    projection: dict[str, Any] | None
    events: list[TimelineEntry]


class CorrectRequest(BaseModel):
    entity_id: uuid.UUID
    field: str = Field(min_length=1)       # 如 location
    value: Any
    reason: str = ""


class CorrectResponse(BaseModel):
    event_id: uuid.UUID
    superseded_event_id: uuid.UUID | None
    projection: dict[str, Any] | None


# ---------------------------------------------------------------- 场景检索（CLIP 跨模态）


class SceneSearchRequest(BaseModel):
    """通用场景物件查找：文本/图片至少给一个（图片为 base64 编码）。"""

    query_text: str | None = Field(default=None, min_length=1)
    query_image_base64: str | None = Field(default=None, min_length=1)
    top_k: int = Field(default=8, ge=1, le=50)

    @model_validator(mode="after")
    def _at_least_one_input(self) -> SceneSearchRequest:
        if not self.query_text and not self.query_image_base64:
            raise ValueError("query_text 与 query_image_base64 至少提供一个")
        return self


class RecentFrameEntry(BaseModel):
    """联调面板用：最近摄入的一帧（含处理状态，caption 为空表示感知尚未完成）。"""

    frame_asset_id: uuid.UUID
    captured_at: datetime
    caption: str | None = None
    scene_tags: list[Any] = Field(default_factory=list)
    evidence_available: bool
    evidence_url: str | None = None


class RecentFramesResponse(BaseModel):
    """最近摄入帧列表 + 摄入积压量（pending_outbox>0 表示还有帧在排队等感知）。"""

    frames: list[RecentFrameEntry]
    pending_outbox: int


class SceneSearchHit(BaseModel):
    """单条命中：帧 + 相似度分数 + 证据可用性（媒体 TTL 删除后 evidence_url 为 null）。"""

    frame_asset_id: uuid.UUID
    captured_at: datetime
    caption: str
    scene_tags: list[Any] = Field(default_factory=list)
    score: float
    evidence_available: bool
    evidence_url: str | None = None


class AudioSearchHit(BaseModel):
    """单条语音命中：语音资产 + 相似度分数 + 证据可用性（媒体 TTL 删除后为 false）。"""

    audio_asset_id: uuid.UUID
    captured_at: datetime
    transcript: str
    score: float
    evidence_available: bool


class SceneSearchResponse(BaseModel):
    query_text: str | None = None
    has_image_query: bool = False
    hits: list[SceneSearchHit] = Field(default_factory=list)
    audio_hits: list[AudioSearchHit] = Field(default_factory=list)


class ForgetRecentRequest(BaseModel):
    minutes: int = Field(gt=0, le=24 * 60)
    scope: list[str] = Field(
        default_factory=lambda: ["evidence", "frame", "audio", "observation", "candidate", "event", "vector", "projection"]
    )


class ForgetRecentResponse(BaseModel):
    request_id: uuid.UUID
    status: str
    jobs: list[dict[str, Any]]
    tombstone_id: uuid.UUID | None = None


class AuditRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor: str
    action: str
    target: str
    detail: dict[str, Any]
    created_at: datetime


# ---------------------------------------------------------------- 偏好查询（Agent Access）


class PreferenceHit(BaseModel):
    """一条偏好陈述：来自 PREFERENCE_STATED 事件（语音/观察沉淀）。"""

    entity: EntityRef
    event_id: uuid.UUID
    payload: dict[str, Any]                # 如 {preference: "不喜欢这家胡辣汤"}
    stated_at: datetime
    confidence: float
    superseded: bool = False               # 已被纠正取代


class PreferenceResponse(BaseModel):
    subject: str
    hits: list[PreferenceHit] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    cache_until: datetime | None = None


# ---------------------------------------------------------------- Agent 授权（grants 管理契约）


class AgentGrantCreateRequest(BaseModel):
    agent_client_id: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(min_length=1)
    purpose: str = ""
    ttl_days: int = Field(default=30, ge=1, le=365)
    allowed_entity_types: list[str] | None = None


class AgentGrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    grant_id: uuid.UUID
    owner_id: uuid.UUID
    agent_client_id: str
    scopes: list[Any]
    household_ids: list[Any]
    allowed_entity_types: list[Any] | None
    purpose: str
    issued_at: datetime
    expires_at: datetime
    revocable: bool
    revoked_at: datetime | None


class AgentGrantCreateResponse(BaseModel):
    grant: AgentGrantOut
    token: str                              # 原始 token 只在此返回一次，库中仅存哈希


# ---------------------------------------------------------------- Signal（主动式）


SIGNAL_TYPES = ("LOW_CONSUMABLE", "STALE_LOCATION")


class SignalSubscriptionCreateRequest(BaseModel):
    signal_types: list[str] = Field(min_length=1)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    cooldown_seconds: int = Field(default=3600, ge=0)
    daily_cap: int = Field(default=10, ge=1, le=100)
    ttl_days: int = Field(default=30, ge=1, le=365)

    @model_validator(mode="after")
    def _known_types(self) -> SignalSubscriptionCreateRequest:
        unknown = [t for t in self.signal_types if t not in SIGNAL_TYPES]
        if unknown:
            raise ValueError(f"未知信号类型：{unknown}（可用：{list(SIGNAL_TYPES)}）")
        return self


class SignalSubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    grant_id: uuid.UUID | None
    signal_types: list[Any]
    min_confidence: float
    cooldown_seconds: int
    daily_cap: int
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    signal_type: str
    entity_id: uuid.UUID | None
    payload: dict[str, Any]
    confidence: float
    status: str
    created_at: datetime
    expires_at: datetime


class SignalListResponse(BaseModel):
    signals: list[SignalOut] = Field(default_factory=list)
    # 因冷却/每日上限/过期被抑制的数量（可观测性：抑制不是丢失）
    suppressed: int = 0


# ---------------------------------------------------------------- 下行：设备消息与回执
#
# 注意：这里只冻结通用信封字段（通信架构 §5.2 `rme.device-message.v0`）。
# payload 内的提醒主题、理由、按钮、措辞和交互动作仍待产品与 Agent 专项 review，
# 不要把 REMINDER_SIGNAL 的 payload 当成已冻结的 v1 业务契约。

DEVICE_MESSAGE_SCHEMA_REF = "rme.device-message.v0"

DEVICE_MESSAGE_TYPES = (
    "REMINDER_SIGNAL",          # 值得呈现的提醒
    "POLICY_UPDATE",            # 策略版本更新通知
    "PRIVACY_PAUSE",            # 隐私暂停 / 解绑 / 凭证撤销
    "CAPTURE_BUDGET_UPDATE",    # 采集预算与能力配置更新
    "CAPTURE_REQUEST",          # 采集请求：设备本地策略决定执不执行（§8）
    "DIAGNOSTIC",               # 仅限测试构建的诊断命令
)

# §5.4 回执状态。RECEIVED/PRESENTED/SPOKEN 是过程，其余是终态。
#
# EXECUTED/REJECTED 是 CAPTURE_REQUEST 专用的终态：提醒类消息的终局是「用户看没看到」，
# 采集请求的终局是「设备本地策略让不让做」。复用 DISMISSED/FAILED 会把「策略正常拒绝」
# 和「设备故障」混成一个状态，事后查审计分不清是隐私生效还是链路坏了。
DELIVERY_RECEIPT_STATUSES = (
    "RECEIVED",
    "PRESENTED",
    "SPOKEN",
    "DISMISSED",
    "EXPIRED",
    "FAILED",
    "EXECUTED",
    "REJECTED",
)
TERMINAL_RECEIPT_STATUSES = ("DISMISSED", "FAILED", "EXPIRED", "EXECUTED", "REJECTED")


class DeliveryPolicy(BaseModel):
    """投递限制：设备据此决定能否展示文字、能否 TTS 播报。"""

    allow_text: bool = True
    # 语音是比 HUD 文字更硬的打断，默认关闭，由调用方显式开启
    allow_tts: bool = False


class DeviceMessageCreateRequest(BaseModel):
    """手动注入一条下行消息（第一版触发源：不接规则也不接 Agent）。"""

    message_type: str = "REMINDER_SIGNAL"
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_schema_ref: str = Field(default="rme.reminder-signal.draft", max_length=128)
    priority: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"
    delivery_policy: DeliveryPolicy = Field(default_factory=DeliveryPolicy)
    # 不传则用 config.device_message_ttl_seconds
    ttl_seconds: int | None = Field(default=None, ge=1, le=86400)

    @model_validator(mode="after")
    def _known_type(self) -> DeviceMessageCreateRequest:
        if self.message_type not in DEVICE_MESSAGE_TYPES:
            raise ValueError(
                f"未知消息类型：{self.message_type}（可用：{list(DEVICE_MESSAGE_TYPES)}）"
            )
        return self


class DeviceMessageOut(BaseModel):
    """下行信封，同时是 WebSocket 推送的报文体。"""

    schema_ref: str = DEVICE_MESSAGE_SCHEMA_REF
    message_id: uuid.UUID
    target_device_id: uuid.UUID
    message_type: str
    created_at: datetime
    expires_at: datetime
    priority: str
    payload_schema_ref: str
    payload: dict[str, Any]
    delivery_policy: DeliveryPolicy
    # 服务端投递状态（设备侧不需要，用于本机调试与前端观测）
    status: str
    last_receipt_status: str | None = None

    @classmethod
    def of(cls, msg: Any) -> DeviceMessageOut:
        return cls(
            message_id=msg.id,
            target_device_id=msg.target_device_id,
            message_type=msg.message_type,
            created_at=msg.created_at,
            expires_at=msg.expires_at,
            priority=msg.priority,
            payload_schema_ref=msg.payload_schema_ref,
            payload=msg.payload or {},
            delivery_policy=DeliveryPolicy(allow_text=msg.allow_text, allow_tts=msg.allow_tts),
            status=msg.status,
            last_receipt_status=msg.last_receipt_status,
        )


class DeviceMessageCreateResponse(BaseModel):
    message: DeviceMessageOut
    # 本次创建时在线并已即时推送的连接数；0 表示落库等设备来拉（inbox 或重连补投）
    pushed_connections: int = 0


class DeviceInboxResponse(BaseModel):
    """轮询兜底（§5.3 首版通道）：返回未终态且未过期的消息。"""

    messages: list[DeviceMessageOut] = Field(default_factory=list)
    expired: int = 0


class DeliveryReceiptIn(BaseModel):
    message_id: uuid.UUID
    status: str
    detail: dict[str, Any] = Field(default_factory=dict)
    device_reported_at: datetime | None = None

    @model_validator(mode="after")
    def _known_status(self) -> DeliveryReceiptIn:
        if self.status not in DELIVERY_RECEIPT_STATUSES:
            raise ValueError(
                f"未知回执状态：{self.status}（可用：{list(DELIVERY_RECEIPT_STATUSES)}）"
            )
        return self


class DeliveryReceiptOut(BaseModel):
    message_id: uuid.UUID
    status: str
    # 该 (message_id, status) 之前已上报过：幂等重放，未产生第二条终态
    duplicate: bool = False
    message_status: str


# ---------------------------------------------------------------- 采集请求（CAPTURE_REQUEST）
#
# 通信架构 §8 的硬约束：「云端消息不能绕过眼镜本地策略远程强制打开相机或麦克风。
# 未来若增加『请求现场确认』，也只能生成需要用户确认或本地策略允许的 CaptureIntent，
# 不能直接调用媒体 API。」
#
# 所以这里建模的是**请求**不是命令：云端表达「希望采一次」，设备端做本地 PolicyCheck
# （会话状态、佩戴、权限、隐私暂停、采集预算）后自行决定执行或拒绝，并用
# EXECUTED / REJECTED 回执把结果告诉云端。云端拿不到「强制执行」这个动作。

CAPTURE_REQUEST_SCHEMA_REF = "rme.capture-request.v0"

CAPTURE_ACTIONS = (
    "CAPTURE_PHOTO",     # 请求一张代表图
    "CAPTURE_AUDIO",     # 请求一段定长短音频
    "START_PERIODIC",    # 请求开启周期采集会话
    "PAUSE",             # 请求暂停当前会话的新采集
    "RESUME",            # 请求恢复采集
    "STOP",              # 请求结束会话并清理
)

# 设备控制通道。adb=后端在本机通过 USB 转成 intent（联调期，后端必须与眼镜同机）；
# inbox=落库等设备自己来拉（架构目标形态，脱离 USB）。
CONTROL_TRANSPORTS = ("adb", "inbox")


class CaptureRequestCreate(BaseModel):
    """从控制台下发一次采集请求。"""

    action: str
    # START_PERIODIC 专用：周期采集间隔
    interval_seconds: int | None = Field(default=None, ge=5, le=3600)
    # CAPTURE_AUDIO 专用：录制时长
    duration_seconds: int | None = Field(default=None, ge=1, le=300)
    # 触发理由，进审计与 CaptureIntent.trigger，便于事后区分人工采集与自动采集
    reason: str = Field(default="operator_console", max_length=64)
    ttl_seconds: int | None = Field(default=None, ge=1, le=86400)
    # 覆盖设备默认通道（联调时在同一台设备上对比 adb 与 inbox 两条链路）
    transport: str | None = None

    @model_validator(mode="after")
    def _check(self) -> CaptureRequestCreate:
        if self.action not in CAPTURE_ACTIONS:
            raise ValueError(f"未知采集动作：{self.action}（可用：{list(CAPTURE_ACTIONS)}）")
        if self.transport is not None and self.transport not in CONTROL_TRANSPORTS:
            raise ValueError(
                f"未知控制通道：{self.transport}（可用：{list(CONTROL_TRANSPORTS)}）"
            )
        # 参数与动作不匹配时直接拒绝，而不是静默忽略——静默忽略会让控制台以为
        # 「我设了 5 秒间隔」，设备却按默认 30 秒采，事后对不上账。
        if self.interval_seconds is not None and self.action != "START_PERIODIC":
            raise ValueError("interval_seconds 只对 START_PERIODIC 有效")
        if self.duration_seconds is not None and self.action != "CAPTURE_AUDIO":
            raise ValueError("duration_seconds 只对 CAPTURE_AUDIO 有效")
        return self

    def to_payload(self) -> dict[str, Any]:
        """转成 rme.capture-request.v0 载荷（设备端据此构造本地 CaptureIntent）。"""
        return {
            "schema_ref": CAPTURE_REQUEST_SCHEMA_REF,
            "action": self.action,
            "interval_seconds": self.interval_seconds,
            "duration_seconds": self.duration_seconds,
            "trigger": self.reason,
            # 设备端必须把它当作请求：本地策略优先，拒绝走 REJECTED 回执而不是静默丢弃
            "requires_local_policy_check": True,
        }


class DispatchOut(BaseModel):
    """一次分发的结果。accepted 只代表「命令送出去了」，不代表设备执行了。"""

    transport: str
    accepted: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class CaptureRequestOut(BaseModel):
    message: DeviceMessageOut
    dispatch: DispatchOut
    # inbox 通道下本次即时推送到的长连数；adb 通道恒为 0
    pushed_connections: int = 0


class ReceiptRecord(BaseModel):
    """已收到的一条回执。控制台靠 detail 区分「策略拒绝」和「链路坏了」。"""

    status: str
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    device_reported_at: datetime | None = None

    @classmethod
    def of(cls, receipt: Any) -> ReceiptRecord:
        return cls(
            status=receipt.status,
            detail=receipt.detail or {},
            created_at=receipt.created_at,
            device_reported_at=receipt.device_reported_at,
        )


class CaptureRequestRecord(BaseModel):
    """历史采集请求条目（控制台轮询用）。"""

    message: DeviceMessageOut
    action: str
    transport: str
    receipts: list[ReceiptRecord] = Field(default_factory=list)


class CaptureRequestListResponse(BaseModel):
    requests: list[CaptureRequestRecord] = Field(default_factory=list)


class DeviceOut(BaseModel):
    """设备列表项：控制台据此选择目标设备与通道。"""

    device_id: uuid.UUID
    kind: str
    name: str
    runtime_package: str | None = None
    control_transport: str = "inbox"

    @classmethod
    def of(cls, device: Any) -> DeviceOut:
        return cls(
            device_id=device.id,
            kind=device.kind,
            name=device.name,
            runtime_package=device.runtime_package,
            control_transport=device.control_transport or "inbox",
        )


class DeviceListResponse(BaseModel):
    devices: list[DeviceOut] = Field(default_factory=list)


class DeviceBindingUpdate(BaseModel):
    """绑定设备到某个眼镜 App 运行时与控制通道（不然 connector 不知道往哪发）。"""

    runtime_package: str | None = Field(default=None, max_length=128)
    control_transport: str | None = None

    @model_validator(mode="after")
    def _check(self) -> DeviceBindingUpdate:
        if self.control_transport is not None and self.control_transport not in CONTROL_TRANSPORTS:
            raise ValueError(
                f"未知控制通道：{self.control_transport}（可用：{list(CONTROL_TRANSPORTS)}）"
            )
        return self
