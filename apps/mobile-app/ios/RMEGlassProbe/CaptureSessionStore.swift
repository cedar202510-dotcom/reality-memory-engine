import Foundation

enum ProbeSessionState: String, Codable {
    case idle
    case active
    case paused
    case ended

    var displayName: String {
        switch self {
        case .idle:
            "未开始"
        case .active:
            "采集中"
        case .paused:
            "已暂停"
        case .ended:
            "已结束"
        }
    }
}

enum ProbeCaptureTrigger: String, Codable {
    case manual = "MANUAL"
    case periodic = "PERIODIC"
    case ringMotion = "RING_MOTION"
}

enum ProbeCaptureOutcome: String, Codable {
    case succeeded = "SUCCEEDED"
    case skipped = "SKIPPED"
    case failed = "FAILED"
}

struct ProbeCaptureObservation: Identifiable, Codable {
    let id: UUID
    let sessionID: UUID
    let scheduledAt: Date
    let completedAt: Date
    let trigger: ProbeCaptureTrigger
    let triggerDecisionID: UUID?
    let outcome: ProbeCaptureOutcome
    let reason: String?
    let byteCount: Int?
    let captureLatencyMilliseconds: Int?
    let localMediaReference: String?
    let analysisState: String
    let deviceSummary: String
    let wearingStatus: String
    let applicationState: String
}

struct ProbeAudioObservation: Identifiable, Codable {
    let id: UUID
    let sessionID: UUID
    let trigger: String
    let triggerDecisionID: UUID?
    let startedAt: Date
    let endedAt: Date
    let durationMilliseconds: Int
    let byteCount: Int
    let peakDBFS: Double
    let codec: String
    let channels: UInt32
    let localMediaReference: String?
    let analysisState: String
    let applicationState: String
}

struct ProbeAudioPolicySnapshot: Codable {
    let sessionVADEnabled: Bool
    let streamCodec: String
    let vadThresholdDBFS: Double
    let speechStartFrames: Int
    let silenceEndMilliseconds: Int
    let maxSegmentMilliseconds: Int
    let minSegmentMilliseconds: Int
    let maxPreRollBytes: Int
    let rawAudioPersistedOnlyWhenRetainLocalSamples: Bool
}

struct ProbeRingPolicySnapshot: Codable {
    let mountPosition: ProbeRingMountPosition?
    let sensorCollectionEnabled: Bool
    let rapidMovementTriggerEnabled: Bool
    let triggeredAudioEnabled: Bool
    let sensitivity: ProbeRingSensitivity
    let accelerationDeltaThresholdRaw: Double
    let gyroscopeMagnitudeThresholdRaw: Double
    let triggerCooldownMilliseconds: Int
    let triggeredAudioWindowMilliseconds: Int
    let detectorRuleVersion: String
    let baselineWindowBatchCount: Int?
    let relativeChangeThreshold: Double?
    let strongRelativeChangeThreshold: Double?
    let accelerationNoiseFloorRaw: Double?
    let gyroscopeNoiseFloorRaw: Double?
    let strongTriggerCooldownMilliseconds: Int?
    let minimumAccelerationForTriggerRaw: Double?
    let minimumGyroscopeForTriggerRaw: Double?
    let normalConfirmationBatchCount: Int?
    let headRotationExcursionThresholdDegrees: Double?
    let headGravityTiltThresholdDegrees: Double?
    let headMovementStartDPS: Double?
    let headSettleDPS: Double?
    let headSettleDurationMilliseconds: Int?
}

struct ProbeRingSensorSnapshot: Codable {
    let deviceID: String
    let deviceName: String
    let sampleRateHz: Int
    let accelRangeG: Int
    let gyroRangeDPS: Int
    let mountPosition: ProbeRingMountPosition?
}

struct ProbeRingMotionAssessment: Identifiable, Codable {
    let id: UUID
    let sessionID: UUID
    let windowStartedAt: Date
    let windowEndedAt: Date
    let detectedAt: Date
    let classification: String
    let displayLabel: String
    let sampleCount: Int
    let peakAccelerationDeltaRaw: Double
    let peakGyroscopeMagnitudeRaw: Double
    let detectorRuleVersion: String
    let sensitivity: ProbeRingSensitivity
    let captureRequested: Bool
    let requestedModalities: [String]
    let suppressionReason: String?
    let motionIntensityRatio: Double?
    let captureTier: String?
    let requestedImageCount: Int?
    let capturePolicyVersion: String?
    let accelerationBaselineRaw: Double?
    let gyroscopeBaselineRaw: Double?
    let relativeChangeScore: Double?
    let isStrongChange: Bool?
    let acceleratedCaptureIntervalMilliseconds: Int?
    let acceleratedCaptureWindowMilliseconds: Int?
    let mountPosition: ProbeRingMountPosition?
    let rotationExcursionDegrees: Double?
    let gravityTiltDegrees: Double?
    let endingGyroscopeDPS: Double?
    let sustainedMotion: Bool?
}

struct ProbeRingHardwareEventRecord: Identifiable, Codable {
    let id: UUID
    let occurredAt: Date
    let deviceTimestampMilliseconds: UInt32
    let type: String
    let detail: String?
}

struct ProbeRingIMUBatchRecord: Codable {
    let schemaVersion: String
    let sessionID: UUID
    let sourceEnvelopeID: UUID
    let deviceID: String
    let receivedAt: Date
    let sequenceStart: UInt32
    let frameCount: Int
    let sampleSize: Int
    let samples: [RingIMUSample]
}

struct ProbeAuditEvent: Identifiable, Codable {
    let id: UUID
    let occurredAt: Date
    let type: String
    let detail: String?
}

struct ProbeCaptureSession: Identifiable, Codable {
    let schemaVersion: String
    let id: UUID
    let startedAt: Date
    var endedAt: Date?
    var state: ProbeSessionState
    let intervalSeconds: Int
    let retainLocalSamples: Bool
    let localMediaTTLSeconds: Int
    let uploadAllowed: Bool
    let audioPolicy: ProbeAudioPolicySnapshot
    let ringPolicy: ProbeRingPolicySnapshot
    let deviceSummaryAtStart: String
    var observations: [ProbeCaptureObservation]
    var audioObservations: [ProbeAudioObservation]
    var ringSensor: ProbeRingSensorSnapshot?
    var ringDataReference: String?
    var ringBatchCount: Int
    var ringSampleCount: Int
    var ringSequenceGapCount: Int
    var ringMotionAssessments: [ProbeRingMotionAssessment]
    var ringHardwareEvents: [ProbeRingHardwareEventRecord]
    var auditEvents: [ProbeAuditEvent]

    var succeededCount: Int {
        observations.filter { $0.outcome == .succeeded }.count
    }

    var skippedCount: Int {
        observations.filter { $0.outcome == .skipped }.count
    }

    var failedCount: Int {
        observations.filter { $0.outcome == .failed }.count
    }

    var audioSegmentCount: Int {
        audioObservations.count
    }
}

final class ProbeArtifactStore {
    private let fileManager: FileManager
    private let rootURL: URL
    private let encoder: JSONEncoder

    init(fileManager: FileManager = .default) {
        self.fileManager = fileManager

        let applicationSupport = fileManager.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first!
        rootURL = applicationSupport.appendingPathComponent(
            "RealityMemoryProbe",
            isDirectory: true
        )

        encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]

        try? fileManager.createDirectory(
            at: rootURL,
            withIntermediateDirectories: true
        )
    }

    func appendDebugLog(_ item: ProbeLogItem) throws {
        let url = rootURL.appendingPathComponent("debug-events.ndjson")
        let lineEncoder = JSONEncoder()
        lineEncoder.dateEncodingStrategy = .iso8601
        var data = try lineEncoder.encode(item)
        data.append(0x0A)

        if fileManager.fileExists(atPath: url.path) {
            let handle = try FileHandle(forWritingTo: url)
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
            try handle.close()
        } else {
            try data.write(to: url, options: .atomic)
        }
    }

    @discardableResult
    func saveSession(_ session: ProbeCaptureSession) throws -> URL {
        let directory = try sessionDirectory(for: session.id)
        let url = directory.appendingPathComponent("session.json")
        try encoder.encode(session).write(to: url, options: .atomic)
        return url
    }

    func saveImage(_ data: Data, sessionID: UUID, observationID: UUID) throws -> String {
        let directory = try sessionDirectory(for: sessionID)
            .appendingPathComponent("evidence", isDirectory: true)
        try fileManager.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )

        let filename = "\(observationID.uuidString.lowercased()).\(imageFileExtension(for: data))"
        let url = directory.appendingPathComponent(filename)
        try data.write(to: url, options: .atomic)
        return "evidence/\(filename)"
    }

    func saveAudio(_ data: Data, sessionID: UUID, observationID: UUID) throws -> String {
        let directory = try sessionDirectory(for: sessionID)
            .appendingPathComponent("evidence", isDirectory: true)
        try fileManager.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )

        let filename = "\(observationID.uuidString.lowercased()).pcm"
        let url = directory.appendingPathComponent(filename)
        try data.write(
            to: url,
            options: [.atomic, .completeFileProtectionUnlessOpen]
        )
        return "evidence/\(filename)"
    }

    @discardableResult
    func appendRingBatch(_ batch: ProbeRingIMUBatchRecord) throws -> String {
        let directory = try sessionDirectory(for: batch.sessionID)
            .appendingPathComponent("ring", isDirectory: true)
        try fileManager.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )

        let filename = "imu.ndjson"
        let url = directory.appendingPathComponent(filename)
        let lineEncoder = JSONEncoder()
        lineEncoder.dateEncodingStrategy = .iso8601
        var data = try lineEncoder.encode(batch)
        data.append(0x0A)

        if fileManager.fileExists(atPath: url.path) {
            let handle = try FileHandle(forWritingTo: url)
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
            try handle.synchronize()
            try handle.close()
        } else {
            try data.write(
                to: url,
                options: [.atomic, .completeFileProtectionUnlessOpen]
            )
        }
        return "ring/\(filename)"
    }

    private func imageFileExtension(for data: Data) -> String {
        if
            data.count >= 12,
            String(data: data.prefix(4), encoding: .ascii) == "RIFF",
            String(data: data.dropFirst(8).prefix(4), encoding: .ascii) == "WEBP"
        {
            return "webp"
        }
        if data.count >= 3, data[0] == 0xFF, data[1] == 0xD8, data[2] == 0xFF {
            return "jpg"
        }
        if data.count >= 8, Array(data.prefix(8)) == [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A] {
            return "png"
        }
        return "bin"
    }

    private func sessionDirectory(for id: UUID) throws -> URL {
        let directory = rootURL
            .appendingPathComponent("sessions", isDirectory: true)
            .appendingPathComponent(id.uuidString.lowercased(), isDirectory: true)
        try fileManager.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        return directory
    }
}
