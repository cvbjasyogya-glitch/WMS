import Foundation

enum AppShortcutType: String, CaseIterable {
    case attendance = "cloud.cvbjasyogya.erp.attendance"
    case stock = "cloud.cvbjasyogya.erp.stock"
    case cashier = "cloud.cvbjasyogya.erp.cashier"
    case notifications = "cloud.cvbjasyogya.erp.notifications"

    var targetURL: URL {
        switch self {
        case .attendance:
            return AppConfig.erpURL(path: "/absen/", source: "ios-shortcut")
        case .stock:
            return AppConfig.erpURL(path: "/stock/", source: "ios-shortcut")
        case .cashier:
            return AppConfig.erpURL(path: "/kasir/", source: "ios-shortcut")
        case .notifications:
            return AppConfig.erpURL(path: "/notifications/", source: "ios-shortcut")
        }
    }
}

enum AppConfig {
    static let webOrigin = URL(string: "https://erp.cvbjasyogya.cloud")!
    static let launchURL = erpURL(path: "/workspace/", source: "ios-app")
    static let allowedHost = webOrigin.host?.lowercased() ?? "erp.cvbjasyogya.cloud"
    static let userAgentSuffix = " ERP-CVBJAS-iOSWrapper/1.0"

    static func erpURL(path: String, source: String) -> URL {
        var components = URLComponents(url: webOrigin, resolvingAgainstBaseURL: false)!
        components.path = path
        components.queryItems = [URLQueryItem(name: "source", value: source)]
        return components.url!
    }

    static func normalizedERPURL(from url: URL?) -> URL? {
        guard let url else {
            return nil
        }
        guard
            let scheme = url.scheme?.lowercased(),
            scheme == "https",
            let host = url.host?.lowercased(),
            host == allowedHost
        else {
            return nil
        }

        if URLComponents(url: url, resolvingAgainstBaseURL: false)?
            .queryItems?
            .contains(where: { $0.name == "source" }) == true {
            return url
        }

        guard var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return url
        }
        var queryItems = components.queryItems ?? []
        queryItems.append(URLQueryItem(name: "source", value: "ios-app"))
        components.queryItems = queryItems
        return components.url
    }
}
