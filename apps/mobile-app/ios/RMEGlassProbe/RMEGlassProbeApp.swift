import SwiftUI

@main
struct RMEGlassProbeApp: App {
    @StateObject private var model = GlassProbeModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
                .onOpenURL { url in
                    model.handleOpenURL(url)
                }
                .onChange(of: scenePhase) { phase in
                    switch phase {
                    case .active:
                        model.recordApplicationLifecycle("前台")
                    case .inactive:
                        model.recordApplicationLifecycle("非活跃")
                    case .background:
                        model.recordApplicationLifecycle("后台")
                    @unknown default:
                        model.recordApplicationLifecycle("未知")
                    }
                }
        }
    }
}
