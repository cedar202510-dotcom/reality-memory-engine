package com.realitymemory.glasses.downlink

import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import com.realitymemory.glasses.BuildConfig
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * RV101 的第一版下行客户端。
 *
 * 使用后端已有的 inbox + receipt HTTP API，不依赖第三方网络库；WebSocket 会在真机确认
 * 后台网络和功耗后作为低延迟主路径加入。HTTP 与 WebSocket 共用 message_id 幂等语义。
 */
class DeviceDownlinkClient(
    context: Context,
    private val onPresentation: (DownlinkPresentation) -> Unit,
    private val onAudit: (String, JSONObject) -> Unit,
) {
    private val appContext = context.applicationContext
    private val handler = Handler(Looper.getMainLooper())
    private val executor = Executors.newSingleThreadExecutor()
    private val requestRunning = AtomicBoolean(false)
    private val inFlightIds = ConcurrentHashMap.newKeySet<String>()
    private val preferences =
        appContext.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    @Volatile
    private var started = false

    @Volatile
    private var presentationEnabled = false

    @Volatile
    private var backendDeviceId: String? =
        preferences.getString(KEY_BACKEND_DEVICE_ID, null)

    @Volatile
    private var lastConnectionState: String? = null

    private val completedIds = linkedSetOf<String>().apply {
        val saved = preferences.getString(KEY_COMPLETED_IDS, null)
        if (!saved.isNullOrBlank()) {
            runCatching {
                val values = JSONArray(saved)
                repeat(values.length()) { index ->
                    values.optString(index).takeIf(String::isNotBlank)?.let(::add)
                }
            }
        }
    }

    private val periodicPoll = object : Runnable {
        override fun run() {
            enqueuePoll()
        }
    }

    fun start() {
        if (!enabled() || started) return
        started = true
        schedule(0L)
    }

    fun setPresentationEnabled(enabled: Boolean) {
        presentationEnabled = enabled
        if (enabled && started) schedule(0L)
    }

    fun sendReceipt(
        messageId: String,
        status: String,
        detail: JSONObject = JSONObject(),
    ) {
        if (!enabled() || messageId.isBlank()) return
        executor.execute {
            sendReceiptAttempt(messageId, status, detail, attempt = 0)
        }
    }

    fun shutdown() {
        started = false
        handler.removeCallbacksAndMessages(null)
        executor.shutdown()
    }

    private fun enabled(): Boolean =
        BuildConfig.DEBUG_DEVICE_UPLOAD_ENABLED &&
            BuildConfig.DEBUG_BACKEND_BASE_URL.isNotBlank()

    private fun enqueuePoll() {
        if (!started || !requestRunning.compareAndSet(false, true)) return
        executor.execute {
            var success = false
            try {
                ensureRegistered()
                if (presentationEnabled) pollInbox()
                success = true
                reportConnectionState("CONNECTED", null)
            } catch (error: Throwable) {
                reportConnectionState("RETRYING", describe(error))
            } finally {
                requestRunning.set(false)
                schedule(if (success) POLL_INTERVAL_MS else RETRY_INTERVAL_MS)
            }
        }
    }

    private fun schedule(delayMs: Long) {
        if (!started) return
        handler.removeCallbacks(periodicPoll)
        handler.postDelayed(periodicPoll, delayMs)
    }

    private fun ensureRegistered(): String {
        backendDeviceId?.takeIf(String::isNotBlank)?.let { return it }
        val body = JSONObject()
            .put("kind", "glasses")
            .put("name", stableDeviceName())
            .put("runtime_package", BuildConfig.APPLICATION_ID)
            .put("control_transport", "inbox")
        val response = request("POST", "/internal/v1/devices", body)
        val deviceId = response.optString("device_id")
        require(deviceId.isNotBlank()) { "设备注册响应缺少 device_id" }
        backendDeviceId = deviceId
        preferences.edit().putString(KEY_BACKEND_DEVICE_ID, deviceId).apply()
        audit(
            "DOWNLINK_DEVICE_REGISTERED",
            JSONObject()
                .put("backend_device_id", deviceId)
                .put("device_name", stableDeviceName()),
        )
        return deviceId
    }

    private fun pollInbox() {
        var deviceId = ensureRegistered()
        val response = try {
            request(
                "GET",
                "/internal/v1/devices/$deviceId/inbox",
                body = null,
            )
        } catch (error: DownlinkHttpException) {
            if (error.status != HttpURLConnection.HTTP_NOT_FOUND) throw error
            clearBackendDeviceId()
            deviceId = ensureRegistered()
            request(
                "GET",
                "/internal/v1/devices/$deviceId/inbox",
                body = null,
            )
        }
        val messages = response.optJSONArray("messages") ?: JSONArray()
        repeat(messages.length()) { index ->
            val envelope = messages.optJSONObject(index) ?: return@repeat
            val messageId = envelope.optString("message_id")
            if (
                messageId.isBlank() ||
                isCompleted(messageId) ||
                !inFlightIds.add(messageId)
            ) {
                return@repeat
            }
            val parsed = runCatching { parsePresentation(envelope) }
            parsed.onSuccess { presentation ->
                sendReceiptAttempt(
                    messageId,
                    "RECEIVED",
                    JSONObject().put("transport", "HTTP_INBOX"),
                    attempt = 0,
                )
                handler.post { onPresentation(presentation) }
            }.onFailure { error ->
                audit(
                    "DOWNLINK_MESSAGE_REJECTED",
                    JSONObject()
                        .put("message_id", messageId)
                        .put("error", describe(error)),
                )
                sendReceiptAttempt(
                    messageId,
                    "FAILED",
                    JSONObject()
                        .put("stage", "LOCAL_SCHEMA_VALIDATION")
                        .put("error", describe(error)),
                    attempt = 0,
                )
            }
        }
    }

    private fun parsePresentation(envelope: JSONObject): DownlinkPresentation {
        require(envelope.optString("schema_ref") == DEVICE_MESSAGE_SCHEMA_REF) {
            "不支持的设备消息信封"
        }
        require(envelope.optString("message_type") == "REMINDER_SIGNAL") {
            "不是可呈现的消息类型"
        }
        require(envelope.optString("payload_schema_ref") == PRESENTATION_SCHEMA_REF) {
            "不支持的呈现载荷"
        }
        val expiresAt = Instant.parse(envelope.getString("expires_at")).toEpochMilli()
        require(expiresAt > System.currentTimeMillis()) { "消息已经过期" }

        val deliveryPolicy = envelope.optJSONObject("delivery_policy") ?: JSONObject()
        val allowText = deliveryPolicy.optBoolean("allow_text", true)
        val allowTts = deliveryPolicy.optBoolean("allow_tts", false)
        require(allowText || allowTts) { "文字与 TTS 均被禁止" }

        val payload = envelope.getJSONObject("payload")
        val content = payload.getJSONObject("presentation")
        val rawIntent = content.getString("intent")
        val intent = runCatching { PresentationIntent.valueOf(rawIntent) }
            .getOrDefault(PresentationIntent.ANSWER)
        val fallback = rawIntent.takeIf { it != intent.name }
        val title = content.getString("title").trim().take(MAX_TITLE_CHARS)
        require(title.isNotBlank()) { "标题为空" }
        val body = content.optNullableString("body")
            .orEmpty()
            .trim()
            .take(MAX_BODY_CHARS)
            .takeIf(String::isNotBlank)
        val speechText = content.optNullableString("speech_text")
            .orEmpty()
            .trim()
            .take(MAX_SPEECH_CHARS)
            .takeIf(String::isNotBlank)
        val interaction = runCatching {
            PresentationInteraction.valueOf(content.getString("interaction"))
        }.getOrDefault(PresentationInteraction.NONE)

        return DownlinkPresentation(
            messageId = envelope.getString("message_id"),
            intent = intent,
            title = title,
            body = body,
            speechText = speechText,
            interaction = interaction,
            allowText = allowText,
            allowTts = allowTts,
            expiresAtEpochMs = expiresAt,
            priority = envelope.optString("priority", "NORMAL"),
            fallbackIntent = fallback,
        )
    }

    private fun sendReceiptAttempt(
        messageId: String,
        status: String,
        detail: JSONObject,
        attempt: Int,
    ) {
        val deviceId = backendDeviceId
        if (deviceId.isNullOrBlank()) {
            if (attempt < MAX_RECEIPT_RETRIES) {
                handler.postDelayed(
                    {
                        executor.execute {
                            sendReceiptAttempt(messageId, status, detail, attempt + 1)
                        }
                    },
                    retryDelay(attempt),
                )
            }
            return
        }
        val body = JSONObject()
            .put("message_id", messageId)
            .put("status", status)
            .put("detail", detail)
            .put("device_reported_at", Instant.now().toString())
        runCatching {
            request(
                "POST",
                "/internal/v1/devices/$deviceId/receipts",
                body,
            )
        }.onSuccess {
            audit(
                "DOWNLINK_RECEIPT_SENT",
                JSONObject()
                    .put("message_id", messageId)
                    .put("status", status)
                    .put("attempt", attempt + 1),
            )
            if (status in TERMINAL_STATUSES) {
                markCompleted(messageId)
                inFlightIds.remove(messageId)
            }
        }.onFailure { error ->
            audit(
                "DOWNLINK_RECEIPT_FAILED",
                JSONObject()
                    .put("message_id", messageId)
                    .put("status", status)
                    .put("attempt", attempt + 1)
                    .put("error", describe(error)),
            )
            if (attempt < MAX_RECEIPT_RETRIES && started) {
                handler.postDelayed(
                    {
                        executor.execute {
                            sendReceiptAttempt(messageId, status, detail, attempt + 1)
                        }
                    },
                    retryDelay(attempt),
                )
            }
        }
    }

    private fun request(
        method: String,
        path: String,
        body: JSONObject?,
    ): JSONObject {
        val connection =
            URL("${BuildConfig.DEBUG_BACKEND_BASE_URL.trimEnd('/')}$path")
                .openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = CONNECT_TIMEOUT_MS
            connection.readTimeout = READ_TIMEOUT_MS
            connection.setRequestProperty("Accept", "application/json")
            if (body != null) {
                val bytes = body.toString().toByteArray(StandardCharsets.UTF_8)
                connection.doOutput = true
                connection.setFixedLengthStreamingMode(bytes.size)
                connection.setRequestProperty(
                    "Content-Type",
                    "application/json; charset=utf-8",
                )
                connection.outputStream.use { it.write(bytes) }
            }
            val status = connection.responseCode
            val stream =
                if (status in 200..299) connection.inputStream else connection.errorStream
            val responseBody = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (status !in 200..299) {
                throw DownlinkHttpException(status, responseBody.take(MAX_ERROR_CHARS))
            }
            return if (responseBody.isBlank()) JSONObject() else JSONObject(responseBody)
        } finally {
            connection.disconnect()
        }
    }

    private fun stableDeviceName(): String {
        val androidId = Settings.Secure.getString(
            appContext.contentResolver,
            Settings.Secure.ANDROID_ID,
        ).orEmpty()
        val suffix = androidId.takeLast(6).ifBlank { "device" }
        return "RealGit ${Build.MODEL.ifBlank { "RV101" }} $suffix"
    }

    private fun clearBackendDeviceId() {
        backendDeviceId = null
        preferences.edit().remove(KEY_BACKEND_DEVICE_ID).apply()
        audit(
            "DOWNLINK_DEVICE_REGISTRATION_RESET",
            JSONObject().put("reason", "BACKEND_DEVICE_NOT_FOUND"),
        )
    }

    @Synchronized
    private fun isCompleted(messageId: String): Boolean = messageId in completedIds

    @Synchronized
    private fun markCompleted(messageId: String) {
        completedIds.remove(messageId)
        completedIds.add(messageId)
        while (completedIds.size > MAX_COMPLETED_IDS) {
            completedIds.remove(completedIds.first())
        }
        preferences.edit()
            .putString(KEY_COMPLETED_IDS, JSONArray(completedIds.toList()).toString())
            .apply()
    }

    private fun reportConnectionState(state: String, error: String?) {
        if (state == lastConnectionState) return
        lastConnectionState = state
        audit(
            "DOWNLINK_CONNECTION_STATE",
            JSONObject()
                .put("state", state)
                .put("backend_device_id", backendDeviceId ?: JSONObject.NULL)
                .put("error", error ?: JSONObject.NULL),
        )
    }

    private fun audit(event: String, detail: JSONObject) {
        handler.post { onAudit(event, detail) }
    }

    private fun JSONObject.optNullableString(key: String): String? =
        if (!has(key) || isNull(key)) null else optString(key).takeIf(String::isNotBlank)

    private fun retryDelay(attempt: Int): Long =
        RECEIPT_RETRY_BASE_MS * (1L shl attempt.coerceIn(0, 4))

    private fun describe(error: Throwable): String =
        "${error.javaClass.simpleName}: ${error.message}"

    private class DownlinkHttpException(
        val status: Int,
        responseBody: String,
    ) : IllegalStateException("HTTP $status: $responseBody")

    companion object {
        private const val PREFERENCES = "reality_downlink"
        private const val KEY_BACKEND_DEVICE_ID = "backend_device_id"
        private const val KEY_COMPLETED_IDS = "completed_message_ids"
        private const val DEVICE_MESSAGE_SCHEMA_REF = "rme.device-message.v0"
        private const val PRESENTATION_SCHEMA_REF = "rme.glasses-presentation.v0"
        private const val POLL_INTERVAL_MS = 3_000L
        private const val RETRY_INTERVAL_MS = 5_000L
        private const val RECEIPT_RETRY_BASE_MS = 1_000L
        private const val CONNECT_TIMEOUT_MS = 3_000
        private const val READ_TIMEOUT_MS = 5_000
        private const val MAX_RECEIPT_RETRIES = 5
        private const val MAX_COMPLETED_IDS = 100
        private const val MAX_TITLE_CHARS = 42
        private const val MAX_BODY_CHARS = 80
        private const val MAX_SPEECH_CHARS = 100
        private const val MAX_ERROR_CHARS = 1_000
        private val TERMINAL_STATUSES = setOf("DISMISSED", "EXPIRED", "FAILED")
    }
}
