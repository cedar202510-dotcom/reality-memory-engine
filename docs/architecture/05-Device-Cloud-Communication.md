# 设备、手机与云端通信架构

> 文档版本：v0.1  
> 更新日期：2026-07-24  
> 负责范围：设备绑定、上行证据、下行消息、投递回执和手机兼容中继  
> 当前状态：上行对象与流程可实施；云端沉淀规则、下行提醒业务字段和实时通道待 review  
> 数据对象依据：[多模态数据契约 v1.0](../engineering/Reality-Memory-Multimodal-Data-Contract-v1.0.md)

## 1. 结论

眼镜、手机和云端不是三个平级“后端”。

| 部分 | 中文理解 | 负责什么 |
| --- | --- | --- |
| 眼镜端 Runtime | 设备端运行程序 | 采集、隐私状态、本地加密队列、上行、提醒呈现和回执 |
| Reality 手机 App | 唯一用户控制 App | 登录、设备绑定、策略设置、查询、审计、提醒和可选中继 |
| Memory Platform | 云端记忆平台 | 接入、解析、跨模态融合、事实事件、当前状态、查询和信号 |
| Agent | 云端或受控服务 | 理解查询、判断提醒价值、处理歧义和组织措辞 |

首选链路是眼镜直接与云端通信。手机负责用户控制，也可以在眼镜网络或设备能力
受限时成为中继，但不是所有媒体永久必经的节点。

```text
上行：
RV101 眼镜 Runtime
  -> HTTPS / 对象存储
  -> Cloud Ingest
  -> 解析与记忆沉淀

下行：
StateProjection / MemorySignal
  -> 提醒规则与 Agent
  -> 设备消息通道
  -> RV101 文字或 TTS
  -> 投递回执

控制：
Reality 手机 App
  <-> Cloud Control API
  <-> 设备绑定、策略、暂停、删除和状态
```

## 2. 当前冻结程度

| 内容 | 当前结论 |
| --- | --- |
| `CaptureSession` 到 `EvidenceItem` 的对象语义 | 已由 v1 数据契约固定，可并行开发 |
| 上行必须带来源、双时间标尺、策略和幂等信息 | 已固定 |
| 媒体先取得上传授权、再上传密文、最后确认完成 | 当前可实施方案 |
| 手机是唯一用户 App、眼镜是设备 Runtime | 已固定 |
| 云端如何选模型、融合和生成事实 | 待记忆沉淀 review |
| 哪些状态值得提醒、何时提醒 | 待产品与 Agent review |
| 下行提醒的业务字段和文案结构 | 待 review，不生成正式 v1 Schema |
| 下行使用轮询、WebSocket、MQTT 还是系统推送 | 待 RV101 真机网络和后台测试 |

因此，当前可以实现通用的设备消息“信封”和回执能力，但不能把示例
`ReminderSignal` 当成最终业务契约。

## 3. 设备身份与绑定

推荐绑定过程：

```text
1. 用户在 Reality 手机 App 登录 Reality Account。
2. 眼镜显示一次性设备码或二维码。
3. 手机把设备码提交给 Cloud Control API。
4. 云端把 device_id 绑定到 owner_id / household_id。
5. 眼镜使用一次性码换取短期 device_token 和设备证书引用。
6. 眼镜以后只用设备凭证访问设备 API，不持有用户的完整账号 Token。
```

设备凭证至少限制：

- 只能代表一个 `device_id`。
- 只能上传属于该设备的来源和 Evidence。
- 只能读取发给该设备的消息。
- 不能查询完整记忆库，也不能写 `MemoryEvent`。
- 可由手机或云端撤销；撤销后眼镜停止上传并进入可解释的受限状态。

## 4. 上行：眼镜把采集结果交给云端

### 4.1 上行内容

眼镜上传的是证据和设备事实，不是现实语义结论：

- 采集会话、采集意图、采集窗口和逐模态采集尝试。
- `SourceEnvelope`，即来源、设备、时间、策略和关联编号。
- `EvidenceItem`，即短期图片、短视频、短音频或传感器窗口的元数据。
- 加密后的媒体对象。
- 上传、过期、本地删除和失败审计事件。

眼镜端不得上传“用户正在吃饭”“用户不喜欢胡辣汤”“钥匙被拿起”作为事实。
这些只能由云端解析和事实门控产生。

### 4.2 媒体上传流程

当前 v1 数据契约定义三步流程：

```text
POST /internal/v1/evidence/init
  -> 返回 evidence_item_id、upload_id、短时 upload_url

PUT <upload_url>
  -> 上传 AES-256-GCM 密文

POST /internal/v1/evidence/{evidence_item_id}/complete
  -> 云端校验哈希和字节数并返回 accepted
```

只有 `complete` 返回 `accepted: true`，眼镜才能把本地队列标为“云端已接收”。
端侧删除仍需要 TTL、结构化完成通知或明确删除策略，不能仅因网络请求成功就立即
抹掉审计信息。

小型结构化设备事件可以批量 HTTPS 上传。批量接口路径尚未冻结，但每条记录仍须
使用 v1 Schema、稳定 ID 和幂等键，不得把 NDJSON 到达顺序当成现实时间。

### 4.3 本地队列状态

```text
STAGED
  -> ENCRYPTED
  -> WAITING_NETWORK
  -> INITIALIZED
  -> UPLOADING
  -> COMPLETING
  -> ACCEPTED
  -> DELETING
  -> DELETED

任一上传阶段
  -> RETRYABLE_FAILED / PERMANENT_FAILED / EXPIRED
```

- 断网、超时和 5xx 使用同一 `evidence_item_id` 重试。
- 幂等键相同但正文哈希不同必须停止重试并进入审计。
- 用户暂停阻止新采集，但不自动代表可以继续上传所有旧证据；是否上传由暂停策略决定。
- 用户删除、TTL 到期和设备解绑优先于上传重试。

## 5. 下行：云端把消息交给眼镜

### 5.1 下行只传结果和控制，不传记忆数据库

云端可能向眼镜发送：

- 值得呈现的提醒。
- 策略版本更新通知。
- 隐私暂停、设备解绑或凭证撤销。
- 采集预算和能力配置更新。
- 仅限测试构建的诊断命令。

云端不应把完整 `MemoryEvent` 或 `StateProjection` 数据库同步到眼镜。眼镜只保留
完成当前交互所需的最小消息和短期状态。

### 5.2 通用设备消息信封

以下是下行通道的建议草案，不是正式 v1 业务 Schema：

```json
{
  "schema_ref": "rme.device-message.v0",
  "message_id": "msg_...",
  "target_device_id": "glass_...",
  "message_type": "REMINDER_SIGNAL",
  "created_at": "2026-07-24T10:00:00Z",
  "expires_at": "2026-07-24T10:10:00Z",
  "priority": "NORMAL",
  "payload_schema_ref": "rme.reminder-signal.draft",
  "payload": {},
  "delivery_policy": {
    "allow_text": true,
    "allow_tts": true
  }
}
```

当前只建议固定通用字段：消息编号、目标设备、类型、创建时间、过期时间、优先级、
载荷版本和投递限制。`payload` 内提醒主题、理由、按钮、措辞和交互动作均待 review。

### 5.3 下行传输的实施顺序

1. **首版轮询。** 眼镜在已联网、会话激活或固定低频时拉取设备收件箱。它最容易
   调试，也能先验证鉴权、过期、去重和回执。
2. **第二版长连接。** 真机确认后台网络、重连、功耗后，再在 WebSocket 与 MQTT
   中选择。两者都可实现，不应在无真机数据时提前冻结。
3. **系统或厂商推送。** 只有在 Rokid 固件、应用分发和通知权限稳定后才评估，
   不能作为首版唯一通道。

建议轮询接口示意：

```text
GET /internal/v1/devices/{device_id}/inbox?cursor=<opaque>
```

该路径和返回字段仍是建议接口。正式实现前需要完成云端下行 review。

### 5.4 投递回执

眼镜必须使用 `message_id` 幂等回传状态：

| 状态 | 中文含义 |
| --- | --- |
| `RECEIVED` | 设备已收到消息 |
| `PRESENTED` | 文字已展示 |
| `SPOKEN` | TTS 已开始或完成，具体阶段待字段定义 |
| `DISMISSED` | 用户关闭或忽略 |
| `EXPIRED` | 到达或处理时已过期，未呈现 |
| `FAILED` | 因设备状态、权限或渲染错误失败 |

回执只说明设备投递结果，不代表用户已经接受提醒内容，也不能直接修改记忆事实。

## 6. 云端如何产生提醒

当前建议链路是：

```text
MemoryEvent
  -> StateProjection 更新
  -> SignalCandidate
  -> 规则、授权、冷却和去重
  -> Agent 判断价值并组织简短措辞
  -> ReminderSignal 草案
  -> DeviceMessage
  -> 眼镜展示 / TTS
  -> DeliveryReceipt
```

这条链路表达职责边界，不代表每个对象字段已经确定。尚需单独 review：

- 什么状态变化可以产生 `SignalCandidate`。
- 规则与 Agent 谁拥有最终提醒决定权。
- 提醒优先级、过期、冷却、每日上限和终端选择。
- 眼镜显示文字、TTS、按钮和追问入口的字段。
- 用户忽略、确认、纠正后如何回到记忆事件流。

## 7. 手机兼容中继

当眼镜无法稳定直连互联网时，可以使用：

```text
眼镜本地加密队列
  -> 已绑定手机的局域网或 BLE 传输
  -> Reality 手机 App
  -> 同一 Cloud Ingest
```

中继时必须保留原始 `device_id`、来源时间和 `producer_device_id`，并另外记录
`relay_device_id`。手机接收时间不能覆盖眼镜采集时间，手机也不能把 Evidence
转换成事实。

下行也可以由手机中继，但同一 `message_id` 只能产生一条最终投递状态，防止眼镜
直连和手机中继同时重复播报。

## 8. 隐私与失败优先级

从高到低：

1. 用户本地暂停、关闭、摘下和删除。
2. 设备解绑、凭证撤销和策略失效。
3. TTL 到期和敏感内容阻断。
4. 正常上传、配置更新和提醒投递。
5. 调试命令。

云端消息不能绕过眼镜本地策略远程强制打开相机或麦克风。未来若增加“请求现场
确认”，也只能生成需要用户确认或本地策略允许的 `CaptureIntent`，不能直接调用
媒体 API。

## 9. 联调验收

上行最小验收：

- 同一 Evidence 重试不会产生重复对象或重复解析任务。
- 图片、音频和 IMU 可通过 `capture_window_id` 与双时间标尺关联。
- 上传完成前断网可以恢复，TTL 或删除发生后不会继续上传。
- 设备解绑后旧 Token 无法继续写入。

下行通道最小验收：

- 同一消息重复拉取只展示一次。
- 过期消息不展示、不播报，并返回 `EXPIRED`。
- 暂停采集不妨碍必要的隐私或解绑通知。
- 提醒回执不修改 `MemoryEvent` 或 `StateProjection`。

真机还需测量轮询和长连接的后台存活、重连时间、耗电、温升、网络切换和 TTS
冲突。完成这些测试和云端下行 review 后，才能发布正式下行 v1 Schema。

