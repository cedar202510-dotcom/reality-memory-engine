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
| `REMINDER` | 需要及时看到的重要提醒 | 圆形感叹号 | 提醒决策 | 有动作时约 12 秒，可显示“知道了” |
| `TASK` | 明确任务或时间节点 | 勾选任务 | Agent / 任务信号 | 有动作时约 12 秒，可显示“完成” |
| `CONSUMABLE` | 内部兼容枚举；用户侧称“采购提醒” | 购物袋 | 采购信号 | 有动作时约 12 秒，可显示“加入采购清单” |
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
| `CONSUMABLE` | `icon_purchase_bag` | `MessageOverlay` |
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
| `presentation.interaction` | 是 | 无操作时为字符串 `NONE`；有操作时为 `{type, action_id}` |
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
左侧语义线：x=40，y=230–350
标题起点：x=64，y=285，最多 3 行
主动作：右下角紧凑描边按钮，只显示一个图标和明确动作文字
颜色：#00FF00
后台提醒：纯黑不透明独立显示层，遮住 Rokid 首页内容
显示层底色：#000000（单绿光显示中不发光）
```

佩戴告知是本地专用的居中组件：更大的感知圆环、向外扩散的单绿水纹、品牌文案和取消
提示。它不占用云端消息的左对齐布局。

普通回答使用 `NONE`，到时自动消失。需要用户明确表达时，交互对象只能使用固定动作：

| `interaction.type` | 眼镜固定文字 | 允许意图 | 含义 |
| --- | --- | --- | --- |
| `ACKNOWLEDGE` | `✓ 知道了` | `REMINDER`、受信系统消息 | 用户明确确认提醒 |
| `COMPLETE_TASK` | `✓ 完成` | `TASK` | 请求后端把对应任务标为完成 |
| `ADD_TO_SHOPPING_LIST` | `＋ 加入采购清单` | `CONSUMABLE` | 请求加入清单，不触发购买 |
| `DISMISS` | `× 关闭` | `PRIVACY`、`SYSTEM` | 只关闭本次呈现 |

`action_id` 是后端生成的幂等动作编号，所有有操作的消息都必须提供。Agent 不能下发
自由按钮文字，眼镜根据 `interaction.type` 映射固定中文和图标。超时关闭不执行动作。
用户动作先作为可审计回执落库，再由受约束的后端服务更新任务或采购清单；它不能直接
修改 `MemoryEvent`，也不能自动购买。

## 6. 回执

眼镜按现有 `DeliveryReceipt` 接口回传：

| 状态 | 触发时机 |
| --- | --- |
| `RECEIVED` | 消息已落入眼镜本地队列并通过基础 Schema 校验 |
| `PRESENTED` | 覆盖层窗口已经附着并完成首帧，或 Activity 已确认渲染该消息 |
| `SPOKEN` | TTS 实际完成，不是仅调用 `speak()` |
| `DISMISSED` | 超时关闭，或用户执行主动作后关闭 |
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
- `rme.glasses-presentation.v0` 的字段、来源组合、文字长度和自由样式拦截。
- Agent Gateway 自动把普通回答转换为 `ANSWER`，把低耗材信号转换为
  `CONSUMABLE + ADD_TO_SHOPPING_LIST`，并通过受限 Agent scope 写入消息队列。

当前眼镜 Debug APK 0.1.7 已实现：

- 后端设备自注册与 `device_id` 持久化。
- 佩戴感知期间每 3 秒轮询 inbox。
- 本地图标映射、固定布局、文本长度保护、队列和 `message_id` 去重。
- 后台消息使用短时纯黑不透明 `SYSTEM_ALERT_WINDOW` 独立显示层，遮住 Rokid 首页。
- 收到、显示层首帧、TTS 完成、用户动作或超时关闭的回执；视觉层未确认时回
  `FAILED/VISUAL_UI_NOT_CONFIRMED`，不伪报 `DISMISSED`。

2026-07-25 RV101 真机已验证 HTTP 链路能够返回：

```text
RECEIVED -> PRESENTED -> DISMISSED
```

`dumpsys window` 同时确认 `RealGitPresentation` 为 `480×640`、
`TYPE_APPLICATION_OVERLAY`、`HAS_DRAWN`。RV101 的 `adb screencap` 不会合成单绿光
HUD 的实际发光层，因此黑色抓图不能单独作为“未显示”的判据。

当前仍缺：

- WebSocket 低延迟客户端；当前先用 HTTP inbox 跑通，现有 WebSocket API 保留。
- 设备令牌和“设备只能读取自己的消息”鉴权。
- 正式版覆盖层授权引导或 Rokid 系统白名单；Debug 安装脚本当前通过 ADB 开启权限。
- 后端消费 `COMPLETE_TASK` 与 `ADD_TO_SHOPPING_LIST` 动作回执并更新对应业务对象。
- 真机人工确认各语义图标、TTS 完成时点、物理单击广播和离线补投。

因此这份文档已经对应可构建且完成一次消息闭环真机验证的 0.1.7 代码；后台轮询
稳定性、TTS 时点、物理单击和离线补投仍必须按测试计划继续验证。
