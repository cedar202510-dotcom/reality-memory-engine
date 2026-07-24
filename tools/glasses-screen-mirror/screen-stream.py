"""眼镜屏幕镜像桥：adb screencap 循环抓屏 → MJPEG(multipart/x-mixed-replace) HTTP 服务。

用法：python3 screen-stream.py [port]（默认 8091）
  /stream  MJPEG 流（前端联调页地址栏填 http://127.0.0.1:8091/stream）
  /frame   最新单帧 PNG
帧率受 adb screencap 耗时限制（USB 下约 1-3 fps），足够看清眼镜 UI 状态。
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8091
BOUNDARY = "rme-screen"

latest: bytes | None = None
seq = 0
cond = threading.Condition()


def capture_loop() -> None:
    global latest, seq
    while True:
        try:
            png = subprocess.run(
                ["adb", "exec-out", "screencap", "-p"],
                capture_output=True, timeout=10,
            ).stdout
            if png[:8] == b"\x89PNG\r\n\x1a\n":  # 有效 PNG 才发布（设备断开时 stdout 为空/报错文本）
                with cond:
                    latest, seq = png, seq + 1
                    cond.notify_all()
        except Exception:
            pass
        time.sleep(0.15)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默访问日志
        pass

    def do_GET(self):
        if self.path.startswith("/frame"):
            with cond:
                frame = latest
            if frame is None:
                self.send_response(503); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(frame)
            return
        if not self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<body style='margin:0;background:#000'><img src='/stream' style='max-width:100vw'></body>")
            return
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last = -1
        try:
            while True:
                with cond:
                    cond.wait_for(lambda: seq != last, timeout=5)
                    frame, last = latest, seq
                if frame is None:
                    continue
                self.wfile.write(
                    f"--{BOUNDARY}\r\nContent-Type: image/png\r\nContent-Length: {len(frame)}\r\n\r\n".encode()
                )
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            pass  # 客户端关页是常态


threading.Thread(target=capture_loop, daemon=True).start()
print(f"glasses screen mirror at http://127.0.0.1:{PORT}/stream")
ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
