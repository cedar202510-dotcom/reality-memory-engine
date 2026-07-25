package com.realitymemory.glasses.sensor

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import com.realitymemory.glasses.BuildConfig
import com.realitymemory.glasses.evidence.EvidenceRepository
import com.realitymemory.glasses.runtime.CaptureModality
import com.realitymemory.glasses.runtime.CaptureWindowContext
import com.realitymemory.glasses.runtime.MotionTrigger
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.time.Instant
import java.util.ArrayDeque
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class GlassSensorAdapter(
    context: Context,
    private val repository: EvidenceRepository,
    private val onMotionTrigger: (MotionTrigger) -> Unit,
) : SensorEventListener {
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val accelerometer =
        sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER, true)
            ?: sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroscope =
        sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE, true)
            ?: sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
    private val triggerEngine = MotionTriggerEngine()
    private val buffer = ArrayDeque<MotionSample>()
    private val pendingWindows = mutableListOf<PendingSensorWindow>()
    private val ioExecutor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val liveSnapshotFile =
        File(context.filesDir, "reality-memory/runtime/live-sensor.json")
    private val liveSnapshotWritePending = AtomicBoolean(false)

    private var running = false
    private var sequence = 0L
    private var lastLiveSnapshotNs = 0L
    private var lastSampleReceivedNs = 0L
    private var restartCount = 0
    private var lastTrigger: MotionTrigger? = null
    private var ax = 0f
    private var ay = 0f
    private var az = 0f
    private var gx = 0f
    private var gy = 0f
    private var gz = 0f
    private var accelAccuracy = SensorManager.SENSOR_STATUS_UNRELIABLE
    private var gyroAccuracy = SensorManager.SENSOR_STATUS_UNRELIABLE

    val available: Boolean
        get() = accelerometer != null && gyroscope != null

    private val streamWatchdog = object : Runnable {
        override fun run() {
            if (!running) return
            val stalledForMs =
                (SystemClock.elapsedRealtimeNanos() - lastSampleReceivedNs) / 1_000_000L
            if (stalledForMs >= STREAM_STALL_TIMEOUT_MS) {
                repository.appendRuntimeAudit(
                    "SENSOR_STREAM_STALLED",
                    sensorDetail()
                        .put("stalled_for_ms", stalledForMs)
                        .put("restart_count", restartCount),
                )
                restartRegistrations()
            }
            if (running) mainHandler.postDelayed(this, STREAM_WATCHDOG_INTERVAL_MS)
        }
    }

    fun start(): Boolean {
        if (running) return true
        val accel = accelerometer ?: return false
        val gyro = gyroscope ?: return false
        triggerEngine.reset()
        buffer.clear()
        sequence = 0
        lastLiveSnapshotNs = 0
        lastSampleReceivedNs = SystemClock.elapsedRealtimeNanos()
        restartCount = 0
        lastTrigger = null
        val accelerometerStarted =
            sensorManager.registerListener(this, accel, SensorManager.SENSOR_DELAY_GAME)
        val gyroscopeStarted =
            sensorManager.registerListener(this, gyro, SensorManager.SENSOR_DELAY_GAME)
        running = accelerometerStarted && gyroscopeStarted
        if (!running) sensorManager.unregisterListener(this)
        repository.appendRuntimeAudit(
            if (running) "SENSOR_LISTENER_STARTED" else "SENSOR_LISTENER_FAILED",
            sensorDetail()
                .put("accelerometer_registered", accelerometerStarted)
                .put("gyroscope_registered", gyroscopeStarted),
        )
        mainHandler.removeCallbacks(streamWatchdog)
        if (running) mainHandler.postDelayed(streamWatchdog, STREAM_WATCHDOG_INTERVAL_MS)
        return running
    }

    fun stop(reason: String = "SESSION_ENDED") {
        if (!running) return
        mainHandler.removeCallbacks(streamWatchdog)
        sensorManager.unregisterListener(this)
        running = false
        pendingWindows.toList().forEach { finalizePending(it, cancelled = true) }
        pendingWindows.clear()
        buffer.clear()
        repository.appendRuntimeAudit(
            "SENSOR_LISTENER_STOPPED",
            sensorDetail().put("reason", reason),
        )
        publishStoppedSnapshot(reason)
    }

    fun captureWindow(
        window: CaptureWindowContext,
        postTriggerMs: Long = 4_000L,
        onComplete: (Boolean, String) -> Unit,
    ) {
        val requestedAt = Instant.now()
        if (!running) {
            repository.recordAttempt(
                window,
                CaptureModality.SENSOR,
                requestedAt,
                "FAILED",
                "DEVICE_UNAVAILABLE",
                0,
                null,
            )
            onComplete(false, "眼镜 IMU 不可用")
            return
        }
        pendingWindows += PendingSensorWindow(
            window = window,
            requestedAt = requestedAt,
            startedNs = System.nanoTime(),
            deadlineMonotonicNs = android.os.SystemClock.elapsedRealtimeNanos() + postTriggerMs * 1_000_000L,
            samples = buffer.toMutableList(),
            onComplete = onComplete,
        )
    }

    override fun onSensorChanged(event: SensorEvent) {
        lastSampleReceivedNs = SystemClock.elapsedRealtimeNanos()
        when (event.sensor.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                ax = event.values[0]
                ay = event.values[1]
                az = event.values[2]
            }

            Sensor.TYPE_GYROSCOPE -> {
                gx = event.values[0]
                gy = event.values[1]
                gz = event.values[2]
                publishSample(event.timestamp)
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        when (sensor?.type) {
            Sensor.TYPE_ACCELEROMETER -> accelAccuracy = accuracy
            Sensor.TYPE_GYROSCOPE -> gyroAccuracy = accuracy
        }
    }

    fun shutdown() {
        stop("SERVICE_DESTROYED")
        ioExecutor.shutdown()
    }

    private fun restartRegistrations() {
        val accel = accelerometer ?: return
        val gyro = gyroscope ?: return
        sensorManager.unregisterListener(this)
        val accelerometerStarted =
            sensorManager.registerListener(this, accel, SensorManager.SENSOR_DELAY_GAME)
        val gyroscopeStarted =
            sensorManager.registerListener(this, gyro, SensorManager.SENSOR_DELAY_GAME)
        running = accelerometerStarted && gyroscopeStarted
        restartCount += 1
        lastSampleReceivedNs = SystemClock.elapsedRealtimeNanos()
        repository.appendRuntimeAudit(
            if (running) "SENSOR_LISTENER_RESTARTED" else "SENSOR_LISTENER_RESTART_FAILED",
            sensorDetail()
                .put("accelerometer_registered", accelerometerStarted)
                .put("gyroscope_registered", gyroscopeStarted)
                .put("restart_count", restartCount),
        )
        if (!running) {
            sensorManager.unregisterListener(this)
            publishStoppedSnapshot("RESTART_FAILED")
        }
    }

    private fun publishSample(monotonicNs: Long) {
        val sample = MotionSample(
            wallClockEpochMs = System.currentTimeMillis(),
            monotonicNs = monotonicNs,
            ax = ax,
            ay = ay,
            az = az,
            gx = gx,
            gy = gy,
            gz = gz,
            accuracy = minOf(accelAccuracy, gyroAccuracy),
        )
        sequence += 1
        buffer.addLast(sample)
        val cutoff = monotonicNs - PRE_TRIGGER_BUFFER_NS
        while (buffer.isNotEmpty() && buffer.first().monotonicNs < cutoff) buffer.removeFirst()

        pendingWindows.forEach { it.samples += sample }
        val completed = pendingWindows.filter { monotonicNs >= it.deadlineMonotonicNs }
        completed.forEach {
            pendingWindows.remove(it)
            finalizePending(it, cancelled = false)
        }

        val trigger = triggerEngine.accept(sample)
        if (trigger != null) lastTrigger = trigger
        publishLiveDebugSnapshot(sample)
        trigger?.let(onMotionTrigger)
    }

    private fun publishLiveDebugSnapshot(latest: MotionSample) {
        if (!BuildConfig.DEBUG) return
        if (latest.monotonicNs - lastLiveSnapshotNs < LIVE_SNAPSHOT_INTERVAL_NS) return
        if (!liveSnapshotWritePending.compareAndSet(false, true)) return
        lastLiveSnapshotNs = latest.monotonicNs
        val debugState = triggerEngine.debugState()
        val samples = buffer.toList()
            .filterIndexed { index, _ -> index % LIVE_SAMPLE_DOWNSAMPLE == 0 }
            .takeLast(LIVE_SAMPLE_LIMIT)
        val json = JSONObject()
            .put("schema_ref", "rme.debug-live-sensor.v1")
            .put("active", running)
            .put("stream_status", "RECEIVING")
            .put("sensor_mode", sensorMode())
            .put("updated_at", Instant.ofEpochMilli(latest.wallClockEpochMs).toString())
            .put("sequence", sequence)
            .put("sample_rate_target_hz", 50)
            .put("phase", debugState.phase)
            .put("start_threshold_rad_s", debugState.startThresholdRadS)
            .put("baseline_mean_rad_s", debugState.baselineMeanRadS)
            .put(
                "baseline_standard_deviation_rad_s",
                debugState.baselineStandardDeviationRadS,
            )
            .put("baseline_sample_count", debugState.baselineSampleCount)
            .put(
                "latest",
                motionSampleJson(latest),
            )
            .put(
                "last_trigger",
                lastTrigger?.let(::motionTriggerJson) ?: JSONObject.NULL,
            )
            .put(
                "samples",
                JSONArray().apply {
                    samples.forEach { put(motionSampleJson(it)) }
                },
            )
        ioExecutor.execute {
            val temporary = File(liveSnapshotFile.parentFile, ".live-sensor.json.tmp")
            runCatching {
                liveSnapshotFile.parentFile?.mkdirs()
                temporary.writeText(json.toString())
                check(temporary.renameTo(liveSnapshotFile)) {
                    "无法替换六轴实时快照"
                }
            }.onFailure {
                temporary.delete()
            }
            liveSnapshotWritePending.set(false)
        }
    }

    private fun publishStoppedSnapshot(reason: String) {
        if (!BuildConfig.DEBUG || ioExecutor.isShutdown) return
        val json = JSONObject()
            .put("schema_ref", "rme.debug-live-sensor.v1")
            .put("active", false)
            .put("stream_status", "STOPPED")
            .put("stop_reason", reason)
            .put("sensor_mode", sensorMode())
            .put("updated_at", Instant.now().toString())
            .put("sequence", sequence)
            .put("sample_rate_target_hz", 50)
            .put("phase", "STOPPED")
            .put("samples", JSONArray())
        ioExecutor.execute {
            liveSnapshotFile.parentFile?.mkdirs()
            liveSnapshotFile.writeText(json.toString())
        }
    }

    private fun sensorMode(): String =
        if (accelerometer?.isWakeUpSensor == true && gyroscope?.isWakeUpSensor == true) {
            "WAKE_UP"
        } else {
            "NON_WAKE_UP"
        }

    private fun sensorDetail(): JSONObject =
        JSONObject()
            .put("sensor_mode", sensorMode())
            .put("accelerometer_name", accelerometer?.name ?: JSONObject.NULL)
            .put("gyroscope_name", gyroscope?.name ?: JSONObject.NULL)

    private fun motionSampleJson(sample: MotionSample): JSONObject =
        JSONObject()
            .put("occurred_at", Instant.ofEpochMilli(sample.wallClockEpochMs).toString())
            .put("monotonic_ns", sample.monotonicNs)
            .put("ax_m_s2", sample.ax)
            .put("ay_m_s2", sample.ay)
            .put("az_m_s2", sample.az)
            .put("gx_rad_s", sample.gx)
            .put("gy_rad_s", sample.gy)
            .put("gz_rad_s", sample.gz)
            .put("gyro_magnitude_rad_s", sample.gyroMagnitude)
            .put("linear_acceleration_m_s2", sample.linearAccelerationMagnitude)
            .put("accuracy", sample.accuracy)

    private fun motionTriggerJson(trigger: MotionTrigger): JSONObject =
        JSONObject()
            .put("occurred_at", Instant.ofEpochMilli(trigger.occurredAtEpochMs).toString())
            .put("duration_ms", trigger.durationMs)
            .put("peak_gyro_rad_s", trigger.peakGyroRadS)
            .put("integrated_rotation_deg", trigger.integratedRotationDeg)
            .put("max_linear_acceleration_m_s2", trigger.maxLinearAcceleration)
            .put("intensity", trigger.intensity)

    private fun finalizePending(pending: PendingSensorWindow, cancelled: Boolean) {
        if (cancelled) {
            repository.recordAttempt(
                pending.window,
                CaptureModality.SENSOR,
                pending.requestedAt,
                "CANCELLED",
                "USER_PAUSED",
                elapsedMs(pending.startedNs),
                null,
            )
            pending.onComplete(false, "IMU 窗口已取消")
            return
        }
        ioExecutor.execute {
            val file = repository.newTemporaryFile("ndjson")
            runCatching {
                FileOutputStream(file).bufferedWriter().use { output ->
                    pending.samples.forEachIndexed { index, sample ->
                        output.append(
                            JSONObject()
                                .put("sequence", index)
                                .put("occurred_at", Instant.ofEpochMilli(sample.wallClockEpochMs).toString())
                                .put("monotonic_ns", sample.monotonicNs)
                                .put("ax_m_s2", sample.ax)
                                .put("ay_m_s2", sample.ay)
                                .put("az_m_s2", sample.az)
                                .put("gx_rad_s", sample.gx)
                                .put("gy_rad_s", sample.gy)
                                .put("gz_rad_s", sample.gz)
                                .put("accuracy", sample.accuracy)
                                .toString(),
                        ).append('\n')
                    }
                }
                val firstSample = pending.samples.first()
                val lastSample = pending.samples.last()
                val durationMs = pending.samples.durationMs()
                val evidenceId = repository.finalizeEvidence(
                    window = pending.window,
                    modality = CaptureModality.SENSOR,
                    sourceFile = file,
                    mimeType = "application/x-ndjson",
                    capturedAt = Instant.ofEpochMilli(firstSample.wallClockEpochMs),
                    durationMs = durationMs,
                    media = JSONObject()
                        .put("format", "NDJSON")
                        .put("sensor_types", JSONArray(listOf("ACCELEROMETER", "GYROSCOPE")))
                        .put("coordinate_frame", "ANDROID_DEVICE_FRAME")
                        .put("mount_position", "GLASSES_NATIVE")
                        .put(
                            "axis_definition",
                            JSONObject()
                                .put("x", "UNVERIFIED_RV101")
                                .put("y", "UNVERIFIED_RV101")
                                .put("z", "UNVERIFIED_RV101"),
                        )
                        .put(
                            "units",
                            JSONObject()
                                .put("accelerometer", "METER_PER_SECOND_SQUARED")
                                .put("gyroscope", "RADIAN_PER_SECOND"),
                        )
                        .put("requested_sampling_mode", "SENSOR_DELAY_GAME")
                        .put("actual_sample_count", pending.samples.size)
                        .put(
                            "actual_sample_rate_hz",
                            if (durationMs > 0) {
                                (pending.samples.size - 1) * 1_000.0 / durationMs
                            } else {
                                JSONObject.NULL
                            },
                        )
                        .put("calibration_profile", "rv101-axis/unknown"),
                    monotonicStartNs = firstSample.monotonicNs,
                    monotonicEndNs = lastSample.monotonicNs,
                )
                repository.recordAttempt(
                    pending.window,
                    CaptureModality.SENSOR,
                    pending.requestedAt,
                    "SUCCEEDED",
                    null,
                    elapsedMs(pending.startedNs),
                    evidenceId,
                )
            }.onSuccess {
                mainHandler.post { pending.onComplete(true, "IMU 窗口已进入加密队列") }
            }.onFailure { error ->
                file.delete()
                repository.recordAttempt(
                    pending.window,
                    CaptureModality.SENSOR,
                    pending.requestedAt,
                    "FAILED",
                    "FINALIZE_FAILED",
                    elapsedMs(pending.startedNs),
                    null,
                )
                mainHandler.post { pending.onComplete(false, "IMU 写入失败：${error.message}") }
            }
        }
    }

    private fun List<MotionSample>.durationMs(): Long {
        if (size < 2) return 0
        return ((last().monotonicNs - first().monotonicNs) / 1_000_000L).coerceAtLeast(0)
    }

    private fun elapsedMs(startedNs: Long) = (System.nanoTime() - startedNs) / 1_000_000L

    private data class PendingSensorWindow(
        val window: CaptureWindowContext,
        val requestedAt: Instant,
        val startedNs: Long,
        val deadlineMonotonicNs: Long,
        val samples: MutableList<MotionSample>,
        val onComplete: (Boolean, String) -> Unit,
    )

    companion object {
        private const val STREAM_STALL_TIMEOUT_MS = 5_000L
        private const val STREAM_WATCHDOG_INTERVAL_MS = 2_500L
        private const val PRE_TRIGGER_BUFFER_NS = 4_000_000_000L
        private const val LIVE_SNAPSHOT_INTERVAL_NS = 200_000_000L
        private const val LIVE_SAMPLE_DOWNSAMPLE = 2
        private const val LIVE_SAMPLE_LIMIT = 120
    }
}
