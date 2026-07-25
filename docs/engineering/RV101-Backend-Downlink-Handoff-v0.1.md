# RV101 后端消息下发交接说明 v0.1

> 状态：联调准备稿  
> 目标：让后端或 Agent 把回答、提醒和系统状态发到 RV101，由眼镜使用固定组件呈现并回传结果  
> 呈现字段详见
> [`RV101-DOWNLINK-PRESENTATION-CONTRACT-v0.1.md`](../../apps/reality-memory-glasses/docs/RV101-DOWNLINK-PRESENTATION-CONTRACT-v0.1.md)

## 1. 当前结论

后端的通用通信层已经存在，但真机下发闭环尚未完成：

- 已有消息落库、WebSocket 实时推送、离线轮询补投、过期处理和投递回执 API。
- 已有 `rme.device-message.v0` 信封和 `delivery_policy`。
- `payload` 目前还是任意 JSON，尚未校验 `rme.glasses-presentation.v0`。
- 眼镜 APK 目前没有 WebSocket / inbox 消费者，暂时不能直接收到这些消息。
- `/internal/v1` 当前依赖本机或可信内网，没有设备令牌，不能直接暴露到公网。

因此“后端 API 已有”不等于“Agent 回答已经能显示到真机”。下一步要同时补后端业务载荷
校验和眼镜端接收器。

## 2. 完整链路

```text
Agent 回答 / 提醒决策
→ POST /internal/v1/devices/{device_id}/messages
→ device_messages 落库
→ WebSocket 实时推送
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
      "interaction": "ACKNOWLEDGE"
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
`presentation.intent` 区分普通回答、提醒、任务、耗材和隐私状态。这样不用先修改数据库
和消息类型枚举。后续如果要在通信层区分问答与提醒，再单独评审 `AGENT_RESPONSE`。

创建成功后，响应中的关键字段：

| 字段 | 含义 |
| --- | --- |
| `message.message_id` | 幂等编号；眼镜去重和回执必须使用 |
| `message.created_at` / `expires_at` | 服务端生成的创建与过期时间 |
| `message.payload` | 原样交给眼镜消费者的呈现载荷 |
| `message.delivery_policy` | 是否允许文字和 TTS |
| `pushed_connections` | 当前即时推送成功的连接数；`0` 只代表设备不在线，消息仍已落库 |

## 4. 眼镜接收消息

### 实时主路径

```text
WS /internal/v1/devices/{device_id}/stream
```

连接建立后，后端会先发送积压消息，再推送新消息。眼镜需要：

1. 每隔小于服务端空闲超时时间发送 `{"type":"ping"}`。
2. 收到消息先按 `message_id` 去重，再校验过期时间和 `payload_schema_ref`。
3. 回 `RECEIVED` 后排入本地呈现队列。
4. 实际可见后回 `PRESENTED`；TTS 完成后回 `SPOKEN`。
5. 用户单击右下角确认控件后回 `DISMISSED`。
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

### 轮询兜底

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
    "interaction": "SINGLE_CLICK"
  },
  "device_reported_at": "2026-07-25T10:00:08Z"
}
```

## 5. 后端需要实现

1. 新增 `GlassesPresentationPayload` Pydantic 模型，并在
   `payload_schema_ref=rme.glasses-presentation.v0` 时强制校验。
2. 校验 `intent`、`source.kind`、文字长度、TTL 和 `allow_tts` 的组合。
3. 把 Agent 回答或提醒信号转换成受约束载荷，再调用统一的消息创建服务；不要让模型直接
   生成 HTML、SVG、坐标或颜色。
4. 保持 `message_id` 至少一次投递和幂等回执语义。
5. 增加设备身份、短期 device token 和“设备只能读取自己的消息”校验。
6. 多实例部署前把进程内 `DeviceHub` 替换为 Redis pub/sub 或配置粘性路由。

短期联调可以直接调用现有 HTTP 创建接口。正式接入同一后端进程的 Agent / Signal
Worker 时，应抽出共享的 `create_device_message()` 应用服务，避免服务内部绕 HTTP
调用自己。

## 6. 眼镜端需要实现

1. 保存 `backend_base_url`、`device_id` 和后续的设备凭证。
2. 实现 WebSocket 长连、心跳、断线重连与 inbox 轮询兜底。
3. 实现 `intent → 本地图标 + 固定布局` 映射。
4. 将 `ACKNOWLEDGE` 显示为右下角圆形勾选图标，将 `DISMISS` 显示为圆形叉号；动作提示
   不进入正文。
5. 实现 TTL、队列优先级、文本截断、重复消息和未知意图降级。
6. 实际显示和播报后发送对应回执，并把失败原因写入 `detail`。

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

1. 设备在线时创建消息，`pushed_connections=1`，两秒内出现对应固定组件。
2. 普通回答与提醒使用不同图标，但图标位置和正文骨架不跳动。
3. `ACKNOWLEDGE` 只在右下角显示勾选图标与弱化“单击”，不成为第三行正文。
4. 设备依次回传 `RECEIVED`、`PRESENTED`，可选 TTS 完成后回 `SPOKEN`。
5. 用户确认后回 `DISMISSED`，相同 `message_id` 重投不再次显示。
6. 眼镜离线时消息落库；重连通过 WebSocket backlog 或 inbox 补投。
7. 已过期消息不显示、不播报；未知意图降级为 `ANSWER` 并记录原因。
8. 未授权设备不能读取、确认或伪造其他设备的消息。
