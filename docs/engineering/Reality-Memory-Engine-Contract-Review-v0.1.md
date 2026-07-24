# Reality Memory Engine 数据契约 Review v0.1

## 结论

当前总方向是合理的：多模态采集先进统一入口，再转成统一观察，最后只有 `MemoryEvent` 成为长期事实。真正需要收紧的是边界：现在 iOS App 导出的 `session.json` 还是“采集清单”，不能直接当成最终记忆核心契约。

第一阶段应先固化三层：

1. `CaptureSession`：采集会话。它描述用户何时允许设备采集、设备链路是否可用、采集策略是什么。它不是现实活动，也不是记忆事实。
2. `SourceEnvelope` / `EvidenceItem`：来源信封和短暂证据。前者回答“这条输入从哪里来、什么时候来、在什么策略下产生”，后者回答“媒体证据临时在哪里、多久删除、是否加密”。它们仍然不是事实。
3. `AtomicObservation` 到 `MemoryCandidate`：原子观察和记忆候选。模型只能写观察和候选；候选通过规则、置信度、冲突和用户纠正后，才追加成 `MemoryEvent`。

`ActivityEpisode` 要放在采集之后做。它是“做饭、找东西、阅读”这类现实活动段，不应该和手机端采集 Session 混成一个东西。

## 当前 iOS 实现状态

统一手机 App 位于 `apps/mobile-app/`。它现在可以作为 Phase 0 的采集入口：

- 图片：手动拍照和周期拍照都写入同一个 `ProbeCaptureSession`。
- 音频：已支持 30 秒手动音频/VAD 测试；本轮新增了会话内短音频/VAD 开关，命中的语音片段会写入同一个 `session.json`。
- 留存：默认只保留元数据；只有用户打开“保留本地样本”后，JPEG/PCM 才写入本地 `evidence/`。
- 审计：断连、摘下、暂停、结束、App 生命周期变化都会写入 audit events。

这已经足够做真机验证，但还不是最终后端表结构。

## 主要问题

### 1. Observation 现在混了三件事

`ProbeCaptureObservation` 现在同时表达：

- 一次采集尝试是否成功。
- 可能存在的图片证据。
- 后续是否待分析。

正式契约里应拆成：

- `capture_attempt`：采集尝试，记录成功、失败、跳过和原因。
- `SourceEnvelope`：来源信封，统一图片、音频、短视频、传感器、按键、佩戴事件。
- `EvidenceItem`：短暂证据，记录媒体引用、TTL、加密和删除状态。

这样短视频和音频进来时，不需要新增一套平行结构。

### 2. 音频格式不能只靠假设

当前代码把音频标为 `PCM_S16LE_16KHZ`，这是基于 CXR-L 当前返回值的工程假设。真机测试必须核对：

- SDK 回调里的 codec/type/channels。
- PCM 实际采样率和播放速度。
- ASR 是否正常。
- 不同音频 mode 是否改变降噪、波束或通道。

所以正式 `EvidenceItem` 里应有 `codec`、`sample_rate_hz`、`channels`、`duration_ms`、`byte_count`、`capture_mode`，采样率未知时必须允许 `unknown`，不能写死成事实。

### 3. ActivityEpisode 不应由 App 直接判断

手机 App 只知道采集 Session：用户开始、暂停、恢复、结束，眼镜断连、摘下、后台等。这是设备和授权边界。

`ActivityEpisode` 是语义边界：比如同一个采集 Session 里可能先“做饭”，中间“接电话”，再回来“做饭”。它应由后端 Temporal Fusion 根据多张图片、短音频、传感器和用户话语综合判断。App 最多提供候选信号，不应直接写 Episode。

### 4. MemoryEvent 必须有受控事件类型

`MemoryEvent` 是唯一长期事实源，建议首版只放少量类型：

- `OBJECT_OBSERVED_AT`：观察到某物在某位置。
- `OBJECT_MOVED`：某物从 A 到 B 的位置变化。
- `CONSUMABLE_LEVEL_OBSERVED`：耗材余量被观察到。
- `PREFERENCE_STATED`：用户表达偏好。
- `TASK_STATED`：用户表达任务或提醒需求。
- `USER_CORRECTION`：用户纠正上一条或某条记忆。
- `FORGET_REQUESTED`：用户要求删除或近窗遗忘。

事件类型少一点，后面 StateProjection 才能可重放、可纠错。

### 5. 戒指原始信号、动作判断和采集触发必须分层

戒指接入后不能把每个 IMU 样本直接当成 `AtomicObservation`，也不能把一次阈值命中直接当成用户行为事实。首版分为三层：

1. `rme.ring-imu-batch.v1`：原始六轴批次。完整保留 `sequence_start`、设备相对时间、手机接收时间和原始整数值，写入 `ring/imu.ndjson`。它是短期结构化证据，不是语义观察。
2. `ProbeRingMotionAssessment`：手机侧动作信号判断。首版只表达“检测到快速移动”，同时保存规则版本、阈值档位和峰值指标。它是可解释的候选信号，不等于“拿钥匙”“吃饭”等现实活动。
3. 图片和音频采集结果：通过 `triggerDecisionID` 引用动作判断。这样可以审计某次快速移动是否请求了图片/音频、采集是否成功，也可以在后续解析时按同一时间窗组合。

戒指时间目前有两套标尺：

- `device_timestamp_ms`：戒指侧相对时间，用于排序、间隔和窗口。
- `received_at`：手机收到整批数据的绝对时间，用于和眼镜证据粗对齐。

同一批各样本的手机时间可以根据最后一个设备时间戳向前估算，但估算值不能覆盖原字段，也不能冒充精确硬件同步时间。正式 `SourceEnvelope` 需要补充 `clock_domain`、`clock_sync_method` 和 `time_uncertainty_ms`。

“快速移动触发眼镜”属于 `CaptureIntent`（采集意图），不是 `MemoryEvent`。它只说明系统为何发起一次取证，不说明现实世界发生了什么。图片、音频和后续解析结果仍需经过观察、组合、活动段和记忆候选流程。

## 最小闭环建议

第一阶段不要急着做复杂 Agent。建议按这个闭环落地：

```text
CaptureSession（采集会话）
  -> SourceEnvelope（来源信封）
  -> EvidenceItem（短暂证据）
  -> AtomicObservation（原子观察）
  -> ObservationBundle（观察包）
  -> ActivityEpisode（活动段）
  -> MemoryCandidate（记忆候选）
  -> MemoryEvent（记忆事件）
  -> StateProjection（当前状态）
```

中文理解：

- `CaptureSession`：一次用户允许设备采集的窗口。
- `SourceEnvelope`：每条输入的统一外壳，保证来源、时间、策略、幂等都可追溯。
- `EvidenceItem`：短期图片、短视频、短音频或传感器窗口，完成结构化后删除。
- `AtomicObservation`：模型或解析器看到的最小观察，例如“疑似钥匙在茶几右侧”。
- `ObservationBundle`：把同一时间窗或同一变化的多个观察放在一起。
- `ActivityEpisode`：一段现实活动，例如“做晚饭”。
- `MemoryCandidate`：可能成为记忆的候选断言，还不是事实。
- `MemoryEvent`：追加式事实变化，是长期事实源。
- `StateProjection`：从事件流算出的当前状态，例如“钥匙现在可能在茶几右侧”。

## 下一步

1. 用当前 iOS App 跑真机：开启会话内短音频/VAD，导出 `session.json`，确认音频片段、策略快照和审计事件完整。
2. 新增正式 JSON Schema：`source-envelope.schema.json`、`evidence-item.schema.json`、`atomic-observation.schema.json`、`memory-candidate.schema.json`、`memory-event.schema.json`。
3. 把 `ProbeCaptureObservation` 映射到正式 `SourceEnvelope + EvidenceItem`，不要让后端直接依赖 iOS 临时结构。
4. 再做图片/音频解析器，先输出 `AtomicObservation`，不要直接写 `MemoryEvent`。
