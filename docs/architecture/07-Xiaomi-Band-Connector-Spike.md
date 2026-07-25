# Xiaomi Band Connector Spike

> 文档版本：v0.1  
> 更新日期：2026-07-25  
> 负责范围：在不影响现有眼镜、戒指和 iOS 采集路径的前提下，验证是否能把
> Gadgetbridge 的小米手环 10 采集能力抽成 RealGit 的人体特征 Collector。

## 1. 结论

可以试，但不能按“接一个 SDK”理解。Gadgetbridge 不是给第三方 App 调用的官方
SDK，而是一个完整 Android 应用，其中包含小米手环协议、认证、同步、数据库和 UI。
最终目标不是人工导出 SQLite、查看手机目录或离线搬运文件，而是做一个 Android
端 Collector，与手环保持蓝牙连接，把实时或准实时人体特征数据直接转成 Reality
Memory 的事件并上传。最小风险路线是：

```text
Xiaomi Smart Band 10
  -> Android Band Collector Spike (BLE live/private-protocol connection)
  -> 本地 wearable_metrics stream + offline spool
  -> RealGit SourceEnvelope / EvidenceItem
  -> Memory Platform Ingest API
```

Spike 阶段不改 `apps/mobile-app/ios`、不改 `apps/reality-memory-glasses` 主链路，
也不要求用户人工导出文件。它只验证三件事：

1. Android 端能否稳定连接小米手环 10 并完成认证。
2. 能否拿到心率、步数、睡眠、血氧、压力等人体特征数据。
3. 哪些字段是真实时流，哪些字段只能通过周期拉取或历史同步获得。
4. 能否把这些数据自动映射成现有上行契约并上传云端。

SQLite、Health Connect 和 Gadgetbridge 导出文件只作为字段审计和回归验证工具，
不能成为最终产品链路。

## 2. 当前项目边界

当前仓库里的手机 App 是 iOS 工程：

```text
apps/mobile-app/ios/
```

它通过 CXR-L 接入 Rokid 眼镜，通过 CoreBluetooth 接入 Ring Sound 戒指。它不能
直接复用 Gadgetbridge 的 Java/Kotlin Android 代码。

当前 Android 工程主要是眼镜端 Runtime：

```text
apps/reality-memory-glasses/
apps/rokid-glass-probe/
```

它们不是用户手机 App。小米手环 10 的 Gadgetbridge 路线应作为新的 Android
Collector Spike，而不是塞进现有 iOS App 或眼镜 Runtime。

## 3. 为什么不直接把 Gadgetbridge 当库

Gadgetbridge 的有用部分包括：

- 小米设备配对和 auth key 配置。
- Xiaomi protobuf 协议认证与加密。
- 活动数据同步。
- 心率、步数、SpO2、压力、睡眠等数据解析。
- 本地数据库和导出能力。

但它同时也包含：

- 大量设备 UI、设置页、通知、闹钟、天气、固件、表盘等产品功能。
- 自己的数据库模型。
- 自己的后台服务和权限模型。
- AGPL 许可证约束。

所以首选不是把整个 App 作为 SDK 嵌入，而是先建立一个隔离目录，评估是否抽取
协议层：

```text
experiments/xiaomi-band-collector/
  README.md
  app/                    # 独立 Android spike，不参与主 App 构建
  notes/gadgetbridge-map.md
```

只有当 Spike 证明可行后，再决定：

| 方案 | 说明 | 适用阶段 |
| --- | --- | --- |
| Fork Gadgetbridge | 直接基于它改成 Reality Band Collector | 最快验证，开源合规压力最大 |
| 抽协议层 | 只迁移 Xiaomi protobuf、认证、同步和解析相关代码 | 产品化候选 |
| Intent/Health Connect 桥接 | 外部安装 Gadgetbridge，Reality App 读 Health Connect 或导出文件 | 仅用于字段审计和内部对照 |
| 自研 BLE HR | 只接手环 10 心率广播 | 实时心率单点能力，优先 POC |

## 4. 不影响现有系统的 Spike 路线

### 4.1 Phase 0：只做文档和边界

本阶段只新增文档，不改任何运行代码。

验收：

- 明确 Android-only 边界。
- 明确不影响 iOS CXR-L、Ring Sound、RV101 眼镜 Runtime。
- 明确上行仍使用现有 `SourceEnvelope + EvidenceItem`。

### 4.2 Phase 1：实时链路验证

先验证公开实时能力，不依赖 Gadgetbridge：

1. 在小米手环 10 上开启心率广播。
2. Android 测试 App 扫描 BLE Heart Rate Service。
3. 订阅 Heart Rate Measurement notify。
4. 记录通知频率、断连重连、后台稳定性和电量影响。
5. 把实时心率样本写成本地 `wearable_metrics.ndjson` 并上传测试后端。

验收标准：

- 不需要人工导出。
- 不需要读取 Gadgetbridge SQLite。
- App 运行时可以收到心率流。
- 断网时进入本地 spool，恢复网络后自动上传。

### 4.3 Phase 2：Gadgetbridge 私有协议验证

先不 fork 代码，用真实 Android 手机安装 Gadgetbridge nightly 或稳定版，验证：

1. 小米手环 10 通过 Mi Fitness 完成首次绑定。
2. 获取 Xiaomi auth key。
3. Gadgetbridge 能连接小米手环 10。
4. 确认 Gadgetbridge 对 Xiaomi protobuf 设备的实时连接能力。
5. 记录能以实时或准实时方式获得的数据：
   - realtime heart rate
   - realtime steps
   - battery / wearing / device state
6. 再记录只能周期拉取或历史同步的数据：
   - heart_rate
   - steps
   - sleep sessions / sleep stages
   - spo2
   - stress
   - respiratory rate
   - workouts
7. SQLite 或 Health Connect 仅用于检查字段粒度和时间戳，不作为最终链路。

验收产物：

```text
research/xiaomi-band-10-gadgetbridge-field-audit.md
testdata/wearables/xiaomi-band-10/<run-id>/
```

### 4.4 Phase 3：独立 Android Collector Spike

新建独立 Android 工程，不加入现有发布 App：

```text
experiments/xiaomi-band-collector/
```

最小功能：

- 设备选择和 auth key 输入。
- 连接小米手环 10。
- 保持 BLE 连接并接收实时心率、实时步数等 live stats。
- 对只能拉取的数据执行周期同步，而不是人工导出。
- 把实时样本和周期同步结果写入本地 `wearable_metrics.ndjson`。
- 用现有 debug backend 上传器风格，上传到 `/internal/v1/device-evidence`。

本阶段可以先不迁移全部 Gadgetbridge UI，只保留采集链。

### 4.5 Phase 4：产品化选择

如果 Phase 3 成立，再选产品路线：

1. 做 Reality Android 手机 App，把 Band Collector 放进去。
2. 或做独立 companion app，只负责手环采集和上传。
3. 或继续用 Health Connect 作为低优先级补充，但不把它当实时通信主链路。

## 5. 上行契约建议

人体特征数据不应伪装成图片、音频或普通 IMU。建议作为 `modality=sensor` 的
结构化 Evidence。

示例：

```json
{
  "schema_ref": "rme.wearable-metrics.v0",
  "device_kind": "xiaomi_smart_band_10",
  "adapter": "xiaomi-band-collector/gadgetbridge-spike",
  "interval_start": "2026-07-25T01:00:00Z",
  "interval_end": "2026-07-25T01:05:00Z",
  "metrics": [
    {
      "type": "heart_rate_bpm",
      "value": 72,
      "unit": "bpm",
      "sampled_at": "2026-07-25T01:03:12Z"
    },
    {
      "type": "spo2_percent",
      "value": 97,
      "unit": "percent",
      "sampled_at": "2026-07-25T01:03:12Z"
    }
  ],
  "privacy_class": "wellness_signal",
  "medical_use": false
}
```

睡眠建议单独建 interval：

```json
{
  "schema_ref": "rme.sleep-session.v0",
  "device_kind": "xiaomi_smart_band_10",
  "adapter": "xiaomi-band-collector/gadgetbridge-spike",
  "sleep_start": "2026-07-24T15:32:00Z",
  "sleep_end": "2026-07-24T22:41:00Z",
  "stages": [
    {
      "stage": "light",
      "start": "2026-07-24T15:32:00Z",
      "end": "2026-07-24T16:12:00Z"
    }
  ],
  "privacy_class": "wellness_signal",
  "medical_use": false
}
```

## 6. 云端落点

短期不新开专用接口，复用现有设备 Evidence 入口：

```text
POST /internal/v1/device-evidence
```

上传形态：

- `source_envelope`：描述 Android Band Collector、手环、时间和授权。
- `evidence_item`：`modality=sensor`，mime type 可用
  `application/x-ndjson` 或 `application/json`。
- `file`：`wearable_metrics.ndjson` 或单个 JSON 文件。

后续如果人体特征数据量稳定增长，再考虑新增批量结构化接口。Spike 阶段不要先改
后端表结构。

## 7. 权限、合规与产品风险

### 7.1 Android 权限

Android Collector 至少需要：

- `BLUETOOTH_SCAN`
- `BLUETOOTH_CONNECT`
- `ACCESS_FINE_LOCATION` 或相关扫描兼容权限，取决于系统版本
- `FOREGROUND_SERVICE`
- `INTERNET`
- Health Connect 读取权限，如果采用 Health Connect 路线

### 7.2 小米授权

小米手环 10 私有协议通常需要官方 App 绑定后生成的 auth key。Spike 必须把
auth key 视为敏感凭据：

- 只存 Android Keystore 或受保护本地配置。
- 不上传到云端。
- 不写日志。
- 用户解绑手环时删除。

### 7.3 开源许可证

Gadgetbridge 是 AGPL 生态项目。任何复制、修改、分发或作为服务组成部分使用，
都需要开源合规评估。Spike 阶段可以阅读和验证；产品化前必须由负责人确认：

- 是否 fork 并开源派生代码。
- 是否只借鉴协议思想并重新实现。
- 是否用 Health Connect 避开直接分发 Gadgetbridge 派生代码。

## 8. 建议的下一步

1. 找一台 Android 手机和一只小米手环 10。
2. 用 Mi Fitness 首次绑定，拿到 auth key。
3. 用 Gadgetbridge 验证实际可同步字段。
4. 先完成心率广播实时 POC。
5. 再用 Gadgetbridge 验证私有协议下的实时/准实时字段边界。
6. 把实时链路和同步链路的字段审计写入 `research/`。
7. 再决定是否创建 `experiments/xiaomi-band-collector/` 独立 Android Spike。

不要直接把 Gadgetbridge 大量源码并入当前主线。先用真实设备确认数据价值和字段
粒度，再决定是否承受协议迁移和开源合规成本。
