# Agent 数据调用技术架构

> 文档版本：v0.2  
> 负责范围：账号授权、记忆查询、信号订阅、纠正、删除和 Agent Demo  
> 上游接口：[云端记忆平台架构](02-Memory-Platform-Architecture.md)  
> 总体边界：[分层技术架构](README.md)

## 1. 目标

Reality Memory Engine 是独立的云端记忆平台。手机 App、眼镜 Agent、主动式
Agent 和未来合作方都是它的客户端，不是记忆本体本身。

数据调用层负责：

- 让用户把 Reality 账号授权给某个 Agent。
- 让 Agent 查询对象、偏好、任务、活动和时间线。
- 让 Agent 订阅值得关注的状态变化。
- 让用户通过 Agent 发起纠正和遗忘。
- 对每次访问、订阅和修改命令进行审计。

Agent 不直接访问事件数据库，不直接写事实，也不默认获得原始图片、视频和音频。

## 2. 账号和授权关系

正确关系是：

```text
Reality Account
  -> Household / Owner
  -> Bound Devices
  -> Memory Events and Projections
  -> AgentGrant
  -> Agent Client
```

用户绑定的是 Reality 账号，不应要求每个 Agent 共享设备凭证或数据库密码。如果
主动式 Agent 运行在其他平台，它通过标准授权流程获得受限 Token。

`AgentGrant` 表示用户授予某个 Agent 的权限：

```json
{
  "schema_ref": "rme.agent-grant.v1",
  "grant_id": "uuid",
  "owner_id": "uuid",
  "agent_client_id": "proactive-agent-demo",
  "scopes": [
    "memory.query.objects",
    "memory.query.preferences",
    "memory.query.tasks",
    "memory.signal.subscribe"
  ],
  "household_ids": ["uuid"],
  "allowed_entity_types": ["OBJECT", "FOOD", "TASK"],
  "purpose": "PERSONAL_ASSISTANCE",
  "issued_at": "2026-07-24T10:00:00Z",
  "expires_at": "2026-08-24T10:00:00Z",
  "revocable": true
}
```

如果未来需要绑定 GitHub、日历、外卖或其他线上账号，这些是独立的数据源授权。
它们可以帮助 Memory Platform 做实体归因，但不能替代 Reality 账号。

## 3. API 分层

### 3.1 Query API：查询当前记忆

回答“现在是什么状态”：

- 某个物品最后出现在哪里。
- 某个耗材还剩多少。
- 用户是否表达过某项偏好。
- 当前有哪些未完成任务。
- 某个活动最近进展到哪里。

### 3.2 Timeline API：查询事件时间线

回答“发生过什么变化”：

- 钥匙最近三次位置变化。
- 某耗材从开封到接近用完。
- 某项偏好何时被表达、何时被纠正。
- 某个阅读活动的进度历史。

### 3.3 Signal API：订阅值得关注的变化

Signal 是经过规则判断后可供 Agent 消费的状态信号，例如：

- 耗材可能接近用完。
- 某个任务即将到期。
- 用户请求后续提醒。
- 某个高频使用物品位置长时间不确定。

Signal 不是 MemoryEvent。它是从事实和当前状态派生出的可过期通知候选。

### 3.4 Command API：受控纠正和遗忘

Agent 可以代表用户提交命令：

- “不是茶几，是玄关。”
- “我不是不喜欢胡辣汤，只是不喜欢这家。”
- “忘掉最近十分钟。”
- “删除关于这个物品的记忆。”

Command API 创建纠正或遗忘请求，由 Memory Core 和 Privacy Service 验证后转成
事件或删除工作流。Agent 不能直接提交任意 `MemoryEvent`。

## 4. 最小 API

### 4.1 查询

```text
POST /v1/memory/query
GET  /v1/entities/{entity_id}/timeline
GET  /v1/state/{projection_type}/{entity_id}
```

查询请求建议：

```json
{
  "query_id": "uuid",
  "natural_language": "我的钥匙上次在哪里？",
  "intent": "FIND_OBJECT",
  "subject": {
    "name": "钥匙"
  },
  "time_range": null,
  "response_detail": "SUMMARY_WITH_PROVENANCE"
}
```

查询结果建议：

```json
{
  "query_id": "uuid",
  "answer_type": "OBJECT_LOCATION",
  "answer": {
    "entity_id": "uuid",
    "display_name": "钥匙",
    "location": "客厅茶几右侧"
  },
  "confidence": 0.81,
  "freshness": {
    "observed_at": "2026-07-24T09:30:00Z",
    "age_seconds": 1800
  },
  "alternatives": [
    {
      "location": "玄关柜",
      "confidence": 0.34
    }
  ],
  "provenance_summary": {
    "supporting_event_ids": ["uuid"],
    "support_count": 2,
    "last_corrected_at": null
  },
  "limitations": [
    "这是最后一次可靠观察，不保证物品仍在原处"
  ]
}
```

Agent 应把限制自然地表达给用户，不能把 0.81 置信度说成绝对确定。

### 4.2 信号订阅

```text
POST   /v1/signal-subscriptions
GET    /v1/signals
POST   /v1/signals/{id}/ack
DELETE /v1/signal-subscriptions/{id}
```

订阅必须包含：

- 允许的信号类型。
- 家庭和实体范围。
- 最低置信度。
- 冷却时间和每日上限。
- 投递终端。
- 过期时间和撤销方式。

### 4.3 纠正

```text
POST /v1/memory/corrections
```

```json
{
  "command_id": "uuid",
  "target_event_id": "uuid",
  "correction": {
    "field": "location",
    "value": "玄关柜"
  },
  "user_confirmation": {
    "method": "EXPLICIT_TEXT",
    "confirmed_at": "2026-07-24T10:10:00Z"
  },
  "idempotency_key": "opaque"
}
```

平台验证后创建 `USER_CORRECTION`，再重算状态。

### 4.4 遗忘

```text
POST /v1/privacy/forget-requests
GET  /v1/privacy/forget-requests/{id}
```

遗忘必须返回分层状态：

- 设备 Evidence 删除。
- 云端 Evidence 删除。
- 候选和观察处理。
- MemoryEvent 失效或删除。
- Projection 重算。
- Agent 缓存和订阅影响。

## 5. Agent 允许和禁止的能力

| 能力 | 默认 | 原因 |
| --- | --- | --- |
| 查询结构化当前状态 | 允许，按 Scope | Agent 的主要使用方式 |
| 查询事件时间线 | 允许，按 Scope | 支持解释和回忆 |
| 订阅状态信号 | 允许，需用户授权和限流 | 支持主动服务 |
| 提交自然语言查询 | 允许 | Query Service 负责理解 |
| 提交用户明确纠正 | 允许，经 Command API | Memory Core 决定事实变化 |
| 提交删除或近窗遗忘 | 允许，经 Privacy API | 用户可控性 |
| 读取原始图片/音频 | 默认禁止 | Evidence 短期且高度敏感 |
| 直接写 MemoryEvent | 禁止 | 防止 Agent 越过事实门控 |
| 直接更新 StateProjection | 禁止 | 投影必须可重算 |
| 自动购物或发送消息 | 当前禁止 | 超出首阶段行动边界 |

若内部调试需要查看 Evidence，必须使用单独的短期调试授权，不能复用 Agent Token。

## 6. Query Service 与 Agent 的分工

### Query Service 负责

- 自然语言意图解析。
- 实体消歧和家庭权限过滤。
- 从 Projection、Event 和索引中取数。
- 返回置信度、新鲜度、备选和来源摘要。
- 对删除和纠正后的结果保持一致。

### Agent 负责

- 结合当前对话理解用户目的。
- 选择查询、时间线、订阅或纠正工具。
- 用适当措辞解释结果和不确定性。
- 在歧义影响结果时追问。
- 决定是否把 Signal 转成对用户有价值的提醒。

### Agent 不负责

- 自己重新分析原始媒体。
- 在长期对话上下文里复制整套记忆数据库。
- 通过提示词决定候选是否成为事实。
- 绕过用户授权访问其他家庭。

## 7. 主动式 Agent

主动式 Agent 的触发链：

```text
MemoryEvent
  -> StateProjection 更新
  -> Signal Rule
  -> MemorySignal
  -> 用户授权和订阅过滤
  -> 冷却、去重、时间和终端判断
  -> Agent 生成简短措辞
  -> 提醒投递
  -> 用户确认、忽略、追问或纠正
```

首阶段只允许提醒和建议。Agent 不能因为“洗衣液快用完”直接购买，也不能因为
“用户不喜欢这家胡辣汤”自动评价商家。

## 8. Demo 设计

Demo 应证明三个系统块真正连通，而不是只展示一个聊天页面。

### 8.1 推荐 Demo：找物

```text
眼镜采集前后图片
  -> 云端观察到钥匙和位置变化
  -> MemoryEvent：OBJECT_MOVED
  -> StateProjection：钥匙最后在茶几右侧
  -> Agent 查询：“我的钥匙在哪？”
  -> 返回位置、时间和置信度
  -> 用户纠正：“其实在玄关”
  -> 新增 USER_CORRECTION
  -> 再次查询得到新投影
```

这个 Demo 同时验证采集、沉淀、查询和纠正。

### 8.2 推荐 Demo：饮食偏好

```text
图片：用户正在吃胡辣汤
音频：“这个胡辣汤不好喝”
  -> 图片和音频原子观察
  -> 用餐 ActivityEpisode
  -> PREFERENCE_STATED
  -> Agent 查询：“我对胡辣汤有什么偏好？”
  -> 返回负面偏好及归因范围
```

如果没有订单数据，回答必须说明只知道“当前胡辣汤”或“胡辣汤类别”，不知道
具体商家。加入订单后可演示更精确的实体归因。

### 8.3 主动提醒 Demo

在静态测试数据中形成耗材下降事件：

```text
StateProjection：洗衣液 LOW
  -> Signal：LOW_CONSUMABLE
  -> Agent：“洗衣液可能快用完了，需要加入待办吗？”
```

Agent 只建议，不自动购买。

## 9. 调用结果的解释标准

每个面向用户的答案至少考虑：

- 结果是什么。
- 最后观察时间。
- 当前置信度。
- 是否存在备选。
- 是事实事件还是推断状态。
- 哪些信息已经过期或被删除。

示例：

> 我最后一次可靠看到钥匙是在今天 9:30，位置是客厅茶几右侧。这个判断来自两次
> 相近观察，但已经过去半小时，之后可能被移动过。

这比直接说“钥匙就在茶几上”更符合现实记忆的不确定性。

## 10. 权限 Scope

首版建议：

```text
memory.query.objects
memory.query.consumables
memory.query.preferences
memory.query.tasks
memory.query.activities
memory.timeline.read
memory.signal.subscribe
memory.correction.submit
memory.forget.submit
memory.audit.self.read
```

高风险能力单独授权：

```text
evidence.debug.read
memory.export
household.admin
```

Token 必须绑定：

- 用户和家庭。
- Agent Client。
- Scope。
- 用途。
- 过期时间。
- 可撤销 Grant。

## 11. 隔离和审计

每次调用记录：

- 哪个 Agent Client。
- 代表哪个用户。
- 使用哪个 Grant 和 Scope。
- 查询了哪些实体和时间范围。
- 返回了哪类结果。
- 是否提交纠正或遗忘。
- 是否触发提醒。

审计日志不得保存完整自然语言结果或敏感结构化值，除非产品明确需要且策略允许。

跨家庭访问在鉴权层拒绝，不能依赖 Query Prompt 提醒模型不要越权。

## 12. 缓存和删除一致性

Agent 平台不得把查询结果无限保存到自己的长期对话记录。

要求：

- 查询响应可以携带 `cache_until`。
- 删除和纠正触发缓存失效事件。
- Signal 过期后不得继续投递。
- Agent Grant 撤销后，停止订阅并清除受控缓存。
- 原始 Evidence 不进入 Agent 缓存。
- 导出或第三方保存需要单独授权。

## 13. 错误和降级

| 情况 | Agent 行为 |
| --- | --- |
| 没有可靠记忆 | 明确说不知道，不编造 |
| 有多个对象候选 | 追问用户指的是哪一个 |
| 位置已过期 | 返回最后观察和过期提示 |
| 记忆正在删除 | 不返回旧缓存，提示删除处理中 |
| Scope 不足 | 请求用户授权，不尝试绕过 |
| Memory Platform 暂时不可用 | 稍后重试，不把对话历史当作权威替代 |
| Signal 已过期 | 丢弃，不投递迟到提醒 |
| 纠正存在冲突 | 提示用户确认，保留原事件关系 |

## 14. Agent 工具接口

给 Agent 的工具应是高层结构化命令，而不是数据库查询：

```text
find_object(name, time_range?)
get_object_timeline(entity_id, limit?)
get_preference(subject, category?)
list_open_tasks(time_range?)
summarize_activity(time_range, activity_type?)
subscribe_signal(signal_type, filters, cooldown)
submit_correction(target_event_id, correction, confirmation)
request_forget(scope, confirmation)
```

每个工具映射到 Memory API，并由服务端再次做权限和 Schema 校验。

## 15. 当前阶段实现顺序

1. 实现 Agent Client 注册和测试用户授权。
2. 实现 `memory.query.objects` 或 `memory.query.preferences` 一条查询链。
3. Query 结果返回置信度、新鲜度、备选和来源摘要。
4. 做一个真实采集数据驱动的 Agent Demo。
5. 实现用户纠正并验证 Projection 重算。
6. 实现一个 Signal 订阅和提醒。
7. 实现 Grant 撤销和缓存失效。
8. 最后再扩展更多 Agent、第三方账号和主动服务。

## 16. 验收标准

- Agent 只能用受限 Token 调用 Memory API。
- Agent 无法直接写 MemoryEvent 和 StateProjection。
- 查询结果在纠正后发生可解释变化。
- 删除请求后，Agent 不再返回旧缓存。
- 同一 Agent 不能访问未授权家庭。
- 回答包含时间、新鲜度和必要的不确定性。
- Signal 受冷却、去重、过期和用户状态约束。
- 原始 Evidence 默认不暴露给 Agent。
- Demo 使用真实或版本化测试数据，不用手写最终答案冒充链路结果。

## 17. 与前两部分的依赖

```text
数据采集
  提供真实、可追溯、时间可对齐的 Evidence
        |
        v
数据沉淀
  形成 MemoryEvent 和 StateProjection
        |
        v
数据调用与 Agent
  查询、订阅、纠正和遗忘
```

Agent 团队可以先用固定的 Memory API Mock 并行开发，但 Mock 必须符合云端正式响应
Schema。等云端最小投影完成后，只替换数据源，不重写 Agent 对话逻辑。
