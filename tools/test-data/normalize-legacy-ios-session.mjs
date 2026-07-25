#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  access,
  copyFile,
  cp,
  mkdir,
  readFile,
  readdir,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";

const [sourceArg, destinationArg, datasetId, title] = process.argv.slice(2);
if (!sourceArg || !destinationArg || !datasetId || !title) {
  throw new Error(
    "Usage: node normalize-legacy-ios-session.mjs <source-session-dir> <destination> <dataset-id> <title>",
  );
}

const sourceDir = path.resolve(sourceArg);
const destination = path.resolve(destinationArg);
const rawDir = path.join(destination, "raw");
const normalizedDir = path.join(destination, "normalized");

try {
  await access(destination);
  throw new Error(`Destination already exists: ${destination}`);
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}

const session = JSON.parse(await readFile(path.join(sourceDir, "session.json"), "utf8"));
await mkdir(rawDir, { recursive: true });
await mkdir(normalizedDir, { recursive: true });
await copyFile(path.join(sourceDir, "session.json"), path.join(rawDir, "session.json"));
await cp(path.join(sourceDir, "evidence"), path.join(rawDir, "evidence"), {
  recursive: true,
});

const ringPath = path.join(sourceDir, session.ringDataReference || "");
let ringBatches = [];
if (session.ringDataReference) {
  await mkdir(path.join(rawDir, "ring"), { recursive: true });
  await copyFile(ringPath, path.join(rawDir, "ring", "imu.ndjson"));
  ringBatches = (await readFile(ringPath, "utf8"))
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

const compact = (value) => String(value).toLowerCase().replaceAll("-", "");
const makeId = (prefix, value) => `${prefix}_${compact(value)}`;
const sessionId = makeId("ses", session.id);
const deviceId = "device_legacy_ios_cxrl_fixture";
const policyId = makeId("policy", session.id);
const ttlExpiresAt = "2027-07-24T23:59:59.000Z";
const sourceEnvelopeIds = [];
const captureIntents = [];
const captureWindows = [];
const captureAttempts = [];
const sourceEnvelopes = [];
const evidenceItems = [];
const windowByDecision = new Map();
const attemptsByEvidence = new Map();

const normalizedSession = {
  schema_ref: "rme.capture-session.v1",
  capture_session_id: sessionId,
  device_id: deviceId,
  state: String(session.state || "paused").toUpperCase(),
  started_at: session.startedAt,
  started_monotonic_ns: null,
  ended_at: session.endedAt || null,
  ended_monotonic_ns: null,
  start_reason: "DEBUG_TEST",
  end_reason: session.endedAt ? "LEGACY_SESSION_ENDED" : null,
  policy_snapshot_id: policyId,
  consent_notice_version: "legacy-explicit-test-export/1.0",
  runtime_version: "ios-cxrl-legacy",
  extensions: {
    source_schema_version: session.schemaVersion,
    monotonic_time_missing: true,
    original_state: session.state,
    original_session_id: session.id,
  },
};

function minTime(values) {
  return values.filter(Boolean).sort()[0];
}

function maxTime(values) {
  return values.filter(Boolean).sort().at(-1);
}

function modalities(values) {
  return [...new Set(values.map((value) => String(value).toUpperCase()))];
}

function addMotionWindow(assessment) {
  const decisionKey = compact(assessment.id);
  const relatedImages = (session.observations || []).filter(
    (item) => item.triggerDecisionID && compact(item.triggerDecisionID) === decisionKey,
  );
  const relatedAudio = (session.audioObservations || []).filter(
    (item) => item.triggerDecisionID && compact(item.triggerDecisionID) === decisionKey,
  );
  const intentId = makeId("cin", assessment.id);
  const windowId = makeId("win", assessment.id);
  const start = minTime([
    assessment.windowStartedAt,
    assessment.detectedAt,
    ...relatedImages.map((item) => item.scheduledAt),
    ...relatedAudio.map((item) => item.startedAt),
  ]);
  const end = maxTime([
    assessment.windowEndedAt,
    assessment.detectedAt,
    ...relatedImages.map((item) => item.completedAt),
    ...relatedAudio.map((item) => item.endedAt),
  ]);
  const metricKeys = [
    "sampleCount",
    "peakAccelerationDeltaRaw",
    "peakGyroscopeMagnitudeRaw",
    "accelerationBaselineRaw",
    "gyroscopeBaselineRaw",
    "motionIntensityRatio",
    "relativeChangeScore",
    "isStrongChange",
  ];
  const metrics = {};
  for (const key of metricKeys) {
    if (assessment[key] !== undefined) metrics[key] = assessment[key];
  }
  captureIntents.push({
    schema_ref: "rme.capture-intent.v1",
    capture_intent_id: intentId,
    capture_session_id: sessionId,
    signal_kind: "HEAD_MOTION_TRANSITION",
    occurred_at: assessment.detectedAt,
    monotonic_start_ns: null,
    monotonic_end_ns: null,
    detector_rule_version: assessment.detectorRuleVersion,
    intensity: assessment.isStrongChange ? "STRONG" : "MEDIUM",
    metrics,
    requested_modalities: modalities(assessment.requestedModalities || ["IMAGE"]),
    extensions: {
      legacy_classification: assessment.classification,
      legacy_capture_tier: assessment.captureTier || null,
      capture_policy_version: assessment.capturePolicyVersion || null,
      sensor_source: "EXTERNAL_RING_FIXED_TO_GLASSES",
      monotonic_time_missing: true,
    },
  });
  captureWindows.push({
    schema_ref: "rme.capture-window.v1",
    capture_window_id: windowId,
    capture_session_id: sessionId,
    capture_intent_id: intentId,
    window_start: start,
    window_end: end,
    monotonic_start_ns: null,
    monotonic_end_ns: null,
    requested_modalities: modalities(assessment.requestedModalities || ["IMAGE"]),
    policy_snapshot_id: policyId,
    state: "FINALIZED",
    extensions: {
      legacy_time_source: "WALL_CLOCK_FIELDS",
    },
  });
  windowByDecision.set(decisionKey, { intentId, windowId });
}

for (const assessment of session.ringMotionAssessments || []) {
  addMotionWindow(assessment);
}

function ensureLegacyWindow(item, modality) {
  if (item.triggerDecisionID) {
    const existing = windowByDecision.get(compact(item.triggerDecisionID));
    if (existing) return existing;
  }
  const key = compact(item.id);
  const existing = windowByDecision.get(key);
  if (existing) return existing;
  const intentId = makeId("cin", item.id);
  const windowId = makeId("win", item.id);
  const start = item.startedAt || item.scheduledAt || item.completedAt;
  const end = item.endedAt || item.completedAt || start;
  captureIntents.push({
    schema_ref: "rme.capture-intent.v1",
    capture_intent_id: intentId,
    capture_session_id: sessionId,
    signal_kind: "DEBUG_TEST",
    occurred_at: start,
    monotonic_start_ns: null,
    monotonic_end_ns: null,
    detector_rule_version: "legacy-periodic-or-vad-import/1.0",
    intensity: "LOW",
    metrics: {
      legacy_trigger: item.trigger || "UNKNOWN",
    },
    requested_modalities: [modality],
    extensions: {
      monotonic_time_missing: true,
    },
  });
  captureWindows.push({
    schema_ref: "rme.capture-window.v1",
    capture_window_id: windowId,
    capture_session_id: sessionId,
    capture_intent_id: intentId,
    window_start: start,
    window_end: end,
    monotonic_start_ns: null,
    monotonic_end_ns: null,
    requested_modalities: [modality],
    policy_snapshot_id: policyId,
    state: "FINALIZED",
    extensions: {
      legacy_trigger: item.trigger || "UNKNOWN",
    },
  });
  const created = { intentId, windowId };
  windowByDecision.set(key, created);
  return created;
}

async function addMediaEvidence(item, modality) {
  const { intentId, windowId } = ensureLegacyWindow(item, modality);
  const evidenceId = makeId("evd", item.id);
  const envelopeId = makeId("src", item.id);
  const attemptId = makeId("att", item.id);
  const rawPath = path.join(rawDir, item.localMediaReference);
  const fileStats = await stat(rawPath);
  const checksum = await sha256(rawPath);
  const occurredAt = item.startedAt || item.completedAt || item.scheduledAt;
  const observedAt = item.endedAt || item.completedAt || occurredAt;
  const isAudio = modality === "AUDIO";
  const sampleRateHz = isAudio ? 16000 : null;
  const channels = isAudio ? item.channels || 1 : null;
  const actualDurationMs = isAudio
    ? Math.round((fileStats.size / (sampleRateHz * channels * 2)) * 1000)
    : 0;
  const media = isAudio
    ? {
        container: "RAW_PCM",
        codec: "PCM_S16LE",
        sample_rate_hz: sampleRateHz,
        channel_count: channels,
        capture_mode: item.trigger === "SESSION_VAD" ? "LEGACY_PHONE_VAD" : "LEGACY_TRIGGERED_AUDIO",
        duration_source: "BYTE_COUNT",
        declared_capture_window_duration_ms: item.durationMilliseconds ?? null,
        peak_dbfs: item.peakDBFS ?? null,
      }
    : {
        codec: path.extname(item.localMediaReference).toLowerCase() === ".webp" ? "WEBP" : "JPEG",
        capture_mode: "LEGACY_CXRL_IMAGE",
        camera_facing: "WORLD",
      };
  sourceEnvelopes.push({
    schema_ref: "rme.source-envelope.v1",
    source_envelope_id: envelopeId,
    device_id: deviceId,
    device_kind: "IOS_CXRL_GATEWAY_WITH_ROKID_GLASSES",
    device_adapter: "ios-cxrl-legacy-fixture/1.0",
    capture_session_id: sessionId,
    capture_window_id: windowId,
    capture_intent_id: intentId,
    occurred_at: occurredAt,
    observed_at: observedAt,
    monotonic_start_ns: null,
    monotonic_end_ns: null,
    clock_domain: "IOS_WALLCLOCK_ONLY_LEGACY",
    clock_sync_method: "LEGACY_IMPORT",
    time_uncertainty_ms: 1000,
    policy_snapshot_id: policyId,
    modality,
    payload_kind: "EVIDENCE_ITEM",
    payload_ref: evidenceId,
    idempotency_key: evidenceId,
    extensions: {
      original_observation_id: item.id,
      original_trigger: item.trigger,
      monotonic_time_missing: true,
    },
  });
  sourceEnvelopeIds.push(envelopeId);
  evidenceItems.push({
    schema_ref: "rme.evidence-item.v1",
    evidence_item_id: evidenceId,
    source_envelope_id: envelopeId,
    capture_window_id: windowId,
    modality,
    mime_type: isAudio
      ? "audio/L16"
      : path.extname(item.localMediaReference).toLowerCase() === ".webp"
        ? "image/webp"
        : "image/jpeg",
    captured_at: occurredAt,
    duration_ms: actualDurationMs,
    byte_count: fileStats.size,
    sha256: checksum,
    encryption: {
      algorithm: "NONE_TEST_FIXTURE",
      key_ref: null,
      iv_base64: null,
    },
    retention: {
      ttl_expires_at: ttlExpiresAt,
      purpose: "EXPLICIT_DEBUG_SAMPLE",
      debug_sample: true,
    },
    media,
    sensitivity_labels: [],
    extensions: {
      raw_relative_path: path.relative(destination, rawPath),
      source_analysis_state: item.analysisState,
      source_application_state: item.applicationState,
    },
  });
  const attempt = {
    schema_ref: "rme.capture-attempt.v1",
    capture_attempt_id: attemptId,
    capture_window_id: windowId,
    modality,
    requested_at: item.scheduledAt || item.startedAt || occurredAt,
    result: item.outcome && item.outcome !== "SUCCEEDED" ? "FAILED" : "SUCCEEDED",
    reason_code: null,
    latency_ms: item.captureLatencyMilliseconds || 0,
    evidence_item_id: evidenceId,
    runtime_version: "ios-cxrl-legacy",
    extensions: {
      original_trigger: item.trigger,
    },
  };
  captureAttempts.push(attempt);
  attemptsByEvidence.set(evidenceId, attemptId);
}

function addAttemptWithoutEvidence(item, modality) {
  const { windowId } = ensureLegacyWindow(item, modality);
  const sourceOutcome = String(item.outcome || "FAILED").toUpperCase();
  captureAttempts.push({
    schema_ref: "rme.capture-attempt.v1",
    capture_attempt_id: makeId("att", item.id),
    capture_window_id: windowId,
    modality,
    requested_at: item.scheduledAt || item.startedAt || item.completedAt,
    result: ["FAILED", "SKIPPED", "CANCELLED"].includes(sourceOutcome)
      ? sourceOutcome
      : "FAILED",
    reason_code: "LEGACY_REASON_UNKNOWN",
    latency_ms: item.captureLatencyMilliseconds || 0,
    evidence_item_id: null,
    runtime_version: "ios-cxrl-legacy",
    extensions: {
      original_trigger: item.trigger,
      original_outcome: item.outcome,
      original_analysis_state: item.analysisState || null,
    },
  });
}

for (const image of session.observations || []) {
  if (image.localMediaReference) {
    await addMediaEvidence(image, "IMAGE");
  } else {
    addAttemptWithoutEvidence(image, "IMAGE");
  }
}
for (const audio of session.audioObservations || []) {
  if (audio.localMediaReference) {
    await addMediaEvidence(audio, "AUDIO");
  } else {
    addAttemptWithoutEvidence(audio, "AUDIO");
  }
}

if (ringBatches.length > 0) {
  const allSamples = ringBatches.flatMap((batch) => batch.samples || []);
  const firstSample = allSamples[0];
  const lastSample = allSamples.at(-1);
  const firstBatch = ringBatches[0];
  const lastBatch = ringBatches.at(-1);
  const intentId = makeId("cin", `${session.id}sensor`);
  const windowId = makeId("win", `${session.id}sensor`);
  const evidenceId = makeId("evd", `${session.id}sensor`);
  const envelopeId = makeId("src", `${session.id}sensor`);
  const rawRelativePath = "raw/ring/imu.ndjson";
  const rawSensorPath = path.join(destination, rawRelativePath);
  const startDeviceMs = firstSample.timestampMilliseconds;
  const endDeviceMs = lastSample.timestampMilliseconds;
  captureIntents.push({
    schema_ref: "rme.capture-intent.v1",
    capture_intent_id: intentId,
    capture_session_id: sessionId,
    signal_kind: "DEBUG_TEST",
    occurred_at: firstBatch.receivedAt,
    monotonic_start_ns: startDeviceMs * 1_000_000,
    monotonic_end_ns: endDeviceMs * 1_000_000,
    detector_rule_version: "legacy-session-sensor-stream/1.0",
    intensity: "LOW",
    metrics: {
      batch_count: ringBatches.length,
      sample_count: allSamples.length,
    },
    requested_modalities: ["SENSOR"],
    extensions: {
      sensor_source: "EXTERNAL_RING_FIXED_TO_GLASSES",
    },
  });
  captureWindows.push({
    schema_ref: "rme.capture-window.v1",
    capture_window_id: windowId,
    capture_session_id: sessionId,
    capture_intent_id: intentId,
    window_start: firstBatch.receivedAt,
    window_end: lastBatch.receivedAt,
    monotonic_start_ns: startDeviceMs * 1_000_000,
    monotonic_end_ns: endDeviceMs * 1_000_000,
    requested_modalities: ["SENSOR"],
    policy_snapshot_id: policyId,
    state: "FINALIZED",
    extensions: {
      device_time_start_ms: startDeviceMs,
      device_time_end_ms: endDeviceMs,
    },
  });
  sourceEnvelopes.push({
    schema_ref: "rme.source-envelope.v1",
    source_envelope_id: envelopeId,
    device_id: makeId("ring", session.ringSensor?.deviceID || "unknown"),
    device_kind: "RING_SOUND_IMU",
    device_adapter: "ring-sound-ios-legacy-fixture/1.0",
    capture_session_id: sessionId,
    capture_window_id: windowId,
    capture_intent_id: intentId,
    occurred_at: firstBatch.receivedAt,
    observed_at: lastBatch.receivedAt,
    monotonic_start_ns: startDeviceMs * 1_000_000,
    monotonic_end_ns: endDeviceMs * 1_000_000,
    clock_domain: "RING_DEVICE_MILLISECONDS",
    clock_sync_method: "BATCH_RECEIVE_TIME_BACKFILL",
    time_uncertainty_ms: 300,
    policy_snapshot_id: policyId,
    modality: "SENSOR",
    payload_kind: "EVIDENCE_ITEM",
    payload_ref: evidenceId,
    idempotency_key: evidenceId,
    extensions: {
      mount_position: "GLASSES_MOUNTED_EXTERNAL_RING",
      source_batch_schema: "rme.ring-imu-batch.v1",
    },
  });
  sourceEnvelopeIds.push(envelopeId);
  evidenceItems.push({
    schema_ref: "rme.evidence-item.v1",
    evidence_item_id: evidenceId,
    source_envelope_id: envelopeId,
    capture_window_id: windowId,
    modality: "SENSOR",
    mime_type: "application/x-ndjson",
    captured_at: firstBatch.receivedAt,
    duration_ms: Math.max(0, endDeviceMs - startDeviceMs),
    byte_count: (await stat(rawSensorPath)).size,
    sha256: await sha256(rawSensorPath),
    encryption: {
      algorithm: "NONE_TEST_FIXTURE",
      key_ref: null,
      iv_base64: null,
    },
    retention: {
      ttl_expires_at: ttlExpiresAt,
      purpose: "EXPLICIT_DEBUG_SAMPLE",
      debug_sample: true,
    },
    media: {
      format: "RME_RING_IMU_BATCH_NDJSON_V1",
      sensor_types: ["ACCELEROMETER", "GYROSCOPE"],
      coordinate_frame: "LEGACY_RING_DEVICE_FRAME_UNCALIBRATED",
      mount_position: "GLASSES_MOUNTED_EXTERNAL_RING",
      units: {
        accelerometer: "RAW_INT16",
        gyroscope: "RAW_INT16",
      },
      sample_rate_hz: session.ringSensor?.sampleRateHz || null,
      accel_range_g: session.ringSensor?.accelRangeG || null,
      gyro_range_dps: session.ringSensor?.gyroRangeDPS || null,
      actual_sample_count: allSamples.length,
      batch_count: ringBatches.length,
      calibration_profile: "glasses-frame-v1-fixed-orientation",
    },
    sensitivity_labels: [],
    extensions: {
      raw_relative_path: rawRelativePath,
    },
  });
  captureAttempts.push({
    schema_ref: "rme.capture-attempt.v1",
    capture_attempt_id: makeId("att", `${session.id}sensor`),
    capture_window_id: windowId,
    modality: "SENSOR",
    requested_at: firstBatch.receivedAt,
    result: "SUCCEEDED",
    reason_code: null,
    latency_ms: 0,
    evidence_item_id: evidenceId,
    runtime_version: "ios-ring-legacy",
    extensions: {},
  });
}

await writeJson(path.join(normalizedDir, "capture-session.json"), normalizedSession);
await writeNdjson(path.join(normalizedDir, "capture-intents.ndjson"), captureIntents);
await writeNdjson(path.join(normalizedDir, "capture-windows.ndjson"), captureWindows);
await writeNdjson(path.join(normalizedDir, "capture-attempts.ndjson"), captureAttempts);
await writeNdjson(path.join(normalizedDir, "source-envelopes.ndjson"), sourceEnvelopes);
await writeNdjson(path.join(normalizedDir, "evidence-items.ndjson"), evidenceItems);

const manifest = {
  schemaVersion: "rme.test-fixture.v2",
  datasetId,
  title,
  createdAt: new Date().toISOString(),
  approvedForRepositoryTestFixture: true,
  source: {
    chain: "Rokid glasses -> CXR-L iOS app; external ring fixed to glasses -> BLE iOS app",
    originalSessionId: session.id,
    originalSessionSchema: session.schemaVersion,
    originalState: session.state,
  },
  counts: {
    images: evidenceItems.filter((item) => item.modality === "IMAGE").length,
    audioSegments: evidenceItems.filter((item) => item.modality === "AUDIO").length,
    sensorEvidence: evidenceItems.filter((item) => item.modality === "SENSOR").length,
    captureAttempts: captureAttempts.length,
    failedOrSkippedAttempts: captureAttempts.filter((item) => item.result !== "SUCCEEDED").length,
    ringSamples: session.ringSampleCount || 0,
    motionDecisions: (session.ringMotionAssessments || []).length,
    captureWindows: captureWindows.length,
  },
  contract: {
    documentation: "docs/engineering/RealGit-Multimodal-Data-Contract-v1.0.md",
    schemas: "contracts/reality-memory/v1/",
  },
  limitations: [
    "This is legacy iOS/CXR-L data, not Rokid native Android capture.",
    "Media wall-clock timestamps have no recorded monotonic timestamp; normalized values are null.",
    "Ring device time and iOS receive time are both preserved and are not treated as exact hardware synchronization.",
    "Raw fixture files are intentionally unencrypted and must never enter the production ingestion namespace.",
    "Audio duration_ms is derived from PCM byte count; the original requested capture duration remains in media metadata.",
  ],
};
await writeJson(path.join(destination, "manifest.json"), manifest);

const readme = `# ${title}

本数据集来自真实真机采集，包含原始导出和按 RealGit v1 契约转换后的输入。

- \`raw/\`：手机 App 原始 \`session.json\`、媒体和戒指批次 NDJSON，不改写。
- \`normalized/\`：采集会话、采集意图、采集窗口、采集尝试、来源信封和证据元数据。
- \`manifest.json\`：来源、计数、限制与契约位置。

这不是 Rokid 原生 Android 数据。它的价值是验证多模态时间关联、历史数据兼容、
图片重复筛选、PCM 时长校验和后端结构化管线。生产接入必须拒绝
\`NONE_TEST_FIXTURE\` 加密类型。
`;
await writeFile(path.join(destination, "README.md"), readme);
console.log(destination);

async function sha256(filePath) {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

async function writeJson(filePath, value) {
  await writeFile(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

async function writeNdjson(filePath, values) {
  await writeFile(filePath, `${values.map((value) => JSON.stringify(value)).join("\n")}\n`);
}
