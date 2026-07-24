"""实体解析器：按 canonical_name/别名/embedding/视觉向量匹配已有实体。

原则：相似但不完全一致 → 保守新建，不合并。
例外（物体级合并）：候选带来源帧 CLIP 向量时，若某实体的实例代表视觉向量
高度相似（≥ resolver_visual_merge_threshold）且名称 trgm 过了低门槛
（≥ resolver_name_low_bar，防止同帧异物误并），则视为同一物体实例合并，
并把新名字记为别名、滑动平均更新实体的代表视觉向量。
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Entity

EXACT_MATCH = 1.0
TRGM_THRESHOLD = 0.9          # 很高才合并；否则新建
EMBEDDING_THRESHOLD = 0.98    # 名称向量近重合才视为同一实体


def _update_visual_average(entity: Entity, frame_vec: list[float]) -> None:
    """滑动平均更新实体的实例代表视觉向量。"""
    n = entity.visual_embedding_count or 0
    if entity.visual_embedding is None or n <= 0:
        entity.visual_embedding = list(frame_vec)
        entity.visual_embedding_count = 1
        return
    merged = [(a * n + b) / (n + 1) for a, b in zip(entity.visual_embedding, frame_vec)]
    entity.visual_embedding = merged
    entity.visual_embedding_count = n + 1


def _record_alias(entity: Entity, name: str) -> None:
    """视觉合并发生时，把候选的新叫法记为别名（提升后续名称匹配命中）。"""
    if name.lower() == entity.canonical_name.lower():
        return
    aliases = list(entity.aliases or [])
    if name not in aliases:
        entity.aliases = aliases + [name]


async def resolve_entity(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    name: str,
    embedding: list[float] | None = None,
    frame_visual_embedding: list[float] | None = None,
    created_from: str = "observation",
) -> tuple[Entity, bool]:
    """返回 (entity, created)。保守策略：只有强匹配才复用，否则新建。"""
    settings = get_settings()
    name = name.strip()
    matched: Entity | None = None

    # 1) 规范名精确匹配 / 别名精确包含
    matched = await session.scalar(
        select(Entity).where(
            Entity.household_id == household_id,
            or_(
                func.lower(Entity.canonical_name) == name.lower(),
                Entity.aliases.contains([name]),
            ),
        )
    )

    # 2) trgm 高相似（≥0.9 才合并，避免"手机壳"并入"手机"）
    if matched is None:
        rows = (
            await session.execute(
                select(Entity, func.similarity(Entity.canonical_name, name).label("sim")).where(
                    Entity.household_id == household_id,
                    Entity.canonical_name.op("%")(name),
                )
            )
        ).all()
        for entity, sim in rows:
            if sim >= TRGM_THRESHOLD:
                matched = entity
                break

    # 3) 名称向量近重合
    if matched is None and embedding is not None:
        near = (
            await session.execute(
                select(Entity, Entity.embedding.cosine_distance(embedding).label("dist")).where(
                    Entity.household_id == household_id,
                    Entity.embedding.is_not(None),
                )
            )
        ).all()
        for entity, dist in near:
            if dist is not None and (1 - dist) >= EMBEDDING_THRESHOLD:
                matched = entity
                break

    # 4) 视觉辅助的物体级合并：视觉高度相似 + 名称过低门槛（挡同帧异物）
    if matched is None and frame_visual_embedding is not None:
        rows = (
            await session.execute(
                select(
                    Entity,
                    Entity.visual_embedding.cosine_distance(frame_visual_embedding).label("dist"),
                    func.similarity(Entity.canonical_name, name).label("name_sim"),
                ).where(
                    Entity.household_id == household_id,
                    Entity.visual_embedding.is_not(None),
                )
            )
        ).all()
        best: tuple[Entity, float] | None = None
        for entity, dist, name_sim in rows:
            if dist is None:
                continue
            visual_sim = 1 - dist
            if (
                visual_sim >= settings.resolver_visual_merge_threshold
                and (name_sim or 0) >= settings.resolver_name_low_bar
            ):
                if best is None or visual_sim > best[1]:
                    best = (entity, visual_sim)
        if best is not None:
            matched = best[0]
            _record_alias(matched, name)

    if matched is not None:
        if frame_visual_embedding is not None:
            _update_visual_average(matched, frame_visual_embedding)
        return matched, False

    entity = Entity(
        household_id=household_id,
        canonical_name=name,
        embedding=embedding,
        visual_embedding=list(frame_visual_embedding) if frame_visual_embedding else None,
        visual_embedding_count=1 if frame_visual_embedding else 0,
        created_from=created_from,
    )
    session.add(entity)
    await session.flush()
    return entity, True
