"""本地策略：耳机的拒绝权。"""
from __future__ import annotations

from collector.policy import LocalPolicy


def _policy(**kw) -> LocalPolicy:
    return LocalPolicy(max_duration_seconds=kw.pop("max_duration_seconds", 60), **kw)


def test_photo_is_refused_with_a_readable_reason():
    """请求拍照不做「就近替代」，如实回答耳机没有摄像头。"""
    decision = _policy().check_capture("CAPTURE_PHOTO", None)
    assert decision.allowed is False
    assert "没有摄像头" in decision.reason
    assert decision.detail["policy"] == decision.reason


def test_unknown_action_is_refused_not_guessed():
    decision = _policy().check_capture("CAPTURE_SMELL", None)
    assert decision.allowed is False
    assert "不认识" in decision.reason


def test_paused_blocks_capture_but_not_session_control():
    """暂停期间麦克风不能被打开，但 RESUME 必须还能执行——否则一暂停就再也解不开。"""
    policy = _policy()
    policy.pause("操作者按了暂停")
    assert policy.check_capture("CAPTURE_AUDIO", 5).allowed is False
    assert "操作者按了暂停" in policy.check_capture("CAPTURE_AUDIO", 5).reason
    assert policy.check_capture("RESUME", None).allowed is True
    assert policy.check_capture("STOP", None).allowed is True

    policy.resume()
    assert policy.check_capture("CAPTURE_AUDIO", 5).allowed is True


def test_over_budget_duration_is_clamped_and_reported():
    """超预算按上限截断，但必须在回执里说清楚要的 300 秒没有生效。"""
    decision = _policy(max_duration_seconds=60).check_capture("CAPTURE_AUDIO", 300)
    assert decision.allowed is True
    assert decision.detail["clamped_duration_seconds"] == 60
    assert decision.detail["requested_duration_seconds"] == 300
    assert "60" in decision.detail["clamp_reason"]


def test_zero_duration_is_refused():
    assert _policy().check_capture("CAPTURE_AUDIO", 0).allowed is False


def test_playback_requires_tts_permission():
    decision = _policy().check_playback(
        allow_tts=False, expected_device="IFLYBUDS", actual_device="IFLYBUDS Air 2", allow_any=False
    )
    assert decision.allowed is False
    assert "allow_tts" in decision.reason


def test_playback_refused_when_default_output_is_not_the_earbuds():
    """默认输出设备不是耳机就拒播：私人提醒不能从笔记本外放出去。"""
    decision = _policy().check_playback(
        allow_tts=True,
        expected_device="IFLYBUDS",
        actual_device="MacBook Pro Speakers",
        allow_any=False,
    )
    assert decision.allowed is False
    assert "MacBook Pro Speakers" in decision.reason
    assert decision.detail["output_device"] == "MacBook Pro Speakers"


def test_playback_refused_when_output_device_is_unknown():
    """拿不到默认输出设备时同样拒播——不确定声音去哪儿，就不要放。"""
    decision = _policy().check_playback(
        allow_tts=True, expected_device="IFLYBUDS", actual_device=None, allow_any=False
    )
    assert decision.allowed is False


def test_playback_allowed_on_matching_device():
    decision = _policy().check_playback(
        allow_tts=True,
        expected_device="IFLYBUDS",
        actual_device="IFLYBUDS Air 2",
        allow_any=False,
    )
    assert decision.allowed is True
    assert decision.detail["output_device"] == "IFLYBUDS Air 2"


def test_allow_any_output_skips_the_check_but_records_it():
    """显式关掉核对时也要留痕，否则事后看回执分不清声音到底从哪出的。"""
    decision = _policy().check_playback(
        allow_tts=True,
        expected_device="IFLYBUDS",
        actual_device="MacBook Pro Speakers",
        allow_any=True,
    )
    assert decision.allowed is True
    assert decision.detail["output_check"] == "skipped"
    assert decision.detail["output_device"] == "MacBook Pro Speakers"
