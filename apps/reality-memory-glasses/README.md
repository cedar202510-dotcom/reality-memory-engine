# Reality Memory for Glasses

这是运行在 Rokid Glasses RV101 本机上的正式 Android App 工程。它与
`apps/rokid-glass-probe/` 的关系是：

- `rokid-glass-probe`：保留为单项能力验证和设备排障基线。
- `reality-memory-glasses`：面向真实产品演进，负责端侧感知、用户交互、提醒呈现
  和短期证据交付。

它不是只面向研发的数据采集器。对用户而言，它首先是 Reality Memory 在眼镜上的
体验入口：明确告知何时开始、允许取消本次感知、支持用户主动“记一下”，并能显示
或播报后端 Agent 产生的提醒。当前阶段优先实现可靠采集，AI 判断和事实沉淀仍在
云端完成。当前“测试提醒”只验证本地文字和 TTS 呈现，真实云端下行通道与提醒
业务载荷尚未完成 review 和实现。

## 当前首版能力

- 接收 RV101 佩戴、摘下和镜腿折叠广播。
- 佩戴后以单绿界面告知“RealGit 已开启现实感知”，约 5 秒后恢复空白并进入本次
  采集会话。
- 读取眼镜自身加速度计与陀螺仪。
- 使用“稳定基线 -> 运动突变 -> 回稳”规则生成客观的头动采集意图。
- 普通头动：无业务预览图片 + 10 秒短音频 + 触发前后 IMU。
- 强头动：2.5 秒无业务预览短视频 + 10 秒短音频 + 触发前后 IMU。
- 活跃期间每 60 秒补一张基线图片和一个 IMU 窗口；后续由真机功耗和信息增量实验
  调整，不把该频率写成产品常量。
- 告知界面单击取消本次感知；再次佩戴时重新开启，不保留跨佩戴暂停状态。
- 保留眼镜 AI 键主动“记一下”，但采集过程不显示“已记下”或其它后台采集状态。
- Debug APK 可通过 ADB 拉起测试提醒，验证眼镜文字和 TTS 播报链路。
- 原始媒体使用 Android Keystore 中的 AES-256-GCM 密钥加密后进入本地 Outbox。
- 为每次采集生成 `CaptureSession`、`CaptureIntent`、`CaptureWindow`、
  `CaptureAttempt`、`SourceEnvelope` 和 `EvidenceItem`。
- Manifest 已声明网络权限，但设备绑定、受限凭证、Evidence 上传、删除回执和
  云端下行尚未实现。

当前 `0.1.0` 设备验证构建会在元数据中写入 24 小时 TTL，但尚未实现到期清理
任务。它只能用于显式测试，不能接入生产用户数据。正式联调前必须改为策略下发的
短 TTL，并实现本地密文、暂存文件和密钥引用的删除及回执。当前构建也仍使用一个
设备级 Keystore 别名直接加密，正式上传前需要补充每项 Evidence 的数据密钥封装
或等价的可独立失效方案。

头动规则只表达“出现了值得提高采集密度的变化”，不表达用户拿起了杯子、看见了
钥匙或开始吃饭。现实语义必须由后端多模态解析和记忆候选流程产生。

## 设备和构建基线

- 目标设备：Rokid Glasses RV101
- 系统基线：YodaOS-Sprite / Android 12 / API 31
- 语言：Kotlin
- 编译 SDK：35
- 目标 SDK：35（运行设备仍为 Android 12 / API 31）
- Java：17
- 相机：CameraX 1.4.2
- 音频：`AudioRecord`，优先 16 kHz / 8 通道 / `0x6000FC`，不支持时显式降级为单通道
- 传感器：`SensorManager.SENSOR_DELAY_GAME`

在仓库根目录执行：

```bash
cd apps/reality-memory-glasses
./gradlew test
./gradlew assembleDebug
```

APK 输出：

```text
app/build/outputs/apk/debug/app-debug.apk
```

已构建好的 APK 直接交给测试电脑安装。测试电脑只负责安装和真机测试，不参与
APK 构建；它只需要 Android Platform-Tools 中的 `adb`、Rokid 开发线和眼镜端
ADB 授权，不需要 Java、Gradle 或 Android Studio。安装命令和签名注意事项见
[RV101 真机测试计划](docs/RV101-TEST-PLAN-v0.1.md)。

每次交付 APK 时必须同时生成测试包：

```bash
./scripts/build-test-bundle.sh 0.1.1-debug
```

测试包包含 APK、SHA-256、[RV101 真机测试计划](docs/RV101-TEST-PLAN-v0.1.md)
以及安装、开始测试、收集日志和原始数据的脚本。不得只把一个没有测试说明的 APK
交给真机队友。

## 本地数据位置

眼镜 App 私有目录：

```text
/data/data/com.realitymemory.glasses/files/reality-memory/
```

其中：

- `outbox/<capture_session_id>/<capture_window_id>/`：加密媒体和契约 JSON。
- `audit.ndjson`：会话状态、窗口和证据入队的最小审计日志。
- `debug-export/`：仅 Debug APK 存在，最多保留 64 MB 受控测试明文样本，供回传
  检查图片、短视频、PCM 和 IMU；Release APK 不生成该目录。

通过开发线读取：

```bash
adb shell run-as com.realitymemory.glasses \
  find files/reality-memory -maxdepth 4 -type f

adb exec-out run-as com.realitymemory.glasses \
  tar -C files -cf - reality-memory > reality-memory-device-export.tar
```

真机队友应使用配套脚本完成一轮测试：

```bash
./scripts/install-on-rv101.sh ./reality-memory-glasses-debug.apk
./scripts/start-test-run.sh <run-id>
# 按测试计划完成动作
./scripts/collect-test-results.sh <start-test-run 输出的结果目录>
```

运行中的 Debug APK 可用下面的命令模拟一条云端 Agent 提醒：

```bash
./scripts/send-test-reminder.sh "记得把资料给小王"
```

导出的 `.bin.enc` 不能脱离该眼镜 Android Keystore 解密。需要交给后端的正式上传
流程应使用设备身份完成密钥封装；调试导出不能把生产密钥或明文媒体提交到 Git。

## 真机测试闸门

代码可以在没有开发线的电脑上构建。安装和以下结论必须由持有 RV101 与开发线的
队友验证：

1. 官方 Sample 可以通过 ADB 安装并运行。
2. CameraX 能同时绑定无预览 `ImageCapture` 与 `VideoCapture`。
3. 8 通道 AudioRecord 的实际通道数、文件大小和时长正确。
4. IMU 的实际采样率、轴向和时间戳稳定性。
5. 佩戴提示 Activity 是否允许从系统广播拉起；若固件阻止，则降级为 TTS + 通知。
6. 摘下、折叠、后台、熄屏、低电量和高温时是否可靠停止新采集。
7. 30 分钟运行的耗电、温升、崩溃、相机占用和音频冲突。
8. 运动触发阈值在抬头、转头、起身、行走和静坐手部活动下的误触发率。

真机未验证前，`rv101-axis/unknown` 和动态头动阈值都属于实验配置，不得作为稳定
产品能力对外承诺。

## 相关文档

- [眼镜端现有 UI 交互预览](docs/RV101-UI-PREVIEW.html)
- [数据采集架构](../../docs/architecture/01-Data-Capture-Architecture.md)
- [设备与云端通信](../../docs/architecture/04-Device-Cloud-Communication.md)
- [多模态数据契约 v1.0](../../docs/engineering/Reality-Memory-Multimodal-Data-Contract-v1.0.md)
- [机器 Schema](../../contracts/reality-memory/v1/README.md)
