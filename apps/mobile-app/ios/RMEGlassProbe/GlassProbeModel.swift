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
        let triggerDecisionID: UUID?
    }

    private struct ActiveRingAudioWindow {
        let decisionID: UUID
        let startedAt: Date
        var endsAt: Date
        var data: Data
        var peakDBFS: Double
    }

    private struct RingPhotoBurstPlan {
        let tier: String
        let displayName: String
        let imageCount: Int
        let intensityRatio: Double
        let acceleratedIntervalSeconds: Int
        let acceleratedWindowSeconds: TimeInterval
    }

    private enum AudioCaptureMode: Equatable {
        case manualTest
        case sessionVAD
        case ringTriggered(UUID)

        var displayName: String {
            switch self {
            case .manualTest:
                "测试采集中"
            case .sessionVAD:
                "Session 采集中"
            case .ringTriggered:
                "戒指触发采集中"
            }
        }

        var isManualTest: Bool {
            self == .manualTest
        }

        var isSessionVAD: Bool {
            self == .sessionVAD
        }

        var triggerDecisionID: UUID? {
            if case .ringTriggered(let decisionID) = self {
                return decisionID
            }
            return nil
        }
    }

    private static let logger = Logger(
        subsystem: "com.realitymemoryengine.RMEGlassProbe",
        category: "Capture"
    )
    private static let photoTimeoutSeconds: TimeInterval = 12
    private static let audioTestSeconds: TimeInterval = 30
    private static let ringTriggeredAudioWindowSeconds: TimeInterval = 8
    private static let ringPhotoBurstPolicyVersion = "relative-motion-adaptive-capture.v2"
    private static let acceleratedCaptureIntervalSeconds = 8
    private static let normalAttentionWindowSeconds: TimeInterval = 20
    private static let strongAttentionWindowSeconds: TimeInterval = 30

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
    @Published private(set) var isSessionAudioEnabled = false
    @Published private(set) var isSessionAudioRunning = false
    @Published private(set) var isAudioStreamStarted = false
    @Published private(set) var audioPacketCount = 0
    @Published private(set) var audioByteCount = 0
    @Published private(set) var audioLevelDBFS: Double?
    @Published private(set) var isSpeechActive = false
    @Published private(set) var audioSegmentCount = 0
    @Published private(set) var lastAudioSummary = "尚未测试"
    @Published private(set) var desktopDebugStatus = "正在寻找电脑调试台"
    @Published private(set) var ringBluetoothStatus = "正在读取蓝牙状态"
    @Published private(set) var ringConnectionStatus = "未连接"
    @Published private(set) var ringDevices: [RingDiscoveredDevice] = []
    @Published private(set) var selectedRingDeviceID: UUID?
    @Published private(set) var isRingConnected = false
    @Published private(set) var isRingSensorReporting = false
    @Published private(set) var ringIdentityStatus = "尚未验证戒指身份"
    @Published private(set) var ringSensorConfiguration: RingSensorConfiguration?
    @Published private(set) var ringBatchCount = 0
    @Published private(set) var ringSampleCount = 0
    @Published private(set) var ringSequenceGapCount = 0
    @Published private(set) var ringAccelerationMagnitude: Double?
    @Published private(set) var ringGyroscopeMagnitude: Double?
    @Published private(set) var ringAccelerationDelta: Double?
    @Published private(set) var ringAccelerationBaseline: Double?
    @Published private(set) var ringGyroscopeBaseline: Double?
    @Published private(set) var ringAccelerationDynamicThreshold: Double?
    @Published private(set) var ringGyroscopeDynamicThreshold: Double?
    @Published private(set) var ringRelativeChangeScore: Double?
    @Published private(set) var ringMotionContextState = "CALIBRATING"
    @Published private(set) var ringRotationExcursionDegrees: Double?
    @Published private(set) var ringGravityTiltDegrees: Double?
    @Published private(set) var ringEndingGyroscopeDPS: Double?
    @Published private(set) var lastRingJudgement = "尚未收到戒指动作数据"
    @Published private(set) var lastRingJudgementAt: Date?
    @Published private(set) var lastRingEvent = "尚未收到戒指事件"
    @Published private(set) var ringSensorAutoStartEnabled = true
    @Published private(set) var ringRapidMovementTriggerEnabled = true
    @Published private(set) var ringTriggeredAudioEnabled = true
    @Published private(set) var ringSensitivity: ProbeRingSensitivity = .medium
    @Published private(set) var ringMountPosition: ProbeRingMountPosition = .glassesMounted

    private let client: any RGCxrClient
    private let artifactStore = ProbeArtifactStore()
    private let ringAdapter = RingDeviceAdapter()
    private let debugBridge = PhoneDebugBridge()
    private var cancellables = Set<AnyCancellable>()
    private var captureLoopTask: Task<Void, Never>?
    private var photoTimeoutTask: Task<Void, Never>?
    private var pendingPhotoRequest: PendingPhotoRequest?
    private var audioTestTask: Task<Void, Never>?
    private var ringAudioStopTask: Task<Void, Never>?
    private var audioCaptureMode: AudioCaptureMode?
    private var activeRingAudioWindow: ActiveRingAudioWindow?
    private let audioSegmenter = ProbeAudioSpeechSegmenter()
    private var audioChannels: UInt32 = 1
    private var ringMotionDetector = RingRapidMovementDetector()
    private var nextExpectedRingSequence: UInt32?
    private var ringSystemInfo: RingSystemInfo?
    private var debugSnapshotTask: Task<Void, Never>?
    private var acceleratedCaptureUntil: Date?
    private var acceleratedCaptureRearmRequired = false
    private var stableBatchesAfterAcceleration = 0

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
        isConnected && isCustomViewRunning && !isPhotoPending && sessionState != .active && !isAudioTestRunning
    }

    var canStartRingLinkedCapture: Bool {
        canStartSession && isRingConnected && isRingSensorReporting
    }

    var ringLinkedCaptureReadiness: String {
        if sessionState == .active {
            return "联动采集中"
        }
        if !isRingConnected {
            return "等待戒指连接"
        }
        if !isRingSensorReporting {
            return "等待戒指六轴数据"
        }
        if !isConnected {
            return "等待眼镜连接"
        }
        if !isCustomViewRunning {
            return "等待打开眼镜采集界面"
        }
        if isPhotoPending {
            return "等待当前拍照完成"
        }
        if isAudioTestRunning {
            return "请先结束独立音频测试"
        }
        return "已就绪：快速移动将触发图片和 8 秒短音频"
    }

    var canToggleAudioTest: Bool {
        isAudioTestRunning || (audioCaptureMode == nil && isConnected && isCustomViewRunning)
    }

    var canScanRing: Bool {
        !isRingConnected && ringConnectionStatus != "扫描中" && ringConnectionStatus != "连接中"
    }

    var canConnectSelectedRing: Bool {
        selectedRingDeviceID != nil && !isRingConnected
    }

    var selectedRingDevice: RingDiscoveredDevice? {
        ringDevices.first { $0.id == selectedRingDeviceID }
    }

    var audioStreamStatus: String {
        guard let audioCaptureMode else {
            return "未启动"
        }
        return audioCaptureMode.displayName
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
            options: .init(appDisplayName: "Reality Memory", pageName: nil)
        )
        client = CxrClient.shared

        bindDebugBridge()
        bindEvents()
        bindRingAdapter()
        debugBridge.start()
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
            appName: "Reality Memory"
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
        stopAudioCapture(reason: "AUTHENTICATION_CLEARED")
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
        requestPhoto(trigger: .manual, sessionID: nil, triggerDecisionID: nil)
    }

    func scanRingDevices() {
        ringAdapter.scan()
    }

    func selectRingDevice(_ id: UUID?) {
        guard !isRingConnected else {
            return
        }
        selectedRingDeviceID = id
    }

    func connectSelectedRing() {
        guard let selectedRingDeviceID else {
            appendLog("请先扫描并选择戒指")
            return
        }
        ringAdapter.connect(deviceID: selectedRingDeviceID)
    }

    func disconnectRing() {
        ringAdapter.disconnect()
    }

    func startRingSensorReport() {
        guard isRingConnected else {
            appendLog("请先连接戒指")
            return
        }
        ringSensorAutoStartEnabled = true
        ringMotionDetector.reset()
        nextExpectedRingSequence = nil
        ringAdapter.startSensorReport()
    }

    func stopRingSensorReport() {
        ringSensorAutoStartEnabled = false
        ringAdapter.stopSensorReport()
    }

    func setRingSensorAutoStartEnabled(_ enabled: Bool) {
        ringSensorAutoStartEnabled = enabled
        if enabled, isRingConnected, !isRingSensorReporting {
            startRingSensorReport()
        } else if !enabled, isRingSensorReporting {
            ringAdapter.stopSensorReport()
        }
    }

    func setRingRapidMovementTriggerEnabled(_ enabled: Bool) {
        guard sessionState != .active else {
            return
        }
        ringRapidMovementTriggerEnabled = enabled
        appendLog(enabled ? "戒指快速移动触发已开启" : "戒指快速移动触发已关闭")
    }

    func setRingTriggeredAudioEnabled(_ enabled: Bool) {
        guard sessionState != .active else {
            return
        }
        ringTriggeredAudioEnabled = enabled
        appendLog(enabled ? "戒指触发短音频已开启" : "戒指触发短音频已关闭")
    }

    func setRingSensitivity(_ sensitivity: ProbeRingSensitivity) {
        guard sessionState != .active else {
            return
        }
        ringSensitivity = sensitivity
        ringMotionDetector.reset()
        appendLog("戒指快速移动灵敏度已设置为\(sensitivity.displayName)")
    }

    func toggleAudioTest() {
        if isAudioTestRunning {
            stopAudioTest(reason: "USER_STOPPED")
        } else {
            startAudioTest()
        }
    }

    func startAudioTest() {
        guard isConnected, isCustomViewRunning, audioCaptureMode == nil else {
            appendLog("无法开始音频测试：眼镜链路或 Custom View 未就绪")
            return
        }

        guard startAudioCapture(mode: .manualTest) else {
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
        guard audioCaptureMode?.isManualTest == true else {
            return
        }
        stopAudioCapture(reason: reason)
    }

    func setSessionAudioEnabled(_ enabled: Bool) {
        guard sessionState != .active else {
            return
        }
        isSessionAudioEnabled = enabled
        appendLog(enabled ? "会话内短音频/VAD 已开启" : "会话内短音频/VAD 已关闭")
    }

    private func startSessionAudioIfNeeded() {
        guard isSessionAudioEnabled else {
            return
        }
        guard currentSession != nil else {
            appendLog("无法开始会话音频：当前没有采集 Session")
            return
        }
        _ = startAudioCapture(mode: .sessionVAD)
    }

    @discardableResult
    private func startAudioCapture(mode: AudioCaptureMode) -> Bool {
        guard isConnected, isCustomViewRunning, audioCaptureMode == nil else {
            appendLog("无法开始音频/VAD：眼镜链路、界面或现有音频流状态不满足")
            return false
        }

        audioTestTask?.cancel()
        ringAudioStopTask?.cancel()
        audioSegmenter.reset()
        audioCaptureMode = mode
        isAudioTestRunning = mode.isManualTest
        isSessionAudioRunning = mode.isSessionVAD || mode.triggerDecisionID != nil
        isAudioStreamStarted = false
        audioPacketCount = 0
        audioByteCount = 0
        audioLevelDBFS = nil
        isSpeechActive = false
        audioSegmentCount = 0
        switch mode {
        case .manualTest:
            lastAudioSummary = "等待眼镜 PCM 音频流"
            appendLog("开始 30 秒音频/VAD 测试")
        case .sessionVAD:
            lastAudioSummary = "等待眼镜 PCM 音频流（会话内 VAD）"
            appendLog("开始会话内短音频/VAD")
        case .ringTriggered:
            lastAudioSummary = "等待眼镜 PCM 音频流（戒指触发窗口）"
            appendLog("戒指快速移动已触发 8 秒短音频窗口")
        }

        if let error = client.startRecord("stream", codec: .pcm, mode: .antClose) {
            audioCaptureMode = nil
            isAudioTestRunning = false
            isSessionAudioRunning = false
            lastAudioSummary = "音频流启动失败：\(String(describing: error))"
            appendLog(lastAudioSummary)
            return false
        }

        return true
    }

    private func stopAudioCapture(reason: String) {
        guard let mode = audioCaptureMode else {
            return
        }

        audioTestTask?.cancel()
        audioTestTask = nil
        ringAudioStopTask?.cancel()
        ringAudioStopTask = nil
        if activeRingAudioWindow != nil {
            finalizeRingTriggeredAudioWindow(endedAt: Date())
        }
        if let segment = audioSegmenter.finish() {
            if mode.triggerDecisionID == nil {
                recordAudioSegment(segment)
            }
        }
        let error = client.stopRecord("stream")
        isAudioTestRunning = false
        isSessionAudioRunning = false
        isAudioStreamStarted = false
        isSpeechActive = false
        audioCaptureMode = nil
        activeRingAudioWindow = nil

        if let error {
            lastAudioSummary = "停止请求失败：\(String(describing: error))"
            appendLog(lastAudioSummary)
        } else {
            let label: String
            switch mode {
            case .manualTest:
                label = "音频/VAD 测试"
            case .sessionVAD:
                label = "会话内短音频/VAD"
            case .ringTriggered:
                label = "戒指触发短音频"
            }
            lastAudioSummary = "\(label)结束：\(audioPacketCount) 包，\(audioByteCount) 字节，\(audioSegmentCount) 段"
            appendLog("\(label)结束：\(reason)")
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
            audioPolicy: ProbeAudioPolicySnapshot(
                sessionVADEnabled: isSessionAudioEnabled,
                streamCodec: "PCM_S16LE_16KHZ",
                vadThresholdDBFS: ProbeAudioSpeechSegmenter.thresholdDBFS,
                speechStartFrames: ProbeAudioSpeechSegmenter.speechStartFrames,
                silenceEndMilliseconds: Int(ProbeAudioSpeechSegmenter.silenceEndSeconds * 1_000),
                maxSegmentMilliseconds: Int(ProbeAudioSpeechSegmenter.maxSegmentSeconds * 1_000),
                minSegmentMilliseconds: Int(ProbeAudioSpeechSegmenter.minSegmentSeconds * 1_000),
                maxPreRollBytes: ProbeAudioSpeechSegmenter.maxPreRollBytes,
                rawAudioPersistedOnlyWhenRetainLocalSamples: true
            ),
            ringPolicy: ProbeRingPolicySnapshot(
                mountPosition: ringMountPosition,
                sensorCollectionEnabled: isRingSensorReporting,
                rapidMovementTriggerEnabled: ringRapidMovementTriggerEnabled,
                triggeredAudioEnabled: ringTriggeredAudioEnabled,
                sensitivity: ringSensitivity,
                accelerationDeltaThresholdRaw: ringSensitivity.accelerationNoiseFloor,
                gyroscopeMagnitudeThresholdRaw: ringSensitivity.gyroscopeNoiseFloor,
                triggerCooldownMilliseconds: Int(
                    (
                        ringMountPosition == .glassesMounted
                            ? RingRapidMovementDetector.headTriggerCooldownSeconds
                            : RingRapidMovementDetector.triggerCooldownSeconds
                    ) * 1_000
                ),
                triggeredAudioWindowMilliseconds: Int(
                    Self.ringTriggeredAudioWindowSeconds * 1_000
                ),
                detectorRuleVersion: RingRapidMovementDetector.ruleVersion,
                baselineWindowBatchCount: RingRapidMovementDetector.baselineWindowBatchCount,
                relativeChangeThreshold: ringSensitivity.relativeChangeThreshold,
                strongRelativeChangeThreshold: ringSensitivity.strongRelativeChangeThreshold,
                accelerationNoiseFloorRaw: ringSensitivity.accelerationNoiseFloor,
                gyroscopeNoiseFloorRaw: ringSensitivity.gyroscopeNoiseFloor,
                strongTriggerCooldownMilliseconds: Int(
                    RingRapidMovementDetector.strongTriggerCooldownSeconds * 1_000
                ),
                minimumAccelerationForTriggerRaw:
                    ringSensitivity.minimumAccelerationForTrigger,
                minimumGyroscopeForTriggerRaw:
                    ringSensitivity.minimumGyroscopeForTrigger,
                normalConfirmationBatchCount: 2,
                headRotationExcursionThresholdDegrees:
                    ringSensitivity.headRotationExcursionThresholdDegrees,
                headGravityTiltThresholdDegrees:
                    ringSensitivity.headGravityTiltThresholdDegrees,
                headMovementStartDPS:
                    ringSensitivity.headMovementStartDPS,
                headSettleDPS: ringSensitivity.headSettleDPS,
                headSettleDurationMilliseconds: Int(
                    RingRapidMovementDetector.headSettleDurationSeconds * 1_000
                )
            ),
            deviceSummaryAtStart: deviceSummary,
            observations: [],
            audioObservations: [],
            ringSensor: makeRingSensorSnapshot(),
            ringDataReference: nil,
            ringBatchCount: 0,
            ringSampleCount: 0,
            ringSequenceGapCount: 0,
            ringMotionAssessments: [],
            ringHardwareEvents: [],
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
        ringBatchCount = 0
        ringSampleCount = 0
        ringSequenceGapCount = 0
        nextExpectedRingSequence = nil
        ringMotionDetector.reset()
        acceleratedCaptureUntil = nil
        acceleratedCaptureRearmRequired = false
        stableBatchesAfterAcceleration = 0
        persistCurrentSession()
        appendLog("采集 Session 已开始：每 \(captureIntervalSeconds) 秒")
        if ringRapidMovementTriggerEnabled, !isRingSensorReporting {
            appendLog("戒指联动尚未采集：请先连接戒指并开启传感器")
        }
        startSessionAudioIfNeeded()
        startCaptureLoop()
    }

    func startRingLinkedCapture() {
        guard canStartRingLinkedCapture else {
            appendLog("无法开始戒指联动采集：\(ringLinkedCaptureReadiness)")
            return
        }
        retainLocalSamples = true
        ringRapidMovementTriggerEnabled = true
        ringTriggeredAudioEnabled = true
        appendLog("戒指联动采集已配置：保留本地样本、触发图片和 8 秒短音频")
        startCaptureSession()
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
        startSessionAudioIfNeeded()
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
                    self.stopAudioCapture(reason: "BLE_DISCONNECTED")
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
                    self.stopAudioCapture(reason: "CUSTOM_VIEW_CLOSED")
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
                    self.stopAudioCapture(reason: "NOT_WEARING")
                }
                if !isWearing, self.sessionState == .active || self.sessionState == .paused {
                    self.endCaptureSession(reason: "NOT_WEARING")
                }
            }
            .store(in: &cancellables)
    }

    private func bindRingAdapter() {
        ringAdapter.onStateChanged = { [weak self] state in
            Task { @MainActor [weak self] in
                guard let self else {
                    return
                }
                let wasConnected = self.isRingConnected
                self.ringConnectionStatus = state.displayName
                self.isRingConnected = state.isConnected
                self.isRingSensorReporting = state.isSensorReporting
                self.appendLog("戒指状态：\(state.displayName)")
                switch state {
                case .bluetoothUnavailable(let reason):
                    self.ringBluetoothStatus = reason
                default:
                    self.ringBluetoothStatus = "可用"
                }
                if wasConnected, !state.isConnected {
                    self.mutateCurrentSession { session in
                        session.auditEvents.append(
                            ProbeAuditEvent(
                                id: UUID(),
                                occurredAt: Date(),
                                type: "RING_DISCONNECTED",
                                detail: state.displayName
                            )
                        )
                    }
                }
            }
        }

        ringAdapter.onDevicesChanged = { [weak self] devices in
            Task { @MainActor [weak self] in
                guard let self else {
                    return
                }
                self.ringDevices = devices
                if
                    self.selectedRingDeviceID == nil
                        || !devices.contains(where: { $0.id == self.selectedRingDeviceID })
                {
                    self.selectedRingDeviceID = devices.first?.id
                }
                self.scheduleDebugSnapshot()
            }
        }

        ringAdapter.onSystemInfo = { [weak self] systemInfo in
            Task { @MainActor [weak self] in
                guard let self else {
                    return
                }
                self.ringSystemInfo = systemInfo
                self.ringIdentityStatus =
                    "\(systemInfo.displayName) · SN 尾号 \(systemInfo.serialNumberSuffix) · "
                    + "\(systemInfo.batteryPercent)%"
                if self.ringSensorAutoStartEnabled {
                    try? await Task.sleep(nanoseconds: 350_000_000)
                    guard self.isRingConnected, !self.isRingSensorReporting else {
                        return
                    }
                    self.startRingSensorReport()
                }
            }
        }

        ringAdapter.onSensorConfiguration = { [weak self] configuration in
            Task { @MainActor [weak self] in
                guard let self else {
                    return
                }
                self.ringSensorConfiguration = configuration
                self.ringMotionDetector.reset()
                self.nextExpectedRingSequence = nil
                self.mutateCurrentSession { session in
                    session.ringSensor = self.makeRingSensorSnapshot()
                    session.auditEvents.append(
                        ProbeAuditEvent(
                            id: UUID(),
                            occurredAt: Date(),
                            type: "RING_SENSOR_REPORT_STARTED",
                            detail: "sampleRate=\(configuration.sampleRateHz)Hz"
                        )
                    )
                }
            }
        }

        ringAdapter.onIMUBatch = { [weak self] batch, receivedAt in
            Task { @MainActor [weak self] in
                self?.handleRingIMUBatch(batch, receivedAt: receivedAt)
            }
        }

        ringAdapter.onHardwareEvent = { [weak self] event in
            Task { @MainActor [weak self] in
                guard let self else {
                    return
                }
                let eventName = event.detail ?? event.type
                self.lastRingEvent = eventName
                self.appendLog("戒指事件：\(eventName)")
                if
                    event.type == "RING_KEY_SINGLE_PRESS",
                    self.ringSensorAutoStartEnabled,
                    self.isRingConnected,
                    !self.isRingSensorReporting
                {
                    Task { @MainActor [weak self] in
                        try? await Task.sleep(nanoseconds: 700_000_000)
                        guard
                            let self,
                            self.ringSensorAutoStartEnabled,
                            self.isRingConnected,
                            !self.isRingSensorReporting
                        else {
                            return
                        }
                        self.appendLog("检测到模式切换按键，自动重试开启六轴数据")
                        self.startRingSensorReport()
                    }
                }
                guard self.sessionState == .active, self.currentSession != nil else {
                    return
                }
                self.mutateCurrentSession { session in
                    session.ringHardwareEvents.append(
                        ProbeRingHardwareEventRecord(
                            id: UUID(),
                            occurredAt: event.occurredAt,
                            deviceTimestampMilliseconds: event.deviceTimestampMilliseconds,
                            type: event.type,
                            detail: event.detail
                        )
                    )
                }
            }
        }

        ringAdapter.onLog = { [weak self] message in
            Task { @MainActor [weak self] in
                self?.appendLog(message)
            }
        }
    }

    private func handleRingIMUBatch(_ batch: RingIMUBatch, receivedAt: Date) {
        ringBatchCount += 1
        ringSampleCount += batch.samples.count

        if let expected = nextExpectedRingSequence, batch.sequenceStart != expected {
            ringSequenceGapCount += 1
            appendLog("戒指序号不连续：期望 \(expected)，收到 \(batch.sequenceStart)")
        }
        nextExpectedRingSequence = batch.sequenceStart &+ UInt32(batch.frameCount)

        let result = ringMotionDetector.process(
            batch: batch,
            receivedAt: receivedAt,
            sensitivity: ringSensitivity,
            configuration: ringSensorConfiguration,
            mountPosition: ringMountPosition
        )
        ringAccelerationMagnitude = result.metrics?.accelerationMagnitude
        ringGyroscopeMagnitude = result.metrics?.gyroscopeMagnitude
        ringAccelerationDelta = result.metrics?.accelerationDelta
        ringAccelerationBaseline = result.metrics?.accelerationBaseline
        ringGyroscopeBaseline = result.metrics?.gyroscopeBaseline
        ringAccelerationDynamicThreshold = result.metrics?.accelerationDynamicThreshold
        ringGyroscopeDynamicThreshold = result.metrics?.gyroscopeDynamicThreshold
        ringRelativeChangeScore = result.metrics?.relativeChangeScore
        ringMotionContextState = result.metrics?.contextState ?? "CALIBRATING"
        ringRotationExcursionDegrees = result.metrics?.rotationExcursionDegrees
        ringGravityTiltDegrees = result.metrics?.gravityTiltDegrees
        ringEndingGyroscopeDPS = result.metrics?.endingGyroscopeDPS
        updateAcceleratedCaptureState(
            receivedAt: receivedAt,
            contextState: ringMotionContextState
        )
        debugBridge.send(
            type: "ringBatch",
            payload: LiveDebugRingBatch(
                receivedAt: receivedAt,
                configuration: ringSensorConfiguration,
                accelerationDeltaThresholdRaw:
                    result.metrics?.accelerationDynamicThreshold
                    ?? ringSensitivity.accelerationNoiseFloor
                        * ringSensitivity.relativeChangeThreshold,
                gyroscopeMagnitudeThresholdRaw:
                    result.metrics?.gyroscopeDynamicThreshold
                    ?? ringSensitivity.gyroscopeNoiseFloor
                        * ringSensitivity.relativeChangeThreshold,
                batch: batch
            )
        )
        scheduleDebugSnapshot()

        guard sessionState == .active, let sessionID = currentSession?.id else {
            if let detection = result.detection {
                lastRingJudgement = ringJudgementSummary(detection, suffix: "未在采集 Session 中，不触发眼镜")
                lastRingJudgementAt = detection.detectedAt
            }
            return
        }

        var ringDataReference: String?
        if retainLocalSamples {
            do {
                ringDataReference = try artifactStore.appendRingBatch(
                    ProbeRingIMUBatchRecord(
                        schemaVersion: "rme.ring-imu-batch.v1",
                        sessionID: sessionID,
                        sourceEnvelopeID: UUID(),
                        deviceID: selectedRingDeviceID?.uuidString.lowercased() ?? "unknown",
                        receivedAt: receivedAt,
                        sequenceStart: batch.sequenceStart,
                        frameCount: batch.frameCount,
                        sampleSize: batch.sampleSize,
                        samples: batch.samples
                    )
                )
            } catch {
                appendLog("戒指原始数据写入失败：\(error.localizedDescription)")
            }
        }

        mutateCurrentSession { session in
            session.ringBatchCount += 1
            session.ringSampleCount += batch.samples.count
            session.ringSequenceGapCount = ringSequenceGapCount
            if let ringDataReference {
                session.ringDataReference = ringDataReference
            }
        }

        if let detection = result.detection {
            handleRingRapidMovement(detection, sessionID: sessionID)
        }
    }

    private func handleRingRapidMovement(
        _ detection: RingRapidMovementDetection,
        sessionID: UUID
    ) {
        let decisionID = UUID()
        let captureRequested =
            ringRapidMovementTriggerEnabled
            && !acceleratedCaptureRearmRequired
        let burstPlan = ringPhotoBurstPlan(for: detection)
        let requestedModalities = captureRequested
            ? (ringTriggeredAudioEnabled ? ["IMAGE", "AUDIO"] : ["IMAGE"])
            : []
        let suppressionReason: String?
        if captureRequested {
            suppressionReason = nil
        } else if acceleratedCaptureRearmRequired {
            suppressionReason = "WAITING_FOR_RELATIVE_STABILITY"
        } else {
            suppressionReason = "RING_TRIGGER_DISABLED"
        }

        lastRingJudgement = ringJudgementSummary(
            detection,
            suffix: captureRequested
                ? (
                    detection.mountPosition == .glassesMounted
                        ? "\(burstPlan.displayName)，拍摄一张代表图"
                        : "\(burstPlan.displayName)，立即拍照并进入 \(Int(burstPlan.acceleratedWindowSeconds)) 秒关注窗口"
                )
                : "仅记录判断，未开启联动"
        )
        lastRingJudgementAt = detection.detectedAt
        appendLog("戒指判断：\(lastRingJudgement)")

        mutateCurrentSession { session in
            session.ringMotionAssessments.append(
                ProbeRingMotionAssessment(
                    id: decisionID,
                    sessionID: sessionID,
                    windowStartedAt: detection.windowStartedAt,
                    windowEndedAt: detection.windowEndedAt,
                    detectedAt: detection.detectedAt,
                    classification:
                        detection.mountPosition == .glassesMounted
                            ? "HEAD_POSE_TRANSITION_SETTLED"
                            : "RELATIVE_MOTION_CHANGE",
                    displayLabel:
                        detection.mountPosition == .glassesMounted
                            ? (detection.sustainedMotion == true
                                ? "持续运动结束并回稳"
                                : "头部转向后回稳")
                            : (detection.isStrongChange
                                ? "强烈运动突变"
                                : "运动状态变化"),
                    sampleCount: detection.sampleCount,
                    peakAccelerationDeltaRaw: detection.peakAccelerationDelta,
                    peakGyroscopeMagnitudeRaw: detection.peakGyroscopeMagnitude,
                    detectorRuleVersion:
                        detection.mountPosition == .glassesMounted
                            ? RingRapidMovementDetector.ruleVersion
                            : RingRapidMovementDetector.legacyRuleVersion,
                    sensitivity: detection.sensitivity,
                    captureRequested: captureRequested,
                    requestedModalities: requestedModalities,
                    suppressionReason: suppressionReason,
                    motionIntensityRatio: burstPlan.intensityRatio,
                    captureTier: burstPlan.tier,
                    requestedImageCount: burstPlan.imageCount,
                    capturePolicyVersion: Self.ringPhotoBurstPolicyVersion,
                    accelerationBaselineRaw: detection.accelerationBaseline,
                    gyroscopeBaselineRaw: detection.gyroscopeBaseline,
                    relativeChangeScore: detection.relativeChangeScore,
                    isStrongChange: detection.isStrongChange,
                    acceleratedCaptureIntervalMilliseconds:
                        burstPlan.acceleratedIntervalSeconds * 1_000,
                    acceleratedCaptureWindowMilliseconds:
                        Int(burstPlan.acceleratedWindowSeconds * 1_000),
                    mountPosition: detection.mountPosition,
                    rotationExcursionDegrees:
                        detection.rotationExcursionDegrees,
                    gravityTiltDegrees: detection.gravityTiltDegrees,
                    endingGyroscopeDPS: detection.endingGyroscopeDPS,
                    sustainedMotion: detection.sustainedMotion
                )
            )
            session.auditEvents.append(
                ProbeAuditEvent(
                    id: UUID(),
                    occurredAt: detection.detectedAt,
                    type: "RING_RAPID_MOVEMENT_DETECTED",
                    detail:
                        "decision=\(decisionID.uuidString.lowercased());"
                        + "tier=\(burstPlan.tier);"
                        + "ratio=\(String(format: "%.2f", burstPlan.intensityRatio));"
                        + "mount=\(detection.mountPosition.rawValue);"
                        + "rotationDegrees=\(String(format: "%.1f", detection.rotationExcursionDegrees ?? 0));"
                        + "gravityTiltDegrees=\(String(format: "%.1f", detection.gravityTiltDegrees ?? 0));"
                        + "interval=\(burstPlan.acceleratedIntervalSeconds)s;"
                        + "window=\(Int(burstPlan.acceleratedWindowSeconds))s"
                )
            )
        }

        guard captureRequested else {
            return
        }
        requestPhoto(
            trigger: .ringMotion,
            sessionID: sessionID,
            triggerDecisionID: decisionID,
            scheduledAt: detection.detectedAt
        )
        if burstPlan.acceleratedWindowSeconds > 0 {
            activateAcceleratedCapture(plan: burstPlan)
        }
        if ringTriggeredAudioEnabled {
            beginRingTriggeredAudioWindow(
                decisionID: decisionID,
                startedAt: detection.detectedAt
            )
        }
    }

    private func ringPhotoBurstPlan(
        for detection: RingRapidMovementDetection
    ) -> RingPhotoBurstPlan {
        if detection.mountPosition == .glassesMounted {
            return RingPhotoBurstPlan(
                tier: detection.sustainedMotion == true
                    ? "POST_SUSTAINED_MOTION"
                    : "HEAD_POSE_SETTLED",
                displayName: detection.sustainedMotion == true
                    ? "持续运动结束后视线已稳定"
                    : "头部转向后视线已稳定",
                imageCount: 1,
                intensityRatio: detection.relativeChangeScore,
                acceleratedIntervalSeconds: Self.acceleratedCaptureIntervalSeconds,
                acceleratedWindowSeconds: 0
            )
        }
        if detection.isStrongChange {
            return RingPhotoBurstPlan(
                tier: "STRONG_RELATIVE_CHANGE",
                displayName: "相对基线强烈突变",
                imageCount: 1,
                intensityRatio: detection.relativeChangeScore,
                acceleratedIntervalSeconds: Self.acceleratedCaptureIntervalSeconds,
                acceleratedWindowSeconds: Self.strongAttentionWindowSeconds
            )
        }
        return RingPhotoBurstPlan(
            tier: "RELATIVE_CHANGE",
            displayName: "相对基线发生变化",
            imageCount: 1,
            intensityRatio: detection.relativeChangeScore,
            acceleratedIntervalSeconds: Self.acceleratedCaptureIntervalSeconds,
            acceleratedWindowSeconds: Self.normalAttentionWindowSeconds
        )
    }

    private func activateAcceleratedCapture(plan: RingPhotoBurstPlan) {
        guard acceleratedCaptureUntil == nil else {
            appendLog("动态关注窗口已在运行，本次变化不延长结束时间")
            return
        }
        acceleratedCaptureUntil = Date().addingTimeInterval(plan.acceleratedWindowSeconds)
        acceleratedCaptureRearmRequired = true
        stableBatchesAfterAcceleration = 0
        appendLog(
            "动态采集加速：未来 \(Int(plan.acceleratedWindowSeconds)) 秒每 "
                + "\(plan.acceleratedIntervalSeconds) 秒尝试一张"
        )
        captureLoopTask?.cancel()
        startCaptureLoop()
    }

    private func updateAcceleratedCaptureState(
        receivedAt: Date,
        contextState: String
    ) {
        if let acceleratedCaptureUntil, receivedAt >= acceleratedCaptureUntil {
            self.acceleratedCaptureUntil = nil
            appendLog("动态关注窗口结束，恢复低频基线采集")
            if sessionState == .active {
                captureLoopTask?.cancel()
                startCaptureLoop()
            }
        }
        guard acceleratedCaptureRearmRequired, acceleratedCaptureUntil == nil else {
            return
        }
        if contextState == "RELATIVELY_STABLE" || contextState == "HEAD_STABLE" {
            stableBatchesAfterAcceleration += 1
            if stableBatchesAfterAcceleration >= 3 {
                acceleratedCaptureRearmRequired = false
                stableBatchesAfterAcceleration = 0
                appendLog("已重新达到相对稳定，下一次运动变化可以触发采集")
            }
        } else {
            stableBatchesAfterAcceleration = 0
        }
    }

    private func beginRingTriggeredAudioWindow(decisionID: UUID, startedAt: Date) {
        let endsAt = startedAt.addingTimeInterval(Self.ringTriggeredAudioWindowSeconds)
        activeRingAudioWindow = ActiveRingAudioWindow(
            decisionID: decisionID,
            startedAt: startedAt,
            endsAt: endsAt,
            data: Data(),
            peakDBFS: -160
        )

        if audioCaptureMode?.isSessionVAD == true {
            appendLog("戒指触发已关联到正在运行的会话音频流")
        } else if let mode = audioCaptureMode {
            appendLog("戒指短音频未启动：当前音频流为 \(mode.displayName)")
            activeRingAudioWindow = nil
            return
        } else {
            guard startAudioCapture(mode: .ringTriggered(decisionID)) else {
                activeRingAudioWindow = nil
                return
            }
        }

        ringAudioStopTask?.cancel()
        ringAudioStopTask = Task { [weak self] in
            try? await Task.sleep(
                nanoseconds: UInt64(Self.ringTriggeredAudioWindowSeconds * 1_000_000_000)
            )
            guard !Task.isCancelled, let self else {
                return
            }
            self.finalizeRingTriggeredAudioWindow(endedAt: Date())
            if self.audioCaptureMode?.triggerDecisionID == decisionID {
                self.stopAudioCapture(reason: "RING_TRIGGER_WINDOW_COMPLETED")
            }
        }
    }

    private func appendToRingTriggeredAudioWindow(
        _ data: Data,
        levelDBFS: Double?,
        receivedAt: Date
    ) {
        guard var window = activeRingAudioWindow, receivedAt <= window.endsAt else {
            return
        }
        window.data.append(data)
        if let levelDBFS {
            window.peakDBFS = max(window.peakDBFS, levelDBFS)
        }
        activeRingAudioWindow = window
    }

    private func finalizeRingTriggeredAudioWindow(endedAt: Date) {
        guard let window = activeRingAudioWindow else {
            return
        }
        activeRingAudioWindow = nil
        guard !window.data.isEmpty, let sessionID = currentSession?.id else {
            mutateCurrentSession { session in
                session.auditEvents.append(
                    ProbeAuditEvent(
                        id: UUID(),
                        occurredAt: endedAt,
                        type: "RING_TRIGGER_AUDIO_EMPTY",
                        detail: "decision=\(window.decisionID.uuidString.lowercased())"
                    )
                )
            }
            return
        }

        let observationID = UUID()
        let durationMilliseconds = max(
            1,
            Int(min(endedAt, window.endsAt).timeIntervalSince(window.startedAt) * 1_000)
        )
        debugBridge.send(
            type: "media",
            payload: LiveDebugMediaItem(
                id: observationID.uuidString.lowercased(),
                kind: "AUDIO",
                occurredAt: min(endedAt, window.endsAt),
                trigger: "RING_MOTION_WINDOW",
                triggerDecisionID: window.decisionID.uuidString.lowercased(),
                mimeType: "audio/pcm;rate=16000;channels=\(audioChannels)",
                durationMilliseconds: durationMilliseconds,
                captureLatencyMilliseconds: nil,
                byteCount: window.data.count,
                base64Data: window.data.base64EncodedString()
            )
        )
        var localReference: String?
        if retainLocalSamples {
            do {
                localReference = try artifactStore.saveAudio(
                    window.data,
                    sessionID: sessionID,
                    observationID: observationID
                )
            } catch {
                appendLog("戒指触发音频写入失败：\(error.localizedDescription)")
            }
        }

        let observation = ProbeAudioObservation(
            id: observationID,
            sessionID: sessionID,
            trigger: "RING_MOTION_WINDOW",
            triggerDecisionID: window.decisionID,
            startedAt: window.startedAt,
            endedAt: min(endedAt, window.endsAt),
            durationMilliseconds: durationMilliseconds,
            byteCount: window.data.count,
            peakDBFS: window.peakDBFS,
            codec: "PCM_S16LE_16KHZ",
            channels: audioChannels,
            localMediaReference: localReference,
            analysisState: localReference == nil ? "NOT_QUEUED" : "PENDING_LOCAL",
            applicationState: applicationState
        )
        audioSegmentCount += 1
        lastAudioSummary = String(
            format: "戒指触发音频：%d ms，%d 字节，峰值 %.1f dBFS",
            durationMilliseconds,
            window.data.count,
            window.peakDBFS
        )
        mutateCurrentSession { session in
            session.audioObservations.append(observation)
            session.auditEvents.append(
                ProbeAuditEvent(
                    id: UUID(),
                    occurredAt: observation.endedAt,
                    type: "RING_TRIGGER_AUDIO_WINDOW_COMPLETED",
                    detail: "decision=\(window.decisionID.uuidString.lowercased());bytes=\(window.data.count)"
                )
            )
        }
    }

    private func ringJudgementSummary(
        _ detection: RingRapidMovementDetection,
        suffix: String
    ) -> String {
        if detection.mountPosition == .glassesMounted {
            return String(
                format:
                    "头部转向后已回稳（累计转角 %.1f°，重力方向变化 %.1f°，"
                    + "末尾转动 P90 %.1f°/s）· %@",
                detection.rotationExcursionDegrees ?? 0,
                detection.gravityTiltDegrees ?? 0,
                detection.endingGyroscopeDPS ?? 0,
                suffix
            )
        }
        return String(
            format:
                "运动变化 %.1f×（加速度 P90 %.0f / 基线 %.0f，"
                + "转动 P90 %.0f / 基线 %.0f）· %@",
            detection.relativeChangeScore,
            detection.peakAccelerationDelta,
            detection.accelerationBaseline,
            detection.peakGyroscopeMagnitude,
            detection.gyroscopeBaseline,
            suffix
        )
    }

    private func makeRingSensorSnapshot() -> ProbeRingSensorSnapshot? {
        guard let configuration = ringSensorConfiguration else {
            return nil
        }
        return ProbeRingSensorSnapshot(
            deviceID: selectedRingDeviceID?.uuidString.lowercased() ?? "unknown",
            deviceName: selectedRingDevice?.name ?? "Ring Sound",
            sampleRateHz: configuration.sampleRateHz,
            accelRangeG: configuration.accelRangeG,
            gyroRangeDPS: configuration.gyroRangeDPS,
            mountPosition: ringMountPosition
        )
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
        guard audioCaptureMode != nil else {
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
            appendToRingTriggeredAudioWindow(
                packet.data,
                levelDBFS: result.levelDBFS,
                receivedAt: Date()
            )
            if result.speechStarted {
                appendLog("VAD 检测到语音开始")
            }
            if
                let segment = result.completedSegment,
                audioCaptureMode?.triggerDecisionID == nil
            {
                recordAudioSegment(segment)
            }
        @unknown default:
            appendLog("收到未知音频事件")
        }
    }

    private func recordAudioSegment(_ segment: ProbeAudioSegment) {
        let observationID = UUID()
        let triggerDecisionID = ringDecisionID(for: segment)
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
        debugBridge.send(
            type: "media",
            payload: LiveDebugMediaItem(
                id: observationID.uuidString.lowercased(),
                kind: "AUDIO",
                occurredAt: segment.endedAt,
                trigger: triggerDecisionID == nil ? "SESSION_VAD" : "RING_MOTION",
                triggerDecisionID: triggerDecisionID?.uuidString.lowercased(),
                mimeType: "audio/pcm;rate=16000;channels=\(audioChannels)",
                durationMilliseconds: segment.durationMilliseconds,
                captureLatencyMilliseconds: nil,
                byteCount: segment.data.count,
                base64Data: segment.data.base64EncodedString()
            )
        )

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
            trigger: triggerDecisionID == nil ? "SESSION_VAD" : "RING_MOTION",
            triggerDecisionID: triggerDecisionID,
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

    private func ringDecisionID(for segment: ProbeAudioSegment) -> UUID? {
        if let decisionID = audioCaptureMode?.triggerDecisionID {
            return decisionID
        }
        guard let window = activeRingAudioWindow else {
            return nil
        }
        let overlapsWindow =
            segment.endedAt >= window.startedAt
            && segment.startedAt <= window.endsAt
        return overlapsWindow ? window.decisionID : nil
    }

    private func requestPhoto(
        trigger: ProbeCaptureTrigger,
        sessionID: UUID?,
        triggerDecisionID: UUID?,
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
                    triggerDecisionID: triggerDecisionID,
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
            trigger: trigger,
            triggerDecisionID: triggerDecisionID
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
                            triggerDecisionID: triggerDecisionID,
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
                self.debugBridge.send(
                    type: "media",
                    payload: LiveDebugMediaItem(
                        id: observationID.uuidString.lowercased(),
                        kind: "IMAGE",
                        occurredAt: Date(),
                        trigger: trigger.rawValue,
                        triggerDecisionID: triggerDecisionID?.uuidString.lowercased(),
                        mimeType: "image/jpeg",
                        durationMilliseconds: nil,
                        captureLatencyMilliseconds: latency,
                        byteCount: data.count,
                        base64Data: data.base64EncodedString()
                    )
                )
                if let sessionID {
                    self.recordObservation(
                        id: observationID,
                        sessionID: sessionID,
                        scheduledAt: scheduledAt,
                        trigger: trigger,
                        triggerDecisionID: triggerDecisionID,
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
                    triggerDecisionID: triggerDecisionID,
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
                let interval = self.effectiveCaptureIntervalSeconds
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
                        triggerDecisionID: nil,
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
                    triggerDecisionID: nil,
                    scheduledAt: scheduledAt
                )
            }
        }
    }

    private var effectiveCaptureIntervalSeconds: Int {
        guard let acceleratedCaptureUntil else {
            return captureIntervalSeconds
        }
        if acceleratedCaptureUntil > Date() {
            return min(captureIntervalSeconds, Self.acceleratedCaptureIntervalSeconds)
        }
        self.acceleratedCaptureUntil = nil
        return captureIntervalSeconds
    }

    private func pauseCaptureSession(reason: String) {
        guard sessionState == .active else {
            return
        }

        captureLoopTask?.cancel()
        captureLoopTask = nil
        acceleratedCaptureUntil = nil
        acceleratedCaptureRearmRequired = false
        stableBatchesAfterAcceleration = 0
        nextCaptureAt = nil
        if let audioCaptureMode, !audioCaptureMode.isManualTest {
            stopAudioCapture(reason: reason)
        }
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
        acceleratedCaptureUntil = nil
        acceleratedCaptureRearmRequired = false
        stableBatchesAfterAcceleration = 0
        nextCaptureAt = nil
        cancelPendingPhoto(reason: "SESSION_ENDED")
        if let audioCaptureMode, !audioCaptureMode.isManualTest {
            stopAudioCapture(reason: reason)
        }
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
        triggerDecisionID: UUID?,
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
            triggerDecisionID: triggerDecisionID,
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
                    triggerDecisionID: request.triggerDecisionID,
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
                triggerDecisionID: request.triggerDecisionID,
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
        scheduleDebugSnapshot()
    }

    private func bindDebugBridge() {
        debugBridge.onStatusChanged = { [weak self] status in
            guard let self else {
                return
            }
            desktopDebugStatus = status
            scheduleDebugSnapshot()
        }
        debugBridge.onCommand = { [weak self] command in
            self?.handleDebugCommand(command)
        }
    }

    private func handleDebugCommand(_ command: LiveDebugCommand) {
        switch command.command {
        case "ring.scan":
            scanRingDevices()
        case "ring.connect":
            guard
                let value = command.deviceID,
                let deviceID = UUID(uuidString: value)
            else {
                appendLog("电脑调试命令缺少有效戒指 UUID")
                return
            }
            selectRingDevice(deviceID)
            connectSelectedRing()
        case "ring.disconnect":
            disconnectRing()
        case "ring.sensor.auto":
            setRingSensorAutoStartEnabled(command.boolValue ?? true)
        case "ring.sensitivity":
            guard
                let value = command.stringValue,
                let sensitivity = ProbeRingSensitivity(rawValue: value)
            else {
                appendLog("电脑调试命令的灵敏度无效")
                return
            }
            setRingSensitivity(sensitivity)
        case "glasses.customView.toggle":
            toggleCustomView()
        case "glasses.photo":
            takePhoto()
        case "audio.toggle":
            toggleAudioTest()
        case "session.start":
            startRingLinkedCapture()
        case "session.pause":
            pauseCaptureSession()
        case "session.resume":
            resumeCaptureSession()
        case "session.end":
            endCaptureSession()
        default:
            appendLog("收到未知电脑调试命令：\(command.command)")
        }
    }

    private func scheduleDebugSnapshot() {
        guard debugSnapshotTask == nil else {
            return
        }
        debugSnapshotTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 100_000_000)
            guard !Task.isCancelled, let self else {
                return
            }
            self.debugSnapshotTask = nil
            self.sendDebugSnapshot()
        }
    }

    private func sendDebugSnapshot() {
        let snapshot = LiveDebugSnapshot(
            phoneName: UIDevice.current.name,
            applicationState: applicationState,
            desktopConnection: desktopDebugStatus,
            glasses: LiveDebugGlassesState(
                authentication: authStatus,
                connection: linkStatus,
                customView: customViewStatus,
                wearing: wearingStatus,
                deviceSummary: deviceSummary,
                photoReady: photoReadinessStatus
            ),
            ring: LiveDebugRingState(
                bluetooth: ringBluetoothStatus,
                connection: ringConnectionStatus,
                selectedDeviceID: selectedRingDeviceID?.uuidString.lowercased(),
                serviceUUID: RingProtocolCodec.serviceUUID,
                notifyCharacteristicUUID: RingProtocolCodec.notifyCharacteristicUUID,
                writeCharacteristicUUID: RingProtocolCodec.writeCharacteristicUUID,
                macAddress: "iOS 不提供蓝牙 MAC 地址",
                candidates: ringDevices.map {
                    LiveDebugRingCandidate(
                        id: $0.id.uuidString.lowercased(),
                        name: $0.name,
                        displayName: $0.displayName,
                        rssi: $0.rssi,
                        advertisesRingService: $0.advertisesRingService,
                        isKnownRing: $0.isKnownRing
                    )
                },
                identity: ringSystemInfo,
                sensorConfiguration: ringSensorConfiguration,
                sensorAutoStartEnabled: ringSensorAutoStartEnabled,
                sensorReporting: isRingSensorReporting,
                batchCount: ringBatchCount,
                sampleCount: ringSampleCount,
                sequenceGapCount: ringSequenceGapCount,
                accelerationMagnitudeRaw: ringAccelerationMagnitude,
                accelerationDeltaRaw: ringAccelerationDelta,
                gyroscopeMagnitudeRaw: ringGyroscopeMagnitude,
                accelerationDeltaThresholdRaw:
                    ringAccelerationDynamicThreshold
                    ?? ringSensitivity.accelerationNoiseFloor
                        * ringSensitivity.relativeChangeThreshold,
                gyroscopeMagnitudeThresholdRaw:
                    ringGyroscopeDynamicThreshold
                    ?? ringSensitivity.gyroscopeNoiseFloor
                        * ringSensitivity.relativeChangeThreshold,
                accelerationBaselineRaw: ringAccelerationBaseline,
                gyroscopeBaselineRaw: ringGyroscopeBaseline,
                relativeChangeScore: ringRelativeChangeScore,
                motionContextState: ringMotionContextState,
                mountPosition: ringMountPosition.rawValue,
                rotationExcursionDegrees: ringRotationExcursionDegrees,
                gravityTiltDegrees: ringGravityTiltDegrees,
                endingGyroscopeDPS: ringEndingGyroscopeDPS,
                detectorRuleVersion:
                    ringMountPosition == .glassesMounted
                        ? RingRapidMovementDetector.ruleVersion
                        : RingRapidMovementDetector.legacyRuleVersion,
                sensitivity: ringSensitivity.rawValue,
                lastJudgement: lastRingJudgement,
                lastJudgementAt: lastRingJudgementAt,
                lastEvent: lastRingEvent
            ),
            session: LiveDebugSessionState(
                id: currentSession?.id.uuidString.lowercased(),
                state: sessionState.rawValue,
                imageCount: currentSession?.observations.count ?? 0,
                audioCount: currentSession?.audioObservations.count ?? 0,
                rapidMovementCount: currentSession?.ringMotionAssessments.count ?? 0,
                retainLocalSamples: retainLocalSamples,
                audioLevelDBFS: audioLevelDBFS,
                speechActive: isSpeechActive,
                captureIntervalSeconds: effectiveCaptureIntervalSeconds,
                captureMode:
                    acceleratedCaptureUntil.map { $0 > Date() } == true
                    ? "动态加速"
                    : acceleratedCaptureRearmRequired
                        ? "等待重新稳定"
                        : "稳定基线",
                acceleratedUntil: acceleratedCaptureUntil,
                captureRearmRequired: acceleratedCaptureRearmRequired
            ),
            recentLogs: Array(logs.prefix(12))
        )
        debugBridge.send(type: "snapshot", payload: snapshot)
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
                        "text": "Reality Memory",
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
