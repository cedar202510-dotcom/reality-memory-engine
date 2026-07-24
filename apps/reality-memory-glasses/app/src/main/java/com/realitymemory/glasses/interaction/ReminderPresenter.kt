package com.realitymemory.glasses.interaction

import android.content.Context
import android.speech.tts.TextToSpeech
import java.util.Locale

class ReminderPresenter(context: Context) : TextToSpeech.OnInitListener {
    private val tts = TextToSpeech(context.applicationContext, this)
    private var ready = false
    private var pendingText: String? = null

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
        pendingText?.let {
            pendingText = null
            speak(it)
        }
    }

    fun speak(text: String) {
        if (!ready) {
            pendingText = text
            return
        }
        tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "reality-memory-${System.nanoTime()}")
    }

    fun shutdown() {
        tts.stop()
        tts.shutdown()
    }
}
