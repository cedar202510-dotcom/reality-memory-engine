package com.realitymemory.glasses.runtime

import android.content.Context
import android.content.Intent

object RuntimeStatusStore {
    const val ACTION_STATUS_CHANGED = "com.realitymemory.glasses.STATUS_CHANGED"
    const val EXTRA_STATE = "state"
    const val EXTRA_MESSAGE = "message"

    private const val PREFS = "reality_runtime_status"
    private const val KEY_STATE = "state"
    private const val KEY_MESSAGE = "message"
    private const val KEY_LAST_EVIDENCE = "last_evidence"

    fun publish(
        context: Context,
        state: SessionState,
        message: String,
        lastEvidence: String? = null,
    ) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_STATE, state.name)
            .putString(KEY_MESSAGE, message)
            .apply {
                if (lastEvidence != null) putString(KEY_LAST_EVIDENCE, lastEvidence)
            }
            .apply()

        context.sendBroadcast(
            Intent(ACTION_STATUS_CHANGED)
                .setPackage(context.packageName)
                .putExtra(EXTRA_STATE, state.name)
                .putExtra(EXTRA_MESSAGE, message),
        )
    }

    fun read(context: Context): Triple<SessionState, String, String?> {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val state = runCatching {
            SessionState.valueOf(prefs.getString(KEY_STATE, SessionState.ARMED.name)!!)
        }.getOrDefault(SessionState.ARMED)
        return Triple(
            state,
            prefs.getString(KEY_MESSAGE, "等待佩戴") ?: "等待佩戴",
            prefs.getString(KEY_LAST_EVIDENCE, null),
        )
    }
}
