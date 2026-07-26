import { useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  BriefcaseBusiness,
  Check,
  ChevronRight,
  Clock3,
  Droplets,
  Filter,
  HeartPulse,
  House,
  MapPin,
  Mic,
  Network,
  Plane,
  Search,
  ShieldCheck,
  Shirt,
  Sparkles,
  Target,
  Users,
  Utensils,
  WandSparkles,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import "./MemoryOverview.css";

const INVENTORY = "/assets/pico/inventory/items";
const WARDROBE = "/assets/pico/wardrobe/items";

const wardrobeObjects = [
  {
    id: "style-hoodie",
    name: "蓝色连帽衫",
    image: `${WARDROBE}/blue-hoodie.png`,
    category: "上装",
    location: "衣柜上层左侧",
    state: "已收纳",
    seen: "昨天 21:42",
    confidence: "较可信 · 92%",
    summary: "系统从多次穿着与收纳片段中形成了这件衣物的稳定主线。",
    timeline: [
      ["昨天", "回到衣柜上层", "晚间收纳片段中再次确认位置。"],
      ["7 月 23 日", "穿着外出", "和黑色长裤一起出现，形成一次搭配记录。"],
      ["7 月 18 日", "首次形成实体", "来自衣柜整理时的连续观察。"],
    ],
  },
  {
    id: "style-shirt",
    name: "白色衬衫",
    image: `${WARDROBE}/white-shirt.png`,
    category: "上装",
    location: "衣柜中层",
    state: "最近穿过",
    seen: "7 月 24 日",
    confidence: "可信 · 95%",
    summary: "最近一次在工作日穿着，系统已记录常见搭配和收纳位置。",
    timeline: [
      ["7 月 24 日", "工作日穿着", "与黑色长裤共同出现。"],
      ["7 月 20 日", "收回衣柜中层", "位置得到再次确认。"],
    ],
  },
  {
    id: "style-knit",
    name: "黑色针织衫",
    image: `${WARDROBE}/black-knit.png`,
    category: "上装",
    location: "衣柜上层右侧",
    state: "已收纳",
    seen: "7 月 22 日",
    confidence: "较可信 · 89%",
    summary: "系统已识别两次穿着记录，当前收纳位置较稳定。",
    timeline: [
      ["7 月 22 日", "收纳位置更新", "从床边移动回衣柜。"],
      ["7 月 12 日", "首次穿着确认", "形成衣物实体主线。"],
    ],
  },
  {
    id: "style-skirt",
    name: "驼色半裙",
    image: `${WARDROBE}/camel-skirt.png`,
    category: "下装",
    location: "衣柜下层",
    state: "两周未穿",
    seen: "7 月 10 日",
    confidence: "一般 · 82%",
    summary: "这件衣物的当前位置可能已经陈旧，需要下一次观察更新。",
    timeline: [
      ["7 月 10 日", "收纳于衣柜下层", "最后一次可靠位置观察。"],
      ["6 月 29 日", "与米色开衫搭配", "形成一条搭配记录。"],
    ],
  },
  {
    id: "style-jeans",
    name: "靛蓝牛仔裤",
    image: `${WARDROBE}/indigo-jeans.png`,
    category: "下装",
    location: "衣柜下层右侧",
    state: "高频穿着",
    seen: "今天 08:06",
    confidence: "可信 · 96%",
    summary: "近两周出现频率较高，系统将它识别为常用下装。",
    timeline: [
      ["今天", "穿着出门", "与蓝色连帽衫共同出现。"],
      ["7 月 21 日", "清洗后重新收纳", "状态从待清洗更新为已收纳。"],
    ],
  },
  {
    id: "style-cardigan",
    name: "米色开衫",
    image: `${WARDROBE}/beige-cardigan.png`,
    category: "上装",
    location: "衣柜中层左侧",
    state: "已收纳",
    seen: "7 月 20 日",
    confidence: "较可信 · 90%",
    summary: "系统记录了三次搭配，当前常与白色衬衫共同出现。",
    timeline: [
      ["7 月 20 日", "位置得到确认", "回到衣柜中层左侧。"],
      ["7 月 15 日", "与白色衬衫搭配", "形成新的搭配关系。"],
    ],
  },
];

const careObjects = [
  {
    id: "care-serum",
    name: "舒缓精华液",
    image: `${INVENTORY}/serum.png`,
    category: "护肤",
    location: "卧室梳妆台",
    state: "余量约三成",
    seen: "今天 07:46",
    confidence: "较可信 · 91%",
    summary: "系统根据瓶身状态和近两周使用频率估算当前余量。",
    timeline: [
      ["今天", "晨间使用", "余量状态继续下降。"],
      ["7 月 18 日", "余量约一半", "来自梳妆台前的连续观察。"],
    ],
  },
  {
    id: "care-cream",
    name: "保湿面霜",
    image: `${INVENTORY}/face-cream.png`,
    category: "护肤",
    location: "卧室梳妆台",
    state: "已开封",
    seen: "昨天 22:31",
    confidence: "可信 · 94%",
    summary: "面霜处于稳定使用中，预计还能使用 12 到 18 天。",
    timeline: [
      ["昨天", "晚间使用", "再次确认已开封状态。"],
      ["7 月 9 日", "首次开封", "开始建立使用进度。"],
    ],
  },
  {
    id: "care-sunscreen",
    name: "日常防晒霜",
    image: `${INVENTORY}/sunscreen.png`,
    category: "护肤",
    location: "玄关随身包",
    state: "接近用完",
    seen: "今天 08:04",
    confidence: "较可信 · 89%",
    summary: "防晒霜余量偏低，但尚未加入采购清单。",
    timeline: [
      ["今天", "随身带出", "位于玄关随身包。"],
      ["7 月 21 日", "余量偏低", "形成补充候选。"],
    ],
  },
  {
    id: "care-perfume",
    name: "木质调香水",
    image: `${INVENTORY}/perfume.png`,
    category: "香氛",
    location: "衣柜内侧",
    state: "低频使用",
    seen: "上周四",
    confidence: "一般 · 84%",
    summary: "近期使用频率较低，系统已形成偏好但不会自动补货。",
    timeline: [
      ["上周四", "出门前使用", "与正式穿搭共同出现。"],
      ["6 月 30 日", "位置确认", "收纳在衣柜内侧。"],
    ],
  },
];

const DOMAINS = [
  {
    key: "food",
    title: "饮食",
    count: 28,
    tone: "#5bd993",
    icon: Utensils,
    subtitle: "口味、餐食、饮品与厨房余量",
    summary: "口味、餐食、饮品和厨房状态在这里连接，而不是被拆成互不相关的列表。",
    tags: ["偏好 7", "物品状态 8", "计划 4"],
    images: [`${INVENTORY}/water-bottle.png`],
    layout: { left: "0%", top: "0%", width: "54%", height: "34%" },
    objects: [
      {
        id: "food-cup",
        name: "常用水杯",
        image: `${INVENTORY}/water-bottle.png`,
        category: "饮品",
        location: "书房工作桌",
        state: "正在使用",
        seen: "今天 10:04",
        confidence: "较可信 · 91%",
        summary: "这是饮食领域中高频出现的饮水物品。",
        timeline: [
          ["今天", "移动到书房工作桌", "从厨房移动至电脑右侧。"],
          ["昨天", "清洗后回到厨房", "形成一次状态变化。"],
        ],
      },
    ],
    patterns: [
      ["不喜欢这家胡辣汤", "今天午餐时明确表达，来自主动语音。", "偏好"],
      ["饮品通常选择少糖", "近 7 次选择中有 6 次为少糖。", "习惯"],
    ],
    plans: [["本周少喝含糖饮料", "已完成 3 天，共计划 5 天。", 60]],
  },
  {
    key: "work",
    title: "工作与学习",
    count: 23,
    tone: "#71aef4",
    icon: BriefcaseBusiness,
    subtitle: "任务、知识、设备与阅读进度",
    summary: "任务、会议知识、设备状态和学习进度沿着同一条工作学习主线组织。",
    tags: ["任务 8", "知识 7", "进度 5"],
    images: [`${INVENTORY}/laptop.png`, `${INVENTORY}/headphones.png`],
    layout: { left: "54%", top: "0%", width: "46%", height: "34%" },
    objects: [
      {
        id: "work-laptop",
        name: "笔记本电脑",
        image: `${INVENTORY}/laptop.png`,
        category: "设备",
        location: "书房工作桌",
        state: "高频使用",
        seen: "今天 09:10",
        confidence: "可信 · 96%",
        summary: "核心工作设备，连接会议、任务和多个专注片段。",
        timeline: [
          ["今天", "开始工作片段", "位于书房工作桌。"],
          ["昨天", "结束阅读片段", "和耳机共同出现。"],
        ],
      },
    ],
    patterns: [["晚上更容易持续阅读", "近三周主要发生在 21 点之后。", "习惯"]],
    plans: [["整理会议结论", "已完成 2 项，共 5 项。", 40]],
  },
  {
    key: "home",
    title: "居住",
    count: 18,
    tone: "#f0c85e",
    icon: House,
    subtitle: "空间、家居物品、设备与家庭耗材",
    summary: "空间、家居物品、家庭耗材和智能设备状态共同构成居住记忆。",
    tags: ["位置 9", "设备 3", "耗材 3"],
    images: [`${INVENTORY}/keys.png`, `${INVENTORY}/phone.png`],
    layout: { left: "0%", top: "34%", width: "32%", height: "34%" },
    objects: [
      {
        id: "home-keys",
        name: "家门钥匙",
        image: `${INVENTORY}/keys.png`,
        category: "玄关",
        location: "玄关托盘",
        state: "已放回",
        seen: "今天 08:12",
        confidence: "可信 · 94%",
        summary: "钥匙的当前位置和移动轨迹已经形成稳定记忆。",
        timeline: [
          ["今天", "放回玄关托盘", "结束出门活动后再次确认。"],
          ["昨天", "随身离开家", "位置状态更新为随身。"],
        ],
      },
    ],
    patterns: [
      ["更常在书房工作", "近 14 天的专注片段主要来自书房。", "习惯"],
      ["客厅灯通常在回家后开启", "来自智能家居事件，只作为生活模式。", "模式"],
    ],
    plans: [["重新整理玄关收纳", "尚未开始。", 0]],
  },
  {
    key: "care",
    title: "个护与美妆",
    count: 14,
    tone: "#ef91c7",
    icon: Droplets,
    subtitle: "护肤、彩妆、香氛与个人日化",
    summary: "护肤、彩妆、香氛、洗护和个人日化用品按使用与消耗状态形成个人护理记忆。",
    tags: ["余量 5", "偏好 4", "计划 2"],
    images: [`${INVENTORY}/serum.png`, `${INVENTORY}/face-cream.png`],
    layout: { left: "32%", top: "34%", width: "37%", height: "34%" },
    objects: careObjects,
    patterns: [
      ["更偏好清爽质地", "来自三次明确表达。", "偏好"],
      ["晚间护肤步骤较稳定", "近两周出现 9 次相同顺序。", "习惯"],
    ],
    plans: [["补充日常防晒霜", "尚未加入采购清单。", 0]],
  },
  {
    key: "style",
    title: "穿搭",
    count: 11,
    tone: "#a998ed",
    icon: Shirt,
    subtitle: "衣物、风格与搭配",
    summary: "衣物与配饰是实体，风格偏好、搭配习惯和购买计划附着在穿搭领域里。",
    tags: ["衣物 6", "偏好 3", "计划 1"],
    images: [`${WARDROBE}/blue-hoodie.png`, `${WARDROBE}/camel-skirt.png`],
    layout: { left: "69%", top: "34%", width: "31%", height: "34%" },
    objects: wardrobeObjects,
    patterns: [["更喜欢宽松剪裁", "来自三次明确选择。", "偏好"]],
    plans: [["补一件轻薄外套", "还未加入采购清单。", 0]],
  },
  {
    key: "relations",
    title: "人际关系",
    count: 16,
    tone: "#f38e84",
    icon: Users,
    subtitle: "人物、关系与共同经历",
    summary: "人物关系、共同经历、对方偏好和仍需兑现的约定在这里汇合。",
    tags: ["人物 7", "偏好 4", "约定 3"],
    images: [`${INVENTORY}/phone.png`, `${INVENTORY}/perfume.png`],
    layout: { left: "0%", top: "68%", width: "30%", height: "32%" },
    objects: [],
    patterns: [
      ["妈妈偏爱茉莉花茶", "两次家庭对话均有明确表达。", "对方偏好"],
      ["林然负责设计对接", "来自两次会议中的明确提及。", "关系"],
    ],
    plans: [["周末给妈妈带茶叶", "尚未完成。", 0]],
  },
  {
    key: "health",
    title: "健康与身体",
    count: 9,
    tone: "#ef7c8a",
    icon: HeartPulse,
    subtitle: "身体状态、睡眠与目标",
    summary: "身体数据、睡眠、运动和健康目标形成趋势，不逐条堆叠传感器读数。",
    tags: ["状态 3", "习惯 2", "计划 3"],
    images: [`${INVENTORY}/smartwatch.png`, `${INVENTORY}/water-bottle.png`],
    layout: { left: "30%", top: "68%", width: "22%", height: "32%" },
    objects: [
      {
        id: "health-watch",
        name: "智能手表",
        image: `${INVENTORY}/smartwatch.png`,
        category: "设备",
        location: "左手腕",
        state: "持续同步",
        seen: "刚刚",
        confidence: "可信 · 97%",
        summary: "用于形成心率、睡眠和运动趋势，不把每条原始读数沉淀为记忆。",
        timeline: [
          ["今天", "同步静息心率", "过去 7 天平均 68 次/分钟。"],
          ["昨晚", "同步睡眠记录", "睡眠 7 小时 12 分。"],
        ],
      },
    ],
    patterns: [["更常在晚饭后散步", "近两周出现 6 次。", "习惯"]],
    plans: [["本周完成 3 次运动", "已完成 2 次。", 67]],
  },
  {
    key: "travel",
    title: "出行",
    count: 6,
    tone: "#69d7dc",
    icon: Plane,
    subtitle: "行程、路线与随身物品",
    summary: "行程、路线、随身物品和出门任务共同形成出行上下文。",
    tags: ["物品 2", "行程 3"],
    images: [`${INVENTORY}/passport.png`, `${INVENTORY}/umbrella.png`],
    layout: { left: "52%", top: "68%", width: "20%", height: "32%" },
    objects: [
      {
        id: "travel-passport",
        name: "护照",
        image: `${INVENTORY}/passport.png`,
        category: "证件",
        location: "书房抽屉",
        state: "已收纳",
        seen: "上周五",
        confidence: "较可信 · 88%",
        summary: "护照与签证材料任务处于同一个出行上下文。",
        timeline: [
          ["上周五", "位置得到确认", "位于书房抽屉内。"],
          ["7 月 3 日", "被取出使用", "和签证材料共同出现。"],
        ],
      },
    ],
    patterns: [["工作日通常乘地铁通勤", "近 10 次出行中出现 8 次。", "习惯"]],
    plans: [["周五前确认签证材料", "两项材料仍待确认。", 50]],
  },
  {
    key: "leisure",
    title: "兴趣与休闲",
    count: 5,
    tone: "#e8a86c",
    icon: WandSparkles,
    subtitle: "音乐、娱乐与个人项目",
    summary: "音乐、娱乐、爱好物品和个人项目保留在一个可继续生长的休闲领域。",
    tags: ["物品 2", "偏好 1", "计划 1"],
    images: [`${INVENTORY}/headphones.png`, `${INVENTORY}/phone.png`],
    layout: { left: "72%", top: "68%", width: "28%", height: "32%" },
    objects: [
      {
        id: "leisure-headphones",
        name: "降噪耳机",
        image: `${INVENTORY}/headphones.png`,
        category: "音乐",
        location: "书房桌面",
        state: "高频使用",
        seen: "昨天 22:40",
        confidence: "可信 · 95%",
        summary: "工作与休闲片段中都经常出现，当前位置较稳定。",
        timeline: [["昨天", "结束听歌", "留在书房桌面。"]],
      },
    ],
    patterns: [["工作时更常听纯音乐", "近 5 次专注片段中出现 4 次。", "偏好"]],
    plans: [["完成当前拼图", "大约完成三分之一。", 35]],
  },
];

function DomainTile({ domain, dimmed, onOpen }) {
  const Icon = domain.icon;
  return (
    <motion.button
      type="button"
      className={`memory-domain-tile memory-domain-${domain.key} ${dimmed ? "is-dimmed" : ""}`}
      style={{ ...domain.layout, "--domain-tone": domain.tone }}
      onClick={() => onOpen(domain.key)}
      whileTap={{ scale: 0.985 }}
      aria-label={`查看${domain.title}记忆`}
    >
      <span className="memory-domain-body">
        <span className="memory-domain-heading">
          <span className="memory-domain-name"><Icon size={14} /><b>{domain.title}</b></span>
          <em>{domain.count} 条</em>
        </span>
        <span className="memory-domain-subtitle">{domain.subtitle}</span>
        <span className="memory-domain-tags">
          {domain.tags.slice(0, 3).map((tag) => <i key={tag}>{tag}</i>)}
        </span>
        <span className="memory-domain-cutouts" aria-hidden="true">
          {domain.images.map((image, index) => (
            <img key={image} src={image} alt="" style={{ "--cutout-index": index }} />
          ))}
        </span>
      </span>
    </motion.button>
  );
}

function MemoryRow({ item, type }) {
  const Icon = type === "plan" ? Target : Sparkles;
  return (
    <article className="memory-fact-row">
      <span className="memory-fact-icon"><Icon size={17} /></span>
      <span className="memory-fact-copy">
        <b>{item[0]}</b>
        <small>{item[1]}</small>
        {type === "plan" && (
          <span className="memory-plan-track" aria-label={`完成 ${item[2]}%`}>
            <i style={{ width: `${item[2]}%` }}></i>
          </span>
        )}
      </span>
      <em>{type === "plan" ? `${item[2]}%` : item[2]}</em>
    </article>
  );
}

function ObjectLibrary({ domain, onOpen }) {
  const [filterOpen, setFilterOpen] = useState(false);
  const [category, setCategory] = useState("全部");
  const categories = ["全部", ...new Set(domain.objects.map((item) => item.category))];
  const objects = category === "全部"
    ? domain.objects
    : domain.objects.filter((item) => item.category === category);

  return (
    <section className="memory-library">
      <div className="memory-section-heading">
        <div>
          <h3>AI 已记住的物品</h3>
          <p>{domain.objects.length ? "按最近更新排列" : "这个领域目前以人物与关系记忆为主"}</p>
        </div>
        {categories.length > 1 && (
          <button
            type="button"
            className={`memory-filter-button ${filterOpen ? "active" : ""}`}
            onClick={() => setFilterOpen((value) => !value)}
            aria-label="筛选物品"
            aria-expanded={filterOpen}
          >
            <Filter size={16} />
          </button>
        )}
      </div>

      <AnimatePresence initial={false}>
        {filterOpen && (
          <motion.div
            className="memory-category-filter"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
          >
            {categories.map((item) => (
              <button
                key={item}
                type="button"
                className={item === category ? "active" : ""}
                onClick={() => { setCategory(item); setFilterOpen(false); }}
              >
                {item}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      {objects.length ? (
        <div className="memory-object-grid">
          {objects.map((item) => (
            <button key={item.id} type="button" className="memory-object-card" onClick={() => onOpen(item)}>
              <span className="memory-object-image"><img src={item.image} alt="" /></span>
              <span>
                <small>{item.category}</small>
                <b>{item.name}</b>
                <em>{item.state}</em>
              </span>
              <ChevronRight size={15} />
            </button>
          ))}
        </div>
      ) : (
        <div className="memory-empty-library">
          <Users size={24} />
          <b>这里没有需要归入物品库的实体</b>
          <p>人物、关系、对方偏好和共同约定会在另外两个视图中持续更新。</p>
        </div>
      )}
    </section>
  );
}

function DomainView({ domain, onBack, onOpenObject }) {
  const [tab, setTab] = useState("objects");
  const tabs = [
    ["objects", `物品库 ${domain.objects.length}`],
    ["patterns", `偏好习惯 ${domain.patterns.length}`],
    ["plans", `计划进度 ${domain.plans.length}`],
  ];

  return (
    <motion.div
      className="memory-domain-page"
      style={{ "--domain-tone": domain.tone }}
      initial={{ opacity: 0, x: 16 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 16 }}
    >
      <div className="memory-domain-topline">
        <button type="button" onClick={onBack} aria-label="返回全览"><ArrowLeft size={18} /></button>
        <span>领域记忆</span>
      </div>
      <header className="memory-domain-header">
        <small>{domain.count} 条有效记忆</small>
        <h2>{domain.title}</h2>
        <p>{domain.summary}</p>
      </header>

      <div className="memory-domain-tabs" role="tablist" aria-label={`${domain.title}记忆视图`}>
        {tabs.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? "active" : ""}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="memory-domain-content">
        {tab === "objects" && <ObjectLibrary domain={domain} onOpen={onOpenObject} />}
        {tab === "patterns" && (
          <section className="memory-fact-section">
            <div className="memory-section-heading">
              <div><h3>偏好与习惯</h3><p>明确表达和稳定重复的生活模式</p></div>
            </div>
            {domain.patterns.map((item) => <MemoryRow key={item[0]} item={item} type="pattern" />)}
          </section>
        )}
        {tab === "plans" && (
          <section className="memory-fact-section">
            <div className="memory-section-heading">
              <div><h3>计划与进度</h3><p>任务、目标与当前进展共用一条主线</p></div>
            </div>
            {domain.plans.map((item) => <MemoryRow key={item[0]} item={item} type="plan" />)}
          </section>
        )}
      </div>
    </motion.div>
  );
}

function ObjectDetail({ item, onClose }) {
  return (
    <motion.section
      className="memory-object-detail"
      initial={{ opacity: 0, y: 26 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 26 }}
      aria-label={`${item.name}详情`}
    >
      <div className="memory-detail-topline">
        <button type="button" onClick={onClose} aria-label="返回领域"><ArrowLeft size={18} /></button>
        <span>物品记忆</span>
        <button type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
      </div>
      <div className="memory-detail-scroll">
        <div className="memory-detail-hero">
          <img src={item.image} alt="" />
        </div>
        <header className="memory-detail-header">
          <small>AI 主动形成的物品记忆</small>
          <h2>{item.name}</h2>
          <p>{item.summary}</p>
        </header>
        <div className="memory-object-status">
          <div><MapPin size={15} /><span>最后位置</span><b>{item.location}</b></div>
          <div><Check size={15} /><span>最近状态</span><b>{item.state}</b></div>
          <div><Clock3 size={15} /><span>最后确认</span><b>{item.seen}</b></div>
          <div><ShieldCheck size={15} /><span>可信状态</span><b>{item.confidence}</b></div>
        </div>
        <section className="memory-detail-timeline">
          <h3>状态变更轨迹</h3>
          {item.timeline.map(([time, title, detail]) => (
            <article key={`${time}-${title}`}>
              <i></i>
              <time>{time}</time>
              <b>{title}</b>
              <p>{detail}</p>
            </article>
          ))}
        </section>
      </div>
    </motion.section>
  );
}

export default function MemoryOverview() {
  const navigate = useNavigate();
  const [activeDomain, setActiveDomain] = useState(null);
  const [selectedObject, setSelectedObject] = useState(null);
  const [query, setQuery] = useState("");
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef(null);

  const domain = DOMAINS.find((item) => item.key === activeDomain);
  const normalizedQuery = query.trim().toLocaleLowerCase("zh-CN");
  const matches = useMemo(() => {
    if (!normalizedQuery) return new Set(DOMAINS.map((item) => item.key));
    return new Set(DOMAINS.filter((item) => {
      const searchable = [
        item.title,
        item.subtitle,
        item.summary,
        ...item.tags,
        ...item.objects.map((object) => object.name),
        ...item.patterns.flat(),
        ...item.plans.flat(),
      ].join(" ").toLocaleLowerCase("zh-CN");
      return searchable.includes(normalizedQuery);
    }).map((item) => item.key));
  }, [normalizedQuery]);

  const startVoiceSearch = () => {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) return;
    const recognition = new Recognition();
    recognition.lang = "zh-CN";
    recognition.interimResults = true;
    recognition.continuous = false;
    recognition.onstart = () => setListening(true);
    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results).map((result) => result[0].transcript).join("");
      setQuery(transcript);
    };
    recognitionRef.current = recognition;
    recognition.start();
  };

  return (
    <div className="page-view memory-overview-page">
      <AnimatePresence mode="wait">
        {!domain ? (
          <motion.div
            key="overview"
            className="memory-overview-scroll"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <header className="memory-overview-header">
              <div><h1>全览</h1><p>记忆在生活中的分布</p></div>
              <div className="memory-overview-actions">
                <span><i></i>刚刚更新</span>
                <button
                  type="button"
                  onClick={() => navigate("/galaxy/relations")}
                  aria-label="查看关系洞察"
                  title="关系洞察"
                >
                  <Network size={17} />
                </button>
              </div>
            </header>

            <label className="memory-overview-search">
              <Search size={18} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索物品、人物或一件事"
                aria-label="搜索现实记忆"
              />
              {query && (
                <button type="button" className="memory-search-clear" onClick={() => setQuery("")} aria-label="清除搜索">
                  <X size={14} />
                </button>
              )}
              <button
                type="button"
                className={`memory-search-mic ${listening ? "active" : ""}`}
                onClick={startVoiceSearch}
                aria-label="语音搜索"
                title={window.SpeechRecognition || window.webkitSpeechRecognition ? "语音搜索" : "当前浏览器不支持语音搜索"}
              >
                <Mic size={16} />
              </button>
            </label>

            <div className="memory-overview-meta">
              <span><b>130 条有效记忆</b> · 9 个生活领域</span>
              <span>近 90 天</span>
            </div>

            <section className="memory-domain-map" aria-label="按有效记忆量显示的生活领域">
              {DOMAINS.map((item) => (
                <DomainTile
                  key={item.key}
                  domain={item}
                  dimmed={!matches.has(item.key)}
                  onOpen={setActiveDomain}
                />
              ))}
              {matches.size === 0 && (
                <div className="memory-search-empty">
                  <Search size={20} />
                  <span>还没有找到与“{query}”相关的记忆</span>
                </div>
              )}
            </section>
            <p className="memory-distribution-note">面积代表已形成的有效记忆量，不代表领域的重要程度。</p>
          </motion.div>
        ) : (
          <DomainView
            key={domain.key}
            domain={domain}
            onBack={() => setActiveDomain(null)}
            onOpenObject={setSelectedObject}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {selectedObject && <ObjectDetail item={selectedObject} onClose={() => setSelectedObject(null)} />}
      </AnimatePresence>
    </div>
  );
}
