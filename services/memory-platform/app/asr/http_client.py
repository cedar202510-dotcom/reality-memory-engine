"""HTTPTranscriber：调用可配置的 HTTP ASR sidecar（如 faster-whisper 服务）。

适配边缘/独立部署：ASR 作为独立服务运行，本平台只通过 HTTP 取转写，
本机不装 torch / faster-whisper。

Sidecar 契约（简洁 JSON，base64 传音频）：
- POST {base_url}/transcribe
  请求 {"audio_base64": "<base64>", "media_kind": "audio"}
  响应 {"segments": [{"start": 0.0, "end": 1.2, "text": "...", "speaker": "S1"?}, ...],
        "language": "zh"?, "duration_seconds": 1.2?}
- 认证：asr_api_key 非空时带 `Authorization: Bearer <key>`。
- 任何超时/网络错误/契约不符 → 返回 None，调用方降级。
"""
from __future__ import annotations

import base64

import httpx

from .base import TranscriptSegment


class HTTPTranscriber:
    """HTTP ASR sidecar 客户端。所有失败静默降级为 None。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    async def transcribe(
        self, audio_bytes: bytes, *, media_kind: str
    ) -> list[TranscriptSegment] | None:
        """统一请求/校验；任何异常或契约不符都返回 None。"""
        payload = {
            "audio_base64": base64.b64encode(audio_bytes).decode(),
            "media_kind": media_kind,
        }
        try:
            # trust_env=False：sidecar 是内网/本机地址，不经系统/环境代理（否则代理会错误接管 localhost 请求）
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                resp = await client.post(
                    f"{self._base_url}/transcribe", json=payload, headers=self._headers()
                )
                resp.raise_for_status()
                data = resp.json()
            segments = data.get("segments")
            if not isinstance(segments, list):
                return None
            return [TranscriptSegment.model_validate(seg) for seg in segments]
        except Exception:  # noqa: BLE001 - 网络/超时/契约问题一律降级
            return None
