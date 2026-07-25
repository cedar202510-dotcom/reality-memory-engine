import { useCallback, useEffect, useState } from "react";
import { Image as ImageIcon, AudioLines, Video, Activity, Download } from "lucide-react";
import { listMedia, mediaRawUrl } from "./api";
import { timeText } from "./StreamPanel";
import { PreviewImage } from "./ImageLightbox";

const PAGE_SIZE = 24;

const KINDS = [
  { value: "", label: "全部" },
  { value: "image", label: "图片" },
  { value: "audio", label: "音频" },
  { value: "video", label: "视频" },
  { value: "sensor", label: "传感器" },
];

const RANGES = [
  { value: "", label: "全部时间" },
  { value: 1, label: "最近 1 小时" },
  { value: 24, label: "最近 24 小时" },
  { value: 24 * 7, label: "最近 7 天" },
];

const KIND_ICON = { image: ImageIcon, audio: AudioLines, video: Video, sensor: Activity };

function dayText(iso) {
  const t = new Date(iso);
  return Number.isNaN(t.getTime()) ? iso : t.toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
}

/** 一条媒体的正文区。原始字节可能已被 TTL 删除，这时只剩派生表示（caption/转写）。 */
function MediaBody({ item }) {
  if (!item.available) {
    // 只说文件没了；caption/转写由卡片下方统一渲染，这里再放一遍会重复两次
    return <div className="media-gone"><span>原始文件已按保留期删除</span></div>;
  }
  const url = mediaRawUrl(item.evidence_item_id);
  if (item.media_kind === "image") {
    return (
      <PreviewImage
        className="media-thumb"
        src={url}
        alt={item.caption || "采集图片"}
        caption={item.caption || timeText(item.captured_at || item.created_at)}
        loading="lazy"
      />
    );
  }
  if (item.media_kind === "audio") {
    // 浏览器放不了的格式（裸 PCM 回的是 octet-stream）不硬塞 <audio>，
    // 塞了只会显示一个永远转不动的播放器
    return item.media_type?.startsWith("audio/") ? (
      <audio className="media-audio" src={url} controls preload="none" />
    ) : (
      <a className="media-download" href={url} download>
        <Download size={14} /> {item.media_type || "未知格式"}，浏览器无法直接播放
      </a>
    );
  }
  if (item.media_kind === "video") {
    return <video className="media-video" src={url} controls preload="metadata" />;
  }
  return (
    <a className="media-download" href={url} download>
      <Download size={14} /> 下载原始文件
    </a>
  );
}

function MediaCard({ item }) {
  const Icon = KIND_ICON[item.media_kind] || Activity;
  const text = item.caption || item.transcript;
  return (
    <li className={`media-card ${item.available ? "" : "expired"}`}>
      <div className="media-body">
        <MediaBody item={item} />
      </div>
      <div className="media-meta">
        <span className="media-kind"><Icon size={12} /> {item.media_kind}</span>
        <time>{timeText(item.captured_at || item.created_at)}</time>
        {item.duration_seconds != null && <span className="media-dur">{item.duration_seconds}s</span>}
      </div>
      {text && <p className="media-text">{text}</p>}
      {/* 三种「没有结果」要分开说：只有 PENDING 才值得等 */}
      {!text && (
        <p className="media-text muted">
          {{
            UNSUPPORTED: "该模态暂无解析链路，只做可靠落盘",
            ABANDONED: "原始媒体已删除，解析未完成且不会再有结果",
            PENDING: "感知处理中…",
          }[item.perception_state] || "没有派生表示"}
        </p>
      )}
    </li>
  );
}

export default function MediaLibrary() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [kind, setKind] = useState("");
  const [hours, setHours] = useState("");
  const [availableOnly, setAvailableOnly] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (offset = 0) => {
      setLoading(true);
      try {
        const params = { limit: PAGE_SIZE, offset };
        if (kind) params.kind = kind;
        if (availableOnly) params.available_only = true;
        if (hours) params.since = new Date(Date.now() - hours * 3600_000).toISOString();
        const data = await listMedia(params);
        // 追加而不是覆盖：翻页要能一直往下看，不是每页替换
        setItems((prev) => (offset === 0 ? data.items : [...prev, ...data.items]));
        setTotal(data.total);
        setError(null);
      } catch (e) {
        setError(String(e.message || e));
      } finally {
        setLoading(false);
      }
    },
    [kind, hours, availableOnly],
  );

  // 过滤条件变了要回到第一页，否则会拿着旧 offset 去查新条件，看到的是中间一段
  useEffect(() => { load(0); }, [load]);

  const grouped = items.reduce((acc, item) => {
    const day = dayText(item.captured_at || item.created_at);
    (acc[day] ||= []).push(item);
    return acc;
  }, {});

  return (
    <div className="page live-page">
      <header className="page-heading">
        <div>
          <p className="eyebrow">数据</p>
          <h1>采集到的东西都在这。</h1>
          <p>
            图片、音频、视频和传感器片段按时间倒序。原始文件有保留期，过期后条目仍在，
            但只剩描述和转写——这是隐私设计，不是数据丢了。
          </p>
        </div>
      </header>

      <section className="live-panel media-panel">
        <div className="media-filters">
          <div className="media-chips">
            {KINDS.map((k) => (
              <button
                key={k.value}
                className={`media-chip ${kind === k.value ? "active" : ""}`}
                onClick={() => setKind(k.value)}
              >
                {k.label}
              </button>
            ))}
          </div>
          <div className="media-filter-right">
            <select value={hours} onChange={(e) => setHours(e.target.value)}>
              {RANGES.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
            <label className="media-toggle">
              <input
                type="checkbox"
                checked={availableOnly}
                onChange={(e) => setAvailableOnly(e.target.checked)}
              />
              只看未过期
            </label>
            <span className={`live-dot ${error ? "error" : "live"}`}>
              {error ? "后端未连接" : `共 ${total} 条`}
            </span>
          </div>
        </div>

        {error && (
          <div className="live-empty">
            <p>拿不到采集记录。</p>
            <small>确认 memory-platform 在跑，且当前页面的 <code>/api</code> 代理指向它。<br />{error}</small>
          </div>
        )}

        {!error && items.length === 0 && !loading && (
          <div className="live-empty">
            <p>这个条件下没有采集记录。</p>
            <small>去「采集」页下发一次拍照，或放宽时间范围。</small>
          </div>
        )}

        {Object.entries(grouped).map(([day, group]) => (
          <div key={day} className="media-group">
            <h3>{day}</h3>
            <ul className="media-grid">
              {group.map((item) => (
                <MediaCard key={item.evidence_item_id} item={item} />
              ))}
            </ul>
          </div>
        ))}

        {items.length < total && (
          <button className="media-more" onClick={() => load(items.length)} disabled={loading}>
            {loading ? "加载中…" : `加载更多（还有 ${total - items.length} 条）`}
          </button>
        )}
      </section>
    </div>
  );
}
