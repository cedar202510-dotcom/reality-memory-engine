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
    let deviceSummaryAtStart: String
    var observations: [ProbeCaptureObservation]
    var audioObservations: [ProbeAudioObservation]
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

        let filename = "\(observationID.uuidString.lowercased()).jpg"
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
