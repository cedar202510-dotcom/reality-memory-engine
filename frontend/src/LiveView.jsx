import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { healthz, recentFrames, evidenceUrl } from "./api";

const DEFAULT_STREAM = "http://127.0.0.1:8090/stream";

function timeText(iso) {
  const t = new Date(iso);
  return Number.isNaN(t.getTime())
    ? iso
    : t.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** 眼镜 MJPEG 实时画面：img 直连探针的 multipart/x-mixed-replace 流。
 *  同源 /events 每秒轮询采集事件：拍照 → 快门闪白 + 📸 角标；采集会话 → REC 红点。 */
function StreamPanel() {
  const [url, setUrl] = useState(() => localStorage.getItem("rme-stream-url") || DEFAULT_STREAM);
  const [draft, setDraft] = useState(url);
  const [state, setState] = useState("connecting"); // connecting | live | stale | error
  const [staleAge, setStaleAge] = useState(null); // 僵住时最后一帧的秒龄
  const [devicePresent, setDevicePresent] = useState(null); // 桥报告的设备在场状态；null=桥不支持
  const wasLive = useRef(false); // 跟踪 live 跳变，用于自动重连
  const [epoch, setEpoch] = useState(0); // 变更强制 img 重连
  const [flash, setFlash] = useState(0); // 递增触发一次快门动画
  const [lastShot, setLastShot] = useState(null); // {ts, detail}
  const [recording, setRecording] = useState(false);
  const seenTs = useRef(0);

  useEffect(() => {
    let origin;
    try { origin = new URL(url).origin; } catch { return; }
    seenTs.current = Date.now(); // 只响应连接之后的新事件
    let alive = true;
    const timer = setInterval(async () => {
      try {
        const events = await (await fetch(`${origin}/events`)).json();
        if (!alive) return;
        for (const ev of events) {
          if (ev.type === "recording_started") setRecording(true);
          if (ev.type === "recording_stopped") setRecording(false);
          if (ev.ts <= seenTs.current) continue;
          if (ev.type === "photo_captured") {
            seenTs.current = ev.ts;
            setLastShot(ev);
            setFlash((n) => n + 1);
          }
        }
      } catch { /* 预览断开时 /events 一并不可达，靠流状态提示 */ }
    }, 1000);
    return () => { alive = false; clearInterval(timer); };
  }, [url, epoch]);

  // 画面新鲜度：MJPEG 的 <img> 只在首帧触发一次 onLoad，之后即使源头断了也会
  // 一直挂着最后一帧。仅凭 onLoad 判活会在设备掉线数小时后仍显示「直播中」。
  // 因此额外轮询 /status 拿最后一帧的年龄；服务端没有该端点时不改变原有判定。
  useEffect(() => {
    let origin;
    try { origin = new URL(url).origin; } catch { return; }
    let alive = true;
    const timer = setInterval(async () => {
      try {
        const resp = await fetch(`${origin}/status`, { cache: "no-store" });
        if (!resp.ok || !alive) return; // 404 → 该服务端不支持，保持既有行为
        const s = await resp.json();
        if (!alive) return;
        // 帧恢复了就强制重连 <img>：MJPEG 连接可能在长时间无数据后被浏览器/中间层丢弃，
        // 此时源头虽已恢复，画面仍停在旧帧。拔掉眼镜再插回来正是这个场景，
        // 不该要求用户手动点一次「连接」。
        if (s.live && !wasLive.current) setEpoch((n) => n + 1);
        wasLive.current = s.live;
        setState((prev) => (prev === "error" ? prev : s.live ? "live" : "stale"));
        setStaleAge(s.age_ms == null ? null : Math.round(s.age_ms / 1000));
        setDevicePresent(s.device ?? null);
      } catch {
        // 区分两种失败：resp.ok=false 是「服务端没有 /status」（上面已 return，保持原判定）；
        // 走到这里是 fetch 抛错 = 桥本身不可达，此时流必然也断了。必须把 wasLive 归位，
        // 否则桥重启后 live 不构成跳变，永远不会触发重连。
        if (!alive) return;
        wasLive.current = false;
        setDevicePresent(null);
      }
    }, 2000);
    return () => { alive = false; clearInterval(timer); };
  }, [url, epoch]);

  const apply = (e) => {
    e.preventDefault();
    localStorage.setItem("rme-stream-url", draft);
    setUrl(draft);
    setState("connecting");
    setEpoch(epoch + 1);
  };

  return (
    <section className="live-panel">
      <div className="live-panel-head">
        <h2>眼镜实时画面</h2>
        <span className="live-head-tags">
          {recording && <span className="live-rec"><i />采集中</span>}
          <span className={`live-dot ${state}`}>
            {{
              connecting: "连接中",
              live: "直播中",
              stale: staleAge == null ? "画面已停止" : `画面已停止 ${staleAge}s`,
              error: "未连接",
            }[state]}
          </span>
        </span>
      </div>
      <div className="live-stream-frame">
        <img
          key={`${url}#${epoch}`}
          src={url}
          alt="Rokid 眼镜实时预览"
          onLoad={() => setState("live")}
          onError={() => setState("error")}
        />
        {flash > 0 && <div key={flash} className="live-shutter" aria-hidden="true" />}
        {lastShot && (
          <div key={`b${flash}`} className="live-shot-badge">
            📸 已拍照 {timeText(new Date(lastShot.ts).toISOString())}
          </div>
        )}
        {/* 僵住时不整屏遮挡：陈旧画面仍有参考价值，但必须一眼看出它不是实时的 */}
        {state === "stale" && (
          <div className="live-stale-banner">
            {devicePresent === false
              ? "眼镜已断开 · 插回 USB 即自动恢复，无需操作"
              : `画面已停止更新${staleAge != null ? ` ${staleAge} 秒` : ""} · 这不是实时画面`}
          </div>
        )}
        {(state === "connecting" || state === "error") && (
          <div className="live-stream-hint">
            <p>{state === "connecting" ? "正在连接眼镜预览流…" : "连不上眼镜预览流。"}</p>
            <small>
              眼镜端在探针 App 里开启「预览」，然后 USB 联调执行
              <code> adb forward tcp:8090 tcp:8090</code>，或改用眼镜的局域网地址。
            </small>
          </div>
        )}
      </div>
      <form className="live-url-row" onSubmit={apply}>
        <input aria-label="预览流地址" value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck={false} />
        <button type="submit">连接</button>
        <button type="button" aria-label="重连" onClick={(e) => apply(e)}><RefreshCw size={14} /></button>
      </form>
    </section>
  );
}

/** 后端消化情况：healthz + 最近摄入帧轮询，看得到「流进来 → 感知产出 caption」的全链路。 */
function IngestPanel() {
  const [backend, setBackend] = useState("connecting");
  const [frames, setFrames] = useState([]);
  const [pending, setPending] = useState(0);
  const timer = useRef();

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        await healthz();
        const data = await recentFrames(10);
        if (!alive) return;
        setBackend("live");
        setFrames(data.frames);
        setPending(data.pending_outbox);
      } catch {
        if (alive) setBackend("error");
      }
      timer.current = setTimeout(poll, 4000);
    };
    poll();
    return () => { alive = false; clearTimeout(timer.current); };
  }, []);

  return (
    <section className="live-panel">
      <div className="live-panel-head">
        <h2>后端记忆消化</h2>
        <span className={`live-dot ${backend}`}>
          {{ connecting: "连接中", live: pending > 0 ? `${pending} 帧排队中` : "已就绪", error: "后端未连接" }[backend]}
        </span>
      </div>
      {backend === "error" && (
        <div className="live-empty">
          <p>memory-platform 未启动。</p>
          <small><code>cd services/memory-platform && uvicorn app.main:app --port 8000</code></small>
        </div>
      )}
      {backend === "live" && frames.length === 0 && (
        <div className="live-empty"><p>还没有任何摄入帧。</p><small>眼镜上传后，这里会出现帧和它的场景描述。</small></div>
      )}
      <ul className="live-frame-list">
        {frames.map((f) => (
          <li key={f.frame_asset_id}>
            {f.evidence_available
              ? <img src={evidenceUrl(f.frame_asset_id)} alt="" loading="lazy" />
              : <span className="live-thumb-gone">已过期</span>}
            <div>
              <b>{f.caption || "感知处理中…"}</b>
              <small>
                {timeText(f.captured_at)}
                {f.scene_tags?.length > 0 && ` · ${f.scene_tags.slice(0, 4).join("、")}`}
              </small>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function LiveView() {
  return (
    <div className="page live-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">联调</p>
          <h1>眼镜进来的每一帧，看得见。</h1>
          <p>左边是 Rokid 探针的实时画面，右边是 memory-platform 对这些帧的消化结果。</p>
        </div>
      </header>
      <div className="live-grid">
        <StreamPanel />
        <IngestPanel />
      </div>
    </div>
  );
}
