import Foundation

enum ProbeRingSensitivity: String, Codable, CaseIterable, Identifiable {
    case high
    case medium
    case low

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .high:
            "高"
        case .medium:
            "中"
        case .low:
            "低"
        }
    }

    var accelerationDeltaThreshold: Double {
        switch self {
        case .high:
            2_800
        case .medium:
            5_000
        case .low:
            8_000
        }
    }

    var gyroscopeMagnitudeThreshold: Double {
        switch self {
        case .high:
            5_000
        case .medium:
            9_000
        case .low:
            14_000
        }
    }
}

struct RingRapidMovementDetection {
    let windowStartedAt: Date
    let windowEndedAt: Date
    let detectedAt: Date
    let sampleCount: Int
    let peakAccelerationDelta: Double
    let peakGyroscopeMagnitude: Double
    let sensitivity: ProbeRingSensitivity
}

struct RingLiveMetrics {
    let accelerationMagnitude: Double
    let gyroscopeMagnitude: Double
    let accelerationDelta: Double
}

struct RingRapidMovementDetector {
    static let ruleVersion = "rapid-movement.raw-threshold.v1"
    static let triggerCooldownSeconds: TimeInterval = 8

    private var previousSample: RingIMUSample?
    private var lastTriggerAt: Date?
    private var isArmed = true
    private var quietSampleCount = 0

    mutating func reset() {
        previousSample = nil
        lastTriggerAt = nil
        isArmed = true
        quietSampleCount = 0
    }

    mutating func process(
        batch: RingIMUBatch,
        receivedAt: Date,
        sensitivity: ProbeRingSensitivity
    ) -> (metrics: RingLiveMetrics?, detection: RingRapidMovementDetection?) {
        guard !batch.samples.isEmpty else {
            return (nil, nil)
        }

        var peakAccelerationDelta = 0.0
        var peakGyroscopeMagnitude = 0.0
        var latestMetrics: RingLiveMetrics?

        for sample in batch.samples {
            let accelerationMagnitude = magnitude(
                x: Double(sample.accelX),
                y: Double(sample.accelY),
                z: Double(sample.accelZ)
            )
            let gyroscopeMagnitude = magnitude(
                x: Double(sample.gyroX),
                y: Double(sample.gyroY),
                z: Double(sample.gyroZ)
            )
            let accelerationDelta: Double
            if let previousSample {
                accelerationDelta = magnitude(
                    x: Double(sample.accelX) - Double(previousSample.accelX),
                    y: Double(sample.accelY) - Double(previousSample.accelY),
                    z: Double(sample.accelZ) - Double(previousSample.accelZ)
                )
            } else {
                accelerationDelta = 0
            }

            peakAccelerationDelta = max(peakAccelerationDelta, accelerationDelta)
            peakGyroscopeMagnitude = max(peakGyroscopeMagnitude, gyroscopeMagnitude)
            latestMetrics = RingLiveMetrics(
                accelerationMagnitude: accelerationMagnitude,
                gyroscopeMagnitude: gyroscopeMagnitude,
                accelerationDelta: accelerationDelta
            )
            self.previousSample = sample
        }

        let crossedThreshold =
            peakAccelerationDelta >= sensitivity.accelerationDeltaThreshold
            || peakGyroscopeMagnitude >= sensitivity.gyroscopeMagnitudeThreshold
        let isQuiet =
            peakAccelerationDelta < sensitivity.accelerationDeltaThreshold * 0.45
            && peakGyroscopeMagnitude < sensitivity.gyroscopeMagnitudeThreshold * 0.45

        if isQuiet {
            quietSampleCount += batch.samples.count
            if quietSampleCount >= 5 {
                isArmed = true
            }
        } else {
            quietSampleCount = 0
        }

        let cooldownPassed = lastTriggerAt.map {
            receivedAt.timeIntervalSince($0) >= Self.triggerCooldownSeconds
        } ?? true
        guard isArmed, cooldownPassed, crossedThreshold else {
            return (latestMetrics, nil)
        }

        isArmed = false
        quietSampleCount = 0
        lastTriggerAt = receivedAt
        let firstTimestamp = batch.samples.first?.timestampMilliseconds ?? 0
        let lastTimestamp = batch.samples.last?.timestampMilliseconds ?? firstTimestamp
        let durationMilliseconds = lastTimestamp >= firstTimestamp
            ? TimeInterval(lastTimestamp - firstTimestamp)
            : 0

        return (
            latestMetrics,
            RingRapidMovementDetection(
                windowStartedAt: receivedAt.addingTimeInterval(-durationMilliseconds / 1_000),
                windowEndedAt: receivedAt,
                detectedAt: receivedAt,
                sampleCount: batch.samples.count,
                peakAccelerationDelta: peakAccelerationDelta,
                peakGyroscopeMagnitude: peakGyroscopeMagnitude,
                sensitivity: sensitivity
            )
        )
    }

    private func magnitude(x: Double, y: Double, z: Double) -> Double {
        sqrt(x * x + y * y + z * z)
    }
}
