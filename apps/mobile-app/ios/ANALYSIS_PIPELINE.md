# Analysis Pipeline Boundary

## Decision

第一阶段不把手机 App 设计成长期运行的 LLM Agent。手机端承担确定性的 Reality Edge 职责：

- 建立和结束采集 Session。
- 执行固定间隔、暂停、断连和佩戴策略。
- 生成图片 Evidence 与无媒体审计元数据。
- 将待分析项写成稳定、可重试的结构化清单。

分析端拆成两层：

1. `Evidence Selector`（证据筛选器）：在短期 TTL 内做图片质量检查、短窗相似度聚类和代表帧选择。
2. `Vision Extractor`（图片解析器）：只对选中的图片做结构化多模态模型调用。
3. `Session Analysis Agent`（会话分析器）：读取同一时间窗内的多张 ObservationCandidate，维护活动上下文，判断语义片段边界，处理冲突并生成候选事件。

## Information Gain

连续采集产生的是候选证据，不是等量的记忆。处理规则是：

- 精确重复、不可用图片直接跳过解析。
- 视觉相近的图片先归入同一个短时窗口，只选择少量清晰代表帧。
- 轻微转头可能导致像素明显变化，因此不能只靠图片哈希决定是否有新信息。
- 图片解析后继续比较对象集合、对象关系、文字和活动阶段；没有语义增量的观察只作为既有状态的重复支持。
- 同窗语音可以提高图片优先级。例如用户说“这个胡辣汤不好喝”时，应优先保留时间最近、能看清餐品或包装的图片。
- 原始图片完成筛选和结构化后按 TTL 删除；长期层只保留观察、选择记录、来源引用和删除回执。

推荐的处理顺序：

```text
关注窗口内的连续图片
  -> 质量筛选
  -> 短窗视觉相似度聚类
  -> 代表帧选择
  -> 图片结构化解析
  -> 语义增量判断
  -> ObservationBundle（同一变化的观察包）
  -> MemoryCandidate（记忆候选）
```

## Why Not One Long Prompt

每次都把整个历史重新上传给单次 API，会造成成本随 Session 长度增长，并且难以重试、去重和审计。把单图抽取和跨帧编排分开后：

- 单图调用可以按 `evidence_id` 幂等重试。
- 原始图片可在抽取完成后按 TTL 删除。
- Agent 上下文只保留结构化候选和短摘要。
- Session 边界变化不需要重新处理全部图片。
- 模型输出仍然只是 Candidate，不能直接修改长期记忆。

## Two Session Layers

### Capture Session

由设备端管理，边界是明确且安全的：

- 用户开始、暂停、恢复或结束。
- 眼镜摘下时结束。
- BLE 断开或 Custom View 关闭时暂停。
- iOS 后台或进程失活时默认不承诺继续采集。

### Semantic Episode

由分析 Agent 在 Capture Session 内切分。一段做饭可以是一个 Capture Session，但包含准备食材、切菜、烹饪和装盘等多个 Semantic Episode。

Episode 边界综合以下信号：

- 地点或空间语义显著变化。
- 主体对象集合显著变化。
- 动作目标或任务阶段变化。
- 长时间静止、证据空窗或用户显式语音。
- 当前候选无法由既有活动上下文解释。

首版不要仅凭一帧图片结束 Episode。建议要求连续两次观测支持新意图，或使用显式事件作为强边界。

## Data Flow

```text
ProbeCaptureSession
  -> ProbeCaptureObservation
  -> Evidence
  -> Vision Extractor
  -> ObservationCandidate
  -> Session Analysis Agent
  -> SemanticEpisode
  -> MemoryEvent candidate
  -> validation / conflict resolution
  -> StateProjection
```

## First Analysis Contract

Session Agent 的最小输入不直接依赖 CXR-L 类型：

```json
{
  "session_id": "uuid",
  "observation_id": "uuid",
  "captured_at": "ISO-8601",
  "trigger": "PERIODIC",
  "device_context": {
    "device_summary": "Glasses_3616",
    "wearing_status": "WORN"
  },
  "media": {
    "local_ref": "opaque temporary reference",
    "ttl_until": "ISO-8601"
  }
}
```

单图模型必须返回经过 JSON Schema 校验的 Candidate：

```json
{
  "scene": {
    "place_type": "kitchen",
    "activity": "meal_preparation",
    "confidence": 0.82
  },
  "objects": [],
  "state_changes": [],
  "privacy_labels": [],
  "quality": {
    "usable": true,
    "reason": null
  }
}
```

Session Agent 输出 Episode 和 Candidate，不直接输出确定事实：

```json
{
  "episode_action": "CONTINUE",
  "episode_id": "episode_uuid",
  "activity_intent": "prepare_dinner",
  "confidence": 0.78,
  "supporting_observation_ids": ["uuid"],
  "memory_candidates": []
}
```

## Next Implementation Slice

1. 用 5/15/30/60 秒档位完成前台真机稳定性实验。
2. 从 App 沙盒导出 `session.json` 和明确授权的短样本。
3. 选取一个受控家庭场景，用单图 Vision Extractor 生成合法 Candidate。
4. 用 3 至 10 张连续图片验证 Episode 的继续、切换和结束。
5. 验证结构化完成后删除图片，保留 Candidate、审计和删除回执。
