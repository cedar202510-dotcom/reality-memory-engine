# Reality Memory Engine 分层技术架构

> 文档版本：v0.3
> 更新日期：2026-07-24  
> 产品母版：`docs/product/Reality-Memory-Engine-PRD-v1.3.md`  
> 当前状态：当前工程架构入口；未冻结内容会在正文中明确标为“待 review”

## 1. 这组文档解决什么问题

Reality Memory Engine 同时涉及眼镜、戒指、手机、云端记忆平台和 Agent。现有
PRD 已覆盖完整产品设想，但把设备路径、数据契约、云端沉淀和 Agent 调用写在同一
份长文档中，容易产生三个误解：

1. 把手机 App 的用户界面和手机中继能力视为同一个不可拆组件。
2. 把“眼镜本机运行采集 Runtime”误解为“所有证据仍必须经过手机”。
3. 把采集会话、现实活动、模型观察和长期记忆混成同一层数据。

本组文档把工程系统拆成四个强关联、可独立开发和验收的部分：

| 部分 | 中文含义 | 主要责任 | 详细文档 |
| --- | --- | --- | --- |
| 数据采集 | 真实世界信息如何进入系统 | 设备连接、触发、采集、短期证据、时间对齐、上传路由 | [01 数据采集架构](01-Data-Capture-Architecture.md) |
| 数据沉淀 | 短期证据如何成为可纠正的记忆 | 解析、跨模态融合、候选、事实事件、当前状态、删除 | [02 云端记忆平台架构](02-Memory-Platform-Architecture.md) |
| 数据调用 | Agent 如何安全使用记忆 | 账号授权、查询、订阅、纠正、遗忘、审计和 Demo | [03 Agent 调用架构](03-Agent-Access-Architecture.md) |
| 设备接入 | 新设备如何接入后端 | Connector 三段式、设备注册、认证、版本、健康、接入清单 | [04 设备接入 Connector 架构](04-Device-Connector-Architecture.md) |
| 端云通信 | 眼镜、手机和云端如何交换数据 | 设备身份、上行 Evidence、下行消息、中继和回执 | [05 设备与云端通信](05-Device-Cloud-Communication.md) |

这里的“网关”是一个逻辑角色，表示负责设备身份、策略、加密、重试和上传的边缘
组件。它可以运行在眼镜、手机或未来家庭 Hub 上，不应永久等同于某个手机页面。

## 2. 当前架构结论

### 2.1 长期目标

正式主路径是：

```text
眼镜佩戴事件 / 眼镜自身 IMU / 用户显式“记一下”
  -> RV101 原生 Runtime
  -> 本地确定性触发
  -> 眼镜采集单图、前后帧、短视频或短音频
  -> 眼镜在有可用网络时直接上传 Memory Platform
  -> 云端完成解析、融合和记忆沉淀
  -> Agent 查询或生成提醒
  -> 云端通用设备消息
  -> 眼镜文字或 TTS 呈现
```

复杂推理、实体归并、记忆事实和状态投影都在云端完成。眼镜只做低时延、确定性且
可审计的边缘工作，不在本机运行长期记忆推理。戒指仍可作为可选触发和主动语音
Adapter，但不再是眼镜采集成立的前提。

### 2.2 当前可执行路径

RV101 开发线已经到位，由持有开发线和真机的队友负责安装验证。当前主开发路径已
切换为眼镜原生 App：

```text
眼镜佩戴事件 / 眼镜自身 IMU / 用户显式“记一下”
  -> Reality Memory for Glasses
  -> CameraX / AudioRecord / SensorManager
  -> 本地加密 Evidence 队列
  -> 后续接入云端 Ingest API
```

原 CXR-L 手机协同路径继续作为兼容实验和历史测试数据来源，不再承担正式眼镜
Runtime。开发电脑负责生成 APK 和完整测试包；持有开发线和 RV101 的测试电脑
直接安装已构建 APK，只负责设备能力验证、日志与采样回传，不重复构建。

### 2.3 兼容路径

如果需要接入戒指且 RV101 无法稳定作为 BLE 中心设备连接戒指，采用：

```text
戒指
  -> 手机 App
  -> 手机生成 CaptureIntent（采集意图）
  -> BLE / 局域网命令发送给眼镜 Runtime
  -> 眼镜采集
  -> 优先由眼镜直传云端，必要时经手机中继
```

手机在这里是戒指接入和本地命令中继，不是云端 Memory Platform，也不是记忆
事实的保存位置。

### 2.4 无戒指路径

眼镜自身佩戴事件和 IMU 已经构成独立路径：

```text
眼镜佩戴事件
  -> 用户收到一次现实记录提示
  -> 眼镜 Runtime 进入后台协调状态
  -> 使用眼镜自身 IMU、低频定时、场景变化和本地 VAD 触发采集
  -> 眼镜直传云端或离线加密暂存
```

“Runtime 持续运行”不等于“连续录制”。即使进入该降级路径，仍只采集有界的
图片、前后帧、最长约 2-3 秒短视频和 VAD 命中的短音频，不录制长视频或连续
音视频流。

## 3. 系统边界

```text
┌────────────────────── 数据采集层 ──────────────────────┐
│ Ring Adapter │ Glass Runtime │ Mobile Relay │ Policy  │
│ Trigger      │ Capture       │ Evidence TTL │ Upload  │
└─────────────────────────┬──────────────────────────────┘
                          │ SourceEnvelope + EvidenceItem
┌──────────────────── 云端记忆平台 ───────────────────────┐
│ Ingest │ Evidence │ Extractors │ Temporal Fusion       │
│ Candidate │ Entity Resolution │ Event Store │ Projection│
│ Query │ Signal │ Privacy/Delete │ Audit                │
└─────────────────────────┬──────────────────────────────┘
                          │ Memory API + Signal Subscription
┌──────────────────── 数据调用与 Agent ───────────────────┐
│ Account Grant │ Query │ Timeline │ Signal │ Correction │
│ Proactive Agent │ Glass Agent │ Mobile Agent │ Partners │
└────────────────────────────────────────────────────────┘
```

### 3.1 数据采集层不负责

- 不把快速移动解释成“拿起钥匙”或“正在吃饭”。
- 不直接创建长期 `MemoryEvent`。
- 不保存长期媒体库。
- 不由设备端模型直接覆盖用户当前状态。

### 3.2 云端记忆平台不负责

- 不绕过设备本地策略远程强制启动相机或麦克风。
- 不把单次模型输出直接当成事实。
- 不让 Agent 直接修改事件表。
- 不依赖长期保存原始图片、视频和音频。

### 3.3 Agent 不负责

- 不直接读取默认受限的原始 Evidence。
- 不直接写 `MemoryEvent` 或 `StateProjection`。
- 不把推测伪装成确定事实。
- 当前阶段不自动购物、发送消息或执行其他外部动作。

## 4. 分层之间的接口

三支工作流可以并行，但必须共同冻结以下接口。

| 接口 | 生产方 | 消费方 | 作用 |
| --- | --- | --- | --- |
| `CaptureSession` | 采集层 | 采集层、云端审计 | 描述一次授权和设备运行窗口，不代表现实活动 |
| `CaptureIntent` | 戒指/手机/眼镜调度器 | 眼镜采集 Runtime | 描述为何请求哪些模态，不代表现实事实 |
| `SourceEnvelope` | 采集层 | 云端 Ingest | 描述来源设备、触发设备、时间、策略和传输路由 |
| `EvidenceItem` | 采集层 | Evidence Service、解析器 | 描述短期图片、短视频、音频或传感器窗口 |
| `AtomicObservation` | 模态解析器 | 时间融合 | 描述最小可追溯观察，例如“疑似杯子位于桌面” |
| `MemoryCandidate` | 时间融合 | Memory Core | 描述尚未确认的现实断言 |
| `MemoryEvent` | Memory Core | Projection、Query | 追加式事实变化，是唯一长期事实源 |
| `StateProjection` | Projection Engine | Query、Agent | 从事件流计算出的当前最佳状态 |
| `MemoryQuery` / `MemorySignal` | Memory API | Agent | 查询结果和可订阅状态变化 |
| `DeviceMessage` / `DeliveryReceipt` | 云端投递层 / 眼镜 | 眼镜 / 云端投递层 | 通用下行消息和设备投递结果，业务载荷待 review |

`CaptureSession` 到 `StateProjection` 已有
[`contracts/reality-memory/v1/`](../../contracts/reality-memory/v1/README.md)
机器 Schema。下行 `DeviceMessage` 和提醒业务载荷尚未进入正式 v1 Schema，只能
作为通信层建议，不得假装已经冻结。

## 5. 统一标识与时间规则

多设备协同最容易出错的是“同一件事无法对齐”。所有接口至少需要以下关联信息：

| 字段 | 含义 |
| --- | --- |
| `owner_id` / `household_id` | 数据归属和隔离边界 |
| `capture_session_id` | 设备和授权层的采集会话 |
| `capture_window_id` | 同一触发下的一组多模态采集 |
| `capture_intent_id` | 某次触发所产生的采集意图 |
| `source_envelope_id` | 一条来源输入的唯一编号 |
| `evidence_item_id` | 一份短期证据的唯一编号 |
| `producer_device_id` | 实际生成数据的设备 |
| `trigger_source_device_id` | 发出触发信号的设备，例如戒指 |
| `relay_device_id` | 实际中继数据的设备，可为空 |
| `occurred_at` | 事件在来源时钟中的发生时间 |
| `observed_at` | 当前设备观察或接收的时间 |
| `monotonic_start_ns` / `monotonic_end_ns` | 设备单调时间范围，避免系统时钟跳变 |
| `clock_domain` | 时间属于戒指、眼镜、手机还是云端 |
| `clock_sync_method` | NTP、协议校时、接收时间估算等 |
| `time_uncertainty_ms` | 跨设备时间对齐的不确定范围 |
| `policy_snapshot_id` | 采集时生效的策略版本 |
| `idempotency_key` | 断网重试时防止重复处理 |

`capture_session_id` 不能复用为 `activity_episode_id`。前者回答“设备什么时候被允许
采集”，后者回答“用户当时在做什么”，只能由后端融合产生。

## 6. 控制面与数据面

为避免手机 App 被误认为系统本体，架构需要区分两条链。

### 6.1 控制面

控制面负责账号、设备绑定、策略、暂停、删除和密钥：

```text
用户设置 / Agent 授权
  -> Cloud Control API
  -> 签名 PolicySnapshot
  -> 眼镜 / 手机 / 家庭 Hub
```

手机 App 是推荐的配置入口，但未来也可以由 Web、眼镜界面或企业管理端完成。

### 6.2 数据面

数据面负责证据和结构化事件：

```text
设备采集
  -> 设备本地加密缓冲
  -> 眼镜直传或手机中继
  -> Cloud Ingest
  -> 解析与记忆沉淀
```

两条链共享设备身份和策略版本，但不要求所有媒体字节必须经过手机。

### 6.3 下行消息面

下行消息负责把云端产生的提醒、策略或设备状态送到眼镜：

```text
MemorySignal / Policy Update
  -> 通用设备消息
  -> 眼镜文字或 TTS
  -> DeliveryReceipt
```

当前先冻结“需要通用消息信封和回执”这一边界。提醒业务字段、Agent 决策规则和
轮询、WebSocket、MQTT、系统推送的最终选择仍待 review，详见
[设备与云端通信](05-Device-Cloud-Communication.md)。

## 7. 当前代码与目标架构的距离

| 模块 | 当前已实现 | 仍缺少 |
| --- | --- | --- |
| iOS Reality App | CXR-L 图片、短音频/VAD、戒指 NUS、IMU、动作触发、采集 Session、本地测试清单 | 正式 SourceEnvelope、上传接口、自动戒指模式处理、后台可靠性 |
| Reality Memory for Glasses | 佩戴会话、眼镜 IMU 动态触发、无预览图片/短视频、短音频、加密 Evidence 队列、暂停/关闭/“记一下”、文字与 TTS 提醒入口 | RV101 真机验证、VAD、上传、TTL 实际清理与删除回执、签名策略、功耗校准、后端提醒通道 |
| RV101 Glass Probe | CameraX 无业务预览拍照、30 秒周期、佩戴广播、前台服务框架 | 仅继续承担官方能力对照和设备排障，不再扩展为正式产品 |
| PC Session Viewer | 图片、PCM、戒指数据和触发关联展示 | 正式契约展示、上传/解析状态、云端记忆结果 |
| Memory Platform | PRD 和工程设计 | 可运行 Ingest、Evidence、Parser、Fusion、Event Store、Projection、Query |
| Agent Access | 产品边界和少量旧 Schema | 正式授权、查询、订阅、纠正、删除和 Demo Agent |

因此当前系统已经从单项采集探针进入正式眼镜 App 开发，但还不是端到端 Memory
产品：本地采集与用户控制已有首版，云端解析、记忆沉淀和真实提醒投递尚待联调。

## 8. 当前待补齐项

当前产品 PRD 已完成手机、眼镜和云端职责收敛。剩余问题主要属于工程 review：

1. **RV101 真机能力。** CameraX、AudioRecord、IMU、佩戴广播、后台、网络、温升
   和功耗仍需开发线验证。
2. **设备身份和上行联调。** 需要实现绑定、设备凭证、签名策略、上传客户端、
   断网重试和删除回执。
3. **云端沉淀规则。** 解析模型、相似度筛选、时间融合、事实门控和实体归因尚未
   完成系统 review。
4. **下行业务契约。** 提醒内容、优先级、交互动作和 Agent 决策边界尚未冻结。
5. **下行传输。** 首版建议轮询，是否升级 WebSocket、MQTT 或系统推送取决于
   RV101 真机数据。

## 9. 开发顺序

```text
阶段 A：RV101 原生能力闸门
  -> 验证 CameraX / AudioRecord / 生命周期
  -> 验证眼镜 IMU / 佩戴广播 / 文字与 TTS
  -> 校准触发、功耗和温升

阶段 B：端云上行闭环
  -> 设备绑定和受限设备凭证
  -> Evidence 初始化、密文上传、完成确认
  -> 断网队列、TTL、删除回执和手机兼容中继

阶段 C：云端最小记忆闭环
  -> Ingest
  -> 图片/音频解析
  -> AtomicObservation
  -> MemoryCandidate
  -> MemoryEvent
  -> StateProjection

阶段 D：Agent Demo
  -> 账号授权
  -> 找物、偏好或活动查询
  -> 订阅一个状态变化
  -> 用通用设备消息投递一个提醒并回传回执
  -> 展示纠正和删除后结果重算
```

每个阶段都必须复用同一套版本化契约，不能让历史手机 PoC、正式眼镜 Runtime 和
云端解析团队各自发明一套数据结构。

## 10. 文档关系

- 产品定位、用户场景和产品边界以
  `docs/product/Reality-Memory-Engine-PRD-v1.3.md` 为母版。
- 当前部署和数据通道决策以本文件及四份分层文档为工程口径。
- `docs/engineering/Reality-Memory-Engine-Engineering-Architecture-v1.3.md`
  保留完整流水线解释。
- `docs/engineering/Reality-Memory-Multimodal-Data-Contract-v1.0.md`
  与 `contracts/reality-memory/v1/` 是当前正式数据契约和机器 Schema。
- `docs/engineering/archive/Reality-Memory-Engine-Contract-Review-v0.1.md`
  保留第一次数据契约 Review 结论，仅作历史参考。
