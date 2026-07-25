"""下行运行时：订阅设备消息 → 本地策略 → 录音/播报 → 回执。

通道选择与后端 `app/connectors/inbox.py` 的目标形态一致：优先长连
（`WS /internal/v1/devices/{id}/stream`），连不上就退回轮询
（`GET /internal/v1/devices/{id}/inbox`）。两条路拿到的是同一种信封，处理代码只有一份。

三个刻意的设计：

1. **收发分离。** 接收循环只做「收下来丢进队列」，真正的录音/播报在单独的 worker 里
   串行执行。录一段 60 秒的音频会阻塞 60 秒，如果它挡在接收循环上，服务端的心跳会
   超时把连接掐了（默认 90s 空闲断开）。
2. **回执一律走 HTTP。** 长连也能回执，但那样就有两条回执路径要维护，而回执的可靠性
   比它的延迟重要得多——轮询模式下本来也只能走 HTTP。
3. **先占坑再执行。** 投递是至少一次的，同一条请求会到达两次；占坑记录落盘，重启也
   不会重放。重投时原样补发上次的终态，而不是重新录一段。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable, Iterator, Protocol

from .audio import wav_duration_seconds, wav_peak_level
from .client import BackendClient
from .config import Config
from .policy import Decision, LocalPolicy
from .spool import Spool
from .uplink import Uplink, utcnow
from .vad import Segment

# 一次监听活过这么久才算「链路是好的」，短于它就按故障退避重连
MIN_HEALTHY_LISTEN_SECONDS = 1.0
MAX_LISTEN_BACKOFF_SECONDS = 30.0

CAPTURE_REQUEST = "CAPTURE_REQUEST"
REMINDER_SIGNAL = "REMINDER_SIGNAL"
PRIVACY_PAUSE = "PRIVACY_PAUSE"


class Recorder(Protocol):
    """录音后端。抽成协议是为了让测试跑在没有耳机、也没有 ffmpeg 的机器上。"""

    def __call__(self, seconds: float) -> bytes: ...


class Speaker(Protocol):
    """播报后端。返回实际使用的音色名，进回执——用错音色（英文音色念中文）时
    `say` 照样返回 0，不把音色记下来的话，事后只能听见「一串乱码」而查不出原因。"""

    def __call__(self, text: str) -> str | None: ...


@dataclass
class Outcome:
    """一条消息的处理结果：一个终态回执 + 附带细节。"""

    status: str
    detail: dict[str, Any]


class EarbudsRuntime:
    def __init__(
        self,
        *,
        config: Config,
        policy: LocalPolicy,
        uplink: Uplink,
        client: BackendClient,
        spool: Spool,
        recorder: Recorder,
        speaker: Speaker,
        output_probe: Callable[[], str | None],
        log: Callable[[str], None] = print,
        segment_source: Callable[[], Iterator[Segment]] | None = None,
    ) -> None:
        self.config = config
        self.policy = policy
        self.uplink = uplink
        self.client = client
        self.spool = spool
        self.recorder = recorder
        self.speaker = speaker
        self.output_probe = output_probe
        self.log = log
        self.segment_source = segment_source

        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._periodic: asyncio.Task | None = None
        self._stop = asyncio.Event()
        # 会话线程的退出信号。麦克风读取是阻塞的，只能靠线程 + 事件停。
        self._listen_stop = threading.Event()

    # ---------------------------------------------------------------- 主循环

    async def run(self) -> None:
        """跑到被 stop() 或 Ctrl-C 打断为止。"""
        workers = [
            asyncio.create_task(self._worker(), name="earbuds-worker"),
            asyncio.create_task(self._drain_loop(), name="earbuds-drain"),
            asyncio.create_task(self._receive_loop(), name="earbuds-receive"),
        ]
        try:
            await self._stop.wait()
        finally:
            await self._cancel_periodic()
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    def stop(self) -> None:
        self._stop.set()

    async def _receive_loop(self) -> None:
        """长连优先，断了就退回轮询，好了再切回来。"""
        while not self._stop.is_set():
            try:
                connected = await self._ws_session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 任何连接问题都退回轮询，不能让运行时死掉
                connected = False
                self.log(f"[downlink] 长连不可用（{type(exc).__name__}: {exc}），退回 inbox 轮询")
            if not connected:
                with contextlib.suppress(Exception):
                    await self._poll_once()
                await asyncio.sleep(self.config.poll_interval_seconds)

    async def _ws_session(self) -> bool:
        """跑一次长连会话。返回 True 表示连上过（断开后由外层重连）。"""
        try:
            import websockets
        except ImportError:
            return False

        async with websockets.connect(self.config.ws_url) as ws:
            self.log(f"[downlink] 长连已建立：{self.config.ws_url}")
            # 连上先补一次 inbox：长连只推「连接期间」的消息，服务端会在连上时冲积压，
            # 但轮询期间被标成 SENT 的消息不会二次推送，补一次最省心。
            with contextlib.suppress(Exception):
                await self._poll_once()
            while not self._stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=self.config.ping_interval_seconds)
                except asyncio.TimeoutError:
                    # 服务端 device_ws_idle_timeout_seconds 内没收到任何帧就会断开，
                    # 心跳的唯一作用是让它知道我们还在。
                    await ws.send(json.dumps({"type": "ping"}))
                    continue
                frame = json.loads(raw)
                if frame.get("type") in ("pong", "receipt_ack", "error"):
                    if frame.get("type") == "error":
                        self.log(f"[downlink] 服务端报错帧：{frame.get('detail')}")
                    continue
                await self._enqueue(frame)
        return True

    async def _poll_once(self) -> None:
        messages = await self.client.fetch_inbox(self.config.device_id)
        for message in messages:
            await self._enqueue(message)

    async def _enqueue(self, message: dict[str, Any]) -> None:
        if not message.get("message_id"):
            return
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            # 队列满 = 前面还有几十条没处理完，此时再收只会让延迟更离谱。丢掉不回执，
            # 消息仍在服务端待投递集合里，下一轮 inbox 会再给我们一次。
            self.log("[downlink] 处理队列已满，本条留给下一轮补投")

    async def _worker(self) -> None:
        while True:
            message = await self._queue.get()
            try:
                await self.handle_message(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 单条消息的失败不能带走 worker
                self.log(f"[downlink] 处理消息失败：{type(exc).__name__}: {exc}")
            finally:
                self._queue.task_done()

    async def _drain_loop(self) -> None:
        """定期把 spool 里的积压推上去（断网期间录的音靠这条路补上来）。"""
        while True:
            await asyncio.sleep(self.config.poll_interval_seconds)
            if self.spool.depth() == 0:
                continue
            report = await self.uplink.drain()
            if report.uploaded or report.rejected:
                self.log(
                    f"[uplink] 补传 {report.uploaded} 条，重复 {report.duplicates} 条，"
                    f"拒收 {report.rejected} 条，待重试 {report.retry_later} 条"
                )

    # ---------------------------------------------------------------- 消息处理

    async def handle_message(self, message: dict[str, Any]) -> None:
        message_id = str(message["message_id"])
        if not self.spool.claim(message_id):
            await self._resend_prior_outcome(message_id)
            return

        await self._receipt(message_id, "RECEIVED", {"runtime": "iflybuds-host-collector"})
        message_type = message.get("message_type")
        if message_type == CAPTURE_REQUEST:
            outcome = await self._handle_capture(message)
        elif message_type == REMINDER_SIGNAL:
            outcome = await self._handle_reminder(message)
        elif message_type == PRIVACY_PAUSE:
            self.policy.pause("云端下发 PRIVACY_PAUSE")
            outcome = Outcome("DISMISSED", {"applied": "paused"})
        else:
            # 未实现的类型也必须落终态：不终结的消息会一直留在待投递集合里，
            # 每次重连都再推一遍，看起来像消息风暴。
            outcome = Outcome(
                "DISMISSED",
                {"unsupported_message_type": message_type, "runtime": "iflybuds-host-collector"},
            )

        self.spool.record_outcome(message_id, outcome.status)
        await self._receipt(message_id, outcome.status, outcome.detail)

    async def _resend_prior_outcome(self, message_id: str) -> None:
        """重投的消息不重新执行，只补发上次的终态。"""
        prior = self.spool.outcome_of(message_id)
        if prior:
            await self._receipt(message_id, prior, {"duplicate_delivery": True})
            return
        # 占了坑却没有结果 = 上次处理到一半进程没了。既不能宣称执行成功，也不能装作
        # 没发生过，如实回一条 FAILED 让控制台知道这条请求结局未知。
        await self._receipt(
            message_id,
            "FAILED",
            {
                "reason": "collector_restarted_mid_flight",
                "message": "采集器在处理这条请求时重启，执行结果未知，未重复执行",
            },
        )
        self.spool.record_outcome(message_id, "FAILED")

    async def _handle_capture(self, message: dict[str, Any]) -> Outcome:
        payload = message.get("payload") or {}
        action = str(payload.get("action", "UNKNOWN"))
        duration = payload.get("duration_seconds")
        decision = self.policy.check_capture(action, duration)
        if not decision.allowed:
            return Outcome("REJECTED", decision.detail)

        if action == "PAUSE":
            self.policy.pause("云端下发 PAUSE")
            return Outcome("EXECUTED", {"action": action, "paused": True})
        if action == "RESUME":
            self.policy.resume()
            return Outcome("EXECUTED", {"action": action, "paused": False})
        if action == "STOP":
            stopped = await self._cancel_periodic()
            return Outcome("EXECUTED", {"action": action, "periodic_stopped": stopped})
        if action == "START_PERIODIC":
            detail = await self.start_session(interval_seconds=payload.get("interval_seconds"))
            return Outcome("EXECUTED", {"action": action, **detail})

        # CAPTURE_AUDIO
        seconds = float(
            decision.detail.get("clamped_duration_seconds")
            or duration
            or self.config.default_duration_seconds
        )
        try:
            detail = await self._capture_audio(
                seconds=seconds,
                trigger="explicit",
                meta={
                    "capture_request_message_id": str(message["message_id"]),
                    "capture_trigger": payload.get("trigger"),
                },
            )
        except Exception as exc:  # noqa: BLE001 — 录音/上传的失败是链路问题，不是策略拒绝
            return Outcome("FAILED", {"reason": type(exc).__name__, "message": str(exc)})
        return Outcome("EXECUTED", {**decision.detail, **detail})

    async def _capture_audio(
        self, *, seconds: float, trigger: str, meta: dict[str, Any]
    ) -> dict[str, Any]:
        """录一段 → 落 spool → 立刻尝试上传。返回进回执的细节。

        录音走线程：底层是 ffmpeg 子进程，阻塞几十秒，不能占着事件循环。
        """
        started = utcnow()
        wav = await asyncio.to_thread(self.recorder, seconds)
        finished = utcnow()
        actual = wav_duration_seconds(wav)
        peak = wav_peak_level(wav)
        entry = self.uplink.enqueue_audio(
            wav=wav,
            occurred_at=started,
            observed_at=finished,
            trigger=trigger,
            meta={
                **{k: v for k, v in meta.items() if v is not None},
                # effective = 本地策略裁决之后真正录的秒数；请求的原始秒数（可能已被
                # 采集预算截断）由策略层写进回执，两者不能共用一个名字。
                "effective_duration_seconds": seconds,
                "actual_duration_seconds": actual,
                "peak_level": peak,
                "input_device": self.config.input_device,
            },
        )
        report = await self.uplink.drain()
        detail: dict[str, Any] = {
            "idempotency_key": entry.key,
            "bytes": len(wav),
            "effective_duration_seconds": seconds,
            "actual_duration_seconds": actual,
            # 电平进回执，是为了让「录到了但是一片静音」在控制台上就能看出来，
            # 而不是等到转写返回空文本才发现耳机麦克风根本没被选中。
            "peak_level": peak,
            "uploaded": report.uploaded,
            "spool_depth": self.spool.depth(),
        }
        if report.envelope_ids:
            detail["envelope_id"] = report.envelope_ids[0]
        if not report.clean:
            detail["upload_pending"] = True
            detail["upload_errors"] = report.errors[:3]
        return detail

    # ---------------------------------------------------------------- 记忆会话

    async def start_session(self, *, interval_seconds: int | None = None) -> dict[str, Any]:
        """开启一段记忆会话，返回进回执与日志的细节。

        对耳机来说 START_PERIODIC 的语义就是「开始记忆这段时间」。具体怎么采由本地
        `capture_mode` 决定，并在回执里如实标注——云端以为自己开的是定时采集、实际跑的是
        VAD 分段，这个差异必须让控制台看得见，而不是悄悄替它决定。
        """
        await self._cancel_periodic()
        if self.config.capture_mode == "vad":
            self._periodic = asyncio.create_task(
                self._vad_session_loop(), name="earbuds-vad-session"
            )
            detail: dict[str, Any] = {
                "mode": "vad",
                "note": "记忆会话已开启：监听麦克风，按「一句话」自动分段上传",
                "silence_ms": self.config.vad_silence_ms,
                "min_speech_ms": self.config.vad_min_speech_ms,
            }
            if interval_seconds:
                detail["ignored"] = {
                    "interval_seconds": "VAD 模式下断句由语音停顿决定，间隔参数不生效"
                }
            return detail

        interval = int(interval_seconds or self.config.default_interval_seconds)
        self._periodic = asyncio.create_task(
            self._periodic_loop(interval), name="earbuds-periodic"
        )
        return {
            "mode": "periodic",
            "interval_seconds": interval,
            "duration_seconds": self.config.default_duration_seconds,
            "note": "周期采集已启动；每轮录一段定长音频并上传",
        }

    async def stop_session(self) -> bool:
        return await self._cancel_periodic()

    # ---------------------------------------------------------------- VAD 会话

    def _default_segment_source(self) -> Iterator[Segment]:
        """真麦克风 + VAD。每帧检查一次停止信号，暂停时能立刻把麦克风关掉。

        停止检查放在帧级而不是句级：句级检查意味着「按了暂停但当前这句说完之前麦克风
        还开着」，那不叫暂停。
        """
        from .audio import resolve_input_device
        from .vad import MicStream, VadConfig, VadSegmenter

        device = resolve_input_device(self.config.input_device, self.config.ffmpeg_binary)
        vad_config = VadConfig(
            sample_rate=self.config.sample_rate,
            end_silence_ms=self.config.vad_silence_ms,
            min_speech_ms=self.config.vad_min_speech_ms,
            max_segment_ms=self.config.vad_max_segment_ms,
            threshold_factor=self.config.vad_threshold_factor,
        )
        segmenter = VadSegmenter(vad_config)
        self.log(f"[capture] 监听 {device}（静音 {vad_config.end_silence_ms}ms 断句）")
        with MicStream(
            device_index=device.index,
            sample_rate=self.config.sample_rate,
            frame_bytes=segmenter.frame_bytes,
            ffmpeg_binary=self.config.ffmpeg_binary,
        ) as stream:
            for frame in stream.frames():
                if self._listen_stop.is_set():
                    break
                segment = segmenter.push(frame)
                if segment is not None:
                    yield segment
            tail = segmenter.flush()
            if tail is not None:
                yield tail

    async def _vad_session_loop(self) -> None:
        """记忆会话：一直听，按句上传，直到 STOP。

        隐私暂停期间**麦克风保持关闭**，而不是「照采不传」——04 号文档原则 4 说的是
        摘下眼镜等于停止采集。这条在耳机上更要紧：耳机没有佩戴检测，暂停开关是用户
        唯一能真正关掉麦克风的手段。
        """
        loop = asyncio.get_running_loop()
        backoff = 1.0
        try:
            while True:
                if self.policy.paused:
                    await asyncio.sleep(1.0)
                    continue
                started = loop.time()
                await self._listen_until_paused()
                if self.policy.paused:
                    backoff = 1.0
                    continue
                elapsed = loop.time() - started
                if elapsed >= MIN_HEALTHY_LISTEN_SECONDS:
                    backoff = 1.0
                    continue
                # 麦克风流刚开就结束了：耳机断连、被别的 App 独占、ffmpeg 起不来。
                # 不退避的话这里会变成一个吃满 CPU、每秒拉起几百个 ffmpeg 的死循环。
                self.log(
                    f"[capture] 麦克风流意外结束（{elapsed:.2f}s），{backoff:.0f}s 后重试"
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, MAX_LISTEN_BACKOFF_SECONDS)
        except asyncio.CancelledError:
            raise
        finally:
            self._listen_stop.set()
            self.log("[capture] 记忆会话已结束")

    async def _listen_until_paused(self) -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Segment | BaseException | None] = asyncio.Queue()
        self._listen_stop.clear()
        source = self.segment_source or self._default_segment_source

        def reader() -> None:
            try:
                for segment in source():
                    loop.call_soon_threadsafe(queue.put_nowait, segment)
                    if self._listen_stop.is_set():
                        break
            except BaseException as exc:  # noqa: BLE001 — 线程里的异常必须搬回事件循环
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        thread = threading.Thread(target=reader, name="earbuds-mic", daemon=True)
        thread.start()
        try:
            while True:
                try:
                    # 超时轮询而不是纯阻塞等：暂停信号来自另一个协程，而下一段语音
                    # 可能几分钟都不来，不能等到那时候才发现该关麦克风。
                    item = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if self.policy.paused:
                        return
                    continue
                if item is None:
                    return
                if isinstance(item, BaseException):
                    self.log(f"[capture] 监听中断：{type(item).__name__}: {item}")
                    return
                if self.policy.paused:
                    # 暂停生效瞬间已经在缓冲区里的那一句：丢掉不传。
                    self.log("[capture] 隐私暂停，丢弃一段已缓冲语音")
                    return
                await self._ingest_segment(item)
        finally:
            self._listen_stop.set()
            await asyncio.to_thread(thread.join, 5.0)

    async def _ingest_segment(self, segment: Segment) -> None:
        """一句话 → 信封 → spool → 上传。"""
        wav = segment.to_wav()
        finished = utcnow()
        started = finished - timedelta(seconds=segment.duration_seconds)
        self.uplink.enqueue_audio(
            wav=wav,
            occurred_at=started,
            observed_at=finished,
            # VAD 是设备自己判断「有人在说话」，不是用户显式要求采集
            trigger="auto",
            meta={
                "capture_mode": "vad",
                "input_device": self.config.input_device,
                "actual_duration_seconds": round(segment.duration_seconds, 2),
                "peak_level": segment.peak,
                # silence=正常收尾 / max_length=被上限截断，后者说明这段很可能不是一句话
                "vad_end_reason": segment.reason,
            },
        )
        report = await self.uplink.drain()
        self.log(
            f"[capture] 一句话 {segment.duration_seconds:.1f}s 峰值 {segment.peak:.3f} → "
            f"上传 {report.uploaded} 条，待重试 {report.retry_later} 条"
        )

    async def _periodic_loop(self, interval: int) -> None:
        """周期采集：睡一个间隔录一段。隐私暂停期间只睡不录。"""
        while True:
            await asyncio.sleep(interval)
            decision = self.policy.check_capture("CAPTURE_AUDIO", self.config.default_duration_seconds)
            if not decision.allowed:
                self.log(f"[capture] 周期采集被本地策略跳过：{decision.reason}")
                continue
            try:
                await self._capture_audio(
                    seconds=self.config.default_duration_seconds,
                    trigger="auto",
                    meta={"periodic_interval_seconds": interval},
                )
            except Exception as exc:  # noqa: BLE001 — 一轮失败不该终止整个周期会话
                self.log(f"[capture] 周期采集失败：{type(exc).__name__}: {exc}")

    async def _cancel_periodic(self) -> bool:
        if self._periodic is None:
            return False
        # 先放停止信号再取消任务：麦克风读取在线程里，只有它自己会看这个事件。
        # 光取消协程的话 ffmpeg 会继续持有麦克风，STOP 就成了一句空话。
        self._listen_stop.set()
        self._periodic.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._periodic
        self._periodic = None
        return True

    # ---------------------------------------------------------------- 播报

    async def _handle_reminder(self, message: dict[str, Any]) -> Outcome:
        payload = message.get("payload") or {}
        text = str(payload.get("text") or payload.get("message") or "").strip()
        policy_block = message.get("delivery_policy") or {}
        allow_tts = bool(policy_block.get("allow_tts"))

        if not text:
            return Outcome("FAILED", {"reason": "empty_payload", "message": "提醒没有可播报的正文"})

        decision = self.policy.check_playback(
            allow_tts=allow_tts,
            expected_device=self.config.output_device,
            actual_device=self.output_probe(),
            allow_any=self.config.allow_any_output,
        )
        if not decision.allowed:
            # 用 REJECTED 而不是 FAILED：这是设备侧策略正常拒绝，链路完全正常。
            # 契约里 REJECTED 原本是给 CAPTURE_REQUEST 的，但它要区分的正是
            # 「策略拒绝」与「投递失败」，播报拒绝落在同一个区分上。
            return Outcome("REJECTED", {**decision.detail, "text_preview": text[:40]})

        await self._receipt(str(message["message_id"]), "PRESENTED", {"text_length": len(text)})
        try:
            voice = await asyncio.to_thread(self.speaker, text)
        except Exception as exc:  # noqa: BLE001
            return Outcome("FAILED", {"reason": type(exc).__name__, "message": str(exc)})

        spoken = {**decision.detail, "voice": voice or "system_default"}
        await self._receipt(str(message["message_id"]), "SPOKEN", spoken)
        # 耳机上没有「用户点掉提醒」这个动作，播完就是这条消息在设备侧的终局。
        # 不落终态它会一直留在待投递集合里被反复重推。
        return Outcome("DISMISSED", {**spoken, "closed_by": "playback_finished"})

    # ---------------------------------------------------------------- 回执

    async def _receipt(self, message_id: str, status: str, detail: dict[str, Any]) -> None:
        try:
            await self.client.post_receipt(
                device_id=self.config.device_id,
                message_id=message_id,
                status=status,
                detail={**detail, "reported_at": utcnow().isoformat()},
            )
        except Exception as exc:  # noqa: BLE001 — 回执失败不该让已经完成的采集白干
            self.log(f"[downlink] 回执 {status} 发送失败：{type(exc).__name__}: {exc}")


__all__ = ["Decision", "EarbudsRuntime", "Outcome", "Recorder", "Speaker"]
