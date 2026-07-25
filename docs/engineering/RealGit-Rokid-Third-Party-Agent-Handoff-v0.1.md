# RealGit Rokid 三方智能体云端与真机交接 v0.1

> 日期：2026-07-26
> 状态：SSE 协议适配和自动化测试已完成；待部署真实 HTTPS 后端、平台登记和真机验收

## 1. 先明确两条并行接入路线

RealGit 当前同时保留两条可以分别验证的用户主动对话路线。它们都连接同一个
Agent Gateway，但不是已经自动串联的前后两层，首轮测试不要同时启用。

### 路线 A：新版 AIUI/OAF 程序包

```text
乐奇 / AIUI 调度
-> RealGit AIUI 程序包
-> HTTPS /v1/chat
-> Agent Gateway
-> AIUI 页面显示与 TTS
```

这是 `apps/reality-memory-aiui-agent/` 当前实现的路径，按照新版 AIUI/OAF 文档开发，
在新版 AIUI Studio 创建项目和上传程序包。

创建页建议填写：

| 字段 | 建议值 |
| --- | --- |
| 智能体名称 | `RealGit` |
| 版本号 | `0.1.0` |
| 类别 | `生活` |
| 功能介绍 | `连接你的现实记忆，回答物品位置、个人偏好、任务和近期活动等问题；不确定时明确说明，不自动执行外部动作。` |
| 开场白 | `我是 RealGit。你可以问我物品最后出现在哪里、最近提到过什么任务，或某条记忆为什么形成。` |
| 权限依赖 | 第一版只勾选`网络` |
| 摄像头 | 不勾选；当前 AIUI 程序包不直接拍照 |
| 语音识别 | 不勾选；第一版由乐奇/AIUI 对话上下文传入文字 |
| 麦克风 | 不勾选；当前 AIUI 程序包不直接录音 |
| 预览图/视频 | 至少 3 个素材，遵守平台格式与大小限制 |
| Agent 程序包 | 配置真实 HTTPS 后端后生成的 `.aix` |

图标可以在内部调试阶段暂用默认图标，但正式提审前应换成 RealGit 产品图标。预览素材
应展示眼镜中的真实单绿界面和回答状态，不用手机 Web App 截图代替。

程序包上传前必须修改：

```text
apps/reality-memory-aiui-agent/config.js
```

至少配置：

```js
apiBaseUrl: "https://<真实 Agent Gateway 域名>",
clientToken: "<仅用于 POC 的 AIUI 客户端 token>"
```

`apiBaseUrl` 仍为 `replace-with-realgit-api.example` 时只能做源码和页面检查，不能进行
真实网络测试，也不要提交最终程序包。唤醒/命中测试可先使用：

```text
我想问 RealGit，我的钥匙最后一次在哪里？
```

### 路线 B：旧灵珠三方自定义智能体

RealGit 的 Agent 和记忆平台由我们自己运行，所以在旧灵珠平台分类中属于：

```text
项目开发 -> 三方智能体 -> 创建 -> 自定义智能体
```

它不是“灵珠智能体”。灵珠智能体是在 Rokid 平台内使用模型、插件和工作流搭建；
RealGit 则需要 Rokid 调用我们自己的 HTTPS SSE 服务。

| 路线 | 平台入口 | 后端接口 | 当前用途 |
| --- | --- | --- |
| A：AIUI/OAF | 新版 AIUI Studio | `/v1/chat` | 推荐先验证新框架程序包和定制页面 |
| B：三方 SSE | 旧灵珠平台“三方智能体” | `/v1/rokid/agent/sse` | 验证外部 Agent 兼容接入与系统默认呈现 |

不要为了上传 AIUI 程序包而把 RealGit 后端登记成“灵珠智能体”。如果新版平台后续提供
三方 SSE 的迁移入口，应迁移同一份协议配置，不改变 RealGit 的外部 Agent 定位。

目前没有官方依据证明路线 B 的 SSE 回答会自动进入路线 A 的自定义 AIUI 页面。若两条
路线都要保留，必须分别验收；没有完成平台关联验证前不能描述成同一条端到端链路。

官方协议：

- <https://rokid.yuque.com/ub8h5n/hth52o/qq4gs616xz4ellh1>
- <https://js.rokid.com/AIUI/guide/quickstart?lang=zh-CN&version=0.14.0>

## 2. 已实现的三方 SSE 入口

```text
POST /v1/rokid/agent/sse
Content-Type: application/json
Authorization: Bearer <ROKID_AGENT_AK>
```

代码位置：

- `services/agent-gateway/app/rokid_agent.py`
- `services/agent-gateway/app/main.py`
- `services/agent-gateway/tests/test_rokid_agent.py`

处理过程：

```text
Rokid 请求
-> 校验 Bearer AK 和可选 agent_id
-> 提取最后一条用户文字
-> 转为 RealGit 内部 ChatRequest
-> Agent Gateway 查询 Memory Platform
-> 输出 SSE message 事件
-> 输出 SSE done 事件
```

第一版只支持文字输入。平台请求中可以存在图片字段，但没有用户文字时返回 `422`，
不能把尚未实现的视觉问答伪装成可用能力。

当前 Agent Gateway 不是逐 token 生成：模型完成回答后，一次输出完整 `message`，
随后输出 `done`。这满足首轮协议联调，但真实首字延迟仍需云端和真机测量。

## 3. 路线 B 的灵珠平台创建字段

在“三方智能体”中选择“自定义智能体”，建议填写：

| 字段 | 建议值 |
| --- | --- |
| 智能体名称 | `RealGit` |
| 智能体 ID | `realgit-memory-advisor` |
| 类别 | `生活` |
| 入参类型 | 第一阶段只选择`文字` |
| SSE 接口地址 | `https://<Agent Gateway 域名>/v1/rokid/agent/sse` |
| 智能体鉴权 AK | 与云端 `ROKID_AGENT_AK` 完全一致 |
| 功能介绍 | `连接你的现实记忆，回答物品位置、个人偏好、任务和近期活动等问题；不确定时明确说明，不自动执行外部动作。` |
| 开场白 | `我是 RealGit。你可以问我物品最后出现在哪里、最近提到过什么任务，或某条记忆为什么形成。` |

若平台自动生成智能体 ID，则将生成值配置到云端 `ROKID_AGENT_ID`，不要继续使用表中的
建议值。

AK 必须在部署环境中生成并通过密钥管理注入，不写入 Git、截图、测试日志或客户端包。
可使用：

```bash
openssl rand -hex 32
```

## 4. 云端部署边界

正式测试不在当前开发电脑运行后端。推荐拓扑：

```text
Rokid / 乐奇
-> 公网 HTTPS Agent Gateway
-> 内网 Memory Platform
-> 内网 PostgreSQL / pgvector
```

只有 Agent Gateway 对 Rokid 暴露 HTTPS。Memory Platform、PostgreSQL、模型
sidecar 和管理接口都不直接暴露公网。

Agent Gateway 必填环境变量：

```bash
MEMORY_BASE_URL=http://memory-platform:8000
MEMORY_AGENT_TOKEN=<受限 AgentGrant token>

LLM_PROVIDER=<openai 或 kimi-coding>
LLM_BASE_URL=<模型兼容接口地址>
LLM_API_KEY=<模型密钥>
LLM_MODEL=<模型名>

ROKID_AGENT_AK=<与灵珠平台填写值一致>
ROKID_AGENT_ID=<平台登记的 RealGit 智能体 ID>
```

仓库提供无密钥模板：

```text
services/agent-gateway/.env.example
```

`ROKID_AGENT_AK` 未配置时，三方入口会安全地拒绝全部请求。它与
`AIUI_CLIENT_TOKEN` 用途不同，不能混用：

- `ROKID_AGENT_AK`：灵珠服务器调用三方 SSE 接口。
- `AIUI_CLIENT_TOKEN`：AIUI 程序包直接调用 `/v1/chat` 的早期联调凭证。

第一阶段仍是单用户 POC。当前 Rokid 的 `user_id` 只用于构造短期会话命名空间，不能
直接当作 RealGit 家庭域授权。上线多用户前必须建立 Rokid 账号与 RealGit 用户/家庭的
受控绑定，并为每个用户签发短期凭证或受限 AgentGrant。

## 5. 没有眼镜时的服务端自测

安装并运行 Agent Gateway 后：

```bash
curl -N https://<Agent Gateway 域名>/v1/rokid/agent/sse \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $ROKID_AGENT_AK" \
  -d '{
    "message_id": "realgit-test-conversation-001",
    "agent_id": "realgit-memory-advisor",
    "user_id": "rokid-test-user",
    "message": [
      {
        "role": "user",
        "type": "text",
        "text": "我的钥匙最后一次在哪里？"
      }
    ],
    "metadata": {
      "context": {
        "location": "杭州",
        "latitude": "30.2",
        "longitude": "120.2",
        "weather": "晴",
        "battery": "80"
      }
    }
  }'
```

预期响应结构：

```text
event: message
data: {"role":"agent","message_id":"realgit-test-conversation-001",...,"answer_stream":"...","is_finish":false,"type":"answer"}

event: done
data: {"role":"agent","message_id":"realgit-test-conversation-001",...,"answer_stream":"","is_finish":true,"type":"answer"}
```

仓库测试：

```bash
cd services/agent-gateway
pytest -q
```

当前基线为 17 项通过，其中 5 项覆盖 Rokid 鉴权、SSE 事件、Agent ID、文字输入和
会话连续性。

## 6. 路线 B 的队友真机测试步骤

前置条件：

1. RV101 已通过 Rokid AI 手机 App 绑定到测试账号。
2. 手机 App 与灵珠开发者平台使用可访问同一测试智能体的账号。
3. 云端 SSE 地址具备有效公网 HTTPS 证书。
4. 灵珠平台已登记 RealGit 三方自定义智能体。
5. 云端 Memory Platform、Agent Gateway 和真实模型均健康。

操作：

1. 在 Rokid AI 手机 App 进入`开发者 -> 智能体调试 -> 我自己的智能体`。
2. 选择 `RealGit`。
3. 戴上眼镜，说：`乐奇，问 RealGit，我的钥匙最后一次在哪里？`
4. 再问：`刚才那个位置是什么？`，验证同一 `message_id` 的上下文连续性。
5. 发起一个没有结果的问题，确认系统明确表示不知道，不编造记忆。
6. 结束 AIUI 对话后，验证原生 RealGit Runtime 的六轴监听仍在继续。
7. 制造一次后端不可用，确认眼镜给出可理解的失败提示并可再次重试。

路线 A 的 AIUI/OAF 程序包测试按
`apps/reality-memory-aiui-agent/README.md` 单独进行。两条路线使用不同测试会话，
避免同一问题重复回答时无法判断来源。

## 7. 必须保留的测试资料

提交测试结果时保留：

- 测试时间、眼镜型号、固件版本、Rokid AI App 版本。
- 测试智能体 ID 和 Git commit，不记录 AK。
- 每轮 `message_id`、`agent_id`、HTTP 状态和 SSE 事件顺序。
- Agent Gateway 首包耗时、总耗时和错误摘要。
- 眼镜录屏或可见结果照片。
- 原生 Runtime 在 AIUI 对话前、中、后的六轴监听状态。
- 失败时的服务端日志和手机 App/眼镜日志，清除 Authorization 和个人敏感内容。

验收标准：

1. 乐奇能稳定命中 RealGit。
2. 一次提问只显示/播报一次回答。
3. 回答来自真实 Memory Platform 查询，不是固定假数据。
4. 连续追问保留短期上下文。
5. AIUI 对话不破坏原生六轴监听和后续采集恢复。
6. 服务异常不会让眼镜长期卡死，下一轮可以恢复。

## 8. 尚未完成

- 没有真实云端 HTTPS 地址和部署验收。
- 没有在灵珠平台登记最终 `agent_id` 与 AK。
- 没有真机验证 Rokid 的 SSE 解析细节和超时限制。
- 没有图片输入和真正逐 token 流式输出。
- 没有完成 Rokid 用户与 RealGit 用户/家庭域的多用户绑定。
- 没有验证 AIUI 程序包与三方 Agent 在新版 AIUI Studio 中的最终关联方式。
- 没有证明三方 SSE 回答会进入自定义 AIUI 页面；当前按两条并行路线管理。
- 主动提醒仍由原生 RV101 Runtime 下发，不通过三方智能体对话通道。
