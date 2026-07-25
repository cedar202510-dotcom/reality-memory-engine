package com.realitymemory.glasses.evidence

import android.content.Context
import android.os.SystemClock
import com.realitymemory.glasses.BuildConfig
import com.realitymemory.glasses.runtime.CaptureModality
import com.realitymemory.glasses.runtime.CaptureWindowContext
import com.realitymemory.glasses.runtime.MotionTrigger
import com.realitymemory.glasses.runtime.SessionState
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.security.MessageDigest
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.UUID

class EvidenceRepository(private val context: Context) {
    private val cryptoBox = CryptoBox()
    private val root = File(context.filesDir, "reality-memory")
    private val outbox = File(root, "outbox")
    private val debugExport = File(root, "debug-export")
    private val auditFile = File(root, "audit.ndjson")
    private val debugManifestFile = File(debugExport, "manifest.ndjson")
    private val preferences = context.getSharedPreferences("reality_device", Context.MODE_PRIVATE)
    private var evidenceReadyListener: (() -> Unit)? = null

    val deviceId: String = preferences.getString("device_id", null)
        ?: id("glass").also { preferences.edit().putString("device_id", it).apply() }

    var activeSessionId: String? = null
        private set

    var recoveredInterruptedSessionCount: Int = 0
        private set

    init {
        outbox.mkdirs()
        recoverInterruptedSessions()
    }

    fun setEvidenceReadyListener(listener: (() -> Unit)?) {
        evidenceReadyListener = listener
    }

    private fun recoverInterruptedSessions() {
        outbox.listFiles()
            ?.filter { it.isDirectory }
            ?.forEach { directory ->
                val sessionFile = File(directory, "capture-session.json")
                if (!sessionFile.exists()) return@forEach
                runCatching {
                    val session = JSONObject(sessionFile.readText())
                    val previousState = session.optString("state")
                    if (
                        previousState != SessionState.ACTIVE.name &&
                        previousState != SessionState.DISCLOSURE.name
                    ) {
                        return@runCatching
                    }
                    val recoveredAt = Instant.now()
                    val extensions =
                        session.optJSONObject("extensions") ?: JSONObject()
                    extensions
                        .put("interrupted_state", previousState)
                        .put("recovered_at", recoveredAt.toString())
                    session
                        .put("state", SessionState.ENDED.name)
                        .put("ended_at", recoveredAt.toString())
                        .put("ended_monotonic_ns", SystemClock.elapsedRealtimeNanos())
                        .put("end_reason", INTERRUPTED_SESSION_RECOVERED)
                        .put("extensions", extensions)
                    writeObject(directory, "capture-session.json", session)
                    recoveredInterruptedSessionCount += 1
                    appendAudit(
                        "STALE_SESSION_RECOVERED",
                        JSONObject()
                            .put(
                                "capture_session_id",
                                session.optString("capture_session_id", directory.name),
                            )
                            .put("previous_state", previousState)
                            .put("end_reason", INTERRUPTED_SESSION_RECOVERED),
                    )
                }.onFailure { error ->
                    appendAudit(
                        "STALE_SESSION_RECOVERY_FAILED",
                        JSONObject()
                            .put("capture_session_id", directory.name)
                            .put("error", error.message ?: error.javaClass.simpleName),
                    )
                }
            }
    }

    @Synchronized
    fun openSession(startReason: String): String {
        activeSessionId?.let { return it }
        val sessionId = id("ses")
        activeSessionId = sessionId
        val now = Instant.now()
        writeObject(
            sessionDir(sessionId),
            "capture-session.json",
            JSONObject()
                .put("schema_ref", "rme.capture-session.v1")
                .put("capture_session_id", sessionId)
                .put("device_id", deviceId)
                .put("state", SessionState.DISCLOSURE.name)
                .put("started_at", now.toString())
                .put("started_monotonic_ns", SystemClock.elapsedRealtimeNanos())
                .put("ended_at", JSONObject.NULL)
                .put("ended_monotonic_ns", JSONObject.NULL)
                .put("start_reason", startReason)
                .put("end_reason", JSONObject.NULL)
                .put("policy_snapshot_id", POLICY_ID)
                .put("consent_notice_version", "wear-notice/1.0")
                .put("runtime_version", BuildConfig.RUNTIME_VERSION)
                .put("extensions", JSONObject().put("phase", "DEVICE_VALIDATION")),
        )
        appendAudit("SESSION_OPENED", JSONObject().put("capture_session_id", sessionId))
        return sessionId
    }

    @Synchronized
    fun updateSessionState(state: SessionState, endReason: String? = null) {
        val sessionId = activeSessionId ?: return
        val file = File(sessionDir(sessionId), "capture-session.json")
        if (!file.exists()) return
        val json = JSONObject(file.readText())
            .put("state", state.name)
            .put("end_reason", endReason ?: JSONObject.NULL)
        if (state == SessionState.ENDED) {
            json.put("ended_at", Instant.now().toString())
            json.put("ended_monotonic_ns", SystemClock.elapsedRealtimeNanos())
        }
        writeObject(sessionDir(sessionId), "capture-session.json", json)
        appendAudit(
            "SESSION_STATE_CHANGED",
            JSONObject().put("capture_session_id", sessionId).put("state", state.name),
        )
        if (state == SessionState.ENDED) activeSessionId = null
    }

    @Synchronized
    fun beginWindow(
        signalKind: String,
        requestedModalities: Set<CaptureModality>,
        motion: MotionTrigger? = null,
    ): CaptureWindowContext {
        val sessionId = requireNotNull(activeSessionId) { "No active capture session" }
        val now = Instant.now()
        val monotonicNow = SystemClock.elapsedRealtimeNanos()
        val intentId = id("cin")
        val windowId = id("win")
        val context = CaptureWindowContext(
            captureSessionId = sessionId,
            captureIntentId = intentId,
            captureWindowId = windowId,
            signalKind = signalKind,
            startedAtEpochMs = now.toEpochMilli(),
            monotonicStartNs = motion?.monotonicStartNs ?: monotonicNow,
            requestedModalities = requestedModalities,
        )
        val metrics = JSONObject()
        if (motion == null) {
            metrics.put("source", signalKind)
        } else {
            metrics
                .put("duration_ms", motion.durationMs)
                .put("peak_gyro_rad_s", motion.peakGyroRadS)
                .put("integrated_rotation_deg", motion.integratedRotationDeg)
                .put("max_linear_acceleration_m_s2", motion.maxLinearAcceleration)
        }
        val intent = JSONObject()
            .put("schema_ref", "rme.capture-intent.v1")
            .put("capture_intent_id", intentId)
            .put("capture_session_id", sessionId)
            .put("signal_kind", signalKind)
            .put("occurred_at", Instant.ofEpochMilli(motion?.occurredAtEpochMs ?: now.toEpochMilli()).toString())
            .put("monotonic_start_ns", motion?.monotonicStartNs ?: monotonicNow)
            .put("monotonic_end_ns", motion?.monotonicEndNs ?: monotonicNow)
            .put(
                "detector_rule_version",
                if (motion == null) "explicit-or-schedule.v1" else "glasses-head-transition.v1",
            )
            .put("intensity", motion?.intensity ?: "LOW")
            .put("metrics", metrics)
            .put("requested_modalities", modalityArray(requestedModalities))
            .put("extensions", JSONObject())
        writeObject(windowDir(context), "capture-intent.json", intent)

        val expectedEndMs = now.plus(WINDOW_DURATION_SECONDS, ChronoUnit.SECONDS)
        val window = JSONObject()
            .put("schema_ref", "rme.capture-window.v1")
            .put("capture_window_id", windowId)
            .put("capture_session_id", sessionId)
            .put("capture_intent_id", intentId)
            .put("window_start", now.toString())
            .put("window_end", expectedEndMs.toString())
            .put("monotonic_start_ns", context.monotonicStartNs)
            .put("monotonic_end_ns", monotonicNow + WINDOW_DURATION_SECONDS * 1_000_000_000L)
            .put("requested_modalities", modalityArray(requestedModalities))
            .put("policy_snapshot_id", POLICY_ID)
            .put("state", "OPEN")
            .put("extensions", JSONObject())
        writeObject(windowDir(context), "capture-window.json", window)
        appendAudit("CAPTURE_WINDOW_OPENED", JSONObject().put("capture_window_id", windowId))
        return context
    }

    @Synchronized
    fun finalizeWindow(window: CaptureWindowContext, state: String = "FINALIZED") {
        val file = File(windowDir(window), "capture-window.json")
        if (!file.exists()) return
        val json = JSONObject(file.readText())
            .put("window_end", Instant.now().toString())
            .put("monotonic_end_ns", SystemClock.elapsedRealtimeNanos())
            .put("state", state)
        writeObject(windowDir(window), "capture-window.json", json)
        evidenceReadyListener?.invoke()
    }

    @Synchronized
    fun finalizeEvidence(
        window: CaptureWindowContext,
        modality: CaptureModality,
        sourceFile: File,
        mimeType: String,
        capturedAt: Instant,
        durationMs: Long,
        media: JSONObject,
        monotonicStartNs: Long = window.monotonicStartNs,
        monotonicEndNs: Long = SystemClock.elapsedRealtimeNanos(),
        sensitivityLabels: List<String> = emptyList(),
    ): String {
        val evidenceId = id("evd")
        val sourceId = id("src")
        val plaintextByteCount = sourceFile.length()
        val plaintextSha256 = sha256(sourceFile)
        if (BuildConfig.DEBUG_PLAINTEXT_FIXTURE_EXPORT) {
            saveDebugFixture(
                sourceFile = sourceFile,
                window = window,
                evidenceId = evidenceId,
                modality = modality,
                mimeType = mimeType,
                capturedAt = capturedAt,
                durationMs = durationMs,
            )
        }
        val encrypted = cryptoBox.encrypt(
            sourceFile,
            File(windowDir(window), "$evidenceId.bin.enc"),
        )
        sourceFile.delete()

        val evidence = JSONObject()
            .put("schema_ref", "rme.evidence-item.v1")
            .put("evidence_item_id", evidenceId)
            .put("source_envelope_id", sourceId)
            .put("capture_window_id", window.captureWindowId)
            .put("modality", modality.name)
            .put("mime_type", mimeType)
            .put("captured_at", capturedAt.toString())
            .put("duration_ms", durationMs.coerceAtLeast(0))
            .put("byte_count", plaintextByteCount)
            .put("sha256", plaintextSha256)
            .put(
                "encryption",
                JSONObject()
                    .put("algorithm", "AES_256_GCM")
                    .put("key_ref", CryptoBox.KEY_ALIAS)
                    .put("iv_base64", encrypted.ivBase64),
            )
            .put(
                "retention",
                JSONObject()
                    .put("ttl_expires_at", capturedAt.plus(24, ChronoUnit.HOURS).toString())
                    .put("purpose", "STRUCTURE_EXTRACTION")
                    .put("debug_sample", false),
            )
            .put("media", media)
            .put("sensitivity_labels", JSONArray(sensitivityLabels))
            .put(
                "extensions",
                JSONObject()
                    .put("local_ciphertext_name", encrypted.file.name)
                    .put("ciphertext_byte_count", encrypted.byteCount)
                    .put("ciphertext_sha256", encrypted.sha256),
            )
        writeObject(windowDir(window), "$evidenceId.evidence.json", evidence)

        val sourceEnvelope = JSONObject()
            .put("schema_ref", "rme.source-envelope.v1")
            .put("source_envelope_id", sourceId)
            .put("device_id", deviceId)
            .put("device_kind", "ROKID_GLASSES_RV101")
            .put("device_adapter", "rokid-native-android/1.0")
            .put("capture_session_id", window.captureSessionId)
            .put("capture_window_id", window.captureWindowId)
            .put("capture_intent_id", window.captureIntentId)
            .put("occurred_at", capturedAt.toString())
            .put("observed_at", Instant.now().toString())
            .put("monotonic_start_ns", monotonicStartNs)
            .put("monotonic_end_ns", monotonicEndNs)
            .put("clock_domain", "ANDROID_ELAPSED_REALTIME_NANOS")
            .put("clock_sync_method", "ANDROID_SYSTEM_CLOCK_ANCHOR")
            .put("time_uncertainty_ms", 50)
            .put("policy_snapshot_id", POLICY_ID)
            .put("modality", modality.name)
            .put("payload_kind", "EVIDENCE_ITEM")
            .put("payload_ref", evidenceId)
            .put("idempotency_key", evidenceId)
            .put("extensions", JSONObject().put("runtime_version", BuildConfig.RUNTIME_VERSION))
        writeObject(windowDir(window), "$sourceId.source.json", sourceEnvelope)
        appendAudit(
            "EVIDENCE_ENQUEUED",
            JSONObject()
                .put("capture_window_id", window.captureWindowId)
                .put("evidence_item_id", evidenceId)
                .put("modality", modality.name),
        )
        return evidenceId
    }

    @Synchronized
    fun recordAttempt(
        window: CaptureWindowContext,
        modality: CaptureModality,
        requestedAt: Instant,
        result: String,
        reasonCode: String?,
        latencyMs: Long,
        evidenceItemId: String?,
    ) {
        val attemptId = id("att")
        val json = JSONObject()
            .put("schema_ref", "rme.capture-attempt.v1")
            .put("capture_attempt_id", attemptId)
            .put("capture_window_id", window.captureWindowId)
            .put("modality", modality.name)
            .put("requested_at", requestedAt.toString())
            .put("result", result)
            .put("reason_code", reasonCode ?: JSONObject.NULL)
            .put("latency_ms", latencyMs.coerceAtLeast(0))
            .put("evidence_item_id", evidenceItemId ?: JSONObject.NULL)
            .put("runtime_version", BuildConfig.RUNTIME_VERSION)
            .put("extensions", JSONObject())
        writeObject(windowDir(window), "$attemptId.attempt.json", json)
    }

    fun newTemporaryFile(extension: String): File {
        val directory = File(context.cacheDir, "capture").apply { mkdirs() }
        return File(directory, "${UUID.randomUUID()}.$extension")
    }

    fun newExternalTemporaryFile(extension: String): File {
        val root = context.getExternalFilesDir("vendor-recording") ?: context.cacheDir
        val directory = File(root, "capture").apply { mkdirs() }
        return File(directory, "${UUID.randomUUID()}.$extension")
    }

    fun outboxPath(): String = outbox.absolutePath

    internal fun outboxDirectory(): File = outbox

    internal fun debugExportDirectory(): File = debugExport

    internal fun appendRuntimeAudit(event: String, detail: JSONObject) {
        appendAudit(event, detail)
    }

    private fun sessionDir(sessionId: String) = File(outbox, sessionId).apply { mkdirs() }

    private fun windowDir(window: CaptureWindowContext) =
        File(sessionDir(window.captureSessionId), window.captureWindowId).apply { mkdirs() }

    private fun modalityArray(values: Set<CaptureModality>) =
        JSONArray().apply { values.forEach { put(it.name) } }

    private fun writeObject(directory: File, name: String, json: JSONObject) {
        directory.mkdirs()
        val destination = File(directory, name)
        val temporary = File(directory, "$name.tmp")
        temporary.writeText(json.toString(2))
        if (!temporary.renameTo(destination)) {
            temporary.copyTo(destination, overwrite = true)
            temporary.delete()
        }
    }

    private fun appendAudit(event: String, detail: JSONObject) {
        auditFile.parentFile?.mkdirs()
        val record = JSONObject()
            .put("event", event)
            .put("occurred_at", Instant.now().toString())
            .put("monotonic_ns", SystemClock.elapsedRealtimeNanos())
            .put("detail", detail)
        FileOutputStream(auditFile, true).bufferedWriter().use {
            it.append(record.toString()).append('\n')
        }
    }

    private fun saveDebugFixture(
        sourceFile: File,
        window: CaptureWindowContext,
        evidenceId: String,
        modality: CaptureModality,
        mimeType: String,
        capturedAt: Instant,
        durationMs: Long,
    ) {
        debugExport.mkdirs()
        pruneDebugFixtures(sourceFile.length())
        val extension = when (modality) {
            CaptureModality.IMAGE -> "jpg"
            CaptureModality.VIDEO -> "mp4"
            CaptureModality.AUDIO -> "pcm"
            CaptureModality.SENSOR -> "ndjson"
        }
        val destination = File(
            File(debugExport, window.captureSessionId).apply { mkdirs() },
            "${window.captureWindowId}-$evidenceId.$extension",
        )
        sourceFile.copyTo(destination, overwrite = true)
        val record = JSONObject()
            .put("evidence_item_id", evidenceId)
            .put("capture_session_id", window.captureSessionId)
            .put("capture_window_id", window.captureWindowId)
            .put("modality", modality.name)
            .put("mime_type", mimeType)
            .put("captured_at", capturedAt.toString())
            .put("duration_ms", durationMs)
            .put("byte_count", destination.length())
            .put("relative_path", destination.relativeTo(debugExport).path)
            .put("authorization_scope", "CONTROLLED_RV101_DEBUG_FIXTURE")
            .put("ttl_expires_at", capturedAt.plus(24, ChronoUnit.HOURS).toString())
        FileOutputStream(debugManifestFile, true).bufferedWriter().use {
            it.append(record.toString()).append('\n')
        }
    }

    private fun pruneDebugFixtures(incomingBytes: Long) {
        val files = debugExport.walkTopDown()
            .filter { it.isFile && it != debugManifestFile }
            .sortedBy { it.lastModified() }
            .toMutableList()
        var total = files.sumOf { it.length() }
        while (files.isNotEmpty() && total + incomingBytes > DEBUG_EXPORT_BUDGET_BYTES) {
            val oldest = files.removeAt(0)
            total -= oldest.length()
            oldest.delete()
        }
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read < 0) break
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun id(prefix: String) = "${prefix}_${UUID.randomUUID()}"

    companion object {
        const val POLICY_ID = "pol_phase0_local_v1"
        const val INTERRUPTED_SESSION_RECOVERED = "PROCESS_INTERRUPTED_RECOVERED"
        private const val WINDOW_DURATION_SECONDS = 12L
        private const val DEBUG_EXPORT_BUDGET_BYTES = 64L * 1024L * 1024L
    }
}
