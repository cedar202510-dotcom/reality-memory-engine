import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var model: GlassProbeModel

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 0) {
                    statusSection
                    Divider()
                    actionSection
                    Divider()
                    sessionSection
                    Divider()
                    resultSection
                    Divider()
                    logSection
                }
            }
            .background(Color(uiColor: .systemBackground))
            .navigationTitle("Glass Probe")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        model.refreshEnvironment()
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("刷新环境状态")
                }
            }
        }
    }

    private var statusSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("CXR-L 1.0.4")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)

            StatusRow(
                title: "Rokid AI App",
                value: model.rokidAppInstalled ? "已安装" : "未检测到",
                symbol: "iphone",
                isReady: model.rokidAppInstalled
            )
            StatusRow(
                title: "授权",
                value: model.authStatus,
                symbol: "key",
                isReady: model.isAuthenticated
            )
            StatusRow(
                title: "眼镜链路",
                value: model.linkStatus,
                symbol: "eyeglasses",
                isReady: model.isConnected
            )
            StatusRow(
                title: "眼镜界面",
                value: model.customViewStatus,
                symbol: "rectangle.on.rectangle",
                isReady: model.isCustomViewRunning
            )
            StatusRow(
                title: "音频流",
                value: model.isAudioStreamStarted ? "采集中" : "未启动",
                symbol: "waveform",
                isReady: model.isAudioStreamStarted
            )
        }
        .padding(20)
    }

    private var actionSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("链路操作")
                .font(.headline)

            HStack(spacing: 12) {
                ActionButton(
                    title: model.isAuthenticated ? "重新授权" : "授权",
                    symbol: "person.badge.key",
                    prominent: true,
                    disabled: !model.canAuthorize
                ) {
                    model.authenticate()
                }

                ActionButton(
                    title: model.isCustomViewRunning ? "关闭界面" : "打开界面",
                    symbol: model.isCustomViewRunning ? "rectangle.slash" : "rectangle.inset.filled",
                    prominent: false,
                    disabled: !model.canToggleCustomView
                ) {
                    model.toggleCustomView()
                }
            }

            HStack(spacing: 12) {
                ActionButton(
                    title: "读取设备",
                    symbol: "info.circle",
                    prominent: false,
                    disabled: !model.isConnected
                ) {
                    model.readDeviceInfo()
                }

                ActionButton(
                    title: "拍照",
                    symbol: "camera",
                    prominent: true,
                    disabled: !model.canTakePhoto
                ) {
                    model.takePhoto()
                }
            }

            ActionButton(
                title: model.isAudioTestRunning ? "停止音频测试" : "开始 30 秒音频测试",
                symbol: model.isAudioTestRunning ? "stop.fill" : "waveform.badge.mic",
                prominent: model.isAudioTestRunning,
                disabled: !model.canToggleAudioTest
            ) {
                model.toggleAudioTest()
            }

            LabeledContent("拍照状态", value: model.photoReadinessStatus)
            LabeledContent(
                "音频电平",
                value: model.audioLevelDBFS.map { String(format: "%.1f dBFS", $0) } ?? "尚无数据"
            )
            LabeledContent(
                "音频结果",
                value: "\(model.audioPacketCount) 包 · \(model.audioByteCount) 字节 · \(model.audioSegmentCount) 段"
            )
            Text(model.lastAudioSummary)
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)

            Toggle(
                "眼镜调试文字",
                isOn: Binding(
                    get: { model.showsGlassDebugOverlay },
                    set: { model.setGlassDebugOverlay($0) }
                )
            )
            .disabled(model.isCustomViewRunning)

            if model.isAuthenticated {
                Button(role: .destructive) {
                    model.clearAuthentication()
                } label: {
                    Label("清除授权", systemImage: "xmark.shield")
                }
                .font(.subheadline.weight(.medium))
            }
        }
        .padding(20)
    }

    private var sessionSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("采集 Session")
                    .font(.headline)
                Spacer()
                if let url = model.latestSessionURL {
                    ShareLink(item: url) {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .accessibilityLabel("导出 Session JSON")
                }
            }

            Picker(
                "采集间隔",
                selection: Binding(
                    get: { model.captureIntervalSeconds },
                    set: { model.setCaptureInterval($0) }
                )
            ) {
                ForEach([5, 15, 30, 60], id: \.self) { seconds in
                    Text("\(seconds)s").tag(seconds)
                }
            }
            .pickerStyle(.segmented)
            .disabled(model.sessionState == .active)

            Toggle(
                "保留本地样本",
                isOn: Binding(
                    get: { model.retainLocalSamples },
                    set: { model.setRetainLocalSamples($0) }
                )
            )
            .disabled(model.sessionState == .active)

            HStack(spacing: 12) {
                switch model.sessionState {
                case .idle, .ended:
                    ActionButton(
                        title: "开始",
                        symbol: "play.fill",
                        prominent: true,
                        disabled: !model.canStartSession
                    ) {
                        model.startCaptureSession()
                    }
                case .active:
                    ActionButton(
                        title: "暂停",
                        symbol: "pause.fill",
                        prominent: true,
                        disabled: false
                    ) {
                        model.pauseCaptureSession()
                    }
                    ActionButton(
                        title: "结束",
                        symbol: "stop.fill",
                        prominent: false,
                        disabled: false
                    ) {
                        model.endCaptureSession()
                    }
                case .paused:
                    ActionButton(
                        title: "恢复",
                        symbol: "play.fill",
                        prominent: true,
                        disabled: !model.canStartSession
                    ) {
                        model.resumeCaptureSession()
                    }
                    ActionButton(
                        title: "结束",
                        symbol: "stop.fill",
                        prominent: false,
                        disabled: false
                    ) {
                        model.endCaptureSession()
                    }
                }
            }

            LabeledContent("状态", value: model.sessionState.displayName)
            LabeledContent("手机 App", value: model.applicationState)
            LabeledContent(
                "采集结果",
                value: "\(model.sessionSucceededCount) 成功 · \(model.sessionSkippedCount) 跳过 · \(model.sessionFailedCount) 失败"
            )
            LabeledContent(
                "语音片段",
                value: "\(model.currentSession?.audioSegmentCount ?? 0) 段"
            )

            if let nextCaptureAt = model.nextCaptureAt {
                LabeledContent("下次采集") {
                    Text(nextCaptureAt, style: .time)
                }
            }

            if let session = model.currentSession {
                LabeledContent(
                    "Session",
                    value: String(session.id.uuidString.prefix(8)).lowercased()
                )
            }
        }
        .padding(20)
    }

    private var resultSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("真机结果")
                .font(.headline)

            LabeledContent("设备", value: model.deviceSummary)
            LabeledContent("佩戴", value: model.wearingStatus)

            if let image = model.capturedImage {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: .infinity)
                    .background(Color(uiColor: .secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                    .accessibilityLabel("眼镜拍照结果")
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "photo")
                        .font(.title)
                        .foregroundStyle(.secondary)
                    Text("尚无照片")
                        .font(.headline)
                    Text("完成授权、连接和眼镜界面打开后可拍照")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity, minHeight: 150)
            }
        }
        .padding(20)
    }

    private var logSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("事件日志")
                    .font(.headline)
                Spacer()
                Button {
                    model.clearLog()
                } label: {
                    Image(systemName: "trash")
                }
                .accessibilityLabel("清空日志")
                .disabled(model.logs.isEmpty)
            }

            if model.logs.isEmpty {
                Text("暂无事件")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(model.logs) { item in
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Text(item.time)
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .frame(width: 58, alignment: .leading)
                        Text(item.message)
                            .font(.caption)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
        }
        .padding(20)
    }
}

private struct StatusRow: View {
    let title: String
    let value: String
    let symbol: String
    let isReady: Bool

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .frame(width: 22)
                .foregroundStyle(isReady ? Color.green : Color.secondary)

            Text(title)
                .font(.body)

            Spacer()

            Circle()
                .fill(isReady ? Color.green : Color.orange)
                .frame(width: 8, height: 8)
            Text(value)
                .font(.callout)
                .foregroundStyle(.secondary)
        }
    }
}

private struct ActionButton: View {
    let title: String
    let symbol: String
    let prominent: Bool
    let disabled: Bool
    let action: () -> Void

    var body: some View {
        Group {
            if prominent {
                button
                    .buttonStyle(.borderedProminent)
            } else {
                button
                    .buttonStyle(.bordered)
            }
        }
        .controlSize(.large)
        .disabled(disabled)
    }

    private var button: some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .frame(maxWidth: .infinity)
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(GlassProbeModel())
}
