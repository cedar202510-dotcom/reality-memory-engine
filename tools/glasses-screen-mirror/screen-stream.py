"""眼镜屏幕镜像桥：adb screencap 循环抓屏 → MJPEG(multipart/x-mixed-replace) HTTP 服务。

用法：python3 screen-stream.py [port]（默认 8091）
  /stream  MJPEG 流（前端联调页地址栏填 http://127.0.0.1:8091/stream）
  /frame   最新单帧 PNG
  /status  JSON {seq, age_ms, live}，供前端判断画面是不是已经僵住
帧率受 adb screencap 耗时限制（USB 下约 1-3 fps），足够看清眼镜 UI 状态。

关于 /status：设备断开后 adb 不再产出新帧，但 latest 会永久保留最后一次成功的画面。
如果只看「流能不能连上」，前端会在设备掉线几小时后仍然显示「直播中」并挂着一张
陈旧画面——这比直接报错更容易误导。因此把「最后一帧多久以前」显式暴露出去。
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8091
BOUNDARY = "rme-screen"
# 超过该秒数没有新帧即视为不再直播（screencap 正常在 USB 下约 1-3 fps）
STALE_AFTER_SECONDS = 5.0

latest: bytes | None = None
seq = 0
last_frame_ts: float = 0.0
cond = threading.Condition()


def frame_age() -> float:
    """最后一帧距今秒数；从未成功抓到帧时返回 inf。"""
    return float("inf") if last_frame_ts == 0.0 else time.time() - last_frame_ts


def capture_loop() -> None:
    global latest, seq, last_frame_ts
    while True:
        try:
            png = subprocess.run(
                ["adb", "exec-out", "screencap", "-p"],
                capture_output=True, timeout=10,
            ).stdout
            if png[:8] == b"\x89PNG\r\n\x1a\n":  # 有效 PNG 才发布（设备断开时 stdout 为空/报错文本）
                with cond:
                    latest, seq, last_frame_ts = png, seq + 1, time.time()
                    cond.notify_all()
        except Exception:
            pass
        time.sleep(0.15)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 静默访问日志
        pass

    def do_GET(self):
        if self.path.startswith("/status"):
            age = frame_age()
            body = json.dumps({
                "seq": seq,
                "age_ms": None if age == float("inf") else int(age * 1000),
                "live": age <= STALE_AFTER_SECONDS,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            # 联调页跑在 :5173，与本服务不同源；img 标签不受限但 fetch 受限
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
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
                    # 超时返回时 seq 未变，说明没有新帧。此前这里无条件把同一帧再写一遍，
                    # 结果是设备掉线后流仍在「稳定输出」，前端永远看不出画面已经僵住。
                    fresh = cond.wait_for(lambda: seq != last, timeout=5)
                    frame, last = latest, seq
                if frame is None or not fresh:
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
