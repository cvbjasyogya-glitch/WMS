import SwiftUI

struct RootShellView: View {
    @EnvironmentObject private var navigationState: AppNavigationState

    var body: some View {
        ZStack(alignment: .bottom) {
            Color(red: 7 / 255, green: 17 / 255, blue: 31 / 255)
                .ignoresSafeArea()

            WebContainerView(
                requestedURL: navigationState.currentURL,
                reloadToken: navigationState.reloadToken,
                isLoading: $navigationState.isLoading,
                showOfflineBanner: $navigationState.showOfflineBanner
            )
            .ignoresSafeArea()

            if navigationState.isLoading {
                loadingPill
                    .padding(.top, 12)
                    .frame(maxHeight: .infinity, alignment: .top)
                    .transition(.opacity)
            }

            if navigationState.showOfflineBanner {
                offlineBanner
                    .padding(.horizontal, 16)
                    .padding(.bottom, 18)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: navigationState.isLoading)
        .animation(.easeInOut(duration: 0.2), value: navigationState.showOfflineBanner)
    }

    private var loadingPill: some View {
        HStack(spacing: 10) {
            ProgressView()
                .progressViewStyle(.circular)
                .tint(.white)
            Text("Memuat ERP-CV.BJAS…")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(.white)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(
            Capsule(style: .continuous)
                .fill(Color.black.opacity(0.72))
        )
    }

    private var offlineBanner: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Koneksi sedang bermasalah")
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(.white)
            Text("ERP tetap memakai halaman terakhir. Coba muat ulang saat internet kembali stabil.")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Color.white.opacity(0.82))
            Button {
                navigationState.retryCurrentPage()
            } label: {
                Text("Coba Lagi")
                    .font(.system(size: 14, weight: .bold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .fill(Color.white)
                    )
                    .foregroundStyle(Color(red: 7 / 255, green: 17 / 255, blue: 31 / 255))
            }
            .buttonStyle(.plain)
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(Color(red: 11 / 255, green: 23 / 255, blue: 42 / 255).opacity(0.96))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 1)
        )
    }
}
