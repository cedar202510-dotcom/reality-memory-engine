# Agent Memory 平台与开源方案竞争格局调研（截至 2026 年中）

> 调研目的：评估 RealGit（ontology + 事件溯源 + 候选门 + 五段时间模型 + 删除回执）推广为通用 agent memory 方案的差异化空间。

---

## 1. Mem0

- **架构核心**：「抽取 → 整合 → 检索」流水线。基础版是向量库 + 事实片段；Mem0g 变体在向量库旁加一个有向带标签知识图谱。混合检索（语义 + 关键词 + 实体）。论文：[Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory (arXiv 2504.19413, 2025-04)](https://arxiv.org/html/2605.28969v1)。
- **写入机制**：每轮对话后由 LLM 抽取「显著事实」，与已有相似记忆比对后自主决定 ADD / UPDATE / DELETE / NOOP。**全自动提交，无候选/确认门**——LLM 抽取结果直接成为事实。
- **读取/注入**：语义 top-k + 图遍历，注入上下文；宣称比 OpenAI 内置记忆快 91%、省 90% token。
- **时间模型**：事实带时间戳；2026-04 算法重写后宣称加强 temporal/multi-hop 查询，但本质上不是双时态（bi-temporal）模型。
- **特色/优势**：生态与分发最强——YC 支持，累计融资 2400 万美元（2025-10 宣布 Series A 2000 万，Basis Set Ventures 领投，Peak XV、GitHub Fund 参与）；宣称是 AWS Agent SDK 独家记忆提供方；2025 年 API 调用量从 3500 万增至 1.86 亿。开源 Apache 2.0，star 约 4.8–5.8 万（不同来源口径不一）。定价：免费档 / $19 Starter / $79 Growth / $249 Pro。来源：[Ry Walker Research: Mem0](https://rywalker.com/research/mem0)、[Hamza Shabbir: Mem0 vs Letta vs Zep](https://hamzashabbir.dev/article/ai-agent-memory-layer-mem0-vs-letta-vs-zep)、[Atlan: Mem0 alternatives](https://atlan.com/know/mem0-alternatives/)。
- **不足与痛点**：
  - **benchmark 争议是公开的**：Mem0 论文把 Zep 测成 65.99%，Zep 用修正后的 harness（修复说话人角色映射、时间戳 API、并行检索）重测为 75.14%，约 9 分差距；Mem0 反分析则称 Zep 另报的 84% 在正确处理 adversarial 类别并做 10 次平均后跌到 58.44%。双方都是善意争论实现细节，但说明**分数是 harness 的属性，不是系统的属性**。来源：[Mnemoverse: LLM-as-a-Judge & the LoCoMo Number](https://mnemoverse.com/docs/research/evaluation/llm-as-judge-patterns)。
  - LOCOMO 本身有方法论缺陷：Mem0 代码库里的 `answer_matches` 在 gold 为空时恒返回 False，导致 446 道 category-5 题中 444 道（约占整个 benchmark 23%）「正确拒答」和「幻觉编造」得同样的零分——对抗类分数在文献中基本不可测。来源：[Positioning Continuity Evaluation (arXiv 2604.10981)](https://arxiv.org/html/2604.10981v2)。
  - 厂商博客后来宣称 91.6（LOCOMO）/93.4（LongMemEval），但这是非同行评议的自报数（harness 开源于 mem0ai/memory-benchmarks），与论文里 GPT-4o-mini 的 68.44 差距很大，口径混乱。来源：[Beyond Recall (arXiv 2605.28969) Table 2.1](https://arxiv.org/html/2605.28969v1)。
  - 抽取即事实，无审计链：无法回答「这条记忆为什么存在、由谁确认」。

## 2. Zep / Graphiti

- **架构核心**：**双时态知识图谱**（bi-temporal KG），Neo4j 后端。每条边带四个时间戳：`t_created`/`t_expired`（事务时间轴）+ `t_valid`/`t_invalid`（有效时间轴）。这是全场最接近我们事件溯源语义的系统。来源：[Zep: A Temporal Knowledge Graph Architecture for Agent Memory (arXiv 2501.13956, 2025-01)](https://arxiv.org/html/2501.13956v1)、[wal.sh: Agent Memory Architectures decomposed](https://wal.sh/research/2026-agent-memory-systems/)。
- **写入机制**：`add_episode` → LLM 抽取实体+边 → 物化进图；**冲突时自动 invalidate 旧边（supersede 的等价物）**，旧事实不删除而是标记失效、保留历史。无候选门——抽取直接入图。
- **读取/注入**：三模态混合检索（BM25 + 余弦 + 图遍历），返回的是**合成后的事实字符串而非原文**。宣称 DMR 94.8%（vs MemGPT 93.4%）、LongMemEval +18.5% 准确率 / -90% 延迟。
- **时间模型**：**全场最强**——显式双时态，支持边有效期与 as-of 语义。
- **特色/优势**：时态语义工程化程度最高；Graphiti 开源被广泛采用（约 1.2 万 star，[niteagent 对比](https://niteagent.com/blog/ai-agent-memory-comparison-2026/)）；第三方（donto 报告）称其为「与我们最接近的单一对标：独立做到了双时态建模 + 溯源 + 边失效」。
- **不足与痛点**：
  - **删除/遗忘原语缺失**：在 ForgetEval-Adv 385 例删除基准上只得 7%，143 例因「release 和 query-addressable purge 原语缺失」无法评测。来源：[Control-Plane Placement Shapes Forgetting (arXiv 2606.15903)](https://arxiv.org/html/2606.15903v2)。
  - 合成事实字符串丢失表层形式（surface form），对逐字校验类评测是类别性错配。
  - LLM 抽取错误直接烙进图；无候选隔离。
  - Zep CE 已弃用，Graphiti 是开源继任者；商业版 Zep Cloud 免费档 + Flex 约 $125/月（5 万 credits）。来源：[Mem0 vs Zep (mem0.ai 博客)](https://mem0.ai/blog/mem0-vs-zep)。

## 3. Letta（原 MemGPT）

- **架构核心**：「LLM 即操作系统」隐喻。三层：**core memory blocks**（常驻上下文、自编辑）、**recall memory**（对话历史检索）、**archival memory**（向量库）。Letta V1（2025）加入原生推理与 heartbeats 多步控制。配套 ADE 开发环境与 Agent File（.af）开放序列化格式。来源：[Letta 官方: Memory Blocks](https://www.letta.com/blog/memory-blocks/)、[letta-ai/agent-file](https://github.com/letta-ai/agent-file)。
- **写入机制**：**agent 自编辑**——模型通过 `memory_insert` 等工具自己决定何时写什么。这是最激进的「写入权交给模型」方案。
- **时间模型**：无事实有效期、无 as-of 查询；冲突靠模型自己覆写 block。
- **特色/优势**：记忆与 agent runtime 深度一体；状态可移植（.af）；分层控制对开发者透明可控。
- **不足与痛点**：
  - **换页是自愿的**：没有「内核」在内存压力时强制换出；模型必须在事实滑出 FIFO 窗口前自觉写入归档，失败模式是「读起来流利的静默遗忘」。来源：[wal.sh 架构分解](https://wal.sh/research/2026-agent-memory-systems/)。
  - 自编辑无外部验证循环，压缩误差会逐周期累积（Root Theorem 论文的批评）。来源：[Root Theorem of Context Engineering (arXiv 2604.20874)](https://arxiv.org/html/2604.20874v1)。
  - 约 2.1 万 star；Cloud Pro 约 $20/月。来源：[openalternative: CopilotKit vs Letta](https://openalternative.co/compare/copilotkit/vs/letta)、[developersdigest](https://www.developersdigest.tech/blog/best-ai-agent-memory-providers-2026)。

## 4. LangMem（LangChain）

- **架构核心**：存储无关的记忆 SDK，建在 LangGraph `BaseStore` 上。三类记忆：**semantic**（事实/偏好）、**episodic**（交互样例）、**procedural**（经验改写系统提示词——Mem0/Zep 均无对应物）。
- **写入机制**：`create_manage_memory_tool`（agent 主动写）+ `create_memory_store_manager`（会话后后台抽取）。namespace 按 user_id 隔离。
- **时间模型**：无有效期/as-of 概念；无候选门。
- **特色/优势**：LangGraph 生态内零摩擦；MIT 免费；程序化记忆（改自身 prompt）独家。
- **不足与痛点**：年轻 SDK、API 演进快；价值基本绑定 LangChain 栈；纯记忆能力被 Letta/Zep/Mem0 全面超越（[agentmarketcap 评估](https://agentmarketcap.ai/blog/2026/04/10/agent-memory-vendor-landscape-2026-letta-zep-mem0-langmem)）。来源：[LangMem 官方文档教程（DigitalOcean）](https://www.digitalocean.com/community/tutorials/langmem-sdk-agent-long-term-memory)、[Atlan 指南](https://atlan.com/know/long-term-memory-langchain-agents/)。

## 5. Supermemory

- **架构核心**：自研学习模型 + 图数据库，基础设施为 Cloudflare Workers + PostgreSQL/pgvector。摄取管线内置 embedding、chunking、事实抽取与**矛盾消解**；自动构建用户画像；事实分 static（长期）/ dynamic（近期上下文）。提供连接器（Gmail、Notion、Drive、GitHub、S3 等）与 MCP server。来源：[vectorize.io 八框架对比](https://vectorize.io/articles/best-ai-agent-memory-systems)、[Supermemory 官方: How it works](https://supermemory.ai/docs/concepts/how-it-works)。
- **写入机制**：全自动摄取 + 内部矛盾消解；无公开候选门机制。
- **时间模型**：static/dynamic 二分 + 画像持续更新，非双时态。
- **采用现状**：2024-04 以消费者书签工具起家，2025-04 高峰 5 万用户、1 万+ star；2025-10 完成种子轮（约 260 万美元，Google/Cloudflare 高管参投）后转型 memory API。2026 年 star 约 2.2 万。定价按用量：免费档 $5/月额度，Pro 档约 $20–399/月。来源：[MemoryPlugin 编年](https://www.memoryplugin.com/alternatives/supermemory)、[Gamgee 对比](https://gamgee.ai/vs/supermemory-vs-retaindb/)、[supermemory.ai/pricing](https://supermemory.ai/pricing/)。
- **不足与痛点**：内部实现闭源黑盒；「比 Mem0 快 25 倍、比 Zep 快 10 倍」等为厂商自报，无第三方审计。

## 6. Cognee

- **架构核心**：开源（Apache 2.0）记忆平台：文档 → chunk → 向量 embedding + 图节点抽取 + 关系发现 + **自动生成 ontology**。知识图谱与向量双写。v1.0（2026-06-26）推出记忆原生 API：`remember / recall / forget / improve`。可完全自托管（Docker/pip），PostgreSQL 持久化，带 Web UI。来源：[dailyaiworld](https://dailyaiworld.com/workflow/cognee-agent-memory-knowledge-graph-workflow-2026)、[noqta: Cognee v1.0](https://noqta.tn/en/blog/cognee-v1-open-source-memory-layer-ai-agents-guide-2026)。
- **写入机制**：摄取管线自动抽取，无候选门；`improve()` 做事后图精炼。
- **时间模型**：演化的 KG，无严格双时态语义。
- **采用现状**：约 2.7–2.8 万 star、190 贡献者、127 个 release；企业里常与推理层产品（如 Naboo）配套部署。
- **不足与痛点**：ontology 自动生成噪声较大；`forget()` 语义严谨性存疑（无删除审计）；API 年轻。第三方定位为「agent 见过什么」而非「公司决定什么」。

## 7. 平台内置记忆（OpenAI / Anthropic / Google）

- **ChatGPT（Dreaming V3）**：记忆演进三阶段——saved memories（2024-04，手动「记住这个」清单）→ Dreaming v0（2025-04，后台引用历史补充）→ **Dreaming V3（2026-06-04）**：完全替代手动清单，后台进程跨全部对话合成单一记忆状态，**自我更新**（例子：「你七月要去新加坡」过期后自动改写为「你七月去了新加坡」），Plus/Pro 容量翻倍，厂商宣称事实召回 82.8%。**代价：放弃了逐条记忆的精确审计轨迹**。来源：[theaitrack](https://theaitrack.com/openai-chatgpt-memory-dreaming-update/)、[MemX](https://memx.app/blog/chatgpt-dreaming-v3-memory-explained/)、[MemoryLake](https://www.memorylake.ai/en/blogs/chatgpt-dreaming-memory)。
- **Claude**：2025-09 起向 Team/Enterprise 推出记忆——**按项目隔离的记忆摘要**，约每 24 小时自动合成更新一次，提供 memory summary 界面供查看/编辑，并向所有用户提供 incognito 聊天。来源：[VentureBeat](https://venturebeat.com/ai/anthropic-adds-memory-to-claude-team-and-enterprise-incognito-for-all)、[MemoryX 对比](https://memoryx.cc/blog/ai-memory-comparison/)。
- **Gemini**：Personal context（2025）可引用过往对话；2026-03 上线**从 ChatGPT/Claude 导入记忆**的工具——记忆可移植性已成平台竞争战场。来源：[gHacks](https://www.ghacks.net/2026/03/31/google-adds-chatgpt-and-claude-import-tools-to-gemini-for-memory-and-chat-history/)、[Android Police](https://www.androidpolice.com/gemini-takes-on-chatgpt-claude-major-switching-upgrade/)。
- **共同特征**：平台内闭环、无外部 ontology/API、可审计性弱（Dreaming 明确牺牲了审计换取新鲜度）、跨平台携带靠导入导出 hack。这恰是独立记忆层（含我们方案）存在的市场理由。

## 8. 学术方案

| 方案 | 核心机制 | 时间/冲突处理 | 备注 |
|---|---|---|---|
| **Generative Agents**（Stanford, Park 2023）| 记忆流 + 检索打分（recency+importance+relevance）+ reflection 生成高层抽象 | 无冲突/失效语义 | 范式奠基作，几乎所有后续系统引用 |
| **MemoryBank**（AAAI 2024）| 记忆流 + 艾宾浩斯遗忘曲线衰减 + 每日摘要 + 用户画像 | 衰减式遗忘，无冲突消解 | 「遗忘」首次被形式化 |
| **MemGPT**（Packer 2023）| OS 虚拟内存/分页，自编辑 | 无 | → 商业化即 Letta |
| **A-MEM**（arXiv 2502.12110, 2025-02，被引约 900）| Zettelkasten 笔记卡（关键词/标签/上下文属性），新记忆触发**链接生成 + 记忆演化**（旧笔记被更新）| 演化是启发式的，无有效期/失效 | 动态图式记忆的学术代表 |
| **HippoRAG / HippoRAG 2**（NeurIPS 2024 / 2025）| 海马体索引：KG + Personalized PageRank 多跳联想检索 | 增量整合，无失效语义 | 检索侧创新，非写入治理 |
| **MemOS**（arXiv 2505.22101 / 2507.03724, 2025）| 记忆作为可调度资源：**MemCube** 单元 + 全生命周期（生成/激活/融合/归档/过期）+ MemScheduler/MemGovernance + **溯源标签、版本追踪、细粒度权限** | 有生命周期与过期概念，但非事件溯源 | 系统级治理的最强学术表述，与我们理念最接近 |
| **EverMemOS**（arXiv 2601.02163, 2026-01，被引 26）| 记忆痕（engram）生命周期：对话流 → **MemCell**（情景痕迹+原子事实+时间限定的 Foresight 信号）→ 主题性 **MemScene** 巩固 + 用户画像 → MemScene 引导的 agentic 检索重组上下文 | 时间限定信号，冲突消解仍是模型驱动 | 宣称 LoCoMo/LongMemEval SOTA，代码开源；分层（cell→scene）与我们 L1→L3 类似 |

**2026 年新趋势（重要）**：学术界正在向我们设计的方向收敛——[Eywa: Provenance-Grounded Long-Term Memory（2026-05）](https://arxiv.org/html/2605.30771v1)主打溯源接地；[ElephantBroker](https://arxiv.org/pdf/2603.25097)实现「四状态证据验证模型」；[MemGuard（2026-05）](https://arxiv.org/html/2605.28009v1)专治记忆污染；[ForgetEval-Adv / Control-Plane Placement（2026-06）](https://arxiv.org/html/2606.15903v2)首次系统化评测删除/遗忘。这些都还是论文而非生产平台，但说明「候选验证 + 溯源 + 可删除」已是公认缺口。

---

## 横向对比与差异化评估

### 公认未解决的痛点（跨来源共识）

1. **评测危机**：LOCOMO 分数 harness 依赖（Mem0↔Zep 互相打脸各 9–25 分）、拒答 matcher bug 使 23% 题目不可测、LLM-as-judge 方差大。2026 年已有评论直呼「benchmark 剧场」：[The Hidden Layer](https://essays.bloo-mind.ai/posts/2026-05-20-mem-eval/)。**没有任何记忆系统拥有一个可信的、治理维度的评测故事**。
2. **写入时机与写入权**：两个极端都失败——Letta 式模型自觉写入 → 静默遗忘；Mem0/Zep 式自动抽取 → 抽取幻觉直接成事实。**没有生产系统做候选隔离**。
3. **冲突与过时**：多数是 LLM 决定的 UPDATE/DELETE 或 last-write-wins；双时态只有 Zep 一家；五段时间模型无人实现。来源：[AI Memory Works: Conflicts](https://aimemoryworks.com/architecture/conflicting-memories/)。
4. **遗忘与删除**：Graphiti 在删除基准上 7%；各家普遍缺 query-addressable purge；GDPR 式删除回执全场缺席。
5. **记忆污染/投毒**：MemGuard、PersistBench 等 2026 论文专门立项，说明已是现实威胁。
6. **可审计性倒退**：Dreaming V3 用合成换新鲜度、主动放弃逐条审计——大平台在往反方向走，留下治理型记忆的市场空位。

### RealGit 的差异化判定

| 设计要素 | 场上最接近的等价物 | 判定 |
|---|---|---|
| **候选/事实硬隔离 + 置信度门** | 无生产等价物；仅 2026 研究（Eywa 验证状态、ElephantBroker 四状态证据、MemGuard 过滤）触及 | ✅ **真差异化**（但窗口有限，学界在收敛） |
| **事件溯源：追加 MemoryEvent + supersedes 链 + 投影重算** | Zep 边失效是最接近语义，但它是图内就地失效而非可重放事件日志+可重算投影；Mem0 直接改写片段；MemOS 有版本追踪但非事件溯源 | ✅ **真差异化**（事件溯源+投影重算无等价物） |
| **五段时间模型**（发生/观察/接收/接受/有效期）| Zep 双时态（2 轴 4 时间戳）是其真子集 | ✅ **真差异化**（严格超集） |
| **删除回执 + 审计** | 全场缺席；ChatGPT 反其道而行 | ✅ **真差异化** |
| **分层 L1 摘要→L2 候选→L3 实体主线** | EverMemOS MemCell→MemScene、Generative Agents reflection、LangMem 三类记忆 | ⚠️ 差异化最弱，属行业通行做法 |
| **ontology（实体类型+状态维度+事件类型）** | Cognee 自动 ontology、Zep 图 schema | ⚠️ 部分差异：我们显式声明 vs 它们自动推断 |

**结论**：没有任何单一系统或组合与我们的全套设计等价。最接近的对手是 **Zep**（双时态+失效+溯源，但无候选门、无投影重算、删除能力实测垫底）；概念上最接近的是 **MemOS**（治理/生命周期/溯源的学术表述）和 2026 年溯源/验证类新论文。**真正的护城河在「治理与信任」维度（候选门、事件溯源、可删除、可审计）——而这恰恰是所有现有 benchmark（LOCOMO/LongMemEval/DMR）不测的维度**。

**战略含义**：差异化成立，但需要自带评测故事——用 ForgetEval 式删除基准、冲突消解基准、as-of 查询正确性、写入污染抵抗（MemGuard 式攻击）来定义一个新的评测象限，而不是在 LOCOMO 的「harness 剧场」里与 Mem0/Zep 缠斗。窗口期估计 1–2 年：学术界 2026 年已开始收敛到同一方向。
