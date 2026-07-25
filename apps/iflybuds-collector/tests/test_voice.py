"""音色选择：中文提醒必须用中文音色。

真机踩过的坑——系统默认音色是英文的，用它念中文，耳机里出来的是一串听不懂的音节，
而 `say` 返回 0、回执照样是 SPOKEN。所以「选对音色」是采集器的责任，且必须可验证。
"""
from __future__ import annotations

import pytest

from collector import audio

VOICES = [
    ("Alex", "en_US"),
    ("Samantha", "en_US"),
    ("Meijia", "zh_TW"),
    ("Tingting", "zh_CN"),
]


@pytest.fixture
def fake_voices(monkeypatch):
    def _install(voices):
        monkeypatch.setattr(audio, "list_voices", lambda *a, **k: voices)

    return _install


def test_chinese_text_picks_a_chinese_voice(fake_voices):
    fake_voices(VOICES)
    assert audio.resolve_voice("牛奶还有两天过期") == "Tingting"


def test_english_text_keeps_the_system_default(fake_voices):
    """英文正文不折腾：系统默认音色本来就合适，换成中文音色反而更差。"""
    fake_voices(VOICES)
    assert audio.resolve_voice("Your milk expires in two days") == ""


def test_explicit_voice_always_wins(fake_voices):
    fake_voices(VOICES)
    assert audio.resolve_voice("牛奶还有两天过期", "Sinji") == "Sinji"
    assert audio.resolve_voice("Hello", "Sinji") == "Sinji"


def test_falls_back_to_any_zh_voice_when_preferred_missing(fake_voices):
    fake_voices([("Alex", "en_US"), ("Sandy", "zh_CN")])
    assert audio.resolve_voice("你好") == "Sandy"


def test_no_chinese_voice_falls_back_to_default_rather_than_failing(fake_voices):
    """一个中文音色都没有时宁可念出乱码也不静默丢掉提醒——但回执里会记下用的是默认音色。"""
    fake_voices([("Alex", "en_US")])
    assert audio.resolve_voice("你好") == ""


def test_voice_listing_parses_names_with_spaces_and_parens():
    """`say -v '?'` 的名字列可能带空格和括号，解析不能按第一个空格切。"""
    line = "Eddy (Chinese (China mainland)) zh_CN    # 你好！我叫Eddy。"
    match = audio._VOICE_LINE.match(line)
    assert match is not None
    assert match.group("name") == "Eddy (Chinese (China mainland))"
    assert match.group("locale") == "zh_CN"


def test_cjk_detection_covers_mixed_text():
    assert audio.CJK.search("提醒 reminder") is not None
    assert audio.CJK.search("plain ascii") is None
