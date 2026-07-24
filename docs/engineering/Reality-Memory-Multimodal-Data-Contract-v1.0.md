# Reality Memory Engine 多模态数据契约 v1.0

状态：当前正式 v1 契约，可供采集端与结构化沉淀端并行开发
适用范围：Rokid 眼镜原生 App、后端接入层、模态解析器、时间融合、记忆核心
不含范围：云端下行设备消息、提醒业务载荷和 Agent 提醒决策
机器契约：`contracts/reality-memory/v1/`

## 1. 这份契约解决什么

本契约把两支开发工作明确分开：

| 责任方 | 负责到哪里 | 明确不负责什么 |
| --- | --- | --- |
| 眼镜采集端 | 佩戴会话、采集触发、图片/短视频/短音频/IMU、加密队列、上传与删除回执 | 不判断用户在做什么，不生成偏好、任务或事实 |
| 后端结构化沉淀端 | 校验、解析、跨模态对齐、活动分段、候选事实、事实事件、当前状态 | 不把原始模型输出直接当事实，不长期依赖原始媒体 |

完整链路：

```text
CaptureSession（采集会话）
  -> CaptureWindow（采集窗口）
  -> SourceEnvelope（来源信封）
  -> EvidenceItem（短暂证据）
  -> AtomicObservation（原子观察）
  -> ObservationBundle（观察包）
  -> ActivityEpisode（活动段）
  -> MemoryCandidate（记忆候选）
  -> MemoryEvent（记忆事实事件）
  -> StateProjection（当前状态）
```

其中，眼镜端的交付边界止于 `EvidenceItem` 上传完成。`AtomicObservation` 及之后
全部属于后端。

## 2. 五条不可破坏的原则

1. `MemoryEvent` 是唯一持久事实源。模型输出、活动分段和当前状态都不是事实源。
2. 原始媒体是有 TTL 的短暂证据，完成结构化或到期后必须删除。
3. 一次头动阈值命中只是 `CaptureIntent`（采集意图），不表示用户看见、拿起或做了什么。
4. 多模态关联必须依靠同一 `capture_window_id` 和双时间标尺，不能只靠文件名或到达顺序。
5. 所有解析、筛选、融合和记忆判断必须保留版本、输入引用、置信度和可撤销关系。

## 3. 统一标识和时间

### 3.1 标识

所有标识均由产生对象的一侧生成，并在其生命周期内不可更改：

| 字段 | 含义 | 示例 |
| --- | --- | --- |
| `device_id` | 已绑定设备的稳定匿名标识 | `glass_01J...` |
| `capture_session_id` | 一次佩戴并允许记忆的采集会话 | `ses_01J...` |
| `capture_window_id` | 同一触发前后的一组多模态证据 | `win_01J...` |
| `capture_intent_id` | 为什么发起这次采集 | `cin_01J...` |
| `source_envelope_id` | 一条来源输入的统一信封 | `src_01J...` |
| `evidence_item_id` | 一项短期证据 | `evd_01J...` |
| `observation_id` | 一条最小结构化观察 | `obs_01J...` |
| `bundle_id` | 同一现实变化的观察集合 | `bun_01J...` |
| `activity_episode_id` | 一段可修订的现实活动 | `epi_01J...` |
| `memory_candidate_id` | 尚未成为事实的候选断言 | `can_01J...` |
| `memory_event_id` | 追加式事实变化 | `mem_01J...` |

推荐使用 UUIDv7 或 ULID。服务端不得通过重新生成 ID 来修复重复上传，应使用
`idempotency_key` 返回原结果。

### 3.2 双时间标尺

每条来源数据必须同时带：

- `occurred_at`：UTC RFC 3339 时间，用于跨设备和用户时间线。
- `monotonic_start_ns` / `monotonic_end_ns`：设备启动后的单调时钟，用于同设备内精确排序和计算时长。
- `clock_domain`：例如 `ANDROID_ELAPSED_REALTIME_NANOS`。
- `clock_sync_method`：例如 `ANDROID_SYSTEM_CLOCK_ANCHOR`。
- `time_uncertainty_ms`：当前绝对时间估计误差，不允许省略后假装精确。

媒体时间段使用半开区间 `[start, end)`。单张图片的开始和结束可以相同。后端不得
用上传到达时间覆盖采集发生时间。

正式采集端必须填写单调时钟。历史测试夹具如果原实现没有记录，可以显式使用
`null`，同时令 `clock_sync_method=LEGACY_IMPORT` 并在 `extensions` 标明缺失原因；
禁止用 `0` 或上传时间伪造。接入生产队列时仍应拒绝新设备产生的空单调时间。

## 4. 采集端契约

### 4.1 CaptureSession：采集会话

`CaptureSession` 表示一次用户允许设备感知现实的设备窗口，通常从佩戴后提示开始，
在摘下、折叠、用户暂停后结束或进入暂停。

它不是“吃饭”“阅读”这类现实活动。

关键字段：

```json
{
  "schema_ref": "rme.capture-session.v1",
  "capture_session_id": "ses_01J...",
  "device_id": "glass_01J...",
  "state": "ACTIVE",
  "started_at": "2026-07-24T06:20:10.123Z",
  "started_monotonic_ns": 78422100123000,
  "ended_at": null,
  "ended_monotonic_ns": null,
  "start_reason": "WEAR_CONFIRMED",
  "end_reason": null,
  "policy_snapshot_id": "pol_01J...",
  "consent_notice_version": "wear-notice/1.0",
  "runtime_version": "android-glasses/0.1.0"
}
```

允许状态：

- `ARMED`：运行时在等待佩戴，相机、麦克风和 IMU 不工作。
- `DISCLOSURE`：正在向用户显示或播报本次佩戴提示。
- `ACTIVE`：允许按策略产生证据。
- `PAUSED`：用户暂停，不得开始新的媒体采集。
- `BLOCKED`：权限、隐私策略、温度或资源条件阻止采集。
- `ENDED`：会话结束。

### 4.2 CaptureIntent：采集意图

`CaptureIntent` 是端侧策略生成的一次客观触发判断。它解释“为什么尝试采集”，
但不是证据，也不是事实。

首版头动触发示例：

```json
{
  "schema_ref": "rme.capture-intent.v1",
  "capture_intent_id": "cin_01J...",
  "capture_session_id": "ses_01J...",
  "signal_kind": "HEAD_MOTION_TRANSITION",
  "occurred_at": "2026-07-24T06:21:02.410Z",
  "monotonic_start_ns": 78474380000000,
  "monotonic_end_ns": 78475740000000,
  "detector_rule_version": "glasses-head-transition.v1",
  "intensity": "MEDIUM",
  "metrics": {
    "duration_ms": 1360,
    "integrated_rotation_deg": 21.4,
    "peak_gyro_rad_s": 0.91,
    "max_gravity_tilt_deg": 12.8
  },
  "requested_modalities": ["IMAGE", "AUDIO", "SENSOR"],
  "extensions": {}
}
```

首版允许的 `signal_kind`：

- `HEAD_MOTION_TRANSITION`
- `WEAR_CONFIRMED`
- `USER_EXPLICIT`
- `VOICE_ACTIVITY`，仅在 VAD 真机验证完成后启用
- `DEBUG_TEST`，只能在显式调试策略中使用

不得出现 `PICKED_UP_CUP`、`STARTED_EATING`、`LOOKED_AT_KEYS` 等语义行为名称。

### 4.3 CaptureWindow：采集窗口

`CaptureWindow` 是多模态对齐的核心。一次触发产生的一张图片、一段短视频、
一段短音频和一个 IMU 窗口必须共享同一个 `capture_window_id`。

```json
{
  "schema_ref": "rme.capture-window.v1",
  "capture_window_id": "win_01J...",
  "capture_session_id": "ses_01J...",
  "capture_intent_id": "cin_01J...",
  "window_start": "2026-07-24T06:20:58.410Z",
  "window_end": "2026-07-24T06:21:12.410Z",
  "monotonic_start_ns": 78470380000000,
  "monotonic_end_ns": 78484380000000,
  "requested_modalities": ["IMAGE", "AUDIO", "SENSOR"],
  "policy_snapshot_id": "pol_01J...",
  "state": "FINALIZED"
}
```

一个窗口可以缺少某种媒体，但必须有对应 `CaptureAttempt` 说明是失败、被策略跳过，
还是设备不支持。

### 4.4 CaptureAttempt：采集尝试

每种模态每次尝试写一条审计记录。即使没有生成文件也要保留：

```json
{
  "schema_ref": "rme.capture-attempt.v1",
  "capture_attempt_id": "att_01J...",
  "capture_window_id": "win_01J...",
  "modality": "VIDEO",
  "requested_at": "2026-07-24T06:21:02.420Z",
  "result": "SKIPPED",
  "reason_code": "CAMERA_BUSY",
  "latency_ms": 4,
  "evidence_item_id": null,
  "runtime_version": "android-glasses/0.1.0"
}
```

`result` 允许：

- `SUCCEEDED`
- `FAILED`
- `SKIPPED`
- `CANCELLED`

首版统一原因码：

- `POLICY_BLOCKED`
- `USER_PAUSED`
- `NOT_WORN`
- `PERMISSION_MISSING`
- `CAMERA_BUSY`
- `MICROPHONE_BUSY`
- `THERMAL_LIMIT`
- `STORAGE_LIMIT`
- `DEVICE_UNAVAILABLE`
- `FINALIZE_FAILED`
- `TTL_EXPIRED`

### 4.5 SourceEnvelope：来源信封

每一项输入都用 `SourceEnvelope` 包装。它只描述来源、时间、策略和载荷引用。

```json
{
  "schema_ref": "rme.source-envelope.v1",
  "source_envelope_id": "src_01J...",
  "device_id": "glass_01J...",
  "device_kind": "ROKID_GLASSES_RV101",
  "device_adapter": "rokid-native-android/1.0",
  "capture_session_id": "ses_01J...",
  "capture_window_id": "win_01J...",
  "capture_intent_id": "cin_01J...",
  "occurred_at": "2026-07-24T06:21:03.000Z",
  "observed_at": "2026-07-24T06:21:03.188Z",
  "monotonic_start_ns": 78474970000000,
  "monotonic_end_ns": 78474970000000,
  "clock_domain": "ANDROID_ELAPSED_REALTIME_NANOS",
  "clock_sync_method": "ANDROID_SYSTEM_CLOCK_ANCHOR",
  "time_uncertainty_ms": 50,
  "policy_snapshot_id": "pol_01J...",
  "modality": "IMAGE",
  "payload_kind": "EVIDENCE_ITEM",
  "payload_ref": "evd_01J...",
  "idempotency_key": "evd_01J...",
  "extensions": {
    "firmware_build": "to-be-collected"
  }
}
```

`modality` 允许：

- `IMAGE`
- `VIDEO`
- `AUDIO`
- `SENSOR`
- `DEVICE_EVENT`
- `USER_INPUT`
- `ONLINE_CONTEXT`

`ONLINE_CONTEXT` 用于未来接入订单、日历等授权数据，不能伪装成眼镜证据。
这类异步线上来源可以令 `capture_session_id`、`capture_window_id` 和
`capture_intent_id` 为 `null`，但仍必须有稳定来源身份、授权策略、发生时间和幂等键。

### 4.6 EvidenceItem：短暂证据

`EvidenceItem` 是不可变的证据元数据。上传状态、处理状态和删除状态通过独立
`EvidenceLifecycleEvent` 追加，不直接改写原记录。

生产证据只允许 `AES_256_GCM`。仓库中经用户明确授权的历史测试数据可使用
`NONE_TEST_FIXTURE`，但必须处于测试数据命名空间、`debug_sample=true`，且生产接入
令牌不得上传这种对象。

通用字段：

```json
{
  "schema_ref": "rme.evidence-item.v1",
  "evidence_item_id": "evd_01J...",
  "source_envelope_id": "src_01J...",
  "capture_window_id": "win_01J...",
  "modality": "IMAGE",
  "mime_type": "image/jpeg",
  "captured_at": "2026-07-24T06:21:03.000Z",
  "duration_ms": 0,
  "byte_count": 428112,
  "sha256": "hex-encoded-sha256",
  "encryption": {
    "algorithm": "AES_256_GCM",
    "key_ref": "device-key-wrapped-dek-id",
    "iv_base64": "base64-value"
  },
  "retention": {
    "ttl_expires_at": "2026-07-24T06:36:03.000Z",
    "purpose": "STRUCTURE_EXTRACTION",
    "debug_sample": false
  },
  "media": {},
  "sensitivity_labels": [],
  "extensions": {}
}
```

图片 `media`：

```json
{
  "codec": "JPEG",
  "width_px": 1920,
  "height_px": 1080,
  "orientation_deg": 0,
  "camera_facing": "WORLD",
  "capture_mode": "CAMERAX_IMAGE_CAPTURE_NO_PREVIEW",
  "jpeg_quality": 100
}
```

短视频 `media`：

```json
{
  "container": "MP4",
  "video_codec": "UNKNOWN_UNTIL_PROBED",
  "width_px": 1280,
  "height_px": 720,
  "frame_rate_fps": null,
  "has_audio_track": false,
  "capture_mode": "CAMERAX_VIDEO_CAPTURE_NO_PREVIEW",
  "finalize_status": "SUCCESS"
}
```

禁止在 `VideoRecordEvent.Finalize` 成功前创建成功的 `EvidenceItem`。实际编码参数
必须从成品文件或 CameraX 输出读取，不能按预期值写死。

音频 `media`：

```json
{
  "container": "RAW_PCM",
  "codec": "PCM_S16LE",
  "sample_rate_hz": 16000,
  "channel_count": 8,
  "channel_mask": "0x6000FC",
  "channel_layout": [
    "PROCESSED_0",
    "PROCESSED_1",
    "RAW_MIC_0",
    "RAW_MIC_1",
    "RAW_MIC_2",
    "RAW_MIC_3",
    "HARDWARE_ECHO_0",
    "HARDWARE_ECHO_1"
  ],
  "audio_source": "MIC",
  "capture_mode": "ROKID_RAW_8_CHANNEL"
}
```

Rokid 官方推荐值是 16 kHz、16-bit、`0x6000FC`。但每个文件仍必须记录
`AudioRecord` 返回的实际通道数和配置；若降级为单通道，必须写实际值。

IMU `media`：

```json
{
  "format": "NDJSON",
  "sensor_types": ["ACCELEROMETER", "GYROSCOPE"],
  "coordinate_frame": "ANDROID_DEVICE_FRAME",
  "mount_position": "GLASSES_NATIVE",
  "axis_definition": {
    "x": "RIGHT",
    "y": "UP",
    "z": "TOWARD_WEARER"
  },
  "units": {
    "accelerometer": "METER_PER_SECOND_SQUARED",
    "gyroscope": "RADIAN_PER_SECOND"
  },
  "requested_sampling_mode": "SENSOR_DELAY_GAME",
  "actual_sample_count": 614,
  "calibration_profile": "rv101-axis/unknown"
}
```

原始 NDJSON 每行：

```json
{
  "sequence": 42,
  "monotonic_ns": 78474912345678,
  "sensor": "GYROSCOPE",
  "x": 0.12,
  "y": -0.43,
  "z": 0.08,
  "accuracy": 3
}
```

### 4.7 EvidenceLifecycleEvent：证据生命周期事件

```json
{
  "schema_ref": "rme.evidence-lifecycle-event.v1",
  "event_id": "elf_01J...",
  "evidence_item_id": "evd_01J...",
  "state": "UPLOADED_ENCRYPTED",
  "occurred_at": "2026-07-24T06:21:08.000Z",
  "actor": "GLASSES_EDGE",
  "reason_code": null,
  "request_id": "req_01J..."
}
```

状态按追加事件推进：

```text
CAPTURED_LOCAL -> ENCRYPTED_LOCAL -> QUEUED -> UPLOADED_ENCRYPTED
-> PROCESSING -> STRUCTURED -> DELETING -> DELETED

任一阶段 -> FAILED / REJECTED / EXPIRED -> DELETING -> DELETED
```

`DELETED` 必须有删除回执。上传完成不等于允许立即删除；设备应等待服务端确认接收，
但 TTL 和用户删除请求优先。

## 5. 后端结构化契约

### 5.1 AtomicObservation：原子观察

`AtomicObservation` 是解析器从证据中得到的最小可追溯观察。它不是长期事实。

```json
{
  "schema_ref": "rme.atomic-observation.v1",
  "observation_id": "obs_01J...",
  "observation_type": "TRANSCRIPT_SEGMENT",
  "time_range": {
    "start": "2026-07-24T06:21:04.100Z",
    "end": "2026-07-24T06:21:06.300Z",
    "time_uncertainty_ms": 80
  },
  "capture_window_id": "win_01J...",
  "source_refs": [
    {
      "source_envelope_id": "src_audio_01J...",
      "evidence_item_id": "evd_audio_01J...",
      "start_offset_ms": 1100,
      "end_offset_ms": 3300
    }
  ],
  "evidence_refs": [
    {
      "evidence_item_id": "evd_audio_01J...",
      "start_offset_ms": 1100,
      "end_offset_ms": 3300
    }
  ],
  "content": {
    "text": "这个胡辣汤太难喝了",
    "language": "zh-CN",
    "speaker_role": "PROBABLE_USER"
  },
  "confidence": 0.94,
  "provenance": {
    "producer": "audio-extractor",
    "model": "asr-model-id",
    "model_version": "2026-07-01",
    "procedure_version": "audio-extractor/1.0"
  },
  "usage_constraints": ["NO_DIRECT_FACT_WRITE"],
  "extensions": {}
}
```

`source_refs` 是必需追溯关系。媒体观察同时填写 `evidence_item_id` 和时间偏移；订单、
日历等结构化来源可以只引用 `source_envelope_id`。`evidence_refs` 是便于媒体解析器
读取的冗余索引，不应成为唯一来源链。

首版 `observation_type`：

- `VISUAL_OBJECT`
- `VISUAL_ATTRIBUTE`
- `SPATIAL_RELATION`
- `VISIBLE_TEXT`
- `SCENE_CONTEXT`
- `TRANSCRIPT_SEGMENT`
- `SPEECH_ACT`
- `EXPRESSED_SENTIMENT`
- `MOTION_SIGNAL`
- `DEVICE_STATE`
- `ONLINE_RECORD`

解析器必须拆开“听到了什么”和“推断意味着什么”。例如：

- `TRANSCRIPT_SEGMENT`：`这个胡辣汤太难喝了`
- `EXPRESSED_SENTIMENT`：负向评价，目标文本为“这个胡辣汤”
- 商品精确 ID 仍可为空，等待订单数据消歧

### 5.2 ObservationBundle：观察包

`ObservationBundle` 把同一时间窗或同一现实变化的多个观察放在一起：

```json
{
  "schema_ref": "rme.observation-bundle.v1",
  "bundle_id": "bun_01J...",
  "time_range": {
    "start": "2026-07-24T06:20:58.410Z",
    "end": "2026-07-24T06:21:12.410Z"
  },
  "capture_window_ids": ["win_01J..."],
  "observation_ids": [
    "obs_visual_meal",
    "obs_transcript",
    "obs_negative_sentiment"
  ],
  "bundle_kind": "MULTIMODAL_MOMENT",
  "fusion": {
    "procedure_version": "temporal-fusion/1.0",
    "max_alignment_gap_ms": 2500,
    "confidence": 0.87
  },
  "supersedes_bundle_id": null
}
```

重复图片先经过 `EvidenceSelectionRecord` 选择代表帧。图片不同不等于现实信息有增量。

### 5.3 ActivityEpisode：活动段

`ActivityEpisode` 是后端对一段现实活动的可修订分组。例如“用餐”“阅读”“找东西”。
它不是采集会话，也不是事实事件。

```json
{
  "schema_ref": "rme.activity-episode.v1",
  "activity_episode_id": "epi_01J...",
  "episode_type": "MEAL",
  "time_range": {
    "start": "2026-07-24T06:18:00Z",
    "end": "2026-07-24T06:42:00Z"
  },
  "bundle_ids": ["bun_01J...", "bun_01K..."],
  "boundary_confidence": 0.78,
  "state": "OPEN",
  "segmentation": {
    "procedure_version": "episode-segmentation/1.0",
    "start_reasons": ["SCENE_CHANGE", "MEAL_OBJECTS_APPEARED"],
    "end_reasons": []
  },
  "supersedes_episode_id": null
}
```

允许修订方式是产生新版本并用 `supersedes_episode_id` 指向旧版本，不原地静默改写。

### 5.4 MemoryCandidate：记忆候选

`MemoryCandidate` 是可能成为长期记忆的受约束断言，还不是事实：

```json
{
  "schema_ref": "rme.memory-candidate.v1",
  "memory_candidate_id": "can_01J...",
  "candidate_type": "PREFERENCE_STATED",
  "subject": {
    "entity_type": "USER",
    "entity_id": "usr_01J..."
  },
  "predicate": "DISLIKES",
  "object": {
    "entity_type": "FOOD_ITEM",
    "entity_id": null,
    "label": "胡辣汤",
    "resolution_state": "UNRESOLVED"
  },
  "valid_time": {
    "start": "2026-07-24T06:21:04.100Z",
    "end": null
  },
  "supporting_bundle_ids": ["bun_01J..."],
  "supporting_observation_ids": [
    "obs_transcript",
    "obs_negative_sentiment"
  ],
  "confidence": 0.83,
  "conflicts": [],
  "policy_decision": "REVIEW_OR_RULE_GATE",
  "candidate_procedure_version": "preference-candidate/1.0"
}
```

如果之后获得用户授权的外卖订单，`ONLINE_RECORD` 可以把“胡辣汤”解析到具体商家
和商品。新候选可以引用旧候选并提高实体解析精度，但不能伪造当时眼镜看见了订单。

### 5.5 MemoryEvent：记忆事实事件

只有 Memory Core 可以追加 `MemoryEvent`：

```json
{
  "schema_ref": "rme.memory-event.v1",
  "memory_event_id": "mem_01J...",
  "event_type": "PREFERENCE_STATED",
  "subject": {
    "entity_type": "USER",
    "entity_id": "usr_01J..."
  },
  "predicate": "DISLIKES",
  "object": {
    "entity_type": "FOOD_ITEM",
    "entity_id": "food_01J...",
    "label": "胡辣汤"
  },
  "recorded_at": "2026-07-24T06:22:00Z",
  "valid_time": {
    "start": "2026-07-24T06:21:04.100Z",
    "end": null
  },
  "source_candidate_ids": ["can_01J..."],
  "confidence": 0.86,
  "policy_snapshot_id": "pol_01J...",
  "supersedes_event_id": null,
  "correction_target_event_id": null,
  "status": "ACTIVE"
}
```

首版事件类型仅允许：

- `OBJECT_OBSERVED_AT`
- `OBJECT_MOVED`
- `CONSUMABLE_LEVEL_OBSERVED`
- `PREFERENCE_STATED`
- `TASK_STATED`
- `USER_CORRECTION`
- `FORGET_REQUESTED`

### 5.6 StateProjection：当前状态

`StateProjection` 是从 `MemoryEvent` 重放得到的查询结果，可随纠正、删除和实体合并
重新计算：

```json
{
  "schema_ref": "rme.state-projection.v1",
  "projection_id": "prj_preference_usr_food",
  "projection_type": "USER_PREFERENCE",
  "subject_id": "usr_01J...",
  "key": "food:胡辣汤",
  "value": {
    "sentiment": "DISLIKE",
    "target_entity_id": "food_01J..."
  },
  "as_of": "2026-07-24T06:22:00Z",
  "source_event_ids": ["mem_01J..."],
  "confidence": 0.86,
  "freshness": "CURRENT",
  "projection_version": 7
}
```

投影存储可以被删除并从事件流重建。Agent 和提醒服务读取投影，但不能直接改投影。

## 6. 多模态对齐规则

后端按以下优先级关联：

1. 相同 `capture_window_id`。
2. 相同设备单调时钟范围是否重叠。
3. UTC 时间范围与 `time_uncertainty_ms` 是否允许重叠。
4. 模态内容是否提供弱语义支持。

第 4 条不能反过来覆盖前三条。例如图片中有饭和音频中出现“难吃”，如果两者相隔
很远且不在同一窗口，不能仅凭语义相似就强行绑定。

窗口允许：

- 触发前 IMU：建议 4 秒。
- 触发后图片：回稳后尽快拍摄。
- 强变化短视频：建议最长 2–3 秒。
- 触发音频：首版建议最长 10 秒；延长到 30 秒必须由 VAD 或显式用户动作续期。

这些是策略默认值，不写死在 Schema 中。每次实际范围以时间字段为准。

## 7. 上传接口

眼镜只有在 Android 活跃网络同时具备 `NET_CAPABILITY_INTERNET` 和
`NET_CAPABILITY_VALIDATED` 时才认为可以尝试上传。“与手机同一网络”不等于已经
能访问后端。

### 7.1 初始化

```http
POST /internal/v1/evidence/init
Authorization: Bearer <device-token>
Idempotency-Key: <evidence_item_id>
X-Policy-Version: <policy_snapshot_id>
Content-Type: application/json
```

请求包含：

```json
{
  "source_envelope": {},
  "evidence_item": {},
  "ciphertext": {
    "byte_count": 428160,
    "sha256": "ciphertext-sha256"
  }
}
```

响应：

```json
{
  "request_id": "req_01J...",
  "evidence_item_id": "evd_01J...",
  "upload_id": "upl_01J...",
  "upload_url": "short-lived-signed-url",
  "required_headers": {},
  "expires_at": "2026-07-24T06:26:03Z"
}
```

### 7.2 上传密文

```http
PUT <upload_url>
Content-Type: application/octet-stream
```

只上传端侧加密后的对象。签名 URL 过期后重新调用 `init`，不生成新的
`evidence_item_id`。

### 7.3 完成

```http
POST /internal/v1/evidence/{evidence_item_id}/complete
Idempotency-Key: <evidence_item_id>:complete
```

```json
{
  "upload_id": "upl_01J...",
  "ciphertext_sha256": "ciphertext-sha256",
  "ciphertext_byte_count": 428160
}
```

只有响应 `accepted: true` 后，端侧才能把队列标为已接收。

### 7.4 删除回执

```http
POST /internal/v1/evidence/{evidence_item_id}/delete-receipt
```

```json
{
  "deleted_at": "2026-07-24T06:24:00Z",
  "scope": ["LOCAL_CIPHERTEXT", "LOCAL_STAGING", "LOCAL_KEY_REFERENCE"],
  "reason": "STRUCTURED_OR_ACKNOWLEDGED",
  "result": "DELETED"
}
```

## 8. 后端接入校验

接入层在进入解析队列前必须拒绝：

- Schema 版本不支持。
- `device_id` 与设备令牌不匹配。
- 幂等键重复但正文哈希不同。
- 媒体哈希或字节数不匹配。
- `capture_window_id` 不属于对应会话。
- 绝对时间明显倒退且没有时钟重置说明。
- TTL 已到期。
- 策略不允许该模态。

可接收但必须标记质量问题：

- `time_uncertainty_ms` 较大。
- 视频或音频实际参数未知。
- 某个窗口缺少请求过的模态，但有失败审计。
- IMU 轴向尚未完成真机校准。

## 9. 结构化团队的最小开发顺序

1. 建立 Schema 校验和幂等接入，原样保存不可变元数据。
2. 图片、音频、视频、IMU 分别输出 `AtomicObservation`，不直接写记忆。
3. 按 `capture_window_id` 和时间范围生成 `ObservationBundle`。
4. 增加证据质量与重复筛选，避免相似图片逐张沉淀。
5. 用可修订规则生成 `ActivityEpisode`。
6. 只为首版受控事件类型生成 `MemoryCandidate`。
7. 通过策略、置信度、冲突和用户纠正门后追加 `MemoryEvent`。
8. 从事件流重算 `StateProjection`，供查询与提醒使用。

## 10. 首个联合验收样例

建议使用“用户用餐时说这个胡辣汤太难喝了”作为首个多模态验收：

1. 头部由稳定到转动再回稳，产生 `CaptureIntent`。
2. 同一 `CaptureWindow` 中生成图片、音频和 IMU 三项 Evidence。
3. 图片解析器输出餐食/容器等视觉观察。
4. 音频解析器输出逐字稿和负向评价观察。
5. 时间融合生成一个多模态观察包。
6. 活动分段器将其归入用餐活动段。
7. 候选生成器产生“用户不喜欢胡辣汤”的偏好候选，商品 ID 可暂时未解析。
8. Memory Core 通过门控后追加偏好事实事件。
9. 原始媒体删除，观察、候选、事件和删除回执仍可审计。

验收失败示例：

- 只有头动，没有图片或语音支持，却产生“用户正在吃饭”。
- 图片和语音不在同一窗口且时间不重叠，却被强行绑定。
- 逐字稿一生成就直接写入 `MemoryEvent`。
- 原始图片被长期保存作为查询依赖。
- 用户纠正后只改当前状态，没有追加纠正事件并重算投影。

## 11. 待真机确认项

下列字段结构已经固定，但取值必须等待 RV101 真机：

- CameraX 实际图片尺寸、JPEG 质量和首次/连续拍照时延。
- CameraX 短视频的分辨率、帧率、编码器、Finalize 时延和最大稳定时长。
- 8 通道 AudioRecord 的实际通道数、通道顺序、同步性和是否存在固件差异。
- 眼镜 IMU 的真实采样频率、轴向、时间戳稳定性和精度字段。
- 佩戴广播在前台、后台、重启后是否稳定。
- TextToSpeech 的音频路由与固件限制。
- 网络切换、离线队列、温升、功耗和存储上限。

这些取值通过新版本设备能力或校准配置下发，不修改本契约的核心语义。

## 12. 本版本明确不包含的契约

v1.0 只冻结“采集证据如何进入云端，以及云端如何形成可追溯记忆”的对象语义。
以下内容尚未完成专项 review，因此不在 `contracts/reality-memory/v1/` 中提供正式
Schema：

- 云端发给眼镜的通用 `DeviceMessage`。
- `ReminderSignal`、提醒文案、按钮和终端交互。
- `DeliveryReceipt` 的最终状态与字段。
- Agent、规则和用户策略之间的提醒决策分工。
- 下行使用轮询、WebSocket、MQTT 或系统推送的最终选择。

当前建议边界和联调顺序见
[`04-Device-Cloud-Communication.md`](../architecture/04-Device-Cloud-Communication.md)。
后续下行契约完成 review 后应使用独立 Schema 版本发布，不在现有 Evidence 对象中
临时塞入提醒字段。
