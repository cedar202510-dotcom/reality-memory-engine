package com.realitymemory.glassprobe.collector;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;

import com.realitymemory.glassprobe.ProbeLog;

import org.json.JSONObject;

/**
 * IMU 采样：官方裸机路线使用标准 SensorManager。
 *
 * 原始波形不出设备（见 04 connector 架构"传感器数据默认只上摘要"）：
 * 每 imu_window_seconds 聚合一个窗口，只上报 RMS/峰值/样本数摘要，
 * 作为 modality=sensor、无附件的信封入 spool。后端用它做运动上下文
 * 与设备心跳，不重建轨迹。
 */
public final class ImuSampler implements SensorEventListener {
    private final Context context;
    private final CollectorConfig config;
    private final EnvelopeSpooler spooler;
    private final String sessionId;

    private SensorManager sensorManager;
    private boolean running;

    // 窗口内聚合状态（回调都在主线程 looper，不需要加锁）
    private long windowStartMs;
    private int accelCount;
    private double accelSumSquares;
    private double accelPeak;
    private int gyroCount;
    private double gyroSumSquares;
    private double gyroPeak;

    public ImuSampler(Context context, CollectorConfig config, EnvelopeSpooler spooler, String sessionId) {
        this.context = context.getApplicationContext();
        this.config = config;
        this.spooler = spooler;
        this.sessionId = sessionId;
    }

    public synchronized void start() {
        if (running || !config.imuEnabled) {
            return;
        }
        sensorManager = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        if (sensorManager == null) {
            ProbeLog.append(context, "IMU_UNAVAILABLE", "no SensorManager");
            return;
        }
        Sensor accel = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER);
        Sensor gyro = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE);
        if (accel == null && gyro == null) {
            ProbeLog.append(context, "IMU_UNAVAILABLE", "no accelerometer/gyroscope sensors");
            return;
        }
        resetWindow();
        if (accel != null) {
            sensorManager.registerListener(this, accel, SensorManager.SENSOR_DELAY_GAME);
        }
        if (gyro != null) {
            sensorManager.registerListener(this, gyro, SensorManager.SENSOR_DELAY_GAME);
        }
        running = true;
        ProbeLog.append(context, "IMU_STARTED", "window_s=" + config.imuWindowSeconds);
    }

    public synchronized void stop() {
        if (!running) {
            return;
        }
        running = false;
        sensorManager.unregisterListener(this);
        flushWindow();
        ProbeLog.append(context, "IMU_STOPPED", "imu sampling stopped");
    }

    @Override
    public void onSensorChanged(SensorEvent event) {
        double magnitude = Math.sqrt(
                event.values[0] * event.values[0]
                        + event.values[1] * event.values[1]
                        + event.values[2] * event.values[2]);
        if (event.sensor.getType() == Sensor.TYPE_ACCELEROMETER) {
            accelCount++;
            accelSumSquares += magnitude * magnitude;
            accelPeak = Math.max(accelPeak, magnitude);
        } else if (event.sensor.getType() == Sensor.TYPE_GYROSCOPE) {
            gyroCount++;
            gyroSumSquares += magnitude * magnitude;
            gyroPeak = Math.max(gyroPeak, magnitude);
        }
        if (System.currentTimeMillis() - windowStartMs >= config.imuWindowSeconds * 1000L) {
            flushWindow();
        }
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) {
    }

    private void flushWindow() {
        if (accelCount == 0 && gyroCount == 0) {
            resetWindow();
            return;
        }
        try {
            JSONObject imu = new JSONObject();
            imu.put("window_seconds", config.imuWindowSeconds);
            imu.put("accel_samples", accelCount);
            imu.put("accel_rms", accelCount > 0 ? Math.sqrt(accelSumSquares / accelCount) : 0.0);
            imu.put("accel_peak", accelPeak);
            imu.put("gyro_samples", gyroCount);
            imu.put("gyro_rms", gyroCount > 0 ? Math.sqrt(gyroSumSquares / gyroCount) : 0.0);
            imu.put("gyro_peak", gyroPeak);

            JSONObject meta = new JSONObject();
            meta.put("imu", imu);
            JSONObject envelope = EnvelopeSpooler.buildEnvelope(
                    config, sessionId, "auto", "sensor", windowStartMs, meta);
            spooler.spool(envelope, null, null);
        } catch (Exception e) {
            ProbeLog.append(context, "IMU_SPOOL_FAILED", e.getClass().getSimpleName() + ": " + e.getMessage());
        }
        resetWindow();
    }

    private void resetWindow() {
        windowStartMs = System.currentTimeMillis();
        accelCount = 0;
        accelSumSquares = 0;
        accelPeak = 0;
        gyroCount = 0;
        gyroSumSquares = 0;
        gyroPeak = 0;
    }
}
