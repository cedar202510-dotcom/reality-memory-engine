package com.realitymemory.glasses.runtime

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import com.realitymemory.glasses.MainActivity
import com.realitymemory.glasses.capture.AudioCaptureAdapter
import com.realitymemory.glasses.capture.CameraCaptureAdapter
import com.realitymemory.glasses.evidence.EvidenceRepository
import com.realitymemory.glasses.interaction.ReminderPresenter
import com.realitymemory.glasses.sensor.GlassSensorAdapter
import java.util.concurrent.atomic.AtomicInteger

class RealityRuntimeService : LifecycleService() {
    private val handler = Handler(Looper.getMainLooper())

    private lateinit var repository: EvidenceRepository
    private lateinit var camera: CameraCaptureAdapter
    private lateinit var audio: AudioCaptureAdapter
    private lateinit var sensors: GlassSensorAdapter
    private lateinit var presenter: ReminderPresenter

    private var state = SessionState.ARMED
    private var cameraReady = false
    private var disclosureGeneration = 0

    private val baselineCapture = object : Runnable {
        override fun run() {
            if (state == SessionState.ACTIVE) {
                capture(
                    signalKind = "DEBUG_TEST",
                    modalities = setOf(CaptureModality.IMAGE, CaptureModality.SENSOR),
                )
                handler.postDelayed(this, BASELINE_CAPTURE_INTERVAL_MS)
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        repository = EvidenceRepository(this)
        camera = CameraCaptureAdapter(this, repository)
        audio = AudioCaptureAdapter(repository)
        presenter = ReminderPresenter(this)
        sensors = GlassSensorAdapter(this, repository) { motion ->
            if (state != SessionState.ACTIVE) return@GlassSensorAdapter
            val modalities = if (motion.intensity == "STRONG") {
                setOf(CaptureModality.VIDEO, CaptureModality.AUDIO, CaptureModality.SENSOR)
            } else {
                setOf(CaptureModality.IMAGE, CaptureModality.AUDIO, CaptureModality.SENSOR)
            }
            capture("HEAD_MOTION_TRANSITION", modalities, motion)
        }
        RuntimeStatusStore.publish(this, SessionState.ARMED, "等待佩戴")
        camera.prepare { ready, error ->
            cameraReady = ready
            if (!ready && state == SessionState.ACTIVE) {
                publish(SessionState.BLOCKED, "相机暂不可用：$error")
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        ensureForeground()
        when (intent?.action) {
            ACTION_START_EXPLICIT -> startDisclosure("USER_EXPLICIT")
            ACTION_WEAR_CHANGED -> {
                val worn = intent.getBooleanExtra(EXTRA_WORN, false)
                if (worn) startDisclosure("WEAR_CONFIRMED") else endSession("NOT_WORN")
            }
            ACTION_TOGGLE_PAUSE -> togglePause()
            ACTION_REMEMBER_NOW -> rememberNow()
            ACTION_END_SESSION -> endSession("USER_CLOSED_THIS_SESSION")
            ACTION_TEST_REMINDER -> showReminder(
                intent.getStringExtra(EXTRA_REMINDER_TEXT)
                    ?: "提醒：你刚才记录的事情已经整理好了。",
            )
        }
        return START_STICKY
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        sensors.shutdown()
        camera.shutdown()
        audio.shutdown()
        presenter.shutdown()
        super.onDestroy()
    }

    private fun startDisclosure(startReason: String) {
        if (state == SessionState.ACTIVE || state == SessionState.DISCLOSURE) return
        if (!hasCapturePermissions()) {
            repository.openSession(startReason)
            repository.updateSessionState(SessionState.BLOCKED)
            publish(SessionState.BLOCKED, "需要相机和麦克风权限")
            return
        }
        repository.openSession(startReason)
        state = SessionState.DISCLOSURE
        repository.updateSessionState(state)
        disclosureGeneration += 1
        val generation = disclosureGeneration
        publish(state, "5 秒后开始感知本次现实片段")
        presenter.speak("Reality Memory 已准备好，五秒后开始感知。你可以随时暂停。")
        handler.postDelayed({
            if (state == SessionState.DISCLOSURE && generation == disclosureGeneration) {
                activate(startReason)
            }
        }, DISCLOSURE_DELAY_MS)
    }

    private fun activate(startReason: String) {
        if (!hasCapturePermissions()) {
            state = SessionState.BLOCKED
            repository.updateSessionState(state)
            publish(state, "权限不足，未开始感知")
            return
        }
        state = SessionState.ACTIVE
        repository.updateSessionState(state)
        val sensorReady = sensors.start()
        publish(
            state,
            if (sensorReady) "正在帮你留意重要变化" else "正在记录，IMU 暂不可用",
        )
        handler.removeCallbacks(baselineCapture)
        handler.postDelayed(baselineCapture, BASELINE_CAPTURE_INTERVAL_MS)
        capture(
            signalKind = if (startReason == "WEAR_CONFIRMED") "WEAR_CONFIRMED" else "USER_EXPLICIT",
            modalities = setOf(CaptureModality.IMAGE, CaptureModality.SENSOR),
        )
    }

    private fun togglePause() {
        when (state) {
            SessionState.ACTIVE -> {
                state = SessionState.PAUSED
                handler.removeCallbacks(baselineCapture)
                sensors.stop()
                audio.stop()
                camera.stopActiveRecording()
                repository.updateSessionState(state)
                publish(state, "本次感知已暂停")
                presenter.speak("已暂停。")
            }
            SessionState.PAUSED -> {
                state = SessionState.ACTIVE
                repository.updateSessionState(state)
                sensors.start()
                handler.postDelayed(baselineCapture, BASELINE_CAPTURE_INTERVAL_MS)
                publish(state, "已经继续")
                presenter.speak("已继续。")
            }
            SessionState.DISCLOSURE -> endSession("USER_CLOSED_DURING_DISCLOSURE")
            else -> startDisclosure("USER_EXPLICIT")
        }
    }

    private fun rememberNow() {
        if (state != SessionState.ACTIVE) {
            publish(state, "请先继续本次感知")
            return
        }
        capture(
            signalKind = "USER_EXPLICIT",
            modalities = setOf(
                CaptureModality.IMAGE,
                CaptureModality.AUDIO,
                CaptureModality.SENSOR,
            ),
        )
        publish(state, "正在记下这一刻")
        presenter.speak("好，我记一下。")
    }

    private fun showReminder(text: String) {
        publish(state, text)
        presenter.speak(text)
    }

    private fun endSession(reason: String) {
        disclosureGeneration += 1
        handler.removeCallbacks(baselineCapture)
        sensors.stop()
        audio.stop()
        camera.stopActiveRecording()
        repository.updateSessionState(SessionState.ENDED, reason)
        state = SessionState.ENDED
        publish(state, "本次已经结束")
        presenter.speak("本次已经结束。")
    }

    private fun capture(
        signalKind: String,
        modalities: Set<CaptureModality>,
        motion: MotionTrigger? = null,
    ) {
        if (state != SessionState.ACTIVE) return
        val window = repository.beginWindow(signalKind, modalities, motion)
        val remaining = AtomicInteger(modalities.size)
        val complete: (Boolean, String) -> Unit = { success, message ->
            if (success) {
                RuntimeStatusStore.publish(this, state, message, window.captureWindowId)
            }
            if (remaining.decrementAndGet() == 0) repository.finalizeWindow(window)
        }

        modalities.forEach { modality ->
            when (modality) {
                CaptureModality.IMAGE -> {
                    if (cameraReady) camera.captureImage(window, complete)
                    else markUnavailable(window, modality, complete)
                }
                CaptureModality.VIDEO -> {
                    if (cameraReady) camera.captureShortVideo(window, onComplete = complete)
                    else markUnavailable(window, modality, complete)
                }
                CaptureModality.AUDIO -> audio.capture(window, onComplete = complete)
                CaptureModality.SENSOR -> sensors.captureWindow(window, onComplete = complete)
            }
        }
    }

    private fun markUnavailable(
        window: CaptureWindowContext,
        modality: CaptureModality,
        complete: (Boolean, String) -> Unit,
    ) {
        repository.recordAttempt(
            window,
            modality,
            java.time.Instant.now(),
            "FAILED",
            "DEVICE_UNAVAILABLE",
            0,
            null,
        )
        complete(false, "$modality 暂不可用")
    }

    private fun publish(newState: SessionState, message: String) {
        state = newState
        RuntimeStatusStore.publish(this, newState, message)
        updateNotification(message)
    }

    private fun hasCapturePermissions(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    private fun ensureForeground() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                NOTIFICATION_CHANNEL,
                "Reality Memory",
                NotificationManager.IMPORTANCE_LOW,
            ),
        )
        startForeground(NOTIFICATION_ID, buildNotification("等待开始"))
    }

    private fun updateNotification(message: String) {
        getSystemService(NotificationManager::class.java)
            .notify(NOTIFICATION_ID, buildNotification(message))
    }

    private fun buildNotification(message: String): Notification {
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return Notification.Builder(this, NOTIFICATION_CHANNEL)
            .setContentTitle("Reality Memory")
            .setContentText(message)
            .setSmallIcon(android.R.drawable.presence_video_online)
            .setContentIntent(openIntent)
            .setOngoing(true)
            .build()
    }

    companion object {
        const val ACTION_START_EXPLICIT = "com.realitymemory.glasses.START_EXPLICIT"
        const val ACTION_WEAR_CHANGED = "com.realitymemory.glasses.WEAR_CHANGED"
        const val ACTION_TOGGLE_PAUSE = "com.realitymemory.glasses.TOGGLE_PAUSE"
        const val ACTION_REMEMBER_NOW = "com.realitymemory.glasses.REMEMBER_NOW"
        const val ACTION_END_SESSION = "com.realitymemory.glasses.END_SESSION"
        const val ACTION_TEST_REMINDER = "com.realitymemory.glasses.TEST_REMINDER"
        const val EXTRA_WORN = "worn"
        const val EXTRA_WEAR_SOURCE = "wear_source"
        const val EXTRA_REMINDER_TEXT = "reminder_text"

        private const val NOTIFICATION_CHANNEL = "reality_memory_runtime"
        private const val NOTIFICATION_ID = 501
        private const val DISCLOSURE_DELAY_MS = 5_000L
        private const val BASELINE_CAPTURE_INTERVAL_MS = 60_000L
    }
}
