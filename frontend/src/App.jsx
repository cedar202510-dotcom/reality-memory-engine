import { useState, useEffect, useRef } from "react";
import { Routes, Route, Navigate, Outlet, useNavigate, useLocation, useOutletContext, useSearchParams } from "react-router-dom";
import { Mic, Keyboard, Send, Maximize2, X, Check, Coffee, Zap, MapPin, PieChart, ChevronRight, Radio, ArrowLeft, Camera } from "lucide-react";
import { CirclesFour, Compass, Path, UserCircle } from "@phosphor-icons/react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import "./styles.css";
import TopologyGraph from "./TopologyGraph";
import LiveView from "./LiveView";
import CaptureConsole from "./CaptureConsole";
import PresenceOrb from "./PresenceOrb";
import MyPage from "./MyPage";
import IconPreview from "./IconPreview";
import { mockWhereIs, whereIs } from "./api";

const timelineDays = [
  {
    id: "2025-11-29",
    month: "十一月",
    day: 29,
    weekday: "周六",
    title: "低速整理日",
    summary: "家务、补觉和零散移动比较多，系统只保留了几个确定片段。",
    intensity: 0.38,
    confirmations: 0,
    places: ["卧室", "客厅"],
    items: [
      { id: "d1129-1", time: "10:46", period: "起床后", category: "作息", title: "补觉结束", detail: "卧室环境音变弱，手机被拿起，推测结束一段较长休息。", tone: "dim" },
      { id: "d1129-2", time: "17:20", period: "家务", category: "空间", title: "客厅短时整理", detail: "连续移动水杯、纸巾和遥控器，客厅桌面状态更新。", tone: "green" }
    ]
  },
  {
    id: "2025-11-30",
    month: "十一月",
    day: 30,
    weekday: "周日",
    title: "外出准备日",
    summary: "当天的重点是出门前确认随身物品，饮食记录较少。",
    intensity: 0.48,
    confirmations: 1,
    places: ["玄关", "楼下"],
    items: [
      { id: "d1130-1", time: "09:12", period: "出门前", category: "物品", title: "随身物品确认", detail: "背包、钥匙、水杯被连续带离玄关。", tone: "aqua" },
      { id: "d1130-2", time: "21:08", period: "回家后", category: "线索", title: "水杯位置待确认", detail: "回家后未再次捕获水杯，建议确认是否仍在包里。", tone: "warm", needsConfirmation: true }
    ]
  },
  {
    id: "2025-12-01",
    month: "十二月",
    day: 1,
    weekday: "周一",
    title: "工作密度上升",
    summary: "上午进入深工作，下午有一次物品位置变化，晚上状态趋于安静。",
    intensity: 0.72,
    confirmations: 1,
    places: ["书房", "工作桌"],
    items: [
      { id: "d1201-1", time: "09:40", period: "上午", category: "专注", title: "书房深工作开始", detail: "键盘输入持续，背景噪声稳定，系统标记为一段连续工作。", tone: "green" },
      { id: "d1201-2", time: "15:28", period: "下午", category: "物品", title: "充电器被移动", detail: "充电器从书房桌面移动到工作桌下方。", tone: "aqua", objectName: "充电器" },
      { id: "d1201-3", time: "22:12", period: "夜间", category: "状态", title: "房间恢复安静", detail: "主要设备停止移动，灯光变化后进入低活动状态。", tone: "dim" }
    ]
  },
  {
    id: "2025-12-02",
    month: "十二月",
    day: 2,
    weekday: "周二",
    title: "饮食偏好浮现",
    summary: "午餐评价被捕获，适合沉淀成餐饮偏好，但需要用户确认。",
    intensity: 0.64,
    confirmations: 2,
    places: ["餐桌", "书房"],
    items: [
      { id: "d1202-1", time: "12:30", period: "午餐", category: "饮食", title: "外卖偏好记录", detail: "语音捕获：“这家胡辣汤不好喝”。", tone: "warm", needsConfirmation: true, objectName: "胡辣汤" },
      { id: "d1202-2", time: "16:55", period: "下午", category: "线索", title: "咖啡摄入偏晚", detail: "连续两天在 17 点前后饮用咖啡，可能影响晚间入睡。", tone: "green", needsConfirmation: true }
    ]
  },
  {
    id: "2025-12-03",
    month: "十二月",
    day: 3,
    weekday: "周三",
    title: "空间线索清晰",
    summary: "这一天的记录更像生活现场索引，物品和空间关系比较完整。",
    intensity: 0.58,
    confirmations: 0,
    places: ["客厅", "厨房", "玄关"],
    items: [
      { id: "d1203-1", time: "08:06", period: "早晨", category: "物品", title: "钥匙出现在玄关", detail: "钥匙最后一次被看见在玄关托盘内。", tone: "aqua" },
      { id: "d1203-2", time: "19:42", period: "晚间", category: "饮食", title: "晚餐后厨房清理", detail: "厨房台面物品减少，餐具进入水槽区域。", tone: "green" }
    ]
  },
  {
    id: "2025-12-04",
    month: "十二月",
    day: 4,
    weekday: "周四",
    title: "今天的生活截面",
    summary: "从工作、午餐到出门准备，几条关键线索已经能拼出当天节奏。",
    intensity: 0.9,
    confirmations: 2,
    places: ["书房", "餐桌", "玄关"],
    items: [
      { id: "d1204-1", time: "08:00", period: "早晨", category: "出行", title: "随身物品确认", detail: "带走背包、钥匙与水杯。", tone: "aqua" },
      { id: "d1204-2", time: "10:18", period: "工作", category: "物品", title: "充电器位置变更", detail: "书房桌面移动到工作桌下方。", tone: "green", objectName: "充电器" },
      { id: "d1204-3", time: "12:30", period: "午餐", category: "饮食", title: "外卖偏好记录", detail: "语音捕获：“这家胡辣汤不好喝”。", tone: "warm", needsConfirmation: true, objectName: "胡辣汤" },
      { id: "d1204-4", time: "18:46", period: "傍晚", category: "状态", title: "回到低干扰环境", detail: "客厅与书房的环境音下降，系统标记为可休息窗口。", tone: "dim" }
    ]
  },
  {
    id: "2025-12-05",
    month: "十二月",
    day: 5,
    weekday: "周五",
    title: "轻量复盘",
    summary: "记录数量不多，但出现了一次和设备相关的确认。",
    intensity: 0.42,
    confirmations: 1,
    places: ["书房"],
    items: [
      { id: "d1205-1", time: "11:22", period: "上午", category: "设备", title: "耳机短时离线", detail: "耳机离开电脑附近 23 分钟，随后回到书房。", tone: "aqua", needsConfirmation: true },
      { id: "d1205-2", time: "23:10", period: "夜间", category: "作息", title: "夜间设备收束", detail: "手机接入床头充电，电脑进入休眠。", tone: "dim" }
    ]
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
const INITIAL_GREETING = "我在。你可以直接问现实里的事。";

function AgentHome() {
  const { messages, setMessages, isTyping, setIsTyping, setShowClues } = useOutletContext();
  const [listening, setListening] = useState(false);
  const [agentText, setAgentText] = useState(INITIAL_GREETING);
  const [agentMedia, setAgentMedia] = useState([]);
  const [userText, setUserText] = useState("");
  const [hasAnswered, setHasAnswered] = useState(false);
  const [answerVersion, setAnswerVersion] = useState(0);
  const [inputMode, setInputMode] = useState("voice");
  const [draft, setDraft] = useState("");
  const [previewMedia, setPreviewMedia] = useState(null);
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const interactionRef = useRef(0);
  const voiceTimerRef = useRef(null);
  const agentSpeechTimerRef = useRef(null);
  const textInputRef = useRef(null);
  const reduceMotion = useReducedMotion();

  useEffect(() => () => {
    interactionRef.current += 1;
    window.clearTimeout(voiceTimerRef.current);
    window.clearTimeout(agentSpeechTimerRef.current);
  }, []);

  useEffect(() => {
    if (!previewMedia) return undefined;
    const handleEscape = (event) => {
      if (event.key === "Escape") setPreviewMedia(null);
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [previewMedia]);

  const handleSend = async (text) => {
    const interactionId = ++interactionRef.current;
    const textToSend = text || "我的充电器在哪里？";
    const questionShownAt = Date.now();
    window.clearTimeout(agentSpeechTimerRef.current);
    setAgentSpeaking(false);
    setUserText(textToSend);
    setIsTyping(true);
    setListening(false);

    // 真实后端优先；memory-platform 未启动时回退演示答案，保持原型可独立展示
    const objectName = extractObjectName(textToSend);
    let response = { answer_text: FALLBACK_ANSWER, media: [] };
    try {
      const res = await whereIs(objectName, true);
      if (res?.answer_text) {
        response = { ...response, ...res };
      }
    } catch {
      response = await mockWhereIs(objectName);
    }

    if (/身份证|证件/.test(objectName) && !response.media?.length) {
      const mediaMock = await mockWhereIs(objectName);
      response = {
        ...response,
        answer_text: response.answer_text || mediaMock.answer_text,
        media: mediaMock.media,
      };
    }

    const minimumQuestionHold = reduceMotion ? 420 : 1100;
    const remainingHold = Math.max(0, minimumQuestionHold - (Date.now() - questionShownAt));
    await new Promise(resolve => setTimeout(resolve, remainingHold));
    if (interactionRef.current !== interactionId) return;

    setUserText("");
    setAgentText(response.answer_text);
    setAgentMedia(response.media || []);
    setAnswerVersion(version => version + 1);
    setHasAnswered(true);
    setIsTyping(false);
    setAgentSpeaking(true);

    const speakingDuration = reduceMotion
      ? 480
      : Math.min(2800, Math.max(1400, response.answer_text.length * 44));
    agentSpeechTimerRef.current = window.setTimeout(() => {
      setAgentSpeaking(false);
    }, speakingDuration);
  };

  const handleVoice = () => {
    setListening(true);
    voiceTimerRef.current = window.setTimeout(() => {
      handleSend();
    }, 1000);
  }

  const openKeyboard = () => {
    setInputMode("text");
    textInputRef.current?.focus({ preventScroll: true });
    window.requestAnimationFrame(() => {
      textInputRef.current?.focus({ preventScroll: true });
    });
  };

  const closeKeyboard = () => {
    setInputMode("voice");
    textInputRef.current?.blur();
  };

  const handleTextSubmit = (event) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || isTyping || listening) return;
    setDraft("");
    setInputMode("voice");
    textInputRef.current?.blur();
    handleSend(text);
  };

  return (
    <div className="page-view agent-page">
      <div className="agent-orb-stage">
        <PresenceOrb state={listening ? "listening" : isTyping || agentSpeaking ? "thinking" : "idle"} />
      </div>

      <header className="top agent-top">
        <div className="brand">
          <b>顾问</b>
          <span>你的专属现实顾问</span>
        </div>
        <i className="enabled" aria-label="已开启"></i>
      </header>
      
      {/* 顶部线索提醒（灵动岛风格） */}
      <div className="memory-hint-wrap">
        <motion.button 
          className="hint-pill" 
          onClick={() => setShowClues(true)}
          initial={{ opacity: 0, transform: "translateY(-14px) scale(0.96)" }}
          animate={{ opacity: 1, transform: "translateY(0px) scale(1)" }}
          transition={{ type: "spring", duration: 0.42, bounce: 0.12 }}
        >
          <span className="status-dot"></span> 2 条记忆线索待确认
        </motion.button>
      </div>

      <div
        className={`dialogue agent-dialogue ${isTyping || listening ? "is-asking" : ""} ${hasAnswered ? "has-answer" : ""}`}
        aria-live="polite"
      >
        <div className="agent-center-text agent-greeting" aria-hidden={hasAnswered}>
          {INITIAL_GREETING}
        </div>
        {hasAnswered && (
          <div key={`${answerVersion}-${agentText}`} className="agent-center-text agent-answer-text">
            <span className="agent-answer-copy">{agentText}</span>
            {agentMedia.map((media) => (
              media.type === "image" && (
                <button
                  key={media.id}
                  type="button"
                  className="agent-answer-media"
                  onClick={() => setPreviewMedia(media)}
                  aria-label="放大查看位置图片"
                >
                  <img src={media.url} alt={media.alt} />
                  {(media.source_label || media.captured_at) && (
                    <span className="agent-media-caption">
                      <span>{media.source_label}</span>
                      <time>{media.captured_at}</time>
                    </span>
                  )}
                  <span className="agent-media-zoom" aria-hidden="true">
                    <Maximize2 size={13} strokeWidth={1.8} />
                  </span>
                </button>
              )
            ))}
          </div>
        )}
      </div>

      <div className="agent-user-lane" aria-live="polite">
        <AnimatePresence>
          {userText && (
            <motion.div 
              initial={reduceMotion
                ? { opacity: 0 }
                : {
                    opacity: 0,
                    transform: "translateY(42px) scale(0.97)",
                    filter: "blur(5px)"
                  }}
              animate={{
                opacity: 1,
                transform: "translateY(0px) scale(1)",
                filter: "blur(0px)"
              }}
              exit={reduceMotion
                ? { opacity: 0, transition: { duration: 0.16 } }
                : {
                    opacity: 0,
                    transform: "translateY(-20px) scale(0.98)",
                    filter: "blur(5px)",
                    transition: { duration: 0.5, ease: [0.25, 0.1, 0.25, 1] }
                  }}
              transition={reduceMotion
                ? { duration: 0.18 }
                : { type: "spring", duration: 0.32, bounce: 0.1 }}
              className="agent-user-bubble"
            >
              {userText}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <form
        className={`composer composer--${inputMode}`}
        role="group"
        aria-label={inputMode === "text" ? "文字输入" : "语音输入"}
        onSubmit={handleTextSubmit}
      >
        <button
          type="button"
          className={`voice ${listening ? 'listening' : ''}`}
          onClick={handleVoice}
          disabled={listening || isTyping}
        >
          <span className="voice-label">{listening ? "正在听..." : "轻点说话"}</span>
          <span className="voice-waveform" aria-hidden="true">
            <i style={{ "--wave-height": "8px", "--wave-index": 1 }} />
            <i style={{ "--wave-height": "14px", "--wave-index": 2 }} />
            <i style={{ "--wave-height": "20px", "--wave-index": 3 }} />
            <i style={{ "--wave-height": "11px", "--wave-index": 4 }} />
            <i style={{ "--wave-height": "17px", "--wave-index": 5 }} />
            <i style={{ "--wave-height": "7px", "--wave-index": 6 }} />
          </span>
        </button>

        <input
          ref={textInputRef}
          className="text-entry"
          type="text"
          inputMode="text"
          enterKeyHint="send"
          autoComplete="off"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="输入你想问的事"
          aria-label="输入你想问的事"
          disabled={isTyping || listening}
        />

        <button
          type={inputMode === "text" && draft.trim() ? "submit" : "button"}
          className="keyboard-toggle"
          onClick={inputMode === "voice" ? openKeyboard : draft.trim() ? undefined : closeKeyboard}
          aria-label={
            inputMode === "voice"
              ? "切换到文字输入"
              : draft.trim()
                ? "发送"
                : "切换到语音输入"
          }
          title={
            inputMode === "voice"
              ? "文字输入"
              : draft.trim()
                ? "发送"
                : "语音输入"
          }
          disabled={isTyping || listening}
        >
          {inputMode === "voice" ? (
            <Keyboard size={20} strokeWidth={1.8} aria-hidden="true" />
          ) : draft.trim() ? (
            <Send size={18} strokeWidth={2} aria-hidden="true" />
          ) : (
            <Mic size={19} strokeWidth={1.9} aria-hidden="true" />
          )}
        </button>
      </form>

      <AnimatePresence>
        {previewMedia && (
          <motion.div
            className="media-lightbox"
            role="dialog"
            aria-modal="true"
            aria-label="位置图片预览"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduceMotion ? 0.12 : 0.22 }}
            onClick={() => setPreviewMedia(null)}
          >
            <motion.div
              className="media-lightbox__content"
              initial={reduceMotion ? { opacity: 0 } : { opacity: 0, transform: "scale(0.97)" }}
              animate={{ opacity: 1, transform: "scale(1)" }}
              exit={reduceMotion ? { opacity: 0 } : { opacity: 0, transform: "scale(0.985)" }}
              transition={{ type: "spring", duration: reduceMotion ? 0.16 : 0.38, bounce: 0.08 }}
              onClick={(event) => event.stopPropagation()}
            >
              <button
                type="button"
                className="media-lightbox__close"
                onClick={() => setPreviewMedia(null)}
                aria-label="关闭图片预览"
              >
                <X size={19} />
              </button>
              <img src={previewMedia.url} alt={previewMedia.alt} />
              <div className="media-lightbox__meta">
                <span>{previewMedia.source_label}</span>
                <time>{previewMedia.captured_at}</time>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function TimelineView() {
  const { setSelectedObject } = useOutletContext();
  const [selectedDayId, setSelectedDayId] = useState("2025-12-04");
  const [scrubberOpen, setScrubberOpen] = useState(false);
  const floatingScrubberRef = useRef(null);
  const [itemsByDay, setItemsByDay] = useState(() =>
    Object.fromEntries(timelineDays.map(day => [day.id, day.items]))
  );

  const selectedDay = timelineDays.find(day => day.id === selectedDayId) || timelineDays[0];
  const selectedItems = itemsByDay[selectedDay.id] || [];
  const selectedDayIndex = Math.max(0, timelineDays.findIndex(day => day.id === selectedDay.id));

  const handleConfirm = (e, id, confirmed) => {
    e.stopPropagation();
    setItemsByDay(prev => ({
      ...prev,
      [selectedDay.id]: (prev[selectedDay.id] || []).map(item =>
        item.id === id
          ? { ...item, needsConfirmation: false, statusText: confirmed ? "已确认" : "已忽略" }
          : item
      )
    }));
  };

  const handleCardKeyDown = (event, objectName) => {
    if (!objectName) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setSelectedObject(objectName);
    }
  };



  return (
    <div className="page-view timeline-page">
      <header className="top timeline-header">
        <div className="brand">
          <b>轨迹</b>
          <span>日常留下的片段</span>
        </div>
        <div className="timeline-top-right">
          <AnimatePresence mode="wait">
            <motion.div
              key={selectedDay.id}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 4 }}
              transition={{ duration: 0.15 }}
              className="timeline-date-badge"
            >
              {selectedDay.month}{selectedDay.day}日 · {selectedDay.weekday}
            </motion.div>
          </AnimatePresence>
          <button className="icon-btn" aria-label="分析聚类"><PieChart size={18} /></button>
        </div>
      </header>

      <div className="timeline-container">
        <AnimatePresence mode="wait">
          <motion.div
            key={selectedDay.id}
            className="timeline-list"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
          >
            {selectedItems.map((item, index) => (
              <motion.div
                layout
                key={item.id}
                className="timeline-node"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.025, duration: 0.18 }}
              >
                <div className="node-time-badge">
                  <span className="time-text">{item.time}</span>
                  <span className="period-text">{item.period}</span>
                </div>
                <div className={`node-bullet tone-${item.tone}`}></div>

                <article
                  className={`dark-card tone-${item.tone} ${item.objectName ? "clickable" : ""}`}
                  onClick={() => item.objectName && setSelectedObject(item.objectName)}
                  onKeyDown={(event) => handleCardKeyDown(event, item.objectName)}
                  role={item.objectName ? "button" : undefined}
                  tabIndex={item.objectName ? 0 : undefined}
                >
                  <div className="card-top-row">
                    <span className="event-category">{item.category}</span>
                    {item.objectName && (
                      <span className="more-link">
                        详情 <ChevronRight size={14} />
                      </span>
                    )}
                  </div>
                  <h3 className="card-title">{item.title}</h3>
                  <p className="card-detail">{item.detail}</p>

                  {item.needsConfirmation ? (
                    <div className="confirm-inline-bar">
                      <span className="prompt-text">确认沉淀到记忆？</span>
                      <div className="btn-group">
                        <button className="mini-icon-btn check" onClick={(e) => handleConfirm(e, item.id, true)} aria-label="确认">
                          <Check size={14} />
                        </button>
                        <button className="mini-icon-btn close" onClick={(e) => handleConfirm(e, item.id, false)} aria-label="忽略">
                          <X size={14} />
                        </button>
                      </div>
                    </div>
                  ) : item.statusText ? (
                    <span className="status-note">{item.statusText}</span>
                  ) : null}
                </article>
              </motion.div>
            ))}
          </motion.div>
        </AnimatePresence>
      </div>

      <div className={`floating-day-switcher ${scrubberOpen ? "open" : ""}`}>
        <AnimatePresence>
          {scrubberOpen && (
            <motion.div
              className="floating-day-panel"
              initial={{ opacity: 0, y: 14, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 10, scale: 0.98 }}
              transition={{ type: "spring", duration: 0.32, bounce: 0.08 }}
            >
              <div
                className="floating-scrubber"
                role="listbox"
                aria-label="滑动切换日期"
                tabIndex={0}
              >
                {timelineDays.map((day, index) => (
                  <div
                    key={day.id}
                    className={`floating-scrubber-mark ${day.id === selectedDay.id ? "active" : ""}`}
                    onClick={() => setSelectedDayId(day.id)}
                    style={{
                      "--wave": `${Math.max(12, 42 - Math.abs(index - selectedDayIndex) * 8)}px`,
                      "--distance": Math.abs(index - selectedDayIndex)
                    }}
                  >
                    <i></i>
                    <span>{day.day}</span>
                  </div>
                ))}
              </div>
              <small>上下滑动</small>
            </motion.div>
          )}
        </AnimatePresence>
        <button
          type="button"
          className="day-switch-toggle"
          aria-label={scrubberOpen ? "收起日期滑条" : "展开日期滑条"}
          aria-expanded={scrubberOpen}
          onClick={() => setScrubberOpen(open => !open)}
        >
          <span className="switch-chevron" aria-hidden="true"></span>
        </button>
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
          <span>生活中的一切</span>
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
              <span className="label">当前记录位置</span>
              <span className="val">{data.currentLocation}</span>
            </div>
          </div>

          <div className="micro-timeline">
            <h4>物品轨迹</h4>
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
            <h3>待确认线索</h3>
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
  const iconWeight = (tab) => activeTab === tab ? "duotone" : "regular";

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
          <Compass size={22} weight={iconWeight("agent")} />
          <span>顾问</span>
        </button>
        <button className={`dock-item ${activeTab === 'timeline' ? 'active' : ''}`} onClick={() => navigate("/timeline")}>
          <Path size={22} weight={iconWeight("timeline")} />
          <span>轨迹</span>
        </button>
        <button className={`dock-item ${activeTab === 'galaxy' ? 'active' : ''}`} onClick={() => navigate("/galaxy")}>
          <CirclesFour size={22} weight={iconWeight("galaxy")} />
          <span>全览</span>
        </button>
        <button className={`dock-item ${activeTab === 'my' ? 'active' : ''}`} onClick={() => navigate("/my")}>
          <UserCircle size={22} weight={iconWeight("my")} />
          <span>我的</span>
        </button>
      </nav>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/icon-preview" element={<IconPreview />} />
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
