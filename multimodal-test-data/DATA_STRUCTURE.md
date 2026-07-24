# 多模态测试数据结构说明

这份文档说明 `multimodal-test-data` 里的样本如何映射到 Reality Memory Engine 的核心数据链路。正式字段以
[`Reality-Memory-Multimodal-Data-Contract-v1.0.md`](../docs/engineering/Reality-Memory-Multimodal-Data-Contract-v1.0.md)
和 `contracts/reality-memory/v1/` 为准；本目录保存少量可复现的真实输入。

## 核心概念

`Session`，中文可以理解为“采集会话”。它表示用户打开一次现实记忆采集后的连续时间窗口。一个会话里可以同时出现图片、音频、戒指传感器、设备状态和审计事件。这个样本里的会话文件是：

```text
datasets/2026-07-24-ios-cxrl-session-001/sessions/ce998edb-cc5f-4c18-a93f-55d6b97e7f9d/session.json
```

`EvidenceItem`，中文可以理解为“原始证据”。它是短期保存的图片、短音频或未来的短视频、传感器片段。证据只用于结构化分析、交叉验证和审计，不应该作为长期记忆本体保存。

`Observation`，中文可以理解为“观察记录”。它描述某个证据是什么时间采的、由什么触发、文件在哪里、当前是否已经分析。本样本里图片观察在 `session.json` 的 `observations` 中，音频观察在 `audioObservations` 中。

`AtomicObservation`，中文可以理解为“原子观察”。它是解析器下一步要产出的统一结构，例如“图片里可能有一碗汤”“音频里用户表达不喜欢这个食物”。当前数据包还没有解析器输出，所以只有原始观察和证据。

`MemoryEvent`，中文可以理解为“记忆事件”。它是系统最终允许长期保存的事实变更来源。这个样本还没有生成 `MemoryEvent`，后续解析器和候选审核链路会用这些证据来生成候选，再决定是否沉淀。

## 数据集清单

每个数据集目录都有一个 `manifest.json`。它是为了测试方便额外生成的总清单，字段含义如下：

- `schemaVersion`：测试数据包清单版本，目前是 `rme.test-fixture.v1`。
- `datasetId`：数据集 ID，和目录名一致。
- `source`：数据来源，包括 App 包名、设备型号、拉取时间和手机沙盒路径。
- `session`：采集会话摘要，包括会话 ID、开始时间、状态、采集间隔、音频策略等。
- `counts`：媒体和日志数量统计。
- `mediaTimeline`：跨模态媒体时间轴，已经把图片和音频按时间排序。
- `logs`：调试日志文件引用。
- `notes`：采集样本的已知限制。

## 会话结构

`session.json` 是手机 App 原始会话记录。关键字段如下：

- `id`：会话 ID。
- `schemaVersion`：手机端会话记录版本，本样本为 `rme.capture-session.v1`。
- `startedAt`：会话开始时间，UTC。
- `state`：会话当前状态，本样本是 `paused`。
- `intervalSeconds`：周期图片采集间隔，本样本是 30 秒。
- `retainLocalSamples`：是否在手机本地保留原始样本，本样本为 `true`。
- `uploadAllowed`：是否允许上传，本样本为 `false`。
- `localMediaTTLSeconds`：本地原始媒体保留时间。
- `audioPolicy`：VAD 音频切分策略，例如阈值、静音结束时长、最长片段时长、音频编码。
- `observations`：图片观察列表。
- `audioObservations`：音频观察列表。
- `auditEvents`：会话内审计事件，例如会话开始、图片采集成功、音频片段完成、前后台变化。

## 图片观察

图片观察位于 `session.json` 的 `observations` 数组。每条记录对应一个 `evidence/*.jpg` 文件。

关键字段：

- `id`：图片观察 ID。
- `scheduledAt`：计划采集时间。
- `completedAt`：实际采集完成时间。
- `captureLatencyMilliseconds`：从计划采集到完成的延迟。
- `trigger`：触发来源，本样本为 `PERIODIC`，即周期采集。
- `outcome`：采集结果，本样本为 `SUCCEEDED`。
- `analysisState`：分析状态，本样本为 `PENDING_LOCAL`，表示还没有进入结构化解析。
- `localMediaReference`：相对会话目录的图片文件路径。
- `applicationState`：采集发生时手机 App 状态。
- `wearingStatus`：眼镜佩戴状态；本样本仍是 `未知`。

## 音频观察

音频观察位于 `session.json` 的 `audioObservations` 数组。每条记录对应一个 `evidence/*.pcm` 文件。

关键字段：

- `id`：音频观察 ID。
- `startedAt`：VAD 判定语音片段开始时间。
- `endedAt`：VAD 判定语音片段结束时间。
- `durationMilliseconds`：片段时长。
- `trigger`：触发来源，本样本为 `SESSION_VAD`，即会话内语音活动检测。
- `codec`：原始音频编码，本样本为 `PCM_S16LE_16KHZ`。
- `channels`：声道数，本样本为 1。
- `peakDBFS`：片段峰值音量，用于粗略判断是否录到有效声音。
- `analysisState`：分析状态，本样本为 `PENDING_LOCAL`。
- `localMediaReference`：相对会话目录的 PCM 文件路径。

`derived/wav/*.wav` 是同一段 PCM 音频加 WAV 头后的派生文件，方便播放器和人工听检。正式解析器应优先使用 `localMediaReference` 指向的原始 PCM，或明确记录自己使用了派生 WAV。

## 两类样本

`2026-07-24-ios-cxrl-session-001` 用于图片与 VAD 音频测试。它没有持久化的戒指原始
IMU，不能测试传感器闭环。

`2026-07-24-glasses-mounted-ring-small-001` 是最小兼容样本。它包含外置戒指固定在
眼镜框时的 338 个 IMU 样本，以及同一旧手机会话中的 5 张图片和 1 段音频。它可
测试旧数据导入和时间关联，但不是 RV101 本机传感器结果。

## 调试事件

`debug-events.ndjson` 是 App 级调试日志，每行一个 JSON 对象。它不等同于会话事实，但对排查设备状态很有用。

本样本中它包含：

- 手机 App 前后台变化。
- Rokid 授权和 Custom View 状态。
- 眼镜 BLE 连接和断开。
- 戒指扫描、连接、设备确认、普通双击、开启传感器等事件。

需要注意：第一包导出没有会话内的戒指传感器样本文件。第二包才包含一段很小的
外置戒指 IMU 闭环样本。

## 时间对齐规则

后续解析器和沉淀链路应优先使用同一 `capture_window_id`，并结合双时间标尺：

- 图片优先使用 `completedAt` 表示证据形成时间，`scheduledAt` 表示触发计划时间。
- 音频使用 `startedAt` 到 `endedAt` 表示声音片段窗口。
- 审计事件使用 `occurredAt`。
- 调试事件使用 `date`。
- 外置戒指原始样本保留 `timestampMilliseconds` 设备相对时间，批次保留
  `receivedAt` 手机接收时间。两者不能互相覆盖。
- 历史手机媒体没有记录单调时钟，标准化后明确为 `null` 并标记
  `clock_sync_method=LEGACY_IMPORT`。

跨模态合并时，不建议只按数组顺序推断关联关系。正确做法是使用时间窗口，例如：

- 某段音频落在某张图片采集前后 10 到 30 秒内，可以作为同一现实片段的候选上下文。
- 戒指快速移动事件如果有持续时间，应记录开始、峰值和结束时间，再去触发或解释附近的图片与音频。
- 如果多个证据互相矛盾，应保留候选置信度和来源，不要直接覆盖长期事实。

## 到正式链路的映射

当前样本可以进入下面这段最小链路：

```text
Session
→ EvidenceItem
→ 图片/音频解析器
→ AtomicObservation
→ ObservationBundle
→ MemoryCandidate
```

它还不能直接覆盖完整链路，因为当前缺少：

- RV101 原生 `SensorManager` 六轴样本。
- 图片解析器输出。
- 音频转写和语义解析输出。
- ActivityEpisode，也就是“活动片段”，例如一次吃饭、一段通勤或一次找东西过程。
- MemoryEvent，也就是可持久化的事实变更。
- StateProjection，也就是由事件流推导出的当前状态。

这个数据包的价值在于固定少量真实输入和兼容映射。正式眼镜 App 上机后，原生图片、
短视频、8 通道音频和六轴数据必须建立新的数据集，不能覆盖历史样本。
