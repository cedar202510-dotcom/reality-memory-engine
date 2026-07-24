package com.realitymemory.glasses.capture

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import com.realitymemory.glasses.evidence.EvidenceRepository
import com.realitymemory.glasses.runtime.CaptureModality
import com.realitymemory.glasses.runtime.CaptureWindowContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.FileOutputStream
import java.time.Instant
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class AudioCaptureAdapter(private val repository: EvidenceRepository) {
    private val executor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val recording = AtomicBoolean(false)

    @SuppressLint("MissingPermission")
    fun capture(
        window: CaptureWindowContext,
        requestedDurationMs: Long = 10_000L,
        onComplete: (Boolean, String) -> Unit,
    ) {
        if (!recording.compareAndSet(false, true)) {
            repository.recordAttempt(
                window,
                CaptureModality.AUDIO,
                Instant.now(),
                "SKIPPED",
                "MICROPHONE_BUSY",
                0,
                null,
            )
            onComplete(false, "麦克风正在使用")
            return
        }

        executor.execute {
            val requestedAt = Instant.now()
            val startedNs = System.nanoTime()
            val file = repository.newTemporaryFile("pcm")
            var recorder: AudioRecord? = null
            try {
                val configuration = buildRecorder()
                recorder = configuration.recorder
                recorder.startRecording()
                val capturedAt = Instant.now()
                val capturedMonotonicStartNs = SystemClock.elapsedRealtimeNanos()
                val buffer = ByteArray(configuration.bufferSize)
                val deadline = System.nanoTime() + requestedDurationMs * 1_000_000L
                var bytesWritten = 0L
                FileOutputStream(file).use { output ->
                    while (System.nanoTime() < deadline && recording.get()) {
                        val read = recorder.read(buffer, 0, buffer.size, AudioRecord.READ_BLOCKING)
                        if (read > 0) {
                            output.write(buffer, 0, read)
                            bytesWritten += read
                        } else if (read < 0) {
                            error("AudioRecord read failed: $read")
                        }
                    }
                }
                val actualDurationMs = if (configuration.channelCount > 0) {
                    bytesWritten * 1_000L /
                        (SAMPLE_RATE * configuration.channelCount * BYTES_PER_SAMPLE)
                } else {
                    requestedDurationMs
                }
                val capturedMonotonicEndNs = SystemClock.elapsedRealtimeNanos()
                val evidenceId = repository.finalizeEvidence(
                    window = window,
                    modality = CaptureModality.AUDIO,
                    sourceFile = file,
                    mimeType = "audio/L16",
                    capturedAt = capturedAt,
                    durationMs = actualDurationMs,
                    media = JSONObject()
                        .put("container", "RAW_PCM")
                        .put("codec", "PCM_S16LE")
                        .put("sample_rate_hz", SAMPLE_RATE)
                        .put("channel_count", configuration.channelCount)
                        .put("channel_mask", configuration.channelMaskLabel)
                        .put("channel_layout", configuration.channelLayout)
                        .put("audio_source", "MIC")
                        .put("capture_mode", configuration.captureMode),
                    monotonicStartNs = capturedMonotonicStartNs,
                    monotonicEndNs = capturedMonotonicEndNs,
                )
                repository.recordAttempt(
                    window,
                    CaptureModality.AUDIO,
                    requestedAt,
                    "SUCCEEDED",
                    null,
                    elapsedMs(startedNs),
                    evidenceId,
                )
                post(onComplete, true, "短音频已进入加密队列")
            } catch (error: Throwable) {
                file.delete()
                repository.recordAttempt(
                    window,
                    CaptureModality.AUDIO,
                    requestedAt,
                    "FAILED",
                    "DEVICE_UNAVAILABLE",
                    elapsedMs(startedNs),
                    null,
                )
                post(onComplete, false, "录音失败：${error.message}")
            } finally {
                recording.set(false)
                runCatching { recorder?.stop() }
                recorder?.release()
            }
        }
    }

    fun stop() {
        recording.set(false)
    }

    fun shutdown() {
        stop()
        executor.shutdown()
    }

    private fun buildRecorder(): AudioConfiguration {
        return runCatching { buildEightChannelRecorder() }
            .getOrElse { buildMonoRecorder() }
    }

    @SuppressLint("MissingPermission")
    private fun buildEightChannelRecorder(): AudioConfiguration {
        val format = AudioFormat.Builder()
            .setSampleRate(SAMPLE_RATE)
            .setChannelMask(ROKID_EIGHT_CHANNEL_MASK)
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .build()
        val minimum = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            ROKID_EIGHT_CHANNEL_MASK,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val recorder = AudioRecord.Builder()
            .setAudioSource(MediaRecorder.AudioSource.MIC)
            .setAudioFormat(format)
            .setBufferSizeInBytes(maxOf(minimum, 16_384))
            .build()
        check(recorder.state == AudioRecord.STATE_INITIALIZED) { "8-channel AudioRecord unavailable" }
        return AudioConfiguration(
            recorder = recorder,
            bufferSize = maxOf(minimum, 16_384),
            channelCount = recorder.channelCount,
            channelMaskLabel = "0x6000FC",
            channelLayout = JSONArray(
                listOf(
                    "PROCESSED_0",
                    "PROCESSED_1",
                    "RAW_MIC_0",
                    "RAW_MIC_1",
                    "RAW_MIC_2",
                    "RAW_MIC_3",
                    "HARDWARE_ECHO_0",
                    "HARDWARE_ECHO_1",
                ),
            ),
            captureMode = "ROKID_RAW_8_CHANNEL",
        )
    }

    @SuppressLint("MissingPermission")
    private fun buildMonoRecorder(): AudioConfiguration {
        val minimum = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val recorder = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minimum, 4_096),
        )
        check(recorder.state == AudioRecord.STATE_INITIALIZED) { "Mono AudioRecord unavailable" }
        return AudioConfiguration(
            recorder = recorder,
            bufferSize = maxOf(minimum, 4_096),
            channelCount = recorder.channelCount,
            channelMaskLabel = "CHANNEL_IN_MONO",
            channelLayout = JSONArray(listOf("MONO")),
            captureMode = "ANDROID_MONO_FALLBACK",
        )
    }

    private fun post(callback: (Boolean, String) -> Unit, success: Boolean, message: String) {
        mainHandler.post { callback(success, message) }
    }

    private fun elapsedMs(startedNs: Long) = (System.nanoTime() - startedNs) / 1_000_000L

    private data class AudioConfiguration(
        val recorder: AudioRecord,
        val bufferSize: Int,
        val channelCount: Int,
        val channelMaskLabel: String,
        val channelLayout: JSONArray,
        val captureMode: String,
    )

    companion object {
        private const val SAMPLE_RATE = 16_000
        private const val BYTES_PER_SAMPLE = 2
        private const val ROKID_EIGHT_CHANNEL_MASK = 0x6000FC
    }
}
