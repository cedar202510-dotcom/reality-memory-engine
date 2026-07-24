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
