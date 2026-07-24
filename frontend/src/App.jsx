import { useEffect, useMemo, useRef, useState } from "react";
import { Home, History, Search, Mic, UserRound, ArrowDown, ChevronLeft, Cast } from "lucide-react";
import LiveView from "./LiveView";
import { whereIs } from "./api";

const rooms = ["客厅", "书房", "卧室", "玄关", "卫生间"];

const itemSeeds = [
  ["charger", "充电器", "客厅", "工作桌下方", "今天 10:18", "电源与线材"],
  ["cup", "水杯", "书房", "工作桌右侧", "今天 10:04", "日常用品"],
  ["remote", "遥控器", "客厅", "沙发右侧", "昨晚 22:31", "影音设备"],
  ["tissue", "纸巾盒", "客厅", "茶几上", "今天 08:40", "日常用品"],
  ["controller", "游戏手柄", "客厅", "电视柜第二层", "周三 21:16", "影音设备"],
  ["headphones", "耳机", "书房", "显示器旁", "今天 09:12", "数码设备"],
  ["laptop", "笔记本电脑", "书房", "工作桌中央", "今天 10:21", "数码设备"],
  ["mouse", "鼠标", "书房", "工作桌右侧", "今天 10:21", "数码设备"],
  ["keyboard", "键盘", "书房", "工作桌中央", "今天 10:21", "数码设备"],
  ["book", "《设计中的设计》", "书房", "书架第二层", "昨晚 23:08", "书籍"],
  ["pen", "钢笔", "书房", "笔筒里", "周四 18:02", "文具"],
  ["drive", "移动硬盘", "书房", "左侧抽屉", "周二 20:45", "数码设备"],
  ["watch", "手表", "卧室", "床头柜上", "今天 07:48", "随身物品"],
  ["glasses", "眼镜", "卧室", "床头柜上", "今天 07:51", "随身物品"],
  ["perfume", "香水", "卧室", "衣柜内侧", "周四 08:26", "日常用品"],
  ["wallet", "钱包", "玄关", "托盘左侧", "今天 08:12", "随身物品"],
  ["cable", "数据线", "卧室", "床头柜抽屉", "周一 23:20", "电源与线材"],
  ["keys", "钥匙", "玄关", "玄关托盘", "今天 08:12", "随身物品"],
  ["umbrella", "雨伞", "玄关", "入户门右侧", "周四 19:03", "日常用品"],
  ["access", "门禁卡", "玄关", "钱包夹层", "今天 08:12", "随身物品"],
  ["backpack", "背包", "玄关", "换鞋凳旁", "今天 08:15", "随身物品"],
  ["scissors", "剪刀", "书房", "工具抽屉", "周三 16:44", "工具"],
  ["medicine", "药盒", "卧室", "床头柜第二层", "周四 22:00", "健康用品"],
];

const items = itemSeeds.map(([id, name, room, location, seen, category], index) => ({
  id, name, room, location, seen, category, index,
  events: id === "charger" ? [
    { time: "08:42", title: "在工作桌上", note: "当天第一次形成稳定的位置记忆。" },
    { time: "10:16", title: "可能正在移动", note: "前后观察发生变化，系统暂不把推断当成事实。" },
    { time: "10:18", title: "掉到工作桌下方", note: "再次被看见后，位置变化得到确认。" },
    { time: "现在", title: "仍在工作桌下方", note: "此后没有发现新的位置变化。" },
  ] : [
    { time: "上周", title: `在${room}被记住`, note: "这是当前保留的最早位置节点。" },
    { time: seen.split(" ")[0], title: `在${location}被看见`, note: "位置由一次清晰观察更新。" },
    { time: "现在", title: `仍在${location}`, note: "此后没有发现新的位置变化。" },
  ],
}));

const memories = [
  ["任务", "快递今天早上已送到门口", "待取回"], ["任务", "明天下午取干洗", "明天 15:00"],
  ["任务", "周五前归还图书", "本周五"], ["偏好", "晚上十点后不主动提醒", "已生效"],
  ["偏好", "咖啡不加糖", "常用偏好"], ["偏好", "工作时减少非必要通知", "已生效"],
  ["进度", "《设计中的设计》读到第 86 页", "昨晚更新"], ["生活", "最近一次给植物浇水是周三", "周三 19:20"],
  ["生活", "上次倒垃圾是在今天早上 10:24", "今天"],
];

const nav = [
  { id: "now", label: "现在", Icon: Home },
  { id: "rewind", label: "回拨", Icon: History },
  { id: "ask", label: "询问", Icon: Search },
  { id: "live", label: "联调", Icon: Cast },
];

function Placeholder({ label, item, compact = false }) {
  return (
    <div className={`placeholder ${compact ? "compact" : ""}`} aria-label={`${label}${item ? `：${item}` : ""}`}>
      <span className="object-silhouette" aria-hidden="true" />
      <small>{label}</small>
      {item && <strong>{item}</strong>}
    </div>
  );
}

function Header({ paused, setPaused, navigate, toast }) {
  const [recordOpen, setRecordOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const secondary = [["all", "所有"], ["memory", "记忆"], ["devices", "设备"], ["privacy", "隐私"], ["open", "开放能力"]];
  const go = (id) => { navigate(id); setProfileOpen(false); setRecordOpen(false); };
  return (
    <header className="topbar">
      <button className="wordmark" onClick={() => go("now")}>Reality Memory</button>
      <div className="home-name">我的家</div>
      <div className="top-actions">
        <button className={`record-link ${paused ? "paused" : ""}`} onClick={() => { setRecordOpen(!recordOpen); setProfileOpen(false); }}>
          <i />{paused ? "暂停中" : "记录中"}
        </button>
        <button className="avatar" aria-label="打开我的" onClick={() => { setProfileOpen(!profileOpen); setRecordOpen(false); }}><UserRound size={17} /></button>
      </div>
      {recordOpen && <div className="system-sheet record-sheet">
        <p>现实记录</p>
        <button onClick={() => { setPaused(!paused); setRecordOpen(false); toast(paused ? "现实记录已恢复" : "现实记录已暂停"); }}>{paused ? "恢复记录" : "暂停记录"}</button>
        <button onClick={() => { setRecordOpen(false); toast("已忘记最近 10 分钟"); }}>忘记最近 10 分钟</button>
        <button onClick={() => go("privacy")}>查看记录范围</button>
      </div>}
      {profileOpen && <div className="system-sheet profile-sheet">
        <div className="profile-intro"><Placeholder label="用户头像" compact /><span><b>我的</b><small>Reality Memory</small></span></div>
        {secondary.map(([id, label]) => <button key={id} onClick={() => go(id)}>{label}<span>›</span></button>)}
      </div>}
    </header>
  );
}

function Navigation({ view, navigate }) {
  return <>
    <aside className="side-nav">{nav.map(({ id, label, Icon }) => <button key={id} className={view === id ? "active" : ""} onClick={() => navigate(id)}><Icon size={18}/><span>{label}</span></button>)}</aside>
    <nav className="mobile-nav">{nav.map(({ id, label, Icon }) => <button key={id} className={view === id ? "active" : ""} onClick={() => navigate(id)}><Icon size={18}/><span>{label}</span></button>)}</nav>
  </>;
}

function QueryBar({ value, setValue, ask, compact = false }) {
  return <form className={`query-bar ${compact ? "compact" : ""}`} onSubmit={(e) => { e.preventDefault(); ask(); }}>
    <input aria-label="询问现实" value={value} onChange={(e) => setValue(e.target.value)} placeholder="充电器在哪里？" />
    <button type="button" className="mic" aria-label="模拟语音输入" onClick={() => setValue("我的充电器在哪里？")}><Mic size={18}/></button>
    <button type="submit" className="ask-submit">询问</button>
  </form>;
}

function HomeMap({ openItem }) {
  return <section className="home-map" aria-label="我的家空间地图">
    <div className="map-lines" aria-hidden="true" />
    <div className="room living"><span className="room-name">客厅</span><button className="map-object charger" onClick={() => openItem("charger")}><b>充电器</b><small>工作桌下方 · 刚刚变化</small></button><button className="map-object remote" onClick={() => openItem("remote")}><b>遥控器</b><small>沙发右侧</small></button></div>
    <div className="room study"><span className="room-name">书房</span><button className="map-object cup" onClick={() => openItem("cup")}><b>水杯</b><small>工作桌右侧</small></button></div>
    <div className="room bedroom"><span className="room-name">卧室</span><button className="map-object watch" onClick={() => openItem("watch")}><b>手表</b><small>床头柜上</small></button></div>
    <div className="room entry"><span className="room-name">玄关</span><button className="map-object keys" onClick={() => openItem("keys")}><b>钥匙</b><small>玄关托盘</small></button><span className="map-note">快递 · 门口</span></div>
    <div className="room bathroom"><span className="room-name">卫生间</span><span className="private-room">禁采</span></div>
  </section>;
}

function NowView({ navigate, openItem, openGlass, query, setQuery, ask }) {
  return <div className="page now-page">
    <header className="page-heading"><div><p className="eyebrow">现在</p><h1>家的此刻，一目了然。</h1><p>位置、变化和待办，都来自被允许记住的现实。</p></div><button className="text-link glass-entry" onClick={openGlass}>戴上眼镜查看 →</button></header>
    <HomeMap openItem={openItem}/>
    <section className="now-summary">
      <button onClick={() => openItem("charger")}><span>刚刚变化</span><b>充电器从工作桌掉到了下方</b><small>10:18 · 客厅工作区</small></button>
      <button onClick={() => navigate("memory")}><span>接下来</span><b>快递已送到门口</b><small>今天早上 · 待取回</small></button>
      <button onClick={() => navigate("all")}><span>所有物品</span><b>{items.length} 件有位置记录</b><small>查看完整物品网络</small></button>
    </section>
    <section className="query-section"><div><h2>问一件眼前的事</h2><p>临时查询，不会变成聊天记录。</p></div><QueryBar value={query} setValue={setQuery} ask={ask}/></section>
  </div>;
}

function RewindView({ openItem }) {
  return <div className="page narrow-page"><header className="page-heading"><div><p className="eyebrow">回拨</p><h1>回到变化发生的那一刻。</h1><p>选择一件物品，查看它在现实中的位置版本。</p></div></header>
    <section className="featured-rewind"><Placeholder label="场景图：充电器从桌面掉落" item="充电器"/><div><span>今天 10:16 → 10:18</span><h2>从工作桌，到工作桌下方</h2><p>Reality Memory 只保留位置与变化。原始画面不会成为可浏览的生活录像。</p><button className="primary-text" onClick={() => openItem("charger")}>查看这次变化</button></div></section>
    <section className="section-block"><div className="section-title"><h2>最近的现实版本</h2><p>每件物品都有自己的时间线。</p></div><div className="simple-list">{items.slice(0,6).map(item => <button key={item.id} onClick={() => openItem(item.id)}><span><b>{item.name}</b><small>{item.room} · {item.location}</small></span><time>{item.seen}</time></button>)}</div></section>
  </div>;
}

function AskView({ query, setQuery, ask, answer, openItem, openGlass }) {
  return <div className="page ask-page"><header className="page-heading"><div><p className="eyebrow">询问</p><h1>直接问现实。</h1><p>这是一次临时查询，不是一段需要维护的对话。</p></div></header>
    <div className="ask-center"><QueryBar value={query} setValue={setQuery} ask={ask}/>
      {answer?.loading && <section className="answer"><span>正在询问现实</span><h2>正在检索记忆…</h2><p>首次询问新物体会做混合召回与画面精判，可能需要几秒。</p></section>}
      {answer && !answer.loading && <section className="answer"><span>{answer.demo ? "演示答案（后端未连接）" : "当前答案"}</span><h2>{answer.title}</h2><p>{answer.sub}</p><div>{answer.demo && <button onClick={() => openItem("charger")}>查看位置变化</button>}<button onClick={openGlass}>在眼镜中查看</button></div></section>}
      <div className="suggestions"><span>也可以问</span>{["钥匙在哪里？", "我看到第几页了？", "上次倒垃圾是什么时候？"].map(x => <button key={x} onClick={() => { setQuery(x); }}>{x}</button>)}</div></div>
  </div>;
}

function AllView({ openItem }) {
  const stageRef = useRef(null);
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    const update = () => {
      if (!stageRef.current) return;
      const rect = stageRef.current.getBoundingClientRect();
      const distance = Math.max(stageRef.current.offsetHeight - window.innerHeight, 1);
      setProgress(Math.max(0, Math.min(1, -rect.top / distance)));
    };
    update(); window.addEventListener("scroll", update, { passive: true }); window.addEventListener("resize", update);
    return () => { window.removeEventListener("scroll", update); window.removeEventListener("resize", update); };
  }, []);
  return <div className="page all-page"><header className="page-heading all-heading"><div><p className="eyebrow">所有</p><h1>家里被记住的物品。</h1><p>向下浏览，它们会从生活中的堆放状态，回到清晰的位置记录。</p></div><span>{items.length} 件</span></header>
    <section className="pile-stage" ref={stageRef} style={{ "--progress": progress }}>
      <div className="pile-sticky">
        <div className="pile-copy" style={{ opacity: 1 - Math.min(progress * 2.2, 1) }}><span>我的物品</span><small>继续向下</small></div>
        <div className="sticker-cloud">{items.slice(0,18).map((item, i) => { const angle = ((i * 37) % 70) - 35; const x = ((i * 83) % 76) - 38; const y = ((i * 47) % 52) - 26; return <div key={item.id} className="pile-sticker" style={{ "--x": `${x}vw`, "--y": `${y}vh`, "--r": `${angle}deg`, "--delay": i }}><Placeholder label="产品贴图" item={item.name} compact/></div>; })}</div>
      </div>
    </section>
    <section className="object-grid" aria-label="所有物品卡片">{items.map(item => <button key={item.id} className="object-card" onClick={() => openItem(item.id)}><Placeholder label="产品贴图" item={item.name}/><span><b>{item.name}</b><small>{item.room} · {item.location}</small><em>{item.seen}</em></span></button>)}</section>
  </div>;
}

function ItemDetail({ item, back, toast }) {
  const [eventIndex, setEventIndex] = useState(item.events.length - 1);
  useEffect(() => setEventIndex(item.events.length - 1), [item.id, item.events.length]);
  const event = item.events[eventIndex];
  return <div className="page detail-page"><button className="back-link" onClick={back}><ChevronLeft size={16}/>返回</button><header className="detail-head"><p className="eyebrow">{item.category}</p><h1>{item.name}</h1></header>
    <div className="detail-layout">
      <aside className="item-timeline"><div className="timeline-label"><b>时间</b><span>{event.time}</span></div><input aria-label={`${item.name}时间线`} type="range" min="0" max={item.events.length - 1} step="1" value={eventIndex} onChange={e => setEventIndex(Number(e.target.value))}/><div className="event-labels">{item.events.map((x,i) => <button key={x.time} className={i === eventIndex ? "active" : ""} onClick={() => setEventIndex(i)}>{x.time}</button>)}</div></aside>
      <main className="item-state"><span>{item.room}</span><h2>{event.title}</h2><p>{event.note}</p><dl><div><dt>位置</dt><dd>{eventIndex === item.events.length - 1 ? item.location : event.title.replace(/^在/, "")}</dd></div><div><dt>依据</dt><dd>{eventIndex === 1 ? "一次清晰观察" : "位置变化节点"}</dd></div><div><dt>原始画面</dt><dd>未长期保存</dd></div></dl></main>
      <aside className="item-visual"><Placeholder label="产品贴图" item={item.name}/><p>最后看见</p><b>{item.seen}</b><div><button onClick={() => toast("已进入位置纠正流程")}>纠正</button><button className="danger" onClick={() => toast(`已提交忘记“${item.name}”的请求`)}>忘记</button></div></aside>
    </div>
  </div>;
}

function MemoryView() {
  return <div className="page narrow-page"><header className="page-heading"><div><p className="eyebrow">记忆</p><h1>物品之外，生活仍在继续。</h1><p>任务、偏好和进度被整理成可以使用的记忆。</p></div></header><div className="memory-groups">{["任务","偏好","进度","生活"].map(group => <section key={group}><h2>{group}</h2>{memories.filter(x => x[0] === group).map((x,i) => <button key={i}><span><b>{x[1]}</b><small>{x[2]}</small></span><i className="memory-switch">已记住</i></button>)}</section>)}</div></div>;
}

function DevicesView({ openGlass }) {
  return <div className="page narrow-page"><header className="page-heading"><div><p className="eyebrow">设备</p><h1>记录发生在被允许的设备上。</h1><p>连接状态和记录范围始终可以查看。</p></div></header><section className="device-hero"><Placeholder label="产品图：RV101 眼镜" item="Rokid RV101"/><div><span className="online">已连接</span><h2>RV101</h2><p>电量 78% · 最近同步 10:24</p><button className="primary-text" onClick={openGlass}>进入眼镜演示</button></div></section><section className="settings-list"><div><span><b>Reality Memory 订阅有效</b><small>长期记忆与多设备能力可用</small></span><strong>有效</strong></div><div><span><b>这台浏览器</b><small>当前展示设备</small></span><strong>在线</strong></div></section></div>;
}

function PrivacyView({ paused, setPaused, toast }) {
  return <div className="page narrow-page"><header className="page-heading"><div><p className="eyebrow">隐私</p><h1>记住什么，由你决定。</h1><p>系统只保存结构化的位置和变化，不提供生活录像。</p></div></header><section className="privacy-statement"><h2>记忆从 2026 年 7 月 12 日开始</h2><p>当前有 4 个可记录空间，1 个禁采空间。</p></section><section className="settings-list"><div><span><b>现实记录</b><small>{paused ? "新变化不会被记住" : "正在记住被允许空间中的变化"}</small></span><button className={`ios-switch ${paused ? "" : "on"}`} aria-label="切换现实记录" onClick={() => { setPaused(!paused); toast(paused ? "现实记录已恢复" : "现实记录已暂停"); }}><i/></button></div>{rooms.map(room => <div key={room}><span><b>{room}</b><small>{room === "卫生间" ? "不会产生任何新记忆" : "仅保存结构化位置与变化"}</small></span><strong className={room === "卫生间" ? "private" : ""}>{room === "卫生间" ? "禁采" : "允许"}</strong></div>)}</section><button className="forget-action" onClick={() => toast("已进入批量忘记流程")}>管理与忘记记忆</button></div>;
}

function OpenView() {
  return <div className="page narrow-page"><header className="page-heading"><div><p className="eyebrow">开放能力</p><h1>让现实记忆进入更多设备。</h1><p>同一套隐私边界，可以服务未来的眼镜、家居与个人设备。</p></div></header><Placeholder label="流程图：设备接入 Reality Memory 能力网络" item="能力网络"/><section className="capability-row"><div><span>01</span><h2>结构化记忆</h2><p>设备提交对象、位置与变化，而不是持续上传原始画面。</p></div><div><span>02</span><h2>用户授权</h2><p>每个空间和设备都遵循同一套暂停、禁采与忘记规则。</p></div><div><span>03</span><h2>长期能力</h2><p>订阅承载跨设备的连续记忆，但控制权始终属于用户。</p></div></section></div>;
}

function GlassView({ close }) {
  const [scene, setScene] = useState("find");
  const [controls, setControls] = useState(true);
  const timer = useRef();
  const reveal = () => { setControls(true); clearTimeout(timer.current); timer.current = setTimeout(() => setControls(false), 3400); };
  useEffect(() => { reveal(); return () => clearTimeout(timer.current); }, [scene]);
  return <div className={`glass-view ${controls ? "controls-visible" : ""}`} onClick={reveal}>
    <Placeholder label={scene === "find" ? "第一视角场景图：低头看向工作桌下方" : "第一视角场景图：进入卫生间"} />
    <div className="lens-vignette"/>
    <div className="glass-hud">{scene === "find" ? <><i/><p>找到了，你的充电器掉在工作桌下面了。</p><ArrowDown size={28}/></> : <><i/><p>当前空间已禁采</p><small>这里不会产生新的现实记忆</small></>}</div>
    <button className="glass-exit" onClick={(e) => { e.stopPropagation(); close(); }}>退出</button>
    <button className="glass-scene" onClick={(e) => { e.stopPropagation(); setScene(scene === "find" ? "private" : "find"); }}>{scene === "find" ? "查看禁采场景" : "返回找物场景"}</button>
  </div>;
}

function App() {
  const [view, setView] = useState("now");
  const [previous, setPrevious] = useState("now");
  const [selectedId, setSelectedId] = useState("charger");
  const [paused, setPaused] = useState(false);
  const [query, setQuery] = useState("我的充电器在哪里？");
  const [answer, setAnswer] = useState(null);
  const [glass, setGlass] = useState(false);
  const [toastText, setToastText] = useState("");
  const selected = useMemo(() => items.find(x => x.id === selectedId) || items[0], [selectedId]);
  const toast = (text) => { setToastText(text); setTimeout(() => setToastText(""), 2400); };
  const navigate = (next) => { if (view !== "detail") setPrevious(view); setView(next); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const openItem = (id) => { setPrevious(view); setSelectedId(id); setView("detail"); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const ask = async () => {
    setView("ask");
    setAnswer({ loading: true });
    // 「我的充电器在哪里？」→「充电器」：where-is 收物体名，不收整句
    const name = query.replace(/^(我的|请问|帮我找|找一下)+/, "").replace(/(在哪里|在哪儿|在哪|去哪了)?[？?。]*$/, "").trim() || query;
    try {
      const resp = await whereIs(name, true);
      setAnswer({
        title: resp.answer_text || `没有找到「${name}」的位置记忆。`,
        sub: `通道 ${resp.channel} · 置信度 ${Math.round((resp.confidence || 0) * 100)}%${resp.location ? ` · ${resp.location}` : ""}`,
      });
    } catch {
      // 后端未连接 → 回退演示答案，保持原型可独立展示
      setAnswer({ demo: true, title: "找到了，你的充电器掉在工作桌下面了。", sub: "最后确认于今天 10:18 · 客厅工作区" });
    }
  };
  let content;
  if (view === "now") content = <NowView navigate={navigate} openItem={openItem} openGlass={() => setGlass(true)} query={query} setQuery={setQuery} ask={ask}/>;
  else if (view === "rewind") content = <RewindView openItem={openItem}/>;
  else if (view === "ask") content = <AskView query={query} setQuery={setQuery} ask={ask} answer={answer} openItem={openItem} openGlass={() => setGlass(true)}/>;
  else if (view === "all") content = <AllView openItem={openItem}/>;
  else if (view === "detail") content = <ItemDetail item={selected} back={() => navigate(previous)} toast={toast}/>;
  else if (view === "live") content = <LiveView/>;
  else if (view === "memory") content = <MemoryView/>;
  else if (view === "devices") content = <DevicesView openGlass={() => setGlass(true)}/>;
  else if (view === "privacy") content = <PrivacyView paused={paused} setPaused={setPaused} toast={toast}/>;
  else content = <OpenView/>;
  return <div className="app-shell"><Header paused={paused} setPaused={setPaused} navigate={navigate} toast={toast}/><Navigation view={view} navigate={navigate}/><main className="content">{content}</main>{view !== "now" && view !== "ask" && view !== "all" && view !== "detail" && view !== "live" && <button className="floating-query" onClick={() => navigate("ask")}>询问现实</button>}{toastText && <div className="toast">{toastText}</div>}{glass && <GlassView close={() => setGlass(false)}/>}</div>;
}

export default App;
