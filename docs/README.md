# RealGit 文档导航

这里是项目文档的统一入口。当前文档按“产品、架构、工程、探索、归档”分层，
避免同一目录中同时出现多个看似有效的版本。

## 当前权威文档

| 阅读目的 | 文档 | 状态 |
| --- | --- | --- |
| 理解产品定位、范围与阶段目标 | [产品 PRD v1.3](product/RealGit-PRD-v1.3.md) | 当前产品母版 |
| 理解端、云、Agent 的整体边界 | [分层技术架构](architecture/README.md) | 当前工程口径 |
| 开发眼镜端采集 | [数据采集架构](architecture/01-Data-Capture-Architecture.md) | 当前参考，硬件参数待真机 |
| 开发云端记忆沉淀 | [云端记忆平台架构](architecture/02-Memory-Platform-Architecture.md) | 方案参考，沉淀规则待 review |
| 开发 Agent 查询与提醒判断 | [Agent 调用架构](architecture/03-Agent-Access-Architecture.md) | 方案参考，业务策略待 review |
| 开发眼镜与云端通信 | [设备与云端通信](architecture/05-Device-Cloud-Communication.md) | 上行可实施，下行业务内容待 review |
| 开发灵感 / 问题 / 任务捕捉 | [灵感旁路架构](architecture/06-Idea-Capture-Sidecar-Architecture.md) | 方案参考，待 review |
| 对接数据对象和 JSON Schema | [多模态数据契约 v1.0](engineering/RealGit-Multimodal-Data-Contract-v1.0.md) | 当前正式契约 |

机器可校验的 JSON Schema 位于
[`contracts/reality-memory/v1/`](../contracts/reality-memory/v1/README.md)。

## 目录规则

- `product/` 顶层只放当前产品母版。
- `architecture/` 顶层只放当前系统边界和分层方案。
- `engineering/` 顶层只放仍用于开发的工程参考和数据契约。
- `product/concepts/` 放尚未冻结的体验与视觉探索。
- `architecture/concepts/` 放尚未冻结的架构探索与可行性判断，不得作为实现依据。
- 每个主题自己的 `archive/` 保存旧版本和历史 review，不作为当前实现依据。
- `visuals/` 保存辅助理解的 HTML 图，不替代 Markdown 权威文档。

旧文档不得直接删除。归档后需要在对应 `archive/README.md` 说明替代文档和失效原因。

## 状态词

- **当前权威**：发生冲突时以该文档为准。
- **当前参考**：可以指导实现，但仍有真机参数或接口细节待确认。
- **方案参考 / 待 review**：用于并行讨论，不得当成冻结业务契约。
- **历史归档**：只用于追溯决策，不指导新实现。

