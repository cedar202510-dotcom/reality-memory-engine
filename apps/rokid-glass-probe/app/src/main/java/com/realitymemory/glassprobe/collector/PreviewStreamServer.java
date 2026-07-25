package com.realitymemory.glassprobe.collector;

import android.content.Context;

import com.realitymemory.glassprobe.ProbeLog;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 眼镜本机 MJPEG 预览服务器：把相机实时帧以 multipart/x-mixed-replace 推给浏览器。
 *
 * 电脑侧两种接入方式（见 README）：
 *   1. 开发线：adb forward tcp:8090 tcp:8090 后打开 http://127.0.0.1:8090
 *   2. 同一局域网：直接打开 http://<眼镜IP>:8090
 *
 * 仅调试用途：无认证，明文 HTTP。默认关闭，由 UI 按钮显式开启。
 */
public final class PreviewStreamServer {
    private static final String BOUNDARY = "rme-frame";
    private static final int MAX_EVENTS = 50;

    /** 采集事件环形缓冲（静态：无论预览是否开启都先记着，开启后 /events 可查）。 */
    private static final ArrayDeque<String> EVENTS = new ArrayDeque<>();

    /** 拍照/采集状态变化时由 CaptureForegroundService 调用；type 如 photo_captured。 */
    public static void recordEvent(String type, String detail) {
        String json = "{\"ts\":" + System.currentTimeMillis()
                + ",\"type\":\"" + type + "\",\"detail\":\"" + detail.replace("\"", "'") + "\"}";
        synchronized (EVENTS) {
            EVENTS.addLast(json);
            while (EVENTS.size() > MAX_EVENTS) {
                EVENTS.removeFirst();
            }
        }
    }

    private final Context context;
    private final int port;

    private ServerSocket serverSocket;
    private Thread acceptThread;
    private volatile boolean running;

    private final Object frameLock = new Object();
    private byte[] latestFrame;
    private long frameSeq;
    private final AtomicInteger clientCount = new AtomicInteger();

    public PreviewStreamServer(Context context, int port) {
        this.context = context.getApplicationContext();
        this.port = port;
    }

    public synchronized void start() {
        if (running) {
            return;
        }
        try {
            serverSocket = new ServerSocket(port);
        } catch (Exception e) {
            ProbeLog.append(context, "PREVIEW_BIND_FAILED", "port=" + port + ", " + e.getMessage());
            return;
        }
        running = true;
        acceptThread = new Thread(this::acceptLoop, "preview-server");
        acceptThread.setDaemon(true);
        acceptThread.start();
        ProbeLog.append(context, "PREVIEW_STARTED",
                "http://127.0.0.1:" + port + " (adb forward tcp:" + port + " tcp:" + port + ")");
    }

    public synchronized void stop() {
        if (!running) {
            return;
        }
        running = false;
        try {
            serverSocket.close();
        } catch (Exception ignored) {
        }
        synchronized (frameLock) {
            frameLock.notifyAll();   // 唤醒等帧的客户端线程，让它们发现 running=false 退出
        }
        acceptThread = null;
        ProbeLog.append(context, "PREVIEW_STOPPED", "preview server stopped");
    }

    public boolean isRunning() {
        return running;
    }

    /** 有客户端在看才值得做 YUV→JPEG 转换，采集侧据此跳过无人观看时的编码开销。 */
    public boolean hasViewers() {
        return running && clientCount.get() > 0;
    }

    /** 相机分析线程推入最新帧（JPEG 字节）。 */
    public void submitFrame(byte[] jpeg) {
        synchronized (frameLock) {
            latestFrame = jpeg;
            frameSeq++;
            frameLock.notifyAll();
        }
    }

    private void acceptLoop() {
        while (running) {
            try {
                Socket socket = serverSocket.accept();
                Thread client = new Thread(() -> serveClient(socket), "preview-client");
                client.setDaemon(true);
                client.start();
            } catch (Exception e) {
                if (running) {
                    ProbeLog.append(context, "PREVIEW_ACCEPT_ERROR", e.getMessage());
                }
                return;
            }
        }
    }

    private void serveClient(Socket socket) {
        try (Socket s = socket) {
            s.setTcpNoDelay(true);
            BufferedReader reader = new BufferedReader(
                    new InputStreamReader(s.getInputStream(), StandardCharsets.US_ASCII));
            String requestLine = reader.readLine();
            if (requestLine == null) {
                return;
            }
            String path = requestLine.split(" ").length > 1 ? requestLine.split(" ")[1] : "/";
            // 读掉剩余请求头
            String line;
            while ((line = reader.readLine()) != null && !line.isEmpty()) {
                // ignore
            }

            OutputStream out = s.getOutputStream();
            if (path.startsWith("/stream")) {
                serveStream(out);
            } else if (path.startsWith("/frame")) {
                serveSingleFrame(out);
            } else if (path.startsWith("/events")) {
                serveEvents(out);
            } else {
                serveIndex(out);
            }
        } catch (Exception ignored) {
            // 客户端断开是常态（关标签页），不当错误记录。
        }
    }

    private void serveIndex(OutputStream out) throws Exception {
        String html = "<!doctype html><html><head><meta charset='utf-8'>"
                + "<title>Reality Glass Preview</title>"
                + "<style>body{margin:0;background:#000;display:flex;flex-direction:column;"
                + "align-items:center;color:#0f6;font-family:monospace}"
                + "img{max-width:100vw;max-height:90vh}</style></head>"
                + "<body><p>Reality Glass live preview</p>"
                + "<img src='/stream' alt='waiting for frames...'></body></html>";
        byte[] body = html.getBytes(StandardCharsets.UTF_8);
        String head = "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                + "Content-Length: " + body.length + "\r\nConnection: close\r\n\r\n";
        out.write(head.getBytes(StandardCharsets.US_ASCII));
        out.write(body);
        out.flush();
    }

    /** 最近采集事件 JSON 数组；带 CORS 头供前端联调页跨源轮询。 */
    private void serveEvents(OutputStream out) throws Exception {
        List<String> snapshot;
        synchronized (EVENTS) {
            snapshot = new ArrayList<>(EVENTS);
        }
        byte[] body = ("[" + String.join(",", snapshot) + "]").getBytes(StandardCharsets.UTF_8);
        String head = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + "Access-Control-Allow-Origin: *\r\nCache-Control: no-cache\r\n"
                + "Content-Length: " + body.length + "\r\nConnection: close\r\n\r\n";
        out.write(head.getBytes(StandardCharsets.US_ASCII));
        out.write(body);
        out.flush();
    }

    private void serveSingleFrame(OutputStream out) throws Exception {
        byte[] frame;
        synchronized (frameLock) {
            frame = latestFrame;
        }
        if (frame == null) {
            out.write("HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n"
                    .getBytes(StandardCharsets.US_ASCII));
            out.flush();
            return;
        }
        String head = "HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\n"
                + "Content-Length: " + frame.length + "\r\nConnection: close\r\n\r\n";
        out.write(head.getBytes(StandardCharsets.US_ASCII));
        out.write(frame);
        out.flush();
    }

    private void serveStream(OutputStream out) throws Exception {
        String head = "HTTP/1.1 200 OK\r\n"
                + "Content-Type: multipart/x-mixed-replace; boundary=" + BOUNDARY + "\r\n"
                + "Cache-Control: no-cache\r\nConnection: close\r\n\r\n";
        out.write(head.getBytes(StandardCharsets.US_ASCII));

        clientCount.incrementAndGet();
        ProbeLog.append(context, "PREVIEW_CLIENT_JOINED", "viewers=" + clientCount.get());
        try {
            long lastSeq = -1;
            while (running) {
                byte[] frame;
                synchronized (frameLock) {
                    while (running && frameSeq == lastSeq) {
                        frameLock.wait(1000);
                    }
                    if (!running) {
                        return;
                    }
                    frame = latestFrame;
                    lastSeq = frameSeq;
                }
                if (frame == null) {
                    continue;
                }
                String part = "--" + BOUNDARY + "\r\nContent-Type: image/jpeg\r\n"
                        + "Content-Length: " + frame.length + "\r\n\r\n";
                out.write(part.getBytes(StandardCharsets.US_ASCII));
                out.write(frame);
                out.write("\r\n".getBytes(StandardCharsets.US_ASCII));
                out.flush();
            }
        } finally {
            clientCount.decrementAndGet();
            ProbeLog.append(context, "PREVIEW_CLIENT_LEFT", "viewers=" + clientCount.get());
        }
    }
}
