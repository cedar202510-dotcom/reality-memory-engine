# RealGit 前端

React + Vite 原型。大部分视图仍是设计演示（mock 数据），已接真实后端的部分：

- **询问**：`GET /api/v1/memory/objects/where-is?deep=true`，后端未启动时自动回退演示答案。
- **联调**（侧边栏第 4 项）：Rokid 眼镜实时画面 + memory-platform 摄入消化面板。

## 启动

```bash
# 1. 后端（默认放行 http://localhost:5173 的 CORS，代理下其实不需要）
cd services/memory-platform && uvicorn app.main:app --port 8000

# 2. 前端 dev server（/api 代理到 8000，可用 RME_API_TARGET 覆盖）
cd frontend && npm install && npm run dev
```

用 Claude Code 的话，两个服务的启动配置在 `.claude/launch.json`。该文件不进版本库
（端口摆法各人不同，跟着仓库走只会互相覆盖），首次 clone 后自己复制一份：

```bash
cp .claude/launch.json.example .claude/launch.json
```

需要同时跑两套栈时（比如一套连采集用的 8010 后端），在模板里追加一条配置，用
`RME_API_TARGET` 指向另一个后端、`--port` 换个前端端口即可。

## Rokid 视频流联调

眼镜探针 App 开启「预览」后，它在眼镜本机 8090 端口起 MJPEG 服务
（`apps/rokid-glass-probe` 的 `PreviewStreamServer`）：

- **USB 联调**：`adb forward tcp:8090 tcp:8090`，联调页默认地址
  `http://127.0.0.1:8090/stream` 直接可用；
- **局域网**：联调页地址栏改成 `http://<眼镜IP>:8090/stream`。

联调页右侧每 4 秒轮询 `GET /api/v1/memory/frames/recent`，展示最近摄入帧的
caption / scene_tags / 证据缩略图与感知积压量（`pending_outbox`），可以直观看到
「眼镜画面 → 上传 → 感知产出」的全链路延迟。
