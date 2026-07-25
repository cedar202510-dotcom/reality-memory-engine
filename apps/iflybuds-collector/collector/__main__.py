"""命令行入口：devices / register / selftest / capture / push / run。

排障顺序就是子命令的顺序——先确认系统看得见耳机（devices），再确认能录能放
（selftest），再确认能上传（capture），最后才是长期运行（run）。每一步都能独立
跑通或独立失败，不用一上来就把整条链路接起来猜哪一段坏了。
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys

from . import audio
from .client import BackendClient, BackendError
from .config import DEVICE_ADAPTER, DEVICE_KIND, Config
from .downlink import EarbudsRuntime
from .policy import LocalPolicy
from .spool import Spool
from .uplink import Uplink, utcnow

RUNTIME_LABEL = DEVICE_ADAPTER


def _make_recorder(config: Config):
    """把配置里的设备名解析成一个「给我 N 秒音频」的函数。

    每次录音前重新解析设备索引：耳机断连重连后索引会变，缓存下来的索引会安静地录到
    另一个麦克风上——这种错误最难发现，因为它照样产出一个合法的 WAV 文件。
    """

    def record(seconds: float) -> bytes:
        device = audio.resolve_input_device(config.input_device, config.ffmpeg_binary)
        return audio.record_wav(
            device_index=device.index,
            seconds=seconds,
            sample_rate=config.sample_rate,
            channels=config.channels,
            ffmpeg_binary=config.ffmpeg_binary,
        )

    return record


def _make_speaker(config: Config):
    def speak(text: str) -> str:
        return audio.speak(text, output_device=config.output_device, voice=config.tts_voice)

    return speak


# ---------------------------------------------------------------- 子命令


def cmd_devices(config: Config) -> int:
    print("音频输入设备（ffmpeg avfoundation）：")
    try:
        devices = audio.list_input_devices(config.ffmpeg_binary)
    except audio.AudioError as exc:
        print(f"  ✗ {exc}")
        return 1
    for device in devices:
        mark = "←" if config.input_device.lower() in device.name.lower() else " "
        print(f"  {mark} {device}")

    print(f"\n配置的输入设备名：{config.input_device!r}")
    try:
        chosen = audio.resolve_input_device(config.input_device, config.ffmpeg_binary)
        print(f"  ✓ 命中 {chosen}")
    except audio.AudioError as exc:
        print(f"  ✗ {exc}")

    current = audio.default_output_device()
    print(f"\n当前系统默认输出设备：{current or '未知'}")
    print(f"配置的输出设备名：{config.output_device!r}")
    if config.allow_any_output:
        print("  ! ALLOW_ANY_OUTPUT=1：播报不做设备核对，声音可能从外放出去")
    elif current and config.output_device.lower() in current.lower():
        print("  ✓ 播报会进耳机")
    else:
        print("  ✗ 播报会被本地策略拒绝（把耳机设为系统默认输出设备即可）")

    zh_voice = audio.resolve_voice("中文提醒", config.tts_voice)
    print(f"\n中文提醒会用的音色：{zh_voice or '系统默认'}")
    if not zh_voice:
        print("  ! 这台机器上没找到中文音色，中文会被英文音色念成乱码；用 TTS_VOICE 指定一个")
    return 0


def cmd_selftest(config: Config, seconds: float, skip_playback: bool) -> int:
    """不碰后端，只验证这台机器上「录得到」和「放得出」。"""
    print(f"[1/2] 从「{config.input_device}」录 {seconds:g} 秒…")
    try:
        wav = _make_recorder(config)(seconds)
    except audio.AudioError as exc:
        print(f"  ✗ {exc}")
        return 1
    peak = audio.wav_peak_level(wav)
    actual = audio.wav_duration_seconds(wav)
    print(f"  ✓ {len(wav)} 字节，时长 {actual or 0:.2f}s，峰值电平 {peak if peak is None else round(peak, 3)}")
    if peak is not None and peak < 0.01:
        print("  ! 电平接近静音：确认耳机麦克风已被系统选中，且终端有麦克风权限")

    if skip_playback:
        return 0
    print("[2/2] 播报一句测试语音…")
    current = audio.default_output_device()
    if not config.allow_any_output and (
        not current or config.output_device.lower() not in current.lower()
    ):
        print(f"  ✗ 当前默认输出设备是「{current or '未知'}」，不是耳机；跳过播放（本地策略）")
        return 1
    try:
        voice = _make_speaker(config)("耳机通道自检完成，这句话应该是清晰的中文")
    except audio.AudioError as exc:
        print(f"  ✗ {exc}")
        return 1
    print(f"  ✓ 已播放到「{current}」，音色 {voice or '系统默认'}")
    if not voice:
        print("  ! 用的是系统默认音色：如果它是英文音色，中文会被念成乱码")
    return 0


async def cmd_register(config: Config, name: str) -> int:
    async with BackendClient(config.api_base_url, timeout=config.http_timeout_seconds) as client:
        try:
            device = await client.register_device(
                kind="earbuds",
                name=name,
                runtime_package=RUNTIME_LABEL,
                control_transport="inbox",
            )
        except BackendError as exc:
            print(f"✗ 注册失败：{exc}")
            return 1
    device_id = device["device_id"]
    print(f"✓ 设备已注册：{device['name']}（{device['kind']}），device_id={device_id}")
    print("\n把它写进环境变量后再跑 run：")
    print(f"  export RME_EARBUDS_DEVICE_ID={device_id}")
    return 0


async def cmd_capture(config: Config, seconds: float) -> int:
    """录一段并立刻上传，不订阅下行。第一次打通上行链路时用。"""
    spool = Spool(config.spool_dir)
    async with BackendClient(config.api_base_url, timeout=config.http_timeout_seconds) as client:
        uplink = Uplink(config=config, spool=spool, client=client, session_id=config.session_id())
        started = utcnow()
        try:
            wav = await asyncio.to_thread(_make_recorder(config), seconds)
        except audio.AudioError as exc:
            print(f"✗ 录音失败：{exc}")
            return 1
        peak = audio.wav_peak_level(wav)
        entry = uplink.enqueue_audio(
            wav=wav,
            occurred_at=started,
            observed_at=utcnow(),
            trigger="explicit",
            meta={
                "reason": "cli_capture",
                "input_device": config.input_device,
                # 与下行运行时那条路写同样的字段：同一段证据从两个入口进来，meta 不能长得不一样，
                # 否则事后按 peak_level 排查「录到了但一片静音」时会漏掉 CLI 采的那些。
                "effective_duration_seconds": seconds,
                "actual_duration_seconds": audio.wav_duration_seconds(wav),
                "peak_level": peak,
            },
        )
        print(f"已落 spool：{entry.key}（{len(wav)} 字节，峰值电平 {peak if peak is None else round(peak, 3)}）")
        if peak is not None and peak < 0.01:
            print("  ! 电平接近静音：确认耳机麦克风已被系统选中，且终端有麦克风权限")
        report = await uplink.drain()
    print(
        f"上传：成功 {report.uploaded} / 重复 {report.duplicates} / "
        f"拒收 {report.rejected} / 待重试 {report.retry_later}"
    )
    for error in report.errors[:3]:
        print(f"  ! {error}")
    if report.envelope_ids:
        print(f"信封 id：{report.envelope_ids[0]}")
    return 0 if report.uploaded or report.duplicates else 1


async def cmd_push(config: Config, text: str, ttl: int | None) -> int:
    """从操作者这边推一条待播报的提醒（扮演云端角色，验证下行播报链路）。"""
    if not config.device_id:
        print("✗ 需要 RME_EARBUDS_DEVICE_ID")
        return 1
    async with BackendClient(config.api_base_url, timeout=config.http_timeout_seconds) as client:
        try:
            result = await client.push_voice_message(
                device_id=config.device_id, text=text, allow_tts=True, ttl_seconds=ttl
            )
        except BackendError as exc:
            print(f"✗ 推送失败：{exc}")
            return 1
    message = result["message"]
    pushed = result.get("pushed_connections", 0)
    print(f"✓ 已下发 {message['message_id']}（状态 {message['status']}）")
    if pushed:
        print(f"  即时推送到 {pushed} 条长连")
    else:
        print("  无在线长连：消息已排队，采集器下次拉 inbox 时取走")
    return 0


def _build_runtime(config: Config, client: BackendClient, session_id: str) -> EarbudsRuntime:
    spool = Spool(config.spool_dir)
    return EarbudsRuntime(
        config=config,
        policy=LocalPolicy(
            max_duration_seconds=config.max_duration_seconds, paused=config.start_paused
        ),
        uplink=Uplink(config=config, spool=spool, client=client, session_id=session_id),
        client=client,
        spool=spool,
        recorder=_make_recorder(config),
        speaker=_make_speaker(config),
        output_probe=audio.default_output_device,
    )


async def cmd_listen(config: Config, seconds: float | None) -> int:
    """本地开一段记忆会话：监听麦克风，按句上传。不订阅下行。

    「会话制」在命令行上的样子就是这个：你显式开一段，它才听；Ctrl-C 就停。没有
    「后台默默一直听」这个状态。
    """
    session_id = config.session_id()
    async with BackendClient(config.api_base_url, timeout=config.http_timeout_seconds) as client:
        runtime = _build_runtime(config, client, session_id)
        detail = await runtime.start_session()
        print(f"会话 {session_id}  模式 {detail['mode']}")
        print(detail["note"])
        print("说话即录，静音断句。Ctrl-C 结束会话\n")
        try:
            if seconds:
                await asyncio.sleep(seconds)
            else:
                await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await runtime.stop_session()
            report = await runtime.uplink.drain()
            if report.retry_later:
                print(f"! 还有 {report.retry_later} 条没传上去，留在 spool 里")
    print("\n会话已结束，麦克风已释放。")
    return 0


async def cmd_run(config: Config, listen: bool = False) -> int:
    if not config.device_id:
        print("✗ 需要 RME_EARBUDS_DEVICE_ID（先跑 register）")
        return 1
    async with BackendClient(config.api_base_url, timeout=config.http_timeout_seconds) as client:
        session_id = config.session_id()
        runtime = _build_runtime(config, client, session_id)
        print(f"设备 {config.device_id}  会话 {session_id}")
        print(f"后端 {config.api_base_url}  设备类型 {DEVICE_KIND}  适配器 {DEVICE_ADAPTER}")
        print(f"输入「{config.input_device}」 输出「{config.output_device}」 队列 {config.spool_dir}")
        if runtime.policy.paused:
            print("! 启动时处于隐私暂停：采集请求会被拒绝，直到云端下发 RESUME")
        if listen:
            detail = await runtime.start_session()
            print(f"! 已自动开启记忆会话（{detail['mode']}）：{detail['note']}")
        else:
            print("采集会话未开启（会话制）：控制台下发「开始周期采集」或用 listen 子命令开启")
        print("Ctrl-C 退出\n")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, runtime.stop)
        await runtime.run()
    print("\n已退出。未上传的录音留在 spool 里，下次启动会自动补传。")
    return 0


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m collector", description="IFLYBUDS 宿主侧采集器"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="列出音频设备并核对配置")

    selftest = sub.add_parser("selftest", help="不连后端，验证录音与播报")
    selftest.add_argument("--seconds", type=float, default=3.0)
    selftest.add_argument("--skip-playback", action="store_true")

    register = sub.add_parser("register", help="在后端注册这副耳机并拿到 device_id")
    register.add_argument("--name", default="IFLYBUDS Air 2")

    capture = sub.add_parser("capture", help="录一段并上传（只走上行）")
    capture.add_argument("--seconds", type=float, default=8.0)

    push = sub.add_parser("push", help="下发一条待播报的提醒（扮演云端）")
    push.add_argument("text")
    push.add_argument("--ttl", type=int, default=None)

    listen = sub.add_parser("listen", help="开一段记忆会话：说话即录，静音断句，自动上传")
    listen.add_argument("--seconds", type=float, default=None, help="到点自动结束；默认跑到 Ctrl-C")

    run = sub.add_parser("run", help="常驻：订阅下行 + 采集 + 播报 + 补传")
    run.add_argument(
        "--listen", action="store_true", help="启动即开记忆会话（默认会话制，等云端下发）"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = Config()

    if args.command == "devices":
        return cmd_devices(config)
    if args.command == "selftest":
        return cmd_selftest(config, args.seconds, args.skip_playback)
    if args.command == "register":
        return asyncio.run(cmd_register(config, args.name))
    if args.command == "capture":
        return asyncio.run(cmd_capture(config, args.seconds))
    if args.command == "push":
        return asyncio.run(cmd_push(config, args.text, args.ttl))
    if args.command == "listen":
        try:
            return asyncio.run(cmd_listen(config, args.seconds))
        except KeyboardInterrupt:
            return 0
    if args.command == "run":
        try:
            return asyncio.run(cmd_run(config, listen=args.listen))
        except KeyboardInterrupt:
            return 0
    raise SystemExit(f"未知子命令：{args.command}")


if __name__ == "__main__":
    sys.exit(main())
