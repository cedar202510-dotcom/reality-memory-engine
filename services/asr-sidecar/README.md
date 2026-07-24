# RME ASR Sidecar（faster-whisper 语音转写服务）

memory-platform 语音流水线的 ASR 层：独立的 faster-whisper（CTranslate2）HTTP 服务。
平台侧通过 `ASR_PROVIDER=http` + `app/asr/http_client.py` 消费本服务。

## API 契约

```
POST /transcribe
Authorization: Bearer <ASR_API_KEY>          # 仅当服务端配置了 ASR_API_KEY 时需要
请求  {"audio_base64": "<base64>", "media_kind": "audio"}
响应  {"segments": [{"start": 0.0, "end": 1.2, "text": "...", "speaker": null}, ...],
       "language": "zh", "duration_seconds": 1.2}

GET /healthz → {"status": "ok", "model": "small", "model_loaded": true}
```

- 语言检测自动开启（faster-whisper 内置），`language` 为检测到的 ISO 语言码。
- `speaker` 恒为 null：faster-whisper 不做说话人分离（diarization 需另行接入 pyannote 等）。
- VAD 过滤开启（Silero，`vad_filter=True`），适配采集端 0.4–15s 的 VAD 片段。

## 支持的音频格式

接受常见**容器格式**：wav / mp3 / m4a / ogg / flac 等（PyAV 按容器嗅探解码，内部重采样到 16kHz 单声道）。
**不接受裸 PCM 流**（无容器头无法判定采样率/声道）——采集端请封装为 WAV 再上传。
解码失败返回 422。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ASR_MODEL_SIZE` | `small` | Whisper 模型：`tiny`/`base`/`small`/`medium`/`large-v3` |
| `ASR_DEVICE` | `cpu` | `cpu` 或 `cuda`（GPU 需换 CUDA 版 CTranslate2 环境） |
| `ASR_COMPUTE_TYPE` | `int8` | `int8`/`float16`/`float32` 等 |
| `ASR_MODEL_DIR` | `/models` | 模型下载缓存目录（挂卷持久化，避免重复下载） |
| `ASR_API_KEY` | 空 | 非空时要求 `Authorization: Bearer <key>` |
| `ASR_BEAM_SIZE` | `5` | 解码 beam size |

模型大小权衡（中文场景）：`tiny`/`base` 快但中文错字多；`small`（默认）是 CPU 上质量/速度的平衡点；
`medium`/`large-v3` 质量更好但 CPU 上 15s 片段可能需要数十秒，建议仅在有 GPU 时使用。

## 本地运行

```bash
cd services/asr-sidecar
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# 首次运行会自动下载模型到 ASR_MODEL_DIR（small ≈ 460MB）
ASR_MODEL_DIR=./models ASR_API_KEY=dev-key \
  ./.venv/bin/python -m uvicorn app.main:app --port 8100

# 冒烟
curl -s http://localhost:8100/healthz
curl -s -X POST http://localhost:8100/transcribe \
  -H "Authorization: Bearer dev-key" -H "Content-Type: application/json" \
  -d "{\"audio_base64\": \"$(base64 -i clip.m4a)\", \"media_kind\": \"audio\"}"
```

## Docker

```bash
# 构建期预下载模型（可用 --build-arg ASR_MODEL_SIZE=medium 换模型）
docker build -t rme-asr-sidecar services/asr-sidecar

# 或直接走仓库根目录的编排（含模型缓存卷 rme-asr-models）：
docker compose -f infra/docker-compose.yml up -d asr-sidecar
```

命名卷 `rme-asr-models` 首次创建时会把镜像内预下载的模型复制进卷；之后换模型大小只需改
`ASR_MODEL_SIZE`，新模型会在首次启动时下载进同一卷。

## 对接 memory-platform（本地运行平台时）

```bash
# services/memory-platform/.env
ASR_PROVIDER=http
ASR_BASE_URL=http://localhost:8100
ASR_API_KEY=dev-key          # 与 sidecar 的 ASR_API_KEY 一致；都为空则可省略
```
