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
| `app/sessions.py` | 内存会话 + TTL |

## API

- `POST /v1/chat` — `{message, session_id?}` → `{session_id, reply, tool_trace}`
- `POST /v1/proactive/check` — 拉取平台待投递信号 → `{suggestions[], suppressed}`
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
                  "memory.signal.subscribe"],
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
```

`LLM_PROVIDER=fake` 时无需任何 API key(工具循环由测试脚本驱动,见 `tests/`)。

## 测试

```bash
.venv/bin/pytest            # harness 单测(FakeChatLLM + MockTransport 平台)
```

跨服务契约测试(gateway harness ↔ 真实平台,进程内 ASGI)在
`services/memory-platform/tests/test_gateway_e2e.py`,随平台测试套件运行。
