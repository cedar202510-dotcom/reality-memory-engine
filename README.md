# Reality Memory Engine

这是 Reality Memory Engine 的唯一项目仓库。它把眼镜、戒指、手机和未来硬件产生的
短时证据，转化为可查询、可纠正、可删除、可审计的现实记忆。

## 当前入口

- [文档总导航](docs/README.md)
- [产品 PRD v1.3](docs/product/Reality-Memory-Engine-PRD-v1.3.md)
- [分层技术架构](docs/architecture/README.md)
- [多模态数据契约 v1.0](docs/engineering/Reality-Memory-Multimodal-Data-Contract-v1.0.md)
- [JSON Schema 与样例](contracts/reality-memory/v1/README.md)

## 代码边界

- `apps/mobile-app/`：唯一用户侧手机 App，负责账号、设备绑定、策略、查询、提醒
  和必要时的数据中继。
- `apps/reality-memory-glasses/`：正式 RV101 设备端 App，负责感知、隐私状态、
  本地短期队列、上行和提醒呈现。
- `apps/rokid-glass-probe/`：保留的 RV101 能力探针与排障基线，不是正式产品。
- `archive/cxrl-probe/`：已归档 CXR-L 兼容实验，不是第二个用户 App。
- `hardware/ring-sound-sdk/`：戒指 SDK、协议和硬件资料。

用户侧仍只有一个 Reality 手机 App。眼镜 App 是硬件上的设备 Runtime，不承载完整
账号产品，也不保存长期记忆本体。正式眼镜优先直连统一云端，手机是用户控制端和
兼容中继。

## 当前阶段

正在开发并真机验证 RV101 原生采集链路。眼镜端已经有佩戴会话、IMU 动态触发、
无业务预览图片/短视频、短音频、本地加密 Evidence 队列和本地提醒呈现代码；
CameraX、AudioRecord、传感器、后台生命周期、功耗和温升仍需持有开发线的真机
测试。云端记忆沉淀和下行提醒业务契约尚未冻结。
