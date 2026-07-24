# RV101 真机测试计划 v0.1

## 1. 本次要证明什么

本测试不是只看 APK 能否打开，而是验证一次完整的眼镜端闭环：

```text
佩戴并提示
  -> 用户允许本次感知
  -> 眼镜 IMU 识别相对稳定后的头动变化
  -> 图片 / 短视频 / 短音频 / IMU 进入同一采集窗口
  -> 原始证据和契约数据可导出
  -> 暂停、摘下或本次关闭后停止新采集
  -> 文字和语音提醒可以触达用户
```

当前不验收图片或音频的语义解析，也不把头动解释为具体行为。测试结果用于校准
设备能力、时间、阈值、功耗和数据契约。

## 2. 测试前准备

- RV101 眼镜与 Rokid 专用开发线。
- 手机 Rokid AI App 已连接眼镜，并打开“眼镜 ADB 调试”。
- 电脑已安装 Android Platform-Tools，`adb devices` 只出现一台状态为 `device` 的设备。
- 使用随 APK 一起提供的 `scripts/install-on-rv101.sh` 安装。
- 场景中不要出现无关人脸、身份证件、聊天页面、地址或未获同意的第三方对话。
- 准备一张桌子、一个无隐私文字的水杯和一段 10 米左右的行走路线。

安装并开始记录：

```bash
./scripts/install-on-rv101.sh ./reality-memory-glasses-debug.apk
./scripts/start-test-run.sh 20260724-rv101-native-001
```

## 3. 测试动作和预期

| 编号 | 操作 | 持续/次数 | 预期结果 |
| --- | --- | --- | --- |
| T01 | 打开 App 并授予相机、麦克风权限 | 1 次 | 黑底界面正常；显示 5 秒提示；可听到开始播报 |
| T02 | 戴上、摘下、再次戴上 | 各 2 次 | 每次佩戴只提示一次；摘下结束会话；重新佩戴生成新会话 |
| T03 | 坐姿保持头部相对稳定 | 30 秒 | IMU 有数据；不应连续触发运动窗口 |
| T04 | 缓慢左转头、回中，缓慢右转头、回中 | 每侧 3 次，间隔 3 秒 | 产生少量 `HEAD_MOTION_TRANSITION`；普通变化优先图片 |
| T05 | 抬头、回中，低头、回中 | 每方向 3 次，间隔 3 秒 | IMU 轴值与 T04 有可区分变化；记录实际触发次数 |
| T06 | 较快转头后回稳 | 3 次，间隔 12 秒 | 强变化应尝试 2.5 秒短视频；不得每 8 秒无限循环 |
| T07 | 站起、坐下 | 3 轮 | 记录 IMU 与是否触发，不要求识别成“站起” |
| T08 | 正常行走约 10 米 | 往返 2 次 | 记录连续运动下的窗口数量、冷却和误触发情况 |
| T09 | 点击“记一下”，看向水杯并说固定语句 | 2 次 | 图片、10 秒音频和 IMU 共用一个 `capture_window_id` |
| T10 | 固定语句：“这杯水有一点凉，我不太喜欢。” | 随 T09 | PCM 中能听清；记录真实通道数、字节数和时长 |
| T11 | 点击“暂停”，重复 T04 和固定语句 | 30 秒 | 暂停后不产生新的媒体 Evidence |
| T12 | 点击“继续”，执行一次 T09 | 1 次 | 采集恢复；生成新的窗口 |
| T13 | 点击“测试提醒” | 2 次 | 眼镜显示提醒；能听到 TTS；记录是否抢占系统音频 |
| T14 | 点击“本次关闭”后继续移动 | 30 秒 | 会话为 `ENDED`；不再开始新采集 |

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
- `sensorservice-before/after.txt`：传感器清单和运行状态。
- `battery-before/after.txt`：电量与温度。
- `package-before/after.txt`：权限、版本和安装状态。
- `logcat.txt`：本次测试完整系统日志。
- `reality-memory-app-data.tar`：App 审计、契约 JSON、加密 Outbox，以及 Debug
  APK 限额保留的原始图片、短视频、PCM 和 IMU。

Debug APK 的明文原始样本上限为 64 MB，TTL 标记为 24 小时；它们只用于受控测试。
Release APK 不生成明文副本。上传 GitHub 前由测试者确认样本不含无关个人信息。

## 6. GitHub 回传规则

每次发布上传一个测试包：

```text
reality-memory-glasses-<version>.zip
  reality-memory-glasses-debug.apk
  RV101-TEST-PLAN-v0.1.md
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
