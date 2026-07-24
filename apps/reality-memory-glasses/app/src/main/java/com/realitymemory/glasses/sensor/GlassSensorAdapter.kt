package com.realitymemory.glasses.sensor

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Handler
import android.os.Looper
import com.realitymemory.glasses.evidence.EvidenceRepository
import com.realitymemory.glasses.runtime.CaptureModality
import com.realitymemory.glasses.runtime.CaptureWindowContext
import com.realitymemory.glasses.runtime.MotionTrigger
import org.json.JSONArray
import org.json.JSONObject
import java.io.FileOutputStream
import java.time.Instant
import java.util.ArrayDeque
import java.util.concurrent.Executors

class GlassSensorAdapter(
    context: Context,
    private val repository: EvidenceRepository,
    private val onMotionTrigger: (MotionTrigger) -> Unit,
) : SensorEventListener {
    private val sensorManager = context.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val gyroscope = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
    private val triggerEngine = MotionTriggerEngine()
    private val buffer = ArrayDeque<MotionSample>()
    private val pendingWindows = mutableListOf<PendingSensorWindow>()
    private val ioExecutor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())

    private var running = false
    private var sequence = 0L
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

    fun start(): Boolean {
        if (running) return true
        val accel = accelerometer ?: return false
        val gyro = gyroscope ?: return false
        triggerEngine.reset()
        buffer.clear()
        sequence = 0
        val accelerometerStarted =
            sensorManager.registerListener(this, accel, SensorManager.SENSOR_DELAY_GAME)
        val gyroscopeStarted =
            sensorManager.registerListener(this, gyro, SensorManager.SENSOR_DELAY_GAME)
        running = accelerometerStarted && gyroscopeStarted
        if (!running) sensorManager.unregisterListener(this)
        return running
    }

    fun stop() {
        if (!running) return
        sensorManager.unregisterListener(this)
        running = false
        pendingWindows.toList().forEach { finalizePending(it, cancelled = true) }
        pendingWindows.clear()
        buffer.clear()
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
        stop()
        ioExecutor.shutdown()
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

        triggerEngine.accept(sample)?.let(onMotionTrigger)
    }

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
                val evidenceId = repository.finalizeEvidence(
                    window = pending.window,
                    modality = CaptureModality.SENSOR,
                    sourceFile = file,
                    mimeType = "application/x-ndjson",
                    capturedAt = pending.requestedAt,
                    durationMs = pending.samples.durationMs(),
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
                        .put("calibration_profile", "rv101-axis/unknown"),
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
        private const val PRE_TRIGGER_BUFFER_NS = 4_000_000_000L
    }
}
