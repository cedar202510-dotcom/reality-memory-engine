from __future__ import annotations

import io
import struct
import wave

from app.perception.audio_media import prepare_audio_for_asr


def test_rv101_raw_pcm_is_downmixed_to_mono_wav():
    frames = [
        (10, 10, 100, 200, 300, 400, 0, 0),
        (20, 20, -100, -200, -300, -400, 0, 0),
    ]
    raw = b"".join(struct.pack("<8h", *frame) for frame in frames)
    meta = {
        "evidence_item": {
            "mime_type": "audio/L16",
            "media": {
                "container": "RAW_PCM",
                "codec": "PCM_S16LE",
                "sample_rate_hz": 16000,
                "channel_count": 8,
                "channel_layout": [
                    "PROCESSED_0",
                    "PROCESSED_1",
                    "RAW_MIC_0",
                    "RAW_MIC_1",
                    "RAW_MIC_2",
                    "RAW_MIC_3",
                    "HARDWARE_ECHO_0",
                    "HARDWARE_ECHO_1",
                ],
            },
        }
    }

    converted, media_kind = prepare_audio_for_asr(raw, meta)

    assert media_kind == "audio/wav"
    with wave.open(io.BytesIO(converted), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 16000
        assert wav.getnframes() == 2
        assert struct.unpack("<2h", wav.readframes(2)) == (250, -250)


def test_unknown_audio_is_left_unchanged():
    data = b"already-encoded"
    assert prepare_audio_for_asr(data, {}) == (data, "audio")
