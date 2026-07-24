package com.realitymemory.glasses.sensor

import com.realitymemory.glasses.runtime.MotionTrigger
import kotlin.math.PI
import kotlin.math.max
import kotlin.math.sqrt

data class MotionSample(
    val wallClockEpochMs: Long,
    val monotonicNs: Long,
    val ax: Float,
    val ay: Float,
    val az: Float,
    val gx: Float,
    val gy: Float,
    val gz: Float,
    val accuracy: Int,
) {
    val gyroMagnitude: Double
        get() = sqrt((gx * gx + gy * gy + gz * gz).toDouble())

    val linearAccelerationMagnitude: Double
        get() = kotlin.math.abs(sqrt((ax * ax + ay * ay + az * az).toDouble()) - EARTH_GRAVITY)

    companion object {
        private const val EARTH_GRAVITY = 9.80665
    }
}

class MotionTriggerEngine {
    private enum class Phase { LEARNING, STABLE, MOVING, COOLDOWN }

    private var phase = Phase.LEARNING
    private var stableSinceNs = 0L
    private var movementStartedNs = 0L
    private var lastSampleNs = 0L
    private var belowEndThresholdSinceNs = 0L
    private var cooldownUntilNs = 0L
    private var baselineMean = 0.0
    private var baselineVariance = 0.0
    private var baselineSamples = 0
    private var peakGyro = 0.0
    private var integratedRotationRad = 0.0
    private var maxLinearAcceleration = 0.0

    fun accept(sample: MotionSample): MotionTrigger? {
        val gyro = sample.gyroMagnitude
        val linearAcceleration = sample.linearAccelerationMagnitude
        val now = sample.monotonicNs
        val deltaSeconds = if (lastSampleNs == 0L) 0.0 else {
            ((now - lastSampleNs).coerceAtLeast(0L) / 1_000_000_000.0).coerceAtMost(0.2)
        }
        lastSampleNs = now

        when (phase) {
            Phase.LEARNING -> {
                updateBaseline(gyro)
                if (baselineSamples >= MIN_BASELINE_SAMPLES && isCalm(gyro, linearAcceleration)) {
                    stableSinceNs = now
                    phase = Phase.STABLE
                }
            }

            Phase.STABLE -> {
                if (isCalm(gyro, linearAcceleration)) {
                    if (stableSinceNs == 0L) stableSinceNs = now
                    updateBaseline(gyro)
                } else if (now - stableSinceNs >= REQUIRED_STABLE_NS && gyro >= startThreshold()) {
                    beginMovement(sample)
                } else {
                    stableSinceNs = 0L
                }
            }

            Phase.MOVING -> {
                peakGyro = max(peakGyro, gyro)
                maxLinearAcceleration = max(maxLinearAcceleration, linearAcceleration)
                integratedRotationRad += gyro * deltaSeconds
                if (gyro < END_GYRO_THRESHOLD) {
                    if (belowEndThresholdSinceNs == 0L) belowEndThresholdSinceNs = now
                } else {
                    belowEndThresholdSinceNs = 0L
                }

                val durationNs = now - movementStartedNs
                val settled = belowEndThresholdSinceNs != 0L &&
                    now - belowEndThresholdSinceNs >= SETTLE_AFTER_MOTION_NS
                if ((durationNs >= MIN_MOVEMENT_NS && settled) || durationNs >= MAX_MOVEMENT_NS) {
                    return finishMovement(sample)
                }
            }

            Phase.COOLDOWN -> {
                if (now >= cooldownUntilNs && isCalm(gyro, linearAcceleration)) {
                    stableSinceNs = now
                    phase = Phase.STABLE
                    updateBaseline(gyro)
                }
            }
        }
        return null
    }

    fun reset() {
        phase = Phase.LEARNING
        stableSinceNs = 0L
        movementStartedNs = 0L
        lastSampleNs = 0L
        belowEndThresholdSinceNs = 0L
        cooldownUntilNs = 0L
        baselineMean = 0.0
        baselineVariance = 0.0
        baselineSamples = 0
        peakGyro = 0.0
        integratedRotationRad = 0.0
        maxLinearAcceleration = 0.0
    }

    fun currentStartThreshold(): Double = startThreshold()

    private fun beginMovement(sample: MotionSample) {
        phase = Phase.MOVING
        movementStartedNs = sample.monotonicNs
        belowEndThresholdSinceNs = 0L
        peakGyro = sample.gyroMagnitude
        integratedRotationRad = 0.0
        maxLinearAcceleration = sample.linearAccelerationMagnitude
    }

    private fun finishMovement(sample: MotionSample): MotionTrigger? {
        val durationMs = (sample.monotonicNs - movementStartedNs) / 1_000_000L
        val rotationDeg = integratedRotationRad * 180.0 / PI
        phase = Phase.COOLDOWN
        cooldownUntilNs = sample.monotonicNs + COOLDOWN_NS
        stableSinceNs = 0L

        if (rotationDeg < MIN_ROTATION_DEG && peakGyro < STRONG_GYRO_THRESHOLD) return null
        val intensity = when {
            peakGyro >= STRONG_GYRO_THRESHOLD || rotationDeg >= 35.0 -> "STRONG"
            peakGyro >= 1.0 || rotationDeg >= 18.0 -> "MEDIUM"
            else -> "LOW"
        }
        return MotionTrigger(
            occurredAtEpochMs = sample.wallClockEpochMs,
            monotonicStartNs = movementStartedNs,
            monotonicEndNs = sample.monotonicNs,
            durationMs = durationMs,
            peakGyroRadS = peakGyro,
            integratedRotationDeg = rotationDeg,
            maxLinearAcceleration = maxLinearAcceleration,
            intensity = intensity,
        )
    }

    private fun updateBaseline(value: Double) {
        baselineSamples += 1
        val alpha = if (baselineSamples < 30) 1.0 / baselineSamples else 0.04
        val difference = value - baselineMean
        baselineMean += alpha * difference
        baselineVariance = (1 - alpha) * (baselineVariance + alpha * difference * difference)
    }

    private fun startThreshold(): Double {
        val standardDeviation = sqrt(baselineVariance.coerceAtLeast(0.0))
        return max(MIN_START_GYRO_THRESHOLD, baselineMean + BASELINE_SIGMA_MULTIPLIER * standardDeviation)
    }

    private fun isCalm(gyro: Double, linearAcceleration: Double): Boolean =
        gyro < CALM_GYRO_THRESHOLD && linearAcceleration < CALM_LINEAR_ACCELERATION

    companion object {
        private const val MIN_BASELINE_SAMPLES = 25
        private const val REQUIRED_STABLE_NS = 1_500_000_000L
        private const val MIN_MOVEMENT_NS = 250_000_000L
        private const val MAX_MOVEMENT_NS = 2_500_000_000L
        private const val SETTLE_AFTER_MOTION_NS = 350_000_000L
        private const val COOLDOWN_NS = 8_000_000_000L
        private const val CALM_GYRO_THRESHOLD = 0.28
        private const val CALM_LINEAR_ACCELERATION = 1.8
        private const val MIN_START_GYRO_THRESHOLD = 0.55
        private const val END_GYRO_THRESHOLD = 0.25
        private const val STRONG_GYRO_THRESHOLD = 1.8
        private const val MIN_ROTATION_DEG = 8.0
        private const val BASELINE_SIGMA_MULTIPLIER = 4.0
    }
}
