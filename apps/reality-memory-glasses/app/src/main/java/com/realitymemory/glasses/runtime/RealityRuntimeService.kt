package com.realitymemory.glasses.runtime

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.widget.Toast
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
import com.realitymemory.glasses.wearable.HeartRateEvidenceBuffer
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

class RealityRuntimeService : LifecycleService() {
    private val handler = Handler(Looper.getMainLooper())
    private val wearStateExecutor = Executors.newSingleThreadExecutor()

    private lateinit var repository: EvidenceRepository
    private lateinit var camera: CameraCaptureAdapter
    private lateinit var audio: AudioCaptureAdapter
    private lateinit var sensors: GlassSensorAdapter
    private lateinit var presenter: ReminderPresenter
    private lateinit var uploader: DebugBackendUploader
    private lateinit var heartRateBroadcast: HeartRateBroadcastCollector
    private lateinit var heartRateEvidence: HeartRateEvidenceBuffer
    private val wearStateReceiver: BroadcastReceiver = WearStateReceiver()

    private var state = SessionState.ARMED
    private var cameraReady = false
    private var cameraPreparing = false
    private var disclosureGeneration = 0
    private var reminderGeneration = 0
    private var wearDisclosureRequestGeneration = 0
    private var wearDisclosureVisibleGeneration = 0
    private var foregroundPromotionAudited = false
    private val captureWindowBusy = AtomicBoolean(false)

    override fun onCreate() {
        super.onCreate()
        ContextCompat.registerReceiver(
            this,
            wearStateReceiver,
            IntentFilter().apply {
                addAction(WearStateReceiver.ACTION_TAKE_STATUS_CHANGED)
                addAction(WearStateReceiver.ACTION_LEG_STATUS_CHANGED)
            },
            ContextCompat.RECEIVER_EXPORTED,
        )
        repository = EvidenceRepository(this)
        uploader = DebugBackendUploader(repository)
        repository.setEvidenceReadyListener { uploader.enqueue() }
        uploader.start()
        camera = CameraCaptureAdapter(this, repository)
        audio = AudioCaptureAdapter(this, repository)
        presenter = ReminderPresenter(this)
        heartRateEvidence = HeartRateEvidenceBuffer(repository)
        heartRateBroadcast = HeartRateBroadcastCollector(
            context = this,
            onSample = { sample -> handler.post { recordHeartRateBroadcastSample(sample) } },
            onStatus = { message -> handler.post { recordHeartRateBroadcastStatus(message) } },
        )
        sensors = GlassSensorAdapter(this, repository) { motion ->
            if (state != SessionState.ACTIVE) return@GlassSensorAdapter
            capture(
                signalKind = "HEAD_MOTION_TRANSITION",
                modalities = setOf(
                    CaptureModality.IMAGE,
                    CaptureModality.VIDEO,
                    CaptureModality.SENSOR,
                ),
                motion = motion,
                useRokidSystemRecorder = true,
                systemVideoDurationMs = MOTION_SYSTEM_VIDEO_DURATION_MS,
            )
        }
        RuntimeStatusStore.publish(
            this,
            SessionState.ARMED,
            "等待佩戴",
            displayKind = RuntimeDisplayKind.NONE,
        )
        reconcileCurrentWearState()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        ensureForeground()
        when (intent?.action) {
            ACTION_ARM_MONITOR -> publish(
                SessionState.ARMED,
                "等待佩戴",
                RuntimeDisplayKind.NONE,
            )
            ACTION_START_EXPLICIT -> {
                WearStateStore.setResumeSuppressed(this, false)
                startDisclosure(
                    intent.getStringExtra(EXTRA_START_REASON) ?: "USER_EXPLICIT",
                )
            }
            ACTION_WEAR_CHANGED -> {
                val worn = intent.getBooleanExtra(EXTRA_WORN, false)
                val source = intent.getStringExtra(EXTRA_WEAR_SOURCE) ?: "UNKNOWN"
                WearStateStore.recordObservedState(this, worn)
                WearStateStore.setResumeSuppressed(this, false)
                repository.appendRuntimeAudit(
                    "WEAR_STATE_RECEIVED",
                    JSONObject()
                        .put("worn", worn)
                        .put("source", source)
                        .put("runtime_state", state.name),
                )
                if (worn) {
                    startDisclosure("WEAR_CONFIRMED")
                } else {
                    endSession("NOT_WORN", announce = false)
                }
            }
            ACTION_TOGGLE_PAUSE -> {
                WearStateStore.setResumeSuppressed(this, true)
                endSession("LEGACY_TOGGLE_CANCELLED", announce = true)
            }
            ACTION_REMEMBER_NOW -> rememberNow()
            ACTION_TEST_SYSTEM_VIDEO -> captureSystemVideoNow()
            ACTION_END_SESSION -> {
                WearStateStore.setResumeSuppressed(this, true)
                endSession("USER_CLOSED_THIS_SESSION", announce = true)
            }
            ACTION_TEST_REMINDER -> showReminder(
                intent.getStringExtra(EXTRA_REMINDER_TEXT)
                    ?: "提醒：你刚才记录的事情已经整理好了。",
            )
            ACTION_DISMISS_REMINDER -> dismissReminder()
            ACTION_START_HEART_RATE_BROADCAST_POC -> startHeartRateBroadcastPoc()
            ACTION_STOP_HEART_RATE_BROADCAST_POC -> stopHeartRateBroadcastPoc()
            ACTION_REPORT_WEAR_DISCLOSURE_VISIBLE -> {
                wearDisclosureVisibleGeneration = wearDisclosureRequestGeneration
                repository.appendRuntimeAudit(
                    "WEAR_DISCLOSURE_UI_VISIBLE",
                    JSONObject()
                        .put("runtime_state", state.name)
                        .put("request_generation", wearDisclosureVisibleGeneration),
                )
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        runCatching { unregisterReceiver(wearStateReceiver) }
        sensors.shutdown()
        camera.shutdown()
        audio.shutdown()
        heartRateBroadcast.stop()
        heartRateEvidence.shutdown()
        presenter.shutdown()
        repository.setEvidenceReadyListener(null)
        uploader.shutdown()
        wearStateExecutor.shutdownNow()
        super.onDestroy()
    }

    private fun reconcileCurrentWearState() {
        val previousWorn = WearStateStore.lastObservedState(this)
        val resumeSuppressed = WearStateStore.isResumeSuppressed(this)
        wearStateExecutor.execute {
            val currentWorn = WearStateStore.readCurrentRokidWearState()
            handler.post {
                repository.appendRuntimeAudit(
                    "WEAR_STATE_RECONCILED",
                    JSONObject()
                        .put("current_worn", currentWorn ?: JSONObject.NULL)
                        .put("previous_worn", previousWorn ?: JSONObject.NULL)
                        .put("resume_suppressed", resumeSuppressed)
                        .put("runtime_state", state.name),
                )
                if (currentWorn == null) return@post
                WearStateStore.recordObservedState(this, currentWorn)
                if (!currentWorn) {
                    WearStateStore.setResumeSuppressed(this, false)
                    if (state == SessionState.ACTIVE || state == SessionState.DISCLOSURE) {
                        endSession("NOT_WORN_RECONCILED", announce = false)
                    }
                    return@post
                }
                if (
                    !resumeSuppressed &&
                    state != SessionState.ACTIVE &&
                    state != SessionState.DISCLOSURE
                ) {
                    startDisclosure("WEAR_STATE_RECONCILED")
                    requestWearDisclosureUi()
                }
            }
        }
    }

    private fun startDisclosure(startReason: String) {
        repository.appendRuntimeAudit(
            "RUNTIME_START_REQUESTED",
            JSONObject()
                .put("start_reason", startReason)
                .put("runtime_state", state.name),
        )
        if (state == SessionState.ACTIVE) {
            showDisclosureWhileActive()
            return
        }
        if (state == SessionState.DISCLOSURE) return
        if (!hasCapturePermissions()) {
            repository.openSession(startReason)
            repository.updateSessionState(SessionState.BLOCKED)
            publish(SessionState.BLOCKED, "需要相机和麦克风权限")
            return
        }
        repository.openSession(startReason)
        ensureCameraPrepared()
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

    private fun showDisclosureWhileActive() {
        disclosureGeneration += 1
        val generation = disclosureGeneration
        publish(
            SessionState.ACTIVE,
            "RealGit 已开启现实感知",
            RuntimeDisplayKind.DISCLOSURE,
        )
        presenter.speak("RealGit 已开启现实感知。")
        handler.postDelayed(
            {
                if (state == SessionState.ACTIVE && generation == disclosureGeneration) {
                    publish(
                        SessionState.ACTIVE,
                        "现实感知运行中",
                        RuntimeDisplayKind.NONE,
                    )
                }
            },
            DISCLOSURE_DELAY_MS,
        )
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

    private fun captureSystemVideoNow() {
        if (state != SessionState.ACTIVE) return
        capture(
            signalKind = "DEBUG_TEST",
            modalities = setOf(
                CaptureModality.IMAGE,
                CaptureModality.VIDEO,
                CaptureModality.SENSOR,
            ),
            useRokidSystemRecorder = true,
            systemVideoDurationMs = DEBUG_SYSTEM_VIDEO_DURATION_MS,
        )
    }

    private fun showReminder(text: String) {
        if (state != SessionState.ACTIVE) return
        reminderGeneration += 1
        val generation = reminderGeneration
        publish(state, text, RuntimeDisplayKind.REMINDER)
        openTransientUi()
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
        heartRateEvidence.start()
        heartRateBroadcast.start()
    }

    private fun stopHeartRateBroadcastPoc() {
        heartRateBroadcast.stop()
        heartRateEvidence.stop()
    }

    private fun recordHeartRateBroadcastStatus(message: String) {
        repository.appendRuntimeAudit(
            "HEART_RATE_BROADCAST_STATUS",
            JSONObject().put("message", message),
        )
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
        heartRateEvidence.append(sample)
    }

    private fun endSession(reason: String, announce: Boolean) {
        disclosureGeneration += 1
        val endGeneration = disclosureGeneration
        reminderGeneration += 1
        sensors.stop(reason)
        audio.stop()
        stopHeartRateBroadcastPoc()
        camera.suspendCapture()
        cameraReady = false
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
            publish(
                SessionState.ARMED,
                "等待佩戴",
                RuntimeDisplayKind.NONE,
            )
            return
        }
        handler.postDelayed(
            {
                if (state == SessionState.ENDED && disclosureGeneration == endGeneration) {
                    publish(
                        SessionState.ARMED,
                        "等待佩戴",
                        RuntimeDisplayKind.NONE,
                    )
                }
            },
            CANCELLED_DISPLAY_MS,
        )
    }

    private fun capture(
        signalKind: String,
        modalities: Set<CaptureModality>,
        motion: MotionTrigger? = null,
        cameraWaitAttempt: Int = 0,
        useRokidSystemRecorder: Boolean = false,
        systemVideoDurationMs: Long = MOTION_SYSTEM_VIDEO_DURATION_MS,
    ) {
        if (state != SessionState.ACTIVE) return
        val systemVideoProvidesImage =
            useRokidSystemRecorder &&
                CaptureModality.VIDEO in modalities &&
                CaptureModality.IMAGE in modalities
        val needsAppCamera =
            modalities.any {
                it == CaptureModality.IMAGE && !systemVideoProvidesImage ||
                    it == CaptureModality.VIDEO && !useRokidSystemRecorder
            }
        if (!cameraReady && needsAppCamera) {
            ensureCameraPrepared()
            if (cameraWaitAttempt < CAMERA_READY_MAX_ATTEMPTS) {
                handler.postDelayed(
                    {
                        capture(
                            signalKind = signalKind,
                            modalities = modalities,
                            motion = motion,
                            cameraWaitAttempt = cameraWaitAttempt + 1,
                            useRokidSystemRecorder = useRokidSystemRecorder,
                            systemVideoDurationMs = systemVideoDurationMs,
                        )
                    },
                    CAMERA_READY_RETRY_DELAY_MS,
                )
                return
            }
        }
        if (!captureWindowBusy.compareAndSet(false, true)) {
            repository.appendRuntimeAudit(
                "CAPTURE_SKIPPED_BUSY",
                JSONObject()
                    .put("signal_kind", signalKind)
                    .put(
                        "requested_modalities",
                        JSONArray(modalities.map { it.name }),
                    )
                    .put("reason", "ANOTHER_CAPTURE_WINDOW_IS_ACTIVE"),
            )
            return
        }
        val window = repository.beginWindow(signalKind, modalities, motion)
        val captureOperations = modalities.filterNot {
            it == CaptureModality.IMAGE && systemVideoProvidesImage
        }
        if (captureOperations.isEmpty()) {
            captureWindowBusy.set(false)
            repository.finalizeWindow(window)
            return
        }
        val remaining = AtomicInteger(captureOperations.size)
        val complete: (Boolean, String) -> Unit = { success, message ->
            if (success) {
                RuntimeStatusStore.updateLastEvidence(this, window.captureWindowId)
            }
            if (remaining.decrementAndGet() == 0) {
                repository.finalizeWindow(window)
                if (needsAppCamera) camera.suspendCapture()
                captureWindowBusy.set(false)
            }
        }

        captureOperations.forEach { modality ->
            when (modality) {
                CaptureModality.IMAGE -> {
                    if (cameraReady) camera.captureImage(window, complete)
                    else markUnavailable(window, modality, complete)
                }
                CaptureModality.VIDEO -> {
                    if (useRokidSystemRecorder) {
                        camera.captureRokidSystemVideo(
                            window = window,
                            durationMs = systemVideoDurationMs,
                            deriveRepresentativeFrame = systemVideoProvidesImage,
                            onComplete = complete,
                        )
                    } else if (cameraReady) {
                        camera.captureShortVideo(window, onComplete = complete)
                    }
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
        manager.createNotificationChannel(
            NotificationChannel(
                ALERT_NOTIFICATION_CHANNEL,
                "RealGit 提醒",
                NotificationManager.IMPORTANCE_HIGH,
            ).apply {
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            },
        )
        runCatching {
            startForeground(NOTIFICATION_ID, buildNotification("等待开始"))
        }.onSuccess {
            if (!foregroundPromotionAudited) {
                foregroundPromotionAudited = true
                repository.appendRuntimeAudit(
                    "FOREGROUND_SERVICE_PROMOTION_REQUESTED",
                    JSONObject().put("runtime_state", state.name),
                )
            }
        }.onFailure { error ->
            repository.appendRuntimeAudit(
                "FOREGROUND_SERVICE_PROMOTION_FAILED",
                JSONObject()
                    .put("runtime_state", state.name)
                    .put("error", error.message ?: error.javaClass.simpleName),
            )
        }
    }

    private fun updateNotification(message: String) {
        // Keep the notification bound to the foreground service on RV101.
        startForeground(NOTIFICATION_ID, buildNotification(message))
    }

    private fun openTransientUi(openedFromWear: Boolean = false) {
        runCatching {
            val intent = Intent(this, MainActivity::class.java)
                .addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP,
                )
            if (openedFromWear) {
                intent.putExtra(MainActivity.EXTRA_OPENED_FROM_WEAR, true)
            }
            startActivity(intent)
        }
    }

    private fun requestWearDisclosureUi() {
        wearDisclosureRequestGeneration += 1
        val requestGeneration = wearDisclosureRequestGeneration
        repository.appendRuntimeAudit(
            "WEAR_DISCLOSURE_UI_REQUESTED",
            JSONObject()
                .put("strategy", "FULL_SCREEN_NOTIFICATION_ACTIVITY_AND_TEXT_TOAST")
                .put("request_generation", requestGeneration),
        )
        runCatching {
            Toast.makeText(
                applicationContext,
                "RealGit 已开启现实感知",
                Toast.LENGTH_LONG,
            ).show()
        }.onSuccess {
            repository.appendRuntimeAudit(
                "WEAR_DISCLOSURE_TEXT_FALLBACK_REQUESTED",
                JSONObject().put("request_generation", requestGeneration),
            )
        }.onFailure { error ->
            repository.appendRuntimeAudit(
                "WEAR_DISCLOSURE_TEXT_FALLBACK_FAILED",
                JSONObject()
                    .put("request_generation", requestGeneration)
                    .put("error", error.message ?: error.javaClass.simpleName),
            )
        }
        val openIntent = PendingIntent.getActivity(
            this,
            1,
            Intent(this, MainActivity::class.java)
                .addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP,
                )
                .putExtra(MainActivity.EXTRA_OPENED_FROM_WEAR, true),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = Notification.Builder(this, ALERT_NOTIFICATION_CHANNEL)
            .setContentTitle("RealGit")
            .setContentText("已开启现实感知")
            .setSmallIcon(android.R.drawable.presence_video_online)
            .setCategory(Notification.CATEGORY_STATUS)
            .setPriority(Notification.PRIORITY_HIGH)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setContentIntent(openIntent)
            .setFullScreenIntent(openIntent, true)
            .setAutoCancel(true)
            .build()
        getSystemService(NotificationManager::class.java)
            .notify(WEAR_DISCLOSURE_NOTIFICATION_ID, notification)
        handler.postDelayed(
            { openTransientUi(openedFromWear = true) },
            WEAR_DISCLOSURE_ACTIVITY_DELAY_MS,
        )
        handler.postDelayed(
            {
                if (wearDisclosureVisibleGeneration < requestGeneration) {
                    repository.appendRuntimeAudit(
                        "WEAR_DISCLOSURE_UI_NOT_CONFIRMED",
                        JSONObject()
                            .put("request_generation", requestGeneration)
                            .put("runtime_state", state.name)
                            .put(
                                "reason",
                                "BACKGROUND_ACTIVITY_OR_FULL_SCREEN_NOTIFICATION_NOT_SHOWN",
                            ),
                    )
                }
            },
            WEAR_DISCLOSURE_CONFIRMATION_TIMEOUT_MS,
        )
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
        const val ACTION_ARM_MONITOR = "com.realitymemory.glasses.ARM_MONITOR"
        const val ACTION_WEAR_CHANGED = "com.realitymemory.glasses.WEAR_CHANGED"
        const val ACTION_TOGGLE_PAUSE = "com.realitymemory.glasses.TOGGLE_PAUSE"
        const val ACTION_REMEMBER_NOW = "com.realitymemory.glasses.REMEMBER_NOW"
        const val ACTION_TEST_SYSTEM_VIDEO =
            "com.realitymemory.glasses.TEST_SYSTEM_VIDEO"
        const val ACTION_END_SESSION = "com.realitymemory.glasses.END_SESSION"
        const val ACTION_TEST_REMINDER = "com.realitymemory.glasses.TEST_REMINDER"
        const val ACTION_DISMISS_REMINDER = "com.realitymemory.glasses.DISMISS_REMINDER"
        const val ACTION_START_HEART_RATE_BROADCAST_POC =
            "com.realitymemory.glasses.START_HEART_RATE_BROADCAST_POC"
        const val ACTION_STOP_HEART_RATE_BROADCAST_POC =
            "com.realitymemory.glasses.STOP_HEART_RATE_BROADCAST_POC"
        const val ACTION_REPORT_WEAR_DISCLOSURE_VISIBLE =
            "com.realitymemory.glasses.REPORT_WEAR_DISCLOSURE_VISIBLE"
        const val EXTRA_WORN = "worn"
        const val EXTRA_WEAR_SOURCE = "wear_source"
        const val EXTRA_REMINDER_TEXT = "reminder_text"
        const val EXTRA_START_REASON = "start_reason"

        private const val NOTIFICATION_CHANNEL = "reality_memory_runtime"
        private const val ALERT_NOTIFICATION_CHANNEL = "reality_memory_alerts"
        private const val NOTIFICATION_ID = 501
        private const val WEAR_DISCLOSURE_NOTIFICATION_ID = 502
        private const val DISCLOSURE_DELAY_MS = 5_000L
        private const val WEAR_DISCLOSURE_ACTIVITY_DELAY_MS = 350L
        private const val WEAR_DISCLOSURE_CONFIRMATION_TIMEOUT_MS = 2_500L
        private const val CANCELLED_DISPLAY_MS = 3_000L
        private const val REMINDER_DISPLAY_MS = 8_000L
        private const val MOTION_SYSTEM_VIDEO_DURATION_MS = 3_000L
        private const val DEBUG_SYSTEM_VIDEO_DURATION_MS = 5_000L
        private const val CAMERA_READY_RETRY_DELAY_MS = 150L
        private const val CAMERA_READY_MAX_ATTEMPTS = 20
    }
}
