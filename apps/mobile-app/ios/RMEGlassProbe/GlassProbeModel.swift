import Combine
import Foundation
import OSLog
import RGCxrClient
import UIKit

@MainActor
final class GlassProbeModel: ObservableObject {
    private struct PendingPhotoRequest {
        let id: UUID
        let sessionID: UUID?
        let scheduledAt: Date
        let trigger: ProbeCaptureTrigger
    }

    private static let logger = Logger(
        subsystem: "com.realitymemoryengine.RMEGlassProbe",
        category: "Capture"
    )
    private static let photoTimeoutSeconds: TimeInterval = 12
    private static let audioTestSeconds: TimeInterval = 30

    @Published private(set) var rokidAppInstalled = false
    @Published private(set) var authStatus = "未授权"
    @Published private(set) var linkStatus = "未连接"
    @Published private(set) var customViewStatus = "未打开"
    @Published private(set) var wearingStatus = "未知"
    @Published private(set) var deviceSummary = "尚未读取"
    @Published private(set) var capturedImage: UIImage?
    @Published private(set) var logs: [ProbeLogItem] = []
    @Published private(set) var isAuthenticated = false
    @Published private(set) var isAuthenticating = false
    @Published private(set) var isConnected = false
    @Published private(set) var isCustomViewRunning = false
    @Published private(set) var isPhotoPending = false
    @Published private(set) var captureIntervalSeconds = 30
    @Published private(set) var retainLocalSamples = false
    @Published private(set) var sessionState: ProbeSessionState = .idle
    @Published private(set) var currentSession: ProbeCaptureSession?
    @Published private(set) var latestSessionURL: URL?
    @Published private(set) var nextCaptureAt: Date?
    @Published private(set) var showsGlassDebugOverlay = false
    @Published private(set) var applicationState = "前台"
    @Published private(set) var isAudioTestRunning = false
    @Published private(set) var isAudioStreamStarted = false
    @Published private(set) var audioPacketCount = 0
    @Published private(set) var audioByteCount = 0
    @Published private(set) var audioLevelDBFS: Double?
    @Published private(set) var isSpeechActive = false
    @Published private(set) var audioSegmentCount = 0
    @Published private(set) var lastAudioSummary = "尚未测试"

    private let client: any RGCxrClient
    private let artifactStore = ProbeArtifactStore()
    private var cancellables = Set<AnyCancellable>()
    private var captureLoopTask: Task<Void, Never>?
    private var photoTimeoutTask: Task<Void, Never>?
    private var pendingPhotoRequest: PendingPhotoRequest?
    private var audioTestTask: Task<Void, Never>?
    private let audioSegmenter = ProbeAudioSpeechSegmenter()
    private var audioChannels: UInt32 = 1

    var canAuthorize: Bool {
        rokidAppInstalled && !isAuthenticating
    }

    var canToggleCustomView: Bool {
        isConnected
    }

    var canTakePhoto: Bool {
        isCustomViewRunning && !isPhotoPending
    }

    var canStartSession: Bool {
        isConnected && isCustomViewRunning && !isPhotoPending && sessionState != .active
    }

    var canToggleAudioTest: Bool {
        isAudioTestRunning || (isConnected && isCustomViewRunning)
    }

    var photoReadinessStatus: String {
        if !isCustomViewRunning {
            return "眼镜界面未就绪"
        }
        if isPhotoPending {
            return "正在等待上一张回调"
        }
        return "可以拍照"
    }

    var sessionSucceededCount: Int {
        currentSession?.succeededCount ?? 0
    }

    var sessionSkippedCount: Int {
        currentSession?.skippedCount ?? 0
    }

    var sessionFailedCount: Int {
        currentSession?.failedCount ?? 0
    }

    init() {
        _ = CxrClient.initialize(
            mode: .customView,
            options: .init(appDisplayName: "Reality Memory Probe", pageName: nil)
        )
        client = CxrClient.shared

        bindEvents()
        applyAuthState(client.auth.currentState)
        refreshEnvironment()
        appendLog("CXR-L SDK 已初始化为 CUSTOMVIEW")
    }

    func refreshEnvironment() {
        rokidAppInstalled = client.isRokidAppInstalled()
        appendLog(rokidAppInstalled ? "已检测到 Rokid AI App" : "未检测到 Rokid AI App")
    }

    func authenticate() {
        guard rokidAppInstalled else {
            appendLog("无法授权：未检测到 Rokid AI App")
            return
        }

        appendLog("正在请求相机与麦克风授权")
        client.auth.authenticate(
            scopes: [.microphone, .camera],
            appName: "Reality Memory Probe"
        ) { [weak self] result in
            DispatchQueue.main.async {
                switch result {
                case .success:
                    self?.appendLog("Rokid 授权成功，SDK 已接收 token")
                case .failure(let error):
                    self?.appendLog("Rokid 授权失败：\(error.localizedDescription)")
                }
            }
        }
    }

    func clearAuthentication() {
        cancelPendingPhoto(reason: "AUTHENTICATION_CLEARED")
        stopAudioTest(reason: "AUTHENTICATION_CLEARED")
        client.auth.clearAuthentication()
        capturedImage = nil
        appendLog("已清除本机 Rokid 授权")
    }

    func handleOpenURL(_ url: URL) {
        let handled = client.handleOpenURL(url)
        appendLog(handled ? "已处理 Rokid 授权回调" : "收到未识别的 URL 回调")
    }

    func toggleCustomView() {
        if isCustomViewRunning {
            closeCustomView()
        } else {
            openCustomView()
        }
    }

    func readDeviceInfo() {
        let error = client.getDeviceInfo { [weak self] info in
            DispatchQueue.main.async {
                guard let info else {
                    self?.appendLog("设备信息回调为空")
                    return
                }

                let name = info.deviceName ?? "Rokid Glasses"
                let battery = info.batteryLevel.map { "\($0)%" } ?? "未知电量"
                let version = info.systemVersion ?? "未知固件"
                self?.deviceSummary = "\(name) · \(battery) · \(version)"
                self?.wearingStatus = info.wearingStatus ? "已佩戴" : "未佩戴"
                self?.appendLog("已读取眼镜设备信息")
            }
        }
        handleImmediateError(error, action: "读取设备信息")
    }

    func takePhoto() {
        requestPhoto(trigger: .manual, sessionID: nil)
    }

    func toggleAudioTest() {
        if isAudioTestRunning {
            stopAudioTest(reason: "USER_STOPPED")
        } else {
            startAudioTest()
        }
    }

    func startAudioTest() {
        guard isConnected, isCustomViewRunning, !isAudioTestRunning else {
            appendLog("无法开始音频测试：眼镜链路或 Custom View 未就绪")
            return
        }

        audioTestTask?.cancel()
        audioSegmenter.reset()
        isAudioTestRunning = true
        isAudioStreamStarted = false
        audioPacketCount = 0
        audioByteCount = 0
        audioLevelDBFS = nil
        isSpeechActive = false
        audioSegmentCount = 0
        lastAudioSummary = "等待眼镜 PCM 音频流"
        appendLog("开始 30 秒音频/VAD 测试")

        if let error = client.startRecord("stream", codec: .pcm, mode: .antClose) {
            isAudioTestRunning = false
            lastAudioSummary = "音频流启动失败：\(String(describing: error))"
            appendLog(lastAudioSummary)
            return
        }

        audioTestTask = Task { [weak self] in
            try? await Task.sleep(
                nanoseconds: UInt64(Self.audioTestSeconds * 1_000_000_000)
            )
            guard !Task.isCancelled else {
                return
            }
            self?.stopAudioTest(reason: "TEST_WINDOW_COMPLETED")
        }
    }

    func stopAudioTest(reason: String = "USER_STOPPED") {
        guard isAudioTestRunning else {
            return
        }

        audioTestTask?.cancel()
        audioTestTask = nil
        if let segment = audioSegmenter.finish() {
            recordAudioSegment(segment)
        }
        let error = client.stopRecord("stream")
        isAudioTestRunning = false
        isAudioStreamStarted = false
        isSpeechActive = false

        if let error {
            lastAudioSummary = "停止请求失败：\(String(describing: error))"
            appendLog(lastAudioSummary)
        } else {
            lastAudioSummary = "测试结束：\(audioPacketCount) 包，\(audioByteCount) 字节，\(audioSegmentCount) 段"
            appendLog("音频/VAD 测试结束：\(reason)")
        }
    }

    func setCaptureInterval(_ seconds: Int) {
        guard [5, 15, 30, 60].contains(seconds), sessionState != .active else {
            return
        }
        captureIntervalSeconds = seconds
        appendLog("采集间隔已设置为 \(seconds) 秒")
    }

    func setRetainLocalSamples(_ enabled: Bool) {
        guard sessionState != .active else {
            return
        }
        retainLocalSamples = enabled
        appendLog(enabled ? "本地样本保留已开启" : "本地样本保留已关闭")
    }

    func setGlassDebugOverlay(_ enabled: Bool) {
        guard !isCustomViewRunning else {
            return
        }
        showsGlassDebugOverlay = enabled
        appendLog(enabled ? "眼镜调试文字已开启" : "眼镜静默空白模式已开启")
    }

    func recordApplicationLifecycle(_ state: String) {
        guard applicationState != state else {
            return
        }
        applicationState = state
        appendLog("手机 App 生命周期：\(state)")
        mutateCurrentSession { session in
            session.auditEvents.append(
                ProbeAuditEvent(
                    id: UUID(),
                    occurredAt: Date(),
                    type: "APP_LIFECYCLE_CHANGED",
                    detail: state
                )
            )
        }
    }

    func startCaptureSession() {
        guard isConnected, isCustomViewRunning else {
            appendLog("无法开始 Session：眼镜链路或界面未就绪")
            return
        }

        captureLoopTask?.cancel()
        let now = Date()
        currentSession = ProbeCaptureSession(
            schemaVersion: "rme.capture-session.v1",
            id: UUID(),
            startedAt: now,
            endedAt: nil,
            state: .active,
            intervalSeconds: captureIntervalSeconds,
            retainLocalSamples: retainLocalSamples,
            localMediaTTLSeconds: retainLocalSamples ? 86_400 : 0,
            uploadAllowed: false,
            deviceSummaryAtStart: deviceSummary,
            observations: [],
            audioObservations: [],
            auditEvents: [
                ProbeAuditEvent(
                    id: UUID(),
                    occurredAt: now,
                    type: "SESSION_STARTED",
                    detail: "interval=\(captureIntervalSeconds)s"
                )
            ]
        )
        sessionState = .active
        capturedImage = nil
        persistCurrentSession()
        appendLog("采集 Session 已开始：每 \(captureIntervalSeconds) 秒")
        startCaptureLoop()
    }

    func pauseCaptureSession() {
        pauseCaptureSession(reason: "USER_PAUSED")
    }

    func resumeCaptureSession() {
        guard sessionState == .paused, isConnected, isCustomViewRunning else {
            appendLog("无法恢复 Session：眼镜链路或界面未就绪")
            return
        }

        sessionState = .active
        mutateCurrentSession { session in
            session.state = .active
            session.auditEvents.append(
                ProbeAuditEvent(
                    id: UUID(),
                    occurredAt: Date(),
                    type: "SESSION_RESUMED",
                    detail: nil
                )
            )
        }
        appendLog("采集 Session 已恢复")
        startCaptureLoop()
    }

    func endCaptureSession() {
        endCaptureSession(reason: "USER_ENDED")
    }

    func clearLog() {
        logs.removeAll()
    }

    private func bindEvents() {
        client.auth.statePublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in
                self?.applyAuthState(state)
            }
            .store(in: &cancellables)

        client.auth.eventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                self?.handleAuthEvent(event)
            }
            .store(in: &cancellables)

        client.audioEventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                self?.handleAudioEvent(event)
            }
            .store(in: &cancellables)

        RGCxrClientBLE.shared.connectionStatePublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] connected in
                guard let self else {
                    return
                }
                self.isConnected = connected
                self.linkStatus = connected ? "BLE 已连接" : "未连接"
                self.appendLog(connected ? "眼镜 BLE 链路已连接" : "眼镜 BLE 链路已断开")
                if !connected {
                    self.cancelPendingPhoto(reason: "BLE_DISCONNECTED")
                    self.stopAudioTest(reason: "BLE_DISCONNECTED")
                    if self.sessionState == .active {
                        self.pauseCaptureSession(reason: "BLE_DISCONNECTED")
                    }
                }
            }
            .store(in: &cancellables)

        client.customViewRunningEventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in
                guard let self else {
                    return
                }
                self.isCustomViewRunning = event.isRunning
                self.customViewStatus = event.isRunning ? "运行中" : "未打开"
                self.appendLog(event.isRunning ? "眼镜 Custom View 已打开" : "眼镜 Custom View 已关闭")
                if !event.isRunning {
                    self.cancelPendingPhoto(reason: "CUSTOM_VIEW_CLOSED")
                    self.stopAudioTest(reason: "CUSTOM_VIEW_CLOSED")
                    if self.sessionState == .active {
                        self.pauseCaptureSession(reason: "CUSTOM_VIEW_CLOSED")
                    }
                }
            }
            .store(in: &cancellables)

        client.wearingStatusEventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] isWearing in
                guard let self else {
                    return
                }
                self.wearingStatus = isWearing ? "已佩戴" : "未佩戴"
                self.appendLog(isWearing ? "收到佩戴事件" : "收到摘下事件")
                if !isWearing {
                    self.stopAudioTest(reason: "NOT_WEARING")
                }
                if !isWearing, self.sessionState == .active || self.sessionState == .paused {
                    self.endCaptureSession(reason: "NOT_WEARING")
                }
            }
            .store(in: &cancellables)
    }

    private func applyAuthState(_ state: RGCxrClientAuthState) {
        isAuthenticated = state.isAuthenticated

        switch state {
        case .notAuthenticated:
            isAuthenticating = false
            authStatus = "未授权"
        case .authenticating:
            isAuthenticating = true
            authStatus = "授权中"
        case .authenticated:
            isAuthenticating = false
            authStatus = "已授权"
        case .expired:
            isAuthenticating = false
            authStatus = "已过期"
        case .failed:
            isAuthenticating = false
            authStatus = "失败"
        @unknown default:
            isAuthenticating = false
            authStatus = "未知状态"
            appendLog("收到未知授权状态")
        }
    }

    private func handleAuthEvent(_ event: RGCxrClientAuthEvent) {
        switch event {
        case .stateChanged:
            break
        case .authenticationSucceeded(_, _, let deviceName):
            appendLog("授权设备：\(deviceName ?? "Rokid Glasses")")
        case .authenticationFailed(let error):
            appendLog("授权事件失败：\(error)")
        case .tokenExpired:
            appendLog("Rokid token 已过期")
        @unknown default:
            appendLog("收到未知授权事件")
        }
    }

    private func handleAudioEvent(_ event: RGCxrClientAudioEvent) {
        guard isAudioTestRunning else {
            return
        }

        switch event {
        case .started(let info):
            isAudioStreamStarted = true
            audioChannels = info.channels
            lastAudioSummary = "PCM 流已启动：\(info.channels) 声道，类型 \(info.type)"
            appendLog(lastAudioSummary)
        case .stream(let packet):
            audioPacketCount += 1
            audioByteCount += packet.data.count

            let result = audioSegmenter.process(packet.data)
            audioLevelDBFS = result.levelDBFS
            isSpeechActive = audioSegmenter.isSpeechActive
            if result.speechStarted {
                appendLog("VAD 检测到语音开始")
            }
            if let segment = result.completedSegment {
                recordAudioSegment(segment)
            }
        @unknown default:
            appendLog("收到未知音频事件")
        }
    }

    private func recordAudioSegment(_ segment: ProbeAudioSegment) {
        let observationID = UUID()
        audioSegmentCount += 1
        isSpeechActive = false
        lastAudioSummary = String(
            format: "片段 %d：%d ms，%d 字节，峰值 %.1f dBFS",
            audioSegmentCount,
            segment.durationMilliseconds,
            segment.data.count,
            segment.peakDBFS
        )
        appendLog("VAD 语音片段完成：\(lastAudioSummary)")

        guard let sessionID = currentSession?.id else {
            appendLog("当前没有采集 Session，仅保留音频测试指标")
            return
        }

        var localReference: String?
        if retainLocalSamples {
            do {
                localReference = try artifactStore.saveAudio(
                    segment.data,
                    sessionID: sessionID,
                    observationID: observationID
                )
            } catch {
                appendLog("音频样本写入失败：\(error.localizedDescription)")
            }
        }

        let observation = ProbeAudioObservation(
            id: observationID,
            sessionID: sessionID,
            startedAt: segment.startedAt,
            endedAt: segment.endedAt,
            durationMilliseconds: segment.durationMilliseconds,
            byteCount: segment.data.count,
            peakDBFS: segment.peakDBFS,
            codec: "PCM_S16LE_16KHZ",
            channels: audioChannels,
            localMediaReference: localReference,
            analysisState: localReference == nil ? "NOT_QUEUED" : "PENDING_LOCAL",
            applicationState: applicationState
        )

        mutateCurrentSession { session in
            session.audioObservations.append(observation)
            session.auditEvents.append(
                ProbeAuditEvent(
                    id: UUID(),
                    occurredAt: observation.endedAt,
                    type: "AUDIO_SEGMENT_COMPLETED",
                    detail: "duration=\(observation.durationMilliseconds)ms;bytes=\(observation.byteCount)"
                )
            )
        }
    }

    private func requestPhoto(
        trigger: ProbeCaptureTrigger,
        sessionID: UUID?,
        scheduledAt: Date = Date()
    ) {
        let observationID = UUID()

        guard canTakePhoto else {
            let reason = isPhotoPending ? "CAPTURE_IN_FLIGHT" : "CUSTOM_VIEW_NOT_READY"
            appendLog(
                isPhotoPending
                    ? "拍照跳过：正在等待上一张照片回调"
                    : "拍照跳过：眼镜 Custom View 未就绪"
            )
            if let sessionID {
                recordObservation(
                    id: observationID,
                    sessionID: sessionID,
                    scheduledAt: scheduledAt,
                    trigger: trigger,
                    outcome: .skipped,
                    reason: reason,
                    data: nil,
                    latencyMilliseconds: nil
                )
            }
            return
        }

        isPhotoPending = true
        let pendingRequest = PendingPhotoRequest(
            id: observationID,
            sessionID: sessionID,
            scheduledAt: scheduledAt,
            trigger: trigger
        )
        pendingPhotoRequest = pendingRequest
        startPhotoTimeout(for: pendingRequest)
        capturedImage = nil
        appendLog("正在请求 1024×768 照片，触发：\(trigger.rawValue)")

        let error = client.takePhotoWithData(
            width: 1024,
            height: 768,
            quality: 80
        ) { [weak self] data in
            DispatchQueue.main.async {
                guard let self else {
                    return
                }

                guard self.finishPendingPhoto(id: observationID) else {
                    self.appendLog("收到已取消或已超时照片的迟到回调，已忽略")
                    return
                }
                let latency = Int(Date().timeIntervalSince(scheduledAt) * 1_000)
                guard let image = UIImage(data: data) else {
                    self.appendLog("照片返回 \(data.count) 字节，但无法解码")
                    if let sessionID {
                        self.recordObservation(
                            id: observationID,
                            sessionID: sessionID,
                            scheduledAt: scheduledAt,
                            trigger: trigger,
                            outcome: .failed,
                            reason: "IMAGE_DECODE_FAILED",
                            data: data,
                            latencyMilliseconds: latency
                        )
                    }
                    return
                }

                self.capturedImage = image
                self.appendLog("照片接收成功：\(data.count) 字节，耗时 \(latency) ms")
                if let sessionID {
                    self.recordObservation(
                        id: observationID,
                        sessionID: sessionID,
                        scheduledAt: scheduledAt,
                        trigger: trigger,
                        outcome: .succeeded,
                        reason: nil,
                        data: data,
                        latencyMilliseconds: latency
                    )
                }
            }
        }

        if let error {
            guard finishPendingPhoto(id: observationID) else {
                appendLog("拍照同步错误对应的请求已经结束")
                return
            }
            handleImmediateError(error, action: "拍照")
            if let sessionID {
                recordObservation(
                    id: observationID,
                    sessionID: sessionID,
                    scheduledAt: scheduledAt,
                    trigger: trigger,
                    outcome: .failed,
                    reason: String(describing: error),
                    data: nil,
                    latencyMilliseconds: nil
                )
            }
        }
    }

    private func startCaptureLoop() {
        captureLoopTask?.cancel()
        captureLoopTask = Task { [weak self] in
            guard let self else {
                return
            }

            while !Task.isCancelled {
                let interval = self.captureIntervalSeconds
                let scheduledAt = Date().addingTimeInterval(TimeInterval(interval))
                self.nextCaptureAt = scheduledAt
                do {
                    try await Task.sleep(
                        nanoseconds: UInt64(interval) * 1_000_000_000
                    )
                } catch {
                    return
                }

                guard
                    !Task.isCancelled,
                    self.sessionState == .active,
                    let sessionID = self.currentSession?.id
                else {
                    return
                }

                let delay = Date().timeIntervalSince(scheduledAt)
                let toleratedDelay = max(2, TimeInterval(interval) * 0.5)
                if delay > toleratedDelay {
                    let delayMilliseconds = Int(delay * 1_000)
                    self.appendLog(
                        "定时采集跳过：调度晚到 \(delayMilliseconds) ms，"
                            + "App 状态：\(self.applicationState)"
                    )
                    self.recordObservation(
                        id: UUID(),
                        sessionID: sessionID,
                        scheduledAt: scheduledAt,
                        trigger: .periodic,
                        outcome: .skipped,
                        reason: "SCHEDULER_DELAYED_\(delayMilliseconds)MS",
                        data: nil,
                        latencyMilliseconds: nil
                    )
                    continue
                }

                self.requestPhoto(
                    trigger: .periodic,
                    sessionID: sessionID,
                    scheduledAt: scheduledAt
                )
            }
        }
    }

    private func pauseCaptureSession(reason: String) {
        guard sessionState == .active else {
            return
        }

        captureLoopTask?.cancel()
        captureLoopTask = nil
        nextCaptureAt = nil
        stopAudioTest(reason: reason)
        sessionState = .paused
        mutateCurrentSession { session in
            session.state = .paused
            session.auditEvents.append(
                ProbeAuditEvent(
                    id: UUID(),
                    occurredAt: Date(),
                    type: "SESSION_PAUSED",
                    detail: reason
                )
            )
        }
        appendLog("采集 Session 已暂停：\(reason)")
    }

    private func endCaptureSession(reason: String) {
        guard sessionState == .active || sessionState == .paused else {
            return
        }

        captureLoopTask?.cancel()
        captureLoopTask = nil
        nextCaptureAt = nil
        cancelPendingPhoto(reason: "SESSION_ENDED")
        stopAudioTest(reason: reason)
        sessionState = .ended
        mutateCurrentSession { session in
            session.state = .ended
            session.endedAt = Date()
            session.auditEvents.append(
                ProbeAuditEvent(
                    id: UUID(),
                    occurredAt: Date(),
                    type: "SESSION_ENDED",
                    detail: reason
                )
            )
        }
        appendLog("采集 Session 已结束：\(reason)")
    }

    private func recordObservation(
        id: UUID,
        sessionID: UUID,
        scheduledAt: Date,
        trigger: ProbeCaptureTrigger,
        outcome: ProbeCaptureOutcome,
        reason: String?,
        data: Data?,
        latencyMilliseconds: Int?
    ) {
        guard currentSession?.id == sessionID else {
            appendLog("忽略不属于当前 Session 的采集结果")
            return
        }

        var localReference: String?
        if
            outcome == .succeeded,
            retainLocalSamples,
            let data
        {
            do {
                localReference = try artifactStore.saveImage(
                    data,
                    sessionID: sessionID,
                    observationID: id
                )
            } catch {
                appendLog("本地样本写入失败：\(error.localizedDescription)")
            }
        }

        let observation = ProbeCaptureObservation(
            id: id,
            sessionID: sessionID,
            scheduledAt: scheduledAt,
            completedAt: Date(),
            trigger: trigger,
            outcome: outcome,
            reason: reason,
            byteCount: data?.count,
            captureLatencyMilliseconds: latencyMilliseconds,
            localMediaReference: localReference,
            analysisState: localReference == nil ? "NOT_QUEUED" : "PENDING_LOCAL",
            deviceSummary: deviceSummary,
            wearingStatus: wearingStatus,
            applicationState: applicationState
        )

        mutateCurrentSession { session in
            session.observations.append(observation)
            session.auditEvents.append(
                ProbeAuditEvent(
                    id: UUID(),
                    occurredAt: observation.completedAt,
                    type: "CAPTURE_\(outcome.rawValue)",
                    detail: reason
                )
            )
        }
    }

    private func mutateCurrentSession(_ mutation: (inout ProbeCaptureSession) -> Void) {
        guard var session = currentSession else {
            return
        }
        mutation(&session)
        currentSession = session
        persistCurrentSession()
    }

    private func persistCurrentSession() {
        guard let session = currentSession else {
            return
        }

        do {
            latestSessionURL = try artifactStore.saveSession(session)
        } catch {
            Self.logger.error(
                "Failed to persist session: \(error.localizedDescription, privacy: .public)"
            )
        }
    }

    private func openCustomView() {
        guard
            let payload = Self.makeCustomViewPayload(
                showsDebugOverlay: showsGlassDebugOverlay
            )
        else {
            appendLog("无法生成 Custom View JSON")
            return
        }

        appendLog(
            showsGlassDebugOverlay
                ? "正在打开带调试文字的 Custom View"
                : "正在打开静默空白 Custom View"
        )
        let error = client.openCustomView(payload) { [weak self] success, errorCode in
            DispatchQueue.main.async {
                if success {
                    self?.appendLog("Custom View 打开请求成功")
                } else {
                    self?.appendLog("Custom View 打开失败，错误码：\(errorCode.map { String($0) } ?? "未知")")
                }
            }
        }
        handleImmediateError(error, action: "打开 Custom View")
    }

    private func closeCustomView() {
        cancelPendingPhoto(reason: "CUSTOM_VIEW_CLOSE_REQUESTED")
        appendLog("正在关闭眼镜 Custom View")
        let error = client.closeCustomView { [weak self] success in
            DispatchQueue.main.async {
                self?.appendLog(success ? "Custom View 已关闭" : "Custom View 关闭失败")
            }
        }
        handleImmediateError(error, action: "关闭 Custom View")
    }

    private func startPhotoTimeout(for request: PendingPhotoRequest) {
        photoTimeoutTask?.cancel()
        photoTimeoutTask = Task { [weak self] in
            do {
                try await Task.sleep(
                    nanoseconds: UInt64(Self.photoTimeoutSeconds * 1_000_000_000)
                )
            } catch {
                return
            }

            guard
                let self,
                self.pendingPhotoRequest?.id == request.id
            else {
                return
            }

            self.pendingPhotoRequest = nil
            self.isPhotoPending = false
            self.photoTimeoutTask = nil
            let latency = Int(Date().timeIntervalSince(request.scheduledAt) * 1_000)
            self.appendLog("拍照等待超过 12 秒，已自动复位")
            if let sessionID = request.sessionID {
                self.recordObservation(
                    id: request.id,
                    sessionID: sessionID,
                    scheduledAt: request.scheduledAt,
                    trigger: request.trigger,
                    outcome: .failed,
                    reason: "CAPTURE_TIMEOUT",
                    data: nil,
                    latencyMilliseconds: latency
                )
            }
        }
    }

    @discardableResult
    private func finishPendingPhoto(id: UUID) -> Bool {
        guard pendingPhotoRequest?.id == id else {
            return false
        }
        photoTimeoutTask?.cancel()
        photoTimeoutTask = nil
        pendingPhotoRequest = nil
        isPhotoPending = false
        return true
    }

    private func cancelPendingPhoto(reason: String) {
        guard let request = pendingPhotoRequest else {
            return
        }

        photoTimeoutTask?.cancel()
        photoTimeoutTask = nil
        pendingPhotoRequest = nil
        isPhotoPending = false
        let latency = Int(Date().timeIntervalSince(request.scheduledAt) * 1_000)
        appendLog("在途拍照已取消：\(reason)")
        if let sessionID = request.sessionID {
            recordObservation(
                id: request.id,
                sessionID: sessionID,
                scheduledAt: request.scheduledAt,
                trigger: request.trigger,
                outcome: .failed,
                reason: reason,
                data: nil,
                latencyMilliseconds: latency
            )
        }
    }

    private func handleImmediateError(_ error: RGCxrClientError?, action: String) {
        if let error {
            appendLog("\(action)未启动：\(String(describing: error))")
        } else {
            appendLog("\(action)请求已发送")
        }
    }

    private func appendLog(_ message: String) {
        let item = ProbeLogItem(message: message)
        Self.logger.info("\(message, privacy: .public)")
        try? artifactStore.appendDebugLog(item)
        logs.insert(item, at: 0)
        if logs.count > 30 {
            logs.removeLast(logs.count - 30)
        }
    }

    private static func makeCustomViewPayload(showsDebugOverlay: Bool) -> String? {
        let children: [[String: Any]]
        if showsDebugOverlay {
            children = [
                [
                    "type": "TextView",
                    "props": [
                        "id": "statusText",
                        "layout_width": "wrap_content",
                        "layout_height": "wrap_content",
                        "text": "Reality Memory Probe",
                        "textColor": "#00FF00",
                        "textSize": "18sp",
                        "textStyle": "bold",
                        "gravity": "center"
                    ]
                ],
                [
                    "type": "TextView",
                    "props": [
                        "id": "detailText",
                        "layout_width": "wrap_content",
                        "layout_height": "wrap_content",
                        "text": "Capture link ready",
                        "textColor": "#00CC66",
                        "textSize": "14sp",
                        "gravity": "center",
                        "marginTop": "12dp"
                    ]
                ]
            ]
        } else {
            children = []
        }

        let payload: [String: Any] = [
            "type": "LinearLayout",
            "props": [
                "id": "root",
                "layout_width": "match_parent",
                "layout_height": "match_parent",
                "orientation": "vertical",
                "gravity": "center",
                "backgroundColor": "#FF000000"
            ],
            "children": children
        ]

        guard
            let data = try? JSONSerialization.data(withJSONObject: payload),
            let string = String(data: data, encoding: .utf8)
        else {
            return nil
        }
        return string
    }
}

struct ProbeLogItem: Identifiable, Codable {
    let id: UUID
    let date: Date
    let message: String

    init(id: UUID = UUID(), date: Date = Date(), message: String) {
        self.id = id
        self.date = date
        self.message = message
    }

    var time: String {
        Self.formatter.string(from: date)
    }

    private static let formatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        return formatter
    }()
}
