import { useState, useEffect, useRef } from "react";
import { Mic, Keyboard, CircleDot, Milestone, Sparkles, X, Check, Coffee, Zap, MapPin, SlidersHorizontal, ChevronRight } from "lucide-react";
import "./styles.css";

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

function AgentHome({ setMessages, messages, isTyping, setIsTyping, setShowClues }) {
  const [listening, setListening] = useState(false);

  const handleSend = (text) => {
    const textToSend = text || "我的充电器在哪里？";
    const newMsg = { id: Date.now(), text: textToSend, sender: "user" };
    setMessages(prev => {
      const lastAgent = prev.slice().reverse().find(m => m.sender === 'agent');
      return lastAgent ? [lastAgent, newMsg] : [newMsg];
    });
    
    setIsTyping(true);
    setListening(false);

    setTimeout(() => {
      setMessages(prev => [...prev, { id: Date.now()+1, text: "", sender: "agent", type: "thinking" }]);
      setTimeout(() => {
        setMessages(prev => [
          prev[0], 
          { id: Date.now()+2, text: "最后一次确认在客厅工作桌下方。今天 10:18 之后没有新的移动记录。", sender: "agent" }
        ]);
        setIsTyping(false);
      }, 1500);
    }, 600);
  };

  const handleVoice = () => {
    setListening(true);
    setTimeout(() => {
      handleSend();
    }, 1000);
  }

  return (
    <div className="page-view agent-page">
      <div className="light-field-agent" aria-hidden="true">
        <i className="beam one"></i>
        <i className="beam two"></i>
        <i className="beam three"></i>
      </div>

      <div className="orb-center">
        <i className="ring r1"></i>
        <i className="ring r2"></i>
        <i className="ring r3"></i>
        <span className="orb-wrap"><i className="orb"></i></span>
      </div>

      <header className="top">
        <div className="brand">
          <b>在场</b>
          <span>随时待命的现实记忆 Agent。</span>
        </div>
        <i className="enabled" aria-label="已开启"></i>
      </header>

      <div className="dialogue" aria-live="polite">
        {messages.map(msg => (
          <div key={msg.id} className={`bubble ${msg.sender} ${msg.type === "thinking" ? "thinking" : ""}`}>
            {msg.type === "thinking" ? <><i/><i/><i/></> : msg.text}
          </div>
        ))}
      </div>

      <button className="hint-pill" onClick={() => setShowClues(true)} style={{ opacity: isTyping ? 0 : 1 }}>
        <span className="status-dot"></span> 2 条记忆线索待确认
      </button>

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

function TimelineView({ setSelectedObject }) {
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

function GalaxyView({ setSelectedObject }) {
  return (
    <div className="page-view galaxy-page">
      {/* Indigo Space Nebula & Planet Glow Background */}
      <div className="galaxy-bg-canvas">
        <div className="star-field"></div>
        <div className="planet-glow"></div>
      </div>

      <header className="top">
        <div className="brand">
          <b>全览</b>
          <span>现实记忆拓扑全貌</span>
        </div>
      </header>

      <div className="galaxy-viewport">
        <div className="galaxy-canvas">
          <div className="star-cluster c-objects" style={{top: '25%', left: '16%'}}>
            <div className="dark-pill-node float-anim" onClick={() => setSelectedObject("充电器")}>
              <span className="node-dot active"></span>
              <span>充电器</span>
            </div>
            <div className="dark-pill-node dim float-anim delay-1">
              <span>钥匙</span>
            </div>
            <span className="cluster-label">物品</span>
          </div>

          <div className="star-cluster c-prefs" style={{top: '52%', left: '56%'}}>
            <div className="dark-pill-node float-anim delay-2" onClick={() => setSelectedObject("胡辣汤")}>
              <span className="node-dot warning"></span>
              <span>胡辣汤</span>
            </div>
            <div className="dark-pill-node float-anim">
              <span>咖啡无糖</span>
            </div>
            <span className="cluster-label">偏好</span>
          </div>

          <div className="star-cluster c-tasks" style={{top: '72%', left: '22%'}}>
            <div className="dark-pill-node float-anim delay-1">
              <span>快递包裹</span>
            </div>
            <span className="cluster-label">待办</span>
          </div>

          <svg className="constellation" width="100%" height="100%">
            <path d="M 120 140 Q 200 240 240 320" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="1" strokeDasharray="3 3"/>
          </svg>
        </div>
      </div>
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

function App() {
  const [activeTab, setActiveTab] = useState("agent");
  const [messages, setMessages] = useState([{ id: 1, text: "我在。你可以直接问现实里的事。", sender: "agent" }]);
  const [isTyping, setIsTyping] = useState(false);
  const [selectedObject, setSelectedObject] = useState(null);
  const [showClues, setShowClues] = useState(false);

  return (
    <div className={`app-shell premium-dark mode-${activeTab}`}>
      <div className="status-bar">
        <span>9:41</span><span>Reality</span>
      </div>

      <main className="main-content">
        {activeTab === "agent" && (
          <AgentHome 
            messages={messages} 
            setMessages={setMessages} 
            isTyping={isTyping} 
            setIsTyping={setIsTyping}
            setShowClues={setShowClues}
          />
        )}
        {activeTab === "timeline" && <TimelineView setSelectedObject={setSelectedObject} />}
        {activeTab === "galaxy" && <GalaxyView setSelectedObject={setSelectedObject} />}
      </main>

      {selectedObject && (
        <ObjectDrawer objectName={selectedObject} onClose={() => setSelectedObject(null)} />
      )}
      {showClues && (
        <CluesDrawer onClose={() => setShowClues(false)} />
      )}

      <nav className="bottom-dock premium-dock">
        <button className={`dock-item ${activeTab === 'agent' ? 'active' : ''}`} onClick={() => setActiveTab("agent")}>
          <CircleDot size={20} />
          <span>在场</span>
        </button>
        <button className={`dock-item ${activeTab === 'timeline' ? 'active' : ''}`} onClick={() => setActiveTab("timeline")}>
          <Milestone size={20} />
          <span>上下文</span>
        </button>
        <button className={`dock-item ${activeTab === 'galaxy' ? 'active' : ''}`} onClick={() => setActiveTab("galaxy")}>
          <Sparkles size={20} />
          <span>全览</span>
        </button>
      </nav>
    </div>
  );
}

export default App;
