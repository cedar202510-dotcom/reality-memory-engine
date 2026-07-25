# Hackathon 功能清单

> 文档版本：v0.1
> 文档日期：2026-07-25
> 当前状态：**待排期，未冻结**。本文档是参赛所需的功能拆解与工作量估算，不是产品承诺
> 上游文档：[赛道选择与演示设计 v0.1](Hackathon-Track-Selection-and-Demo-Plan-v0.1.md)
> 产品母版：[产品 PRD v1.3](../product/RealGit-PRD-v1.3.md)

## 0. 读法

功能按**批次**组织，不按赛道组织。原因：F0 是所有赛道共用的底座，
F1–F6 各自对应一个赛道，可以按设备到位情况和剩余时间任意裁剪。

每项功能标注：**目标 / 涉及文件 / 工作量 / 验收标准 / 风险**。
验收标准是可执行的判定条件，不是描述性目标——写不出验收标准的功能不进这份清单。

工作量单位是「人天」，按熟悉本仓库的一人计。

---

## 1. 现状基线（不要重复造）

动手前先确认这些**已经有了**：

| 已有能力 | 位置 | 说明 |
|---|---|---|
| Envelope 摄入、幂等、去重、outbox | [gateway/__init__.py:38](../../services/memory-platform/app/gateway/__init__.py:38) | 不需要改 |
| 感知流水线（k3 caption/抽取 + CLIP 向量） | `app/perception/`、`app/vision/clip_local.py` | **CLIP 已是本地实现** |
| 找物双通道、场景检索、时间线、纠正、偏好 | [query/__init__.py](../../services/memory-platform/app/query/__init__.py) | 5 个端点齐了 |
| 下行：消息、收件箱、回执、**WebSocket 长连** | [downlink/__init__.py:322](../../services/memory-platform/app/downlink/__init__.py:322) | 比预期完整，`device_stream_endpoint` 已在 |
| Agent 工具：`find_object` / `get_object_timeline` / `get_preference` / `submit_correction` | [agent-gateway/app/tools.py:13](../../services/agent-gateway/app/tools.py:13) | 4 个只读+纠正工具 |
| 主动提醒措辞（模板 + LLM 两路） | [agent-gateway/app/proactive.py:28](../../services/agent-gateway/app/proactive.py:28) | 已有 |
| ASR 本地模型 faster-whisper-tiny | `services/asr-sidecar/models/` | **已下载，离线可用** |
| `fake` provider（LLM / vision / ASR 三处） | [config.py:25,51,61](../../services/memory-platform/app/config.py:25) | **天然的断网降级开关** |
| 真机数据集 + 带 ground truth 的实拍帧 | `multimodal-test-data/`、`data/frames/` | 演示预热数据 |

> 关键推论：断网演示（F3）只缺 **VLM 一环**。CLIP 本地、ASR 本地、`fake` provider 都已就位。

---

## 2. F0 — 共同底座（无论投哪个赛道都要做）

### F0.1 修复 `fold_task_events` 覆盖缺陷 ★ 最高优先级

**目标**：同一实体的多条任务不再互相覆盖。

当前 [projections.py](../../services/memory-platform/app/memory/projections.py) 中：

```python
for ev in _sorted(events):
    if ev.event_type == "TASK_STATED":
        state["task"] = ...      # ← 每轮覆盖，只有最后一条活下来
```

docstring 声明这是「v0 一律视为 open」的有意简化，
**但一旦同一实体出现第二条任务它就是缺陷**，且与「任务管理」需求直接矛盾。

| 项 | 内容 |
|---|---|
| 涉及文件 | `app/memory/projections.py`（改 fold）、`app/schemas/__init__.py`（`EVENT_TYPES` 增 `TASK_COMPLETED` / `TASK_CANCELLED`）、`contracts/reality-memory/v1/memory-event.schema.json`（枚举扩展，**走正式兼容检查流程**）、`tests/test_projection.py` |
| 工作量 | 0.5 天 |
| 验收 | 连续写入 20 条 `TASK_STATED`，投影返回 20 条，无覆盖；先写失败测试再改实现 |
| 风险 | 契约枚举扩展需按 `contracts/reality-memory/v1/README.md` 做消费者兼容检查，别绕过 |

`fold_preference_events` 有同样结构，但偏好可能确实该只留最新——**需产品确认，本批次不动**。

### F0.2 `scripts/hackathon_demo.py` 排练脚本

**目标**：一条命令跑完第 2 段演示的全部交互点，既是排练工具，也是 L2 降级预案。

| 项 | 内容 |
|---|---|
| 涉及文件 | 新建 `services/memory-platform/scripts/hackathon_demo.py`，复用 [`multimodal_e2e_find_object.py`](../../services/memory-platform/scripts/multimodal_e2e_find_object.py) 的 ASGI + worker 启停结构 |
| 覆盖交互点 | ① 摄入 → 找物 ② 纠正后重查结果变化 ③ `forget-recent` 后查不到 + 审计留痕 ④ 未授权 Agent → 403 ⑤ CLIP 场景检索 |
| 工作量 | 1 天 |
| 验收 | 断开外网、`LLM_PROVIDER=fake` 时脚本仍完整跑通并打印每步结论 |
| 风险 | 低。已有两个同构脚本可抄 |

### F0.3 演示数据预热流程

**目标**：把「前一晚跑满 `rme_demo` 库」变成一条命令，不靠现场记忆。

| 项 | 内容 |
|---|---|
| 涉及文件 | `scripts/` 下一个 shell 或 Makefile target，串起两个既有 demo 脚本 |
| 工作量 | 0.25 天 |
| 验收 | 新机器上从空库到「找物可答、场景检索可答」全自动，无手工步骤 |

**F0 小计：1.75 天。**

---

## 3. F1 — #10 DIMENENSIONAL「Agent 触碰真实世界」

赛道核心是「Agent 主动伸手够现实」。当前 4 个工具全是读记忆，**没有一个能让 Agent 影响物理世界**。

### F1.1 `request_live_capture` 工具

| 项 | 内容 |
|---|---|
| 目标 | Agent 判定记忆置信度不足时，主动请求眼镜当场看一眼 |
| 涉及文件 | [agent-gateway/app/tools.py:13](../../services/agent-gateway/app/tools.py:13) 增工具定义 + `execute_tool` 分支；`app/memory_client.py` 增下行调用 |
| 依赖 | F1.2 |
| 工作量 | 0.5 天 |
| 验收 | Agent 对话中调用该工具 → memory-platform 产生一条 `DeviceMessage` |

### F1.2 `CAPTURE_INTENT` 下行消息类型

| 项 | 内容 |
|---|---|
| 目标 | 下行通道支持「请求采集」这一业务载荷 |
| 涉及文件 | [downlink/__init__.py](../../services/memory-platform/app/downlink/__init__.py)（消息类型 + 校验）；`tests/test_downlink.py` |
| 工作量 | 0.5 天 |
| 验收 | `POST /{device_id}/messages` 下发 → 设备 inbox / WebSocket 收到 → 回执落库 |
| 风险 | **下行业务字段在 [分层架构 §8](../architecture/README.md) 中标注为「待 review、未冻结」。** 本项属演示性扩展，不得反向声称契约已冻结 |

### F1.3 眼镜端响应 CaptureIntent

| 项 | 内容 |
|---|---|
| 目标 | 眼镜收到下行请求后触发一次采集并上行，形成闭环 |
| 涉及文件 | `apps/reality-memory-glasses/` |
| 工作量 | 1–1.5 天（**需真机，依赖持有开发线的队友**） |
| 验收 | 端到端：Agent 提问 → 眼镜自动拍 → 4 秒内答案更新 |
| 风险 | **最高**。真机联调不可控，须留 F1.4 兜底 |

### F1.4 置信度门限与兜底话术

| 项 | 内容 |
|---|---|
| 目标 | Agent 何时该调 `request_live_capture` 的判定；眼镜不可用时优雅降级 |
| 涉及文件 | `agent-gateway/app/harness.py` 系统提示 + `proactive.py` |
| 工作量 | 0.5 天 |
| 验收 | 眼镜离线时 Agent 回答「我记忆里是 X，但不确定」，不报错、不假装采集成功 |

**F1 小计：2.5–3 天。**

---

## 4. F2 — #3 灵光「见自己」：灵感旁路

完全按 [06 号文档 §9](../architecture/06-Idea-Capture-Sidecar-Architecture.md) 的批次划分，此处只做取舍。

| 批次 | 内容 | 演示必需 | 工作量 |
|---|---|---|---|
| A | `fold_task_events` 修复 | 已归入 F0.1 | — |
| B | 四张表（`idea_captures` / `idea_records` / `idea_events` / `idea_projections`）+ 迁移 `0008_idea_sidecar.py` + models + schemas | ✅ 必需 | 1 天 |
| C | 网关按 `meta.capture_purpose=="idea"` 分流 + `app/idea/` worker（ASR → 先落 `raw_text` → LLM 拆条 → 事件 → 投影）+ TTL 豁免 | ✅ 必需 | 1.5 天 |
| D | `/ideas` REST 端点 + `ideas:read` / `ideas:write` scope（**默认拒绝**） | ✅ 必需（前端要读） | 1 天 |
| E | 删除子系统 + 墓碑 | ⭕ 可延后 | 0.5 天 |
| F | 五个测试文件 | ✅ **`test_idea_degradation.py` 必需** | 1 天 |

### 演示关键点：降级测试就是卖点

06 号文档 §5.1 的验收底线是「**用户按下了捕捉键，就必须有一条东西留下来**」。
台上当场把 LLM 关掉（`LLM_PROVIDER=fake`）再录一条，条目依然在 —— 这比任何功能罗列都有说服力。
因此 `tests/test_idea_degradation.py` 不是测试，**是演示脚本的源代码**。

### 契约兼容红线

按 06 号文档 §4.2：**不要给 `SourceEnvelopeIn.trigger` 加 `idea_capture` 枚举**，
用 `meta.capture_purpose` 承载。零契约变更，旧消费者原样忽略。

**F2 小计：4.5 天（含 E）/ 4 天（不含 E）。**

---

## 5. F3 — #2 Desktop Daemon：本地信任域

**只缺 VLM 一环**（见 §1 推论）。

### F3.1 本地 VLM 兜底

| 项 | 内容 |
|---|---|
| 目标 | 拔掉外网后 caption / 抽取仍能产出，不退化成 `fake` |
| 涉及文件 | `app/llm/` 增一个本地 provider；`config.py` 的 `llm_provider` 枚举扩展 |
| 工作量 | 1–2 天（**取决于选型和显存**，见待决 Q4） |
| 验收 | `LLM_PROVIDER=local` + 断网，`hackathon_demo.py` 全流程通过 |
| 风险 | 中高。模型选型和硬件能力未确认，**这是 F3 唯一的不确定项** |

### F3.2 本地部署包

| 项 | 内容 |
|---|---|
| 目标 | Memory Platform + Postgres + ASR sidecar 一键起在一台桌面机上 |
| 涉及文件 | `infra/` 下 compose 或脚本 |
| 工作量 | 0.5 天 |
| 验收 | 新机器 `docker compose up` 后 `/healthz` 通过 |

### F3.3 夜间批处理

| 项 | 内容 |
|---|---|
| 目标 | 「睡觉时办事」——空闲时段消化 `pending_outbox` 积压 |
| 涉及文件 | `app/workers/` 增调度策略 |
| 工作量 | 0.5 天 |
| 验收 | 白天堆积的感知任务在夜间窗口自动清空，`pending_outbox` 归零 |
| 备注 | 这一条是赛题「睡觉时办事」的字面回应，**性价比最高** |

**F3 小计：2–3 天。**

---

## 6. F4 — #21 涂鸦：结构化事件入口

**现状障碍**：[schemas/__init__.py:53](../../services/memory-platform/app/schemas/__init__.py:53) 的
`modality` 是 `Literal["image","video","audio","sensor"]`，
**没有结构化设备事件这一类**。PRD §8.1 把「结构化事件」列为独立模态并声称「直接进入候选链」，
但契约里没有对应位置。

| 项 | 内容 |
|---|---|
| 目标 | 门锁/传感器事件进入候选链，触发一次采集 |
| 方案 | 复用 `modality="sensor"` + `meta` 承载事件语义（与 06 号文档 §4.2 同样的规避思路，**不动冻结枚举**） |
| 涉及文件 | `app/perception/` 增结构化事件处理分支；`app/gateway/` 分流 |
| 工作量 | 1 天 |
| 验收 | POST 一条门锁事件 → 产生 `AtomicObservation` → 进入候选 |
| 风险 | 需确认涂鸦设备能否领到；拿不到则用 curl 模拟事件，**赛题看的是「解决真实生活问题」而非「设备真连上了」** |

**F4 小计：1 天。**

---

## 7. F5 — #1 Injective：Idea 存在性证明

严格按 [07 号文档 §10](../architecture/concepts/07-Idea-Provenance-and-Encrypted-Matching.md) 的分期，
**只做 Phase 0 + Phase 1，不碰 Phase 2/3**。

### F5.1 Phase 0：承诺层

| 项 | 内容 |
|---|---|
| 目标 | 每条 `idea_record` 的加盐 hash，本地计算，不上链 |
| 涉及文件 | `app/idea/hashing.py`：JCS（RFC 8785）canonical 序列化 + 32 字节 CSPRNG salt + SHA-256 |
| 依赖 | **F2 批次 B**（`content_hash` / `hash_salt` 字段在 `idea_records` 上） |
| 工作量 | 0.5 天 |
| 验收 | 07 号文档 §10.2 四条：跨机器同 hash、salt 进备份流程、**有独立离线校验脚本**、文档写明「这不是法律确权」 |

### F5.2 Phase 1：锚定层

| 项 | 内容 |
|---|---|
| 目标 | 每日 Merkle root 上链，单条保留 inclusion proof |
| 涉及文件 | 新建独立目录（**不进 memory-platform**）；合约用 `injective-evm-developer` |
| 工作量 | 1.5–2 天 |
| 验收 | 评委输入 `内容 + salt` → 离线脚本算出 hash → 与链上 root 比对通过。**必须让评委自己跑一遍** |
| 风险 | 测试网水龙头、钱包、Gas，全部现场不可控 → **前一晚锚定好，台上只做验证不做上链** |

### 叙事红线

07 号文档 §7.4 明确反对把加密货币基础设施引入 RealGit 主体：
「方向与 RealGit 的信任叙事相反……**若真要做，做成独立产品线、独立 App、独立品牌**」。

**执行上**：独立分支、独立 README、与主产品只共享灵感数据导出接口。
不要把 RealGit 包装成区块链项目。

**F5 小计：2–2.5 天。**

---

## 8. F6 — #23 zilo：戒指 Adapter

| 项 | 内容 |
|---|---|
| 目标 | Zilo Whisper 按键 + 麦克风接入，作为触发源和主动语音入口 |
| 方案 | 按 PRD §4.5 写一个 Device Adapter，记忆本体零改动 |
| 参照 | 已有 `hardware/ring-sound-sdk/`（协议、`ring_sound.py`）可作实现范本 |
| 工作量 | 1–2 天（**完全取决于 Zilo SDK 质量**） |
| 验收 | 按戒指说一句 → 条目落库 →（可选）眼镜 TTS 回读 |
| 风险 | **阻塞性**：拿不到实物则整个赛道放弃，不做任何前置投入 |

**F6 小计：1–2 天（条件性）。**

---

## 9. 优先级与排期

### 9.1 依赖关系

```text
F0.1 修复缺陷 ─────────────┐
F0.2 排练脚本 ─┬───────────┤
F0.3 数据预热 ─┘           │
                           ├─→ 所有演示
F2-B 灵感表 ──→ F2-C 流水线 ──→ F2-D API ──→ #3 可演示
      └────────────────────────→ F5.1 Phase0 ──→ F5.2 Phase1 ──→ #1 可演示
F1.2 下行消息 ──→ F1.1 工具 ──→ F1.3 眼镜端 ──→ #10 可演示
                                    └─ F1.4 兜底（F1.3 失败时替代）
F3.1 本地 VLM ─┬→ F3.2 部署包 ─→ F3.3 夜间批处理 ──→ #2 可演示
```

### 9.2 建议顺序

| 序 | 内容 | 累计 | 理由 |
|---|---|---|---|
| 1 | F0 全部 | 1.75 天 | 无条件必做，且 F0.1 是真 bug |
| 2 | F1.1 + F1.2 + F1.4 | 3.25 天 | 不依赖真机，先把 Agent 侧做完 |
| 3 | F2 批次 B/C/D/F | 7.25 天 | 最大单块，纯软件可控 |
| 4 | F1.3 眼镜端 | 8.75 天 | 与队友真机进度并行，**失败有 F1.4 兜底** |
| 5 | F3 全部 | 11.25 天 | 本地 VLM 是唯一不确定项 |
| 6 | F5.1 + F5.2 | 13.5 天 | 依赖 F2-B 完成 |
| 7 | F4 / F6 | 条件性 | 设备到位才做 |

### 9.3 如果时间只够一半

砍到 **F0 + F1（除 F1.3）+ F2 批次 B/C/D**，约 6.5 天，可完整演示 #10 和 #3 两个赛道。
这两个也正是 [赛道选择文档 §2.5](Hackathon-Track-Selection-and-Demo-Plan-v0.1.md) 推荐的核心组合中的两个。

---

## 10. 明确不做

| 不做 | 原因 |
|---|---|
| 耗材趋势预测的真实实现 | 需多天连续观测，hackathon 物理上不可能。演示用预置曲线并**明确说明** |
| 执行器 / 电机 / 开门 | #10 赛题提到但本项目无硬件基础，不硬凑 |
| 07 号文档 Phase 2/3（teaser 市场、密码学发现层） | 文档自己的结论是「Phase 2 必须先成功才能做 Phase 3」，而 Phase 2 都没开始 |
| 灵感的自动优先级排序 / 每日回顾 | 06 号文档 §10 明确列为 non-goal，先验证捕捉本身 |
| `fold_preference_events` 改 list | 偏好可能确实该只留最新，**需产品确认后再动** |
| 松灵 / 地瓜 / PICO 的运行环境适配 | 见赛道选择文档 §2.3，工程量是从头再来 |

---

## 11. 待决问题

- **Q1** Zilo Whisper 与涂鸦设备能否领到实物？直接决定 F6 / F4 是否启动。
- **Q2** F3.1 本地 VLM 选哪个模型？显存是否够？**这是 F3 唯一的不确定项，应最先验证**。
- **Q3** F1.3 眼镜端由谁做、真机什么时候可用？决定 #10 是完整闭环还是降级演示。
- **Q4** F0.1 的契约枚举扩展（`TASK_COMPLETED` / `TASK_CANCELLED`）走完整兼容检查流程需要多久？
- **Q5** F5 独立分支的品牌/命名是否现在就定？影响 README 和演示物料。

---

## 12. 本文档不承诺的事

- 工作量是估算不是承诺，未经排期确认
- 本清单中的功能未进入 [PRD](../product/RealGit-PRD-v1.3.md) 与
  [分层架构](../architecture/README.md) 之前，**不构成实现依据**
- F1.2 的下行业务字段属演示性扩展，不得据此声称下行契约已冻结
- F5 不承诺任何法律保护效果（沿用 07 号文档 §12 的免责范围）
