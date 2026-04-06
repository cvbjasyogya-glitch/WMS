# ERP-CV.BJAS iOS Wrapper

Wrapper iOS ringan untuk ERP-CV.BJAS memakai **SwiftUI + WKWebView**.

## Kenapa model ini

- web ERP tetap menjadi pusat sistem, jadi perilaku web dan app tetap sinkron
- lebih ringan daripada membangun UI iOS kedua yang berbeda arah
- tetap bisa memakai deep link, universal link, kamera, lokasi, mikrofon, dan push/PWA dari domain ERP
- cocok untuk operasi harian yang butuh stabil dan mudah dirawat

## Struktur

- `project.yml` untuk generate project Xcode via XcodeGen
- `ERPBJAS/App/` untuk state aplikasi, deep link, dan quick action
- `ERPBJAS/UI/` untuk shell view dan WKWebView container
- `ERPBJAS/Resources/` untuk `Info.plist`, entitlements, launch screen, dan asset catalog

## Start URL

Wrapper iOS membuka:

- `https://erp.cvbjasyogya.cloud/workspace/?source=ios-app`

Shortcut cepat akan membuka:

- `/absen/`
- `/stock/`
- `/kasir/`
- `/notifications/`

## Build di Mac

1. Install `XcodeGen`:
   - `brew install xcodegen`
2. Masuk ke folder:
   - `mobile/ios-wrapper`
3. Generate project:
   - `xcodegen generate`
4. Buka:
   - `ERPBJAS.xcodeproj`
5. Isi `Signing & Capabilities`:
   - Development Team
   - Bundle identifier final
6. Pastikan entitlements `Associated Domains` aktif.
7. Build ke simulator/device dari Xcode.

## Syarat sebelum release

1. Domain ERP harus HTTPS stabil.
2. Backend harus melayani:
   - `https://erp.cvbjasyogya.cloud/.well-known/apple-app-site-association`
3. Env server harus diisi:
   - `IOS_APP_IDS`
4. Bundle identifier final harus sinkron dengan file association dan signing profile.

## Catatan

- Wrapper ini sengaja tipis dan fokus pada kestabilan.
- Jika nanti butuh fitur native berat seperti printer bluetooth atau barcode scanner native, baru kita pecah modul native tambahan.
