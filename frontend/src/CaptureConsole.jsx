import { useCallback, useEffect, useRef, useState } from "react";
import { Camera, Mic, Pause, Play, Square, Timer } from "lucide-react";
import StreamPanel, { timeText } from "./StreamPanel";
import { bindDevice, createCaptureRequest, listCaptureRequests, listDevices } from "./api";

const RUNTIMES = [
  { value: "com.realitymemory.glassprobe", label: "探针 App（拍照 / 周期采集 / 预览流）" },
  { value: "com.realitymemory.glasses", label: "正式 App（拍照 / 结束会话）" },
  // 耳机不是 Android 设备，这里放的是宿主侧 collector 的标识而不是包名。它只能走 inbox：
  // adb 通道对它没有意义，选了也只会得到一条 unknown_runtime 失败。
  { value: "iflybuds-host-collector/0.1.0", label: "IFLYBUDS 采集器（录音 / 播报，仅 inbox）" },
];

const TRANSPORTS = [
  { value: "adb", label: "adb（本机 USB，今天就能跑）" },
  { value: "inbox", label: "inbox（设备自拉，脱离 USB）" },
];

const ACTIONS = [
  { action: "CAPTURE_PHOTO", label: "拍一张", icon: Camera, primary: true },
  { action: "START_PERIODIC", label: "开始周期采集", icon: Timer },
  { action: "PAUSE", label: "暂停", icon: Pause },
  { action: "RESUME", label: "恢复", icon: Play },
  { action: "STOP", label: "结束并清理", icon: Square },
  { action: "CAPTURE_AUDIO", label: "录一段", icon: Mic },
];

/** 把一条请求记录翻成人话。
 *
 *  关键区分：adb 通道的 EXECUTED 只代表 intent 送到了运行时，并不代表照片拍到了
 *  （后端在 detail.execution_evidence 里标注了这一点）。控制台必须照实说，否则演示时
 *  会出现「界面显示已执行、眼镜其实没动」这种最难查的假象。 */
function statusOf(record) {
  const { status, last_receipt_status: receipt } = record.message;
  const last = record.receipts[record.receipts.length - 1];
  const detail = last?.detail || {};
  const reason = detail.message || detail.policy || detail.reason || null;

  if (receipt === "EXECUTED") {
    return detail.execution_evidence === "intent_delivered_only"
      ? { tone: "sent", text: "命令已送达运行时", note: "设备是否真的采集，看左边画面" }
      : { tone: "ok", text: "设备已执行", note: null };
  }
  if (receipt === "REJECTED") return { tone: "warn", text: "设备拒绝", note: reason };
  if (receipt === "FAILED") return { tone: "warn", text: "失败", note: reason };
  if (status === "EXPIRED") return { tone: "muted", text: "已过期未投递", note: null };
  if (status === "RECEIVED") return { tone: "ok", text: "设备已收到", note: null };
  if (status === "SENT") return { tone: "sent", text: "已推送，等回执", note: null };
  return { tone: "pending", text: "排队中，等设备来拉", note: null };
}

function DeviceBar({ devices, deviceId, setDeviceId, onBind, busy, error }) {
  const device = devices.find((d) => d.device_id === deviceId);

  return (
    <section className="live-panel">
      <div className="live-panel-head">
        <h2>目标设备</h2>
        <span className={`live-dot ${!error && device?.runtime_package ? "live" : "error"}`}>
          {error ? "后端未连接" : device?.runtime_package ? "已绑定" : "未绑定运行时"}
        </span>
      </div>
      {/* 后端连不上时，空下拉框 +「未绑定运行时」看起来像设备没接好，会把人引到
          错误的方向去查眼镜。这里必须先说清楚是后端的问题，并给出具体地址。 */}
      {error && (
        <div className="live-empty">
          <p>拿不到设备列表，采集动作已禁用。</p>
          <small>
            后端多半没起，或者当前页面的 <code>/api</code> 代理指到了旧后端。确认
            memory-platform 在跑，且 Vite 的 <code>RME_API_TARGET</code> 指向它。
            <br />{String(error)}
          </small>
        </div>
      )}
      <div className="cap-binding">
        <label>
          <span>设备</span>
          <select value={deviceId || ""} onChange={(e) => setDeviceId(e.target.value)}>
            {devices.map((d) => (
              <option key={d.device_id} value={d.device_id}>
                {d.name}（{d.kind}）
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>眼镜 App</span>
          <select
            value={device?.runtime_package || ""}
            onChange={(e) => onBind({ runtime_package: e.target.value })}
            disabled={!device || busy}
          >
            <option value="" disabled>未绑定</option>
            {RUNTIMES.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
        </label>
        <label>
          <span>控制通道</span>
          <select
            value={device?.control_transport || "inbox"}
            onChange={(e) => onBind({ control_transport: e.target.value })}
            disabled={!device || busy}
          >
            {TRANSPORTS.map((t) => (
              <option key={t.value} value={t.value}>{t.label}</option>
            ))}
          </select>
        </label>
      </div>
      {device?.control_transport === "adb" && (
        <p className="cap-note">
          adb 通道要求后端进程与眼镜插在同一台机器上，是联调形态。设备端补上 inbox
          轮询后改选 inbox 即可脱离 USB，前端不用改。
        </p>
      )}
    </section>
  );
}

function ActionPanel({ onSend, busy, disabledReason }) {
  const disabled = Boolean(disabledReason);
  const [interval, setIntervalSeconds] = useState(30);
  const [duration, setDuration] = useState(8);

  const send = (action) => {
    const body = { action };
    if (action === "START_PERIODIC") body.interval_seconds = Number(interval);
    if (action === "CAPTURE_AUDIO") body.duration_seconds = Number(duration);
    onSend(body);
  };

  return (
    <section className="live-panel">
      <div className="live-panel-head">
        <h2>采集动作</h2>
        <span className="live-dot">{busy ? "下发中…" : "就绪"}</span>
      </div>
      <div className="cap-actions">
        {ACTIONS.map(({ action, label, icon: Icon, primary }) => (
          <button
            key={action}
            className={`cap-action ${primary ? "primary" : ""}`}
            onClick={() => send(action)}
            disabled={busy || disabled}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </div>
      <div className="cap-params">
        <label>
          <span>周期间隔</span>
          <input
            type="number" min={5} max={3600} value={interval}
            onChange={(e) => setIntervalSeconds(e.target.value)}
          />
          <small>秒</small>
        </label>
        <label>
          <span>音频时长</span>
          <input
            type="number" min={1} max={300} value={duration}
            onChange={(e) => setDuration(e.target.value)}
          />
          <small>秒</small>
        </label>
      </div>
      {disabled && <p className="cap-note">{disabledReason}</p>}
    </section>
  );
}

function HistoryPanel({ requests, error }) {
  return (
    <section className="live-panel">
      <div className="live-panel-head">
        <h2>请求与回执</h2>
        <span className={`live-dot ${error ? "error" : "live"}`}>
          {error ? "后端未连接" : `${requests.length} 条`}
        </span>
      </div>
      {!error && requests.length === 0 && (
        <div className="live-empty">
          <p>还没有下发过采集请求。</p>
          <small>点上面的按钮，这里会出现请求、通道和设备回执。</small>
        </div>
      )}
      <ul className="cap-history">
        {requests.map((r) => {
          const s = statusOf(r);
          return (
            <li key={r.message.message_id}>
              <div className="cap-history-head">
                <b>{r.action}</b>
                <span className="cap-transport">{r.transport}</span>
                <span className={`cap-status ${s.tone}`}>{s.text}</span>
              </div>
              <small>
                {timeText(r.message.created_at)}
                {s.note && ` · ${s.note}`}
              </small>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default function CaptureConsole() {
  const [devices, setDevices] = useState([]);
  const [deviceId, setDeviceId] = useState(null);
  const [requests, setRequests] = useState([]);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const timer = useRef();

  /** 返回是否拿到了设备列表（调用方据此决定要不要继续重试）。 */
  const refreshDevices = useCallback(async () => {
    try {
      const data = await listDevices();
      setDevices(data.devices);
      setError(null);
      setDeviceId((cur) => cur || data.devices[0]?.device_id || null);
      return data.devices.length > 0;
    } catch (e) {
      setError(String(e.message || e));
      return false;
    }
  }, []);

  // 设备列表要重试：只拉一次的话，后端晚起或中途重启后控制台会永远停在「后端未连接」，
  // 只能靠刷新页面恢复——而这恰恰是最容易被误判成「眼镜没连上」的状态。
  useEffect(() => {
    let alive = true;
    let timer;
    const tick = async () => {
      const ok = await refreshDevices();
      if (!alive) return;
      // 连上且已有设备后不再轮询：设备列表几乎不变，没必要一直打后端
      if (!ok) timer = setTimeout(tick, 4000);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [refreshDevices]);

  // 请求状态靠轮询：inbox 通道下终态由设备回执产生，可能在下发后好几秒才到。
  useEffect(() => {
    if (!deviceId) return undefined;
    let alive = true;
    const poll = async () => {
      try {
        const data = await listCaptureRequests(deviceId, 20);
        if (!alive) return;
        setRequests(data.requests);
        setError(null);
      } catch (e) {
        if (alive) setError(String(e.message || e));
      }
      timer.current = setTimeout(poll, 3000);
    };
    poll();
    return () => { alive = false; clearTimeout(timer.current); };
  }, [deviceId]);

  const handleBind = async (patch) => {
    setBusy(true);
    try {
      await bindDevice(deviceId, patch);
      await refreshDevices();
    } catch (e) {
      setToast(`绑定失败：${e.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  const handleSend = async (body) => {
    setBusy(true);
    try {
      const res = await createCaptureRequest(deviceId, body);
      const d = res.dispatch;
      setToast(
        d.accepted
          ? `已受理（${d.transport}）`
          : `未送出：${d.detail?.message || d.detail?.reason || "未知原因"}`
      );
      const data = await listCaptureRequests(deviceId, 20);
      setRequests(data.requests);
    } catch (e) {
      // 422 在这里是契约拦截（动作不存在、参数配错动作），把后端的话原样带出来
      setToast(`下发失败：${e.message || e}`);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const device = devices.find((d) => d.device_id === deviceId);

  return (
    <div className="page live-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">采集</p>
          <h1>在网页上按一下，眼镜就采一次。</h1>
          <p>
            这里下发的是<b>请求</b>不是命令：眼镜本地策略（权限、佩戴、隐私暂停）有完整的
            拒绝权，拒绝会回一条 REJECTED，不会静默丢弃。
          </p>
        </div>
      </header>
      <div className="live-grid">
        <StreamPanel />
        <div className="cap-column">
          <DeviceBar
            devices={devices}
            deviceId={deviceId}
            setDeviceId={setDeviceId}
            onBind={handleBind}
            busy={busy}
            error={error}
          />
          <ActionPanel
            onSend={handleSend}
            busy={busy}
            disabledReason={
              error
                ? "后端未连接，无法下发采集请求。先确认 memory-platform 在跑。"
                : !device
                ? "后端里还没有任何设备。"
                : !device.runtime_package
                ? "先给设备绑定一个眼镜 App，再下发动作。"
                : null
            }
          />
          <HistoryPanel requests={requests} error={error} />
        </div>
      </div>
      {toast && <div className="cap-toast">{toast}</div>}
    </div>
  );
}
