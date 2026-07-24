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
| GET | `/v1/memory/audit?limit=` | 审计记录 |
| GET | `/healthz` | 健康检查 |

冻结契约（`SourceEnvelope` / `AtomicObservation` / `MemoryCandidate` / `FindObjectResponse`）的 JSON Schema 由 `python -m app.contracts.export` 导出到 `app/contracts/generated/`。

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
  query/             # where-is 双通道、Answerer 阶段、timeline、correct
  privacy/           # TTL 清理、forget-recent 删除流水线、审计 API
  workers/           # outbox 轮询 + TTL 循环
scripts/smoke_demo.py
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
