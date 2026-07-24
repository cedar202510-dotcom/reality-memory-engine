package com.realitymemory.glasses.runtime

enum class SessionState {
    ARMED,
    DISCLOSURE,
    ACTIVE,
    PAUSED,
    BLOCKED,
    ENDED,
}

enum class CaptureModality {
    IMAGE,
    VIDEO,
    AUDIO,
    SENSOR,
}

data class MotionTrigger(
    val occurredAtEpochMs: Long,
    val monotonicStartNs: Long,
    val monotonicEndNs: Long,
    val durationMs: Long,
    val peakGyroRadS: Double,
    val integratedRotationDeg: Double,
    val maxLinearAcceleration: Double,
    val intensity: String,
)

data class CaptureWindowContext(
    val captureSessionId: String,
    val captureIntentId: String,
    val captureWindowId: String,
    val signalKind: String,
    val startedAtEpochMs: Long,
    val monotonicStartNs: Long,
    val requestedModalities: Set<CaptureModality>,
)
