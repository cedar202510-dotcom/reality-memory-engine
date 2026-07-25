"""下行运行时：一条消息进来，最终产生什么回执、有没有真的动麦克风。

这里测的是设备侧那一半语义。后端那一半（消息排队、终态收敛、控制台展示）在
`services/memory-platform/tests/test_earbuds_connector.py`。
"""
from __future__ import annotations

import asyncio

from collector.audio import AudioError
from collector.config import DEVICE_ADAPTER, DEVICE_KIND
from collector.downlink import EarbudsRuntime
from collector.policy import LocalPolicy
from collector.spool import Spool
from collector.uplink import Uplink
from collector.vad import Segment


def spoken_segment(seconds: float = 1.5, peak: float = 0.4) -> Segment:
    """一段假的「一句话」。内容无所谓，测的是它会不会被正确地变成信封。"""
    frames = int(16000 * seconds)
    return Segment(
        pcm=b"\x00\x10" * frames,
        sample_rate=16000,
        peak=peak,
        offset_seconds=0.0,
        duration_seconds=seconds,
    )

MESSAGE_ID = "8a0f6f10-0000-4000-8000-000000000001"


def build_runtime(
    config, backend, recorder, speaker, *, output="IFLYBUDS Air 2", paused=False, segments=None
):
    spool = Spool(config.spool_dir)
    source = None
    if segments is not None:
        # 替身麦克风：直接吐出已经切好的句子，测试不需要真的听见声音
        source = lambda: iter(segments)  # noqa: E731
    return EarbudsRuntime(
        config=config,
        policy=LocalPolicy(max_duration_seconds=config.max_duration_seconds, paused=paused),
        uplink=Uplink(config=config, spool=spool, client=backend, session_id="sess-test"),
        client=backend,
        spool=spool,
        recorder=recorder,
        speaker=speaker,
        output_probe=lambda: output,
        log=lambda _msg: None,
        segment_source=source,
    )


def capture(action: str, message_id: str = MESSAGE_ID, **payload) -> dict:
    return {
        "message_id": message_id,
        "message_type": "CAPTURE_REQUEST",
        "payload": {"schema_ref": "rme.capture-request.v0", "action": action, **payload},
        "delivery_policy": {"allow_text": True, "allow_tts": False},
    }


def reminder(text: str, *, allow_tts: bool = True, message_id: str = MESSAGE_ID) -> dict:
    return {
        "message_id": message_id,
        "message_type": "REMINDER_SIGNAL",
        "payload": {"text": text},
        "delivery_policy": {"allow_text": True, "allow_tts": allow_tts},
    }


# ---------------------------------------------------------------- 采集


async def test_capture_audio_records_uploads_and_reports_executed(
    config, backend, recorder, speaker
):
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(capture("CAPTURE_AUDIO", duration_seconds=5))

    assert recorder.calls == [5.0]
    assert backend.statuses() == ["RECEIVED", "EXECUTED"]

    envelope, media = backend.uploads[0]
    assert envelope["modality"] == "audio"
    assert envelope["trigger"] == "explicit"
    assert envelope["device_id"] == config.device_id
    # 设备差异只出现在 meta 的这两个字段里（04 §2）
    assert envelope["meta"]["device_kind"] == DEVICE_KIND
    assert envelope["meta"]["device_adapter"] == DEVICE_ADAPTER
    assert envelope["meta"]["capture_request_message_id"] == MESSAGE_ID
    assert media == recorder.wav

    detail = backend.detail_of("EXECUTED")
    assert detail["envelope_id"] == "env-1"
    assert detail["uploaded"] == 1
    assert detail["spool_depth"] == 0
    assert detail["peak_level"] > 0


async def test_capture_photo_is_rejected_without_touching_the_microphone(
    config, backend, recorder, speaker
):
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(capture("CAPTURE_PHOTO"))

    assert recorder.calls == []
    assert backend.statuses() == ["RECEIVED", "REJECTED"]
    assert "没有摄像头" in backend.detail_of("REJECTED")["policy"]


async def test_capture_while_paused_is_rejected(config, backend, recorder, speaker):
    runtime = build_runtime(config, backend, recorder, speaker, paused=True)
    await runtime.handle_message(capture("CAPTURE_AUDIO", duration_seconds=5))

    assert recorder.calls == []
    assert backend.statuses()[-1] == "REJECTED"
    assert "隐私暂停" in backend.detail_of("REJECTED")["policy"]


async def test_over_budget_duration_is_clamped_before_recording(
    config, backend, recorder, speaker
):
    """本地采集预算是设备侧的：云端不能通过调大 duration 让麦克风一直开着。"""
    config.max_duration_seconds = 30
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(capture("CAPTURE_AUDIO", duration_seconds=300))

    assert recorder.calls == [30.0]
    detail = backend.detail_of("EXECUTED")
    assert detail["clamped_duration_seconds"] == 30
    # 请求的原始秒数与真正录的秒数在回执里必须同时可见，否则事后对不上账
    assert detail["requested_duration_seconds"] == 300
    assert detail["effective_duration_seconds"] == 30


async def test_recording_failure_is_reported_as_failed_not_rejected(
    config, backend, recorder, speaker
):
    """录不到与不让录是两回事：一个是链路坏了，一个是策略拒绝。"""
    recorder.error = AudioError("耳机可能刚断连")
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(capture("CAPTURE_AUDIO", duration_seconds=3))

    assert backend.statuses()[-1] == "FAILED"
    assert "断连" in backend.detail_of("FAILED")["message"]


async def test_upload_failure_keeps_audio_in_spool_and_says_so(
    config, backend, recorder, speaker
):
    """断网时照录不误：音频留在 spool 等补传，回执如实标注还没传上去。"""
    backend.upload_error = ConnectionError("后端连不上")
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(capture("CAPTURE_AUDIO", duration_seconds=3))

    detail = backend.detail_of("EXECUTED")
    assert detail["upload_pending"] is True
    assert detail["spool_depth"] == 1
    assert backend.uploads == []

    # 网络恢复后同一段音频被补传上去
    backend.upload_error = None
    report = await runtime.uplink.drain()
    assert report.uploaded == 1
    assert len(backend.uploads) == 1


# ---------------------------------------------------------------- 至少一次投递


async def test_duplicate_delivery_does_not_record_twice(config, backend, recorder, speaker):
    """长连补投 + inbox 轮询会让同一条请求到达两次，第二次只补发终态。"""
    runtime = build_runtime(config, backend, recorder, speaker)
    message = capture("CAPTURE_AUDIO", duration_seconds=3)
    await runtime.handle_message(message)
    await runtime.handle_message(message)

    assert recorder.calls == [3.0]
    assert len(backend.uploads) == 1
    assert backend.statuses() == ["RECEIVED", "EXECUTED", "EXECUTED"]
    assert backend.receipts[-1][2]["duplicate_delivery"] is True


async def test_restart_mid_flight_is_reported_as_failed(config, backend, recorder, speaker):
    """占了坑却没有结果 = 上次处理到一半进程没了，如实说结局未知，不重复执行。"""
    Spool(config.spool_dir).claim(MESSAGE_ID)

    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(capture("CAPTURE_AUDIO", duration_seconds=3))

    assert recorder.calls == []
    assert backend.statuses() == ["FAILED"]
    assert backend.detail_of("FAILED")["reason"] == "collector_restarted_mid_flight"


# ---------------------------------------------------------------- 播报


async def test_reminder_is_spoken_then_closed(config, backend, recorder, speaker):
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(reminder("牛奶还有两天过期"))

    assert speaker.spoken == ["牛奶还有两天过期"]
    assert backend.statuses() == ["RECEIVED", "PRESENTED", "SPOKEN", "DISMISSED"]
    # 耳机上没有「用户点掉提醒」这个动作，播完即终局；不终结会被反复重推
    assert backend.detail_of("DISMISSED")["closed_by"] == "playback_finished"
    assert backend.detail_of("SPOKEN")["output_device"] == "IFLYBUDS Air 2"
    # 音色进回执：英文音色念中文时 say 照样返回 0，不记音色就查不出「一串乱码」的原因
    assert backend.detail_of("SPOKEN")["voice"] == "Tingting"


async def test_reminder_refused_when_output_is_the_laptop_speaker(
    config, backend, recorder, speaker
):
    """默认输出设备不是耳机就不播——外放一条私人提醒比漏掉它严重得多。"""
    runtime = build_runtime(config, backend, recorder, speaker, output="MacBook Pro Speakers")
    await runtime.handle_message(reminder("体检报告出来了"))

    assert speaker.spoken == []
    assert backend.statuses() == ["RECEIVED", "REJECTED"]
    detail = backend.detail_of("REJECTED")
    assert "MacBook Pro Speakers" in detail["policy"]
    # 拒播的回执里不放全文：它没被播出去，也不该被抄进云端审计
    assert detail["text_preview"] == "体检报告出来了"


async def test_reminder_without_tts_permission_is_not_spoken(
    config, backend, recorder, speaker
):
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(reminder("低优先级提醒", allow_tts=False))

    assert speaker.spoken == []
    assert backend.statuses()[-1] == "REJECTED"


async def test_playback_failure_is_reported_as_failed(config, backend, recorder, speaker):
    speaker.error = AudioError("指定的输出设备不可用")
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(reminder("该喝水了"))

    assert backend.statuses()[-1] == "FAILED"


# ---------------------------------------------------------------- 其他消息类型


async def test_privacy_pause_message_blocks_the_next_capture(
    config, backend, recorder, speaker
):
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(
        {"message_id": MESSAGE_ID, "message_type": "PRIVACY_PAUSE", "payload": {}}
    )
    assert backend.statuses()[-1] == "DISMISSED"

    await runtime.handle_message(capture("CAPTURE_AUDIO", message_id="other-1", duration_seconds=3))
    assert recorder.calls == []
    assert backend.statuses("other-1")[-1] == "REJECTED"


async def test_unknown_message_type_is_closed_not_left_pending(
    config, backend, recorder, speaker
):
    """不认识的类型也要落终态，否则它会一直留在待投递集合里被反复重推。"""
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(
        {"message_id": MESSAGE_ID, "message_type": "CAPTURE_BUDGET_UPDATE", "payload": {}}
    )

    assert backend.statuses()[-1] == "DISMISSED"
    assert backend.detail_of("DISMISSED")["unsupported_message_type"] == "CAPTURE_BUDGET_UPDATE"


# ---------------------------------------------------------------- 会话控制


async def test_pause_resume_stop_are_executed_even_while_paused(
    config, backend, recorder, speaker
):
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(capture("PAUSE", message_id="m-pause"))
    assert runtime.policy.paused is True
    assert backend.statuses("m-pause")[-1] == "EXECUTED"

    await runtime.handle_message(capture("RESUME", message_id="m-resume"))
    assert runtime.policy.paused is False
    assert backend.statuses("m-resume")[-1] == "EXECUTED"

    await runtime.handle_message(capture("STOP", message_id="m-stop"))
    assert backend.statuses("m-stop")[-1] == "EXECUTED"
    assert backend.detail_of("EXECUTED")["action"] == "PAUSE"  # 第一条 EXECUTED


async def test_start_periodic_reports_the_interval_it_actually_uses(
    config, backend, recorder, speaker
):
    config.capture_mode = "periodic"
    runtime = build_runtime(config, backend, recorder, speaker)
    await runtime.handle_message(capture("START_PERIODIC", message_id="m-periodic", interval_seconds=45))
    try:
        detail = backend.detail_of("EXECUTED")
        assert detail["mode"] == "periodic"
        assert detail["interval_seconds"] == 45
        assert detail["duration_seconds"] == config.default_duration_seconds
    finally:
        await runtime.stop_session()


async def test_vad_session_uploads_each_sentence(config, backend, recorder, speaker):
    """一句话 = 一条 modality=audio 的信封，trigger 是 auto（设备自己判断有人在说话）。"""
    config.capture_mode = "vad"
    runtime = build_runtime(
        config, backend, recorder, speaker, segments=[spoken_segment(), spoken_segment(2.0)]
    )
    await runtime.start_session()
    await asyncio.sleep(0.3)
    await runtime.stop_session()

    assert len(backend.uploads) == 2
    envelope, media = backend.uploads[0]
    assert envelope["modality"] == "audio"
    assert envelope["trigger"] == "auto"
    assert envelope["meta"]["capture_mode"] == "vad"
    assert envelope["meta"]["peak_level"] == 0.4
    assert envelope["meta"]["vad_end_reason"] == "silence"
    assert media.startswith(b"RIFF")  # 真的是个 WAV，不是裸 PCM


async def test_paused_session_does_not_upload_what_it_heard(config, backend, recorder, speaker):
    """隐私暂停期间不上传，也不会去开麦克风——暂停不是「采了不传」。"""
    config.capture_mode = "vad"
    runtime = build_runtime(
        config, backend, recorder, speaker, segments=[spoken_segment()], paused=True
    )
    await runtime.start_session()
    await asyncio.sleep(0.3)
    await runtime.stop_session()

    assert backend.uploads == []


async def test_dead_microphone_backs_off_instead_of_spinning(config, backend, recorder, speaker):
    """麦克风流一开就结束（耳机断连、被独占）时不能立刻重开。

    没有退避的话这里是个吃满 CPU、每秒拉起几百个 ffmpeg 的死循环——第一版就是这样，
    被这条用例逮到的。
    """
    config.capture_mode = "vad"
    runtime = build_runtime(config, backend, recorder, speaker, segments=[spoken_segment()])
    await runtime.start_session()
    await asyncio.sleep(0.5)
    await runtime.stop_session()

    # 0.5 秒内最多跑完第一轮，第二轮被 1 秒退避挡住
    assert len(backend.uploads) == 1


async def test_stopping_the_session_releases_the_microphone(config, backend, recorder, speaker):
    """STOP 必须把停止信号放给读麦克风的线程，否则 ffmpeg 会继续占着麦克风。"""
    config.capture_mode = "vad"
    runtime = build_runtime(config, backend, recorder, speaker, segments=[])
    await runtime.start_session()
    assert runtime._listen_stop.is_set() is False
    stopped = await runtime.stop_session()
    assert stopped is True
    assert runtime._listen_stop.is_set() is True


async def test_start_session_in_vad_mode_says_the_interval_is_ignored(
    config, backend, recorder, speaker
):
    """云端以为自己开的是定时采集、设备实际跑的是 VAD——这个差异必须回执里可见。"""
    config.capture_mode = "vad"
    runtime = build_runtime(config, backend, recorder, speaker, segments=[])
    await runtime.handle_message(capture("START_PERIODIC", message_id="m-vad", interval_seconds=45))
    try:
        detail = backend.detail_of("EXECUTED")
        assert detail["mode"] == "vad"
        assert detail["silence_ms"] == config.vad_silence_ms
        assert "interval_seconds" in detail["ignored"]
    finally:
        await runtime.stop_session()
