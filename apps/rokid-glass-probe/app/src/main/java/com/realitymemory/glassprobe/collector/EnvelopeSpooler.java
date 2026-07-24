package com.realitymemory.glassprobe.collector;

import android.content.Context;

import com.realitymemory.glassprobe.ProbeLog;

import org.json.JSONObject;

import java.io.File;
import java.io.FileWriter;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 本地持久化上传队列（spool-and-forward）。
 *
 * 每条待上传信封在 files/spool/ 下有两个文件：
 *   <key>.json     信封 + 上传所需的内部字段（payload 文件名等）
 *   <key>.payload  可选的媒体附件（JPEG / WAV），sensor 信封没有附件
 *
 * 断网、服务被杀、眼镜重启后，spool 内容仍在，由 EnvelopeUploader 续传。
 * 写入顺序保证：先写 payload，再写 json；只有 json 存在才算就绪，
 * 所以任何时刻崩溃都不会产生"半条"任务被上传。
 */
public final class EnvelopeSpooler {
    private static final String SPOOL_DIR = "spool";
    private static final int MAX_ITEMS = 300;   // 超过则丢最旧的，防止塞满眼镜存储

    private static final AtomicLong SEQ = new AtomicLong();

    private final Context context;

    public EnvelopeSpooler(Context context) {
        this.context = context.getApplicationContext();
    }

    /** 组装一条 SourceEnvelopeIn 信封（字段与后端 schemas.SourceEnvelopeIn 一一对应）。 */
    public static JSONObject buildEnvelope(
            CollectorConfig config,
            String sessionId,
            String trigger,
            String modality,
            long occurredAtMs,
            JSONObject extraMeta
    ) throws Exception {
        String key = sessionId + "-" + occurredAtMs + "-" + SEQ.incrementAndGet();

        JSONObject meta = extraMeta != null ? extraMeta : new JSONObject();
        meta.put("device_kind", CollectorConfig.DEVICE_KIND);
        meta.put("device_adapter", CollectorConfig.DEVICE_ADAPTER);

        JSONObject envelope = new JSONObject();
        if (!config.deviceId.isEmpty()) {
            envelope.put("device_id", config.deviceId);
        }
        envelope.put("source_session_id", sessionId);
        envelope.put("occurred_at", isoUtc(occurredAtMs));
        envelope.put("observed_at", isoUtc(System.currentTimeMillis()));
        envelope.put("idempotency_key", key);
        envelope.put("trigger", trigger);
        envelope.put("modality", modality);
        envelope.put("meta", meta);
        return envelope;
    }

    /** 入队。payload 可为 null（sensor 摘要信封只有 meta）。 */
    public void spool(JSONObject envelope, byte[] payload, String payloadName) {
        try {
            File dir = spoolDir();
            String key = envelope.getString("idempotency_key");

            JSONObject item = new JSONObject();
            item.put("envelope", envelope);
            item.put("created_ms", System.currentTimeMillis());
            if (payload != null) {
                File payloadFile = new File(dir, key + ".payload");
                java.nio.file.Files.write(payloadFile.toPath(), payload);
                item.put("payload_file", payloadFile.getName());
                item.put("payload_name", payloadName);
            }

            File jsonFile = new File(dir, key + ".json");
            try (FileWriter writer = new FileWriter(jsonFile)) {
                writer.write(item.toString());
            }
            enforceCap(dir);
        } catch (Exception e) {
            ProbeLog.append(context, "SPOOL_FAILED", e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    /** 就绪任务的 json 文件，按创建时间从旧到新。 */
    public List<File> listReady() {
        File[] files = spoolDir().listFiles((dir, name) -> name.endsWith(".json"));
        if (files == null) {
            return new ArrayList<>();
        }
        List<File> list = new ArrayList<>(Arrays.asList(files));
        list.sort(Comparator.comparingLong(File::lastModified));
        return list;
    }

    public File payloadFile(String payloadFileName) {
        return new File(spoolDir(), payloadFileName);
    }

    /** 上传成功后删除任务及其附件。 */
    public void remove(File jsonFile, String payloadFileName) {
        if (payloadFileName != null) {
            //noinspection ResultOfMethodCallIgnored
            new File(spoolDir(), payloadFileName).delete();
        }
        //noinspection ResultOfMethodCallIgnored
        jsonFile.delete();
    }

    public int depth() {
        File[] files = spoolDir().listFiles((dir, name) -> name.endsWith(".json"));
        return files == null ? 0 : files.length;
    }

    private File spoolDir() {
        File dir = new File(context.getFilesDir(), SPOOL_DIR);
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        return dir;
    }

    private void enforceCap(File dir) {
        List<File> ready = listReady();
        int overflow = ready.size() - MAX_ITEMS;
        for (int i = 0; i < overflow; i++) {
            File oldest = ready.get(i);
            try {
                JSONObject item = new JSONObject(new String(
                        java.nio.file.Files.readAllBytes(oldest.toPath())));
                remove(oldest, item.optString("payload_file", null));
                ProbeLog.append(context, "SPOOL_DROPPED", "capacity cap, dropped " + oldest.getName());
            } catch (Exception e) {
                //noinspection ResultOfMethodCallIgnored
                oldest.delete();
            }
        }
    }

    private static String isoUtc(long epochMs) {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));
        return format.format(new Date(epochMs));
    }
}
