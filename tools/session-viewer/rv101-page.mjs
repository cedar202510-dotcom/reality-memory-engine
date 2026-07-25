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
    .axis-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 6px;
      margin-bottom: 12px;
    }
    .axis-value {
      min-width: 0;
      padding: 7px 8px;
      border-left: 3px solid var(--axis-color);
      background: #f6f8f6;
    }
    .axis-value strong { display: block; font-size: 14px; }
    .axis-value span { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; }
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
    .event.ok { background: #f2f8f4; }
    .event.warn { background: #fff8e9; }
    .event.bad { background: #fff2f0; }
    .event.ok strong { color: var(--green); }
    .event.warn strong { color: var(--amber); }
    .event.bad strong { color: var(--red); }
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
      .axis-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>RV101 原生眼镜联调台</h1>
      <div class="subtitle">开发线直连 · 原生六轴与手环心率 · 图片 / 带声短视频 · 后端沉淀</div>
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
        <button type="button" data-command="system_video">测试系统带声视频</button>
        <button type="button" data-command="heart_rate_start">开始手环心率</button>
        <button type="button" data-command="heart_rate_stop">停止心率</button>
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
          <div class="subtitle" id="pipelineDetail" style="margin-top:6px"></div>
        </div>
      </section>

      <section class="panel span-8">
        <div class="panel-head">
          <div><h2>眼镜原生六轴变化</h2><div class="subtitle" id="sensorTitle">等待传感器窗口</div></div>
          <span class="badge" id="sensorBadge">无样本</span>
        </div>
        <div class="panel-body">
          <div class="metric-row" id="sensorMetrics"></div>
          <div class="axis-grid" id="sensorAxes"></div>
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
          <div><h2>手环实时心率</h2><div class="subtitle" id="heartRateStatus">尚未启动心率广播测试</div></div>
          <span class="badge" id="heartRateBadge">无样本</span>
        </div>
        <div class="panel-body">
          <div class="metric-row" id="heartRateMetrics"></div>
          <dl id="heartRateInfo" style="margin-top:14px"></dl>
        </div>
      </section>

      <section class="panel span-12">
        <div class="panel-head">
          <div><h2>音频链路诊断</h2><div class="subtitle">区分“文件生成成功”“系统允许录音”和“声音可被识别”</div></div>
          <span class="badge" id="audioBadge">等待样本</span>
        </div>
        <div class="panel-body"><dl id="audioInfo"></dl></div>
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
    const stateName = {
      ACTIVE: "总会话持续运行",
      ARMED: "等待佩戴",
      DISCLOSURE: "启动提示中",
      BLOCKED: "已阻止",
      ENDED: "已结束",
    };
    const resultName = {
      SUCCEEDED: "成功",
      FAILED: "失败",
      SKIPPED: "已跳过",
      UPLOADED: "已上传",
      PENDING: "等待上传",
      UPLOADING: "上传中",
      RETRYING: "等待重试",
      RETRY_PENDING: "等待重试",
      PERMANENT_FAILURE: "永久失败",
    };
    const reasonName = {
      CAMERA_BUSY: "相机正被另一项采集占用",
      DEVICE_UNAVAILABLE: "设备当前不可用",
      CAMERA_PREPARE_FAILED: "相机初始化失败",
      CAMERA_IMAGE_CAPTURE_FAILED: "拍照失败",
      CAMERA_VIDEO_CAPTURE_FAILED: "应用短视频录制失败",
      CAMERA_VIDEO_START_FAILED: "应用短视频启动失败",
      ROKID_SYSTEM_RECORDER_FAILED: "乐奇系统录制器没有生成有效视频",
      VIDEO_METADATA_FAILED: "视频元数据读取失败",
      VIDEO_FINALIZE_FAILED: "视频证据写入失败",
      FINALIZE_FAILED: "证据文件写入失败",
      DERIVED_FRAME_EXTRACTION_OR_FINALIZE_FAILED: "视频代表帧提取或写入失败",
      ANOTHER_CAPTURE_WINDOW_IS_ACTIVE: "另一项采集仍在进行，本次触发已合并跳过",
      NOT_WORN: "眼镜已摘下",
      USER_CLOSED_THIS_SESSION: "用户取消本次感知",
      LEGACY_TOGGLE_CANCELLED: "用户通过旧入口取消",
      SESSION_ENDED: "感知会话已结束",
      SERVICE_DESTROYED: "眼镜运行服务已终止",
      RESTART_FAILED: "六轴监听自动恢复失败",
      PROCESS_INTERRUPTED_RECOVERED: "应用进程曾被系统终止，重启后补记结束",
      BACKGROUND_ACTIVITY_OR_FULL_SCREEN_NOTIFICATION_NOT_SHOWN:
        "系统未展示后台页面或全屏通知",
    };
    const eventName = {
      SESSION_OPENED: "感知会话已开始",
      SESSION_STATE_CHANGED: "感知会话状态变化",
      CAPTURE_WINDOW_OPENED: "已打开采集窗口",
      CAPTURE_SKIPPED_BUSY: "采集触发已合并跳过",
      EVIDENCE_ENQUEUED: "证据已进入上传队列",
      EVIDENCE_UPLOAD_SUCCEEDED: "证据上传成功",
      EVIDENCE_UPLOAD_FAILED: "证据上传失败",
      EVIDENCE_UPLOAD_PERMANENT_FAILURE: "证据上传永久失败",
      CAMERA_PREPARED_IMAGE_ONLY: "眼镜相机已准备",
      CAMERA_PREPARE_FAILED: "眼镜相机准备失败",
      CAMERA_MODE_BOUND: "相机采集模式已启用",
      CAMERA_IMAGE_BIND_FAILED: "拍照模式启用失败",
      CAMERA_IMAGE_CAPTURE_FAILED: "拍照失败",
      CAMERA_IMAGE_RESTORE_FAILED: "拍照模式恢复失败",
      CAMERA_VIDEO_BIND_FAILED: "短视频模式启用失败",
      CAMERA_VIDEO_START_FAILED: "短视频启动失败",
      CAMERA_VIDEO_CAPTURE_FAILED: "短视频录制失败",
      AUDIO_CAPTURE_SYSTEM_SILENCED: "普通独立录音被系统静音",
      ROKID_SYSTEM_RECORDER_BIND_REQUESTED: "正在连接乐奇系统录制服务",
      ROKID_SYSTEM_RECORDER_WAITING_FOR_CONNECTION: "正在等待乐奇系统录制服务连接",
      ROKID_SYSTEM_VIDEO_REQUESTED: "已请求乐奇系统短视频",
      ROKID_SYSTEM_VIDEO_STARTED: "乐奇系统短视频已开始",
      ROKID_SYSTEM_VIDEO_SUCCEEDED: "乐奇系统短视频成功",
      ROKID_SYSTEM_VIDEO_FAILED: "乐奇系统短视频失败",
      ROKID_SYSTEM_KEYFRAME_SUCCEEDED: "视频代表帧提取成功",
      ROKID_SYSTEM_KEYFRAME_FAILED: "视频代表帧提取失败",
      HEART_RATE_BROADCAST_STATUS: "心率广播状态变化",
      HEART_RATE_BROADCAST_SAMPLE: "收到实时心率样本",
      HEART_RATE_EVIDENCE_SUCCEEDED: "心率证据批次已生成",
      HEART_RATE_EVIDENCE_FAILED: "心率证据批次生成失败",
      HEART_RATE_EVIDENCE_DEFERRED: "心率证据暂未生成",
      WEAR_STATE_RECEIVED: "收到眼镜佩戴状态",
      WEAR_STATE_RECONCILED: "已核对眼镜当前佩戴状态",
      RUNTIME_START_REQUESTED: "收到现实感知启动请求",
      WEAR_DISCLOSURE_UI_REQUESTED: "已请求显示佩戴提示",
      WEAR_DISCLOSURE_UI_VISIBLE: "佩戴提示已在眼镜显示",
      WEAR_DISCLOSURE_TEXT_FALLBACK_REQUESTED: "已请求显示佩戴文字提示",
      WEAR_DISCLOSURE_TEXT_FALLBACK_FAILED: "佩戴文字提示请求失败",
      WEAR_DISCLOSURE_UI_NOT_CONFIRMED: "佩戴圆环提示未确认显示",
      FOREGROUND_SERVICE_PROMOTION_REQUESTED: "已请求进入前台服务",
      FOREGROUND_SERVICE_PROMOTION_FAILED: "进入前台服务失败",
      STALE_SESSION_RECOVERED: "已结算上次异常中断的会话",
      STALE_SESSION_RECOVERY_FAILED: "异常会话恢复失败",
      SENSOR_LISTENER_STARTED: "眼镜六轴监听已启动",
      SENSOR_LISTENER_FAILED: "眼镜六轴监听启动失败",
      SENSOR_LISTENER_STOPPED: "眼镜六轴监听已停止",
      SENSOR_STREAM_STALLED: "眼镜六轴数据流中断",
      SENSOR_LISTENER_RESTARTED: "眼镜六轴监听已自动恢复",
      SENSOR_LISTENER_RESTART_FAILED: "眼镜六轴监听恢复失败",
    };
    const signalName = {
      GLASSES_HEAD_MOTION: "头部动作",
      HEAD_MOTION: "头部动作",
      HEAD_MOTION_TRANSITION: "头部视角变化",
      USER_EXPLICIT: "用户主动记录",
      DEBUG_TEST: "调试采集",
      WEAR: "佩戴启动",
      WEAR_CONFIRMED: "确认佩戴后启动",
      DEVELOPMENT_INSTALL: "开发安装后启动",
    };
    const motionPhaseName = {
      LEARNING: "学习静止基线",
      STABLE: "相对稳定",
      MOVING: "检测到视角变化",
      COOLDOWN: "触发后冷却",
    };
    const intensityName = { LOW: "轻微", MEDIUM: "中等", STRONG: "明显" };
    const detailKeyName = {
      capture_session_id: "会话",
      capture_window_id: "采集窗口",
      evidence_item_id: "证据",
      modality: "模态",
      http_status: "响应状态",
      attempt_count: "尝试次数",
      duration_ms: "计划时长",
      has_audio_track: "包含音轨",
      output_exists: "生成文件",
      output_bytes: "文件大小",
      service_connected: "系统服务已连接",
      derive_representative_frame: "提取代表帧",
      signal_kind: "触发原因",
      requested_modalities: "请求内容",
      mode: "模式",
      reason: "原因",
      message: "技术信息",
      worn: "当前佩戴",
      current_worn: "当前佩戴",
      previous_worn: "上次已知佩戴",
      resume_suppressed: "用户取消后保持停止",
      source: "状态来源",
      runtime_state: "运行状态",
      start_reason: "启动原因",
      strategy: "显示方式",
      sensor_mode: "传感器模式",
      accelerometer_name: "加速度计",
      gyroscope_name: "陀螺仪",
      accelerometer_registered: "加速度计注册",
      gyroscope_registered: "陀螺仪注册",
      stalled_for_ms: "断流时长",
      restart_count: "自动恢复次数",
      request_generation: "提示请求序号",
      previous_state: "中断前状态",
      end_reason: "结束原因",
      error: "错误",
      peak_dbfs: "峰值",
      rms_dbfs: "均方根",
      bpm: "心率",
      peripheral_name: "设备名称",
      peripheral_address: "设备地址",
      rssi: "信号强度",
      sample_count: "样本数",
      first_bpm: "首个心率",
      last_bpm: "末个心率",
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

    function localizeReason(code) {
      if (!code) return "—";
      if (reasonName[code]) return reasonName[code];
      if (String(code).startsWith("ROKID_SYSTEM_RECORDER_ERROR_")) {
        return "乐奇系统录制服务返回错误（代码 " + String(code).split("_").at(-1) + "）";
      }
      return String(code);
    }

    function localizeTechnicalError(value) {
      const text = String(value || "");
      if (text.includes("证据文件为空")) return "后端拒绝接收：证据文件为空";
      if (text.includes("HTTP 422")) return "后端校验未通过（HTTP 422）";
      if (text.includes("camera recorder stop failed")) {
        return "系统录制器没有正常进入录制状态，停止时失败，未生成视频文件";
      }
      if (text.includes("Access") && text.includes("restricted")) {
        return "应用退到后台后，相机访问被系统限制";
      }
      return text || "没有提供更多技术信息";
    }

    function localizeDetailValue(key, value) {
      if (value == null) return "无";
      if (key === "modality") return modalityName[value] || value;
      if (key === "signal_kind") return signalName[value] || value;
      if (key === "requested_modalities" && Array.isArray(value)) {
        return value.map((item) => modalityName[item] || item).join("、");
      }
      if (key === "reason") return localizeReason(value);
      if (key === "error" || key === "message") return localizeTechnicalError(value);
      if (key === "duration_ms") return fmtDuration(value);
      if (key === "output_bytes") return Number(value) ? Math.round(Number(value) / 1024) + " KB" : "0 KB";
      if (typeof value === "boolean") return value ? "是" : "否";
      if (Array.isArray(value)) return value.join("、");
      if (typeof value === "object") return JSON.stringify(value);
      return String(value);
    }

    function formatAuditDetail(item) {
      const detail = item.detail || {};
      if (item.event === "EVIDENCE_UPLOAD_FAILED") {
        return "第 " + (detail.attempt_count || "—") + " 次上传失败：" +
          localizeTechnicalError(detail.error);
      }
      if (item.event === "EVIDENCE_UPLOAD_PERMANENT_FAILURE") {
        return "后端已明确拒绝该证据，停止继续重试：" +
          localizeTechnicalError(detail.error);
      }
      if (item.event === "EVIDENCE_UPLOAD_SUCCEEDED") {
        return "已发送到电脑后端" + (detail.http_status ? "（HTTP " + detail.http_status + "）" : "");
      }
      if (item.event === "EVIDENCE_ENQUEUED") {
        return (modalityName[detail.modality] || detail.modality || "证据") + "已保存并等待上传";
      }
      if (item.event === "AUDIO_CAPTURE_SYSTEM_SILENCED") {
        return "普通 AudioRecord 入口被固件静音；音频应从乐奇系统带声视频取得";
      }
      if (item.event === "ROKID_SYSTEM_VIDEO_FAILED") {
        return localizeTechnicalError(detail.message || detail.error) +
          "；生成文件：" + (detail.output_exists ? "是" : "否") +
          "；大小：" + (detail.output_bytes ? Math.round(detail.output_bytes / 1024) + " KB" : "0 KB");
      }
      if (item.event === "HEART_RATE_BROADCAST_SAMPLE") {
        return "心率：" + detail.bpm + " BPM；设备：" +
          (detail.peripheral_name || "未命名手环") + "；信号：" +
          (detail.rssi == null ? "未知" : detail.rssi + " dBm");
      }
      if (item.event === "HEART_RATE_EVIDENCE_SUCCEEDED") {
        return "已将 " + detail.sample_count + " 个心率样本打包并进入上传队列；范围：" +
          detail.first_bpm + "–" + detail.last_bpm + " BPM";
      }
      if (item.event === "HEART_RATE_EVIDENCE_DEFERRED") {
        return "当前没有有效采集会话，" + detail.sample_count + " 个心率样本未进入证据队列";
      }
      return Object.entries(detail)
        .filter(([key]) => !["camera_inventory"].includes(key))
        .map(([key, value]) =>
          (detailKeyName[key] || key) + "：" + localizeDetailValue(key, value)
        )
        .join("；") || "无附加信息";
    }

    function auditKind(event) {
      if (event.includes("FAILED") || event.includes("FAILURE") || event.includes("SILENCED")) return "bad";
      if (event.includes("SUCCEEDED")) return "ok";
      if (event.includes("SKIPPED") || event.includes("NOT_CONFIRMED")) return "warn";
      return "";
    }

    function renderDevice(data) {
      const connected = data.connected && data.device;
      $("deviceDot").className = "dot " + (connected ? "ok" : data.error ? "bad" : "warn");
      $("deviceStatus").textContent = connected ? "RV101 已通过开发线连接" : "未检测到 RV101";
      $("deviceDetail").textContent = data.error || (connected
        ? data.device.serial + " · " + (data.app.processId ? "采集程序运行中" : "采集程序未运行")
        : "请检查开发线、USB 调试授权和眼镜连接状态。");
      badge(
        $("appBadge"),
        !data.app.installed
          ? "未安装"
          : data.app.activityForeground
            ? "页面在前台"
            : data.app.foregroundService
              ? "后台持续运行"
              : data.app.serviceRunning
                ? "后台稳定性不足"
                : data.app.processId
                  ? "仅进程存在"
                  : "已安装",
        data.app.foregroundService || data.app.activityForeground ? "ok" : "warn",
      );
      $("deviceInfo").innerHTML = definitionList([
        ["型号", data.device?.model],
        ["序列号", data.device?.serial],
        ["佩戴状态", data.worn == null ? "系统未返回" : data.worn ? "已佩戴" : "已摘下"],
        ["Android", data.device?.androidVersion],
        ["应用版本", data.app.versionName ? "v" + data.app.versionName + " (" + data.app.versionCode + ")" : null],
        ["应用进程", data.app.processId || "未运行"],
        [
          "应用页面",
          data.app.activityForeground
            ? "正在眼镜前台显示"
            : data.app.processId
              ? "未占用眼镜前台"
              : "未运行",
        ],
        [
          "运行服务",
          data.app.foregroundService
            ? "前台服务持续运行"
            : data.app.serviceRunning
              ? "普通后台服务，稳定性不足"
              : "未运行",
        ],
        ["ADB", data.adbPath],
      ]);
    }

    function renderSession(data) {
      const session = data.session;
      const live = data.liveSensor;
      const liveAgeMs = live?.updated_at
        ? Date.now() - new Date(live.updated_at).getTime()
        : Infinity;
      const sensorState = live?.active === false
        ? "监听已停止"
        : live && liveAgeMs <= 5_000
          ? "实时监听中"
          : live && liveAgeMs <= 15_000
            ? "数据刷新稍慢"
            : live
              ? "数据已断流"
              : "尚无六轴状态";
      const windowState = data.window?.state === "OPEN"
        ? "本次短采集正在录制"
        : data.window
          ? "最近一次短采集已结束"
          : "尚未触发短采集";
      badge(
        $("sessionBadge"),
        stateName[session?.state] || session?.state || "无会话",
        session?.state === "ACTIVE" ? "ok" : "warn",
      );
      $("sessionInfo").innerHTML = definitionList([
        ["会话编号", session?.capture_session_id],
        ["总会话", stateName[session?.state] || session?.state],
        ["六轴监听", sensorState],
        ["短采集窗口", windowState],
        ["启动原因", signalName[session?.start_reason] || session?.start_reason],
        ["开始时间", fmtTime(session?.started_at)],
        ["最近采集窗口", data.window?.capture_window_id],
        ["窗口信号", signalName[data.intent?.signal_kind] || data.intent?.signal_kind],
        ["请求模态", data.intent?.requested_modalities?.map((item) => modalityName[item] || item).join("、")],
        ["运行时版本", session?.runtime_version],
      ]);
    }

    function renderPipeline(data) {
      const uploaded = data.uploads.filter((item) => item.state === "UPLOADED" || item.state === "SUCCEEDED").length;
      const permanentFailures = data.uploads.filter((item) => item.state === "PERMANENT_FAILURE").length;
      const pending = data.uploads.filter((item) =>
        item.state && !["UPLOADED", "SUCCEEDED", "PERMANENT_FAILURE"].includes(item.state)
      ).length;
      const backend = data.backend.connected;
      const pipeline = data.pipeline;
      const pipelineStages = pipeline?.stages || {};
      const received = Number(pipelineStages.source_envelopes?.count || 0);
      const stored = Number(pipelineStages.evidence_items?.count || 0);
      const assets = Number(pipelineStages.structured_assets?.count || 0);
      const observations = Number(pipelineStages.atomic_observations?.count || 0);
      const candidates = Number(pipelineStages.memory_candidates?.count || 0);
      const events = Number(pipelineStages.memory_events?.count || 0);
      const projections = Number(pipelineStages.state_projections?.count || 0);
      const agent = Boolean(data.agent?.connected);
      const stages = [
        ["真机证据", data.evidence.length ? data.evidence.length + " 条" : "等待采集", data.evidence.length ? "ok" : "pending"],
        [
          "设备上传",
          [
            uploaded ? uploaded + " 条成功" : "",
            pending ? pending + " 条待重试" : "",
            permanentFailures ? permanentFailures + " 条永久失败" : "",
          ].filter(Boolean).join(" / ") || "尚无记录",
          permanentFailures ? "warn" : uploaded ? "ok" : pending ? "warn" : "pending",
        ],
        ["后端接收", received || stored ? received + " 个信封 / " + stored + " 条证据" : backend ? "等待本会话" : "未连接", received || stored ? "ok" : backend ? "pending" : "warn"],
        ["结构化沉淀", assets || observations || candidates ? assets + " 份资产 / " + observations + " 条观察" : pipeline?.error ? "状态接口不可用" : "尚未形成观察", assets ? "ok" : pipeline?.error ? "warn" : "pending"],
        ["事实与顾问", events || projections ? events + " 条事实 / " + projections + " 个状态" : agent ? "顾问在线，尚无本会话事实" : "顾问未启动", events || projections ? "ok" : agent ? "pending" : "warn"],
      ];
      $("pipeline").innerHTML = stages.map(([title, detail, kind]) =>
        '<div class="stage ' + kind + '"><strong>' + esc(title) + '</strong>' + esc(detail) + '</div>'
      ).join("");
      badge($("backendBadge"), backend ? "后端在线" : "后端未启动", backend ? "ok" : "warn");
      $("backendDetail").textContent = data.backend.url + " · " + data.backend.detail +
        "；顾问 " + (agent ? "在线" : "未启动") + " · " + data.agent.url;
      const parsed = pipelineStages.structured_assets || {};
      const summary = parsed.latest_transcript
        ? "最新语音转写：" + parsed.latest_transcript
        : parsed.latest_caption
          ? "最新图片描述：" + parsed.latest_caption
          : "";
      const limitations = Array.isArray(pipeline?.limitations) ? pipeline.limitations.join("；") : "";
      $("pipelineDetail").textContent = pipeline?.error || [summary, limitations].filter(Boolean).join("。") || "等待本会话进入后端。";
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
      const live = sensorData?.live || null;
      const latest = summary?.samples?.at(-1) || null;
      const liveAgeMs = live?.updated_at
        ? Date.now() - new Date(live.updated_at).getTime()
        : Infinity;
      const streamStopped = live && live.active === false;
      const streamDelayed =
        live && live.active !== false && liveAgeMs > 5000 && liveAgeMs <= 15000;
      const streamStalled = live && live.active !== false && liveAgeMs > 15000;
      const streamLabel = streamStopped
        ? "监听已停止"
        : streamStalled
          ? "数据已断流"
          : streamDelayed
            ? "电脑刷新延迟"
          : summary
            ? (live ? "实时 · " : "") + sensorData.sampleCount + " 个样本"
            : "无样本";
      badge(
        $("sensorBadge"),
        streamLabel,
        streamStopped || streamStalled
          ? "bad"
          : streamDelayed
            ? "warn"
            : summary
              ? "ok"
              : "",
      );
      $("sensorTitle").textContent = live
        ? (streamStopped
            ? "监听已停止：" + (reasonName[live.stop_reason] || live.stop_reason || "未知原因")
            : streamStalled
              ? "超过 15 秒没有收到新六轴数据"
              : streamDelayed
                ? "眼镜数据仍在监听，电脑页面刷新稍慢"
              : (motionPhaseName[live.phase] || live.phase || "后台监听中")) +
          " · 更新 " + fmtTime(live.updated_at) +
          (live.sensor_mode
            ? " · " + (live.sensor_mode === "WAKE_UP" ? "唤醒型传感器" : "普通传感器")
            : "")
        : sensorData?.item
          ? fmtTime(sensorData.item.captured_at) + " · " + (sensorData.item.capture_window_id || "")
          : "等待传感器窗口";
      const metrics = summary ? [
        [fmtNumber(latest?.gyro) + " rad/s", "当前角速度强度"],
        [live ? fmtNumber(live.start_threshold_rad_s) + " rad/s" : fmtNumber(summary.maxGyro) + " rad/s", live ? "当前触发阈值" : "峰值角速度"],
        [
          fmtNumber(latest?.linear_acceleration_m_s2) + " m/s²",
          "当前线性加速度",
        ],
        [
          fmtNumber(live?.sample_rate_target_hz ?? summary.rate, 1) + " Hz",
          live ? "眼镜原始采样频率" : "实际采样频率",
        ],
      ] : [["—", "当前角速度强度"], ["—", "当前触发阈值"], ["—", "当前线性加速度"], ["—", "实际采样频率"]];
      $("sensorMetrics").innerHTML = metrics.map(([value, label]) =>
        '<div class="metric"><strong>' + esc(value) + '</strong><span>' + esc(label) + '</span></div>'
      ).join("");
      const axes = latest ? [
        ["AX", latest.ax, "m/s²", "#246c9e"],
        ["AY", latest.ay, "m/s²", "#a76300"],
        ["AZ", latest.az, "m/s²", "#b83a3a"],
        ["GX", latest.gx, "rad/s", "#246c9e"],
        ["GY", latest.gy, "rad/s", "#a76300"],
        ["GZ", latest.gz, "rad/s", "#b83a3a"],
      ] : [["AX"], ["AY"], ["AZ"], ["GX"], ["GY"], ["GZ"]];
      $("sensorAxes").innerHTML = axes.map(([label, value, unit, color]) =>
        '<div class="axis-value" style="--axis-color:' + esc(color || "#a5aea9") + '">' +
        '<strong>' + esc(value == null ? "—" : fmtNumber(value, 3)) + '</strong>' +
        '<span>' + esc(label + (unit ? " · " + unit : "")) + '</span></div>'
      ).join("");
      drawSensorChart();
    }

    function renderDecision(data) {
      const intent = data.intent;
      const metrics = intent?.metrics || {};
      const title = intent
        ? (signalName[intent.signal_kind] || intent.signal_kind || "未知信号") + " · " + (intensityName[intent.intensity] || intent.intensity || "未分级")
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
          ? data.attempts.map((item) =>
              (modalityName[item.modality] || item.modality) + " " +
              (resultName[item.result] || item.result) +
              (item.reason_code ? "（" + localizeReason(item.reason_code) + "）" : "")
            ).join("；")
          : "—"],
      ].map(([key, value]) => '<div class="strategy-row"><span>' + esc(key) + '</span><strong>' + esc(value) + '</strong></div>').join("");
    }

    function renderAudioDiagnostics(data) {
      const direct = data.audioDiagnostics?.directAudio;
      const systemVideo = data.audioDiagnostics?.systemVideo;
      let state = "等待样本";
      let kind = "";
      if (systemVideo?.hasAudioTrack === true) {
        state = "系统带声视频可用";
        kind = "ok";
      } else if (direct?.systemSilenced === true) {
        state = "普通录音被系统静音";
        kind = "warn";
      } else if (direct?.likelySilent === false) {
        state = "普通录音有信号";
        kind = "ok";
      } else if (direct) {
        state = "普通录音疑似静音";
        kind = "warn";
      }
      badge($("audioBadge"), state, kind);
      $("audioInfo").innerHTML = definitionList([
        ["普通短音频入口", direct?.captureMode || "尚无样本"],
        ["系统静音标记", direct?.systemSilenced == null ? "尚未检测" : direct.systemSilenced ? "是，固件已静音" : "否"],
        ["普通录音峰值", direct?.peakDbfs == null ? null : fmtNumber(direct.peakDbfs) + " dBFS"],
        ["普通录音均方根", direct?.rmsDbfs == null ? null : fmtNumber(direct.rmsDbfs) + " dBFS"],
        ["乐奇系统视频音轨", systemVideo == null ? "尚未测试" : systemVideo.hasAudioTrack ? "存在" : "不存在"],
        ["系统视频时长", systemVideo?.durationMs == null ? null : fmtDuration(systemVideo.durationMs)],
        ["系统视频上传", resultName[systemVideo?.uploadState] || systemVideo?.uploadState || "尚无记录"],
      ]);
    }

    function renderHeartRate(data) {
      const heartRate = data.heartRate || {};
      const latest = heartRate.latest;
      const latestTime = latest ? new Date(latest.capturedAt).getTime() : 0;
      const recent = latestTime && Date.now() - latestTime <= 10_000;
      badge(
        $("heartRateBadge"),
        latest ? (recent ? "实时接收中" : "样本已中断") : "无样本",
        latest ? (recent ? "ok" : "warn") : "",
      );
      $("heartRateStatus").textContent = heartRate.status || "尚未启动心率广播测试";
      const metrics = [
        [latest?.bpm == null ? "—" : latest.bpm + " BPM", "最新心率"],
        [heartRate.sampleCount ? heartRate.sampleCount + " 个" : "—", "当前审计窗样本"],
        [heartRate.averageIntervalMs == null ? "—" : fmtDuration(heartRate.averageIntervalMs), "平均通知间隔"],
        [heartRate.maxGapMs == null ? "—" : fmtDuration(heartRate.maxGapMs), "最长中断"],
      ];
      $("heartRateMetrics").innerHTML = metrics.map(([value, label]) =>
        '<div class="metric"><strong>' + esc(value) + '</strong><span>' + esc(label) + '</span></div>'
      ).join("");
      const batch = heartRate.latestBatch;
      $("heartRateInfo").innerHTML = definitionList([
        ["手环名称", latest?.peripheralName || "尚未识别"],
        ["BLE 地址", latest?.peripheralAddress],
        ["接收信号", latest?.rssi == null ? null : latest.rssi + " dBm"],
        ["最后样本", fmtTime(latest?.capturedAt)],
        [
          "连续性判断",
          heartRate.sampleCount < 3
            ? "样本不足"
            : heartRate.stable
              ? "最近接收稳定"
              : "最近存在超过 5 秒的中断",
        ],
        [
          "最近证据批次",
          batch
            ? (batch.succeeded ? "成功" : "失败") + " · " + fmtTime(batch.occurredAt) +
              (batch.sample_count ? " · " + batch.sample_count + " 个样本" : "")
            : "尚未形成",
        ],
      ]);
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
        const uploadKind = ["UPLOADED", "SUCCEEDED"].includes(item.upload_state)
          ? "ok"
          : item.upload_state === "PERMANENT_FAILURE"
            ? "bad"
            : item.upload_state
              ? "warn"
              : "";
        return '<article class="media-item">' + visual +
          '<div class="media-copy"><div class="media-title"><span>' + esc(modalityName[item.modality] || item.modality) +
          '</span><span class="badge ' + uploadKind + '">' + esc(resultName[item.upload_state] || item.upload_state || "仅在眼镜本地") + '</span></div>' +
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
        '<div class="event ' + auditKind(item.event) + '"><span class="event-time">' + esc(fmtTime(item.occurred_at)) +
        '</span><strong>' + esc(eventName[item.event] || item.event) + '</strong><span class="event-detail">' +
        esc(formatAuditDetail(item)) + '</span></div>'
      ).join("") : '<div class="empty">尚无设备审计事件。</div>';
    }

    async function loadSensor(data) {
      if (data.liveSensor) {
        sensorId = "live:" + data.liveSensor.sequence;
        sensorData = {
          item: null,
          live: data.liveSensor,
          sampleCount: data.liveSensor.samples.length,
          samples: data.liveSensor.samples,
        };
        renderSensor();
        return;
      }
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
      renderHeartRate(current);
      renderAudioDiagnostics(current);
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
    }), 750);
    load().catch((error) => {
      $("deviceDetail").textContent = error.message;
      $("deviceDot").className = "dot bad";
    });
    renderSensor();
  </script>
</body>
</html>`;
