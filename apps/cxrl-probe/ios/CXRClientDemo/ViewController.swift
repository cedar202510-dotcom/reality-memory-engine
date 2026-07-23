import Combine
import CryptoKit
import RGCxrClient
import UIKit

struct CxrProbeState {
    var companionInstalled = false
    var authenticated = false
    var connected = false
    var customViewOpened = false
    var wearing: Bool?
    var takingPhoto = false
    var scheduledCaptureEnabled = false
    var captureCount = 0
    var lastImage: UIImage?
    var lastCaptureSummary = "No capture yet"
    var audioTestRunning = false
    var audioStreamStarted = false
    var audioPacketCount = 0
    var audioBytes = 0
    var audioLevelDBFS: Double?
    var speechActive = false
    var audioSegmentCount = 0
    var lastAudioSummary = "No audio test yet"
    var status = "Check Rokid AI App first"
    var recentEvents: [String] = []

    var captureReady: Bool {
        authenticated && connected && customViewOpened && !takingPhoto
    }
}

private struct AudioSegment {
    let data: Data
    let startedAt: Date
    let endedAt: Date
    let peakDBFS: Double

    var durationMs: Int {
        Int(endedAt.timeIntervalSince(startedAt) * 1_000)
    }
}

private struct AudioVADResult {
    let levelDBFS: Double
    let speechStarted: Bool
    let completedSegment: AudioSegment?
}

private final class AudioSpeechSegmenter {
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

    func process(_ data: Data, now: Date = Date()) -> AudioVADResult {
        let level = Self.calculateDBFS(data)
        var started = false

        if segmentStartedAt == nil {
            preRoll.append(data)
            if preRoll.count > maxPreRollBytes {
                preRoll.removeFirst(preRoll.count - maxPreRollBytes)
            }

            if level >= thresholdDBFS {
                consecutiveSpeechFrames += 1
            } else {
                consecutiveSpeechFrames = 0
            }

            if consecutiveSpeechFrames >= speechStartFrames {
                segmentStartedAt = now
                lastSpeechAt = now
                peakDBFS = level
                segmentData = preRoll
                preRoll.removeAll(keepingCapacity: true)
                consecutiveSpeechFrames = 0
                started = true
            }

            return AudioVADResult(
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
        let shouldFinish = duration >= maxSegmentSeconds || silence >= silenceEndSeconds
        let completed = shouldFinish ? finish(at: now) : nil

        return AudioVADResult(
            levelDBFS: level,
            speechStarted: false,
            completedSegment: completed
        )
    }

    func finish(at now: Date = Date()) -> AudioSegment? {
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
        return AudioSegment(data: data, startedAt: startedAt, endedAt: now, peakDBFS: peak)
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
        guard data.count >= 2 else { return -120 }
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

        guard sampleCount > 0 else { return -120 }
        let rms = sqrt(sumSquares / Double(sampleCount))
        return 20 * log10(max(rms, 0.000_001))
    }
}

final class CxrProbeController {
    static let shared = CxrProbeController()

    let state = CurrentValueSubject<CxrProbeState, Never>(CxrProbeState())

    private let link: RGCxrLink
    private let session: RGCxrCustomViewSession
    private var cancellables = Set<AnyCancellable>()
    private var customViewOpening = false
    private var captureTimer: Timer?
    private var audioTestTimer: Timer?
    private let audioSegmenter = AudioSpeechSegmenter()
    private var audioChannels: UInt32 = 1
    private var pendingTrigger = "manual"

    private static let customViewJSON = """
    {
      "type": "LinearLayout",
      "props": {
        "id": "root",
        "layout_width": "match_parent",
        "layout_height": "match_parent",
        "orientation": "vertical",
        "gravity": "center",
        "backgroundColor": "#000000"
      },
      "children": []
    }
    """

    private init() {
        link = CxrClient.makeLink(appDisplayName: "Reality CXR-L Probe")
        session = link.makeCustomViewSession()
        bindEvents()
        checkCompanionApp()
    }

    @discardableResult
    func handleOpenURL(_ url: URL) -> Bool {
        link.handleOpenURL(url)
    }

    func checkCompanionApp() {
        let installed = CxrClient.shared.isRokidAppInstalled()
        update(installed ? "Rokid AI App found" : "Rokid AI App missing") {
            $0.companionInstalled = installed
            $0.status = installed ? "Companion app found; request authorization" :
                "Install Rokid AI App 1.9.0 or newer"
        }
    }

    func authorize() {
        guard state.value.companionInstalled else {
            checkCompanionApp()
            return
        }
        update("Opening Rokid AI App authorization") {
            $0.status = "Complete authorization in Rokid AI App"
        }
        link.authenticate(scopes: [.camera, .microphone]) { [weak self] result in
            DispatchQueue.main.async {
                switch result {
                case .success:
                    self?.update("Authorization succeeded") {
                        $0.authenticated = true
                        $0.status = "Authorized; waiting for BLE connection"
                    }
                    self?.openCustomViewIfPossible()
                case .failure(let error):
                    self?.update("Authorization failed: \(error.localizedDescription)") {
                        $0.authenticated = false
                        $0.status = "Authorization failed"
                    }
                }
            }
        }
    }

    func openCustomView() {
        openCustomViewIfPossible()
    }

    func capture(trigger: String = "manual") {
        guard state.value.captureReady else {
            update("Capture blocked: session not ready") {
                $0.status = "Wait for authorization, BLE, and CustomView"
            }
            return
        }
        pendingTrigger = trigger
        update("Capture requested: \(trigger)") {
            $0.takingPhoto = true
            $0.status = "Taking photo"
        }
        let error = session.media.takePhoto(width: 1024, height: 768, quality: 80) { [weak self] data in
            DispatchQueue.main.async {
                self?.acceptImage(data)
            }
        }
        if let error {
            update("Capture request failed: \(error)") {
                $0.takingPhoto = false
                $0.status = "Capture request failed"
            }
        }
    }

    func startScheduledCapture() {
        guard captureTimer == nil else { return }
        update("30-second capture loop started") {
            $0.scheduledCaptureEnabled = true
        }
        capture(trigger: "timer")
        captureTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            guard let self else { return }
            if self.state.value.wearing == false {
                self.event("Scheduled capture skipped: glasses not worn")
            } else if self.state.value.captureReady {
                self.capture(trigger: "timer")
            } else {
                self.event("Scheduled capture waiting for a ready session")
            }
        }
    }

    func stopScheduledCapture() {
        captureTimer?.invalidate()
        captureTimer = nil
        update("Scheduled capture stopped") {
            $0.scheduledCaptureEnabled = false
        }
    }

    func startAudioTest() {
        let current = state.value
        guard current.captureReady, !current.audioTestRunning else {
            event("Audio test blocked: session not ready or already running")
            return
        }

        audioSegmenter.reset()
        audioTestTimer?.invalidate()
        update("Starting 30-second glasses audio/VAD test") {
            $0.audioTestRunning = true
            $0.audioStreamStarted = false
            $0.audioPacketCount = 0
            $0.audioBytes = 0
            $0.audioLevelDBFS = nil
            $0.speechActive = false
            $0.lastAudioSummary = "Waiting for glasses PCM stream"
            $0.status = "Starting audio test"
        }

        let error = session.media.startAudioStream(codec: .pcm, mode: .antClose)
        if let error {
            audioSegmenter.reset()
            update("Audio stream request failed: \(error)") {
                $0.audioTestRunning = false
                $0.audioStreamStarted = false
                $0.status = "Audio test failed to start"
            }
            return
        }

        audioTestTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: false) { [weak self] _ in
            self?.stopAudioTest(reason: "30-second limit reached")
        }
    }

    func stopAudioTest(reason: String = "manual") {
        audioTestTimer?.invalidate()
        audioTestTimer = nil
        guard state.value.audioTestRunning || state.value.audioStreamStarted else { return }

        if let segment = audioSegmenter.finish() {
            acceptAudioSegment(segment)
        }
        let error = session.media.stopAudioStream()
        update(error == nil ? "Audio test stopped: \(reason)" : "Audio stop returned: \(String(describing: error))") {
            $0.audioTestRunning = false
            $0.audioStreamStarted = false
            $0.speechActive = false
            $0.status = error == nil ? "Audio test stopped" : "Audio stop needs inspection"
        }
    }

    func deleteAudioSamples() {
        guard let directory = audioDirectoryURL() else { return }
        try? FileManager.default.removeItem(at: directory)
        update("Deleted local audio test segments") {
            $0.audioSegmentCount = 0
            $0.lastAudioSummary = "Local audio test segments deleted"
        }
    }

    func disconnect() {
        stopScheduledCapture()
        stopAudioTest(reason: "disconnect")
        if state.value.customViewOpened {
            _ = session.customView.close(callback: nil)
        }
        link.disconnect()
        customViewOpening = false
        update("Disconnected") {
            $0.connected = false
            $0.customViewOpened = false
            $0.wearing = nil
            $0.takingPhoto = false
            $0.audioTestRunning = false
            $0.audioStreamStarted = false
            $0.speechActive = false
            $0.status = "Disconnected"
        }
    }

    private func bindEvents() {
        link.events.authStatePublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] authState in
                guard let self else { return }
                let authenticated = authState.isAuthenticated
                self.update("Authorization state changed") {
                    $0.authenticated = authenticated
                }
                self.openCustomViewIfPossible()
            }
            .store(in: &cancellables)

        link.events.connectionStatePublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] connected in
                guard let self else { return }
                self.update("BLE connection: \(connected)") {
                    $0.connected = connected
                    $0.status = connected ? "BLE ready; opening CustomView" : "Waiting for BLE connection"
                    if !connected {
                        $0.customViewOpened = false
                    }
                }
                if !connected {
                    self.handleAudioDisconnect()
                }
                self.openCustomViewIfPossible()
            }
            .store(in: &cancellables)

        session.statePublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                self?.event("Session state: \(event.state.rawValue)")
            }
            .store(in: &cancellables)

        session.customViewEvents.lifecyclePublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                self?.handleCustomViewEvent(event)
            }
            .store(in: &cancellables)

        session.deviceEvents.wearingStatusPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] wearing in
                self?.update("Wearing status: \(wearing)") {
                    $0.wearing = wearing
                }
                if !wearing {
                    self?.stopAudioTest(reason: "glasses not worn")
                }
            }
            .store(in: &cancellables)

        session.mediaEvents.audioPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] audioEvent in
                self?.handleAudioEvent(audioEvent)
            }
            .store(in: &cancellables)
    }

    private func handleAudioEvent(_ audioEvent: RGCxrClientAudioEvent) {
        switch audioEvent {
        case .started(let info):
            audioChannels = max(1, info.channels)
            update("Audio stream started: codec=\(info.codec), channels=\(info.channels), type=\(info.type)") {
                $0.audioStreamStarted = true
                $0.lastAudioSummary = "PCM stream active; speak during the 30-second window"
                $0.status = "Audio/VAD test running"
            }
        case .stream(let packet):
            guard state.value.audioTestRunning else { return }
            let vad = audioSegmenter.process(packet.data)
            updateAudioMetrics(
                packetBytes: packet.data.count,
                levelDBFS: vad.levelDBFS,
                speechStarted: vad.speechStarted
            )
            if let segment = vad.completedSegment {
                acceptAudioSegment(segment)
            }
        @unknown default:
            event("Unknown audio event received")
        }
    }

    private func updateAudioMetrics(
        packetBytes: Int,
        levelDBFS: Double,
        speechStarted: Bool
    ) {
        var current = state.value
        current.audioPacketCount += 1
        current.audioBytes += packetBytes
        current.audioLevelDBFS = levelDBFS
        current.speechActive = audioSegmenter.isSpeechActive
        if speechStarted {
            let timestamp = ISO8601DateFormatter().string(from: Date())
            current.recentEvents.insert(
                "\(timestamp)  Local VAD speech started at \(String(format: "%.1f", levelDBFS)) dBFS",
                at: 0
            )
            current.recentEvents = Array(current.recentEvents.prefix(12))
        }
        state.send(current)
    }

    private func acceptAudioSegment(_ segment: AudioSegment) {
        let capturedAt = ISO8601DateFormatter().string(from: segment.startedAt)
        let digest = SHA256.hash(data: segment.data).map { String(format: "%02x", $0) }.joined()
        let fileName = "vad-\(Int(segment.startedAt.timeIntervalSince1970 * 1_000)).pcm"
        var persisted = false

        if let directory = audioDirectoryURL() {
            try? FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.protectionKey: FileProtectionType.completeUnlessOpen]
            )
            let fileURL = directory.appendingPathComponent(fileName)
            do {
                try segment.data.write(to: fileURL, options: .atomic)
                try? FileManager.default.setAttributes(
                    [.protectionKey: FileProtectionType.completeUnlessOpen],
                    ofItemAtPath: fileURL.path
                )
                persisted = true
            } catch {
                event("Audio segment write failed: \(error.localizedDescription)")
            }
        }

        appendEventPayload([
            "schema_version": "0.2",
            "event_type": "evidence.audio.segmented",
            "source": "rokid_cxrl_audio",
            "trigger": "local_vad_test",
            "captured_at": capturedAt,
            "duration_ms": segment.durationMs,
            "audio_bytes": segment.data.count,
            "audio_sha256": digest,
            "codec": "pcm_s16le",
            "sample_rate_hz_assumption": 16_000,
            "channels_reported": audioChannels,
            "peak_dbfs": segment.peakDBFS,
            "audio_persisted_for_explicit_test": persisted
        ])

        update("VAD segment completed: \(segment.durationMs) ms, \(segment.data.count) bytes") {
            $0.audioSegmentCount += 1
            $0.speechActive = false
            $0.lastAudioSummary = [
                "\(capturedAt)",
                "\(segment.durationMs) ms",
                "\(segment.data.count) bytes",
                String(format: "peak %.1f dBFS", segment.peakDBFS),
                persisted ? fileName : "not persisted"
            ].joined(separator: " | ")
        }
    }

    private func handleAudioDisconnect() {
        audioTestTimer?.invalidate()
        audioTestTimer = nil
        guard state.value.audioTestRunning || state.value.audioStreamStarted else {
            audioSegmenter.reset()
            return
        }
        if let segment = audioSegmenter.finish() {
            acceptAudioSegment(segment)
        }
        audioSegmenter.reset()
        update("Audio test ended because BLE disconnected") {
            $0.audioTestRunning = false
            $0.audioStreamStarted = false
            $0.speechActive = false
        }
    }

    private func openCustomViewIfPossible() {
        let current = state.value
        guard current.authenticated,
              current.connected,
              !current.customViewOpened,
              !customViewOpening else { return }
        customViewOpening = true
        update("Opening CustomView") {
            $0.status = "Opening CustomView on glasses"
        }
        let error = session.customView.open(Self.customViewJSON) { [weak self] success, errorCode in
            DispatchQueue.main.async {
                guard let self else { return }
                self.customViewOpening = false
                if success {
                    self.update("CustomView open callback succeeded") {
                        $0.customViewOpened = true
                        $0.status = "Ready to capture"
                    }
                } else {
                    self.update("CustomView open callback failed: \(errorCode.map { String($0) } ?? "unknown")") {
                        $0.customViewOpened = false
                        $0.status = "CustomView open failed"
                    }
                }
            }
        }
        if let error {
            customViewOpening = false
            update("CustomView request failed: \(error)") {
                $0.status = "CustomView request failed"
            }
        }
    }

    private func handleCustomViewEvent(_ event: RGCxrSessionCustomViewEvent) {
        switch event {
        case .opened:
            customViewOpening = false
            update("CustomView opened; capture APIs are ready") {
                $0.customViewOpened = true
                $0.status = "Ready to capture"
            }
        case .updated:
            self.event("CustomView updated")
        case .closed:
            customViewOpening = false
            update("CustomView closed") {
                $0.customViewOpened = false
                $0.status = "CustomView closed"
            }
        case .iconsSent:
            self.event("CustomView icons sent")
        case .error(let code, let message):
            customViewOpening = false
            update("CustomView error: \(code) \(message ?? "")") {
                $0.customViewOpened = false
                $0.status = "CustomView failed"
            }
        @unknown default:
            self.event("Unknown CustomView event received")
        }
    }

    private func acceptImage(_ data: Data) {
        let capturedAt = ISO8601DateFormatter().string(from: Date())
        let trigger = pendingTrigger
        update("Image received: \(data.count) bytes") {
            $0.takingPhoto = false
            $0.captureCount += 1
            $0.lastImage = UIImage(data: data)
            $0.lastCaptureSummary = "\(capturedAt) | \(data.count) bytes | \(trigger)"
            $0.status = "Capture received"
        }
        appendObservation(capturedAt: capturedAt, trigger: trigger, imageData: data)
    }

    private func appendObservation(capturedAt: String, trigger: String, imageData: Data) {
        let digest = SHA256.hash(data: imageData).map { String(format: "%02x", $0) }.joined()
        appendEventPayload([
            "schema_version": "0.2",
            "event_type": "evidence.image.captured",
            "source_envelope_id": UUID().uuidString,
            "occurred_at": capturedAt,
            "source": "rokid_cxrl_photo",
            "trigger": trigger,
            "modality": "IMAGE",
            "image_bytes": imageData.count,
            "image_sha256": digest,
            "image_persisted": false,
            "wearing": state.value.wearing.map { $0 as Any } ?? NSNull()
        ])
    }

    private func appendEventPayload(_ payload: [String: Any]) {
        guard JSONSerialization.isValidJSONObject(payload),
              let data = try? JSONSerialization.data(withJSONObject: payload),
              let line = String(data: data, encoding: .utf8)?.appending("\n").data(using: .utf8),
              let url = logFileURL() else { return }
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil)
        }
        guard let handle = try? FileHandle(forWritingTo: url) else { return }
        handle.seekToEndOfFile()
        handle.write(line)
        try? handle.close()
    }

    private func audioDirectoryURL() -> URL? {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)
            .first?
            .appendingPathComponent("audio-vad-test", isDirectory: true)
    }

    private func logFileURL() -> URL? {
        guard let directory = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first else { return nil }
        try? FileManager.default.createDirectory(
            at: directory,
            withIntermediateDirectories: true
        )
        return directory.appendingPathComponent("probe-events.jsonl")
    }

    private func event(_ message: String) {
        update(message) { _ in }
    }

    private func update(_ message: String, mutate: (inout CxrProbeState) -> Void) {
        var current = state.value
        mutate(&current)
        let timestamp = ISO8601DateFormatter().string(from: Date())
        current.recentEvents.insert("\(timestamp)  \(message)", at: 0)
        current.recentEvents = Array(current.recentEvents.prefix(12))
        state.send(current)
    }
}

final class ViewController: UIViewController {
    private lazy var controller = CxrProbeController.shared
    private var cancellables = Set<AnyCancellable>()

    private let statusLabel = UILabel()
    private let readinessLabel = UILabel()
    private let captureSummaryLabel = UILabel()
    private let audioSummaryLabel = UILabel()
    private let previewImageView = UIImageView()
    private let eventTextView = UITextView()
    private let authorizeButton = UIButton(type: .system)
    private let captureButton = UIButton(type: .system)
    private let timerButton = UIButton(type: .system)
    private let audioButton = UIButton(type: .system)

    override func viewDidLoad() {
        super.viewDidLoad()
        configureUI()
        bindState()
    }

    private func configureUI() {
        view.backgroundColor = UIColor(red: 0.96, green: 0.97, blue: 0.97, alpha: 1)

        let title = UILabel()
        title.text = "Reality CXR-L Probe"
        title.font = .systemFont(ofSize: 28, weight: .bold)
        title.textColor = UIColor(red: 0.09, green: 0.13, blue: 0.17, alpha: 1)

        statusLabel.font = .systemFont(ofSize: 17, weight: .semibold)
        statusLabel.numberOfLines = 0

        readinessLabel.font = .monospacedSystemFont(ofSize: 14, weight: .medium)
        readinessLabel.numberOfLines = 0
        readinessLabel.backgroundColor = .white
        readinessLabel.layer.cornerRadius = 4
        readinessLabel.layer.masksToBounds = true

        captureSummaryLabel.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        captureSummaryLabel.numberOfLines = 0

        audioSummaryLabel.font = .monospacedSystemFont(ofSize: 12, weight: .regular)
        audioSummaryLabel.numberOfLines = 0

        previewImageView.contentMode = .scaleAspectFit
        previewImageView.backgroundColor = .black
        previewImageView.heightAnchor.constraint(equalToConstant: 220).isActive = true

        eventTextView.isEditable = false
        eventTextView.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        eventTextView.backgroundColor = .white
        eventTextView.heightAnchor.constraint(equalToConstant: 180).isActive = true

        let checkButton = makeButton("1. Check Rokid AI App", color: .darkGray, action: #selector(checkApp))
        configureButton(authorizeButton, title: "2. Request glasses permissions", color: .systemGreen)
        authorizeButton.addTarget(self, action: #selector(authorize), for: .touchUpInside)
        let openButton = makeButton("3. Open CustomView when ready", color: .systemGreen, action: #selector(openView))
        configureButton(captureButton, title: "Capture once", color: .systemBlue)
        captureButton.addTarget(self, action: #selector(capture), for: .touchUpInside)
        configureButton(timerButton, title: "Start 30s timer", color: .darkGray)
        timerButton.addTarget(self, action: #selector(toggleTimer), for: .touchUpInside)
        configureButton(audioButton, title: "Start 30s audio/VAD test", color: .systemIndigo)
        audioButton.addTarget(self, action: #selector(toggleAudioTest), for: .touchUpInside)
        let deleteAudioButton = makeButton(
            "Delete local audio test segments",
            color: .systemRed,
            action: #selector(deleteAudioSamples)
        )
        let disconnectButton = makeButton("Disconnect", color: .systemOrange, action: #selector(disconnect))

        let stack = UIStackView(arrangedSubviews: [
            title,
            statusLabel,
            readinessLabel,
            checkButton,
            authorizeButton,
            openButton,
            captureButton,
            timerButton,
            audioButton,
            audioSummaryLabel,
            deleteAudioButton,
            previewImageView,
            captureSummaryLabel,
            disconnectButton,
            eventTextView
        ])
        stack.axis = .vertical
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false

        let scroll = UIScrollView()
        scroll.translatesAutoresizingMaskIntoConstraints = false
        scroll.addSubview(stack)
        view.addSubview(scroll)

        NSLayoutConstraint.activate([
            scroll.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            scroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            scroll.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            stack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor, constant: 20),
            stack.leadingAnchor.constraint(equalTo: scroll.frameLayoutGuide.leadingAnchor, constant: 20),
            stack.trailingAnchor.constraint(equalTo: scroll.frameLayoutGuide.trailingAnchor, constant: -20),
            stack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor, constant: -24)
        ])
    }

    private func bindState() {
        controller.state
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in
                self?.render(state)
            }
            .store(in: &cancellables)
    }

    private func render(_ state: CxrProbeState) {
        statusLabel.text = state.status
        statusLabel.textColor = state.captureReady ? .systemGreen : .systemOrange
        readinessLabel.text = """
          Rokid AI App        \(state.companionInstalled ? "READY" : "WAIT")
          Authorization       \(state.authenticated ? "READY" : "WAIT")
          BLE link            \(state.connected ? "READY" : "WAIT")
          CustomView          \(state.customViewOpened ? "READY" : "WAIT")
          Wearing             \(state.wearing.map { String($0) } ?? "unknown")
          Captures            \(state.captureCount)
          Audio stream        \(state.audioStreamStarted ? "ACTIVE" : "OFF")
          Audio packets       \(state.audioPacketCount)
          Audio bytes         \(state.audioBytes)
          Audio level         \(state.audioLevelDBFS.map { String(format: "%.1f dBFS", $0) } ?? "unknown")
          Voice segment       \(state.speechActive ? "ACTIVE" : "idle")
          Audio segments      \(state.audioSegmentCount)
        """
        captureButton.isEnabled = state.captureReady
        authorizeButton.isEnabled = state.companionInstalled
        timerButton.isEnabled = state.captureReady || state.scheduledCaptureEnabled
        timerButton.setTitle(
            state.scheduledCaptureEnabled ? "Stop timer" : "Start 30s timer",
            for: .normal
        )
        audioButton.isEnabled = state.captureReady || state.audioTestRunning
        audioButton.setTitle(
            state.audioTestRunning ? "Stop audio/VAD test" : "Start 30s audio/VAD test",
            for: .normal
        )
        previewImageView.image = state.lastImage
        captureSummaryLabel.text = state.lastCaptureSummary
        audioSummaryLabel.text = state.lastAudioSummary
        eventTextView.text = state.recentEvents.joined(separator: "\n")
    }

    private func makeButton(_ title: String, color: UIColor, action: Selector) -> UIButton {
        let button = UIButton(type: .system)
        configureButton(button, title: title, color: color)
        button.addTarget(self, action: action, for: .touchUpInside)
        return button
    }

    private func configureButton(_ button: UIButton, title: String, color: UIColor) {
        var configuration = UIButton.Configuration.filled()
        configuration.title = title
        configuration.baseBackgroundColor = color
        configuration.cornerStyle = .small
        configuration.contentInsets = NSDirectionalEdgeInsets(top: 12, leading: 14, bottom: 12, trailing: 14)
        button.configuration = configuration
    }

    @objc private func checkApp() {
        controller.checkCompanionApp()
    }

    @objc private func authorize() {
        controller.authorize()
    }

    @objc private func openView() {
        controller.openCustomView()
    }

    @objc private func capture() {
        controller.capture()
    }

    @objc private func toggleTimer() {
        if controller.state.value.scheduledCaptureEnabled {
            controller.stopScheduledCapture()
        } else {
            controller.startScheduledCapture()
        }
    }

    @objc private func toggleAudioTest() {
        if controller.state.value.audioTestRunning {
            controller.stopAudioTest()
        } else {
            controller.startAudioTest()
        }
    }

    @objc private func deleteAudioSamples() {
        controller.deleteAudioSamples()
    }

    @objc private func disconnect() {
        controller.disconnect()
    }
}
