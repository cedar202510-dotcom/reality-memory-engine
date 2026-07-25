"""给实体补粗分类（PORTABLE / FIXTURE / PERSON / CONSUMABLE）。

为什么不放在摄入热路径里：分类要调 LLM，而 resolve_entity 在每帧感知里都会跑。
把一次网络往返塞进那条路会让感知延迟随物体数线性上涨。所以这里做批量回填，
新实体默认 UNCLASSIFIED，隔一阵跑一次就行。

用户改过的分类（category_source='user'）永不覆盖——那是人给的答案，不是模型的。

用法：
    cd services/memory-platform
    .venv/bin/python scripts/classify_entities.py --dry-run
    .venv/bin/python scripts/classify_entities.py
    .venv/bin/python scripts/classify_entities.py --all   # 连已判过的一起重判（不含 user）
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.llm import build_llm_client  # noqa: E402
from app.memory.classify import classify_names  # noqa: E402
from app.models import Entity  # noqa: E402


async def main(dry_run: bool, redo_all: bool) -> None:
    settings = get_settings()
    print(f"LLM_PROVIDER={settings.llm_provider}")
    if settings.llm_provider == "fake":
        print("！FakeLLM 不会给出真实分类，先在 .env 配好 LLM_PROVIDER 再跑")

    llm = build_llm_client()
    async with SessionLocal() as session:
        query = select(Entity)
        if not redo_all:
            query = query.where(Entity.category == "UNCLASSIFIED")
        # 用户拍过板的一律不动
        query = query.where(Entity.category_source != "user")
        entities = list((await session.scalars(query)).all())

        if not entities:
            print("没有需要分类的实体。")
            return

        names = sorted({e.canonical_name for e in entities})
        print(f"{len(entities)} 个实体、{len(names)} 个不同名称待分类")

        verdict = await classify_names(llm, names)
        missing = [n for n in names if n not in verdict]

        counts: Counter[str] = Counter()
        for e in entities:
            category = verdict.get(e.canonical_name)
            if category is None:
                continue
            counts[category] += 1
            if not dry_run:
                e.category = category
                e.category_source = "llm"

        for category, n in counts.most_common():
            sample = [n2 for n2 in names if verdict.get(n2) == category][:6]
            print(f"  {category:13} {n:3} 个    {'、'.join(sample)}")
        if missing:
            # 判不了的留在 UNCLASSIFIED——这是诚实的「还没判」，不是兜底垃圾桶
            print(f"  UNCLASSIFIED  {len(missing):3} 个名称模型没给出合法类别：{'、'.join(missing[:10])}")

        if dry_run:
            print("\n--dry-run：什么都没写。")
            return
        await session.commit()
        print(f"\n已写入 {sum(counts.values())} 个实体的分类。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写库")
    parser.add_argument("--all", action="store_true", help="连已判过的一起重判（user 改过的仍然跳过）")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run, args.all))
