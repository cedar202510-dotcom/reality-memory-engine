# RealGit Rokid AIUI 智能体

这是 RealGit 的用户主动对话入口，不替代
`apps/reality-memory-glasses/` 原生采集与主动提醒 Runtime。

## 两条眼镜消息路径

```text
用户主动询问
乐奇 -> RealGit AIUI -> Agent Gateway -> AIUI 文字与 TTS

系统主动提醒
Memory Signal -> Agent Gateway -> 原生 Runtime -> RV101 提醒覆盖层
```

AIUI 请求固定携带：

```json
{
  "source": "ROKID_AIUI",
  "response_channel": "AIUI_CONVERSATION"
}
```

这会阻止同一条对话回答再次进入原生眼镜消息队列。

## 配置

编辑 `config.js`：

- `apiBaseUrl`：Agent Gateway 的 HTTPS 地址，不带结尾 `/`。
- `clientToken`：早期联调使用的 AIUI 客户端 token。
- `deviceId`：可选的 RV101 设备 UUID，仅用于来源关联，不触发原生下发。
- `enableTts`：是否在 AIUI 页面中播报用户主动询问的回答。

线上 AIUI 网络请求必须使用 HTTPS，发布前还需要在 Rokid 开发者后台登记域名。
静态 `clientToken` 只能用于 POC；正式多用户版本应换成用户级短期凭证。

后端对应配置：

```bash
AIUI_CLIENT_TOKEN=<与 config.js 一致的联调 token>
```

## 本地检查

```bash
cd apps/reality-memory-aiui-agent
npm test
```

该检查不依赖 npm 第三方包，会校验 AIUI 目录、页面区块、HTTPS 配置和回答通道路由。

## 导入、打包与真机测试

第一种方式是在 Rokid Craft 中导入本仓库的
`apps/reality-memory-aiui-agent/` 子目录，完成预览后点击打包生成 `.aix`。

若已经安装 Rokid 官方 `aix` 命令行工具：

```bash
aix pack apps/reality-memory-aiui-agent \
  -o realgit-aiui-agent-v0.1.0.aix
```

随后在 Rokid 灵珠平台创建 AIUI 智能体、上传 `.aix` 并进入真机调试。首轮测试话术：

```text
乐奇，问 RealGit，我的钥匙最后一次在哪里？
```

验收时必须同时确认：

1. AIUI 页面显示 Agent Gateway 的真实回答。
2. 回答只出现一次，原生 Runtime 不再显示重复 `ANSWER`。
3. 后端主动任务或采购提醒仍能通过原生 Runtime 独立出现。
4. AIUI 会话结束后，原生六轴监听和运动触发采集继续工作。
