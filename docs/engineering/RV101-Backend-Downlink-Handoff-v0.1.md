# RV101 后端消息下发交接说明 v0.1

> 状态：联调准备稿  
> 目标：让后端或 Agent 把回答、提醒和系统状态发到 RV101，由眼镜使用固定组件呈现并回传结果  
> 呈现字段详见
> [`RV101-DOWNLINK-PRESENTATION-CONTRACT-v0.1.md`](../../apps/reality-memory-glasses/docs/RV101-DOWNLINK-PRESENTATION-CONTRACT-v0.1.md)

## 1. 当前结论

后端通信层和眼镜 HTTP 接收器已经实现，并完成第一轮真机联调：

- 已有消息落库、WebSocket 实时推送、离线轮询补投、过期处理和投递回执 API。
- 已有 `rme.device-message.v0` 信封和 `delivery_policy`。
- 后端已校验 `rme.glasses-presentation.v0` 的字段、来源、长度和自由样式。
- 眼镜 Debug APK 0.1.7 已实现设备自注册、每 3 秒 inbox 轮询、固定组件与回执。
- RV101 已验证 `RECEIVED -> PRESENTED -> DISMISSED`；后台视觉层使用短时纯黑
  `SYSTEM_ALERT_WINDOW` 独立显示层，遮住 Rokid 首页，消息结束立即移除。
- WebSocket API 已存在，但眼镜暂时使用 HTTP inbox，待真机确认后台网络后再降低延迟。
- `/internal/v1` 当前依赖本机或可信内网，没有设备令牌，不能直接暴露到公网。

因此当前可以用开发线和本机后端验证人工测试消息，但 Agent 结果自动转消息、生产设备
鉴权以及正式版覆盖层授权或 Rokid 白名单仍未完成。

## 2. 完整链路

```text
Agent 回答 / 提醒决策
→ POST /internal/v1/devices/{device_id}/messages
→ device_messages 落库
→ 眼镜 HTTP inbox 拉取（当前）/ WebSocket 实时推送（后续）
→ 眼镜按 intent 选择本地图标与固定组件
→ 眼镜显示文字 / 可选 TTS
→ RECEIVED / PRESENTED / SPOKEN / DISMISSED 回执
→ 后端记录投递结果

WebSocket 断开
→ 眼镜重连，或 GET inbox 轮询
→ 补投未结束且未过期的消息
```

下发只传本次需要呈现的最小结果，不把 `MemoryEvent`、`StateProjection` 或原始证据同步
到眼镜。

## 3. 后端创建消息

现有接口：

```http
POST /internal/v1/devices/{device_id}/messages
Content-Type: application/json
```

联调请求：

```json
{
  "message_type": "REMINDER_SIGNAL",
  "payload_schema_ref": "rme.glasses-presentation.v0",
  "priority": "HIGH",
  "ttl_seconds": 120,
  "delivery_policy": {
    "allow_text": true,
    "allow_tts": true
  },
  "payload": {
    "presentation": {
      "intent": "TASK",
      "title": "记得把资料给小王",
      "body": "你已经到公司了",
      "speech_text": "记得把资料给小王",
      "interaction": {
        "type": "COMPLETE_TASK",
        "action_id": "task-complete-20260726-001"
      }
    },
    "source": {
      "kind": "MEMORY_SIGNAL",
      "reference_id": "signal_uuid"
    },
    "correlation_id": "agent_turn_or_signal_id"
  }
}
```

第一阶段继续使用现有 `REMINDER_SIGNAL` 作为所有用户可见消息的外层类型，由
`presentation.intent` 区分普通回答、提醒、任务、采购提醒和隐私状态。内部暂时保留
`CONSUMABLE` 兼容枚举，用户侧只显示“采购提醒”。这样不用先修改数据库和消息类型枚举。
后续如果要在通信层区分问答与提醒，再单独评审 `AGENT_RESPONSE`。

创建成功后，响应中的关键字段：

| 字段 | 含义 |
| --- | --- |
| `message.message_id` | 幂等编号；眼镜去重和回执必须使用 |
| `message.created_at` / `expires_at` | 服务端生成的创建与过期时间 |
| `message.payload` | 原样交给眼镜消费者的呈现载荷 |
| `message.delivery_policy` | 是否允许文字和 TTS |
| `pushed_connections` | 当前即时推送成功的连接数；`0` 只代表设备不在线，消息仍已落库 |

## 4. 眼镜接收消息

### 已有 WebSocket 路径

```text
WS /internal/v1/devices/{device_id}/stream
```

连接建立后，后端会先发送积压消息，再推送新消息。当前 APK 尚未启用这条路径；加入时
眼镜需要：

1. 每隔小于服务端空闲超时时间发送 `{"type":"ping"}`。
2. 收到消息先按 `message_id` 去重，再校验过期时间和 `payload_schema_ref`。
3. 回 `RECEIVED` 后排入本地呈现队列。
4. 实际可见后回 `PRESENTED`；TTS 完成后回 `SPOKEN`。
5. 用户执行右下角主动作后回 `DISMISSED`，`detail` 必须带动作类型和 `action_id`。
6. 断线后退避重连，重连收到重复消息时不得重复弹出已经终结的消息。

WebSocket 回执帧：

```json
{
  "type": "receipt",
  "message_id": "2b832a93-cb97-4b1d-a57d-428cb639575d",
  "status": "PRESENTED",
  "detail": {},
  "device_reported_at": "2026-07-25T10:00:03Z"
}
```

### 当前眼镜使用的轮询路径

```http
GET /internal/v1/devices/{device_id}/inbox
```

返回未终结且未过期的消息。使用轮询收到消息后，通过下面的 HTTP 接口回执：

```http
POST /internal/v1/devices/{device_id}/receipts
Content-Type: application/json
```

```json
{
  "message_id": "2b832a93-cb97-4b1d-a57d-428cb639575d",
  "status": "DISMISSED",
  "detail": {
    "reason": "PRIMARY_ACTION",
    "interaction": "COMPLETE_TASK",
    "action_id": "task-complete-20260726-001",
    "user_action": true
  },
  "device_reported_at": "2026-07-25T10:00:08Z"
}
```

## 5. 后端需要实现

已经完成 `GlassesPresentationPayload` Pydantic 校验。后端后续需要：

1. 把 Agent 回答或提醒信号转换成受约束载荷，再调用统一的消息创建服务；不要让模型直接
   生成 HTML、SVG、坐标或颜色。
2. 保持 `message_id` 至少一次投递和幂等回执语义。
3. 消费带 `user_action=true` 的回执，按 `action_id` 幂等更新任务或采购清单；加入清单
   不得自动下单。
4. 增加设备身份、短期 device token 和“设备只能读取自己的消息”校验。
5. 多实例部署前把进程内 `DeviceHub` 替换为 Redis pub/sub 或配置粘性路由。

短期联调可以直接调用现有 HTTP 创建接口。正式接入同一后端进程的 Agent / Signal
Worker 时，应抽出共享的 `create_device_message()` 应用服务，避免服务内部绕 HTTP
调用自己。

## 6. 眼镜端需要实现

Debug APK 0.1.7 已实现上述基础能力。后续眼镜端需要：

1. 用 WebSocket 替换 3 秒 HTTP 轮询作为低延迟主路径，保留 inbox 兜底。
2. 接入正式 `backend_base_url` 和设备凭证，不再依赖 Debug BuildConfig。
3. 正式分发时引导用户授予“在其他应用上层显示”权限，或申请 Rokid 系统白名单。
4. 用真机继续验证后台网络、多个消息排队、TTS 完成回执、物理单击动作和离线补投。

## 7. 联调必须提供

后端队友需要拿到：

- 本文档和 `rme.glasses-presentation.v0` 呈现契约。
- 可访问的后端 `base_url`。
- 已登记的 RV101 `device_id`。
- 本地联调阶段的端口或 ADB reverse 配置。
- 一组 `ANSWER`、`REMINDER`、`TASK`、`CONSUMABLE` 测试消息。
- 眼镜端日志和后端 `device_messages` / receipt 审计记录。

当前 USB 联调可以把后端端口反向映射给眼镜：

```bash
adb reverse tcp:<backend_port> tcp:<backend_port>
```

眼镜随后访问 `http://127.0.0.1:<backend_port>`。这只适用于开发线测试，不是正式网络
架构。

## 8. 验收标准

1. HTTP 轮询版创建设备消息后即使 `pushed_connections=0`，眼镜也应在约 3 秒内显示。
2. 普通回答与提醒使用不同图标，但图标位置和正文骨架不跳动。
3. 普通回答使用 `NONE`；重要提醒显示“知道了”，任务显示“完成”，采购提醒显示
   “加入采购清单”，眼镜端不接受后端自由按钮文字。
4. 设备依次回传 `RECEIVED`、`PRESENTED`，可选 TTS 完成后回 `SPOKEN`。
5. 用户动作后回 `DISMISSED`，回执包含 `interaction`、`action_id` 和
   `user_action=true`；相同 `message_id` 重投不再次显示。
6. 眼镜离线时消息落库；重连通过 WebSocket backlog 或 inbox 补投。
7. 已过期消息不显示、不播报；未知意图降级为 `ANSWER` 并记录原因。
8. 未授权设备不能读取、确认或伪造其他设备的消息。

当前 Debug 安装脚本会通过 ADB 为测试包启用 `SYSTEM_ALERT_WINDOW`。普通侧载正式 APK
不能静默获得此权限；缺少权限时眼镜会降级为系统通知和可选 TTS，若视觉层没有确认，
最终回 `FAILED`，不会把“后端已收到”误报成“用户已看到”。

## 9. 手动测试入口

后端启动、开发线执行 `adb reverse tcp:8765 tcp:8765`、眼镜佩戴进入感知状态后：

```bash
cd apps/reality-memory-glasses
./scripts/test-downlink-presentation.sh
```

第三个参数可以指定 `ANSWER`、`REMINDER`、`TASK` 或 `CONSUMABLE`：

```bash
./scripts/test-downlink-presentation.sh http://127.0.0.1:8765 "" TASK
```

如果本机 PostgreSQL 暂未启动，可用不接收采集证据的最小模拟器验证眼镜链路：

```bash
node ./scripts/fake-downlink-server.mjs TASK
```
