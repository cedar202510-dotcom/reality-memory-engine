#!/usr/bin/env node
import { createServer } from "node:http";
import { readFile, readdir, stat } from "node:fs/promises";
import { createReadStream } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_PORT = 8787;
const DEFAULT_SAMPLE_RATE = 16000;
const HOST = "127.0.0.1";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootArg = process.argv[2] || process.env.RME_CAPTURE_ROOT || process.cwd();
const port = Number(process.env.PORT || process.argv[3] || DEFAULT_PORT);
const captureRoot = await resolveCaptureRoot(path.resolve(rootArg));

function sendJson(res, value, status = 200) {
  const body = Buffer.from(JSON.stringify(value, null, 2));
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": body.length,
    "cache-control": "no-store",
  });
  res.end(body);
}

function sendText(res, text, status = 200, contentType = "text/plain; charset=utf-8") {
  const body = Buffer.from(text);
  res.writeHead(status, {
    "content-type": contentType,
    "content-length": body.length,
    "cache-control": "no-store",
  });
  res.end(body);
}

function fail(res, error, status = 500) {
  sendJson(res, { error: error instanceof Error ? error.message : String(error) }, status);
}

async function exists(p) {
  try {
    await stat(p);
    return true;
  } catch {
    return false;
  }
}

async function resolveCaptureRoot(inputRoot) {
  const candidates = [
    inputRoot,
    path.join(inputRoot, "RealityMemoryProbe"),
    path.join(inputRoot, "Library", "Application Support", "RealityMemoryProbe"),
  ];
  for (const candidate of candidates) {
    if (await exists(path.join(candidate, "sessions"))) {
      return candidate;
    }
  }
  throw new Error(
    `找不到 sessions 目录。请传入 RealityMemoryProbe 根目录，或包含 RealityMemoryProbe 的拉取目录：${inputRoot}`,
  );
}

function safeJoin(root, relativePath) {
  const clean = String(relativePath || "").replace(/^\/+/, "");
  const resolved = path.resolve(root, clean);
  const rootWithSep = root.endsWith(path.sep) ? root : `${root}${path.sep}`;
  if (resolved !== root && !resolved.startsWith(rootWithSep)) {
    throw new Error(`非法路径：${relativePath}`);
  }
  return resolved;
}

function secondsBetween(base, value) {
  if (!base || !value) return null;
  const diff = new Date(value).getTime() - new Date(base).getTime();
  if (!Number.isFinite(diff)) return null;
  return Math.max(0, diff / 1000);
}

function pickObservationType(observation) {
  const mediaType = observation.mediaType || observation.type || observation.modality || "";
  const localRef = observation.localRef || observation.localPath || observation.localMediaReference || "";
  if (/audio/i.test(mediaType) || /\.pcm$/i.test(localRef)) return "audio";
  if (/image|photo/i.test(mediaType) || /\.(jpe?g|png|webp|heic)$/i.test(localRef)) return "image";
  return "event";
}

function normalizeObservation(session, observation, index) {
  const startedAt = observation.startedAt || observation.scheduledAt || observation.capturedAt || observation.requestedAt || observation.createdAt || null;
  const endedAt = observation.endedAt || observation.completedAt || null;
  const completedAt = observation.completedAt || endedAt || startedAt;
  const type = pickObservationType(observation);
  return {
    index,
    id: observation.id || observation.observationId || `observation-${index}`,
    type,
    status: observation.analysisState || observation.status || observation.outcome || "UNKNOWN",
    trigger: observation.trigger || observation.captureTrigger || observation.reason || null,
    startedAt,
    endedAt,
    completedAt,
    startOffsetSec: secondsBetween(session.startedAt, startedAt || completedAt),
    endOffsetSec: secondsBetween(session.startedAt, endedAt || completedAt || startedAt),
    localRef: observation.localRef || observation.localPath || observation.localMediaReference || observation.evidenceLocalRef || null,
    bytes: observation.bytes || observation.byteCount || observation.sizeBytes || null,
    durationMs: observation.durationMs || observation.durationMilliseconds || observation.audioDurationMs || null,
    peakDbfs: observation.peakDbfs ?? observation.peakDBFS ?? null,
    raw: observation,
  };
}

function getObservations(session) {
  const direct = [
    ...(Array.isArray(session.imageObservations) ? session.imageObservations : []),
    ...(Array.isArray(session.audioObservations) ? session.audioObservations : []),
    ...(Array.isArray(session.observations) ? session.observations : []),
  ];
  return direct
    .map((observation, index) => normalizeObservation(session, observation, index))
    .sort((a, b) => (a.startOffsetSec ?? a.endOffsetSec ?? 0) - (b.startOffsetSec ?? b.endOffsetSec ?? 0));
}

async function readSession(sessionId) {
  const sessionPath = safeJoin(path.join(captureRoot, "sessions"), path.join(sessionId, "session.json"));
  const session = JSON.parse(await readFile(sessionPath, "utf8"));
  const observations = getObservations(session);
  return {
    ...session,
    viewer: {
      sessionId,
      observations,
      imageCount: observations.filter((item) => item.type === "image").length,
      audioCount: observations.filter((item) => item.type === "audio").length,
      eventCount: observations.filter((item) => item.type === "event").length,
      auditCount: Array.isArray(session.audit) ? session.audit.length : Array.isArray(session.auditEvents) ? session.auditEvents.length : 0,
    },
  };
}

async function listSessions() {
  const sessionsDir = path.join(captureRoot, "sessions");
  const entries = await readdir(sessionsDir, { withFileTypes: true });
  const summaries = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    try {
      const session = await readSession(entry.name);
      summaries.push({
        id: entry.name,
        state: session.state || "UNKNOWN",
        startedAt: session.startedAt || null,
        endedAt: session.endedAt || null,
        intervalSeconds: session.intervalSeconds ?? null,
        retainLocalSamples: Boolean(session.retainLocalSamples),
        uploadAllowed: Boolean(session.uploadAllowed),
        audioPolicy: session.audioPolicy || null,
        imageCount: session.viewer.imageCount,
        audioCount: session.viewer.audioCount,
        eventCount: session.viewer.eventCount,
        auditCount: session.viewer.auditCount,
      });
    } catch (error) {
      summaries.push({ id: entry.name, error: error.message });
    }
  }
  summaries.sort((a, b) => String(b.startedAt || "").localeCompare(String(a.startedAt || "")));
  return summaries;
}

async function detectMime(filePath) {
  const buffer = await readFile(filePath);
  if (buffer.length >= 12 && buffer.subarray(0, 4).toString("ascii") === "RIFF" && buffer.subarray(8, 12).toString("ascii") === "WEBP") {
    return "image/webp";
  }
  if (buffer.length >= 3 && buffer[0] === 0xff && buffer[1] === 0xd8 && buffer[2] === 0xff) return "image/jpeg";
  if (buffer.length >= 8 && buffer.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return "image/png";
  if (buffer.length >= 12 && buffer.subarray(4, 12).toString("ascii") === "ftypheic") return "image/heic";
  return "application/octet-stream";
}

function wavHeader(dataLength, sampleRate, channels = 1, bitsPerSample = 16) {
  const header = Buffer.alloc(44);
  const byteRate = sampleRate * channels * bitsPerSample / 8;
  const blockAlign = channels * bitsPerSample / 8;
  header.write("RIFF", 0);
  header.writeUInt32LE(36 + dataLength, 4);
  header.write("WAVE", 8);
  header.write("fmt ", 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(channels, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write("data", 36);
  header.writeUInt32LE(dataLength, 40);
  return header;
}

async function sendMedia(res, sessionId, relativeRef) {
  if (!relativeRef) throw new Error("缺少媒体路径");
  const sessionDir = safeJoin(path.join(captureRoot, "sessions"), sessionId);
  const filePath = safeJoin(sessionDir, relativeRef);
  const mime = await detectMime(filePath);
  const fileStat = await stat(filePath);
  res.writeHead(200, {
    "content-type": mime,
    "content-length": fileStat.size,
    "cache-control": "no-store",
  });
  createReadStream(filePath).pipe(res);
}

async function sendAudio(res, sessionId, relativeRef, sampleRate) {
  if (!relativeRef) throw new Error("缺少音频路径");
  const sessionDir = safeJoin(path.join(captureRoot, "sessions"), sessionId);
  const filePath = safeJoin(sessionDir, relativeRef);
  const fileStat = await stat(filePath);
  const rate = Number(sampleRate) || DEFAULT_SAMPLE_RATE;
  res.writeHead(200, {
    "content-type": "audio/wav",
    "cache-control": "no-store",
  });
  res.write(wavHeader(fileStat.size, rate));
  createReadStream(filePath).pipe(res);
}

const page = String.raw`<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Reality Memory Session Viewer</title>
  <style>
    :root {
      --bg: #f6f7f8;
      --panel: #ffffff;
      --ink: #172026;
      --muted: #66727c;
      --line: #d9e0e5;
      --image: #1f7a70;
      --audio: #b25c22;
      --event: #4967a9;
      --bad: #b42318;
      --ok: #1d7f43;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
      letter-spacing: 0;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 22px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
      position: sticky;
      top: 0;
      z-index: 4;
    }
    h1 { font-size: 18px; margin: 0; font-weight: 720; }
    button, select {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 7px;
      min-height: 34px;
      padding: 0 10px;
      font-size: 13px;
    }
    button { cursor: pointer; }
    button.active { background: #172026; color: #fff; border-color: #172026; }
    main {
      display: grid;
      grid-template-columns: minmax(260px, 320px) 1fr;
      min-height: calc(100vh - 72px);
    }
    aside {
      border-right: 1px solid var(--line);
      background: #fbfcfc;
      padding: 14px;
      overflow: auto;
    }
    .workspace {
      padding: 16px 20px 28px;
      overflow: auto;
    }
    .root {
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .session-list {
      display: grid;
      gap: 8px;
      margin-top: 14px;
    }
    .session-row {
      width: 100%;
      text-align: left;
      padding: 10px;
      min-height: 78px;
      background: #fff;
    }
    .session-id {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 11px;
      overflow-wrap: anywhere;
      color: #25313a;
    }
    .meta {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 7px;
      color: var(--muted);
      font-size: 12px;
    }
    .pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 2px 7px;
      background: #fff;
      white-space: nowrap;
    }
    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(6, minmax(120px, 1fr));
      gap: 8px;
      margin-bottom: 16px;
    }
    .metric {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 10px;
      min-height: 68px;
    }
    .metric span { display: block; color: var(--muted); font-size: 12px; }
    .metric strong { display: block; font-size: 18px; margin-top: 5px; }
    .timeline {
      border-top: 1px solid var(--line);
      margin: 18px 0;
      padding-top: 12px;
    }
    .rail {
      position: relative;
      height: 56px;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 8px;
      overflow: hidden;
    }
    .tick {
      position: absolute;
      top: 0;
      bottom: 0;
      width: 1px;
      background: #e7ebee;
    }
    .marker {
      position: absolute;
      top: 11px;
      height: 32px;
      min-width: 10px;
      border-radius: 6px;
      transform: translateX(-50%);
      border: 1px solid rgba(0,0,0,.08);
    }
    .marker.image { background: var(--image); }
    .marker.audio { background: var(--audio); transform: none; opacity: .9; }
    .marker.event { background: var(--event); }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 12px;
    }
    article {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      overflow: hidden;
    }
    article .body { padding: 10px; }
    .preview {
      width: 100%;
      aspect-ratio: 4 / 3;
      background: #eef1f3;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    .preview img {
      width: 100%;
      height: 100%;
      object-fit: contain;
    }
    audio { width: 100%; margin-top: 8px; }
    .item-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
      font-weight: 700;
    }
    .small {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }
    details { margin-top: 8px; }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      background: #f3f5f6;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      max-height: 260px;
      overflow: auto;
      font-size: 11px;
    }
    .empty {
      padding: 40px;
      text-align: center;
      color: var(--muted);
    }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .summary { grid-template-columns: repeat(2, 1fr); }
      header { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Reality Memory 采集查看器</h1>
      <div class="root" id="root"></div>
    </div>
    <div>
      <button id="refresh">刷新</button>
    </div>
  </header>
  <main>
    <aside>
      <div class="small">Session 是一次采集窗口；这里按时间把图片、短音频和设备/审计事件放在一起，方便判断它们能否在后续解析层对齐。</div>
      <div class="session-list" id="sessions"></div>
    </aside>
    <section class="workspace" id="workspace">
      <div class="empty">选择左侧一次 Session</div>
    </section>
  </main>
  <script>
    const state = { sessions: [], current: null, sampleRate: 16000 };
    const $ = (id) => document.getElementById(id);

    function fmtTime(value) {
      if (!value) return "未写入";
      return new Date(value).toLocaleString("zh-CN", { hour12: false });
    }

    function fmtOffset(value) {
      if (value === null || value === undefined) return "-";
      return "+" + Number(value).toFixed(1) + "s";
    }

    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[ch]));
    }

    async function api(path) {
      const res = await fetch(path, { cache: "no-store" });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }

    async function loadSessions() {
      const data = await api("/api/sessions");
      state.sessions = data.sessions;
      $("root").textContent = data.root;
      renderSessionList();
      if (state.sessions.length && !state.current) {
        await loadSession(state.sessions[0].id);
      }
    }

    function renderSessionList() {
      $("sessions").innerHTML = state.sessions.map((item) => {
        const active = state.current === item.id ? " active" : "";
        return '<button class="session-row' + active + '" data-id="' + esc(item.id) + '">' +
          '<div class="session-id">' + esc(item.id) + '</div>' +
          '<div class="meta">' +
            '<span class="pill">' + esc(item.state) + '</span>' +
            '<span class="pill">图 ' + esc(item.imageCount) + '</span>' +
            '<span class="pill">音 ' + esc(item.audioCount) + '</span>' +
            '<span class="pill">' + esc(fmtTime(item.startedAt)) + '</span>' +
          '</div>' +
        '</button>';
      }).join("");
      document.querySelectorAll(".session-row").forEach((button) => {
        button.addEventListener("click", () => loadSession(button.dataset.id));
      });
    }

    async function loadSession(id) {
      state.current = id;
      renderSessionList();
      const session = await api("/api/session?id=" + encodeURIComponent(id));
      renderSession(session);
    }

    function renderSession(session) {
      const obs = session.viewer.observations;
      const maxSec = Math.max(10, ...obs.map((item) => item.endOffsetSec ?? item.startOffsetSec ?? 0));
      $("workspace").innerHTML = [
        renderToolbar(session),
        renderSummary(session),
        renderTimeline(obs, maxSec),
        '<div class="grid">' + obs.map((item) => renderObservation(session.viewer.sessionId, item)).join("") + '</div>'
      ].join("");
      $("sampleRate").addEventListener("change", (event) => {
        state.sampleRate = Number(event.target.value);
        document.querySelectorAll("audio[data-ref]").forEach((audio) => {
          audio.src = audioSrc(session.viewer.sessionId, audio.dataset.ref);
        });
      });
    }

    function renderToolbar(session) {
      return '<div class="toolbar">' +
        '<div><strong>Session</strong><div class="small">' + esc(session.viewer.sessionId) + '</div></div>' +
        '<label class="small">PCM 播放采样率 <select id="sampleRate">' +
          [16000, 24000, 32000, 44100, 48000].map((rate) => '<option value="' + rate + '"' + (rate === state.sampleRate ? " selected" : "") + '>' + rate + ' Hz</option>').join("") +
        '</select></label>' +
      '</div>';
    }

    function renderSummary(session) {
      const items = [
        ["状态", session.state || "UNKNOWN"],
        ["开始", fmtTime(session.startedAt)],
        ["结束", fmtTime(session.endedAt)],
        ["图片", session.viewer.imageCount],
        ["短音频", session.viewer.audioCount],
        ["审计事件", session.viewer.auditCount],
      ];
      return '<div class="summary">' + items.map(([label, value]) =>
        '<div class="metric"><span>' + esc(label) + '</span><strong>' + esc(value) + '</strong></div>'
      ).join("") + '</div>' +
      '<div class="small">采集间隔：' + esc(session.intervalSeconds ?? "-") +
      ' 秒 · 本地样本：' + esc(session.retainLocalSamples ? "保留" : "不保留") +
      ' · 上传：' + esc(session.uploadAllowed ? "允许" : "关闭") +
      ' · 会话 VAD：' + esc(session.audioPolicy?.sessionVADEnabled ? "开启" : "关闭") + '</div>';
    }

    function renderTimeline(obs, maxSec) {
      const ticks = Array.from({ length: 6 }, (_, idx) => idx * 20).map((left) =>
        '<span class="tick" style="left:' + left + '%"></span>'
      ).join("");
      const markers = obs.map((item) => {
        const start = Math.min(100, ((item.startOffsetSec ?? item.endOffsetSec ?? 0) / maxSec) * 100);
        const end = Math.min(100, ((item.endOffsetSec ?? item.startOffsetSec ?? 0) / maxSec) * 100);
        const width = item.type === "audio" ? Math.max(1.2, end - start) : 1.8;
        return '<span class="marker ' + esc(item.type) + '" title="' + esc(item.type + " " + fmtOffset(item.startOffsetSec)) +
          '" style="left:' + start + '%;width:' + width + '%"></span>';
      }).join("");
      return '<div class="timeline"><div class="small">时间线：从 Session 开始计时，总跨度约 ' + esc(maxSec.toFixed(1)) +
        ' 秒。绿色是图片，橙色是短音频，蓝色是事件。</div><div class="rail">' + ticks + markers + '</div></div>';
    }

    function mediaSrc(sessionId, ref) {
      return "/media?session=" + encodeURIComponent(sessionId) + "&ref=" + encodeURIComponent(ref);
    }

    function audioSrc(sessionId, ref) {
      return "/audio.wav?session=" + encodeURIComponent(sessionId) + "&ref=" + encodeURIComponent(ref) + "&rate=" + encodeURIComponent(state.sampleRate);
    }

    function renderObservation(sessionId, item) {
      const title = item.type === "image" ? "图片证据" : item.type === "audio" ? "短音频证据" : "事件";
      const preview = item.type === "image" && item.localRef
        ? '<div class="preview"><img src="' + esc(mediaSrc(sessionId, item.localRef)) + '" alt="capture"></div>'
        : '<div class="preview"><span class="small">' + esc(title) + '</span></div>';
      const player = item.type === "audio" && item.localRef
        ? '<audio controls preload="metadata" data-ref="' + esc(item.localRef) + '" src="' + esc(audioSrc(sessionId, item.localRef)) + '"></audio>'
        : "";
      return '<article>' + preview + '<div class="body">' +
        '<div class="item-title"><span>' + esc(title) + '</span><span class="pill">' + esc(item.status) + '</span></div>' +
        '<div class="small">' +
          esc(fmtOffset(item.startOffsetSec)) + ' → ' + esc(fmtOffset(item.endOffsetSec)) +
          (item.durationMs ? ' · ' + esc(item.durationMs) + 'ms' : '') +
          (item.bytes ? ' · ' + esc(item.bytes) + ' bytes' : '') +
          (item.peakDbfs !== null ? ' · peak ' + esc(Number(item.peakDbfs).toFixed(2)) + ' dBFS' : '') +
        '</div>' +
        '<div class="small">' + esc(item.localRef || "无本地文件") + '</div>' +
        player +
        '<details><summary class="small">原始记录 JSON</summary><pre>' + esc(JSON.stringify(item.raw, null, 2)) + '</pre></details>' +
      '</div></article>';
    }

    $("refresh").addEventListener("click", loadSessions);
    loadSessions().catch((error) => {
      $("workspace").innerHTML = '<div class="empty">' + esc(error.message) + '</div>';
    });
  </script>
</body>
</html>`;

const server = createServer(async (req, res) => {
  try {
    const requestUrl = new URL(req.url || "/", `http://${HOST}:${port}`);
    if (requestUrl.pathname === "/") {
      sendText(res, page, 200, "text/html; charset=utf-8");
      return;
    }
    if (requestUrl.pathname === "/api/sessions") {
      sendJson(res, { root: captureRoot, sessions: await listSessions() });
      return;
    }
    if (requestUrl.pathname === "/api/session") {
      const id = requestUrl.searchParams.get("id");
      if (!id) return fail(res, new Error("缺少 session id"), 400);
      sendJson(res, await readSession(id));
      return;
    }
    if (requestUrl.pathname === "/media") {
      await sendMedia(res, requestUrl.searchParams.get("session"), requestUrl.searchParams.get("ref"));
      return;
    }
    if (requestUrl.pathname === "/audio.wav") {
      await sendAudio(res, requestUrl.searchParams.get("session"), requestUrl.searchParams.get("ref"), requestUrl.searchParams.get("rate"));
      return;
    }
    sendText(res, "Not found", 404);
  } catch (error) {
    fail(res, error, 500);
  }
});

server.listen(port, HOST, () => {
  console.log(`Reality Memory Session Viewer`);
  console.log(`Root: ${captureRoot}`);
  console.log(`URL:  http://${HOST}:${port}`);
  console.log(``);
  console.log(`Usage: node ${path.relative(process.cwd(), path.join(__dirname, "server.mjs"))} <RealityMemoryProbe-or-pulled-container> [port]`);
});
