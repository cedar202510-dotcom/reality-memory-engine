import Foundation

struct ProbeAudioSegment {
    let data: Data
    let startedAt: Date
    let endedAt: Date
    let peakDBFS: Double

    var durationMilliseconds: Int {
        Int(endedAt.timeIntervalSince(startedAt) * 1_000)
    }
}

struct ProbeAudioVADResult {
    let levelDBFS: Double
    let speechStarted: Bool
    let completedSegment: ProbeAudioSegment?
}

final class ProbeAudioSpeechSegmenter {
    private let thresholdDBFS = -38.0
    private let speechStartFrames = 3
    private let silenceEndSeconds = 1.0
    private let maxSegmentSeconds = 15.0
    private let minSegmentSeconds = 0.4
    private let maxPreRollBytes = 32_000

    private var preRoll = Data()
    private var segmentData = Data()
    private var consecutiveSpeechFrames = 0
    private var segmentStartedAt: Date?
    private var lastSpeechAt: Date?
    private var peakDBFS = -120.0

    var isSpeechActive: Bool {
        segmentStartedAt != nil
    }

    func process(_ data: Data, now: Date = Date()) -> ProbeAudioVADResult {
        let level = Self.calculateDBFS(data)
        var started = false

        if segmentStartedAt == nil {
            preRoll.append(data)
            if preRoll.count > maxPreRollBytes {
                preRoll.removeFirst(preRoll.count - maxPreRollBytes)
            }

            consecutiveSpeechFrames = level >= thresholdDBFS
                ? consecutiveSpeechFrames + 1
                : 0

            if consecutiveSpeechFrames >= speechStartFrames {
                segmentStartedAt = now
                lastSpeechAt = now
                peakDBFS = level
                segmentData = preRoll
                preRoll.removeAll(keepingCapacity: true)
                consecutiveSpeechFrames = 0
                started = true
            }

            return ProbeAudioVADResult(
                levelDBFS: level,
                speechStarted: started,
                completedSegment: nil
            )
        }

        segmentData.append(data)
        peakDBFS = max(peakDBFS, level)
        if level >= thresholdDBFS {
            lastSpeechAt = now
        }

        let duration = now.timeIntervalSince(segmentStartedAt ?? now)
        let silence = now.timeIntervalSince(lastSpeechAt ?? now)
        let completed = duration >= maxSegmentSeconds || silence >= silenceEndSeconds
            ? finish(at: now)
            : nil

        return ProbeAudioVADResult(
            levelDBFS: level,
            speechStarted: false,
            completedSegment: completed
        )
    }

    func finish(at now: Date = Date()) -> ProbeAudioSegment? {
        guard let startedAt = segmentStartedAt else {
            reset()
            return nil
        }

        let data = segmentData
        let peak = peakDBFS
        reset()
        guard now.timeIntervalSince(startedAt) >= minSegmentSeconds else {
            return nil
        }
        return ProbeAudioSegment(
            data: data,
            startedAt: startedAt,
            endedAt: now,
            peakDBFS: peak
        )
    }

    func reset() {
        preRoll.removeAll(keepingCapacity: true)
        segmentData.removeAll(keepingCapacity: true)
        consecutiveSpeechFrames = 0
        segmentStartedAt = nil
        lastSpeechAt = nil
        peakDBFS = -120.0
    }

    private static func calculateDBFS(_ data: Data) -> Double {
        guard data.count >= 2 else {
            return -120
        }

        var sumSquares = 0.0
        var sampleCount = 0
        data.withUnsafeBytes { rawBuffer in
            var index = 0
            while index + 1 < rawBuffer.count {
                let low = UInt16(rawBuffer[index])
                let high = UInt16(rawBuffer[index + 1]) << 8
                let sample = Int16(bitPattern: low | high)
                let normalized = Double(sample) / Double(Int16.max)
                sumSquares += normalized * normalized
                sampleCount += 1
                index += 2
            }
        }

        guard sampleCount > 0 else {
            return -120
        }
        let rms = sqrt(sumSquares / Double(sampleCount))
        return 20 * log10(max(rms, 0.000_001))
    }
}
