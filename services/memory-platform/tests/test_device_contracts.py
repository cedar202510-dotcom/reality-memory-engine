from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.gateway import _map_device_trigger
from app.schemas import DeviceEvidenceItemIn, DeviceSourceEnvelopeIn


def _source() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_ref": "rme.source-envelope.v1",
        "source_envelope_id": "src_test-001",
        "device_id": "glass_test-001",
        "device_kind": "ROKID_GLASSES_RV101",
        "device_adapter": "rokid-native-android/1.0",
        "capture_session_id": "ses_test-001",
        "capture_window_id": "win_test-001",
        "capture_intent_id": "cin_test-001",
        "occurred_at": now,
        "observed_at": now,
        "monotonic_start_ns": 100,
        "monotonic_end_ns": 200,
        "clock_domain": "ANDROID_ELAPSED_REALTIME_NANOS",
        "clock_sync_method": "ANDROID_SYSTEM_CLOCK_ANCHOR",
        "time_uncertainty_ms": 50,
        "policy_snapshot_id": "pol_phase0_local_v1",
        "modality": "AUDIO",
        "payload_kind": "EVIDENCE_ITEM",
        "payload_ref": "evd_test-001",
        "idempotency_key": "evd_test-001",
        "extensions": {},
    }


def test_device_source_accepts_glasses_ids_and_uppercase_modality():
    source = DeviceSourceEnvelopeIn.model_validate(_source())
    assert source.device_id == "glass_test-001"
    assert source.modality == "AUDIO"


def test_device_source_rejects_reversed_monotonic_range():
    raw = _source()
    raw["monotonic_end_ns"] = 99
    with pytest.raises(ValidationError):
        DeviceSourceEnvelopeIn.model_validate(raw)


def test_device_evidence_contract_accepts_rv101_audio_metadata():
    now = datetime.now(timezone.utc).isoformat()
    evidence = DeviceEvidenceItemIn.model_validate(
        {
            "schema_ref": "rme.evidence-item.v1",
            "evidence_item_id": "evd_test-001",
            "source_envelope_id": "src_test-001",
            "capture_window_id": "win_test-001",
            "modality": "AUDIO",
            "mime_type": "audio/L16",
            "captured_at": now,
            "duration_ms": 9984,
            "byte_count": 2_555_904,
            "sha256": "a" * 64,
            "encryption": {
                "algorithm": "AES_256_GCM",
                "key_ref": "reality-memory-evidence-v1",
                "iv_base64": "test",
            },
            "retention": {
                "ttl_expires_at": now,
                "purpose": "STRUCTURE_EXTRACTION",
                "debug_sample": False,
            },
            "media": {
                "container": "RAW_PCM",
                "codec": "PCM_S16LE",
                "sample_rate_hz": 16000,
                "channel_count": 8,
            },
            "sensitivity_labels": [],
            "extensions": {},
        }
    )
    assert evidence.media["channel_count"] == 8


def test_device_trigger_mapping_is_conservative():
    assert _map_device_trigger({"signal_kind": "USER_EXPLICIT"}) == "explicit"
    assert _map_device_trigger({"signal_kind": "HEAD_MOTION_TRANSITION"}) == "auto"
    assert _map_device_trigger(None) == "auto"
