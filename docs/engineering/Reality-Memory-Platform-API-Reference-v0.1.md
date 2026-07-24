# Reality Memory Platform API 参考 v0.1

> 文档版本：v0.1
> 文档日期：2026-07-24
> 适用服务：`services/memory-platform/`（FastAPI 模块化单体）
> 文档用途：面向客户端开发者（iOS App / Rokid 眼镜端）的后端 HTTP API 参考
> 验证状态：全部 9 个端点已于 2026-07-24 通过端到端冒烟测试（真实配置：LLM=kimi-coding k3、
> 视觉=本地 CLIP ViT-B-32、ASR=none），文中响应示例均摘自真实响应，仅做适度截断。

---

## 1. 服务概述

Memory Platform 是 Reality Memory Engine 的后端沉淀服务，负责接收采集端上报的证据
（图片 / 音频信封），异步完成感知（caption → 结构化抽取 → 候选门 → 事实事件 → 状态投影），
并对外提供"东西在哪"查询、场景检索、纠正与遗忘等能力。

- **Base URL**：开发环境 `http://localhost:8765`（端口由启动命令决定；
  `uvicorn app.main:app --port <port>`，工作目录为 `services/memory-platform/`）。
- **鉴权**：当前版本无鉴权，仅限本机 / 内网使用。
- **编码与时间**：请求 / 响应均为 JSON（ ingest 除外，见 §3.1）；时间字段为 UTC RFC 3339。
- **异步架构提示**：`POST /internal/v1/envelopes` 是**同步落库 + 异步感知**。
  接口返回成功只代表信封与证据已落库并写入 outbox；感知由后台 worker 消费
  `frame.process` / `audio.process` 事件完成（轮询间隔 1 秒）。在真实 LLM 配置下，
  **单帧处理约需 30–60 秒**。注入数据后需等待片刻再调用查询类端点才能看到结果。
- **证据 TTL**：原始媒体是短暂证据，默认 `EVIDENCE_TTL_MINUTES=15` 分钟后物理删除；
  长期保留的是 caption、场景标签、向量等结构化表示（详见架构文档）。

## 2. 端点总览

| # | 方法 | 路径 | 路由组 | 功能 |
| --- | --- | --- | --- | --- |
| 1 | GET | `/healthz` | main | 健康检查 |
| 2 | POST | `/internal/v1/envelopes` | gateway | 幂等接收来源信封 + 证据落盘 + 去重 + outbox |
| 3 | GET | `/v1/memory/objects/where-is` | query | "东西在哪"双通道查询 |
| 4 | POST | `/v1/memory/scene-search` | query | 文本 / 图片跨模态场景检索 |
| 5 | GET | `/v1/memory/frames/{frame_asset_id}/evidence` | query | 读取帧的原始证据媒体 |
| 6 | GET | `/v1/memory/objects/{entity_id}/timeline` | query | 实体事实事件时间线 |
| 7 | POST | `/v1/memory/correct` | query | 用户纠正（不改历史，重算投影） |
| 8 | POST | `/v1/memory/forget-recent` | privacy | 遗忘最近 N 分钟（8 子系统删除流水线） |
| 9 | GET | `/v1/memory/audit` | privacy | 审计记录查询 |

## 3. 通用约定

### 3.1 ingest 使用 multipart/form-data

`POST /internal/v1/envelopes` 不是 JSON 接口。请求体为 multipart：

- form 字段 `envelope`：**JSON 字符串**（`SourceEnvelopeIn` 结构，见 §4.1）；
- form 字段 `files`：文件列表（可多个；图片建议 JPEG，音频任意常见封装）。

curl 示例：

```bash
curl -X POST http://localhost:8765/internal/v1/envelopes \
  -F 'envelope={"occurred_at":"2026-07-24T14:22:58Z","observed_at":"2026-07-24T14:22:58Z","idempotency_key":"dev-001","trigger":"explicit","modality":"image","source_session_id":"ses-001"}' \
  -F 'files=@frame.jpg;type=image/jpeg'
```

### 3.2 幂等（idempotency_key）

同一 `idempotency_key` 重复投递不会创建新信封：直接返回首次投递的信封与证据 id，
并置 `idempotent_replay=true`。客户端断网重传、队列重放均依赖此键去重，
**必须为每次真实采集生成稳定且唯一的键**（重试时保持原键不变）。

### 3.3 证据去重（pHash / 内容哈希）

同一模态、近 1 小时（`PHASH_DEDUP_WINDOW_MINUTES=60`）内的活跃证据参与去重：

- 图片：计算 8×8 aHash，与窗口内证据的汉明距离 ≤ 6（`PHASH_HAMMING_THRESHOLD`）
  判定为"持续证据"——**不新建证据、不落盘**，只刷新既有证据的 TTL，
  其 id 出现在响应的 `duplicate_evidence_ids` 中；
- 音频：无法做感知哈希，用内容 SHA-256 前 8 字节做精确去重（同一文件字节级一致才去重）。

### 3.4 outbox 异步感知

每个新建证据在同事务写入一条 outbox 事件（`frame.process` 或 `audio.process`），
后台 worker 消费后依次完成：caption / 转写 → 结构化原子观察 → 记忆候选门 →
事实事件（MemoryEvent）→ 状态投影（StateProjection）。查询类端点只读已沉淀的结构化
数据，**不等待** outbox 消费；注入与查询之间的可见性延迟见 §1。

### 3.5 错误格式

两类 422 格式并存，客户端需兼容：

- **Pydantic 校验失败**（字段缺失 / 类型错误 / 范围越界）：FastAPI 默认结构，
  `detail` 为数组（含 `type` / `loc` / `msg` / `input`）；
- **业务校验失败**（envelope JSON 解析失败、base64 非法等）：`HTTPException`，
  `detail` 为字符串。

404 统一为 `{"detail": "<原因>"}`。

### 3.6 审计

ingest、查询（where-is / scene-search）、纠正、遗忘都会写入审计记录
（`GET /v1/memory/audit` 可查），actor 目前固定为 `device:<device_id>` 或 `user:owner`。

---

## 4. Gateway（采集接入）

### 4.1 POST /internal/v1/envelopes

接收一条来源信封及其证据文件，幂等落库、去重、写 outbox。

**请求**：multipart/form-data（见 §3.1）。form 字段 `envelope` 为如下 JSON：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `occurred_at` | datetime | 是 | 采集发生时间（UTC RFC 3339） |
| `observed_at` | datetime | 是 | 设备观察到的时间 |
| `idempotency_key` | string | 是 | 幂等键，1–256 字符（见 §3.2） |
| `trigger` | enum | 否 | `explicit`（默认）/ `auto` / `ring_motion` |
| `modality` | enum | 否 | `image`（默认）/ `video` / `audio` / `sensor`；当前感知流水线已验证 `image` 与 `audio` |
| `device_id` | UUID \| null | 否 | 已绑定设备标识 |
| `source_session_id` | string \| null | 否 | 采集会话标识 |
| `meta` | object | 否 | 扩展元数据，默认 `{}` |

form 字段 `files`：0..n 个文件。空文件（0 字节）会被跳过。

**响应** 200：`IngestResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `envelope` | object | 落库后的信封（含服务端生成的 `id`、`ingested_at`） |
| `evidence_item_ids` | UUID[] | 新建的证据 id（每个非重复文件一个） |
| `duplicate_evidence_ids` | UUID[] | 判重命中的既有证据 id（仅刷新 TTL，见 §3.3） |
| `idempotent_replay` | bool | 是否为幂等重放（见 §3.2） |

首次投递真实响应：

```json
{
  "envelope": {
    "id": "59a4ef7f-f83b-4104-8feb-113280514c71",
    "device_id": null,
    "source_session_id": "doc-capture",
    "occurred_at": "2026-07-24T14:22:58.180302Z",
    "observed_at": "2026-07-24T14:22:58.180302Z",
    "ingested_at": "2026-07-24T14:22:58.197762Z",
    "idempotency_key": "doc-capture-1784902978",
    "trigger": "explicit",
    "modality": "image",
    "meta": {}
  },
  "evidence_item_ids": ["cae6868c-7365-4f06-8b6f-88b8daf81400"],
  "duplicate_evidence_ids": [],
  "idempotent_replay": false
}
```

同键重放真实响应（信封 id、证据 id 与首次完全相同）：

```json
{
  "envelope": { "id": "59a4ef7f-f83b-4104-8feb-113280514c71", "...": "同上" },
  "evidence_item_ids": ["cae6868c-7365-4f06-8b6f-88b8daf81400"],
  "duplicate_evidence_ids": [],
  "idempotent_replay": true
}
```

**错误**：

- 422（`detail` 为字符串）：`envelope` 字段不是合法 JSON 或不满足 schema，例如
  `{"detail": "envelope 校验失败: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"}`；
- 422（`detail` 为数组）：multipart 缺少 `envelope` 字段等 FastAPI 层校验失败。

---

## 5. Query（查询与纠正）

### 5.1 GET /v1/memory/objects/where-is

"我的 X 在哪"——双通道查询，永远返回 200 + 置信度 + 新鲜度表述，不因"不知道"而报错。

**Query 参数**：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `name` | string | 是 | 物体名称，min_length=1 |
| `deep` | bool | 否 | 默认 `false`。`true` 时跳过通道 1，强制走深度检索 |

**响应** 200：`FindObjectResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `query` | string | 回显查询名 |
| `channel` | enum | `projection` / `deep_retrieval` / `not_found` |
| `entity` | object \| null | `{id, canonical_name, aliases}` |
| `location` | string \| null | 当前位置 |
| `last_seen_time` | datetime \| null | 最后一次看到的时间 |
| `freshness` | string \| null | "最后一次看到是 3 分钟前"式表述 |
| `confidence` | float | 聚合置信度 |
| `answer_text` | string | 可直接展示的自然语言回答 |
| `alternatives` | object[] | 历史其它位置（最多 3 个，`{location, last_seen_time, confidence}`） |
| `timeline_url` | string \| null | 该实体的时间线端点路径 |

**行为（双通道）**：

- **通道 1（projection）**：名称 / 别名精确命中或 pg_trgm 模糊命中已知实体 →
  O(1) 读状态投影。实体存在但无有效位置（如刚被遗忘）时，返回
  `channel=projection, location=null`，**不会**继续走通道 2（避免"遗忘后又想起来"）。
- **通道 2（deep_retrieval）**：未知名称 → 多路混合召回（文本向量 / trgm 降级 +
  CLIP 视觉跨模态 + 语音转写，加权融合）→ Answerer 精判（证据未删的帧带图）→
  回答并**回写一条记忆候选**（置信度足够时经候选门升级为实体，下次同名查询即走通道 1）。
- 召回为空或精判未找到 → `channel=not_found`。

通道 1 命中真实响应：

```json
{
  "query": "笔记本电脑",
  "channel": "projection",
  "entity": {"id": "e6a51825-de18-4b6c-9b21-f6460606eda0", "canonical_name": "笔记本电脑", "aliases": []},
  "location": "办公桌",
  "last_seen_time": "2026-07-24T14:22:58.180302Z",
  "freshness": "最后一次看到是 50 秒前",
  "confidence": 0.9,
  "answer_text": "笔记本电脑最后一次看到是 50 秒前，在办公桌。",
  "alternatives": [
    {"location": "办公桌右侧", "last_seen_time": "2026-07-24T14:11:01.295333Z", "confidence": 0.9}
  ],
  "timeline_url": "/v1/memory/objects/e6a51825-de18-4b6c-9b21-f6460606eda0/timeline"
}
```

认识实体但无有效位置的真实响应：

```json
{
  "query": "手机",
  "channel": "projection",
  "entity": {"id": "86d7646d-0073-4259-b534-7e2f380d94e4", "canonical_name": "手机", "aliases": []},
  "location": null, "last_seen_time": null, "freshness": null,
  "confidence": 0.0,
  "answer_text": "认识「手机」，但当前没有有效的位置记忆（可能刚被遗忘）。",
  "alternatives": [],
  "timeline_url": "/v1/memory/objects/86d7646d-0073-4259-b534-7e2f380d94e4/timeline"
}
```

`not_found` 真实响应（`answer_text` 由 Answerer 生成，附低置信度）：

```json
{
  "query": "完全没见过的东西xyz",
  "channel": "not_found",
  "entity": null, "location": null, "last_seen_time": null, "freshness": null,
  "confidence": 0.05,
  "answer_text": "这两帧里都是办公桌上的电脑、手机、汤碗、饮料瓶这些常见东西，没看到有叫“xyz”的陌生物品。……",
  "alternatives": [],
  "timeline_url": null
}
```

**错误**：422（`detail` 为数组）——缺少 `name` 或为空字符串。

### 5.2 POST /v1/memory/scene-search

通用场景物件查找：文本 / 图片跨模态检索帧的 CLIP 视觉向量；文本 query 同时检索语音转写。

**请求** JSON：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `query_text` | string \| null | 二选一 | 文本 query，min_length=1 |
| `query_image_base64` | string \| null | 二选一 | base64 编码的查询图片 |
| `top_k` | int | 否 | 默认 8，范围 1–50 |

`query_text` 与 `query_image_base64` 至少提供一个；两者同时提供时，两路向量取均值
融合为单一查询向量。

**响应** 200：`SceneSearchResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `query_text` | string \| null | 回显 |
| `has_image_query` | bool | 是否带图片 query |
| `hits` | object[] | 帧命中，按相似度降序 |
| `hits[].frame_asset_id` | UUID | 帧 id（可用于 §5.3 取证据） |
| `hits[].caption` / `scene_tags` | string / string[] | 感知生成的长期表示 |
| `hits[].score` | float | 余弦相似度（= 1 − cosine_distance，保留 6 位小数） |
| `hits[].evidence_available` | bool | 原始媒体是否仍在 TTL 内可读 |
| `hits[].evidence_url` | string \| null | 证据可用时的取媒体路径，否则 null |
| `audio_hits` | object[] | 语音命中（`{audio_asset_id, captured_at, transcript, score, evidence_available}`），仅文本 query 时检索 |

文本 query 真实响应（top_k=3，截断为 2 条）：

```json
{
  "query_text": "笔记本电脑",
  "has_image_query": false,
  "hits": [
    {
      "frame_asset_id": "60029c06-6f3f-43aa-9256-e8de4fa4d29d",
      "captured_at": "2026-07-24T14:14:03.706625Z",
      "caption": "办公桌上摆放着笔记本电脑、手机、纸巾和几份餐食，一人正坐在桌前使用电脑。",
      "scene_tags": ["笔记本电脑", "手机", "包子", "汤碗", "塑料盖", "纸巾", "调料包", "键盘", "办公桌", "人手"],
      "score": 0.224247,
      "evidence_available": true,
      "evidence_url": "/v1/memory/frames/60029c06-6f3f-43aa-9256-e8de4fa4d29d/evidence"
    },
    {
      "frame_asset_id": "3914d49d-0b59-4035-8ccb-c4a7724b0b20",
      "captured_at": "2026-07-24T14:22:58.180302Z",
      "caption": "一张杂乱的办公桌上摆放着打开的笔记本电脑、亮屏手机、外星人电解质饮料瓶、卷纸、缠绕的线缆和一碗汤，背景中有人正使用电脑工作。",
      "scene_tags": ["笔记本电脑", "手机", "电解质饮料瓶", "卷纸", "纸巾", "线缆", "汤碗", "办公桌", "键盘", "黄色包装袋"],
      "score": 0.197339,
      "evidence_available": true,
      "evidence_url": "/v1/memory/frames/3914d49d-0b59-4035-8ccb-c4a7724b0b20/evidence"
    }
  ],
  "audio_hits": []
}
```

图片 query 真实响应（用已注入的帧自检索，top1 相似度 1.0）：

```json
{
  "query_text": null,
  "has_image_query": true,
  "hits": [
    {"frame_asset_id": "3914d49d-0b59-4035-8ccb-c4a7724b0b20", "score": 1.0, "...": "同上"},
    {"frame_asset_id": "60029c06-6f3f-43aa-9256-e8de4fa4d29d", "score": 0.836027, "...": "同上"}
  ],
  "audio_hits": []
}
```

**错误**：

- 422（`detail` 为数组）：两种输入都缺省 —
  `query_text 与 query_image_base64 至少提供一个`；或 `top_k` 越界；
- 422（`detail` 为字符串）：`{"detail": "query_image_base64 不是合法的 base64"}`。

**行为说明**：检索对象是 `frame_assets.visual_embedding`（CLIP 向量，512 维）。
若服务未配置视觉编码器（`VISION_PROVIDER=none`），视觉检索整体关闭，返回空 hits。

### 5.3 GET /v1/memory/frames/{frame_asset_id}/evidence

读取某帧的原始证据媒体（二进制流）。

**路径参数**：`frame_asset_id`（UUID，来自 scene-search 的 `hits[].frame_asset_id`）。

**响应** 200：`content-type: image/jpeg` 的二进制媒体（真实测量：一张采集帧约 79 KB）。

**错误**：

- 404 `{"detail": "frame 不存在"}` — id 无对应帧；
- 404 `{"detail": "证据媒体已过期删除"}` — 帧存在但媒体已过 TTL 被物理删除
  （或已被 forget-recent 清除）。**长期表示（caption / 标签 / 向量）不受影响**，
  客户端应将 404 视为正常生命周期事件而非故障。

### 5.4 GET /v1/memory/objects/{entity_id}/timeline

实体的事实事件时间线（含已被取代 / 已失效的历史，便于审计"系统为什么这么认为"）。

**路径参数**：`entity_id`（UUID，来自 where-is 的 `entity.id`）。

**响应** 200：`TimelineResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entity` | object | `{id, canonical_name, aliases}` |
| `projection` | object \| null | 当前 `last_seen` 投影状态；无投影为 null |
| `events` | object[] | 按 `event_time_from`、`accepted_at` 升序 |
| `events[].event_id` | UUID | 事件 id |
| `events[].event_type` | string | 如 `OBJECT_OBSERVED_AT` / `USER_CORRECTION` |
| `events[].valid_to` | datetime \| null | 非 null 表示已失效（被遗忘），**历史行保留不删** |
| `events[].payload` | object | 事件载荷（如 `{location, state, color}`） |
| `events[].confidence` | object | 五维置信度（model/identity/spatial/temporal/policy/aggregate） |
| `events[].superseded_by` | UUID \| null | 取代本事件的新事件 id（纠正链） |

真实响应（截断为 2 条事件）：

```json
{
  "entity": {"id": "e6a51825-de18-4b6c-9b21-f6460606eda0", "canonical_name": "笔记本电脑", "aliases": []},
  "projection": {"location": "办公桌", "confidence": 0.9, "last_seen_time": "2026-07-24T14:22:58.180302+00:00"},
  "events": [
    {
      "event_id": "6ae6683d-d80f-4f83-84d5-5ad157dc524c",
      "event_type": "OBJECT_OBSERVED_AT",
      "event_time_from": "2026-07-24T14:11:01.218526Z",
      "accepted_at": "2026-07-24T14:11:49.302751Z",
      "valid_to": "2026-07-24T14:13:12.797019Z",
      "payload": {"color": "银色", "state": "打开", "location": "办公桌"},
      "confidence": {"model": 0.9, "policy": 1.0, "spatial": 0.9, "identity": 0.85, "temporal": 0.9, "aggregate": 0.89},
      "superseded_by": null
    },
    {
      "event_id": "3fd14bc5-5fe8-4482-88d0-fe00870bbea1",
      "event_type": "OBJECT_OBSERVED_AT",
      "event_time_from": "2026-07-24T14:22:58.180302Z",
      "accepted_at": "2026-07-24T14:23:48.374018Z",
      "valid_to": null,
      "payload": {"color": "黑色", "state": "打开", "location": "办公桌", "position": "画面左侧"},
      "confidence": {"model": 0.9, "policy": 1.0, "spatial": 0.9, "identity": 0.85, "temporal": 0.95, "aggregate": 0.9},
      "superseded_by": null
    }
  ]
}
```

**错误**：404 `{"detail": "entity 不存在"}`。

### 5.5 POST /v1/memory/correct

用户纠正。**不改历史**：追加一条 `USER_CORRECTION` 事件（supersedes 当前最新有效事件），
随后立即重算该实体投影。

**请求** JSON：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `entity_id` | UUID | 是 | 被纠正实体 |
| `field` | string | 是 | 纠正字段，min_length=1，如 `location` |
| `value` | any | 是 | 纠正后的值 |
| `reason` | string | 否 | 纠正原因，默认 `""` |

**响应** 200：`CorrectResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | UUID | 新写入的纠正事件 |
| `superseded_event_id` | UUID \| null | 被取代的旧事件（无有效旧事件时为 null） |
| `projection` | object \| null | 重算后的投影；纠正的投影带 `corrected: true`，confidence 固定 0.99 |

真实响应：

```json
{
  "event_id": "06e12dc1-00ca-42b4-8dce-cc2075b3feab",
  "superseded_event_id": "8fd66731-c821-47c4-bbf3-233f4f6fdb0d",
  "projection": {
    "location": "文档示例书架",
    "last_seen_time": "2026-07-24T14:24:01.494570+00:00",
    "confidence": 0.99,
    "corrected": true
  }
}
```

纠正后再调 where-is 即返回新位置（冒烟实测验证）。纠正同时写一条 `action=correct`
审计记录（含 field / value / reason / supersedes_event_id）。

**错误**：404 `{"detail": "entity 不存在"}`；422（`detail` 为数组）——缺字段或 `field` 为空。

---

## 6. Privacy（遗忘与审计）

### 6.1 POST /v1/memory/forget-recent

"忘掉最近 N 分钟"——按时间窗口执行的删除流水线，同步执行完成才返回。

**请求** JSON：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `minutes` | int | 是 | 时间窗口，1–1440（24 小时）；窗口起点 = now − minutes |
| `scope` | string[] | 否 | 默认全部 8 个子系统（见下）；未知子系统名会被忽略 |

**8 个子系统 job**（固定执行顺序：event → observation → frame → audio →
evidence → candidate → projection → vector）：

| 子系统 | 行为 |
| --- | --- |
| `event` | 窗口内 `ingested_at` 的事实事件标记 `valid_to=now`（**不改历史**，事件行保留） |
| `observation` | 删除窗口内证据派生的原子观察 |
| `frame` / `audio` | 删除窗口内证据对应的帧 / 语音长期结构化表示（含向量） |
| `evidence` | **物理删除**窗口内证据文件，`retention_state=DELETED` |
| `candidate` | 删除窗口内创建的记忆候选 |
| `projection` | 重算受影响实体的投影（无有效事件 → 投影清空） |
| `vector` | 清理窗口内创建的孤儿实体：无事件引用的整体删除，有事件（已失效）的清除向量 |

**响应** 200：`ForgetRecentResponse`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `request_id` | UUID | 删除请求 id |
| `status` | string | `DONE`（全部 job 成功）/ `FAILED`（任一 job 失败；单 job 失败不阻塞其它子系统，错误记入 `jobs[].last_error`） |
| `jobs` | object[] | 每个子系统 `{subsystem, status, last_error}` |
| `tombstone_id` | UUID \| null | 删除墓碑 id（内含 `audit_hash`：request_id + 各子系统删除计数的 SHA-256，供对账） |

真实响应（冒烟测试 minutes=10）：

```json
{
  "request_id": "…",
  "status": "DONE",
  "jobs": [
    {"subsystem": "evidence", "status": "DONE", "last_error": null},
    {"subsystem": "frame", "status": "DONE", "last_error": null},
    {"subsystem": "audio", "status": "DONE", "last_error": null},
    {"subsystem": "observation", "status": "DONE", "last_error": null},
    {"subsystem": "candidate", "status": "DONE", "last_error": null},
    {"subsystem": "event", "status": "DONE", "last_error": null},
    {"subsystem": "vector", "status": "DONE", "last_error": null},
    {"subsystem": "projection", "status": "DONE", "last_error": null}
  ],
  "tombstone_id": "9efaa871-…（截断）"
}
```

遗忘完成后会写一条 `action=forget` 审计记录（含 minutes、各子系统删除计数 summary、
audit_hash）。冒烟实测：遗忘后再查同一物体，`location=null`，不再给出旧位置。

**错误**：422（`detail` 为数组）——`minutes` 越界（如 `{"type": "greater_than", "loc": ["body", "minutes"], "msg": "Input should be greater than 0", "input": 0}`）。

### 6.2 GET /v1/memory/audit

审计记录查询，按创建时间倒序。

**Query 参数**：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `limit` | int | 否 | 默认 50，范围 1–500 |

**响应** 200：数组，元素 `AuditRecordOut`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID | 记录 id |
| `actor` | string | `device:<device_id>` / `user:owner` |
| `action` | string | `ingest` / `query` / `correct` / `forget` / `event_accepted` / `audio_skip` 等 |
| `target` | string | 如 `envelope:<id>`、`where-is:<name>`、`entity:<id>`、`deletion_request:<id>` |
| `detail` | object | 动作相关的结构化细节 |
| `created_at` | datetime | 创建时间 |

真实响应（limit=5，截断为 2 条）：

```json
[
  {
    "id": "293c3365-752d-40a3-84c8-38673b90e8d7",
    "actor": "user:owner",
    "action": "correct",
    "target": "entity:e6a51825-de18-4b6c-9b21-f6460606eda0",
    "detail": {
      "field": "location",
      "value": "文档示例书架",
      "reason": "API 文档示例",
      "supersedes_event_id": "8fd66731-c821-47c4-bbf3-233f4f6fdb0d"
    },
    "created_at": "2026-07-24T14:24:01.497586Z"
  },
  {
    "id": "e196ba21-16c2-4fca-8e0b-1bba135e5e0a",
    "actor": "user:owner",
    "action": "query",
    "target": "scene-search:<image>",
    "detail": {"top_k": 2, "n_hits": 2, "n_audio_hits": 0, "has_image_query": true},
    "created_at": "2026-07-24T14:24:01.452923Z"
  }
]
```

**错误**：422（`detail` 为数组）——`limit` 越界。

---

## 7. 健康检查

### GET /healthz

无参数。响应 200：

```json
{"status": "ok"}
```

仅表示 HTTP 进程存活，不检查数据库 / worker 状态。

---

## 8. 错误码汇总

| 状态码 | 出现端点 | 语义 | `detail` 形态 |
| --- | --- | --- | --- |
| 200 | 全部 | 成功（where-is 的"不知道"也是 200，看 `channel`） | — |
| 404 | frames/evidence | `frame 不存在` / `证据媒体已过期删除`（TTL 或遗忘，属正常生命周期） | 字符串 |
| 404 | timeline、correct | `entity 不存在` | 字符串 |
| 422 | envelopes | `envelope` 字段 JSON 解析 / schema 校验失败 | 字符串 |
| 422 | scene-search | `query_image_base64 不是合法的 base64` | 字符串 |
| 422 | 全部 | 请求体 / 参数不满足 schema（缺字段、越界、类型错） | 数组（FastAPI 默认） |

---

## 9. 修订记录

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| v0.1 | 2026-07-24 | 首版。基于当日 9/9 端点端到端冒烟测试（真实配置：LLM=kimi-coding k3、本地 CLIP ViT-B-32、ASR=none、Postgres+pgvector），响应示例均摘自真实响应。 |

参考文档：《Reality Memory Engine 多模态数据契约 v1.0》、
《Reality Memory Engine 工程架构与数据链路 v1.3》。
