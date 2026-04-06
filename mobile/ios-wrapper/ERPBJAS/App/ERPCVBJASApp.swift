import SwiftUI

@main
struct ERPCVBJASApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var navigationState = AppNavigationState()

    var body: some Scene {
        WindowGroup {
            RootShellView()
                .environmentObject(navigationState)
                .onOpenURL { url in
                    navigationState.open(url)
                }
                .onContinueUserActivity(NSUserActivityTypeBrowsingWeb) { userActivity in
                    navigationState.open(userActivity.webpageURL)
                }
                .onReceive(NotificationCenter.default.publisher(for: .erpShortcutActivated)) { notification in
                    navigationState.openShortcut(named: notification.object as? String)
                }
                .task {
                    if let pendingShortcut = AppDelegate.pendingShortcutType {
                        navigationState.openShortcut(named: pendingShortcut)
                        AppDelegate.pendingShortcutType = nil
                    }
                }
        }
    }
}
