import Foundation

enum ProbeRingMountPosition: String, Codable, CaseIterable {
    case fingerWorn = "FINGER_WORN"
    case glassesMounted = "GLASSES_MOUNTED"

    var displayName: String {
        switch self {
        case .fingerWorn:
            "手指佩戴"
        case .glassesMounted:
            "固定在眼镜"
        }
    }
}

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

    var relativeChangeThreshold: Double {
        switch self {
        case .high:
            1.8
        case .medium:
            2.2
        case .low:
            2.8
        }
    }

    var strongRelativeChangeThreshold: Double {
        switch self {
        case .high:
            5.0
        case .medium:
            6.0
        case .low:
            8.0
        }
    }

    var accelerationNoiseFloor: Double {
        switch self {
        case .high:
            500
        case .medium:
            600
        case .low:
            800
        }
    }

    var gyroscopeNoiseFloor: Double {
        switch self {
        case .high:
            1_700
        case .medium:
            2_000
        case .low:
            2_500
        }
    }

    var minimumAccelerationForTrigger: Double {
        switch self {
        case .high:
            2_400
        case .medium:
            2_800
        case .low:
            3_500
        }
    }

    var minimumGyroscopeForTrigger: Double {
        switch self {
        case .high:
            3_500
        case .medium:
            4_000
        case .low:
            5_000
        }
    }

    var headRotationExcursionThresholdDegrees: Double {
        switch self {
        case .high:
            12
        case .medium:
            16
        case .low:
            24
        }
    }

    var headGravityTiltThresholdDegrees: Double {
        switch self {
        case .high:
            8
        case .medium:
            12
        case .low:
            18
        }
    }

    var headMovementStartDPS: Double {
        switch self {
        case .high:
            12
        case .medium:
            16
        case .low:
            22
        }
    }

    var headSettleDPS: Double {
        switch self {
        case .high:
            20
        case .medium:
            18
        case .low:
            16
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
    let accelerationBaseline: Double
    let gyroscopeBaseline: Double
    let relativeChangeScore: Double
    let isStrongChange: Bool
    let mountPosition: ProbeRingMountPosition
    let rotationExcursionDegrees: Double?
    let gravityTiltDegrees: Double?
    let endingGyroscopeDPS: Double?
    let sustainedMotion: Bool?
}

struct RingLiveMetrics {
    let accelerationMagnitude: Double
    let gyroscopeMagnitude: Double
    let accelerationDelta: Double
    let accelerationBaseline: Double
    let gyroscopeBaseline: Double
    let accelerationDynamicThreshold: Double
    let gyroscopeDynamicThreshold: Double
    let relativeChangeScore: Double
    let contextState: String
    let mountPosition: ProbeRingMountPosition
    let rotationExcursionDegrees: Double?
    let gravityTiltDegrees: Double?
    let endingGyroscopeDPS: Double?
}

struct RingRapidMovementDetector {
    private struct BatchFeature {
        let accelerationP90: Double
        let gyroscopeP90: Double
    }

    private struct HeadFeature {
        let gyroXRaw: Double
        let gyroYRaw: Double
        let gyroZRaw: Double
        let gravityXRaw: Double
        let gravityYRaw: Double
        let gravityZRaw: Double
    }

    private enum HeadState {
        case calibrating
        case stable
        case moving
        case settling
    }

    static let ruleVersion = "glasses-head-transition.v1"
    static let legacyRuleVersion = "relative-motion-baseline.v2"
    static let baselineWindowBatchCount = 20
    static let minimumCalibrationBatchCount = 8
    static let triggerCooldownSeconds: TimeInterval = 20
    static let strongTriggerCooldownSeconds: TimeInterval = 6
    static let stableChangeRatio = 1.35
    static let headSettleDurationSeconds: TimeInterval = 0.5
    static let headTriggerCooldownSeconds: TimeInterval = 3
    static let sustainedMotionAccelerationP95G = 0.12

    private var previousSample: RingIMUSample?
    private var lastTriggerAt: Date?
    private var isArmed = true
    private var stableBatchCount = 0
    private var candidateBatchCount = 0
    private var recentFeatures: [BatchFeature] = []
    private var headState: HeadState = .calibrating
    private var recentHeadFeatures: [HeadFeature] = []
    private var headPreviousTimestamp: UInt32?
    private var headMovementStartedAt: Date?
    private var headSettledDuration: TimeInterval = 0
    private var headLastTriggerAt: Date?
    private var headIntegratedX = 0.0
    private var headIntegratedY = 0.0
    private var headIntegratedZ = 0.0
    private var headMinX = 0.0
    private var headMaxX = 0.0
    private var headMinY = 0.0
    private var headMaxY = 0.0
    private var headMinZ = 0.0
    private var headMaxZ = 0.0
    private var headStartGravity = (x: 0.0, y: 0.0, z: 0.0)
    private var headMaximumGravityTilt = 0.0
    private var headPeakAccelerationDeltaRaw = 0.0
    private var headPeakGyroscopeRaw = 0.0
    private var headTransitionSampleCount = 0
    private var headSustainedMotion = false
    private var headSustainedMotionBatchCount = 0

    mutating func reset() {
        previousSample = nil
        lastTriggerAt = nil
        isArmed = true
        stableBatchCount = 0
        candidateBatchCount = 0
        recentFeatures.removeAll(keepingCapacity: true)
        headState = .calibrating
        recentHeadFeatures.removeAll(keepingCapacity: true)
        headPreviousTimestamp = nil
        headMovementStartedAt = nil
        headSettledDuration = 0
        headLastTriggerAt = nil
        resetHeadTransition()
    }

    mutating func process(
        batch: RingIMUBatch,
        receivedAt: Date,
        sensitivity: ProbeRingSensitivity,
        configuration: RingSensorConfiguration?,
        mountPosition: ProbeRingMountPosition
    ) -> (metrics: RingLiveMetrics?, detection: RingRapidMovementDetection?) {
        switch mountPosition {
        case .fingerWorn:
            processFinger(
                batch: batch,
                receivedAt: receivedAt,
                sensitivity: sensitivity
            )
        case .glassesMounted:
            processGlasses(
                batch: batch,
                receivedAt: receivedAt,
                sensitivity: sensitivity,
                configuration: configuration
            )
        }
    }

    private mutating func processFinger(
        batch: RingIMUBatch,
        receivedAt: Date,
        sensitivity: ProbeRingSensitivity
    ) -> (metrics: RingLiveMetrics?, detection: RingRapidMovementDetection?) {
        guard !batch.samples.isEmpty else {
            return (nil, nil)
        }

        var accelerationDeltas: [Double] = []
        var gyroscopeMagnitudes: [Double] = []
        var latestAccelerationMagnitude = 0.0

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

            accelerationDeltas.append(accelerationDelta)
            gyroscopeMagnitudes.append(gyroscopeMagnitude)
            latestAccelerationMagnitude = accelerationMagnitude
            self.previousSample = sample
        }

        let accelerationP90 = percentile(accelerationDeltas, fraction: 0.9)
        let gyroscopeP90 = percentile(gyroscopeMagnitudes, fraction: 0.9)
        let accelerationBaseline = max(
            sensitivity.accelerationNoiseFloor,
            median(recentFeatures.map(\.accelerationP90))
        )
        let gyroscopeBaseline = max(
            sensitivity.gyroscopeNoiseFloor,
            median(recentFeatures.map(\.gyroscopeP90))
        )
        let relativeChangeScore = max(
            accelerationP90 / accelerationBaseline,
            gyroscopeP90 / gyroscopeBaseline
        )
        let isCalibrating = recentFeatures.count < Self.minimumCalibrationBatchCount
        let isStable = relativeChangeScore < Self.stableChangeRatio
        let contextState: String
        if isCalibrating {
            contextState = "CALIBRATING"
        } else if isStable {
            contextState = "RELATIVELY_STABLE"
        } else {
            contextState = "MOTION_CHANGING"
        }
        let latestMetrics = RingLiveMetrics(
            accelerationMagnitude: latestAccelerationMagnitude,
            gyroscopeMagnitude: gyroscopeP90,
            accelerationDelta: accelerationP90,
            accelerationBaseline: accelerationBaseline,
            gyroscopeBaseline: gyroscopeBaseline,
            accelerationDynamicThreshold: accelerationBaseline * sensitivity.relativeChangeThreshold,
            gyroscopeDynamicThreshold: gyroscopeBaseline * sensitivity.relativeChangeThreshold,
            relativeChangeScore: relativeChangeScore,
            contextState: contextState,
            mountPosition: .fingerWorn,
            rotationExcursionDegrees: nil,
            gravityTiltDegrees: nil,
            endingGyroscopeDPS: nil
        )

        recentFeatures.append(
            BatchFeature(
                accelerationP90: accelerationP90,
                gyroscopeP90: gyroscopeP90
            )
        )
        if recentFeatures.count > Self.baselineWindowBatchCount {
            recentFeatures.removeFirst(recentFeatures.count - Self.baselineWindowBatchCount)
        }

        if isStable {
            stableBatchCount += 1
            if stableBatchCount >= 3 {
                isArmed = true
            }
        } else {
            stableBatchCount = 0
        }

        let meetsAbsoluteMinimum =
            accelerationP90 >= sensitivity.minimumAccelerationForTrigger
            || gyroscopeP90 >= sensitivity.minimumGyroscopeForTrigger
        let isRelativeCandidate =
            relativeChangeScore >= sensitivity.relativeChangeThreshold
            && meetsAbsoluteMinimum
        candidateBatchCount = isRelativeCandidate ? candidateBatchCount + 1 : 0
        let normalCooldownPassed = lastTriggerAt.map {
            receivedAt.timeIntervalSince($0) >= Self.triggerCooldownSeconds
        } ?? true
        let strongCooldownPassed = lastTriggerAt.map {
            receivedAt.timeIntervalSince($0) >= Self.strongTriggerCooldownSeconds
        } ?? true
        let isStrongChange =
            relativeChangeScore >= sensitivity.strongRelativeChangeThreshold
        let shouldTrigger =
            !isCalibrating
            && (
                (isArmed
                    && normalCooldownPassed
                    && candidateBatchCount >= 2)
                || (strongCooldownPassed && isStrongChange && meetsAbsoluteMinimum)
            )
        guard shouldTrigger else {
            return (latestMetrics, nil)
        }

        isArmed = false
        stableBatchCount = 0
        candidateBatchCount = 0
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
                peakAccelerationDelta: accelerationP90,
                peakGyroscopeMagnitude: gyroscopeP90,
                sensitivity: sensitivity,
                accelerationBaseline: accelerationBaseline,
                gyroscopeBaseline: gyroscopeBaseline,
                relativeChangeScore: relativeChangeScore,
                isStrongChange: isStrongChange,
                mountPosition: .fingerWorn,
                rotationExcursionDegrees: nil,
                gravityTiltDegrees: nil,
                endingGyroscopeDPS: nil,
                sustainedMotion: nil
            )
        )
    }

    private mutating func processGlasses(
        batch: RingIMUBatch,
        receivedAt: Date,
        sensitivity: ProbeRingSensitivity,
        configuration: RingSensorConfiguration?
    ) -> (metrics: RingLiveMetrics?, detection: RingRapidMovementDetection?) {
        guard !batch.samples.isEmpty else {
            return (nil, nil)
        }

        let accelerationScale =
            Double(configuration?.accelRangeG ?? 16) / 32_768
        let gyroscopeScale =
            Double(configuration?.gyroRangeDPS ?? 2_000) / 32_768
        var accelerationDeltas: [Double] = []
        var gyroscopeMagnitudesRaw: [Double] = []
        var latestAccelerationMagnitude = 0.0

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
            accelerationDeltas.append(accelerationDelta)
            gyroscopeMagnitudesRaw.append(gyroscopeMagnitude)
            latestAccelerationMagnitude = accelerationMagnitude
            self.previousSample = sample
        }

        let feature = HeadFeature(
            gyroXRaw: median(batch.samples.map { Double($0.gyroX) }),
            gyroYRaw: median(batch.samples.map { Double($0.gyroY) }),
            gyroZRaw: median(batch.samples.map { Double($0.gyroZ) }),
            gravityXRaw: average(batch.samples.map { Double($0.accelX) }),
            gravityYRaw: average(batch.samples.map { Double($0.accelY) }),
            gravityZRaw: average(batch.samples.map { Double($0.accelZ) })
        )
        let accelerationP90 = percentile(accelerationDeltas, fraction: 0.9)
        let gyroscopeP90Raw = percentile(gyroscopeMagnitudesRaw, fraction: 0.9)
        let gyroBias = (
            x: median(recentHeadFeatures.map(\.gyroXRaw)),
            y: median(recentHeadFeatures.map(\.gyroYRaw)),
            z: median(recentHeadFeatures.map(\.gyroZRaw))
        )
        let baselineGravity = (
            x: average(recentHeadFeatures.map(\.gravityXRaw)),
            y: average(recentHeadFeatures.map(\.gravityYRaw)),
            z: average(recentHeadFeatures.map(\.gravityZRaw))
        )
        let correctedGyroscopeDPS = batch.samples.map { sample in
            magnitude(
                x: (Double(sample.gyroX) - gyroBias.x) * gyroscopeScale,
                y: (Double(sample.gyroY) - gyroBias.y) * gyroscopeScale,
                z: (Double(sample.gyroZ) - gyroBias.z) * gyroscopeScale
            )
        }
        let correctedGyroscopeP90DPS = percentile(
            correctedGyroscopeDPS,
            fraction: 0.9
        )
        let gravityTiltFromBaseline = angleDegrees(
            left: baselineGravity,
            right: (
                x: feature.gravityXRaw,
                y: feature.gravityYRaw,
                z: feature.gravityZRaw
            )
        )
        let isCalibrating =
            recentHeadFeatures.count < Self.minimumCalibrationBatchCount
        if isCalibrating {
            appendHeadFeature(feature)
            headState = .calibrating
            return (
                headMetrics(
                    latestAccelerationMagnitude: latestAccelerationMagnitude,
                    accelerationP90: accelerationP90,
                    gyroscopeP90Raw: gyroscopeP90Raw,
                    correctedGyroscopeP90DPS: correctedGyroscopeP90DPS,
                    gravityTiltDegrees: gravityTiltFromBaseline,
                    sensitivity: sensitivity,
                    accelerationScale: accelerationScale,
                    gyroscopeScale: gyroscopeScale,
                    contextState: "CALIBRATING"
                ),
                nil
            )
        }

        if headState == .calibrating {
            headState = .stable
        }
        let startByRotation =
            correctedGyroscopeP90DPS >= sensitivity.headMovementStartDPS
        let startByGravity =
            gravityTiltFromBaseline
                >= sensitivity.headGravityTiltThresholdDegrees * 0.5
        if headState == .stable, startByRotation || startByGravity {
            beginHeadTransition(
                receivedAt: receivedAt,
                gravity:
                    magnitude(
                        x: baselineGravity.x,
                        y: baselineGravity.y,
                        z: baselineGravity.z
                    ) > 0
                        ? baselineGravity
                        : (
                            x: feature.gravityXRaw,
                            y: feature.gravityYRaw,
                            z: feature.gravityZRaw
                        )
            )
            headState = .moving
        }

        guard headState == .moving || headState == .settling else {
            appendHeadFeature(feature)
            return (
                headMetrics(
                    latestAccelerationMagnitude: latestAccelerationMagnitude,
                    accelerationP90: accelerationP90,
                    gyroscopeP90Raw: gyroscopeP90Raw,
                    correctedGyroscopeP90DPS: correctedGyroscopeP90DPS,
                    gravityTiltDegrees: gravityTiltFromBaseline,
                    sensitivity: sensitivity,
                    accelerationScale: accelerationScale,
                    gyroscopeScale: gyroscopeScale,
                    contextState: "HEAD_STABLE"
                ),
                nil
            )
        }

        integrateHeadRotation(
            samples: batch.samples,
            gyroBias: gyroBias,
            gyroscopeScale: gyroscopeScale
        )
        headTransitionSampleCount += batch.samples.count
        headPeakAccelerationDeltaRaw = max(
            headPeakAccelerationDeltaRaw,
            accelerationP90
        )
        headPeakGyroscopeRaw = max(
            headPeakGyroscopeRaw,
            gyroscopeP90Raw
        )
        headMaximumGravityTilt = max(
            headMaximumGravityTilt,
            angleDegrees(
                left: headStartGravity,
                right: (
                    x: feature.gravityXRaw,
                    y: feature.gravityYRaw,
                    z: feature.gravityZRaw
                )
            )
        )
        if accelerationP90 * accelerationScale
            >= Self.sustainedMotionAccelerationP95G
        {
            headSustainedMotionBatchCount += 1
            if headSustainedMotionBatchCount >= 2 {
                headSustainedMotion = true
            }
        } else {
            headSustainedMotionBatchCount = max(
                0,
                headSustainedMotionBatchCount - 1
            )
        }

        let rotationExcursion = currentHeadRotationExcursion()
        let isSettled =
            correctedGyroscopeP90DPS <= sensitivity.headSettleDPS
        if isSettled {
            headState = .settling
            headSettledDuration += batchDurationSeconds(batch)
        } else {
            headState = .moving
            headSettledDuration = 0
        }
        let contextState: String
        if headSustainedMotion && headState == .moving {
            contextState = "SUSTAINED_MOTION"
        } else if headState == .settling {
            contextState = "HEAD_SETTLING"
        } else {
            contextState = "HEAD_TURNING"
        }
        let metrics = headMetrics(
            latestAccelerationMagnitude: latestAccelerationMagnitude,
            accelerationP90: accelerationP90,
            gyroscopeP90Raw: gyroscopeP90Raw,
            correctedGyroscopeP90DPS: correctedGyroscopeP90DPS,
            gravityTiltDegrees: headMaximumGravityTilt,
            sensitivity: sensitivity,
            accelerationScale: accelerationScale,
            gyroscopeScale: gyroscopeScale,
            contextState: contextState,
            rotationExcursionDegrees: rotationExcursion
        )
        guard headSettledDuration >= Self.headSettleDurationSeconds else {
            return (metrics, nil)
        }

        let movementStartedAt = headMovementStartedAt ?? receivedAt
        let sampleCount = headTransitionSampleCount
        let peakAccelerationDelta = headPeakAccelerationDeltaRaw
        let peakGyroscopeMagnitude = headPeakGyroscopeRaw
        let maximumGravityTilt = headMaximumGravityTilt
        let sustainedMotion = headSustainedMotion
        let rotationScore =
            rotationExcursion
                / sensitivity.headRotationExcursionThresholdDegrees
        let gravityScore =
            maximumGravityTilt
                / sensitivity.headGravityTiltThresholdDegrees
        let informationChangeScore = max(rotationScore, gravityScore)
        let meetsInformationChange =
            rotationExcursion
                >= sensitivity.headRotationExcursionThresholdDegrees
            || maximumGravityTilt
                >= sensitivity.headGravityTiltThresholdDegrees
        let cooldownPassed = headLastTriggerAt.map {
            receivedAt.timeIntervalSince($0)
                >= Self.headTriggerCooldownSeconds
        } ?? true
        let shouldTrigger = meetsInformationChange && cooldownPassed
        if shouldTrigger {
            headLastTriggerAt = receivedAt
        }
        recentHeadFeatures.removeAll(keepingCapacity: true)
        appendHeadFeature(feature)
        resetHeadTransition()
        headState = .calibrating

        guard shouldTrigger else {
            return (
                headMetrics(
                    latestAccelerationMagnitude: latestAccelerationMagnitude,
                    accelerationP90: accelerationP90,
                    gyroscopeP90Raw: gyroscopeP90Raw,
                    correctedGyroscopeP90DPS: correctedGyroscopeP90DPS,
                    gravityTiltDegrees: maximumGravityTilt,
                    sensitivity: sensitivity,
                    accelerationScale: accelerationScale,
                    gyroscopeScale: gyroscopeScale,
                    contextState: "HEAD_STABLE",
                    rotationExcursionDegrees: rotationExcursion
                ),
                nil
            )
        }

        return (
            metrics,
            RingRapidMovementDetection(
                windowStartedAt: movementStartedAt,
                windowEndedAt: receivedAt,
                detectedAt: receivedAt,
                sampleCount: sampleCount,
                peakAccelerationDelta: peakAccelerationDelta,
                peakGyroscopeMagnitude: peakGyroscopeMagnitude,
                sensitivity: sensitivity,
                accelerationBaseline: sensitivity.accelerationNoiseFloor,
                gyroscopeBaseline: sensitivity.gyroscopeNoiseFloor,
                relativeChangeScore: informationChangeScore,
                isStrongChange:
                    sustainedMotion
                    || rotationExcursion >= 60
                    || maximumGravityTilt >= 30,
                mountPosition: .glassesMounted,
                rotationExcursionDegrees: rotationExcursion,
                gravityTiltDegrees: maximumGravityTilt,
                endingGyroscopeDPS: correctedGyroscopeP90DPS,
                sustainedMotion: sustainedMotion
            )
        )
    }

    private mutating func beginHeadTransition(
        receivedAt: Date,
        gravity: (x: Double, y: Double, z: Double)
    ) {
        resetHeadTransition()
        headMovementStartedAt = receivedAt
        headStartGravity = gravity
    }

    private mutating func resetHeadTransition() {
        headMovementStartedAt = nil
        headSettledDuration = 0
        headIntegratedX = 0
        headIntegratedY = 0
        headIntegratedZ = 0
        headMinX = 0
        headMaxX = 0
        headMinY = 0
        headMaxY = 0
        headMinZ = 0
        headMaxZ = 0
        headMaximumGravityTilt = 0
        headPeakAccelerationDeltaRaw = 0
        headPeakGyroscopeRaw = 0
        headTransitionSampleCount = 0
        headSustainedMotion = false
        headSustainedMotionBatchCount = 0
    }

    private mutating func integrateHeadRotation(
        samples: [RingIMUSample],
        gyroBias: (x: Double, y: Double, z: Double),
        gyroscopeScale: Double
    ) {
        for sample in samples {
            let timestamp = sample.timestampMilliseconds
            let deltaMilliseconds: UInt32
            if let headPreviousTimestamp {
                deltaMilliseconds = timestamp &- headPreviousTimestamp
            } else {
                deltaMilliseconds = 10
            }
            headPreviousTimestamp = timestamp
            let dt = min(0.05, max(0.001, Double(deltaMilliseconds) / 1_000))
            headIntegratedX +=
                (Double(sample.gyroX) - gyroBias.x) * gyroscopeScale * dt
            headIntegratedY +=
                (Double(sample.gyroY) - gyroBias.y) * gyroscopeScale * dt
            headIntegratedZ +=
                (Double(sample.gyroZ) - gyroBias.z) * gyroscopeScale * dt
            headMinX = min(headMinX, headIntegratedX)
            headMaxX = max(headMaxX, headIntegratedX)
            headMinY = min(headMinY, headIntegratedY)
            headMaxY = max(headMaxY, headIntegratedY)
            headMinZ = min(headMinZ, headIntegratedZ)
            headMaxZ = max(headMaxZ, headIntegratedZ)
        }
    }

    private func currentHeadRotationExcursion() -> Double {
        magnitude(
            x: headMaxX - headMinX,
            y: headMaxY - headMinY,
            z: headMaxZ - headMinZ
        )
    }

    private mutating func appendHeadFeature(_ feature: HeadFeature) {
        recentHeadFeatures.append(feature)
        if recentHeadFeatures.count > Self.baselineWindowBatchCount {
            recentHeadFeatures.removeFirst(
                recentHeadFeatures.count - Self.baselineWindowBatchCount
            )
        }
    }

    private func headMetrics(
        latestAccelerationMagnitude: Double,
        accelerationP90: Double,
        gyroscopeP90Raw: Double,
        correctedGyroscopeP90DPS: Double,
        gravityTiltDegrees: Double,
        sensitivity: ProbeRingSensitivity,
        accelerationScale: Double,
        gyroscopeScale: Double,
        contextState: String,
        rotationExcursionDegrees: Double = 0
    ) -> RingLiveMetrics {
        let informationChangeScore = max(
            rotationExcursionDegrees
                / sensitivity.headRotationExcursionThresholdDegrees,
            gravityTiltDegrees
                / sensitivity.headGravityTiltThresholdDegrees
        )
        return RingLiveMetrics(
            accelerationMagnitude: latestAccelerationMagnitude,
            gyroscopeMagnitude: gyroscopeP90Raw,
            accelerationDelta: accelerationP90,
            accelerationBaseline: sensitivity.accelerationNoiseFloor,
            gyroscopeBaseline: sensitivity.gyroscopeNoiseFloor,
            accelerationDynamicThreshold:
                Self.sustainedMotionAccelerationP95G
                    / max(accelerationScale, 0.000_001),
            gyroscopeDynamicThreshold:
                sensitivity.headMovementStartDPS
                    / max(gyroscopeScale, 0.000_001),
            relativeChangeScore: informationChangeScore,
            contextState: contextState,
            mountPosition: .glassesMounted,
            rotationExcursionDegrees: rotationExcursionDegrees,
            gravityTiltDegrees: gravityTiltDegrees,
            endingGyroscopeDPS: correctedGyroscopeP90DPS
        )
    }

    private func batchDurationSeconds(_ batch: RingIMUBatch) -> TimeInterval {
        guard
            let first = batch.samples.first?.timestampMilliseconds,
            let last = batch.samples.last?.timestampMilliseconds
        else {
            return 0
        }
        let milliseconds = last &- first
        return max(0.01, min(1, Double(milliseconds) / 1_000))
    }

    private func angleDegrees(
        left: (x: Double, y: Double, z: Double),
        right: (x: Double, y: Double, z: Double)
    ) -> Double {
        let leftMagnitude = magnitude(x: left.x, y: left.y, z: left.z)
        let rightMagnitude = magnitude(x: right.x, y: right.y, z: right.z)
        guard leftMagnitude > 0, rightMagnitude > 0 else {
            return 0
        }
        let cosine = min(
            1,
            max(
                -1,
                (left.x * right.x + left.y * right.y + left.z * right.z)
                    / (leftMagnitude * rightMagnitude)
            )
        )
        return acos(cosine) * 180 / .pi
    }

    private func average(_ values: [Double]) -> Double {
        guard !values.isEmpty else {
            return 0
        }
        return values.reduce(0, +) / Double(values.count)
    }

    private func median(_ values: [Double]) -> Double {
        percentile(values, fraction: 0.5)
    }

    private func percentile(_ values: [Double], fraction: Double) -> Double {
        guard !values.isEmpty else {
            return 0
        }
        let sorted = values.sorted()
        let index = min(
            sorted.count - 1,
            max(0, Int((Double(sorted.count - 1) * fraction).rounded()))
        )
        return sorted[index]
    }

    private func magnitude(x: Double, y: Double, z: Double) -> Double {
        sqrt(x * x + y * y + z * z)
    }
}
