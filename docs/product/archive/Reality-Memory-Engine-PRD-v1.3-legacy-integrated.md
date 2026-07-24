# Reality Memory Engine 产品需求文档

> 文档版本：v1.3  
> 文档日期：2026-07-24  
> 产品名称：Reality Memory Engine / 现实记忆引擎  
> 当前首发硬件：Rokid Glasses（RV101）、语音智能戒指、统一手机网关  
> 文档用途：产品、Glass 客户端、手机端、后端、算法、数据与测试团队的统一开发依据

---

## 1. 产品摘要

Reality Memory Engine 是面向智能硬件与个人 Agent 的现实世界记忆中台。系统从眼镜、戒指、手机及未来设备接收图像、短视频、主动语音、传感器信号或结构化事件，将短暂的原始证据转化为可检索、可纠正、可删除、可审计的现实记忆。

产品解决的核心问题是：现实世界中的对象、空间、行为、偏好与任务持续发生变化，但当前个人 Agent 主要掌握线上信息，缺少对现实状态的连续理解。Reality Memory Engine 将这些变化组织成实体主线上的事件流，并计算每个实体在当前时刻的最佳状态，使 Agent 能回答“上次在哪里”“最近发生了什么”“什么快用完了”，并在关键状态变化时主动服务用户。

一句话定位：

> 面向智能硬件和个人 Agent 的现实世界记忆中台，让设备能够持续理解、沉淀并调用用户身边的状态变化。

首个可用产品以家庭为可信运行域，以“找物”为英雄场景，同时跑通耗材余量、口头偏好与任务、隐私暂停与遗忘。用户侧只有一个 Reality 手机 App：它承载用户账号、设备配对、授权策略、本地加密队列、上传和后续前端体验，并通过可插拔 Device Adapter 接入眼镜、戒指及未来硬件。当前 CXR-L Adapter 在该 App 内验证 Rokid 图片与音频链路；最终眼镜本机的原生 Runtime 完成低打扰采集后，仍通过统一手机网关进入用户账号与云端记忆平台。

---

## 2. 背景与产品机会

个人 AI 已经能读取聊天、文档、网页、日程和消费记录，但对用户现实生活中的连续状态缺少稳定数据：

- 一个物品被放到了哪里。
- 家庭耗材何时开封、如何消耗、何时接近用完。
- 用户对一次消费、食物或服务表达了怎样的偏好。
- 一本书读到了哪里，一项家庭活动进展到了什么程度。
- 哪些状态变化值得提醒，哪些只是短暂噪声。

现实世界数据具有连续、模糊、多模态和高隐私的特点。单次识别结果不足以形成可靠记忆，原始媒体长期保存又会显著增加信任风险。因此系统需要同时具备四种能力：

1. 低打扰地获得现实变化证据。
2. 将模型输出约束为候选观察，并通过多次观测、策略与用户纠正形成事实。
3. 用追加式事件保存历史，用可重算投影表达当前状态。
4. 让用户始终知道系统何时工作，并能暂停、纠正、删除和审计。

---

## 3. 产品目标

### 3.1 用户目标

- 用户可以快速询问常用物品上次出现的位置。
- 用户可以获得耗材接近用完的低打扰提醒。
- 用户的主动口头偏好、任务和纠正可以进入个人记忆。
- 用户无需在佩戴过程中反复确认采集，仍可随时暂停或结束。
- 用户可以查看系统沉淀的结构化记忆，并完成纠正、删除和近窗遗忘。

### 3.2 平台目标

- 建立与设备厂商无关的采集、策略、事件和查询契约。
- 建立 `SourceEnvelope → EvidenceItem → AtomicObservation → MemoryCandidate → MemoryEvent → StateProjection` 的事实链。
- 支持原子观察经过 `ObservationBundle → ActionSegment → ActivityEpisode` 完成跨时间、跨模态和跨设备聚合。
- 支持实体主线、候选分支、冲突、纠正和重算。
- 支持 Query、Timeline、Signal、Privacy、Audit 五类中台能力。
- 让新增硬件只需实现 Device Adapter，不改动记忆本体与核心服务。
- 让所有需要蓝牙、Wi-Fi 或本地网络中继的硬件统一接入一个手机 App，不按设备或模态拆分用户应用。

### 3.3 当前阶段目标

当前研发从 Rokid 真机采集能力验证开始，依次证明：

1. 先在统一手机 App 的 CXR-L Adapter 中取得真实眼镜图片和短音频，验证授权、连接、媒体质量、账号归属与统一来源契约。
2. 获得裸机调试条件后，将设备侧采集逻辑迁入 RV101 原生 Glass Runtime，并验证佩戴/摘下、后台生命周期、无业务预览采集和本地 VAD；证据仍经手机网关进入用户账号与云端。
3. 用户收到一次“5 秒后开启现实记录”的轻提示，可在倒计时内关闭；会话中随时可以暂停、摘下或全局关闭。
4. 会话激活后可按策略采集单图、前后帧、2–3 秒短视频和短音频片段；产品不录制长视频或连续视频。
5. PoC 媒体只在显式测试授权下短暂保存；正式链路完成结构化后立即删除 Evidence。
6. 使用统一观察契约验证图片、短视频、音频、IMU、设备状态和结构化事件能够进入同一记忆形成流程。

---

## 4. 产品原则

### 4.1 记忆变化，而非堆积媒体

系统的持久资产是结构化实体、事件、状态和关系。图像、短视频与音频承担短时证据角色，完成处理、交叉验证或超时后删除，用户最终查询的是现实记忆而非媒体回放。

### 4.2 模型产生候选，事件构成事实

视觉、语音或传感器解析器只能创建 `AtomicObservation`。观察经过跨时间/跨模态聚合后形成 `MemoryCandidate`，再经过策略、实体归因、置信度、冲突检测和交叉验证，才生成追加式 `MemoryEvent`。当前状态由事件流计算，任何纠正都通过新事件完成。

### 4.3 渐进形成现实模型

衣橱、梳妆台等高密度空间使用分层记忆。系统先保存空间摘要和主要对象，再通过购买、拆封、使用、穿着、移动等日常事件逐步建立对象主线。长期准确性来自多次真实交互，而非一次全量扫描。

### 4.4 信任是运行条件

每次佩戴只提示一次，5 秒后默认进入后台可工作状态；佩戴期间不再反复打断。禁采空间、敏感内容过滤、暂停、全局关闭、近窗遗忘和审计都属于核心运行链路。

### 4.5 一个手机入口，设备适配与中台解耦

用户侧只发布一个 Reality 手机 App。图片、短视频、音频和传感器是该 App 内的模态能力，不是独立应用；Rokid、戒指及未来设备通过各自 Device Adapter 接入同一个账号、策略、加密队列与上传管道。Rokid 原生 Glass Runtime 只承担眼镜本机采集，不承载用户账号或记忆本体。CXR-L 仅是统一 App 内的过渡 Adapter，不作为最终后台感知方案。

### 4.6 有界媒体而非连续录像

- 支持单图、前后帧和最长 2–3 秒的短视频片段。
- 不录制、不上传、不分析长视频或连续视频流。
- 音频只形成显式触发或本地 VAD 切分出的短片段，不将整段环境音作为长期证据。
- VAD 允许在有效授权会话内读取本地小缓冲，但静音数据不保存、不上传、不进入 ASR。

---

## 5. 用户、角色与权限

### 5.1 目标用户

| 用户 | 需求 | 当前入口 |
|---|---|---|
| 家庭主用户 Owner | 找物、耗材、偏好、任务、隐私控制 | 眼镜、戒指、手机 |
| 家庭成员 Member | 使用经 Owner 授权的家庭记忆 | 手机、Agent |
| 访客 Guest | 在访客存在时获得明确的采集保护 | 策略自动降级 |
| 内部测试人员 Tester | 验证设备、算法和隐私链路 | 测试版 Glass App、内部控制台 |
| Agent / 设备服务账号 | 查询记忆或订阅状态信号 | 内部 API |

### 5.2 权限角色

| 角色 | 读取 | 写入 | 删除 | 策略管理 | 调试证据 |
|---|---|---|---|---|---|
| Owner | 家庭域全部授权记忆 | 可确认、纠正 | 可删除与近窗遗忘 | 可管理 | 测试环境显式授权 |
| Member | 按实体、空间和类型授权 | 可提交候选与纠正 | 删除本人产生的主动记忆 | 无 | 无 |
| Guest | 无持久读取权限 | 无 | 无 | 无 | 无 |
| Device | 最小策略与会话信息 | 采集元数据、证据、结构化事件 | 本地清理回执 | 无 | 按测试策略 |
| Agent | 按 scope 查询与订阅 | 按 scope 创建建议或结构化事件 | 无 | 无 | 无 |

所有数据均绑定 `household_id`、`owner_id` 与策略快照。跨家庭查询在鉴权层直接拒绝。

### 5.3 首次启用与日常佩戴

首次启用完成一次完整授权：

1. Owner 登录或创建家庭域。
2. 绑定 Rokid Glasses 与戒指。
3. 说明系统沉淀结构化记忆、原始媒体仅短时处理的规则。
4. 获取相机、麦克风、通知、蓝牙和必要系统权限。
5. 设置家庭位置、家庭 Wi-Fi、禁采空间和全局开关。
6. 完成一次拍照、暂停和删除测试。
7. 进入“每次佩戴 5 秒后默认开启”的日常模式。

首次授权与佩戴提示承担不同职责：首次授权建立长期权限和隐私设置；每次佩戴提示告知本次会话即将开始，并允许用户在 5 秒内关闭。系统权限被撤销或隐私条款发生实质变化时，重新进入首次授权流程。

---

## 6. 核心场景

### 6.1 P0：找物

用户问题示例：

- “我的钥匙上次放在哪里？”
- “遥控器最后一次在客厅哪里出现？”
- “我昨天把充电器拿到卧室了吗？”

成功结果包含：

- 对象规范名和可识别别名。
- 最近高置信语义位置，例如“客厅茶几右侧”。
- 观察时间和状态新鲜度。
- 置信度等级与必要时的备选位置。
- 支持继续追问对象时间线。

基本流转：

```text
眼镜观察到对象
  → 视觉模型抽取对象、容器、相对位置
  → 与已有对象进行实体归并
  → 生成位置候选
  → 多帧或用户动作验证
  → 生成 MOVED / OBSERVED_AT 事件
  → 更新 location StateProjection
  → Query 返回当前最佳位置
```

### 6.2 P0：耗材余量

用户价值是提前知道纸巾、洗衣液等物品接近用完，并获得补货建议。

系统记录：

- 耗材对象和包装实例。
- 开封状态。
- 余量等级或估算比例。
- 余量变化趋势。
- 最近使用时间。
- 预测耗尽时间区间。

系统只有在连续观测显示下降趋势、置信度达到阈值并满足提醒冷却期时产生 `LOW_STOCK` 信号。提醒给出建议，不直接执行购买。

### 6.3 P0：口头偏好与任务

用户通过戒指主动录音、眼镜主动指令或手机入口表达：

- “这家外卖很好吃。”
- “下次不要点这家的面。”
- “记得提醒我明天拿快递。”
- “这个识别错了，它是书房的充电器。”

音频处理链：

```text
显式录音
  → ASR
  → Intent / Preference / Correction 抽取
  → 对象与时间归因
  → 候选
  → 明确表达自动确认，歧义表达等待追问
  → 生成 PREFERENCE_EXPRESSED / INTENT_CREATED / CORRECTION 事件
```

### 6.4 P0：隐私闭环

用户可以：

- 在佩戴倒计时内关闭本次会话。
- 在 ACTIVE 会话内立即暂停并手动恢复。
- 在手机端持续关闭自动现实记录。
- 将家庭位置、Wi-Fi 或手动空间标记为禁采域。
- 删除单条记忆、实体时间线的一段或最近 N 分钟。
- 查看何时由哪台设备、因何触发、沉淀了何种结构化记忆。

### 6.5 P1：阅读进度

系统低频观察用户正在阅读的书和可见页码，保存近似进度：

- `book_entity_id`
- `page_estimate`
- `chapter_hint`
- `observed_at`
- `confidence`

阅读场景使用低频图片即可；连续读书时默认从高频采集预算中降级。产品接受小范围页码误差，并通过后续观测更新。

### 6.6 P1：场景回忆

用户按对象、空间或时间询问：

- “上周阳台晾过哪件衣服？”
- “这个花瓶什么时候从餐桌移到玄关？”
- “最近谁用过工具箱？”

回答由事件流生成，返回结构化事件摘要和置信度，不提供已删除的原始媒体回看。

### 6.7 P2：衣橱与梳妆台渐进记忆

系统通过购买、拆封、使用、穿着、晾晒、收纳和移动事件逐步发现物品：

```text
PlaceSnapshot（空间摘要）
  → ObjectCandidate（局部对象候选）
  → Entity（稳定对象）
  → MemoryEvent（使用、穿着、移动、消耗）
  → StateProjection（当前存在、位置、可用性）
```

同一区域只保留可解释的空间摘要、主要对象和变化。小物品在被用户单独拿起、使用、命名或多次稳定出现时升级为独立实体。

---

## 7. 产品总体架构

```text
┌──────────────────────────── 硬件与设备运行时 ────────────────────────┐
│ Rokid Native Runtime │ Ring │ Future Glasses / Sensors             │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ BLE / Wi-Fi / Local Transport
┌────────────────────────── 统一 Reality 手机 App ─────────────────────┐
│ Device Adapters │ Account/Pairing │ Session FSM │ Local Policy      │
│ Capture/VAD │ Encrypted Queue │ Upload/Relay │ Audit │ Secure Erase │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ SourceEnvelope / Ingest API
┌──────────────────────────── Memory Platform ─────────────────────────┐
│ Device Registry │ Evidence │ Modality Extractors │ Temporal Fusion │
│ Candidate Store │ Entity Resolver │ Event Store │ Projection Engine│
│ Query/Search │ Signal Bus │ Privacy/Delete │ Audit                 │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ Memory API
┌──────────────────────────── 消费与行动层 ────────────────────────────┐
│ Glass Agent │ Mobile Agent │ Home Agent │ Future Robots / Partners │
└──────────────────────────────────────────────────────────────────────┘
```

### 7.1 架构边界

**统一手机 App / Edge Gateway** 负责用户侧通用逻辑：

- 用户账号、设备注册、配对和证据归属。
- 来源会话与佩戴会话状态机的统一编排。
- 本地策略快照与调用相机、麦克风或传感器前的 PolicyCheck。
- CXR-L 等手机侧图片/短视频采集调度、音频 VAD、预算与节流。
- 证据加密、过期与安全删除。
- 接收眼镜 Runtime、戒指及未来硬件的本地传输，统一映射为 `SourceEnvelope`。
- 维护单一加密上传队列、网络重试、幂等和审计。

**Device Adapter** 负责厂商差异：

- 相机、麦克风、录像与传感器 API。
- 佩戴、摘下、折叠、按键与系统事件。
- 电量、温度、网络和后台限制。
- 厂商授权、配对与应用分发。

**设备侧 Runtime** 只在硬件必须本机运行时存在：

- 调用硬件本机相机、麦克风和传感器。
- 执行低时延采集、本地 VAD、短时加密缓冲和安全删除。
- 通过版本化 Local Transport Contract 将 Evidence 与设备事件交给统一手机 App。
- 不建立第二套用户账号、上传队列、记忆模型或用户前端。

**Memory Platform** 负责设备无关的记忆能力：

- 策略、证据和按模态选择解析器。
- 原子观察、跨模态/跨时间聚合、记忆候选和实体解析。
- ActivityEpisode、事件主线和当前状态投影。
- 当前状态投影。
- 查询、信号、删除和审计。

### 7.2 唯一事实源与首版部署

`MemoryEvent` 是现实记忆的唯一持久事实源。其他形态均为可删除、可重算或可替换的派生数据：

- `StateProjection` 由有效事件流确定性重算，不独立创造事实。
- 全文索引、向量索引、缓存和 Signal 均可由事件与投影重建。
- 向量仅用于召回结构化摘要或实体候选，不作为事实，也不能绕过权限直接回答。
- 原始 `Evidence` 是短时处理材料，不是长期事实源。
- `AtomicObservation` 是解析器产生的不可变观察，不等同于事实。
- `MemoryCandidate` 是经过聚合后仍待决的现实断言，不等同于已确认记忆。
- 删除和纠正通过追加控制事件、失效标记与投影重算完成，并保留最小不可逆审计 tombstone。

首版后端采用模块化单体：API、异步 Worker 和 PostgreSQL 可以共同部署，但模块的数据所有权、契约和幂等边界必须保持。`MemoryEvent` 追加与 `outbox_events` 写入在同一数据库事务中完成；投影、索引和 Signal 通过 Outbox 异步消费，保证失败后可以重放且不产生重复事实。

### 7.3 推荐代码仓结构

```text
apps/
  reality-mobile/          # 唯一用户 App：账号、设备、采集、队列、上传与前端
  rokid-runtime/           # 眼镜本机采集 Runtime，不是独立用户产品
  internal-console/        # 仅研发和运营使用
services/
  gateway/
  policy/
  evidence/
  perception/
  memory-core/
  query/
  signal/
  privacy/
packages/
  source-contract/         # SourceEnvelope、EvidenceItem、能力描述
  perception-contract/     # AtomicObservation、Bundle、Segment、Episode
  memory-contract/         # Entity、MemoryCandidate、Event、Projection
  api-client-kotlin/
  api-client-python/
adapters/
  mobile-camera/
  rokid-native/
  rokid-cxr-l/
  ring-ble/
transports/
  ble/
  local-wifi/
  https-upload/
infra/
  migrations/
  observability/
tests/
  contract/
  integration/
  device/
```

首版允许单体后端按上述模块分包部署；接口和数据所有权保持边界，方便后续独立扩展。

### 7.4 首版技术基线

仓库当前为绿地项目，建议使用以下基线，使设备、AI 与服务端可以快速联调：

| 层 | 技术基线 | 说明 |
|---|---|---|
| Reality 手机 App | 首版 iOS；后续 Android，共享 Source Contract 与业务规则 | 唯一用户入口、账号、配对、策略、加密队列、上传、管理和提醒 |
| Rokid Glass Runtime | Kotlin、Android API 31、CameraX、AudioRecord、SensorManager、Room | 眼镜本机低打扰采集，通过本地传输交给手机网关 |
| 本地调度 | Foreground Service、协程、Room 顺序日志 | 眼镜 Runtime 和手机网关分别维护有界任务与可重放队列 |
| CXR-L Adapter | 当前集成于统一 iOS App，必要时实现 Android Adapter | 开发线到位前验证眼镜图片与音频，不形成第二个 App |
| 后端 API | Python 3.12、FastAPI、Pydantic、SQLAlchemy、Alembic | 便于 AI 与戒指 SDK 协同 |
| 结构化存储 | PostgreSQL 16 | Entity、Event、Projection、Policy、Audit |
| 向量检索 | pgvector | 首版与 PostgreSQL 共库 |
| 临时证据 | S3 兼容对象存储 + KMS | 生命周期规则和独立 DEK |
| 缓存与节流 | Redis | 幂等、冷却、短期会话状态 |
| 异步处理 | PostgreSQL Outbox + Worker | 首版避免引入独立消息集群 |
| 可观测性 | OpenTelemetry、结构化日志、Prometheus 指标 | 串联 device/session/evidence/event |
| 本地开发 | Docker Compose | Postgres、Redis、对象存储、后端 |

事件量和外部订阅规模增长后，可将 Outbox 消费层替换为 Kafka 或 NATS；Event、Projection 和 API 契约保持不变。

---

## 8. Rokid 产品接入方案

### 8.1 目标设备与实现决策

当前目标真机固定为 **Rokid Glasses，硬件型号 RV101**。当前版本的设备实现以 RV101 的消费级开发体系为准：

- 采集主路径：在 RV101 眼镜本机运行 YodaOS-Sprite 裸机 Android Runtime。
- 传输主路径：Runtime 通过 BLE/Wi-Fi 本地通道将 Evidence 与事件交给统一手机 App，再归入用户账号并上传云端。
- 设备能力：使用 CameraX、AudioRecord、SensorManager、佩戴/摘下广播与系统按键。
- 过渡验证：CXR-L 仅用于开发线到位前取得真实图片/短音频并验证统一契约。
- 最终采集：必须使用运行在 RV101 眼镜本机的原生 Android App；CXR-L 不作为后台无感采集的产品兜底。
- AIUI：不作为 Glass App、Memory Platform 或 Agent API 的注册与运行依赖。
- 平台边界：RV101 相关代码只存在于 `rokid-native` 和 `rokid-cxr-l` Adapter；Edge Contract 与 Memory Core 不感知具体型号。

RV101 的最终固件版本、系统构建号、Rokid AI App 版本和 SDK 版本必须写入每次真机实验记录与 `DeviceCapabilityProfile`，不能只以产品名称判断能力。

### 8.2 官方能力基线

Rokid 当前为 Rokid Glasses 提供以下相关开发路径：

| 路径 | 运行位置 | 能力 | 在本项目中的角色 |
|---|---|---|---|
| 眼镜端裸机开发 | RV101 眼镜本机 | Android 12 / API 31、CameraX、AudioRecord、SensorManager、佩戴/摘下广播、按键 | 最终设备侧采集 Runtime |
| CXR-L SDK 1.0.4 | 统一 Android/iOS 手机 App | 经 Rokid AI App 完成授权与连接，调用拍照、音频、自定义 View/App | 当前统一手机 App 内的过渡 Adapter |
| CXR-M SDK | Android 手机 | 实时音视频、Wi-Fi P2P、自定义场景 | 获得对应商务能力后再评估 |

眼镜端裸机开发文档明确提供：

- YodaOS-Sprite，基于 Android 12（API 31）/ Android Go。
- CameraX `ImageCapture` 拍照和 `VideoCapture` 录像。
- 8 通道 16 kHz PCM `AudioRecord`。
- `SensorManager` 六轴 IMU。
- 佩戴事件 `com.rokid.sprite.ACTION_TAKE_STATUS_CHANGED`，`glasses_take_state` 为 `"1"` 表示佩戴、`"0"` 表示摘下。
- 镜腿折叠事件 `com.rokid.sprite.ACTION_LEG_STATUS_CHANGED`。
- 480×640 显示区域，以及专用开发线、Rokid AI App 开启 ADB 的真机联调方式。

### 8.3 AIUI 与本项目的关系

当前 Glass App、CXR-L、Memory Platform 和 Agent API 的开发链不依赖 AIUI 注册。AIUI Studio 用于在 Rokid 体系内创作和发布 AIUI Agent；本项目当前需要的是设备开发者账号、眼镜调试权限、Android 工程和对应 SDK/授权。

接入选择如下：

- 现实采集服务使用眼镜端裸机 Android App。
- 开发线到位前，统一手机 App 的 CXR-L Adapter 可经 Rokid AI App 获取拍照/音频用于解析链路测试。
- 最终产品不依赖 CXR-L CustomView 或其拍照回显；原生 Glass App 直接调用 CameraX/AudioRecord。
- Rokid 内部 AIUI Agent 可在后续作为 Memory API 的一个消费端。
- CXR-L 需要 Rokid AI App 或 Hi Rokid、授权 token 和会话构建；这不等同于注册 AIUI Agent。

### 8.4 Rokid Glass App 模块

| 模块 | 职责 |
|---|---|
| `WearStateReceiver` | 接收佩戴、摘下、镜腿展开/折叠广播 |
| `SessionCoordinator` | 驱动佩戴会话状态机与 5 秒倒计时 |
| `CaptureService` | 在允许的生命周期中维护相机和调度器 |
| `RokidCameraAdapter` | CameraX 绑定、单图采集、短视频采集 |
| `RokidAudioAdapter` | AudioRecord、本地 VAD、短片段切分与显式语音采集 |
| `RokidSensorAdapter` | IMU、按键与触控事件 |
| `LocalPolicyEngine` | 在调用媒体 API 前完成本地策略判断 |
| `CaptureScheduler` | 固定间隔、动态触发、预算与冷却 |
| `EncryptedEvidenceBuffer` | 媒体加密暂存、TTL 与安全删除 |
| `TransportAdapter` | 通过 BLE/Wi-Fi 本地通道向统一手机 App 发送 Evidence 与事件 |
| `AuditReporter` | 会话、策略命中、采集尝试和删除回执 |
| `StatusUI` | 倒计时、暂停、错误和低干扰运行状态 |

### 8.5 Android 运行约束

Rokid Glasses 基于 Android 12。Android 12 对从后台启动前台服务，以及后台服务使用相机和麦克风有系统限制。产品期望状态机保持不变，具体运行方式按真机验证结果选择：

1. 佩戴广播拉起轻量可见界面，展示 5 秒倒计时，并在界面可见期间启动带 `camera` 类型的前台服务。
2. 若厂商系统为佩戴广播或系统应用提供专用豁免，使用厂商支持路径。
3. 若第三方应用无法在预期生命周期持续调用相机或麦克风，记录为最终产品阻塞项并寻求 Rokid 支持、系统白名单或受支持的生命周期入口；不得把存在系统回显的 CXR-L 拍照路径当作最终后台感知兜底。

真机 PoC 必须记录前台、熄屏、摘下、折叠、进程被杀、断网、锁屏和重启后的实际行为。

### 8.6 RV101 数据通道

所有终端与平台之间使用统一 `SourceEnvelope`。它至少包含 `source_id`、`device_id`、`source_session_id`、`occurred_at`、`observed_at`、`monotonic_offset_ms`、`policy_snapshot_id`、`trigger`、`modality`、`schema_ref`、`idempotency_key` 和零到多个 `EvidenceItem` 引用。厂商原始事件名保留在扩展字段中，但不能成为记忆核心契约。

当前按以下顺序实现和验证：

1. **统一手机网关**：所有硬件先绑定用户手机 App；App 负责账号归属、策略校验、加密队列、重试和云端上传。
2. **CXR-L 过渡 Adapter**：开发线到位前，统一手机 App 直接通过 CXR-L 获取受控图片或音频，并封装为相同 `SourceEnvelope`。
3. **Rokid 原生 Runtime**：开发线到位后，眼镜在本机完成无业务预览采集，再通过版本化 BLE/Wi-Fi Local Transport Contract 发送给同一手机 App。
4. **离线暂存**：手机不可达时，设备 Runtime 只在有效策略与 TTL 内保存加密证据；手机离线时由 App 本地加密排队。过期、暂停、摘下或删除请求到达后优先清理。

首版不允许每种硬件建立独立手机 App、独立账号体系或独立上传链路。云端只接受统一手机 App 代表已绑定设备提交的数据；设备直连云端仅保留为未来受控降级或企业部署能力，不是首版默认路径。当前实现不得依赖其他 Rokid 产品线未公开的 P2P 或文件 API。

### 8.7 Glass UI

眼镜显示采用 480×640 单绿线框规范，信息保持短促：

- 佩戴提示：“5 秒后开启现实记录”
- 次要操作：“单击关闭”
- 活跃状态：完成授权提示后默认不显示业务画面、相机预览或持续文字；仅保留系统强制的隐私指示。
- 暂停状态：“现实记录已暂停”
- 策略阻断：“当前空间已禁采”
- 错误状态：“相机不可用，记录已停止”

提示仅在佩戴会话开始时出现一次。运行期间只在用户操作、策略变化或错误需要处理时反馈。

---

## 9. 戒指接入方案

### 9.1 当前 SDK 能力

项目内语音戒指 SDK 基线：

- Python SDK `0.3.4`，语音戒指 v4 协议。
- BLE 使用 Nordic UART Service。
- 录音为 16 kHz、16 bit、单声道，Speex Wideband Q3。
- 支持录音列表、快速下载、录音完成后的主动分帧上报。
- 支持六轴 IMU 批量上报。
- 支持普通双击、HMM 手势、按键双击和按键单击事件。
- 设备启动后默认处于录音模式；单击尝试在录音模式和手势模式之间切换。
- 实时 IMU 需要设备处于手势模式；录音模式与手势/实时 IMU 运行存在状态约束。

### 9.2 首版产品角色

戒指承担低摩擦显式交互：

| 用户操作 | 默认语义 | 系统行为 |
|---|---|---|
| 按键双击 | 立即记一下 | 触发眼镜单图并创建 `explicit_capture` |
| 普通双击/预设手势 | 暂停或恢复 | 切换本次佩戴会话状态 |
| 录音模式长按 | 说一条记忆 | 采集主动短语音并抽取偏好、任务或纠正 |
| 手机端确认映射 | 忘记最近内容 | 调用近窗遗忘，并要求二次确认 |

映射保留配置能力，真机测试后选择误触率最低的手势。

### 9.3 戒指桥接服务

当前 SDK 为 Python 参考实现。产品接入需要一个长期运行的 Ring Bridge：

```text
戒指 BLE
  → Ring Adapter
  → 标准 DeviceEvent
  → Edge Core / Backend
```

标准事件示例：

```json
{
  "event_id": "evt_ring_01",
  "device_id": "ring_01",
  "event_type": "KEY_DOUBLE_PRESS",
  "occurred_at": "2026-07-23T08:30:00Z",
  "session_id": "wear_01",
  "payload": {
    "mapped_action": "EXPLICIT_CAPTURE"
  }
}
```

首版 Ring Bridge 可运行在手机或开发机。后续移动端实现 BLE 协议后，手机成为稳定中继。

### 9.4 运动信号使用

当前戒指 IMU 适合短时动作验证、手势和实验数据采集。持续采集调度优先使用 Rokid 本机 IMU、相机变化和用户显式事件；戒指连续 IMU 门控在设备模式、功耗与误判率通过验证后加入。

---

## 10. 佩戴会话与采集状态机

### 10.1 会话状态

```text
ENDED
  → WEAR_DETECTED
  → COUNTDOWN_5S
      ├─ 用户关闭 → DISABLED_FOR_THIS_WEAR
      ├─ 权限或策略阻断 → BLOCKED
      └─ 倒计时结束 → ACTIVE

ACTIVE
  ├─ 采集触发 → POLICY_CHECK → CAPTURING → ACTIVE
  ├─ 用户暂停 → PAUSED
  ├─ 禁采策略生效 → BLOCKED
  ├─ 严重错误 → ERROR
  └─ 摘下/折叠/会话失效 → ENDING → ENDED

PAUSED
  ├─ 用户恢复 → POLICY_CHECK → ACTIVE
  └─ 摘下 → ENDING → ENDED

BLOCKED
  ├─ 策略恢复且用户仍佩戴 → ACTIVE
  └─ 摘下 → ENDING → ENDED
```

### 10.2 状态语义

| 状态 | 相机/音频 | 调度 | 允许事件 |
|---|---|---|---|
| `COUNTDOWN_5S` | 关闭 | 关闭 | 关闭、全局关闭 |
| `ACTIVE` | 按策略开放 | 运行 | 暂停、显式采集、主动语音 |
| `PAUSED` | 关闭 | 关闭 | 恢复、删除、结束 |
| `BLOCKED` | 关闭 | 关闭 | 策略刷新、删除、结束 |
| `DISABLED_FOR_THIS_WEAR` | 关闭 | 关闭 | 删除、结束 |
| `ENDING/ENDED` | 关闭 | 关闭 | 清理与审计 |

### 10.3 会话规则

- 每次从摘下到佩戴创建一个新的 `session_id`。
- 佩戴后仅提示一次，倒计时默认 5 秒。
- 倒计时内的“关闭”只作用于本次佩戴。
- “暂停”可在本次会话内恢复。
- “全局关闭”持久保存，需要用户主动重新开启。
- 摘下事件立即停止调度、解除 CameraX、停止 AudioRecord、清理待处理媒体并结束会话。
- 断连或佩戴事件不可靠时，安全超时自动结束会话。
- 所有状态变更写入本地不可篡改顺序日志，并异步上报审计服务。

---

## 11. 采集策略

### 11.1 采集输入

| 模态 | 来源 | 适用信息 | 默认使用方式 |
|---|---|---|---|
| 单图 | 眼镜 | 对象、位置、余量、页码、场景摘要 | 主要视觉输入 |
| 前后帧 | 眼镜 | 拿起、放下、开合、前后状态 | 快速动作的低成本表达 |
| 2–3 秒短视频 | 眼镜/未来视觉设备 | 连续动作、倒出、快速移动 | 仅在静态帧歧义且策略允许时使用；不支持长视频 |
| 短音频片段 | 戒指/眼镜/手机 | 偏好、任务、命名、纠错、环境声音事件 | 显式触发或本地 VAD 切分 |
| IMU | 眼镜/戒指 | 运动强度、姿态变化、手势 | 调度与动作辅助 |
| 设备状态 | 所有设备 | 电量、网络、温度、佩戴状态 | 预算和安全控制 |
| 结构化事件 | 手机/智能家居 | 门锁、日历、传感器、确认 | 直接进入候选链 |

首版明确不接收长视频或连续视频流。图片、短视频、音频和传感器分别使用可替换的模态解析器，但都输出同一 `AtomicObservation` 契约。设备型号只影响 Adapter、校准和能力描述，不改变观察、记忆和查询契约。

### 11.2 触发来源

1. **显式触发**：戒指双击、按键、语音“记一下”。
2. **固定间隔**：PoC 和初期家庭测试使用。
3. **运动触发**：头部运动、场景变化、短时 IMU 峰值。
4. **语义触发**：对象新出现、被拿起、容器打开、余量变化或本地 VAD 检测到连续人声。
5. **时间触发**：阅读等持续场景的低频进度记录。
6. **外部触发**：家庭设备事件或 Agent 请求一次现场确认。

### 11.3 采集前策略检查

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

返回值：

```json
{
  "decision": "ALLOW",
  "policy_version": "pol_42",
  "retention": {
    "local_ttl_seconds": 600,
    "cloud_ttl_seconds": 900
  },
  "redaction_profile": "home_default",
  "max_bytes": 3145728
}
```

`DENY` 时设备不得启动媒体 API。没有有效策略、策略签名失效或策略版本回退时按 `DENY` 处理。

### 11.4 动态采集优先级

完整产品使用可解释评分：

```text
capture_priority =
  explicit_intent
  + motion_change
  + scene_novelty
  + memory_value
  + uncertainty_reduction
  - privacy_risk
  - battery_cost
  - thermal_cost
  - daily_budget_pressure
```

推荐归一化为 0–100：

- `>= 70`：立即采集。
- `40–69`：进入冷却队列，等待下一证据或低成本单图。
- `< 40`：跳过并记录原因。

显式触发始终提高优先级，但仍受禁采与权限策略约束。

### 11.5 频率策略

PoC 测试档位：5、15、30、60 秒。

产品化后的初始建议：

| 场景 | 建议频率 | 模态 |
|---|---|---|
| 高运动、拿放物品 | 2–5 秒内前后帧或短视频 | 图片/短视频 |
| 普通家庭走动 | 15–30 秒 | 单图 |
| 坐姿、电视、休息 | 2–5 分钟或暂停 | 单图 |
| 阅读 | 3–5 分钟 | 单图 |
| 禁采域、低电量、过热 | 0 | 无 |

实际默认值由 Rokid 续航、温升、后台存活和记忆收益实验决定，并通过服务端策略下发。

### 11.6 采集预算

策略按用户、设备、会话和模态设置：

- 每分钟最大采集次数。
- 每日媒体字节数。
- 每日模型处理成本。
- 单会话短视频总时长和短音频总时长。
- 电量低于阈值时的降级策略。
- 温度超过阈值时的立即停止策略。

预算命中后优先保留显式触发和高价值变化，降低背景频率。

### 11.7 音频触发与切分

音频采集分为两种模式：

1. **显式语音**：戒指按键、眼镜按键或用户明确指令触发，优先级最高。
2. **会话内 VAD**：用户已授权现实记录且音频策略允许时，设备本地读取小缓冲并检测语音活动；只有命中语音段的短片段进入 Evidence。

约束如下：

- 音量阈值只用于 PoC 校准，产品判断使用 VAD，并结合最短人声时长、静音结束窗口和冷却期。
- 推荐预滚缓冲不超过 500 ms，连续静音约 800–1200 ms 后结束，单段最长 15 秒；最终参数由真机数据决定。
- 静音缓冲不落盘、不上传、不进入 ASR；命中片段完成结构化后立即删除。
- CXR-L 没有独立 VAD 事件。过渡探针必须先开启眼镜音频流，再在手机本地做 VAD 和短片段切分，因此只用于受控测试。
- 最终原生 Glass App 在眼镜本机执行 AudioRecord + VAD，只上传命中的短片段或结构化结果。
- 摘下、暂停、策略收紧、权限撤销、超时或进程结束时立即停止音频流并清空未成段缓冲。

---

## 12. 证据生命周期与 AI 处理

### 12.1 证据状态

```text
CAPTURED_LOCAL
  → ENCRYPTED_LOCAL
  → QUEUED
  → UPLOADED_ENCRYPTED
  → PROCESSING
  → STRUCTURED
  → DELETING
  → DELETED

任一阶段
  → EXPIRED / REJECTED / FAILED
  → DELETING
  → DELETED
```

### 12.2 默认留存

| 环境 | 媒体 | 默认策略 |
|---|---|---|
| Rokid 采集 PoC | 图片/短音频 | 显式测试授权下短暂保存，完成验证后删除 |
| 正式处理链 | 图片 | 本地最长 10 分钟；云端最长 15 分钟；完成结构化即删 |
| 正式处理链 | 短视频/短音频 | 本地与云端最长 15 分钟；完成结构化即删 |
| 测试调试 | 显式授权样本 | 本地加密，最长 24 小时，单独测试角色可见 |

TTL 是上限，删除事件优先于 TTL。媒体对象使用独立 DEK；删除 DEK、对象和派生缓存后写删除回执。

### 12.3 感知与记忆形成流水线

```text
SourceEnvelope
  → EvidenceItem / Structured Source Event
  → 安全扫描与敏感内容检测
  → 模态预处理
  → Image / ShortVideo / Audio / Sensor / StructuredEvent Extractor
  → AtomicObservation
  → ObservationBundle
  → ActionSegment / ActivityEpisode
  → MemoryCandidate
  → Entity Resolution
  → Policy & Confidence Gate
  → Conflict Resolver
  → MemoryEvent
  → Projection Engine
  → Search Index / Signal Evaluation
  → Evidence Deletion
```

解析器按模态复用，不按硬件复制。例如 Rokid、手机和机器人产生的图片都进入 Image Extractor；设备差异通过 `DeviceCapabilityProfile`、校准参数和 `SourceEnvelope` 上下文传入。

### 12.4 解析器输出要求

每个 `AtomicObservation` 必须包含：

- 观察类型与受约束的谓词。
- 主体、对象或数值结果。
- 现象发生时间范围、观察时间和接收时间。
- 可用时的空间、区域、轨迹或说话人上下文。
- 一个或多个证据引用。
- 解析器、模型和版本。
- 置信度及校准版本。
- 可解释特征。
- 敏感性标签。
- 允许用途与留存策略。

自然语言描述和 ASR 文本可以作为受控字段，但不能替代结构化谓词、实体、时间、置信度和来源。模型不得直接创建 `MemoryEvent` 或更新 `StateProjection`。

### 12.5 时序与跨模态聚合

- `ObservationBundle` 只关联同一时间窗或同一现实变化的多个原子观察，不复制原始媒体。
- `ActionSegment` 表达一个局部动作，例如拿起、切菜、放下或等待。
- `ActivityEpisode` 表达语义目标相对稳定的一段活动，例如做饭；它可以包含多个 Segment。
- `source_session_id` 表达佩戴、连接或采集会话；`activity_episode_id` 表达现实活动，两者不得混用。
- Episode 边界综合时间间隔、地点变化、对象集合变化、动作预测误差、目标变化和显式用户信号，并使用迟滞避免频繁切段。

---

## 13. 记忆本体

### 13.1 一条现实记忆的定义

一条现实记忆是在一个时间点或时间窗内，系统基于设备观测或用户明确输入，对某个现实实体、语义实体、状态变化或关系形成的结构化断言。它至少包含：

- 所属家庭域与主体实体。
- 发生了什么，或哪个状态维度发生了怎样的变化。
- 事件发生时间、实际观测时间和系统接收时间。
- 来源设备、来源候选和当时生效的策略快照。
- 身份、空间、时间和聚合置信度。
- 当前有效性、冲突关系、纠正或删除关系。

例如“钥匙现在在茶几上”不是一张图片，也不是一次模型输出，而是由“RV101 在 08:30 观察到疑似钥匙位于茶几右侧，经身份归并和多次观测接受为 `MOVED` 事件，当前尚无更新的互斥事件”推导出的状态。

### 13.2 核心对象

| 对象 | 定义 |
|---|---|
| `Household` | 数据隔离、授权和策略执行的最高可信域 |
| `Actor` | 产生操作的用户、设备、服务或 Agent 的统一身份 |
| `Person` | Owner、家庭成员或临时参与者 |
| `Object` | 可被识别、定位、使用或改变状态的现实物品 |
| `Place` | 家庭、房间、区域、家具、容器、层与相对位置 |
| `Activity` | 阅读、穿衣、晾晒、做饭等持续过程 |
| `Intent` | 用户希望记住、完成、查找、纠正或删除的事情 |
| `Preference` | 用户对对象、服务、食物或体验表达的倾向 |
| `SourceEnvelope` | 设备或用户入口产生、尚未经过模型解释的统一来源上下文 |
| `EvidenceItem` | 与来源关联的短暂图片、短视频、短音频或传感器窗口 |
| `AtomicObservation` | 模态解析器产生的不可变、可追溯原子观察 |
| `ObservationBundle` | 同一时间窗或现实变化下的多观察关联 |
| `ActionSegment` | 拿起、切菜、放下、等待等局部动作片段 |
| `ActivityEpisode` | 目标相对稳定并可包含多个 Segment 的现实活动 |
| `MemoryCandidate` | 由观察和活动聚合形成、尚未成为事实的现实断言 |
| `MemoryEvent` | 追加式、可追溯的事实变化 |
| `StateProjection` | 从事件流计算的当前最佳状态 |
| `SignalCandidate` | 由投影变化或规则产生、尚未决定是否提醒的信号 |
| `ReminderDecision` | 对是否提醒、何时提醒、通过何种终端和如何措辞的受控决策 |
| `ReminderDelivery` | 提醒的投递、查看、忽略和追问结果 |
| `PolicySnapshot` | 采集、处理、留存和调用权限快照 |
| `DeletionTombstone` | 不包含被删内容、仅证明删除范围和完成状态的最小审计记录 |

### 13.3 实体类型

```text
HOUSEHOLD
ACTOR
PERSON
OBJECT
PLACE
ACTIVITY
INTENT
PREFERENCE
COLLECTION
CONSUMABLE_INSTANCE
DEVICE
```

### 13.4 Object 分类模板

`Object.class` 决定允许的状态维度、身份特征和默认衰减策略：

| Object class | 例子 | 主要状态 |
|---|---|---|
| `durable_singleton` | 钥匙、遥控器、充电器 | location、containment、availability、condition |
| `consumable` | 洗衣液、纸巾、护肤品 | lifecycle、remaining_ratio、quantity、open_state |
| `collection` | 一套工具、衣物集合 | membership、location、availability |
| `container` | 抽屉、收纳盒、工具箱 | location、open_state、membership |
| `wearable` | 外套、鞋、眼镜 | location、condition、usage_activity、ownership |
| `document_media` | 书、杂志、纸质文件 | location、activity_progress、condition |
| `appliance` | 咖啡机、空气净化器 | location、condition、usage_activity |
| `semantic_memory` | 外卖偏好、家庭规则、口头任务 | preference、intent_status、validity |

同一物理类别可以按用户意图采用不同模板。例如一瓶收藏酒可按 `durable_singleton` 管理，而日常饮料按 `consumable` 管理。

### 13.5 状态维度

| 维度 | 适用对象 | 值结构 | 典型事件 |
|---|---|---|---|
| `location` | Object、Person | place_id + relative_position | MOVED、OBSERVED_AT |
| `containment` | Object | container_id + depth | PUT_IN、TAKEN_OUT |
| `availability` | Object | available/missing/unknown | AVAILABILITY_CHANGED |
| `quantity` | Object、Consumable | count + unit + range | QUANTITY_CHANGED |
| `remaining_ratio` | Consumable | 0–1 + range | CONSUMED、REFILLED |
| `lifecycle` | Object | new/opened/in_use/empty/disposed | PURCHASED、OPENED、DISPOSED |
| `condition` | Object | intact/damaged/broken/dirty | CONDITION_CHANGED |
| `cleanliness` | Object、Place | clean/used/dirty/unknown | CLEANLINESS_CHANGED |
| `open_state` | Object、Container | open/closed/unknown | OPENED、CLOSED |
| `membership` | Collection、Container | member_entity_ids + confidence | RELATION_CHANGED |
| `usage_activity` | Object、Appliance、Wearable | active/idle/last_used_at | USED |
| `ownership` | Object | person_id/household/shared | ASSIGNED |
| `preference` | Preference | polarity + strength + context | PREFERENCE_EXPRESSED |
| `intent_status` | Intent | open/done/cancelled/expired | INTENT_CREATED、COMPLETED |
| `activity_progress` | Activity | page/step/percentage/range | PROGRESS_UPDATED |
| `physio_behavior_signal` | Person | derived_type + interval + confidence | SIGNAL_DERIVED |
| `outfit` | Person | garment_entity_ids | WORN |
| `privacy_state` | Place、Session | allowed/blocked/paused | POLICY_CHANGED |

实体只启用与自身类别匹配的状态维度。状态 schema 由 `entity_class` 的模板定义，并允许后续增加维度。

`physio_behavior_signal` 只接受经过授权的非诊断性派生信号，不保存为医疗结论，不用于首版主动提醒。

### 13.6 Place 语义层级

```text
Household
  └─ Room
      └─ Zone / Furniture
          └─ Container
              └─ Shelf / Drawer / Compartment
                  └─ Relative Position
```

示例：

```text
家
  → 客厅
  → 茶几
  → 桌面
  → 右侧靠近遥控器
```

MVP 使用语义空间和相对位置，不依赖三维地图。未来可把空间坐标作为 Place 的附加属性。

### 13.7 事件类型

```text
OBSERVED_AT
MOVED
PUT_IN
TAKEN_OUT
PURCHASED
OPENED
CLOSED
USED
CONSUMED
REFILLED
QUANTITY_CHANGED
AVAILABILITY_CHANGED
CONDITION_CHANGED
ASSIGNED
WORN
PREFERENCE_EXPRESSED
INTENT_CREATED
INTENT_COMPLETED
PROGRESS_UPDATED
RELATION_CHANGED
USER_CONFIRMED
USER_CORRECTED
MERGED
SPLIT
REDACTED
DELETED
```

### 13.8 时间模型

现实事件必须区分“发生、观察、接收、接受和生效”：

| 字段 | 含义 |
|---|---|
| `event_time.from` / `event_time.to` | 事件实际发生的点或区间；无法精确判断时保存范围 |
| `observed_at` | 设备实际观察或用户表达的时间 |
| `ingested_at` | 平台成功接收 `SourceEnvelope` 或 Evidence 元数据的时间 |
| `accepted_at` | 候选被写入事实主线的时间 |
| `valid_from` / `valid_to` | 该事件或状态在事实语义上的有效区间 |
| `device_monotonic_offset_ms` | 设备单调时钟相对会话起点的偏移，用于校正断网与系统时间漂移 |

事件排序优先使用校正后的 `observed_at`；在时间不确定或乱序到达时保留区间和不确定性，不以 `ingested_at` 冒充发生时间。投影以 `valid_from`、事件优先级和纠正关系计算当前状态。

---

## 14. 现实世界主线、候选与纠错

### 14.1 事实链

```text
SourceEnvelope
  → EvidenceItem
  → AtomicObservation
  → ObservationBundle / ActionSegment / ActivityEpisode
  → MemoryCandidate
  → MemoryEvent (append-only)
  → StateProjection (rebuildable)
```

### 14.2 主线与分支

- 每个稳定实体拥有 `stream_id`，其已接受事件构成主线。
- 低置信 `MemoryCandidate` 保存在候选区，可视为尚未合并的事实分支。
- 互斥候选进入同一 `conflict_set_id`。
- 用户纠正创建带 `supersedes_event_id` 的 `USER_CORRECTED` 事件；原事件正文保持不可变，其 `superseded` 有效状态由事件关系计算。
- 投影引擎按有效事件重算，不修改历史事件正文。

### 14.3 候选状态

```text
PENDING
ACCEPTED
REJECTED
CONFLICTED
EXPIRED
MERGED
REDACTED
```

### 14.4 自动接受规则

候选满足以下条件时可进入主线：

- 策略允许该实体、模态和状态类型。
- 身份归因达到阈值。
- 候选置信度达到该事件类型阈值。
- 与当前状态无高强度互斥，或有足够证据支持状态变化。
- 不涉及需要显式确认的敏感分类。
- 证据来源和模型版本处于允许列表。

默认优先级：

```text
用户明确确认
  > 用户明确表达的主动语音
  > 多设备/多次观测一致
  > 单源高置信观察
  > 单源低置信观察
```

### 14.5 置信度

候选同时保存：

- `model_confidence`
- `identity_confidence`
- `spatial_confidence`
- `temporal_confidence`
- `policy_confidence`
- `aggregate_confidence`

聚合值用于排序，不覆盖各分量。不同事件类型使用独立校准曲线。

### 14.6 冲突处理

位置冲突示例：

```text
候选 A：钥匙在玄关柜，0.78
候选 B：钥匙在客厅茶几，0.82
```

若 B 时间更新且视觉显示明确移动，生成 `MOVED`。若时间相近、身份不稳定，则创建冲突集并等待下一证据。查询时返回最佳假设与备选，不把低置信冲突包装成确定事实。

---

## 15. 复杂场景分层

### 15.1 三级结构

| 层级 | 名称 | 内容 | 生命周期 |
|---|---|---|---|
| L1 | `PlaceSnapshot` | 空间摘要、主要类别、拥挤度、显著变化 | 长期结构化 |
| L2 | `ObjectCandidate` | 局部对象、类别、位置、置信度、证据指针 | 候选期 |
| L3 | `ObjectMainline` | 已稳定归因的实体与事件主线 | 长期 |

### 15.2 对象升级信号

对象在以下情况下从 L2 升级为 L3：

- 用户主动命名。
- 购买、拆封或首次使用被观察到。
- 被单独拿起、放置或穿着。
- 在多个时间点稳定出现。
- 与已有实体特征匹配。
- 用户查询或纠正过该对象。

### 15.3 密集场景查询

默认查询返回 L1 摘要和高置信 L3 对象。用户继续追问具体小物品时，系统检索仍在 TTL 内的候选证据或使用后续新观测，不将一次场景图中的全部检测框直接持久化为实体。

---

## 16. 数据结构

### 16.1 `SourceEnvelope`

```json
{
  "id": "src_01",
  "spec_version": "1.0",
  "type": "media.image.captured",
  "source": "device://rokid/rv101/glass_01",
  "subject": "actor://owner_01",
  "household_id": "hh_01",
  "device_id": "glass_01",
  "source_session_id": "wear_01",
  "modality": "IMAGE",
  "trigger": "PERIODIC",
  "occurred_at": "2026-07-23T08:30:00Z",
  "observed_at": "2026-07-23T08:30:00Z",
  "ingested_at": "2026-07-23T08:30:03Z",
  "device_monotonic_offset_ms": 182030,
  "policy_snapshot_id": "pol_42",
  "schema_ref": "source-envelope/1.0",
  "idempotency_key": "glass_01:wear_01:182030",
  "capability_profile_version": "rv101-fw-1.20",
  "evidence_item_ids": ["evd_01"],
  "extensions": {
    "vendor_event_type": "CAMERA_CAPTURE_COMPLETED"
  }
}
```

`SourceEnvelope` 借鉴通用事件封装的 `type/source/subject/time/schema` 语义，但不是记忆本体。一个来源事件可以不带 Evidence，也可以关联图片与 IMU 等多个 `EvidenceItem`。

### 16.2 `EvidenceItem`

```json
{
  "id": "evd_01",
  "source_envelope_id": "src_01",
  "modality": "IMAGE",
  "content_type": "image/jpeg",
  "phenomenon_time": {
    "from": "2026-07-23T08:30:00Z",
    "to": "2026-07-23T08:30:00Z"
  },
  "storage_ref": "opaque://temporary/evd_01",
  "encryption_key_id": "dek_01",
  "ttl_until": "2026-07-23T08:45:00Z",
  "retention_state": "PROCESSING",
  "sensitivity_labels": [],
  "dedupe_token": "hmac-sha256:...",
  "metadata": {
    "battery_percent": 78,
    "thermal_state": "NORMAL",
    "capture_latency_ms": 420
  }
}
```

`dedupe_token` 使用家庭域与短时间窗隔离的 HMAC 密钥生成，只用于 Evidence 生命周期内的重复检测；它随 Evidence 一同删除，不能作为长期可关联或可还原的媒体指纹。

### 16.3 `AtomicObservation`

```json
{
  "id": "obs_01",
  "observation_type": "RELATION",
  "subject": {
    "entity_candidate_id": "obj_keys_candidate",
    "class": "KEYS"
  },
  "predicate": "located_at",
  "result": {
    "place_candidate_id": "place_coffee_table",
    "relative_position": "right_side"
  },
  "phenomenon_time": {
    "from": "2026-07-23T08:30:00Z",
    "to": "2026-07-23T08:30:00Z"
  },
  "observed_at": "2026-07-23T08:30:00Z",
  "evidence_item_ids": ["evd_01"],
  "procedure": {
    "extractor": "image-understanding",
    "model_name": "vision-model",
    "model_version": "v1",
    "schema_version": "atomic-observation/1.0"
  },
  "confidence": {
    "model": 0.88,
    "spatial": 0.82
  },
  "sensitivity_labels": [],
  "allowed_purposes": ["MEMORY_FORMATION"]
}
```

`AtomicObservation` 是解析结果，不具有候选状态，也不能被模型直接提升为事实。同一 Evidence 可以产生多个观察，一个观察也可以引用多个 Evidence。

### 16.4 `ObservationBundle`、`ActionSegment` 与 `ActivityEpisode`

```json
{
  "bundle_id": "bundle_01",
  "atomic_observation_ids": ["obs_01", "obs_02", "obs_03"],
  "time_range": {
    "from": "2026-07-23T08:29:58Z",
    "to": "2026-07-23T08:30:05Z"
  },
  "action_segment": {
    "id": "seg_01",
    "type": "PLACE_OBJECT",
    "confidence": 0.84
  },
  "activity_episode": {
    "id": "episode_01",
    "type": "ORGANIZING_ROOM",
    "status": "ACTIVE",
    "boundary_confidence": 0.76
  }
}
```

Bundle、Segment 和 Episode 只保存结构化关联与摘要，不复制媒体。Episode 可以处于 `ACTIVE / SUSPENDED / ENDED / REOPENED`，允许短暂等待后继续同一目标。

### 16.5 `MemoryCandidate`

```json
{
  "id": "cand_01",
  "source_observation_ids": ["obs_01", "obs_02"],
  "source_episode_id": "episode_01",
  "candidate_type": "OBJECT_LOCATION",
  "subject": {
    "entity_id": "obj_keys_01",
    "class": "KEYS",
    "identity_confidence": 0.91
  },
  "assertion": {
    "state_dimension": "location",
    "value": {
      "place_id": "place_coffee_table",
      "relative_position": "right_side"
    }
  },
  "event_time": {
    "from": "2026-07-23T08:30:00Z",
    "to": "2026-07-23T08:30:00Z"
  },
  "confidence": {
    "model": 0.88,
    "identity": 0.91,
    "spatial": 0.82,
    "aggregate": 0.87
  },
  "status": "PENDING",
  "formation_procedure": "location-memory-policy/1.0",
  "requires_confirmation": false
}
```

### 16.6 `MemoryEvent`

```json
{
  "id": "mem_evt_01",
  "household_id": "hh_01",
  "stream_id": "stream_obj_keys_01",
  "branch_id": "main",
  "event_type": "MOVED",
  "entity_id": "obj_keys_01",
  "event_time": {
    "from": "2026-07-23T08:30:00Z",
    "to": "2026-07-23T08:30:00Z"
  },
  "observed_at": "2026-07-23T08:30:02Z",
  "ingested_at": "2026-07-23T08:30:03Z",
  "accepted_at": "2026-07-23T08:30:04Z",
  "valid_from": "2026-07-23T08:30:00Z",
  "valid_to": null,
  "payload": {
    "from_place_id": "place_entryway",
    "to_place_id": "place_coffee_table",
    "relative_position": "right_side"
  },
  "source_candidate_ids": ["cand_01", "cand_02"],
  "confidence": 0.91,
  "policy_snapshot_id": "pol_42",
  "supersedes_event_id": null
}
```

### 16.7 `StateProjection`

```json
{
  "entity_id": "obj_keys_01",
  "projection_type": "CURRENT_STATE",
  "as_of": "2026-07-23T08:30:04Z",
  "version": 17,
  "state": {
    "location": {
      "place_id": "place_coffee_table",
      "relative_position": "right_side",
      "observed_at": "2026-07-23T08:30:00Z",
      "confidence": 0.91,
      "freshness": "RECENT"
    },
    "availability": {
      "value": "AVAILABLE",
      "confidence": 0.84
    }
  },
  "conflicts": []
}
```

### 16.8 存储分层

| 数据层 | 存储 | 生命周期 | 是否直接作为事实 |
|---|---|---|---|
| 设备采集缓冲 | RV101/手机本地加密存储 | 秒到 10 分钟 | 否 |
| 原始 Evidence | 独立加密对象存储 | 正式环境最长 15 分钟 | 否 |
| SourceEnvelope / Observation / Candidate | PostgreSQL | 按处理与审计策略 | 否 |
| MemoryEvent | PostgreSQL 追加式事件表 | 直至用户删除或策略到期 | 是 |
| StateProjection | PostgreSQL | 可重建 | 否 |
| 全文/向量索引 | PostgreSQL/pgvector | 可重建、随删除同步清理 | 否 |
| Signal / Cache | PostgreSQL/Redis | 短期、可重建 | 否 |
| Audit / Tombstone | PostgreSQL | 按合规策略保留最小字段 | 否 |

测试调试环境只有在 Tester 显式授权、隔离账户和隔离密钥下，才可将 Evidence 延长至最多 24 小时；生产默认不继承此窗口。

### 16.9 核心数据库表

```sql
households(
  id, owner_actor_id, name, region, status, created_at, updated_at
)

actors(
  id, household_id, actor_type, principal_ref, role,
  status, created_at, updated_at
)

devices(
  id, household_id, owner_actor_id, vendor, product_name,
  model, firmware_version, os_build, app_version,
  capability_profile_json, credential_status, last_seen_at
)

entities(
  id, household_id, type, class, canonical_name,
  aliases_json, identity_features_json, status, created_at, updated_at
)

places(
  id, household_id, parent_id, place_type, name,
  relative_descriptor, policy_zone_id, created_at
)

wear_sessions(
  id, household_id, device_id, trigger_source, state,
  policy_snapshot_id, started_at, ended_at, end_reason
)

capture_attempts(
  id, household_id, device_id, session_id, scheduled_at,
  attempted_at, trigger, policy_decision, result_code,
  latency_ms, metadata_json, idempotency_key
)

source_envelopes(
  id, spec_version, household_id, actor_id, device_id, source_session_id,
  type, source, subject, modality, trigger, occurred_at, observed_at,
  ingested_at, device_monotonic_offset_ms, schema_ref,
  capability_profile_version, extensions_json,
  policy_snapshot_id, idempotency_key
)

evidence_items(
  id, household_id, source_envelope_id, modality, content_type,
  phenomenon_time_from, phenomenon_time_to, storage_ref, key_id,
  ttl_until, retention_state, sensitivity_labels_json,
  deleted_at, metadata_json
)

atomic_observations(
  id, household_id, observation_type, subject_json, predicate,
  result_json, phenomenon_time_from, phenomenon_time_to, observed_at,
  procedure_json, confidence_json, sensitivity_labels_json,
  allowed_purposes_json, created_at
)

observation_evidence_links(
  observation_id, evidence_item_id, relation_type, created_at
)

observation_bundles(
  id, household_id, time_from, time_to, grouping_reason,
  confidence, created_at
)

bundle_observation_links(
  bundle_id, observation_id, created_at
)

action_segments(
  id, household_id, bundle_id, segment_type, time_from, time_to,
  place_id, confidence_json, status, created_at
)

activity_episodes(
  id, household_id, episode_type, goal_candidate_json,
  source_session_ids_json, started_at, ended_at,
  boundary_confidence, status, created_at, updated_at
)

episode_segment_links(
  episode_id, segment_id, sequence_no, created_at
)

memory_candidates(
  id, household_id, candidate_type, entity_id,
  source_observation_ids_json, source_episode_id,
  assertion_json, confidence_json, status, conflict_set_id,
  formation_procedure, created_at, resolved_at
)

entity_aliases(
  id, household_id, entity_id, alias_type, alias_value,
  source, confidence, created_at
)

candidate_links(
  id, household_id, candidate_id, target_type, target_id,
  relation_type, confidence, created_at
)

memory_events(
  id, household_id, stream_id, branch_id, event_type, entity_id,
  event_time_from, event_time_to, observed_at, ingested_at, accepted_at,
  valid_from, valid_to, device_monotonic_offset_ms, payload_json,
  source_candidate_ids_json, confidence, policy_snapshot_id,
  supersedes_event_id
)

state_projections(
  entity_id, projection_type, version, as_of,
  state_json, conflict_json, rebuilt_at
)

policy_snapshots(
  id, household_id, version, mode, allowed_scopes_json,
  capture_budget_json, retention_policy_json, signature, created_at
)

signal_candidates(
  id, household_id, signal_type, entity_id, payload_json,
  priority, status, dedupe_key, created_at, expires_at
)

reminder_decisions(
  id, household_id, signal_candidate_id, decision, reason_code,
  channel, target_device_id, wording_json, policy_snapshot_id,
  created_at, expires_at
)

reminder_deliveries(
  id, household_id, reminder_decision_id, channel, target_device_id,
  delivery_status, delivered_at, acknowledged_at, response_type
)

agent_grants(
  id, household_id, agent_actor_id, scope_json,
  entity_filter_json, expires_at, revoked_at, created_at
)

deletion_requests(
  id, household_id, requester_id, target_type, target_id,
  time_from, time_to, status, created_at, completed_at
)

deletion_jobs(
  id, deletion_request_id, subsystem, target_ref,
  status, attempt_count, last_error, completed_at
)

deletion_tombstones(
  id, household_id, target_type, target_id,
  deletion_request_id, audit_hash, completed_at
)

audit_records(
  id, household_id, actor_type, actor_id, action,
  resource_type, resource_id, policy_version, result,
  metadata_json, occurred_at
)

outbox_events(
  id, aggregate_type, aggregate_id, event_type,
  payload_json, idempotency_key, created_at,
  published_at, attempt_count
)
```

`memory_events` 与对应 `outbox_events` 必须在同一事务内写入。所有消费者以 `outbox_events.id` 或业务 `idempotency_key` 去重。

### 16.10 关键索引

- `memory_events(household_id, entity_id, event_time_from desc)`
- `memory_events(stream_id, accepted_at)`
- `memory_candidates(status, created_at)`
- `atomic_observations(household_id, observed_at desc)`
- `activity_episodes(household_id, status, started_at desc)`
- `evidence_items(ttl_until, retention_state)`
- `source_envelopes(household_id, observed_at desc)`
- `capture_attempts(device_id, session_id, scheduled_at)`
- `places(household_id, parent_id)`
- `signal_candidates(household_id, status, priority, created_at)`
- `audit_records(household_id, occurred_at desc)`
- `entities(household_id, class, canonical_name)`
- `outbox_events(published_at, created_at)`

自然语言检索使用结构化过滤、全文索引与向量索引组合。向量只保存结构化摘要或经批准的派生表示。

---

## 17. 服务端模块

### 17.1 Device Registry

- 管理设备身份、Owner、家庭域、硬件型号、固件、App 版本。
- 签发设备凭据和最小 scope。
- 记录设备能力矩阵。

### 17.2 Session & Policy Service

- 创建、更新和结束佩戴会话。
- 下发签名策略快照。
- 处理暂停、恢复、全局关闭和策略热更新。
- 确保收紧策略立即影响下一次采集。

### 17.3 Evidence Service

- 创建临时上传授权。
- 验证大小、模态、TTL、策略版本、传输完整性和短窗 `dedupe_token`。
- 使用每证据独立密钥加密。
- 驱动删除和回执。

### 17.4 Perception Orchestrator

- 按模态选择 Image、ShortVideo、Audio、Sensor 或 StructuredEvent Extractor。
- 控制重试、超时、成本和模型版本。
- 将解析器结果按统一 Schema 写入 `atomic_observations`。
- 对图片执行质量、重复、敏感内容和场景变化门控。
- 对短视频执行片段解码、关键帧/运动信息提取；不接受长视频或连续视频流。
- 对音频执行 VAD 结果校验、ASR、说话人片段和声音事件提取，不把整段转写直接当作事实。
- 对模型输出执行 JSON Schema 校验，拒绝无法归因或越权字段。

首版技术候选用于快速实验，不写入核心契约：

| 能力 | 可替换候选 | 选型标准 |
|---|---|---|
| 图像质量、变化和基础跟踪 | OpenCV | 端侧速度、功耗、误过滤率 |
| 多模态场景理解 | Qwen-VL/InternVL 或同级受控模型 | 结构化准确率、中文能力、成本 |
| 物体检测与开放词汇定位 | Florence-2、Grounding DINO 或同级模型 | 小物体召回、类别泛化 |
| 分割与跨帧关联 | SAM 2、TAPIR 或同级模型 | 遮挡恢复、延迟、部署成本 |
| 短音频 VAD/ASR | 端侧 VAD + 可私有化中文 ASR | 误触发率、漏检率、短句准确率、端到端时延 |

具体模型必须在统一受控评测集上比较；更换模型只产生新的 `model_name`、`model_version` 和校准版本，不改变 AtomicObservation、MemoryCandidate、Event 或 Query 契约。

### 17.5 Temporal Fusion

- 根据时间窗、地点、对象集合、动作变化和来源可靠度构建 `ObservationBundle`。
- 将局部动作归入 `ActionSegment`，再根据目标连续性和迟滞规则维护 `ActivityEpisode`。
- 支持不同设备和模态对同一 Episode 提供观察，不要求它们使用同一通信协议。
- 输出结构化聚合结果和 `MemoryCandidate`，不直接写入 `MemoryEvent`。
- 记录每次边界决策的规则版本、模型版本、置信度和来源观察，保证可回放与可评测。

### 17.6 Entity Resolver

- 根据类别、外观、空间、时间和用户命名归并实体。
- 支持实体合并和拆分事件。
- 管理别名与身份置信度。
- 综合使用类别、视觉 embedding、颜色/形状、OCR 文本、容器关系、语义位置、时间连续性、短时 tracklet、用户命名和历史交互。
- 对“同类多实例”默认保守建候选，不因一次相似观测直接合并。
- `MERGED` 与 `SPLIT` 都通过事件表达，并触发投影、索引和候选链接重算。

### 17.7 Event Store

- 接受通过 Gate 的候选。
- 追加 MemoryEvent。
- 提供流式回放和按时间查询。
- 保证同一幂等键只生成一个事件。

### 17.8 Projection Engine

- 按实体和状态维度消费事件。
- 生成当前状态、趋势和冲突。
- 支持从任意时间点重算。
- 删除或纠正后更新所有派生投影。

### 17.9 Query & Search

- 对象查找、位置、时间线、空间摘要、耗材、偏好和任务查询。
- 输出置信度、新鲜度和备选假设。
- 根据调用方 scope 过滤字段和实体。

### 17.10 Signal & Reminder Service

- 根据投影变化计算 `LOW_STOCK`、`OBJECT_MOVED`、`INTENT_DETECTED`、`CONFIDENCE_CONFLICT` 等 `SignalCandidate`。
- 对候选执行去重、冷却、优先级、过期、用户状态和隐私策略检查。
- 生成 `ReminderDecision` 并选择可用终端完成提醒投递。
- 当前阶段不自动购物、不代表用户发送任意消息，也不执行其他外部世界动作。

### 17.11 Privacy & Audit

- 全链路删除、近窗遗忘、脱敏和 tombstone。
- 用户可见审计。
- 证明证据已删除、派生任务已取消、索引已更新。

---

## 18. 内部 API 契约

所有写接口要求：

- `Authorization: Bearer <device-or-service-token>`
- `Idempotency-Key`
- `X-Policy-Version`
- UTC 事件时间与设备单调时钟偏移。
- 请求和响应包含 `request_id`。

### 18.1 会话

```http
POST /internal/v1/sessions
```

```json
{
  "device_id": "glass_01",
  "trigger_source": "WEAR_EVENT",
  "wear_detected_at": "2026-07-23T08:00:00Z",
  "app_version": "0.1.0",
  "device_state": {
    "battery_percent": 82,
    "network": "WIFI"
  }
}
```

```http
PATCH /internal/v1/sessions/{session_id}
```

允许动作：`ACTIVATE`、`PAUSE`、`RESUME`、`BLOCK`、`END`。

### 18.2 策略

```http
GET /internal/v1/capture-policy?device_id=glass_01&session_id=wear_01
```

策略包含：

- 当前运行模式。
- 允许模态与触发来源。
- 禁采时段、位置和上下文。
- 采集预算。
- 证据 TTL。
- 调试证据权限。
- 策略签名与过期时间。

### 18.3 采集审计

```http
POST /internal/v1/capture-attempts
```

```json
{
  "capture_id": "cap_01",
  "session_id": "wear_01",
  "device_id": "glass_01",
  "scheduled_at": "2026-07-23T08:10:00Z",
  "attempted_at": "2026-07-23T08:10:00.120Z",
  "modality": "IMAGE",
  "trigger": "PERIODIC",
  "policy_version": "pol_42",
  "result": "CAPTURED_LOCAL",
  "latency_ms": 430,
  "local_deleted_at": "2026-07-23T08:10:01Z",
  "error_code": null
}
```

### 18.4 证据

```http
POST /internal/v1/evidence/init
POST /internal/v1/evidence/{id}/complete
POST /internal/v1/evidence/{id}/delete-receipt
```

PoC 阶段服务端关闭 Evidence 上传 feature flag，仅开放采集元数据。

### 18.5 结构化事件

```http
POST /internal/v1/observation-candidates
POST /internal/v1/memory-events
```

只有 Perception 与 Memory Core 服务账号可以调用。设备端可提交预结构化候选，但不能直接写主线事件。

### 18.6 查询

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

`where-is` 响应：

```json
{
  "entity": {
    "id": "obj_keys_01",
    "name": "钥匙"
  },
  "best_location": {
    "place_path": ["家", "客厅", "茶几", "右侧"],
    "observed_at": "2026-07-23T08:30:00Z",
    "confidence": 0.91,
    "freshness": "RECENT"
  },
  "alternatives": [],
  "source_event_id": "mem_evt_01"
}
```

### 18.7 隐私

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

`forget-recent`：

```json
{
  "minutes": 10,
  "scope": ["EVIDENCE", "CANDIDATES", "EVENTS", "PROJECTIONS", "INDEXES"],
  "reason": "USER_REQUEST"
}
```

### 18.8 信号

```http
POST /v1/memory/subscriptions
GET  /v1/memory/signals
WS   /v1/memory/signals/stream
```

信号类型：

```text
LOW_STOCK
OBJECT_MOVED
OBJECT_MISSING
INTENT_DETECTED
TASK_DUE
PREFERENCE_UPDATED
ACTIVITY_PROGRESS_UPDATED
CONFIDENCE_CONFLICT
PRIVACY_STATE_CHANGED
```

---

## 19. Agent 调用逻辑

### 19.1 Agent 访问模式

| 模式 | 例子 | 权限 |
|---|---|---|
| 查询 | 找钥匙、查时间线 | `memory.read` |
| 订阅 | 监听低库存 | `signal.subscribe` |
| 建议 | 生成补货提醒 | `suggestion.write` |
| 确认 | 用户通过近场设备确认候选 | `memory.confirm` |
| 纠正 | 用户口头修正对象或位置 | `memory.correct` |

### 19.2 主动服务

```text
StateProjection 发生变化
  → SignalCandidate 生成
  → 去重与冷却
  → 检查用户状态和隐私模式
  → Reminder Policy 决定是否、何时和通过哪个终端提醒
  → 必要时由 Agent 生成简短提醒措辞
  → ReminderDelivery
  → 用户确认、忽略或追问
```

默认近场优先级：

```text
正在佩戴的眼镜
  > 当前活跃手机
  > 家庭音箱/其他设备
```

SignalCandidate 只表示“有可能值得提醒的状态变化”。当前阶段唯一允许的主动结果是提醒投递；系统不得自动购物、代替用户发送任意消息或执行其他外部动作。Agent 只在歧义判断和个性化措辞确有收益时参与，不能直接写入 MemoryEvent。

### 19.3 回答可解释性

Agent 对现实状态的回答必须由 Query API 的结构化结果生成，至少保留以下可解释字段：

- 对象：`entity_id`、规范名和命中的别名。
- 状态：状态维度、当前值和可能的备选值。
- 时间：`observed_at`、新鲜度和时间不确定范围。
- 空间：`place_id`、语义路径和相对位置。
- 可信度：聚合置信度及主要置信度分量。
- 来源：`memory_event_id`、来源模态和来源设备类型。
- 确认：是否由用户明确确认或纠正。

面向用户的默认回答不暴露内部 ID，但在审计和调试视图中可以沿 `memory_event_id → source_candidate_ids → evidence deletion receipt` 追溯。原始 Evidence 已删除时，系统明确显示“结构化记忆来源已处理并删除”，不能伪造媒体回看。

找物回答示例：

```json
{
  "answer": "钥匙最近一次在客厅茶几右侧被看到，时间是今天 16:30。",
  "entity": {"id": "obj_keys_01", "name": "钥匙"},
  "state": {"dimension": "location", "place_path": ["家", "客厅", "茶几"], "relative_position": "右侧"},
  "observed_at": "2026-07-23T08:30:00Z",
  "freshness": "RECENT",
  "confidence": 0.91,
  "alternatives": [],
  "memory_event_id": "mem_evt_01",
  "user_confirmed": false
}
```

---

## 20. 隐私、安全与风控

### 20.1 策略执行顺序

```text
触发
  → 本地权限与策略
  → 采集
  → 本地敏感检测/加密
  → 服务端策略复核
  → 模型处理
  → 结构化入库
  → 媒体删除
```

本地策略在相机和麦克风启动前执行。服务端二次检查不能替代设备侧停止采集。

### 20.2 禁采空间

首版组合使用：

- 用户手动设置家庭内禁采空间。
- 已知 Wi-Fi SSID/BSSID。
- 手机地理围栏。
- 眼镜端快速暂停。

后续加入房间识别时，房间模型只能收紧策略；识别不确定时采用更严格结果。

### 20.3 敏感内容

敏感分类包括：

- 屏幕、证件、支付信息和密码。
- 浴室、卧室私密状态。
- 未授权访客。
- 医疗、身体和亲密场景。

处理结果为：

- 采集前阻断。
- 设备端删除。
- 局部脱敏后再处理。
- 只保留无敏感字段的结构化结果。

### 20.4 全链路删除

删除请求覆盖：

1. 设备本地证据与离线队列。
2. 对象存储和加密密钥。
3. AtomicObservation、Bundle、Segment、Episode 和 MemoryCandidate。
4. MemoryEvent 或其有效性。
5. StateProjection 重算。
6. 全文与向量索引。
7. 缓存、信号和异步任务。
8. 审计 tombstone。

删除完成后返回各子系统回执；失败项持续重试并对 Owner 可见。

### 20.5 审计展示

用户看到：

- 设备与会话。
- 触发来源。
- 采集结果和策略版本。
- 形成的结构化记忆。
- 原始证据删除状态。
- Agent 查询和信号消费记录。

---

## 21. 统一手机 App

手机 App 是首版唯一用户入口和默认数据网关。当前阶段先建设设备连接、采集、加密队列和上传等后端能力，前端页面可以逐步补齐，但不能为图片、短视频、音频、戒指或不同眼镜拆分多个用户 App。核心模块与后续页面包括：

1. **账号与设备注册**：用户身份、设备绑定、密钥和能力档案。
2. **设备 Adapter**：Rokid CXR-L、Rokid Native Transport、戒指 BLE 与未来硬件。
3. **统一采集 Session**：跨图片、短视频、音频、传感器的策略和状态。
4. **加密队列与上传**：本地 TTL、幂等、断网重试、删除回执。
5. **设备页面**：眼镜和戒指状态、固件、权限、最近同步。
6. **运行与隐私**：家庭、外出、暂停、禁采空间、近窗遗忘和审计。
7. **记忆与提醒**：对象、时间线、耗材、偏好、任务、纠正和提醒。

首个 PoC 可以暂不完成记忆浏览等完整前端，但必须在同一手机 App 内跑通至少一个眼镜 Adapter、音频与图片采集、统一 Session、账号归属和可替换上传接口。内部 Web 控制台只能辅助调试，不能替代手机网关。

---

## 22. 质量指标

### 22.1 产品指标

| 指标 | MVP 目标 |
|---|---|
| 找物 Top-1 语义位置正确率 | ≥70%，限定家庭与测试物品集 |
| 已入库找物查询延迟 | P50 ≤3 秒 |
| 耗材提醒有用率 | ≥50% |
| 清晰主动语音偏好/任务入库成功率 | ≥80% |
| 暂停、全局关闭、删除成功率 | 100% |
| 佩戴提示次数 | 每次佩戴最多 1 次 |

### 22.2 记忆质量

| 指标 | 含义 |
|---|---|
| 候选接受率 | 采集与模型有效性 |
| 用户纠正率 | 主线事实错误水平 |
| 实体误合并/误拆分率 | Identity 质量 |
| 状态冲突率 | 同实体互斥状态 |
| 投影重算一致性 | 事件回放确定性 |
| 记忆新鲜度 | 当前状态距最后可信观察时间 |

### 22.3 设备与成本

| 指标 | 含义 |
|---|---|
| 计划采集 tick 成功/可归因率 | 调度可靠性 |
| 每小时耗电 | 佩戴可用性 |
| 温升与过热停止次数 | 设备安全 |
| 每用户每日证据数和字节 | 传输成本 |
| 每用户每日模型成本 | 运营成本 |
| 原始媒体平均存活时长 | 隐私承诺 |

---

## 23. 研发阶段与工作包

### Phase 0：Rokid 与戒指能力验证

#### P0-A Rokid 官方 Sample 跑通

输入：

- Rokid Glasses（RV101）真机。
- 专用开发线。
- 手机 Rokid AI App 开启 ADB。
- Android Studio。
- 官方 [`GlassesBareDevSample.zip`](https://rokid-ota.oss-cn-hangzhou.aliyuncs.com/toB/Document/CXR_Bare/GlassesBareDevSample.zip)。

步骤：

1. 构建并安装 Sample。
2. 验证佩戴/摘下、折叠广播。
3. 验证 CameraX 无 Preview 单图。
4. 验证 VideoCapture。
5. 验证 AudioRecord。
6. 验证 SensorManager 与按键。
7. 用 `adb pull` 检查媒体并完成删除。

产出：

- 设备、固件、系统版本和权限矩阵。
- 后台/熄屏/折叠/摘下行为报告。
- 单图耗时、失败率、耗电和温升基线。
- 官方 Sample 与目标 App 的差异清单。

#### P0-B 后台会话可行性

测试：

- 佩戴广播是否能可靠触发应用。
- 倒计时期间启动相机前台服务是否成功。
- Activity 不可见后 CameraX 能否继续工作。
- 熄屏、锁屏、折叠、摘下、进程回收后的行为。
- Android 12 前台服务限制在目标固件上的表现。
- 眼镜 Runtime 到统一手机网关的 BLE/Wi-Fi 传输、断连恢复与背压；CXR-L 只记录为过渡 Adapter。

退出条件：

- 获得稳定、合法的相机调用生命周期。
- 获得可靠的佩戴结束信号或可信安全超时。
- 能证明暂停/摘下后不再调用相机。

#### P0-C 戒指能力验证

步骤：

1. 使用本地 Python SDK 扫描和连接。
2. 获取系统信息、电量与固件。
3. 验证按键双击、单击和手势事件。
4. 验证主动录音、自动分帧接收与 WAV 解码。
5. 验证手势模式下的短时 IMU。
6. 测量模式切换、误触、断连和重连。

产出：

- 手势到产品动作的推荐映射。
- 手机/开发机 Ring Bridge 方案。
- 录音与 IMU 状态约束测试报告。

### Phase 1：Rokid 定时截图 PoC

功能：

- 佩戴事件。
- 5 秒倒计时和一次轻提示。
- 本次关闭、暂停、恢复、摘下结束。
- 固定间隔截图。
- 本地策略检查。
- 图片成功验证后立即删除。
- 无媒体采集元数据审计。

PoC 服务端接口：

- `POST /internal/v1/sessions`
- `GET /internal/v1/capture-policy`
- `POST /internal/v1/capture-attempts`
- `POST /internal/v1/privacy/pause`
- `POST /internal/v1/privacy/erase`
- `GET /internal/v1/audit`

验收：

- 30 分钟会话内，≥95% 计划 tick 有成功或可归因结果。
- 暂停后无新截图。
- 摘下后会话结束且无新截图。
- 服务端请求体、日志和存储中无媒体、缩略图、OCR 或可还原指纹。
- 默认媒体零外传、零残留。
- 重复请求不产生重复会话或审计记录。

### Phase 2：Edge Core 与隐私链

功能：

- 签名策略快照。
- 离线策略缓存与 fail closed。
- 加密证据缓冲区。
- TTL 清理。
- 断网队列。
- 全局关闭、禁采空间、删除回执。
- 设备凭据与版本管理。

验收：

- 策略收紧在下一次采集前生效。
- 无有效策略时相机不启动。
- 断网重试不能绕过暂停、删除或策略版本。
- 进程重启后恢复为安全状态。

### Phase 3：感知与记忆候选链

功能：

- 图片上传授权和加密。
- Vision Extractor。
- 短音频 VAD、ASR 与 Intent/Preference Extractor。
- AtomicObservation、ObservationBundle、ActionSegment 和 ActivityEpisode。
- MemoryCandidate。
- 实体归并。
- 置信度与冲突。
- 证据删除。

首批受控类别：

- 钥匙、遥控器、充电器。
- 洗衣液或纸巾一类耗材。
- 外卖偏好。
- 明确口头任务。

验收：

- 每个模型结果都有候选和证据来源。
- 模型不能直接更新投影。
- 结构化完成后媒体在 TTL 内删除。
- 候选可接受、拒绝、冲突和过期。

### Phase 4：Memory Core 与 P0 场景

功能：

- Entity、Place、MemoryEvent、StateProjection。
- 找物 Query 和 Timeline。
- 耗材趋势与 `LOW_STOCK`。
- 偏好与任务查询。
- 用户纠正。
- 近窗遗忘与投影重算。

验收脚本：

1. 用户把钥匙从玄关移到茶几，查询返回茶几和时间。
2. 用户再次移动钥匙，时间线保留两次事件，当前投影更新。
3. 用户纠正一次误识别，投影重算后查询正确。
4. 洗衣液连续观测下降，产生一次去重后的低库存建议。
5. 用户说“这家外卖很好吃”，偏好可查。
6. 删除最近 10 分钟后，相关证据、候选、事件、投影、索引和信号完成清理。

### Phase 5：真实家庭试用

范围：

- 至少 5 个家庭。
- 每户有限对象白名单和一个耗材类别。
- 统一设备版本与策略。
- 每日质量、耗电、温升和隐私审计。

发布门槛：

- 达到第 22 节指标。
- 删除和暂停 100% 通过。
- 所有媒体 TTL 可验证。
- 找物错误可被用户理解并纠正。
- 会话提示低打扰。

### Phase 6：中台开放

功能：

- 受控开发者账号。
- Device Adapter SDK。
- Agent scopes 与订阅。
- 限流、计费、配额和审计。
- 更多硬件适配。

---

## 24. 三天活动开发计划与团队分工

### 24.1 时间盒

本次活动按北京时间 **2026-07-26 00:00** 截止计算。以 **2026-07-23 16:51:41** 为计划起点，剩余墙钟时间为 **55 小时 8 分 19 秒**。

两晚正常休息、吃饭、设备故障和最后提交缓冲必须计入计划。每位成员实际可用开发时间按 **30–36 小时**估算，不按 55 小时连续开发安排任务。最终提交应在 7 月 25 日 23:15 前完成，保留 45 分钟上传和平台故障缓冲。

### 24.2 本次活动唯一目标

本次不实现完整中台，而是交付一个可以真实演示、能证明产品价值的纵向闭环：

```text
CXR-L 过渡探针或 RV101 原生 App 真实采集一张图片
  → 上传到单一后端
  → 一个多模态模型抽取对象与语义位置
  → 写入 AtomicObservation、MemoryCandidate 和 MemoryEvent
  → 生成最新位置 StateProjection
  → 用户查询“钥匙在哪里”
  → 返回位置、时间和置信度
  → 用户暂停或删除后停止采集并清理临时图片
```

演示只使用 3 类预先准备的物品：钥匙、遥控器、充电器；只使用 2–3 个语义位置。重点是链路真实和结果可解释，不追求开放世界识别。

### 24.3 活动范围

**必须完成：**

- RV101 官方 Sample 构建、安装和真机拍照。
- Glass App 的手动采集；定时采集在真机允许时加入。
- 最小 `ACTIVE / PAUSED / ENDED` 会话状态。
- 图片上传、单一多模态模型调用和结构化 JSON 校验。
- `Evidence → AtomicObservation → MemoryCandidate → Event → Projection` 最小数据链。
- 一个找物查询入口，可使用简单 Web 页面或内部控制台。
- 暂停后不再采集；临时图片处理后删除。
- 可重复执行的三分钟演示脚本和录屏。

**有余量再完成：**

- 佩戴广播和 5 秒倒计时。
- 戒指双击触发主动录音或“记一下”。
- 一次用户纠正后投影重算。
- 简单审计时间线。

**本次活动不实现：**

- 完整手机管理 App。
- 动态采集评分、复杂禁采空间识别和长期离线队列。
- 耗材趋势、衣橱建库、多人家庭权限和主动 Signal。
- 自建模型、向量数据库、微服务拆分、开发者平台。
- 长视频、连续视频流和复杂跨设备实时媒体传输。

这些能力仍保留在完整产品路线中，不进入本次提交的阻塞路径。

### 24.4 推荐团队配置

本次只建立三个主工作流，每个工作流始终只有一个明确负责人：

| 工作流 | 负责人角色 | 前 24 小时任务 | 后 24 小时任务 | 最终交付 |
|---|---|---|---|---|
| A：RV101 设备端 | Android/硬件负责人 | 跑通 Sample、CameraX、权限、真机安装；输出图片 | 接入会话、上传、暂停与清理；稳定 APK | RV101 APK、设备操作说明、真实采集 |
| B：AI 与记忆后端 | 后端/算法负责人 | 冻结三个 JSON 契约；搭建单体 API、数据库和模型调用 | Observation、Candidate、Event、Projection、Query、删除 | 可启动服务、数据库、API 与测试 |
| C：集成与演示 | 全栈/产品负责人 | 建立演示数据、简单查询页、持续拉通 A/B | 集成测试、降级处理、录屏、讲稿和提交包 | 演示页面、脚本、视频、提交材料 |

人员映射：

| 实际人数 | 分配 |
|---|---|
| 1 人 | 先完成 A 的真机采集，再完成 B 的最小闭环，最后用 Swagger/简单页面承担 C；戒指不做 |
| 2 人 | 1 人负责 A；1 人负责 B+C；到 7 月 24 日 19:00 后共同集成 |
| 3 人 | A、B、C 各 1 人，是本次推荐配置 |
| 4 人及以上 | 第 4 人负责戒指与 QA；其余人员优先补测试、录屏和容灾，不新开产品模块 |

编码 Agent 可以并行生成 schema、API 客户端、测试和文档，但每个工作流的人类负责人必须审查并合并；设备端与后端不得同时修改同一份契约。

### 24.5 逐时里程碑

| 时间（北京时间） | 设备端 A | 后端 B | 集成/演示 C | 里程碑 |
|---|---|---|---|---|
| 7/23 17:00–18:00 | 核对 RV101、开发线、ADB | 建立单体服务与本地数据库 | 冻结演示物品、位置、脚本 | 范围和接口冻结 |
| 7/23 18:00–21:00 | 官方 Sample 安装并拍出第一张图 | 完成 ingest/query API 骨架 | 建立最小查询页 | **21:00 相机 Go/No-Go** |
| 7/23 21:00–24:00 | 图片导出或上传、手动暂停 | 跑通模型并得到合法 JSON | 用固定样本拉通页面 | 第一条真实模型结果 |
| 7/24 09:00–12:00 | 会话、清理、可选定时采集 | Evidence/Candidate 持久化 | 联调真实 RV101 图片 | **12:00 设备路径冻结** |
| 7/24 13:00–16:00 | 修复真机阻塞问题 | Event、Projection、Find Query | 准备三组可重复场景 | 查询返回真实位置 |
| 7/24 16:00–19:00 | 接入最终接口 | 幂等、错误码、删除 | 完成端到端串联 | **19:00 首次完整 Demo** |
| 7/24 19:00–22:00 | 稳定性修复 | 稳定性修复 | 首轮完整彩排和问题单 | 主链路可连续运行 3 次 |
| 7/25 09:00–11:00 | 只修 P0 Bug | 只修 P0 Bug | 只修演示阻塞问题 | **11:00 功能冻结** |
| 7/25 11:00–15:00 | APK 与设备说明 | 启动脚本、测试与数据清理 | UI、讲稿、架构图 | 提交候选版本 |
| 7/25 15:00–18:00 | 配合彩排 | 配合彩排 | 录制主视频和备用视频 | 演示资产完成 |
| 7/25 18:00–20:00 | 最终真机检查 | 最终服务检查 | 两次计时彩排 | **20:00 代码冻结** |
| 7/25 20:00–22:00 | 打包 APK | 打包服务 | 整理 README、视频、材料 | 可上传提交包 |
| 7/25 22:00–23:15 | 仅处理提交阻塞 | 仅处理提交阻塞 | 上传并逐项核验 | **23:15 完成提交** |
| 7/25 23:15–24:00 | 备用 | 备用 | 平台与网络缓冲 | 截止缓冲 |

### 24.6 三个冻结契约

7 月 23 日 18:00 后只允许向后兼容地增加可选字段：

1. `SourceEnvelope`：来源、设备、来源会话、时间、触发方式、策略版本、Schema 和 Evidence 引用。
2. `AtomicObservation` / `MemoryCandidate`：受约束谓词、实体候选、时间、置信度、解析过程和来源。
3. `FindObjectResponse`：对象、最佳位置、观察时间、置信度、来源事件。

数据库首版只实现 `source_envelopes`、`evidence_items`、`atomic_observations`、`memory_candidates`、`memory_events`、`state_projections` 和必要的 `capture_attempts`。Bundle、Segment 与 Episode 可先以同库 JSON/关系表实现；活动期间不拆微服务，不引入 Kafka，不做通用插件系统。

### 24.7 Go/No-Go 与降级

| 判断时间 | 阻塞条件 | 立即降级 |
|---|---|---|
| 7/23 21:00 | RV101 裸机 Sample 无法拍照 | 再排查 60 分钟；仍失败则使用 CXR-L 或 RV101 手动导出图片，不继续研究后台采集 |
| 7/24 12:00 | 后台/定时拍照不稳定 | 保留可见 Activity 内手动采集，演示会话语义与暂停 |
| 7/24 16:00 | AI 输出不稳定 | 限定三个物品和三个位置，固定单一提示词与 JSON Schema，不增加模型 |
| 7/24 19:00 | 完整事件系统未跑通 | 使用单体服务和四张核心表，不实现异步 Outbox 消费 |
| 7/25 11:00 | 戒指仍未接入主链路 | 从活动 Demo 移除戒指，保留独立能力说明 |
| 7/25 15:00 | 演示 UI 不稳定 | 使用经过验证的内部 Web 页或 Swagger，不继续做视觉优化 |

所有降级都必须保留真实 RV101 输入、真实模型输出和可解释查询这三个价值证明。不得用预写结果冒充实时处理。

### 24.8 提交完成定义

活动提交只有同时满足以下条件才算完成：

- RV101 能在现场或录屏中产生真实图片。
- 同一图片能生成结构化候选、事件和位置投影。
- 找物查询能返回位置、时间和置信度。
- 暂停或结束后不会继续产生采集记录。
- 临时图片可被删除，数据库仍保留结构化记忆。
- 主链路在同一环境连续成功运行 3 次。
- 新机器根据 README 可在 15 分钟内启动后端和演示页。
- APK、源代码、配置模板、演示视频、架构图和三分钟讲稿已进入最终提交包。

完整产品的 WP0–WP9 工作包在活动结束后继续按第 23 节阶段推进；本次产物对应 WP1 的 RV101 PoC，以及 WP0、WP4–WP7 的最小纵向切片。

---

## 25. 测试矩阵

### 25.1 Glass 真机

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
- 2–3 秒短视频上限；验证不存在长视频或连续视频入口。
- 策略在会话中收紧。
- 删除与上传竞态。

### 25.2 戒指

- 扫描、连接、重连。
- 单击、双击、长按和 HMM 手势。
- 录音完成主动上报。
- 缺帧补传。
- 录音模式与手势模式切换。
- 低电量与设备忙。
- 多连接竞争。

### 25.3 后端

- 鉴权和家庭隔离。
- 幂等重放。
- 时钟乱序。
- 证据 TTL。
- 候选冲突。
- AtomicObservation Schema、跨模态 Bundle 和 Episode 边界回放。
- 实体合并/拆分。
- 事件回放和投影确定性。
- 删除全链路。
- Signal 去重和冷却。

### 25.4 端到端

- 佩戴到第一条结构化记忆。
- 对象移动到 Query。
- 主动语音到 Preference/Intent。
- 状态变化到 Signal。
- 用户纠正到投影重算。
- 近窗遗忘到查询不可见和审计完成。

### 25.5 受控评测集

在接入生产模型和家庭试用前，建立 50–100 段经参与者明确同意的短场景样本。每段包含目标任务、结构化标注、设备与光照条件、允许留存范围和删除日期，不将日常无边界采集直接作为训练集。

评测集至少覆盖：

- 同类多实例：两串钥匙、多个充电器、同款衣物。
- 移动与遮挡：拿起、放下、装入抽屉、被其他物品遮挡。
- 密集空间：衣橱、梳妆台、工具箱。
- 光照与视角：逆光、暗光、运动模糊、只出现局部。
- 耗材：开封、明显下降、补充、更换新包装。
- 主动语音：偏好、否定偏好、任务、纠正、删除。
- 隐私：屏幕、证件、访客、禁采空间。
- 系统边界：断网、时钟漂移、重复上传、乱序事件、模型重试。

所有模型和阈值使用同一划分进行离线对比，并在 RV101 真机端到端链路上复测。生产选型以实体准确率、事件准确率、隐私误放行率、延迟和成本的综合结果决定，不以单次演示效果决定。

### 25.6 主要风险与控制

| 风险 | 控制与降级 |
|---|---|
| RV101 后台相机或佩戴广播与文档预期不一致 | Phase 0 真机能力矩阵；使用 Rokid 支持的 Activity/前台服务/白名单路径；CXR-L 仅维持算法测试，最终产品保持阻塞而不降级为有回显采集 |
| 固定频率采集导致续航、温升或无效图片过多 | 采集预算、动态门控、低电/过热停止、服务端策略下发 |
| 同类物品误合并导致找物错误 | 保守 IdentityResolver、tracklet/位置/OCR 多特征、候选分支、用户纠正 |
| 原始媒体泄露或超时未删 | 端侧加密、每证据 DEK、短 TTL、删除 Worker、回执与告警 |
| 禁采策略因定位不确定而失效 | 本地策略优先、识别不确定时取更严格结果、无有效策略 fail closed |
| 断网或重试产生重复事实 | SourceEnvelope 与 API 幂等键、事务 Outbox、消费者去重 |
| 设备时间漂移导致时间线错误 | UTC + 单调时钟偏移、时间区间、服务端校正与乱序重放测试 |
| Agent 把低置信候选表述成事实 | Query 统一返回置信度、备选和来源；Agent 不直接访问 Candidate/Evidence |
| 删除只清理主库但遗漏索引或队列 | 删除编排、逐子系统 job、tombstone、投影重算和端到端删除测试 |
| 厂商 SDK 或型号能力变化 | Device Adapter 隔离、版本化 `DeviceCapabilityProfile`、契约测试 |

---

## 26. 默认配置

以下作为首个开发版本的可配置默认值：

| 配置 | 默认值 |
|---|---|
| 佩戴倒计时 | 5 秒 |
| PoC 截图间隔 | 30 秒，测试 5/15/30/60 秒 |
| 单次图片大小上限 | 3 MB |
| 单次短视频 | 2–3 秒 |
| 自动 VAD 音频片段上限 | 15 秒 |
| 显式主动语音上限 | 30 秒 |
| 正式本地证据 TTL | 最长 10 分钟 |
| 正式云端证据 TTL | 最长 15 分钟 |
| 测试调试证据 TTL | 最长 24 小时，本地加密 |
| 断连安全结束超时 | 30 秒 |
| 策略刷新 | 会话开始、每 5 分钟、收到 push 时 |
| 低库存提醒冷却 | 24 小时 |
| 找物候选自动接受阈值 | 初始 0.85，按评测校准 |
| 低置信候选过期 | 7 天 |

设备测试可以调整这些数值，变更必须写入策略版本和实验记录。

---

## 27. 开发完成定义

一个工作包达到 Done 需要：

- 代码、schema 与接口文档完成。
- 单元测试和 Contract Test 通过。
- 关键错误有明确错误码。
- 隐私、审计和删除路径有测试。
- 指标可观测。
- 真机相关功能提供设备型号、固件和复现步骤。
- 所有临时证据符合 TTL。
- 对下游的依赖和版本已固定。

---

## 28. 需要通过实验固化的参数

这些参数已有产品方向，最终数值由 Phase 0–2 数据固化：

1. Rokid 后台相机在目标固件上的合法运行生命周期。
2. 佩戴广播在应用未启动、熄屏和进程回收情况下的可靠性。
3. 截图 5/15/30/60 秒档的耗电、温升、失败率与记忆收益。
4. 眼镜 Runtime 到统一手机 App 的本地传输、手机加密队列与 CXR-L 过渡 Adapter 的稳定性。
5. CXR-L 音频编码、声道、VAD 阈值、预滚、静音结束窗和误触发率。
6. 戒指手势映射、误触率和模式切换体验。
7. 找物、耗材和偏好的自动接受阈值。
8. 本地敏感内容检测的性能与安全降级策略。

这些实验不会改变中台本体与事实链，只决定首个设备适配和策略默认值。

---

## 29. 研发启动顺序

开发 Agent 拿到本文档后，按以下顺序启动：

1. 下载并跑通 Rokid `GlassesBareDevSample`。
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

## 30. 参考资料

### Rokid 官方

- [Rokid 开放平台](https://open.rokid.com/?lang=cn)
- [Rokid 官方安全支持型号列表（Rokid Glasses / RV101）](https://global.rokid.com/pages/security-center-1)
- [Rokid SDK 列表](https://open.rokid.com/sdk?lang=cn)
- [Rokid Glasses 眼镜端裸机开发 v1.0.0](https://custom.rokid.com/prod/rokid_web/ff28c865a9634876be98cbc293588460/pc/cn/index.html)
- [CXR-L SDK v1.0.4](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/cn/3b63d21420e645e3affca478b39e4a13.html)

### Android 官方

- [CameraX 拍照](https://developer.android.com/media/camera/camerax/take-photo)
- [Android 12 后台启动前台服务限制](https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start)
- [前台服务类型与相机权限](https://developer.android.com/develop/background-work/services/fgs/service-types)

### 跨设备、观察与溯源

- [CloudEvents Specification](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md)
- [W3C Semantic Sensor Network Ontology / SOSA](https://www.w3.org/TR/vocab-ssn-2023/)
- [W3C PROV-O](https://www.w3.org/TR/prov-o/)
- [W3C Web of Things Thing Description 1.1](https://www.w3.org/TR/wot-thing-description11/)
- [OGC SensorThings API](https://www.ogc.org/standards/sensorthings/)

### 第一视角与时序理解

- [Ego4D: Around the World in 3,000 Hours of Egocentric Video](https://arxiv.org/abs/2110.07058)
- [The EPIC-KITCHENS Dataset](https://arxiv.org/abs/2005.00343)
- [Predictive Event Segmentation and Representation](https://arxiv.org/abs/2210.05710)
- [Cognitive Architectures for Language Agents](https://arxiv.org/abs/2309.02427)

### 项目内戒指资料

- `/Users/bytedance/Desktop/real git/hardware/ring-sound-sdk/README.md`
- `/Users/bytedance/Desktop/real git/hardware/ring-sound-sdk/ring_sound_use.md`
- `/Users/bytedance/Desktop/real git/hardware/ring-sound-sdk/protocol.md`
- `/Users/bytedance/Desktop/real git/hardware/ring-sound-sdk/ring_sound.py`

---

## 31. 最终产品形态

Reality Memory Engine 的最终形态由三部分组成：

1. **Reality Mobile Gateway**：唯一用户手机 App，承载账号、设备 Adapter、统一 Session、策略、加密队列、上传、管理与提醒；眼镜和未来硬件只运行必要的设备侧 Runtime。
2. **Perception & Memory Platform**：用可替换的模态解析器将多源证据转化为原子观察、活动 Episode、实体事件、当前状态和可检索记忆。
3. **Agent Interface**：让个人 Agent、家庭设备和未来机器人在权限范围内查询记忆、订阅信号，并在当前阶段生成受控提醒。

当前 CXR-L 是统一手机 App 内的过渡 Adapter，Rokid 原生 Glass Runtime 是首个最终设备侧实现。两者输出同一 Source Contract，并由同一手机账号、策略、队列和上传链路承接；后续硬件只增加 Adapter、Local Transport 和必要的能力描述，不重建手机 App、感知、记忆或提醒流水线。产品先通过真机图片与短音频 PoC 证明设备能力和信任链，再逐步接入结构化观察、记忆主线和提醒服务，最终形成可被多硬件复用的现实世界记忆基础设施。
