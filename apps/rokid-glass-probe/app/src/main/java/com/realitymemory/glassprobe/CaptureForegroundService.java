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
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.core.content.ContextCompat;
import androidx.lifecycle.LifecycleService;

import com.google.common.util.concurrent.ListenableFuture;

import java.io.File;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class CaptureForegroundService extends LifecycleService {
    static final String ACTION_CAPTURE_ONCE = "com.realitymemory.glassprobe.CAPTURE_ONCE";
    static final String ACTION_START_PERIODIC = "com.realitymemory.glassprobe.START_PERIODIC";
    static final String ACTION_WEAR_DETECTED = "com.realitymemory.glassprobe.WEAR_DETECTED";
    static final String ACTION_PAUSE = "com.realitymemory.glassprobe.PAUSE";
    static final String ACTION_RESUME = "com.realitymemory.glassprobe.RESUME";
    static final String ACTION_STOP = "com.realitymemory.glassprobe.STOP";

    private static final String CHANNEL_ID = "reality_glass_probe";
    private static final int NOTIFICATION_ID = 101;
    private static final long PERIODIC_INTERVAL_MS = 30_000L;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private ExecutorService cameraExecutor;
    private ImageCapture imageCapture;
    private boolean paused = false;
    private boolean periodic = false;
    private boolean foreground = false;

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
        ProbeLog.append(this, "SERVICE_CREATED", "capture service created");
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
            ProbeLog.append(this, "PAUSED", "capture paused");
        } else if (ACTION_RESUME.equals(action)) {
            paused = false;
            ProbeLog.append(this, "RESUMED", "capture resumed");
        } else if (ACTION_STOP.equals(action)) {
            stopCapture();
        }

        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        super.onDestroy();
        handler.removeCallbacksAndMessages(null);
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
        ProbeLog.append(this, "ACTIVE", "periodic capture every 30s");
    }

    private void stopCapture() {
        periodic = false;
        paused = false;
        handler.removeCallbacks(periodicTick);
        imageCapture = null;
        ProbeLog.append(this, "ENDED", "capture stopped");
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    private void bindCameraThen(Runnable afterBind) {
        if (imageCapture != null) {
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
                cameraProvider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, capture);
                imageCapture = capture;
                ProbeLog.append(this, "CAMERA_BOUND", "CameraX bound to lifecycle");
                afterBind.run();
            } catch (Exception e) {
                ProbeLog.append(this, "CAMERA_BIND_FAILED", e.getClass().getSimpleName() + ": " + e.getMessage());
            }
        }, ContextCompat.getMainExecutor(this));
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
                    boolean deleted = file.exists() && file.delete();
                    ProbeLog.append(
                            CaptureForegroundService.this,
                            "CAPTURED_LOCAL",
                            "trigger=" + trigger + ", latency_ms=" + latencyMs + ", bytes=" + bytes + ", deleted=" + deleted
                    );
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
