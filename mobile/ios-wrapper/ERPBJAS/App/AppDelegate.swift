import UIKit

extension Notification.Name {
    static let erpShortcutActivated = Notification.Name("erpShortcutActivated")
}

final class AppDelegate: NSObject, UIApplicationDelegate {
    static var pendingShortcutType: String?

    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        if let shortcutItem = launchOptions?[.shortcutItem] as? UIApplicationShortcutItem {
            Self.pendingShortcutType = shortcutItem.type
            return false
        }
        return true
    }

    func application(
        _ application: UIApplication,
        performActionFor shortcutItem: UIApplicationShortcutItem,
        completionHandler: @escaping (Bool) -> Void
    ) {
        Self.pendingShortcutType = shortcutItem.type
        NotificationCenter.default.post(name: .erpShortcutActivated, object: shortcutItem.type)
        Self.pendingShortcutType = nil
        completionHandler(true)
    }
}
