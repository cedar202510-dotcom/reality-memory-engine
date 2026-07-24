package com.realitymemory.glasses.sensor

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MotionTriggerEngineTest {
    @Test
    fun stableNoiseDoesNotTrigger() {
        val engine = MotionTriggerEngine()
        var timeNs = 0L
        repeat(400) {
            timeNs += STEP_NS
            val smallNoise = if (it % 2 == 0) 0.03f else -0.03f
            val trigger = engine.accept(sample(timeNs, gx = smallNoise))
            assertNull(trigger)
        }
    }

    @Test
    fun headTurnAfterStablePeriodTriggersOnce() {
        val engine = MotionTriggerEngine()
        var timeNs = 0L
        var trigger: com.realitymemory.glasses.runtime.MotionTrigger? = null

        repeat(130) {
            timeNs += STEP_NS
            trigger = engine.accept(sample(timeNs, gx = 0.03f)) ?: trigger
        }
        repeat(15) {
            timeNs += STEP_NS
            trigger = engine.accept(sample(timeNs, gy = 1.2f)) ?: trigger
        }
        repeat(30) {
            timeNs += STEP_NS
            trigger = engine.accept(sample(timeNs, gx = 0.04f)) ?: trigger
        }

        assertNotNull(trigger)
        assertEquals("MEDIUM", trigger!!.intensity)
        assertTrue(trigger!!.integratedRotationDeg >= 18.0)
        assertTrue(trigger!!.durationMs in 500..1_600)
    }

    @Test
    fun cooldownSuppressesImmediateSecondTurn() {
        val engine = MotionTriggerEngine()
        var timeNs = 0L
        repeat(130) {
            timeNs += STEP_NS
            engine.accept(sample(timeNs, gx = 0.03f))
        }

        var triggerCount = 0
        repeat(35) {
            timeNs += STEP_NS
            if (engine.accept(sample(timeNs, gy = 1.3f)) != null) triggerCount += 1
        }
        repeat(30) {
            timeNs += STEP_NS
            if (engine.accept(sample(timeNs, gx = 0.03f)) != null) triggerCount += 1
        }
        repeat(35) {
            timeNs += STEP_NS
            if (engine.accept(sample(timeNs, gz = 1.4f)) != null) triggerCount += 1
        }
        repeat(30) {
            timeNs += STEP_NS
            if (engine.accept(sample(timeNs, gx = 0.03f)) != null) triggerCount += 1
        }

        assertEquals(1, triggerCount)
    }

    private fun sample(
        monotonicNs: Long,
        gx: Float = 0f,
        gy: Float = 0f,
        gz: Float = 0f,
    ) = MotionSample(
        wallClockEpochMs = monotonicNs / 1_000_000L,
        monotonicNs = monotonicNs,
        ax = 0f,
        ay = 0f,
        az = 9.80665f,
        gx = gx,
        gy = gy,
        gz = gz,
        accuracy = 3,
    )

    companion object {
        private const val STEP_NS = 20_000_000L
    }
}
