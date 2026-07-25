package com.realitymemory.glasses.runtime

import android.content.Context
import android.content.Intent
import com.realitymemory.glasses.downlink.DownlinkPresentation
import com.realitymemory.glasses.downlink.PresentationIntent
import com.realitymemory.glasses.downlink.PresentationInteraction
import org.json.JSONObject

enum class RuntimeDisplayKind {
    NONE,
    DISCLOSURE,
    REMINDER,
    PRESENTATION,
    CANCELLED,
    BLOCKED,
}

data class RuntimeStatus(
    val state: SessionState,
    val message: String,
    val lastEvidence: String?,
    val displayKind: RuntimeDisplayKind,
    val presentation: DownlinkPresentation? = null,
)

object RuntimeStatusStore {
    const val ACTION_STATUS_CHANGED = "com.realitymemory.glasses.STATUS_CHANGED"
    const val EXTRA_STATE = "state"
    const val EXTRA_MESSAGE = "message"
    const val EXTRA_DISPLAY_KIND = "display_kind"

    private const val PREFS = "reality_runtime_status"
    private const val KEY_STATE = "state"
    private const val KEY_MESSAGE = "message"
    private const val KEY_LAST_EVIDENCE = "last_evidence"
    private const val KEY_DISPLAY_KIND = "display_kind"
    private const val KEY_PRESENTATION = "presentation"

    fun publish(
        context: Context,
        state: SessionState,
        message: String,
        lastEvidence: String? = null,
        displayKind: RuntimeDisplayKind = defaultDisplayKind(state),
        presentation: DownlinkPresentation? = null,
    ) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_STATE, state.name)
            .putString(KEY_MESSAGE, message)
            .putString(KEY_DISPLAY_KIND, displayKind.name)
            .apply {
                if (presentation != null) {
                    putString(KEY_PRESENTATION, presentationToJson(presentation).toString())
                } else {
                    remove(KEY_PRESENTATION)
                }
            }
            .apply {
                if (lastEvidence != null) putString(KEY_LAST_EVIDENCE, lastEvidence)
            }
            .apply()

        context.sendBroadcast(
            Intent(ACTION_STATUS_CHANGED)
                .setPackage(context.packageName)
                .putExtra(EXTRA_STATE, state.name)
                .putExtra(EXTRA_MESSAGE, message)
                .putExtra(EXTRA_DISPLAY_KIND, displayKind.name),
        )
    }

    fun updateLastEvidence(context: Context, lastEvidence: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_LAST_EVIDENCE, lastEvidence)
            .apply()
        context.sendBroadcast(Intent(ACTION_STATUS_CHANGED).setPackage(context.packageName))
    }

    fun read(context: Context): RuntimeStatus {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val state = runCatching {
            SessionState.valueOf(prefs.getString(KEY_STATE, SessionState.ARMED.name)!!)
        }.getOrDefault(SessionState.ARMED)
        val displayKind = runCatching {
            RuntimeDisplayKind.valueOf(
                prefs.getString(KEY_DISPLAY_KIND, defaultDisplayKind(state).name)!!,
            )
        }.getOrDefault(defaultDisplayKind(state))
        return RuntimeStatus(
            state = state,
            message = prefs.getString(KEY_MESSAGE, "等待佩戴") ?: "等待佩戴",
            lastEvidence = prefs.getString(KEY_LAST_EVIDENCE, null),
            displayKind = displayKind,
            presentation = prefs.getString(KEY_PRESENTATION, null)
                ?.let(::presentationFromJson),
        )
    }

    private fun presentationToJson(value: DownlinkPresentation): JSONObject =
        JSONObject()
            .put("message_id", value.messageId)
            .put("intent", value.intent.name)
            .put("title", value.title)
            .put("body", value.body ?: JSONObject.NULL)
            .put("speech_text", value.speechText ?: JSONObject.NULL)
            .put("interaction", value.interaction.name)
            .put("allow_text", value.allowText)
            .put("allow_tts", value.allowTts)
            .put("expires_at_epoch_ms", value.expiresAtEpochMs)
            .put("priority", value.priority)
            .put("fallback_intent", value.fallbackIntent ?: JSONObject.NULL)

    private fun presentationFromJson(raw: String): DownlinkPresentation? =
        runCatching {
            val value = JSONObject(raw)
            DownlinkPresentation(
                messageId = value.getString("message_id"),
                intent = PresentationIntent.valueOf(value.getString("intent")),
                title = value.getString("title"),
                body = value.optNullableString("body"),
                speechText = value.optNullableString("speech_text"),
                interaction = PresentationInteraction.valueOf(
                    value.getString("interaction"),
                ),
                allowText = value.optBoolean("allow_text", true),
                allowTts = value.optBoolean("allow_tts", false),
                expiresAtEpochMs = value.getLong("expires_at_epoch_ms"),
                priority = value.optString("priority", "NORMAL"),
                fallbackIntent = value.optNullableString("fallback_intent"),
            )
        }.getOrNull()

    private fun JSONObject.optNullableString(key: String): String? =
        if (!has(key) || isNull(key)) null else optString(key).takeIf(String::isNotBlank)

    private fun defaultDisplayKind(state: SessionState): RuntimeDisplayKind = when (state) {
        SessionState.DISCLOSURE -> RuntimeDisplayKind.DISCLOSURE
        SessionState.BLOCKED -> RuntimeDisplayKind.BLOCKED
        else -> RuntimeDisplayKind.NONE
    }
}
