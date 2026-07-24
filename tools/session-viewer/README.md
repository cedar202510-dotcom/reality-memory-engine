# Reality Memory 调试台

电脑端开发辅助程序，用于实时观察戒指、手机中介和 Rokid 眼镜采集链路，也可以检查从手机沙盒拉取的历史 Session。它不是第二个用户 App；真正连接 CXR-L 眼镜和戒指的运行时仍在统一手机 App 中。

## 双击运行

生成桌面程序：

```bash
tools/session-viewer/build-macos-app.sh
```

桌面会出现 `Reality Memory Debug Console.app`。双击后程序会自动：

- 启动本机调试服务
- 通过 Bonjour 等待手机 App
- 打开 `http://127.0.0.1:8787`
- 将日志写入 `~/Library/Logs/RealityMemoryDebugConsole.log`

手机与 Mac 需要位于同一局域网。手机 App 必须保持打开；当前 CXR-L 过渡方案仍由手机完成 Rokid 授权、眼镜连接、图片和音频采集。

## 实时联调

实时页分层显示：

- 戒指名称、型号、序列号、固件、电量和 iOS Peripheral UUID
- Ring Sound NUS 服务、通知特征和写入特征 UUID
- 只符合戒指协议的扫描候选及 RSSI
- 六轴信号的实时动作强度、三轴加速度和三轴角速度
- 当前动作相对触发阈值的百分比，以及安静、明显动作、触发三个范围
- 最近一次快速移动判断、眼镜状态、Session 状态和手机日志
- 戒指触发或手动采集的实时图片与短音频
- 从电脑发回手机的扫描、连接、灵敏度、拍照、音频和 Session 控制命令

iOS 不向 App 暴露 BLE MAC 地址，因此端到端联调模式显示 iOS Peripheral UUID。若要读取 MAC，需要让 Mac 直接连接戒指；此时戒指无法同时保持手机连接，不适合测试“戒指 → 手机 → 眼镜”的完整链路。

### 动作强度与动态采集

- 当前默认将戒指固定在眼镜上，规则版本为 `glasses-head-transition.v1`。
- 检测器累计短时三轴转角，并比较重力方向变化；中档初始阈值为累计转角 `16°` 或重力方向变化 `12°`。
- 达到变化阈值后不会在转动峰值立即拍照，而是等待校正角速度连续约 `0.5` 秒回到稳定范围。
- 回稳后只请求 1 张代表图，不自动进入每 8 秒重复截图窗口。
- 行走等持续运动需要连续两个窗口确认；运动期间不拍，停止并回稳后最多触发一次。
- 只动眼睛而头部不动不会产生六轴触发，这是当前方案明确的能力边界。
- 手指佩戴的相对峰值检测仍作为旧实验规则保留，不与眼镜安装位样本混合校准。
- 一次有效头部转向可同时开启 8 秒短音频窗口。
- CXR-L 当前没有公开短视频录制 API，因此过渡方案不会把极强动作切换成视频。该能力由后续 RV101 原生 APK 的 CameraX 链路实现。

“常见动作标定”按传感器安装位置分为两组：

- `固定在眼镜`：记录头部静止、抬头、左右转头、低头看物品、拿放水杯、坐姿起立和行走。
- `手指佩戴（旧）`：保留此前静止、拿放水杯、坐下起身、正常行走、抬手触物和快速挥手样本。

两组样本分别统计和清空，不会混合校准。每条记录保存 `mountPosition`、安装配置版本、采样完整度、加速度突变与转动速度的 P95/最大值，以及当前阈值越线结果。固定在眼镜时必须保持戒指相对镜框的位置和朝向不变，否则三轴方向不再可直接比较。数据位于：

```text
~/Library/Application Support/RealityMemoryDebug/action-samples.json
```

## 从手机拉取后启动

手机 App 采集完一次 Session 后，在电脑上运行：

```bash
tools/session-viewer/pull-ios-sandbox.sh
```

脚本会输出一个 `/tmp/rme-session-viewer-...` 目录，然后用它启动查看器：

```bash
node tools/session-viewer/server.mjs /tmp/rme-session-viewer-20260724-091454
```

然后打开：

```text
http://127.0.0.1:8787
```

如果连接了多台设备，可以手动传入 device id：

```bash
tools/session-viewer/pull-ios-sandbox.sh F7A8B39B-4D84-5111-BBD9-24F5DBE9125B
```

## 读取已有目录

```bash
node tools/session-viewer/server.mjs /tmp/rme-device-container-20260724-0909
```

传入路径可以是：

- `RealityMemoryProbe` 根目录
- 包含 `RealityMemoryProbe` 的目录
- `devicectl device copy from` 拉出的容器目录，只要里面有 `sessions/`

## 当前能力

- 列出所有采集 Session
- 显示开始/结束时间、采集状态、图片数量、短音频数量、戒指样本数和审计事件数量
- 按 Session 时间线对齐图片、短音频、戒指动作判断和设备事件
- 显示本地图片证据
- 将原始 `.pcm` 短音频临时包装成 WAV，供浏览器播放
- 在“动作强度、三轴加速度、三轴角速度”三种视图间切换
- 按戒指量程把原始 `Int16` 换算成 `g` 和 `°/s`，显示 P90 与峰值
- 在六轴曲线上标出快速移动判断时刻，并与眼镜图片、短音频共用 Session 时间标尺
- 分层展示六轴原始数据统计、快速移动判断及其关联的图片/音频
- 下载完整 `ring/imu.ndjson`；页面为了流畅最多抽样显示 5000 个点，原始文件不被修改
- 展开查看每条 observation 的原始 JSON

## 注意

音频播放默认按 `PCM_S16LE / mono / 16000 Hz` 解释。若听起来速度不对，可以在页面右上角切换采样率。后续应由正式 `EvidenceItem` 写入准确的 codec、sampleRate、channelCount 和 duration。

戒指曲线中的横轴使用手机收到每批数据的绝对时间，并根据同一批样本的设备相对时间向前估算各采样点位置。它适合做图片、音频和动作判断的时间对照，但不是高精度硬件时钟同步结果；正式数据契约仍需保留设备时间、手机接收时间和时钟不确定性。
