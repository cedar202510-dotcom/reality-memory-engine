# Reality Memory Session Viewer

电脑端开发辅助查看器，用来快速检查手机 App 采集到的 Session 内容。它不是用户侧 App，只读取已经从手机沙盒拉到电脑上的本地文件。

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
