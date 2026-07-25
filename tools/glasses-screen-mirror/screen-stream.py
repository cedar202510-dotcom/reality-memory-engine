"""眼镜桥：adb screencap 循环抓屏 → MJPEG HTTP 服务，并在设备重新插上时自动恢复 adb forward。

用法：python3 screen-stream.py [port] [--forward 8090:8090 ...] [--no-forward]
  /stream  MJPEG 流（前端联调页地址栏填 http://127.0.0.1:8091/stream）
  /frame   最新单帧 PNG
  /status  JSON {seq, age_ms, live, device, forwards}
帧率受 adb screencap 耗时限制（USB 下约 1-3 fps），足够看清眼镜 UI 状态。

为什么要管 adb forward：眼镜画面有两条独立链路，断线行为完全不同。
  - 本服务的屏幕镜像走主机侧 screencap 轮询，不需要 forward，拔插后循环重试即可自愈；
  - 探针 App 的相机预览（眼镜上的 PreviewStreamServer:8090）必须靠 `adb forward` 打通，
    而 forward 在拔线时被 adb 销毁，插回去不会自动重建——于是相机预览永久失联。
既然本服务已经在持续探测设备在场状态，就顺带在「设备重新出现」的瞬间把 forward 重建，
省掉一次人工敲命令。这是联调期的便利，不属于产品链路。

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

argv = sys.argv[1:]
PORT = int(argv[0]) if argv and argv[0].isdigit() else 8091
# 设备回来时要重建的端口转发；--no-forward 关闭。默认带上探针相机预览用的 8090。
FORWARDS: list[str] = []
if "--no-forward" not in argv:
    FORWARDS = [argv[i + 1] for i, a in enumerate(argv) if a == "--forward"] or ["8090:8090"]

BOUNDARY = "rme-screen"
# 超过该秒数没有新帧即视为不再直播（screencap 正常在 USB 下约 1-3 fps）
STALE_AFTER_SECONDS = 5.0

latest: bytes | None = None
seq = 0
last_frame_ts: float = 0.0
device_present = False
forward_state: dict[str, str] = {}  # "8090:8090" -> ok / 错误原因
cond = threading.Condition()


def frame_age() -> float:
    """最后一帧距今秒数；从未成功抓到帧时返回 inf。"""
    return float("inf") if last_frame_ts == 0.0 else time.time() - last_frame_ts


def forward_loop() -> None:
    """周期性无条件执行 adb forward，用它的退出码作为转发状态的唯一真相。

    走过两版弯路，都是同一类错误——把一次性动作的结果当成持续状态汇报：
      1. 边沿触发（「抓帧失败 → 成功」时重建一次）。短暂重连时两侧 screencap 都可能
         成功，跳变根本不发生；转发也可能在设备始终在线时丢失（adb server 重启、
         手工 remove）。此时 forward_state 停留在上次的 ok，实际早已失效。
      2. 解析 `adb forward --list` 比对。该命令列的是**所有设备**的转发，不带设备
         过滤时会把别的设备的同端口转发误判成自己的（实测：指向不存在设备的实例
         照样报 ok）。

    adb forward 本身幂等，每 2 秒跑一次的开销可以忽略，而退出码直接反映目标设备的
    真实结果，不需要任何推断。简单的做法在这里同时也是唯一正确的做法。
    """
    global forward_state
    while True:
        state: dict[str, str] = {}
        for spec in FORWARDS:
            local, _, remote = spec.partition(":")
            try:
                proc = subprocess.run(
                    ["adb", "forward", f"tcp:{local}", f"tcp:{remote}"],
                    capture_output=True, timeout=10, text=True,
                )
                state[spec] = "ok" if proc.returncode == 0 else (proc.stderr or "failed").strip()[:120]
            except Exception as exc:  # noqa: BLE001 - 转发是尽力而为，失败不能拖垮抓屏
                state[spec] = str(exc)[:120]
            if forward_state.get(spec) != state[spec]:
                print(f"[bridge] adb forward {spec} → {state[spec]}", flush=True)
        forward_state = state
        time.sleep(2.0)


def capture_loop() -> None:
    global latest, seq, last_frame_ts, device_present
    while True:
        got_frame = False
        try:
            png = subprocess.run(
                ["adb", "exec-out", "screencap", "-p"],
                capture_output=True, timeout=10,
            ).stdout
            if png[:8] == b"\x89PNG\r\n\x1a\n":  # 有效 PNG 才发布（设备断开时 stdout 为空/报错文本）
                got_frame = True
                with cond:
                    latest, seq, last_frame_ts = png, seq + 1, time.time()
                    cond.notify_all()
        except Exception:
            pass

        if got_frame != device_present:
            device_present = got_frame
            print(
                f"[bridge] 设备{'已连接' if got_frame else '已断开，等待重新插上…'}",
                flush=True,
            )

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
                "device": device_present,
                "forwards": forward_state,
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
if FORWARDS:
    threading.Thread(target=forward_loop, daemon=True).start()
print(f"glasses screen mirror at http://127.0.0.1:{PORT}/stream")
ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
