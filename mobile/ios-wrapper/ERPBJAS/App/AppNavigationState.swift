import Foundation

@MainActor
final class AppNavigationState: ObservableObject {
    @Published var currentURL: URL = AppConfig.launchURL
    @Published var isLoading = true
    @Published var showOfflineBanner = false
    @Published var reloadToken = 0

    func open(_ url: URL?) {
        guard let normalized = AppConfig.normalizedERPURL(from: url) else {
            return
        }
        currentURL = normalized
        showOfflineBanner = false
    }

    func openShortcut(named shortcutType: String?) {
        guard
            let shortcutType,
            let shortcut = AppShortcutType(rawValue: shortcutType)
        else {
            return
        }
        currentURL = shortcut.targetURL
        showOfflineBanner = false
    }

    func retryCurrentPage() {
        showOfflineBanner = false
        reloadToken += 1
    }
}
