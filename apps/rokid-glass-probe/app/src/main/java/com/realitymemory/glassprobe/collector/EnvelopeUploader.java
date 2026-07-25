package com.realitymemory.glassprobe.collector;

import android.content.Context;

import com.realitymemory.glassprobe.ProbeLog;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.List;

/**
 * 后台上传线程：定期 drain spool，multipart POST 到
 * {backend_base_url}/internal/v1/envelopes。
 *
 * - 幂等键由信封携带，重复投递后端直接吐回既有信封，所以"上传成功但删除前崩溃"
 *   最多造成一次无害的重放。
 * - 单条失败即停止本轮（保持时序、避免打爆后端），指数退避后重试。
 * - 不引第三方 HTTP 依赖，HttpURLConnection 足够且保持 Android Go 包体积。
 */
public final class EnvelopeUploader {
    private static final String BOUNDARY = "----RealityGlassProbe";
    private static final int CONNECT_TIMEOUT_MS = 10_000;
    private static final int READ_TIMEOUT_MS = 30_000;
    private static final long MAX_BACKOFF_MS = 5 * 60_000L;

    private final Context context;
    private final CollectorConfig config;
    private final EnvelopeSpooler spooler;

    private Thread worker;
    private volatile boolean running;

    public EnvelopeUploader(Context context, CollectorConfig config, EnvelopeSpooler spooler) {
        this.context = context.getApplicationContext();
        this.config = config;
        this.spooler = spooler;
    }

    public synchronized void start() {
        if (running || !config.canUpload()) {
            return;
        }
        running = true;
        worker = new Thread(this::loop, "envelope-uploader");
        worker.setDaemon(true);
        worker.start();
        ProbeLog.append(context, "UPLOADER_STARTED", "target=" + config.backendBaseUrl);
    }

    public synchronized void stop() {
        running = false;
        if (worker != null) {
            worker.interrupt();
            worker = null;
        }
        ProbeLog.append(context, "UPLOADER_STOPPED", "spool_depth=" + spooler.depth());
    }

    private void loop() {
        long backoffMs = 0;
        while (running) {
            try {
                boolean allOk = drainOnce();
                backoffMs = allOk ? 0 : Math.min(nextBackoff(backoffMs), MAX_BACKOFF_MS);
                Thread.sleep(config.uploadIntervalSeconds * 1000L + backoffMs);
            } catch (InterruptedException e) {
                return;
            } catch (Exception e) {
                ProbeLog.append(context, "UPLOADER_LOOP_ERROR", e.getClass().getSimpleName() + ": " + e.getMessage());
            }
        }
    }

    /** 返回 true 表示本轮没有遇到失败（含空队列）。 */
    private boolean drainOnce() {
        List<File> ready = spooler.listReady();
        for (File jsonFile : ready) {
            if (!running) {
                return true;
            }
            JSONObject item;
            try {
                item = new JSONObject(new String(Files.readAllBytes(jsonFile.toPath()), StandardCharsets.UTF_8));
            } catch (Exception e) {
                // 损坏任务：删除，不能让一条坏数据永久堵死队列。
                ProbeLog.append(context, "UPLOAD_ITEM_CORRUPT", jsonFile.getName());
                spooler.remove(jsonFile, null);
                continue;
            }

            String payloadFileName = item.optString("payload_file", null);
            long startedAt = System.currentTimeMillis();
            boolean ok = postEnvelope(item, payloadFileName);
            long latencyMs = System.currentTimeMillis() - startedAt;
            if (ok) {
                spooler.remove(jsonFile, payloadFileName);
                ProbeLog.append(context, "UPLOAD_OK",
                        jsonFile.getName() + ", latency_ms=" + latencyMs + ", spool_depth=" + spooler.depth());
            } else {
                ProbeLog.append(context, "UPLOAD_FAILED",
                        jsonFile.getName() + ", latency_ms=" + latencyMs + "; will retry");
                return false;
            }
        }
        return true;
    }

    private boolean postEnvelope(JSONObject item, String payloadFileName) {
        HttpURLConnection conn = null;
        try {
            JSONObject envelope = item.getJSONObject("envelope");
            URL url = new URL(config.backendBaseUrl + "/internal/v1/envelopes");
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setDoOutput(true);
            conn.setConnectTimeout(CONNECT_TIMEOUT_MS);
            conn.setReadTimeout(READ_TIMEOUT_MS);
            conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + BOUNDARY);

            try (OutputStream out = conn.getOutputStream()) {
                writeFormField(out, "envelope", envelope.toString());
                if (payloadFileName != null && !payloadFileName.isEmpty()) {
                    File payload = spooler.payloadFile(payloadFileName);
                    if (payload.exists()) {
                        String uploadName = item.optString("payload_name", "payload.bin");
                        writeFilePart(out, "files", uploadName, Files.readAllBytes(payload.toPath()));
                    }
                }
                out.write(("--" + BOUNDARY + "--\r\n").getBytes(StandardCharsets.UTF_8));
            }

            int code = conn.getResponseCode();
            if (code >= 200 && code < 300) {
                return true;
            }
            // 4xx 是契约级错误，重试不会好转：删除并审计，避免永久堵队列。
            if (code >= 400 && code < 500) {
                ProbeLog.append(context, "UPLOAD_REJECTED",
                        "http=" + code + ", dropping item; " + readError(conn));
                return true;
            }
            ProbeLog.append(context, "UPLOAD_HTTP_ERROR", "http=" + code + "; " + readError(conn));
            return false;
        } catch (Exception e) {
            // 异常类型和消息必须落日志。原来这里直接 return false，UPLOAD_FAILED 只有
            // 「latency_ms=34; will retry」——明文 HTTP 被系统拦截、DNS 不通、连接被拒
            // 全长一个样，只能靠猜。眼镜上没法挂调试器，日志是唯一的排查入口。
            ProbeLog.append(context, "UPLOAD_ERROR",
                    e.getClass().getSimpleName() + ": " + e.getMessage());
            return false;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    /** 读后端返回的错误体（截断）。契约不匹配时 422 的正文才是真正有用的那部分。 */
    private static String readError(HttpURLConnection conn) {
        try (InputStream err = conn.getErrorStream()) {
            if (err == null) {
                return "no body";
            }
            String body = new String(readAll(err), StandardCharsets.UTF_8).trim();
            return body.length() > 300 ? body.substring(0, 300) + "…" : body;
        } catch (Exception e) {
            return "unreadable: " + e.getClass().getSimpleName();
        }
    }

    private static byte[] readAll(InputStream in) throws Exception {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        int n;
        while ((n = in.read(chunk)) > 0) {
            buf.write(chunk, 0, n);
        }
        return buf.toByteArray();
    }

    private static void writeFormField(OutputStream out, String name, String value) throws Exception {
        String head = "--" + BOUNDARY + "\r\n"
                + "Content-Disposition: form-data; name=\"" + name + "\"\r\n\r\n";
        out.write(head.getBytes(StandardCharsets.UTF_8));
        out.write(value.getBytes(StandardCharsets.UTF_8));
        out.write("\r\n".getBytes(StandardCharsets.UTF_8));
    }

    private static void writeFilePart(OutputStream out, String name, String fileName, byte[] data) throws Exception {
        String contentType = fileName.endsWith(".wav") ? "audio/wav" : "image/jpeg";
        String head = "--" + BOUNDARY + "\r\n"
                + "Content-Disposition: form-data; name=\"" + name + "\"; filename=\"" + fileName + "\"\r\n"
                + "Content-Type: " + contentType + "\r\n\r\n";
        out.write(head.getBytes(StandardCharsets.UTF_8));
        out.write(data);
        out.write("\r\n".getBytes(StandardCharsets.UTF_8));
    }

    private static long nextBackoff(long current) {
        return current == 0 ? 5_000L : current * 2;
    }
}
