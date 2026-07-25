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
    # 答案出自哪一帧。「最后一次看到在办公桌上」这句话，配上那张照片才算说完——
    # 用户认得出自己那张桌子，认不出一句位置描述对不对。
    frame_asset_id: uuid.UUID | None = None
    evidence_available: bool = False       # 原图是否还在（TTL 到期后为 False，但答案仍有效）
    # 原始媒体默认不给 Agent（§5，同 scene-search）：带 token 的调用永远拿不到这个字段
    evidence_url: str | None = None
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
    # 这条记忆出自哪一帧（顺 source_candidate_ids → observation_ids 追溯的来源，
    # 不是相似度猜的）。纠正类事件没有来源帧，为 null。
    frame_asset_id: uuid.UUID | None = None
    # 帧记录还在但字节已被保留期删除时为 False——不是加载失败。
    # evidence_url 只给 owner 直通（§5：原始媒体默认不暴露给 Agent）。
    evidence_available: bool = False
    evidence_url: str | None = None


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


# ---------------------------------------------------------------- 喜好度洞察（跨模态融合）
#
# 上面的 /preferences 回答「关于 X 你说过什么」，是一次检索。
# 下面这组回答「你对什么有态度、有多强」，是一次聚合——四路证据融合成一个可解释的分数。

AFFINITY_CHANNELS = ("verbal", "intent", "behavior", "attention")

AFFINITY_LEVELS = (
    "强烈喜欢",
    "喜欢",
    "中性",
    "不喜欢",
    "强烈不喜欢",
    "证据不足",
)


class AffinityChannelOut(BaseModel):
    """单通道得分。前端靠它把总分拆开解释，而不是甩一个不知从哪来的数字。"""

    channel: str                           # verbal/intent/behavior/attention
    label: str                             # 中文名，前端直接用
    value: float                           # -1~1
    weight: float                          # 该通道在本次融合中的实际权重
    evidence_count: int


class AffinityEvidenceOut(BaseModel):
    """一条可回溯的证据（原话/任务/使用记录）。"""

    kind: str                              # verbal/intent/behavior
    text: str
    at: datetime | None = None
    event_id: uuid.UUID | None = None
    confidence: float = 0.5
    superseded: bool = False


class PreferenceInsightOut(BaseModel):
    entity: EntityRef
    score: int = Field(ge=0, le=100, description="喜好度 0~100，50 为中性")
    level: str
    polarity: float = Field(ge=-1.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, description="证据充分程度，低于阈值时 level=证据不足")
    channels: list[AffinityChannelOut] = Field(default_factory=list)
    evidence: list[AffinityEvidenceOut] = Field(default_factory=list)
    use_count: int = 0
    frame_count: int = 0
    dwell_seconds: float = 0.0
    pending_count: int = Field(default=0, description="还在候选门里等人确认的相关线索数")
    last_signal_at: datetime | None = None


class PreferenceInsightsResponse(BaseModel):
    items: list[PreferenceInsightOut] = Field(default_factory=list)
    total: int = 0
    generated_at: datetime
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


# ---------------------------------------------------------------- 采集媒体总览
#
# 这是「翻看采集到了什么」的读侧视图，直接建在 evidence_items 上，而不是 frame_assets：
# 后者只有走完 VLM 感知的图片才有行，看不到音频、看不到还在排队的、更看不到视频。
# 要回答「我刚才采的东西呢」，必须从证据本身出发。
#
# 原始媒体有 TTL，过期物理删除但记录保留。所以列表里一定会出现「有记录、没文件」的条目，
# 这不是错误状态，而是隐私设计的正常结果，UI 必须能表达它。

MEDIA_KINDS = ("image", "audio", "video", "sensor")

# 感知状态。三个「没有结果」的状态必须分开，因为它们的含义和处理方式完全不同：
#   PENDING     还在排队，等一等会有
#   UNSUPPORTED 传感器只可靠落盘，没有解析器，永远不会有 caption 或转写——等下去是白等。
#               （视频曾经也在这一档，自 video.process 起不是了：它会被拆成关键帧 + 音轨，
#                 两路都有解析器，所以未完成的视频是 PENDING。）
#   ABANDONED   原始字节已被 TTL 删除而解析从未完成，解析器再也没有输入可读，
#               同样永远不会有结果
# 混成一个 PENDING 会让人对着一堆永远不会完成的条目一直等。
MEDIA_PERCEPTION_STATES = ("READY", "PENDING", "UNSUPPORTED", "ABANDONED")


class MediaItemOut(BaseModel):
    evidence_item_id: uuid.UUID
    media_kind: str
    # 服务端摄入时间；captured_at 是设备端拍摄时间（只有解析出资产后才知道）
    created_at: datetime
    captured_at: datetime | None = None
    ttl_until: datetime
    retention_state: str
    perception_state: str
    # 原始字节是否还在（TTL 删除后为 false，但下面的派生字段仍然有效）
    available: bool
    raw_url: str | None = None
    # 实际 Content-Type，UI 据此决定用 <img> / <audio> / <video> 还是只给下载
    media_type: str | None = None
    # 图片派生
    frame_asset_id: uuid.UUID | None = None
    caption: str | None = None
    scene_tags: list[str] = Field(default_factory=list)
    # 音频派生
    audio_asset_id: uuid.UUID | None = None
    transcript: str | None = None
    language: str | None = None
    duration_seconds: float | None = None


class MediaListResponse(BaseModel):
    items: list[MediaItemOut] = Field(default_factory=list)
    # 满足过滤条件的总数（不受 limit/offset 影响），用于分页与「共 N 条」
    total: int = 0
    limit: int = 0
    offset: int = 0


# ---------------------------------------------------------------- 记忆浏览读侧
#
# where-is 是「问一件事」，这里是「翻记忆本身」：事件流、物品分布、待确认线索。
# 三者都不经 LLM——直接把 memory_events / state_projections / memory_candidates
# 投成界面能画的形状。答案是确定性的，刷新两次结果一样，这对「记忆是否可信」很重要。


class MemoryEventEntry(BaseModel):
    """事件流里的一条。location 从 payload 提到顶层，因为界面主要就显示它。"""

    event_id: uuid.UUID
    entity_id: uuid.UUID | None = None
    entity_name: str | None = None
    event_type: str
    event_time_from: datetime
    accepted_at: datetime
    location: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    # 被后续事件取代（典型是用户纠正覆盖了它）。取代不删除历史，所以列表里仍然出现，
    # UI 要把它画成「已被更新」而不是当前事实——否则界面会同时展示两个互相矛盾的位置。
    superseded: bool = False
    # 人拍板的事件（用户确认线索 / 用户纠正），跟模型自动接受的要能分开
    user_confirmed: bool = False
    # 这条记忆出自哪一帧。顺 source_candidate_ids → observation_ids → frame_asset_id 追溯，
    # 是**来源**而不是相似度猜的——同一个物体在别的帧里也出现过，但只有这一帧生成了这条事件。
    # USER_CORRECTION 没有来源帧（它不出自任何画面），这里就是 null。
    frame_asset_id: uuid.UUID | None = None
    # 原始媒体默认不给 Agent（§5）：只有 owner 直通才有 evidence_url。
    # evidence_available=False 表示帧记录还在但字节已被保留期删除——不是加载失败。
    evidence_available: bool = False
    evidence_url: str | None = None


class MemoryEventsResponse(BaseModel):
    events: list[MemoryEventEntry] = Field(default_factory=list)
    total: int = 0


# 实体粗分类。这一刀切的是「这是不是一件你会去找的东西」，而不是数码/日用那种品类：
# 感知会把 人、手臂、木地板、墙面、空调 一并认成实体，它们在品类表里无处可放，硬塞
# 进「其他」只会让「其他」变成垃圾桶。先按「找得找不得」分，全览和找物默认只看 PORTABLE。
#
# 类别是**推断**出来的，不像位置是**观察**到的——所以它跟别的推断一样要带来源、可纠正，
# UNCLASSIFIED 是诚实的「还没判」，不是兜底垃圾桶。
ENTITY_CATEGORIES = (
    "PORTABLE",       # 随身/可移动物品：手机、充电线、钥匙、茶杯——「我的东西在哪」关心的那批
    "FIXTURE",        # 场景固定物：地板、墙面、窗帘、空调、桌子本身
    "PERSON",         # 人与身体部位：人、手臂、人手
    "CONSUMABLE",     # 食物与耗材：包子、汤面、纸巾
    "UNCLASSIFIED",   # 还没判或判不了
)

# 类别是谁定的。用户改过的绝不能被后续自动分类覆盖。
CATEGORY_SOURCES = ("llm", "user", "unset")


class ObjectNodeOut(BaseModel):
    """一件物品的当前状态。location 为空表示有观察但没解析出位置。"""

    entity_id: uuid.UUID
    canonical_name: str
    aliases: list[Any] = Field(default_factory=list)
    entity_class: str = "instance"
    location: str | None = None
    last_seen_time: datetime | None = None
    confidence: float = 0.0
    event_count: int = 0
    corrected: bool = False
    # 推断出来的粗分类；category_source 说明是模型判的还是你改的
    category: str = "UNCLASSIFIED"
    category_source: str = "unset"
    # 这件东西的实拍缩略图（检测框裁出来的那一块）。为空 = 没检出/没装检测器/原件已过期，
    # 前端退回纯色球——不给占位图，因为占位图会让「没拍到」看起来像「拍到了但长这样」。
    thumb_url: str | None = None


class ObjectGroupOut(BaseModel):
    """同一位置上的物品。全览里的连线就是这个分组，不是别的语义。"""

    location: str
    entity_ids: list[uuid.UUID] = Field(default_factory=list)


class ObjectGraphResponse(BaseModel):
    nodes: list[ObjectNodeOut] = Field(default_factory=list)
    # 只含 2 件以上物品的位置：一件物品自己不构成「放在一起」，给它画组会让图里全是孤环
    groups: list[ObjectGroupOut] = Field(default_factory=list)
    total: int = 0


class MemoryClueOut(BaseModel):
    """待确认线索：候选门没敢自动接受的记忆，等人拍板。

    PENDING = 置信度不够阈值；CONFLICTED = 同一物体撞上了位置不兼容的另一个候选。
    两者都要能确认，但界面得说清是哪一种——「不太确定」和「跟别的记忆打架」
    对用户来说是完全不同的问题。
    """

    candidate_id: uuid.UUID
    entity_id: uuid.UUID | None = None
    object_text: str
    location: str | None = None
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    status: str
    # perception=采集时看到的；query=问答时从画面里推出来的
    source: str
    created_at: datetime
    conflict_set_id: uuid.UUID | None = None
    # 线索出自哪一帧。原始媒体默认不给 Agent（§5），只有 owner 直通才有 evidence_url
    frame_asset_id: uuid.UUID | None = None
    frame_caption: str | None = None
    evidence_available: bool = False
    evidence_url: str | None = None


class MemoryCluesResponse(BaseModel):
    clues: list[MemoryClueOut] = Field(default_factory=list)
    total: int = 0


class ClueResolveRequest(BaseModel):
    """确认或忽略一条线索。确认绕过置信度阈值——人的拍板不需要凑够分数。"""

    decision: Literal["CONFIRM", "REJECT"]
    reason: str = ""


class ClueResolveResponse(BaseModel):
    candidate_id: uuid.UUID
    status: str
    event_id: uuid.UUID | None = None
    entity_id: uuid.UUID | None = None
    projection: dict[str, Any] | None = None
    # 确认一条线索会顺带把同冲突集里的其它候选判为 REJECTED（冲突由用户一次解决）
    rejected_sibling_ids: list[uuid.UUID] = Field(default_factory=list)


# ---------------------------------------------------------------- 下行：设备消息与回执
#
# 注意：这里只冻结通用信封字段（通信架构 §5.2 `rme.device-message.v0`）。
# payload 内的眼镜呈现已由 `rme.glasses-presentation.v0` 约束；其它 REMINDER_SIGNAL
# 草稿载荷仍不能当成已冻结的 v1 业务契约。

DEVICE_MESSAGE_SCHEMA_REF = "rme.device-message.v0"
GLASSES_PRESENTATION_SCHEMA_REF = "rme.glasses-presentation.v0"

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


class GlassesPresentationInteraction(BaseModel):
    """用户可执行的单一主动作；显示文案和图标由眼镜本地映射。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal[
        "DISMISS",
        "ACKNOWLEDGE",
        "COMPLETE_TASK",
        "ADD_TO_SHOPPING_LIST",
    ]
    action_id: str = Field(min_length=1, max_length=128)


class GlassesPresentationContent(BaseModel):
    """眼镜本地固定组件需要的最小语义，不允许后端下发自由样式。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: Literal[
        "ANSWER",
        "REMINDER",
        "TASK",
        "CONSUMABLE",
        "PRIVACY",
        "SYSTEM",
    ]
    title: str = Field(min_length=1, max_length=42)
    body: str | None = Field(default=None, max_length=80)
    speech_text: str | None = Field(default=None, max_length=100)
    interaction: Literal["NONE"] | GlassesPresentationInteraction


class GlassesPresentationSource(BaseModel):
    """产生消息的受约束来源；系统状态不能被普通 Agent 冒充。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    kind: Literal["AGENT_REPLY", "MEMORY_SIGNAL", "SYSTEM_POLICY"]
    reference_id: str | None = Field(default=None, max_length=128)


class GlassesPresentationPayload(BaseModel):
    """`rme.glasses-presentation.v0` 业务载荷。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    presentation: GlassesPresentationContent
    source: GlassesPresentationSource
    correlation_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _source_may_emit_intent(self) -> GlassesPresentationPayload:
        allowed_sources = {
            "ANSWER": {"AGENT_REPLY"},
            "REMINDER": {"AGENT_REPLY", "MEMORY_SIGNAL"},
            "TASK": {"AGENT_REPLY", "MEMORY_SIGNAL"},
            "CONSUMABLE": {"MEMORY_SIGNAL"},
            "PRIVACY": {"SYSTEM_POLICY"},
            "SYSTEM": {"SYSTEM_POLICY"},
        }
        intent = self.presentation.intent
        source = self.source.kind
        if source not in allowed_sources[intent]:
            raise ValueError(f"{source} 不能生成 {intent} 眼镜消息")

        interaction = self.presentation.interaction
        interaction_type = (
            interaction if isinstance(interaction, str) else interaction.type
        )
        allowed_interactions = {
            "ANSWER": {"NONE"},
            "REMINDER": {"NONE", "ACKNOWLEDGE"},
            "TASK": {"NONE", "COMPLETE_TASK"},
            "CONSUMABLE": {"NONE", "ADD_TO_SHOPPING_LIST"},
            "PRIVACY": {"NONE", "DISMISS", "ACKNOWLEDGE"},
            "SYSTEM": {"NONE", "DISMISS", "ACKNOWLEDGE"},
        }
        if interaction_type not in allowed_interactions[intent]:
            raise ValueError(f"{intent} 不允许使用 {interaction_type} 用户动作")
        return self


class DeviceMessageCreateRequest(BaseModel):
    """创建一条下行消息；人工调试与受限 Agent 入口共用此业务契约。"""

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
        if self.payload_schema_ref == GLASSES_PRESENTATION_SCHEMA_REF:
            if self.message_type != "REMINDER_SIGNAL":
                raise ValueError(
                    "rme.glasses-presentation.v0 当前只能使用 REMINDER_SIGNAL 外层类型"
                )
            presentation = GlassesPresentationPayload.model_validate(self.payload)
            if not self.delivery_policy.allow_text and not self.delivery_policy.allow_tts:
                raise ValueError("眼镜呈现消息必须至少允许文字或 TTS 之一")
            if (
                not self.delivery_policy.allow_text and
                not presentation.presentation.speech_text
            ):
                raise ValueError("只允许 TTS 时必须提供 speech_text")
            if not self.delivery_policy.allow_tts:
                presentation.presentation.speech_text = None
            self.payload = presentation.model_dump(mode="json", exclude_none=True)
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

# 设备类型（04 §5.1）。这不是能力声明——耳机能不能录音、眼镜能不能拍照，由设备侧
# Collector 自己回答（不支持的动作走 REJECTED 回执），后端不按 kind 猜设备能做什么。
# earbuds：蓝牙耳机，采集与播报都由宿主侧 Collector 代跑（apps/iflybuds-collector）。
DEVICE_KINDS = ("glasses", "ring", "phone", "earbuds")


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


class DeviceRegisterIn(BaseModel):
    """设备自注册（04 §5.5 第 4 步：后端注册设备、下发 device_id）。

    按 name 幂等：采集器每次启动都可以调一次而不会攒出一堆同名设备。名字是人给的，
    也是控制台上唯一能认出「这是我桌上那副耳机」的东西，所以它就是幂等键。
    """

    kind: str
    name: str = Field(min_length=1, max_length=128)
    # 耳机这类没有 Android 包名的设备，这里放 collector 标识（如
    # iflybuds-host-collector/0.1.0），控制台据此知道对面跑的是什么运行时。
    runtime_package: str | None = Field(default=None, max_length=128)
    control_transport: str | None = None

    @model_validator(mode="after")
    def _check(self) -> DeviceRegisterIn:
        if self.kind not in DEVICE_KINDS:
            raise ValueError(f"未知设备类型：{self.kind}（可用：{list(DEVICE_KINDS)}）")
        if self.control_transport is not None and self.control_transport not in CONTROL_TRANSPORTS:
            raise ValueError(
                f"未知控制通道：{self.control_transport}（可用：{list(CONTROL_TRANSPORTS)}）"
            )
        return self


class TranscribeResponse(BaseModel):
    """一次性语音转写的结果（在场页把话变成字用）。

    这里**没有** evidence_item_id / audio_asset_id：这段音频不入库，转写完就丢。
    对着界面问一句话不等于授权把自己的声音存进记忆库，两件事必须分开授权。
    """

    text: str = Field(description="整段转写文本（各分段拼接）")


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
