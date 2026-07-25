import {
  Aperture,
  CalendarDots,
  ChatCircleDots,
  CirclesFour,
  ClockCounterClockwise,
  Compass,
  Footprints,
  MagicWand,
  Path,
  Radio,
  Scroll,
  Sparkle,
  UserCircle,
  Waveform,
} from "@phosphor-icons/react";

const advisorIcons = [
  { name: "Compass", label: "方向感 / 顾问", Icon: Compass, recommended: true },
  { name: "Sparkle", label: "灵性 / 智能入口", Icon: Sparkle },
  { name: "Radio", label: "接收现实信号", Icon: Radio },
  { name: "Aperture", label: "观察 / 感知入口", Icon: Aperture },
  { name: "MagicWand", label: "智能处理", Icon: MagicWand },
  { name: "ChatCircleDots", label: "问答 / 对话", Icon: ChatCircleDots },
];

const trailIcons = [
  { name: "Footprints", label: "留下的痕迹", Icon: Footprints, recommended: true },
  { name: "ClockCounterClockwise", label: "回看 / 历史", Icon: ClockCounterClockwise },
  { name: "Scroll", label: "记录 / 卷轴", Icon: Scroll },
  { name: "CalendarDots", label: "一天里的片段", Icon: CalendarDots },
  { name: "Waveform", label: "感知流", Icon: Waveform },
  { name: "Path", label: "路径 / 轨迹", Icon: Path },
];

function IconCard({ item }) {
  const { Icon } = item;
  return (
    <div className={`icon-preview-card ${item.recommended ? "recommended" : ""}`}>
      <span className="icon-preview-mark">
        <Icon size={32} weight={item.recommended ? "duotone" : "regular"} />
      </span>
      <b>{item.name}</b>
      <small>{item.label}</small>
      {item.recommended && <em>推荐</em>}
    </div>
  );
}

export default function IconPreview() {
  return (
    <div className="icon-preview-page">
      <header className="icon-preview-head">
        <p>Navigation Icon Preview</p>
        <h1>导航图标候选</h1>
        <span>用于对比顾问、轨迹、全览、我的四个主入口</span>
      </header>

      <section className="icon-preview-section">
        <h2>当前推荐组合</h2>
        <div className="icon-preview-dock">
          {[
            { label: "顾问", Icon: Compass },
            { label: "轨迹", Icon: Path },
            { label: "全览", Icon: CirclesFour },
            { label: "我的", Icon: UserCircle },
          ].map(({ label, Icon }) => (
            <button key={label}>
              <Icon size={25} weight="duotone" />
              <span>{label}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="icon-preview-section">
        <h2>顾问</h2>
        <div className="icon-preview-grid">
          {advisorIcons.map((item) => <IconCard key={item.name} item={item} />)}
        </div>
      </section>

      <section className="icon-preview-section">
        <h2>轨迹</h2>
        <div className="icon-preview-grid">
          {trailIcons.map((item) => <IconCard key={item.name} item={item} />)}
        </div>
      </section>
    </div>
  );
}
