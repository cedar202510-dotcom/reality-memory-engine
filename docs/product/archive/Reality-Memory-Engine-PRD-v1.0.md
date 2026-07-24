# Reality Memory Engine（现实记忆引擎）PRD

> 文档版本：v1.0  
> 日期：2026-07-23  
> 项目阶段：产品与技术方案冻结，进入硬件采集 PoC  
> 目标读者：产品、Glass/Android、手机端、后端、AI/算法、数据、安全、测试工程师，以及后续接入 Memory API 的 Agent 开发者

---

## 1. 产品摘要

Reality Memory Engine 是面向智能硬件和个人 Agent 的现实世界记忆中台。系统通过 AI 眼镜、智能戒指、手机及未来其他智能硬件采集现实世界中的短时证据，将其理解为结构化的对象、地点、事件和状态变化，沉淀为可查询、可纠正、可删除、可审计的长期记忆，并通过内部 API 向 Agent 提供找物、状态时间线、低库存信号和偏好/意图等能力。

系统首个落地场景是家庭。眼镜提供第一视角视觉与交互入口，戒指提供低摩擦的主动语音、手势和控制信号，手机提供设备连接、策略设置和记忆审计，云端完成证据处理、候选生成、实体归一、事件沉淀、状态投影和查询服务。

长期产品结构为：

```text
多硬件输入
  → 采集策略与隐私控制
  → 短时证据处理
  → 观察候选
  → 结构化记忆事件
  → 当前状态与时间线
  → Memory API / Signal API
  → 个人 Agent 与智能硬件调用
```

研发从两个最小硬件验证开始：

1. 在真实 Rokid 眼镜上验证 Glass App 的定时截图、佩戴会话、暂停、清理、功耗和后台运行能力；该阶段不接 AI，不上传图片。
2. 使用项目内 Ring Sound SDK 验证戒指连接、按键/手势、主动录音、IMU 数据和标准化 DeviceEvent 输出；明确录音模式与手势/IMU 模式的实际边界。

硬件采集验证通过后，再接入 `Evidence → ObservationCandidate → MemoryEvent → StateProjection` 的完整记忆链路。

---

## 2. 背景与问题

现有个人 AI 能够获得聊天、文档、网页、日程、消费记录等线上上下文，但很少拥有对现实世界的连续理解。物品被放到哪里、耗材如何减少、一次购买或使用如何发生、用户表达过什么偏好、某件现实任务处于什么状态，通常没有形成可供 AI 使用的长期数据。

智能眼镜、戒指、手机、机器人和家庭设备已经能够提供图像、短视频、音频、动作与设备信号。项目要解决的问题不是简单保存这些媒体，而是将不同设备的输入统一转化为可靠的现实状态变化，并持续维护：

- 现实中有哪些值得记忆的对象、地点和语义信息；
- 这些对象的状态在什么时候发生了什么变化；
- 哪些识别结果只是候选，哪些可以作为当前可信状态；
- 复杂场景如何通过日常交互渐进建立记忆；
- 用户如何知道系统何时工作，并能暂停、更正和遗忘；
- Agent 如何在授权范围内查询或订阅这些记忆。

“现实世界的 Git”是系统的数据组织方式：每个对象拥有可追溯的状态主线；低置信或互相冲突的解释暂存在候选/冲突分支；确认、纠错和删除通过追加事件完成；当前状态由事件流重算，而不是直接覆盖历史。

---

## 3. 产品目标

### 3.1 长期目标

1. 建立一套与具体硬件和模型解耦的现实记忆数据模型。
2. 支持图像、短视频、主动音频、手势、IMU 摘要和结构化设备事件统一接入。
3. 将现实状态沉淀为对象主线、地点快照、事件时间线和当前状态投影。
4. 让结构化记忆能够被用户查询、纠正、删除和审计。
5. 通过 Memory API 与 Signal API 为个人 Agent、智能硬件和未来机器人提供现实上下文。
6. 在家庭真实使用中形成可持续提高的记忆质量：对象身份更稳定、错误事实更少、采集成本更低、用户干扰更少。

### 3.2 第一阶段目标

第一阶段验证“家庭可信现实记忆”的最小闭环：

- 找物：回答“钥匙/遥控器上次在哪里”；
- 耗材：记录洗衣液、纸巾等剩余状态变化并生成低库存建议；
- 主动语义记忆：将“这家外卖很好吃”“提醒我拿快递”等主动语音转为偏好或意图；
- 隐私闭环：佩戴提示、暂停、全局关闭、删除近期记忆、查看审计；
- 端到端数据链：采集、处理、候选、事件、投影、查询和删除均可验证。

### 3.3 产品边界

MVP 聚焦单一用户或单一 Owner 家庭域，位置以家庭内的语义层级表达，Agent 通过内部 API 使用结构化记忆。第三方开放、多 Agent 编排、自动下单、完整家庭三维建模、旁人生物识别和健康/情绪推断在后续独立阶段评审。

长期记忆由结构化事件和状态投影构成。原始图片、短视频与音频仅在处理和短时交叉验证窗口内存在，不向用户提供媒体回看能力，也不向 Agent 暴露。

---

## 4. 用户、使用环境与核心场景

### 4.1 目标用户

- 首批用户：愿意在家庭环境试用智能眼镜与戒指，希望减少找物、断货和遗忘的人。
- 后续用户：已经拥有 AI 眼镜、可穿戴设备、家庭机器人或个人 Agent 的用户。
- 平台客户：希望为硬件或 Agent 增加现实记忆能力的设备与软件开发者。

### 4.2 使用环境

| 环境 | 产品行为 |
|---|---|
| 家庭授权空间 | 佩戴会话默认进入可工作状态；按策略进行定时或事件触发采集 |
| 用户设置的禁采空间 | 设备端在调用相机/麦克风前阻断采集 |
| 工作环境 | 默认关闭视觉与环境音频，仅保留用户主动触发的个人备忘 |
| 外出环境 | 使用弱运行策略，主要响应“记一下”、主动拍照和主动语音 |
| 暂停状态 | 设备立即停止采集并清空待上传媒体队列，控制事件仍可处理 |

### 4.3 场景优先级

| 优先级 | 场景 | 输入 | 结构化输出 | 用户结果 |
|---|---|---|---|---|
| P0 | 找物 | 眼镜图片、显式“记一下”、语义位置 | Object、Place、moved/observed 事件、location 投影 | 返回最近可信位置与观察时间 |
| P0 | 耗材状态 | 多次图片、用户确认 | remaining_ratio、quantity、consumed 事件 | 低库存建议 |
| P0 | 主动偏好/任务 | 戒指长按主动录音或眼镜主动语音 | preference、intent_task 事件 | 可查询、可更正的偏好/待办 |
| P0 | 隐私与审计 | 眼镜/戒指/手机控制 | PolicySnapshot、删除任务、审计记录 | 暂停、遗忘、查看系统记住了什么 |
| P1 | 阅读进度 | 阅读会话内低频图片 | progress 事件 | 返回大致页码或章节 |
| P1 | 场景回忆 | 对象与地点事件积累 | Timeline | 回答某件事何时发生 |
| P2 | 衣橱/梳妆台渐进建库 | 日常拿取、使用、购买、穿戴 | PlaceSnapshot、ObjectCandidate、ObjectMainline | 随使用逐渐形成物品清单 |

### 4.4 关键用户故事

1. 用户戴上眼镜，听到一次轻提示：“5 秒后开启现实记录，可关闭。”用户未关闭，系统进入当次佩戴会话的后台可工作状态。
2. 用户把钥匙从玄关放到茶几。系统在合规采集和识别后，将“钥匙的位置变为客厅茶几”写入对象时间线。
3. 用户之后询问“钥匙在哪”，Agent 查询 `where-is`，返回“最近一次在客厅茶几看到，时间为 20:15，置信度高”。
4. 系统多次观察洗衣液余量下降，候选经多次一致观测合并后更新状态，并产生低库存建议。
5. 用户长按戒指说“这家外卖很好吃”。手机或眼镜网关接收音频，云端转写并形成对商家的正向偏好。
6. 用户进入暂停状态后，设备不再产生媒体；用户删除最近 10 分钟记忆后，相关证据、候选、事件、投影、搜索索引和缓存均不可再查询。

---

## 5. 产品与系统总体结构

### 5.1 端到端架构

```text
┌──────────────────────── 设备与客户端 ────────────────────────┐
│ Rokid Glass App       Ring BLE Gateway       手机管理端      │
│ 相机/短视频/提示       手势/录音/IMU          模式/审计/提醒   │
└───────────────┬──────────────┬─────────────────┬─────────────┘
                ▼              ▼                 ▼
       Device Adapter + Local Policy Engine + Encrypted Queue
                │
                ▼
       Ingest Gateway / Session & Policy Service
                │
                ▼
       Short-lived Evidence Vault
                │
                ▼
    Quality/Dedupe/Privacy Gate → Vision/ASR Extractor
                │
                ▼
          ObservationCandidate
                │
                ▼
   Entity Resolution + Place Resolution + Conflict Resolver
                │
                ▼
      Append-only Memory Event Store + Outbox
                │
           ┌────┴──────────┐
           ▼               ▼
   State Projection   Search / Vector Index
           └────┬──────────┘
                ▼
 Query / Timeline / Signal / Privacy / Audit API
                │
                ▼
       眼镜 Agent / 手机 Agent / 未来第三方 Agent
```

### 5.2 系统模块

| 模块 | 核心职责 | 主要输出 |
|---|---|---|
| Glass App | 管理佩戴会话、显示轻提示、执行策略、定时/显式采集、安全清理、上报元数据或短时证据 | CaptureAttempt、Evidence |
| Ring Adapter/Gateway | BLE 连接、录音接收、手势/按键/IMU 解析、标准化设备事件 | DeviceEvent、AudioEvidence |
| 手机管理端 | 设备配对、运行模式、禁采规则、全局关闭、审计、删除、更正、提醒 | Policy、UserAction |
| Session & Policy Service | 维护佩戴会话和签名策略快照，处理暂停与撤销 | Session、PolicySnapshot |
| Ingest Gateway | 鉴权、幂等、限流、策略校验、证据登记 | SourceEvent、Evidence metadata |
| Perception Pipeline | 质量/重复过滤、风险预处理、视觉/音频理解 | ObservationCandidate |
| Memory Core | 实体解析、状态维度校验、候选融合、冲突处理、事件追加 | MemoryEvent |
| Projection & Search | 计算当前状态、时间线、语义搜索、低库存检测 | StateProjection、Signal |
| Privacy & Audit | 全链路删除、审计、策略追踪、数据用途控制 | DeletionJob、AuditRecord |
| Agent Access | 结构化查询、订阅和授权控制 | QueryResult、Signal delivery |

### 5.3 唯一事实源

- `MemoryEvent` 的 append-only 事件流是系统事实源。
- `StateProjection`、搜索索引、向量索引和缓存都可以从事件流重建。
- 模型输出只能形成 `ObservationCandidate`，不能直接覆盖当前状态。
- Agent 的自然语言答案必须可回溯到事件或投影，不以向量召回结果直接作为事实。
- 每个 Object 与 Place 使用独立 stream；事件追加与投影更新使用 transactional outbox，支持幂等重放。

### 5.4 MVP 部署形态

上文模块是逻辑边界。MVP 使用模块化单体，避免在数据量和团队规模尚未验证前拆成大量微服务：

```text
Backend API Process
  session / policy / ingest / query / privacy / audit

Async Worker Process
  evidence preprocessing / perception / candidate fusion
  memory event / projection / deletion

Infrastructure
  PostgreSQL + object storage + queue/Redis
```

设备端为一个 Glass App 和一个 Android 手机伴侣端；Ring Gateway 首先在 Python 工具中验证，再进入手机伴侣端。每个逻辑模块拥有独立 package、schema 和接口，达到容量或团队协作边界后再拆服务。

---

## 6. 客户端形态与设备职责

### 6.1 Rokid Glass App

项目需要一个运行在目标 Rokid Glasses/Glass3 上的眼镜端应用或服务。它不是完整消费级 App，而是设备采集、会话与隐私控制的执行端。

Rokid 官方 Glass3 SDK 当前支持眼镜端 Android 应用，并将眼镜端 SDK 与手机端 SDK 分开：眼镜端负责硬件能力、媒体采集、消息与文件；手机端负责设备连接、蓝牙/P2P、媒体接收和配置。官方示例提供 `takePhoto`、`startRecord`、`stopRecord`、`startAudioRecord`、`stopAudioRecord`、视频流和消息/文件能力。

Glass App 的职责：

1. 初始化厂商 SDK，注册独立 `clientId`。
2. 获取并缓存签名的采集策略。
3. 管理一次佩戴会话的状态机。
4. 在相机或麦克风调用前执行本地 PolicyCheck。
5. 执行固定间隔或显式触发的拍照，后续支持受控短视频。
6. 对本地媒体进行加密、短队列管理、过期清理和删除回执。
7. 将控制消息、采集元数据和媒体通过合适通道交给手机或云端。
8. 展示低干扰的记录状态、暂停和错误反馈。
9. 记录电量、温升、耗时、失败码和网络用量。

设备适配器接口：

```text
startWearSession(trigger, policySnapshot)
capturePhoto(captureReason, policySnapshot)
captureClip(maxSeconds, captureReason, policySnapshot)
captureVoice(maxSeconds, explicitIntent, policySnapshot)
pauseSession(reason)
resumeSession()
endWearSession(reason)
getDeviceState()
purgeLocalEvidence(timeRange)
```

厂商 SDK 只存在于 `RokidGlassAdapter` 内，Memory Core 不直接依赖 Rokid API，以便未来接入其他眼镜。

### 6.2 手机伴侣端

手机端是连接、配置和信任管理入口，首版至少提供：

- 账号与家庭域；
- Rokid 眼镜配对、P2P/文件通道状态；
- Ring BLE Gateway；
- 家庭、工作、外出、暂停模式；
- 禁采空间、禁采时段和全局关闭；
- 最近的结构化记忆及其来源设备；
- 暂停、恢复、遗忘最近 N 分钟、单条删除和更正；
- 低库存建议与 Agent 调用授权；
- 内部调试页：连接、策略版本、采集结果和清理状态。

### 6.3 戒指与 Ring BLE Gateway

项目内 Ring Sound SDK 的基线为 Python SDK 0.3.4、语音戒指 v4 协议，通过 Nordic UART Service 连接。现有能力包括：

| 能力 | 当前事实 | 产品用途 |
|---|---|---|
| 按键双击 `0x0703` | 独立按键事件，不触发单击切换 | “记一下”、确认候选、请求眼镜拍照 |
| 主动录音 | 长按录音，16 kHz、单声道、16 bit、Speex Wideband Q3，结束后主动分帧上报 | 用户主动表达偏好、任务、纠错 |
| IMU `0x0605` | 手势模式下批量上报六轴，采样率以 `0x0602` 返回为准 | 短会话动作研究、手势特征、活动摘要 |
| HMM 手势 `0x0702` | 手势模式下设备端识别 | 二级确认/否定交互 |
| 普通双击 `0x0701` | 手势模式事件 | 可配置控制 |
| 模式切换 | 录音模式与手势/IMU 模式互斥，SDK 不能可靠查询或主动设置模式 | 作为硬件限制进入状态机与测试 |

首版不把戒指作为全天持续运动门控器。Ring Adapter 先将原始协议统一为：

```json
{
  "device_event_id": "devt_...",
  "device_id": "ring_001",
  "event_type": "key_double_press|voice_completed|gesture|imu_window|battery",
  "occurred_at": "2026-07-23T20:15:00+08:00",
  "sequence": 123,
  "payload": {},
  "firmware_version": "V2.000.0001.0015"
}
```

正式移动端接入可选择：

1. 按 NUS/v4 协议在 Android 侧实现受测 BLE Client；
2. 使用供应商提供的 Android SDK；
3. Python SDK 保留为实验、数据采样和协议回归工具。

### 6.4 未来设备

摄像头、机器人、手机传感器和智能家居通过 Device Adapter 接入。所有设备最终只向中台提交 `SourceEvent`、`Evidence` 或已经结构化的 `ObservationCandidate`，不直接修改对象状态。

### 6.5 眼镜、手机与服务端的数据通道

首版采用“眼镜采集、手机中继、云端处理”的主链路：

```text
控制与状态：
手机 Backend Client
  ⇄ Bluetooth/P2P message
Rokid Glass App

媒体：
Rokid Glass App
  → 本地加密临时文件
  → Rokid P2P/file channel
  → 手机伴侣端
  → Ingest Gateway / pre-signed upload
  → Evidence Vault

戒指：
Ring
  → BLE NUS
  → 手机 Ring Gateway
  → DeviceEvent / AudioEvidence
  → Ingest Gateway
```

选择原则：

- 蓝牙用于控制、小消息和状态同步；
- 图片、音频和短视频使用 P2P/Wi-Fi 文件通道；
- P0 只上报采集元数据，不传媒体；
- P1 由手机向服务端请求 `evidence/init`，得到短时上传地址与加密参数，完成上传后调用 `evidence/complete`；
- 目标眼镜若经真机证明能够稳定、合规地直连云端，可复用同一 Ingest 协议直接上传；手机中继仍作为默认兼容路径；
- Glass App 和手机都维护有限、加密、可见的离线队列。队列超出字节上限、时间上限或策略失效时删除媒体，不无限重试。

一次 P1 图片写入的完整时序：

```text
1. Glass App 读取有效 PolicySnapshot
2. 本地 PolicyCheck 通过
3. 调用 takePhoto，生成 capture_id
4. 图片写入本地加密临时文件
5. 通过 P2P 传到手机
6. 手机请求 POST /internal/v1/evidence/init
7. 服务端再次校验 session、policy、预算与幂等键
8. 手机上传密文并调用 evidence/complete
9. 服务端进入异步处理队列
10. 手机与眼镜清理本地文件并上报 deletion receipt
11. Worker 生成候选、事件与投影
12. Evidence 到达融合完成或 expires_at 后销毁
```

---

## 7. 佩戴会话、运行模式与采集策略

### 7.1 佩戴会话状态机

```text
ENDED
  → WEAR_DETECTED
  → COUNTDOWN_5S
      ├─ 用户关闭 / 权限缺失 / 策略拒绝
      │    → DISABLED_FOR_THIS_WEAR
      └─ 5 秒内无关闭
           → ACTIVE

ACTIVE
  ├─ 触发采集 → POLICY_CHECK → CAPTURED / BLOCKED / FAILED
  ├─ 用户暂停 → PAUSED
  ├─ 策略收紧 → PAUSED_BY_POLICY
  └─ 摘下 / 连接丢失 / 手动结束
       → ENDING → secure cleanup → ENDED

PAUSED
  ├─ 用户恢复且策略允许 → ACTIVE
  └─ 摘下 → ENDING → ENDED
```

产品行为：

- 每次检测到佩戴后只轻提示一次：“5 秒后开启现实记录，可关闭。”
- 未关闭则第 5 秒进入当次佩戴会话的后台可工作状态。
- 会话中不重复弹出开启确认；保留低干扰状态指示和随时暂停入口。
- “本次关闭”只影响当前佩戴；“暂停”可在当前会话恢复；“全局关闭”持久生效。
- 摘下结束会话；下次佩戴重新提示。
- 若目标机型无法可靠提供佩戴/摘下事件，PoC 使用“手动开始/结束 + 连接断开保护”，并在能力矩阵中记录。

“后台持续”表示服务持续处于可工作状态，不等于连续录像、持续录音或逐帧上传。

### 7.2 采集决策

```text
L0 Policy Gate
  运行模式、空间、授权、暂停、设备权限、访客、预算
        ↓
L1 Low-cost Gate
  显式意图、固定间隔、冷却时间、质量、模糊、曝光、重复、场景变化
        ↓
L2 Capture
  单图优先；前后状态需要时使用短视频；音频仅由用户主动触发
        ↓
L3 Cloud Understanding
  候选生成、去重、对象归一、跨观测融合
```

### 7.3 媒介选择

| 场景/信号 | 采集形式 | 首版策略 |
|---|---|---|
| 戒指双击“记一下” | 单图，可关联主动语音 | 立即触发，优先级最高 |
| 家庭佩戴会话 | 固定间隔单图 | 先通过 PoC 选取安全档位，后续升级为动态频率 |
| 拿起—放下、开合、倒出 | 前后两帧或 2–3 秒短视频 | 单图无法判定时才使用 |
| 阅读 | 低频单图 | 在阅读模式中每 3–5 分钟作为初始实验值 |
| 偏好、任务、纠错 | 主动短音频 | 单段建议不超过 30 秒 |
| 密集梳妆台/衣橱 | PlaceSnapshot + 被互动对象候选 | 通过使用过程渐进建库 |
| 戒指 IMU | 端侧/网关聚合后的窗口特征 | 输出 activity/gesture 摘要，默认不上传全天原始轴 |

### 7.4 动态频率的后续演进

固定间隔只用于采集能力验证和建立基线。AI 链路上线后，采集频率由以下信号联合决定：

- 用户显式触发；
- 佩戴/空间变化；
- 戒指或设备给出的活动窗口；
- 图像变化与重复度；
- 当前任务，例如阅读、整理、做饭；
- 设备电量、温升、网络和每日预算；
- 最近一段时间是否已经产生有效记忆。

策略服务下发 `min_interval`、`max_interval`、`daily_capture_budget`、`heavy_model_budget` 和降级方式。预算用尽时回到仅显式触发。

---

## 8. 现实记忆数据模型

### 8.1 一条现实记忆的定义

一条现实记忆是在一个时间点或时间窗内，系统基于设备或用户输入，对某个现实或语义实体的状态、变化或关系形成的结构化断言。它至少包含：

- 实体及其稳定身份；
- 状态维度与值；
- 观察时间和事件时间；
- 来源设备与采集原因；
- 置信度与归因；
- 当时的策略快照；
- 候选、主线、冲突或删除状态；
- 可用于重算、纠错和审计的版本信息。

### 8.2 核心对象

| 对象 | 定义 |
|---|---|
| `Household` | Owner 的家庭授权域与数据隔离边界 |
| `Actor` | 用户、家庭成员、设备或 Agent |
| `Entity` | 可被记忆指向的现实或语义实体基类 |
| `Object` | 钥匙、花瓶、洗衣液、书、衣物、设备等物理实体 |
| `Place` | 家庭内的层级语义位置 |
| `SourceEvent` | 设备产生的原始控制或采集事件 |
| `Evidence` | 短时图片、短视频、主动音频或传感摘要 |
| `ObservationCandidate` | 模型或规则从证据中提取的候选断言 |
| `MemoryEvent` | 通过策略、实体解析、去重与冲突处理后的不可变事件 |
| `StateDimension` | 实体可以发生变化的状态轴 |
| `StateProjection` | 从事件流计算出的当前最佳状态 |
| `PlaceSnapshot` | 对密集空间的 L1 整体摘要 |
| `PolicySnapshot` | 采集、处理、留存和调用时的权限快照 |
| `Signal` | low_stock、object_moved、intent_detected、conflict 等主动信号 |
| `DeletionTombstone` | 仅证明删除发生过、不包含被删内容的审计记录 |

### 8.3 Object 分类

分类决定默认可用的状态轴和校验规则，但不会为每类物品建立完全独立的数据模型。

| Object class | 例子 | 常用状态维度 |
|---|---|---|
| `durable_singleton` | 钥匙、花瓶、遥控器 | location、containment、integrity、availability |
| `consumable` | 洗衣液、纸巾、护肤品 | location、quantity、remaining_ratio、lifecycle |
| `collection` | 一套餐具、一组工具 | membership、count、location_summary |
| `container` | 抽屉、衣橱、收纳盒 | contents_summary、openness、capacity |
| `wearable` | 衣物、鞋、配饰 | ownership、worn_by、cleanliness、location |
| `document_media` | 书、文件、票据 | location、progress、status |
| `appliance` | 家电、电子设备 | power_state、availability、maintenance_state |
| `semantic_memory` | 偏好、意图、任务 | preference、intent_task、status |

### 8.4 StateDimension

| 维度 | 值类型 | 示例 |
|---|---|---|
| `location` | PlaceRef + spatial_hint | 钥匙在客厅茶几右侧 |
| `containment` | parent/container relation | 药在卧室抽屉内 |
| `quantity` | number + unit + estimated | 还有 3 包纸巾 |
| `remaining_ratio` | 0–1 range | 洗衣液约 10%–20% |
| `lifecycle` | enum | acquired、opened、expired、discarded |
| `integrity` | enum + detail | 花瓶完整、破损 |
| `openness` | enum | 柜门打开、盒子关闭 |
| `availability` | enum | 可用、缺失、不可用 |
| `cleanliness` | enum | 已洗、待洗 |
| `usage_activity` | event enum | 拿起、放下、使用、穿戴 |
| `progress` | numeric/text anchor | 书看到约第 126 页 |
| `membership` | set relation | 衬衫属于衣橱集合 |
| `preference` | polarity + target + reason | 对某商家正向偏好 |
| `intent_task` | intent + status + due hint | 提醒拿快递 |
| `physio_behavior_signal` | time-window summary | 活动强度较高 |

每个 Entity 只启用适用状态轴。例如花瓶主要使用位置与完整性；洗衣液使用位置、开封与剩余比例；书使用位置与阅读进度。

### 8.5 EventType

首版事件类型：

```text
observed
acquired
moved
placed_in
removed_from
used
consumed
quantity_estimated
opened
closed
damaged
repaired
worn
cleaned
progress_observed
preference_stated
intent_stated
confirmed
corrected
merged
forgotten
redacted
```

### 8.6 四层数据链

```text
SourceEvent
  设备控制、拍照、录音、IMU 窗口、手势
    ↓
Evidence
  短时媒体或传感摘要
    ↓
ObservationCandidate
  对象、地点、状态、变化、置信度、模型版本
    ↓
MemoryEvent
  经策略、实体解析、去重、融合和冲突处理后的事件
    ↓
StateProjection / Timeline / Signal
  当前状态、历史时间线、主动信号
```

硬件与模型模块的交付边界是 `ObservationCandidate`；只有 Memory Core 可以追加 `MemoryEvent`。

### 8.7 主线、候选与冲突

| 状态 | 说明 | 可否驱动 Agent 主动提醒 |
|---|---|---|
| `candidate` | 一次或多次尚未满足合并门槛的观察 | 否 |
| `mainline` | 当前系统接受的可信事件主线 | 是 |
| `conflict` | 与主线或其他候选互斥的解释 | 否 |
| `redacted` | 已删除，仅有无内容 tombstone | 否 |

合并规则：

1. 用户主动确认或纠正的优先级最高。
2. 已知非敏感实体、高置信、无冲突的候选可以自动合入。
3. 多次独立观测对同一对象、名称或状态保持一致时，提高融合置信度。
4. 同一对象在同一有效时间段的互斥位置不能同时进入主线。
5. 低置信候选可以用于搜索召回，但不产生低库存等主动打扰。
6. 纠错通过追加 `corrected` 事件并重算投影完成。

对于“第一次把护肤品名称识别错、后面多次识别正确”的情况：

```text
首次候选 A（中置信）
  + 后续候选 B、B（同一对象身份，名称一致）
  → Identity Resolver 形成更高置信的 B
  → A 被标记 superseded
  → 合入 mainline 的是 B
```

### 8.8 时间模型

每条事件保留：

| 字段 | 含义 |
|---|---|
| `observed_at` | 设备实际观察时间 |
| `event_time.from/to` | 推断现实变化发生的时间区间 |
| `ingested_at` | 服务端接收时间 |
| `valid_from/valid_to` | 状态断言的预计有效区间 |
| `monotonic_offset` | 设备会话内单调时间，用于处理时钟漂移 |

### 8.9 Place 模型

MVP 使用语义层级：

```text
家庭
  → 房间
    → 家具/区域
      → 容器/层
        → spatial_hint
```

示例：`家 → 阳台 → 阳台柜 → 左下层 → 靠右侧`。

未来设备若提供可靠的相机内参、同步 IMU、6DoF、anchor 和重定位能力，可在 Observation 中增加可选 `SpatialContext`；语义 Place 始终保留为面向用户和 Agent 的稳定表达。

### 8.10 复杂空间的渐进模型

衣橱、梳妆台、杂物柜等采用三层记录：

| 层级 | 内容 | 升级条件 |
|---|---|---|
| L1 `PlaceSnapshot` | 整体摘要、类别、拥挤度、显著变化 | 低频或显式观察 |
| L2 `ObjectCandidate` | 单次可见但身份尚不稳定的对象 | 多次出现、被提及、被拿起或使用 |
| L3 `ObjectMainline` | 有稳定身份与时间线的对象 | 用户确认或多次一致观测 |

购买、拆封、拿取、使用、穿戴、放下和口头说出名称都是强升级信号。系统通过日常变化逐渐了解衣物和护肤品，而不是依赖一次远景识别全部 SKU。

### 8.11 示例结构

`ObservationCandidate`：

```json
{
  "candidate_id": "obs_01",
  "household_id": "hh_01",
  "source": {
    "device_id": "glass_01",
    "modality": "image",
    "source_event_id": "src_01",
    "captured_at": "2026-07-23T20:15:00+08:00"
  },
  "policy_snapshot_id": "pol_08",
  "evidence": {
    "evidence_id": "ev_01",
    "expires_at": "2026-07-24T20:15:00+08:00",
    "retention_state": "processing_window"
  },
  "claims": [
    {
      "entity_hint": {
        "name": "洗衣液",
        "class": "consumable"
      },
      "state_dimension": "remaining_ratio",
      "value": {
        "range": [0.10, 0.25]
      },
      "place_hint": "阳台柜左下层",
      "confidence": 0.81
    }
  ],
  "model": {
    "name": "vision_extractor",
    "version": "v1",
    "prompt_version": "p3"
  },
  "status": "pending"
}
```

`MemoryEvent`：

```json
{
  "event_id": "evt_01",
  "stream_id": "object:laundry_detergent_01",
  "branch_id": "mainline",
  "event_type": "quantity_estimated",
  "entity_id": "laundry_detergent_01",
  "observed_at": "2026-07-23T20:15:00+08:00",
  "event_time": {
    "from": "2026-07-23T20:10:00+08:00",
    "to": "2026-07-23T20:15:00+08:00"
  },
  "claims": [
    {
      "dimension": "remaining_ratio",
      "op": "set_estimate",
      "value": {
        "range": [0.10, 0.25]
      }
    },
    {
      "dimension": "location",
      "op": "set",
      "value": {
        "place_id": "balcony_cabinet_lower_left"
      }
    }
  ],
  "confidence": 0.86,
  "derived_from": ["obs_01", "obs_02", "obs_03"],
  "policy_snapshot_id": "pol_08",
  "schema_version": 1
}
```

---

## 9. 数据存储与生命周期

### 9.1 存储分层

| 数据 | 存储位置 | 生命周期 | 是否为事实源 |
|---|---|---|---|
| 设备本地媒体 | Glass/Ring 加密短队列 | 上传成功、处理完成或过期后删除 | 否 |
| 原始 Evidence | 加密对象存储 Evidence Vault | 短处理与交叉验证窗口，默认上限建议 24 小时，可配置 | 否 |
| SourceEvent / CaptureAttempt | PostgreSQL | 按审计策略保留，不含媒体内容 | 否 |
| ObservationCandidate | PostgreSQL JSONB | 候选融合、纠错和评测需要；受删除策略控制 | 否 |
| MemoryEvent | PostgreSQL append-only 表 | 长期，直至用户删除 | 是 |
| StateProjection | PostgreSQL | 可重算 | 否 |
| 搜索向量 | pgvector 或等价索引 | 随事件删除和重建 | 否 |
| 缓存/任务 | Redis 或队列 | 短时 | 否 |
| Audit / Tombstone | PostgreSQL | 保留不含被删内容的操作证明 | 否 |

### 9.2 原始证据策略

1. PoC 阶段图片不上传云端，设备端验证后立即删除。
2. AI 阶段 Evidence 进入独立加密对象存储，使用 per-evidence DEK。
3. 默认最大处理窗口建议为 24 小时；实际值由安全评审和试验确定，并通过策略服务配置。
4. 候选提前完成融合时，可在短缓冲期后提前删除证据；到达 `expires_at` 必须删除。
5. Evidence 只供系统处理和授权调试，不提供用户相册或 Agent 回看。
6. 跨天纠错依赖已保存的结构化候选、模型版本、对象身份特征和后续观测，不依赖长期保留原图。
7. 删除证据时同时更新 `retention_state`、撤销密钥并写清理回执。

### 9.3 PostgreSQL 最小表

```text
households
actors
devices
wear_sessions
capture_attempts
source_events
entities
entity_aliases
places
evidence
observation_candidates
candidate_links
memory_events
state_projections
policy_snapshots
signals
agent_grants
deletion_jobs
deletion_tombstones
audit_records
outbox_events
```

关键约束：

- `capture_id`、`device_event_id`、`candidate_id`、`event_id` 全局唯一。
- 事件 append、outbox 写入在同一事务内完成。
- Projection 使用 `last_event_sequence` 保证幂等。
- 向量索引只保存可删除的派生表示，查询结果必须回到事件/投影校验。
- 所有表带 `household_id`，防止跨家庭访问。
- schema 与事件 payload 均有版本号和迁移策略。

---

## 10. 云端理解与记忆生成

### 10.1 处理流水线

```text
Evidence accepted
  → Policy validation
  → Quality / blur / exposure / duplicate filtering
  → Sensitive-content preprocessing
  → Image / short-video / ASR extraction
  → JSON schema validation
  → ObservationCandidate
  → Entity identity resolution
  → Place resolution
  → Candidate dedupe and fusion
  → Conflict detection
  → MemoryEvent append
  → Projection rebuild
  → Signal evaluation
  → Evidence deletion
```

### 10.2 模型输出契约

Extractor 只允许输出版本化 JSON：

- 可见对象及 bbox/region（可选）；
- 对象类别、名称候选和别名；
- Place 候选与空间关系；
- StateDimension、值、范围、单位；
- 动作或事件候选；
- 各 claim 的置信度；
- 证据时间段；
- 内容风险标签；
- 模型、提示词和预处理版本。

无法通过 schema 校验、置信度过低或来源策略不允许的结果进入失败/拒绝状态，不写 MemoryEvent。

### 10.3 对象身份解析

`IdentityResolver` 使用：

- 用户给出的名称；
- 多次出现的一致视觉特征；
- Place 与时间连续性；
- 拿起/放下等短窗 tracklet；
- 包装文字/OCR；
- 对象类别与尺寸；
- 用户确认或纠错；
- 已有对象别名。

跨天长期对象身份由 Memory Core 负责，单个视频 tracker 只提供短窗证据。

### 10.4 置信度融合

实现时将置信度拆分为：

```text
model_confidence
source_reliability
identity_confidence
place_confidence
cross_observation_support
conflict_penalty
user_confirmation_boost
```

最终融合分数与合并规则必须可配置、可回放、可通过标注集评测。阈值不写死在模型 prompt 或客户端。

### 10.5 技术参考项

以下作为候选实现和实验基线，不构成不可替换的产品依赖：

| 能力 | 参考项 | 使用条件 |
|---|---|---|
| 端侧质量/重复过滤 | OpenCV | 直接作为基线评测 |
| 图像/短视频结构化 | Qwen2.5-VL、InternVL 或等价商用 API | 使用同一家庭样本集比较 JSON 合格率、幻觉率、成本和时延 |
| OCR/区域候选 | Florence-2 或等价轻量模型 | 能减少主 VLM 调用或提高名称识别时采用 |
| 开放词表定位 | Grounding DINO | 对用户点名对象定位有显著收益时采用 |
| 短窗分割/跟踪 | SAM 2、TAPIR | 只用于高价值短动作，证明能减少错误事件后进入主链 |
| 端侧风险门 | MediaPipe 或单一移动推理 Runtime | 功耗可接受且能显著拦截风险帧时采用 |
| 事件存储 | PostgreSQL + JSONB | 首版默认参考实现 |
| 向量召回 | pgvector | 只做检索辅助 |
| 空间增强 | OpenXR、RTAB-Map、Open3D | 真机具备内参、同步位姿和稳定重定位后单独 PoC |
| 内部状态可视化 | Grafana State Timeline | 仅用于实验和排障 |

模型、SDK 和开源组件必须通过 Adapter、Extractor 或 Repository 接口隔离，便于替换和回滚。

---

## 11. 内部 API 契约

MVP 实现 API 契约但仅对内部设备、服务和 Agent 开放。外部第三方接入在权限、质量与安全达到发布门槛后启用。

### 11.1 通用要求

所有写接口携带：

- `household_id`
- `device_id` 或 `actor_id`
- `session_id`
- `idempotency_key`
- `policy_snapshot_id`
- `occurred_at` / `captured_at`
- `schema_version`

鉴权令牌绑定家庭、设备、用途、字段和有效期。错误码区分策略拒绝、暂停、权限缺失、预算耗尽、证据过期、schema 无效、冲突待确认和数据已遗忘。

### 11.2 P0 采集 PoC API

```text
POST /internal/v1/sessions
PATCH /internal/v1/sessions/{session_id}
GET  /internal/v1/capture-policy
POST /internal/v1/capture-attempts
POST /internal/v1/privacy/pause
POST /internal/v1/privacy/erase
GET  /internal/v1/audit
```

P0 的 `capture-attempts` 只接收：

```json
{
  "capture_id": "cap_01",
  "session_id": "sess_01",
  "planned_at": "2026-07-23T20:15:00+08:00",
  "result": "CAPTURED_LOCAL|BLOCKED_POLICY|FAILED|DISCARDED",
  "policy_snapshot_id": "pol_08",
  "duration_ms": 240,
  "error_code": null,
  "local_deleted_at": "2026-07-23T20:15:02+08:00"
}
```

该阶段服务端 schema 中不包含媒体、缩略图、OCR、文本或可还原画面的指纹。

### 11.3 Evidence 与候选 API

```text
POST /internal/v1/evidence/init
PUT  {pre_signed_upload_url}
POST /internal/v1/evidence/{id}/complete
POST /internal/v1/evidence/{id}/processing-result
POST /internal/v1/observation-candidates
POST /internal/v1/candidates/{id}/confirm
POST /internal/v1/candidates/{id}/reject
```

媒体上传在 P0 中由 feature flag 关闭。P1 开启后，`evidence/init` 必须先验证有效策略，返回独立的加密与过期参数。

### 11.4 Memory 写入与查询

```text
POST /internal/v1/memory/events

GET /v1/memory/objects?query=
GET /v1/memory/objects/{id}
GET /v1/memory/objects/{id}/where-is
GET /v1/memory/objects/{id}/timeline
GET /v1/memory/places/{id}/snapshot
GET /v1/memory/events?from=&to=&type=
GET /v1/memory/consumables/low-stock
GET /v1/memory/search?q=
```

`where-is` 返回：

```json
{
  "entity_id": "key_01",
  "location": {
    "place_id": "living_room_table",
    "display_name": "客厅茶几",
    "spatial_hint": "靠右侧"
  },
  "observed_at": "2026-07-23T20:15:00+08:00",
  "confidence": 0.91,
  "source_event_id": "evt_02",
  "open_conflict": false
}
```

### 11.5 Privacy 与 Audit

```text
GET    /v1/privacy/mode
PUT    /v1/privacy/mode
GET    /v1/privacy/policy
POST   /v1/memory/forget-recent
POST   /v1/memory/redact
DELETE /v1/memory/{id}
GET    /v1/memory/audit
GET    /v1/memory/deletion-jobs/{id}
```

### 11.6 Signal

```text
GET  /v1/memory/suggestions
POST /v1/memory/subscriptions
WS   /v1/memory/signals
```

首版可用数据库 outbox + 手机推送或轮询实现；契约预留：

```text
low_stock
object_moved
intent_detected
preference_updated
memory_conflict
deletion_completed
```

---

## 12. Agent 调用方式

### 12.1 Agent 可用能力

| 能力 | 调用 | 用途 |
|---|---|---|
| 对象查询 | `objects?query=` | 名称与别名解析 |
| 当前位置 | `where-is` | 找物 |
| 状态历史 | `timeline` | 回顾变化 |
| 低库存 | `consumables/low-stock` | 生成补货建议 |
| 自然语言检索 | `search` | 跨对象、地点和事件回忆 |
| 信号订阅 | `subscriptions/signals` | 主动服务 |
| 用户纠错 | confirm/reject/correct | 将用户反馈写回 Memory Core |

### 12.2 授权模型

- Agent 默认只读结构化摘要。
- 授权按家庭、用户、用途、数据类型、字段和有效期控制。
- 原始 Evidence 不对 Agent 开放。
- 写入确认、删除和外部动作使用独立 scope。
- 低库存信号只生成建议；购买等外部动作需要独立用户授权。
- 多个设备可收到同一 Signal，但首版由固定近场优先级选择一个用户触达端，例如眼镜优先、手机兜底。

### 12.3 回答可解释性

Agent 返回现实事实时同时携带：

- 对象；
- 当前状态或事件；
- 最近观察时间；
- 语义位置；
- 置信度或是否存在冲突；
- 可供审计的 `source_event_id`；
- 数据是否为用户确认。

---

## 13. 隐私、安全与信任设计

### 13.1 用户控制

1. 首次安装完成相机、麦克风、数据处理与家庭模式的明确授权。
2. 每次佩戴后轻提示一次，5 秒后默认开启当次会话。
3. 眼镜、手机和可用的戒指控制均可暂停；暂停在设备本地即时生效。
4. 用户可设置全局关闭、本次关闭、禁采空间、禁采时段和网络限制。
5. 审计页显示：何时、哪台设备、何种触发、形成了什么结构化记忆、证据是否删除。
6. 用户可更正、删除单条记忆或遗忘最近 N 分钟。

### 13.2 Policy Gate

设备在调用相机/麦克风前检查：

```text
session active
AND current policy valid
AND location/time allowed
AND permission granted
AND not paused
AND within battery/network/budget limits
```

云端在解密、模型调用和入库前再次检查策略快照。撤销或暂停后到达的迟到上传不解密、不处理。

### 13.3 敏感内容处理

- 用户设置的浴室、卫生间等禁采空间由本地策略先阻断。
- 工作/公共环境默认只支持主动触发。
- AI 阶段在 Evidence 离开设备前后设置风险门，识别屏幕、证件、人脸密集场景等并拒绝或脱敏。
- 首版不建立旁人人脸/声纹身份档案。
- 原始媒体不用于模型训练，除非用户进入独立、明确的授权流程。

### 13.4 删除语义

`forget-recent` 或单条删除覆盖：

```text
设备本地队列
→ Evidence DEK
→ 对象存储
→ 转写、裁剪和派生文件
→ ObservationCandidate
→ MemoryEvent / StateProjection
→ 搜索与向量索引
→ 缓存
→ 异步任务引用
```

查询索引先变为不可见，再完成物理清理。系统返回可查询的 DeletionJob；完成后只保留无内容 tombstone 和操作审计。

### 13.5 安全控制

- 设备独立凭证和短期令牌；
- TLS 与请求签名；
- per-evidence DEK + KMS 信封加密；
- 家庭级数据隔离；
- RBAC/ABAC 到设备、Agent、用途和字段；
- 证据访问、导出、删除和模型调用均审计；
- 离线队列限时、限量、加密；
- 失败任务有限重试，过期证据不无限积压。

---

## 14. 最小验证与实施路线

### 14.1 Phase 0A：Rokid 定时截图 PoC

目标：在真实目标机型上证明 Glass App 能安全、可控地管理一次佩戴会话并按固定间隔完成本地截图。

范围：

- 使用官方 Glass3 SDK/Demo 建立眼镜端 Android 工程；
- 真机验证安装、签名、SDK 初始化、相机权限和 `takePhoto`；
- 验证前台、后台、熄屏、锁定、断网、进程重启和连接丢失行为；
- 验证是否有可靠佩戴/摘下事件；
- 实现 5 秒倒计时、本次关闭、ACTIVE、PAUSED、ENDED 状态机；
- 测试 5/15/30/60 秒截图间隔；
- 图片只在设备端用于成功/失败验证，之后立即删除；
- 服务端只接收 capture metadata；
- 记录功耗、温升、成功率、失败码和清理回执。

验收：

1. 30 分钟会话中，至少 95% 的计划 tick 产生 `CAPTURED_LOCAL` 或可归因失败记录。
2. 暂停或结束后不再新增截图。
3. 默认模式无媒体上传，服务端请求体与日志中无图片、缩略图、OCR 或文本。
4. 会话结束后设备无普通截图残留。
5. 相同 `idempotency_key` 重放不生成重复记录。
6. 策略在会话中收紧时，下一次相机调用前停止。
7. 输出《Rokid 能力矩阵》：后台限制、佩戴事件、支持分辨率、单次耗时、温升、电量、文件路径、录制指示、P2P/网络和降级方案。

降级规则：

- 无可靠佩戴事件：采用手动开始/结束与断连保护。
- 后台相机不可用：保留前台/显式采集模式，并评估厂商合作或手机伴侣方案。
- 功耗或温升不满足长会话：降低频率并保留显式采集。

### 14.2 Phase 0B：戒指采集 PoC

目标：证明现有 Ring Sound 硬件可稳定产生标准化控制、音频和短窗 IMU 事件。

范围：

- 使用 Python SDK 0.3.4 建立回归脚本；
- 验证 BLE 扫描/连接、系统信息与校时；
- 连续验证按键双击 `0x0703`；
- 验证长按录音、主动 `0x0505` 分帧接收、缺帧补取、Speex 解码与设备端清理；
- 在手势模式验证 `0x0601/0x0605` IMU 批量上报与 `0x0702` HMM 手势；
- 记录录音模式与手势/IMU 模式切换实际表现；
- 输出统一 DeviceEvent；
- 评估 Android BLE Client 的实现工作量。

验收：

1. 50 次按键双击中至少 95% 被正确接收且不重复。
2. 20 段主动录音均能完整拼接，失败可归因，测试结束后按策略清理。
3. 10 分钟 IMU 会话能持续接收批次并记录序列缺口。
4. 模式未知或设备忙碌时不产生错误的业务状态。
5. 断连重连、重复包、损坏包和超时均有明确状态与错误码。
6. 输出《Ring 能力矩阵》《标准 DeviceEvent Schema》《Android 接入建议》。

### 14.3 Phase 0C：内部控制服务

可与硬件 PoC 并行开发：

- Session API；
- Capture Policy API；
- CaptureAttempt API；
- Pause/Erase API；
- Audit API；
- 鉴权、幂等、策略版本和 contract tests；
- 服务端 schema 明确禁止媒体字段。

### 14.4 Phase 1：最小 AI 记忆闭环

目标：跑通一条真实结构化记忆链，优先选择“钥匙从玄关移动到茶几”。

交付：

```text
GlassCaptureAdapter
→ Evidence Vault
→ Quality/Dedupe
→ Vision Extractor
→ ObservationCandidate
→ Entity/Place Resolver
→ MemoryEvent
→ StateProjection
→ where-is / timeline / audit / forget-recent
```

同时接入一条戒指主动语音链：

```text
Ring active voice
→ AudioEvidence
→ ASR
→ preference/intent candidate
→ MemoryEvent
→ search
```

验收：

1. 钥匙移动后，`where-is` 返回正确语义位置和时间。
2. 重复图片不制造重复对象和事件。
3. 低置信或冲突位置不进入主线。
4. 主动语音可形成偏好/意图并支持纠错。
5. Evidence 在策略窗口内删除，查询与审计保留结构化结果。
6. `forget-recent` 后相关数据在 Query、向量、缓存和任务中不可见。

### 14.5 Phase 2：家庭 MVP

范围：

- 找物；
- 一种耗材的余量变化与低库存建议；
- 主动偏好/任务；
- 5–20 户高接触家庭试验；
- 动态采集频率、成本预算和模型横评；
- 审计、更正、暂停、删除完整体验；
- 一个 P1 场景，例如阅读进度。

### 14.6 Phase 3：中台化

- 更多 Device Adapter；
- 对外开发者文档与受限 API；
- Signal 订阅；
- 家庭成员与字段级共享；
- Agent 委托授权；
- 复杂空间的渐进建库；
- 有明确增益后再接入空间锚点、短视频跟踪和更多时序能力。

---

## 15. 研发工作包、依赖与交付

### 15.1 工作包

| WP | 模块 | 主要交付 | 前置依赖 |
|---|---|---|---|
| WP0 | 契约与仓库骨架 | OpenAPI、JSON Schema、错误码、模块边界、测试夹具 | 无 |
| WP1 | Rokid Glass App | Adapter、会话状态机、PolicyCheck、定时截图、清理、Telemetry | 目标设备、SDK、WP0 schema |
| WP2 | Ring Adapter | Python 回归、标准 DeviceEvent、音频/IMU/手势 PoC、Android 方案 | 戒指、项目 SDK |
| WP3 | Session/Policy Service | 会话、策略快照、暂停、预算、capture metadata | WP0 |
| WP4 | Evidence/Ingest | 鉴权、幂等、加密、短 TTL、队列、删除回执 | WP3、安全方案 |
| WP5 | Perception | Edge Gate、Vision/ASR Extractor、schema validation、模型评测 | WP4、样本集 |
| WP6 | Memory Core | Entity、Place、Candidate、Event Store、冲突、Projection、Outbox | WP0、WP5 schema |
| WP7 | Query/Agent API | where-is、timeline、search、low-stock、Signal | WP6 |
| WP8 | Privacy/Audit | 审计页、删除编排、更正、权限和 Agent grant | WP3、WP4、WP6 |
| WP9 | QA/Benchmark | 硬件矩阵、E2E、故障注入、标注集、成本/质量报告 | 各模块 |

### 15.2 依赖图

```text
WP0
 ├─→ WP1 Rokid PoC ───────────────┐
 ├─→ WP2 Ring PoC ────────────────┤
 ├─→ WP3 Session/Policy ─→ WP4 Evidence/Ingest
 └─→ WP6 Memory Core skeleton      │
                                   ▼
                 WP4 → WP5 Perception → WP6 Memory Core
                                            ├─→ WP7 Query/Agent
                                            └─→ WP8 Privacy/Audit

WP9 QA/Benchmark 横跨所有工作包
```

### 15.3 建议仓库结构

```text
apps/
  glass-rokid/
  mobile-companion/
services/
  session-policy/
  ingest/
  perception/
  memory-core/
  query-api/
  privacy-audit/
packages/
  contracts/
  device-adapter-sdk/
  event-schemas/
  test-fixtures/
adapters/
  ring-python/
  ring-android/
infra/
  postgres/
  object-storage/
  queue/
docs/
  architecture/
  api/
  runbooks/
tests/
  contract/
  e2e/
  hardware/
  benchmark/
```

### 15.4 Definition of Done

每个工作包完成时必须同时具备：

- 实现代码；
- 单元测试；
- contract test；
- 结构化日志和错误码；
- 隐私与删除行为；
- 可回放的样本或测试夹具；
- README/运行说明；
- 指标与验收结果；
- 已知限制及降级策略。

---

## 16. 指标与验收体系

### 16.1 硬件采集

- 定时截图计划执行率；
- 拍照成功率与错误分布；
- 暂停/结束后的额外采集数，目标为 0；
- 本地媒体清理成功率，目标为 100%；
- Ring 事件接收率、重复率和断连恢复；
- 单次采集时延、耗电、温升、上传字节；
- 后台存活和进程恢复情况。

### 16.2 记忆质量

- 找物 Top-1 语义位置正确率；
- 对象身份合并正确率；
- 错误事实率；
- 候选冲突率；
- 用户纠错率；
- 多次观测后的置信度提升；
- 结构化 JSON 合格率；
- 偏好/意图抽取成功率；
- 耗材提醒有用率与忽略率；
- 复杂场景落入 L1/L2/L3 的分布。

### 16.3 性能与成本

- Query P50/P95；
- 每条有效记忆的模型调用、网络和存储成本；
- Edge Gate 减少的重模型调用比例；
- 每用户每日 Evidence 数、有效 MemoryEvent 数；
- Evidence 平均存活时长；
- 队列积压、重试和死信；
- Projection 重建时长。

### 16.4 隐私与可靠性

- 暂停成功率 100%；
- 删除任务完成率 100%；
- 删除后 Query/向量/缓存命中数为 0；
- 迟到上传被拒绝率；
- 策略版本不一致次数；
- 跨家庭访问测试必须全部拒绝；
- 重复上传、worker 重试和 outbox 重放不产生重复事件。

### 16.5 评测集

建立 50–100 条取得明确同意的家庭短样本作为初始回归集，覆盖：

- 钥匙、遥控器、充电器找物；
- 洗衣液/纸巾余量；
- 拿起、放下、打开、关闭；
- 阅读进度；
- 梳妆台/衣橱 L1 摘要；
- 主动偏好、任务和纠错；
- 模糊、黑屏、遮挡、重复帧；
- 同一对象多个位置冲突；
- 暂停、删除、迟到上传和断网重试。

模型与开源组件都使用同一评测集比较，不以单次 Demo 效果决定生产选型。

---

## 17. 风险与控制

| 风险 | 控制 |
|---|---|
| Rokid 后台相机或佩戴事件能力与预期不一致 | Phase 0A 真机矩阵；Adapter 隔离；手动会话/显式采集降级 |
| 眼镜耗电与温升影响佩戴 | 多间隔实测；预算与低电量降级；单图优先 |
| 戒指模式互斥影响交互 | 将录音和 IMU 状态写入 Ring Adapter；首版以双击和主动语音为主 |
| 模型把猜测写成事实 | Candidate 隔离、schema 校验、实体解析、冲突分支、融合门槛 |
| 同一物品身份漂移 | 多观测、别名、Place/时间约束、短窗 tracklet 和用户纠错 |
| 密集场景误盘点 | L1 摘要、L2 候选、L3 渐进主线 |
| 原始媒体留存超期 | per-evidence DEK、严格 TTL、定时清理、删除回执和监控 |
| 用户不清楚系统是否工作 | 每次佩戴一次轻提示、状态指示、暂停和审计 |
| 成本失控 | Edge Gate、冷却时间、每日预算、重模型配额、仅显式降级 |
| 删除遗漏派生数据 | DeletionJob 扇出、索引先隐藏、全链路 E2E 测试 |
| 供应商或模型锁定 | Device Adapter、Extractor 接口、版本化 schema、横评与回滚 |
| 过早开放第三方访问 | 先使用内部 API；Agent grant、字段 scope 和审计通过后逐步开放 |

---

## 18. 研发开始时需要冻结的配置

以下均作为配置或 Phase 0 产出，不写死在客户端：

| 配置 | 初始方案 |
|---|---|
| 佩戴提示倒计时 | 5 秒 |
| 本次关闭/暂停/全局关闭语义 | 按会话状态机实现 |
| P0 截图档位 | 5/15/30/60 秒全部测试，按真机结果选择 |
| Evidence 最大窗口 | AI Pilot 默认建议不超过 24 小时，可被更短策略覆盖 |
| 主动音频时长 | 建议不超过 30 秒 |
| 短视频时长 | 建议 2–3 秒 |
| 低电量阈值 | 由真机实验冻结，候选初始值 20% |
| 家庭/工作/外出判断 | 用户显式设置优先，Wi-Fi/地理围栏辅助 |
| 禁采空间 | 首版支持手动规则，Wi-Fi/地理围栏作为辅助 |
| 自动合入阈值 | 由标注集校准，拆分为多维置信度 |
| Agent 触达端优先级 | 眼镜优先、手机兜底，后续可配置 |

---

## 19. 技术资料与参考

### 19.1 Rokid 官方资料

- Rokid Open Platform：<https://open.rokid.com/>
- Glass3 SDK 概览：<https://x-docs.rokid.com/docs/terminal-sdk/getting-started/%E6%8E%A5%E5%85%A5%E6%8C%87%E5%8D%97.html>
- SDK 文档入口：<https://x-docs.rokid.com/docs/terminal-sdk/>
- Glass SDK API Reference：<https://x-docs.rokid.com/docs/en/terminal-sdk/api-reference/Glass3%20%20SDK%28%E7%9C%BC%E9%95%9C%E7%AB%AF%29%20API%E6%96%87%E6%A1%A3.html>
- 眼镜端拍照/录像/录音示例：<https://x-docs.rokid.com/%E4%BB%A3%E7%A0%81%E7%A4%BA%E4%BE%8B/30-media/01-%E7%9C%BC%E9%95%9C%E7%AB%AF-SDK-%E6%8B%8D%E7%85%A7%E5%BD%95%E5%83%8F%E5%BD%95%E9%9F%B3%E4%B8%8E-AI.html>

上述资料证明了眼镜端 Android 应用、手机端配套 SDK、媒体采集和双端通信的公开能力；后台常驻、佩戴事件、录制指示、功耗和具体目标机型权限仍以 Phase 0A 真机结果为准。

### 19.2 项目内戒指资料

- `hardware/ring-sound-sdk/README.md`
- `hardware/ring-sound-sdk/ring_sound_use.md`
- `hardware/ring-sound-sdk/protocol.md`
- `hardware/ring-sound-sdk/ring_sound.py`
- `hardware/ring-sound-sdk/demo.apk`

### 19.3 研究与开源参考

- OpenCV：端侧质量、变化与重复过滤
- Qwen2.5-VL / InternVL：多模态结构化候选
- Florence-2：轻量 OCR 与区域理解
- Grounding DINO / SAM 2 / TAPIR：高价值短动作的定位、分割和短窗跟踪
- Ego4D / OpenEQA / Mementos：第一视角任务和状态变化评测设计
- PostgreSQL / pgvector：事件事实源与语义召回
- OpenXR / RTAB-Map / Open3D：具备可靠位姿和重定位后的条件空间 PoC

---

## 20. 最终交付标准

当本 PRD 的家庭 MVP 完成时，另一名 Agent 或设备可以在授权范围内：

1. 向系统提交眼镜、戒指或结构化设备事件；
2. 查看每次输入是否被策略允许、是否形成候选和事件；
3. 查询一个对象的当前状态和完整变化时间线；
4. 获得低库存、对象移动或用户意图等信号；
5. 对低置信候选进行确认或纠错；
6. 暂停采集并删除指定对象或时间窗的全部相关数据；
7. 通过审计记录说明系统在何时、通过什么设备、沉淀了什么结构化记忆；
8. 在不接触原始媒体的前提下，为个人 Agent 提供可信现实上下文。

研发执行顺序为：

```text
先验证 Rokid 与 Ring 的真实采集能力
→ 冻结设备事件和内部 API 契约
→ 跑通单一对象的 AI 记忆闭环
→ 扩展到找物、耗材、主动偏好
→ 进入真实家庭试验
→ 最后开放更多设备和 Agent
```
