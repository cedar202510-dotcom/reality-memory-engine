"""实体粗分类：按名字判「这是不是一件你会去找的东西」。

为什么按**名字**而不是按视觉向量判：
entity.visual_embedding 是**整帧** CLIP 向量的滑动平均（见 resolver._update_visual_average），
它编码的是「这东西出现在什么场景里」，不是「这东西长什么样」。实测同一批场景里
茶杯 ↔ 木地板 的余弦距离只有 0.083——一个杯子和一块地板在这个空间里几乎重合。
拿它做零样本分类只会得到「茶室的东西 / 书桌的东西」，那就是现成的位置分组换个名字。
要按外观判必须先有物体级裁剪（frame_regions 里 source='detect' 的那条路），现在还没有。

为什么分这四档而不是数码/日用那种品类：
感知会把 人、手臂、木地板、墙面、空调 一并认成实体（它们确实在画面里）。品类表容不下
它们，硬塞进「其他」会让「其他」变成垃圾桶。而「我的东西在哪」只关心 PORTABLE 那一档。
"""
from __future__ import annotations

from ..llm.base import LLMClient
from ..schemas import ENTITY_CATEGORIES

# 一次调用判多少个名字。实测 40 个一批时 k3 只回一部分就收尾（JSON 被截断），
# 而漏掉的名字在代码里会静默变成 UNCLASSIFIED——看起来像「模型拿不准」，其实是
# 「模型没说完」。这两件事在界面上完全不同，不能混。所以批量压小 + 对漏项重试。
BATCH_SIZE = 12
# 漏项重试轮数。每轮把上一轮没回的名字再问一次，批量减半。
MAX_ROUNDS = 3

_VALID = set(ENTITY_CATEGORIES)

PROMPT = """把下列物体名称各自归入一个类别。

类别定义：
- PORTABLE：可移动、会被人拿走或到处放的东西。手机、充电线、钥匙、茶杯、背包、书。
  判断标准是「主人会问『它在哪』」。
- FIXTURE：属于场景本身、基本不动的东西。地板、墙面、天花板、窗帘、空调、门、
  以及作为家具的桌子/椅子/置物架本身。
- PERSON：人，以及人的身体部位。人、手、手臂、脸。
- CONSUMABLE：吃的喝的和一次性耗材。包子、汤面、饮料、纸巾、调料包。
- UNCLASSIFIED：名称太含糊或压根判不了。

注意：同一个词在不同语境可能不同，按最常见的理解判就行。拿不准就给 UNCLASSIFIED，
不要硬猜——分错了比不分更糟，界面会把它当成确定的事实展示。

物体名称：
{names}

只输出 JSON：{{"results": [{{"name": "原名称", "category": "类别"}}]}}
每个输入名称都要出现一次，name 必须与输入完全一致。"""


async def classify_names(llm: LLMClient, names: list[str]) -> dict[str, str]:
    """名称 → 类别。判不了的名字不会出现在返回里（调用方保持 UNCLASSIFIED）。

    模型返回不合契约的类别、漏项、多出没问过的名字，一律丢弃——宁可留 UNCLASSIFIED，
    也不要把一个瞎猜的类别写进库里当事实。
    """
    pending = list(dict.fromkeys(n for n in names if n and n.strip()))
    out: dict[str, str] = {}
    size = BATCH_SIZE

    # 漏项重试：模型没回的名字再问一次、批量减半。不重试的话「模型没说完」会被
    # 当成「模型判不了」，界面上看起来一样，但一个是 bug、一个是事实。
    for _ in range(MAX_ROUNDS):
        if not pending:
            break
        for start in range(0, len(pending), size):
            batch = pending[start : start + size]
            prompt = PROMPT.format(names="\n".join(f"- {n}" for n in batch))
            try:
                raw = await llm.complete_json(task="entity_classify", prompt=prompt)
            except Exception:  # noqa: BLE001 - 一批失败不该带塌整次分类
                continue
            asked = set(batch)
            for row in (raw or {}).get("results", []) or []:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name", "")).strip()
                category = str(row.get("category", "")).strip().upper()
                # 只认问过的名字 + 契约内的类别
                if name in asked and category in _VALID and category != "UNCLASSIFIED":
                    out[name] = category
        pending = [n for n in pending if n not in out]
        size = max(1, size // 2)
    return out
