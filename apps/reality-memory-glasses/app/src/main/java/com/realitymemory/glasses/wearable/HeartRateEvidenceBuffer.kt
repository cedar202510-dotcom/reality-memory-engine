package com.realitymemory.glasses.wearable

import android.os.Handler
import android.os.Looper
import com.realitymemory.glasses.evidence.EvidenceRepository
import com.realitymemory.glasses.runtime.CaptureModality
import org.json.JSONArray
import org.json.JSONObject
import java.io.FileOutputStream
import java.time.Duration
import java.time.Instant
import java.util.concurrent.Executors

class HeartRateEvidenceBuffer(
    private val repository: EvidenceRepository,
) {
    private val handler = Handler(Looper.getMainLooper())
    private val ioExecutor = Executors.newSingleThreadExecutor()
    private val samples = mutableListOf<HeartRateBroadcastSample>()
    private var active = false
    private var flushScheduled = false

    fun start() {
        active = true
    }

    fun append(sample: HeartRateBroadcastSample) {
        if (!active) return
        samples += sample
        if (!flushScheduled) {
            flushScheduled = true
            handler.postDelayed(::flush, BATCH_DURATION_MS)
        }
        if (samples.size >= MAX_BATCH_SAMPLES) flush()
    }

    fun stop() {
        active = false
        handler.removeCallbacksAndMessages(null)
        flushScheduled = false
        flush()
    }

    fun shutdown() {
        stop()
        ioExecutor.shutdown()
    }

    private fun flush() {
        handler.removeCallbacksAndMessages(null)
        flushScheduled = false
        if (samples.isEmpty()) return
        if (repository.activeSessionId == null) {
            repository.appendRuntimeAudit(
                "HEART_RATE_EVIDENCE_DEFERRED",
                JSONObject()
                    .put("reason", "NO_ACTIVE_CAPTURE_SESSION")
                    .put("sample_count", samples.size),
            )
            samples.clear()
            return
        }
        val batch = samples.toList()
        samples.clear()
        if (active) {
            flushScheduled = true
            handler.postDelayed(::flush, BATCH_DURATION_MS)
        }
        ioExecutor.execute { persist(batch) }
    }

    private fun persist(batch: List<HeartRateBroadcastSample>) {
        val requestedAt = Instant.now()
        val startedNs = System.nanoTime()
        val window = runCatching {
            repository.beginWindow(
                signalKind = "DEBUG_TEST",
                requestedModalities = setOf(CaptureModality.SENSOR),
            )
        }.getOrElse { error ->
            repository.appendRuntimeAudit(
                "HEART_RATE_EVIDENCE_FAILED",
                JSONObject().put("message", error.message ?: error.javaClass.simpleName),
            )
            return
        }
        val file = repository.newTemporaryFile("ndjson")
        runCatching {
            FileOutputStream(file).bufferedWriter().use { output ->
                batch.forEachIndexed { index, sample ->
                    output.append(
                        JSONObject()
                            .put("sequence", index)
                            .put("occurred_at", sample.capturedAt.toString())
                            .put("monotonic_ns", sample.monotonicNs)
                            .put("heart_rate_bpm", sample.bpm)
                            .put("rssi_dbm", sample.rssi ?: JSONObject.NULL)
                            .put("peripheral_name", sample.peripheralName ?: JSONObject.NULL)
                            .put("peripheral_address", sample.peripheralAddress)
                            .put("raw_hex", sample.rawHex)
                            .toString(),
                    ).append('\n')
                }
            }
            val first = batch.first()
            val last = batch.last()
            val durationMs = Duration.between(first.capturedAt, last.capturedAt)
                .toMillis()
                .coerceAtLeast(0)
            val evidenceId = repository.finalizeEvidence(
                window = window,
                modality = CaptureModality.SENSOR,
                sourceFile = file,
                mimeType = "application/x-ndjson",
                capturedAt = first.capturedAt,
                durationMs = durationMs,
                media = JSONObject()
                    .put("format", "NDJSON")
                    .put("sensor_types", JSONArray(listOf("HEART_RATE")))
                    .put("units", JSONObject().put("heart_rate", "BEATS_PER_MINUTE"))
                    .put("sampling_mode", "BLE_GATT_NOTIFICATION")
                    .put("source_standard", "Bluetooth SIG Heart Rate Service 0x180D")
                    .put("characteristic", "Heart Rate Measurement 0x2A37")
                    .put("device_adapter", "ble-heart-rate-service/android-poc")
                    .put("actual_sample_count", batch.size)
                    .put(
                        "peripheral_name",
                        first.peripheralName ?: JSONObject.NULL,
                    )
                    .put("peripheral_address", first.peripheralAddress),
                monotonicStartNs = first.monotonicNs,
                monotonicEndNs = last.monotonicNs,
                sensitivityLabels = listOf("HEALTH_DATA", "WEARABLE_IDENTIFIER"),
            )
            repository.recordAttempt(
                window = window,
                modality = CaptureModality.SENSOR,
                requestedAt = requestedAt,
                result = "SUCCEEDED",
                reasonCode = null,
                latencyMs = (System.nanoTime() - startedNs) / 1_000_000L,
                evidenceItemId = evidenceId,
            )
            repository.finalizeWindow(window)
            repository.appendRuntimeAudit(
                "HEART_RATE_EVIDENCE_SUCCEEDED",
                JSONObject()
                    .put("evidence_item_id", evidenceId)
                    .put("capture_window_id", window.captureWindowId)
                    .put("sample_count", batch.size)
                    .put("first_bpm", first.bpm)
                    .put("last_bpm", last.bpm)
                    .put("duration_ms", durationMs),
            )
        }.onFailure { error ->
            file.delete()
            repository.recordAttempt(
                window = window,
                modality = CaptureModality.SENSOR,
                requestedAt = requestedAt,
                result = "FAILED",
                reasonCode = "HEART_RATE_EVIDENCE_WRITE_FAILED",
                latencyMs = (System.nanoTime() - startedNs) / 1_000_000L,
                evidenceItemId = null,
            )
            repository.finalizeWindow(window, "CANCELLED")
            repository.appendRuntimeAudit(
                "HEART_RATE_EVIDENCE_FAILED",
                JSONObject().put("message", error.message ?: error.javaClass.simpleName),
            )
        }
    }

    companion object {
        private const val BATCH_DURATION_MS = 10_000L
        private const val MAX_BATCH_SAMPLES = 30
    }
}
