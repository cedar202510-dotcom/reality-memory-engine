# Reality CXR-L Probe

> Archived reference only. Reality Memory Engine 只有一个正式用户侧手机 App：`apps/mobile-app/`。本目录保留 CXR-L SDK 兼容性实验、官方 Sample 对照和历史真机记录，不再作为产品入口继续演进。

Reality Memory Engine 的过渡链路探针。当前以 **iOS 为主方案**，Android 工程保留为备用。

两端都属于 CXR-L 手机 App：

```text
iPhone / Android Phone
  -> CXR-L SDK
  -> 手机上的 Rokid AI App
  -> 已配对的 Rokid Glasses
```

它不在眼镜上安装 APK，因此不需要眼镜裸机开发所用的专用开发线。最终产品仍使用运行在 RV101 眼镜本机的原生 Android App；CXR-L 只用于开发线到位前验证真实图片、短音频和统一来源契约。

## iOS 主方案

目录：`ios/`

已实现：

- 使用官方 CXR-L iOS 1.0.4 Sample 随包 SDK。
- 使用 `RGCxrLink + RGCxrCustomViewSession` 新接口。
- 通过 `rokidai://` 拉起 Rokid AI App。
- 通过 `cxrl://auth/callback` 接收授权结果。
- 鉴权成功后由 SDK 自动准备 BLE 通道，无需手动 `connect(token)`。
- BLE 就绪后打开 CustomView，收到 opened 状态后才允许拍照。
- 手动拍照、30 秒周期拍照、佩戴状态门控。
- 30 秒受控眼镜音频流测试。
- 手机本地 PCM 音量计算和轻量 VAD，只保存命中的短人声片段。
- VAD 片段最长 15 秒；摘下、断连、手动停止或 30 秒测试到时立即停止。
- 最后一张图片只在内存中预览。
- 事件日志只保存时间、字节数、SHA-256、VAD 指标等元数据。
- CustomView 使用空白黑色页面；CXR-L 自身的系统拍照反馈仍无法由本探针关闭。

### 1. 安装开发工具

本机已经安装并验证：

- Apple Command Line Tools
- CocoaPods 1.16.2
- 项目 Pods

本机已经安装完整 Xcode，可直接构建和运行。

Xcode 安装完成后执行：

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
```

如果 Pods 需要重新生成：

```bash
cd "/Users/bytedance/Desktop/RealGit/archive/cxrl-probe/ios"
./scripts/bootstrap.sh
```

### 2. 用 Xcode 打开

必须打开 workspace，而不是单独打开 xcodeproj：

```text
ios/CXRClientDemo.xcworkspace
```

在 Xcode 中：

1. 选择 `CXRClientDemo` target。
2. 进入 `Signing & Capabilities`。
3. 选择你的 Apple Development Team。
4. 确认 Bundle ID 为 `com.realitymemory.cxrlprobe`；如与你账户冲突，改成你的唯一 ID。
5. 运行设备选择你的 iPhone，不要选 Simulator，蓝牙链路必须真机验证。

### 3. 手机准备

1. iPhone 已安装 Rokid AI App。
2. Rokid AI App 已连接眼镜。
3. iPhone 与 Mac 建立开发信任。
4. iOS 16 及以上设备开启 Developer Mode。

### 4. 首轮操作顺序

1. Xcode 点击 Run，将 App 安装到 iPhone。
2. 点 `1. Check Rokid AI App`。
3. 点 `2. Request glasses permissions`。
4. 在 Rokid AI App 中批准相机和麦克风权限。
5. Rokid AI App 通过 `cxrl://auth/callback` 返回 Probe。
6. 等待 `Authorization`、`BLE link`、`CustomView` 都显示 `READY`。
7. 点 `Capture once`。
8. 手机出现眼镜图片预览后，再点 `Start 30s timer`。
9. 点 `Start 30s audio/VAD test`，在测试窗口内先保持安静，再说一到两句短句。
10. 确认页面出现音量、音频包数量和 `Audio segments`；需要结束时点 `Stop audio/VAD test`。
11. 测试完成后点 `Delete local audio test segments`。

预期状态：

```text
Rokid AI App        READY
Authorization       READY
BLE link            READY
CustomView          READY
```

### 5. iOS 打包方式

第一次真机测试不需要先导出 IPA。Xcode 的 Run 会完成编译、签名并直接安装到 iPhone。

需要分发给其他测试者时，再使用：

```text
Product -> Archive -> Distribute App
```

通常选择 TestFlight。这里不是手工把文件压缩成 IPA。

### 6. iOS 日志与生命周期

元数据日志位于 App 沙盒：

```text
Library/Application Support/probe-events.jsonl
```

可通过 Xcode 的 Devices and Simulators 下载 App Container 后查看。

显式音频测试命中的 PCM 片段位于：

```text
Documents/audio-vad-test/
```

文件使用 iOS Data Protection，格式按 SDK 当前返回值暂按 16 kHz、16-bit little-endian PCM 解释。真机测试必须核对 SDK 报告的 codec、channels、实际播放速度和 ASR 结果，不能只凭字节流存在就认定格式正确。

CXR-L 没有暴露独立 VAD 回调，所以在 30 秒测试窗口内，眼镜到手机的音频流持续存在；静音数据只用于手机本地 VAD，不落盘、不上传。最终原生 Glass App 会把 AudioRecord + VAD 移到眼镜端。

`bluetooth-central` 允许 CoreBluetooth 的相关后台行为，但不保证普通 30 秒 Timer 永久运行。App 被用户强杀后，CXR-L 链路和采样一定停止。该限制也是 CXR-L 不能成为最终后台感知方案的原因之一。

## Android 备用方案

根目录仍是可打开的 Android Gradle 工程，使用：

```text
com.rokid.cxr:client-l:1.0.4
```

它已实现同样的授权、CustomView、拍照和 30 秒采样流程。Android 构建需要 [Android Studio](https://developer.android.com/studio) 与 Android SDK 36.1。

## 安全边界

- 不把 Rokid 账户中心授权 key 写入代码。
- 不记录或打印完整运行时 token。
- 不把 OpenAI API key 放入手机 App。
- 图片默认不写入相册或沙盒文件。
- 结构化 Session Agent 通过后端调用模型。

## 设计资料

- [CXR-L Token 与状态流](docs/CXRL-TOKEN-AND-STATE-FLOW.md)
- [Activity Session Agent 设计](docs/ACTIVITY-SESSION-AGENT-DESIGN.md)
- [结构化输出 Schema](schemas/activity-session-update.schema.json)

## 官方依据

- [Rokid SDK 选型页](https://open.rokid.com/sdk?lang=zh)
- [CXR-L 1.0.4 详细文档](https://custom.rokid.com/prod/rokid_web/84feb39f8ef141b0ad0326f902ab881f/pc/cn/3b63d21420e645e3affca478b39e4a13.html)
- [CXR-L iOS 1.0.4 官方 Sample](https://rokid-ota.oss-cn-hangzhou.aliyuncs.com/toB/Document/CXR-L/v1.0.4/iOS/ios_cxr_l_sample.zip)
