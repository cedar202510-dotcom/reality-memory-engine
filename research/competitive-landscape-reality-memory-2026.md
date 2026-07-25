# “现实记忆”相邻场景竞品与替代方案调研（截至 2026 年中）

> 调研目的：为 RealGit（眼镜+戒指采集→结构化现实记忆）的 P0 场景——①找物、②耗材余量提醒、③口头偏好/任务记录、④隐私可控采集——评估现有方案与痛点，判断真需求/伪需求与机会窗口。

---

## A. 找物方案

### A1. 蓝牙/UWB 追踪器（AirTag / Tile / SmartTag / Chipolo）

**怎么解决**：给物品挂标签 → 手机 App 定位/响铃/众包网络找回。

**明确的不足与痛点**：

1. **只能找“挂了标签的”**——这是品类结构性天花板。钥匙、钱包、行李箱可以挂，但遥控器、眼镜、水杯、文件、玩具等日常高频丢失物无法也不值得全部挂标签（单个 AirTag 249 元，且没有挂孔需另购配件）。来源：微信公众号评测 https://mp.weixin.qq.com/s?__biz=MzA5OTA4NTE4Mw==&mid=2650914105&idx=2&sn=ba91c2f3753b7184d64102dd91daa2f0
2. **家庭共享曾是重大槽点**：AirTag 上市时只能绑定单一 Apple ID，家人无法看到彼此的 AirTag。2021 年 MacRumors 汇集大量用户抱怨（夫妻共用钥匙场景集体翻车：“Tile 都能共享，苹果居然不行”）。iOS 17（2023）才补上“最多共享 5 人”。来源：https://www.macrumors.com/2021/05/04/airtag-uses-disappointed-family-sharing/ ；https://www.theverge.com/2023/6/6/23751614/apple-airtag-find-my-sharing-ios-17-feature
3. **反跟踪争议持续发酵**：苹果 2021.4–2024.4 收到超 4 万起跟踪报告；截至 2026.5 面临 30+ 起诉讼；内部文件承认安全措施“只能威慑、不能防止”恶意使用；曾发生 AirTag 跟踪致死案；eBay 上甚至有拆掉扬声器的“静音 AirTag”。反跟踪机制（警报延迟、提示音响起）与防盗/找回功能存在内在矛盾——“防跟踪做得越好，找被盗物品就越没用”。来源：https://www.macrumors.com/2026/05/01/airtag-stalking-lawsuits-apple/ ；https://www.engadget.com/apple-airtag-stalking-police-reports-190022315.html ；https://zhuanlan.zhihu.com/p/372279706
4. **生态锁定**：AirTag 仅 iPhone、SmartTag 仅三星手机可用；SmartTag 实测有效距离约 30 米；Tile 长期没有 UWB 精准定位，众包网络密度远小于 Find My。来源：https://finance.sina.cn/tech/2021-03-08/detail-ikkntiak5972894.d.html ；https://www.life360.com/en-mx/blog/bluetooth-tracker-buying-guide

### A2. 视觉找物（智能眼镜官方功能）

- **Ray-Ban Meta“记忆”功能**（Meta Connect 2024 发布，2024.10 随 Meta View v186 推送）：用户需主动说“Hey Meta, remember where I parked”，眼镜拍下当下画面，之后可问“我车停哪了”。**这是目前大厂眼镜上唯一与“现实记忆”直接相关的功能**。痛点：①必须由用户预判并主动下指令——Mashable 直接点破：“讽刺的是，健忘的人首先要记得让 AI 去记”；②只做一次性“记住-回放”，没有被动、持续的结构化物品位置索引；③“钥匙放哪了”这类事后追问不在能力内。来源：https://mashable.com/article/ray-ban-meta-smart-glasses-wheres-my-car ；https://www.theverge.com/2024/10/3/24261238/meta-ray-ban-update-reminders-voice-messages
- **Rokid Glasses（2025）**：主打翻译/导航/拍照/提词，AI 物体识别为即时问答型，无持久物品位置记忆产品。来源：https://www.ubergizmo.com/2025/09/rokid-glasses/

### A3. 家庭机器人

- **Amazon Astro**：2021 发布，研发成本超 10 亿美元，售价 $1,600 且至今仅邀请制；从未提供物品定位功能，定位是“带轮子的 Echo Show + 移动监控”。被早期评论称为“a solution in search of a problem”。Astro for Business 上线仅 8 个月（2023.11–2024.7）即关停并变砖退款。来源：https://www.geekwire.com/2024/amazon-discontinues-astro-for-business-robot-security-guard-to-focus-on-astro-home-robot/ ；https://www.eetimes.com/amazon-struggle-with-roi-in-smart-homes-and-iot/
- **Samsung Ballie**：承诺 2025 夏上市 → 跳票 → 缺席 CES 2026 → 官网报名页悄然下线。来源：https://the-gadgeteer.com/2026/05/20/home-robots-available-2026/

**判断：真需求，方案严重不全。** Tile 用十年验证了“找物”付费市场，AirTag 把它做大；但所有方案只覆盖“可挂标签的物品”这一小块。视觉/机器人路线要么是“主动指令式一次性记忆”（Meta），要么根本没有物品定位能力（Astro/Ballie）。**“没挂标签的日常物品上次放哪了”在消费级市场无任何可用方案。**

---

## B. 屏幕/数字生活记忆（“现实记忆”的对照系）

### B1. Microsoft Recall（Copilot+ PC）

- 2024.5 发布即被安全研究者称“privacy nightmare”“内置间谍软件”，被迫从 2024.6 首发一路推迟近一年，2025.4 才正式推送。
- 最终形态：**opt-in（默认关闭）+ Windows Hello 生物认证 + 本地处理本地加密存储 + 敏感信息（密码/银行卡/SSN）自动过滤 + 可按应用/网站过滤 + 可暂停可删除可整体卸载**，且仅限 40+ TOPS NPU 的 Copilot+ PC。
- 媒体定性：“Recall 的真正问题是人们不信任微软”（PCMag 评论标题）。
- 来源：https://www.zdnet.com/article/microsoft-adds-three-new-ai-features-to-copilot-pcs-including-the-controversial-recall/ ；https://blogs.windows.com/windowsexperience/2024/06/07/update-on-the-recall-preview-feature-for-copilot-pcs/ ；https://support.microsoft.com/en-us/windows/privacy/privacy-and-control-over-your-recall-experience ；https://www.pcmag.com/opinions/categories/operating-systems

### B2. Rewind.ai → Limitless → 被 Meta 收购关停

- Rewind（2022.11 Mac 上线）：本地录屏+OCR+转写，“人生搜索引擎”，主打 local-first 隐私，a16z/NEA 投资，曾病毒式传播。
- 2024.4 转型 Limitless Pendant（$99 吊坠），存储从纯本地转为“Confidential Cloud”，老用户普遍认为“bait-and-switch”。
- **2025.12.5 Meta 收购 Limitless；Rewind Mac 应用 2025.12.19 停止录制并下架；Pendant 停售；EU/UK/巴西/以色列/韩国/土耳其/中国区直接停服**，存量用户须接受 Meta 新隐私条款或限期导出数据。独立“记忆增强”公司故事终结，团队并入 Reality Labs 做眼镜。
- 来源：https://techinformed.com/meta-acquires-limitless-pendant-users-moved-to-free-unlimited-plan/ ；https://www.usecarly.com/blog/meta-limitless-acquisition/ ；https://luci.memories.ai/blog/rewind-ai-shut-down-on-device-replacement

### B3. Apple / Google 的屏幕与视觉记忆能力

- **Apple Visual Intelligence（iOS 26，2025）**：截图即搜（Ask / Image Search / Highlight to Search），对标 Circle to Search；端侧处理 + Private Cloud Compute。属“查询时刻的工具”，不做持久记忆。来源：https://www.bgr.com/tech/visual-intelligence-in-ios-26-is-almost-as-good-as-googles-circle-to-search/
- **Google Circle to Search / Gemini 屏幕上下文**：同为即时屏幕理解；Google 的 Project Astra 展示过“眼镜记住你看到的东西”的原型（视觉+记忆），但未产品化。来源：https://jetruby.com/blog/mobile-intelligence-2025-google-vs-apple/

### B4. 隐私设计光谱与公众反应

| 产品 | 存储/处理 | 默认状态 | 删除机制 | 公众反应 |
|---|---|---|---|---|
| Recall | 本地+加密 | opt-in（被舆论逼出来的） | 可暂停/过滤/删除/卸载 | 发布即翻车，推迟一年 |
| Rewind | 纯本地 | 默认录 | 本地可控 | 隐私口碑好，但死于商业转型 |
| Limitless | 云端 Confidential Cloud + Consent Mode | 默认录 | 收购后限期导出 | 收购后信任崩塌、区域停服 |
| Alexa+（2025.2） | 云端（2025.3 起取消本地语音处理选项） | 持久记忆偏好 | App 内管理 | 隐私顾虑+非 Prime $19.99/月 |

**判断：需求被验证（“photographic memory”叙事两次病毒传播），但①信任是准入门槛，Recall/Apple/AirTag 史证明默认开启=公关灾难，opt-in+本地+可删除是行业被迫收敛到的底线——这正是我们 P0④ 的设计依据；②所有产品记的是“屏幕/数字生活”，没有人在做“物理现实”的记忆——赛道空档明确；③Limitless 之死证明：绑定单一可被收购的云厂商的 lifelog 是脆弱的，本地优先+数据可携带是差异化卖点。**

---

## C. 家庭耗材/库存管理

### C1. Amazon Dash Button / Dash Replenishment（已死）

- Dash Button（2015–2019.2 停售）死因复盘：①亚马逊副总裁 Daniel Rausch 承认“一个家庭需要 500 个按钮”，方案不实用；②虚拟按钮/Alexa 语音/Subscribe & Save/DRS 让它过时；③用户痛点：价格下单后才知道且会变、误触（小孩按 50 次=50 单）、一年一换电池、背胶易掉——“本该让购物消失，却持续消耗注意力”；④京东“来点”同类产品历史销量平均只有两位数。来源：https://www.failory.com/amazon/dash-buttons ；https://kknews.cc/zh-tw/tech/zby64za.html ；https://museumoffailure.com/exhibition/amazon-dash-button
- Dash Replenishment（家电自动补货 SDK）随惠而浦/LG/三星合作无疾而终，未形成规模。

### C2. 智能冰箱摄像头

- **Samsung Family Hub / AI Vision Inside**：三星官方脚注承认截至 2025.4 **只能识别 37 种食物**（2024.3 为 33 种），且**无法识别冰箱门架和冷冻室的物品**；第三方评测估计识别正确率约 60%，Engadget 2026.1 评测把“limited AI food recognition”列为缺点；智能溢价 $800+；社区论坛大量“Error 41/图像识别失败”投诉。来源：https://news.samsung.com/us/tag/bespoke/feed/ ；https://www.smarthomeexplorer.com/reviews/ecosystem/samsung-family-hub-fridge ；https://www.engadget.com/home/kitchen-tech/samsung-bespoke-fridge-with-ai-review-all-the-bells-and-whistles-140000099.html ；https://eu.community.samsung.com/t5/home-appliances/inside-fridge-picture-not-working/td-p/1920720
- **FridgeCam by Smarter**：后装冰箱摄像头，用户评价“unboxing disappointment and false promises”；配网仅支持 2.4GHz、连接问题多发；识别依赖手动扫条码。来源：https://climbing-moss.com/2018/08/23/fridgecam-unboxing-disappointment-and-false-promises/ ；https://smarterhelp.zendesk.com/hc/en-us/articles/360001264825

### C3. 库存管理 App 的留存问题

- 品类通病：**录入靠自律，出库永不发生**。“前置性全量手动录入是人们放弃 pantry app 的首要原因”（Fango）；“大多数人一周内停止更新”（MealThinker 对 SuperCook 类手动清单的实测结论）；条码扫描“扫进去容易，用掉半罐豆子时没人记得扫出来”，库存数周内失真；**Plan to Eat 官方直接砍掉了 pantry 功能**，理由是“数字库存与真实厨房永远无法同步，该功能制造的挫败感大于价值”。来源：https://fango.fi/en/blog/best-pantry-inventory-app/ ；https://mealthinker.com/blog/meal-planning-app-pantry-tracking

**判断：需求为真（WRAP 估英国家庭年均浪费 £1,000 食物；Dash 最畅销的恰是洗衣液/卫生纸等耗材），但过去十年三条路线——实体按钮、冰箱摄像头、手动 App——全部失败或半死不活。共性死因是“把感知成本转嫁给人”。谁能做到“免录入、被动感知余量”，谁就解开了这个品类死结。注意反面信号：失败过多也可能意味着付费意愿弱，建议以“提醒价值”而非“自动下单”切入。**

---

## D. 语音记录/口头笔记

### D1. 专用 AI 录音硬件与软件

- **Plaud Note / NotePin**：硬件口碑好（30h 续航、MagSafe、112 语言），但痛点集中：无屏幕看不到录制状态、触控手势不稳定（误录/想录录不上）、同步失败、订阅叠加、大房间/嘈杂环境转写下滑。来源：https://tldv.io/blog/plaud-notepin-review/ ；https://www.dapperandgroomed.com/blog/plaud-note-review-this-ai-powered-voice-recorder-might-change-the-way-you-work
- **Limitless Pendant**：$99、首日预售破万单验证需求；2025.12 被 Meta 收购停售（见 B2）。另 Amazon 2025.7 收购同类 Bee——品类被巨头收割中。
- **Otter.ai**：企业场景被批“重大隐私与安全风险”——拿到 M365/Google Workspace 权限后自动嵌入并录制任何会议。来源：https://mightygadget.com/plaud-note-pro-review/

### D2. 为什么用户不直接用 Siri/Alexa 记？

- 经典语音助手是“命令-响应”模式、极其脆弱：“换一种说法问同一件事就可能没有结果，且对话之间毫无连续性”（Karten Network 对 Alexa 的定性）；Siri 听错专有名词约 30%（yougot.ai 实测）；Alexa 提醒默认只在 Echo 设备上响、不跟人走；系统语音备忘录没有调度，“你得记得去回放，这就违背了初衷”。
- 更关键的是**没有结构化沉淀**：对 Siri/Alexa 说“记住我对花生过敏”不会进入任何可检索、可执行的偏好库（Alexa 早年有过 “Remember This” 功能，体验不稳定且被边缘化；Alexa+ 直到 2025.2 才补上持久偏好记忆，但代价是全云端处理+订阅）。
- 来源：https://karten-network.org.uk/newsletter-article-category/update-from-mobile-technology-advisor/ ；https://www.yougot.ai/blog/technology/app-comparisons/reminder-app-with-voice-input

**判断：真需求且已被付费验证（Plaud 出货、Limitless 首日万单），但主战场是“会议/对话转写”，**“随口说一句偏好/任务并被长期结构化记住”这个子场景服务薄弱**——巨头助手不可靠且无沉淀，专用硬件重会议轻生活。同事可深挖 Plaud/Limitless；我们注意差异化在“生活化口头记忆”而非会议记录。**

---

## 总结：机会窗口排序

| 场景 | 现有方案强度 | 需求验证 | 机会窗口 |
|---|---|---|---|
| ①找物（未挂标签物品） | **最弱——消费级市场无方案**：追踪器只管挂签物品；Meta 眼镜要主动下指令且只记一次；机器人路线失败 | 强（Tile/AirTag 十年付费市场；Meta 把该功能当发布会主打） | **最大** |
| ②耗材余量 | 极弱——三条路线全灭（Dash 停售、冰箱摄像头识别率~60%/仅 37 种、App 靠自律高流失） | 需求真实但付费意愿存疑（多次商业化失败） | **大，但需警惕“伪付费”信号**；共性死因“感知成本转嫁给人”正是我们被动采集的解题点 |
| ③口头偏好/任务 | 中——Plaud/Limitless 验证付费但重会议；Siri/Alexa 不可靠无沉淀；Alexa+ 刚起步 | 中强（硬件预售验证） | 中等，差异化在“生活记忆”而非会议 |
| ④隐私可控采集/删除 | 行业被迫收敛到 opt-in+本地+可删除（Recall 翻车一年、Limitless 收购停服、AirTag 诉讼） | — | **不是独立场景而是准入门槛+信任差异化**，本地优先+可删除+数据可携带应作为核心卖点 |

**结论：机会窗口最大的是①找物——它是唯一“有强付费证据、且现有方案在物理形态上根本无法覆盖主场景（未挂标签物品）”的赛道；②耗材是第二窗口，所有先行者死于“让人干活”，我们的眼镜+戒指被动采集恰好消除该成本，但应吸取 Dash 的教训：做“提醒”而非“自动下单”，做“少数高价值耗材”而非“全家 500 件物品”。**
