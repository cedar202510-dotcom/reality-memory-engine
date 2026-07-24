"""会话存储：内存态 + TTL（§12：查询结果不进长期存储，过期即失去）。

会话只保存对话消息（含工具结果消息）；不做独立的结果缓存层，
因此"纠正/删除后缓存失效"在结构上成立——每次查询都是对平台的实时调用。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Session:
    id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    expires_at: datetime = field(default_factory=_now)


class SessionStore:
    def __init__(self, *, ttl_minutes: int = 30, max_sessions: int = 1000) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._max = max_sessions
        self._sessions: dict[str, Session] = {}

    def _purge(self) -> None:
        now = _now()
        for sid in [s for s, sess in self._sessions.items() if sess.expires_at <= now]:
            del self._sessions[sid]
        # 容量兜底：按过期时间淘汰最旧会话
        while len(self._sessions) > self._max:
            oldest = min(self._sessions.values(), key=lambda s: s.expires_at)
            del self._sessions[oldest.id]

    def get_or_create(self, session_id: str | None) -> Session:
        self._purge()
        if session_id and session_id in self._sessions:
            sess = self._sessions[session_id]
        else:
            sess = Session(id=session_id or uuid.uuid4().hex)
            self._sessions[sess.id] = sess
        sess.expires_at = _now() + self._ttl
        return sess

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
