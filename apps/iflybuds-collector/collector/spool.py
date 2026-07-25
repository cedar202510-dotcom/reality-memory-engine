"""本地持久化队列：先落盘，再由上传器 drain。

04 号文档原则 3——离线是常态，不是异常。录完就直接 POST 的采集器在断网、后端重启、
笔记本合盖这三种日常情况下都会丢数据，而这三种情况每天都会发生。

顺带承担消息去重：下行是**至少一次**投递（长连补投 + inbox 轮询会让同一条 CAPTURE_REQUEST
到达两次），去重表必须落盘——只放在内存里的话，采集器重启后会把重启前已经执行过的
请求再执行一遍，用户会听到两次播报、云端会多出一条重复录音。
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

PENDING_DIRNAME = "pending"
SEEN_FILENAME = "seen-messages.txt"
# 去重表上限：超过就截掉最旧的一半。设备消息 TTL 默认 600s，几千条足够覆盖任何
# 现实中的重投窗口，无上限增长反而会让一个长期运行的采集器把磁盘写满。
SEEN_LIMIT = 4000


@dataclass(frozen=True)
class SpoolEntry:
    """一条待上传的证据：信封 JSON + 媒体文件成对存在。"""

    key: str
    envelope_path: Path
    media_path: Path

    def envelope(self) -> dict:
        return json.loads(self.envelope_path.read_text("utf-8"))

    def media(self) -> bytes:
        return self.media_path.read_bytes()


class Spool:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.pending_dir = self.root / PENDING_DIRNAME
        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.seen_path = self.root / SEEN_FILENAME
        # message_id → 已回执的终态（"" = 占了坑但还没跑完）
        self._seen: dict[str, str] = self._load_seen()

    # ---------------------------------------------------------------- 上传队列

    def enqueue(self, *, key: str, envelope: dict, media: bytes, suffix: str = ".wav") -> SpoolEntry:
        """落盘一条待上传证据。

        媒体先写、信封后写，且都经临时文件 + rename：`pending()` 只认信封存在的条目，
        所以进程在任何一步被杀掉，都不会出现「信封说有音频、音频却是半个文件」的条目。
        """
        safe = _safe_key(key)
        media_path = self.pending_dir / f"{safe}{suffix}"
        envelope_path = self.pending_dir / f"{safe}.json"
        _atomic_write(media_path, media)
        _atomic_write(
            envelope_path,
            json.dumps(envelope, ensure_ascii=False, indent=2).encode("utf-8"),
        )
        return SpoolEntry(key=safe, envelope_path=envelope_path, media_path=media_path)

    def pending(self) -> list[SpoolEntry]:
        """待上传条目，按落盘时间正序——录音的先后顺序对时间线是有意义的。"""
        entries: list[tuple[float, SpoolEntry]] = []
        for envelope_path in self.pending_dir.glob("*.json"):
            media = next(
                (p for p in self.pending_dir.glob(f"{envelope_path.stem}.*") if p.suffix != ".json"),
                None,
            )
            if media is None:
                # 信封在、媒体没了：孤儿条目，留着只会每轮重试都失败一次
                envelope_path.unlink(missing_ok=True)
                continue
            entries.append(
                (
                    envelope_path.stat().st_mtime,
                    SpoolEntry(key=envelope_path.stem, envelope_path=envelope_path, media_path=media),
                )
            )
        return [entry for _, entry in sorted(entries, key=lambda pair: pair[0])]

    def discard(self, entry: SpoolEntry) -> None:
        entry.envelope_path.unlink(missing_ok=True)
        entry.media_path.unlink(missing_ok=True)

    def reject(self, entry: SpoolEntry, reason: str) -> Path:
        """后端明确拒收（4xx）的条目挪进 rejected/，不删也不再重试。

        删掉会让「录到的音频去哪了」永远查不出来；留在 pending 里则会每一轮都重试一次
        注定失败的上传。契约不兼容的旧条目正是靠这个目录被人发现的。
        """
        rejected_dir = self.root / "rejected"
        rejected_dir.mkdir(parents=True, exist_ok=True)
        for path in (entry.envelope_path, entry.media_path):
            if path.exists():
                os.replace(path, rejected_dir / path.name)
        note = rejected_dir / f"{entry.key}.reason.txt"
        note.write_text(reason, encoding="utf-8")
        return note

    def depth(self) -> int:
        return len(list(self.pending_dir.glob("*.json")))

    # ---------------------------------------------------------------- 消息去重

    def claim(self, message_id: str) -> bool:
        """占坑：返回 True 表示这条消息是第一次见到，可以执行。

        先占坑再执行：宁可在崩溃时漏执行一条请求，也不能在重投时把同一条请求执行两遍——
        采集和播报都是有副作用的。占坑与结果分两次写，正是为了让「占了坑但没写结果」
        这个中间态可被识别（= 处理到一半进程没了）。
        """
        key = str(message_id)
        if key in self._seen:
            return False
        self._append_seen(key, "")
        return True

    def record_outcome(self, message_id: str, status: str) -> None:
        """记下这条消息最终回了什么状态，供重投时原样补发。"""
        self._append_seen(str(message_id), status)

    def outcome_of(self, message_id: str) -> str | None:
        """None=没见过；""=见过但没跑完（崩在中间）；其余=已回过的终态。"""
        return self._seen.get(str(message_id))

    def _append_seen(self, key: str, status: str) -> None:
        self._seen[key] = status
        with self.seen_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{key}\t{status}\n")
        if len(self._seen) > SEEN_LIMIT:
            self._compact_seen()

    def _load_seen(self) -> dict[str, str]:
        if not self.seen_path.exists():
            return {}
        seen: dict[str, str] = {}
        for line in self.seen_path.read_text("utf-8").splitlines():
            if not line.strip():
                continue
            key, _, status = line.partition("\t")
            # 后写的覆盖先写的：占坑行在前，结果行在后
            seen[key.strip()] = status.strip()
        return seen

    def _compact_seen(self) -> None:
        keep = dict(list(self._seen.items())[-(SEEN_LIMIT // 2) :])
        self._seen = keep
        body = "".join(f"{key}\t{status}\n" for key, status in keep.items())
        _atomic_write(self.seen_path, body.encode("utf-8"))


def _safe_key(key: str) -> str:
    """幂等键会直接变成文件名，先把路径分隔符挡掉。"""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in key).strip("._")
    return cleaned or uuid.uuid4().hex


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


__all__ = ["Spool", "SpoolEntry"]
