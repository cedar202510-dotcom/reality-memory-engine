package com.realitymemory.glasses.capture

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.MediaMetadataRetriever
import android.media.MediaRecorder
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
import org.json.JSONArray
import org.json.JSONObject
import java.io.FileOutputStream
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
    private val cameraBusy = AtomicBoolean(false)
    private val systemRecorder = RokidSystemRecordingClient(service)

    private var provider: ProcessCameraProvider? = null
    private var selector: CameraSelector? = null
    private var imageCapture: ImageCapture? = null
    private var videoCapture: VideoCapture<Recorder>? = null
    private var cameraFacing = "UNKNOWN"
    private var boundMode = BoundMode.NONE
    @Volatile private var activeRecording: Recording? = null
    private var activeStopRunnable: Runnable? = null
    @Volatile private var systemRecordingActive = false

    fun prepare(onReady: (Boolean, String?) -> Unit) {
        val systemRecorderConnected = systemRecorder.connect()
        repository.appendRuntimeAudit(
            "ROKID_SYSTEM_RECORDER_BIND_REQUESTED",
            JSONObject().put("connected_immediately", systemRecorderConnected),
        )
        if (provider != null && selector != null && boundMode == BoundMode.IMAGE) {
            onReady(true, null)
            return
        }
        val future = ProcessCameraProvider.getInstance(service)
        future.addListener({
            runCatching {
                val cameraProvider = future.get()
                val cameraSelector = selectAvailableCamera(cameraProvider)
                provider = cameraProvider
                selector = cameraSelector
                bindImageMode("SERVICE_PREPARE")
                repository.appendRuntimeAudit("CAMERA_PREPARED_IMAGE_ONLY", cameraDiagnostic())
                onReady(true, null)
            }.onFailure { error ->
                provider?.unbindAll()
                imageCapture = null
                videoCapture = null
                boundMode = BoundMode.NONE
                repository.appendRuntimeAudit(
                    "CAMERA_PREPARE_FAILED",
                    cameraDiagnostic().put("error", describe(error)),
                )
                onReady(false, "${error.javaClass.simpleName}: ${error.message}")
            }
        }, ContextCompat.getMainExecutor(service))
    }

    fun captureImage(window: CaptureWindowContext, onComplete: (Boolean, String) -> Unit) {
        if (!cameraBusy.compareAndSet(false, true)) {
            recordFailure(window, CaptureModality.IMAGE, "CAMERA_BUSY", onComplete, "SKIPPED")
            return
        }
        val requestedAt = Instant.now()
        val startedNs = System.nanoTime()
        mainHandler.post {
            val capture = runCatching { ensureImageMode() }.getOrElse { error ->
                cameraBusy.set(false)
                repository.appendRuntimeAudit(
                    "CAMERA_IMAGE_BIND_FAILED",
                    cameraDiagnostic().put("error", describe(error)),
                )
                repository.recordAttempt(
                    window,
                    CaptureModality.IMAGE,
                    requestedAt,
                    "FAILED",
                    "DEVICE_UNAVAILABLE",
                    elapsedMs(startedNs),
                    null,
                )
                onComplete(false, "拍照模式初始化失败：${error.message}")
                return@post
            }
            val capturedMonotonicStartNs = SystemClock.elapsedRealtimeNanos()
            val file = repository.newTemporaryFile("jpg")
            val options = ImageCapture.OutputFileOptions.Builder(file).build()
            try {
                capture.takePicture(
                    options,
                    executor,
                    object : ImageCapture.OnImageSavedCallback {
                        override fun onImageSaved(
                            outputFileResults: ImageCapture.OutputFileResults,
                        ) {
                            cameraBusy.set(false)
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
                                        .put("capture_mode", "CAMERAX_IMAGE_ONLY_NO_PREVIEW")
                                        .put("jpeg_quality", JPEG_QUALITY),
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
                            cameraBusy.set(false)
                            file.delete()
                            repository.appendRuntimeAudit(
                                "CAMERA_IMAGE_CAPTURE_FAILED",
                                cameraDiagnostic().put("error", describe(exception)),
                            )
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
            } catch (error: Throwable) {
                cameraBusy.set(false)
                file.delete()
                repository.appendRuntimeAudit(
                    "CAMERA_IMAGE_CAPTURE_FAILED",
                    cameraDiagnostic().put("error", describe(error)),
                )
                repository.recordAttempt(
                    window,
                    CaptureModality.IMAGE,
                    requestedAt,
                    "FAILED",
                    "DEVICE_UNAVAILABLE",
                    elapsedMs(startedNs),
                    null,
                )
                onComplete(false, "拍照启动失败：${error.message}")
            }
        }
    }

    fun captureShortVideo(
        window: CaptureWindowContext,
        durationMs: Long = 2_500L,
        onComplete: (Boolean, String) -> Unit,
    ) {
        if (!cameraBusy.compareAndSet(false, true)) {
            recordFailure(window, CaptureModality.VIDEO, "CAMERA_BUSY", onComplete, "SKIPPED")
            return
        }
        val requestedAt = Instant.now()
        val startedNs = System.nanoTime()
        mainHandler.post {
            val capture = runCatching { bindVideoMode("VIDEO_CAPTURE_REQUEST") }.getOrElse { error ->
                cameraBusy.set(false)
                repository.appendRuntimeAudit(
                    "CAMERA_VIDEO_BIND_FAILED",
                    cameraDiagnostic().put("error", describe(error)),
                )
                repository.recordAttempt(
                    window,
                    CaptureModality.VIDEO,
                    requestedAt,
                    "FAILED",
                    "DEVICE_UNAVAILABLE",
                    elapsedMs(startedNs),
                    null,
                )
                restoreImageMode()
                onComplete(false, "录像模式初始化失败：${error.message}")
                return@post
            }
            val capturedMonotonicStartNs = SystemClock.elapsedRealtimeNanos()
            val file = repository.newTemporaryFile("mp4")
            val recording = runCatching {
                capture.output
                    .prepareRecording(service, FileOutputOptions.Builder(file).build())
                    .start(executor) { event ->
                        if (event is VideoRecordEvent.Finalize) {
                            activeRecording = null
                            activeStopRunnable?.let(mainHandler::removeCallbacks)
                            activeStopRunnable = null
                            if (event.hasError() || !file.exists() || file.length() == 0L) {
                                file.delete()
                                repository.appendRuntimeAudit(
                                    "CAMERA_VIDEO_CAPTURE_FAILED",
                                    cameraDiagnostic()
                                        .put("error_code", event.error)
                                        .put("error", event.cause?.let(::describe) ?: JSONObject.NULL),
                                )
                                repository.recordAttempt(
                                    window,
                                    CaptureModality.VIDEO,
                                    requestedAt,
                                    "FAILED",
                                    "FINALIZE_FAILED",
                                    elapsedMs(startedNs),
                                    null,
                                )
                                finishVideoCapture(
                                    onComplete,
                                    false,
                                    "短视频失败：${event.cause?.message ?: event.error}",
                                )
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
                                        .put("requested_duration_ms", durationMs)
                                        .put("has_audio_track", metadata.hasAudioTrack)
                                        .put("capture_mode", "CAMERAX_VIDEO_ONLY_NO_PREVIEW")
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
                                finishVideoCapture(onComplete, false, "视频写入失败：${error.message}")
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
                            finishVideoCapture(onComplete, true, "短视频已进入加密队列")
                        }
                    }
            }.getOrElse { error ->
                file.delete()
                repository.appendRuntimeAudit(
                    "CAMERA_VIDEO_START_FAILED",
                    cameraDiagnostic().put("error", describe(error)),
                )
                repository.recordAttempt(
                    window,
                    CaptureModality.VIDEO,
                    requestedAt,
                    "FAILED",
                    "DEVICE_UNAVAILABLE",
                    elapsedMs(startedNs),
                    null,
                )
                finishVideoCapture(onComplete, false, "录像启动失败：${error.message}")
                return@post
            }
            activeRecording = recording
            activeStopRunnable = Runnable {
                if (activeRecording === recording) recording.stop()
            }.also { mainHandler.postDelayed(it, durationMs) }
        }
    }

    fun captureRokidSystemVideo(
        window: CaptureWindowContext,
        durationMs: Long = 5_000L,
        deriveRepresentativeFrame: Boolean = false,
        onComplete: (Boolean, String) -> Unit,
    ) {
        if (!cameraBusy.compareAndSet(false, true)) {
            recordFailure(window, CaptureModality.VIDEO, "CAMERA_BUSY", onComplete, "SKIPPED")
            if (deriveRepresentativeFrame) {
                repository.recordAttempt(
                    window,
                    CaptureModality.IMAGE,
                    Instant.now(),
                    "SKIPPED",
                    "CAMERA_BUSY",
                    0,
                    null,
                )
            }
            return
        }
        val requestedAt = Instant.now()
        val startedNs = System.nanoTime()
        val completed = AtomicBoolean(false)
        var capturedMonotonicStartNs = SystemClock.elapsedRealtimeNanos()
        mainHandler.post {
            provider?.unbindAll()
            imageCapture = null
            videoCapture = null
            boundMode = BoundMode.NONE

            val requestedFile = repository.newExternalTemporaryFile("mp4")
            repository.appendRuntimeAudit(
                "ROKID_SYSTEM_VIDEO_REQUESTED",
                JSONObject()
                    .put("duration_ms", durationMs)
                    .put("derive_representative_frame", deriveRepresentativeFrame)
                    .put("service_connected", systemRecorder.isConnected()),
            )
            systemRecordingActive = true
            val accepted = systemRecorder.captureCameraVideo(
                requestedFile,
                durationMs,
                object : RokidSystemRecordingClient.Callback {
                    override fun onStarted(path: String) {
                        capturedMonotonicStartNs = SystemClock.elapsedRealtimeNanos()
                        repository.appendRuntimeAudit(
                            "ROKID_SYSTEM_VIDEO_STARTED",
                            JSONObject().put("output_path", path),
                        )
                    }

                    override fun onCompleted(file: java.io.File, success: Boolean, message: String?) {
                        if (!completed.compareAndSet(false, true)) return
                        systemRecordingActive = false
                        val completedFile = file.takeIf { it.exists() } ?: requestedFile
                        if (!success || !completedFile.exists() || completedFile.length() == 0L) {
                            val outputBytes = completedFile.length()
                            completedFile.delete()
                            requestedFile.delete()
                            repository.appendRuntimeAudit(
                                "ROKID_SYSTEM_VIDEO_FAILED",
                                JSONObject()
                                    .put("message", message ?: JSONObject.NULL)
                                    .put("output_exists", completedFile.exists())
                                    .put("output_bytes", outputBytes),
                            )
                            repository.recordAttempt(
                                window,
                                CaptureModality.VIDEO,
                                requestedAt,
                                "FAILED",
                                "ROKID_SYSTEM_RECORDER_FAILED",
                                elapsedMs(startedNs),
                                null,
                            )
                            recordDerivedFrameFailureIfRequested(
                                window,
                                requestedAt,
                                startedNs,
                                deriveRepresentativeFrame,
                                "ROKID_SYSTEM_RECORDER_FAILED",
                            )
                            finishSystemVideoCapture(
                                onComplete,
                                false,
                                "乐奇系统短视频失败：${message ?: "没有生成文件"}",
                            )
                            return
                        }

                        executor.execute {
                            persistRokidSystemVideo(
                                window = window,
                                requestedAt = requestedAt,
                                startedNs = startedNs,
                                capturedMonotonicStartNs = capturedMonotonicStartNs,
                                completedFile = completedFile,
                                requestedFile = requestedFile,
                                requestedDurationMs = durationMs,
                                deriveRepresentativeFrame = deriveRepresentativeFrame,
                                onComplete = onComplete,
                            )
                        }
                    }

                    override fun onError(errorCode: Int, message: String) {
                        if (!completed.compareAndSet(false, true)) return
                        systemRecordingActive = false
                        requestedFile.delete()
                        repository.appendRuntimeAudit(
                            "ROKID_SYSTEM_VIDEO_FAILED",
                            JSONObject()
                                .put("error_code", errorCode)
                                .put("message", message),
                        )
                        repository.recordAttempt(
                            window,
                            CaptureModality.VIDEO,
                            requestedAt,
                            "FAILED",
                            "ROKID_SYSTEM_RECORDER_ERROR_$errorCode",
                            elapsedMs(startedNs),
                            null,
                        )
                        recordDerivedFrameFailureIfRequested(
                            window,
                            requestedAt,
                            startedNs,
                            deriveRepresentativeFrame,
                            "ROKID_SYSTEM_RECORDER_ERROR_$errorCode",
                        )
                        finishSystemVideoCapture(
                            onComplete,
                            false,
                            "乐奇系统短视频失败：$message",
                        )
                    }
                },
            )
            if (!systemRecorder.isConnected() && accepted) {
                repository.appendRuntimeAudit(
                    "ROKID_SYSTEM_RECORDER_WAITING_FOR_CONNECTION",
                    JSONObject()
                        .put("timeout_ms", 3_000)
                        .put("message", "录制请求已保留，正在等待乐奇系统服务连接"),
                )
            }
        }
    }

    private fun persistRokidSystemVideo(
        window: CaptureWindowContext,
        requestedAt: Instant,
        startedNs: Long,
        capturedMonotonicStartNs: Long,
        completedFile: java.io.File,
        requestedFile: java.io.File,
        requestedDurationMs: Long,
        deriveRepresentativeFrame: Boolean,
        onComplete: (Boolean, String) -> Unit,
    ) {
        val metadata = runCatching { readVideoMetadata(completedFile) }.getOrElse { error ->
            completedFile.delete()
            requestedFile.delete()
            repository.recordAttempt(
                window,
                CaptureModality.VIDEO,
                requestedAt,
                "FAILED",
                "VIDEO_METADATA_FAILED",
                elapsedMs(startedNs),
                null,
            )
            recordDerivedFrameFailureIfRequested(
                window,
                requestedAt,
                startedNs,
                deriveRepresentativeFrame,
                "VIDEO_METADATA_FAILED",
            )
            finishSystemVideoCapture(
                onComplete,
                false,
                "乐奇系统视频元数据读取失败：${error.message}",
            )
            return
        }
        val derivedFrameResult = if (deriveRepresentativeFrame) {
            runCatching { extractRepresentativeFrame(completedFile, metadata.durationMs) }
        } else {
            null
        }
        val evidenceId = runCatching {
            repository.finalizeEvidence(
                window = window,
                modality = CaptureModality.VIDEO,
                sourceFile = completedFile,
                mimeType = "video/mp4",
                capturedAt = requestedAt,
                durationMs = metadata.durationMs,
                media = JSONObject()
                    .put("container", "MP4")
                    .put("video_codec", "ROKID_SYSTEM_MEDIA_RECORDER")
                    .put("width_px", metadata.width)
                    .put("height_px", metadata.height)
                    .put("frame_rate_fps", metadata.frameRate ?: JSONObject.NULL)
                    .put("requested_duration_ms", requestedDurationMs)
                    .put("has_audio_track", metadata.hasAudioTrack)
                    .put(
                        "capture_mode",
                        "ROKID_SYSTEM_RECORDING_SERVICE_NO_APP_PREVIEW",
                    )
                    .put("finalize_status", "SUCCESS"),
                monotonicStartNs = capturedMonotonicStartNs,
                monotonicEndNs = SystemClock.elapsedRealtimeNanos(),
            )
        }.getOrElse { error ->
            completedFile.delete()
            requestedFile.delete()
            derivedFrameResult?.getOrNull()?.file?.delete()
            repository.recordAttempt(
                window,
                CaptureModality.VIDEO,
                requestedAt,
                "FAILED",
                "FINALIZE_FAILED",
                elapsedMs(startedNs),
                null,
            )
            recordDerivedFrameFailureIfRequested(
                window,
                requestedAt,
                startedNs,
                deriveRepresentativeFrame,
                "VIDEO_FINALIZE_FAILED",
            )
            finishSystemVideoCapture(
                onComplete,
                false,
                "乐奇系统视频写入失败：${error.message}",
            )
            return
        }
        requestedFile.delete()
        repository.recordAttempt(
            window,
            CaptureModality.VIDEO,
            requestedAt,
            "SUCCEEDED",
            null,
            elapsedMs(startedNs),
            evidenceId,
        )

        val derivedImageEvidenceId = derivedFrameResult?.fold(
            onSuccess = { frame ->
                runCatching {
                    repository.finalizeEvidence(
                        window = window,
                        modality = CaptureModality.IMAGE,
                        sourceFile = frame.file,
                        mimeType = "image/jpeg",
                        capturedAt = requestedAt.plusMillis(frame.frameTimeMs),
                        durationMs = 0,
                        media = JSONObject()
                            .put("codec", "JPEG")
                            .put("width_px", frame.width)
                            .put("height_px", frame.height)
                            .put("orientation_deg", 0)
                            .put("camera_facing", "WORLD")
                            .put(
                                "capture_mode",
                                "DERIVED_KEYFRAME_FROM_ROKID_SYSTEM_VIDEO",
                            )
                            .put("frame_time_ms", frame.frameTimeMs)
                            .put("derived_from_evidence_item_id", evidenceId)
                            .put("jpeg_quality", SYSTEM_KEYFRAME_JPEG_QUALITY),
                        monotonicStartNs =
                            capturedMonotonicStartNs + frame.frameTimeMs * 1_000_000L,
                        monotonicEndNs =
                            capturedMonotonicStartNs + frame.frameTimeMs * 1_000_000L,
                    )
                }.onFailure { frame.file.delete() }.getOrNull()
            },
            onFailure = { null },
        )
        if (deriveRepresentativeFrame) {
            if (derivedImageEvidenceId != null) {
                repository.recordAttempt(
                    window,
                    CaptureModality.IMAGE,
                    requestedAt,
                    "SUCCEEDED",
                    null,
                    elapsedMs(startedNs),
                    derivedImageEvidenceId,
                )
                repository.appendRuntimeAudit(
                    "ROKID_SYSTEM_KEYFRAME_SUCCEEDED",
                    JSONObject()
                        .put("evidence_item_id", derivedImageEvidenceId)
                        .put("derived_from_evidence_item_id", evidenceId),
                )
            } else {
                recordDerivedFrameFailureIfRequested(
                    window,
                    requestedAt,
                    startedNs,
                    true,
                    "DERIVED_FRAME_EXTRACTION_OR_FINALIZE_FAILED",
                )
                repository.appendRuntimeAudit(
                    "ROKID_SYSTEM_KEYFRAME_FAILED",
                    JSONObject().put(
                        "message",
                        derivedFrameResult?.exceptionOrNull()?.message ?: "图片证据写入失败",
                    ),
                )
            }
        }

        repository.appendRuntimeAudit(
            "ROKID_SYSTEM_VIDEO_SUCCEEDED",
            JSONObject()
                .put("evidence_item_id", evidenceId)
                .put("derived_image_evidence_item_id", derivedImageEvidenceId ?: JSONObject.NULL)
                .put("has_audio_track", metadata.hasAudioTrack)
                .put("duration_ms", metadata.durationMs),
        )
        finishSystemVideoCapture(
            onComplete,
            true,
            if (metadata.hasAudioTrack) {
                "乐奇系统带声短视频与代表帧已进入加密队列"
            } else {
                "乐奇系统短视频与代表帧已进入队列，但没有音轨"
            },
        )
    }

    fun stopActiveRecording() {
        activeStopRunnable?.let(mainHandler::removeCallbacks)
        activeStopRunnable = null
        activeRecording?.stop()
        activeRecording = null
        if (systemRecordingActive) {
            systemRecorder.stopCameraRecording()
            systemRecordingActive = false
        }
    }

    fun suspendCapture() {
        stopActiveRecording()
        provider?.unbindAll()
        imageCapture = null
        videoCapture = null
        boundMode = BoundMode.NONE
    }

    fun shutdown() {
        suspendCapture()
        systemRecorder.shutdown()
        executor.shutdown()
    }

    private fun ensureImageMode(): ImageCapture {
        if (boundMode == BoundMode.IMAGE) {
            imageCapture?.let { return it }
        }
        return bindImageMode("IMAGE_CAPTURE_REQUEST")
    }

    private fun bindImageMode(reason: String): ImageCapture {
        val cameraProvider = requireNotNull(provider) { "Camera provider is unavailable" }
        val cameraSelector = requireNotNull(selector) { "Camera selector is unavailable" }
        val startedNs = System.nanoTime()
        val image = ImageCapture.Builder()
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
            .setJpegQuality(JPEG_QUALITY)
            .build()
        cameraProvider.unbindAll()
        imageCapture = null
        videoCapture = null
        boundMode = BoundMode.NONE
        cameraProvider.bindToLifecycle(service, cameraSelector, image)
        imageCapture = image
        boundMode = BoundMode.IMAGE
        repository.appendRuntimeAudit(
            "CAMERA_MODE_BOUND",
            cameraDiagnostic()
                .put("mode", BoundMode.IMAGE.name)
                .put("reason", reason)
                .put("bind_latency_ms", elapsedMs(startedNs)),
        )
        return image
    }

    private fun bindVideoMode(reason: String): VideoCapture<Recorder> {
        val cameraProvider = requireNotNull(provider) { "Camera provider is unavailable" }
        val cameraSelector = requireNotNull(selector) { "Camera selector is unavailable" }
        val startedNs = System.nanoTime()
        val recorder = Recorder.Builder()
            .setQualitySelector(
                QualitySelector.fromOrderedList(
                    listOf(Quality.HD, Quality.SD),
                    FallbackStrategy.lowerQualityOrHigherThan(Quality.SD),
                ),
            )
            .build()
        val video = VideoCapture.Builder(recorder).build()
        cameraProvider.unbindAll()
        imageCapture = null
        videoCapture = null
        boundMode = BoundMode.NONE
        cameraProvider.bindToLifecycle(service, cameraSelector, video)
        videoCapture = video
        boundMode = BoundMode.VIDEO
        repository.appendRuntimeAudit(
            "CAMERA_MODE_BOUND",
            cameraDiagnostic()
                .put("mode", BoundMode.VIDEO.name)
                .put("reason", reason)
                .put("bind_latency_ms", elapsedMs(startedNs)),
        )
        return video
    }

    private fun finishVideoCapture(
        onComplete: (Boolean, String) -> Unit,
        success: Boolean,
        message: String,
    ) {
        mainHandler.post {
            val restoreError = restoreImageMode()
            cameraBusy.set(false)
            if (restoreError == null) {
                onComplete(success, message)
            } else {
                onComplete(
                    success,
                    "$message；拍照模式恢复失败：${restoreError.message}",
                )
            }
        }
    }

    private fun finishSystemVideoCapture(
        onComplete: (Boolean, String) -> Unit,
        success: Boolean,
        message: String,
    ) {
        mainHandler.post {
            cameraBusy.set(false)
            onComplete(success, message)
        }
    }

    private fun recordDerivedFrameFailureIfRequested(
        window: CaptureWindowContext,
        requestedAt: Instant,
        startedNs: Long,
        requested: Boolean,
        reason: String,
    ) {
        if (!requested) return
        repository.recordAttempt(
            window,
            CaptureModality.IMAGE,
            requestedAt,
            "FAILED",
            reason,
            elapsedMs(startedNs),
            null,
        )
    }

    private fun restoreImageMode(): Throwable? {
        return runCatching { bindImageMode("VIDEO_CAPTURE_FINISHED") }
            .exceptionOrNull()
            ?.also { error ->
                repository.appendRuntimeAudit(
                    "CAMERA_IMAGE_RESTORE_FAILED",
                    cameraDiagnostic().put("error", describe(error)),
                )
            }
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
        val result = JSONObject()
            .put("camera_facing", cameraFacing)
            .put("bound_mode", boundMode.name)
        val manager = service.getSystemService(CameraManager::class.java) ?: return result
        val cameras = JSONArray()
        runCatching {
            manager.cameraIdList.forEach { cameraId ->
                val characteristics = manager.getCameraCharacteristics(cameraId)
                val streamMap = characteristics.get(
                    CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP,
                )
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
                        )
                        .put(
                            "ae_target_fps_ranges",
                            JSONArray().apply {
                                characteristics.get(
                                    CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES,
                                )?.forEach { range ->
                                    put(
                                        JSONObject()
                                            .put("min", range.lower)
                                            .put("max", range.upper),
                                    )
                                }
                            },
                        )
                        .put(
                            "jpeg_output_sizes",
                            sizeArray(streamMap?.getOutputSizes(ImageFormat.JPEG)),
                        )
                        .put(
                            "video_output_sizes",
                            sizeArray(streamMap?.getOutputSizes(MediaRecorder::class.java)),
                        ),
                )
            }
        }.onFailure { result.put("inventory_error", describe(it)) }
        return result.put("camera_inventory", cameras)
    }

    private fun sizeArray(sizes: Array<android.util.Size>?): JSONArray =
        JSONArray().apply {
            sizes
                ?.sortedByDescending { it.width.toLong() * it.height }
                ?.take(MAX_DIAGNOSTIC_SIZES)
                ?.forEach { put("${it.width}x${it.height}") }
        }

    private fun describe(error: Throwable): String =
        generateSequence(error) { it.cause }
            .take(MAX_ERROR_CAUSES)
            .joinToString(" <- ") { "${it.javaClass.simpleName}: ${it.message}" }

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
                hasAudioTrack = retriever.extractMetadata(
                    MediaMetadataRetriever.METADATA_KEY_HAS_AUDIO,
                ) == "yes",
            )
        } finally {
            retriever.release()
        }
    }

    private fun extractRepresentativeFrame(
        file: java.io.File,
        durationMs: Long,
    ): DerivedFrame {
        val frameTimeMs = (durationMs / 2).coerceAtLeast(0)
        val retriever = MediaMetadataRetriever()
        val bitmap = try {
            retriever.setDataSource(file.absolutePath)
            checkNotNull(
                retriever.getFrameAtTime(
                    frameTimeMs * 1_000L,
                    MediaMetadataRetriever.OPTION_CLOSEST_SYNC,
                ),
            ) { "系统短视频没有可解码的画面" }
        } finally {
            retriever.release()
        }
        val output = repository.newTemporaryFile("jpg")
        return try {
            FileOutputStream(output).use { stream ->
                check(
                    bitmap.compress(
                        Bitmap.CompressFormat.JPEG,
                        SYSTEM_KEYFRAME_JPEG_QUALITY,
                        stream,
                    ),
                ) { "代表帧 JPEG 编码失败" }
            }
            DerivedFrame(
                file = output,
                frameTimeMs = frameTimeMs,
                width = bitmap.width,
                height = bitmap.height,
            )
        } catch (error: Throwable) {
            output.delete()
            throw error
        } finally {
            bitmap.recycle()
        }
    }

    private data class VideoMetadata(
        val durationMs: Long,
        val width: Int,
        val height: Int,
        val frameRate: Double?,
        val hasAudioTrack: Boolean,
    )

    private data class DerivedFrame(
        val file: java.io.File,
        val frameTimeMs: Long,
        val width: Int,
        val height: Int,
    )

    private enum class BoundMode {
        NONE,
        IMAGE,
        VIDEO,
    }

    companion object {
        private const val JPEG_QUALITY = 92
        private const val SYSTEM_KEYFRAME_JPEG_QUALITY = 88
        private const val MAX_DIAGNOSTIC_SIZES = 12
        private const val MAX_ERROR_CAUSES = 4
    }
}
