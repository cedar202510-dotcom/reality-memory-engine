"""喜好度洞察：把跨模态证据融合成「用户对什么有什么态度」。

affinity.py 是纯打分函数（可单测、可解释），service.py 负责从库里取数。
"""
from .affinity import (
    AffinityScore,
    AffinitySignals,
    ChannelScore,
    IntentStatement,
    VerbalStatement,
    score_affinity,
)
from .service import EntityAffinity, EvidenceRef, compute_household_affinities

__all__ = [
    "AffinityScore",
    "AffinitySignals",
    "ChannelScore",
    "EntityAffinity",
    "EvidenceRef",
    "IntentStatement",
    "VerbalStatement",
    "compute_household_affinities",
    "score_affinity",
]
