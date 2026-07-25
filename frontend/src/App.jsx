import { useState, useEffect, useRef, useCallback, useMemo } from "react";
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
import XRRoomPreview from "./XRRoomPreview";
import PicoMode from "./PicoMode";
import { whereIs, recentEvents, objectTimeline, evidenceUrl, apiUrl, transcribe } from "./api";
import { PreviewImage } from "./ImageLightbox";

const timelineDays = [
  {
    id: "2025-11-29",
    month: "十一月",
    day: 29,
    weekday: "周六",
    title: "休息与整理",
    summary: "早上补觉，下午进行了简短的家务整理。",
    intensity: 0.2,
    confirmations: 0,
    places: ["卧室", "客厅"],
    events: [
      {
        event_id: "m-d1129-1",
        event_time_from: "2025-11-29T10:46:00Z",
        event_type: "OBJECT_OBSERVED_AT",
        entity_name: "手机",
        location: "卧室",
        payload: { detail: "卧室环境音变弱，推测结束一段较长休息。" },
        confidence: 0.95,
      },
      {
        event_id: "m-d1129-2",
        event_time_from: "2025-11-29T17:20:00Z",
        event_type: "OBJECT_OBSERVED_AT",
        entity_name: "水杯、纸巾",
        location: "客厅",
        payload: { detail: "连续移动水杯、纸巾和遥控器，客厅桌面状态更新。" },
        confidence: 0.88,
      }
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
    events: [
      {
        event_id: "m-d1130-1",
        event_time_from: "2025-11-30T09:12:00Z",
        event_type: "OBJECT_OBSERVED_AT",
        entity_name: "背包、钥匙",
        location: "玄关",
        payload: { detail: "背包、钥匙、水杯被连续带离玄关。" },
        confidence: 0.9,
      },
      {
        event_id: "m-d1130-2",
        event_time_from: "2025-11-30T21:08:00Z",
        event_type: "OBJECT_MISSING",
        entity_name: "水杯",
        location: "包内?",
        payload: { detail: "回家后未再次捕获水杯，建议确认是否仍在包里。" },
        confidence: 0.6,
        needsConfirmation: true
      }
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
    events: [
      {
        event_id: "m-d1201-1",
        event_time_from: "2025-12-01T09:40:00Z",
        event_type: "USER_STATE",
        entity_name: "工作环境",
        location: "书房",
        payload: { detail: "键盘输入持续，背景噪声稳定，系统标记为一段连续工作。" },
        confidence: 0.99,
      },
      {
        event_id: "m-d1201-2",
        event_time_from: "2025-12-01T15:28:00Z",
        event_type: "OBJECT_MOVED",
        entity_name: "充电器",
        location: "工作桌下方",
        payload: { detail: "充电器从书房桌面移动到工作桌下方。" },
        confidence: 0.92,
        entity_id: "mock-charger"
      }
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


function pickRecordingMime() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  return candidates.find(t => window.MediaRecorder?.isTypeSupported?.(t)) || "";
}

const FALLBACK_ANSWER = "最后一次确认在客厅工作桌下方。今天 10:18 之后没有新的移动记录。";
const INITIAL_GREETING = "我在。你可以直接问现实里的事。";

export const mockWhereIs = async (name) => {
  await new Promise(resolve => setTimeout(resolve, 320));
  if (/身份证|证件/.test(name)) {
    return {
      answer_text: "最后一次确认在书房右侧抽屉的证件袋里。下面是昨天记录到的位置画面。",
      media: [
        {
          id: "mock-id-card-location",
          type: "image",
          url: "/mock/id-card-location.png",
          alt: "书房抽屉内的证件袋",
          captured_at: "昨天 21:46",
          source_label: "书房右侧抽屉",
        },
      ],
    };
  }
  return { answer_text: FALLBACK_ANSWER, media: [] };
};

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
  const recorderRef = useRef(null);
  const [notice, setNotice] = useState("");
  const reduceMotion = useReducedMotion();

  useEffect(() => () => {
    const rec = recorderRef.current;
    if (rec && rec.state !== "inactive") rec.stop();
    rec?.stream?.getTracks?.().forEach(t => t.stop());
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

  const handleVoice = async () => {
    if (listening) {
      if (recorderRef.current?.state === "recording") recorderRef.current.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      const mime = pickRecordingMime();
      const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      recorderRef.current = rec;
      const chunks = [];
      rec.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach(t => t.stop());
        const blob = new Blob(chunks, { type: rec.mimeType });
        if (blob.size < 400) {
          setListening(false);
          return;
        }
        setIsTyping(true);
        setListening(false);
        try {
          const { transcribe } = await import("./api");
          const text = await transcribe(blob);
          if (text) {
            handleSend(text);
          } else {
            setIsTyping(false);
          }
        } catch (err) {
          console.warn("Transcription failed, falling back", err);
          handleSend("我的充电器在哪里？");
        }
      };
      rec.start();
      setListening(true);
      setNotice("");
    } catch (err) {
      setNotice("无法使用麦克风");
      setListening(false);
    }
  };

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
      {notice && <div className="toast-notice">{notice}</div>}
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
  
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState(null);

  useEffect(() => {
    let alive = true;
    recentEvents(100)
      .then(data => { if (alive) { setEvents(data.events); setApiError(null); } })
      .catch(e => { if (alive) setApiError(String(e.message || e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const realTimelineDays = useMemo(() => {
    if (!events.length) return [];
    const daysMap = new Map();
    events.forEach(ev => {
      const date = new Date(ev.event_time_from);
      if (Number.isNaN(date.getTime())) return;
      const dayId = date.toISOString().split("T")[0];
      if (!daysMap.has(dayId)) {
        daysMap.set(dayId, {
          id: dayId,
          month: date.toLocaleDateString("zh-CN", { month: "long" }),
          day: date.getDate(),
          weekday: date.toLocaleDateString("zh-CN", { weekday: "short" }),
          events: []
        });
      }
      daysMap.get(dayId).events.push(ev);
    });
    return Array.from(daysMap.values()).sort((a, b) => b.id.localeCompare(a.id));
  }, [events]);

  const activeTimelineDays = realTimelineDays.length > 0 ? realTimelineDays : timelineDays; // fallback to mock timelineDays if empty/error

  const [selectedDayId, setSelectedDayId] = useState("");
  const [scrubberOpen, setScrubberOpen] = useState(false);
  const floatingScrubberRef = useRef(null);
  const [itemsByDay, setItemsByDay] = useState(() => Object.fromEntries(activeTimelineDays.map(day => [day.id, day.events])));
  useEffect(() => { if (activeTimelineDays.length > 0 && !selectedDayId) setSelectedDayId(activeTimelineDays[0].id); }, [activeTimelineDays, selectedDayId]);

  const selectedDay = activeTimelineDays.find(day => day.id === selectedDayId) || activeTimelineDays[0];
  const selectedItems = itemsByDay[selectedDay.id] || [];
  const selectedDayIndex = Math.max(0, activeTimelineDays.findIndex(day => day.id === selectedDay.id));

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
            
            {apiError && <div className="timeline-hint error" style={{marginBottom:10, fontSize:12}}><p>未能连接到后端，展示离线数据。</p><small>{apiError}</small></div>}
            
            {selectedDay.events ? (
              // Real data render
              <div className="real-events-list">
                {(() => {
                  const groups = [];
                  for (const ev of selectedDay.events) {
                    const last = groups[groups.length - 1];
                    if (last && ev.frame_asset_id && last.frameId === ev.frame_asset_id) last.events.push(ev);
                    else groups.push({ frameId: ev.frame_asset_id, events: [ev] });
                  }
                  return groups;
                })().map((group, index) => {
                  const head = group.events[0];
                  const multi = group.events.length > 1;
                  const clockText = (iso) => {
                    const t = new Date(iso);
                    return Number.isNaN(t.getTime()) ? "" : t.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
                  };
                  const EVENT_LABEL = {
                    OBJECT_OBSERVED_AT: "看到",
                    OBJECT_MOVED: "移动",
                    USER_CORRECTION: "你纠正过",
                    PREFERENCE_STATED: "偏好",
                    TASK_STATED: "待办",
                    CONSUMABLE_LEVEL_OBSERVED: "余量",
                  };
                  const eventLabel = (type) => EVENT_LABEL[type] || type;
                  const detailText = (payload = {}, location) => {
                    const extras = Object.entries(payload)
                      .filter(([k, v]) => !["location", "object_text", "field", "value", "reason"].includes(k) && v)
                      .filter(([, v]) => typeof v !== "boolean")
                      .map(([, v]) => (Array.isArray(v) ? v.join("、") : String(v)));
                    return [location, ...extras].filter(Boolean).join(" · ");
                  };

                  return (
                    <motion.div layout key={head.event_id} className="timeline-node" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.025, duration: 0.18 }}>
                      <div className="node-time-badge"><span className="time-text">{clockText(head.event_time_from)}</span></div>
                      <div className="node-bullet tone-green"></div>
                      <div className={`dark-card tone-green ${head.entity_id ? "clickable" : ""} ${head.superseded ? "superseded" : ""}`} onClick={() => head.entity_id && setSelectedObject(head.entity_id)}>
                        <div className="card-with-thumb">
                          {head.frame_asset_id && (
                            head.evidence_url ? (
                              <PreviewImage className="event-thumb" src={evidenceUrl(head.frame_asset_id)} alt="来源画面" caption="来源画面" loading="lazy" />
                            ) : <span className="event-thumb gone" title="原图已删" />
                          )}
                          <div className="card-with-thumb-body">
                            <div className="card-top-row">
                              <span className="card-title">{multi ? `这一眼看到 ${group.events.length} 件东西` : `${head.entity_name} · ${eventLabel(head.event_type)}`}</span>
                            </div>
                            {multi ? (
                              <ul className="frame-objects">
                                {group.events.map(ev => (
                                  <li key={ev.event_id} className={ev.superseded ? "superseded" : ""} onClick={(e) => { e.stopPropagation(); if (ev.entity_id) setSelectedObject(ev.entity_id); }}>
                                    <b>{ev.entity_name}</b><span>{detailText(ev.payload, ev.location) || "没有位置信息"}</span><em>{Math.round(ev.confidence * 100)}%</em>
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <>
                                <p className="card-detail">{detailText(head.payload, head.location) || "没有位置信息"}</p>
                                <div className="card-badges">
                                  {head.superseded && <span className="status-note">已被更新</span>}
                                  {head.user_confirmed && <span className="status-note confirmed">你确认过</span>}
                                  <span className="conf-note">置信度 {Math.round(head.confidence * 100)}%</span>
                                </div>
                              </>
                            )}
                          </div>
                        </div>
                      </div>
                    </motion.div>
                  );
                })}
              </div>
            ) : (
              // Mock data render (Original)
              selectedItems.map((item, index) => (

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
            ))
            )}
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
                {activeTimelineDays.map((day, index) => (
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
  const [realData, setRealData] = useState(null);
  const [apiError, setApiError] = useState(null);

  useEffect(() => {
    let alive = true;
    setRealData(null);
    setApiError(null);
    objectTimeline(objectName)
      .then(d => { if (alive) setRealData(d); })
      .catch(e => { if (alive) setApiError(String(e.message || e)); });
    return () => { alive = false; };
  }, [objectName]);

  const useMock = apiError || (!realData?.events?.length && !realData?.projection);
  const data = useMock ? mockObjectDetails[objectName] || { 
    name: objectName, 
    category: "现实物品", 
    currentLocation: "已知位置", 
    lastUpdated: "刚才",
    history: [{ time: "刚才", action: "状态确认", detail: "记录于当前上下文" }] 
  } : realData;

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
          {apiError && <p className="timeline-hint error" style={{marginBottom:10, fontSize:12}}>后端连接失败，展示离线数据。{apiError}</p>}
          
          {!useMock ? (
            <>
              <div className="status-card-box">
                <MapPin size={16} color="var(--green)" />
                <div>
                  <span className="label">{data?.projection?.location ? "最后一次看到" : "位置"}</span>
                  <span className="val">{data?.projection?.location || "没有解析出位置"}</span>
                </div>
              </div>
              <div className="micro-timeline">
                <h4>微观轨迹（{data?.events?.length || 0} 条事件）</h4>
                {!(data?.events?.length) && <p className="detail">还没有事件。</p>}
                {[...(data?.events || [])].reverse().map((ev) => {
                  const EVENT_LABEL = { OBJECT_OBSERVED_AT: "看到", OBJECT_MOVED: "移动", USER_CORRECTION: "你纠正过", PREFERENCE_STATED: "偏好", TASK_STATED: "待办", CONSUMABLE_LEVEL_OBSERVED: "余量" };
                  const clockText = (iso) => { const t = new Date(iso); return Number.isNaN(t.getTime()) ? "" : t.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }); };
                  return (
                    <div key={ev.event_id} className={`timeline-item ${ev.superseded_by ? "superseded" : ""}`}>
                      <div className="item-left">
                        <span className="time">{clockText(ev.event_time_from)}</span>
                        <div className="line-dot"></div>
                      </div>
                      <div className="item-right">
                        <div className="card-with-thumb">
                          {ev.frame_asset_id && (
                            ev.evidence_url ? (
                              <PreviewImage className="event-thumb sm" src={evidenceUrl(ev.frame_asset_id)} alt="截图" />
                            ) : <span className="event-thumb sm gone" />
                          )}
                          <div className="card-with-thumb-body">
                            <span className="action">{EVENT_LABEL[ev.event_type] || ev.event_type}</span>
                            <p className="detail">{ev.location || "没有记录位置"}</p>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          ) : (
            // Mock render
          <>
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
          </>
                  )}
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
      <Route path="/xr-room" element={<XRRoomPreview />} />
      <Route path="/pico" element={<PicoMode />} />
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
