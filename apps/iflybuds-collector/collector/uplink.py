"""上行：把一段耳机录音变成 SourceEnvelope，先落 spool，再 drain 到 Ingest API。

04 号文档的三段式里，这个模块是「设备侧 Collector → 传输契约」那一段。契约本身
（`SourceEnvelopeIn`）是全局唯一的，耳机的所有设备特性只压缩进 meta 的几个字段——
后端的感知、融合、候选层不会因为多了一副耳机而改一行。

时间语义按记忆平台的五段时间模型填：
  occurred_at  = 录音开始（现实中声音发生的时刻）
  observed_at  = 录音结束（设备观察完成的时刻）
  ingested_at  = 后端落库时间，采集器不填也填不了
"""
from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .client import BackendClient, BackendError, IngestResult
from .config import DEVICE_ADAPTER, DEVICE_KIND, Config
from .spool import Spool, SpoolEntry


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DrainReport:
    uploaded: int = 0
    duplicates: int = 0
    rejected: int = 0
    retry_later: int = 0
    envelope_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.retry_later == 0 and self.rejected == 0


class Uplink:
    """信封构造 + 本地队列 + 上传。

    录音与上传刻意分开：录音必须在请求到达时就地完成（麦克风就那一瞬间可用），上传
    可以等到网络恢复。两件事绑在一起的采集器，一断网就连录都不录了。
    """

    def __init__(self, *, config: Config, spool: Spool, client: BackendClient, session_id: str) -> None:
        self.config = config
        self.spool = spool
        self.client = client
        self.session_id = session_id
        self._seq = itertools.count(1)
        # 采集完成后会立刻 drain 一次，后台补传循环也在 drain：两个协程同时读到同一批
        # pending 条目就会把同一段音频传两遍。幂等键让后端只留一条信封，但白跑一趟网络
        # 请求没有意义，而且两边都会去 unlink 同一个文件。
        self._drain_lock = asyncio.Lock()

    def next_idempotency_key(self) -> str:
        """会话 id + 序号（04 原则 2）。同一段录音重投多少次，后端只留一条信封。"""
        return f"{self.session_id}-{next(self._seq):06d}"

    def build_envelope(
        self,
        *,
        idempotency_key: str,
        occurred_at: datetime,
        observed_at: datetime,
        trigger: str,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            # 未注册时留空：信封仍会被接收（审计记 device:unknown），便于第一次联调
            "device_id": self.config.device_id or None,
            "source_session_id": self.session_id,
            "occurred_at": occurred_at.isoformat(),
            "observed_at": observed_at.isoformat(),
            "idempotency_key": idempotency_key,
            "trigger": trigger,
            "modality": "audio",
            "meta": {
                # 设备差异只出现在这两个字段里，记忆平台内部不认识它们（04 §2）
                "device_kind": DEVICE_KIND,
                "device_adapter": DEVICE_ADAPTER,
                "host": self.config.host_label(),
                "sample_rate": self.config.sample_rate,
                "channels": self.config.channels,
                **(meta or {}),
            },
        }

    def enqueue_audio(
        self,
        *,
        wav: bytes,
        occurred_at: datetime,
        observed_at: datetime,
        trigger: str,
        meta: dict[str, Any] | None = None,
    ) -> SpoolEntry:
        key = self.next_idempotency_key()
        envelope = self.build_envelope(
            idempotency_key=key,
            occurred_at=occurred_at,
            observed_at=observed_at,
            trigger=trigger,
            meta=meta,
        )
        return self.spool.enqueue(key=key, envelope=envelope, media=wav, suffix=".wav")

    async def drain(self) -> DrainReport:
        """把 spool 里的条目全部推上去。

        单条失败不影响后面的条目：一条被后端拒收的旧契约条目不应该把它后面所有新录音
        都堵在队列里。
        """
        async with self._drain_lock:
            return await self._drain_once()

    async def _drain_once(self) -> DrainReport:
        report = DrainReport()
        for entry in self.spool.pending():
            try:
                result = await self._upload(entry)
            except BackendError as exc:
                if exc.permanent:
                    self.spool.reject(entry, str(exc))
                    report.rejected += 1
                else:
                    report.retry_later += 1
                report.errors.append(str(exc))
                continue
            except Exception as exc:  # noqa: BLE001 — 网络层什么都可能抛，留着下轮重试
                report.retry_later += 1
                report.errors.append(f"{type(exc).__name__}: {exc}")
                continue

            self.spool.discard(entry)
            report.envelope_ids.append(result.envelope_id)
            if result.idempotent_replay or result.duplicate_evidence_ids:
                report.duplicates += 1
            else:
                report.uploaded += 1
        return report

    async def _upload(self, entry: SpoolEntry) -> IngestResult:
        return await self.client.upload_envelope(
            envelope=entry.envelope(),
            media=entry.media(),
            filename=f"{entry.key}.wav",
            # 明确写 audio/wav：后端按 modality 选解析器，但 ASR sidecar 会看 content_type
            content_type="audio/wav",
        )


__all__ = ["DrainReport", "Uplink", "utcnow"]
