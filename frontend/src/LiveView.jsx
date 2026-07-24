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

/** 眼镜 MJPEG 实时画面：img 直连探针的 multipart/x-mixed-replace 流。 */
function StreamPanel() {
  const [url, setUrl] = useState(() => localStorage.getItem("rme-stream-url") || DEFAULT_STREAM);
  const [draft, setDraft] = useState(url);
  const [state, setState] = useState("connecting"); // connecting | live | error
  const [epoch, setEpoch] = useState(0); // 变更强制 img 重连

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
        <span className={`live-dot ${state}`}>{{ connecting: "连接中", live: "直播中", error: "未连接" }[state]}</span>
      </div>
      <div className="live-stream-frame">
        <img
          key={`${url}#${epoch}`}
          src={url}
          alt="Rokid 眼镜实时预览"
          onLoad={() => setState("live")}
          onError={() => setState("error")}
        />
        {state !== "live" && (
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
