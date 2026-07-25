# 设备接入 Connector 架构

> 文档版本：v0.1
> 更新日期：2026-07-25
> 负责范围：多设备（乐奇/Rokid 眼镜、Ring 戒指、手机、未来设备）如何接入云端记忆平台
> 上游文档：[01 数据采集架构](01-Data-Capture-Architecture.md)
> 下游文档：[02 云端记忆平台架构](02-Memory-Platform-Architecture.md)

## 1. 这份文档解决什么问题

01 号文档回答"信号如何被采集"，02 号文档回答"证据如何变成记忆"。中间还缺一层
明确回答：

- 一台新设备（例如乐奇 Rokid Glasses）接入后端时，需要实现什么、注册什么。
- 设备差异（SDK、协议、触发方式）应该被隔离在哪一层。
- 后端如何管理多个设备接入器（connector）的身份、版本、健康和下线。

本文把这一层命名为 **Connector 层**，并给出当前代码库中的落地映射。

## 2. Connector 的定义：三段式

一个完整的设备 connector 由三段组成，只有中间的契约是全局统一的：

```text
[设备侧 Collector]        [传输契约]                [平台侧 Adapter]
设备原生 API 采集    ->   SourceEnvelope + 附件  ->  Ingest API 幂等接收
CameraX/AudioRecord       multipart HTTPS            去重/落盘/outbox
SensorManager/BLE/CXR-L   idempotency_key            device 注册与审计
```

| 段 | 运行位置 | 是否设备相关 | 当前实现 |
| --- | --- | --- | --- |
| Collector | 设备本机或中继手机 | 是，每种设备一套 | `apps/rokid-glass-probe`（乐奇眼镜）、iOS Reality App（手机+戒指） |
| 传输契约 | 网络边界 | 否，全局唯一 | `SourceEnvelopeIn` + `POST /internal/v1/envelopes`（[gateway](../../services/memory-platform/app/gateway/__init__.py)） |
| Adapter | 云端 | 弱相关，只做映射 | gateway ingest（当前所有设备共用一个通用 adapter） |

**核心设计决策：设备差异永远不进入记忆平台内部。** 感知、融合、候选、事件层
只认识 `SourceEnvelope / EvidenceItem`，不认识"Rokid""CXR-L""NUS v4"。设备相
关的所有知识被压缩到两个地方：

1. 设备侧 Collector 的实现代码。
2. 信封上的三个标识字段：`device_id`（设备注册身份）、`trigger`（触发方式）、
   `meta.device_kind / meta.device_adapter`（设备类型与接入器版本）。

## 3. 设计原则

1. **契约唯一。** 新设备接入 = 写一个新的 Collector，把设备原生数据映射成
   信封，不是给后端加一条新链路。v1 冻结契约见
   `contracts/reality-memory/v1/source-envelope.schema.json`（其中
   `device_kind` / `device_adapter` 字段就是为多设备预留的）。
2. **幂等优先。** 设备网络不可靠，重复投递是常态。`idempotency_key` 由采集端
   生成（会话 id + 序号），后端重复投递直接返回既有信封。
3. **离线是常态，不是异常。** Collector 必须先落本地 spool（持久化队列），再
   由独立的上传器 drain。眼镜断网、后台被杀、重启后都能续传。
4. **策略在边缘执行。** 佩戴/摘下、暂停、隐私开关在设备侧就阻止采集，而不是
   采集后由云端丢弃。摘下眼镜 = 停止采集，而非"采集但不上传"。
5. **证据短命，信封长命。** 原始媒体走 TTL 物理删除；信封与审计记录长期保留，
   保证"数据从哪来"永远可回答。
6. **传感器数据默认只上摘要。** IMU 等高频数据在设备侧聚合成窗口摘要
   （`modality=sensor`，只有 meta 没有附件），原始波形不出设备，除非某个具体
   算法需要且策略允许。

## 4. 乐奇（Rokid Glasses）的接入路线映射

Rokid 官方给出三条开发路线（详见
[ROKID-DEVELOPMENT-GUIDE.md](../../apps/rokid-glass-probe/docs/ROKID-DEVELOPMENT-GUIDE.md)），
在 connector 视角下的映射：

| 官方路线 | Connector 形态 | 状态 |
| --- | --- | --- |
| 眼镜端裸机开发 1.0.0 | On-device Collector：APK 跑在眼镜上，CameraX + AudioRecord + SensorManager 采集，HTTPS 直传 Ingest API | **当前主路线**，`apps/rokid-glass-probe` |
| CXR-L 1.0.4 | Relay Collector：手机 App 经 Rokid AI App 取眼镜媒体，再由手机上传 | 备选，裸机路线失败时启用 |
| CXR-M 1.1.0 | 不使用 | 需商务对接，不公开 |

两条可用路线上传的是**同一种信封**，后端不感知差异，只有
`meta.device_adapter` 不同（`rokid-glass-probe/bare` vs `mobile-cxr-l`）。这就
是 connector 层的价值：路线切换不动后端。

## 5. Connector 的管理

### 5.1 设备注册与身份

- 后端已有 `devices` 表（`household_id / kind / name`），`kind` 取值见
  `schemas.DEVICE_KINDS`：`glasses / ring / phone / earbuds`。注册走
  `POST /internal/v1/devices`，按 (household, name) 幂等——设备侧 Collector 每次启动
  都会调一次，没有幂等的话一副耳机重启十次就会在控制台上变成十台设备。
- `kind` 不是能力声明。后端不知道 `earbuds` 没有摄像头，也不该知道：能力边界由设备侧
  Collector 用 `REJECTED` 回执回答（见 [08](08-IFLYBUDS-Earbuds-Connector.md) §2）。
- 设备侧配置文件持有自己的 `device_id`（后端注册后下发）。未注册设备
  `device_id` 可空，信封仍被接收（审计 actor 记为 `device:unknown`），便于
  真机联调，但生产策略应要求非空。
- 每个 Collector 启动时生成 `source_session_id`（一次佩戴/一次服务生命周期），
  用于把同一会话的多条信封关联起来。

### 5.2 认证（分阶段）

| 阶段 | 方案 |
| --- | --- |
| 当前（Phase 1，内网联调） | Ingest API 挂在 `/internal/v1`，只在可信网络暴露；device_id 可空 |
| 下一步 | 复用 AgentGrant 模式给设备发 device token：注册时发放、Header 携带、服务端哈希校验、可吊销 |
| 远期 | 按 01 文档的加密信封方案，媒体端到端加密，网关只见密文 |

### 5.3 版本与能力管理

- `meta.device_adapter` 携带 collector 名称+版本（如
  `rokid-glass-probe/0.2.0`），后端可按版本统计、排障、拒收过旧版本。
- 新增模态或触发方式时，先改 v1 契约评审（`schemas/__init__.py` 中的
  Literal 枚举是冻结契约），再改 Collector。
- Collector 能力描述（能拍照？能录音？有 IMU？）当前记录在各自 README；设备
  数量增多后再考虑上收为注册表字段，避免过早建设。

### 5.4 健康与可观测

- 每条 ingest 都写 `AuditRecord`（actor=`device:<id>`），天然是接入流量账本。
- Collector 本地保留 JSONL 审计日志（probe-log.jsonl），采集/上传/失败全记录，
  可用 `adb shell run-as` 拉取。
- 心跳：Collector 定期发一条 `modality=sensor` 的摘要信封（含电量、温度、
  spool 深度），后端无需新接口即可监控设备存活。

### 5.5 新设备接入清单

1. 确认设备侧可用的采集 API 与系统限制（后台、权限、网络）。
2. 写 Collector：采集 → 本地 spool → 上传器（幂等键、重试、退避）。
3. 定义 `meta.device_kind / meta.device_adapter` 取值并写入设备 README。
4. 后端 `devices` 表注册设备，下发 `device_id`。
5. 用 `scripts/` 冒烟脚本或真机跑通 ingest → perception → query 全链路。
6. 验证离线续传、重复投递幂等、TTL 删除三个失败路径。

## 6. 当前代码映射

| 组件 | 位置 |
| --- | --- |
| 传输契约（运行时） | `services/memory-platform/app/schemas/__init__.py` 的 `SourceEnvelopeIn` |
| 传输契约（冻结版） | `contracts/reality-memory/v1/source-envelope.schema.json` |
| 平台侧 Adapter | `services/memory-platform/app/gateway/__init__.py`（幂等 + 去重 + 落盘 + outbox） |
| 乐奇 Collector | `apps/rokid-glass-probe/`（CameraX 拍照 + AudioRecord + IMU 摘要 + spool 上传，见其 README） |
| 耳机 Collector | `apps/iflybuds-collector/`（宿主机跑，耳机只出麦克风和扬声器，见 [08](08-IFLYBUDS-Earbuds-Connector.md)） |
| 设备注册 | `services/memory-platform/app/models/__init__.py` 的 `Device` + `POST /internal/v1/devices` |

## 7. Roadmap

1. 真机验证乐奇 Collector 的直传路径（网络稳定性、后台存活、温升耗电）。
2. Ingest API 增加 device token 认证与设备注册接口。
3. 心跳信封 + 简单设备状态页（复用 audit 数据）。
4. 若裸机直传不成立，落地 CXR-L Relay Collector（`apps/mobile-cxr-l`）。
