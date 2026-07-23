package com.realitymemory.cxrlprobe

data class BoundarySignals(
    val goalShift: Double,
    val spaceShift: Double,
    val objectSetShift: Double,
    val socialContextShift: Double,
    val temporalGap: Double,
    val predictionError: Double
)

enum class BoundaryDecision {
    CONTINUE,
    NEED_MORE_EVIDENCE,
    CANDIDATE_SPLIT
}

data class BoundaryScore(
    val total: Double,
    val decision: BoundaryDecision
)

object SessionBoundaryPolicy {
    const val NEED_MORE_EVIDENCE_THRESHOLD = 0.45
    const val SESSION_SPLIT_THRESHOLD = 0.72

    fun score(signals: BoundarySignals): BoundaryScore {
        val total = (
            signals.goalShift.coerceIn(0.0, 1.0) * 0.40 +
                signals.spaceShift.coerceIn(0.0, 1.0) * 0.15 +
                signals.objectSetShift.coerceIn(0.0, 1.0) * 0.15 +
                signals.socialContextShift.coerceIn(0.0, 1.0) * 0.10 +
                signals.temporalGap.coerceIn(0.0, 1.0) * 0.10 +
                signals.predictionError.coerceIn(0.0, 1.0) * 0.10
            )

        val decision = when {
            total >= SESSION_SPLIT_THRESHOLD -> BoundaryDecision.CANDIDATE_SPLIT
            total >= NEED_MORE_EVIDENCE_THRESHOLD -> BoundaryDecision.NEED_MORE_EVIDENCE
            else -> BoundaryDecision.CONTINUE
        }
        return BoundaryScore(total = total, decision = decision)
    }
}
