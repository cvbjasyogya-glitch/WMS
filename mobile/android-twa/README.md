# ERP-CV.BJAS Android App

Wrapper aplikasi Android untuk ERP-CV.BJAS memakai **Trusted Web Activity (TWA)**.

## Kenapa TWA

- web dan app memakai domain ERP yang sama
- performa lebih ringan daripada membangun UI mobile kedua
- tetap kompatibel dengan PWA, service worker, push notification, kamera, geotag, dan mode standalone yang sudah ada
- maintenance jauh lebih aman untuk ERP yang dipakai harian

## Struktur

- `app/` Android application module
- `app/src/main/java/.../ErpLauncherActivity.kt` launcher TWA
- `app/src/main/res/...` icon, splash, dan theme
- `app/src/main/res/xml/shortcuts.xml` shortcut launcher Android

## URL yang dibuka aplikasi

Secara default app membuka:

- `https://erp.cvbjasyogya.cloud/workspace/?source=android-app`

Shortcut launcher bawaan:

- Absen Foto
- Stok Gudang
- Kasir Harian
- Notifikasi

Jika domain atau jalur start app berubah, update:

- `app/build.gradle`
- server env `ANDROID_TWA_START_URL`

## Syarat sebelum build release

1. Pastikan PWA web sudah aktif di domain produksi.
2. Isi env server:
   - `ANDROID_APP_PACKAGE`
   - `ANDROID_SHA256_CERT_FINGERPRINTS`
   - `ANDROID_TWA_START_URL`
3. Pastikan route berikut bisa diakses publik:
   - `https://erp.cvbjasyogya.cloud/.well-known/assetlinks.json`
4. Sign app release dengan keystore final, lalu ambil SHA-256 certificate fingerprint.

## Build di Android Studio

1. Buka folder ini di Android Studio:
   - `mobile/android-twa`
2. Biarkan Android Studio sync Gradle.
3. Jalankan `Build > Generate Signed Bundle / APK`.
4. Pilih `Android App Bundle` untuk Play Store atau `APK` untuk distribusi internal.

## Catatan Produksi

- TWA paling cocok jika domain ERP memakai HTTPS stabil.
- Push, service worker, dan install prompt tetap dikelola oleh web ERP.
- Jika nanti perlu fitur native tambahan seperti printer bluetooth, scanner barcode hardware, atau background sync native, baru kita pecah ke hybrid/native module khusus.
- Release checklist store ada di:
  - `deploy/android/play-store-release-checklist.md`
