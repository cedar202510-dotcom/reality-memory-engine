# Reality Memory iOS App

统一的 Reality Memory 手机 App。当前 iOS 版本通过 CXR-L iOS SDK 1.0.4 接入 Rokid Glasses，并通过 CoreBluetooth 接入 Ring Sound 戒指，用来验证图片、短音频/VAD、戒指六轴传感器、跨设备触发、采集 Session 和本地证据清单；它不是眼镜专用 App，也不与音频、图片等模态拆成多个用户 App。

验证顺序：

1. 检测手机上的 Rokid AI App。
2. 请求相机和麦克风授权。
3. 等待眼镜 BLE 链路连接。
4. 在眼镜上打开 Custom View。
5. 请求一张 1024 x 768 JPEG 并在手机内存中预览。
6. 以 5、15、30 或 60 秒间隔运行受控采集 Session。
7. 可选开启会话内短音频/VAD，将命中的语音片段元数据写入同一个 Session。
8. 可连接 Ring Sound 戒指，完整记录 `0x0605` 六轴 IMU 批次。
9. 用透明阈值规则判断“快速移动”，并触发带同一判断编号的眼镜图片和 8 秒短音频窗口。
10. 将 Session、采集结果、音频片段、戒指判断和审计事件写入结构化 JSON。

## 戒指联动

手机 App 直接实现 Ring Sound v4 的 Nordic UART Service 协议，不依赖电脑中转。iOS 不向 App 暴露蓝牙 MAC 地址，所以手机端以 CoreBluetooth 设备 UUID 标识戒指；传感器字段仍与供应商协议及 Windows 采集方案保持一致。

真机操作顺序：

1. 点“扫描”，选择戒指并连接。
2. 单击戒指切换到手势模式。
3. 点“开启传感器”。只有收到 `0x0602 error_code=0` 后，界面才显示“传感器采集中”；若提示设备忙，重新切换戒指模式再试。
4. 开启“保留本地样本”，否则只保存统计和动作判断，不保存完整原始六轴数据。
5. 保持“快速移动触发眼镜采集”和“触发时采集 8 秒短音频”开启，再开始采集会话。

原始 IMU 不滤波、不换算、不去重。每批保留设备时间戳、连续序号和手机收到批次的绝对时间。当前“快速移动”只是测试规则，不是最终动作模型：它比较相邻样本的加速度向量变化和陀螺仪向量幅度，支持高、中、低三档灵敏度，并有 8 秒冷却时间。

## 采集 Session

- Session 必须在 BLE 已连接、Custom View 已打开时由用户明确开始。
- Custom View 默认使用纯黑空内容树，保持会话已构建但不在眼镜上显示调试文字。
- “眼镜调试文字”只用于联调，且只能在打开 Custom View 前切换。
- 支持开始、暂停、恢复和结束；BLE 断开或 Custom View 关闭会自动暂停，摘下眼镜会结束。
- “保留本地样本”默认关闭。关闭时只记录采集元数据，JPEG 和 PCM 都不落盘。
- 开启本地样本后，图片和 VAD 命中的短音频只写入 App 沙盒，标记为 `PENDING_LOCAL`，不允许上传。
- 每次状态变化和采集结果同时写入 Xcode unified logging 与 `debug-events.ndjson`。

本地结构：

```text
Application Support/RealityMemoryProbe/
  debug-events.ndjson
  sessions/<session-id>/
    session.json
    evidence/<observation-id>.webp
    evidence/<observation-id>.pcm
    ring/imu.ndjson
```

`session.json` 使用 `rme.capture-session.v1`，可作为后续结构化解析和 ActivityEpisode/MemoryCandidate 闭环的输入清单。图片、音频和戒指动作判断都属于同一个采集 Session；其中 Session 是设备采集边界，ActivityEpisode 才是后续分析出的“做饭、找东西、阅读”等现实活动边界。

`ring/imu.ndjson` 每行是一批 `rme.ring-imu-batch.v1` 原始数据。`session.json` 只记录传感器参数、批次数、样本数、序号异常、动作判断和文件引用，避免长会话反复重写全部传感器样本。

## 打开工程

依赖安装完成后，只打开：

```text
RMEGlassProbe.xcworkspace
```

不要使用 `RMEGlassProbe.xcodeproj`，否则 CocoaPods Framework 不会被链接。

## 真机要求

- iPhone 运行 iOS 16 或更高版本。
- iPhone 已安装 Rokid AI App，并已绑定 Rokid Glasses。
- Xcode 已登录 Apple 账号，并使用 `Automatically manage signing`。
- CXR-L 的 `cxrl://auth/callback` 回调由 App 的 `onOpenURL` 转交给 SDK。

本 App 不上传照片或音频，也不自行保存授权 token。只有用户打开“保留本地样本”后，Session 图片和短音频才会临时写入 App 沙盒。

## 当前运行边界

CXR-L 采集由 iPhone App、Rokid AI App 和眼镜链路共同完成。当前定时 Session 只承诺 App 前台运行；锁屏、后台、App 被系统终止后的采集行为需要分别做真机实验，不能视为已支持。

## 静默与后台测试

眼镜端“静默”与 iPhone 端“后台运行”是两件事：

- 静默模式仍会打开 CXR-L Custom View，但发送纯黑背景和空 `children`，从而保持拍照所需的眼镜会话。
- 静默 Custom View 只能隐藏应用自己的文字和图片，不能关闭 `takePhotoWithData` 触发的眼镜系统拍照回显。CXR-L 1.0.4 公开接口及官方 Sample 只提供 `width`、`height`、`quality`，没有 `silent` 或 `preview` 开关。
- iPhone 切到后台后，iOS 可能暂停普通定时任务。`bluetooth-central` 只用于处理相关蓝牙事件，不代表 App 可以无限期定时拍照。
- Observation 会保存 `scheduledAt`、`completedAt` 和 `applicationState`。定时器因挂起而明显晚醒时，会记录 `SCHEDULER_DELAYED_*MS`，不会回到前台后补拍并算作正常后台采集。

建议每轮使用 15 秒间隔并分别运行至少 2 分钟：

1. App 保持前台。
2. 切换到其他 App，但不锁屏。
3. 锁屏。
4. 从 App 切换器中强制结束进程。

每轮单独结束并分享 `session.json`。只有照片成功时间持续覆盖对应测试窗口，才能认定该状态支持周期采集。
