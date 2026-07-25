import { execFile } from "node:child_process";
import { access } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

const PACKAGE_NAME = "com.realitymemory.glasses";
const APP_DATA_ROOT = "files/reality-memory";
const BACKEND_PORT = 8765;
const AGENT_PORT = 8200;
const MAX_ADB_BUFFER = 64 * 1024 * 1024;
const POLL_INTERVAL_MS = 750;
const DEVICE_REFRESH_INTERVAL_MS = 10_000;

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

async function firstExecutable(candidates) {
  for (const candidate of unique(candidates)) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      // Keep looking.
    }
  }
  return null;
}

async function resolveAdbPath() {
  const androidHome = process.env.ANDROID_HOME || process.env.ANDROID_SDK_ROOT;
  const direct = await firstExecutable([
    process.env.ADB,
    androidHome && path.join(androidHome, "platform-tools", "adb"),
    path.join(os.homedir(), "Library", "Android", "sdk", "platform-tools", "adb"),
    path.join(os.homedir(), "Android", "Sdk", "platform-tools", "adb"),
    "/opt/homebrew/bin/adb",
    "/usr/local/bin/adb",
  ]);
  if (direct) return direct;

  try {
    const { stdout } = await execFileAsync("/usr/bin/which", ["adb"], {
      encoding: "utf8",
      timeout: 2_000,
    });
    return stdout.trim() || null;
  } catch {
    return null;
  }
}

function parseDevices(output) {
  return output
    .split(/\r?\n/)
    .slice(1)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [serial, status, ...parts] = line.split(/\s+/);
      const properties = {};
      for (const part of parts) {
        const separator = part.indexOf(":");
        if (separator > 0) {
          properties[part.slice(0, separator)] = part.slice(separator + 1);
        }
      }
      return {
        serial,
        status,
        model: properties.model || null,
        product: properties.product || null,
        device: properties.device || null,
        transportId: properties.transport_id || null,
      };
    });
}

function chooseDevice(devices, preferredSerial) {
  const connected = devices.filter((device) => device.status === "device");
  return (
    connected.find((device) => device.serial === preferredSerial)
    || connected.find((device) => device.model === "RG_glasses")
    || connected.find((device) => device.product === "glasses")
    || connected[0]
    || null
  );
}

function parseJsonLines(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .flatMap((line) => {
      try {
        return [JSON.parse(line)];
      } catch {
        return [];
      }
    });
}

function parseSnapshotBundle(output) {
  const records = [];
  let meta = {};
  let audit = [];
  let manifest = [];
  let liveSensor = null;
  let liveSensorLines = [];
  let currentFile = null;
  let currentLines = [];
  let section = null;

  const finishFile = () => {
    if (!currentFile) return;
    try {
      records.push({ ...JSON.parse(currentLines.join("\n")), _device_path: currentFile });
    } catch {
      records.push({
        schema_ref: "rme.debug-unparsed-json.v1",
        _device_path: currentFile,
        _parse_error: true,
      });
    }
    currentFile = null;
    currentLines = [];
  };

  for (const rawLine of output.split(/\r?\n/)) {
    const line = rawLine.replace(/\r$/, "");
    if (line.startsWith("@@RME_FILE@@")) {
      finishFile();
      section = "file";
      currentFile = line.slice("@@RME_FILE@@".length);
      continue;
    }
    if (line === "@@RME_END_FILE@@") {
      finishFile();
      section = null;
      continue;
    }
    if (line === "@@RME_META@@") {
      finishFile();
      section = "meta";
      continue;
    }
    if (line === "@@RME_AUDIT@@") {
      finishFile();
      section = "audit";
      continue;
    }
    if (line === "@@RME_MANIFEST@@") {
      finishFile();
      section = "manifest";
      continue;
    }
    if (line === "@@RME_LIVE_SENSOR@@") {
      finishFile();
      section = "live-sensor";
      continue;
    }

    if (section === "file" && currentFile) currentLines.push(line);
    else if (section === "meta" && line.trim()) {
      try {
        meta = JSON.parse(line);
      } catch {
        // The next successful poll will replace malformed transient output.
      }
    } else if (section === "audit") {
      audit.push(line);
    } else if (section === "manifest") {
      manifest.push(line);
    } else if (section === "live-sensor") {
      liveSensorLines.push(line);
    }
  }
  finishFile();

  audit = parseJsonLines(audit.join("\n"));
  manifest = parseJsonLines(manifest.join("\n"));
  try {
    liveSensor = JSON.parse(liveSensorLines.join("\n"));
  } catch {
    liveSensor = null;
  }
  return { meta, records, audit, manifest, liveSensor };
}

function recordBySchema(records, schemaRef) {
  return records.find((record) => record.schema_ref === schemaRef) || null;
}

function recordsBySchema(records, schemaRef) {
  return records.filter((record) => record.schema_ref === schemaRef);
}

function deriveHeartRate(audit) {
  const samples = audit
    .filter((item) => item.event === "HEART_RATE_BROADCAST_SAMPLE")
    .sort((a, b) => String(a.occurred_at).localeCompare(String(b.occurred_at)));
  const latestStatus = [...audit]
    .reverse()
    .find((item) => item.event === "HEART_RATE_BROADCAST_STATUS");
  const latestBatch = [...audit]
    .reverse()
    .find((item) =>
      item.event === "HEART_RATE_EVIDENCE_SUCCEEDED"
      || item.event === "HEART_RATE_EVIDENCE_FAILED"
    );
  const intervals = samples.slice(1).map((sample, index) =>
    new Date(sample.occurred_at).getTime() - new Date(samples[index].occurred_at).getTime()
  ).filter((value) => Number.isFinite(value) && value >= 0);
  const latest = samples.at(-1) || null;
  return {
    status: latestStatus?.detail?.message || "尚未启动心率广播测试",
    latest: latest ? {
      bpm: latest.detail?.bpm ?? null,
      peripheralName: latest.detail?.peripheral_name ?? null,
      peripheralAddress: latest.detail?.peripheral_address ?? null,
      rssi: latest.detail?.rssi ?? null,
      capturedAt: latest.detail?.captured_at || latest.occurred_at,
      rawHex: latest.detail?.raw_hex ?? null,
    } : null,
    sampleCount: samples.length,
    averageIntervalMs: intervals.length
      ? intervals.reduce((sum, value) => sum + value, 0) / intervals.length
      : null,
    maxGapMs: intervals.length ? Math.max(...intervals) : null,
    stable: intervals.length >= 2 && Math.max(...intervals) <= 5_000,
    latestBatch: latestBatch ? {
      succeeded: latestBatch.event === "HEART_RATE_EVIDENCE_SUCCEEDED",
      occurredAt: latestBatch.occurred_at,
      ...latestBatch.detail,
    } : null,
  };
}

function parsePackageInfo(output) {
  const versionName = output.match(/\bversionName=([^\s]+)/)?.[1] || null;
  const versionCode = output.match(/\bversionCode=(\d+)/)?.[1] || null;
  return {
    installed: Boolean(versionName || versionCode),
    versionName,
    versionCode,
  };
}

function mediaExtension(modality, mimeType, relativePath) {
  const ext = path.extname(relativePath || "").toLowerCase();
  if (ext) return ext;
  if (modality === "IMAGE") return ".jpg";
  if (modality === "VIDEO") return ".mp4";
  if (modality === "AUDIO" || mimeType?.includes("pcm")) return ".pcm";
  if (modality === "SENSOR") return ".ndjson";
  return "";
}

function mediaMime(item) {
  const ext = mediaExtension(item.modality, item.mime_type, item.relative_path);
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".png") return "image/png";
  if (ext === ".mp4") return "video/mp4";
  if (ext === ".wav") return "audio/wav";
  if (ext === ".pcm") return "audio/L16";
  if (ext === ".ndjson") return "application/x-ndjson";
  return item.mime_type || "application/octet-stream";
}

function makeWav(pcm, sampleRate = 16_000, channelCount = 1, bitsPerSample = 16) {
  const header = Buffer.alloc(44);
  const byteRate = sampleRate * channelCount * bitsPerSample / 8;
  const blockAlign = channelCount * bitsPerSample / 8;
  header.write("RIFF", 0);
  header.writeUInt32LE(36 + pcm.length, 4);
  header.write("WAVE", 8);
  header.write("fmt ", 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);
  header.writeUInt16LE(channelCount, 22);
  header.writeUInt32LE(sampleRate, 24);
  header.writeUInt32LE(byteRate, 28);
  header.writeUInt16LE(blockAlign, 32);
  header.writeUInt16LE(bitsPerSample, 34);
  header.write("data", 36);
  header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}

function deriveSnapshot(bundle, previous) {
  const session = recordBySchema(bundle.records, "rme.capture-session.v1");
  const intent = recordBySchema(bundle.records, "rme.capture-intent.v1");
  const window = recordBySchema(bundle.records, "rme.capture-window.v1");
  const attempts = recordsBySchema(bundle.records, "rme.capture-attempt.v1")
    .filter(
      (item) =>
        !window?.capture_window_id
        || item.capture_window_id === window.capture_window_id,
    )
    .sort((a, b) => String(a.requested_at).localeCompare(String(b.requested_at)));
  const evidence = recordsBySchema(bundle.records, "rme.evidence-item.v1");
  const uploads = bundle.records
    .filter((record) => record._device_path?.endsWith(".upload.json"))
    .map((record) => ({
      ...record,
      evidence_item_id: path.basename(record._device_path).replace(/\.upload\.json$/, ""),
    }));
  const uploadByEvidence = new Map(uploads.map((item) => [item.evidence_item_id, item]));
  const evidenceById = new Map(evidence.map((item) => [item.evidence_item_id, item]));

  const media = bundle.manifest
    .filter((item) => !session || item.capture_session_id === session.capture_session_id)
    .map((item) => {
      const evidenceItem = evidenceById.get(item.evidence_item_id);
      const upload = uploadByEvidence.get(item.evidence_item_id);
      return {
        ...item,
        id: item.evidence_item_id,
        mime_type: item.mime_type || evidenceItem?.mime_type,
        extension: mediaExtension(item.modality, item.mime_type, item.relative_path),
        content_type: mediaMime(item),
        device_path: `${APP_DATA_ROOT}/debug-export/${item.relative_path}`,
        upload_state: upload?.state || null,
        upload_attempt_count: upload?.attempt_count || 0,
        upload_error: upload?.last_error || null,
        media: evidenceItem?.media || null,
      };
    })
    .sort((a, b) => String(b.captured_at).localeCompare(String(a.captured_at)));
  const latestAudio = media.find((item) => item.modality === "AUDIO") || null;
  const latestSystemVideo = media.find(
    (item) =>
      item.modality === "VIDEO"
      && item.media?.capture_mode === "ROKID_SYSTEM_RECORDING_SERVICE_NO_APP_PREVIEW",
  ) || null;
  const signalQuality = latestAudio?.media?.signal_quality || null;

  return {
    ...previous,
    session,
    intent,
    window,
    attempts,
    evidence,
    uploads,
    media,
    liveSensor: bundle.liveSensor,
    heartRate: deriveHeartRate(bundle.audit),
    audioDiagnostics: {
      directAudio: latestAudio
        ? {
            evidenceItemId: latestAudio.id,
            capturedAt: latestAudio.captured_at,
            captureMode: latestAudio.media?.capture_mode || null,
            peakDbfs: signalQuality?.peak_dbfs ?? null,
            rmsDbfs: signalQuality?.rms_dbfs ?? null,
            likelySilent: signalQuality?.likely_silent ?? null,
            systemSilenced: signalQuality?.system_silenced ?? null,
          }
        : null,
      systemVideo: latestSystemVideo
        ? {
            evidenceItemId: latestSystemVideo.id,
            capturedAt: latestSystemVideo.captured_at,
            hasAudioTrack: latestSystemVideo.media?.has_audio_track ?? null,
            durationMs: latestSystemVideo.duration_ms ?? null,
            uploadState: latestSystemVideo.upload_state ?? null,
          }
        : null,
    },
    audit: bundle.audit.slice(-100).reverse(),
    sessionPath: bundle.meta.session_path || null,
    windowPath: bundle.meta.window_path || null,
  };
}

export function createRv101Adapter(options = {}) {
  const preferredSerial = options.serial || process.env.RME_RV101_SERIAL || null;
  const backendUrl = options.backendUrl || process.env.RME_BACKEND_URL || `http://127.0.0.1:${BACKEND_PORT}`;
  const agentUrl = options.agentUrl || process.env.RME_AGENT_URL || `http://127.0.0.1:${AGENT_PORT}`;
  let adbPath = null;
  let selectedDevice = null;
  let pollTimer = null;
  let polling = false;
  let stopped = false;
  let lastDeviceRefreshAt = 0;
  const mediaCache = new Map();
  const sensorCache = new Map();

  let snapshot = {
    enabled: true,
    connected: false,
    adbPath: null,
    devices: [],
    device: null,
    app: {
      packageName: PACKAGE_NAME,
      installed: false,
      versionName: null,
      versionCode: null,
      processId: null,
      serviceRunning: false,
      foregroundService: false,
      activityForeground: false,
    },
    worn: null,
    backend: {
      url: backendUrl,
      connected: false,
      detail: "尚未检查",
    },
    agent: {
      url: agentUrl,
      connected: false,
      detail: "尚未检查",
    },
    pipeline: null,
    audioDiagnostics: {
      directAudio: null,
      systemVideo: null,
    },
    session: null,
    intent: null,
    window: null,
    attempts: [],
    evidence: [],
    uploads: [],
    media: [],
    liveSensor: null,
    heartRate: {
      status: "尚未启动心率广播测试",
      latest: null,
      sampleCount: 0,
      averageIntervalMs: null,
      maxGapMs: null,
      stable: false,
      latestBatch: null,
    },
    audit: [],
    lastUpdatedAt: null,
    error: null,
  };

  async function adb(args, encoding = "utf8") {
    if (!adbPath) throw new Error("未找到 Android Platform-Tools（adb）");
    const result = await execFileAsync(adbPath, args, {
      encoding,
      timeout: 8_000,
      maxBuffer: MAX_ADB_BUFFER,
    });
    return result.stdout;
  }

  async function deviceAdb(args, encoding = "utf8") {
    if (!selectedDevice) throw new Error("未连接 RV101");
    return adb(["-s", selectedDevice.serial, ...args], encoding);
  }

  async function runAs(args, encoding = "utf8") {
    return deviceAdb(["exec-out", "run-as", PACKAGE_NAME, ...args], encoding);
  }

  async function refreshDevice() {
    const output = await adb(["devices", "-l"]);
    const devices = parseDevices(output);
    selectedDevice = chooseDevice(devices, preferredSerial || selectedDevice?.serial);
    snapshot.devices = devices;
    snapshot.device = selectedDevice;
    snapshot.connected = Boolean(selectedDevice);
    if (!selectedDevice) {
      snapshot.app = {
        packageName: PACKAGE_NAME,
        installed: false,
        versionName: null,
        versionCode: null,
        processId: null,
        serviceRunning: false,
        foregroundService: false,
        activityForeground: false,
      };
      snapshot.worn = null;
      return;
    }

    const [
      packageOutput,
      processOutput,
      modelOutput,
      androidOutput,
      serviceOutput,
      activityOutput,
      wornOutput,
    ] = await Promise.all([
      deviceAdb(["shell", "dumpsys", "package", PACKAGE_NAME]).catch(() => ""),
      deviceAdb(["shell", "pidof", PACKAGE_NAME]).catch(() => ""),
      deviceAdb(["shell", "getprop", "ro.product.model"]).catch(() => ""),
      deviceAdb(["shell", "getprop", "ro.build.version.release"]).catch(() => ""),
      deviceAdb(["shell", "dumpsys", "activity", "services", PACKAGE_NAME]).catch(() => ""),
      deviceAdb(["shell", "dumpsys", "activity", "activities"]).catch(() => ""),
      deviceAdb(["shell", "getprop", "vendor.rkd.glasses.is_take_on"]).catch(() => ""),
    ]);
    snapshot.device = {
      ...selectedDevice,
      model: modelOutput.trim() || selectedDevice.model,
      androidVersion: androidOutput.trim() || null,
    };
    snapshot.app = {
      packageName: PACKAGE_NAME,
      ...parsePackageInfo(packageOutput),
      processId: processOutput.trim() || null,
      serviceRunning: serviceOutput.includes("RealityRuntimeService"),
      foregroundService:
        serviceOutput.includes("RealityRuntimeService") &&
        /\bisForeground=true\b/.test(serviceOutput),
      activityForeground:
        new RegExp(`topResumedActivity=.*${PACKAGE_NAME.replaceAll(".", "\\.")}`)
          .test(activityOutput),
    };
    snapshot.worn = wornOutput.trim() === "1"
      ? true
      : wornOutput.trim() === "0"
        ? false
        : null;
    await deviceAdb(["reverse", `tcp:${BACKEND_PORT}`, `tcp:${BACKEND_PORT}`]).catch(() => "");
  }

  async function refreshBackend() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 1_200);
    try {
      const response = await fetch(`${backendUrl}/healthz`, { signal: controller.signal });
      const body = await response.text();
      snapshot.backend = {
        url: backendUrl,
        connected: response.ok,
        status: response.status,
        detail: body.slice(0, 300) || response.statusText,
      };
    } catch (error) {
      snapshot.backend = {
        url: backendUrl,
        connected: false,
        detail: error.name === "AbortError" ? "连接超时" : error.message,
      };
    } finally {
      clearTimeout(timeout);
    }
  }

  async function refreshAgent() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 1_200);
    try {
      const response = await fetch(`${agentUrl}/healthz`, { signal: controller.signal });
      const body = await response.text();
      snapshot.agent = {
        url: agentUrl,
        connected: response.ok,
        status: response.status,
        detail: body.slice(0, 300) || response.statusText,
      };
    } catch (error) {
      snapshot.agent = {
        url: agentUrl,
        connected: false,
        detail: error.name === "AbortError" ? "连接超时" : error.message,
      };
    } finally {
      clearTimeout(timeout);
    }
  }

  async function refreshPipeline() {
    const sourceSessionId = snapshot.session?.capture_session_id;
    if (!snapshot.backend.connected || !sourceSessionId) {
      snapshot.pipeline = null;
      return;
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2_000);
    try {
      const url = new URL("/internal/v1/debug/pipeline", backendUrl);
      url.searchParams.set("source_session_id", sourceSessionId);
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) {
        throw new Error(`沉淀状态接口 HTTP ${response.status}`);
      }
      snapshot.pipeline = await response.json();
    } catch (error) {
      snapshot.pipeline = {
        source_session_id: sourceSessionId,
        error: error.name === "AbortError" ? "读取沉淀状态超时" : error.message,
      };
    } finally {
      clearTimeout(timeout);
    }
  }

  async function readDeviceSnapshot() {
    const script = [
      `session=$(ls -td ${APP_DATA_ROOT}/outbox/ses_* 2>/dev/null | head -n 1)`,
      `window=$(ls -td "$session"/win_* 2>/dev/null | head -n 1)`,
      `windows=$(ls -td "$session"/win_* 2>/dev/null | head -n 8)`,
      `printf '@@RME_META@@\\n'`,
      `printf '{"session_path":"%s","window_path":"%s"}\\n' "$session" "$window"`,
      `for f in "$session/capture-session.json"; do`,
      `  if [ -f "$f" ]; then`,
      `    printf '@@RME_FILE@@%s\\n' "$f"`,
      `    cat "$f"`,
      `    printf '\\n@@RME_END_FILE@@\\n'`,
      `  fi`,
      `done`,
      `for current_window in $windows; do`,
      `  for f in "$current_window"/*.json; do`,
      `    if [ -f "$f" ]; then`,
      `      printf '@@RME_FILE@@%s\\n' "$f"`,
      `      cat "$f"`,
      `      printf '\\n@@RME_END_FILE@@\\n'`,
      `    fi`,
      `  done`,
      `done`,
      `printf '@@RME_AUDIT@@\\n'`,
      `tail -n 120 ${APP_DATA_ROOT}/audit.ndjson 2>/dev/null`,
      `printf '@@RME_MANIFEST@@\\n'`,
      `tail -n 160 ${APP_DATA_ROOT}/debug-export/manifest.ndjson 2>/dev/null`,
      `printf '@@RME_LIVE_SENSOR@@\\n'`,
      `cat ${APP_DATA_ROOT}/runtime/live-sensor.json 2>/dev/null`,
    ].join("\n");
    const output = await runAs(["sh", "-c", script]);
    snapshot = deriveSnapshot(parseSnapshotBundle(output), snapshot);
  }

  async function poll() {
    if (polling || stopped) return;
    polling = true;
    try {
      if (!adbPath) adbPath = await resolveAdbPath();
      snapshot.adbPath = adbPath;
      if (!adbPath) throw new Error("没有找到 adb，请安装 Android Platform-Tools");

      const now = Date.now();
      if (!selectedDevice || now - lastDeviceRefreshAt >= DEVICE_REFRESH_INTERVAL_MS) {
        await refreshDevice();
        lastDeviceRefreshAt = now;
      }
      await refreshBackend();
      await refreshAgent();
      if (selectedDevice && snapshot.app.installed) {
        await readDeviceSnapshot();
      }
      await refreshPipeline();
      snapshot.error = null;
      snapshot.lastUpdatedAt = new Date().toISOString();
    } catch (error) {
      snapshot.error = error.message;
      snapshot.lastUpdatedAt = new Date().toISOString();
      if (/device|offline|closed|not found/i.test(error.message)) {
        selectedDevice = null;
        snapshot.connected = false;
      }
    } finally {
      polling = false;
    }
  }

  function findMedia(id) {
    const media = snapshot.media.find((item) => item.id === id);
    if (!media) throw new Error("没有找到这条真机媒体");
    if (!media.device_path.startsWith(`${APP_DATA_ROOT}/debug-export/`)) {
      throw new Error("媒体路径不在允许读取的调试目录中");
    }
    return media;
  }

  async function readMedia(id, options = {}) {
    const item = findMedia(id);
    const cacheKey = `${id}:${options.asAudio ? "audio" : "raw"}`;
    if (mediaCache.has(cacheKey)) return mediaCache.get(cacheKey);
    let body = await runAs(["cat", item.device_path], null);
    let contentType = item.content_type;
    if (options.asAudio && item.extension === ".pcm") {
      const sampleRate = Number(item.media?.sample_rate_hz || 16_000);
      const channelCount = Number(item.media?.channel_count || item.media?.channels || 1);
      body = makeWav(body, sampleRate, channelCount);
      contentType = "audio/wav";
    }
    const result = { body, contentType, item };
    mediaCache.set(cacheKey, result);
    if (mediaCache.size > 12) mediaCache.delete(mediaCache.keys().next().value);
    return result;
  }

  async function readSensor(id) {
    const item = findMedia(id);
    if (item.modality !== "SENSOR") throw new Error("这条证据不是六轴传感器数据");
    if (sensorCache.has(id)) return sensorCache.get(id);
    const text = await runAs(["cat", item.device_path]);
    const samples = parseJsonLines(text);
    const result = {
      item,
      sampleCount: samples.length,
      samples: samples.slice(-2_500),
    };
    sensorCache.set(id, result);
    if (sensorCache.size > 8) sensorCache.delete(sensorCache.keys().next().value);
    return result;
  }

  async function command(name) {
    if (!selectedDevice) throw new Error("未连接 RV101");
    switch (name) {
      case "refresh":
        await poll();
        break;
      case "wake_start":
        await deviceAdb(["shell", "input", "keyevent", "224"]);
        await deviceAdb(["shell", "am", "start", "-n", `${PACKAGE_NAME}/.MainActivity`]);
        break;
      case "capture_now":
        await deviceAdb([
          "shell",
          "am",
          "start",
          "-n",
          `${PACKAGE_NAME}/.MainActivity`,
          "--es",
          "rme_debug_command",
          "remember_now",
        ]);
        break;
      case "system_video":
        await deviceAdb([
          "shell",
          "am",
          "start",
          "-n",
          `${PACKAGE_NAME}/.MainActivity`,
          "--es",
          "rme_debug_command",
          "system_video",
        ]);
        break;
      case "end_session":
        await deviceAdb([
          "shell",
          "am",
          "start",
          "-n",
          `${PACKAGE_NAME}/.MainActivity`,
          "--es",
          "rme_debug_command",
          "end_session",
        ]);
        break;
      case "connect_backend":
        await deviceAdb(["reverse", `tcp:${BACKEND_PORT}`, `tcp:${BACKEND_PORT}`]);
        break;
      case "heart_rate_start":
        await deviceAdb([
          "shell",
          "pm",
          "grant",
          PACKAGE_NAME,
          "android.permission.BLUETOOTH_SCAN",
        ]).catch(() => "");
        await deviceAdb([
          "shell",
          "pm",
          "grant",
          PACKAGE_NAME,
          "android.permission.BLUETOOTH_CONNECT",
        ]).catch(() => "");
        await deviceAdb([
          "shell",
          "am",
          "start",
          "-n",
          `${PACKAGE_NAME}/.MainActivity`,
          "--es",
          "rme_debug_command",
          "heart_rate_start",
        ]);
        break;
      case "heart_rate_stop":
        await deviceAdb([
          "shell",
          "am",
          "start",
          "-n",
          `${PACKAGE_NAME}/.MainActivity`,
          "--es",
          "rme_debug_command",
          "heart_rate_stop",
        ]);
        break;
      default:
        throw new Error(`不支持的 RV101 调试命令：${name}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
    await poll();
    return { accepted: true, command: name };
  }

  return {
    start() {
      stopped = false;
      poll().catch(() => {});
      pollTimer = setInterval(() => poll().catch(() => {}), POLL_INTERVAL_MS);
      pollTimer.unref();
    },
    stop() {
      stopped = true;
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
    },
    refresh: poll,
    getSnapshot() {
      return structuredClone(snapshot);
    },
    readMedia,
    readSensor,
    command,
  };
}
