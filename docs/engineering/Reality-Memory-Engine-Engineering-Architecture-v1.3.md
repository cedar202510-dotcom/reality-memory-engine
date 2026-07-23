# Reality Memory Engine 工程架构与数据链路

> 文档版本：v1.3-engineering  
> 文档日期：2026-07-24  
> 母版来源：Reality-Memory-Engine-PRD-v1.3.md  
> 文档用途：让研发、算法、数据、设备和测试团队理解从采集到沉淀的完整工程链路

---

## 1. 核心结论

1. 用户侧只有一个 Reality 手机 App，它是首版账号、配对、策略、加密队列、上传、管理和提醒的默认网关。
2. 最终眼镜采集路径是运行在 Rokid Glasses RV101 眼镜本机的原生 Android Runtime；它只负责设备侧低打扰采集，不承载用户账号或记忆本体。
3. CXR-L iOS/Android 是统一手机 App 内的第一阶段过渡 Adapter，用来提前验证真实图片、短音频、授权和后端契约；它不能作为最终后台无感采集方案。
4. 产品不录长视频，不接收连续视频流。只支持单图、前后帧、2-3 秒短视频、短音频、传感器窗口和结构化设备事件。
5. 每种模态有自己的解析器，但所有解析器都输出同一套 `AtomicObservation` 观察契约。
6. 模型只创建观察和候选，不能直接写入 `MemoryEvent`，也不能直接更新 `StateProjection`。
7. `MemoryEvent` 是唯一持久事实源；`StateProjection`、索引、信号和缓存都是可重算派生数据。
8. Agent 的完整设计暂不展开。本阶段只规定 Agent 在查询、提醒措辞和少量歧义判断中参与，不能越过 Memory Core 写事实。

---

## 2. 总体链路

```text
设备/入口
  -> Device Adapter
  -> Reality Mobile Gateway / Edge Core
  -> SourceEnvelope
  -> EvidenceItem 或 Structured Source Event
  -> 安全扫描与敏感内容检测
  -> 模态预处理
  -> Modality Extractor
  -> AtomicObservation
  -> ObservationBundle
  -> ActionSegment / ActivityEpisode
  -> MemoryCandidate
  -> Entity Resolution
  -> Policy & Confidence Gate
  -> Conflict Resolver
  -> MemoryEvent
  -> Projection Engine
  -> Query / Search / Signal
  -> ReminderDecision / ReminderDelivery
  -> Evidence Deletion
```

这条链路里最重要的分工是：

- 眼镜 Runtime 负责眼镜本机低打扰采集，统一手机网关负责账号归属、配对、策略、加密队列和上传。
- 解析器负责把单个模态变成结构化观察。
- Temporal Fusion 负责把多个观察组织成时间窗、动作片段和活动。
- Memory Core 负责候选是否能成为事实。
- Projection Engine 负责从事实事件计算当前状态。
- Agent 只消费结构化结果，不接触原始媒体，不直接写事实。

---

## 3. 分层架构

```text
设备与交互层
  Rokid Native Runtime / CXR-L Adapter / Ring / Phone / Future Adapters

Reality Mobile Gateway / Edge Core
  Account / Pairing / Source Adapter / Session FSM / Local Policy
  Capture Scheduler / VAD Scheduler / Encrypted Buffer / Upload Relay
  Device Audit / Secure Erase

Memory Platform
  Device Registry / Evidence / Perception Orchestrator / Temporal Fusion
  Candidate Store / Entity Resolver / Event Store / Projection Engine
  Query / Signal / Privacy / Audit

消费与行动层
  Glass Agent / Mobile Agent / Home Agent / Future Robots / Partners
```

### 3.1 Device Adapter

Device Adapter 处理硬件和厂商 SDK 差异，包括：

- 相机、麦克风、录像、传感器 API。
- 佩戴、摘下、折叠、按键、手势和系统事件。
- 电量、温度、网络和后台生命周期。
- 厂商授权、配对、应用分发和调试方式。

新增硬件只增加 Adapter、`DeviceCapabilityProfile` 和校准参数，不新增一套记忆本体。

### 3.2 Reality Mobile Gateway / Edge Core

Reality Mobile Gateway / Edge Core 是可复用的用户侧通用逻辑，包括：

- 用户账号、家庭域归属、设备绑定和本地信任状态。
- 来源会话和佩戴会话状态机。
- 本地策略快照和调用媒体 API 前的 `PolicyCheck`。
- CXR-L 阶段的图片、短视频、音频和传感器采集调度。
- 原生眼镜 Runtime 阶段的本地传输接收、背压、重试和上传。
- 本地 VAD、预算、节流和离线队列。
- 证据加密、过期和安全删除。
- 厂商事件到 `SourceEnvelope` 的映射。
- 采集尝试、策略命中、删除回执和设备审计。

### 3.3 Memory Platform

Memory Platform 是设备无关的中台能力，包括：

- 设备注册、策略、证据和鉴权。
- 按模态选择解析器。
- 原子观察、跨模态聚合、活动 Episode 和记忆候选。
- 实体归并、冲突、纠正和追加式事件。
- 当前状态投影、查询、信号、提醒、隐私删除和审计。

---

## 4. 关键对象中英对照

| 英文对象 | 中文理解 | 是否事实 | 主要用途 |
|---|---|---:|---|
| `DeviceCapabilityProfile` | 设备能力画像 | 否 | 描述某台设备能采什么、限制是什么、固件版本是什么 |
| `SourceEnvelope` | 来源信封 | 否 | 封装一次设备或用户入口事件的来源、时间、策略和证据引用 |
| `EvidenceItem` | 短暂证据 | 否 | 图片、短视频、短音频或传感器窗口，完成结构化后删除 |
| `Structured Source Event` | 结构化来源事件 | 否 | 已经结构化的设备事件，例如佩戴、按键、门锁状态 |
| `AtomicObservation` | 原子观察 | 否 | 单个解析器输出的最小结构化观察 |
| `ObservationBundle` | 观察包 | 否 | 同一时间窗或同一现实变化下的多个原子观察集合 |
| `ActionSegment` | 动作片段 | 否 | 几秒到几分钟的局部动作，例如拿起、切菜、放下 |
| `ActivityEpisode` | 活动段 / 活动会话 | 否 | 目标相对稳定的一段活动，例如做饭、收拾厨房 |
| `MemoryCandidate` | 记忆候选 | 否 | 可能成为记忆事实的现实断言 |
| `MemoryEvent` | 记忆事件 | 是 | 追加式事实变化，是唯一持久事实源 |
| `StateProjection` | 状态投影 | 派生 | 从事件流计算出的当前最佳状态 |
| `SignalCandidate` | 信号候选 | 否 | 可能值得提醒的状态变化 |
| `ReminderDecision` | 提醒决策 | 否 | 是否提醒、何时提醒、在哪个终端提醒、怎么说 |
| `ReminderDelivery` | 提醒投递 | 否 | 提醒发出、查看、忽略和追问结果 |
| `PolicySnapshot` | 策略快照 | 否 | 当前采集、处理、留存和调用权限 |
| `DeletionTombstone` | 删除墓碑 | 审计 | 不含被删内容，只证明删除范围和完成状态 |

---

## 5. 模态解析链路

### 5.1 图片解析器 Image Extractor

输入：

- 单图、前后帧中的图片。
- `SourceEnvelope` 上下文，例如设备、时间、触发方式、策略版本、佩戴会话。
- `DeviceCapabilityProfile` 和校准参数，例如分辨率、视角、方向、低光表现。

输出的典型 `AtomicObservation`：

- 对象存在：`object_present`
- 对象位置：`located_at`
- 容器关系：`inside`、`on_top_of`
- 状态变化：`opened`、`closed`、`remaining_ratio_changed`
- 文本/OCR：`text_observed`
- 敏感内容标签：`screen`、`credential`、`third_party`

触发原则：

- 显式触发优先。
- 高运动、场景变化、对象拿放时提高采集优先级。
- 坐姿、电视、休息等低变化场景降频。
- 禁采、低电量、过热或策略失效时不启动相机。

### 5.2 短视频解析器 ShortVideo Extractor

输入：

- 2-3 秒短视频片段。
- 可选关键帧、运动轨迹和前后帧。

输出的典型 `AtomicObservation`：

- 快速动作：拿起、放下、倒出、打开、关闭。
- 短时轨迹：对象从 A 移到 B。
- 静态帧难判断的过程变化。

使用原则：

- 只在静态图歧义、动作过快或连续变化需要验证时使用。
- 不接收长视频或连续视频流。
- 单会话短视频总时长受预算控制。
- 短视频完成结构化后按 Evidence TTL 删除。

### 5.3 音频解析器 Audio Extractor

输入：

- 显式语音片段，例如戒指按键或眼镜按键触发。
- 会话内 VAD 命中的短音频片段。

输出的典型 `AtomicObservation`：

- ASR 文本。
- 用户偏好：喜欢、不喜欢、以后不要。
- 用户任务：提醒、待办、找物请求。
- 用户纠正：识别错了、位置错了、删除最近内容。
- 环境声音事件：门铃、提示音等，首版谨慎使用。

触发与切分原则：

- 显式语音优先级最高。
- 会话内 VAD 只在用户已授权现实记录且音频策略允许时运行。
- 推荐预滚不超过 500 ms。
- 连续静音约 800-1200 ms 后结束。
- 自动 VAD 单段最长 15 秒。
- 静音缓冲不落盘、不上传、不进入 ASR。
- CXR-L 阶段在手机本地 VAD；原生 Glass App 阶段在眼镜端 `AudioRecord + VAD`。

### 5.4 传感器解析器 Sensor Extractor

输入：

- 眼镜 IMU、戒指 IMU、佩戴/摘下、折叠、按键、手势、电量、温度、网络。

输出的典型 `AtomicObservation`：

- 佩戴状态变化。
- 姿态和运动强度。
- 可能的手势意图。
- 设备健康与预算信息。

使用原则：

- 传感器更多用于调度、门控和动作辅助，而不是单独形成记忆事实。
- 佩戴、摘下、暂停、禁采、低电量和过热是硬边界信号。
- 设备状态事件可以不带媒体 Evidence，直接作为结构化来源事件进入链路。

### 5.5 结构化事件解析器 StructuredEvent Extractor

输入：

- 手机确认、智能家居事件、日历、门锁、用户手动输入、Agent 请求一次现场确认。

输出的典型 `AtomicObservation` 或 `MemoryCandidate`：

- 用户明确确认。
- 用户纠正。
- 设备状态。
- 外部世界状态。

使用原则：

- 已经结构化且权限明确的事件可以绕过媒体解析。
- 仍必须绑定 `SourceEnvelope`、策略快照、幂等键和审计记录。

---

## 6. 从观察到记忆

### 6.1 AtomicObservation：解析器的边界

`AtomicObservation` 是解析结果，不是事实。它必须包含：

- 观察类型和受约束谓词。
- 主体、对象或数值结果。
- 现象发生时间范围、观察时间和接收时间。
- 可用时的空间、区域、轨迹或说话人上下文。
- 一个或多个证据引用。
- 解析器、模型和版本。
- 置信度和校准版本。
- 可解释特征。
- 敏感性标签。
- 允许用途与留存策略。

模型输出的自然语言描述和 ASR 文本可以保留，但不能替代结构化谓词、实体、时间、置信度和来源。

### 6.2 ObservationBundle：把同一变化放在一起

`ObservationBundle` 只关联同一时间窗或同一现实变化的多个原子观察，不复制原始媒体。

例子：

```text
同一时间窗内：
  图片看到钥匙在茶几右侧
  IMU 显示用户刚低头靠近茶几
  上一帧看到钥匙在手里

合成：
  一个关于“钥匙被放到茶几”的 ObservationBundle
```

### 6.3 ActionSegment：局部动作

`ActionSegment` 表达几秒到几分钟的动作，例如：

- 拿出西红柿。
- 切菜。
- 放下钥匙。
- 打开抽屉。
- 等水烧开。

Segment 可以变化，但仍服务于同一个粗目标。

### 6.4 ActivityEpisode：活动会话

`ActivityEpisode` 表达目标相对稳定的一段现实活动，例如：

- 做晚饭。
- 吃饭。
- 收拾厨房。
- 出门买菜。
- 洗漱准备睡觉。

Session 不是按房间机械切分。位置变化只是边界证据，不是边界本身。一个人在厨房台面、冰箱和灶台之间移动，通常仍是同一个“做晚饭”Episode；如果他在厨房放下锅、拿起清洁用品开始擦地，则可能切换到“清洁厨房”Episode。

### 6.5 MemoryCandidate：候选事实

`MemoryCandidate` 是由观察和活动聚合形成、尚未成为事实的现实断言。它保存：

- 候选类型，例如对象位置、耗材余量、偏好、任务。
- 主体实体或实体候选。
- 状态维度和值。
- 时间范围。
- 置信度分量。
- 来源观察和来源活动。
- 候选状态，例如 `PENDING`、`ACCEPTED`、`REJECTED`、`CONFLICTED`。

### 6.6 MemoryEvent：唯一事实源

候选只有通过策略、实体归因、置信度、冲突检测和交叉验证后，才写入 `MemoryEvent`。

`MemoryEvent` 采用追加式写入。纠正不是修改旧事件正文，而是写入新的纠正事件，并通过事件关系和投影重算得到当前状态。

### 6.7 StateProjection：当前状态

`StateProjection` 从有效事件流计算，不独立创造事实。它回答：

- 钥匙当前在哪里。
- 洗衣液剩多少。
- 任务是否打开。
- 偏好是否仍有效。
- 某个空间当前有什么高置信对象。

投影、全文索引、向量索引、Signal 和缓存都必须可由事件流重建。

---

## 7. 活动边界规则

### 7.1 边界信号

| 信号 | 初始权重 | 含义 |
|---|---:|---|
| `goal_shift` | 0.40 | 当前行为是否不再服务于原目标 |
| `space_shift` | 0.15 | 房间或场景是否发生持续变化 |
| `object_set_shift` | 0.15 | 活跃物体集合是否整体替换 |
| `social_context_shift` | 0.10 | 互动对象或社会情境是否改变 |
| `temporal_gap` | 0.10 | 是否存在无法由任务等待解释的空档 |
| `prediction_error` | 0.10 | 新观察是否明显违背当前 Episode 的下一步预测 |

初始阈值：

- `< 0.45`：继续当前 Episode。
- `0.45-0.72`：进入待确认边界，再观察 1-2 次。
- `>= 0.72`：候选新 Episode，通常要求连续两次成立后提交。

显式用户停止、隐私场景或设备长时间离线是硬信号，可以绕过普通阈值。

### 7.2 迟滞与可撤销边界

不能让一次模糊图片立刻结束 Episode。Orchestrator 保存：

- `boundary_candidate_since`
- `confirming_observation_ids`
- `previous_episode_snapshot`
- `merge_deadline`

候选切分先处于 tentative。后续证据回到原目标时撤销切分；持续支持新目标时才提交。

### 7.3 中断不是结束

Episode 状态：

```text
tentative -> active -> suspended -> active -> closed
```

例如做饭时接电话，做饭 Episode 进入 suspended；电话结束后，如果目标、场景、物体和时间距离重新匹配厨房状态，则恢复原做饭 Episode，而不是新建第二个做饭 Episode。

---

## 8. 设备采集状态机

```text
ENDED
  -> WEAR_DETECTED
  -> COUNTDOWN_5S
      -> 用户关闭 -> DISABLED_FOR_THIS_WEAR
      -> 权限或策略阻断 -> BLOCKED
      -> 倒计时结束 -> ACTIVE

ACTIVE
  -> 采集触发 -> POLICY_CHECK -> CAPTURING -> ACTIVE
  -> 用户暂停 -> PAUSED
  -> 禁采策略生效 -> BLOCKED
  -> 严重错误 -> ERROR
  -> 摘下/折叠/会话失效 -> ENDING -> ENDED

PAUSED
  -> 用户恢复 -> POLICY_CHECK -> ACTIVE
  -> 摘下 -> ENDING -> ENDED

BLOCKED
  -> 策略恢复且用户仍佩戴 -> ACTIVE
  -> 摘下 -> ENDING -> ENDED
```

### 8.1 状态语义

| 状态 | 相机/音频 | 调度 | 允许事件 |
|---|---|---|---|
| `COUNTDOWN_5S` | 关闭 | 关闭 | 关闭、全局关闭 |
| `ACTIVE` | 按策略开放 | 运行 | 暂停、显式采集、主动语音 |
| `PAUSED` | 关闭 | 关闭 | 恢复、删除、结束 |
| `BLOCKED` | 关闭 | 关闭 | 策略刷新、删除、结束 |
| `DISABLED_FOR_THIS_WEAR` | 关闭 | 关闭 | 删除、结束 |
| `ENDING/ENDED` | 关闭 | 关闭 | 清理与审计 |

### 8.2 采集前策略检查

每次调用 CameraX、VideoCapture 或 AudioRecord 前执行：

```text
PolicyCheck(
  user,
  device,
  session,
  modality,
  trigger,
  location_context,
  people_context,
  battery,
  thermal,
  network,
  budget
)
```

`DENY` 时设备不得启动媒体 API。没有有效策略、策略签名失效或策略版本回退时按 `DENY` 处理。

---

## 9. 数据结构摘要

### 9.1 SourceEnvelope

来源信封用于统一封装设备事件。最少字段：

- `source_id`
- `device_id`
- `source_session_id`
- `occurred_at`
- `observed_at`
- `monotonic_offset_ms`
- `policy_snapshot_id`
- `trigger`
- `modality`
- `schema_ref`
- `idempotency_key`
- `evidence_item_ids`

厂商原始事件名可保留在扩展字段，但不能成为记忆核心契约。

### 9.2 EvidenceItem

短暂证据用于承载图片、短视频、短音频或传感器窗口。它必须包含 TTL、加密引用、模态、内容类型、敏感标签、删除状态和来源信封 ID。

### 9.3 AtomicObservation

原子观察必须能追溯到 Evidence 或结构化来源事件，并带有模型版本、置信度、时间范围和用途限制。

### 9.4 MemoryCandidate

记忆候选必须表达一个受约束的现实断言，例如：

```text
对象 obj_keys_01 的 location 可能是 place_coffee_table/right_side
```

### 9.5 MemoryEvent

记忆事件是追加式事实。它包含事件类型、实体、时间、有效区间、来源候选、策略快照、置信度和纠正关系。

### 9.6 StateProjection

状态投影是从事件流得到的当前最佳状态。删除、纠正或实体合并后，投影必须可重算。

---

## 10. 内部 API

所有写接口要求：

- `Authorization: Bearer <device-or-service-token>`
- `Idempotency-Key`
- `X-Policy-Version`
- UTC 事件时间与设备单调时钟偏移
- 请求和响应包含 `request_id`

### 10.1 会话

```http
POST /internal/v1/sessions
PATCH /internal/v1/sessions/{session_id}
```

作用：

- 创建佩戴会话。
- 激活、暂停、恢复、阻断、结束会话。
- 记录设备状态、策略版本和结束原因。

### 10.2 策略

```http
GET /internal/v1/capture-policy?device_id=glass_01&session_id=wear_01
```

作用：

- 下发当前运行模式、允许模态、触发来源、禁采时段、位置、预算、TTL、调试证据权限和策略签名。
- 设备必须在每次采集前检查策略。

### 10.3 采集审计

```http
POST /internal/v1/capture-attempts
```

作用：

- 记录一次计划或实际采集尝试。
- 即使没有上传媒体，也能审计设备何时、为何尝试采集以及结果是什么。

### 10.4 证据

```http
POST /internal/v1/evidence/init
POST /internal/v1/evidence/{id}/complete
POST /internal/v1/evidence/{id}/delete-receipt
```

作用：

- 创建临时上传授权。
- 标记证据上传完成。
- 回传端侧或云端删除结果。

PoC 阶段服务端可以关闭 Evidence 上传 feature flag，仅开放采集元数据。

### 10.5 观察与记忆

```http
POST /internal/v1/observation-candidates
POST /internal/v1/memory-events
```

作用：

- Perception 服务提交结构化观察和候选。
- Memory Core 在通过策略和置信度门后写入事实事件。
- 设备端不能直接写主线事件。

### 10.6 查询

```http
GET /v1/memory/search?q=钥匙在哪里
GET /v1/memory/objects?query=钥匙
GET /v1/memory/objects/{id}/where-is
GET /v1/memory/objects/{id}/timeline
GET /v1/memory/places/{id}/snapshot
GET /v1/memory/events?from=&to=&type=
GET /v1/memory/consumables/low-stock
GET /v1/memory/intents?status=open
GET /v1/memory/preferences?subject=
```

作用：

- 面向 Agent、手机端、Web 控制台或未来设备返回结构化记忆。
- 返回必须包含置信度、新鲜度、来源事件和可解释字段。

### 10.7 隐私

```http
GET  /v1/privacy/mode
PUT  /v1/privacy/mode
POST /v1/privacy/pause
POST /v1/privacy/resume
POST /v1/memory/forget-recent
POST /v1/memory/redact
DELETE /v1/memory/{id}
GET  /v1/memory/audit
```

作用：

- 查询或修改隐私模式。
- 暂停、恢复、近窗遗忘、脱敏、删除和审计。
- 删除必须覆盖设备本地、对象存储、观察、候选、事件有效性、投影、索引、缓存、信号和异步任务。

### 10.8 信号

```http
POST /v1/memory/subscriptions
GET  /v1/memory/signals
WS   /v1/memory/signals/stream
```

作用：

- 订阅或拉取可能值得提醒的状态变化。
- 当前阶段 Signal 只允许生成提醒，不允许自动购物、自动发消息或执行其他外部动作。

---

## 11. 证据生命周期

```text
CAPTURED_LOCAL
  -> ENCRYPTED_LOCAL
  -> QUEUED
  -> UPLOADED_ENCRYPTED
  -> PROCESSING
  -> STRUCTURED
  -> DELETING
  -> DELETED

任一阶段
  -> EXPIRED / REJECTED / FAILED
  -> DELETING
  -> DELETED
```

默认留存：

| 环境 | 媒体 | 默认策略 |
|---|---|---|
| Rokid 采集 PoC | 图片/短音频 | 显式测试授权下短暂保存，完成验证后删除 |
| 正式处理链 | 图片 | 本地最长 10 分钟；云端最长 15 分钟；完成结构化即删 |
| 正式处理链 | 短视频/短音频 | 本地与云端最长 15 分钟；完成结构化即删 |
| 测试调试 | 显式授权样本 | 本地加密，最长 24 小时，单独测试角色可见 |

TTL 是上限，删除事件优先于 TTL。媒体对象使用独立 DEK；删除 DEK、对象和派生缓存后写删除回执。

---

## 12. 服务端模块

| 模块 | 作用 |
|---|---|
| Device Registry | 管理设备身份、Owner、家庭域、硬件型号、固件、App 版本和能力矩阵 |
| Session & Policy Service | 创建佩戴会话、下发策略、处理暂停恢复和全局关闭 |
| Evidence Service | 创建上传授权、验证证据、驱动删除和回执 |
| Perception Orchestrator | 选择图片、短视频、音频、传感器或结构化事件解析器 |
| Temporal Fusion | 构建 Bundle、Segment、Episode 和 MemoryCandidate |
| Entity Resolver | 根据类别、外观、空间、时间和用户命名归并实体 |
| Event Store | 接受通过 Gate 的候选，追加 MemoryEvent，保证幂等 |
| Projection Engine | 按实体和状态维度消费事件，生成当前状态、趋势和冲突 |
| Query & Search | 支持找物、时间线、空间摘要、耗材、偏好和任务查询 |
| Signal & Reminder Service | 从投影变化生成提醒候选并完成受控投递 |
| Privacy & Audit | 删除、近窗遗忘、脱敏、tombstone 和用户可见审计 |

---

## 13. 首版数据库表

首版只需要实现以下核心表：

```text
households
actors
devices
entities
places
wear_sessions
capture_attempts
source_envelopes
evidence_items
atomic_observations
observation_evidence_links
observation_bundles
bundle_observation_links
action_segments
activity_episodes
episode_segment_links
memory_candidates
entity_aliases
candidate_links
memory_events
state_projections
policy_snapshots
signal_candidates
reminder_decisions
reminder_deliveries
agent_grants
deletion_requests
deletion_jobs
deletion_tombstones
audit_records
outbox_events
```

`memory_events` 与对应 `outbox_events` 必须在同一事务内写入。所有消费者以 `outbox_events.id` 或业务 `idempotency_key` 去重。

---

## 14. 测试重点

### 14.1 Glass 真机

- 初次授权、拒绝权限、撤销权限。
- 佩戴、摘下、折叠、展开。
- 倒计时关闭。
- ACTIVE 暂停与恢复。
- 熄屏、锁屏、切换应用。
- 进程被杀与设备重启。
- Wi-Fi 断开与恢复。
- 低电量、过热、存储不足。
- CameraX 忙、绑定失败、写入失败。
- AudioRecord/CXR-L 音频流启动、停止、断连与超时。
- VAD 静音不成段、人声起止、预滚、最长片段和误触发。
- 2-3 秒短视频上限；验证不存在长视频或连续视频入口。
- 策略在会话中收紧。
- 删除与上传竞态。

### 14.2 后端

- 鉴权和家庭隔离。
- 幂等重放。
- 时钟乱序。
- 证据 TTL。
- 候选冲突。
- AtomicObservation Schema、跨模态 Bundle 和 Episode 边界回放。
- 实体合并和拆分。
- 事件回放和投影确定性。
- 删除全链路。
- Signal 去重和冷却。

### 14.3 端到端

- 佩戴到第一条结构化记忆。
- 对象移动到 Query。
- 主动语音到 Preference/Intent。
- 状态变化到 Signal。
- 用户纠正到投影重算。
- 近窗遗忘到查询不可见和审计完成。

---

## 15. 研发启动顺序

1. 跑通 Rokid `GlassesBareDevSample`。
2. 建立 `rokid-glass` Android 工程与 `edge-contract`。
3. 实现佩戴广播、5 秒倒计时和本地会话状态机。
4. 实现 CameraX 单图与采集后立即删除。
5. 实现无媒体 `capture-attempts` 审计服务。
6. 完成 30 分钟定时截图 PoC 与真机报告。
7. 并行跑通戒指 BLE、双击、主动录音和短时 IMU。
8. 实现策略、证据缓冲和删除链。
9. 接入 Image/Audio Extractor，输出 AtomicObservation 和 MemoryCandidate。
10. 实现 Event Store、Projection、Find Object Query。
11. 接入耗材、偏好、任务和 Signal。
12. 开始真实家庭受控试用。

---

## 16. 与当前代码和文档的关系

- CXR-L 过渡探针：`apps/cxrl-probe/README.md`
- CXR-L Token 与状态：`apps/cxrl-probe/docs/CXRL-TOKEN-AND-STATE-FLOW.md`
- 活动边界与 Session 设计：`apps/cxrl-probe/docs/ACTIVITY-SESSION-AGENT-DESIGN.md`
- 当前结构化输出 Schema：`apps/cxrl-probe/schemas/activity-session-update.schema.json`
- 工程链路可视化：`docs/visuals/reality-memory-engine-flow-v1.3.html`
