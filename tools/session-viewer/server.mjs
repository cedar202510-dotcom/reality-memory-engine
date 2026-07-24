#!/usr/bin/env node
import { createServer } from "node:http";
import { readFile, readdir, stat, mkdir, writeFile } from "node:fs/promises";
import { createReadStream } from "node:fs";
import { createServer as createNetServer } from "node:net";
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_PORT = 8787;
const DEFAULT_BRIDGE_PORT = 8791;
const DEFAULT_SAMPLE_RATE = 16000;
const HOST = "127.0.0.1";
const ACTION_SAMPLE_DATASET_VERSION = "ring-action-calibration.v3";
const ACTION_MOUNT_FINGER = "FINGER_WORN";
const ACTION_MOUNT_GLASSES = "GLASSES_MOUNTED";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const argumentsWithoutFlags = process.argv.slice(2).filter((value) => value !== "--live");
const liveEnabled = process.argv.includes("--live");
const defaultLiveRoot = path.join(os.homedir(), "Library", "Application Support", "RealityMemoryDebug");
const rootArg = argumentsWithoutFlags[0] || process.env.RME_CAPTURE_ROOT || (liveEnabled ? defaultLiveRoot : process.cwd());
const port = Number(process.env.PORT || argumentsWithoutFlags[1] || DEFAULT_PORT);
if (liveEnabled) {
  await mkdir(path.join(path.resolve(rootArg), "sessions"), { recursive: true });
}
const captureRoot = await resolveCaptureRoot(path.resolve(rootArg));

const liveBridge = {
  enabled: liveEnabled,
  connected: false,
  connectedAt: null,
  remoteAddress: null,
  lastMessageAt: null,
  snapshot: null,
  ringSamples: [],
  media: [],
  socket: null,
  previousRingSample: null,
  bonjourProcess: null,
  server: null,
  actionSamples: [],
  activeActionCapture: null,
  actionCaptureTimer: null,
};

const actionSamplesPath = path.join(captureRoot, "action-samples.json");
try {
  const savedActionSamples = JSON.parse(await readFile(actionSamplesPath, "utf8"));
  if (Array.isArray(savedActionSamples)) {
    liveBridge.actionSamples = savedActionSamples.slice(0, 120).map((sample) => ({
      ...sample,
      datasetVersion: sample.datasetVersion || "ring-action-calibration.v1",
      mountPosition: sample.mountPosition || ACTION_MOUNT_FINGER,
    }));
  }
} catch {
  // The file is created after the first completed action sample.
}

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

async function readJsonBody(req) {
  const chunks = [];
  let length = 0;
  for await (const chunk of req) {
    length += chunk.length;
    if (length > 64 * 1024) throw new Error("请求内容过大");
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

function detectMimeBuffer(buffer) {
  if (buffer.length >= 12 && buffer.subarray(0, 4).toString("ascii") === "RIFF" && buffer.subarray(8, 12).toString("ascii") === "WEBP") {
    return "image/webp";
  }
  if (buffer.length >= 3 && buffer[0] === 0xff && buffer[1] === 0xd8 && buffer[2] === 0xff) return "image/jpeg";
  if (buffer.length >= 8 && buffer.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return "image/png";
  if (buffer.length >= 12 && buffer.subarray(4, 12).toString("ascii") === "ftypheic") return "image/heic";
  return "application/octet-stream";
}

function ringSampleTime(sample, lastSample, receivedAt, sampleRateHz, index, count) {
  const receivedMilliseconds = new Date(receivedAt).getTime();
  if (Number.isFinite(receivedMilliseconds) && lastSample) {
    const delta = (Number(lastSample.timestampMilliseconds) - Number(sample.timestampMilliseconds)) >>> 0;
    if (delta < 60_000) return receivedMilliseconds - delta;
  }
  const interval = 1000 / Math.max(1, Number(sampleRateHz) || 25);
  return (Number.isFinite(receivedMilliseconds) ? receivedMilliseconds : Date.now()) - (count - index - 1) * interval;
}

function appendLiveRingBatch(payload) {
  const batch = payload?.batch;
  const samples = Array.isArray(batch?.samples) ? batch.samples : [];
  if (!samples.length) return;
  const configuration = payload.configuration || {};
  const accelerationScale = Number(configuration.accelRangeG || 0) / 32768;
  const gyroscopeScale = Number(configuration.gyroRangeDPS || 0) / 32768;
  const lastSample = samples[samples.length - 1];

  samples.forEach((sample, index) => {
    const accelerationMagnitudeRaw = Math.hypot(Number(sample.accelX), Number(sample.accelY), Number(sample.accelZ));
    const gyroscopeMagnitudeRaw = Math.hypot(Number(sample.gyroX), Number(sample.gyroY), Number(sample.gyroZ));
    const previous = liveBridge.previousRingSample;
    const accelerationDeltaRaw = previous
      ? Math.hypot(
        Number(sample.accelX) - Number(previous.accelX),
        Number(sample.accelY) - Number(previous.accelY),
        Number(sample.accelZ) - Number(previous.accelZ),
      )
      : 0;
    liveBridge.ringSamples.push({
      time: ringSampleTime(sample, lastSample, payload.receivedAt, configuration.sampleRateHz, index, samples.length),
      timestampMilliseconds: sample.timestampMilliseconds,
      accelX: Number(sample.accelX),
      accelY: Number(sample.accelY),
      accelZ: Number(sample.accelZ),
      gyroX: Number(sample.gyroX),
      gyroY: Number(sample.gyroY),
      gyroZ: Number(sample.gyroZ),
      accelXG: Number(sample.accelX) * accelerationScale,
      accelYG: Number(sample.accelY) * accelerationScale,
      accelZG: Number(sample.accelZ) * accelerationScale,
      gyroXDPS: Number(sample.gyroX) * gyroscopeScale,
      gyroYDPS: Number(sample.gyroY) * gyroscopeScale,
      gyroZDPS: Number(sample.gyroZ) * gyroscopeScale,
      accelerationMagnitudeRaw,
      accelerationDeltaRaw,
      gyroscopeMagnitudeRaw,
      accelerationMagnitudeG: accelerationMagnitudeRaw * accelerationScale,
      accelerationDeltaG: accelerationDeltaRaw * accelerationScale,
      gyroscopeMagnitudeDPS: gyroscopeMagnitudeRaw * gyroscopeScale,
      accelerationDeltaThresholdRaw: Number(payload.accelerationDeltaThresholdRaw || 0),
      gyroscopeMagnitudeThresholdRaw: Number(payload.gyroscopeMagnitudeThresholdRaw || 0),
    });
    liveBridge.previousRingSample = sample;
  });
  if (liveBridge.ringSamples.length > 1_500) {
    liveBridge.ringSamples.splice(0, liveBridge.ringSamples.length - 1_500);
  }
}

function summarizeActionValues(values, scale) {
  return {
    p50Raw: percentile(values, 0.50),
    p90Raw: percentile(values, 0.90),
    p95Raw: percentile(values, 0.95),
    p99Raw: percentile(values, 0.99),
    maxRaw: values.length ? Math.max(...values) : 0,
    p50Physical: percentile(values, 0.50) * scale,
    p95Physical: percentile(values, 0.95) * scale,
    maxPhysical: (values.length ? Math.max(...values) : 0) * scale,
  };
}

function summarizeHeadMotion(samples) {
  if (samples.length < 2) return null;
  const medianAxis = (field) => percentile(
    samples.map((sample) => Number(sample[field] || 0)),
    0.5,
  );
  const gyroBias = {
    x: medianAxis("gyroXDPS"),
    y: medianAxis("gyroYDPS"),
    z: medianAxis("gyroZDPS"),
  };
  const integrated = { x: 0, y: 0, z: 0 };
  const ranges = {
    x: { min: 0, max: 0 },
    y: { min: 0, max: 0 },
    z: { min: 0, max: 0 },
  };
  let rotationPathDegrees = 0;
  for (let index = 1; index < samples.length; index += 1) {
    const sample = samples[index];
    const previous = samples[index - 1];
    const dt = Math.min(0.05, Math.max(0, (Number(sample.time) - Number(previous.time)) / 1000));
    const corrected = {
      x: Number(sample.gyroXDPS || 0) - gyroBias.x,
      y: Number(sample.gyroYDPS || 0) - gyroBias.y,
      z: Number(sample.gyroZDPS || 0) - gyroBias.z,
    };
    integrated.x += corrected.x * dt;
    integrated.y += corrected.y * dt;
    integrated.z += corrected.z * dt;
    for (const axis of ["x", "y", "z"]) {
      ranges[axis].min = Math.min(ranges[axis].min, integrated[axis]);
      ranges[axis].max = Math.max(ranges[axis].max, integrated[axis]);
    }
    rotationPathDegrees += Math.hypot(corrected.x, corrected.y, corrected.z) * dt;
  }
  const excursions = {
    x: ranges.x.max - ranges.x.min,
    y: ranges.y.max - ranges.y.min,
    z: ranges.z.max - ranges.z.min,
  };
  const dominantAxis = Object.entries(excursions)
    .sort((left, right) => right[1] - left[1])[0]?.[0] || "x";

  const averageVector = (items) => {
    const divisor = Math.max(1, items.length);
    return {
      x: items.reduce((sum, sample) => sum + Number(sample.accelXG || 0), 0) / divisor,
      y: items.reduce((sum, sample) => sum + Number(sample.accelYG || 0), 0) / divisor,
      z: items.reduce((sum, sample) => sum + Number(sample.accelZG || 0), 0) / divisor,
    };
  };
  const angleBetween = (left, right) => {
    const leftMagnitude = Math.hypot(left.x, left.y, left.z);
    const rightMagnitude = Math.hypot(right.x, right.y, right.z);
    if (!leftMagnitude || !rightMagnitude) return 0;
    const cosine = Math.min(1, Math.max(-1,
      (left.x * right.x + left.y * right.y + left.z * right.z)
      / (leftMagnitude * rightMagnitude),
    ));
    return Math.acos(cosine) * 180 / Math.PI;
  };
  const initialTime = Number(samples[0].time);
  const initialGravity = averageVector(
    samples.filter((sample) => Number(sample.time) <= initialTime + 400),
  );
  const gravityAngles = [];
  for (let index = 0; index < samples.length; index += 10) {
    gravityAngles.push(angleBetween(initialGravity, averageVector(samples.slice(index, index + 10))));
  }
  const finalTime = Number(samples[samples.length - 1].time);
  const tailSamples = samples.filter((sample) => Number(sample.time) >= finalTime - 500);

  return {
    rotationExcursionDegrees: Math.hypot(excursions.x, excursions.y, excursions.z),
    rotationPathDegrees,
    dominantAxis: dominantAxis.toUpperCase(),
    axisExcursionDegrees: excursions,
    maximumGravityTiltDegrees: gravityAngles.length ? Math.max(...gravityAngles) : 0,
    endingGyroscopeP95DPS: percentile(
      tailSamples.map((sample) => Number(sample.gyroscopeMagnitudeDPS || 0)),
      0.95,
    ),
  };
}

async function persistActionSamples() {
  await writeFile(actionSamplesPath, `${JSON.stringify(liveBridge.actionSamples, null, 2)}\n`, "utf8");
}

function finalizeActionCapture(reason = "completed") {
  const capture = liveBridge.activeActionCapture;
  if (!capture) return null;
  clearTimeout(liveBridge.actionCaptureTimer);
  liveBridge.actionCaptureTimer = null;
  liveBridge.activeActionCapture = null;

  const samples = liveBridge.ringSamples.filter((sample) =>
    Number(sample.time) >= capture.startsAtMilliseconds
    && Number(sample.time) <= capture.endsAtMilliseconds
  );
  const configuration = liveBridge.snapshot?.ring?.sensorConfiguration || {};
  const sampleRateHz = Number(configuration.sampleRateHz || capture.sampleRateHz || 100);
  const accelerationScale = Number(configuration.accelRangeG || capture.accelRangeG || 16) / 32768;
  const gyroscopeScale = Number(configuration.gyroRangeDPS || capture.gyroRangeDPS || 2000) / 32768;
  const expectedSampleCount = Math.max(1, Math.round(capture.durationSeconds * sampleRateHz));
  const accelerationThresholdRaw = Number(samples[0]?.accelerationDeltaThresholdRaw || capture.accelerationThresholdRaw || 0);
  const gyroscopeThresholdRaw = Number(samples[0]?.gyroscopeMagnitudeThresholdRaw || capture.gyroscopeThresholdRaw || 0);
  const triggerSampleCount = samples.filter((sample) =>
    Number(sample.accelerationDeltaRaw) >= accelerationThresholdRaw
    || Number(sample.gyroscopeMagnitudeRaw) >= gyroscopeThresholdRaw
  ).length;
  const coveragePercent = Math.min(100, samples.length / expectedSampleCount * 100);
  const result = {
    id: capture.id,
    datasetVersion: ACTION_SAMPLE_DATASET_VERSION,
    mountPosition: capture.mountPosition,
    mountProfile: capture.mountProfile,
    label: capture.label,
    createdAt: capture.createdAt,
    startsAt: capture.startsAt,
    endsAt: new Date(capture.endsAtMilliseconds).toISOString(),
    durationSeconds: capture.durationSeconds,
    status: reason === "completed" && coveragePercent >= 70 ? "完整" : "采样不完整",
    sampleCount: samples.length,
    expectedSampleCount,
    coveragePercent,
    sampleRateHz,
    thresholds: {
      accelerationDeltaRaw: accelerationThresholdRaw,
      gyroscopeMagnitudeRaw: gyroscopeThresholdRaw,
    },
    accelerationDelta: summarizeActionValues(samples.map((sample) => Number(sample.accelerationDeltaRaw || 0)), accelerationScale),
    gyroscopeMagnitude: summarizeActionValues(samples.map((sample) => Number(sample.gyroscopeMagnitudeRaw || 0)), gyroscopeScale),
    headMotion: capture.mountPosition === ACTION_MOUNT_GLASSES
      ? summarizeHeadMotion(samples)
      : null,
    triggerSampleCount,
    crossedCurrentThreshold: triggerSampleCount > 0,
  };
  liveBridge.actionSamples = [result, ...liveBridge.actionSamples].slice(0, 120);
  persistActionSamples().catch((error) => {
    console.error(`保存动作采样失败：${error.message}`);
  });
  return result;
}

function startActionCapture(
  label,
  durationSeconds = 6,
  countdownSeconds = 3,
  mountPosition = ACTION_MOUNT_GLASSES,
) {
  if (liveBridge.activeActionCapture) {
    throw new Error("已有动作正在采样，请等待本次结束");
  }
  const ring = liveBridge.snapshot?.ring;
  if (!liveBridge.connected || !ring?.sensorReporting) {
    throw new Error("戒指传感器未连接或未上报，不能开始动作采样");
  }
  const safeDuration = Math.min(15, Math.max(3, Number(durationSeconds) || 6));
  const safeCountdown = Math.min(5, Math.max(0, Number(countdownSeconds) || 0));
  const now = Date.now();
  const startsAtMilliseconds = now + safeCountdown * 1000;
  const endsAtMilliseconds = startsAtMilliseconds + safeDuration * 1000;
  const configuration = ring.sensorConfiguration || {};
  const normalizedMountPosition = mountPosition === ACTION_MOUNT_FINGER
    ? ACTION_MOUNT_FINGER
    : ACTION_MOUNT_GLASSES;
  liveBridge.activeActionCapture = {
    id: `action-${now}-${Math.random().toString(16).slice(2, 8)}`,
    datasetVersion: ACTION_SAMPLE_DATASET_VERSION,
    mountPosition: normalizedMountPosition,
    mountProfile: normalizedMountPosition === ACTION_MOUNT_GLASSES
      ? "glasses-frame-v1-fixed-orientation"
      : "finger-worn-v1",
    label: String(label || "未命名动作").slice(0, 40),
    createdAt: new Date(now).toISOString(),
    startsAt: new Date(startsAtMilliseconds).toISOString(),
    startsAtMilliseconds,
    endsAt: new Date(endsAtMilliseconds).toISOString(),
    endsAtMilliseconds,
    durationSeconds: safeDuration,
    countdownSeconds: safeCountdown,
    sampleRateHz: Number(configuration.sampleRateHz || 100),
    accelRangeG: Number(configuration.accelRangeG || 16),
    gyroRangeDPS: Number(configuration.gyroRangeDPS || 2000),
    accelerationThresholdRaw: Number(ring.accelerationDeltaThresholdRaw || 0),
    gyroscopeThresholdRaw: Number(ring.gyroscopeMagnitudeThresholdRaw || 0),
  };
  liveBridge.actionCaptureTimer = setTimeout(
    () => finalizeActionCapture("completed"),
    safeCountdown * 1000 + safeDuration * 1000 + 150,
  );
  return liveBridge.activeActionCapture;
}

function handleLiveEnvelope(envelope) {
  liveBridge.lastMessageAt = new Date().toISOString();
  if (envelope?.type === "snapshot") {
    liveBridge.snapshot = envelope.payload;
    return;
  }
  if (envelope?.type === "ringBatch") {
    appendLiveRingBatch(envelope.payload);
    return;
  }
  if (envelope?.type === "media" && envelope.payload?.id) {
    liveBridge.media = [
      envelope.payload,
      ...liveBridge.media.filter((item) => item.id !== envelope.payload.id),
    ].slice(0, 16);
  }
}

function consumeLiveLines(socket, chunk) {
  socket.rmeBuffer = Buffer.concat([socket.rmeBuffer || Buffer.alloc(0), chunk]);
  while (true) {
    const newline = socket.rmeBuffer.indexOf(0x0a);
    if (newline < 0) break;
    const line = socket.rmeBuffer.subarray(0, newline);
    socket.rmeBuffer = socket.rmeBuffer.subarray(newline + 1);
    if (!line.length) continue;
    try {
      handleLiveEnvelope(JSON.parse(line.toString("utf8")));
    } catch (error) {
      console.error(`忽略无法解析的手机调试消息：${error.message}`);
    }
  }
}

function startLiveBridge() {
  if (!liveEnabled) return;
  liveBridge.server = createNetServer((socket) => {
    if (liveBridge.socket && liveBridge.socket !== socket) liveBridge.socket.destroy();
    liveBridge.socket = socket;
    liveBridge.connected = true;
    liveBridge.connectedAt = new Date().toISOString();
    liveBridge.remoteAddress = socket.remoteAddress || null;
    socket.setKeepAlive(true, 5_000);
    socket.on("data", (chunk) => consumeLiveLines(socket, chunk));
    const disconnected = () => {
      if (liveBridge.socket !== socket) return;
      liveBridge.socket = null;
      liveBridge.connected = false;
    };
    socket.on("close", disconnected);
    socket.on("error", (error) => {
      console.error(`手机调试桥连接错误：${error.message}`);
      disconnected();
    });
  });
  liveBridge.server.listen(DEFAULT_BRIDGE_PORT, "0.0.0.0", () => {
    console.log(`Phone bridge: _rme-debug._tcp:${DEFAULT_BRIDGE_PORT}`);
  });
  liveBridge.bonjourProcess = spawn(
    "/usr/bin/dns-sd",
    ["-R", "Reality Memory Debug Console", "_rme-debug._tcp", "local", String(DEFAULT_BRIDGE_PORT)],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
  liveBridge.bonjourProcess.stderr.on("data", (data) => {
    const message = data.toString("utf8").trim();
    if (message) console.error(`Bonjour: ${message}`);
  });
}

function sendLiveCommand(command) {
  if (!liveBridge.socket || !liveBridge.connected) {
    throw new Error("手机尚未连接电脑调试台");
  }
  liveBridge.socket.write(`${JSON.stringify(command)}\n`);
}

function findLiveMedia(id) {
  return liveBridge.media.find((item) => item.id === id);
}

function sendLiveMedia(res, id, audioAsWav = false) {
  const item = findLiveMedia(id);
  if (!item) throw new Error("实时媒体已过期或不存在");
  const data = Buffer.from(item.base64Data || "", "base64");
  if (audioAsWav || String(item.kind).toUpperCase() === "AUDIO") {
    const rate = Number(String(item.mimeType || "").match(/rate=(\d+)/)?.[1]) || DEFAULT_SAMPLE_RATE;
    const channels = Number(String(item.mimeType || "").match(/channels=(\d+)/)?.[1]) || 1;
    const header = wavHeader(data.length, rate, channels);
    res.writeHead(200, {
      "content-type": "audio/wav",
      "content-length": header.length + data.length,
      "cache-control": "no-store",
    });
    res.end(Buffer.concat([header, data]));
    return;
  }
  const mime = detectMimeBuffer(data);
  res.writeHead(200, {
    "content-type": mime === "application/octet-stream" ? item.mimeType : mime,
    "content-length": data.length,
    "cache-control": "no-store",
  });
  res.end(data);
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

function percentile(values, fraction) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.round((sorted.length - 1) * fraction)));
  return sorted[index];
}

function pickObservationType(observation) {
  const mediaType = observation.mediaType || observation.type || observation.modality || "";
  const localRef = observation.localRef || observation.localPath || observation.localMediaReference || "";
  if (observation.classification || /^RING_/i.test(mediaType)) return "ring";
  if (/audio/i.test(mediaType) || /\.pcm$/i.test(localRef)) return "audio";
  if (/image|photo/i.test(mediaType) || /\.(jpe?g|png|webp|heic)$/i.test(localRef)) return "image";
  return "event";
}

function normalizeObservation(session, observation, index) {
  const startedAt = observation.startedAt || observation.windowStartedAt || observation.scheduledAt || observation.capturedAt || observation.requestedAt || observation.occurredAt || observation.createdAt || null;
  const endedAt = observation.endedAt || observation.windowEndedAt || observation.completedAt || null;
  const completedAt = observation.completedAt || observation.detectedAt || observation.occurredAt || endedAt || startedAt;
  const type = pickObservationType(observation);
  return {
    index,
    id: observation.id || observation.observationId || `observation-${index}`,
    type,
    status: observation.analysisState || observation.status || observation.outcome || observation.classification || "UNKNOWN",
    trigger: observation.trigger || observation.captureTrigger || observation.reason || null,
    triggerDecisionId: observation.triggerDecisionID || observation.triggerDecisionId || null,
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
    ...(Array.isArray(session.ringMotionAssessments) ? session.ringMotionAssessments : []),
    ...(Array.isArray(session.ringHardwareEvents) ? session.ringHardwareEvents : []),
  ];
  return direct
    .map((observation, index) => normalizeObservation(session, observation, index))
    .sort((a, b) => (a.startOffsetSec ?? a.endOffsetSec ?? 0) - (b.startOffsetSec ?? b.endOffsetSec ?? 0));
}

async function readRingData(sessionId, session = null) {
  const currentSession = session || await readSession(sessionId);
  const accelRangeG = Number(currentSession.ringSensor?.accelRangeG || 0);
  const gyroRangeDPS = Number(currentSession.ringSensor?.gyroRangeDPS || 0);
  const accelScale = accelRangeG > 0 ? accelRangeG / 32768 : null;
  const gyroScale = gyroRangeDPS > 0 ? gyroRangeDPS / 32768 : null;
  const relativeRef = currentSession.ringDataReference;
  if (!relativeRef) {
    return {
      available: false,
      reference: null,
      totalBatches: currentSession.ringBatchCount || 0,
      totalSamples: currentSession.ringSampleCount || 0,
      displaySamples: [],
    };
  }

  const sessionDir = safeJoin(path.join(captureRoot, "sessions"), sessionId);
  const filePath = safeJoin(sessionDir, relativeRef);
  if (!await exists(filePath)) {
    return {
      available: false,
      reference: relativeRef,
      error: "会话记录了戒指文件，但拉取目录中找不到该文件",
      totalBatches: currentSession.ringBatchCount || 0,
      totalSamples: currentSession.ringSampleCount || 0,
      displaySamples: [],
    };
  }

  const lines = (await readFile(filePath, "utf8")).split(/\r?\n/).filter(Boolean);
  const batches = [];
  const samples = [];
  let previous = null;
  for (const [lineIndex, line] of lines.entries()) {
    let batch;
    try {
      batch = JSON.parse(line);
    } catch (error) {
      if (lineIndex === lines.length - 1) {
        continue;
      }
      throw error;
    }
    batches.push(batch);
    const batchSamples = Array.isArray(batch.samples) ? batch.samples : [];
    const lastDeviceTimestamp = batchSamples.at(-1)?.timestampMilliseconds;
    const receivedMilliseconds = new Date(batch.receivedAt).getTime();
    batchSamples.forEach((sample, index) => {
      const deviceTimestamp = Number(sample.timestampMilliseconds || 0);
      const estimatedMilliseconds = Number.isFinite(receivedMilliseconds) && lastDeviceTimestamp !== undefined
        ? receivedMilliseconds - Math.max(0, Number(lastDeviceTimestamp) - deviceTimestamp)
        : receivedMilliseconds;
      const accelMagnitude = Math.hypot(Number(sample.accelX || 0), Number(sample.accelY || 0), Number(sample.accelZ || 0));
      const gyroMagnitude = Math.hypot(Number(sample.gyroX || 0), Number(sample.gyroY || 0), Number(sample.gyroZ || 0));
      const accelDelta = previous
        ? Math.hypot(
            Number(sample.accelX || 0) - Number(previous.accelX || 0),
            Number(sample.accelY || 0) - Number(previous.accelY || 0),
            Number(sample.accelZ || 0) - Number(previous.accelZ || 0),
          )
        : 0;
      const normalized = {
        sequence: Number(batch.sequenceStart || 0) + index,
        deviceTimestampMilliseconds: deviceTimestamp,
        receivedAt: batch.receivedAt,
        hostEstimatedAt: Number.isFinite(estimatedMilliseconds) ? new Date(estimatedMilliseconds).toISOString() : batch.receivedAt,
        offsetSeconds: secondsBetween(currentSession.startedAt, Number.isFinite(estimatedMilliseconds) ? new Date(estimatedMilliseconds).toISOString() : batch.receivedAt),
        accelX: sample.accelX,
        accelY: sample.accelY,
        accelZ: sample.accelZ,
        gyroX: sample.gyroX,
        gyroY: sample.gyroY,
        gyroZ: sample.gyroZ,
        accelMagnitude,
        accelDelta,
        gyroMagnitude,
        accelXG: accelScale === null ? null : Number(sample.accelX || 0) * accelScale,
        accelYG: accelScale === null ? null : Number(sample.accelY || 0) * accelScale,
        accelZG: accelScale === null ? null : Number(sample.accelZ || 0) * accelScale,
        accelMagnitudeG: accelScale === null ? null : accelMagnitude * accelScale,
        accelDeltaG: accelScale === null ? null : accelDelta * accelScale,
        gyroXDPS: gyroScale === null ? null : Number(sample.gyroX || 0) * gyroScale,
        gyroYDPS: gyroScale === null ? null : Number(sample.gyroY || 0) * gyroScale,
        gyroZDPS: gyroScale === null ? null : Number(sample.gyroZ || 0) * gyroScale,
        gyroMagnitudeDPS: gyroScale === null ? null : gyroMagnitude * gyroScale,
      };
      samples.push(normalized);
      previous = sample;
    });
  }

  const maxDisplaySamples = 5_000;
  const stride = Math.max(1, Math.ceil(samples.length / maxDisplaySamples));
  const accelerationChanges = samples.map((sample) => Number(sample.accelDeltaG ?? sample.accelDelta ?? 0));
  const rotationSpeeds = samples.map((sample) => Number(sample.gyroMagnitudeDPS ?? sample.gyroMagnitude ?? 0));
  return {
    available: true,
    reference: relativeRef,
    totalBatches: batches.length,
    totalSamples: samples.length,
    displayStride: stride,
    physicalUnitsAvailable: accelScale !== null && gyroScale !== null,
    statistics: {
      accelerationChange: {
        p50: percentile(accelerationChanges, 0.5),
        p90: percentile(accelerationChanges, 0.9),
        max: Math.max(0, ...accelerationChanges),
      },
      rotationSpeed: {
        p50: percentile(rotationSpeeds, 0.5),
        p90: percentile(rotationSpeeds, 0.9),
        max: Math.max(0, ...rotationSpeeds),
      },
    },
    displaySamples: samples.filter((_, index) => index % stride === 0),
  };
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
        ringSampleCount: session.ringSampleCount || 0,
        ringMotionCount: Array.isArray(session.ringMotionAssessments) ? session.ringMotionAssessments.length : 0,
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
  return detectMimeBuffer(buffer);
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

async function sendRingRaw(res, sessionId) {
  const session = await readSession(sessionId);
  if (!session.ringDataReference) throw new Error("本次会话没有戒指原始数据文件");
  const sessionDir = safeJoin(path.join(captureRoot, "sessions"), sessionId);
  const filePath = safeJoin(sessionDir, session.ringDataReference);
  const fileStat = await stat(filePath);
  res.writeHead(200, {
    "content-type": "application/x-ndjson; charset=utf-8",
    "content-length": fileStat.size,
    "content-disposition": `attachment; filename="${sessionId}-ring-imu.ndjson"`,
    "cache-control": "no-store",
  });
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
      --ring: #8a3f67;
      --gyro: #287a91;
      --axis-x: #c0392b;
      --axis-y: #17864b;
      --axis-z: #2868b2;
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
    button:disabled { cursor: not-allowed; opacity: .45; }
    .hidden { display: none !important; }
    .header-actions, .view-tabs, .control-row {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
    }
    .view-tabs {
      border: 1px solid var(--line);
      border-radius: 7px;
      overflow: hidden;
      gap: 0;
    }
    .view-tabs button {
      border: 0;
      border-right: 1px solid var(--line);
      border-radius: 0;
    }
    .view-tabs button:last-child { border-right: 0; }
    .view-tabs button.selected { background: var(--ink); color: #fff; }
    .live-view {
      max-width: 1540px;
      margin: 0 auto;
      padding: 18px 22px 32px;
    }
    .live-status {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      min-height: 52px;
      border-bottom: 1px solid var(--line);
      margin-bottom: 16px;
      padding-bottom: 14px;
    }
    .status-title {
      display: flex;
      align-items: center;
      gap: 9px;
      font-weight: 700;
    }
    .status-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: #8b949b;
      box-shadow: 0 0 0 4px rgba(139,148,155,.14);
      flex: 0 0 auto;
    }
    .status-dot.connected {
      background: var(--ok);
      box-shadow: 0 0 0 4px rgba(29,127,67,.14);
    }
    .live-grid {
      display: grid;
      grid-template-columns: minmax(340px, .9fr) minmax(420px, 1.1fr);
      gap: 12px;
      margin-bottom: 12px;
    }
    .debug-panel {
      border: 1px solid var(--line);
      background: var(--panel);
      border-radius: 8px;
      padding: 14px;
      min-width: 0;
    }
    .panel-heading {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .panel-heading h2 {
      font-size: 14px;
      line-height: 1.35;
      margin: 0;
    }
    .kv {
      display: grid;
      grid-template-columns: minmax(126px, .35fr) 1fr;
      border-top: 1px solid #edf0f2;
      min-height: 34px;
      align-items: center;
      font-size: 12px;
    }
    .kv:first-child { border-top: 0; }
    .kv dt { color: var(--muted); }
    .kv dd {
      margin: 0;
      overflow-wrap: anywhere;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .device-candidates {
      display: grid;
      gap: 7px;
      margin-top: 10px;
    }
    .candidate-row {
      display: grid;
      grid-template-columns: 1fr auto auto;
      align-items: center;
      gap: 8px;
      border-top: 1px solid #edf0f2;
      padding-top: 8px;
      font-size: 12px;
    }
    .action-presets {
      display: grid;
      grid-template-columns: repeat(3, minmax(150px, 1fr));
      gap: 8px;
    }
    .action-presets button {
      text-align: left;
      min-height: 48px;
      line-height: 1.25;
    }
    .action-presets button span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      margin-top: 3px;
    }
    .action-progress {
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 10px;
      margin-top: 10px;
      background: #f8fafb;
    }
    .progress-track {
      height: 7px;
      border-radius: 4px;
      background: #e6eaed;
      overflow: hidden;
      margin-top: 7px;
    }
    .progress-fill {
      height: 100%;
      background: var(--ring);
      transition: width .2s linear;
    }
    .sample-table-wrap {
      overflow-x: auto;
      margin-top: 12px;
    }
    .sample-table {
      width: 100%;
      min-width: 850px;
      border-collapse: collapse;
      font-size: 12px;
    }
    .sample-table th, .sample-table td {
      border-top: 1px solid #edf0f2;
      text-align: left;
      padding: 8px;
      vertical-align: top;
    }
    .sample-table th {
      color: var(--muted);
      font-weight: 600;
    }
    .sensor-headline {
      display: grid;
      grid-template-columns: repeat(2, minmax(180px, 1fr));
      gap: 18px;
      margin: 12px 0 10px;
    }
    .sensor-value {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: baseline;
      margin-bottom: 7px;
    }
    .sensor-value strong { font-size: 22px; }
    .sensor-track {
      position: relative;
      height: 15px;
      border: 1px solid var(--line);
      background: linear-gradient(to right, #eaf4ed 0 30%, #fbf1df 30% 66.67%, #f9e7e5 66.67% 100%);
      border-radius: 5px;
      overflow: hidden;
    }
    .sensor-fill {
      height: 100%;
      background: rgba(23,32,38,.68);
      transition: width .1s linear;
    }
    .sensor-trigger {
      position: absolute;
      top: 0;
      bottom: 0;
      left: 66.67%;
      width: 2px;
      background: var(--bad);
    }
    .range-labels {
      display: grid;
      grid-template-columns: 45fr 55fr 50fr;
      gap: 5px;
      color: var(--muted);
      font-size: 10px;
      margin-top: 5px;
    }
    .range-labels span:nth-child(2) { text-align: center; }
    .range-labels span:last-child { text-align: right; }
    .live-chart-wrap {
      width: 100%;
      height: 300px;
      border-top: 1px solid var(--line);
      margin-top: 12px;
      padding-top: 10px;
    }
    #liveRingChart { width: 100%; height: 100%; display: block; }
    .live-media {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      gap: 10px;
    }
    .live-media article { min-width: 0; }
    .live-media .preview { aspect-ratio: 4 / 3; }
    .log-list {
      display: grid;
      gap: 0;
      max-height: 300px;
      overflow: auto;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 11px;
    }
    .log-row {
      display: grid;
      grid-template-columns: 76px 1fr;
      gap: 10px;
      border-top: 1px solid #edf0f2;
      padding: 7px 0;
    }
    .log-row:first-child { border-top: 0; }
    .decision {
      border-left: 4px solid var(--ring);
      background: #f8f4f6;
      padding: 8px 10px;
      margin-top: 10px;
      font-size: 12px;
    }
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
    .marker.ring { background: var(--ring); }
    .ring-panel {
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
      padding: 16px 0;
      margin: 18px 0;
    }
    .ring-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 12px;
    }
    .ring-chart-wrap {
      width: 100%;
      height: 250px;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 8px;
      padding: 8px;
    }
    .chart-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 10px;
      margin: 12px 0 8px;
    }
    .chart-modes {
      display: inline-flex;
      border: 1px solid var(--line);
      border-radius: 7px;
      overflow: hidden;
      background: #fff;
    }
    .chart-modes button {
      border: 0;
      border-right: 1px solid var(--line);
      border-radius: 0;
    }
    .chart-modes button:last-child { border-right: 0; }
    .chart-modes button.selected { background: #172026; color: #fff; }
    #ringChart { width: 100%; height: 100%; display: block; }
    .legend { display: flex; flex-wrap: wrap; gap: 12px; margin: 8px 0 12px; }
    .legend span::before {
      content: "";
      display: inline-block;
      width: 16px;
      height: 3px;
      margin-right: 6px;
      vertical-align: middle;
      background: var(--ring);
    }
    .legend span.gyro::before { background: var(--gyro); }
    .legend span.axis-x::before { background: var(--axis-x); }
    .legend span.axis-y::before { background: var(--axis-y); }
    .legend span.axis-z::before { background: var(--axis-z); }
    .legend span.trigger::before { width: 3px; height: 12px; background: var(--ring); }
    .assessment-list {
      display: grid;
      gap: 8px;
      margin-top: 12px;
    }
    .assessment {
      border-left: 4px solid var(--ring);
      background: #fff;
      padding: 10px 12px;
    }
    .download-link {
      color: #245f89;
      font-size: 12px;
      white-space: nowrap;
    }
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
      .live-grid, .sensor-headline, .action-presets { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .summary { grid-template-columns: repeat(2, 1fr); }
      header { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Reality Memory 调试台</h1>
      <div class="root" id="root"></div>
    </div>
    <div class="header-actions">
      <div class="view-tabs">
        <button type="button" id="showLive" class="selected">实时联调</button>
        <button type="button" id="showHistory">历史 Session</button>
      </div>
      <button id="refresh">刷新</button>
    </div>
  </header>
  <section class="live-view" id="liveView">
    <div class="live-status">
      <div>
        <div class="status-title"><span class="status-dot" id="liveStatusDot"></span><span id="liveStatusTitle">等待手机 App</span></div>
        <div class="small" id="liveStatusDetail">电脑调试桥已启动，正在等待同一局域网内的 Reality Memory 手机 App。</div>
      </div>
      <div class="meta" id="liveCounters"></div>
    </div>

    <div class="live-grid">
      <section class="debug-panel">
        <div class="panel-heading">
          <div><h2>戒指身份与蓝牙链路</h2><div class="small">手机作为蓝牙中介；UUID 是 iOS 可稳定读取的设备标识。</div></div>
          <button type="button" data-command="ring.scan">扫描</button>
        </div>
        <dl id="ringIdentity"><div class="small">等待手机状态...</div></dl>
        <div class="device-candidates" id="ringCandidates"></div>
      </section>

      <section class="debug-panel">
        <div class="panel-heading">
          <div><h2>眼镜与采集控制</h2><div class="small">CXR-L 过渡链路仍由手机 App 连接并调用眼镜能力。</div></div>
          <span class="pill" id="sessionState">未连接</span>
        </div>
        <dl id="glassesState"><div class="small">等待手机状态...</div></dl>
        <div class="control-row" id="glassesControls">
          <button type="button" data-command="glasses.customView.toggle">切换眼镜采集界面</button>
          <button type="button" data-command="glasses.photo">拍一张</button>
          <button type="button" data-command="audio.toggle">开始/停止音频测试</button>
          <button type="button" data-command="session.start">开始 Session</button>
          <button type="button" data-command="session.pause">暂停</button>
          <button type="button" data-command="session.resume">继续</button>
          <button type="button" data-command="session.end">结束</button>
        </div>
      </section>
    </div>

    <section class="debug-panel">
      <div class="panel-heading">
        <div><h2>眼镜头部运动与戒指六轴</h2><div class="small">戒指固定在眼镜时，累计短时转角和重力方向变化；头部回稳约 0.5 秒后才触发。持续行走期间等待稳定，不在转动峰值中拍照。</div></div>
        <div class="control-row">
          <span class="small">灵敏度</span>
          <div class="chart-modes" id="sensitivityControls">
            <button type="button" data-sensitivity="high">高</button>
            <button type="button" data-sensitivity="medium">中</button>
            <button type="button" data-sensitivity="low">低</button>
          </div>
          <button type="button" id="sensorAutoToggle" data-command="ring.sensor.auto" data-bool-value="true">连接后自动开传感器</button>
        </div>
      </div>
      <div class="sensor-headline" id="sensorHeadline"></div>
      <div class="decision" id="ringDecision">尚未收到动作判断。</div>
      <div class="chart-toolbar">
        <div class="chart-modes" id="liveChartModes">
          <button type="button" data-live-chart-mode="intensity" class="selected">动作强度</button>
          <button type="button" data-live-chart-mode="acceleration">三轴加速度</button>
          <button type="button" data-live-chart-mode="rotation">三轴角速度</button>
        </div>
        <span class="small" id="sensorConfiguration">传感器尚未开启</span>
      </div>
      <div class="legend" id="liveRingLegend"></div>
      <div class="live-chart-wrap"><canvas id="liveRingChart"></canvas></div>
    </section>

    <section class="debug-panel" style="margin-top:12px">
      <div class="panel-heading">
        <div><h2>常见动作标定</h2><div class="small">安装位置不同会形成独立数据集。选择动作后先倒计时 3 秒，再记录固定时间窗，每类建议重复 3 次。</div></div>
        <div class="control-row">
          <div class="chart-modes" id="actionMountModes">
            <button type="button" data-action-mount="GLASSES_MOUNTED" class="selected">固定在眼镜</button>
            <button type="button" data-action-mount="FINGER_WORN">手指佩戴（旧）</button>
          </div>
          <button type="button" id="clearActionSamples">清空当前组</button>
        </div>
      </div>
      <div class="decision" id="actionMountNotice">当前数据组：固定在眼镜。请保持戒指相对镜框的位置和朝向不变。</div>
      <div class="action-presets" id="glassesActionPresets">
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="头部静止基线" data-action-duration="5">头部静止基线<span>自然坐着看前方，保持 5 秒</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="抬头看上方物品" data-action-duration="6">抬头看物品<span>从正前方自然抬头、注视、回正</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="向左转头并回正" data-action-duration="6">向左转头<span>自然看向左侧物品，再回到正前方</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="向右转头并回正" data-action-duration="6">向右转头<span>自然看向右侧物品，再回到正前方</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="低头看近处物品" data-action-duration="6">低头看物品<span>从正前方低头观察桌面，再回正</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="拿起并放下水杯（头部）" data-action-duration="7">拿起并放下水杯<span>眼睛自然跟随水杯，不刻意夸大动作</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="坐姿起立并稳定（头部）" data-action-duration="7">坐姿起立<span>自然站起并面向前方稳定</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="正常行走（头部）" data-action-duration="8">正常行走<span>自然向前走 6–8 步</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="抬头注视并保持" data-action-duration="7">抬头后保持<span>从正前方抬头看目标，保持到采样结束</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="向左注视并保持" data-action-duration="7">左转后保持<span>转向左侧目标，保持到采样结束</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="向右注视并保持" data-action-duration="7">右转后保持<span>转向右侧目标，保持到采样结束</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="低头注视并保持" data-action-duration="7">低头后保持<span>低头看近处目标，保持到采样结束</span></button>
        <button type="button" data-action-placement="GLASSES_MOUNTED" data-action-label="只动眼睛头部不动" data-action-duration="6">只动眼睛<span>头部保持正前方，只用眼睛左右观察</span></button>
      </div>
      <div class="action-presets hidden" id="fingerActionPresets">
        <button type="button" data-action-placement="FINGER_WORN" data-action-label="静止基线" data-action-duration="5">静止基线<span>坐着不动，保持 5 秒</span></button>
        <button type="button" data-action-placement="FINGER_WORN" data-action-label="拿起并放下水杯" data-action-duration="6">拿起并放下水杯<span>自然完成一次拿起、靠近、放下</span></button>
        <button type="button" data-action-placement="FINGER_WORN" data-action-label="坐下到起身" data-action-duration="6">坐下到起身<span>从坐姿自然站起并稳定</span></button>
        <button type="button" data-action-placement="FINGER_WORN" data-action-label="正常行走" data-action-duration="8">正常行走<span>连续行走约 6–8 步</span></button>
        <button type="button" data-action-placement="FINGER_WORN" data-action-label="抬手触碰物品" data-action-duration="6">抬手触碰物品<span>自然抬手触碰桌面物品</span></button>
        <button type="button" data-action-placement="FINGER_WORN" data-action-label="快速挥手" data-action-duration="5">快速挥手<span>明显快速移动，作为高强度对照</span></button>
      </div>
      <div id="actionCaptureState" class="action-progress hidden"></div>
      <div id="actionSampleSummary" class="small" style="margin-top:10px">尚未完成动作采样。</div>
      <div class="sample-table-wrap" id="actionSampleTable"></div>
    </section>

    <div class="live-grid" style="margin-top:12px">
      <section class="debug-panel">
        <div class="panel-heading"><div><h2>实时图片、音频与短视频</h2><div class="small">手机刚收到的证据会出现在这里；历史文件请到“历史 Session”。</div></div></div>
        <div class="live-media" id="liveMedia"><div class="small">尚未收到实时媒体。当前 CXR-L 过渡链路尚未接入短视频。</div></div>
      </section>
      <section class="debug-panel">
        <div class="panel-heading"><div><h2>手机事件日志</h2><div class="small">用于确认扫描、连接、传感器开启和眼镜采集是否真正执行。</div></div></div>
        <div class="log-list" id="liveLogs"><div class="small">等待手机日志...</div></div>
      </section>
    </div>
  </section>
  <main id="historyView" class="hidden">
    <aside>
      <div class="small">Session 是一次采集窗口；这里按时间把图片、短音频和设备/审计事件放在一起，方便判断它们能否在后续解析层对齐。</div>
      <div class="session-list" id="sessions"></div>
    </aside>
    <section class="workspace" id="workspace">
      <div class="empty">选择左侧一次 Session</div>
    </section>
  </main>
  <script>
    const state = {
      sessions: [],
      current: null,
      sampleRate: 16000,
      ringData: null,
      ringChartMode: "intensity",
      currentSession: null,
      live: null,
      liveRingSamples: [],
      liveChartMode: "intensity",
      liveMediaSignature: "",
      actionSampling: { active: null, samples: [], mountPosition: "GLASSES_MOUNTED" },
      activeView: "live",
    };
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

    function kv(label, value) {
      return '<div class="kv"><dt>' + esc(label) + '</dt><dd>' + esc(value ?? "未读取") + '</dd></div>';
    }

    function formatNumber(value, digits) {
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(digits) : "-";
    }

    function liveConnected() {
      return Boolean(state.live?.connected && state.live?.snapshot);
    }

    function setView(view) {
      state.activeView = view;
      $("liveView").classList.toggle("hidden", view !== "live");
      $("historyView").classList.toggle("hidden", view !== "history");
      $("showLive").classList.toggle("selected", view === "live");
      $("showHistory").classList.toggle("selected", view === "history");
      if (view === "live") requestAnimationFrame(drawLiveRingChart);
    }

    async function sendCommand(command, extra) {
      const res = await fetch("/api/live/command", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(Object.assign({ command: command }, extra || {})),
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }

    async function postJson(path, body) {
      const res = await fetch(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    }

    function renderLiveStatus() {
      const connected = Boolean(state.live?.connected);
      const snapshot = state.live?.snapshot;
      $("liveStatusDot").classList.toggle("connected", connected);
      $("liveStatusTitle").textContent = connected
        ? "手机 App 已连接"
        : state.live?.enabled
          ? "等待手机 App"
          : "当前未以实时模式启动";
      $("liveStatusDetail").textContent = connected
        ? (snapshot?.phoneName || "iPhone") + " · " + (snapshot?.applicationState || "状态未知") +
          " · 最近数据 " + fmtTime(state.live.lastMessageAt)
        : "请让手机与 Mac 位于同一局域网，并保持 Reality Memory App 打开。";
      $("liveCounters").innerHTML =
        '<span class="pill">实时点 ' + esc(state.live?.ringSampleCount || 0) + '</span>' +
        '<span class="pill">实时媒体 ' + esc(state.live?.media?.length || 0) + '</span>';
    }

    function renderRingIdentity(ring) {
      const identity = ring?.identity || {};
      const selected = (ring?.candidates || []).find((item) => item.id === ring.selectedDeviceID);
      $("ringIdentity").innerHTML = [
        kv("蓝牙状态", ring?.bluetooth),
        kv("连接状态", ring?.connection),
        kv("戒指名称", identity.model || selected?.displayName || selected?.name),
        kv("设备型号", identity.model),
        kv("序列号", identity.serialNumber),
        kv("固件版本", identity.firmwareVersion),
        kv("电量", identity.batteryPercent === undefined ? null : identity.batteryPercent + "%" + (identity.batteryCharging ? "，充电中" : "")),
        kv("MAC 地址", ring?.macAddress || "iOS 不提供"),
        kv("iOS Peripheral UUID", ring?.selectedDeviceID),
        kv("BLE 服务 UUID", ring?.serviceUUID),
        kv("通知特征 UUID", ring?.notifyCharacteristicUUID),
        kv("写入特征 UUID", ring?.writeCharacteristicUUID),
      ].join("");
      const candidates = ring?.candidates || [];
      $("ringCandidates").innerHTML = candidates.length
        ? '<div class="small">只显示广播 Ring Sound NUS 服务或已识别过的候选：</div>' +
          candidates.map((item) =>
            '<div class="candidate-row"><div><strong>' + esc(item.displayName || item.name) +
            '</strong><div class="small">' + esc(item.id) + '</div></div>' +
            '<span class="pill">RSSI ' + esc(item.rssi) + '</span>' +
            '<button type="button" data-command="ring.connect" data-device-id="' + esc(item.id) + '"' +
            (item.id === ring.selectedDeviceID ? " disabled" : "") + '>' +
            (item.id === ring.selectedDeviceID ? "已选择" : "连接") + '</button></div>'
          ).join("")
        : '<div class="small">没有发现符合戒指协议的设备。点击“扫描”后让戒指保持有电并靠近手机。</div>';
    }

    function renderGlasses(snapshot) {
      const glasses = snapshot?.glasses || {};
      const session = snapshot?.session || {};
      $("glassesState").innerHTML = [
        kv("Rokid 授权", glasses.authentication),
        kv("眼镜连接", glasses.connection),
        kv("采集界面", glasses.customView),
        kv("佩戴状态", glasses.wearing),
        kv("设备", glasses.deviceSummary),
        kv("拍照条件", glasses.photoReady),
        kv("Session 编号", session.id),
        kv("图片 / 音频 / 快速移动", (session.imageCount || 0) + " / " + (session.audioCount || 0) + " / " + (session.rapidMovementCount || 0)),
        kv("当前采集节奏", (session.captureMode || "稳定基线") + " · " + (session.captureIntervalSeconds || 30) + " 秒"),
        kv("加速记录至", session.acceleratedUntil ? fmtTime(session.acceleratedUntil) : "未启用"),
        kv("语音活动", session.speechActive ? "检测到说话" : "无"),
        kv("音量", session.audioLevelDBFS === null || session.audioLevelDBFS === undefined ? "-" : formatNumber(session.audioLevelDBFS, 1) + " dBFS"),
      ].join("");
      $("sessionState").textContent = session.state || "未开始";
      $("glassesControls").querySelectorAll("button").forEach((button) => {
        button.disabled = !liveConnected();
      });
    }

    function sensorGauge(title, raw, thresholdRaw, physical, physicalThreshold, unit) {
      const ratio = thresholdRaw > 0 ? raw / thresholdRaw : 0;
      const width = Math.min(100, Math.max(0, ratio / 1.5 * 100));
      return '<div><div class="sensor-value"><span>' + esc(title) + '</span><strong>' +
        esc(Math.round(ratio * 100)) + '%</strong></div>' +
        '<div class="small">' + esc(formatNumber(physical, unit === "g" ? 3 : 1)) + " " + esc(unit) +
        ' · raw ' + esc(formatNumber(raw, 0)) + ' / 阈值 ' + esc(formatNumber(thresholdRaw, 0)) +
        '（' + esc(formatNumber(physicalThreshold, unit === "g" ? 3 : 1)) + " " + esc(unit) + '）</div>' +
        '<div class="sensor-track"><div class="sensor-fill" style="width:' + width + '%"></div><span class="sensor-trigger"></span></div>' +
        '<div class="range-labels"><span>安静 0–45%</span><span>明显动作 45–100%</span><span>触发 ≥100%</span></div></div>';
    }

    function renderSensors(ring) {
      const configuration = ring?.sensorConfiguration || {};
      const accelerationScale = Number(configuration.accelRangeG || 0) / 32768;
      const gyroscopeScale = Number(configuration.gyroRangeDPS || 0) / 32768;
      const accelRaw = Number(ring?.accelerationDeltaRaw || 0);
      const gyroRaw = Number(ring?.gyroscopeMagnitudeRaw || 0);
      const accelThreshold = Number(ring?.accelerationDeltaThresholdRaw || 0);
      const gyroThreshold = Number(ring?.gyroscopeMagnitudeThresholdRaw || 0);
      $("sensorHeadline").innerHTML =
        sensorGauge("加速度变化 P90", accelRaw, accelThreshold, accelRaw * accelerationScale, accelThreshold * accelerationScale, "g") +
        sensorGauge("转动速度 P90", gyroRaw, gyroThreshold, gyroRaw * gyroscopeScale, gyroThreshold * gyroscopeScale, "°/s");
      $("sensorConfiguration").textContent = configuration.sampleRateHz
        ? configuration.sampleRateHz + " Hz · ±" + configuration.accelRangeG + " g · ±" + configuration.gyroRangeDPS +
          " °/s · " + (ring.sensorReporting ? "正在上报" : "未上报") +
          " · 批次 " + (ring.batchCount || 0) + " · 样本 " + (ring.sampleCount || 0)
        : "传感器参数尚未读取";
      const contextNames = {
        CALIBRATING: "正在学习近期基线",
        RELATIVELY_STABLE: "相对稳定",
        MOTION_CHANGING: "运动状态正在变化",
        HEAD_STABLE: "头部稳定",
        HEAD_TURNING: "头部转动中",
        HEAD_SETTLING: "正在等待头部回稳",
        SUSTAINED_MOTION: "持续运动中，暂不触发",
      };
      const judgementTime = ring?.lastJudgementAt
        ? new Date(ring.lastJudgementAt).toLocaleTimeString("zh-CN", { hour12: false })
        : "";
      const historicalJudgement = ring?.lastJudgementAt
        ? "历史触发 " + judgementTime
        : "最近判断";
      const isGlassesMounted = ring?.mountPosition === "GLASSES_MOUNTED";
      const changeSummary = isGlassesMounted
        ? ' · 信息变化 ' + esc(formatNumber(ring?.relativeChangeScore, 2)) + '×' +
          '<div class="small">累计转角 ' + esc(formatNumber(ring?.rotationExcursionDegrees, 1)) +
          '° · 重力方向变化 ' + esc(formatNumber(ring?.gravityTiltDegrees, 1)) +
          '° · 当前校正转速 P90 ' + esc(formatNumber(ring?.endingGyroscopeDPS, 1)) +
          '°/s · 安装位置 固定在眼镜</div>'
        : ' · 相对基线 ' + esc(formatNumber(ring?.relativeChangeScore, 2)) + '×' +
          '<div class="small">加速度基线 ' + esc(formatNumber(ring?.accelerationBaselineRaw, 0)) +
          ' · 转动基线 ' + esc(formatNumber(ring?.gyroscopeBaselineRaw, 0)) + '</div>';
      $("ringDecision").innerHTML =
        '<strong>当前状态：</strong> ' + esc(contextNames[ring?.motionContextState] || ring?.motionContextState || "未知") +
        changeSummary +
        '<div class="small">规则 ' + esc(ring?.detectorRuleVersion || "-") + '</div>' +
        '<div style="margin-top:6px"><strong>' + esc(historicalJudgement) + '：</strong> ' +
        esc(ring?.lastJudgement || "尚未形成判断") + '</div>' +
        '<div class="small">上面是最近一次已经结束的触发记录，不代表当前仍在突变；请以“当前状态”和实时曲线为准。</div>' +
        (ring?.lastEvent ? '<div class="small">最近戒指事件：' + esc(ring.lastEvent) + '</div>' : "");
      document.querySelectorAll("[data-sensitivity]").forEach((button) => {
        button.classList.toggle("selected", button.dataset.sensitivity === ring?.sensitivity);
        button.disabled = !liveConnected();
      });
      const autoButton = $("sensorAutoToggle");
      autoButton.dataset.boolValue = String(!ring?.sensorAutoStartEnabled);
      autoButton.textContent = ring?.sensorAutoStartEnabled ? "自动开启：开" : "自动开启：关";
      autoButton.classList.toggle("active", Boolean(ring?.sensorAutoStartEnabled));
      autoButton.disabled = !liveConnected();
    }

    function renderLiveMedia(media) {
      const signature = (media || []).map((item) => item.id).join(",");
      if (signature === state.liveMediaSignature) return;
      state.liveMediaSignature = signature;
      $("liveMedia").innerHTML = media?.length
        ? media.map((item) => {
          const kind = String(item.kind || "").toUpperCase();
          const preview = kind === "IMAGE"
            ? '<div class="preview"><img src="/api/live/media?id=' + encodeURIComponent(item.id) + '" alt="实时采集图片"></div>'
            : '<div class="preview"><span class="small">' + (kind === "AUDIO" ? "短音频证据" : "短视频证据") + '</span></div>';
          const player = kind === "AUDIO"
            ? '<audio controls preload="metadata" src="/api/live/audio?id=' + encodeURIComponent(item.id) + '"></audio>'
            : "";
          return '<article>' + preview + '<div class="body"><div class="item-title"><span>' +
            esc(kind === "IMAGE" ? "图片" : kind === "AUDIO" ? "短音频" : "短视频") +
            '</span><span class="pill">' + esc(item.trigger || "未知触发") + '</span></div>' +
            '<div class="small">' + esc(fmtTime(item.occurredAt)) + ' · ' + esc(item.byteCount || 0) + ' bytes' +
            (item.durationMilliseconds ? ' · ' + esc(item.durationMilliseconds) + ' ms' : "") +
            (item.captureLatencyMilliseconds ? ' · 回调耗时 ' + esc(item.captureLatencyMilliseconds) + ' ms' : "") +
            '</div>' + player + '</div></article>';
        }).join("")
        : '<div class="small">尚未收到实时媒体。当前 CXR-L 过渡链路尚未接入短视频。</div>';
    }

    function renderLiveLogs(logs) {
      $("liveLogs").innerHTML = logs?.length
        ? logs.map((item) => '<div class="log-row"><span>' +
          esc(new Date(item.date).toLocaleTimeString("zh-CN", { hour12: false })) +
          '</span><span>' + esc(item.message) + '</span></div>').join("")
        : '<div class="small">尚未收到手机日志。</div>';
    }

    function actionMetric(metric, unit, digits) {
      if (!metric) return "-";
      return '<strong>' + esc(formatNumber(metric.p95Raw, 0)) + '</strong> / ' +
        esc(formatNumber(metric.maxRaw, 0)) +
        '<div class="small">P95 / 最大 · ' +
        esc(formatNumber(metric.p95Physical, digits)) + " / " +
        esc(formatNumber(metric.maxPhysical, digits)) + " " + esc(unit) + '</div>';
    }

    function headMotionMetric(metric) {
      if (!metric) return "";
      return '<div class="small">估计最大转角 ' +
        esc(formatNumber(metric.rotationExcursionDegrees, 1)) + '° · 主轴 ' +
        esc(metric.dominantAxis || "-") + ' · 重力方向变化 ' +
        esc(formatNumber(metric.maximumGravityTiltDegrees, 1)) + '° · 末尾 P95 ' +
        esc(formatNumber(metric.endingGyroscopeP95DPS, 1)) + '°/s</div>';
    }

    function renderActionSampling() {
      const data = state.actionSampling || { active: null, samples: [] };
      const active = data.active;
      const mountPosition = data.mountPosition || "GLASSES_MOUNTED";
      const visibleSamples = (data.samples || []).filter((item) =>
        (item.mountPosition || "FINGER_WORN") === mountPosition
      );
      $("glassesActionPresets").classList.toggle("hidden", mountPosition !== "GLASSES_MOUNTED");
      $("fingerActionPresets").classList.toggle("hidden", mountPosition !== "FINGER_WORN");
      $("actionMountNotice").textContent = mountPosition === "GLASSES_MOUNTED"
        ? "当前数据组：固定在眼镜。请保持戒指相对镜框的位置和朝向不变。"
        : "当前数据组：手指佩戴。这里保留此前采集的旧样本，不与眼镜安装位混算。";
      document.querySelectorAll("[data-action-mount]").forEach((button) => {
        button.classList.toggle("selected", button.dataset.actionMount === mountPosition);
        button.disabled = Boolean(active);
      });
      document.querySelectorAll("[data-action-label]").forEach((button) => {
        button.disabled = !liveConnected()
          || Boolean(active)
          || button.dataset.actionPlacement !== mountPosition;
      });
      $("clearActionSamples").disabled = Boolean(active) || !visibleSamples.length;
      if (active) {
        const now = Date.now();
        const starts = new Date(active.startsAt).getTime();
        const ends = new Date(active.endsAt).getTime();
        const isCountdown = now < starts;
        const remaining = Math.max(0, (isCountdown ? starts : ends) - now);
        const progress = isCountdown ? 0 : Math.min(100, Math.max(0, (now - starts) / (ends - starts) * 100));
        $("actionCaptureState").classList.remove("hidden");
        $("actionCaptureState").innerHTML =
          '<strong>' + esc(active.label) + ' · ' +
          (isCountdown ? '准备，' + Math.max(1, Math.ceil(remaining / 1000)) + ' 秒后开始' : '正在记录，剩余 ' + Math.ceil(remaining / 1000) + ' 秒') +
          '</strong><div class="progress-track"><div class="progress-fill" style="width:' + progress + '%"></div></div>';
      } else {
        $("actionCaptureState").classList.add("hidden");
        $("actionCaptureState").innerHTML = "";
      }
      const completeCount = visibleSamples.filter((item) => item.status === "完整").length;
      const crossedCount = visibleSamples.filter((item) => item.crossedCurrentThreshold).length;
      $("actionSampleSummary").textContent = visibleSamples.length
        ? "当前安装组已记录 " + visibleSamples.length + " 次，其中完整 " + completeCount + " 次；按当前阈值有 " + crossedCount + " 次动作越线。"
        : "尚未完成动作采样。";
      $("actionSampleTable").innerHTML = visibleSamples.length
        ? '<table class="sample-table"><thead><tr><th>动作</th><th>时间</th><th>完整度</th><th>加速度突变 raw</th><th>转动速度 raw</th><th>当前阈值结果</th></tr></thead><tbody>' +
          visibleSamples.map((item) =>
            '<tr><td><strong>' + esc(item.label) + '</strong><div class="small">' + esc(item.durationSeconds) + ' 秒</div>' +
            headMotionMetric(item.headMotion) + '</td>' +
            '<td>' + esc(new Date(item.createdAt).toLocaleTimeString("zh-CN", { hour12: false })) + '</td>' +
            '<td>' + esc(formatNumber(item.coveragePercent, 0)) + '%<div class="small">' + esc(item.sampleCount) + ' / ' + esc(item.expectedSampleCount) + ' 点 · ' + esc(item.status) + '</div></td>' +
            '<td>' + actionMetric(item.accelerationDelta, "g", 3) + '</td>' +
            '<td>' + actionMetric(item.gyroscopeMagnitude, "°/s", 1) + '</td>' +
            '<td><span class="pill">' + (item.crossedCurrentThreshold ? "已越线" : "未越线") + '</span><div class="small">越线采样点 ' + esc(item.triggerSampleCount || 0) + '</div></td></tr>'
          ).join("") + '</tbody></table>'
        : "";
    }

    function renderLive() {
      renderLiveStatus();
      const snapshot = state.live?.snapshot;
      renderRingIdentity(snapshot?.ring);
      renderGlasses(snapshot);
      renderSensors(snapshot?.ring);
      renderLiveMedia(state.live?.media || []);
      renderLiveLogs(snapshot?.recentLogs || []);
      renderActionSampling();
      document.querySelectorAll("[data-command]").forEach((button) => {
        if (!button.closest("#glassesControls") && button.id !== "sensorAutoToggle") {
          button.disabled = !liveConnected();
        }
      });
    }

    async function loadLive() {
      const [live, ring, actionSampling] = await Promise.all([
        api("/api/live"),
        api("/api/live/ring"),
        api("/api/live/action-samples"),
      ]);
      state.live = live;
      state.liveRingSamples = ring.samples || [];
      state.actionSampling = {
        ...actionSampling,
        mountPosition: state.actionSampling.mountPosition || "GLASSES_MOUNTED",
      };
      renderLive();
      if (state.activeView === "live") drawLiveRingChart();
    }

    function drawLiveRingChart() {
      const canvas = $("liveRingChart");
      if (!canvas || !state.liveRingSamples.length) return;
      const rect = canvas.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.round(rect.width * ratio));
      canvas.height = Math.max(1, Math.round(rect.height * ratio));
      const ctx = canvas.getContext("2d");
      ctx.scale(ratio, ratio);
      const width = rect.width;
      const height = rect.height;
      const pad = { left: 48, right: 14, top: 20, bottom: 24 };
      const plotWidth = width - pad.left - pad.right;
      const plotHeight = height - pad.top - pad.bottom;
      const cutoff = Date.now() - 30_000;
      const samples = state.liveRingSamples.filter((sample) => Number(sample.time) >= cutoff);
      if (!samples.length) return;
      const mode = state.liveChartMode;
      const seriesByMode = {
        intensity: [
          { field: "accelerationDeltaRaw", threshold: "accelerationDeltaThresholdRaw", label: "加速度突变 / 阈值", color: "#8a3f67", className: "" },
          { field: "gyroscopeMagnitudeRaw", threshold: "gyroscopeMagnitudeThresholdRaw", label: "转动速度 / 阈值", color: "#287a91", className: "gyro" },
        ],
        acceleration: [
          { field: "accelXG", label: "X 轴", color: "#c0392b", className: "axis-x" },
          { field: "accelYG", label: "Y 轴", color: "#17864b", className: "axis-y" },
          { field: "accelZG", label: "Z 轴", color: "#2868b2", className: "axis-z" },
        ],
        rotation: [
          { field: "gyroXDPS", label: "X 轴", color: "#c0392b", className: "axis-x" },
          { field: "gyroYDPS", label: "Y 轴", color: "#17864b", className: "axis-y" },
          { field: "gyroZDPS", label: "Z 轴", color: "#2868b2", className: "axis-z" },
        ],
      };
      const series = seriesByMode[mode] || seriesByMode.intensity;
      $("liveRingLegend").innerHTML = series.map((item) =>
        '<span class="' + item.className + '">' + esc(item.label) + '</span>'
      ).join("") + (mode === "intensity" ? '<span class="trigger">100% 触发线</span>' : "");
      const times = samples.map((sample) => Number(sample.time));
      const minTime = Math.min(...times);
      const maxTime = Math.max(minTime + 1, ...times);
      const values = series.flatMap((item) => samples.map((sample) =>
        mode === "intensity"
          ? Number(sample[item.field] || 0) / Math.max(1, Number(sample[item.threshold] || 0))
          : Number(sample[item.field] || 0)
      ));
      const signed = mode !== "intensity";
      const maximum = signed ? Math.max(0.0001, ...values.map(Math.abs)) : 1.5;
      ctx.clearRect(0, 0, width, height);
      ctx.strokeStyle = "#e1e6e9";
      ctx.lineWidth = 1;
      for (let index = 0; index <= 4; index += 1) {
        const y = pad.top + plotHeight * index / 4;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(width - pad.right, y);
        ctx.stroke();
      }
      if (mode === "intensity") {
        const triggerY = pad.top + (1 - 1 / 1.5) * plotHeight;
        ctx.strokeStyle = "#b42318";
        ctx.beginPath();
        ctx.moveTo(pad.left, triggerY);
        ctx.lineTo(width - pad.right, triggerY);
        ctx.stroke();
      } else {
        const zeroY = pad.top + plotHeight / 2;
        ctx.strokeStyle = "#9da8af";
        ctx.beginPath();
        ctx.moveTo(pad.left, zeroY);
        ctx.lineTo(width - pad.right, zeroY);
        ctx.stroke();
      }
      series.forEach((item) => {
        ctx.strokeStyle = item.color;
        ctx.lineWidth = 1.6;
        ctx.beginPath();
        samples.forEach((sample, index) => {
          const x = pad.left + ((Number(sample.time) - minTime) / (maxTime - minTime)) * plotWidth;
          const rawValue = mode === "intensity"
            ? Number(sample[item.field] || 0) / Math.max(1, Number(sample[item.threshold] || 0))
            : Number(sample[item.field] || 0);
          const normalized = signed
            ? 0.5 - Math.max(-1, Math.min(1, rawValue / maximum)) * 0.5
            : 1 - Math.max(0, Math.min(1, rawValue / maximum));
          const y = pad.top + normalized * plotHeight;
          if (index === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
      });
      ctx.fillStyle = "#66727c";
      ctx.font = "11px system-ui";
      ctx.fillText(mode === "intensity" ? "150%" : "+" + maximum.toFixed(mode === "acceleration" ? 2 : 0), 5, pad.top + 4);
      ctx.fillText(mode === "intensity" ? "0%" : "−" + maximum.toFixed(mode === "acceleration" ? 2 : 0), 8, pad.top + plotHeight);
      ctx.fillText("最近 30 秒", pad.left, height - 5);
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
            '<span class="pill">戒 ' + esc(item.ringSampleCount || 0) + '</span>' +
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
      const [session, ringData] = await Promise.all([
        api("/api/session?id=" + encodeURIComponent(id)),
        api("/api/ring-data?id=" + encodeURIComponent(id)),
      ]);
      state.ringData = ringData;
      state.currentSession = session;
      renderSession(session, ringData);
    }

    function renderSession(session, ringData) {
      const obs = session.viewer.observations;
      const maxSec = Math.max(10, ...obs.map((item) => item.endOffsetSec ?? item.startOffsetSec ?? 0));
      $("workspace").innerHTML = [
        renderToolbar(session),
        renderSummary(session),
        renderTimeline(obs, maxSec),
        renderRingPanel(session, ringData),
        '<div class="grid">' + obs.map((item) => renderObservation(session.viewer.sessionId, item)).join("") + '</div>'
      ].join("");
      $("sampleRate").addEventListener("change", (event) => {
        state.sampleRate = Number(event.target.value);
        document.querySelectorAll("audio[data-ref]").forEach((audio) => {
          audio.src = audioSrc(session.viewer.sessionId, audio.dataset.ref);
        });
      });
      if (ringData.available && ringData.displaySamples.length) {
        bindRingChartControls();
        drawRingChart(ringData.displaySamples, state.ringChartMode, session);
      }
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
        ["戒指样本", session.ringSampleCount || 0],
        ["快速移动", session.ringMotionAssessments?.length || 0],
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
        const width = item.type === "audio" || item.type === "ring" ? Math.max(1.2, end - start) : 1.8;
        return '<span class="marker ' + esc(item.type) + '" title="' + esc(item.type + " " + fmtOffset(item.startOffsetSec)) +
          '" style="left:' + start + '%;width:' + width + '%"></span>';
      }).join("");
      return '<div class="timeline"><div class="small">时间线：从 Session 开始计时，总跨度约 ' + esc(maxSec.toFixed(1)) +
        ' 秒。绿色是图片，橙色是短音频，紫红色是戒指判断，蓝色是其他事件。</div><div class="rail">' + ticks + markers + '</div></div>';
    }

    function renderRingPanel(session, ringData) {
      const assessments = Array.isArray(session.ringMotionAssessments) ? session.ringMotionAssessments : [];
      const rawLink = ringData.reference
        ? '<a class="download-link" href="/ring/raw?session=' + encodeURIComponent(session.viewer.sessionId) + '" download>下载完整原始 NDJSON</a>'
        : "";
      const configuration = session.ringSensor
        ? session.ringSensor.sampleRateHz + ' Hz · ±' + session.ringSensor.accelRangeG + ' g · ±' + session.ringSensor.gyroRangeDPS + ' dps'
        : "未记录";
      const units = ringData.physicalUnitsAvailable ? "物理单位" : "传感器原始数值";
      const accelUnit = ringData.physicalUnitsAvailable ? "g" : "raw";
      const gyroUnit = ringData.physicalUnitsAvailable ? "°/s" : "raw";
      const statistics = ringData.statistics
        ? '<div class="meta">' +
          '<span class="pill">加速度变化 P90 ' + esc(Number(ringData.statistics.accelerationChange.p90 || 0).toFixed(3)) + ' ' + accelUnit + '</span>' +
          '<span class="pill">加速度变化峰值 ' + esc(Number(ringData.statistics.accelerationChange.max || 0).toFixed(3)) + ' ' + accelUnit + '</span>' +
          '<span class="pill">转动速度 P90 ' + esc(Number(ringData.statistics.rotationSpeed.p90 || 0).toFixed(1)) + ' ' + gyroUnit + '</span>' +
          '<span class="pill">转动速度峰值 ' + esc(Number(ringData.statistics.rotationSpeed.max || 0).toFixed(1)) + ' ' + gyroUnit + '</span>' +
        '</div>'
        : "";
      const chart = ringData.available && ringData.displaySamples.length
        ? '<div class="chart-toolbar"><div class="chart-modes">' +
          '<button type="button" data-chart-mode="intensity">动作强度</button>' +
          '<button type="button" data-chart-mode="acceleration">三轴加速度</button>' +
          '<button type="button" data-chart-mode="rotation">三轴角速度</button>' +
          '</div><span class="small">' + units + '</span></div>' +
          '<div class="legend" id="ringLegend"></div><div class="ring-chart-wrap"><canvas id="ringChart"></canvas></div>'
        : '<div class="small">' + esc(ringData.error || "本次会话没有保留戒指原始数据；手机端需开启“保留本地样本”。") + '</div>';
      const assessmentItems = assessments.map((item) => {
        const linked = session.viewer.observations.filter((observation) => observation.triggerDecisionId === item.id);
        const linkedImages = linked.filter((item) => item.type === "image").length;
        const linkedAudios = linked.filter((item) => item.type === "audio").length;
        return '<div class="assessment">' +
          '<div class="item-title"><span>' + esc(item.displayLabel || item.classification) + '</span><span class="pill">' + esc(fmtOffset(secondsBetweenClient(session.startedAt, item.detectedAt))) + '</span></div>' +
          '<div class="small">加速度变化峰值 ' + esc(Number(item.peakAccelerationDeltaRaw || 0).toFixed(0)) +
          ' · 陀螺仪峰值 ' + esc(Number(item.peakGyroscopeMagnitudeRaw || 0).toFixed(0)) +
          ' · 灵敏度 ' + esc(item.sensitivity || "-") + '</div>' +
          '<div class="small">判断编号 ' + esc(item.id) + ' · 关联图片 ' + linkedImages + ' · 关联音频 ' + linkedAudios +
          (item.suppressionReason ? ' · 未触发原因 ' + esc(item.suppressionReason) : '') + '</div>' +
        '</div>';
      }).join("");
      return '<section class="ring-panel">' +
        '<div class="ring-header"><div><strong>戒指信号与动作判断</strong><div class="small">原始六轴信号 → 快速移动判断 → 眼镜图片/短音频</div></div>' + rawLink + '</div>' +
        '<div class="small">传感器参数：' + esc(configuration) + ' · 原始批次 ' + esc(ringData.totalBatches || 0) +
        ' · 原始样本 ' + esc(ringData.totalSamples || 0) + ' · 序号异常 ' + esc(session.ringSequenceGapCount || 0) +
        (ringData.displayStride > 1 ? ' · 曲线每 ' + esc(ringData.displayStride) + ' 点显示 1 点' : '') + '</div>' +
        statistics +
        chart +
        '<div class="assessment-list">' + (assessmentItems || '<div class="small">尚未形成“快速移动”判断。</div>') + '</div>' +
      '</section>';
    }

    function secondsBetweenClient(base, value) {
      if (!base || !value) return null;
      const diff = new Date(value).getTime() - new Date(base).getTime();
      return Number.isFinite(diff) ? Math.max(0, diff / 1000) : null;
    }

    function bindRingChartControls() {
      document.querySelectorAll("[data-chart-mode]").forEach((button) => {
        button.classList.toggle("selected", button.dataset.chartMode === state.ringChartMode);
        button.addEventListener("click", () => {
          state.ringChartMode = button.dataset.chartMode;
          document.querySelectorAll("[data-chart-mode]").forEach((item) => {
            item.classList.toggle("selected", item.dataset.chartMode === state.ringChartMode);
          });
          drawRingChart(state.ringData.displaySamples, state.ringChartMode, state.currentSession);
        });
      });
    }

    function drawRingChart(samples, mode, session) {
      const canvas = $("ringChart");
      if (!canvas || !samples.length) return;
      const ratio = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      const ctx = canvas.getContext("2d");
      ctx.scale(ratio, ratio);
      const width = rect.width;
      const height = rect.height;
      const pad = { left: 42, right: 12, top: 16, bottom: 24 };
      const plotWidth = Math.max(1, width - pad.left - pad.right);
      const plotHeight = Math.max(1, height - pad.top - pad.bottom);
      const minTime = Math.min(...samples.map((item) => Number(item.offsetSeconds || 0)));
      const maxTime = Math.max(minTime + 0.001, ...samples.map((item) => Number(item.offsetSeconds || 0)));
      const physical = Boolean(state.ringData?.physicalUnitsAvailable);
      const modes = {
        intensity: [
          { field: physical ? "accelDeltaG" : "accelDelta", label: "加速度变化", color: "#8a3f67", className: "" },
          { field: physical ? "gyroMagnitudeDPS" : "gyroMagnitude", label: "转动速度", color: "#287a91", className: "gyro" },
        ],
        acceleration: [
          { field: physical ? "accelXG" : "accelX", label: "X 轴", color: "#c0392b", className: "axis-x" },
          { field: physical ? "accelYG" : "accelY", label: "Y 轴", color: "#17864b", className: "axis-y" },
          { field: physical ? "accelZG" : "accelZ", label: "Z 轴", color: "#2868b2", className: "axis-z" },
        ],
        rotation: [
          { field: physical ? "gyroXDPS" : "gyroX", label: "X 轴", color: "#c0392b", className: "axis-x" },
          { field: physical ? "gyroYDPS" : "gyroY", label: "Y 轴", color: "#17864b", className: "axis-y" },
          { field: physical ? "gyroZDPS" : "gyroZ", label: "Z 轴", color: "#2868b2", className: "axis-z" },
        ],
      };
      const series = (modes[mode] || modes.intensity).map((item) => ({
        ...item,
        maximum: Math.max(0.0001, ...samples.map((sample) => Math.abs(Number(sample[item.field] || 0)))),
      }));
      const values = series.flatMap((item) => samples.map((sample) => Number(sample[item.field] || 0)));
      const signed = mode !== "intensity";
      const maxAbsolute = Math.max(0.0001, ...values.map(Math.abs));
      const unit = mode === "acceleration" && physical ? "g" : mode === "rotation" && physical ? "°/s" : physical ? "物理值" : "raw";
      $("ringLegend").innerHTML = series.map((item) =>
        '<span class="' + item.className + '">' + esc(item.label) + '</span>'
      ).join("") + '<span class="trigger">触发判断</span>';

      ctx.strokeStyle = "#e1e6e9";
      ctx.lineWidth = 1;
      for (let index = 0; index <= 4; index += 1) {
        const y = pad.top + plotHeight * index / 4;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(width - pad.right, y);
        ctx.stroke();
      }

      const markerOffsets = Array.isArray(session?.ringMotionAssessments)
        ? session.ringMotionAssessments.map((item) => secondsBetweenClient(session.startedAt, item.detectedAt)).filter((item) => item !== null)
        : [];
      markerOffsets.forEach((offset) => {
        if (offset < minTime || offset > maxTime) return;
        const x = pad.left + ((offset - minTime) / (maxTime - minTime)) * plotWidth;
        ctx.strokeStyle = "#8a3f67";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x, pad.top);
        ctx.lineTo(x, pad.top + plotHeight);
        ctx.stroke();
      });

      if (signed) {
        const zeroY = pad.top + plotHeight / 2;
        ctx.strokeStyle = "#9da8af";
        ctx.beginPath();
        ctx.moveTo(pad.left, zeroY);
        ctx.lineTo(width - pad.right, zeroY);
        ctx.stroke();
      }

      function line(seriesItem) {
        ctx.strokeStyle = seriesItem.color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        samples.forEach((sample, index) => {
          const x = pad.left + ((Number(sample.offsetSeconds || 0) - minTime) / (maxTime - minTime)) * plotWidth;
          const value = Number(sample[seriesItem.field] || 0);
          const maximum = signed ? maxAbsolute : seriesItem.maximum;
          const normalized = signed
            ? 0.5 - Math.max(-1, Math.min(1, value / maximum)) * 0.5
            : 1 - Math.max(0, Math.min(1, value / maximum));
          const y = pad.top + normalized * plotHeight;
          if (index === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
      }
      series.forEach(line);

      ctx.fillStyle = "#66727c";
      ctx.font = "11px system-ui";
      ctx.fillText(signed ? ("±" + maxAbsolute.toFixed(mode === "acceleration" ? 2 : 0)) : "0", 8, pad.top + plotHeight + 4);
      ctx.fillText("+" + minTime.toFixed(1) + "s", pad.left, height - 5);
      const endLabel = "+" + maxTime.toFixed(1) + "s";
      ctx.fillText(endLabel, width - pad.right - ctx.measureText(endLabel).width, height - 5);
      ctx.fillText(
        signed
          ? "上下限 " + maxAbsolute.toFixed(mode === "acceleration" ? 3 : 1) + " " + unit
          : "两条强度曲线分别按自身峰值缩放",
        pad.left,
        11,
      );
    }

    function mediaSrc(sessionId, ref) {
      return "/media?session=" + encodeURIComponent(sessionId) + "&ref=" + encodeURIComponent(ref);
    }

    function audioSrc(sessionId, ref) {
      return "/audio.wav?session=" + encodeURIComponent(sessionId) + "&ref=" + encodeURIComponent(ref) + "&rate=" + encodeURIComponent(state.sampleRate);
    }

    function renderObservation(sessionId, item) {
      const title = item.type === "image" ? "图片证据" : item.type === "audio" ? "短音频证据" : item.type === "ring" ? "戒指动作判断" : "事件";
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

    $("showLive").addEventListener("click", () => setView("live"));
    $("showHistory").addEventListener("click", () => setView("history"));
    $("refresh").addEventListener("click", () => {
      if (state.activeView === "live") loadLive().catch(() => {});
      else loadSessions().catch(() => {});
    });
    document.addEventListener("click", (event) => {
      const commandButton = event.target.closest("[data-command]");
      if (commandButton && !commandButton.disabled) {
        const extra = {};
        if (commandButton.dataset.deviceId) extra.deviceID = commandButton.dataset.deviceId;
        if (commandButton.dataset.boolValue) extra.boolValue = commandButton.dataset.boolValue === "true";
        sendCommand(commandButton.dataset.command, extra).catch((error) => {
          $("liveStatusDetail").textContent = error.message;
        });
      }
      const sensitivityButton = event.target.closest("[data-sensitivity]");
      if (sensitivityButton && !sensitivityButton.disabled) {
        sendCommand("ring.sensitivity", { stringValue: sensitivityButton.dataset.sensitivity }).catch((error) => {
          $("liveStatusDetail").textContent = error.message;
        });
      }
      const chartButton = event.target.closest("[data-live-chart-mode]");
      if (chartButton) {
        state.liveChartMode = chartButton.dataset.liveChartMode;
        document.querySelectorAll("[data-live-chart-mode]").forEach((button) => {
          button.classList.toggle("selected", button === chartButton);
        });
        drawLiveRingChart();
      }
      const actionButton = event.target.closest("[data-action-label]");
      if (actionButton && !actionButton.disabled) {
        postJson("/api/live/action-sample/start", {
          label: actionButton.dataset.actionLabel,
          durationSeconds: Number(actionButton.dataset.actionDuration),
          countdownSeconds: 3,
          mountPosition: actionButton.dataset.actionPlacement,
        }).then((result) => {
          state.actionSampling.active = result.active;
          renderActionSampling();
        }).catch((error) => {
          $("liveStatusDetail").textContent = error.message;
        });
      }
      const actionMountButton = event.target.closest("[data-action-mount]");
      if (actionMountButton && !actionMountButton.disabled) {
        state.actionSampling.mountPosition = actionMountButton.dataset.actionMount;
        renderActionSampling();
      }
    });
    $("clearActionSamples").addEventListener("click", () => {
      postJson("/api/live/action-samples/clear", {
        mountPosition: state.actionSampling.mountPosition,
      }).then((result) => {
        state.actionSampling.samples = result.samples || [];
        renderActionSampling();
      }).catch((error) => {
        $("liveStatusDetail").textContent = error.message;
      });
    });
    window.addEventListener("resize", () => {
      if (state.activeView === "live") drawLiveRingChart();
    });
    loadLive().catch((error) => {
      $("liveStatusDetail").textContent = error.message;
    });
    setInterval(() => {
      loadLive().catch(() => {});
    }, 500);
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
    if (requestUrl.pathname === "/api/live") {
      sendJson(res, {
        enabled: liveBridge.enabled,
        connected: liveBridge.connected,
        connectedAt: liveBridge.connectedAt,
        remoteAddress: liveBridge.remoteAddress,
        lastMessageAt: liveBridge.lastMessageAt,
        snapshot: liveBridge.snapshot,
        ringSampleCount: liveBridge.ringSamples.length,
        media: liveBridge.media.map(({ base64Data, ...item }) => item),
      });
      return;
    }
    if (requestUrl.pathname === "/api/live/ring") {
      sendJson(res, { samples: liveBridge.ringSamples });
      return;
    }
    if (requestUrl.pathname === "/api/live/action-samples") {
      sendJson(res, {
        active: liveBridge.activeActionCapture,
        samples: liveBridge.actionSamples,
      });
      return;
    }
    if (requestUrl.pathname === "/api/live/action-sample/start" && req.method === "POST") {
      const input = await readJsonBody(req);
      const active = startActionCapture(
        input.label,
        input.durationSeconds,
        input.countdownSeconds,
        input.mountPosition,
      );
      sendJson(res, { active }, 201);
      return;
    }
    if (requestUrl.pathname === "/api/live/action-samples/clear" && req.method === "POST") {
      if (liveBridge.activeActionCapture) {
        return fail(res, new Error("动作采样进行中，暂时不能清空"), 409);
      }
      const input = await readJsonBody(req);
      const mountPosition = input.mountPosition === ACTION_MOUNT_FINGER
        ? ACTION_MOUNT_FINGER
        : ACTION_MOUNT_GLASSES;
      liveBridge.actionSamples = liveBridge.actionSamples.filter(
        (sample) => (sample.mountPosition || ACTION_MOUNT_FINGER) !== mountPosition,
      );
      await persistActionSamples();
      sendJson(res, { cleared: true, samples: liveBridge.actionSamples });
      return;
    }
    if (requestUrl.pathname === "/api/live/command" && req.method === "POST") {
      const command = await readJsonBody(req);
      if (!command.command) return fail(res, new Error("缺少 command"), 400);
      sendLiveCommand(command);
      sendJson(res, { accepted: true });
      return;
    }
    if (requestUrl.pathname === "/api/live/media") {
      sendLiveMedia(res, requestUrl.searchParams.get("id"), false);
      return;
    }
    if (requestUrl.pathname === "/api/live/audio") {
      sendLiveMedia(res, requestUrl.searchParams.get("id"), true);
      return;
    }
    if (requestUrl.pathname === "/api/session") {
      const id = requestUrl.searchParams.get("id");
      if (!id) return fail(res, new Error("缺少 session id"), 400);
      sendJson(res, await readSession(id));
      return;
    }
    if (requestUrl.pathname === "/api/ring-data") {
      const id = requestUrl.searchParams.get("id");
      if (!id) return fail(res, new Error("缺少 session id"), 400);
      sendJson(res, await readRingData(id));
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
    if (requestUrl.pathname === "/ring/raw") {
      const sessionId = requestUrl.searchParams.get("session");
      if (!sessionId) return fail(res, new Error("缺少 session id"), 400);
      await sendRingRaw(res, sessionId);
      return;
    }
    sendText(res, "Not found", 404);
  } catch (error) {
    fail(res, error, 500);
  }
});

startLiveBridge();

server.listen(port, HOST, () => {
  console.log(`Reality Memory Debug Console`);
  console.log(`Root: ${captureRoot}`);
  console.log(`URL:  http://${HOST}:${port}`);
  console.log(``);
  console.log(`Usage: node ${path.relative(process.cwd(), path.join(__dirname, "server.mjs"))} [--live] <RealityMemoryProbe-or-pulled-container> [port]`);
});

function shutdown() {
  liveBridge.socket?.destroy();
  liveBridge.server?.close();
  liveBridge.bonjourProcess?.kill();
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 1_000).unref();
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
