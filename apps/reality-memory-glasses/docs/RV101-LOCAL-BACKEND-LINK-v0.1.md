# RV101 眼镜与电脑后端联调

## 0. 使用正确的联调分支

电脑端后端和配套脚本必须使用以下分支：

```text
codex/full-stack-integration
```

在测试电脑上执行：

```bash
git fetch origin
git switch codex/full-stack-integration
git pull --ff-only origin codex/full-stack-integration
```

后续命令都在该分支的仓库根目录执行。不要从 `main` 或其他分支启动本轮联调后端。
APK 直接使用 GitHub 测试包内的成品，不需要重新构建。

## 1. 连接方式

首轮联调不要求云端，也不要求眼镜和电脑在同一 Wi-Fi。开发线连接 RV101 后，用
ADB 反向端口映射：

```text
眼镜 http://127.0.0.1:8765
  -> USB 开发线 / adb reverse
  -> 电脑 http://127.0.0.1:8765
  -> Memory Platform 后端
```

APK 已经包含自动上传器，不需要测试电脑重新构建。它仅在 Debug 构建启用，Release
构建不会生成明文副本，也不会使用这个联调入口。

## 2. 在测试电脑启动后端

先准备 Python 3.11 或更高版本，并启动 PostgreSQL 16 + pgvector。可以使用仓库的
Docker Compose，也可以使用本机已安装的兼容 PostgreSQL：

```bash
docker compose -f infra/docker-compose.yml up -d postgres

cd services/memory-platform
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m alembic upgrade head
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

另开终端确认：

```bash
curl http://127.0.0.1:8765/healthz
```

应返回：

```json
{"status":"ok"}
```

## 3. 连接眼镜并安装 APK

```bash
adb devices -l
adb reverse tcp:8765 tcp:8765
adb reverse --list
./scripts/install-on-rv101.sh ./reality-memory-glasses-debug.apk
```

安装脚本会保留原有 App 数据、建立 `8765` 端口映射，并为 Debug 联调开启短时纯黑
独立提醒显示层权限。正式发布不能依赖 ADB 授权，需要用户授权流程或 Rokid 系统白名单。

## 4. 测试内容

1. 戴上眼镜并确认现实感知提示正常。
2. 静止 10 秒。
3. 按眼镜 AI 键主动“记一下”两次，每次间隔 15 秒；先确认两张图片都成功上传。
4. 在后端确认图片的 `evidence_item_id`、`capture_window_id` 和眼镜端一致。
5. 图片链路通过后，再缓慢左右转头一次并等待 15 秒。
6. 再做一次明显抬头或起身，同时说：“现在开始语音测试，我不喜欢这碗胡辣汤。”
7. 等待 20 秒，让采集完成并触发上传。
8. 暂时拔掉开发线，做一次动作，再接回开发线并重新执行
   `adb reverse tcp:8765 tcp:8765`，验证失败证据会重试。

## 5. 判断是否成功

联调按四层验收。前两层确认眼镜与电脑通信，第三层确认原始证据已经进入后端，
第四层才确认后端完成了结构化解析。不要把 HTTP 成功误认为已经生成长期记忆。

### 5.1 眼镜端上传成功

导出眼镜应用数据：

```bash
adb exec-out run-as com.realitymemory.glasses \
  tar -C files -cf - reality-memory > reality-memory-device-export.tar
```

成功证据对应窗口内会出现：

```text
<evidence_item_id>.upload.json
```

其 `state` 应为 `UPLOADED`。`audit.ndjson` 中应有：

```text
EVIDENCE_UPLOAD_SUCCEEDED
```

对应的 `<evidence_item_id>.upload.json` 还应满足：

- `http_status` 为 `200`；
- `response.validation_warnings` 为空；
- 响应中的 `source_envelope_id`、`evidence_item_id` 与眼镜契约文件一致；
- `response.ingest.evidence_item_ids` 至少有一个后端内部证据编号。

### 5.2 后端已经接收并沉淀原始证据

先看审计接口：

```bash
curl 'http://127.0.0.1:8765/v1/memory/audit?limit=20'
```

应出现 `action=ingest`。再检查数据库中的来源信封、证据和图片解析任务：

```bash
docker compose -f infra/docker-compose.yml exec postgres \
  psql -U rme -d rme -c \
  "SELECT id, source_session_id, modality, idempotency_key, ingested_at
   FROM source_envelopes ORDER BY ingested_at DESC LIMIT 5;"

docker compose -f infra/docker-compose.yml exec postgres \
  psql -U rme -d rme -c \
  "SELECT id, envelope_id, media_kind, storage_ref, retention_state, ttl_until
   FROM evidence_items ORDER BY created_at DESC LIMIT 5;"

docker compose -f infra/docker-compose.yml exec postgres \
  psql -U rme -d rme -c \
  "SELECT id, topic, payload, processed_at
   FROM outbox_events ORDER BY id DESC LIMIT 10;"
```

图片证据必须满足：

- `source_envelopes.modality=image`；
- `evidence_items.media_kind=image` 且 `retention_state=ACTIVE`；
- `storage_ref` 指向后端电脑上的 JPG；
- `outbox_events.topic=frame.process`。

确认 JPG 实际存在且可读取：

```bash
ls -lh services/memory-platform/data/evidence/
```

### 5.3 后端结构化解析是否完成

FastAPI 启动时会同时启动 outbox worker。`frame.process` 的 `processed_at` 非空，表示
任务已经被消费；是否形成长期记忆还要继续查看：

```bash
docker compose -f infra/docker-compose.yml exec postgres \
  psql -U rme -d rme -c \
  "SELECT
     (SELECT count(*) FROM frame_assets) AS frames,
     (SELECT count(*) FROM atomic_observations) AS observations,
     (SELECT count(*) FROM memory_candidates) AS candidates,
     (SELECT count(*) FROM memory_events) AS events,
     (SELECT count(*) FROM state_projections) AS projections;"
```

这五层中文含义依次是：图片的长期结构化描述、模型观察、待审查的记忆候选、
被候选门接受的事实变更、由事实事件计算出的当前状态。真实图片能否走到最后一层，
取决于模型配置、观察置信度和候选门，不是本轮相机通信测试的强制通过条件。

### 5.4 幂等重试

同一证据重试时，接口响应中的 `idempotent_replay` 应为 `true`，数据库不能重复生成
来源信封或证据。断线重连测试必须保留重试前后的上传状态文件和后端审计结果。

## 6. 当前安全边界

- 后端必须只监听本机或受控测试网络，当前接口没有用户鉴权。
- Debug APK 会上传 `debug-export` 中的受控明文副本，仅可用于已授权测试场景。
- 不要采集无关人脸、屏幕隐私文字或未获同意的他人对话。
- 生产版本不能沿用 Debug 明文传输，必须完成设备绑定、传输加密和数据密钥封装。
