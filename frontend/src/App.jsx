import { useState, useEffect, useRef, useCallback } from "react";
import { Routes, Route, Navigate, Outlet, useNavigate, useLocation, useOutletContext, useSearchParams } from "react-router-dom";
import { Mic, Keyboard, CircleDot, Milestone, Sparkles, X, Check, Coffee, Zap, MapPin, SlidersHorizontal, ChevronRight, Radio, ArrowLeft, Camera, Library } from "lucide-react";
import "./styles.css";
import TopologyGraph from "./TopologyGraph";
import LiveView from "./LiveView";
import CaptureConsole from "./CaptureConsole";
import MediaLibrary from "./MediaLibrary";
import PreferencePanel from "./PreferencePanel";
import { LightboxProvider, PreviewImage } from "./ImageLightbox";
import { whereIs, recentEvents, objectTimeline, listClues, resolveClue, evidenceUrl, apiUrl, transcribe } from "./api";

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

function eventLabel(type) {
  return EVENT_LABEL[type] || type;
}

/** 事件/线索卡片的正文：位置 + payload 里的附加属性（颜色、状态、姿态…）。
 *
 *  只渲染值本身、不渲染键名——键名是英文的（has_straw、position），摆到中文界面上很突兀。
 *  代价是布尔值没法显示：`has_straw: true` 只能渲染成「true」，那不是人话。宁可不显示，
 *  也不要为了凑一行字给每个键硬编一份中文标签——payload 的键是 VLM 现场生成的，编不完。 */
function detailText(payload = {}, location) {
  const extras = Object.entries(payload)
    .filter(([k, v]) => !["location", "object_text", "field", "value", "reason"].includes(k) && v)
    .filter(([, v]) => typeof v !== "boolean")
    .map(([, v]) => (Array.isArray(v) ? v.join("、") : String(v)));
  return [location, ...extras].filter(Boolean).join(" · ");
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

/** 从口语问句里取出物品名：「我的充电器在哪里？」→「充电器」。
 *  后端 where-is 收的是物品名而不是整句；抽不出来时退回原文，由深检索兜底。 */
function extractObjectName(text) {
  const stripped = text
    .replace(/[?？。！!，,、\s]/g, "")
    .replace(/^(我的|我地|帮我找|找一下|找找|请问)/, "")
    .replace(/(在哪里|在哪儿|在哪|放哪了|放哪儿了|放在哪|去哪了|呢)$/, "");
  return stripped || text;
}

/** 挑一个这个浏览器真的会录的容器。
 *  Chrome/Firefox 给 webm/opus，Safari 只给 mp4；两种 ASR sidecar 都能按容器解码。
 *  一个都不支持时返回空串，交给 MediaRecorder 用它自己的默认值。 */
function pickRecordingMime() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  return candidates.find(t => window.MediaRecorder?.isTypeSupported?.(t)) || "";
}

let msgSeq = 0;
const nextId = () => `m${++msgSeq}`;

function AgentHome() {
  const { messages, setMessages, isTyping, setIsTyping, setShowClues, setSelectedEntity, clueCount } = useOutletContext();
  // idle | recording | transcribing | asking——四个状态在界面上长得都不一样，
  // 合成一个 boolean 会让「正在听」和「正在转写」变成同一个样子，而它们的等待时长差一个量级
  const [phase, setPhase] = useState("idle");
  const [mode, setMode] = useState("voice");   // voice | text
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");    // 麦克风/转写这类环境问题，不进对话流
  const recorderRef = useRef(null);
  const busy = phase !== "idle" && phase !== "recording";
  // MediaRecorder 的 onstop 是在点「说完」那一刻的闭包里跑的，那时 phase 还是旧值。
  // 守卫要读当下的真值，不能读闭包快照，否则「录完自动提问」这条路能不能走通全凭巧合。
  const askingRef = useRef(false);

  // 离开这一页时必须收掉录音：轨不停的话浏览器标签上的录音红点会一直亮着，
  // 用户会以为我们在后台偷录。
  useEffect(() => () => {
    const rec = recorderRef.current;
    if (rec && rec.state !== "inactive") rec.stop();
    rec?.stream?.getTracks?.().forEach(t => t.stop());
  }, []);

  const handleAsk = async (raw) => {
    const text = (raw || "").trim();
    if (!text || askingRef.current) return;
    askingRef.current = true;

    setNotice("");
    setDraft("");
    // 只留最近这一轮：问句必须和答案待在一起，看不到问的是什么，答案就没有意义
    const question = { id: nextId(), text, sender: "user" };
    setMessages([question, { id: nextId(), sender: "agent", type: "thinking" }]);
    setIsTyping(true);
    setPhase("asking");

    try {
      const res = await whereIs(extractObjectName(text), true);
      setMessages([
        question,
        {
          id: nextId(),
          sender: "agent",
          text: res.answer_text,
          // 答案出自的那张画面。用后端给的相对地址而不是自己拼 id：原图是否暴露由后端
          // 按身份决定（owner 才给），前端拼 id 等于绕开那道判断。
          shot: apiUrl(res.evidence_url),
          // 答出了具体实体就给一条进轨迹的路：答案只是结论，轨迹才是它的依据
          entityId: res.entity?.id || null,
          // 平台自己声明的不确定性（规则生成，不经 LLM），不转达就等于替它把话说满了
          limitations: res.limitations || [],
          outOfScope: res.channel === "not_found",
        },
      ]);
    } catch (e) {
      // 这里绝不能编一个答案顶上。答不出来是事实，装作答得出来会毁掉整个产品的可信度。
      setMessages([
        question,
        { id: nextId(), sender: "agent", error: true, text: `问不到记忆平台：${e.message || e}` },
      ]);
    } finally {
      askingRef.current = false;
      setIsTyping(false);
      setPhase("idle");
    }
  };

  const stopRecording = () => {
    const rec = recorderRef.current;
    if (rec && rec.state === "recording") rec.stop();  // 收尾在 onstop 里，那时最后一块数据才到齐
  };

  const startRecording = async () => {
    setNotice("");
    if (!navigator.mediaDevices?.getUserMedia) {
      // 十有八九是拿局域网 IP 走 http 打开的：浏览器只在 localhost 或 https 下给麦克风
      setNotice("这个页面拿不到麦克风。用 localhost 或 https 打开试试。");
      return;
    }
    let stream;
    try {
      // 不指定 deviceId：跟随系统当前输入设备，插上耳机就自动是耳机麦
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      setNotice(
        e.name === "NotAllowedError"
          ? "麦克风权限被拒绝了。在地址栏左边的权限里放开，再点一次。"
          : `打不开麦克风：${e.message || e}`,
      );
      return;
    }

    const mimeType = pickRecordingMime();
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const chunks = [];
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    rec.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      setPhase("transcribing");
      try {
        const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
        const { text } = await transcribe(blob);
        if (!text) {
          // 空转写是真的没听清（或者太短），不是出错。说清楚，别静悄悄什么都不发生。
          setNotice("没听清，再说一次？");
          setPhase("idle");
          return;
        }
        await handleAsk(text);
      } catch (e) {
        setNotice(String(e.message || e));
        setPhase("idle");
      }
    };
    recorderRef.current = rec;
    rec.start();
    setPhase("recording");
  };

  const voiceLabel = { recording: "正在听…点一下说完", transcribing: "正在转文字…", asking: "正在翻记忆…" }[phase]
    || "轻点说话";

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
          <div
            key={msg.id}
            className={`bubble ${msg.sender} ${msg.type === "thinking" ? "thinking" : ""} ${msg.error ? "error" : ""}`}
          >
            {/* 来源画面放在结论上面：先给看的，再给读的。原图过了 TTL 就没有这一格，
                但答案本身仍然成立——那时下面的 limitations 会说明这件事 */}
            {msg.shot && (
              <PreviewImage
                className="bubble-shot"
                src={msg.shot}
                alt="这个答案出自的画面"
                caption={msg.text}
              />
            )}
            {msg.type === "thinking" ? <><i/><i/><i/></> : msg.text}
            {/* 平台声明的局限要原样转达，不能只把结论那句话拿出来显示 */}
            {msg.limitations?.map((line, i) => (
              <span key={i} className="bubble-note">{line}</span>
            ))}
            {/* 找不到时顺带说清楚能力边界：现在这一页只接了找物这一条查询通道 */}
            {msg.outOfScope && (
              <span className="bubble-note">我目前只答得了「东西在哪」，别的还不会。</span>
            )}
            {msg.entityId && (
              <button className="bubble-trace" onClick={() => setSelectedEntity(msg.entityId)}>
                看这条记忆的轨迹 <ChevronRight size={12} />
              </button>
            )}
          </div>
        ))}
      </div>

      {/* 数量是真的：它等于系统看到了东西但不敢当成事实的次数。写死成常数就把这个信号抹掉了 */}
      {clueCount > 0 && (
        <button className="hint-pill" onClick={() => setShowClues(true)} style={{ opacity: isTyping ? 0 : 1 }}>
          <span className="status-dot"></span> {clueCount} 条记忆线索待确认
        </button>
      )}

      {notice && <p className="composer-note">{notice}</p>}

      <div className="composer" role="group" aria-label="提问">
        {mode === "text" ? (
          <form
            className="text-input"
            onSubmit={(e) => { e.preventDefault(); handleAsk(draft); }}
          >
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="我的充电器在哪里？"
              aria-label="输入问题"
              autoFocus
              disabled={busy}
            />
            <button type="submit" disabled={!draft.trim() || busy} aria-label="发送">
              <ChevronRight size={18} />
            </button>
          </form>
        ) : (
          <button
            className={`voice ${phase === "recording" ? "listening" : ""}`}
            onClick={phase === "recording" ? stopRecording : startRecording}
            disabled={busy}
          >
            {voiceLabel}
          </button>
        )}

        <button
          className="keyboard-toggle"
          onClick={() => { setMode(m => (m === "text" ? "voice" : "text")); setNotice(""); }}
          aria-label={mode === "text" ? "改用语音" : "改用文字"}
          disabled={phase === "recording"}
        >
          {mode === "text" ? (
            <Mic size={19} aria-hidden="true" />
          ) : (
            <span className="keyboard-icon" aria-hidden="true">
              <i></i><i></i><i></i><i></i>
              <i></i><i></i><i></i><i></i>
              <i></i><i></i><i></i><i></i>
            </span>
          )}
        </button>
      </div>
    </div>
  );
}

/** 上下文页：已接受的事件流。
 *
 *  这里刻意**不放**确认按钮。事件是已经过候选门的既成事实，对它点「确认」没有意义；
 *  真正等人拍板的是候选（线索），在确认中心里。旧原型把两者画在一起，看起来热闹，
 *  但会让人以为记忆是在这条流里被批准的——那是错的心智模型。 */
function TimelineView() {
  const { setSelectedEntity, setShowClues, clueCount } = useOutletContext();
  const [events, setEvents] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    recentEvents(40)
      .then(data => { if (alive) { setEvents(data.events); setError(null); } })
      .catch(e => { if (alive) setError(String(e.message || e)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  // 同一天的事件归到一个日期标签下，标签只在当天第一条上出现
  let lastDay = null;

  return (
    <div className="page-view timeline-page">
      <header className="top">
        <div className="brand">
          <b>上下文</b>
          <span>现实发生的流动切片</span>
        </div>
        <button className="icon-btn"><SlidersHorizontal size={18} /></button>
      </header>

      {clueCount > 0 && (
        <button className="timeline-clue-bar" onClick={() => setShowClues(true)}>
          <span className="status-dot"></span>
          {clueCount} 条线索还没确认，它们不在下面这条流里
          <ChevronRight size={14} />
        </button>
      )}

      <div className="timeline-container">
        <div className="timeline-line"></div>

        {loading && <p className="timeline-hint">正在读记忆…</p>}

        {error && (
          <div className="timeline-hint error">
            <p>拿不到事件流。</p>
            <small>确认 memory-platform 在跑，且 <code>/api</code> 代理指向它。<br />{error}</small>
          </div>
        )}

        {!loading && !error && events.length === 0 && (
          <p className="timeline-hint">还没有任何记忆事件。去「采集」页拍一张，感知跑完就会出现在这里。</p>
        )}

        <div className="timeline-list">
          {groupByFrame(events).map((group) => {
            const head = group.events[0];
            const day = dayText(head.event_time_from);
            const showDay = day !== lastDay;
            lastDay = day;
            const multi = group.events.length > 1;
            // 单条时整卡可点；多条时点整卡没有唯一目标，改成点每一行
            const single = multi ? null : head;

            return (
              <div key={head.event_id} className="timeline-node">
                <div className="node-time-badge">
                  <span className="time-text">{clockText(head.event_time_from)}</span>
                  {showDay && <span className="period-text">{day}</span>}
                </div>
                <div className="node-bullet"></div>

                <div
                  className={`dark-card ${single?.entity_id ? "clickable" : ""} ${single?.superseded ? "superseded" : ""}`}
                  onClick={() => single?.entity_id && setSelectedEntity(single.entity_id)}
                >
                  <div className="card-with-thumb">
                    {/* 一组共用一张来源图。纠正类事件没有来源帧（不出自任何画面），那格就空着 */}
                    {head.frame_asset_id && (
                      head.evidence_url ? (
                        <PreviewImage
                          className="event-thumb"
                          src={evidenceUrl(head.frame_asset_id)}
                          alt={multi ? "这一眼的画面" : `${head.entity_name}的来源画面`}
                          caption={
                            multi
                              ? `这一眼看到 ${group.events.length} 件东西 · ${clockText(head.event_time_from)}`
                              : `${head.entity_name} · ${clockText(head.event_time_from)}`
                          }
                          loading="lazy"
                        />
                      ) : (
                        <span className="event-thumb gone" title="原图已按保留期删除，记忆本身还在" />
                      )
                    )}

                    <div className="card-with-thumb-body">
                      <div className="card-top-row">
                        <span className="card-title">
                          {multi
                            ? `这一眼看到 ${group.events.length} 件东西`
                            : `${head.entity_name} · ${eventLabel(head.event_type)}`}
                        </span>
                        {single?.entity_id && (
                          <span className="more-link">
                            轨迹 <ChevronRight size={14} />
                          </span>
                        )}
                      </div>

                      {multi ? (
                        <ul className="frame-objects">
                          {group.events.map((ev) => (
                            <li
                              key={ev.event_id}
                              className={ev.superseded ? "superseded" : ""}
                              onClick={(e) => {
                                // 卡片本身不再有唯一跳转目标，点击必须停在这一行上
                                e.stopPropagation();
                                if (ev.entity_id) setSelectedEntity(ev.entity_id);
                              }}
                            >
                              <b>{ev.entity_name}</b>
                              <span>{detailText(ev.payload, ev.location) || "没有位置信息"}</span>
                              <em>{Math.round(ev.confidence * 100)}%</em>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <>
                          <p className="card-detail">
                            {detailText(head.payload, head.location) || "没有位置信息"}
                          </p>
                          <div className="card-badges">
                            {/* 取代过的事件仍然显示，但必须标出来，否则界面会同时摆出两个矛盾的位置 */}
                            {head.superseded && <span className="status-note">已被后续记忆更新</span>}
                            {head.user_confirmed && <span className="status-note confirmed">你确认过</span>}
                            <span className="conf-note">置信度 {Math.round(head.confidence * 100)}%</span>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
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
          <span>物品之间，存在生活的路径。</span>
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
                              src={evidenceUrl(ev.frame_asset_id)}
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
        ? `已记住：${clue.object_text}在${res.projection?.location || clue.location}`
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
                  <h4>{c.object_text} 在 {c.location}</h4>
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
                      caption={c.frame_caption || `${c.object_text} 在 ${c.location}`}
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

/** 手机壳布局：三个 tab 页共用状态栏与底部 dock，页面本身交给子路由。
 *  抽屉开合也写进 query（?object=…、?clues=1），刷新和浏览器后退都能还原当时看到的界面。 */
function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();

  const activeTab = location.pathname.split("/")[1] || "agent";
  // 开场白只能承诺现在真做得到的事：这一页接的是找物查询，别的问题还答不了
  const [messages, setMessages] = useState([
    { id: "hello", text: "我在。问我东西放哪了——我只答记忆里真看到过的。", sender: "agent" },
  ]);
  const [isTyping, setIsTyping] = useState(false);
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

  return (
    <div className={`app-shell premium-dark mode-${activeTab}`}>
      <div className="status-bar">
        {/* 真表。9:41 是苹果发布会的截图时间，摆在一个讲「记忆有多新」的产品上很讽刺 */}
        <span>{clock}</span><span>Reality</span>
      </div>

      <main className="main-content">
        <Outlet context={{ messages, setMessages, isTyping, setIsTyping, setSelectedEntity, setShowClues, clueCount }} />
      </main>

      {selectedEntity && (
        <ObjectDrawer entityId={selectedEntity} onClose={() => setSelectedEntity(null)} />
      )}
      {showClues && (
        <CluesDrawer onClose={() => setShowClues(false)} onCountChange={setClueCount} />
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
        <button className="dock-item" onClick={() => navigate("/capture")}>
          <Camera size={20} />
          <span>采集</span>
        </button>
        <button className="dock-item" onClick={() => navigate("/media")}>
          <Library size={20} />
          <span>数据</span>
        </button>
        <button className="dock-item" onClick={() => navigate("/live")}>
          <Radio size={20} />
          <span>联调</span>
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
        <Route path="/live" element={<ConsolePage component={LiveView} />} />
        <Route path="/capture" element={<ConsolePage component={CaptureConsole} />} />
        <Route path="/media" element={<ConsolePage component={MediaLibrary} />} />
        <Route element={<AppShell />}>
          <Route path="/agent" element={<AgentHome />} />
          <Route path="/timeline" element={<TimelineView />} />
          <Route path="/galaxy" element={<GalaxyView />} />
        </Route>
        {/* 根路径和任何认不出的 URL 都落回在场页，刷新不会白屏 */}
        <Route path="*" element={<Navigate to="/agent" replace />} />
      </Routes>
    </LightboxProvider>
  );
}

export default App;
