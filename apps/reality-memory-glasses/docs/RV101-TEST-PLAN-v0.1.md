# RV101 真机测试计划 v0.1

## 1. 本次要证明什么

本测试不是只看 APK 能否打开，而是验证一次完整的眼镜端闭环：

```text
佩戴并提示
  -> 默认开启本次感知，用户可单击取消
  -> 眼镜 IMU 识别相对稳定后的头动变化
  -> 图片 / 短视频 / 短音频 / IMU 进入同一采集窗口
  -> Debug 证据通过开发线上传到电脑后端
  -> 原始证据和契约数据可导出
  -> 摘下或取消本次后停止新采集
  -> 文字和语音提醒可以触达用户
```

首轮只验收上传入库，不把后端模型输出正确率作为设备测试通过条件，也不把头动解释
为具体行为。测试结果用于校准设备能力、时间、阈值、功耗和数据契约。

## 2. 测试前准备

- 仓库已经检出 `codex/full-stack-integration` 分支；后端和脚本均从该分支运行，
  不要使用 `main` 或其他分支。
- RV101 眼镜与 Rokid 专用开发线。
- 手机 Rokid AI App 已连接眼镜，并打开“眼镜 ADB 调试”。
- 电脑已安装 Android Platform-Tools，`adb devices` 只出现一台状态为 `device` 的设备。
- 使用随 APK 一起提供的 `scripts/install-on-rv101.sh` 安装。
- 按 `RV101-LOCAL-BACKEND-LINK-v0.1.md` 启动电脑后端；安装脚本会自动执行
  `adb reverse tcp:8765 tcp:8765`。
- 场景中不要出现无关人脸、身份证件、聊天页面、地址或未获同意的第三方对话。
- 准备一张桌子、一个无隐私文字的水杯和一段 10 米左右的行走路线。

### 2.1 测试电脑直接安装，不参与构建

测试包里的 `reality-memory-glasses-debug.apk` 已经是最终可安装产物。测试电脑
只负责安装和真机测试，不需要 Android Studio、Java 或 Gradle，也不要重新构建
APK。测试电脑只需：

1. 解压完整测试包，不要只接收 APK。
2. 安装与电脑系统匹配的 Android Platform-Tools。
3. 用开发线连接 RV101，并在 Rokid AI App 中开启眼镜 ADB 调试。
4. 校验 APK 未在传输中损坏：

```bash
shasum -a 256 -c SHA256SUMS
```

5. 在测试包根目录直接安装：

```bash
./scripts/install-on-rv101.sh ./reality-memory-glasses-debug.apk
```

该 Debug 安装脚本会通过 ADB 开启 `SYSTEM_ALERT_WINDOW`，用于验证后台消息的短时透明
覆盖层。它不是相机、麦克风或后台采集权限，也不代表正式 APK 可以静默获得此权限。

`adb install -r` 会保留同包名 App 的数据并覆盖安装。若出现
`INSTALL_FAILED_UPDATE_INCOMPATIBLE`，说明眼镜上已有同包名但签名不同的 APK；
不要直接卸载，因为卸载会删除尚未导出的 App 私有数据。先运行收集脚本保留数据，
再把错误和旧版本信息反馈给开发者决定是否卸载。

安装并开始记录：

```bash
./scripts/install-on-rv101.sh ./reality-memory-glasses-debug.apk
./scripts/start-test-run.sh 20260724-rv101-native-001
```

## 3. 测试动作和预期

本轮必须先完成 T01、P01、P02 和 P03，确认图片从眼镜采集到电脑后端已经
打通，再继续音频、视频和运动策略测试。不要用视频成功与否阻塞第一轮图片验收。

| 编号 | 操作 | 持续/次数 | 预期结果 |
| --- | --- | --- | --- |
| T01 | 打开 App 并授予相机、麦克风权限 | 1 次 | 只显示绿色圆环、圆点和两行告知；约 5 秒后恢复空白；可听到开始播报 |
| T02 | 戴上、摘下、再次戴上 | 各 2 次 | 每次佩戴只提示一次；摘下结束会话；重新佩戴生成新会话 |
| P01 | 开启本次感知后保持不动 | 10 秒 | 启动窗口成功保存 1 张 JPG；审计出现 `CAMERA_PREPARED_IMAGE_ONLY`，且 `CAMERA_MODE_BOUND` 的模式为 `IMAGE` |
| P02 | 按眼镜 AI 键主动“记一下” | 2 次，间隔 15 秒 | 每次图片尝试为 `SUCCEEDED`，并生成 `EvidenceItem`、`SourceEnvelope` 和 `*.upload.json` |
| P03 | 在电脑后端查询本轮接收记录 | 1 次 | 图片 MIME 为 `image/jpeg`，`capture_window_id` 与眼镜端一致，同一证据只入库一次 |
| T03 | 坐姿保持头部相对稳定 | 30 秒 | IMU 有数据；不应连续触发运动窗口 |
| T04 | 缓慢左转头、回中，缓慢右转头、回中 | 每侧 3 次，间隔 3 秒 | 产生少量 `HEAD_MOTION_TRANSITION`；普通变化优先图片 |
| T05 | 抬头、回中，低头、回中 | 每方向 3 次，间隔 3 秒 | IMU 轴值与 T04 有可区分变化；记录实际触发次数 |
| T06 | 较快转头后回稳 | 3 次，间隔 12 秒 | 图片链路通过后再测；应出现 `IMAGE -> VIDEO -> IMAGE` 模式切换，短视频仍暂用 2.5 秒验证值 |
| T07 | 站起、坐下 | 3 轮 | 记录 IMU 与是否触发，不要求识别成“站起” |
| T08 | 正常行走约 10 米 | 往返 2 次 | 记录连续运动下的窗口数量、冷却和误触发情况 |
| T09 | 按眼镜 AI 键“记一下”，看向水杯并说固定语句 | 2 次 | 界面不显示采集状态；图片、10 秒音频和 IMU 共用一个 `capture_window_id` |
| T10 | 固定语句：“这杯水有一点凉，我不太喜欢。” | 随 T09 | PCM 中能听清；记录真实通道数、字节数和时长 |
| T11 | 佩戴告知出现时单击 | 1 次 | 显示“本次现实感知已取消”约 3 秒；会话为 `ENDED`；继续移动不产生新证据 |
| T12 | 再次摘下并戴上 | 1 次 | 创建新会话并重新显示佩戴告知，不继承上次取消状态 |
| T13 | App 已进入空白感知状态后，用 ADB 发送测试提醒 | 2 次 | 显示绿色提醒并播报 TTS；单击后只关闭提醒，不结束采集 |
| T14 | 空白感知状态下单击，再继续移动 | 30 秒 | 会话为 `ENDED`；不再开始新采集 |
| T15 | 断开开发线后触发一次采集，再接回并重建端口映射 | 1 次 | 先记录 `RETRY_PENDING`，恢复后变为 `UPLOADED`；后端不重复入库 |
| T16 | 后端向眼镜下发固定展示消息 | 每种意图 1 次 | 约 3 秒内显示对应图标和文字；后端依次收到 `RECEIVED`、`PRESENTED`、`DISMISSED` 回执 |

T13 命令：

```bash
./scripts/send-test-reminder.sh "记得把资料给小王"
```

T16 优先使用正式后端和 `scripts/test-downlink-presentation.sh`。若联调电脑暂时没有
PostgreSQL，可先运行下面的模拟器，只验证设备注册、消息拉取、眼镜展示和状态回执：

```bash
node ./scripts/fake-downlink-server.mjs REMINDER
```

模拟器明确拒绝采集证据上传，不会把真实图片、视频或音频误判为已入库。

## 4. 30 分钟稳定性补测

功能测试通过后再做，不要在首轮同时进行：

1. 记录测试前电量、温度和剩余空间。
2. 佩戴运行 30 分钟，按日常节奏静坐、转头和行走。
3. 每 5 分钟记录眼镜体感温度、电量和异常提示。
4. 结束后记录 CameraX 失败、麦克风占用、丢失佩戴广播、崩溃和重启次数。
5. 比较静坐时的误触发数量和动态时的漏触发数量。

## 5. 必须保留的数据

测试结束必须执行：

```bash
./scripts/collect-test-results.sh device-test-results/20260724-rv101-native-001
```

结果包必须包含：

- `run-info.txt`：测试编号、版本和起止时间。
- `device-getprop.txt`：型号、固件、Android 版本和构建指纹。
- `adb-devices-before.txt`：ADB 序列号和连接状态。
- `adb-reverse-before.txt`：眼镜到电脑后端的端口映射。
- `sensorservice-before/after.txt`：传感器清单和运行状态。
- `battery-before/after.txt`：电量与温度。
- `package-before/after.txt`：权限、版本和安装状态。
- `logcat.txt`：本次测试完整系统日志。
- `reality-memory-app-data.tar`：App 审计、契约 JSON、加密 Outbox，以及 Debug
  APK 限额保留的原始图片、短视频、PCM、IMU 和 `*.upload.json` 上传状态。

Debug APK 的明文原始样本上限为 64 MB，TTL 标记为 24 小时；它们只用于受控测试。
Release APK 不生成明文副本。上传 GitHub 前由测试者确认样本不含无关个人信息。

## 6. GitHub 回传规则

每次发布上传一个测试包：

```text
reality-memory-glasses-<version>.zip
  reality-memory-glasses-debug.apk
  RV101-TEST-PLAN-v0.1.md
  RV101-CAPTURE-STRATEGY-v0.1.md
  SHA256SUMS
  scripts/
```

每次真机测试回传：

```text
<run-id>.tar.gz
<run-id>.tar.gz.sha256
```

小于仓库限制的受控测试结果可放入：

```text
multimodal-test-data/datasets/<run-id>/
```

较大的完整结果应作为同一 GitHub Release 的附件，不要反复提交 APK、日志和媒体到
Git 历史。进入仓库的长期测试夹具只挑选少量、匿名、可复用的代表样本。
