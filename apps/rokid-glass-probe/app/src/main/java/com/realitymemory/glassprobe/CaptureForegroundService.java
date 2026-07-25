package com.realitymemory.glassprobe;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.Looper;
import android.util.Size;

import androidx.annotation.NonNull;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.core.resolutionselector.ResolutionSelector;
import androidx.camera.core.resolutionselector.ResolutionStrategy;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.LifecycleService;

import com.google.common.util.concurrent.ListenableFuture;

import com.realitymemory.glassprobe.collector.AudioCaptureController;
import com.realitymemory.glassprobe.collector.CollectorConfig;
import com.realitymemory.glassprobe.collector.EnvelopeSpooler;
import com.realitymemory.glassprobe.collector.EnvelopeUploader;
import com.realitymemory.glassprobe.collector.ImuSampler;
import com.realitymemory.glassprobe.collector.PreviewFrameAnalyzer;
import com.realitymemory.glassprobe.collector.PreviewStreamServer;

import org.json.JSONObject;

import java.io.File;
import java.nio.file.Files;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class CaptureForegroundService extends LifecycleService {
    static final String ACTION_CAPTURE_ONCE = "com.realitymemory.glassprobe.CAPTURE_ONCE";
    static final String ACTION_START_PERIODIC = "com.realitymemory.glassprobe.START_PERIODIC";
    static final String ACTION_WEAR_DETECTED = "com.realitymemory.glassprobe.WEAR_DETECTED";
    static final String ACTION_PAUSE = "com.realitymemory.glassprobe.PAUSE";
    static final String ACTION_RESUME = "com.realitymemory.glassprobe.RESUME";
    static final String ACTION_STOP = "com.realitymemory.glassprobe.STOP";
    static final String ACTION_START_PREVIEW = "com.realitymemory.glassprobe.START_PREVIEW";
    static final String ACTION_STOP_PREVIEW = "com.realitymemory.glassprobe.STOP_PREVIEW";

    private static final String CHANNEL_ID = "reality_glass_probe";
    private static final int NOTIFICATION_ID = 101;
    private static final long PERIODIC_INTERVAL_MS = 30_000L;

    /**
     * 拍照流分辨率上限。不设的话 CameraX 会挑传感器最大档 4032x3024（12MP），
     * 单张 5.5MB / 约 2.4s；这里落到 2016x1512 后是 1.0MB / 约 1.3s。
     * 采集探针每 30s 一张还要走上传，体积和延迟都按这个量级更合适，
     * 12MP 的细节对后端的记忆检索没有额外价值。
     */
    private static final ResolutionSelector STILL_RESOLUTION = new ResolutionSelector.Builder()
            .setResolutionStrategy(new ResolutionStrategy(
                    new Size(1920, 1080),
                    ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER))
            .build();

    private final Handler handler = new Handler(Looper.getMainLooper());
    private ExecutorService cameraExecutor;
    private ImageCapture imageCapture;
    private boolean paused = false;
    private boolean periodic = false;
    private boolean foreground = false;

    // ---- 采集/上报（connector collector 侧，见 docs/architecture/04）----
    private CollectorConfig collectorConfig;
    private EnvelopeSpooler spooler;
    private EnvelopeUploader uploader;
    private AudioCaptureController audioCapture;
    private ImuSampler imuSampler;
    private String sessionId;

    // ---- 电脑实时预览（MJPEG 旁路，不影响采集链路）----
    private PreviewStreamServer previewServer;
    private boolean previewActive = false;
    private boolean boundWithPreview = false;

    // 相机绑定必须串行，见 bindCameraThen 注释
    private boolean bindInFlight = false;
    private final List<Runnable> pendingAfterBind = new java.util.ArrayList<>();

    private final Runnable periodicTick = new Runnable() {
        @Override
        public void run() {
            if (periodic && !paused) {
                captureOnce("PERIODIC");
                handler.postDelayed(this, PERIODIC_INTERVAL_MS);
            }
        }
    };

    @Override
    public void onCreate() {
        super.onCreate();
        cameraExecutor = Executors.newSingleThreadExecutor();

        // 一次服务生命周期 = 一个采集会话；同一会话的信封在后端可关联。
        sessionId = "glass-" + UUID.randomUUID();
        collectorConfig = CollectorConfig.load(this);
        spooler = new EnvelopeSpooler(this);
        uploader = new EnvelopeUploader(this, collectorConfig, spooler);
        audioCapture = new AudioCaptureController(this, collectorConfig, spooler, sessionId);
        imuSampler = new ImuSampler(this, collectorConfig, spooler, sessionId);
        uploader.start();

        ProbeLog.append(this, "SERVICE_CREATED", "capture service created; " + collectorConfig.describe());
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        super.onStartCommand(intent, flags, startId);
        String action = intent != null ? intent.getAction() : "";
        ensureForeground();
        ProbeLog.append(this, "SERVICE_ACTION", action);

        if (ACTION_CAPTURE_ONCE.equals(action)) {
            paused = false;
            captureOnce("MANUAL");
        } else if (ACTION_START_PERIODIC.equals(action)) {
            startPeriodicNow();
        } else if (ACTION_WEAR_DETECTED.equals(action)) {
            handler.postDelayed(this::startPeriodicNow, 5000L);
            ProbeLog.append(this, "COUNTDOWN_5S", "wear detected; periodic capture scheduled after 5s");
        } else if (ACTION_PAUSE.equals(action)) {
            paused = true;
            audioCapture.stop();
            imuSampler.stop();
            PreviewStreamServer.recordEvent("recording_stopped", "paused");
            ProbeLog.append(this, "PAUSED", "capture paused");
        } else if (ACTION_RESUME.equals(action)) {
            paused = false;
            if (periodic) {
                audioCapture.start();
                imuSampler.start();
            }
            ProbeLog.append(this, "RESUMED", "capture resumed");
        } else if (ACTION_START_PREVIEW.equals(action)) {
            startPreview();
        } else if (ACTION_STOP_PREVIEW.equals(action)) {
            stopPreview();
        } else if (ACTION_STOP.equals(action)) {
            stopCapture();
        }

        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        handler.removeCallbacksAndMessages(null);
        audioCapture.stop();
        imuSampler.stop();
        uploader.stop();
        if (previewServer != null) {
            previewServer.stop();
        }
        if (cameraExecutor != null) {
            cameraExecutor.shutdown();
        }
        ProbeLog.append(this, "SERVICE_DESTROYED", "capture service destroyed");
    }

    private void startPeriodicNow() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            ProbeLog.append(this, "CAPTURE_DENIED", "camera permission not granted");
            return;
        }
        paused = false;
        periodic = true;
        captureOnce("PERIODIC_START");
        handler.removeCallbacks(periodicTick);
        handler.postDelayed(periodicTick, PERIODIC_INTERVAL_MS);
        audioCapture.start();
        imuSampler.start();
        PreviewStreamServer.recordEvent("recording_started", "periodic 30s photo + audio + imu");
        ProbeLog.append(this, "ACTIVE", "periodic capture every 30s");
    }

    private void stopCapture() {
        periodic = false;
        paused = false;
        handler.removeCallbacks(periodicTick);
        audioCapture.stop();
        imuSampler.stop();
        imageCapture = null;
        PreviewStreamServer.recordEvent("recording_stopped", "capture ended");
        ProbeLog.append(this, "ENDED", "capture stopped");
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    /**
     * 绑定相机后执行 afterBind。所有状态只在主线程读写（调用方是 onStartCommand /
     * 主线程 Handler，回调走 getMainExecutor），因此不需要额外加锁。
     *
     * 必须串行：bindToLifecycle 前的 unbindAll() 会关掉上一次绑定的 ImageCapture。
     * 早期版本没有在途保护，App 启动时 CAPTURE_ONCE 与 1200ms 的自动 START_PREVIEW
     * 会各起一次绑定，后完成的那次 unbindAll() 正好打断前一次的 takePicture，
     * 报 ImageCapture code=3 "Camera is closed."，严重时相机 HAL 直接进入
     * ERROR_CAMERA_DEVICE 后卡在 PENDING_OPEN 再也开不起来。
     */
    private void bindCameraThen(Runnable afterBind) {
        // 预览开关变化时需要携带/去掉 ImageAnalysis 重新绑定
        if (imageCapture != null && boundWithPreview == previewActive && !bindInFlight) {
            afterBind.run();
            return;
        }
        pendingAfterBind.add(afterBind);
        if (bindInFlight) {
            // 已有绑定在途；回调统一等它完成后 drain，避免并发 unbindAll 互相打断
            return;
        }
        startBind();
    }

    private void startBind() {
        bindInFlight = true;
        // 快照本次要绑的形态：previewActive 可能在异步回调期间被改掉
        final boolean wantPreview = previewActive;
        ListenableFuture<ProcessCameraProvider> providerFuture = ProcessCameraProvider.getInstance(this);
        providerFuture.addListener(() -> {
            try {
                ProcessCameraProvider cameraProvider = providerFuture.get();
                ImageCapture capture = new ImageCapture.Builder()
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                        .setResolutionSelector(STILL_RESOLUTION)
                        .build();
                cameraProvider.unbindAll();
                if (wantPreview) {
                    ImageAnalysis analysis = new ImageAnalysis.Builder()
                            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                            .build();
                    analysis.setAnalyzer(cameraExecutor, new PreviewFrameAnalyzer(
                            previewServer,
                            collectorConfig.previewMaxFps,
                            collectorConfig.previewJpegQuality));
                    cameraProvider.bindToLifecycle(
                            this, CameraSelector.DEFAULT_BACK_CAMERA, capture, analysis);
                } else {
                    cameraProvider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, capture);
                }
                imageCapture = capture;
                boundWithPreview = wantPreview;
                ProbeLog.append(this, "CAMERA_BOUND",
                        "CameraX bound to lifecycle, preview=" + wantPreview);
            } catch (Exception e) {
                ProbeLog.append(this, "CAMERA_BIND_FAILED", e.getClass().getSimpleName() + ": " + e.getMessage());
            } finally {
                bindInFlight = false;
            }

            // 绑定期间预览开关又变了：再绑一次，等待中的回调继续等最终形态
            if (imageCapture != null && boundWithPreview != previewActive) {
                startBind();
                return;
            }
            drainPendingAfterBind();
        }, ContextCompat.getMainExecutor(this));
    }

    private void drainPendingAfterBind() {
        List<Runnable> callbacks = new java.util.ArrayList<>(pendingAfterBind);
        pendingAfterBind.clear();
        if (imageCapture == null) {
            // 绑定失败，回调无相机可用；丢弃并留痕，避免 takePicture 时 NPE
            if (!callbacks.isEmpty()) {
                ProbeLog.append(this, "CAMERA_BIND_DROPPED",
                        "dropped " + callbacks.size() + " pending action(s); camera not bound");
            }
            return;
        }
        for (Runnable callback : callbacks) {
            callback.run();
        }
    }

    /** 开启电脑实时预览：本机起 MJPEG 服务器，相机加挂 ImageAnalysis 出帧。 */
    private void startPreview() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            ProbeLog.append(this, "PREVIEW_DENIED", "camera permission not granted");
            return;
        }
        if (previewActive) {
            return;
        }
        if (previewServer == null) {
            previewServer = new PreviewStreamServer(this, collectorConfig.previewPort);
        }
        previewServer.start();
        if (!previewServer.isRunning()) {
            return;   // 端口被占等绑定失败，日志里已有 PREVIEW_BIND_FAILED
        }
        previewActive = true;
        bindCameraThen(() -> {
        });
    }

    private void stopPreview() {
        if (!previewActive) {
            return;
        }
        previewActive = false;
        if (previewServer != null) {
            previewServer.stop();
        }
        // 立即重绑去掉 ImageAnalysis，停掉相机出帧
        bindCameraThen(() -> {
        });
    }

    /**
     * 拍照期间被摘掉的预览流在这里挂回去。takePicture 的回调跑在 cameraExecutor 上，
     * 而绑定状态只在主线程读写，所以必须 post 回主线程。
     * 期间用户可能已经手动 Stop Preview（previewServer 停了），这时不再自作主张恢复。
     */
    private void resumePreviewIfSuspended(boolean suspended) {
        if (!suspended) {
            return;
        }
        handler.post(() -> {
            if (previewActive || previewServer == null || !previewServer.isRunning()) {
                return;
            }
            previewActive = true;
            ProbeLog.append(this, "PREVIEW_RESUMED", "reattach analysis after still capture");
            bindCameraThen(() -> {
            });
        });
    }

    private void captureOnce(String trigger) {
        if (paused) {
            ProbeLog.append(this, "CAPTURE_SKIPPED", "paused trigger=" + trigger);
            return;
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            ProbeLog.append(this, "CAPTURE_DENIED", "camera permission not granted trigger=" + trigger);
            return;
        }

        // 这颗 HAL 上「静态拍照请求 + ImageAnalysis 预览流」并存会把请求永久卡在
        // in-flight 列表里（logcat 刷 "In-flight list too large"），既不回成功也不回失败，
        // 而且整个相机会被拖死到必须重启设备。preview 单独跑没问题，纯拍照也没问题，
        // 只有两者同时挂着才炸；历史日志里成功的 CAPTURED_LOCAL 无一例外都是 preview=false。
        // 因此拍照期间先把预览流摘掉，拍完（无论成败）再挂回去。预览会短暂卡一下，
        // 但这是让采集链路真正能出图的前提。
        final boolean resumePreviewAfter = previewActive;
        if (resumePreviewAfter) {
            previewActive = false;
            ProbeLog.append(this, "PREVIEW_SUSPENDED", "detach analysis for still capture trigger=" + trigger);
        }

        bindCameraThen(() -> {
            File file = new File(getCacheDir(), "probe_" + System.currentTimeMillis() + ".jpg");
            ImageCapture.OutputFileOptions options = new ImageCapture.OutputFileOptions.Builder(file).build();
            long startedAt = System.currentTimeMillis();
            imageCapture.takePicture(options, cameraExecutor, new ImageCapture.OnImageSavedCallback() {
                @Override
                public void onImageSaved(@NonNull ImageCapture.OutputFileResults outputFileResults) {
                    long latencyMs = System.currentTimeMillis() - startedAt;
                    long bytes = file.exists() ? file.length() : -1L;
                    PreviewStreamServer.recordEvent(
                            "photo_captured", "trigger=" + trigger + ", bytes=" + bytes);
                    if (collectorConfig.canUpload()) {
                        spoolFrame(file, trigger, startedAt);
                        ProbeLog.append(
                                CaptureForegroundService.this,
                                "CAPTURED_SPOOLED",
                                "trigger=" + trigger + ", latency_ms=" + latencyMs + ", bytes=" + bytes
                        );
                    } else {
                        boolean deleted = file.exists() && file.delete();
                        ProbeLog.append(
                                CaptureForegroundService.this,
                                "CAPTURED_LOCAL",
                                "trigger=" + trigger + ", latency_ms=" + latencyMs + ", bytes=" + bytes + ", deleted=" + deleted
                        );
                    }
                    resumePreviewIfSuspended(resumePreviewAfter);
                }

                @Override
                public void onError(@NonNull ImageCaptureException exception) {
                    PreviewStreamServer.recordEvent(
                            "photo_failed", "trigger=" + trigger + ", code=" + exception.getImageCaptureError());
                    ProbeLog.append(
                            CaptureForegroundService.this,
                            "CAPTURE_FAILED",
                            "trigger=" + trigger + ", code=" + exception.getImageCaptureError() + ", message=" + exception.getMessage()
                    );
                    resumePreviewIfSuspended(resumePreviewAfter);
                }
            });
        });
    }

    /** 拍到的帧进入 spool（modality=image），由上传线程异步投递后端；原图立即删除。 */
    private void spoolFrame(File file, String trigger, long occurredAtMs) {
        try {
            byte[] data = Files.readAllBytes(file.toPath());
            JSONObject meta = new JSONObject();
            meta.put("capture_trigger", trigger);
            String envelopeTrigger = "MANUAL".equals(trigger) ? "explicit" : "auto";
            JSONObject envelope = EnvelopeSpooler.buildEnvelope(
                    collectorConfig, sessionId, envelopeTrigger, "image", occurredAtMs, meta);
            spooler.spool(envelope, data, "frame-" + occurredAtMs + ".jpg");
        } catch (Exception e) {
            ProbeLog.append(this, "FRAME_SPOOL_FAILED", e.getClass().getSimpleName() + ": " + e.getMessage());
        } finally {
            //noinspection ResultOfMethodCallIgnored
            file.delete();
        }
    }

    private void ensureForeground() {
        if (foreground) {
            return;
        }
        NotificationManager manager = getSystemService(NotificationManager.class);
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                "Reality Glass Probe",
                NotificationManager.IMPORTANCE_LOW
        );
        manager.createNotificationChannel(channel);

        Intent openIntent = new Intent(this, MainActivity.class);
        PendingIntent pendingIntent = PendingIntent.getActivity(
                this,
                0,
                openIntent,
                PendingIntent.FLAG_IMMUTABLE
        );

        Notification notification = new Notification.Builder(this, CHANNEL_ID)
                .setContentTitle("Reality Glass Probe")
                .setContentText("Camera probe is running")
                .setSmallIcon(android.R.drawable.presence_video_online)
                .setContentIntent(pendingIntent)
                .build();

        startForeground(NOTIFICATION_ID, notification);
        foreground = true;
    }
}
