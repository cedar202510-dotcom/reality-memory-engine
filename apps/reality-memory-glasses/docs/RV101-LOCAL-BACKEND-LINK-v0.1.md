# RV101 眼镜与电脑后端联调

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
adb install -r reality-memory-glasses-debug.apk
adb shell am force-stop com.realitymemory.glasses
adb shell monkey -p com.realitymemory.glasses 1
```

也可以直接运行测试包中的安装脚本，它会自动建立 `8765` 端口映射。

## 4. 测试内容

1. 戴上眼镜并确认现实感知提示正常。
2. 静止 10 秒。
3. 缓慢左右转头一次，等待 15 秒。
4. 再做一次明显抬头或起身，同时说：“现在开始语音测试，我不喜欢这碗胡辣汤。”
5. 等待 20 秒，让采集完成并触发上传。
6. 暂时拔掉开发线，做一次动作，再接回开发线并重新执行
   `adb reverse tcp:8765 tcp:8765`，验证失败证据会重试。

## 5. 判断是否成功

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

后端 `/v1/memory/audit` 中应出现 `ingest`。同一证据重试时，
`idempotent_replay=true`，不能重复生成证据。

## 6. 当前安全边界

- 后端必须只监听本机或受控测试网络，当前接口没有用户鉴权。
- Debug APK 会上传 `debug-export` 中的受控明文副本，仅可用于已授权测试场景。
- 不要采集无关人脸、屏幕隐私文字或未获同意的他人对话。
- 生产版本不能沿用 Debug 明文传输，必须完成设备绑定、传输加密和数据密钥封装。
