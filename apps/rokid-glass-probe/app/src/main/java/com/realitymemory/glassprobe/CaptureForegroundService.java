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

import androidx.annotation.NonNull;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
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
        ProbeLog.append(this, "ACTIVE", "periodic capture every 30s");
    }

    private void stopCapture() {
        periodic = false;
        paused = false;
        handler.removeCallbacks(periodicTick);
        audioCapture.stop();
        imuSampler.stop();
        imageCapture = null;
        ProbeLog.append(this, "ENDED", "capture stopped");
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    private void bindCameraThen(Runnable afterBind) {
        // 预览开关变化时需要携带/去掉 ImageAnalysis 重新绑定
        if (imageCapture != null && boundWithPreview == previewActive) {
            afterBind.run();
            return;
        }
        ListenableFuture<ProcessCameraProvider> providerFuture = ProcessCameraProvider.getInstance(this);
        providerFuture.addListener(() -> {
            try {
                ProcessCameraProvider cameraProvider = providerFuture.get();
                ImageCapture capture = new ImageCapture.Builder()
                        .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                        .build();
                cameraProvider.unbindAll();
                if (previewActive) {
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
                boundWithPreview = previewActive;
                ProbeLog.append(this, "CAMERA_BOUND",
                        "CameraX bound to lifecycle, preview=" + previewActive);
                afterBind.run();
            } catch (Exception e) {
                ProbeLog.append(this, "CAMERA_BIND_FAILED", e.getClass().getSimpleName() + ": " + e.getMessage());
            }
        }, ContextCompat.getMainExecutor(this));
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

    private void captureOnce(String trigger) {
        if (paused) {
            ProbeLog.append(this, "CAPTURE_SKIPPED", "paused trigger=" + trigger);
            return;
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            ProbeLog.append(this, "CAPTURE_DENIED", "camera permission not granted trigger=" + trigger);
            return;
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
                }

                @Override
                public void onError(@NonNull ImageCaptureException exception) {
                    ProbeLog.append(
                            CaptureForegroundService.this,
                            "CAPTURE_FAILED",
                            "trigger=" + trigger + ", code=" + exception.getImageCaptureError() + ", message=" + exception.getMessage()
                    );
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
