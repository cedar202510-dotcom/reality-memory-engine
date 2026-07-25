import { useState, useEffect, useRef } from "react";
import { Routes, Route, Navigate, Outlet, useNavigate, useLocation, useOutletContext, useSearchParams } from "react-router-dom";
import { Mic, Keyboard, CircleDot, Milestone, Sparkles, X, Check, Coffee, Zap, MapPin, SlidersHorizontal, ChevronRight, Radio, ArrowLeft, Camera, User } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import "./styles.css";
import TopologyGraph from "./TopologyGraph";
import LiveView from "./LiveView";
import CaptureConsole from "./CaptureConsole";
import PresenceOrb from "./PresenceOrb";
import MyPage from "./MyPage";
import { whereIs } from "./api";

// Mock Data for Context
const mockContextItems = [
  {
    id: "c1",
    time: "12:30",
    period: "午餐碎片",
    type: "deduction",
    title: "外卖偏好记录",
    subtitle: "针对‘张记胡辣汤’的评价",
    detail: "语音捕获：“这家胡辣汤不好喝”",
    needsConfirmation: true,
    objectName: "胡辣汤"
  },
  {
    id: "c2",
    time: "10:18",
    period: "工作碎片",
    type: "location",
    title: "充电器位置变更",
    detail: "书房桌面 → 工作桌下方",
    needsConfirmation: false,
    objectName: "充电器"
  },
  {
    id: "c3",
    time: "08:00",
    period: "出行碎片",
    type: "event",
    title: "随身物品确认",
    detail: "带走背包、钥匙与水杯",
    needsConfirmation: false,
    objectName: null
  }
];

const mockObjectDetails = {
  "充电器": {
    name: "充电器",
    category: "电子配件",
    currentLocation: "书房工作桌下方",
    lastUpdated: "10:18",
    history: [
      { time: "10:18", action: "位置变更", detail: "从书房桌面移动到工作桌下方" },
      { time: "08:00", action: "状态确认", detail: "在书房桌面，连接 MacBook" },
      { time: "昨天 22:30", action: "状态确认", detail: "床头柜充电" }
    ]
  },
  "胡辣汤": {
    name: "胡辣汤",
    category: "餐饮偏好",
    currentLocation: "张记胡辣汤",
    lastUpdated: "12:30",
    history: [
      { time: "12:30", action: "语音提及", detail: "评价“这家胡辣汤不好喝”" },
      { time: "上周三", action: "消费记录", detail: "首次尝试张记胡辣汤" }
    ]
  }
};

/** 从口语问句里取出物品名：「我的充电器在哪里？」→「充电器」。
 *  后端 where-is 收的是物品名而不是整句；抽不出来时退回原文，由深检索兜底。 */
function extractObjectName(text) {
  const stripped = text
    .replace(/[?？。！!，,、\s]/g, "")
    .replace(/^(我的|我地|帮我找|找一下|找找|请问)/, "")
    .replace(/(在哪里|在哪儿|在哪|放哪了|放哪儿了|放在哪|去哪了|呢)$/, "");
  return stripped || text;
}

const FALLBACK_ANSWER = "最后一次确认在客厅工作桌下方。今天 10:18 之后没有新的移动记录。";

function AgentHome() {
  const { messages, setMessages, isTyping, setIsTyping, setShowClues } = useOutletContext();
  const [listening, setListening] = useState(false);
  const [agentText, setAgentText] = useState("我在。你可以直接问现实里的事。");
  const [userText, setUserText] = useState("");

  const handleSend = async (text) => {
    const textToSend = text || "我的充电器在哪里？";
    setUserText(textToSend);
    setIsTyping(true);
    setListening(false);

    // 真实后端优先；memory-platform 未启动时回退演示答案，保持原型可独立展示
    let reply = FALLBACK_ANSWER;
    try {
      const res = await whereIs(extractObjectName(textToSend), true);
      if (res?.answer_text) {
        reply = res.answer_text;
      }
    } catch {
      /* 后端不可达 → 保持 demo 答案 */
    }

    setTimeout(() => {
      setAgentText(reply);
      setUserText(""); // 用户气泡化为轻烟消失
      setIsTyping(false);
    }, 1500); // 模拟网络延迟和动画过度时间
  };

  const handleVoice = () => {
    setListening(true);
    setTimeout(() => {
      handleSend();
    }, 1000);
  }

  return (
    <div className="page-view agent-page">
      <div style={{ position: "absolute", top: "40%", left: "50%", transform: "translate(-50%, -50%)", zIndex: 0 }}>
        <PresenceOrb state={listening ? "listening" : isTyping ? "thinking" : "idle"} />
      </div>

      <header className="top" style={{ zIndex: 10 }}>
        <div className="brand">
          <b>在场</b>
          <span>随时待命的现实记忆 Agent。</span>
        </div>
        <i className="enabled" aria-label="已开启"></i>
      </header>
      
      {/* 顶部线索提醒（灵动岛风格） */}
      <div style={{ position: "absolute", top: 80, width: "100%", display: "flex", justifyContent: "center", zIndex: 20 }}>
        <motion.button 
          className="hint-pill" 
          onClick={() => setShowClues(true)}
          initial={{ y: -50, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(10px)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "20px", padding: "6px 16px", display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", color: "var(--ink)" }}
        >
          <span className="status-dot"></span> 2 条记忆线索待确认
        </motion.button>
      </div>

      <div className="dialogue" aria-live="polite" style={{ zIndex: 10, display: "flex", flexDirection: "column", height: "100%", justifyContent: "center", paddingBottom: "100px" }}>
        
        <AnimatePresence mode="wait">
          <motion.div 
            key={agentText}
            initial={{ opacity: 0, scale: 0.8, filter: "blur(10px)" }}
            animate={{ opacity: isTyping || listening ? 0 : 1, scale: isTyping || listening ? 1.05 : 1, filter: isTyping || listening ? "blur(10px)" : "blur(0px)" }}
            transition={{ duration: 0.6, type: "spring", bounce: 0.4 }}
            style={{ 
              margin: "0 auto",
              textAlign: "center", 
              fontSize: "15px", 
              color: "var(--ink)", 
              padding: "16px 24px", 
              lineHeight: "1.5",
              background: "rgba(86, 235, 142, 0.08)",
              border: "1px solid rgba(86, 235, 142, 0.2)",
              backdropFilter: "blur(20px)",
              borderRadius: "24px",
              maxWidth: "85%",
              boxShadow: "0 12px 40px rgba(0,0,0,0.3), inset 0 0 20px rgba(86, 235, 142, 0.05)"
            }}
          >
            {agentText}
          </motion.div>
        </AnimatePresence>

        <AnimatePresence>
          {userText && (
            <motion.div 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20, filter: "blur(5px)" }}
              className="bubble user"
              style={{ position: "absolute", bottom: "160px", right: "24px" }}
            >
              {userText}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="composer" role="group" aria-label="语音输入">
        <button className={`voice ${listening ? 'listening' : ''}`} onClick={handleVoice}>
          {listening ? "正在听..." : "轻点说话"}
        </button>
        <button className="keyboard-toggle" aria-label="切换文字输入">
          <span className="keyboard-icon" aria-hidden="true">
            <i></i><i></i><i></i><i></i>
            <i></i><i></i><i></i><i></i>
            <i></i><i></i><i></i><i></i>
          </span>
        </button>
      </div>
    </div>
  );
}

function TimelineView() {
  const { setSelectedObject } = useOutletContext();
  const [items, setItems] = useState(mockContextItems);

  const handleConfirm = (e, id, confirmed) => {
    e.stopPropagation();
    setItems(prev => prev.map(item => item.id === id ? { ...item, needsConfirmation: false, statusText: confirmed ? "已确认" : "已忽略" } : item));
  };

  return (
    <div className="page-view timeline-page">
      <header className="top">
        <div className="brand">
          <b>上下文</b>
          <span>现实发生的流动切片</span>
        </div>
        <button className="icon-btn"><SlidersHorizontal size={18} /></button>
      </header>

      <div className="timeline-container">
        {/* Sleek Dashed Progress Timeline */}
        <div className="timeline-line"></div>

        <div className="timeline-list">
          {items.map((item) => (
            <div key={item.id} className="timeline-node">
              <div className="node-time-badge">
                <span className="time-text">{item.time}</span>
                <span className="period-text">{item.period}</span>
              </div>
              <div className="node-bullet"></div>

              <div 
                className={`dark-card ${item.objectName ? 'clickable' : ''}`}
                onClick={() => item.objectName && setSelectedObject(item.objectName)}
              >
                <div className="card-top-row">
                  <span className="card-title">{item.title}</span>
                  {item.objectName && (
                    <span className="more-link">
                      轨迹 <ChevronRight size={14} />
                    </span>
                  )}
                </div>

                <p className="card-detail">{item.detail}</p>

                {item.needsConfirmation ? (
                  <div className="confirm-inline-bar">
                    <span className="prompt-text">确认记录为偏好？</span>
                    <div className="btn-group">
                      <button className="mini-icon-btn check" onClick={(e) => handleConfirm(e, item.id, true)}>
                        <Check size={14} />
                      </button>
                      <button className="mini-icon-btn close" onClick={(e) => handleConfirm(e, item.id, false)}>
                        <X size={14} />
                      </button>
                    </div>
                  </div>
                ) : item.statusText ? (
                  <span className="status-note">{item.statusText}</span>
                ) : null}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function GalaxyView() {
  const { setSelectedObject } = useOutletContext();
  return (
    <div className="page-view galaxy-page">
      <div className="galaxy-bg-canvas">
        <div className="star-field"></div>
        <div className="planet-glow"></div>
      </div>

      <header className="top">
        <div className="brand">
          <b>全览</b>
          <span>物品之间，存在生活的路径。</span>
        </div>
      </header>
      <TopologyGraph onOpenItem={setSelectedObject}/>
    </div>
  );
}

// Drawer: Object Micro Lifecycle (MYGRID style minimalist dark drawer)
function ObjectDrawer({ objectName, onClose }) {
  const data = mockObjectDetails[objectName] || {
    name: objectName,
    category: "现实物品",
    currentLocation: "已知位置",
    lastUpdated: "刚才",
    history: [{ time: "刚才", action: "状态确认", detail: "记录于当前上下文" }]
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-sheet dark-sheet" onClick={e => e.stopPropagation()}>
        <div className="drawer-handle"></div>
        <div className="drawer-header">
          <div>
            <h3>{data.name}</h3>
            <span className="category-pill">{data.category}</span>
          </div>
          <button className="close-btn" onClick={onClose}><X size={18}/></button>
        </div>

        <div className="drawer-body">
          <div className="status-card-box">
            <MapPin size={16} color="var(--green)" />
            <div>
              <span className="label">当前确切位置</span>
              <span className="val">{data.currentLocation}</span>
            </div>
          </div>

          <div className="micro-timeline">
            <h4>微观轨迹</h4>
            {data.history.map((item, idx) => (
              <div key={idx} className="timeline-item">
                <div className="item-left">
                  <span className="time">{item.time}</span>
                  <div className="line-dot"></div>
                </div>
                <div className="item-right">
                  <span className="action">{item.action}</span>
                  <p className="detail">{item.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// Drawer: Clues Center Drawer
function CluesDrawer({ onClose }) {
  const [cluesList, setCluesList] = useState([
    { id: 1, title: "外卖偏好推断", desc: "午餐提到“这家胡辣汤不好喝”，是否确认记录？" },
    { id: 2, title: "耗材使用提醒", desc: "抽纸使用约 80%，是否加入买单？" }
  ]);

  const handleAction = (id) => {
    setCluesList(prev => prev.filter(c => c.id !== id));
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-sheet dark-sheet" onClick={e => e.stopPropagation()}>
        <div className="drawer-handle"></div>
        <div className="drawer-header">
          <div>
            <h3>线索确认中心</h3>
            <span className="sub-title">推断求证与精细化记忆</span>
          </div>
          <button className="close-btn" onClick={onClose}><X size={18}/></button>
        </div>

        <div className="drawer-body">
          {cluesList.length === 0 ? (
            <div className="empty-clues">
              <Check size={24} color="var(--green)" />
              <p>所有线索已确认</p>
            </div>
          ) : (
            <div className="clues-list">
              {cluesList.map(c => (
                <div key={c.id} className="dark-clue-card">
                  <h4>{c.title}</h4>
                  <p>{c.desc}</p>
                  <div className="clue-actions">
                    <button className="action-btn confirm" onClick={() => handleAction(c.id)}>
                      <Check size={14} /> 确认
                    </button>
                    <button className="action-btn deny" onClick={() => handleAction(c.id)}>
                      <X size={14} /> 忽略
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// 联调与采集控制都是桌面工作台，不是手机功能：跳出 430px 手机模型走全宽双栏
function ConsolePage({ component: Console }) {
  const navigate = useNavigate();
  return (
    <div className="live-console">
      <button className="live-exit" onClick={() => navigate("/agent")}>
        <ArrowLeft size={15} /> 返回应用
      </button>
      <Console />
    </div>
  );
}

/** 手机壳布局：三个 tab 页共用状态栏与底部 dock，页面本身交给子路由。
 *  抽屉开合也写进 query（?object=…、?clues=1），刷新和浏览器后退都能还原当时看到的界面。 */
function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const activeTab = location.pathname.split("/")[1] || "agent";
  const [messages, setMessages] = useState([{ id: 1, text: "我在。你可以直接问现实里的事。", sender: "agent" }]);
  const [isTyping, setIsTyping] = useState(false);

  const selectedObject = searchParams.get("object");
  const showClues = searchParams.get("clues") === "1";

  const setParam = (key, value) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value); else next.delete(key);
      return next;
    }, { replace: true });
  };
  const setSelectedObject = (name) => setParam("object", name || null);
  const setShowClues = (open) => setParam("clues", open ? "1" : null);

  return (
    <div className={`app-shell premium-dark mode-${activeTab}`}>
      <div className="status-bar">
        <span>9:41</span><span>Reality</span>
      </div>

      <main className="main-content">
        <Outlet context={{ messages, setMessages, isTyping, setIsTyping, setSelectedObject, setShowClues }} />
      </main>

      {selectedObject && (
        <ObjectDrawer objectName={selectedObject} onClose={() => setSelectedObject(null)} />
      )}
      {showClues && (
        <CluesDrawer onClose={() => setShowClues(false)} />
      )}

      <nav className="bottom-dock premium-dock">
        {/* 切页只带路径不带 query：抽屉状态属于上一页，跟过去就成了幽灵弹窗 */}
        <button className={`dock-item ${activeTab === 'agent' ? 'active' : ''}`} onClick={() => navigate("/agent")}>
          <CircleDot size={20} />
          <span>在场</span>
        </button>
        <button className={`dock-item ${activeTab === 'timeline' ? 'active' : ''}`} onClick={() => navigate("/timeline")}>
          <Milestone size={20} />
          <span>上下文</span>
        </button>
        <button className={`dock-item ${activeTab === 'galaxy' ? 'active' : ''}`} onClick={() => navigate("/galaxy")}>
          <Sparkles size={20} />
          <span>全览</span>
        </button>
        <button className={`dock-item ${activeTab === 'my' ? 'active' : ''}`} onClick={() => navigate("/my")}>
          <User size={20} />
          <span>我的</span>
        </button>
      </nav>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/live" element={<ConsolePage component={LiveView} />} />
      <Route path="/capture" element={<ConsolePage component={CaptureConsole} />} />
      <Route element={<AppShell />}>
        <Route path="/agent" element={<AgentHome />} />
        <Route path="/timeline" element={<TimelineView />} />
        <Route path="/galaxy" element={<GalaxyView />} />
        <Route path="/my" element={<MyPage />} />
      </Route>
      {/* 根路径和任何认不出的 URL 都落回在场页，刷新不会白屏 */}
      <Route path="*" element={<Navigate to="/agent" replace />} />
    </Routes>
  );
}

export default App;
