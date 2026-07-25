# Agent 回答自动下发 RV101 改动记录 v0.1

日期：2026-07-26

## 目标

移除“Agent 已经回答，但还要人工运行测试脚本才能显示到眼镜”的断点。完成以下代码链：

```text
Agent 对话回答 / 主动建议信号
→ Agent Gateway 固定映射
→ rme.glasses-presentation.v0
→ Memory Platform device_messages
→ RV101 inbox
→ 眼镜显示与回执
```

## 本次改动

1. Memory Platform 新增 `memory.device.message.send` AgentGrant scope。
2. 新增 `GET /v1/agent/devices`，只返回当前 grant 家庭中的设备。
3. 新增 `POST /v1/agent/devices/{device_id}/messages`，与人工入口共用落库、TTL、
   推送和审计实现。
4. Agent Gateway 的 `/v1/chat` 支持 `delivery`，回答完成后自动生成 `ANSWER` 消息。
5. `/v1/proactive/check` 支持 `delivery`；低耗材信号生成采购提醒，其他信号降级为普通
   重要提醒。
6. 下发失败不会吞掉 Agent 原回答；响应会返回 `FAILED` 和原因。成功落库返回
   `QUEUED`、`message_id` 和当前通道。
7. 模型不能传颜色、坐标、HTML、SVG、自由图标和系统/隐私意图。
8. 已签发的旧 AgentGrant 不会自动增加新 scope；联调时需重新签发包含
   `memory.device.message.send` 的 token，并更新 Agent Gateway 配置。

## 明确没有完成

- 本次没有把真机重新接入正在运行的 Memory Platform 与 Agent Gateway，因此尚未留下
  “真实 Agent 内容在眼镜显示”的新真机验收包。
- 任务完成、加入采购清单等用户动作目前只形成可审计回执，后端业务对象更新仍待实现。
- 正式设备 token、覆盖层正式授权和 WebSocket 眼镜客户端仍待完成。

## 验收证据

- Agent Gateway 单测覆盖普通回答和采购提醒的契约转换。
- Memory Platform 测试覆盖 scope 拒绝、家庭设备选择、消息落库和 Agent 审计。
- 跨服务测试覆盖 `/v1/chat` 到真实平台 inbox 的同一 `message_id`。
- 下一轮真机验收必须再补 RV101 的 `RECEIVED -> PRESENTED -> DISMISSED` 日志。
