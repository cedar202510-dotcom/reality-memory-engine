"""TTL 清理：媒体短命。过期证据物理删除，接口上保留 encryption_key_id 字段位。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..memory.events import record_audit
from ..models import EvidenceItem, utcnow


async def sweep_expired_evidence(session: AsyncSession) -> int:
    """删除 ttl_until 过期的证据文件（v0 用本地文件删除模拟 crypto-shredding）。返回删除数。"""
    expired = list(
        (
            await session.scalars(
                select(EvidenceItem).where(
                    EvidenceItem.retention_state == "ACTIVE",
                    EvidenceItem.ttl_until < utcnow(),
                )
            )
        ).all()
    )
    for item in expired:
        if item.storage_ref:
            path = Path(item.storage_ref)
            if path.exists():
                path.unlink()
            item.storage_ref = None
        item.retention_state = "DELETED"
        await record_audit(
            session,
            actor="system/ttl-worker",
            action="ttl_delete",
            target=f"evidence:{item.id}",
            detail={"ttl_until": item.ttl_until.isoformat(), "encryption_key_id": item.encryption_key_id},
        )
    if expired:
        await session.commit()
    return len(expired)
