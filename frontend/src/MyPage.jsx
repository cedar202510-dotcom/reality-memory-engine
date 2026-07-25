import React from "react";
import { User, Battery, Bluetooth, Settings, Shield, Moon, ChevronRight } from "lucide-react";

export default function MyPage() {
  return (
    <div className="page-view my-page" style={{ padding: "0 24px", overflowY: "auto" }}>
      <header className="top" style={{ padding: "20px 0 30px" }}>
        <div className="brand">
          <b>我的</b>
          <span>设置与设备管理</span>
        </div>
      </header>

      {/* User Profile Section */}
      <div className="profile-section" style={{ display: "flex", alignItems: "center", gap: "16px", marginBottom: "40px" }}>
        <div style={{ width: 64, height: 64, borderRadius: "50%", background: "linear-gradient(135deg, var(--green), var(--aqua))", display: "flex", justifyContent: "center", alignItems: "center" }}>
          <User size={32} color="#000" />
        </div>
        <div>
          <h2 style={{ fontSize: "20px", fontWeight: "600", marginBottom: "4px" }}>测试用户</h2>
          <p style={{ color: "var(--muted)", fontSize: "13px" }}>Reality Agent ID: 0x8A...2F</p>
        </div>
      </div>

      {/* Connected Devices */}
      <div className="section-title" style={{ fontSize: "12px", color: "var(--muted)", marginBottom: "12px", textTransform: "uppercase", letterSpacing: "1px" }}>已连接设备</div>
      <div className="device-card" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "16px", padding: "16px", marginBottom: "32px", display: "flex", alignItems: "center", gap: "16px" }}>
        <div style={{ padding: "10px", background: "rgba(255,255,255,0.05)", borderRadius: "12px" }}>
          <Bluetooth size={24} color="var(--aqua)" />
        </div>
        <div style={{ flex: 1 }}>
          <h4 style={{ fontSize: "15px", marginBottom: "4px" }}>Reality Glasses Pro</h4>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "12px", color: "var(--muted)" }}>
            <span style={{ color: "var(--green)", display: "flex", alignItems: "center", gap: "4px" }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--green)" }}></div> 已连接
            </span>
            <span>|</span>
            <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
              <Battery size={12} /> 82%
            </span>
          </div>
        </div>
      </div>

      {/* Settings List */}
      <div className="section-title" style={{ fontSize: "12px", color: "var(--muted)", marginBottom: "12px", textTransform: "uppercase", letterSpacing: "1px" }}>偏好设置</div>
      <div className="settings-list" style={{ background: "rgba(255,255,255,0.02)", borderRadius: "16px", overflow: "hidden" }}>
        {[
          { icon: <Shield size={18} />, label: "隐私与记忆管理", value: "" },
          { icon: <Moon size={18} />, label: "深色模式", value: "系统默认" },
          { icon: <Settings size={18} />, label: "高级调试选项 (Dev)", value: "" }
        ].map((item, idx) => (
          <div key={idx} style={{ 
            display: "flex", justifyContent: "space-between", alignItems: "center", 
            padding: "16px", borderBottom: idx === 2 ? "none" : "1px solid rgba(255,255,255,0.05)" 
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: "12px", fontSize: "15px" }}>
              <span style={{ color: "var(--muted)" }}>{item.icon}</span>
              <span>{item.label}</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--muted)", fontSize: "13px" }}>
              {item.value && <span>{item.value}</span>}
              <ChevronRight size={16} opacity={0.5} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
