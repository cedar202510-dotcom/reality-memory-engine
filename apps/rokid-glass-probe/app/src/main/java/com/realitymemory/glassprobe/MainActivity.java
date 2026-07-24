package com.realitymemory.glassprobe;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import androidx.activity.ComponentActivity;
import androidx.core.content.ContextCompat;

import java.io.File;
import java.util.List;

public class MainActivity extends ComponentActivity {
    private static final int REQUEST_CAPTURE_PERMISSIONS = 42;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView statusView;
    private TextView logView;

    private final BroadcastReceiver liveWearReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            String detail = WearStateReceiver.describeIntent(intent);
            ProbeLog.append(context, "LIVE_BROADCAST", detail);
            refreshLogs();
        }
    };

    private final Runnable refreshLoop = new Runnable() {
        @Override
        public void run() {
            refreshLogs();
            handler.postDelayed(this, 2000);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        ProbeLog.append(this, "APP_OPENED", "main activity opened");
        buildUi();
        requestCameraIfNeeded();
        registerLiveReceiver();
        refreshLogs();
        handler.post(refreshLoop);
        // 联调便利：打开 App 即自动开启 PC 预览（眼镜上难以精准点按钮，adb tap 会被输入
        // 通道拦截）。延迟到相机权限回调之后；已授权时等价于直接启动。
        handler.postDelayed(() -> {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
                    == PackageManager.PERMISSION_GRANTED) {
                ProbeLog.append(this, "PREVIEW_AUTOSTART", "auto start on app open");
                sendServiceAction(CaptureForegroundService.ACTION_START_PREVIEW);
            }
        }, 1200);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        unregisterReceiver(liveWearReceiver);
        handler.removeCallbacksAndMessages(null);
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(18, 18, 18, 18);
        root.setBackgroundColor(Color.BLACK);

        statusView = label("Reality Glass Probe\nstatus: READY");
        statusView.setTextSize(20);
        root.addView(statusView, matchWrap());

        Button captureOnce = button("Capture Once");
        captureOnce.setOnClickListener(v -> sendServiceAction(CaptureForegroundService.ACTION_CAPTURE_ONCE));
        root.addView(captureOnce, matchWrap());

        Button startPeriodic = button("Start 30s Periodic");
        startPeriodic.setOnClickListener(v -> sendServiceAction(CaptureForegroundService.ACTION_START_PERIODIC));
        root.addView(startPeriodic, matchWrap());

        Button pause = button("Pause");
        pause.setOnClickListener(v -> sendServiceAction(CaptureForegroundService.ACTION_PAUSE));
        root.addView(pause, matchWrap());

        Button resume = button("Resume");
        resume.setOnClickListener(v -> sendServiceAction(CaptureForegroundService.ACTION_RESUME));
        root.addView(resume, matchWrap());

        Button startPreview = button("Start PC Preview (MJPEG :8090)");
        startPreview.setOnClickListener(v -> sendServiceAction(CaptureForegroundService.ACTION_START_PREVIEW));
        root.addView(startPreview, matchWrap());

        Button stopPreview = button("Stop PC Preview");
        stopPreview.setOnClickListener(v -> sendServiceAction(CaptureForegroundService.ACTION_STOP_PREVIEW));
        root.addView(stopPreview, matchWrap());

        Button stop = button("Stop and Cleanup");
        stop.setOnClickListener(v -> sendServiceAction(CaptureForegroundService.ACTION_STOP));
        root.addView(stop, matchWrap());

        TextView logTitle = label("Recent local JSONL logs");
        logTitle.setTextSize(14);
        root.addView(logTitle, matchWrap());

        logView = label("");
        logView.setTextSize(11);
        ScrollView scroll = new ScrollView(this);
        scroll.addView(logView);
        root.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f
        ));

        setContentView(root);
    }

    private TextView label(String text) {
        TextView view = new TextView(this);
        view.setText(text);
        view.setTextColor(Color.rgb(0, 255, 102));
        view.setGravity(Gravity.START);
        return view;
    }

    private Button button(String text) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        return button;
    }

    private LinearLayout.LayoutParams matchWrap() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
    }

    private void requestCameraIfNeeded() {
        List<String> missing = new java.util.ArrayList<>();
        for (String permission : new String[]{Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO}) {
            if (ContextCompat.checkSelfPermission(this, permission) != PackageManager.PERMISSION_GRANTED) {
                missing.add(permission);
            }
        }
        if (!missing.isEmpty()) {
            requestPermissions(missing.toArray(new String[0]), REQUEST_CAPTURE_PERMISSIONS);
        }
    }

    private void registerLiveReceiver() {
        IntentFilter filter = new IntentFilter();
        filter.addAction(WearStateReceiver.ACTION_TAKE_STATUS_CHANGED);
        filter.addAction(WearStateReceiver.ACTION_LEG_STATUS_CHANGED);
        registerReceiver(liveWearReceiver, filter);
    }

    private void sendServiceAction(String action) {
        Intent intent = new Intent(this, CaptureForegroundService.class);
        intent.setAction(action);
        try {
            startForegroundService(intent);
            statusView.setText("Reality Glass Probe\nstatus: " + action);
        } catch (Exception e) {
            ProbeLog.append(this, "SERVICE_START_FAILED", e.getClass().getSimpleName() + ": " + e.getMessage());
            refreshLogs();
        }
    }

    private void refreshLogs() {
        File file = ProbeLog.logFile(this);
        List<String> lines = ProbeLog.lastLines(this, 24);
        StringBuilder builder = new StringBuilder();
        builder.append("log: ").append(file.getAbsolutePath()).append("\n\n");
        for (String line : lines) {
            builder.append(line).append("\n");
        }
        logView.setText(builder.toString());
    }
}
