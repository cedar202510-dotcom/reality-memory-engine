# RealGit 与 Rokid AIUI 智能体接入方案 v0.1

> 状态：后端通道路由和最小 AIUI 工程已实现，待配置真实 HTTPS 域名、打包 AIX 和 Rokid 真机验收
> 目标：在保留眼镜后台感知与主动提醒能力的同时，让用户通过乐奇系统语音入口直接询问 RealGit Agent

## 1. 结论

接入 AIUI 不是只修改后端，也不应删除现有眼镜采集 APK 的消息下发能力。最终由三个部分共同组成：

```text
RealGit 眼镜采集 Runtime（Android APK）
  + RealGit 对话智能体（Rokid AIUI / AIX）
  + RealGit Agent Gateway 与 Memory Platform
```

两个眼镜端运行组件属于同一个 RealGit 产品，共享用户、家庭、设备和会话身份，但承担不同职责。

## 2. 眼镜采集 Runtime 保留的职责

现有 `apps/reality-memory-glasses/` 继续负责：

- 佩戴与摘下状态。
- 眼镜六轴传感器监听。
- 运动策略与系统拍照、带声短视频触发。
- Evidence 和设备事件上传。
- 佩戴告知、隐私状态、权限错误和采集异常。
- 后端主动提醒的接收、固定组件呈现和投递回执。

以下消息不能迁移为只依赖 AIUI：

| 场景 | 原因 |
| --- | --- |
| 佩戴后现实感知告知 | 属于采集 Runtime 本地生命周期，不应等待云端 Agent |
| 隐私暂停与禁采状态 | 属于系统策略，Agent 不得伪造 |
| 相机、录音和上传故障 | 只有采集 Runtime 掌握真实运行状态 |
| 主动任务、采购和重要提醒 | 用户没有主动唤醒 AIUI 时仍需要送达 |

## 3. AIUI 智能体新增的职责

新增独立工程，建议位置：

```text
apps/reality-memory-aiui-agent/
```

它负责：

- 通过乐奇系统语音入口进入 RealGit。
- 接收系统 ASR 产生的用户文本。
- 把问题和会话身份发送给 Agent Gateway。
- 在乐奇对话上下文中显示 Agent 回答或受约束卡片。
- 按策略使用 Rokid TTS 播报回答。

第一阶段使用系统唤醒词和智能体调度，例如：

```text
乐奇，问 RealGit 我的钥匙在哪里
```

不能把 AIUI 页面中的 `onVoiceWakeup` 等同于普通侧载 APK 获得自定义全局唤醒词。

## 4. 后端需要修改的部分

现有 `/v1/chat` 已能完成记忆查询并可自动下发 RV101。接入 AIUI 时需要增加来源和回答通道，避免同一回答同时出现在 AIUI 对话和原生覆盖层。

已实现请求：

```json
{
  "message": "我的钥匙在哪里",
  "session_id": "aiui-conversation-id",
  "source": "ROKID_AIUI",
  "device_id": "rv101-device-uuid",
  "correlation_id": "aiui:conversation-turn-id",
  "response_channel": "AIUI_CONVERSATION"
}
```

已实现通道：

| `response_channel` | 用途 |
| --- | --- |
| `AIUI_CONVERSATION` | 用户主动语音询问，回答直接返回 AIUI |
| `RV101_OVERLAY` | 后端主动提醒，发送给原生采集 Runtime |
| `CALLER` | 手机、Web 或普通 API 调用方直接接收 HTTP 回答 |

兼容规则：

1. AIUI 语音问答默认不再同时生成原生 `ANSWER` 覆盖层。
2. 主动任务、采购和重要提醒继续使用现有 `rme.glasses-presentation.v0`。
3. 下发失败不能吞掉 Agent 原回答。
4. `correlation_id` 应串联 AIUI 会话、Agent turn、设备消息和回执。
5. `ROKID_AIUI` 请求若同时要求原生 `delivery`，后端返回 422，防止重复显示。
6. 配置 `AIUI_CLIENT_TOKEN` 后，AIUI 必须携带 `X-RealGit-Client-Token`。

## 5. 契约拆分

现有眼镜呈现契约不整体迁移，而是拆成共享语义和两套呈现适配：

```text
Agent 语义结果
  ├─ AIUI Presentation Adapter -> 对话文字 / AIUI 卡片 / TTS
  └─ RV101 Overlay Adapter      -> 原生固定图标 / 文字 / 动作 / 回执
```

共享字段可以包括：

- `intent`
- `title`
- `body`
- `speech_text`
- `interaction`
- `source`
- `correlation_id`

具体颜色、坐标、动画和图标资源仍由各端本地实现，后端与模型不得下发任意样式代码。

## 6. 资源协调

AIUI 对话和系统带声录像可能竞争麦克风。第一阶段采用以下规则：

1. 六轴监听在 AIUI 对话期间继续运行。
2. AIUI 语音会话占用麦克风时，不启动新的带声录像。
3. 运动触发可以进入短期待处理队列，并记录 `CAPTURE_DEFERRED_RESOURCE_BUSY`。
4. AIUI 会话结束后恢复正常采集策略。
5. 是否允许系统录制与 AIUI 同时使用麦克风，必须通过 RV101 真机验证，不能只依赖 Android 通用行为推断。

## 7. 实施顺序

1. [已完成] 保持 PR #3 已实现的采集、下发和回执链路不变。
2. [已完成] 创建最小 AIUI 对话智能体源码。
3. [已完成] 为 Agent Gateway 增加 `source`、`response_channel` 和
   `correlation_id`。
4. [待配置] 填入真实 HTTPS 后端地址、用户鉴权方案并登记 Rokid 域名。
5. [待打包] 使用 Rokid Craft 或官方 `aix pack` 生成 `.aix`。
6. [待真机] 验证“乐奇 -> RealGit -> 后端记忆查询 -> AIUI 回答”。
7. [待真机] 验证 AIUI 对话期间六轴持续、媒体采集延后和会话结束恢复。

实现位置：

- `apps/reality-memory-aiui-agent/`
- `services/agent-gateway/app/main.py`
- [AIUI 双通道实现记录](RealGit-Rokid-AIUI-Dual-Channel-Change-v0.1.md)
