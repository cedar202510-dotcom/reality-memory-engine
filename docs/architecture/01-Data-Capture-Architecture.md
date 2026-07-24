# 数据采集技术架构

> 文档版本：v0.3
> 负责范围：戒指、眼镜、手机、触发、采集、短期证据和云端传输  
> 上游产品文档：[分层技术架构](README.md)  
> 下游接口文档：[云端记忆平台架构](02-Memory-Platform-Architecture.md)
> 通信接口文档：[设备与云端通信](05-Device-Cloud-Communication.md)

## 1. 目标

数据采集层负责把真实世界中的短暂信号变成可追溯、可删除、可重试的数据输入。
它需要回答：

- 哪台设备产生了信号。
- 哪台设备决定发起采集。
- 哪台设备实际采集了图片、短视频或音频。
- 采集时用户是否授权，哪一版策略生效。
- 多设备数据在时间上如何对应。
- 证据如何加密、传输、过期和删除。

数据采集层不判断“用户正在吃饭”“钥匙被放到桌上”等最终语义。它只能产生原始
传感器窗口、设备事件、采集意图和短期 Evidence。

## 2. 当前事实与可行性结论

### 2.1 已验证与已实现事实

- 历史 iOS Reality App 可以通过 CXR-L 获取眼镜图片和短音频。
- 历史 iOS App 可以通过 CoreBluetooth 连接 Ring Sound 戒指。
- 戒指使用 Nordic UART Service，协议版本为 v4。
- 手机可接收戒指 `0x0605` 六轴 IMU 批次，并用透明阈值规则判断快速移动。
- 快速移动判断可以关联一次眼镜图片请求和一个短音频窗口。
- 旧测试链已经留下小型图片、音频和外置戒指 IMU 兼容数据包。
- 正式 `apps/reality-memory-glasses/` 已实现 CameraX 图片/短视频、AudioRecord、
  SensorManager、佩戴广播、会话状态、本地 AES-256-GCM Evidence 队列和测试提醒
  入口。
- 正式 App 已按 v1 契约生成 `CaptureSession`、`CaptureIntent`、
  `CaptureWindow`、`CaptureAttempt`、`SourceEnvelope` 和 `EvidenceItem`。

以上正式眼镜 App 能力是代码实现事实，不等于 RV101 真机已经通过。相机、音频、
传感器、佩戴广播、后台和功耗仍需持有开发线的队友验证。

### 2.2 Android API 层结论

Android 原生平台支持 BLE Central，也就是由 Android 设备扫描并作为 GATT 客户端
连接戒指。RV101 文档表明其 Runtime 基于 Android 12，因此实现路径在软件 API
层成立：

- 使用 `BluetoothLeScanner` 扫描 NUS Service UUID。
- 使用 `BluetoothDevice.connectGatt()` 作为 GATT 客户端连接戒指。
- 订阅 TX Characteristic 通知，向 RX Characteristic 写入 v4 命令。
- Android 12 需要申请 `BLUETOOTH_SCAN` 和 `BLUETOOTH_CONNECT`。

但目前没有找到 Rokid 针对 RV101 明确承诺“第三方 APK 可长期稳定作为 BLE
Central”的官方条款。官方裸机 Sample 也没有 BLE 示例。因此当前结论必须写成：

> Android API 层可实现，RV101 硬件、固件权限、后台连接和多无线电共存仍待真机
> 确认，不能提前标记为已支持。

### 2.3 眼镜直连云端结论

Android App 可以通过 `INTERNET` 和 `ACCESS_NETWORK_STATE` 使用 HTTPS。正式
眼镜 App 已声明网络权限并具备本地加密 Outbox，但尚未实现设备绑定和上传客户端。
眼镜直传云端在标准 Android 层可实现，但仍需要真机验证：

- 眼镜是否能获得稳定、可用且经过验证的互联网连接。
- 后台和熄屏时网络请求是否持续。
- BLE、Wi-Fi、CameraX、AudioRecord 同时工作是否互相影响。
- 上传对温升、耗电和采集延迟的影响。

## 3. 当前设备路径

### 3.1 P0 主路径：眼镜自主触发，眼镜直传云端

```text
Wear Event / Glass IMU / 用户“记一下”
  -> Local Trigger Engine
  -> CaptureIntent
  -> Local PolicyCheck
  -> CameraX / AudioRecord / SensorManager
  -> Encrypted Evidence Buffer
  -> SourceEnvelope + EvidenceItem
  -> Glass Upload Client
  -> Memory Platform Ingest API
```

这是当前正式首选，因为触发和采集都在眼镜本机完成，不依赖手机 App 或戒指存活。

成立条件：

1. RV101 的佩戴广播、SensorManager、CameraX 和 AudioRecord 真机可用。
2. 眼镜 Runtime 可以在受支持的生命周期内保持前台服务。
3. 运动触发、基线采集和媒体策略满足功耗、温升与信息增量要求。
4. 眼镜能直接完成 HTTPS 上传或离线加密排队。
5. 用户暂停、摘下、策略收紧和删除能及时作用到眼镜。

### 3.2 P1 可选戒指路径：直连眼镜或经手机触发

```text
Ring Sound
  -> BLE NUS -> Glass RingAdapter
  或
  -> BLE NUS -> Reality Mobile App
  -> SensorWindow
  -> Local Trigger Engine
  -> CaptureIntent
Glass Runtime
  -> PolicyCheck
  -> Capture
  -> Glass Direct Upload 或 Mobile Relay
```

使用条件：

- 戒指信号能提高显式语音、手势或动作触发价值。
- RV101 可以稳定承担 BLE Central 时优先直连眼镜。
- RV101 不能稳定承担 BLE Central 时由统一手机 App 中继触发。

触发路径和证据上传路径是两个独立选择，不能绑死：

| 触发路径 | 证据上传路径 |
| --- | --- |
| 戒指 -> 眼镜 | 眼镜 -> 云端 |
| 戒指 -> 手机 -> 眼镜 | 眼镜 -> 云端 |
| 戒指 -> 手机 -> 眼镜 | 眼镜 -> 手机 -> 云端 |

手机负责戒指接入，不代表眼镜证据必须再次绕回手机。

主要风险：

- iOS App 后台或被系统终止后，BLE 连接和命令转发不保证持续。
- 手机到原生 Glass Runtime 的本地命令通道尚未实现。
- 手机、眼镜和戒指有三套时钟，必须显式记录不确定性。
- 手机不在附近时，经手机的戒指触发链失效。

### 3.3 P2 低资源降级路径

```text
Wear Event
  -> 5 秒提示和策略确认
  -> CaptureSession ACTIVE
用户显式“记一下” / 极低频基线 / 受限 Glass IMU
  -> CaptureIntent
  -> 有界图片、短视频或短音频
  -> 云端
```

使用条件：

- 自动媒体触发无法达到续航或温升要求。
- 后台生命周期不允许稳定自动采集。
- 用户选择更严格的隐私或功耗模式。

Runtime 可以持续协调，但不得连续录制。降级后优先保留：

- 佩戴后一次提示，建立采集 Session。
- 用户显式“记一下”。
- 低频定时图片作为基线。
- 在设备预算允许时使用眼镜 IMU 或场景差异提高短窗采集密度。
- 音频策略允许时，本地 VAD 只保存命中的短音频片段。
- 静止、低电量、过热或隐私场景降低或停止采集。

### 3.4 历史兼容路径：手机 CXR-L

```text
Ring Sound
  -> iOS Reality App
  -> 手机快速移动规则
  -> CXR-L Photo / Audio
  -> session.json + evidence + ring/imu.ndjson
```

这条路径现在只用于：

- 采集真实多模态样本。
- 验证时间对齐和关联编号。
- 固化采集契约。
- 为云端解析提供输入包。

它不能证明 RV101 原生 Runtime 的 BLE、后台、功耗或直传能力。

## 4. 戒指能力边界

### 4.1 当前协议事实

| 能力 | 当前状态 | 对产品的影响 |
| --- | --- | --- |
| 设备识别 | 广播名可能为空；NUS 和协议响应可确认设备 | 首次连接需用户选择，成功后保存已确认设备标识 |
| 佩戴事件 | 当前协议没有 | 不能真正做到“检测戴上后自动启动” |
| 实时 IMU | `0x0601` 开启 BLE 上报 | 断连后自动关闭，需要重新请求 |
| 本地 IMU | 只在手势模式可用 | 录音模式下 `0x0601` 可能返回 `DEVICE_BUSY` |
| 模式查询 | 当前协议没有 | App 不能可靠读取当前模式 |
| 模式切换 | 按键单击在录音/手势模式间切换 | 当前仍依赖用户动作，除非固件新增命令 |
| HMM 手势 | `0x0702`，无需开启实时 IMU 上报 | 可作为比原始流更省电的触发来源 |
| 原始 IMU | 批量 `0x0605`，含设备相对时间 | 适合校准和短窗动作判断，不是语义事实 |

### 4.2 “戴上后自动工作”的可实现范围

当前硬件无法直接报告“戴上”。可以实现的是：

1. 已知戒指出现在 BLE 范围并可连接时自动重连。
2. 连接后自动请求 `0x0601`。
3. 如果返回忙碌，记录模式阻塞并提示用户切换到手势模式。
4. 收到按键单击事件后自动重试 `0x0601`。

这不等同于真正的佩戴检测。正式产品若要求无操作持续感知，需要供应商提供以下
至少一项：

- 佩戴/皮肤接触事件。
- 查询和设置录音/手势模式的命令。
- 在戒指本机运行低功耗动作门控并只上报候选事件。
- 允许实时 IMU 与录音能力并存。

### 4.3 功耗策略

不建议把 25Hz 六轴原始流作为全天默认模式。优先级建议：

1. 优先使用戒指内部 `0x0702` HMM 手势或固件侧动作事件。
2. 在校准、算法采样或活动短窗内开启 `0x0605`。
3. 若确需持续 IMU，必须实测戒指和眼镜续航、丢包、温升与蓝牙共存。
4. 云端只接收必要的传感器窗口，不接收无限原始流。

当前手机端 `rapid-movement.raw-threshold.v1` 只能作为可解释的测试规则，不能直接
升级为产品动作模型。

## 5. 眼镜 Runtime 模块

| 模块 | 中文职责 |
| --- | --- |
| `WearStateReceiver` | 接收佩戴、摘下和镜腿状态 |
| `CaptureSessionCoordinator` | 管理本次允许采集的状态和生命周期 |
| `RingAdapter` | 扫描、连接戒指并解析 NUS v4 |
| `GlassSensorAdapter` | 读取眼镜 IMU 和设备状态 |
| `LocalTriggerEngine` | 把传感器窗口和设备事件变成采集意图 |
| `LocalPolicyEngine` | 每次启动媒体 API 前检查签名策略 |
| `CaptureScheduler` | 处理定时、动态触发、预算、冷却和去抖 |
| `CameraAdapter` | CameraX 单图、前后帧和短视频 |
| `AudioAdapter` | AudioRecord、本地 VAD 和显式短语音 |
| `EncryptedEvidenceBuffer` | 短期加密保存、TTL 和安全删除 |
| `EnvelopeBuilder` | 生成统一来源信封和证据元数据 |
| `UploadClient` | HTTPS 直传、幂等重试和断网恢复 |
| `LocalCommandTransport` | 在兼容路径接收手机发来的采集意图 |
| `AuditReporter` | 记录策略命中、采集尝试、上传和删除结果 |

正式 `apps/reality-memory-glasses/` 已实现佩戴接收、会话协调、眼镜 IMU、
确定性运动触发、CameraX、AudioRecord、本地加密队列、来源信封和审计。当前仍缺
戒指 Adapter、签名策略、本地 VAD、上传客户端、TTL 实际清理、删除回执和手机
兼容命令。旧
`apps/rokid-glass-probe/` 只保留为 Camera 与系统事件排障基线。

## 6. 采集状态机

`CaptureSession` 是采集会话，表达用户授权和设备运行窗口，不表达现实活动。

```text
IDLE
  -> 佩戴并获得有效策略
  -> NOTICE_COUNTDOWN
  -> 用户未关闭
  -> ACTIVE

ACTIVE
  -> 用户暂停 / 隐私策略收紧 -> PAUSED
  -> 暂时断网 -> ACTIVE_OFFLINE
  -> 摘下 / 本次关闭 / 策略过期 -> ENDED
  -> 温度或权限阻断 -> BLOCKED

PAUSED
  -> 用户恢复且策略有效 -> ACTIVE
  -> 摘下 / 关闭 -> ENDED

ACTIVE_OFFLINE
  -> 网络恢复 -> ACTIVE 并上传未过期证据
  -> TTL 到期 -> 删除证据并保留最小审计
```

进入 `ACTIVE` 不意味着一直调用相机或麦克风。每次采集仍要独立执行 PolicyCheck。

## 7. 采集意图

`CaptureIntent` 表示“为什么需要收集哪种证据”，是戒指、手机和眼镜之间的关键
接口。它不是观察，也不是记忆事实。

建议最小结构：

```json
{
  "schema_ref": "rme.capture-intent.v1",
  "capture_intent_id": "uuid",
  "source_session_id": "uuid",
  "created_at": "2026-07-24T10:00:00.123Z",
  "expires_at": "2026-07-24T10:00:03.123Z",
  "trigger": {
    "type": "RING_MOTION",
    "source_device_id": "ring-device-id",
    "rule_ref": "rapid-movement.raw-threshold.v1",
    "source_event_ids": ["uuid"]
  },
  "requested_modalities": [
    {
      "modality": "IMAGE",
      "mode": "SINGLE_FRAME"
    },
    {
      "modality": "AUDIO",
      "mode": "VAD_WINDOW",
      "max_duration_ms": 8000
    }
  ],
  "policy_snapshot_id": "uuid",
  "priority": "NORMAL",
  "idempotency_key": "opaque"
}
```

执行端必须返回每个请求模态的结果：

- `SUCCEEDED`
- `DENIED_BY_POLICY`
- `EXPIRED`
- `DEVICE_NOT_READY`
- `RESOURCE_BUSY`
- `CAPTURE_FAILED`
- `SUPPRESSED_BY_COOLDOWN`

一次意图失败不能伪造 Evidence，也不能被后端解释为“现实中没有发生该事件”。

## 8. 来源信封与短期证据

### 8.1 SourceEnvelope

来源信封描述一条输入从哪里来。除 PRD 已有字段外，需要补充多设备路由：

```json
{
  "schema_ref": "rme.source-envelope.v1",
  "source_envelope_id": "uuid",
  "owner_id": "uuid",
  "household_id": "uuid",
  "source_session_id": "uuid",
  "capture_intent_id": "uuid-or-null",
  "producer_device_id": "glass-device-id",
  "trigger_source_device_id": "ring-device-id",
  "relay_device_id": null,
  "transport_route": "GLASS_DIRECT_CLOUD",
  "occurred_at": "2026-07-24T10:00:00.456Z",
  "observed_at": "2026-07-24T10:00:00.600Z",
  "monotonic_offset_ms": 125430,
  "clock_domain": "GLASS_MONOTONIC",
  "clock_sync_method": "NTP_PLUS_MONOTONIC",
  "time_uncertainty_ms": 30,
  "policy_snapshot_id": "uuid",
  "modality": "IMAGE",
  "evidence_item_ids": ["uuid"],
  "idempotency_key": "opaque"
}
```

`transport_route` 首版允许：

- `GLASS_DIRECT_CLOUD`
- `MOBILE_RELAY`
- `LOCAL_DEFERRED`
- `PHASE0_CXRL_MOBILE`

传输路径只影响运维和审计，不应改变图片或音频的解析结果。

### 8.2 EvidenceItem

短期证据至少包含：

- 媒体或结构化传感器的类型。
- 内容类型、编码、采样率、通道、时长、尺寸和字节数。
- 加密方式、内容摘要和临时存储引用。
- 产生时间、上传时间和 TTL。
- 允许用途和隐私标签。
- 删除状态和删除回执。

图片扩展名不能代替真实内容类型。当前测试中出现过 `.jpg` 文件实际为 WebP，
正式实现必须基于文件头或编码器返回值填写 `content_type`。

### 8.3 SensorWindow

原始戒指 IMU 作为短期结构化证据，不应为每个样本创建一条
`AtomicObservation`。建议以窗口或批次保存：

- `sequence_start`
- `frame_count`
- `sample_rate_hz`
- `accel_range_g`
- `gyro_range_dps`
- 原始六轴整数值
- 戒指设备相对时间
- 接收设备绝对时间
- 丢序计数和时间不确定性

## 9. 多设备时间对齐

同一次触发可能跨越戒指、手机、眼镜和云端四套时钟。禁止只保留一个
`captured_at`。

时间规则：

1. 永远保留来源设备原始时间。
2. 同时记录接收设备时间和会话单调时间。
3. 用 `clock_domain` 标明时间属于哪个时钟。
4. 估算时间不能覆盖原值。
5. 跨设备对齐必须携带 `time_uncertainty_ms`。
6. 云端融合窗口应根据不确定性扩张，不能假设毫秒级精确同步。

戒指当前支持 `0x0401/0x0402` 校时。真机阶段应评估它是否足以建立稳定的戒指到
眼镜偏移模型。

## 10. 本地策略与隐私

采集前检查顺序：

```text
设备已绑定
  -> 签名策略存在且未过期
  -> CaptureSession 允许当前模态
  -> 用户未暂停或关闭
  -> 当前空间未禁采
  -> 设备处于佩戴状态
  -> 电量和温度满足预算
  -> 模态权限已授权
  -> 触发未过期且未被冷却抑制
  -> 启动媒体 API
```

无有效策略时默认拒绝采集。云端二次复核不能替代本地停止相机和麦克风。

设备直传云端时，眼镜需要：

- 独立设备证书或硬件绑定密钥。
- 仅允许 Ingest、策略刷新和删除回执的受限凭证。
- 签名且带过期时间的 `PolicySnapshot`。
- 本地加密 Evidence 队列。
- 用户删除和近窗遗忘的高优先级控制通道。

## 11. 离线、重试与删除

```text
采集成功
  -> 本地加密写入
  -> 写入 Envelope 和哈希
  -> 上传
     -> 成功：等待云端接收确认
     -> 失败：按退避策略重试
  -> 云端完成结构化或 TTL 到期
  -> 删除本地和云端 Evidence
  -> 记录最小删除回执
```

要求：

- 重试复用同一 `idempotency_key`。
- TTL 到期后不得继续上传。
- 暂停不一定删除既有合法证据，删除请求必须删除。
- 删除与上传竞态时，删除优先。
- Evidence 删除后保留的审计记录不得包含可恢复媒体。

## 12. RV101 真机闸门

### G1：系统能力

运行并记录：

```bash
adb shell pm list features
adb shell dumpsys bluetooth_manager
adb shell getprop ro.build.fingerprint
adb shell getprop ro.build.version.sdk
```

必须确认：

- `android.hardware.bluetooth_le`
- `BluetoothAdapter` 非空且可启用
- App 可以获得 Nearby Devices 权限
- 固件版本和构建号

### G2：正式 App 基础采集

- 验证佩戴、摘下和镜腿广播。
- 验证 CameraX 无业务预览图片与 2-3 秒短视频。
- 验证 8 通道 AudioRecord；不支持时记录单通道降级。
- 验证眼镜加速度计、陀螺仪、轴向和采样时间。

### G3：可选戒指扫描与连接

- 以 NUS Service UUID 过滤扫描。
- 连接已确认戒指并发现 TX/RX Characteristic。
- 读取系统信息确认设备型号和序列号。
- 启动/停止 IMU 并验证 `0x0605` CRC、序号和采样率。
- 断连后自动重连并重新开启通知。

### G4：后台稳定性

分别测试：

- App 前台、眼镜熄屏、佩戴、摘下、镜腿折叠。
- Runtime 进入后台。
- 进程被系统回收。
- 眼镜重启。
- 戒指离开和重新进入范围。

目标是 30 分钟连续监听无无解释断连。若系统只允许可见 Activity 或前台服务，
必须如实记录，不得把实验结果描述为后台常驻已解决。

### G5：多资源共存

同时运行：

- BLE 戒指通知。
- CameraX 单图和前后帧。
- AudioRecord + VAD。
- Wi-Fi HTTPS 上传。

记录丢包率、拍照延迟、音频断流、CPU、内存、温度和耗电。

### G6：眼镜直传

- 使用现有 `INTERNET` 和 `ACCESS_NETWORK_STATE` 权限实现上传客户端。
- 使用测试设备凭证向开发 Ingest API 上传元数据。
- 再上传小图片和短音频。
- 验证断网排队、恢复、幂等和 TTL。
- 禁止在验证阶段直接接生产用户数据。

### G7：手机兼容命令

如果 G2 或 G3 不通过，验证手机到眼镜 Runtime 的版本化命令通道：

- 连接发现。
- 采集意图签名和过期。
- 发送一次图片和短音频请求。
- 返回逐模态结果。
- 手机离线或 App 被杀时的明确降级。

### G8：Go / No-Go 判定

| 结果 | 采用路径 |
| --- | --- |
| G2、G4、G5、G6 全部通过 | P0 眼镜自主采集并直传云端 |
| P0 通过且可选戒指 G3 通过 | P0 + 戒指直连增强 |
| 戒指直连不通过，手机命令和眼镜直传通过 | P1 手机触发、眼镜直传 |
| 眼镜直传不通过，手机中继通过 | P1 手机兼容中继 |
| 自动采集功耗或生命周期不通过 | P2 显式触发和低资源模式 |
| 眼镜后台采集也不通过 | 设备路线阻塞，需要 Rokid 系统支持或更换硬件 |

## 13. 当前实现任务

1. 在持有 RV101 和开发线的电脑完成 G1、G2、G4、G5。
2. 修正真机返回的图片、视频、音频和 IMU 参数，不用桌面假设伪造能力。
3. 实现设备绑定、受限凭证和三步 Evidence 上行。
4. 实现 TTL、断网重试、删除回执和设备解绑。
5. 在主路径稳定后再决定是否实现眼镜直连戒指；戒指不阻塞 P0。
6. 依据真机数据决定下行轮询、长连接或系统推送，业务载荷另行 review。

## 14. 参考资料

- [Android BLE 概览](https://developer.android.com/develop/connectivity/bluetooth/ble/ble-overview)
- [Android 12 蓝牙权限](https://developer.android.com/develop/connectivity/bluetooth/bt-permissions)
- [连接 BLE GATT Server](https://developer.android.com/develop/connectivity/bluetooth/ble/connect-gatt-server)
- [BLE 后台通信](https://developer.android.com/develop/connectivity/bluetooth/ble/background)
- [Android 网络连接](https://developer.android.com/develop/connectivity/network-ops/connecting)
- [Rokid 眼镜端裸机开发 v1.0.0](https://custom.rokid.com/prod/rokid_web/ff28c865a9634876be98cbc293588460/pc/cn/index.html)
- `hardware/ring-sound-sdk/protocol.md`
- `apps/rokid-glass-probe/docs/ROKID-DEVELOPMENT-GUIDE.md`
- [设备与云端通信](05-Device-Cloud-Communication.md)
