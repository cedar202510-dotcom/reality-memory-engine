package com.realitymemory.glasses.interaction

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap

class ReminderPresenter(context: Context) : TextToSpeech.OnInitListener {
    private val tts = TextToSpeech(context.applicationContext, this)
    private val handler = Handler(Looper.getMainLooper())
    private val callbacks = ConcurrentHashMap<String, (Boolean, String?) -> Unit>()
    private var ready = false
    private var pendingSpeech: PendingSpeech? = null

    init {
        tts.setOnUtteranceProgressListener(
            object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) = Unit

                override fun onDone(utteranceId: String?) {
                    complete(utteranceId, true, null)
                }

                @Deprecated("Deprecated in Java")
                override fun onError(utteranceId: String?) {
                    complete(utteranceId, false, "TTS_ERROR")
                }

                override fun onError(utteranceId: String?, errorCode: Int) {
                    complete(utteranceId, false, "TTS_ERROR_$errorCode")
                }
            },
        )
    }

    override fun onInit(status: Int) {
        ready = status == TextToSpeech.SUCCESS
        if (!ready) return
        val result = tts.setLanguage(Locale.SIMPLIFIED_CHINESE)
        if (result == TextToSpeech.LANG_MISSING_DATA ||
            result == TextToSpeech.LANG_NOT_SUPPORTED
        ) {
            tts.language = Locale.getDefault()
        }
        tts.setSpeechRate(1.0f)
        pendingSpeech?.let {
            pendingSpeech = null
            speak(it.text, it.onComplete)
        }
    }

    fun speak(
        text: String,
        onComplete: ((Boolean, String?) -> Unit)? = null,
    ) {
        if (!ready) {
            pendingSpeech = PendingSpeech(text, onComplete)
            return
        }
        val utteranceId = "reality-memory-${System.nanoTime()}"
        if (onComplete != null) callbacks[utteranceId] = onComplete
        val result = tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, utteranceId)
        if (result == TextToSpeech.ERROR) {
            complete(utteranceId, false, "TTS_START_FAILED")
        }
    }

    fun shutdown() {
        pendingSpeech = null
        callbacks.clear()
        handler.removeCallbacksAndMessages(null)
        tts.stop()
        tts.shutdown()
    }

    private fun complete(
        utteranceId: String?,
        success: Boolean,
        error: String?,
    ) {
        if (utteranceId == null) return
        val callback = callbacks.remove(utteranceId) ?: return
        handler.post { callback(success, error) }
    }

    private data class PendingSpeech(
        val text: String,
        val onComplete: ((Boolean, String?) -> Unit)?,
    )
}
