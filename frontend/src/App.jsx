import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Routes, Route, Navigate, Outlet, useNavigate, useLocation, useOutletContext, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  Check,
  ChevronRight,
  House,
  Keyboard,
  MapPin,
  Maximize2,
  Mic,
  Send,
  X,
} from "lucide-react";
import { CirclesFour, Path, Robot, UserCircle } from "@phosphor-icons/react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import "./styles.css";
import TopologyGraph, { demoGraphObjectTimeline } from "./TopologyGraph";
import LiveView from "./LiveView";
import CaptureConsole from "./CaptureConsole";
import MediaLibrary from "./MediaLibrary";
import PreferencePanel from "./PreferencePanel";
import PresenceOrb from "./PresenceOrb";
import MyPage from "./MyPage";
import LifeHome from "./LifeHome";
import PicoMode from "./PicoMode";
import XRRoomPreview from "./XRRoomPreview";
import { LightboxProvider, PreviewImage } from "./ImageLightbox";
import { askAgent, recentEvents, objectTimeline, listClues, resolveClue, evidenceUrl, apiUrl } from "./api";

// 事件类型 → 人话。后端的事件类型是契约的一部分，不该直接漏到界面上。
const EVENT_LABEL = {
  OBJECT_OBSERVED_AT: "看到",
  OBJECT_MOVED: "移动",
  USER_CORRECTION: "你纠正过",
  PREFERENCE_STATED: "偏好",
  TASK_STATED: "待办",
  CONSUMABLE_LEVEL_OBSERVED: "余量",
};

const CLUE_SOURCE_LABEL = { perception: "采集时看到", query: "问答时推断" };
const TIMELINE_KIND_LABEL = {
  OBJECT_OBSERVED_AT: "物",
  OBJECT_MOVED: "物",
  CONSUMABLE_LEVEL_OBSERVED: "物",
  PREFERENCE_STATED: "偏好",
  TASK_STATED: "任务",
  USER_CORRECTION: "纠正",
};

function eventLabel(type) {
  return EVENT_LABEL[type] || type;
}

function timelineKindLabel(type) {
  return TIMELINE_KIND_LABEL[type] || eventLabel(type);
}

/** 事件/线索卡片的正文：位置 + payload 里的附加属性（颜色、状态、姿态…）。
 *
 *  只渲染值本身、不渲染键名——键名是英文的（has_straw、position），摆到中文界面上很突兀。
 *  代价是布尔值没法显示：`has_straw: true` 只能渲染成「true」，那不是人话。宁可不显示，
 *  也不要为了凑一行字给每个键硬编一份中文标签——payload 的键是 VLM 现场生成的，编不完。 */
function detailText(payload = {}, location) {
  if (payload.preference) return String(payload.preference);
  if (typeof payload.value === "string" || typeof payload.value === "number") {
    return String(payload.value);
  }
  const extras = Object.entries(payload)
    .filter(([k, v]) => !["location", "object_text", "field", "value", "reason"].includes(k) && v)
    .filter(([, v]) => typeof v !== "boolean")
    .map(([, v]) => (Array.isArray(v) ? v.join("、") : String(v)));
  return [location, ...extras].filter(Boolean).join(" · ");
}

function clueStatement(clue) {
  if (clue.event_type === "PREFERENCE_STATED") {
    const preference = clue.payload?.preference || clue.payload?.value || "";
    return [clue.object_text, preference].filter(Boolean).join(" · ");
  }
  return [clue.object_text, clue.location ? `在${clue.location}` : ""].filter(Boolean).join(" ");
}

/** 把连着的、出自同一帧的事件并成一组。
 *
 *  一次观察本来就产生 N 条观测（一眼看到桌上四样东西）。摊成 N 张卡片的话，同一张
 *  照片会连着重复 N 次，读起来像系统看了 N 眼——那是错的。合成一张「这一眼看到了…」
 *  才对得上实际发生的事。
 *
 *  只合并**连续**的同帧事件，不跨时间归并：时序是这条流的全部意义，不能为了去重打乱它。 */
function groupByFrame(events) {
  const groups = [];
  for (const ev of events) {
    const last = groups[groups.length - 1];
    if (last && ev.frame_asset_id && last.frameId === ev.frame_asset_id) {
      last.events.push(ev);
    } else {
      groups.push({ frameId: ev.frame_asset_id, events: [ev] });
    }
  }
  return groups;
}

function clockText(iso) {
  const t = new Date(iso);
  return Number.isNaN(t.getTime()) ? "" : t.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function nowText() {
  return new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function dayText(iso) {
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  const today = new Date();
  const sameDay = t.toDateString() === today.toDateString();
  return sameDay ? "今天" : t.toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
}

function demoTime(dayOffset, hour, minute) {
  const value = new Date();
  value.setDate(value.getDate() + dayOffset);
  value.setHours(hour, minute, 0, 0);
  return value.toISOString();
}

// 后端不可达时才使用。字段与真实 MemoryEvent 保持一致，因此演示与真实数据共用一套卡片。
const DEMO_TIMELINE_EVENTS = [
  {
    event_id: "demo-keys",
    entity_id: "demo-keys",
    entity_name: "家门钥匙",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(0, 8, 12),
    frame_asset_id: "demo-entrance-frame",
    demo_evidence_url: "/assets/pico/inventory/items/keys.png",
    evidence_url: true,
    location: "玄关托盘",
    payload: { position: "托盘内侧" },
    confidence: 0.94,
    superseded: false,
    user_confirmed: true,
  },
  {
    event_id: "demo-wallet",
    entity_id: "demo-wallet",
    entity_name: "钱包",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(0, 8, 12),
    frame_asset_id: "demo-entrance-frame",
    demo_evidence_url: "/assets/pico/inventory/items/keys.png",
    evidence_url: true,
    location: "玄关托盘",
    payload: { position: "钥匙旁" },
    confidence: 0.88,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-water-bottle-today",
    entity_id: "demo-water-bottle",
    entity_name: "水杯",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(0, 10, 4),
    frame_asset_id: "demo-desk-frame-today",
    demo_evidence_url: "/assets/pico/inventory/items/water-bottle.png",
    evidence_url: true,
    location: "书房工作桌",
    payload: { position: "笔记本电脑右侧" },
    confidence: 0.91,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-charger-moved",
    entity_id: "demo-charger",
    entity_name: "充电器",
    event_type: "OBJECT_MOVED",
    event_time_from: demoTime(-1, 18, 46),
    frame_asset_id: null,
    evidence_url: null,
    location: "书房工作桌下方",
    payload: { reason: "从桌面移动到桌下" },
    confidence: 0.87,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-laptop-yesterday",
    entity_id: "demo-laptop",
    entity_name: "笔记本电脑",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-1, 9, 10),
    frame_asset_id: "demo-work-frame-yesterday",
    demo_evidence_url: "/assets/pico/inventory/items/laptop.png",
    evidence_url: true,
    location: "书房工作桌",
    payload: { position: "桌面中央" },
    confidence: 0.96,
    superseded: false,
    user_confirmed: true,
  },
  {
    event_id: "demo-headphones-yesterday",
    entity_id: "demo-headphones",
    entity_name: "耳机",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-1, 9, 10),
    frame_asset_id: "demo-work-frame-yesterday",
    demo_evidence_url: "/assets/pico/inventory/items/laptop.png",
    evidence_url: true,
    location: "书房工作桌",
    payload: { position: "显示器旁" },
    confidence: 0.89,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-charger-correction",
    entity_id: "demo-charger",
    entity_name: "充电器",
    event_type: "USER_CORRECTION",
    event_time_from: demoTime(-2, 21, 6),
    frame_asset_id: null,
    evidence_url: null,
    location: "书房",
    payload: { field: "location", value: "工作桌下方" },
    confidence: 1,
    superseded: false,
    user_confirmed: true,
  },
  {
    event_id: "demo-sunscreen",
    entity_id: "demo-sunscreen",
    entity_name: "防晒霜",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-2, 8, 20),
    frame_asset_id: "demo-dresser-frame",
    demo_evidence_url: "/assets/pico/inventory/items/sunscreen.png",
    evidence_url: true,
    location: "卧室梳妆台",
    payload: { position: "镜子左侧" },
    confidence: 0.93,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-serum",
    entity_id: "demo-serum",
    entity_name: "精华液",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-2, 8, 20),
    frame_asset_id: "demo-dresser-frame",
    demo_evidence_url: "/assets/pico/inventory/items/sunscreen.png",
    evidence_url: true,
    location: "卧室梳妆台",
    payload: { position: "防晒霜旁" },
    confidence: 0.86,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-lunch-preference",
    entity_id: "demo-hulatang",
    entity_name: "胡辣汤",
    event_type: "PREFERENCE_STATED",
    event_time_from: demoTime(-3, 12, 30),
    frame_asset_id: null,
    evidence_url: null,
    location: "餐桌",
    payload: { value: "不喜欢这家外卖的味道" },
    confidence: 0.82,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-keys-old",
    entity_id: "demo-keys",
    entity_name: "家门钥匙",
    event_type: "OBJECT_MOVED",
    event_time_from: demoTime(-3, 20, 40),
    frame_asset_id: "demo-keys-old-frame",
    demo_evidence_url: "/assets/pico/inventory/items/keys.png",
    evidence_url: true,
    location: "餐桌边",
    payload: { position: "购物袋旁" },
    confidence: 0.79,
    superseded: true,
    user_confirmed: false,
  },
  {
    event_id: "demo-umbrella",
    entity_id: "demo-umbrella",
    entity_name: "雨伞",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-3, 8, 5),
    frame_asset_id: "demo-entry-frame-old",
    demo_evidence_url: "/assets/pico/inventory/items/umbrella.png",
    evidence_url: true,
    location: "玄关",
    payload: { position: "入户门右侧" },
    confidence: 0.9,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-task",
    entity_id: "demo-task-passport",
    entity_name: "护照",
    event_type: "TASK_STATED",
    event_time_from: demoTime(-4, 16, 20),
    frame_asset_id: null,
    evidence_url: null,
    location: "书房",
    payload: { value: "周五前确认签证材料" },
    confidence: 0.9,
    superseded: false,
    user_confirmed: true,
  },
  {
    event_id: "demo-passport-observed",
    entity_id: "demo-task-passport",
    entity_name: "护照",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-4, 8, 45),
    frame_asset_id: "demo-documents-frame",
    demo_evidence_url: "/assets/pico/inventory/items/passport.png",
    evidence_url: true,
    location: "书房文件柜",
    payload: { position: "签证材料上方" },
    confidence: 0.95,
    superseded: false,
    user_confirmed: true,
  },
  {
    event_id: "demo-phone-observed",
    entity_id: "demo-phone",
    entity_name: "备用手机",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-4, 8, 45),
    frame_asset_id: "demo-documents-frame",
    demo_evidence_url: "/assets/pico/inventory/items/passport.png",
    evidence_url: true,
    location: "书房文件柜",
    payload: { position: "护照右侧" },
    confidence: 0.83,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-tissue",
    entity_id: "demo-tissue",
    entity_name: "纸巾",
    event_type: "CONSUMABLE_LEVEL_OBSERVED",
    event_time_from: demoTime(-5, 10, 8),
    frame_asset_id: null,
    evidence_url: null,
    location: "客厅柜内",
    payload: { value: "可能只剩最后一包" },
    confidence: 0.76,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-water-bottle-old",
    entity_id: "demo-water-bottle",
    entity_name: "水杯",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-5, 7, 50),
    frame_asset_id: "demo-morning-frame",
    demo_evidence_url: "/assets/pico/inventory/items/water-bottle.png",
    evidence_url: true,
    location: "卧室床头柜",
    payload: { position: "手表旁" },
    confidence: 0.84,
    superseded: true,
    user_confirmed: false,
  },
  {
    event_id: "demo-watch",
    entity_id: "demo-watch",
    entity_name: "手表",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-5, 7, 50),
    frame_asset_id: "demo-morning-frame",
    demo_evidence_url: "/assets/pico/inventory/items/water-bottle.png",
    evidence_url: true,
    location: "卧室床头柜",
    payload: { position: "水杯旁" },
    confidence: 0.92,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-headphones-old",
    entity_id: "demo-headphones",
    entity_name: "耳机",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-6, 9, 12),
    frame_asset_id: null,
    evidence_url: null,
    location: "书房显示器旁",
    payload: {},
    confidence: 0.71,
    superseded: true,
    user_confirmed: false,
  },
  {
    event_id: "demo-perfume",
    entity_id: "demo-perfume",
    entity_name: "香水",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-6, 8, 35),
    frame_asset_id: "demo-cabinet-frame",
    demo_evidence_url: "/assets/pico/inventory/items/perfume.png",
    evidence_url: true,
    location: "卧室衣柜",
    payload: { position: "内侧隔板" },
    confidence: 0.88,
    superseded: false,
    user_confirmed: false,
  },
  {
    event_id: "demo-face-cream",
    entity_id: "demo-face-cream",
    entity_name: "面霜",
    event_type: "OBJECT_OBSERVED_AT",
    event_time_from: demoTime(-6, 8, 35),
    frame_asset_id: "demo-cabinet-frame",
    demo_evidence_url: "/assets/pico/inventory/items/perfume.png",
    evidence_url: true,
    location: "卧室衣柜",
    payload: { position: "香水旁" },
    confidence: 0.81,
    superseded: false,
    user_confirmed: false,
  },
];

const DEMO_PREFERENCE_CLUE = {
  candidate_id: "demo-preference-clue",
  object_text: "胡辣汤",
  event_type: "PREFERENCE_STATED",
  payload: {
    preference: "不喜欢这家外卖的味道",
    sentiment: "DISLIKE",
    intensity: 0.8,
  },
  confidence: 0.76,
  status: "PENDING",
  source: "perception",
  created_at: demoTime(0, 12, 35),
  demo: true,
};

function demoObjectTimeline(entityId) {
  const events = DEMO_TIMELINE_EVENTS
    .filter((event) => event.entity_id === entityId)
    .sort((a, b) => new Date(a.event_time_from) - new Date(b.event_time_from));
  const latest = events[events.length - 1];
  if (!latest) return null;
  return {
    entity: { canonical_name: latest.entity_name, aliases: [] },
    projection: {
      location: latest.location,
      last_seen_time: latest.event_time_from,
      confidence: latest.confidence,
      corrected: events.some((event) => event.event_type === "USER_CORRECTION"),
    },
    events: events.map((event) => ({
      ...event,
      payload: { ...event.payload, location: event.location },
      confidence: { aggregate: event.confidence },
      superseded_by: event.superseded ? "demo-newer-event" : null,
    })),
  };
}

function localDayId(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function timelineDay(date, events = []) {
  return {
    id: localDayId(date),
    month: String(date.getMonth() + 1).padStart(2, "0"),
    day: date.getDate(),
    weekday: date.toLocaleDateString("zh-CN", { weekday: "short" }),
    events,
    preferenceClues: [],
  };
}

function groupEventsByDay(events) {
  const days = new Map();
  events.forEach((event) => {
    const date = new Date(event.event_time_from);
    if (Number.isNaN(date.getTime())) return;
    const id = localDayId(date);
    if (!days.has(id)) days.set(id, timelineDay(date));
    days.get(id).events.push(event);
  });
  days.forEach((day) => {
    day.events.sort((a, b) => new Date(b.event_time_from) - new Date(a.event_time_from));
  });
  return Array.from(days.values()).sort((a, b) => b.id.localeCompare(a.id));
}

let msgSeq = 0;
const nextId = () => `m${++msgSeq}`;

function agentAnswerMeta(toolTrace) {
  const trace = [...(toolTrace || [])].reverse().find((item) => item.tool === "find_object");
  if (!trace?.result) return {};
  try {
    const result = typeof trace.result === "string" ? JSON.parse(trace.result) : trace.result;
    return {
      shot: apiUrl(result.evidence_url),
      entityId: result.entity?.id || null,
      limitations: result.limitations || [],
    };
  } catch {
    return {};
  }
}

function AgentHome() {
  const {
    messages,
    setMessages,
    isTyping,
    setIsTyping,
    setShowClues,
    setSelectedEntity,
    clueCount,
    agentSessionId,
    setAgentSessionId,
  } = useOutletContext();
  // idle | recording | asking。浏览器会边听边返回文字，不再单独等待后端转写。
  const [phase, setPhase] = useState("idle");
  const [mode, setMode] = useState("voice");   // voice | text
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");    // 麦克风/浏览器识别这类环境问题，不进对话流
  const [liveTranscript, setLiveTranscript] = useState("");
  const [previewMedia, setPreviewMedia] = useState(null);  // 答案来源画面的大图预览
  const recognitionRef = useRef(null);
  const speechTextRef = useRef("");
  const speechFinishedRef = useRef(false);
  const textInputRef = useRef(null);
  const reduceMotion = useReducedMotion();
  const busy = phase !== "idle" && phase !== "recording";
  const askingRef = useRef(false);

  // 离开这一页就终止识别，避免浏览器的麦克风状态继续亮着。
  useEffect(() => () => {
    speechFinishedRef.current = true;
    recognitionRef.current?.abort?.();
    recognitionRef.current = null;
  }, []);

  // 大图预览开着时 Esc 关闭
  useEffect(() => {
    if (!previewMedia) return undefined;
    const handleEscape = (event) => {
      if (event.key === "Escape") setPreviewMedia(null);
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [previewMedia]);

  const handleAsk = async (raw) => {
    const text = (raw || "").trim();
    if (!text || askingRef.current) return;
    askingRef.current = true;

    setNotice("");
    setDraft("");
    setLiveTranscript("");
    speechTextRef.current = "";
    // 只留最近这一轮：问句必须和答案待在一起，看不到问的是什么，答案就没有意义
    const question = { id: nextId(), text, sender: "user" };
    setMessages([question, { id: nextId(), sender: "agent", type: "thinking" }]);
    setIsTyping(true);
    setPhase("asking");

    try {
      const res = await askAgent(text, agentSessionId);
      if (res.session_id) setAgentSessionId(res.session_id);
      const answerMeta = agentAnswerMeta(res.tool_trace);
      setMessages([
        question,
        {
          id: nextId(),
          sender: "agent",
          text: res.reply,
          ...answerMeta,
        },
      ]);
    } catch (e) {
      // 这里绝不能编一个答案顶上。答不出来是事实，装作答得出来会毁掉整个产品的可信度。
      setMessages([
        question,
        { id: nextId(), sender: "agent", error: true, text: `暂时连接不到顾问：${e.message || e}` },
      ]);
    } finally {
      askingRef.current = false;
      setIsTyping(false);
      setPhase("idle");
    }
  };

  const stopRecording = () => {
    recognitionRef.current?.stop?.();
  };

  const startRecording = () => {
    setNotice("");
    setLiveTranscript("");
    speechTextRef.current = "";
    speechFinishedRef.current = false;

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setNotice("当前浏览器不支持实时语音识别。请使用最新版 Chrome 或 Edge，或改用文字输入。");
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "zh-CN";
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      recognitionRef.current = recognition;
      setPhase("recording");
    };
    recognition.onresult = (event) => {
      let text = "";
      for (let index = 0; index < event.results.length; index += 1) {
        text += event.results[index][0]?.transcript || "";
      }
      const nextText = text.trim();
      speechTextRef.current = nextText;
      setLiveTranscript(nextText);
    };
    recognition.onerror = (event) => {
      speechFinishedRef.current = true;
      recognitionRef.current = null;
      setLiveTranscript("");
      setPhase("idle");

      const errorText = {
        "not-allowed": "麦克风或语音识别权限被拒绝了。请在浏览器权限里允许后再试。",
        "service-not-allowed": "浏览器的语音识别服务不可用，请检查浏览器语音服务设置。",
        "audio-capture": "没有找到可用的麦克风。",
        "no-speech": "没有听到清晰语音，再说一次？",
        network: "实时语音识别网络不可用，请稍后重试。",
      }[event.error];
      setNotice(errorText || `实时语音识别失败：${event.error || "未知错误"}`);
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      if (speechFinishedRef.current) return;
      speechFinishedRef.current = true;

      const text = speechTextRef.current.trim();
      if (!text) {
        setLiveTranscript("");
        setNotice("没有听到清晰语音，再说一次？");
        setPhase("idle");
        return;
      }
      void handleAsk(text);
    };

    try {
      recognitionRef.current = recognition;
      setPhase("recording");
      recognition.start();
    } catch (e) {
      speechFinishedRef.current = true;
      recognitionRef.current = null;
      setPhase("idle");
      setNotice(`无法启动实时语音识别：${e.message || e}`);
    }
  };

  const voiceLabel = { recording: "正在听…点一下发送", asking: "正在翻记忆…" }[phase]
    || "轻点说话";

  // 只显示最近这一轮问答：问句必须和答案待在一起，看不到问的是什么，答案就没有意义
  const lastUser = [...messages].reverse().find(m => m.sender === "user");
  const lastAgent = [...messages].reverse().find(m => m.sender === "agent" && m.type !== "thinking");
  const thinking = isTyping || phase === "asking";
  const hasAnswered = Boolean(lastUser);
  // 答案出自的那张画面。用后端给的相对地址而不是自己拼 id：原图是否暴露由后端
  // 按身份决定（owner 才给），前端拼 id 等于绕开那道判断。原图过了 TTL 就没有这一格，
  // 但答案本身仍然成立——那时下面的 limitations 会说明这件事。
  const answerMedia = lastAgent?.shot
    ? [{ id: "evidence", url: lastAgent.shot, alt: "这个答案出自的画面" }]
    : [];

  const openKeyboard = () => {
    setMode("text");
    textInputRef.current?.focus({ preventScroll: true });
    window.requestAnimationFrame(() => {
      textInputRef.current?.focus({ preventScroll: true });
    });
  };

  const closeKeyboard = () => {
    setMode("voice");
    textInputRef.current?.blur();
  };

  const handleTextSubmit = (event) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy || phase === "recording") return;
    setMode("voice");
    textInputRef.current?.blur();
    handleAsk(text);
  };

  return (
    <div className="page-view agent-page">
      <div className="agent-orb-stage">
        <PresenceOrb state={phase === "recording" ? "listening" : thinking ? "thinking" : "idle"} />
      </div>

      <header className="top agent-top">
        <div className="brand">
          <b>顾问</b>
          <span>你的专属现实顾问</span>
        </div>
      </header>

      {/* 数量是真的：它等于系统看到了东西但不敢当成事实的次数。写死成常数就把这个信号抹掉了 */}
      {clueCount > 0 && (
        <div className="memory-hint-wrap">
          <motion.button
            className="hint-pill"
            onClick={() => setShowClues(true)}
            initial={{ opacity: 0, transform: "translateY(-14px) scale(0.96)" }}
            animate={{ opacity: 1, transform: "translateY(0px) scale(1)" }}
            transition={{ type: "spring", duration: 0.42, bounce: 0.12 }}
          >
            <span className="status-dot"></span> {clueCount} 条记忆线索待确认
          </motion.button>
        </div>
      )}

      <div
        className={`dialogue agent-dialogue ${thinking || phase === "recording" ? "is-asking" : ""} ${hasAnswered ? "has-answer" : ""}`}
        aria-live="polite"
      >
        <div className="agent-center-text agent-greeting" aria-hidden={hasAnswered}>
          {messages[0]?.text}
        </div>
        {hasAnswered && lastAgent && (
          <div key={lastAgent.id} className={`agent-center-text agent-answer-text ${lastAgent.error ? "error" : ""}`}>
            <span className="agent-answer-copy">{lastAgent.text}</span>
            {answerMedia.map((media) => (
              <button
                key={media.id}
                type="button"
                className="agent-answer-media"
                onClick={() => setPreviewMedia(media)}
                aria-label="放大查看来源画面"
              >
                <img src={media.url} alt={media.alt} />
                <span className="agent-media-zoom" aria-hidden="true">
                  <Maximize2 size={13} strokeWidth={1.8} />
                </span>
              </button>
            ))}
            {/* 平台声明的局限要原样转达，不能只把结论那句话拿出来显示 */}
            {lastAgent.limitations?.map((line, i) => (
              <span key={i} className="agent-answer-note">{line}</span>
            ))}
            {/* 答出了具体实体就给一条进轨迹的路：答案只是结论，轨迹才是它的依据 */}
            {lastAgent.entityId && (
              <button className="agent-trace-link" onClick={() => setSelectedEntity(lastAgent.entityId)}>
                看这条记忆的轨迹 <ChevronRight size={12} />
              </button>
            )}
          </div>
        )}
      </div>

      <div className="agent-user-lane" aria-live="polite">
        <AnimatePresence>
          {(phase === "recording" ? liveTranscript : lastUser?.text) && (
            <motion.div
              key="active-user-question"
              initial={reduceMotion
                ? { opacity: 0 }
                : { opacity: 0, transform: "translateY(42px) scale(0.97)", filter: "blur(5px)" }}
              animate={{ opacity: 1, transform: "translateY(0px) scale(1)", filter: "blur(0px)" }}
              transition={reduceMotion ? { duration: 0.18 } : { type: "spring", duration: 0.32, bounce: 0.1 }}
              className={`agent-user-bubble ${phase === "recording" ? "live" : ""}`}
            >
              {phase === "recording" ? liveTranscript : lastUser.text}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {notice && <p className="composer-note">{notice}</p>}

      <form
        className={`composer composer--${mode}`}
        role="group"
        aria-label={mode === "text" ? "文字输入" : "语音输入"}
        onSubmit={handleTextSubmit}
      >
        <button
          type="button"
          className={`voice ${phase === "recording" ? "listening" : ""}`}
          onClick={phase === "recording" ? stopRecording : startRecording}
          disabled={busy}
        >
          <span className="voice-label">{voiceLabel}</span>
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
          placeholder="我的充电器在哪里？"
          aria-label="输入问题"
          disabled={busy || phase === "recording"}
        />

        <button
          type={mode === "text" && draft.trim() ? "submit" : "button"}
          className="keyboard-toggle"
          onClick={mode === "voice" ? openKeyboard : draft.trim() ? undefined : closeKeyboard}
          aria-label={
            mode === "voice"
              ? "切换到文字输入"
              : draft.trim()
                ? "发送"
                : "切换到语音输入"
          }
          disabled={busy || phase === "recording"}
        >
          {mode === "voice" ? (
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
            aria-label="来源画面预览"
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
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** 轨迹按天组织：正式事件与待确认偏好共用一条时间轴。
 *
 *  同一来源帧会在这里合成一张卡；这只是展示聚合，不会改写后端的原子事件。
 *  偏好候选可由人在流里确认或否认；已经成立的事件不会再次出现确认按钮。 */
function TimelineView() {
  const { setSelectedEntity, setShowClues, clueCount, setClueCount } = useOutletContext();
  const [events, setEvents] = useState([]);
  const [preferenceClues, setPreferenceClues] = useState([]);
  const [error, setError] = useState(null);
  const [clueError, setClueError] = useState(null);
  const [busyPreferenceId, setBusyPreferenceId] = useState(null);
  const [preferenceActionErrors, setPreferenceActionErrors] = useState({});
  const [demoPreferenceResult, setDemoPreferenceResult] = useState("");
  const [loading, setLoading] = useState(true);
  const [selectedDayId, setSelectedDayId] = useState("");
  const [scrubberOpen, setScrubberOpen] = useState(false);
  const floatingScrubberRef = useRef(null);
  const scrubberDraggingRef = useRef(false);

  useEffect(() => {
    let alive = true;
    recentEvents(100)
      .then(data => { if (alive) { setEvents(data.events); setError(null); } })
      .catch(e => { if (alive) setError(String(e.message || e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true;
    listClues()
      .then(data => {
        if (!alive) return;
        setPreferenceClues(data.clues.filter(clue => clue.event_type === "PREFERENCE_STATED"));
        setClueCount(data.total);
        setClueError(null);
      })
      .catch(e => {
        if (alive) setClueError(String(e.message || e));
      });
    return () => { alive = false; };
  }, [setClueCount]);

  const isDemo = Boolean(error);
  const visibleEvents = isDemo ? DEMO_TIMELINE_EVENTS : events;
  const visiblePreferenceClues = clueError ? [DEMO_PREFERENCE_CLUE] : preferenceClues;
  const timelineDays = useMemo(() => {
    const days = groupEventsByDay(visibleEvents);
    const byId = new Map(days.map(day => [day.id, day]));
    visiblePreferenceClues.forEach((clue) => {
      const date = new Date(clue.created_at);
      if (Number.isNaN(date.getTime())) return;
      const id = localDayId(date);
      if (!byId.has(id)) {
        const day = timelineDay(date);
        days.push(day);
        byId.set(id, day);
      }
      byId.get(id).preferenceClues.push(clue);
    });
    days.sort((a, b) => b.id.localeCompare(a.id));
    return days.length > 0 ? days : [timelineDay(new Date())];
  }, [visibleEvents, visiblePreferenceClues]);

  useEffect(() => {
    if (!timelineDays.some((day) => day.id === selectedDayId)) {
      setSelectedDayId(timelineDays[0].id);
    }
  }, [selectedDayId, timelineDays]);

  const selectedDay = timelineDays.find((day) => day.id === selectedDayId) || timelineDays[0];
  const selectedDayIndex = Math.max(0, timelineDays.findIndex((day) => day.id === selectedDay.id));
  const selectedItems = useMemo(() => {
    const eventItems = groupByFrame(selectedDay.events).map(group => ({
      kind: "event",
      id: group.events[0].event_id,
      time: group.events[0].event_time_from,
      group,
    }));
    const clueItems = selectedDay.preferenceClues.map(clue => ({
      kind: "preference",
      id: clue.candidate_id,
      time: clue.created_at,
      clue,
    }));
    return [...eventItems, ...clueItems].sort(
      (a, b) => new Date(b.time) - new Date(a.time)
    );
  }, [selectedDay.events, selectedDay.preferenceClues]);
  const otherClueCount = clueCount === null
    ? 0
    : Math.max(clueCount - preferenceClues.length, 0);

  const handlePreferenceDecision = async (clue, decision) => {
    if (clue.demo) {
      setDemoPreferenceResult(
        decision === "CONFIRM" ? "已确认" : "已否认"
      );
      return;
    }

    setBusyPreferenceId(clue.candidate_id);
    setPreferenceActionErrors(prev => ({ ...prev, [clue.candidate_id]: "" }));
    try {
      await resolveClue(clue.candidate_id, decision);
      setPreferenceClues(prev => prev.filter(item => item.candidate_id !== clue.candidate_id));
      setClueCount(current => current === null ? current : Math.max(current - 1, 0));
      if (decision === "CONFIRM") {
        const latest = await recentEvents(100);
        setEvents(latest.events);
        setError(null);
      }
    } catch (e) {
      setPreferenceActionErrors(prev => ({
        ...prev,
        [clue.candidate_id]: `处理失败：${e.message || e}`,
      }));
    } finally {
      setBusyPreferenceId(null);
    }
  };

  const selectDayFromY = (clientY) => {
    const rect = floatingScrubberRef.current?.getBoundingClientRect();
    if (!rect || timelineDays.length === 0) return;
    const progress = Math.min(1, Math.max(0, (clientY - rect.top) / rect.height));
    const index = Math.round(progress * (timelineDays.length - 1));
    const nextId = timelineDays[index]?.id;
    if (nextId) setSelectedDayId((currentId) => currentId === nextId ? currentId : nextId);
  };

  const handleScrubberPointerDown = (event) => {
    event.preventDefault();
    scrubberDraggingRef.current = true;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    selectDayFromY(event.clientY);
  };

  const handleScrubberPointerMove = (event) => {
    if (!scrubberDraggingRef.current) return;
    event.preventDefault();
    selectDayFromY(event.clientY);
  };

  const handleScrubberPointerEnd = (event) => {
    scrubberDraggingRef.current = false;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    }
  };

  const stepDay = (direction) => {
    const nextIndex = Math.min(
      timelineDays.length - 1,
      Math.max(0, selectedDayIndex + direction)
    );
    const nextId = timelineDays[nextIndex]?.id;
    if (nextId) setSelectedDayId(nextId);
  };

  const handleScrubberWheel = (event) => {
    event.preventDefault();
    if (event.deltaY !== 0) stepDay(event.deltaY > 0 ? 1 : -1);
  };

  const handleScrubberKeyDown = (event) => {
    if (!["ArrowUp", "ArrowDown"].includes(event.key)) return;
    event.preventDefault();
    stepDay(event.key === "ArrowDown" ? 1 : -1);
  };

  const eventMeta = (event) => [
    `置信度 ${Math.round(event.confidence * 100)}%`,
    event.event_type === "USER_CORRECTION" ? "纠正记录" : "",
    event.user_confirmed ? "已确认" : "",
    event.superseded ? "已更新" : "",
  ].filter(Boolean).join(" · ");

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
              className="timeline-date-badge"
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 4 }}
              transition={{ duration: 0.15 }}
            >
              {selectedDay.month}.{String(selectedDay.day).padStart(2, "0")} · {selectedDay.weekday}
            </motion.div>
          </AnimatePresence>
        </div>
      </header>

      {otherClueCount > 0 && (
        <button className="timeline-clue-bar" onClick={() => setShowClues(true)}>
          <span className="status-dot"></span>
          另有 {otherClueCount} 条位置线索等待确认
          <ChevronRight size={14} />
        </button>
      )}

      <div className="timeline-container">
        {loading && <p className="timeline-hint">正在读记忆…</p>}

        {!loading && !error && events.length === 0 && preferenceClues.length === 0 && (
          <p className="timeline-hint">还没有任何记忆事件。去「采集」页拍一张，感知跑完就会出现在这里。</p>
        )}

        <AnimatePresence mode="wait">
          <motion.div
            key={selectedDay.id}
            className="timeline-list"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
          >
            {selectedItems.map((item, index) => {
              if (item.kind === "preference") {
                const clue = item.clue;
                const actionError = preferenceActionErrors[clue.candidate_id];
                const demoResult = clue.demo ? demoPreferenceResult : "";
                return (
                  <motion.div
                    layout
                    key={`preference-${clue.candidate_id}`}
                    className="timeline-node preference-candidate-node"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.025, duration: 0.18 }}
                  >
                    <div className="node-time-badge">
                      <span className="time-text">{clockText(clue.created_at)}</span>
                      <span className="period-text">偏好</span>
                    </div>
                    <div className="node-bullet pending"></div>

                    <div className="dark-card preference-candidate-card">
                      <div className="preference-candidate-copy">
                        <strong>{clue.object_text}</strong>
                        <p className="preference-statement">
                          {clue.payload?.preference || clue.payload?.value}
                        </p>
                        <span className="preference-confidence">
                          置信度 {Math.round(clue.confidence * 100)}%
                        </span>
                      </div>

                      <div className="preference-confirm-row">
                        <span>这项偏好准确吗？</span>
                        {demoResult ? (
                          <span className="preference-result">{demoResult}</span>
                        ) : (
                          <div className="preference-decision-actions">
                            <button
                              type="button"
                              className="preference-decision confirm"
                              title="确认这项偏好"
                              aria-label="确认这项偏好"
                              disabled={busyPreferenceId === clue.candidate_id}
                              onClick={() => handlePreferenceDecision(clue, "CONFIRM")}
                            >
                              <Check size={18} strokeWidth={2.4} />
                            </button>
                            <button
                              type="button"
                              className="preference-decision reject"
                              title="这项偏好不准确"
                              aria-label="这项偏好不准确"
                              disabled={busyPreferenceId === clue.candidate_id}
                              onClick={() => handlePreferenceDecision(clue, "REJECT")}
                            >
                              <X size={18} strokeWidth={2.4} />
                            </button>
                          </div>
                        )}
                      </div>

                      {actionError && <p className="preference-action-error">{actionError}</p>}
                    </div>
                  </motion.div>
                );
              }

              const group = item.group;
              const head = group.events[0];
              const multi = group.events.length > 1;
              const single = multi ? null : head;
              const canOpenSingle = Boolean(single?.entity_id);
              const groupLocations = [...new Set(
                group.events.map(event => event.location).filter(Boolean)
              )];
              const groupTitle = groupLocations.length === 1
                ? groupLocations[0]
                : "同一场景中的物品";
              const sourceImage = head.demo_evidence_url
                || (head.evidence_url && head.frame_asset_id ? evidenceUrl(head.frame_asset_id) : null);

              return (
                <motion.div
                  layout
                  key={head.event_id}
                  className="timeline-node"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.025, duration: 0.18 }}
                >
                  <div className="node-time-badge">
                    <span className="time-text">{clockText(head.event_time_from)}</span>
                    <span className="period-text">{timelineKindLabel(head.event_type)}</span>
                  </div>
                  <div className="node-bullet"></div>

                  <div
                    className={`dark-card ${canOpenSingle ? "clickable" : ""} ${single?.superseded ? "superseded" : ""}`}
                    onClick={() => canOpenSingle && setSelectedEntity(single.entity_id)}
                    onKeyDown={(event) => {
                      if (!canOpenSingle || !["Enter", " "].includes(event.key)) return;
                      event.preventDefault();
                      setSelectedEntity(single.entity_id);
                    }}
                    role={canOpenSingle ? "button" : undefined}
                    tabIndex={canOpenSingle ? 0 : undefined}
                  >
                    {multi ? (
                      <div className="frame-card">
                        <div className="frame-card-head">
                          {head.frame_asset_id && (
                            sourceImage ? (
                              <PreviewImage
                                className="event-thumb frame-source-thumb"
                                src={sourceImage}
                                alt="场景来源画面"
                                caption={`${groupTitle} · ${group.events.length} 件物品 · ${clockText(head.event_time_from)}`}
                                loading="lazy"
                              />
                            ) : (
                              <span className="event-thumb frame-source-thumb gone" title="原图已按保留期删除，记忆本身还在" />
                            )
                          )}
                          <div className="frame-card-summary">
                            <span className="card-title">{groupTitle}</span>
                            <small>{group.events.length} 件物品 · 点击查看轨迹</small>
                          </div>
                        </div>
                        <ul className="frame-objects">
                          {group.events.map((event) => (
                            <li key={event.event_id} className={event.superseded ? "superseded" : ""}>
                              <button
                                type="button"
                                onClick={(clickEvent) => {
                                  clickEvent.stopPropagation();
                                  if (event.entity_id) setSelectedEntity(event.entity_id);
                                }}
                              >
                                <b>{event.entity_name}</b>
                                <span>{detailText(event.payload, event.location) || "没有位置信息"}</span>
                                <em>{eventMeta(event)}</em>
                              </button>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : (
                      <div className="card-with-thumb">
                        {head.frame_asset_id && (
                          sourceImage ? (
                            <PreviewImage
                              className="event-thumb"
                              src={sourceImage}
                              alt={`${head.entity_name}的来源画面`}
                              caption={`${head.entity_name} · ${clockText(head.event_time_from)}`}
                              loading="lazy"
                            />
                          ) : (
                            <span className="event-thumb gone" title="原图已按保留期删除，记忆本身还在" />
                          )
                        )}
                        <div className="card-with-thumb-body">
                          <div className="card-top-row">
                            <span className="card-title">{head.entity_name}</span>
                            {canOpenSingle && (
                              <span className="more-link">
                                详情 <ChevronRight size={14} />
                              </span>
                            )}
                          </div>
                          <p className="card-detail">
                            {detailText(head.payload, head.location) || "没有位置信息"}
                          </p>
                          <div className="card-badges">
                            {head.event_type === "USER_CORRECTION" && <span className="status-note">纠正记录</span>}
                            {head.superseded && <span className="status-note">已被后续记忆更新</span>}
                            {head.user_confirmed && <span className="status-note confirmed">你确认过</span>}
                            <span className="conf-note">置信度 {Math.round(head.confidence * 100)}%</span>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </motion.div>
              );
            })}

            {isDemo && (
              <div className="timeline-hint error timeline-demo-note">
                <p>后端暂时不可达，以上为演示轨迹，不会写入记忆。</p>
              </div>
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
                ref={floatingScrubberRef}
                className="floating-scrubber"
                role="slider"
                aria-label="上下滑动切换日期"
                aria-valuemin={1}
                aria-valuemax={timelineDays.length}
                aria-valuenow={selectedDayIndex + 1}
                tabIndex={0}
                onPointerDown={handleScrubberPointerDown}
                onPointerMove={handleScrubberPointerMove}
                onPointerUp={handleScrubberPointerEnd}
                onPointerCancel={handleScrubberPointerEnd}
                onWheel={handleScrubberWheel}
                onKeyDown={handleScrubberKeyDown}
              >
                {timelineDays.map((day, index) => (
                  <div
                    key={day.id}
                    className={`floating-scrubber-mark ${day.id === selectedDay.id ? "active" : ""}`}
                    style={{
                      "--wave": `${Math.max(12, 42 - Math.abs(index - selectedDayIndex) * 8)}px`,
                      "--distance": Math.abs(index - selectedDayIndex),
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
          aria-label={scrubberOpen ? "收起日期拨片" : "展开日期拨片"}
          aria-expanded={scrubberOpen}
          onClick={() => setScrubberOpen((open) => !open)}
        >
          <span className="switch-chevron" aria-hidden="true"></span>
        </button>
      </div>
    </div>
  );
}

function GalaxyView() {
  const { setSelectedEntity } = useOutletContext();
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
      <TopologyGraph onOpenItem={setSelectedEntity}/>
      <PreferencePanel />
    </div>
  );
}

/** 物品抽屉：单个实体的当前投影 + 完整事件轨迹。
 *
 *  「当前确切位置」这个说法在真实数据下会撒谎——投影可能是空的（有观察但没解析出位置），
 *  也可能已经过时几天。所以位置旁边一定要带上是什么时候看到的，以及是不是被纠正过。 */
function ObjectDrawer({ entityId, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    setError(null);
    if (entityId?.startsWith("demo-")) {
      const demoData = demoObjectTimeline(entityId) || demoGraphObjectTimeline(entityId);
      if (demoData) setData(demoData);
      else setError("演示轨迹中没有这个物品。");
      return () => { alive = false; };
    }
    objectTimeline(entityId)
      .then(d => { if (alive) setData(d); })
      .catch(e => { if (alive) setError(String(e.message || e)); });
    return () => { alive = false; };
  }, [entityId]);

  const projection = data?.projection || {};
  // 事件按时间正序存，轨迹要倒着看：最近发生的在最上面
  const history = [...(data?.events || [])].reverse();

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-sheet dark-sheet" onClick={e => e.stopPropagation()}>
        <div className="drawer-handle"></div>
        <div className="drawer-header">
          <div>
            <h3>{data?.entity?.canonical_name || (error ? "读不到这个物品" : "载入中…")}</h3>
            {data?.entity?.aliases?.length > 0 && (
              <span className="category-pill">也叫 {data.entity.aliases.join("、")}</span>
            )}
            {projection.corrected && <span className="category-pill">你纠正过</span>}
          </div>
          <button className="close-btn" onClick={onClose}><X size={18}/></button>
        </div>

        <div className="drawer-body">
          {error && <p className="timeline-hint error">{error}</p>}

          {data && (
            <>
              <div className="status-card-box">
                <MapPin size={16} color="var(--green)" />
                <div>
                  <span className="label">
                    {projection.location ? "最后一次看到" : "位置"}
                  </span>
                  <span className="val">{projection.location || "没有解析出位置"}</span>
                  {/* 新鲜度不是装饰：不说什么时候看到的，「当前位置」就是在暗示它还在那 */}
                  {projection.last_seen_time && (
                    <span className="label">
                      {dayText(projection.last_seen_time)} {clockText(projection.last_seen_time)}
                      {projection.confidence ? ` · 置信度 ${Math.round(projection.confidence * 100)}%` : ""}
                    </span>
                  )}
                </div>
              </div>

              <div className="micro-timeline">
                <h4>微观轨迹（{history.length} 条事件）</h4>
                {history.length === 0 && <p className="detail">还没有事件。</p>}
                {history.map((ev) => (
                  <div key={ev.event_id} className={`timeline-item ${ev.superseded_by ? "superseded" : ""}`}>
                    <div className="item-left">
                      <span className="time">{clockText(ev.event_time_from)}</span>
                      <div className="line-dot"></div>
                    </div>
                    <div className="item-right">
                      <div className="card-with-thumb">
                        {/* 来源帧。轨迹里同一时刻的多条观察常出自同一帧，重复出现同一张图
                            正说明它们是同一眼看到的。纠正类事件没有来源帧，不占位。 */}
                        {ev.frame_asset_id && (
                          ev.evidence_url ? (
                            // 这里不能用 loading="lazy"：抽屉是带 slideUp 动画的覆盖层，
                            // 懒加载在动画期间算不出可见性，挂载后又没有滚动事件去补触发，
                            // 结果图永远停在「已选好 src 但从不发请求」。单个物品的轨迹条数
                            // 有限，直接加载就好。
                            <PreviewImage
                              className="event-thumb sm"
                              src={ev.demo_evidence_url || evidenceUrl(ev.frame_asset_id)}
                              alt="这条记忆的来源画面"
                              caption={`${eventLabel(ev.event_type)} · ${dayText(ev.event_time_from)} ${clockText(ev.event_time_from)}`}
                            />
                          ) : (
                            <span className="event-thumb sm gone" title="原图已按保留期删除，记忆本身还在" />
                          )
                        )}
                        <div className="card-with-thumb-body">
                          <span className="action">
                            {eventLabel(ev.event_type)}
                            {ev.superseded_by && <em> · 已被更新</em>}
                          </span>
                          <p className="detail">
                            {ev.event_type === "USER_CORRECTION"
                              ? `${ev.payload.field} → ${ev.payload.value}${ev.payload.reason ? `（${ev.payload.reason}）` : ""}`
                              : detailText(ev.payload, ev.payload.location) || "没有位置信息"}
                          </p>
                          <p className="detail muted">
                            {dayText(ev.event_time_from)} · 置信度{" "}
                            {Math.round((ev.confidence?.aggregate || 0) * 100)}%
                          </p>
                        </div>
                      </div>
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

/** 线索确认中心：候选门没敢自动接受的记忆，等人拍板。
 *
 *  点「确认」是真的写记忆——候选升级成事件、投影重算。所以这里必须等接口回来才能
 *  把卡片划掉：乐观地先移除，写失败时用户会以为已经记下了，而记忆里其实什么都没有。 */
function CluesDrawer({ onClose, onCountChange }) {
  const [clues, setClues] = useState([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);
  const [resolved, setResolved] = useState({});  // candidate_id → 处理结果文案

  useEffect(() => {
    let alive = true;
    listClues()
      .then(d => { if (alive) { setClues(d.clues); setTotal(d.total); setError(null); } })
      .catch(e => { if (alive) setError(String(e.message || e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const pending = clues.filter(c => !resolved[c.candidate_id]);

  // 角标读服务端总数减去本次处理掉的，不是读当前列表长度——/clues 有 limit，
  // 总数比这一页多的时候（现在就是），拿页长度当计数会让角标一打开抽屉就往下掉。
  const settled = Object.keys(resolved).length;
  useEffect(() => {
    onCountChange?.(Math.max(total - settled, 0));
  }, [total, settled, onCountChange]);

  const handle = async (clue, decision) => {
    setBusyId(clue.candidate_id);
    try {
      const res = await resolveClue(clue.candidate_id, decision);
      const note = decision === "CONFIRM"
        ? clue.event_type === "PREFERENCE_STATED"
          ? `已确认偏好：${res.projection?.preference || clue.payload?.preference || clue.payload?.value}`
          : `已记住：${clue.object_text}在${res.projection?.location || clue.location}`
        : "已忽略，不写入记忆";
      setResolved(prev => {
        const next = { ...prev, [clue.candidate_id]: note };
        // 确认一条会顺带把同冲突集里的其它候选判否。界面要跟上，否则它们会一直挂在
        // 那里等一个已经被解决的矛盾，用户点了也只会拿到 409。
        for (const sid of res.rejected_sibling_ids || []) next[sid] = "冲突已由上面那条解决";
        return next;
      });
    } catch (e) {
      setResolved(prev => ({ ...prev, [clue.candidate_id]: `没写成功：${e.message || e}` }));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="drawer-overlay" onClick={onClose}>
      <div className="drawer-sheet dark-sheet" onClick={e => e.stopPropagation()}>
        <div className="drawer-handle"></div>
        <div className="drawer-header">
          <div>
            <h3>线索确认中心</h3>
            <span className="sub-title">
              系统看到了，但置信度不够，不敢当成事实
            </span>
          </div>
          <button className="close-btn" onClick={onClose}><X size={18}/></button>
        </div>

        <div className="drawer-body">
          {loading && <p className="timeline-hint">正在读候选…</p>}
          {error && <p className="timeline-hint error">拿不到线索：{error}</p>}

          {!loading && !error && pending.length === 0 && clues.length === 0 && (
            <div className="empty-clues">
              <Check size={24} color="var(--green)" />
              <p>没有待确认的线索</p>
            </div>
          )}

          <div className="clues-list">
            {clues.map(c => {
              const note = resolved[c.candidate_id];
              return (
                <div key={c.candidate_id} className={`dark-clue-card ${note ? "done" : ""}`}>
                  <h4>{clueStatement(c)}</h4>
                  <p className="clue-meta">
                    {CLUE_SOURCE_LABEL[c.source] || c.source} · 置信度 {Math.round(c.confidence * 100)}%
                    {c.status === "CONFLICTED" && <em> · 与另一条记忆冲突</em>}
                  </p>

                  {/* 线索出自哪一帧。原图可能已被保留期删除，那时只剩 caption——
                      这不是加载失败，所以文字和图片要分开渲染，不能只在有图时才给说明 */}
                  {c.evidence_url && (
                    <PreviewImage
                      className="clue-thumb"
                      src={evidenceUrl(c.frame_asset_id)}
                      alt={c.frame_caption || "线索来源画面"}
                      caption={c.frame_caption || clueStatement(c)}
                      loading="lazy"
                    />
                  )}
                  {c.frame_caption && (
                    <p className="clue-caption">
                      {c.frame_caption}
                      {!c.evidence_available && <em> · 原图已按保留期删除</em>}
                    </p>
                  )}

                  {note ? (
                    <span className="status-note confirmed">{note}</span>
                  ) : (
                    <div className="clue-actions">
                      <button
                        className="action-btn confirm"
                        disabled={busyId === c.candidate_id}
                        onClick={() => handle(c, "CONFIRM")}
                      >
                        <Check size={14} /> {busyId === c.candidate_id ? "写入中…" : "确认"}
                      </button>
                      <button
                        className="action-btn deny"
                        disabled={busyId === c.candidate_id}
                        onClick={() => handle(c, "REJECT")}
                      >
                        <X size={14} /> 忽略
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
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

/** 手机壳布局：主 tab 页共用状态栏与底部 dock，页面本身交给子路由。
 *  抽屉开合也写进 query（?object=…、?clues=1），刷新和浏览器后退都能还原当时看到的界面。 */
function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const activeTab = location.pathname.split("/")[1] || "agent";
  const [messages, setMessages] = useState([
    { id: "hello", text: "我在。你可以直接问现实里的事。", sender: "agent" },
  ]);
  const [isTyping, setIsTyping] = useState(false);
  const [agentSessionId, setAgentSessionId] = useState(null);
  // null = 还没问到后端。0 和「不知道」要分开：不知道的时候不该显示「0 条待确认」
  const [clueCount, setClueCount] = useState(null);

  // 抽屉认的是 entity id 而不是物品名：名字不唯一（「纸巾」在库里就有两条候选），
  // 拿名字去查会打开错的那个物品，而 id 是事件流和拓扑图本来就带着的。
  const selectedEntity = searchParams.get("entity");
  const showClues = searchParams.get("clues") === "1";

  useEffect(() => {
    let alive = true;
    listClues().then(d => { if (alive) setClueCount(d.total); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  const [clock, setClock] = useState(() => nowText());
  useEffect(() => {
    const timer = setInterval(() => setClock(nowText()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const setParam = (key, value) => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value); else next.delete(key);
      return next;
    }, { replace: true });
  };
  const setSelectedEntity = (id) => setParam("entity", id || null);
  const setShowClues = (open) => setParam("clues", open ? "1" : null);
  const iconWeight = (tab) => (activeTab === tab ? "duotone" : "regular");
  return (
    <div className={`app-shell premium-dark mode-${activeTab}`}>
      <div className="status-bar">
        <span>RealGit</span><span>{clock}</span>
      </div>

      <main className="main-content">
        <Outlet context={{
          messages,
          setMessages,
          isTyping,
          setIsTyping,
          setSelectedEntity,
          setShowClues,
          clueCount,
          setClueCount,
          agentSessionId,
          setAgentSessionId,
        }} />
      </main>

      {selectedEntity && (
        <ObjectDrawer entityId={selectedEntity} onClose={() => setSelectedEntity(null)} />
      )}
      {showClues && (
        <CluesDrawer onClose={() => setShowClues(false)} onCountChange={setClueCount} />
      )}

      <nav className="bottom-dock premium-dock" aria-label="主要页面">
        {/* 切页只带路径不带 query：抽屉状态属于上一页，跟过去就成了幽灵弹窗 */}
        <button className={`dock-item ${activeTab === "life" ? "active" : ""}`} onClick={() => navigate("/life")}>
          <House size={21} />
          <span>生活</span>
        </button>
        <button className={`dock-item ${activeTab === "timeline" ? "active" : ""}`} onClick={() => navigate("/timeline")}>
          <Path size={22} weight={iconWeight("timeline")} />
          <span>轨迹</span>
        </button>
        <button
          className={`dock-item agent-dock-item ${activeTab === "agent" ? "active" : ""}`}
          onClick={() => navigate("/agent")}
          aria-label="打开在场顾问"
          title="在场顾问"
        >
          <span className="agent-dock-circle"><Robot size={23} weight={iconWeight("agent")} /></span>
          <span className="agent-dock-label">顾问</span>
        </button>
        <button className={`dock-item ${activeTab === "galaxy" ? "active" : ""}`} onClick={() => navigate("/galaxy")}>
          <CirclesFour size={22} weight={iconWeight("galaxy")} />
          <span>全览</span>
        </button>
        <button className={`dock-item ${activeTab === "my" ? "active" : ""}`} onClick={() => navigate("/my")}>
          <UserCircle size={22} weight={iconWeight("my")} />
          <span>我的</span>
        </button>
      </nav>
    </div>
  );
}

function App() {
  return (
    // 放在路由外层：每个页面的缩略图都能点开看原图，浮层本身不参与路由
    <LightboxProvider>
      <Routes>
        {/* 空间体验是独立入口，不替代真实物品拓扑和主应用数据流。 */}
        <Route path="/pico" element={<PicoMode />} />
        <Route path="/xr-room" element={<XRRoomPreview />} />
        <Route path="/live" element={<ConsolePage component={LiveView} />} />
        <Route path="/capture" element={<ConsolePage component={CaptureConsole} />} />
        <Route path="/media" element={<ConsolePage component={MediaLibrary} />} />
        <Route element={<AppShell />}>
          <Route path="/life" element={<LifeHome />} />
          <Route path="/agent" element={<AgentHome />} />
          <Route path="/timeline" element={<TimelineView />} />
          <Route path="/galaxy" element={<GalaxyView />} />
          <Route path="/my" element={<MyPage />} />
        </Route>
        {/* 根路径和任何认不出的 URL 都落回生活页，刷新不会白屏。 */}
        <Route path="*" element={<Navigate to="/life" replace />} />
      </Routes>
    </LightboxProvider>
  );
}

export default App;
