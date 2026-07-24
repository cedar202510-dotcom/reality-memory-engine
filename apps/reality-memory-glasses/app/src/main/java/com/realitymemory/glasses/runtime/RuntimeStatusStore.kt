package com.realitymemory.glasses.runtime

import android.content.Context
import android.content.Intent

enum class RuntimeDisplayKind {
    NONE,
    DISCLOSURE,
    REMINDER,
    CANCELLED,
    BLOCKED,
}

data class RuntimeStatus(
    val state: SessionState,
    val message: String,
    val lastEvidence: String?,
    val displayKind: RuntimeDisplayKind,
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

    fun publish(
        context: Context,
        state: SessionState,
        message: String,
        lastEvidence: String? = null,
        displayKind: RuntimeDisplayKind = defaultDisplayKind(state),
    ) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_STATE, state.name)
            .putString(KEY_MESSAGE, message)
            .putString(KEY_DISPLAY_KIND, displayKind.name)
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
        )
    }

    private fun defaultDisplayKind(state: SessionState): RuntimeDisplayKind = when (state) {
        SessionState.DISCLOSURE -> RuntimeDisplayKind.DISCLOSURE
        SessionState.BLOCKED -> RuntimeDisplayKind.BLOCKED
        else -> RuntimeDisplayKind.NONE
    }
}
