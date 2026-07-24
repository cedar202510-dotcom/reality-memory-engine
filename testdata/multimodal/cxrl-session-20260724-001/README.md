# CXR-L 多模态采集测试包 2026-07-24-001

这是一份由 Reality 手机 App 和 Rokid CXR-L 链路在 iPhone 真机上采集的真实测试数据，用于验证图片、短音频、VAD 切分、时间对齐、数据契约和后续结构化解析。

## 隐私与使用边界

- 数据包含真实环境图片和真实语音，只允许在 Reality Memory Engine 私有仓库及其受控测试环境中使用。
- 禁止复制到公开仓库、公开数据集、演示站点或第三方模型训练集。
- 原始 Session 的 `uploadAllowed` 为 `false`。本目录是数据所有者在 2026-07-24 明确要求建立的单次私有测试夹具，不代表产品默认允许上传原始媒体。
- 如果仓库将来改为公开，必须在公开前删除本目录并清理 Git 历史。

## 数据概览

| 类型 | 数量 | 格式 |
|---|---:|---|
| 图片 | 3 | 实际编码为 WebP，768 x 1024 |
| 音频 | 5 | PCM S16LE，16 kHz，单声道 |
| Session 元数据 | 1 | `rme.capture-session.v1` |

采集时间范围约为 `2026-07-24T01:07:04Z` 至 `2026-07-24T01:08:38Z`。图片由 30 秒周期采集产生，音频由会话内 VAD 切分产生。

## 目录结构

```text
session.json
evidence/
  *.jpg
  *.pcm
SHA256SUMS
```

`session.json` 是时间轴和媒体引用的事实来源。测试代码应通过其中的 `localMediaReference` 定位媒体，不应依赖目录遍历顺序。

## 已知真实边界

### 图片扩展名与编码不一致

三张图片的文件名扩展名为 `.jpg`，但文件魔数和系统解码结果表明实际编码是 WebP。这是采集链路的真实输出，测试解析器必须按内容识别媒体类型，不能只相信扩展名。

### 音频包含 VAD 前缓冲

PCM 文件包含语音开始前的预缓冲数据，因此按文件字节数计算的总时长会长于 `audioObservations[].durationMilliseconds`。后者描述有效语音片段时间，文件则保留了上下文。

### Session 处于暂停状态

该 Session 的最终状态是 `paused`，不是 `ended`。解析器和查看器不得假设所有测试 Session 都有结束时间。

## 本地检查

查看图片真实格式：

```bash
file evidence/*.jpg
sips -g pixelWidth -g pixelHeight -g format evidence/*.jpg
```

播放 PCM：

```bash
ffplay -f s16le -ar 16000 -ac 1 evidence/<文件名>.pcm
```

校验文件：

```bash
shasum -a 256 -c SHA256SUMS
```

