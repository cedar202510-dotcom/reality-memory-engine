# 云端记忆平台技术架构

> 文档版本：v0.2  
> 负责范围：数据接入、证据管理、模态解析、时间融合、事实事件和当前状态  
> 上游接口：[数据采集技术架构](01-Data-Capture-Architecture.md)  
> 下游接口：[Agent 调用技术架构](03-Agent-Access-Architecture.md)

## 1. 目标

云端 Memory Platform 接收眼镜、戒指、手机和未来设备产生的短期证据，将模型
输出约束为可追溯的观察，再通过跨模态融合、实体归因和事实门控形成长期记忆。

平台必须同时满足：

- 不依赖某一种硬件或厂商 SDK。
- 图片、短视频、音频、传感器和结构化事件进入同一事实链。
- 单次模型结果不能直接成为事实。
- 每条事实可以追溯到候选、观察和来源。
- 用户纠正通过新事件表达，不原地篡改历史。
- 原始 Evidence 完成结构化或达到 TTL 后删除。
- 当前状态可以从事件流重新计算。
- Agent 只能通过受控 API 使用结构化记忆。

## 2. 输入和输出边界

### 2.1 采集团队交付给云端

每个测试数据包或在线上传批次至少包含：

```text
capture-session.json
capture-intents.ndjson
source-envelopes.ndjson
evidence-items.ndjson
sensor-windows.ndjson
capture-attempts.ndjson
audit-events.ndjson
evidence/
  images
  short-videos
  short-audio
  optional sensor payloads
```

这些数据只说明“采集了什么、为什么采集、来自哪里”，不应包含未经云端判断的
最终活动、偏好、对象位置或其他事实。

### 2.2 云端交付给调用层

```text
atomic-observations
observation-bundles
action-segments
activity-episodes
memory-candidates
memory-events
state-projections
query-results
memory-signals
audit-records
```

调用层默认不接收原始图片、视频和音频。

## 3. 总体处理链

```text
SourceEnvelope + EvidenceItem
  -> Ingest 校验和幂等去重
  -> Evidence 安全扫描和临时保存
  -> 按模态选择解析器
  -> AtomicObservation（原子观察）
  -> ObservationBundle（观察组合）
  -> ActionSegment（动作片段）
  -> ActivityEpisode（活动段）
  -> MemoryCandidate（记忆候选）
  -> Entity Resolution（实体归因）
  -> Policy / Confidence / Conflict Gate
  -> MemoryEvent（追加式事实事件）
  -> StateProjection（当前状态）
  -> Query / Timeline / Signal
  -> Evidence 删除
```

每一层都有独立编号、来源引用、Schema 版本和处理状态。任何一层失败都不能跳过
中间门控直接更新当前状态。

## 4. 服务划分

| 服务 | 中文职责 |
| --- | --- |
| Device Registry | 管理用户、家庭、设备绑定、设备证书和能力档案 |
| Session & Policy Service | 管理采集会话、签名策略、暂停、恢复和全局关闭 |
| Ingest Gateway | 验证设备身份、来源信封、Schema、大小、TTL 和幂等 |
| Evidence Service | 管理短期证据、上传授权、加密、完整性、TTL 和删除 |
| Perception Orchestrator | 根据模态、设备能力和用途选择解析器 |
| Image Extractor | 从单图或前后帧产生视觉原子观察 |
| Video Extractor | 从 2-3 秒短视频产生动作和状态变化观察 |
| Audio Extractor | 执行 ASR、说话人角色、显式偏好/任务和音频事件抽取 |
| Sensor Extractor | 从 IMU 窗口产生运动强度、候选动作和质量观察 |
| Temporal Fusion | 对齐时间窗，构建观察组合、动作片段和活动段 |
| Candidate Store | 保存尚未成为事实的现实断言及其支持和反证 |
| Entity Resolver | 将“这个杯子”“胡辣汤”“茶几右侧”等归因到稳定实体或位置 |
| Memory Core | 执行策略、置信度、冲突和交叉验证门控，追加事实事件 |
| Event Store | 保存不可变的长期事实事件和纠正关系 |
| Projection Engine | 从事件流计算对象、偏好、任务和活动的当前状态 |
| Query Service | 提供查找、时间线、状态和解释接口 |
| Signal Service | 把值得关注的状态变化转成可订阅信号 |
| Privacy & Audit | 删除、近窗遗忘、访问审计和最小墓碑 |

首个闭环可以部署成较少的进程，但逻辑职责不能混合。例如单个后端进程可以同时
承载 Ingest 和 Evidence，但不能让 HTTP Handler 直接写状态投影。

## 5. 核心数据对象

### 5.1 CaptureSession：采集会话

中文含义：一次用户授权设备采集的运行窗口。

它包含：

- 用户、家庭和设备。
- 开始、暂停、恢复、结束时间。
- 允许的模态和预算。
- 策略版本。
- 设备连接和结束原因。

它不包含“用户正在做饭”这类语义。

### 5.2 CaptureIntent：采集意图

中文含义：某个触发器请求设备收集哪些证据。

例如戒指检测到快速移动，请求眼镜拍一张图并打开 8 秒 VAD 窗口。它解释采集
原因，但不证明用户完成了某个动作。

### 5.3 SourceEnvelope：来源信封

中文含义：一条输入的统一外壳。

它保存：

- 生产设备、触发设备和中继设备。
- 采集会话和采集意图。
- 发生时间、观察时间和时间不确定性。
- 策略版本、模态和 Schema。
- Evidence 引用和幂等键。

### 5.4 EvidenceItem：短期证据

中文含义：完成结构化后要删除的图片、短视频、音频或传感器窗口。

Evidence 不是长期记忆。它只为解析、交叉验证、调试授权和审计服务。

### 5.5 AtomicObservation：原子观察

中文含义：解析器从一个局部输入中得到的最小观察。

例子：

- “画面中疑似有一碗胡辣汤。”
- “用户说：这个胡辣汤不好喝。”
- “右手出现一次高强度旋转动作。”
- “疑似钥匙位于茶几右侧。”

原子观察必须包含：

```json
{
  "schema_ref": "rme.atomic-observation.v1",
  "observation_id": "uuid",
  "observation_type": "USER_UTTERANCE",
  "subject_ref": {
    "kind": "UNRESOLVED_ENTITY",
    "temporary_id": "temp-food-1"
  },
  "predicate": "PREFERENCE_SENTIMENT",
  "value": {
    "sentiment": "NEGATIVE",
    "text": "这个胡辣汤不好喝"
  },
  "confidence": 0.94,
  "occurred_interval": {
    "start": "2026-07-24T10:00:05Z",
    "end": "2026-07-24T10:00:08Z",
    "uncertainty_ms": 250
  },
  "source_envelope_ids": ["uuid"],
  "evidence_item_ids": ["uuid"],
  "extractor": {
    "name": "audio-extractor",
    "version": "0.1.0",
    "model_ref": "configured-model-version"
  },
  "policy_snapshot_id": "uuid"
}
```

模型不知道的字段必须为空或标为未解析，不能编造实体编号、店铺或商品。

### 5.6 ObservationBundle：观察组合

中文含义：把同一时间窗、同一对象或同一变化的多个观察放在一起。

例如：

- 图片：桌上出现胡辣汤。
- 音频：用户说“这个胡辣汤不好喝”。
- 时间：两者相差 4 秒。
- 未来订单事件：该时段存在某商家的胡辣汤订单。

Bundle 只建立关联，不自动确认因果。

### 5.7 ActionSegment：动作片段

中文含义：由多个连续观察支持的一小段动作，例如拿起、放下、开封、倾倒或翻页。

ActionSegment 可以有多个竞争解释：

- `PICK_UP_OBJECT`，置信度 0.62。
- `MOVE_HAND_NEAR_OBJECT`，置信度 0.31。

系统不应为了得到单一答案过早丢弃合理分支。

### 5.8 ActivityEpisode：活动段

中文含义：目标和上下文相对稳定的一段现实活动，例如吃饭、做饭、阅读或找东西。

同一采集 Session 可以包含多个活动段，一个活动也可能跨越短暂的采集断点。
ActivityEpisode 由云端时间融合产生，设备端不能直接写入。

### 5.9 MemoryCandidate：记忆候选

中文含义：可能成为长期记忆、但尚未通过事实门控的现实断言。

候选至少保存：

- 候选类型和结构化值。
- 主体、对象、地点和时间。
- 支持观察和反证观察。
- 实体归因状态。
- 置信度及其计算依据。
- 策略和允许用途。
- 过期时间。

### 5.10 MemoryEvent：记忆事件

中文含义：通过门控后追加写入的事实变化，是唯一长期事实源。

首阶段建议收紧为：

- `OBJECT_OBSERVED_AT`
- `OBJECT_MOVED`
- `CONSUMABLE_LEVEL_OBSERVED`
- `PREFERENCE_STATED`
- `TASK_STATED`
- `USER_CORRECTION`
- `FORGET_REQUESTED`

事件不可原地修改。用户纠正通过 `USER_CORRECTION` 指向被纠正事件，投影引擎
重新计算当前状态。

### 5.11 StateProjection：状态投影

中文含义：从有效事件流计算出的当前最佳状态。

例子：

- 钥匙当前位置候选及新鲜度。
- 某耗材的当前余量等级。
- 用户对胡辣汤的负面偏好。
- 尚未完成的任务。

投影不是新的事实来源。删除数据库中的投影后，应能从事件流重新构建。

## 6. Ingest 接入流程

```text
接收上传
  -> 验证设备证书或中继授权
  -> 验证 owner / household / device 绑定
  -> 验证 Schema 版本
  -> 验证 PolicySnapshot
  -> 验证 TTL、大小、模态和内容哈希
  -> 使用 idempotency_key 去重
  -> 事务写入 SourceEnvelope 元数据
  -> 创建 Evidence 临时存储记录
  -> 发布 perception.requested
```

拒绝原因必须结构化：

- `DEVICE_NOT_BOUND`
- `CREDENTIAL_EXPIRED`
- `POLICY_INVALID`
- `SCHEMA_UNSUPPORTED`
- `EVIDENCE_EXPIRED`
- `MODALITY_NOT_ALLOWED`
- `SIZE_LIMIT_EXCEEDED`
- `HASH_MISMATCH`
- `OWNER_MISMATCH`

上传失败不等于现实事件没有发生，只表示系统没有获得可用证据。

## 7. 模态解析

### 7.1 图片

图片解析器输出：

- 场景和空间类型候选。
- 对象候选、可见属性和相对位置。
- 余量、开合、使用痕迹等状态候选。
- OCR 文本和页码候选。
- 画质、遮挡、隐私和可用性。

单图不能可靠确认“对象移动”。对象移动至少需要前后观察、显式语音或其他事件。

### 7.2 短视频

短视频只用于静态帧难以表达的连续动作：

- 拿起和放下。
- 倒出和消耗。
- 开合容器。
- 快速移动。

解析器应先提取关键帧和运动片段，再输出观察，不把视频长期保存。

### 7.3 音频

音频解析器分两步：

1. ASR 和声音事件层：文本、时间戳、语音质量、说话人角色候选。
2. 语义层：偏好、任务、命名、纠正或现场描述。

“这个好难吃”不能在没有上下文时直接绑定到具体商家商品。它可以形成一个临时
对象上的负面偏好观察，等待图片、订单或用户追问完成归因。

### 7.4 传感器

传感器解析器可以输出：

- 运动强度。
- 姿态变化。
- 候选手势。
- 设备是否稳定。
- 传感器窗口质量和丢包。

传感器通常用于调度和交叉验证。除非有经过评测的动作模型和其他证据支持，不应
单独形成“拿起钥匙”等语义事实。

### 7.5 结构化线上事件

订单、日历、智能家居和用户明确确认属于结构化来源。它们可以提高实体归因和
候选置信度，但仍要绑定来源、授权和时间。

例如外卖订单可以帮助判断画面中的胡辣汤属于哪个商家，但不能证明用户表达的
“不好喝”一定针对订单中的全部商品。

## 8. 时间融合

时间融合负责把多模态观察放入正确上下文。

输入：

- 原子观察时间区间。
- 时间不确定性。
- 采集意图关联。
- 设备、空间、对象和活动候选。
- 观察质量和置信度。

处理原则：

1. 同一 `capture_intent_id` 是强关联，不是事实等价。
2. 时间窗大小要包含两侧不确定性。
3. 相同对象、空间和话语指代提高关联分。
4. 明确用户语音优先于弱模型猜测。
5. 新活动边界需要连续支持或显式强信号。
6. 空窗不自动表示活动结束。
7. 保留竞争 Episode 和实体分支，直到证据足够。

## 9. 事实门控

候选写入 `MemoryEvent` 前依次检查：

```text
候选 Schema 合法
  -> 允许的记忆类型
  -> 策略允许长期保存该结构化结果
  -> 主体和家庭归属明确
  -> 实体归因达到类型要求
  -> 置信度达到该事件阈值
  -> 没有未解决的高强度冲突
  -> 满足所需交叉验证
  -> 幂等检查
  -> 追加 MemoryEvent
```

不同事件使用不同门槛：

| 事件 | 最小建议 |
| --- | --- |
| 明确偏好表达 | 清晰语音 + 可解析对象，可直接形成偏好事件 |
| 模糊偏好表达 | 保留候选，等待上下文或追问 |
| 对象被观察在某处 | 一次高质量视觉观察可以写事件，但投影保留置信度和新鲜度 |
| 对象移动 | 前后位置、动作证据或显式确认 |
| 耗材余量 | 可见包装实例 + 余量等级，提醒需多次趋势 |
| 用户任务 | 明确任务内容和时间对象；歧义时追问 |

## 10. 示例：吃饭时表达负面偏好

### 10.1 只有图片和音频

```text
图片观察：桌上疑似一碗胡辣汤
音频观察：用户说“这个胡辣汤不好喝”
时间关系：相差 3 秒，同一采集意图窗口
  -> ObservationBundle
  -> ActivityEpisode：用餐
  -> MemoryCandidate：用户不喜欢当前胡辣汤
```

如果图像和语音足够清晰，可以形成：

```text
PREFERENCE_STATED
subject = 当前用户
target = 食物类别“胡辣汤”
sentiment = NEGATIVE
scope = 当前实例或一般偏好待定
```

不能凭空补充商家、商品编号或订单。

### 10.2 加入外卖订单

```text
线上订单：10:02 某商家胡辣汤
图片：10:20 疑似胡辣汤
音频：10:21 “这家的胡辣汤不好喝”
```

系统可以提高商家级归因置信度，但仍应保存推理来源。如果用户只说“这个不好喝”，
商品级归因仍可能需要追问或后续观察。

## 11. 删除和近窗遗忘

删除范围可能包含：

- 单条记忆事件。
- 某个实体。
- 最近 N 分钟。
- 某次采集 Session。
- 某个 Agent 的授权和派生缓存。

处理顺序：

```text
接收删除请求
  -> 创建 ForgetRequest
  -> 阻断相关 Evidence 上传和解析
  -> 删除设备和云端短期 Evidence
  -> 使相关候选、事件或索引失效
  -> 重算 StateProjection
  -> 清理 Query / Agent 缓存
  -> 返回分层删除回执
```

审计只保留证明删除发生所需的最小字段，不保留可还原内容。

## 12. 一致性和失败处理

| 失败 | 处理 |
| --- | --- |
| 重复上传 | Ingest 使用幂等键返回原结果 |
| 乱序到达 | 按来源时间和不确定性重排，不依赖接收顺序 |
| 解析器超时 | 独立重试，不重复创建观察 |
| 模型输出不合法 | Schema 校验失败，进入可审计错误队列 |
| 实体归因冲突 | 保留竞争候选，不覆盖既有事实 |
| Event 写入成功但投影失败 | 通过 Outbox 重放 Projection |
| 删除与解析竞态 | 删除标记优先，解析结果不得继续写入 |
| 策略在处理中收紧 | 在候选和事件门控处再次检查 |
| Evidence 已过期 | 不重试模型，记录不可处理原因 |

## 13. 数据存储建议

| 数据 | 建议存储 | 留存 |
| --- | --- | --- |
| SourceEnvelope | PostgreSQL 或事件日志 | 按处理与审计策略 |
| Evidence 元数据 | PostgreSQL | 至删除完成和最小审计结束 |
| 原始 Evidence | 加密对象存储 | 正式链最长约 15 分钟，结构化完成即删 |
| AtomicObservation | PostgreSQL / JSONB | 按调试、审计和产品策略 |
| MemoryCandidate | PostgreSQL | 通过、过期、拒绝或用户删除 |
| MemoryEvent | PostgreSQL 追加式事件表 | 直到用户删除或策略到期 |
| StateProjection | PostgreSQL / 搜索索引 / 缓存 | 可重算 |
| Signal | 队列 + 数据库 | 按投递和审计策略 |

首阶段不要因为未来规模假设提前引入过多基础设施。一个关系数据库、加密对象存储
和可靠任务队列足以跑通最小闭环。

## 14. API 和事件主题

建议最小入口：

```text
POST /v1/source-envelopes
POST /v1/evidence/upload-intents
POST /v1/evidence/{id}/complete
POST /v1/evidence/{id}/deleted
POST /v1/capture-sessions
PATCH /v1/capture-sessions/{id}
```

内部事件：

```text
source.accepted
evidence.ready
perception.requested
observation.created
bundle.updated
episode.updated
candidate.created
candidate.accepted
candidate.rejected
memory-event.appended
projection.updated
signal.created
evidence.delete-requested
evidence.deleted
```

事件消费方必须幂等。主题名称可以调整，但状态转换含义需要冻结。

## 15. 团队并行边界

### 采集团队负责

- 提供真实、版本化、可重放的数据包。
- 保证来源、时间、策略、触发和媒体元数据完整。
- 不在采集包中预写最终活动和事实。

### 云端团队负责

- 用固定测试包开发 Ingest 和解析。
- 输出合法的原子观察和记忆候选。
- 建立事实门控、事件存储和状态投影。
- 提供可供 Agent 使用的查询接口。

### 双方共同负责

- JSON Schema 和兼容版本规则。
- 时间对齐字段。
- 采集意图到 Evidence 的关联。
- 删除、TTL 和幂等测试。
- 真实数据回放的黄金测试集。

## 16. 最小实现顺序

1. 建立版本化 Schema 仓库和契约测试。
2. 实现 SourceEnvelope、EvidenceItem 和 CaptureIntent Ingest。
3. 使用现有真实样本实现图片与音频 Extractor。
4. 输出 AtomicObservation，并保存来源引用。
5. 针对一个场景实现 ObservationBundle 和 MemoryCandidate。
6. 只实现少量 MemoryEvent 类型和事实门控。
7. 实现一种 StateProjection，例如对象当前位置或用户偏好。
8. 提供一个 Query API。
9. 完成 Evidence TTL 删除和回执。
10. 用相同输入包重复运行，验证幂等和可重算。

## 17. 验收标准

- 同一个输入包重复提交不会产生重复事件。
- 每条原子观察能追溯到 SourceEnvelope 和 Evidence。
- 删除 Evidence 后，结构化记忆仍能按策略使用。
- 模型无法直接写 MemoryEvent。
- ActivityEpisode 不由采集 App 创建。
- 用户纠正产生新事件并重算投影。
- 删除请求会阻断竞态中的上传和解析。
- Agent 查询结果包含置信度、新鲜度和可解释来源摘要。
- 关闭或替换某种硬件 Adapter 不需要修改记忆事实模型。

## 18. 尚未冻结的问题

以下内容需要真实数据和评测后再确定：

- 各事件类型的置信度阈值。
- 不同活动的时间融合窗口。
- 图片、短视频和音频解析模型选型。
- 哪些低置信观察可以保留多久。
- 实体归因的自动确认门槛。
- 哪些结构化记忆允许 Agent 主动订阅。

这些开放问题不影响先冻结对象边界、来源关系、幂等、删除和事实写入规则。
