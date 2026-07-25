"""HTTPTranscriber：调用可配置的 HTTP ASR sidecar（如 faster-whisper 服务）。

适配边缘/独立部署：ASR 作为独立服务运行，本平台只通过 HTTP 取转写，
本机不装 torch / faster-whisper。

Sidecar 契约（简洁 JSON，base64 传音频）：
- POST {base_url}/transcribe
  请求 {"audio_base64": "<base64>", "media_kind": "audio", "language": "zh"?}
  language 可选：留空则 sidecar 自动检测（短片段误判率高，中文部署应固定 zh）
  响应 {"segments": [{"start": 0.0, "end": 1.2, "text": "...", "speaker": "S1"?}, ...],
        "language": "zh"?, "duration_seconds": 1.2?}
- 认证：asr_api_key 非空时带 `Authorization: Bearer <key>`。
- 任何超时/网络错误/契约不符 → 返回 None，调用方降级。
"""
from __future__ import annotations

import base64
import logging

import httpx

from .base import TranscriptSegment

logger = logging.getLogger(__name__)


class HTTPTranscriber:
    """HTTP ASR sidecar 客户端。所有失败静默降级为 None。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str = "",
        timeout: float = 60.0,
        language: str = "",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._language = language

    def _headers(self) -> dict[str, str]:
        if self._api_key:
            return {"Authorization": f"Bearer {self._api_key}"}
        return {}

    async def transcribe(
        self, audio_bytes: bytes, *, media_kind: str
    ) -> list[TranscriptSegment] | None:
        """统一请求/校验；任何异常或契约不符都返回 None。"""
        payload: dict[str, object] = {
            "audio_base64": base64.b64encode(audio_bytes).decode(),
            "media_kind": media_kind,
        }
        # 只在显式配置时下发：留空则由 sidecar 的部署级默认或自动检测决定
        if self._language:
            payload["language"] = self._language
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
                logger.warning(
                    "ASR sidecar 响应里没有 segments 列表：keys=%s", list(data)[:8]
                )
                return None
            return [TranscriptSegment.model_validate(seg) for seg in segments]
        except Exception as exc:  # noqa: BLE001 - 网络/超时/契约问题一律降级
            # 降级本身是对的（语音挂了不该阻塞整条流水线），但静默降级不对：
            # 上游只看得到 audit 里一句 asr_unavailable，分不出「sidecar 没起」
            # 「超时」还是「契约变了」，只能靠手工复现去猜。这行日志是唯一的线索。
            logger.warning(
                "ASR sidecar 调用失败，降级为无转写：%s: %s (url=%s, media_kind=%s, bytes=%d)",
                type(exc).__name__,
                exc,
                f"{self._base_url}/transcribe",
                media_kind,
                len(audio_bytes),
            )
            return None
