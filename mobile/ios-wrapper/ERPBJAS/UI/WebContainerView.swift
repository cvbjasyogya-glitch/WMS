import SwiftUI
import WebKit

struct WebContainerView: UIViewRepresentable {
    let requestedURL: URL
    let reloadToken: Int
    @Binding var isLoading: Bool
    @Binding var showOfflineBanner: Bool

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.allowsInlineMediaPlayback = true
        configuration.mediaTypesRequiringUserActionForPlayback = []
        configuration.websiteDataStore = .default()

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.customUserAgent = (webView.customUserAgent ?? "") + AppConfig.userAgentSuffix
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.backgroundColor = .black
        webView.isOpaque = false

        let refreshControl = UIRefreshControl()
        refreshControl.addTarget(context.coordinator, action: #selector(Coordinator.handleRefresh(_:)), for: .valueChanged)
        webView.scrollView.refreshControl = refreshControl

        context.coordinator.webView = webView
        context.coordinator.load(url: requestedURL, in: webView)
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        context.coordinator.parent = self

        if context.coordinator.lastLoadedURL != requestedURL {
            context.coordinator.load(url: requestedURL, in: webView)
            return
        }

        if context.coordinator.lastReloadToken != reloadToken {
            context.coordinator.lastReloadToken = reloadToken
            webView.reload()
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        var parent: WebContainerView
        weak var webView: WKWebView?
        var lastLoadedURL: URL?
        var lastReloadToken: Int

        init(parent: WebContainerView) {
            self.parent = parent
            self.lastReloadToken = parent.reloadToken
        }

        func load(url: URL, in webView: WKWebView) {
            lastLoadedURL = url
            lastReloadToken = parent.reloadToken
            parent.isLoading = true
            parent.showOfflineBanner = false
            webView.load(URLRequest(url: url, cachePolicy: .reloadRevalidatingCacheData))
        }

        @objc
        func handleRefresh(_ sender: UIRefreshControl) {
            webView?.reload()
        }

        private func shouldIgnore(_ error: Error) -> Bool {
            let nsError = error as NSError
            return nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorCancelled
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            parent.isLoading = true
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.isLoading = false
            parent.showOfflineBanner = false
            webView.scrollView.refreshControl?.endRefreshing()
            lastLoadedURL = webView.url ?? lastLoadedURL
        }

        func webView(
            _ webView: WKWebView,
            didFail navigation: WKNavigation!,
            withError error: Error
        ) {
            if shouldIgnore(error) {
                webView.scrollView.refreshControl?.endRefreshing()
                return
            }
            parent.isLoading = false
            parent.showOfflineBanner = true
            webView.scrollView.refreshControl?.endRefreshing()
        }

        func webView(
            _ webView: WKWebView,
            didFailProvisionalNavigation navigation: WKNavigation!,
            withError error: Error
        ) {
            if shouldIgnore(error) {
                webView.scrollView.refreshControl?.endRefreshing()
                return
            }
            parent.isLoading = false
            parent.showOfflineBanner = true
            webView.scrollView.refreshControl?.endRefreshing()
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let targetURL = navigationAction.request.url else {
                decisionHandler(.cancel)
                return
            }

            if AppConfig.normalizedERPURL(from: targetURL) != nil {
                decisionHandler(.allow)
                return
            }

            UIApplication.shared.open(targetURL)
            parent.isLoading = false
            decisionHandler(.cancel)
        }
    }
}
