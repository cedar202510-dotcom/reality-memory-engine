package com.realitymemory.glasses.evidence

import android.os.Handler
import android.os.Looper
import com.realitymemory.glasses.BuildConfig
import org.json.JSONObject
import java.io.BufferedOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Debug APK 的受控明文联调上传器。
 *
 * 默认目标是 adb reverse 映射后的电脑 localhost；Release 构建不会启用。
 */
class DebugBackendUploader(
    private val repository: EvidenceRepository,
) {
    private val executor = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private val sweepRunning = AtomicBoolean(false)

    private val periodicSweep = object : Runnable {
        override fun run() {
            enqueue()
            handler.postDelayed(this, RETRY_INTERVAL_MS)
        }
    }

    fun start() {
        if (!enabled()) return
        handler.removeCallbacks(periodicSweep)
        handler.post(periodicSweep)
    }

    fun enqueue() {
        if (!enabled() || !sweepRunning.compareAndSet(false, true)) return
        executor.execute {
            try {
                pendingCandidates().forEach(::upload)
            } finally {
                sweepRunning.set(false)
            }
        }
    }

    fun shutdown() {
        handler.removeCallbacksAndMessages(null)
        executor.shutdown()
    }

    private fun enabled(): Boolean =
        BuildConfig.DEBUG_DEVICE_UPLOAD_ENABLED &&
            BuildConfig.DEBUG_BACKEND_BASE_URL.isNotBlank()

    private fun pendingCandidates(): List<UploadCandidate> {
        return repository.outboxDirectory()
            .walkTopDown()
            .filter { it.isFile && it.name.endsWith(".evidence.json") }
            .mapNotNull(::candidateFor)
            .filter { shouldAttempt(it.uploadState) }
            .sortedBy { it.evidenceFile.lastModified() }
            .toList()
    }

    private fun candidateFor(evidenceFile: File): UploadCandidate? {
        val evidence = runCatching { JSONObject(evidenceFile.readText()) }.getOrNull() ?: return null
        val evidenceId = evidence.optString("evidence_item_id")
        val sourceId = evidence.optString("source_envelope_id")
        val windowId = evidence.optString("capture_window_id")
        if (evidenceId.isBlank() || sourceId.isBlank() || windowId.isBlank()) return null
        val windowDirectory = evidenceFile.parentFile ?: return null
        val sourceFile = File(windowDirectory, "$sourceId.source.json").takeIf(File::exists) ?: return null
        val captureIntentFile = File(windowDirectory, "capture-intent.json").takeIf(File::exists)
        val captureWindowFile = File(windowDirectory, "capture-window.json").takeIf(File::exists)
        val windowState = captureWindowFile
            ?.let { runCatching { JSONObject(it.readText()).optString("state") }.getOrNull() }
        if (windowState != "FINALIZED") return null
        val sessionId = windowDirectory.parentFile?.name ?: return null
        val plaintextDirectory = File(repository.debugExportDirectory(), sessionId)
        val plaintext = plaintextDirectory.listFiles()
            ?.firstOrNull { it.name.startsWith("$windowId-$evidenceId.") }
            ?: return null
        return UploadCandidate(
            evidenceFile = evidenceFile,
            sourceFile = sourceFile,
            captureIntentFile = captureIntentFile,
            captureWindowFile = captureWindowFile,
            plaintextFile = plaintext,
            uploadState = File(windowDirectory, "$evidenceId.upload.json"),
            evidenceId = evidenceId,
            windowId = windowId,
            mimeType = evidence.optString("mime_type", "application/octet-stream"),
        )
    }

    private fun upload(candidate: UploadCandidate) {
        val attempts = previousAttempts(candidate.uploadState) + 1
        val result = runCatching { post(candidate) }
        result.onSuccess { response ->
            writeState(
                candidate.uploadState,
                JSONObject()
                    .put("state", "UPLOADED")
                    .put("attempt_count", attempts)
                    .put("uploaded_at", Instant.now().toString())
                    .put("endpoint", endpoint())
                    .put("http_status", response.status)
                    .put("response", response.body.take(MAX_RESPONSE_CHARS)),
            )
            repository.appendRuntimeAudit(
                "EVIDENCE_UPLOAD_SUCCEEDED",
                JSONObject()
                    .put("evidence_item_id", candidate.evidenceId)
                    .put("capture_window_id", candidate.windowId)
                    .put("http_status", response.status),
            )
        }.onFailure { error ->
            writeState(
                candidate.uploadState,
                JSONObject()
                    .put("state", "RETRY_PENDING")
                    .put("attempt_count", attempts)
                    .put("last_attempt_at", Instant.now().toString())
                    .put("endpoint", endpoint())
                    .put("last_error", describe(error)),
            )
            repository.appendRuntimeAudit(
                "EVIDENCE_UPLOAD_FAILED",
                JSONObject()
                    .put("evidence_item_id", candidate.evidenceId)
                    .put("capture_window_id", candidate.windowId)
                    .put("attempt_count", attempts)
                    .put("error", describe(error)),
            )
        }
    }

    private fun post(candidate: UploadCandidate): UploadResponse {
        val boundary = "rme-${UUID.randomUUID()}"
        val textParts = buildList {
            add(textPartBytes(boundary, "source_envelope", candidate.sourceFile.readText()))
            add(textPartBytes(boundary, "evidence_item", candidate.evidenceFile.readText()))
            candidate.captureIntentFile?.let {
                add(textPartBytes(boundary, "capture_intent", it.readText()))
            }
            candidate.captureWindowFile?.let {
                add(textPartBytes(boundary, "capture_window", it.readText()))
            }
        }
        val fileHeader = filePartHeaderBytes(boundary, candidate)
        val lineEnding = "\r\n".toByteArray(StandardCharsets.UTF_8)
        val closingBoundary = "--$boundary--\r\n".toByteArray(StandardCharsets.UTF_8)
        val contentLength =
            textParts.sumOf { it.size.toLong() } +
                fileHeader.size +
                candidate.plaintextFile.length() +
                lineEnding.size +
                closingBoundary.size
        val connection = URL(endpoint()).openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.doOutput = true
        connection.connectTimeout = CONNECT_TIMEOUT_MS
        connection.readTimeout = READ_TIMEOUT_MS
        connection.setFixedLengthStreamingMode(contentLength)
        connection.setRequestProperty("Accept", "application/json")
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        try {
            BufferedOutputStream(connection.outputStream).use { output ->
                textParts.forEach(output::write)
                output.write(fileHeader)
                candidate.plaintextFile.inputStream().use { it.copyTo(output) }
                output.write(lineEnding)
                output.write(closingBoundary)
            }

            val status = connection.responseCode
            val responseStream =
                if (status in 200..299) connection.inputStream else connection.errorStream
            val body = responseStream?.bufferedReader()?.use { it.readText() }.orEmpty()
            check(status in 200..299) { "HTTP $status: ${body.take(MAX_RESPONSE_CHARS)}" }
            return UploadResponse(status, body)
        } finally {
            connection.disconnect()
        }
    }

    private fun textPartBytes(
        boundary: String,
        name: String,
        value: String,
    ): ByteArray =
        buildString {
            append("--").append(boundary).append("\r\n")
            append("Content-Disposition: form-data; name=\"").append(name).append("\"\r\n")
            append("Content-Type: application/json; charset=utf-8\r\n\r\n")
            append(value).append("\r\n")
        }.toByteArray(StandardCharsets.UTF_8)

    private fun filePartHeaderBytes(
        boundary: String,
        candidate: UploadCandidate,
    ): ByteArray =
        buildString {
            append("--").append(boundary).append("\r\n")
            append("Content-Disposition: form-data; name=\"file\"; filename=\"")
            append(candidate.plaintextFile.name).append("\"\r\n")
            append("Content-Type: ").append(candidate.mimeType).append("\r\n\r\n")
        }.toByteArray(StandardCharsets.UTF_8)

    private fun endpoint(): String =
        "${BuildConfig.DEBUG_BACKEND_BASE_URL.trimEnd('/')}/internal/v1/device-evidence"

    private fun shouldAttempt(file: File): Boolean {
        if (!file.exists()) return true
        return runCatching {
            val state = JSONObject(file.readText())
            if (state.optString("state") == "UPLOADED") return@runCatching false
            val attempts = state.optInt("attempt_count", 0).coerceAtLeast(0)
            val lastAttempt = state.optString("last_attempt_at")
                .takeIf(String::isNotBlank)
                ?.let(Instant::parse)
                ?: return@runCatching true
            val multiplier = 1L shl (attempts - 1).coerceIn(0, MAX_BACKOFF_SHIFT)
            !Instant.now().isBefore(lastAttempt.plusSeconds(RETRY_INTERVAL_SECONDS * multiplier))
        }.getOrDefault(true)
    }

    private fun previousAttempts(file: File): Int =
        runCatching { JSONObject(file.readText()).optInt("attempt_count", 0) }.getOrDefault(0)

    private fun writeState(file: File, value: JSONObject) {
        val temporary = File(file.parentFile, "${file.name}.tmp")
        temporary.writeText(value.toString(2))
        if (!temporary.renameTo(file)) {
            temporary.copyTo(file, overwrite = true)
            temporary.delete()
        }
    }

    private fun describe(error: Throwable): String =
        "${error.javaClass.simpleName}: ${error.message}"

    private data class UploadCandidate(
        val evidenceFile: File,
        val sourceFile: File,
        val captureIntentFile: File?,
        val captureWindowFile: File?,
        val plaintextFile: File,
        val uploadState: File,
        val evidenceId: String,
        val windowId: String,
        val mimeType: String,
    )

    private data class UploadResponse(val status: Int, val body: String)

    companion object {
        private const val RETRY_INTERVAL_MS = 15_000L
        private const val RETRY_INTERVAL_SECONDS = 15L
        private const val MAX_BACKOFF_SHIFT = 4
        private const val CONNECT_TIMEOUT_MS = 5_000
        private const val READ_TIMEOUT_MS = 30_000
        private const val MAX_RESPONSE_CHARS = 2_000
    }
}
