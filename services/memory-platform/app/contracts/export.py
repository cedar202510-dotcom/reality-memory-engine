"""导出冻结契约的 JSON Schema 到 app/contracts/generated/。

用法：python -m app.contracts.export
"""
from __future__ import annotations

import json
from pathlib import Path

from ..schemas import (
    AtomicObservationIn,
    AtomicObservationOut,
    AudioSearchHit,
    FindObjectResponse,
    MemoryCandidateOut,
    SceneSearchRequest,
    SceneSearchResponse,
    SourceEnvelopeIn,
    SourceEnvelopeOut,
)

CONTRACTS = {
    "SourceEnvelopeIn": SourceEnvelopeIn,
    "SourceEnvelopeOut": SourceEnvelopeOut,
    "AtomicObservationIn": AtomicObservationIn,
    "AtomicObservationOut": AtomicObservationOut,
    "AudioSearchHit": AudioSearchHit,
    "MemoryCandidateOut": MemoryCandidateOut,
    "FindObjectResponse": FindObjectResponse,
    "SceneSearchRequest": SceneSearchRequest,
    "SceneSearchResponse": SceneSearchResponse,
}

OUT_DIR = Path(__file__).parent / "generated"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, model in CONTRACTS.items():
        path = OUT_DIR / f"{name}.json"
        path.write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"exported {path}")


if __name__ == "__main__":
    main()
