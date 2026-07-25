"""喜好度打分：把四路证据融合成一个 0~100 的分数。

这里刻意是纯函数——不碰 session、不查库、不调模型。喜好度是要拿给用户看、
还要被 Agent 当作推荐依据的数字，它必须能被逐项解释、能被单测钉死。
把「怎么算」和「从哪取」分开之后，改权重只需要改这个文件，不用担心
顺手改坏了取数逻辑。

四路证据不是平权的，因为它们回答的不是同一个问题：

  verbal    说了什么   —— 唯一直接表达好恶的通道，也是唯一能取负的主力
  intent    打算怎么做 —— 「还想再买」「以后别买了」，比评价更接近行为承诺
  behavior  实际做了什么 —— 用过/吃过。只能是弱正证据：用了不等于喜欢
  attention 看了多久   —— 画面停留时长。更弱，只能算「感兴趣」不能算「喜欢」

后两路刻意只能往正向拉：从「他盯着看了 30 秒」推不出任何负面结论，
而如果允许它们取负，一个只被拍到一次的物体就会因为「注意力少」被打成不喜欢，
那是把缺少证据错当成了负面证据。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# 各通道权重。verbal 是基准 1.0，其余相对它折算。
W_VERBAL = 1.0
W_INTENT = 0.7
W_BEHAVIOR = 0.35
W_ATTENTION = 0.25

# 证据量的饱和常数：第 1 条证据贡献最大，之后边际递减。
# 说 3 次「好吃」比说 1 次更可信，但不该是 3 倍可信。
MASS_SATURATION = 2.0
BEHAVIOR_SATURATION = 3.0      # 用过 3 次 ≈ 63% 饱和
ATTENTION_SATURATION = 45.0    # 画面停留 45s ≈ 63% 饱和

# 偏好会变。90 天前说「爱吃」不该和昨天说的一样重。
RECENCY_HALF_LIFE_DAYS = 90.0

# 被纠正/被取代的陈述不直接丢弃（它确实发生过），但降到很低的权重
SUPERSEDED_WEIGHT = 0.15

# 低于这个证据量就不给结论：宁可说「不知道」也不要拿 1 帧画面编一个喜好
MIN_CONFIDENCE_FOR_VERDICT = 0.15

LEVEL_STRONG_LIKE = "强烈喜欢"
LEVEL_LIKE = "喜欢"
LEVEL_NEUTRAL = "中性"
LEVEL_DISLIKE = "不喜欢"
LEVEL_STRONG_DISLIKE = "强烈不喜欢"
LEVEL_UNKNOWN = "证据不足"

# intent_kind → 符号。PURCHASE/REPEAT 是正向承诺，AVOID 是负向承诺。
INTENT_SIGN = {"PURCHASE": 1.0, "REPEAT": 1.0, "AVOID": -1.0, "OTHER": 0.0}


def _saturate(x: float, k: float) -> float:
    """0→0，单调递增趋近 1 的饱和曲线。k 是达到 ~63% 的位置。"""
    if x <= 0 or k <= 0:
        return 0.0
    return 1.0 - math.exp(-x / k)


def _recency_weight(age_days: float | None) -> float:
    if age_days is None or age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


@dataclass(frozen=True)
class VerbalStatement:
    """一条口头评价，来自 PREFERENCE_STATED 事件。"""

    sentiment: str                # LIKE / DISLIKE / NEUTRAL
    intensity: float = 0.5        # 0~1
    confidence: float = 0.5       # 事件的 aggregate 置信度
    age_days: float | None = None
    superseded: bool = False
    text: str = ""

    @property
    def signed(self) -> float:
        s = (self.sentiment or "").upper()
        if s == "LIKE":
            return _clamp01(self.intensity)
        if s == "DISLIKE":
            return -_clamp01(self.intensity)
        return 0.0

    @property
    def weight(self) -> float:
        w = _clamp01(self.confidence) * _recency_weight(self.age_days)
        return w * (SUPERSEDED_WEIGHT if self.superseded else 1.0)


@dataclass(frozen=True)
class IntentStatement:
    """一条意图，来自 TASK_STATED 事件。"""

    intent_kind: str = "OTHER"
    confidence: float = 0.5
    age_days: float | None = None
    superseded: bool = False
    text: str = ""

    @property
    def signed(self) -> float:
        return INTENT_SIGN.get((self.intent_kind or "OTHER").upper(), 0.0)

    @property
    def weight(self) -> float:
        w = _clamp01(self.confidence) * _recency_weight(self.age_days)
        return w * (SUPERSEDED_WEIGHT if self.superseded else 1.0)


@dataclass
class AffinitySignals:
    """某个实体的全部喜好证据。由 service 层从库里拼出来。"""

    entity_name: str = ""
    verbal: list[VerbalStatement] = field(default_factory=list)
    intents: list[IntentStatement] = field(default_factory=list)
    use_count: int = 0             # USED / CONSUMED 观察条数
    frame_count: int = 0           # 出现在多少张帧里
    dwell_seconds: float = 0.0     # 视频关键帧推算的画面停留秒数


@dataclass(frozen=True)
class ChannelScore:
    """单通道的结果，用于前端逐项展开解释这个分是怎么来的。"""

    channel: str
    value: float       # -1~1 的有符号取值
    weight: float      # 该通道在本次融合里的实际权重（含证据量折算）
    evidence_count: int


@dataclass(frozen=True)
class AffinityScore:
    score: int                     # 0~100
    level: str
    polarity: float                # -1~1
    confidence: float              # 0~1，证据充分程度
    channels: list[ChannelScore]

    @property
    def has_verdict(self) -> bool:
        return self.level != LEVEL_UNKNOWN


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _weighted_mean(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    """返回 (加权均值, 权重和)。权重和为 0 时均值记 0。"""
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return 0.0, 0.0
    return sum(v * w for v, w in pairs) / total_w, total_w


def score_affinity(signals: AffinitySignals) -> AffinityScore:
    """四路证据 → 喜好度。

    融合方式是「有符号通道按证据量加权平均」，而不是把各通道分数相加：
    相加会让证据多的物体天然分高，但喜好度问的是「多喜欢」不是「有多少证据」——
    证据多少体现在 confidence 上，不该混进分数本身。
    """
    channels: list[ChannelScore] = []
    terms: list[tuple[float, float]] = []

    # ---- verbal ----
    if signals.verbal:
        v_value, v_mass = _weighted_mean([(s.signed, s.weight) for s in signals.verbal])
        v_weight = W_VERBAL * _saturate(v_mass, MASS_SATURATION)
        terms.append((v_value, v_weight))
        channels.append(
            ChannelScore("verbal", v_value, v_weight, len(signals.verbal))
        )

    # ---- intent ----
    if signals.intents:
        i_value, i_mass = _weighted_mean([(s.signed, s.weight) for s in signals.intents])
        i_weight = W_INTENT * _saturate(i_mass, MASS_SATURATION)
        terms.append((i_value, i_weight))
        channels.append(
            ChannelScore("intent", i_value, i_weight, len(signals.intents))
        )

    # ---- behavior（只正向） ----
    b_value = _saturate(signals.use_count, BEHAVIOR_SATURATION)
    if b_value > 0:
        # 权重正比于自身：没用过就完全不参与，而不是以 0 分把结果往中性拽
        b_weight = W_BEHAVIOR * b_value
        terms.append((b_value, b_weight))
        channels.append(ChannelScore("behavior", b_value, b_weight, signals.use_count))

    # ---- attention（只正向） ----
    # 停留秒数优先；没有视频来源时退回帧数（每帧记 1 个「注意力单位」）
    attention_raw = signals.dwell_seconds or float(signals.frame_count)
    a_scale = ATTENTION_SATURATION if signals.dwell_seconds else 4.0
    a_value = _saturate(attention_raw, a_scale)
    if a_value > 0:
        a_weight = W_ATTENTION * a_value
        terms.append((a_value, a_weight))
        channels.append(
            ChannelScore("attention", a_value, a_weight, signals.frame_count)
        )

    polarity, total_weight = _weighted_mean(terms)
    polarity = max(-1.0, min(1.0, polarity))

    # confidence 只看「有符号通道」的证据量：一个只被看见过、从没被评价过的
    # 物体，attention 再高也不代表我们知道用户喜不喜欢它。
    verdict_mass = sum(
        c.weight for c in channels if c.channel in ("verbal", "intent")
    )
    confidence = _clamp01(_saturate(verdict_mass, 0.6))

    score = int(round(50 + 50 * polarity))
    score = max(0, min(100, score))
    level = _level_of(score, confidence)
    return AffinityScore(
        score=score,
        level=level,
        polarity=round(polarity, 4),
        confidence=round(confidence, 4),
        channels=channels,
    )


# 档位阈值，关于中性 50 对称。
#
# 「强烈」档定在 ±38 分（polarity 0.76）而不是更宽松的 ±30，是因为抽取侧把
# 「好吃/不错」标定在 intensity≈0.6：如果 80 分就算强烈喜欢，那么说三次「好吃」
# 就会被系统判成「强烈喜欢」。重复的温和评价应该抬高的是 confidence（我更确定了），
# 不是 polarity（他更喜欢了）——只有用户真的说了「太好吃了」才配进强烈档。
LEVEL_THRESHOLD_STRONG_LIKE = 88
LEVEL_THRESHOLD_LIKE = 62
LEVEL_THRESHOLD_DISLIKE = 38
LEVEL_THRESHOLD_STRONG_DISLIKE = 12


def _level_of(score: int, confidence: float) -> str:
    if confidence < MIN_CONFIDENCE_FOR_VERDICT:
        return LEVEL_UNKNOWN
    if score >= LEVEL_THRESHOLD_STRONG_LIKE:
        return LEVEL_STRONG_LIKE
    if score >= LEVEL_THRESHOLD_LIKE:
        return LEVEL_LIKE
    if score > LEVEL_THRESHOLD_DISLIKE:
        return LEVEL_NEUTRAL
    if score > LEVEL_THRESHOLD_STRONG_DISLIKE:
        return LEVEL_DISLIKE
    return LEVEL_STRONG_DISLIKE
