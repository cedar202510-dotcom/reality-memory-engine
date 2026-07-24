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
- 显示开始/结束时间、采集状态、图片数量、短音频数量和审计事件数量
- 按 Session 时间线对齐图片和短音频
- 显示本地图片证据
- 将原始 `.pcm` 短音频临时包装成 WAV，供浏览器播放
- 展开查看每条 observation 的原始 JSON

## 注意

音频播放默认按 `PCM_S16LE / mono / 16000 Hz` 解释。若听起来速度不对，可以在页面右上角切换采样率。后续应由正式 `EvidenceItem` 写入准确的 codec、sampleRate、channelCount 和 duration。
