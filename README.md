# RealGit

> 记住现实的变化，把时间还给人。

RealGit 是这个项目的唯一代码仓库。它把眼镜、戒指、耳机、手机和未来硬件产生的
短时证据，转化为可查询、可纠正、可删除、可审计的现实记忆。

现实每天都在变，但人得靠回忆去追它：东西放哪了、那句话谁说的、上次是怎么决定的。
RealGit 像给现实做版本管理——变化被自动记下来，人只在需要的时候去查，
省下的时间还给人自己。

## 快速开始

后端（memory-platform）与前端原型：

```bash
docker compose -f infra/docker-compose.yml up -d
```

```bash
cd services/memory-platform && uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

前端 dev server 把 `/api` 代理到 8000。更多联调细节（Rokid 眼镜 MJPEG 实时画面、
摄入消化面板）见 [frontend/README.md](frontend/README.md)。

用 Claude Code 的话，启动配置在 `.claude/launch.json`。该文件不进版本库，首次
clone 后自己复制一份：

```bash
cp .claude/launch.json.example .claude/launch.json
```

## 文档入口

- [文档总导航](docs/README.md)
- [产品 PRD v1.3](docs/product/RealGit-PRD-v1.3.md)
- [分层技术架构](docs/architecture/README.md)
- [多模态数据契约 v1.0](docs/engineering/RealGit-Multimodal-Data-Contract-v1.0.md)
- [JSON Schema 与样例](contracts/reality-memory/v1/README.md)

## 代码边界

### 端侧

- `apps/mobile-app/`：唯一用户侧手机 App，负责账号、设备绑定、策略、查询、提醒
  和必要时的数据中继。
- `apps/reality-memory-glasses/`：正式 RV101 设备端 App，负责感知、隐私状态、
  本地短期队列、上行和提醒呈现。
- `apps/rokid-glass-probe/`：保留的 RV101 能力探针与排障基线，不是正式产品。
- `apps/iflybuds-collector/`：蓝牙耳机（IFLYBUDS Air 2）的宿主侧 Collector，跑在电脑上，
  耳机只提供麦克风和扬声器，负责音频采集上行与语音提醒播报。
- `hardware/ring-sound-sdk/`：戒指 SDK、协议和硬件资料。
- `archive/cxrl-probe/`：已归档 CXR-L 兼容实验，不是第二个用户 App。

用户侧仍只有一个手机 App。眼镜 App 是硬件上的设备 Runtime，不承载完整账号产品，
也不保存长期记忆本体。正式眼镜优先直连统一云端，手机是用户控制端和兼容中继。

### 云侧与工具

- `services/memory-platform/`：记忆平台主服务，负责证据摄入、感知、沉淀与查询。
- `services/agent-gateway/`：Agent 查询与提醒判断入口。
- `services/asr-sidecar/`：faster-whisper 语音转写 sidecar。
- `services/device-connectors/`：设备接入适配。
- `frontend/`：React + Vite 前端原型，部分视图仍是 mock 数据。
- `contracts/`：机器可校验的 JSON Schema 与样例。
- `infra/`：Postgres（pgvector）与 sidecar 的本地编排。
- `tools/`：眼镜投屏、会话查看、测试数据等开发辅助工具。

## 当前阶段

正在开发并真机验证 RV101 原生采集链路。眼镜端已经有佩戴会话、IMU 动态触发、
无业务预览图片/短视频、短音频、本地加密 Evidence 队列和本地提醒呈现代码；
CameraX、AudioRecord、传感器、后台生命周期、功耗和温升仍需持有开发线的真机
测试。云端记忆沉淀和下行提醒业务契约尚未冻结。
