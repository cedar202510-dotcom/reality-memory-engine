# Reality Glass Probe

这是 RealGit 的第一阶段真机验证 App，直接作为 APK 运行在
Rokid Glasses（RV101 / YodaOS-Sprite / Android 12 API 31）上。

## 先说清楚 SDK 选型

当前这个工程走的是 Rokid 官方的“眼镜端裸机开发”路线：

- App 运行位置：眼镜本机
- 开发方式：标准 Android 工程
- 相机：CameraX
- 佩戴/摘下：Rokid 系统广播
- 安装和调试：ADB
- 当前不依赖 CXR-L
- 当前不依赖 CXR-M

`CXR-L SDK` 是公开 SDK，但它运行在 Android/iOS 手机 App 中。手机 App 通过
Rokid AI App 与眼镜连接，再获取图像、音频、显示和指令能力。它不是当前眼镜
APK 的必需依赖。

`CXR-M SDK` 需要商务对接，不公开提供。本工程不使用它，安装流程也不再把
CXR-M 社区工具列为正式方案。

更详细的选型、依赖位置和后续手机端方案见：

[`docs/ROKID-DEVELOPMENT-GUIDE.md`](docs/ROKID-DEVELOPMENT-GUIDE.md)

## 当前 App 验证什么

- 能否在眼镜上安装自己的 APK
- 能否申请 Camera 权限
- CameraX 能否无预览拍照
- 图片验证后能否立即删除
- 能否收到佩戴、摘下和镜腿折叠广播
- Pause / Stop 后是否停止新的采集尝试

界面提供：

- `Capture Once`：拍一张本地 JPEG，记录大小和耗时，然后立即删除
- `Start 30s Periodic`：每 30 秒拍一张
- `Pause`：暂停新采集
- `Resume`：恢复采集
- `Stop and Cleanup`：停止服务

本地 JSONL 日志：

```text
/data/data/com.realitymemory.glassprobe/files/probe-log.jsonl
```

## 现在需要的开发环境

你不需要 Google Play 开发者账号，也不需要 Play Console。APK 是 Android
Studio/Gradle 在本地构建出来的。

推荐安装 Google 官方
[Android Studio](https://developer.android.com/studio)。当前这台 Mac 是 Apple
Silicon，应下载 `Mac (64-bit, ARM)` 版本。

Android Studio 第一次打开工程时会负责下载：

- Android SDK Platform 35
- Android SDK Build-Tools
- Android SDK Platform-Tools（其中包含 `adb`）
- Gradle 和工程依赖

打开工程目录：

```text
/Users/bytedance/Desktop/real git/apps/rokid-glass-probe
```

等待 Gradle Sync 完成后，执行：

```text
Build > Build Bundle(s) / APK(s) > Build APK(s)
```

生成的 Debug APK：

```text
app/build/outputs/apk/debug/app-debug.apk
```

## 官方真机连接路径

截至 Rokid 眼镜端裸机开发文档 v1.0.0（2026-06-05），官方写明的联调方式是：

1. 手机安装并连接 Rokid AI App。
2. 在手机 App 中打开“眼镜 ADB 调试”。
3. 使用 Rokid 专用开发线连接眼镜与电脑。
4. 在电脑执行 `adb devices`。
5. 安装 APK。

手机上的“眼镜 ADB 调试”开关只是允许眼镜开启 ADB 服务，不等于电脑已经连上
眼镜。官方文档没有把无线 ADB 列为裸机开发的正式路径。

连接开发线后，可运行：

```bash
./scripts/check-adb.sh
```

看到设备状态为 `device` 后安装：

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

如果是 `unauthorized`，查看眼镜端或 Rokid AI App 是否出现授权确认，再重新执行
`adb devices`。

## 第一次测试顺序

建议先跑 Rokid 官方 Sample，再跑本工程，避免把设备环境问题误判成我们的代码
问题。

下载并解压官方 Sample：

```bash
./scripts/download-official-sample.sh
```

脚本会放到：

```text
reference/GlassesBareDevSample
```

在 Android Studio 中打开它，构建并安装。确认官方 Sample 的拍照和佩戴状态页
正常后，再执行本工程测试：

1. 打开 `Reality Glass Probe`。
2. 授予相机权限。
3. 点击 `Capture Once`。
4. 确认日志出现 `CAPTURED_LOCAL` 且 `deleted=true`。
5. 点击 `Start 30s Periodic`，等待 2-3 次采集。
6. 点击 `Pause`，确认不再出现新采集日志。
7. 点击 `Resume`，确认恢复。
8. 摘下眼镜，确认出现 `WEAR_RECEIVER` 或 `LIVE_BROADCAST`。
9. 点击 `Stop and Cleanup`。

默认配置下本 App 不上传图片，不接 AI 分析，不接手机端 CXR 数据通道，行为与
旧探针一致。打开下面的采集配置后，它升级为乐奇眼镜的数据采集 Collector。

## 数据采集与上报（Collector）

`collector/` 包实现了 [04 设备接入 Connector 架构](../../docs/architecture/04-Device-Connector-Architecture.md)
中的设备侧 Collector，全部基于官方裸机路线的标准 Android API：

| 模态 | 实现 | 行为 |
| --- | --- | --- |
| image | CameraX（复用探针拍照） | 每张 JPEG 入本地 spool，异步上传后删除原图 |
| audio | `AudioRecord` 16kHz/单声道/PCM16 | 每 20 秒切一段 WAV 入 spool |
| sensor | `SensorManager` 加速度计+陀螺仪 | 每 10 秒聚合一个窗口，只上报 RMS/峰值摘要，原始波形不出设备 |

上报走 `EnvelopeSpooler`（持久化队列）+ `EnvelopeUploader`（后台线程，
multipart POST 到后端 `/internal/v1/envelopes`，幂等键重试安全，断网退避续传，
4xx 拒收即丢弃并审计）。信封字段与
`services/memory-platform/app/schemas.SourceEnvelopeIn` 一一对应：
手动拍照 `trigger=explicit`，佩戴/周期采集 `trigger=auto`，
`meta.device_kind=rokid_glasses`，`meta.device_adapter=rokid-glass-probe/0.2.0`。

### 打开采集上报

配置文件在设备上的 `files/collector.properties`，改配置不需要重新打包：

```bash
adb shell "run-as com.realitymemory.glassprobe sh -c 'cat > files/collector.properties'" <<'EOF'
upload_enabled=true
backend_base_url=http://<后端IP>:8000
device_id=<devices 表注册的 UUID，可暂时省略>
audio_enabled=true
imu_enabled=true
EOF
```

改完后重启采集服务（Stop and Cleanup 再 Start）。配置项与默认值见
`collector/CollectorConfig.java`。

### 观察采集链路

本地日志新增事件：`CAPTURED_SPOOLED` / `AUDIO_CHUNK_SPOOLED` / `UPLOAD_OK` /
`UPLOAD_FAILED` / `SPOOL_DROPPED` 等。后端侧可查 `audit_records`
（action=ingest）确认信封到达。

## 电脑实时预览（MJPEG）

App 内置一个眼镜本机 MJPEG 服务器（`collector/PreviewStreamServer`），把相机
实时帧推到浏览器，用于在电脑上直接看眼镜采集到的画面。链路：

```text
CameraX ImageAnalysis -> YUV→JPEG（≤10fps） -> HTTP multipart/x-mixed-replace
```

使用步骤：

1. 眼镜上打开 App，点 `Start PC Preview (MJPEG :8090)`。
2. 电脑上二选一：
   - 开发线（推荐，不依赖 Wi-Fi）：`adb forward tcp:8090 tcp:8090`，
     浏览器打开 `http://127.0.0.1:8090`；
   - 同一局域网：浏览器直接打开 `http://<眼镜IP>:8090`。
3. 页面内嵌 `/stream` 实时流；`/frame` 可单独取最近一帧（curl 调试用）。
4. 看完点 `Stop PC Preview`，服务器关闭并解除相机的分析用例。

说明：

- 预览是旁路能力，与拍照/上传互不影响；没有浏览器在看时不做 JPEG 编码，
  不额外耗电。
- 无认证、明文 HTTP，仅调试使用；端口和帧率在 `collector.properties` 里配
  （`preview_port` / `preview_max_fps` / `preview_jpeg_quality`）。
- 日志事件：`PREVIEW_STARTED` / `PREVIEW_CLIENT_JOINED` / `PREVIEW_STOPPED`。

### 已知限制（待真机验证）

- Android 12 对后台启动的前台服务有 camera/mic while-in-use 限制，佩戴广播
  拉起服务后能否访问相机麦克风，需要在 YodaOS-Sprite 真机上确认。
- 眼镜网络稳定性、上传对温升耗电的影响，按开发指南第 6 节的验证顺序记录。
