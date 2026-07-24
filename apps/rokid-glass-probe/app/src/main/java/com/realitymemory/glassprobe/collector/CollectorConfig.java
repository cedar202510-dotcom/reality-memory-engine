package com.realitymemory.glassprobe.collector;

import android.content.Context;

import java.io.File;
import java.io.FileInputStream;
import java.util.Properties;

/**
 * 采集/上报配置。从 files/collector.properties 读取，改配置不需要重新打包：
 *
 *   adb shell "run-as com.realitymemory.glassprobe sh -c 'cat > files/collector.properties'" <<'EOF'
 *   upload_enabled=true
 *   backend_base_url=http://192.168.1.10:8000
 *   device_id=550e8400-e29b-41d4-a716-446655440000
 *   audio_enabled=true
 *   imu_enabled=true
 *   EOF
 *
 * 文件不存在时全部使用默认值：不上传、不采音频、不采 IMU，行为与旧探针一致。
 */
public final class CollectorConfig {
    private static final String FILE_NAME = "collector.properties";

    public final boolean uploadEnabled;
    public final String backendBaseUrl;
    public final String deviceId;          // 后端 devices 表注册后下发的 UUID，可为空
    public final boolean audioEnabled;
    public final boolean imuEnabled;
    public final int audioChunkSeconds;
    public final int imuWindowSeconds;
    public final int uploadIntervalSeconds;
    public final int previewPort;
    public final int previewMaxFps;
    public final int previewJpegQuality;

    public static final String DEVICE_KIND = "rokid_glasses";
    public static final String DEVICE_ADAPTER = "rokid-glass-probe/0.2.0";

    private CollectorConfig(Properties props) {
        uploadEnabled = Boolean.parseBoolean(props.getProperty("upload_enabled", "false"));
        backendBaseUrl = trimTrailingSlash(props.getProperty("backend_base_url", ""));
        deviceId = props.getProperty("device_id", "").trim();
        audioEnabled = Boolean.parseBoolean(props.getProperty("audio_enabled", "false"));
        imuEnabled = Boolean.parseBoolean(props.getProperty("imu_enabled", "false"));
        audioChunkSeconds = parseInt(props.getProperty("audio_chunk_seconds"), 20, 5, 60);
        imuWindowSeconds = parseInt(props.getProperty("imu_window_seconds"), 10, 2, 60);
        uploadIntervalSeconds = parseInt(props.getProperty("upload_interval_seconds"), 5, 1, 300);
        previewPort = parseInt(props.getProperty("preview_port"), 8090, 1024, 65535);
        previewMaxFps = parseInt(props.getProperty("preview_max_fps"), 10, 1, 30);
        previewJpegQuality = parseInt(props.getProperty("preview_jpeg_quality"), 70, 30, 95);
    }

    public static CollectorConfig load(Context context) {
        Properties props = new Properties();
        File file = new File(context.getFilesDir(), FILE_NAME);
        if (file.exists()) {
            try (FileInputStream in = new FileInputStream(file)) {
                props.load(in);
            } catch (Exception ignored) {
                // 配置损坏时按默认值运行，不让配置问题弄崩采集服务。
            }
        }
        return new CollectorConfig(props);
    }

    /** 上传的前提：开关打开且填写了后端地址。 */
    public boolean canUpload() {
        return uploadEnabled && !backendBaseUrl.isEmpty();
    }

    public String describe() {
        return "upload=" + uploadEnabled
                + ", base_url=" + (backendBaseUrl.isEmpty() ? "<unset>" : backendBaseUrl)
                + ", device_id=" + (deviceId.isEmpty() ? "<unset>" : deviceId)
                + ", audio=" + audioEnabled
                + ", imu=" + imuEnabled;
    }

    private static String trimTrailingSlash(String url) {
        String trimmed = url.trim();
        while (trimmed.endsWith("/")) {
            trimmed = trimmed.substring(0, trimmed.length() - 1);
        }
        return trimmed;
    }

    private static int parseInt(String raw, int fallback, int min, int max) {
        try {
            int value = Integer.parseInt(raw.trim());
            return Math.max(min, Math.min(max, value));
        } catch (Exception e) {
            return fallback;
        }
    }
}
