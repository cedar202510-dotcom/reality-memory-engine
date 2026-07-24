# Reality Memory Engine 多模态测试数据包

这个目录保存 Reality Memory Engine 早期真机采集样本，用于后续验证图片、短音频、戒指事件、时间对齐、解析器和记忆沉淀流程。

当前数据集：

- `datasets/2026-07-24-ios-cxrl-session-001/`
  - 设备：iPhone 17 真机上的统一手机 App
  - 链路：iOS App 通过 CXR-L/Rokid 链路采集眼镜图片，同时用手机侧 VAD 采集短音频
  - 内容：1 个采集会话，3 张图片，5 段短音频，1 份调试事件日志
  - 戒指：本次导出包含戒指连接、确认设备、开启传感器等调试事件，但没有持久化到会话内的戒指传感器样本文件
- `datasets/2026-07-24-glasses-mounted-ring-small-001/`
  - 设备：iOS/CXR-L 手机网关，外置戒指固定在眼镜框上
  - 内容：5 张图片、1 段短音频、338 个原始 IMU 样本、1 次触发判断
  - 用途：验证旧数据兼容、多模态时间关联、PCM 实际时长和 v1 契约映射
  - 限制：不是 RV101 原生 `SensorManager` 数据，不能用来宣称眼镜原生六轴已经验证

## 目录说明

```text
multimodal-test-data/
  README.md
  DATA_STRUCTURE.md
  datasets/
    2026-07-24-ios-cxrl-session-001/
      manifest.json
      debug-events.ndjson
      sessions/
        ce998edb-cc5f-4c18-a93f-55d6b97e7f9d/
          session.json
          evidence/
            *.jpg
            *.pcm
      derived/
        wav/
          *.wav
    2026-07-24-glasses-mounted-ring-small-001/
      manifest.json
      raw/
        session.json
        evidence/
        ring/imu.ndjson
      normalized/
        capture-session.json
        capture-intents.ndjson
        capture-windows.ndjson
        capture-attempts.ndjson
        source-envelopes.ndjson
        evidence-items.ndjson
```

`sessions/.../session.json` 和 `evidence/*` 是从手机 App 沙盒拉出的原始数据。`derived/wav/*` 是为了人工试听额外生成的 WAV 包装文件，不是手机端原始证据格式。

第二个数据集中的 `raw/` 同样不改写原始导出，`normalized/` 是按
[`Reality-Memory-Multimodal-Data-Contract-v1.0.md`](../docs/engineering/Reality-Memory-Multimodal-Data-Contract-v1.0.md)
生成的兼容输入。历史数据没有记录手机单调时钟，因此对应字段明确为 `null`，不能用
上传时间补造。

## 推荐使用方式

1. 解析 `manifest.json` 获得数据集总体信息和媒体时间轴。
2. 读取 `sessions/<会话ID>/session.json` 作为手机端原始会话记录。
3. 按 `localMediaReference` 找到原始图片和 PCM 音频。
4. 用 `scheduledAt`、`startedAt`、`endedAt`、`completedAt` 做跨模态时间对齐。
5. 图片解析器和音频解析器只应该输出候选观察，不应该直接写长期事实。

当前只保留一个很小的外置戒指样本。Rokid 原生 APK 真机采集后应新增独立数据集，
不要覆盖或混入这个兼容样本。

详细字段说明见 [DATA_STRUCTURE.md](DATA_STRUCTURE.md)。
