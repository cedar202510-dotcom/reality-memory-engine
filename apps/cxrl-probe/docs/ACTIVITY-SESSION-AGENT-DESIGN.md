# Activity Session Agent 设计

## 1. 核心判断

这部分确实应被视为一个有状态的 Agent，但“Agent”指的是我们后端持续维护活动状态的服务角色，不等于第一版必须使用多 Agent 框架。

第一版建议：

```text
CXR-L Observation
  -> Session Orchestrator（确定性状态机、计时器、存储）
  -> Vision/Reasoning Model（判断目标、动作、边界证据）
  -> Strict JSON Schema
  -> Boundary Policy（阈值、迟滞、合并/拆分）
  -> ActivitySession + ActionSegment
```

模型负责语义判断，程序负责事实、时间、ID、状态迁移和隐私约束。这样比让模型自由维护全部记忆更可控，也更容易复盘误判。

## 2. 三层数据，而不是“一张图一条记忆”

### Observation

一次传感器证据，例如一张眼镜照片、佩戴状态、时间、手机区域和上一帧差异。Observation 是不可变事实。

### ActionSegment

几秒到几分钟的细动作，例如：

- 拿出西红柿
- 切菜
- 开火
- 搅拌锅里的汤
- 等水烧开

Segment 可以变化，但仍服务于同一个粗目标。

### ActivitySession

人当前在推进的可解释目标，例如：

- 做晚饭
- 吃饭
- 收拾厨房
- 出门买菜
- 洗漱准备睡觉

所以“在厨房做饭一小时”通常是一个 Session；切菜、炒菜、装盘是其中多个 Segment。

## 3. Session 不是按房间机械切分

位置变化只是边界证据，不是边界本身。

例如从厨房台面走到冰箱，再到灶台，空间发生变化，但目标仍是“做晚饭”，应继续同一 Session。相反，一个人在厨房放下锅、拿起清洁用品并开始擦地，位置不变但目标已经变化，可能应开启“清洁厨房”Session。

推荐边界信号与初始权重：

| 信号 | 权重 | 含义 |
|---|---:|---|
| `goal_shift` | 0.40 | 当前行为是否不再服务于原目标 |
| `space_shift` | 0.15 | 房间/场景是否发生持续变化 |
| `object_set_shift` | 0.15 | 活跃物体集合是否整体替换 |
| `social_context_shift` | 0.10 | 互动对象或社会情境是否改变 |
| `temporal_gap` | 0.10 | 是否存在无法由任务等待解释的空档 |
| `prediction_error` | 0.10 | 新观察是否明显违背当前 Session 的下一步预测 |

初始阈值只是待实测参数：

- `< 0.45`：继续当前 Session。
- `0.45 - 0.72`：进入待确认边界，再观察 1-2 次。
- `>= 0.72`：候选新 Session；通常要求连续两次成立后提交。

显式用户停止、隐私场景或设备长时间离线属于硬信号，可绕过普通阈值。

## 4. 迟滞与可撤销边界

不能让一次模糊图片立刻结束 Session。Orchestrator 保存：

- `boundary_candidate_since`
- `confirming_observation_ids`
- `previous_session_snapshot`
- `merge_deadline`

候选切分先处于 `tentative`。后续证据回到原目标时撤销切分；持续支持新目标时才提交。这样可以处理“走到门口拿个快递又回来做饭”。

## 5. 中断不是结束

Session 状态：

```text
tentative -> active -> suspended -> active -> closed
```

例子：

1. `做晚饭` 为 active。
2. 电话响起，用户接电话，做饭变为 suspended。
3. 建立短 Session `接电话`。
4. 电话结束，视觉和物体上下文重新匹配厨房状态。
5. 关闭 `接电话`，恢复原 `做晚饭`，而不是新建第二个做饭 Session。

第一版限制一个 primary active Session，并保留最多三个 suspended Session。恢复时比较目标、场景、物体和时间距离。

## 6. 结束边界

### 强结束

- 用户显式说“结束记录”。
- 目标完成且出现结果状态，例如饭菜装盘并离开厨房去餐桌。
- 隐私策略要求立即停止。
- 眼镜摘下或断连超过可配置超时。

### 软结束

- 目标置信度持续下降。
- 新目标置信度持续高于旧目标。
- 场景、物体、人物同时发生稳定替换。
- 长时间没有可解释的进展。

等待不等于结束。“烤箱烤 30 分钟”“水烧开前看手机”属于当前目标的等待 Segment，只要目标和关键物体关系仍然成立。

建议 Phase 0 默认值：

- 摘下眼镜或断连：立即 `suspend`。
- 10 分钟未恢复：候选 `close`。
- 普通语义边界：至少 2 个连续 Observation 确认。
- 30 秒采样只用于链路验证；正式产品应由变化检测动态调整为 5-120 秒。

## 7. 日常生活开放分类

第一阶段不考虑工作场景，可用以下弱先验帮助模型，但不要做封闭分类：

- 做饭、备餐、吃饭、饮水
- 清洁、洗衣、整理物品、家庭维护
- 洗漱、洗澡、穿衣、护肤
- 购物、取快递、日常跑腿
- 步行、通勤、短途出行
- 阅读、看视频、游戏、音乐、手工
- 社交、打电话、照护家人
- 找东西、收纳、准备出门
- 休息、发呆、午睡、准备睡觉

小说和日记可以帮助发现行为组合，但它们会压缩、重排或省略动作，不适合作为边界真值。更可靠的初始参考是无脚本第一视角数据集和人类事件分段研究。

## 8. 为什么第一版不用“自由运行的多 Agent”

使用一次 Responses API 调用不等于无状态。每次调用输入应是：

```text
新 Observation
+ 当前 Session 的紧凑快照
+ 最近 3-8 个 Segment 摘要
+ 少量相关长期记忆
```

输出严格匹配 `schemas/activity-session-update.schema.json`。数据库中的 canonical state 才是真实状态。

可以用 `previous_response_id` 或 Conversation 保存连续性，但不能因此不做压缩：历史输入仍会占用上下文和成本。只有出现多工具循环、多个专家分支、复杂人工审批时，再引入 Agents SDK。

## 9. Phase 0 验证指标

- 授权成功率。
- CXR 与蓝牙双链路建立时间。
- CustomView 建立时间。
- 拍照请求成功率与回调延迟。
- 30 秒采样在 30 分钟内的丢帧率。
- 佩戴/摘下事件准确性。
- 图片不落盘策略是否成立。
- 10 个手工标注的日常 Session 中，误切分和漏切分各是多少。

## 10. 研究依据

- [Event Segmentation Theory](https://bpb-us-e2.wpmucdn.com/sites.wustl.edu/dist/e/952/files/2017/09/kurbytics08-v5bjg2.pdf)：事件模型在预测误差上升时更新；目标、空间、因果等变化可形成边界，且活动天然具有粗细层级。
- [EPIC-KITCHENS](https://arxiv.org/abs/2005.00343)：无脚本第一视角厨房活动，使用带起止时间的 verb+noun 动作片段，适合参考 Segment 层。
- [Ego4D](https://arxiv.org/abs/2110.07058)：长时间第一视角活动需要较长上下文，并以动作序列推进目标。
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)：用 JSON Schema 约束模型输出。
- [OpenAI Conversation State](https://developers.openai.com/api/docs/guides/conversation-state)：可延续上下文，但仍应自己维护紧凑状态。
- [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents)：当出现工具循环和复杂编排时再采用。
