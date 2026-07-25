export const rv101Page = `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RV101 原生眼镜联调台</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17201c;
      --muted: #66716b;
      --line: #d8ded9;
      --surface: #ffffff;
      --canvas: #f3f6f4;
      --green: #16794a;
      --green-soft: #e5f2eb;
      --blue: #246c9e;
      --amber: #a76300;
      --red: #b83a3a;
      --black: #111714;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--canvas);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }
    button, a { font: inherit; }
    button {
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 5px;
      padding: 0 12px;
      color: var(--ink);
      background: var(--surface);
      cursor: pointer;
      font-size: 13px;
      font-weight: 650;
    }
    button:hover { border-color: #9aa69f; background: #f8faf8; }
    button:disabled { cursor: wait; opacity: .55; }
    button.primary { color: white; border-color: var(--green); background: var(--green); }
    button.danger { color: var(--red); }
    header {
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      min-height: 68px;
      padding: 12px 22px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.96);
      backdrop-filter: blur(12px);
    }
    h1, h2, h3, p { margin: 0; }
    h1 { font-size: 18px; line-height: 1.2; }
    h2 { font-size: 15px; line-height: 1.25; }
    .subtitle { margin-top: 4px; color: var(--muted); font-size: 12px; }
    .header-actions, .commands, .status-line, .panel-title, .legend {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .header-actions a {
      color: var(--muted);
      text-decoration: none;
      padding: 7px 9px;
      border-radius: 4px;
      font-size: 13px;
    }
    .header-actions a:hover { color: var(--ink); background: var(--canvas); }
    .header-actions a.current { color: var(--green); background: var(--green-soft); font-weight: 700; }
    main {
      width: min(1480px, calc(100% - 28px));
      margin: 14px auto 32px;
    }
    .status-bar {
      display: grid;
      grid-template-columns: 1fr auto;
      align-items: center;
      gap: 16px;
      min-height: 52px;
      padding: 10px 14px;
      border: 1px solid var(--line);
      background: var(--surface);
    }
    .dot {
      display: inline-block;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: #a5aea9;
      flex: 0 0 auto;
    }
    .dot.ok { background: var(--green); box-shadow: 0 0 0 3px var(--green-soft); }
    .dot.warn { background: var(--amber); }
    .dot.bad { background: var(--red); }
    .status-copy { font-size: 13px; font-weight: 700; }
    .status-detail { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
    .commands { flex-wrap: wrap; justify-content: flex-end; }
    .grid {
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .panel {
      min-width: 0;
      border: 1px solid var(--line);
      background: var(--surface);
    }
    .panel-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      min-height: 48px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }
    .panel-body { padding: 13px 14px; }
    .span-3 { grid-column: span 3; }
    .span-4 { grid-column: span 4; }
    .span-5 { grid-column: span 5; }
    .span-7 { grid-column: span 7; }
    .span-8 { grid-column: span 8; }
    .span-12 { grid-column: span 12; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 23px;
      padding: 2px 7px;
      border-radius: 999px;
      color: var(--muted);
      background: #edf0ee;
      font-size: 11px;
      font-weight: 750;
      white-space: nowrap;
    }
    .badge.ok { color: var(--green); background: var(--green-soft); }
    .badge.warn { color: var(--amber); background: #fff1d8; }
    .badge.bad { color: var(--red); background: #fde9e7; }
    dl {
      display: grid;
      grid-template-columns: minmax(88px, .7fr) minmax(0, 1.4fr);
      gap: 9px 12px;
      margin: 0;
      font-size: 12px;
    }
    dt { color: var(--muted); }
    dd { margin: 0; font-weight: 650; overflow-wrap: anywhere; }
    .metric-row {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px;
      margin-bottom: 12px;
    }
    .metric {
      min-width: 0;
      padding: 9px 10px;
      border: 1px solid var(--line);
      background: #fafbfa;
    }
    .metric strong { display: block; font-size: 18px; line-height: 1.15; }
    .metric span { display: block; margin-top: 4px; color: var(--muted); font-size: 11px; }
    .chart-wrap {
      position: relative;
      width: 100%;
      height: 310px;
      border: 1px solid var(--line);
      background: #fbfcfb;
    }
    canvas { display: block; width: 100%; height: 100%; }
    .legend { margin-top: 9px; flex-wrap: wrap; color: var(--muted); font-size: 11px; }
    .legend span::before {
      content: "";
      display: inline-block;
      width: 12px;
      height: 2px;
      margin-right: 5px;
      vertical-align: middle;
      background: var(--legend-color);
    }
    .decision {
      padding: 12px;
      border-left: 3px solid var(--green);
      background: #f4f8f5;
    }
    .decision-title { font-size: 17px; font-weight: 780; }
    .decision-detail { margin-top: 7px; color: var(--muted); font-size: 12px; line-height: 1.55; }
    .strategy {
      display: grid;
      gap: 7px;
      margin-top: 12px;
    }
    .strategy-row {
      display: grid;
      grid-template-columns: 82px 1fr;
      gap: 8px;
      font-size: 12px;
    }
    .strategy-row span:first-child { color: var(--muted); }
    .pipeline {
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 6px;
    }
    .stage {
      position: relative;
      min-height: 62px;
      padding: 9px 8px;
      border: 1px solid var(--line);
      background: #fafbfa;
      font-size: 11px;
    }
    .stage strong { display: block; margin-bottom: 5px; font-size: 12px; }
    .stage.ok { border-color: #add2bc; background: #f1f8f4; }
    .stage.warn { border-color: #e5c58f; background: #fffaf1; }
    .stage.pending { color: var(--muted); }
    .media-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .media-item {
      min-width: 0;
      border: 1px solid var(--line);
      background: #fafbfa;
    }
    .media-visual {
      display: grid;
      place-items: center;
      width: 100%;
      aspect-ratio: 16 / 10;
      overflow: hidden;
      background: var(--black);
    }
    .media-visual img, .media-visual video {
      width: 100%;
      height: 100%;
      object-fit: contain;
    }
    .media-visual.audio {
      aspect-ratio: auto;
      min-height: 82px;
      padding: 14px;
      background: #eef3ef;
    }
    audio { width: 100%; }
    .media-copy { padding: 9px 10px; }
    .media-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 12px;
      font-weight: 750;
    }
    .media-meta { margin-top: 5px; color: var(--muted); font-size: 11px; line-height: 1.45; overflow-wrap: anywhere; }
    .events {
      max-height: 360px;
      overflow: auto;
      border: 1px solid var(--line);
    }
    .event {
      display: grid;
      grid-template-columns: 164px 180px minmax(0, 1fr);
      gap: 9px;
      padding: 8px 10px;
      border-bottom: 1px solid #e8ece9;
      font-size: 11px;
    }
    .event:last-child { border-bottom: 0; }
    .event-time, .event-detail { color: var(--muted); }
    .empty { padding: 24px 10px; color: var(--muted); text-align: center; font-size: 12px; }
    .error { color: var(--red); }
    @media (max-width: 1060px) {
      .span-3, .span-4, .span-5, .span-7, .span-8 { grid-column: span 6; }
      .media-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
      header, .status-bar { align-items: flex-start; grid-template-columns: 1fr; flex-direction: column; }
      .commands { justify-content: flex-start; }
      .span-3, .span-4, .span-5, .span-7, .span-8, .span-12 { grid-column: span 12; }
      .metric-row, .pipeline, .media-grid { grid-template-columns: 1fr 1fr; }
      .event { grid-template-columns: 1fr; }
      .chart-wrap { height: 250px; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>RV101 原生眼镜联调台</h1>
      <div class="subtitle">开发线直连 · 原生六轴 · 图片 / 短视频 / 短音频 · 后端沉淀</div>
    </div>
    <nav class="header-actions">
      <a href="/">手机中介链路</a>
      <a href="/rv101" class="current">RV101 原生链路</a>
    </nav>
  </header>

  <main>
    <section class="status-bar">
      <div>
        <div class="status-line">
          <span class="dot" id="deviceDot"></span>
          <span class="status-copy" id="deviceStatus">正在检查开发线...</span>
        </div>
        <div class="status-detail" id="deviceDetail">调试台将自动识别 RG_glasses，并读取正式应用的调试导出。</div>
      </div>
      <div class="commands">
        <button type="button" data-command="connect_backend">连接本地后端</button>
        <button type="button" data-command="wake_start" class="primary">唤醒并启动</button>
        <button type="button" data-command="capture_now">立即记录</button>
        <button type="button" data-command="end_session" class="danger">结束本次</button>
        <button type="button" data-command="refresh" title="重新读取真机状态">刷新</button>
      </div>
    </section>

    <div class="grid">
      <section class="panel span-3">
        <div class="panel-head">
          <div><h2>眼镜设备</h2><div class="subtitle">ADB 开发线</div></div>
          <span class="badge" id="appBadge">检查中</span>
        </div>
        <div class="panel-body"><dl id="deviceInfo"></dl></div>
      </section>

      <section class="panel span-4">
        <div class="panel-head">
          <div><h2>当前采集会话</h2><div class="subtitle">从佩戴或显式启动到结束的一段连续运行</div></div>
          <span class="badge" id="sessionBadge">无会话</span>
        </div>
        <div class="panel-body"><dl id="sessionInfo"></dl></div>
      </section>

      <section class="panel span-5">
        <div class="panel-head">
          <div><h2>本地后端链路</h2><div class="subtitle">眼镜通过开发线反向端口连接电脑</div></div>
          <span class="badge" id="backendBadge">未连接</span>
        </div>
        <div class="panel-body">
          <div class="pipeline" id="pipeline"></div>
          <div class="subtitle" id="backendDetail" style="margin-top:10px"></div>
        </div>
      </section>

      <section class="panel span-8">
        <div class="panel-head">
          <div><h2>眼镜原生六轴变化</h2><div class="subtitle" id="sensorTitle">等待传感器窗口</div></div>
          <span class="badge" id="sensorBadge">无样本</span>
        </div>
        <div class="panel-body">
          <div class="metric-row" id="sensorMetrics"></div>
          <div class="chart-wrap"><canvas id="sensorChart"></canvas></div>
          <div class="legend">
            <span style="--legend-color:#16794a">角速度总强度</span>
            <span style="--legend-color:#246c9e">X 轴</span>
            <span style="--legend-color:#a76300">Y 轴</span>
            <span style="--legend-color:#b83a3a">Z 轴</span>
          </div>
        </div>
      </section>

      <section class="panel span-4">
        <div class="panel-head">
          <div><h2>最近一次触发判断</h2><div class="subtitle">头部变化先形成采集意图，再开启同一时间窗</div></div>
        </div>
        <div class="panel-body">
          <div class="decision" id="decision"></div>
          <div class="strategy" id="strategy"></div>
        </div>
      </section>

      <section class="panel span-12">
        <div class="panel-head">
          <div><h2>眼镜实际采集内容</h2><div class="subtitle">这里只读取调试 APK 的短期明文副本；正式媒体仍按证据策略加密与过期删除</div></div>
          <span class="badge" id="mediaBadge">0 条</span>
        </div>
        <div class="panel-body"><div class="media-grid" id="mediaGrid"></div></div>
      </section>

      <section class="panel span-12">
        <div class="panel-head">
          <div><h2>设备事件与采集审计</h2><div class="subtitle">用于回答“为什么触发、为什么没触发、采集是否成功”</div></div>
          <span class="badge" id="updatedAt">尚未刷新</span>
        </div>
        <div class="panel-body"><div class="events" id="events"></div></div>
      </section>
    </div>
  </main>

  <script>
    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
    const fmtTime = (value) => {
      if (!value) return "—";
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
    };
    const fmtDuration = (value) => {
      const ms = Number(value);
      if (!Number.isFinite(ms)) return "—";
      return ms >= 1000 ? (ms / 1000).toFixed(1) + " 秒" : ms + " 毫秒";
    };
    const fmtNumber = (value, digits = 2) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
    const modalityName = { IMAGE: "图片", VIDEO: "短视频", AUDIO: "短音频", SENSOR: "六轴传感器" };
    const signalName = {
      GLASSES_HEAD_MOTION: "头部动作",
      HEAD_MOTION: "头部动作",
      USER_EXPLICIT: "用户主动记录",
      DEBUG_TEST: "周期调试记录",
      WEAR: "佩戴启动",
    };
    let current = null;
    let sensorData = null;
    let sensorId = null;
    let mediaSignature = "";
    let commandBusy = false;

    function badge(element, text, kind = "") {
      element.textContent = text;
      element.className = "badge" + (kind ? " " + kind : "");
    }

    function definitionList(rows) {
      return rows.map(([key, value]) => "<dt>" + esc(key) + "</dt><dd>" + esc(value ?? "—") + "</dd>").join("");
    }

    function renderDevice(data) {
      const connected = data.connected && data.device;
      $("deviceDot").className = "dot " + (connected ? "ok" : data.error ? "bad" : "warn");
      $("deviceStatus").textContent = connected ? "RV101 已通过开发线连接" : "未检测到 RV101";
      $("deviceDetail").textContent = data.error || (connected
        ? data.device.serial + " · " + (data.app.processId ? "采集程序运行中" : "采集程序未运行")
        : "请检查开发线、USB 调试授权和眼镜连接状态。");
      badge($("appBadge"), data.app.installed ? (data.app.processId ? "运行中" : "已安装") : "未安装", data.app.processId ? "ok" : "warn");
      $("deviceInfo").innerHTML = definitionList([
        ["型号", data.device?.model],
        ["序列号", data.device?.serial],
        ["Android", data.device?.androidVersion],
        ["应用版本", data.app.versionName ? "v" + data.app.versionName + " (" + data.app.versionCode + ")" : null],
        ["应用进程", data.app.processId || "未运行"],
        ["ADB", data.adbPath],
      ]);
    }

    function renderSession(data) {
      const session = data.session;
      badge($("sessionBadge"), session?.state || "无会话", session?.state === "ACTIVE" ? "ok" : "warn");
      $("sessionInfo").innerHTML = definitionList([
        ["会话编号", session?.capture_session_id],
        ["当前状态", session?.state],
        ["启动原因", session?.start_reason],
        ["开始时间", fmtTime(session?.started_at)],
        ["当前采集窗口", data.window?.capture_window_id],
        ["窗口信号", signalName[data.intent?.signal_kind] || data.intent?.signal_kind],
        ["请求模态", data.intent?.requested_modalities?.map((item) => modalityName[item] || item).join("、")],
        ["运行时版本", session?.runtime_version],
      ]);
    }

    function renderPipeline(data) {
      const uploaded = data.uploads.filter((item) => item.state === "UPLOADED" || item.state === "SUCCEEDED").length;
      const pending = data.uploads.filter((item) => item.state && !["UPLOADED", "SUCCEEDED"].includes(item.state)).length;
      const backend = data.backend.connected;
      const stages = [
        ["真机证据", data.evidence.length ? data.evidence.length + " 条" : "等待采集", data.evidence.length ? "ok" : "pending"],
        ["设备上传", uploaded ? uploaded + " 条成功" : pending ? pending + " 条待重试" : "尚无记录", uploaded ? "ok" : pending ? "warn" : "pending"],
        ["接收网关", backend ? "服务在线" : "未连接", backend ? "ok" : "warn"],
        ["结构化沉淀", backend ? "待本轮验证" : "等待后端", "pending"],
        ["顾问 Agent", backend ? "待本轮验证" : "等待后端", "pending"],
      ];
      $("pipeline").innerHTML = stages.map(([title, detail, kind]) =>
        '<div class="stage ' + kind + '"><strong>' + esc(title) + '</strong>' + esc(detail) + '</div>'
      ).join("");
      badge($("backendBadge"), backend ? "后端在线" : "后端未启动", backend ? "ok" : "warn");
      $("backendDetail").textContent = data.backend.url + " · " + data.backend.detail;
    }

    function summarizeSensor(samples) {
      if (!samples.length) return null;
      const derived = samples.map((sample) => {
        const gx = Number(sample.gx_rad_s || 0);
        const gy = Number(sample.gy_rad_s || 0);
        const gz = Number(sample.gz_rad_s || 0);
        const ax = Number(sample.ax_m_s2 || 0);
        const ay = Number(sample.ay_m_s2 || 0);
        const az = Number(sample.az_m_s2 || 0);
        return { ...sample, gx, gy, gz, ax, ay, az, gyro: Math.hypot(gx, gy, gz), accel: Math.hypot(ax, ay, az) };
      });
      const durationMs = (Number(derived.at(-1).monotonic_ns) - Number(derived[0].monotonic_ns)) / 1e6;
      return {
        samples: derived,
        maxGyro: Math.max(...derived.map((sample) => sample.gyro)),
        maxAccel: Math.max(...derived.map((sample) => sample.accel)),
        rate: durationMs > 0 ? (derived.length - 1) * 1000 / durationMs : 0,
        durationMs,
      };
    }

    function drawSensorChart() {
      const canvas = $("sensorChart");
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(rect.width * ratio));
      canvas.height = Math.max(1, Math.round(rect.height * ratio));
      const ctx = canvas.getContext("2d");
      ctx.scale(ratio, ratio);
      const width = rect.width;
      const height = rect.height;
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#fbfcfb";
      ctx.fillRect(0, 0, width, height);
      const summary = summarizeSensor(sensorData?.samples || []);
      if (!summary) {
        ctx.fillStyle = "#66716b";
        ctx.font = "12px -apple-system, sans-serif";
        ctx.textAlign = "center";
        ctx.fillText("尚未读取到眼镜六轴样本", width / 2, height / 2);
        return;
      }
      const samples = summary.samples;
      const padding = { left: 45, right: 14, top: 16, bottom: 28 };
      const chartWidth = width - padding.left - padding.right;
      const chartHeight = height - padding.top - padding.bottom;
      const maxAbs = Math.max(0.6, ...samples.flatMap((s) => [Math.abs(s.gx), Math.abs(s.gy), Math.abs(s.gz), s.gyro]));
      const range = Math.ceil(maxAbs * 10) / 10;
      const x = (index) => padding.left + index / Math.max(1, samples.length - 1) * chartWidth;
      const y = (value) => padding.top + (range - value) / (range * 2) * chartHeight;

      ctx.strokeStyle = "#e1e6e2";
      ctx.lineWidth = 1;
      ctx.fillStyle = "#76817b";
      ctx.font = "10px -apple-system, sans-serif";
      ctx.textAlign = "right";
      for (let index = 0; index <= 4; index++) {
        const value = range - index * range / 2;
        const rowY = padding.top + index / 4 * chartHeight;
        ctx.beginPath();
        ctx.moveTo(padding.left, rowY);
        ctx.lineTo(width - padding.right, rowY);
        ctx.stroke();
        ctx.fillText(value.toFixed(1), padding.left - 7, rowY + 3);
      }
      const lines = [
        ["gyro", "#16794a", 2.2],
        ["gx", "#246c9e", 1.2],
        ["gy", "#a76300", 1.2],
        ["gz", "#b83a3a", 1.2],
      ];
      for (const [key, color, lineWidth] of lines) {
        ctx.beginPath();
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        samples.forEach((sample, index) => {
          const pointX = x(index);
          const pointY = y(sample[key]);
          if (index === 0) ctx.moveTo(pointX, pointY);
          else ctx.lineTo(pointX, pointY);
        });
        ctx.stroke();
      }
      ctx.fillStyle = "#66716b";
      ctx.textAlign = "left";
      ctx.fillText("0 秒", padding.left, height - 8);
      ctx.textAlign = "right";
      ctx.fillText((summary.durationMs / 1000).toFixed(1) + " 秒", width - padding.right, height - 8);
    }

    function renderSensor() {
      const summary = summarizeSensor(sensorData?.samples || []);
      badge($("sensorBadge"), summary ? sensorData.sampleCount + " 个样本" : "无样本", summary ? "ok" : "");
      $("sensorTitle").textContent = sensorData?.item
        ? fmtTime(sensorData.item.captured_at) + " · " + (sensorData.item.capture_window_id || "")
        : "等待传感器窗口";
      const metrics = summary ? [
        [fmtNumber(summary.maxGyro) + " rad/s", "峰值角速度"],
        [fmtNumber(summary.maxAccel) + " m/s²", "峰值合加速度"],
        [fmtNumber(summary.rate, 1) + " Hz", "实际采样频率"],
        [fmtDuration(summary.durationMs), "样本时间窗"],
      ] : [["—", "峰值角速度"], ["—", "峰值合加速度"], ["—", "实际采样频率"], ["—", "样本时间窗"]];
      $("sensorMetrics").innerHTML = metrics.map(([value, label]) =>
        '<div class="metric"><strong>' + esc(value) + '</strong><span>' + esc(label) + '</span></div>'
      ).join("");
      drawSensorChart();
    }

    function renderDecision(data) {
      const intent = data.intent;
      const metrics = intent?.metrics || {};
      const title = intent
        ? (signalName[intent.signal_kind] || intent.signal_kind || "未知信号") + " · " + (intent.intensity || "未分级")
        : "尚未形成采集意图";
      $("decision").innerHTML =
        '<div class="decision-title">' + esc(title) + '</div>' +
        '<div class="decision-detail">' + esc(intent
          ? "本次请求：" + (intent.requested_modalities || []).map((item) => modalityName[item] || item).join("、")
          : "转动头部或点击“立即记录”后，这里会显示真实触发原因。") + '</div>';
      $("strategy").innerHTML = [
        ["峰值角速度", metrics.peak_gyro_rad_s != null ? fmtNumber(metrics.peak_gyro_rad_s) + " rad/s" : "—"],
        ["累计转角", metrics.integrated_rotation_deg != null ? fmtNumber(metrics.integrated_rotation_deg, 1) + "°" : "—"],
        ["最大线性加速度", metrics.max_linear_acceleration_m_s2 != null ? fmtNumber(metrics.max_linear_acceleration_m_s2) + " m/s²" : "—"],
        ["动作持续", metrics.duration_ms != null ? fmtDuration(metrics.duration_ms) : "—"],
        ["规则版本", intent?.detector_rule_version || "—"],
        ["采集结果", data.attempts.length
          ? data.attempts.map((item) => (modalityName[item.modality] || item.modality) + " " + item.result).join("；")
          : "—"],
      ].map(([key, value]) => '<div class="strategy-row"><span>' + esc(key) + '</span><strong>' + esc(value) + '</strong></div>').join("");
    }

    function renderMedia(data) {
      const display = data.media.filter((item) => item.modality !== "SENSOR").slice(0, 9);
      const signature = display.map((item) => item.id + ":" + item.upload_state).join("|");
      badge($("mediaBadge"), data.media.length + " 条证据副本", data.media.length ? "ok" : "");
      if (signature === mediaSignature) return;
      mediaSignature = signature;
      if (!display.length) {
        $("mediaGrid").innerHTML = '<div class="empty">尚无图片、短视频或短音频。</div>';
        return;
      }
      $("mediaGrid").innerHTML = display.map((item) => {
        const url = "/api/rv101/media?id=" + encodeURIComponent(item.id);
        let visual = "";
        if (item.modality === "IMAGE") {
          visual = '<div class="media-visual"><img loading="lazy" src="' + url + '" alt="RV101 实际采集图片"></div>';
        } else if (item.modality === "VIDEO") {
          visual = '<div class="media-visual"><video controls preload="metadata" src="' + url + '"></video></div>';
        } else if (item.modality === "AUDIO") {
          visual = '<div class="media-visual audio"><audio controls preload="metadata" src="/api/rv101/audio?id=' + encodeURIComponent(item.id) + '"></audio></div>';
        }
        const uploadKind = ["UPLOADED", "SUCCEEDED"].includes(item.upload_state) ? "ok" : item.upload_state ? "warn" : "";
        return '<article class="media-item">' + visual +
          '<div class="media-copy"><div class="media-title"><span>' + esc(modalityName[item.modality] || item.modality) +
          '</span><span class="badge ' + uploadKind + '">' + esc(item.upload_state || "本地") + '</span></div>' +
          '<div class="media-meta">' + esc(fmtTime(item.captured_at)) + '<br>' +
          esc(item.id) + '<br>' + esc(item.byte_count ? Math.round(item.byte_count / 1024) + " KB" : "") +
          (item.upload_error ? '<br><span class="error">' + esc(item.upload_error) + '</span>' : "") +
          '</div></div></article>';
      }).join("");
    }

    function renderEvents(data) {
      $("updatedAt").textContent = data.lastUpdatedAt ? "刷新 " + new Date(data.lastUpdatedAt).toLocaleTimeString("zh-CN", { hour12: false }) : "尚未刷新";
      const events = data.audit.slice(0, 80);
      $("events").innerHTML = events.length ? events.map((item) =>
        '<div class="event"><span class="event-time">' + esc(fmtTime(item.occurred_at)) +
        '</span><strong>' + esc(item.event) + '</strong><span class="event-detail">' +
        esc(JSON.stringify(item.detail || {})) + '</span></div>'
      ).join("") : '<div class="empty">尚无设备审计事件。</div>';
    }

    async function loadSensor(data) {
      const next = data.media.find((item) => item.modality === "SENSOR");
      if (!next) {
        sensorId = null;
        sensorData = null;
        renderSensor();
        return;
      }
      if (next.id === sensorId) return;
      sensorId = next.id;
      const response = await fetch("/api/rv101/sensor?id=" + encodeURIComponent(next.id), { cache: "no-store" });
      if (!response.ok) throw new Error((await response.json()).error || "读取六轴数据失败");
      sensorData = await response.json();
      renderSensor();
    }

    async function load() {
      const response = await fetch("/api/rv101", { cache: "no-store" });
      if (!response.ok) throw new Error((await response.json()).error || "读取真机状态失败");
      current = await response.json();
      renderDevice(current);
      renderSession(current);
      renderPipeline(current);
      renderDecision(current);
      renderMedia(current);
      renderEvents(current);
      await loadSensor(current);
    }

    async function sendCommand(command, button) {
      if (commandBusy) return;
      commandBusy = true;
      document.querySelectorAll("button[data-command]").forEach((item) => { item.disabled = true; });
      try {
        const response = await fetch("/api/rv101/command", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ command }),
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.error || "命令执行失败");
        await load();
      } catch (error) {
        $("deviceDetail").textContent = error.message;
        $("deviceDot").className = "dot bad";
      } finally {
        commandBusy = false;
        document.querySelectorAll("button[data-command]").forEach((item) => { item.disabled = false; });
      }
    }

    document.querySelectorAll("button[data-command]").forEach((button) => {
      button.addEventListener("click", () => sendCommand(button.dataset.command, button));
    });
    window.addEventListener("resize", drawSensorChart);
    setInterval(() => load().catch((error) => {
      $("deviceDetail").textContent = error.message;
      $("deviceDot").className = "dot bad";
    }), 1_500);
    load().catch((error) => {
      $("deviceDetail").textContent = error.message;
      $("deviceDot").className = "dot bad";
    });
    renderSensor();
  </script>
</body>
</html>`;
