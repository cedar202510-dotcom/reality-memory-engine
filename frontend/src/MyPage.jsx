import { useState } from "react";
import { ArrowLeft, Battery, Bluetooth, ChevronRight, Moon, Settings, Shield, User } from "lucide-react";

const deviceGroups = [
  {
    id: "wearables",
    title: "穿戴与随身",
    devices: [
      { name: "Reality Glasses Pro", kind: "眼镜", status: "已连接", meta: "82% 电量", online: true },
      { name: "智能手表", kind: "手表", status: "同步中", meta: "心率与活动", online: true },
      { name: "智能体脂秤", kind: "体脂秤", status: "待授权", meta: "体重与体脂", online: false },
    ],
  },
  {
    id: "environment",
    title: "家居环境",
    devices: [
      { name: "客厅温湿度计", kind: "温湿度", status: "已接入", meta: "24.6℃ · 48%", online: true },
      { name: "卧室空气传感器", kind: "空气", status: "已接入", meta: "CO2 / PM2.5", online: true },
      { name: "玄关门窗传感器", kind: "门磁", status: "离线", meta: "2 小时前", online: false },
      { name: "书房人体传感器", kind: "存在", status: "已接入", meta: "活动感知", online: true },
    ],
  },
  {
    id: "appliances",
    title: "家电",
    devices: [
      { name: "智能冰箱", kind: "冰箱", status: "已接入", meta: "食材与温区", online: true },
      { name: "智能洗衣机", kind: "洗衣机", status: "已接入", meta: "洗涤进度", online: true },
      { name: "客厅空调", kind: "空调", status: "待绑定", meta: "温度与模式", online: false },
      { name: "扫地机器人", kind: "清洁", status: "已接入", meta: "地图与清扫", online: true },
    ],
  },
  {
    id: "space",
    title: "影音与空间",
    devices: [
      { name: "客厅智能音箱", kind: "音箱", status: "已接入", meta: "语音与播放", online: true },
      { name: "餐厅智能灯", kind: "灯光", status: "已接入", meta: "亮度与场景", online: true },
      { name: "电视与遥控器", kind: "影音", status: "已接入", meta: "观看状态", online: true },
    ],
  },
];

const deviceCount = deviceGroups.reduce((sum, group) => sum + group.devices.length, 0);
const onlineCount = deviceGroups.reduce(
  (sum, group) => sum + group.devices.filter((device) => device.online).length,
  0,
);

function DevicePage({ onBack }) {
  return (
    <div className="page-view my-page my-page--devices">
      <header className="top my-top">
        <button className="my-back" onClick={onBack} aria-label="返回我的">
          <ArrowLeft size={18} />
        </button>
        <div className="brand">
          <b>设备</b>
          <span>管理可接入的现实感知源</span>
        </div>
      </header>

      <div className="my-scroll">
        <section className="device-summary">
          <div>
            <span>已接入</span>
            <strong>{onlineCount}</strong>
          </div>
          <div>
            <span>设备总数</span>
            <strong>{deviceCount}</strong>
          </div>
          <div>
            <span>待处理</span>
            <strong>{deviceCount - onlineCount}</strong>
          </div>
        </section>

        {deviceGroups.map((group) => (
          <section className="device-group" key={group.id}>
            <h3>{group.title}</h3>
            <div className="device-list">
              {group.devices.map((device) => (
                <button className="device-row" key={device.name}>
                  <span className="device-mark">{device.kind.slice(0, 2)}</span>
                  <span className="device-copy">
                    <b>{device.name}</b>
                    <small>{device.meta}</small>
                  </span>
                  <span className={device.online ? "device-state online" : "device-state"}>
                    {device.status}
                  </span>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

export default function MyPage() {
  const [view, setView] = useState("home");

  if (view === "devices") {
    return <DevicePage onBack={() => setView("home")} />;
  }

  return (
    <div className="page-view my-page">
      <header className="top my-top">
        <div className="brand">
          <b>我的</b>
          <span>你的个人管理</span>
        </div>
      </header>

      <div className="my-scroll">
        <section className="profile-section">
          <div className="profile-avatar">
            <User size={32} color="#06100b" />
          </div>
          <div>
            <h2>测试用户</h2>
            <p>Reality Agent ID: 0x8A...2F</p>
          </div>
        </section>

        <section className="settings-section">
          <h3>设备</h3>
          <button className="device-card" onClick={() => setView("devices")}>
            <span className="setting-icon">
              <Bluetooth size={22} />
            </span>
            <span className="setting-copy">
              <b>设备管理</b>
              <small>{onlineCount} 台已接入 · {deviceCount - onlineCount} 台待处理</small>
            </span>
            <span className="setting-tail">
              <Battery size={13} />
              82%
              <ChevronRight size={16} opacity={0.55} />
            </span>
          </button>
        </section>

        <section className="settings-section">
          <h3>个人管理</h3>
          <div className="settings-list">
            {[
              { icon: <Shield size={18} />, label: "隐私与记忆", value: "" },
              { icon: <Moon size={18} />, label: "显示偏好", value: "跟随系统" },
              { icon: <Settings size={18} />, label: "高级设置", value: "" },
            ].map((item) => (
              <button className="setting-row" key={item.label}>
                <span className="setting-icon">{item.icon}</span>
                <span className="setting-label">{item.label}</span>
                <span className="setting-tail">
                  {item.value && <small>{item.value}</small>}
                  <ChevronRight size={16} opacity={0.55} />
                </span>
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
