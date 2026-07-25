"""OCR 文本脱敏：把证件号/卡号/手机号在**入库之前**换成类型占位符。

为什么这一步不是可选的加分项，而是这条通道能不能存在的前提：
整个平台的隐私模型是「原始媒体短命」——EVIDENCE_TTL_MINUTES 默认 15 分钟就把
原件物理删了。OCR 却把画面里的字抄成了长期文本，如果原样入库，一张身份证的
姓名和号码会在 Postgres 里活到天荒地老，而那张照片 15 分钟后就没了。
那等于把隐私模型整个反过来：本来是"看过就忘"，变成"看一眼记一辈子，而且记的
偏偏是最敏感的那 18 位数字"。

占位符刻意保留类型名（〔身份证号〕而不是 ***）：
1. 检索还能用——查「身份证」时 ilike '%身份证%' 照样命中〔身份证号〕，
   银行卡这种卡面上只有一串数字、没有品类文字的物体尤其依赖这一点；
2. 事后能看懂——运维看到的是"这里曾有一个身份证号"，而不是一段无从解释的星号。

顺序有讲究：18 位身份证号同时落在银行卡号的 16-19 位区间里，必须先替身份证。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# 15 位老身份证号没有独立规则：它和银行卡号、订单号在纯数字形态上无法区分，
# 硬加规则会把一堆无关数字误伤成证件号。宁可漏，不可把可用文本毁掉。
_RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "id_card",
        # 6 位地区码 + 8 位出生日期 + 3 位顺序码 + 1 位校验位（可为 X）
        re.compile(
            r"(?<![0-9Xx])[1-9]\d{5}(?:19|20)\d{2}"
            r"(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9Xx])"
        ),
        "〔身份证号〕",
    ),
    ("bank_card", re.compile(r"(?<!\d)\d{16,19}(?!\d)"), "〔银行卡号〕"),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "〔手机号〕"),
    (
        "email",
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        "〔邮箱〕",
    ),
]


@dataclass(frozen=True)
class RedactionResult:
    """脱敏结果：可入库的文本 + 命中了哪些类型（按出现顺序去重）。"""

    text: str
    kinds: tuple[str, ...]

    @property
    def redacted(self) -> bool:
        return bool(self.kinds)


def redact_pii(text: str) -> RedactionResult:
    """把文本里的证件号/卡号/手机号/邮箱替换成类型占位符。"""
    kinds: list[str] = []
    out = text
    for kind, pattern, placeholder in _RULES:
        out, n = pattern.subn(placeholder, out)
        if n:
            kinds.append(kind)
    return RedactionResult(text=out, kinds=tuple(kinds))
