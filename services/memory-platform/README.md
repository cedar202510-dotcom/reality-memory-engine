# RME Memory Platform（云端记忆平台后端 v0）

Reality Memory Engine 的第一个云端后端：把眼镜/戒指/手机采集的带时间戳照片，结构化为**可检索、可纠正、可删除、可审计**的现实记忆。首个场景是找物——"我的手机/钥匙上次放哪了？"

## 核心架构原则

1. **模型产生候选，事件构成事实**：VLM/LLM 输出只写 `memory_candidates`；只有候选门（candidate gate）能写 `memory_events`；`state_projections` 由有效事件流确定性重算。
2. **双通道检索**：已知实体走结构化投影（O(1)）；首次被问的物体走向量（或 pg_trgm 降级）检索 top-K 候选帧 → VLM 精判 → 回答并回写候选，被查询过的物体升级为实体。
3. **媒体短命，结构化长存**：原始图片 TTL 默认 15 分钟后物理删除；持久资产是 embedding/caption/观察/事件。
4. **五段时间模型**：`event_time` / `observed_at` / `ingested_at` / `accepted_at` / `valid_from`-`valid_to`。
5. **纠正不改历史**：纠正产生带 `supersedes_event_id` 的新事件，原事件不可变。
6. **模块化单体**：一个 FastAPI 应用，gateway / perception / memory-core / query / privacy 分层，共享 PostgreSQL；异步流水线用 `outbox_events` DB 队列表 + 后台 worker（无 Redis/Kafka）。

## 快速启动

需要 Python 3.11+、PostgreSQL 16 和 pgvector。macOS 自带或 Xcode 附带的旧版
Python 不作为运行环境。

```bash
# 1. 起 PostgreSQL 16 + pgvector（端口 5432，库/用户/密码均为 rme）
cd infra && docker compose up -d && cd ..

# 2. 建 venv 装依赖
cd services/memory-platform
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# 3. 跑迁移（建扩展 vector/pg_trgm + 全部表）
./.venv/bin/python -m alembic upgrade head

# 4. 测试（独立库 rme_test，FakeLLM，无需任何 API key）
./.venv/bin/python -m pytest -q

# 5. 端到端冒烟演示（ingest→检索→纠正→遗忘 全链路打印）
./.venv/bin/python scripts/smoke_demo.py

# 6. 启动服务（默认 LLM_PROVIDER=fake，开箱即用）
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

启动时自动完成：建扩展 → seed 默认家庭+owner+默认设备 → 启动 outbox worker 与 TTL 清理 worker。

## 配置真实 LLM（Moonshot / OpenAI 兼容）

通过环境变量（或 `services/memory-platform/.env`）：

```bash
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_API_KEY=sk-...
LLM_VISION_MODEL=moonshot-v1-8k-vision-preview   # 视觉：chat completions + image_url(base64 data URL)
LLM_TEXT_MODEL=moonshot-v1-8k

# Embedding 可空：为空时检索自动降级为 pg_trgm 模糊匹配，系统仍可完整运行
EMBEDDING_BASE_URL=https://api.moonshot.cn/v1
EMBEDDING_API_KEY=sk-...
EMBEDDING_MODEL=your-embedding-model             # 维度须为 1024（见 app/models EMBEDDING_DIM）
```

其它可调项（默认值见 `app/config.py`）：`DATABASE_URL`、`EVIDENCE_DIR`、`EVIDENCE_TTL_MINUTES=15`、`CANDIDATE_ACCEPT_THRESHOLD=0.85`、`RETRIEVAL_TOP_K=8`、`PHASH_HAMMING_THRESHOLD=6`。

## Audio / 语音

平台支持音频采集的全链路：ingest → ASR 转写 → 语义抽取 → 候选门 → 事件/投影 → 检索/遗忘，与图像帧共用同一套候选门与投影机制（模型只写 `memory_candidates`，绝不直写事件）。

**流水线**（两步式音频解析，对应架构文档 §7.3）：

1. **Gateway**：`modality=audio` 的信封跳过图像 aHash，改用内容 SHA-256（前 8 字节，复用 `phash` 列）在近 1 小时窗口内精确去重；outbox 投递 `audio.process`（图像仍为 `frame.process`）。
2. **ASR 层**：`audio.process` worker 调用 `Transcriber`（`app/asr/`，与 `app/vision/` 同风格抽象）转写 → 写 `audio_assets`（transcript/segments/embedding，媒体 TTL 删除后的长期表示）。ASR 不可用/失败一律降级为跳过 + 审计，绝不阻塞队列。
3. **语义层**：AudioExtractor StageAgent（`audio-extractor-v0.1`）从转写中抽取语音适宜谓词（`PREFERENCE_EXPRESSED` / `INTENT_CREATED` / `USED` / `CONSUMED`）→ `atomic_observations`（挂 `audio_asset_id`，与 `frame_asset_id` 二选一）→ 候选门 → `PREFERENCE_STATED` / `TASK_STATED` 等事件 → `preferences` / `tasks` 投影。
4. **检索**：where-is 通道 2 新增语音转写路（`audio_assets.embedding` 余弦，无 embedding 时降级 pg_trgm），与文本路/视觉路按权重融合（`RETRIEVAL_FUSION_TRANSCRIPT_WEIGHT=0.5`），命中转写作为 Answerer 精判上下文；scene-search 响应新增 `audio_hits`。
5. **遗忘**：forget-recent 新增 `audio` 子系统（默认 scope 已包含），删除窗口内 `audio_assets` 及其观察；TTL 清理对音频证据文件天然生效（媒体类型无关）。

**ASR sidecar 契约**（`ASR_PROVIDER=http`；参考实现见 `services/asr-sidecar/`，基于 faster-whisper，含 Dockerfile 与 compose 编排）：

```
POST {ASR_BASE_URL}/transcribe
Authorization: Bearer <ASR_API_KEY>        # 可选
请求  {"audio_base64": "<base64>", "media_kind": "audio"}
响应  {"segments": [{"start": 0.0, "end": 1.2, "text": "...", "speaker": "S1"?}, ...],
       "language": "zh"?, "duration_seconds": 1.2?}
```

任何超时/网络错误/契约不符 → 平台侧降级为 None（跳过该条，记审计）。

**从 fake 切换到真实 ASR**（faster-whisper sidecar）：

```bash
# 1. 起 sidecar（首次构建会预下载模型；或本地 venv 运行，见 services/asr-sidecar/README.md）
docker compose -f infra/docker-compose.yml up -d asr-sidecar   # 端口 8100

# 2. 平台侧 .env / 环境变量（平台本地运行，不在 compose 内）
ASR_PROVIDER=http
ASR_BASE_URL=http://localhost:8100
ASR_API_KEY=...                # 与 sidecar 的 ASR_API_KEY 一致；两边都为空则可省略
```

**配置项**（默认值见 `app/config.py`）：`ASR_PROVIDER=none|fake|http`（默认 none，语音流水线关闭）、`ASR_BASE_URL`、`ASR_API_KEY`、`ASR_TIMEOUT_SECONDS=60`、`RETRIEVAL_FUSION_TRANSCRIPT_WEIGHT=0.5`。

## 对接 iOS 探针（session.json → envelope 字段映射）

iOS App 每次采集会话导出 `session.json`（采集清单）。上云时**每条观察（observation）映射为一个 SourceEnvelope + 若干 EvidenceItem**：

| iOS session.json | POST /internal/v1/envelopes | 说明 |
| --- | --- | --- |
| `sessionID` | `source_session_id` | 采集会话 id，用于追溯 |
| observation `id` | `idempotency_key`（如 `ios:<sessionID>:<observationID>`） | 幂等去重，重传安全 |
| observation `timestamp` | `occurred_at` + `observed_at` | v0 两者同源；未来区分硬件时间 |
| 触发来源（手动/周期/戒指动作） | `trigger` = `explicit` / `auto` / `ring_motion` | 影响高价值帧判定 |
| 模态（图片/音频） | `modality` = `image` / `audio` | |
| 戒指/眼镜设备登记 | `device_id`（先调内部接口或 seed 里登记） | |
| 断连/摘下等 audit events | `meta` jsonb | 原样保留 |

图片二进制作为 multipart `files` 上传。信封 JSON 放表单字段 `envelope`。

## API 清单

> 完整 API 参考（请求/响应字段、真实示例、错误码、幂等/去重/异步行为）：[docs/engineering/Reality-Memory-Platform-API-Reference-v0.1.md](../../docs/engineering/Reality-Memory-Platform-API-Reference-v0.1.md)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/internal/v1/envelopes` | 采集入口（multipart：envelope JSON + 图片），幂等 + phash 去重 |
| GET | `/v1/memory/objects/where-is?name=手机[&deep=true]` | 找物双通道，返回 FindObjectResponse（位置/新鲜度/置信度/alternatives/timeline_url） |
| POST | `/v1/memory/scene-search` | 场景检索（文本 query 或 base64 图片 query，CLIP 跨模态） |
| GET | `/v1/memory/frames/{frame_asset_id}/evidence` | 取帧原始证据图（TTL 内有效，过期/不存在返回 404） |
| GET | `/v1/memory/objects/{entity_id}/timeline` | 实体事件时间线（含 supersedes 链） |
| POST | `/v1/memory/correct` | 用户纠正 `{entity_id, field, value, reason}` → USER_CORRECTION 事件 + 投影重算 |
| POST | `/v1/memory/forget-recent` | 近窗遗忘 `{minutes, scope[]}` → deletion_request/jobs → tombstone + audit |
| GET | `/v1/memory/preferences?subject=` | 偏好查询（PREFERENCE_STATED 事件，含归因范围 limitations） |
| GET | `/v1/memory/audit?limit=` | 审计记录（agent 调用只能看自己的） |
| POST/GET/DELETE | `/v1/agent/grants[/{id}]` | AgentGrant 签发/列出/撤销（需 `ADMIN_TOKEN`；token 只在签发时返回一次） |
| POST/DELETE | `/v1/signal-subscriptions[/{id}]` | 信号订阅（类型/最低置信度/冷却/每日上限） |
| GET | `/v1/signals` | 拉取待投递信号（过期不投递，抑制计数返回） |
| POST | `/v1/signals/{id}/ack` | 信号回执 |
| GET | `/v1/agent/devices` | Agent 按授权家庭读取可投递设备（需要 `memory.device.message.send`） |
| POST | `/v1/agent/devices/{device_id}/messages` | Agent 向授权家庭内设备发送受约束消息 |
| POST | `/internal/v1/devices/{device_id}/messages` | 下行：手动注入一条设备消息，在线则即时推送 |
| GET | `/internal/v1/devices/{device_id}/inbox` | 下行：轮询兜底，返回未终态未过期消息 |
| POST | `/internal/v1/devices/{device_id}/receipts` | 下行：投递回执（按 message_id + status 幂等） |
| WS | `/internal/v1/devices/{device_id}/stream` | 下行：设备长连，连上先冲积压再实时推 |
| GET | `/healthz` | 健康检查 |

**Agent 鉴权（Agent Access Phase 1）**：带 `Authorization: Bearer <grant token>` 的请求走
scope 鉴权（401/403），审计 actor 记 `agent:<client_id>`，原始 Evidence 对 agent 一律 403；
不带 Authorization 头的本机调用视为 owner 直通（单租户简化）。查询响应含
`provenance_summary` / `limitations` / `cache_until`。Agent 客户端参考
[services/agent-gateway](../agent-gateway/README.md)。

冻结契约（`SourceEnvelope` / `AtomicObservation` / `MemoryCandidate` / `FindObjectResponse`）的 JSON Schema 由 `python -m app.contracts.export` 导出到 `app/contracts/generated/`。

## 下行设备通道（通信架构 §5）

云端 → 设备的消息通道。**通信层已实现，业务载荷仍未冻结**：信封字段按
`rme.device-message.v0` 固定（message_id / 目标设备 / 类型 / 过期 / 优先级 /
delivery_policy），但 `payload` 里提醒的主题、理由、按钮和措辞仍待产品与 Agent
专项 review，因此下行信封**不进** `app/contracts/export.py` 的 v1 契约白名单。

```bash
# 本机跑通全链路（真 uvicorn + 真 WebSocket，模拟一台眼镜）
./.venv/bin/python scripts/downlink_smoke.py
```

设计要点：

- **至少一次投递**。长连推送成功 ≠ 设备呈现成功，只有回执算数。重连会重新收到
  未终结的消息，设备必须按 `message_id` 幂等——这正是通信架构 §7 要求的「眼镜
  直连与手机中继同时收到也只产生一条最终投递状态」。
- **三条路径同一张表**。WebSocket 是低延迟主路径，`GET inbox` 是离线兜底（§5.3
  的首版轮询通道），两者共享 `device_messages` 的状态机与过期语义。
- **过期即静默**。`device_message_ttl_seconds` 默认 600 秒，到期消息不投递、不
  展示、不播报（§5.4）。提醒是时效性内容，宁可错过也不能在几分钟后才播报一条
  已经无关的建议。
- **TTS 默认关**。`delivery_policy.allow_tts` 默认 `false`，语音是比 HUD 文字更
  硬的打断，必须由调用方显式开启。
- **消息状态机**：`PENDING → SENT → RECEIVED → CLOSED`，或任意阶段超时 `EXPIRED`。
  `PRESENTED` / `SPOKEN` 只记时间戳不改状态；终态只认第一条回执。

人工调试仍可调用 `/internal/v1/.../messages`。正式 Agent 路径使用
`/v1/agent/devices/{id}/messages`：要求 `memory.device.message.send` scope，校验目标
设备属于同一授权家庭，并把审计操作者记录为 `agent:<client_id>`。Agent Gateway
负责把回答和确定性信号映射成 `rme.glasses-presentation.v0`；模型不能生成样式、
图标名、系统消息或隐私消息。

### 采集控制（capture_control + connectors）

前端控制台通过 `POST /internal/v1/devices/{id}/capture-requests` 下发 `CAPTURE_REQUEST`，
按设备绑定的通道分发：`adb`（后端在本机把请求翻成 Android intent，要求与眼镜同机）或
`inbox`（只落库，等设备自己来拉，架构目标形态）。两条通道共用 `device_messages` 表与
回执语义，切换通道前端无感。

**下发的是请求不是命令**（通信架构 §8）：设备本地策略有完整拒绝权，拒绝回 `REJECTED`，
与链路故障的 `FAILED` 分开，事后审计才能区分「隐私生效」和「链路坏了」。

`adb` 通道的 `EXECUTED` 只代表 intent 送到了运行时（`detail.execution_evidence =
"intent_delivered_only"`），不代表采集成功。发 intent 前会先按 `KEYCODE_WAKEUP`：
眼镜熄屏时 `am start` 会假装成功，但 Android 12 禁止后台启动 camera 前台服务，
采集不会发生。

未实现（明确的已知缺口）：

- **设备身份**。`/internal/v1` 沿用本机/内网可信假设，没有 device token，任何能
  访问该端口的调用方都能给任意设备下发消息。这个缺口对采集控制比对提醒更要命——
  任何能访问该端口的人都能让眼镜拍照。设备绑定与凭证撤销属于通信 review。
- **设备端下行客户端**。眼镜端目前既没有 inbox 轮询也没有长连客户端，所以 `inbox`
  通道下的请求只会排队等不到执行。今天能端到端跑通的只有 `adb` 通道。
- **多副本**。`DeviceHub` 是进程内注册表，长连只在收到消息的那个进程可见。多副本
  部署需要换 Redis pub/sub 或粘性路由，替换范围限于 `DeviceHub` 这一个类。

## 目录结构

```
app/
  main.py            # FastAPI 装配、lifespan（扩展/seed/worker）
  config.py          # pydantic-settings
  db.py              # async engine/session
  models/            # 全部 SQLAlchemy 模型（含中文注释）
  schemas/           # 冻结契约 Pydantic 模型
  contracts/         # JSON Schema 导出
  gateway/           # ingest API、幂等、phash 去重、证据落盘
  perception/        # Captioner/Extractor 阶段 + 帧处理器
  llm/               # LLMClient 协议 / OpenAICompatibleClient / FakeLLMClient / StageAgent
  memory/            # 候选门、实体解析器、事件写入器、投影引擎、seed
  query/             # where-is 双通道、Answerer 阶段、timeline、correct、preferences
  privacy/           # TTL 清理、forget-recent 删除流水线、审计 API
  auth/              # AgentGrant：token 签发/解析、grant_or_owner 依赖、grants 管理端点
  signals/           # Signal 规则引擎（确定性）+ 订阅/投递/ack API
  downlink/          # 下行设备通道：DeviceHub 长连注册表 + 注入/inbox/回执 API
  capture_control/   # 采集控制面：CAPTURE_REQUEST 下发 + 设备运行时绑定 + 请求历史
  connectors/        # 设备控制通道：adb（本机 USB 联调）/ inbox（设备自拉，目标形态）
  workers/           # outbox 轮询 + TTL 循环（投影重算后触发信号评估）
scripts/smoke_demo.py
scripts/downlink_smoke.py
tests/               # pytest（FakeLLM + 真实 PG，库名 rme_test）
```

## v0 简化项（已知取舍）

- 单租户：所有实体挂在 seed 的默认家庭下，无鉴权。
- 高价值帧判定简化：`trigger=explicit` 或 `scene_tags` 非空即抽取，无质量分/模糊度过滤。
- 候选门冲突检测简化：仅"同一物体、不同 location 的未决候选"判互斥；CONFLICTED 后无自动解决流程。
- 实体解析保守：名称精确/别名/trgm≥0.9/embedding≥0.98 才复用，否则新建（宁多勿并）。
- outbox worker 单条失败直接标记已消费（避免毒消息循环），无重试/DLQ。
- forget-recent 同步执行 jobs（未走后台调度）；事件标记失效（`valid_to`）而非物理删除，历史仍在。
- TTL 删除用本地文件删除模拟 crypto-shredding，`encryption_key_id` 仅为字段占位。
- phash 用 aHash(64bit)，对近似纯色/规则构图的图区分度有限（真实照片没问题）。
- 通道 2 精判最多带 4 张未删证据原图；证据删除后只靠 caption/tags。
- embedding 维度固定 1024；更换模型需同步改 `app/models.EMBEDDING_DIM` 并重建迁移。
