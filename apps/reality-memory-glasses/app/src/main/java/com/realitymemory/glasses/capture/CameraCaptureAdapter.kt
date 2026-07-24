package com.realitymemory.glasses.capture

import android.graphics.BitmapFactory
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.MediaMetadataRetriever
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.video.FallbackStrategy
import androidx.camera.video.FileOutputOptions
import androidx.camera.video.Quality
import androidx.camera.video.QualitySelector
import androidx.camera.video.Recorder
import androidx.camera.video.Recording
import androidx.camera.video.VideoCapture
import androidx.camera.video.VideoRecordEvent
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import com.realitymemory.glasses.evidence.EvidenceRepository
import com.realitymemory.glasses.runtime.CaptureModality
import com.realitymemory.glasses.runtime.CaptureWindowContext
import org.json.JSONObject
import java.time.Instant
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

class CameraCaptureAdapter(
    private val service: LifecycleService,
    private val repository: EvidenceRepository,
) {
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val imageBusy = AtomicBoolean(false)
    private val videoBusy = AtomicBoolean(false)

    private var provider: ProcessCameraProvider? = null
    private var imageCapture: ImageCapture? = null
    private var videoCapture: VideoCapture<Recorder>? = null
    private var cameraFacing = "UNKNOWN"
    @Volatile private var activeRecording: Recording? = null

    fun prepare(onReady: (Boolean, String?) -> Unit) {
        val future = ProcessCameraProvider.getInstance(service)
        future.addListener({
            runCatching {
                val cameraProvider = future.get()
                val selector = selectAvailableCamera(cameraProvider)
                val image = ImageCapture.Builder()
                    .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                    .setJpegQuality(92)
                    .build()
                val recorder = Recorder.Builder()
                    .setQualitySelector(
                        QualitySelector.fromOrderedList(
                            listOf(Quality.HD, Quality.SD),
                            FallbackStrategy.lowerQualityOrHigherThan(Quality.SD),
                        ),
                    )
                    .build()
                val video = VideoCapture.withOutput(recorder)
                val combinedFailure = runCatching {
                    cameraProvider.unbindAll()
                    cameraProvider.bindToLifecycle(service, selector, image, video)
                }.exceptionOrNull()
                if (combinedFailure != null) {
                    cameraProvider.unbindAll()
                    cameraProvider.bindToLifecycle(service, selector, image)
                    videoCapture = null
                    repository.appendRuntimeAudit(
                        "CAMERA_PREPARED_IMAGE_ONLY",
                        cameraDiagnostic()
                            .put("combined_bind_error", describe(combinedFailure)),
                    )
                } else {
                    videoCapture = video
                    repository.appendRuntimeAudit("CAMERA_PREPARED", cameraDiagnostic())
                }
                provider = cameraProvider
                imageCapture = image
                onReady(
                    true,
                    if (combinedFailure == null) null else "视频用例组合不受支持，已降级为拍照",
                )
            }.onFailure { error ->
                repository.appendRuntimeAudit(
                    "CAMERA_PREPARE_FAILED",
                    cameraDiagnostic().put("error", describe(error)),
                )
                onReady(false, "${error.javaClass.simpleName}: ${error.message}")
            }
        }, ContextCompat.getMainExecutor(service))
    }

    fun captureImage(window: CaptureWindowContext, onComplete: (Boolean, String) -> Unit) {
        val capture = imageCapture
        if (capture == null) {
            recordFailure(window, CaptureModality.IMAGE, "DEVICE_UNAVAILABLE", onComplete)
            return
        }
        if (!imageBusy.compareAndSet(false, true) || videoBusy.get()) {
            recordFailure(window, CaptureModality.IMAGE, "CAMERA_BUSY", onComplete, "SKIPPED")
            return
        }

        val requestedAt = Instant.now()
        val startedNs = System.nanoTime()
        val capturedMonotonicStartNs = SystemClock.elapsedRealtimeNanos()
        val file = repository.newTemporaryFile("jpg")
        val options = ImageCapture.OutputFileOptions.Builder(file).build()
        capture.takePicture(
            options,
            executor,
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                    imageBusy.set(false)
                    val dimensions = BitmapFactory.Options().also {
                        it.inJustDecodeBounds = true
                        BitmapFactory.decodeFile(file.absolutePath, it)
                    }
                    val evidenceId = runCatching {
                        repository.finalizeEvidence(
                            window = window,
                            modality = CaptureModality.IMAGE,
                            sourceFile = file,
                            mimeType = "image/jpeg",
                            capturedAt = requestedAt,
                            durationMs = 0,
                            media = JSONObject()
                                .put("codec", "JPEG")
                                .put("width_px", dimensions.outWidth)
                                .put("height_px", dimensions.outHeight)
                                .put("orientation_deg", 0)
                                .put("camera_facing", cameraFacing)
                                .put("capture_mode", "CAMERAX_IMAGE_CAPTURE_NO_PREVIEW")
                                .put("jpeg_quality", 92),
                            monotonicStartNs = capturedMonotonicStartNs,
                            monotonicEndNs = SystemClock.elapsedRealtimeNanos(),
                        )
                    }.getOrElse { error ->
                        file.delete()
                        repository.recordAttempt(
                            window,
                            CaptureModality.IMAGE,
                            requestedAt,
                            "FAILED",
                            "FINALIZE_FAILED",
                            elapsedMs(startedNs),
                            null,
                        )
                        postResult(onComplete, false, "图片写入失败：${error.message}")
                        return
                    }
                    repository.recordAttempt(
                        window,
                        CaptureModality.IMAGE,
                        requestedAt,
                        "SUCCEEDED",
                        null,
                        elapsedMs(startedNs),
                        evidenceId,
                    )
                    postResult(onComplete, true, "图片已进入加密队列")
                }

                override fun onError(exception: ImageCaptureException) {
                    imageBusy.set(false)
                    file.delete()
                    repository.recordAttempt(
                        window,
                        CaptureModality.IMAGE,
                        requestedAt,
                        "FAILED",
                        "DEVICE_UNAVAILABLE",
                        elapsedMs(startedNs),
                        null,
                    )
                    postResult(onComplete, false, "拍照失败：${exception.message}")
                }
            },
        )
    }

    fun captureShortVideo(
        window: CaptureWindowContext,
        durationMs: Long = 2_500L,
        onComplete: (Boolean, String) -> Unit,
    ) {
        val capture = videoCapture
        if (capture == null) {
            recordFailure(window, CaptureModality.VIDEO, "DEVICE_UNAVAILABLE", onComplete)
            return
        }
        if (!videoBusy.compareAndSet(false, true) || imageBusy.get()) {
            recordFailure(window, CaptureModality.VIDEO, "CAMERA_BUSY", onComplete, "SKIPPED")
            return
        }

        val requestedAt = Instant.now()
        val startedNs = System.nanoTime()
        val capturedMonotonicStartNs = SystemClock.elapsedRealtimeNanos()
        val file = repository.newTemporaryFile("mp4")
        val recording = capture.output
            .prepareRecording(service, FileOutputOptions.Builder(file).build())
            .start(executor) { event ->
                if (event is VideoRecordEvent.Finalize) {
                    activeRecording = null
                    videoBusy.set(false)
                    if (event.hasError() || !file.exists() || file.length() == 0L) {
                        file.delete()
                        repository.recordAttempt(
                            window,
                            CaptureModality.VIDEO,
                            requestedAt,
                            "FAILED",
                            "FINALIZE_FAILED",
                            elapsedMs(startedNs),
                            null,
                        )
                        postResult(onComplete, false, "短视频失败：${event.cause?.message ?: event.error}")
                        return@start
                    }
                    val metadata = readVideoMetadata(file)
                    val evidenceId = runCatching {
                        repository.finalizeEvidence(
                            window = window,
                            modality = CaptureModality.VIDEO,
                            sourceFile = file,
                            mimeType = "video/mp4",
                            capturedAt = requestedAt,
                            durationMs = metadata.durationMs,
                            media = JSONObject()
                                .put("container", "MP4")
                                .put("video_codec", "DEVICE_ENCODER")
                                .put("width_px", metadata.width)
                                .put("height_px", metadata.height)
                                .put("frame_rate_fps", metadata.frameRate ?: JSONObject.NULL)
                                .put("has_audio_track", false)
                                .put("capture_mode", "CAMERAX_VIDEO_CAPTURE_NO_PREVIEW")
                                .put("finalize_status", "SUCCESS"),
                            monotonicStartNs = capturedMonotonicStartNs,
                            monotonicEndNs = SystemClock.elapsedRealtimeNanos(),
                        )
                    }.getOrElse { error ->
                        file.delete()
                        repository.recordAttempt(
                            window,
                            CaptureModality.VIDEO,
                            requestedAt,
                            "FAILED",
                            "FINALIZE_FAILED",
                            elapsedMs(startedNs),
                            null,
                        )
                        postResult(onComplete, false, "视频写入失败：${error.message}")
                        return@start
                    }
                    repository.recordAttempt(
                        window,
                        CaptureModality.VIDEO,
                        requestedAt,
                        "SUCCEEDED",
                        null,
                        elapsedMs(startedNs),
                        evidenceId,
                    )
                    postResult(onComplete, true, "短视频已进入加密队列")
                }
            }
        activeRecording = recording
        mainHandler.postDelayed({ recording.stop() }, durationMs)
    }

    fun stopActiveRecording() {
        activeRecording?.stop()
        activeRecording = null
    }

    fun shutdown() {
        stopActiveRecording()
        provider?.unbindAll()
        executor.shutdown()
    }

    private fun selectAvailableCamera(cameraProvider: ProcessCameraProvider): CameraSelector {
        return when {
            cameraProvider.hasCamera(CameraSelector.DEFAULT_BACK_CAMERA) -> {
                cameraFacing = "WORLD_BACK"
                CameraSelector.DEFAULT_BACK_CAMERA
            }
            cameraProvider.hasCamera(CameraSelector.DEFAULT_FRONT_CAMERA) -> {
                cameraFacing = "WORLD_FRONT_DECLARED"
                CameraSelector.DEFAULT_FRONT_CAMERA
            }
            else -> error("CameraX did not expose a back or front camera")
        }
    }

    private fun cameraDiagnostic(): JSONObject {
        val result = JSONObject().put("camera_facing", cameraFacing)
        val manager = service.getSystemService(CameraManager::class.java) ?: return result
        val cameras = org.json.JSONArray()
        runCatching {
            manager.cameraIdList.forEach { cameraId ->
                val characteristics = manager.getCameraCharacteristics(cameraId)
                cameras.put(
                    JSONObject()
                        .put("camera_id", cameraId)
                        .put(
                            "lens_facing",
                            characteristics.get(CameraCharacteristics.LENS_FACING)
                                ?: JSONObject.NULL,
                        )
                        .put(
                            "hardware_level",
                            characteristics.get(
                                CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL,
                            ) ?: JSONObject.NULL,
                        ),
                )
            }
        }.onFailure { result.put("inventory_error", describe(it)) }
        return result.put("camera_inventory", cameras)
    }

    private fun describe(error: Throwable): String =
        "${error.javaClass.simpleName}: ${error.message}"

    private fun recordFailure(
        window: CaptureWindowContext,
        modality: CaptureModality,
        reason: String,
        onComplete: (Boolean, String) -> Unit,
        result: String = "FAILED",
    ) {
        repository.recordAttempt(
            window,
            modality,
            Instant.now(),
            result,
            reason,
            0,
            null,
        )
        postResult(onComplete, false, reason)
    }

    private fun postResult(callback: (Boolean, String) -> Unit, success: Boolean, message: String) {
        mainHandler.post { callback(success, message) }
    }

    private fun elapsedMs(startedNs: Long) = (System.nanoTime() - startedNs) / 1_000_000L

    private fun readVideoMetadata(file: java.io.File): VideoMetadata {
        val retriever = MediaMetadataRetriever()
        return try {
            retriever.setDataSource(file.absolutePath)
            VideoMetadata(
                durationMs = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                    ?.toLongOrNull() ?: 0L,
                width = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH)
                    ?.toIntOrNull() ?: 0,
                height = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_HEIGHT)
                    ?.toIntOrNull() ?: 0,
                frameRate = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_CAPTURE_FRAMERATE)
                    ?.toDoubleOrNull(),
            )
        } finally {
            retriever.release()
        }
    }

    private data class VideoMetadata(
        val durationMs: Long,
        val width: Int,
        val height: Int,
        val frameRate: Double?,
    )
}
