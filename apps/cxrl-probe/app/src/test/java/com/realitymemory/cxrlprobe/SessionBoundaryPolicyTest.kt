package com.realitymemory.cxrlprobe

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SessionBoundaryPolicyTest {
    @Test
    fun stableGoalKeepsCookingInOneSession() {
        val score = SessionBoundaryPolicy.score(
            BoundarySignals(
                goalShift = 0.05,
                spaceShift = 0.15,
                objectSetShift = 0.35,
                socialContextShift = 0.0,
                temporalGap = 0.0,
                predictionError = 0.2
            )
        )

        assertEquals(BoundaryDecision.CONTINUE, score.decision)
        assertTrue(score.total < SessionBoundaryPolicy.SESSION_SPLIT_THRESHOLD)
    }

    @Test
    fun sustainedGoalAndContextChangeProposesSplit() {
        val score = SessionBoundaryPolicy.score(
            BoundarySignals(
                goalShift = 0.95,
                spaceShift = 0.85,
                objectSetShift = 0.8,
                socialContextShift = 0.4,
                temporalGap = 0.2,
                predictionError = 0.9
            )
        )

        assertEquals(BoundaryDecision.CANDIDATE_SPLIT, score.decision)
        assertTrue(score.total >= SessionBoundaryPolicy.SESSION_SPLIT_THRESHOLD)
    }
}
