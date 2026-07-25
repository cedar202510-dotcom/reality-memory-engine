# RV101 眼镜消息呈现契约 v0.1

> 状态：讨论稿，尚未冻结  
> 负责范围：后端或 Agent 如何把可呈现内容交给眼镜；眼镜如何选择固定组件、显示并回传投递结果  
> 不负责：记忆事实写入、采集策略、任意 HTML/CSS/SVG 下发

## 1. 核心边界

后端只下发“呈现意图和内容”，眼镜端负责全部视觉实现：

```text
Agent / 提醒决策
→ DeviceMessage
→ presentation.intent + title + body + speech_text
→ 眼镜本地固定组件
→ 文字显示 / 可选 TTS
→ DeliveryReceipt
```

后端不得下发颜色、字体、坐标、动画、SVG、HTML 或自由图标名称。这样可以保证同一类型
消息在每个固件版本上保持稳定，并避免模型生成不可读或越界界面。

佩戴告知、采集取消、权限异常属于眼镜本地运行状态，不经过 Agent 下发。

## 2. 消息信封

沿用后端已有的 `rme.device-message.v0`，呈现载荷使用
`rme.glasses-presentation.v0`：

```json
{
  "schema_ref": "rme.device-message.v0",
  "message_id": "2b832a93-cb97-4b1d-a57d-428cb639575d",
  "target_device_id": "37f6d7d6-c1ec-46e7-b46c-99b875611e72",
  "message_type": "REMINDER_SIGNAL",
  "created_at": "2026-07-25T10:00:00Z",
  "expires_at": "2026-07-25T10:10:00Z",
  "priority": "NORMAL",
  "payload_schema_ref": "rme.glasses-presentation.v0",
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
  },
  "delivery_policy": {
    "allow_text": true,
    "allow_tts": true
  }
}
```

## 3. 呈现意图

| `intent` | 中文含义 | 固定图标 | 允许来源 | 默认行为 |
| --- | --- | --- | --- | --- |
| `ANSWER` | 用户主动提问后的普通回答 | 顾问星芒 | Agent 对话 | 约 8 秒，可按策略播报 |
| `REMINDER` | 需要及时看到的重要提醒 | 圆形感叹号 | 提醒决策 | 约 8 秒，可按策略播报 |
| `TASK` | 明确任务或时间节点 | 勾选任务 | Agent / 任务信号 | 约 8 秒，右下角单击确认 |
| `CONSUMABLE` | 耗材余量与补充建议 | 耗材电量 | 耗材信号 | 约 6 秒，默认不播报 |
| `PRIVACY` | 隐私暂停、禁采空间或设备解绑 | 隐私盾牌 | 系统策略，不允许 Agent 伪造 | 保持到状态解除或用户确认 |
| `SYSTEM` | 必须让用户知道的设备异常 | 圆形感叹号 | 眼镜 Runtime / 系统服务 | 按故障状态保持 |

找东西、偏好查询、阅读进度等普通问答都使用 `ANSWER`。后端只返回能够确认的文字，
不生成没有位置基础的方向箭头或导航指令。

未知意图不得自由渲染：眼镜应降级为 `ANSWER`，并在回执 `detail` 中记录
`fallback_intent`。

图标名称不是接口字段。它们是眼镜端资源，由 `intent` 在本地映射：

| `intent` | 眼镜端本地资源 | 组件 |
| --- | --- | --- |
| `ANSWER` | `icon_advisor_spark` | `MessageOverlay` |
| `REMINDER` | `icon_alert_circle` | `MessageOverlay` |
| `TASK` | `icon_task_check` | `MessageOverlay` |
| `CONSUMABLE` | `icon_consumable_level` | `MessageOverlay` |
| `PRIVACY` | `icon_privacy_shield` | `MessageOverlay` |
| `SYSTEM` | `icon_alert_circle` | `MessageOverlay` |

后端不传资源名。替换图标、调整线宽或适配新固件只修改眼镜端，不需要改变 Agent 输出。

## 4. 字段限制

| 字段 | 必需 | 限制 |
| --- | --- | --- |
| `presentation.intent` | 是 | 只能使用上表枚举 |
| `presentation.title` | 是 | 1–42 个字符；结论优先，不放模型推理过程 |
| `presentation.body` | 否 | 最多 80 个字符；只放一条必要依据或补充 |
| `presentation.speech_text` | 否 | 最多 100 个字符；仅在 `allow_tts=true` 时可播报 |
| `presentation.interaction` | 是 | `NONE` / `DISMISS` / `ACKNOWLEDGE` |
| `source.kind` | 是 | `AGENT_REPLY` / `MEMORY_SIGNAL` / `SYSTEM_POLICY` |
| `source.reference_id` | 否 | 对话、信号或策略编号，用于审计，不直接显示 |
| `correlation_id` | 是 | 串联 Agent 结果、设备消息和回执 |

眼镜必须在本地再次检查长度、过期时间、允许的来源与意图组合。超出限制时截断显示或
拒绝呈现，不能让任意后端内容突破可视区域。

## 5. 固定布局

所有云端下发消息共用一个布局骨架，只有图标与文字变化。同一语义图标锚点不随
`intent` 改变。交互动作独立放在右下角，不作为第三行正文：

```text
480 × 640 画布
图标中心：x=76，y=235
图标尺寸：24 × 24
左侧语义线：x=40，y=215–355
标题起点：x=64，y=285，最多 3 行
确认动作：右下角固定 20 × 20 圆形勾选图标，下方弱化显示“单击”
取消动作：右下角固定 20 × 20 圆形叉号图标，下方弱化显示“单击”
颜色：#00FF00
背景：#000000（不发光）
```

佩戴告知是本地专用的居中组件：更大的感知圆环、向外扩散的单绿水纹、品牌文案和取消
提示。它不占用云端消息的左对齐布局。

`ACKNOWLEDGE` 只表示用户已经看见并关闭本次呈现，不代表任务已经完成，也不能修改
`MemoryEvent`。`DISMISS` 只关闭界面。没有动作的消息使用 `NONE`，到时自动消失。

## 6. 回执

眼镜按现有 `DeliveryReceipt` 接口回传：

| 状态 | 触发时机 |
| --- | --- |
| `RECEIVED` | 消息已落入眼镜本地队列并通过基础 Schema 校验 |
| `PRESENTED` | 对应组件已经实际进入可见状态 |
| `SPOKEN` | TTS 实际完成，不是仅调用 `speak()` |
| `DISMISSED` | 用户单击关闭 |
| `EXPIRED` | 到达或排队期间过期，未呈现 |
| `FAILED` | Schema、渲染、后台拉起或 TTS 失败 |

同一 `message_id` 必须幂等。眼镜重连收到重复消息时不重复弹出已经进入终态的内容。

## 7. 后端与 Agent 约束

Agent 只产生候选内容；提醒决策层负责确认是否值得下发、目标设备、优先级、TTL 和
`delivery_policy`。`PRIVACY` 与 `SYSTEM` 只能由受信任的系统服务生成。

后端接口验证至少包括：

1. `payload_schema_ref` 与载荷结构一致。
2. `intent` 与 `source.kind` 的组合合法。
3. 标题、正文和播报文字不超长。
4. `allow_tts=false` 时忽略 `speech_text`。
5. 消息必须绑定已授权的目标设备。

## 8. 与当前代码的关系

当前后端已经实现：

- `rme.device-message.v0` 通用信封。
- `REMINDER_SIGNAL` 的落库、WebSocket 推送、轮询补投与过期处理。
- `allow_text` / `allow_tts` 投递限制。
- `RECEIVED`、`PRESENTED`、`SPOKEN`、`DISMISSED`、`EXPIRED`、`FAILED` 回执。

当前仍缺：

- 后端对 `rme.glasses-presentation.v0` 的专用 Schema 与来源组合校验。
- Agent / 提醒决策层把自然语言结果转换成 `intent` 的受约束输出。
- 眼镜端的下行消息消费者、本地图标映射、文本长度保护和回执上报。
- 真机验证消息可见、TTS 完成时点、单击确认和离线重投。

因此这份文档冻结的是下一步联调边界，不表示下行链路已经在眼镜 APK 中完成。
