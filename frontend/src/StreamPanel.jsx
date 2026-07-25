import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";

const DEFAULT_STREAM = "http://127.0.0.1:8090/stream";

export function timeText(iso) {
  const t = new Date(iso);
  return Number.isNaN(t.getTime())
    ? iso
    : t.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** 眼镜 MJPEG 实时画面：img 直连探针的 multipart/x-mixed-replace 流。
 *  同源 /events 每秒轮询采集事件：拍照 → 快门闪白 + 📸 角标；采集会话 → REC 红点。
 *
 *  这条链路直连眼镜的 :8090，不走后端也不走 Vite 代理。它是**观测**通道：这里的快门
 *  动效来自眼镜自己上报的事件，不是前端按钮的回执。采集控制台靠这一点做交叉验证——
 *  按钮只能说「请求已受理」，画面闪白才说明设备真的拍了。onCaptureEvent 把这个信号
 *  交给控制台。 */
export default function StreamPanel({ onCaptureEvent }) {
  const [url, setUrl] = useState(() => localStorage.getItem("rme-stream-url") || DEFAULT_STREAM);
  const [draft, setDraft] = useState(url);
  const [state, setState] = useState("connecting"); // connecting | live | stale | error
  const [staleAge, setStaleAge] = useState(null); // 僵住时最后一帧的秒龄
  const [epoch, setEpoch] = useState(0); // 变更强制 img 重连
  const [flash, setFlash] = useState(0); // 递增触发一次快门动画
  const [lastShot, setLastShot] = useState(null); // {ts, detail}
  const [recording, setRecording] = useState(false);
  const seenTs = useRef(0);
  // 用 ref 存回调：父组件每次渲染都会传新函数，直接进依赖数组会让轮询每秒重建
  const notify = useRef(onCaptureEvent);
  notify.current = onCaptureEvent;

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
            notify.current?.(ev);
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
        setState((prev) => (prev === "error" ? prev : s.live ? "live" : "stale"));
        setStaleAge(s.age_ms == null ? null : Math.round(s.age_ms / 1000));
      } catch { /* 不支持 /status 或跨域被拒：沿用 onLoad 判定 */ }
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
            画面已停止更新{staleAge != null && ` ${staleAge} 秒`} · 这不是实时画面
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
