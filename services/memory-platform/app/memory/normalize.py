"""名称/位置归一化辅助：纯函数，供实体解析、候选门、查询通道共用。

背景（真机数据实测问题）：
- VLM 对同一物体/地点的叫法在帧间不稳定（「手机」vs「智能手机」、「白桌」vs「白色办公桌」）。
- 名称不归一 → 同一物体裂成多个实体，查询通道 1 命中率低；
- 位置不归一 → 候选门把同一张桌子的两种叫法误判为互斥位置，高置信候选被 CONFLICTED。

策略（无模型、零成本）：中文短名以「包含关系 + 字符 Jaccard」判同。
包含判定要求较短一方长度 ≥ 2，避免单字（如「门」「桌」）误并一切。
"""
from __future__ import annotations


def has_cjk(text: str) -> bool:
    """是否含中日韩统一表意文字（用于判断查询是否需要翻译后进 CLIP）。"""
    return any("一" <= ch <= "鿿" for ch in text)


def _char_overlap(a: str, b: str) -> float:
    """字符 overlap 系数：|交集| / |较短方|。比 Jaccard 更适合「简称 vs 全称」
    （「白桌」vs「白色办公桌」：交集{白,桌}/较短方 2 字 = 1.0；Jaccard 只有 0.4）。"""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def names_alias_match(a: str, b: str) -> bool:
    """两个物体名是否应视为同一实体的别名。

    规则：完全相等（忽略大小写/首尾空白）；或较短方是较长方的**后缀**且长度 ≥ 2。
    中文复合名词核心词在尾部：「智能手机」以「手机」结尾 → 同物；
    「手机壳」以「壳」结尾，「手机」只是前缀修饰 → 不合并（历史上明确要防的误并）。
    """
    a, b = a.strip(), b.strip()
    if not a or not b:
        return False
    if a.lower() == b.lower():
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= 2 and longer.lower().endswith(shorter.lower())


def name_is_abbreviation_of(short: str, long: str) -> bool:
    """short 是否是 long 的后缀简称（「手机」之于「智能手机」）。

    有向版本：用于实体解析的纯名称合并——新名是既有名的简称时合并是安全的
    （同类别泛化）；反方向（新名更长、带属性修饰如「黑色智能手机」）可能是
    另一个实例，纯名称不合并，交给视觉辅助合并路径判定。
    """
    short, long = short.strip(), long.strip()
    if not short or not long:
        return False
    if short.lower() == long.lower():
        return True
    return len(short) >= 2 and len(short) < len(long) and long.lower().endswith(short.lower())


def locations_compatible(a: str | None, b: str | None) -> bool:
    """两个位置描述是否指同一地点（用于冲突判定：兼容 → 不互斥）。

    规则：任一为空视为兼容；名称别名判同兼容；
    否则字符 overlap ≥ 0.6 兼容（「白桌」vs「白色办公桌」→ 1.0；
    「白桌」vs「厨房桌」→ 0.5 不兼容）。
    """
    if not a or not b:
        return True
    a, b = a.strip(), b.strip()
    if names_alias_match(a, b):
        return True
    return _char_overlap(a, b) >= 0.6
