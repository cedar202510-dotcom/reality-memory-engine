# RealGit 与 Rokid AIUI 双通道改动记录 v0.1

日期：2026-07-26

## 目标

让用户主动对话和系统主动提醒共用同一个 RealGit Agent，但通过不同的眼镜呈现通道，
避免同一回答重复显示。

```text
用户主动对话
乐奇 -> RealGit AIUI -> Agent Gateway -> AIUI 文字与 TTS

系统主动提醒
Memory Signal -> Agent Gateway -> RV101 原生 Runtime -> 提醒覆盖层
```

## 已完成

1. 从合并后的 `origin/main` 建立 `codex/rokid-aiui-integration`；创建分支时本地最新
   前端与远端 `main` 文件树完全一致，没有覆盖本地页面设计。
2. `/v1/chat` 新增 `source`、`response_channel`、`correlation_id` 和可选来源
   `device_id`。
3. 新增 `AIUI_CONVERSATION` 回答通道；它只返回 HTTP 回答，不写原生眼镜消息队列。
4. `ROKID_AIUI + delivery` 冲突请求返回 422，避免一条回答同时出现在 AIUI 和原生
   覆盖层。
5. 原有 `delivery` 请求继续映射为 `RV101_OVERLAY`；原有
   `/v1/proactive/check` 主动提醒链路不变。
6. 原生眼镜下发复用调用方传入的 `correlation_id`，便于串联 Agent turn 和设备回执。
7. 增加可选 `AIUI_CLIENT_TOKEN` 联调认证。
8. 新增 `apps/reality-memory-aiui-agent/`，包含 Agent 描述、对话页面、真实 HTTPS
   客户端、短期会话复用、错误降级和 TTS。
9. AIUI 页面遵守 RV101 448px 单绿显示约束，不包含按钮或自由样式下发。

## 验证结果

- Agent Gateway：12 项测试通过。
- AIUI 工程静态契约检查：通过。
- 老的 `/v1/chat + delivery` 原生下发测试：通过。
- 自动原生下发开启时，AIUI 对话仍不会生成重复眼镜消息：通过。
- AIUI token 缺失拒绝、正确 token 放行：通过。

## 尚未完成

- 未配置 RealGit 的正式 HTTPS 域名。
- 未完成用户级短期凭证；当前静态 token 仅适合 POC。
- 未在 Rokid Craft 或灵珠平台打包、上传 `.aix`。
- 未在真机验证乐奇意图是否稳定选择 RealGit Agent。
- 未验证 AIUI TTS 与系统带声录像的麦克风资源竞争。
- 未实现 AIUI 活跃状态与原生采集 Runtime 的跨进程资源协调。

这些事项都不能被描述为已经端到端跑通。
