package com.realitymemory.glasses.runtime

import android.content.Context
import java.util.concurrent.TimeUnit

object WearStateStore {
    fun recordObservedState(context: Context, worn: Boolean) {
        preferences(context)
            .edit()
            .putBoolean(KEY_LAST_WORN, worn)
            .putBoolean(KEY_HAS_LAST_WORN, true)
            .apply()
    }

    fun lastObservedState(context: Context): Boolean? {
        val preferences = preferences(context)
        if (!preferences.getBoolean(KEY_HAS_LAST_WORN, false)) return null
        return preferences.getBoolean(KEY_LAST_WORN, false)
    }

    fun setResumeSuppressed(context: Context, suppressed: Boolean) {
        preferences(context)
            .edit()
            .putBoolean(KEY_RESUME_SUPPRESSED, suppressed)
            .apply()
    }

    fun isResumeSuppressed(context: Context): Boolean =
        preferences(context).getBoolean(KEY_RESUME_SUPPRESSED, false)

    fun readCurrentRokidWearState(): Boolean? = runCatching {
        val process = ProcessBuilder(GETPROP_PATH, ROKID_WEAR_PROPERTY)
            .redirectErrorStream(true)
            .start()
        if (!process.waitFor(GETPROP_TIMEOUT_MS, TimeUnit.MILLISECONDS)) {
            process.destroyForcibly()
            return@runCatching null
        }
        when (process.inputStream.bufferedReader().use { it.readText().trim() }) {
            "1" -> true
            "0" -> false
            else -> null
        }
    }.getOrNull()

    private fun preferences(context: Context) =
        context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    private const val PREFERENCES_NAME = "reality_memory_wear_state"
    private const val KEY_HAS_LAST_WORN = "has_last_worn"
    private const val KEY_LAST_WORN = "last_worn"
    private const val KEY_RESUME_SUPPRESSED = "resume_suppressed"
    private const val GETPROP_PATH = "/system/bin/getprop"
    private const val ROKID_WEAR_PROPERTY = "vendor.rkd.glasses.is_take_on"
    private const val GETPROP_TIMEOUT_MS = 750L
}
