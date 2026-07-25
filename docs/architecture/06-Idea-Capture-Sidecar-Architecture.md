# 灵感旁路技术架构（Idea Capture Sidecar）

> 文档版本：v0.1
> 负责范围：灵感 / 问题 / 任务的捕捉、存储、状态管理与查询
> 上游接口：[数据采集技术架构](01-Data-Capture-Architecture.md)、[设备与云端通信](05-Device-Cloud-Communication.md)
> 并列接口：[云端记忆平台架构](02-Memory-Platform-Architecture.md)（**旁路，不共用事实门控**）
> 当前状态：方案参考，待 review。**不改动 `contracts/reality-memory/v1/` 任何已冻结契约**

## 术语约定

本文档中的「**主链路**」「**灵感链路**」指**处理流水线**（感知 → 候选 → 门控 → 事件），
**与区块链无关**。本文档不涉及任何区块链内容。

[07 号文档](concepts/07-Idea-Provenance-and-Encrypted-Matching.md) 中的「链 / 上链 / 链上」
才是指区块链。两份文档相邻且互相引用，不要混读。

---

## 1. 为什么是旁路，而不是接进主链路

主链路的设计前提是「模型对模糊世界的被动观察不可信」，PRD §4.2 明确要求
「模型产生候选，事件构成事实」。灵感的前提正好相反：它是**单次、自愿、第一人称的言语行为**。
说了就是说了，不存在「需要第二次观测来确认用户确实有过这个想法」。

把灵感接进主链路，会在四个具体位置撞墙：

| # | 冲突点 | 代码位置 | 后果 |
|---|---|---|---|
| 1 | 置信度门控要求 `aggregate ≥ 0.85` 才升级为事实 | [gate.py:99](../../services/memory-platform/app/memory/gate.py:99) | ASR 稍差或 LLM 抽取置信度偏低，灵感永远卡在 PENDING，用户说了但系统没有 |
| 2 | 接受候选必调 `resolve_entity(name=object_text)`，强绑物理实体 | [gate.py:108](../../services/memory-platform/app/memory/gate.py:108) | 「这个东西可以做成 X」不指向任何 Entity，会被强行捏造出一个 `type="object"` 的垃圾实体 |
| 3 | 冲突检测基于 `object_text + location` 的互斥判定 | [gate.py:43](../../services/memory-platform/app/memory/gate.py:43) | 对灵感无意义；两条无关灵感不会冲突，但也不会得到任何有价值的冲突语义 |
| 4 | 事实沉淀后 Evidence 按 TTL 删除（PRD §4.1） | [models/__init__.py:116](../../services/memory-platform/app/models/__init__.py:116) | 灵感的价值恰恰在原始表述——「我当时是怎么说的」，删掉就废了 |

**一句话结论**：主链路是为「宁缺勿滥」设计的，灵感链路必须「宁滥勿缺」。
两种相反的失败偏好不能共用同一个门。

### 1.1 那为什么还要长在这个项目里

因为灵感捕捉真正贵的部分不是存储，是**「想到的那一刻手不方便」**。
眼镜恰好解决这一件事。旁路复用采集、上行、隐私、授权、审计基建，
但不复用事实门控——这是本文档的全部设计立场。

---

## 2. 边界：复用什么，不复用什么

| 环节 | 是否复用主链路 | 说明 |
|---|---|---|
| CaptureSession / CaptureIntent | 复用 | 灵感捕捉是一种采集意图，不是新设备形态 |
| SourceEnvelope | 复用 | 通过 `meta.capture_purpose="idea"` 区分，**不扩展 `trigger` 枚举**（见 §4.2） |
| EvidenceItem | 复用 | 但保留策略不同（§6） |
| 上行通道 / 幂等 / 中继 | 复用 | 零改动 |
| ASR（Transcriber） | 复用 | `app/asr/` 原样使用 |
| AudioAsset | 复用 | transcript 是灵感的长期表示 |
| **AtomicObservation** | ❌ 不复用 | 灵感不是「观察」，没有 predicate/subject/object 三元组语义 |
| **MemoryCandidate → Gate** | ❌ 不复用 | 核心分歧点，见 §1 |
| **Entity / resolve_entity** | ❌ 不复用 | 灵感不绑物理实体 |
| **MemoryEvent / StateProjection** | ❌ 不复用 | 独立的 `idea_events` / `idea_projections` |
| AgentGrant / scopes | 复用 | 新增 `ideas:read` / `ideas:write` scope |
| AuditRecord | 复用 | 同一张审计表 |
| DeletionRequest / DeletionJob | 复用 | 新增 `idea` 子系统 |

---

## 3. 数据模型

四张新表。命名与主链路保持同构（capture → record → event → projection），
但物理上完全独立，不共享外键到 `entities` / `memory_events`。

### 3.1 `idea_captures`（一次捕捉）

一次「按下并说话」= 一条。它是原始产物的锚点，不是内容本体。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `household_id` | FK households | 隔离域与主链路一致 |
| `actor_id` | UUID | 捕捉者（灵感强绑个人，不是家庭共有——见 §11-Q3） |
| `envelope_id` | FK source_envelopes, null | App 手输时为空 |
| `evidence_item_id` | FK evidence_items, null | 音频证据 |
| `audio_asset_id` | FK audio_assets, null | ASR 结果 |
| `capture_channel` | String(32) | `glasses_button` / `wake_word` / `app_text` / `app_voice` |
| `raw_text` | Text | **全文转写，永不为空**（手输时即输入原文） |
| `keep_original_audio` | Boolean, default False | 显式保留原声，见 §6.2 |
| `parse_status` | String(32) | `RAW` / `STRUCTURED` / `PARSE_FAILED` |
| `created_at` | timestamptz | |

> **不变量**：`raw_text` 一旦写入不可修改。所有结构化解析都是它的**衍生物**，
> 解析失败或模型改版都不能损坏原文。这是与主链路最重要的哲学差异。

### 3.2 `idea_records`（条目本体，append-only 身份）

一次捕捉可以产生多条记录（「我有两个想法，第一…第二…」）。
记录一旦创建，`id` 和 `content_hash` 不再变化。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `capture_id` | FK idea_captures | |
| `household_id` / `actor_id` | | 冗余，便于隔离查询 |
| `kind` | String(16) | `IDEA` / `QUESTION` / `TASK` / `NOTE` |
| `title` | String(256) | LLM 生成或用户输入；解析失败时取 `raw_text` 前 64 字 |
| `body` | Text | 该条目对应的原文片段 |
| `tags` | JSONB | LLM 建议标签 + 用户标签 |
| `embedding` | vector | 语义检索用。**注意：不出本地信任域，见 07 号文档 §3** |
| `content_hash` | String(64) | `sha256(canonical_json(kind,title,body,created_at,salt))` |
| `hash_salt` | String(64) | 高熵随机盐。**必须有**：idea 文本熵低，无盐哈希可被字典枚举 |
| `parser_version` | String(64) | 与主链路同构，便于回溯 |
| `created_at` | timestamptz | |

`kind` 的区分标准（写进 LLM prompt，不靠模型自由发挥）：

- `QUESTION` — 表述为疑问，指向未知。**优先级最高，宁可错判为问题**
- `IDEA` — 提出一种做法、可能性、方案
- `TASK` — 有明确执行动作和完成态
- `NOTE` — 以上都不是，兜底不丢内容

> 为什么 `QUESTION` 优先：好问题的稀缺性高于好答案，且问题最容易在事后被自己
> 遗忘为「当时随口一说」。分类偏向保留问题，是刻意的。

### 3.3 `idea_events`（变更事件流）

append-only，与 `memory_events` 同构但独立。**这是 07 号文档可锚定性的基础**。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `record_id` | FK idea_records | |
| `stream_id` | String(128) | `idea:<record_id>` |
| `event_type` | String(64) | 见下 |
| `payload` | JSONB | |
| `actor` | String(128) | `user:<id>` / `system/idea-worker` |
| `event_time` | timestamptz | |
| `created_at` | timestamptz | |
| `supersedes_event_id` | UUID, null | 与主链路一致的纠正语义 |
| `valid_to` | timestamptz, null | 语义有效期关闭 |

事件类型：

```
IDEA_CREATED       首次沉淀（每条 record 恰好一条）
IDEA_EDITED        标题/正文/kind 修改（payload: {field, value}）
IDEA_TAGGED        标签变更
TASK_COMPLETED     仅 kind=TASK
TASK_CANCELLED     仅 kind=TASK
IDEA_PROMOTED      升级：NOTE→IDEA、IDEA→TASK 等（payload: {from, to}）
IDEA_LINKED        关联另一条 record（payload: {target_record_id, relation}）
IDEA_ARCHIVED      归档（不是删除）
IDEA_FORGOTTEN     用户删除，走 DeletionRequest 后写入
```

### 3.4 `idea_projections`（当前状态）

按 `(record_id, projection_type)` upsert，`version` 单调递增——与
[`state_projections`](../../services/memory-platform/app/models/__init__.py:309) 完全同构，
可以直接照抄 `_upsert_projection` 的写法。

`projection_type = "current"`，`state` 形如：

```json
{
  "kind": "QUESTION",
  "title": "为什么灵感的价值来自稀缺，证明却来自公开",
  "status": "open",
  "tags": ["crypto", "market-design"],
  "linked": ["<record_id>"],
  "last_event_time": "2026-07-25T10:12:00Z"
}
```

---

## 4. 捕捉入口

### 4.1 三条通道

| 通道 | 触发 | 说明 |
|---|---|---|
| 眼镜物理键 | 长按 1s / 双击 | 起一个 15s 采集窗口，`capture_channel="glasses_button"` |
| 唤醒词 | 「记一下」「想到一个」 | 复用现有 VAD 切分，窗口内文本进旁路 |
| App | 文本框 / 按住说话 | 无 Envelope，直接建 `idea_captures` |

眼镜端只需在既有 CaptureIntent 上标一个用途，**不新增采集能力、不新增媒体类型**，
硬件侧改动接近于零。

### 4.2 契约兼容策略（重要）

直觉做法是给 [`SourceEnvelopeIn.trigger`](../../services/memory-platform/app/schemas/__init__.py:52)
加一个 `idea_capture` 枚举值。**不要这么做。**

`contracts/reality-memory/v1/README.md` 的版本规则要求「扩展枚举前先做消费者兼容检查」，
而 `source-envelope.schema.json` 已经是冻结的 v1，眼镜端、手机中继、测试数据包三方都在消费。
为一个尚未验证的功能触发一轮契约版本流程，代价不成比例。

**改用 `meta`**：

```json
{
  "trigger": "explicit",
  "modality": "audio",
  "meta": { "capture_purpose": "idea", "capture_channel": "glasses_button" }
}
```

`meta` 是自由 JSONB，零契约变更，旧消费者原样忽略。
等灵感功能验证成立、字段稳定，再走一次正式的 v2 枚举扩展。

---

## 5. 处理流水线

新增 outbox topic `idea.process`，独立 worker，**完全不经过 candidate/gate**。

```
Envelope(meta.capture_purpose=idea)
  → 网关分流：不投 audio.process，改投 idea.process
  → idea-worker:
      1. ASR 转写                    ── 复用 Transcriber
      2. 立即写 idea_captures.raw_text 并 commit   ★ 关键：先落原文再解析
      3. LLM 结构化拆分（拆条 + kind + title + tags）
      4. 每条 → idea_records + IDEA_CREATED 事件
      5. 计算 content_hash（含盐）
      6. 投影重算 → idea_projections
```

### 5.1 降级原则（与主链路相反）

主链路 worker 的语义是「记审计、弃本条但继续」——
见 [audio.py `_skip`](../../services/memory-platform/app/perception/audio.py:56)。
灵感链路**不允许丢弃**：

| 失败阶段 | 主链路行为 | 灵感旁路行为 |
|---|---|---|
| ASR 不可用 | skip，无产出 | 保留音频证据，`parse_status=RAW`，**豁免 TTL 直到转写成功** |
| 转写为空 | skip | 同上（可能是 VAD 误切，但用户按了键） |
| LLM 抽取失败 | 只留 AudioAsset | 建 1 条 `kind=NOTE` 的 record，`title` 取 `raw_text` 前 64 字 |
| LLM 拆条数为 0 | — | 同上兜底 |

**用户按下了捕捉键，就必须有一条东西留下来。** 这是旁路的验收底线。

### 5.2 LLM 的职责边界

LLM 在旁路里只做**拆分与标题化**，不做真伪判断、不打置信度门。
它是编辑，不是法官。抽取结果错了，用户改一下（`IDEA_EDITED`）即可；
抽取器挂了，原文还在。

---

## 6. 保留策略与隐私

### 6.1 与 PRD §4.1 的冲突及处理

PRD §4.1「记忆变化，而非堆积媒体」的适用对象是**被动采集的环境媒体**。
灵感是用户主动发起的显式表达，不在该原则的射程内。但为了不动摇整体信任模型，
旁路做严格分层：

| 数据 | 默认保留 | 说明 |
|---|---|---|
| `raw_text` 转写 | **长期** | 灵感的长期表示，等价于用户手写的笔记 |
| `idea_records` / `idea_events` | **长期** | |
| 原始音频 EvidenceItem | **按原 TTL 删除** | 与主链路一致，不做例外 |
| 原始音频（用户显式保留） | 长期，见 6.2 | |

### 6.2 「保留原声」是显式动作

`keep_original_audio=true` 只能由用户在 App 上对**具体某条**捕捉设置，
不能作为全局默认、不能由 Agent 代设。设置时：

- 写 `AuditRecord(action="idea_keep_audio", target="capture:<id>")`
- 对应 `EvidenceItem.retention_state` 置为受保护状态，TTL 清理器跳过
- App 上该条目常驻显示「已保留原声」标记，可随时撤销

### 6.3 删除

`DeletionRequest.scope` 增加 `idea` 子系统，`DeletionJob.subsystem` 枚举加
`idea_capture` / `idea_record` / `idea_event` / `idea_projection` / `idea_vector`。
删除后按主链路惯例写 `DeletionTombstone`。

> **与 07 号文档的接口**：若某条 record 的 `content_hash` 已被锚定，
> 删除本地内容不能、也不应撤销已发布的哈希。用户必须在锚定前被明确告知这一点。
> 详见 [07 号文档](concepts/07-Idea-Provenance-and-Encrypted-Matching.md) §7。

---

## 7. API 与 Agent 访问

### 7.1 REST

```
POST   /ideas/capture           手输/上传，建 capture + records
GET    /ideas                   列表：filter by kind/status/tag/时间窗，全文+向量检索
GET    /ideas/{record_id}       当前投影
GET    /ideas/{record_id}/timeline   事件流（可追溯每次修改）
POST   /ideas/{record_id}/events     追加 IDEA_EDITED / TASK_COMPLETED / ...
POST   /ideas/{record_id}/link       IDEA_LINKED
GET    /ideas/captures/{id}          原始捕捉（含 raw_text）
```

所有写操作都是**追加事件**，没有 PUT/PATCH 直接改行的接口——
与 `memory_events` 不可变的原则保持一致。

### 7.2 Agent scope

新增 `ideas:read` / `ideas:write`，走现有
[`AgentGrant`](../../services/memory-platform/app/models/__init__.py:325) 机制。

> **默认拒绝**：灵感比物品位置敏感得多。`ideas:read` 不包含在任何默认 scope 集合里，
> 必须逐次显式授权，且 `AgentGrant.purpose` 必填非空。

### 7.3 Signal

暂不生成灵感类信号。`TASK` 的到期提醒是明显的下一步，但需要先有 due date 建模，
留到 v0.2（§11-Q4）。

---

## 8. 与主链路唯一的交叉点：TASK_STATED

现状：语音里的 `INTENT_CREATED` 谓词经
[`PREDICATE_TO_EVENT_TYPE`](../../services/memory-platform/app/memory/gate.py:34)
映射为 `TASK_STATED`，进主链路。旁路上线后会有两套任务，必须划清。

**划分标准：是否绑定物理实体。**

| 用户说的话 | 归属 | 理由 |
|---|---|---|
| 「这瓶洗发水快用完了，记得买」 | 主链路 `TASK_STATED` | 绑 Entity（洗发水），能和 `LOW_CONSUMABLE` 信号联动 |
| 「可以做一个加密的 idea 撮合市场」 | 旁路 `IDEA` | 无实体 |
| 「明天记得给张三回邮件」 | 旁路 `TASK` | 无实体 |

实现上：`AudioExtractor` 抽出 `INTENT_CREATED` 时，若
`object_text` 能解析到已有 Entity → 走主链路；否则 → 转投旁路。
这个判断放在 [audio.py](../../services/memory-platform/app/perception/audio.py) 的候选构造前，
是唯一需要改主链路代码的地方。

---

## 9. 改动清单

### 批次 A — 独立价值，不依赖灵感功能（建议先做）

| 文件 | 改动 | 说明 |
|---|---|---|
| [projections.py:61](../../services/memory-platform/app/memory/projections.py:61) | `fold_task_events` 改为 list fold | 当前实现每轮循环覆盖 `state["task"]`，只保留最后一条 TASK_STATED。docstring 已声明这是 v0 有意简化，**但一旦同一实体出现第二条任务它就是缺陷**，且与「任务管理」这个需求直接矛盾 |
| 同上 | `fold_preference_events` 评估是否同样需要 list | 偏好可能确实该只留最新，需产品确认 |
| `schemas/__init__.py` `EVENT_TYPES` | 增 `TASK_COMPLETED` / `TASK_CANCELLED` | 主链路任务也需要终态 |
| `contracts/.../memory-event.schema.json` | 同步扩展 enum | ⚠️ 走正式枚举扩展流程 + 消费者兼容检查 |
| `tests/` | 新增多任务 fold 回归测试 | 先写测试复现覆盖问题 |

> 批次 A 是一个真实缺陷修复，无论灵感功能做不做都该合入。

### 批次 B — 数据模型

| 文件 | 改动 |
|---|---|
| `alembic/versions/0008_idea_sidecar.py` | 新建四张表 + 索引（`idea_records(household_id, created_at)`、`idea_events(record_id, event_time)`、`idea_records` 向量索引） |
| `app/models/__init__.py` | 新增 `IdeaCapture` / `IdeaRecord` / `IdeaEvent` / `IdeaProjection` |
| `app/schemas/__init__.py` | 对应 Pydantic in/out + `IDEA_KINDS` / `IDEA_EVENT_TYPES` 常量 |

### 批次 C — 捕捉与流水线

| 文件 | 改动 |
|---|---|
| `app/gateway/__init__.py` | 按 `meta.capture_purpose=="idea"` 分流投 `idea.process` |
| `app/idea/__init__.py`（新目录） | `worker.py` 流水线、`extractor.py` LLM 拆条、`projections.py` fold、`hashing.py` canonical JSON + 加盐 hash |
| `app/perception/stages.py` | 新增 `IdeaExtractInput` / prompt / `IDEA_PARSER_VERSION` |
| `app/perception/audio.py` | §8 的实体判定分流（唯一改主链路的地方） |
| `app/privacy/ttl.py` | `parse_status=RAW` 与 `keep_original_audio` 的 TTL 豁免 |

### 批次 D — API 与授权

| 文件 | 改动 |
|---|---|
| `app/idea/router.py` | §7.1 全部端点 |
| `app/main.py` | 挂载 router |
| `app/auth/` | `ideas:read` / `ideas:write` scope + 默认拒绝规则 |
| `docs/engineering/RealGit-Platform-API-Reference-v0.1.md` | 补充端点 |

### 批次 E — 删除与审计

| 文件 | 改动 |
|---|---|
| `app/privacy/deletion.py` | idea 子系统删除 job |
| `app/models/__init__.py` | `DeletionJob.subsystem` 注释扩展 |

### 批次 F — 测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_idea_capture.py` | 端到端：Envelope → ASR → records → 投影 |
| `tests/test_idea_degradation.py` | **重点**：ASR 失败 / 空转写 / LLM 失败 三种降级都必须留下条目 |
| `tests/test_idea_events.py` | 事件流、`TASK_COMPLETED`、`IDEA_PROMOTED`、supersede |
| `tests/test_idea_privacy.py` | TTL 豁免、显式保留原声、删除与墓碑 |
| `tests/test_idea_access.py` | scope 隔离、跨 household 拒绝、`ideas:read` 不在默认集合 |

---

## 10. Non-goals（本版本明确不做）

- 不做灵感的自动优先级排序、自动摘要推送、「每日回顾」——先验证捕捉本身
- 不做多人协作编辑、共享灵感库
- 不做 due date / 重复任务 / 日历同步
- 不做与外部工具（Notion / Things / 飞书）的双向同步
- 不做任何链上操作，见 [07 号文档](concepts/07-Idea-Provenance-and-Encrypted-Matching.md)

---

## 11. 待决问题

- **Q1** 眼镜端物理键是否已被其他功能占用？长按 1s 与「隐私暂停」手势是否冲突？需硬件侧确认。
- **Q2** 唤醒词方案要不要本地关键词唤醒（KWS）？纯 ASR 后匹配会导致「记一下」之前的半句丢失，可能需要前置滚动缓冲——这与 PRD §4.6「VAD 只读本地小缓冲」的边界需要重新界定。
- **Q3** 灵感绑 `actor_id` 还是 `household_id`？本文档按「绑个人、家庭内默认不可见」设计，需产品确认。这与现有主链路「家庭为可信域」不一致，是刻意的。
- **Q4** `TASK` 的 due date 与提醒，v0.2 做还是本版就做？影响是否要给旁路接 Signal。
- **Q5** `embedding` 存不存服务端？影响 [07 号文档](concepts/07-Idea-Provenance-and-Encrypted-Matching.md) 的整个威胁模型——embedding 可被反演出原文，一旦上传，「平台看不到灵感内容」的承诺就不成立。**建议先不存服务端向量，只做全文检索**，等 07 号方案定型再决定。

---

## 12. 验收标准

灵感旁路 v0.1 认为可用，当且仅当：

1. 眼镜按键后说一句话，10 秒内 App 上出现对应条目，内容与所说一致。
2. 断网状态下捕捉，恢复后不丢条目、不重复（依赖既有幂等键）。
3. ASR / LLM 任一环节强制失败，条目仍然存在且 `raw_text` 完整。
4. 连续记录 20 条任务，`GET /ideas` 返回 20 条，没有互相覆盖（批次 A 的回归验证）。
5. 未授权 Agent 访问 `/ideas` 返回 403，审计表有记录。
6. 删除一条灵感后，`raw_text`、向量、事件、投影全部不可查，墓碑存在。
