import Foundation
import Network

struct LiveDebugCommand: Decodable {
    let command: String
    let deviceID: String?
    let boolValue: Bool?
    let intValue: Int?
    let stringValue: String?
}

struct LiveDebugRingCandidate: Encodable {
    let id: String
    let name: String
    let displayName: String
    let rssi: Int
    let advertisesRingService: Bool
    let isKnownRing: Bool
}

struct LiveDebugGlassesState: Encodable {
    let authentication: String
    let connection: String
    let customView: String
    let wearing: String
    let deviceSummary: String
    let photoReady: String
}

struct LiveDebugRingState: Encodable {
    let bluetooth: String
    let connection: String
    let selectedDeviceID: String?
    let serviceUUID: String
    let notifyCharacteristicUUID: String
    let writeCharacteristicUUID: String
    let macAddress: String
    let candidates: [LiveDebugRingCandidate]
    let identity: RingSystemInfo?
    let sensorConfiguration: RingSensorConfiguration?
    let sensorAutoStartEnabled: Bool
    let sensorReporting: Bool
    let batchCount: Int
    let sampleCount: Int
    let sequenceGapCount: Int
    let accelerationMagnitudeRaw: Double?
    let accelerationDeltaRaw: Double?
    let gyroscopeMagnitudeRaw: Double?
    let accelerationDeltaThresholdRaw: Double
    let gyroscopeMagnitudeThresholdRaw: Double
    let accelerationBaselineRaw: Double?
    let gyroscopeBaselineRaw: Double?
    let relativeChangeScore: Double?
    let motionContextState: String
    let mountPosition: String
    let rotationExcursionDegrees: Double?
    let gravityTiltDegrees: Double?
    let endingGyroscopeDPS: Double?
    let detectorRuleVersion: String
    let sensitivity: String
    let lastJudgement: String
    let lastJudgementAt: Date?
    let lastEvent: String
}

struct LiveDebugSessionState: Encodable {
    let id: String?
    let state: String
    let imageCount: Int
    let audioCount: Int
    let rapidMovementCount: Int
    let retainLocalSamples: Bool
    let audioLevelDBFS: Double?
    let speechActive: Bool
    let captureIntervalSeconds: Int
    let captureMode: String
    let acceleratedUntil: Date?
    let captureRearmRequired: Bool
}

struct LiveDebugSnapshot: Encodable {
    let phoneName: String
    let applicationState: String
    let desktopConnection: String
    let glasses: LiveDebugGlassesState
    let ring: LiveDebugRingState
    let session: LiveDebugSessionState
    let recentLogs: [ProbeLogItem]
}

struct LiveDebugRingBatch: Encodable {
    let receivedAt: Date
    let configuration: RingSensorConfiguration?
    let accelerationDeltaThresholdRaw: Double
    let gyroscopeMagnitudeThresholdRaw: Double
    let batch: RingIMUBatch
}

struct LiveDebugMediaItem: Encodable {
    let id: String
    let kind: String
    let occurredAt: Date
    let trigger: String
    let triggerDecisionID: String?
    let mimeType: String
    let durationMilliseconds: Int?
    let captureLatencyMilliseconds: Int?
    let byteCount: Int
    let base64Data: String
}

final class PhoneDebugBridge {
    var onStatusChanged: ((String) -> Void)?
    var onCommand: ((LiveDebugCommand) -> Void)?

    private struct Envelope<Payload: Encodable>: Encodable {
        let type: String
        let sentAt: Date
        let payload: Payload
    }

    private let queue = DispatchQueue(label: "com.realitymemoryengine.debug-bridge")
    private let encoder: JSONEncoder
    private var browser: NWBrowser?
    private var connection: NWConnection?
    private var currentEndpoint: NWEndpoint?
    private var pendingMessages: [Data] = []
    private var receiveBuffer = Data()
    private var heartbeatTimer: DispatchSourceTimer?

    init() {
        encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
    }

    func start() {
        queue.async { [weak self] in
            guard let self, self.browser == nil else {
                return
            }
            let browser = NWBrowser(
                for: .bonjour(type: "_rme-debug._tcp", domain: nil),
                using: .tcp
            )
            browser.stateUpdateHandler = { [weak self] state in
                switch state {
                case .ready:
                    self?.publishStatus("正在寻找电脑调试台")
                case .failed(let error):
                    self?.publishStatus("调试桥发现失败：\(error.localizedDescription)")
                case .cancelled:
                    self?.publishStatus("电脑调试桥已停止")
                default:
                    break
                }
            }
            browser.browseResultsChangedHandler = { [weak self] results, _ in
                guard let self, let endpoint = results.first?.endpoint else {
                    return
                }
                self.connect(to: endpoint)
            }
            self.browser = browser
            browser.start(queue: self.queue)
            self.startHeartbeat()
        }
    }

    func send<Payload: Encodable>(type: String, payload: Payload) {
        do {
            var data = try encoder.encode(
                Envelope(type: type, sentAt: Date(), payload: payload)
            )
            data.append(0x0A)
            queue.async { [weak self] in
                self?.enqueueOrSend(data)
            }
        } catch {
            publishStatus("调试数据编码失败：\(error.localizedDescription)")
        }
    }

    private func connect(to endpoint: NWEndpoint) {
        guard currentEndpoint != endpoint || connection == nil else {
            return
        }
        connection?.cancel()
        currentEndpoint = endpoint
        let connection = NWConnection(to: endpoint, using: .tcp)
        self.connection = connection
        connection.stateUpdateHandler = { [weak self, weak connection] state in
            guard let self, let connection else {
                return
            }
            switch state {
            case .ready:
                self.publishStatus("电脑调试台已连接")
                self.flushPendingMessages()
                self.receiveCommands(on: connection)
            case .failed(let error):
                self.publishStatus("电脑调试台连接失败：\(error.localizedDescription)")
                self.connection = nil
                self.scheduleReconnect(to: endpoint)
            case .cancelled:
                if self.connection === connection {
                    self.connection = nil
                }
            default:
                break
            }
        }
        publishStatus("正在连接电脑调试台")
        connection.start(queue: queue)
    }

    private func scheduleReconnect(to endpoint: NWEndpoint) {
        queue.asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let self, self.connection == nil else {
                return
            }
            self.connect(to: endpoint)
        }
    }

    private func startHeartbeat() {
        guard heartbeatTimer == nil else {
            return
        }
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + 1, repeating: 2)
        timer.setEventHandler { [weak self] in
            self?.send(type: "heartbeat", payload: ["state": "alive"])
        }
        heartbeatTimer = timer
        timer.resume()
    }

    private func enqueueOrSend(_ data: Data) {
        guard let connection, connection.state == .ready else {
            pendingMessages.append(data)
            if pendingMessages.count > 20 {
                pendingMessages.removeFirst(pendingMessages.count - 20)
            }
            return
        }
        connection.send(content: data, completion: .contentProcessed { [weak self] error in
            if let error {
                self?.publishStatus("调试数据发送失败：\(error.localizedDescription)")
            }
        })
    }

    private func flushPendingMessages() {
        let messages = pendingMessages
        pendingMessages.removeAll(keepingCapacity: true)
        for message in messages {
            enqueueOrSend(message)
        }
    }

    private func receiveCommands(on connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1_024) {
            [weak self, weak connection] data, _, isComplete, error in
            guard let self, let connection else {
                return
            }
            if let data {
                self.receiveBuffer.append(data)
                self.consumeCommandLines()
            }
            if let error {
                self.handleConnectionEnded(
                    connection,
                    status: "电脑调试台连接中断：\(error.localizedDescription)"
                )
                return
            }
            if isComplete {
                self.handleConnectionEnded(
                    connection,
                    status: "电脑调试台连接已关闭，正在重连"
                )
                return
            }
            self.receiveCommands(on: connection)
        }
    }

    private func handleConnectionEnded(_ connection: NWConnection, status: String) {
        guard self.connection === connection else {
            return
        }
        connection.cancel()
        self.connection = nil
        publishStatus(status)
        if let currentEndpoint {
            scheduleReconnect(to: currentEndpoint)
        }
    }

    private func consumeCommandLines() {
        while let newline = receiveBuffer.firstIndex(of: 0x0A) {
            let line = receiveBuffer.prefix(upTo: newline)
            receiveBuffer.removeSubrange(...newline)
            guard !line.isEmpty else {
                continue
            }
            do {
                let command = try JSONDecoder().decode(LiveDebugCommand.self, from: line)
                DispatchQueue.main.async { [weak self] in
                    self?.onCommand?(command)
                }
            } catch {
                publishStatus("调试命令格式错误：\(error.localizedDescription)")
            }
        }
    }

    private func publishStatus(_ status: String) {
        DispatchQueue.main.async { [weak self] in
            self?.onStatusChanged?(status)
        }
    }
}
