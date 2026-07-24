# Reality Memory v1 Contracts

本文档目录是
[`Reality-Memory-Multimodal-Data-Contract-v1.0.md`](../../../docs/engineering/Reality-Memory-Multimodal-Data-Contract-v1.0.md)
对应的 JSON Schema。

## 所有对象

| Schema | 中文对象 | 产生方 |
| --- | --- | --- |
| `capture-session.schema.json` | 采集会话 | 眼镜端 |
| `capture-intent.schema.json` | 采集意图 | 眼镜端 |
| `capture-window.schema.json` | 多模态采集窗口 | 眼镜端 |
| `capture-attempt.schema.json` | 每种模态的采集尝试 | 眼镜端 |
| `source-envelope.schema.json` | 来源信封 | 眼镜端/其他 Adapter |
| `evidence-item.schema.json` | 短暂证据 | 眼镜端/接入层 |
| `evidence-lifecycle-event.schema.json` | 证据生命周期事件 | 眼镜端和后端 |
| `atomic-observation.schema.json` | 原子观察 | 模态解析器 |
| `observation-bundle.schema.json` | 观察包 | 时间融合服务 |
| `activity-episode.schema.json` | 活动段 | 活动分段服务 |
| `memory-candidate.schema.json` | 记忆候选 | 候选生成器 |
| `memory-event.schema.json` | 记忆事实事件 | Memory Core |
| `state-projection.schema.json` | 当前状态投影 | Projection 服务 |

`common.schema.json` 只提供共享定义，不单独作为业务消息发送。

本目录当前不包含云端下行 `DeviceMessage`、提醒业务载荷或投递回执。这些内容仍在
review，不能用 `extensions` 绕过版本流程塞进现有 v1 对象。建议边界见
[`docs/architecture/04-Device-Cloud-Communication.md`](../../../docs/architecture/04-Device-Cloud-Communication.md)。

## 版本规则

- `schema_ref` 是消息里的稳定版本，例如 `rme.evidence-item.v1`。
- v1 内只允许增加可选字段或扩展枚举前先做消费者兼容检查。
- 删除字段、修改字段含义、改变时间单位或收紧已发布枚举必须升主版本。
- 厂商与实验字段只能放入 `extensions`，不能进入记忆核心判断而不声明版本。
- 消费者遇到未知主版本必须拒绝；遇到已声明可忽略的 `extensions` 可以继续。

## 开发使用

接入层应逐条校验对象，不要只校验最外层上传请求。示例文件
`examples/meal-preference-flow.json` 展示了一次图片、音频与 IMU 如何最终形成偏好状态。

Schema 使用 JSON Schema Draft 2020-12。CI 至少执行：

1. 所有 `.schema.json` 均为合法 JSON。
2. `$ref` 可以解析。
3. 正向样例通过。
4. 缺少时间、来源、证据引用或模型版本的反向样例失败。
5. `MemoryEvent` 的 `event_type` 不接受自由文本。
