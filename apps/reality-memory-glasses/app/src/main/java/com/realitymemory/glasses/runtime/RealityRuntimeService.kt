package com.realitymemory.glasses.runtime

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import com.realitymemory.glasses.MainActivity
import com.realitymemory.glasses.capture.AudioCaptureAdapter
import com.realitymemory.glasses.capture.CameraCaptureAdapter
import com.realitymemory.glasses.evidence.DebugBackendUploader
import com.realitymemory.glasses.evidence.EvidenceRepository
import com.realitymemory.glasses.interaction.ReminderPresenter
import com.realitymemory.glasses.sensor.GlassSensorAdapter
import com.realitymemory.glasses.wearable.HeartRateBroadcastCollector
import com.realitymemory.glasses.wearable.HeartRateBroadcastSample
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicInteger

class RealityRuntimeService : LifecycleService() {
    private val handler = Handler(Looper.getMainLooper())

    private lateinit var repository: EvidenceRepository
    private lateinit var camera: CameraCaptureAdapter
    private lateinit var audio: AudioCaptureAdapter
    private lateinit var sensors: GlassSensorAdapter
    private lateinit var presenter: ReminderPresenter
    private lateinit var uploader: DebugBackendUploader
    private lateinit var heartRateBroadcast: HeartRateBroadcastCollector

    private var state = SessionState.ARMED
    private var cameraReady = false
    private var cameraPreparing = false
    private var disclosureGeneration = 0
    private var reminderGeneration = 0

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
        uploader = DebugBackendUploader(repository)
        repository.setEvidenceReadyListener { uploader.enqueue() }
        uploader.start()
        camera = CameraCaptureAdapter(this, repository)
        audio = AudioCaptureAdapter(repository)
        presenter = ReminderPresenter(this)
        heartRateBroadcast = HeartRateBroadcastCollector(
            context = this,
            onSample = { sample -> handler.post { recordHeartRateBroadcastSample(sample) } },
            onStatus = { message -> handler.post { recordHeartRateBroadcastStatus(message) } },
        )
        sensors = GlassSensorAdapter(this, repository) { motion ->
            if (state != SessionState.ACTIVE) return@GlassSensorAdapter
            val modalities = if (motion.intensity == "STRONG") {
                setOf(CaptureModality.VIDEO, CaptureModality.AUDIO, CaptureModality.SENSOR)
            } else {
                setOf(CaptureModality.IMAGE, CaptureModality.AUDIO, CaptureModality.SENSOR)
            }
            capture("HEAD_MOTION_TRANSITION", modalities, motion)
        }
        RuntimeStatusStore.publish(
            this,
            SessionState.ARMED,
            "等待佩戴",
            displayKind = RuntimeDisplayKind.NONE,
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        ensureForeground()
        val action = intent?.action
        if (action != ACTION_START_HEART_RATE_BROADCAST_POC &&
            action != ACTION_STOP_HEART_RATE_BROADCAST_POC
        ) {
            ensureCameraPrepared()
        }
        when (action) {
            ACTION_START_EXPLICIT -> startDisclosure("USER_EXPLICIT")
            ACTION_WEAR_CHANGED -> {
                val worn = intent.getBooleanExtra(EXTRA_WORN, false)
                if (worn) {
                    startDisclosure("WEAR_CONFIRMED")
                } else {
                    endSession("NOT_WORN", announce = false)
                }
            }
            ACTION_TOGGLE_PAUSE -> endSession("LEGACY_TOGGLE_CANCELLED", announce = true)
            ACTION_REMEMBER_NOW -> rememberNow()
            ACTION_END_SESSION -> endSession("USER_CLOSED_THIS_SESSION", announce = true)
            ACTION_TEST_REMINDER -> showReminder(
                intent.getStringExtra(EXTRA_REMINDER_TEXT)
                    ?: "提醒：你刚才记录的事情已经整理好了。",
            )
            ACTION_DISMISS_REMINDER -> dismissReminder()
            ACTION_START_HEART_RATE_BROADCAST_POC -> startHeartRateBroadcastPoc()
            ACTION_STOP_HEART_RATE_BROADCAST_POC -> heartRateBroadcast.stop()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        sensors.shutdown()
        camera.shutdown()
        audio.shutdown()
        heartRateBroadcast.stop()
        presenter.shutdown()
        repository.setEvidenceReadyListener(null)
        uploader.shutdown()
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
        publish(
            state,
            "RealGit 已开启现实感知",
            RuntimeDisplayKind.DISCLOSURE,
        )
        presenter.speak("RealGit 已开启现实感知。")
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
            if (sensorReady) "现实感知运行中" else "现实感知运行中，IMU 暂不可用",
            RuntimeDisplayKind.NONE,
        )
        handler.removeCallbacks(baselineCapture)
        handler.postDelayed(baselineCapture, BASELINE_CAPTURE_INTERVAL_MS)
        capture(
            signalKind = if (startReason == "WEAR_CONFIRMED") "WEAR_CONFIRMED" else "USER_EXPLICIT",
            modalities = setOf(CaptureModality.IMAGE, CaptureModality.SENSOR),
        )
    }

    private fun rememberNow() {
        if (state != SessionState.ACTIVE) return
        capture(
            signalKind = "USER_EXPLICIT",
            modalities = setOf(
                CaptureModality.IMAGE,
                CaptureModality.AUDIO,
                CaptureModality.SENSOR,
            ),
        )
    }

    private fun showReminder(text: String) {
        if (state != SessionState.ACTIVE) return
        reminderGeneration += 1
        val generation = reminderGeneration
        publish(state, text, RuntimeDisplayKind.REMINDER)
        presenter.speak(text)
        handler.postDelayed(
            {
                if (state == SessionState.ACTIVE && generation == reminderGeneration) {
                    publish(state, "现实感知运行中", RuntimeDisplayKind.NONE)
                }
            },
            REMINDER_DISPLAY_MS,
        )
    }

    private fun dismissReminder() {
        reminderGeneration += 1
        if (state == SessionState.ACTIVE) {
            publish(state, "现实感知运行中", RuntimeDisplayKind.NONE)
        }
    }

    private fun startHeartRateBroadcastPoc() {
        if (!hasBlePermissions()) {
            recordHeartRateBroadcastStatus("缺少蓝牙扫描/连接权限")
            return
        }
        heartRateBroadcast.start()
    }

    private fun recordHeartRateBroadcastStatus(message: String) {
        repository.appendRuntimeAudit(
            "HEART_RATE_BROADCAST_STATUS",
            JSONObject().put("message", message),
        )
        publish(state, message, RuntimeDisplayKind.NONE)
    }

    private fun recordHeartRateBroadcastSample(sample: HeartRateBroadcastSample) {
        repository.appendRuntimeAudit(
            "HEART_RATE_BROADCAST_SAMPLE",
            JSONObject()
                .put("bpm", sample.bpm)
                .put("peripheral_name", sample.peripheralName ?: JSONObject.NULL)
                .put("peripheral_address", sample.peripheralAddress)
                .put("rssi", sample.rssi ?: JSONObject.NULL)
                .put("captured_at", sample.capturedAt.toString())
                .put("monotonic_ns", sample.monotonicNs)
                .put("raw_hex", sample.rawHex)
                .put("adapter", "ble-heart-rate-service/android-poc"),
        )
        publish(state, "实时心率 ${sample.bpm} bpm", RuntimeDisplayKind.NONE)
    }

    private fun endSession(reason: String, announce: Boolean) {
        disclosureGeneration += 1
        val endGeneration = disclosureGeneration
        reminderGeneration += 1
        handler.removeCallbacks(baselineCapture)
        sensors.stop()
        audio.stop()
        camera.stopActiveRecording()
        repository.updateSessionState(SessionState.ENDED, reason)
        state = SessionState.ENDED
        if (announce) {
            publish(
                state,
                "本次现实感知已取消",
                RuntimeDisplayKind.CANCELLED,
            )
            presenter.speak("本次现实感知已取消。")
        } else {
            publish(state, "本次结束", RuntimeDisplayKind.NONE)
        }
        handler.postDelayed(
            {
                if (state == SessionState.ENDED && disclosureGeneration == endGeneration) {
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    stopSelf()
                }
            },
            if (announce) CANCELLED_DISPLAY_MS else 0L,
        )
    }

    private fun capture(
        signalKind: String,
        modalities: Set<CaptureModality>,
        motion: MotionTrigger? = null,
    ) {
        if (state != SessionState.ACTIVE) return
        if (
            !cameraReady &&
            modalities.any { it == CaptureModality.IMAGE || it == CaptureModality.VIDEO }
        ) {
            ensureCameraPrepared()
        }
        val window = repository.beginWindow(signalKind, modalities, motion)
        val remaining = AtomicInteger(modalities.size)
        val complete: (Boolean, String) -> Unit = { success, message ->
            if (success) {
                RuntimeStatusStore.updateLastEvidence(this, window.captureWindowId)
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

    private fun publish(
        newState: SessionState,
        message: String,
        displayKind: RuntimeDisplayKind =
            if (newState == SessionState.BLOCKED) {
                RuntimeDisplayKind.BLOCKED
            } else {
                RuntimeDisplayKind.NONE
            },
    ) {
        state = newState
        RuntimeStatusStore.publish(
            this,
            newState,
            message,
            displayKind = displayKind,
        )
        updateNotification(message)
    }

    private fun hasCapturePermissions(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    private fun hasBlePermissions(): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
            (
                ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_SCAN) ==
                    PackageManager.PERMISSION_GRANTED &&
                    ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT) ==
                    PackageManager.PERMISSION_GRANTED
                )

    private fun ensureCameraPrepared() {
        if (cameraReady || cameraPreparing) return
        if (
            ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        cameraPreparing = true
        camera.prepare { ready, error ->
            cameraPreparing = false
            cameraReady = ready
            if (!ready && state == SessionState.ACTIVE) {
                publish(state, "现实感知运行中，相机暂不可用：$error", RuntimeDisplayKind.NONE)
            }
        }
    }

    private fun ensureForeground() {
        val manager = getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(
                NOTIFICATION_CHANNEL,
                "RealGit",
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
            .setContentTitle("RealGit")
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
        const val ACTION_DISMISS_REMINDER = "com.realitymemory.glasses.DISMISS_REMINDER"
        const val ACTION_START_HEART_RATE_BROADCAST_POC =
            "com.realitymemory.glasses.START_HEART_RATE_BROADCAST_POC"
        const val ACTION_STOP_HEART_RATE_BROADCAST_POC =
            "com.realitymemory.glasses.STOP_HEART_RATE_BROADCAST_POC"
        const val EXTRA_WORN = "worn"
        const val EXTRA_WEAR_SOURCE = "wear_source"
        const val EXTRA_REMINDER_TEXT = "reminder_text"

        private const val NOTIFICATION_CHANNEL = "reality_memory_runtime"
        private const val NOTIFICATION_ID = 501
        private const val DISCLOSURE_DELAY_MS = 5_000L
        private const val CANCELLED_DISPLAY_MS = 3_000L
        private const val BASELINE_CAPTURE_INTERVAL_MS = 60_000L
        private const val REMINDER_DISPLAY_MS = 8_000L
    }
}
