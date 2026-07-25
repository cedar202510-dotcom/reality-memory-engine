# IFLYBUDS 宿主侧采集器

把一副蓝牙耳机（科大讯飞 IFLYBUDS Air 2）接进 Reality Memory 的上行与下行通道。

耳机跑不了我方代码，所以真正的 Collector 跑在**宿主机**上，耳机只提供麦克风和扬声器：

```text
IFLYBUDS Air 2 (HFP mic / A2DP out)
  -> 本采集器（录音 → 本地 spool → 上传；订阅下行 → 本地策略 → 播报）
  -> SourceEnvelope(modality=audio) / DeliveryReceipt
  -> Memory Platform
```

架构背景与设计取舍见
[docs/architecture/08-IFLYBUDS-Earbuds-Connector.md](../../docs/architecture/08-IFLYBUDS-Earbuds-Connector.md)。

## 前提

- macOS（录音走 ffmpeg avfoundation，播报走系统 `say`）
- `ffmpeg` 在 PATH 里：`brew install ffmpeg`
- 终端已获得**麦克风权限**（系统设置 → 隐私与安全性 → 麦克风）
- memory-platform 在跑（默认 `http://127.0.0.1:8765`）

```bash
cd apps/iflybuds-collector
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
```

## 排障顺序就是子命令顺序

每一步都能独立跑通或独立失败，不用一上来就把整条链路接起来猜哪一段坏了。

### 1. 系统看得见耳机吗

```bash
./.venv/bin/python -m collector devices
```

列出所有音频输入设备，标出配置名命中的那个，并告诉你当前默认输出设备是什么、
播报会不会被本地策略拒绝。

### 2. 录得到、放得出吗（不连后端）

```bash
./.venv/bin/python -m collector selftest --seconds 3
```

录 3 秒并报告峰值电平（接近 0 = 耳机麦克风没被选中），然后播一句测试语音。

### 3. 注册设备

```bash
./.venv/bin/python -m collector register --name "IFLYBUDS Air 2"
export RME_EARBUDS_DEVICE_ID=<打印出来的 device_id>
```

按名字幂等，每次启动都可以调一次。

### 4. 上行通不通

```bash
./.venv/bin/python -m collector capture --seconds 8
```

录一段并立刻上传，打印信封 id。

### 5. 开一段记忆会话（说话即录）

```bash
./.venv/bin/python -m collector listen
```

监听麦克风，按「一句话」自动分段上传（VAD：静音 800ms 断句，短于 600ms 的片段当噪声丢弃）。
Ctrl-C 结束会话并释放麦克风。

**会话制是默认行为**：不开会话就不监听。没有「后台默默一直听」这个状态——那会让
「有没有在录」变成用户看不见的东西。

会话里说「小忆，我钥匙在哪」会走问答链路，答案念回耳机；普通陈述才进记忆抽取。

### 6. 常驻

```bash
./.venv/bin/python -m collector run
```

订阅下行（长连优先，断了退回 inbox 轮询）、执行采集请求、播报提醒、补传 spool 积压。
默认**不开**采集会话，等控制台下发「开始周期采集」；要启动即监听加 `--listen`。
Ctrl-C 退出，未上传的录音留在 spool 里等下次启动。

### 6. 下发一条播报（扮演云端，验证下行）

另开一个终端：

```bash
./.venv/bin/python -m collector push "牛奶还有两天过期"
```

## 配置

全部走环境变量，前缀 `RME_EARBUDS_`。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `API_BASE_URL` | `http://127.0.0.1:8765` | 后端地址 |
| `DEVICE_ID` | 空 | `register` 后拿到；`run` 必需 |
| `INPUT_DEVICE` | `IFLYBUDS` | 输入设备名**子串**，不区分大小写 |
| `OUTPUT_DEVICE` | `IFLYBUDS` | 期望的播放设备名子串 |
| `ALLOW_ANY_OUTPUT` | `false` | `true` = 默认输出不是耳机也照播（会外放，慎用） |
| `SAMPLE_RATE` / `CHANNELS` | `16000` / `1` | HFP 链路本身就是这个规格 |
| `DEFAULT_DURATION_SECONDS` | `8` | 请求没带时长时录多久 |
| `MAX_DURATION_SECONDS` | `60` | 本地采集预算上限，超出按上限截断并在回执里说明 |
| `DEFAULT_INTERVAL_SECONDS` | `60` | `START_PERIODIC` 没带间隔时的周期 |
| `SPOOL_DIR` | `~/.rme-earbuds-spool` | 本地队列 |
| `START_PAUSED` | `false` | 启动即隐私暂停，直到云端下发 `RESUME` |
| `CAPTURE_MODE` | `vad` | `vad` = 说话即录、静音断句；`periodic` = 每 N 秒录一段定长 |
| `VAD_SILENCE_MS` | `800` | 静音多久算一句说完。中文句中停顿的上界大约就在这里 |
| `VAD_MIN_SPEECH_MS` | `600` | 短于此丢弃（咳嗽、鼠标点击、椅子响都长这样） |
| `VAD_MAX_SEGMENT_MS` | `30000` | 单句上限，防止持续噪声录成一条巨大证据 |
| `VAD_THRESHOLD_FACTOR` | `3.0` | 阈值 = 本底噪声 × 该系数，跟着环境走而不是写死 |
| `TTS_VOICE` | 空 | 强制指定 `say` 音色。留空时按正文语言自动选（中文 → Tingting 等 `zh_*` 音色） |

## 设备保留拒绝权

云端下发的是**请求**不是命令（通信架构 §8）。所有「能不能做」的判断集中在
[`collector/policy.py`](collector/policy.py)：

- 请求拍照 → `REJECTED`「耳机没有摄像头」，不做就近替代
- 隐私暂停中 → `REJECTED`，麦克风根本不会被打开
- 时长超预算 → 按上限录，回执里同时给出请求值与实际值
- 默认输出设备不是耳机 → `REJECTED`，不把私人提醒外放出去

播报还有一条不属于策略但同样致命的：**中文提醒必须用中文音色**。系统默认音色多半是英文的，
用它念中文出来是一串听不懂的音节，而 `say` 返回 0、回执照样是 `SPOKEN`——云端看不出任何异常。
采集器按正文语言自动选音色，并把实际用的音色写进 `SPOKEN` 回执的 `voice` 字段。

## 测试

```bash
./.venv/bin/python -m pytest -q
```

全部用替身，不碰麦克风、不碰扬声器、不碰网络，也不需要数据库。真机部分由
`selftest` 覆盖，那是人肉验收。后端侧的契约测试在
`services/memory-platform/tests/test_earbuds_connector.py`。
