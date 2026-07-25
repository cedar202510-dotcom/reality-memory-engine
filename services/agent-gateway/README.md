# Agent Gateway

记忆平台的第一个 AgentGrant 客户端:会话式记忆助手(tool-use harness)+ 主动式提醒措辞。

## 边界(为什么是独立服务)

- **只持受限 token**:通过 `MEMORY_AGENT_TOKEN`(AgentGrant bearer token)走 HTTP 契约访问记忆平台;绝不直连平台数据库、绝不 import 平台内部模块。撤销 grant 即物理断开。
- **意图理解在这里,事实在平台**:harness 负责对话理解、工具选择、措辞与不确定性表达;平台负责检索、置信度、来源与家庭隔离。模型永远不能决定"什么成为事实"。
- **无结果缓存**:会话是唯一状态(内存态,TTL 过期即失去),每次查询实时打平台——纠正/删除后的一致性(§12)在结构上成立。

## 组成

| 文件 | 职责 |
| --- | --- |
| `app/harness.py` | 有界 tool-use 循环(≤ `MAX_TOOL_TURNS` 轮,超限降级收尾);系统提示词编码解释标准(§9)与降级规则(§13) |
| `app/tools.py` | §14 工具表:`find_object` / `get_object_timeline` / `get_preference` / `submit_correction`(OpenAI tools schema + 分发) |
| `app/memory_client.py` | 平台 HTTP 客户端;401/403/不可用 → 结构化 error 返回给模型转达,不重试不绕过 |
| `app/llm.py` | 对话 LLM(OpenAI tools 协议;`fake` provider 用于测试) |
| `app/proactive.py` | 信号 → 提醒措辞(默认确定性模板;`PROACTIVE_LLM_WORDING=true` 时 LLM 润色);只建议,不执行 |
| `app/glasses_delivery.py` | Agent 回答/主动建议 → 受约束的眼镜呈现契约；选择目标设备并调用平台消息接口 |
| `app/sessions.py` | 内存会话 + TTL |

## API

- `POST /v1/chat` —
  `{message, session_id?, source?, response_channel?, correlation_id?, device_id?, delivery?}` →
  `{session_id, reply, source, response_channel, correlation_id, tool_trace, delivery?}`
- `POST /v1/proactive/check` — 拉取平台待投递信号，可选自动发到眼镜 →
  `{suggestions[], suppressed, deliveries[]}`
- `POST /v1/signals/{id}/ack` — 用户确认提醒后回执(gateway 不代替用户 ack)
- `GET /healthz`

## 本地运行

```bash
# 1. 平台侧签发 grant(平台需配置 ADMIN_TOKEN)
curl -X POST localhost:8000/v1/agent/grants \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"agent_client_id": "proactive-agent-demo",
       "scopes": ["memory.query.objects", "memory.query.preferences",
                  "memory.timeline.read", "memory.correction.submit",
                  "memory.signal.subscribe", "memory.device.message.send"],
       "purpose": "PERSONAL_ASSISTANCE"}'
# 响应里的 token 只出现一次

# 2. 启动 gateway
cd services/agent-gateway
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
MEMORY_BASE_URL=http://localhost:8000 \
MEMORY_AGENT_TOKEN=<上一步的 token> \
LLM_PROVIDER=kimi-coding LLM_API_KEY=... LLM_MODEL=k3 \
.venv/bin/uvicorn app.main:app --port 8200

# 3. 对话
curl -X POST localhost:8200/v1/chat -d '{"message": "我的钥匙在哪?"}'

# 4. Agent 回答自动进入指定眼镜的后端 inbox
curl -X POST localhost:8200/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "我的钥匙在哪？",
    "delivery": {
      "device_id": "<后端登记的 RV101 device_id>",
      "allow_tts": false
    }
  }'
```

### AIUI 对话

Rokid AIUI 用户主动对话必须明确声明来源与返回通道：

```bash
curl -X POST localhost:8200/v1/chat \
  -H 'Content-Type: application/json' \
  -H "X-RealGit-Client-Token: $AIUI_CLIENT_TOKEN" \
  -d '{
    "message": "我的钥匙最后一次在哪里？",
    "source": "ROKID_AIUI",
    "response_channel": "AIUI_CONVERSATION",
    "correlation_id": "aiui:test-turn"
  }'
```

`AIUI_CONVERSATION` 表示回答由当前 AIUI 页面直接展示和播报。即使
`GLASSES_AUTO_DELIVERY_ENABLED=true`，本次回答也不会再生成原生 `ANSWER`
覆盖层。请求若同时携带 `delivery` 会返回 422，避免重复显示。

可用回答通道：

| 通道 | 含义 |
| --- | --- |
| `CALLER` | 只在 HTTP 响应中返回，适合 Web、手机或普通 API 调用 |
| `AIUI_CONVERSATION` | 用户主动唤醒 AIUI 后，在 AIUI 对话中返回 |
| `RV101_OVERLAY` | 写入原生眼镜 Runtime 的消息队列 |

`source=ROKID_AIUI` 默认解析为 `AIUI_CONVERSATION`，但客户端仍应显式传入，便于
审计。设置 `AIUI_CLIENT_TOKEN` 后，AIUI 请求必须通过
`X-RealGit-Client-Token` 携带相同 token。静态 token 只适合早期联调。

`LLM_PROVIDER=fake` 时无需任何 API key(工具循环由测试脚本驱动,见 `tests/`)。

`delivery` 不是第二次人工下发：它只指定本次回答应该回到哪台眼镜。Agent Gateway
完成回答后会立即生成 `rme.glasses-presentation.v0`，调用受
`memory.device.message.send` scope 保护的平台接口。响应中的 `delivery.status=QUEUED`
表示消息已经进入 `device_messages`；当前 RV101 每约 3 秒轮询一次 inbox。

本地单眼镜联调也可以设置：

```bash
GLASSES_AUTO_DELIVERY_ENABLED=true
GLASSES_DEFAULT_DEVICE_ID=<RV101 device_id>
GLASSES_DEFAULT_ALLOW_TTS=false
AIUI_CLIENT_TOKEN=<早期联调 token>
```

开启后，请求不传 `delivery` 也会自动投到默认眼镜。正式多终端产品应根据本次交互的
来源显式传目标设备，不能在多副眼镜之间猜测。

## 测试

```bash
.venv/bin/pytest            # harness 单测(FakeChatLLM + MockTransport 平台)
```

跨服务契约测试(gateway harness ↔ 真实平台,进程内 ASGI)在
`services/memory-platform/tests/test_gateway_e2e.py`,随平台测试套件运行。
