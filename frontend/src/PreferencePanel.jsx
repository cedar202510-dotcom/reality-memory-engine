import { useEffect, useState } from "react";
import { ChevronDown, Mic, Target, Hand, Eye } from "lucide-react";
import { preferenceInsights } from "./api";

/** 喜好度面板：全览页里回答「你对什么有态度、有多强、凭什么」。
 *
 *  刻意把「凭什么」做成可展开而不是折叠掉：一个 0~100 的分数如果不能落回到
 *  「你在 7 月 25 日说过『这个鸡米花已经软了』」，它就只是个看起来很聪明的数字。
 *  用户要能一眼查到分数的来源，也才有机会发现系统听错了。
 */

const CHANNEL_ICON = {
  verbal: Mic,
  intent: Target,
  behavior: Hand,
  attention: Eye,
};

// 档位 → 配色。用现有的三个语义色，不新增：绿=正面，暖橙=负面，灰=中性/未知。
const LEVEL_TONE = {
  强烈喜欢: "pos strong",
  喜欢: "pos",
  中性: "mid",
  不喜欢: "neg",
  强烈不喜欢: "neg strong",
  证据不足: "unknown",
};

const KIND_LABEL = {
  verbal: "说",
  intent: "打算",
  behavior: "用过",
};

function scoreText(item) {
  // 证据不足时不显示分数：显示一个数字等于宣称我们知道，而我们不知道。
  return item.level === "证据不足" ? "—" : item.score;
}

function ChannelBar({ channel }) {
  const Icon = CHANNEL_ICON[channel.channel] || Mic;
  // value ∈ [-1,1] → 以中线为原点向左右伸展的条
  const pct = Math.min(Math.abs(channel.value), 1) * 50;
  const negative = channel.value < 0;
  return (
    <div className="pref-channel">
      <span className="pref-channel-name">
        <Icon size={12} />
        {channel.label}
      </span>
      <span className="pref-channel-track">
        <span
          className={`pref-channel-fill ${negative ? "neg" : "pos"}`}
          style={{ width: `${pct}%`, [negative ? "right" : "left"]: "50%" }}
        />
        <span className="pref-channel-mid" />
      </span>
      <span className="pref-channel-count">{channel.evidence_count}</span>
    </div>
  );
}

function PreferenceCard({ item }) {
  const [open, setOpen] = useState(false);
  const tone = LEVEL_TONE[item.level] || "mid";
  const dwell = item.dwell_seconds ? `${Math.round(item.dwell_seconds)}s` : null;

  return (
    <div className={`pref-card ${tone}`}>
      <button className="pref-head" onClick={() => setOpen((v) => !v)}>
        <span className="pref-score">{scoreText(item)}</span>
        <span className="pref-ident">
          <b>{item.entity.canonical_name}</b>
          <small>
            {item.level}
            {item.confidence < 0.4 && item.level !== "证据不足" ? " · 证据偏少" : ""}
          </small>
        </span>
        <span className="pref-facts">
          {dwell && <span title="画面停留时长">{dwell}</span>}
          {item.use_count > 0 && <span title="使用/消耗次数">用 {item.use_count}</span>}
          {item.pending_count > 0 && (
            <span className="pending" title="还在候选门里等确认，未计入分数">
              待确认 {item.pending_count}
            </span>
          )}
        </span>
        <ChevronDown size={14} className={`pref-chevron ${open ? "open" : ""}`} />
      </button>

      {open && (
        <div className="pref-body">
          {item.channels.length > 0 && (
            <div className="pref-channels">
              {item.channels.map((c) => (
                <ChannelBar key={c.channel} channel={c} />
              ))}
            </div>
          )}
          {item.evidence.length > 0 ? (
            <ul className="pref-evidence">
              {item.evidence.map((e, i) => (
                <li key={i} className={e.superseded ? "superseded" : ""}>
                  <span className="pref-ev-kind">{KIND_LABEL[e.kind] || e.kind}</span>
                  <span className="pref-ev-text">{e.text}</span>
                  {e.superseded && <span className="pref-ev-flag">已被纠正</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="pref-empty-note">
              只有画面停留证据，没有任何口头评价——所以只能说「看得多」，说不了「喜欢」。
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function PreferencePanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    preferenceInsights({ limit: 50 })
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(String(e)));
    return () => {
      alive = false;
    };
  }, []);

  if (error) {
    return null;
  }

  if (!data) {
    return null;
  }

  // 有结论的排在前面单独成卡；「只被看到过、从没被评价过」的压成一行计数。
  // 这类物体在真实数据里是绝大多数（画面里什么都有），逐个铺成卡片会把
  // 真正有信息量的几条淹掉，而且满屏「证据不足」看起来像功能坏了。
  const decided = data.items.filter((i) => i.level !== "证据不足");
  const undecided = data.items.filter((i) => i.level === "证据不足");

  return (
    <section className="pref-panel">
      <div className="pref-panel-head">
        <h3>喜好度</h3>
        <small>说过的话 × 画面里看到的</small>
      </div>

      {decided.length === 0 ? (
        <p className="pref-loading">
          还没有能下结论的评价。录一段带解说的视频——说出口的「好吃 / 一般般 / 已经软了」
          才是喜好度的来源，光被拍到不算。
        </p>
      ) : (
        <div className="pref-list">
          {decided.map((item) => (
            <PreferenceCard key={item.entity.id} item={item} />
          ))}
        </div>
      )}

      {undecided.length > 0 && (
        <p className="pref-undecided">
          另有 {undecided.length} 件只在画面里出现过、还没有任何评价
          <span>（{undecided.slice(0, 6).map((i) => i.entity.canonical_name).join("、")}
          {undecided.length > 6 ? " 等" : ""}）</span>
        </p>
      )}

      {data.limitations?.length > 0 && (
        <ul className="pref-limits">
          {data.limitations.map((l, i) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
