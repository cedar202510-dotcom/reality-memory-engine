"""喜好度打分（纯函数）单测。不碰数据库，全部是「给定证据 → 期望结论」。

这些断言是喜好度的行为契约：改权重可以，但改到让下面某条不成立时，
必须先想清楚新的行为对不对，而不是顺手改掉断言。
"""
from __future__ import annotations

import pytest

from app.insight.affinity import (
    LEVEL_DISLIKE,
    LEVEL_LIKE,
    LEVEL_NEUTRAL,
    LEVEL_STRONG_DISLIKE,
    LEVEL_STRONG_LIKE,
    LEVEL_UNKNOWN,
    AffinitySignals,
    IntentStatement,
    VerbalStatement,
    score_affinity,
)


def _like(intensity: float = 0.9, **kw) -> VerbalStatement:
    return VerbalStatement(sentiment="LIKE", intensity=intensity, confidence=0.9, **kw)


def _dislike(intensity: float = 0.9, **kw) -> VerbalStatement:
    return VerbalStatement(sentiment="DISLIKE", intensity=intensity, confidence=0.9, **kw)


# ---------------------------------------------------------------- 基本极性


def test_no_evidence_is_unknown_not_neutral():
    """没有任何证据时必须是「证据不足」，不能报 50 分中性。

    这两者在产品上完全不同：中性是「我知道你无所谓」，
    证据不足是「我不知道」。把后者显示成前者是在编造用户画像。
    """
    result = score_affinity(AffinitySignals(entity_name="花生"))
    assert result.level == LEVEL_UNKNOWN
    assert result.score == 50
    assert result.confidence == 0.0
    assert not result.has_verdict


def test_strong_like_scores_high():
    result = score_affinity(
        AffinitySignals(entity_name="橙皮", verbal=[_like(0.95), _like(0.9)])
    )
    assert result.score >= 80
    assert result.level == LEVEL_STRONG_LIKE
    assert result.polarity > 0.8


def test_strong_dislike_scores_low():
    result = score_affinity(
        AffinitySignals(entity_name="鸡米花", verbal=[_dislike(0.95), _dislike(0.9)])
    )
    assert result.score <= 20
    assert result.level == LEVEL_STRONG_DISLIKE
    assert result.polarity < -0.8


def test_mild_evaluation_lands_between_neutral_and_like():
    """「一般般」(intensity 0.2, LIKE) 不该被打成「强烈喜欢」。"""
    result = score_affinity(
        AffinitySignals(entity_name="花生", verbal=[_like(0.2), _like(0.2), _like(0.2)])
    )
    assert 50 < result.score < 62
    assert result.level == LEVEL_NEUTRAL


def test_mixed_verbal_averages_out():
    """褒贬参半 → 接近中性，而不是取最后一条或最强一条。"""
    result = score_affinity(
        AffinitySignals(entity_name="花生", verbal=[_like(0.8), _dislike(0.8)])
    )
    assert result.score == pytest.approx(50, abs=3)


def test_neutral_sentiment_contributes_zero():
    signals = AffinitySignals(
        entity_name="杯子",
        verbal=[VerbalStatement(sentiment="NEUTRAL", intensity=0.9, confidence=0.9)],
    )
    result = score_affinity(signals)
    assert result.score == 50
    # NEUTRAL 仍然算作有人评价过，所以 confidence 不为零
    assert result.confidence > 0


# ---------------------------------------------------------------- 通道语义


def test_attention_alone_never_yields_a_verdict():
    """只被拍到、从没被评价过的物体不能有喜好结论。

    这是最容易出错的地方：画面停留时长是「感兴趣」，不是「喜欢」。
    一个反复出现在画面里的垃圾桶不该被打成用户偏爱的物品。
    """
    result = score_affinity(
        AffinitySignals(entity_name="垃圾桶", frame_count=12, dwell_seconds=60.0)
    )
    assert result.level == LEVEL_UNKNOWN
    assert result.confidence < 0.15
    assert result.score > 50  # 分数偏正，但因证据不足不下结论


def test_behavior_alone_never_yields_a_verdict():
    result = score_affinity(AffinitySignals(entity_name="牙刷", use_count=10))
    assert result.level == LEVEL_UNKNOWN


def test_attention_cannot_pull_score_negative():
    """正向专用通道：注意力/行为再少也只能不参与，不能把分数往下拽。"""
    baseline = score_affinity(
        AffinitySignals(entity_name="橙皮", verbal=[_like(0.9)])
    )
    with_no_attention = score_affinity(
        AffinitySignals(
            entity_name="橙皮", verbal=[_like(0.9)], frame_count=0, dwell_seconds=0.0
        )
    )
    assert with_no_attention.score == baseline.score


def test_attention_nudges_a_dislike_upward_but_does_not_flip_it():
    """看得多可以让负面评价稍微缓和，但绝不能把「不喜欢」翻成「喜欢」。"""
    plain = score_affinity(AffinitySignals(entity_name="鸡米花", verbal=[_dislike(0.7)]))
    watched = score_affinity(
        AffinitySignals(
            entity_name="鸡米花",
            verbal=[_dislike(0.7)],
            frame_count=8,
            dwell_seconds=40.0,
            use_count=3,
        )
    )
    assert watched.score > plain.score
    assert watched.score < 50
    assert watched.level in (LEVEL_DISLIKE, LEVEL_STRONG_DISLIKE, LEVEL_NEUTRAL)


def test_intent_avoid_is_a_negative_signal():
    result = score_affinity(
        AffinitySignals(
            entity_name="这家店",
            intents=[IntentStatement(intent_kind="AVOID", confidence=0.9)],
        )
    )
    assert result.score < 50
    assert result.polarity < 0


def test_intent_repeat_is_a_positive_signal():
    result = score_affinity(
        AffinitySignals(
            entity_name="橙皮",
            intents=[IntentStatement(intent_kind="REPEAT", confidence=0.9)],
        )
    )
    assert result.score > 50


def test_intent_other_is_neutral():
    result = score_affinity(
        AffinitySignals(
            entity_name="快递",
            intents=[IntentStatement(intent_kind="OTHER", confidence=0.9)],
        )
    )
    assert result.score == 50


# ---------------------------------------------------------------- 置信度与衰减


def test_more_statements_raise_confidence_but_saturate():
    one = score_affinity(AffinitySignals(verbal=[_like(0.9)]))
    three = score_affinity(AffinitySignals(verbal=[_like(0.9)] * 3))
    ten = score_affinity(AffinitySignals(verbal=[_like(0.9)] * 10))
    assert one.confidence < three.confidence < ten.confidence
    # 边际递减：从 3 条到 10 条的增幅要小于从 1 条到 3 条
    assert (ten.confidence - three.confidence) < (three.confidence - one.confidence)
    assert ten.confidence <= 1.0


def test_old_statements_weigh_less_than_recent_ones():
    """半年前说「好吃」不该和昨天说「难吃」打平。"""
    result = score_affinity(
        AffinitySignals(
            verbal=[_like(0.9, age_days=365.0), _dislike(0.9, age_days=0.0)]
        )
    )
    assert result.score < 50, "近期的负面评价应当压过一年前的正面评价"


def test_superseded_statement_is_heavily_discounted():
    active_only = score_affinity(AffinitySignals(verbal=[_dislike(0.9)]))
    with_superseded_like = score_affinity(
        AffinitySignals(verbal=[_dislike(0.9), _like(0.9, superseded=True)])
    )
    # 被纠正的正面评价只应轻微拉高，不能把结论翻过来
    assert with_superseded_like.score > active_only.score
    assert with_superseded_like.score < 50


def test_low_confidence_statement_yields_no_verdict():
    """ASR 错听会带低置信度进来，低到一定程度就不该下结论。"""
    result = score_affinity(
        AffinitySignals(
            verbal=[VerbalStatement(sentiment="LIKE", intensity=0.9, confidence=0.05)]
        )
    )
    assert result.level == LEVEL_UNKNOWN


# ---------------------------------------------------------------- 输出契约


def test_score_always_in_range_and_channels_reported():
    result = score_affinity(
        AffinitySignals(
            entity_name="花生",
            verbal=[_like(0.6)],
            intents=[IntentStatement(intent_kind="PURCHASE", confidence=0.8)],
            use_count=2,
            frame_count=5,
            dwell_seconds=25.0,
        )
    )
    assert 0 <= result.score <= 100
    assert -1.0 <= result.polarity <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert {c.channel for c in result.channels} == {
        "verbal",
        "intent",
        "behavior",
        "attention",
    }
    assert all(c.weight > 0 for c in result.channels)


@pytest.mark.parametrize(
    "intensity,expected_level",
    [
        (0.95, LEVEL_STRONG_LIKE),
        (0.7, LEVEL_LIKE),
        (0.1, LEVEL_NEUTRAL),
    ],
)
def test_intensity_maps_to_level(intensity, expected_level):
    result = score_affinity(AffinitySignals(verbal=[_like(intensity)] * 3))
    assert result.level == expected_level


def test_extreme_values_do_not_overflow():
    result = score_affinity(
        AffinitySignals(
            verbal=[_like(99.0)] * 50,   # 越界 intensity 应被夹到 1.0
            use_count=10_000,
            frame_count=10_000,
            dwell_seconds=1e6,
        )
    )
    assert result.score == 100
    assert result.polarity <= 1.0
