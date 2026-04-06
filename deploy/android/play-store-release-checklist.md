# Android Release Checklist

Checklist ini dipakai saat ERP-CV.BJAS akan dirilis ke Play Store.

## 1. Branding dan metadata

- Pastikan nama app final sudah benar:
  - `ERP-CV.BJAS`
- Cek icon launcher, splash, dan shortcut app sudah memakai logo final.
- Cek package name final:
  - `cloud.cvbjasyogya.erp`
- Cek version:
  - `versionCode`
  - `versionName`

## 2. Domain trust / deep link

- Isi env server:
  - `ANDROID_APP_PACKAGE`
  - `ANDROID_SHA256_CERT_FINGERPRINTS`
  - `ANDROID_TWA_START_URL`
- Verifikasi endpoint:
  - `https://erp.cvbjasyogya.cloud/.well-known/assetlinks.json`
- Pastikan fingerprint release sama dengan keystore final Play Store.

## 3. Build

- Buka project:
  - `mobile/android-twa`
- Sync Gradle di Android Studio.
- Generate:
  - `Build > Generate Signed Bundle / APK`
- Untuk Play Store, pilih:
  - `Android App Bundle (AAB)`

## 4. QA sebelum upload

- Login normal
- Install app dari build release
- Launcher membuka workspace
- Shortcut launcher membuka:
  - Absen
  - Stok
  - Kasir
  - Notifikasi
- Universal link / app link domain ERP membuka app
- Kamera, geotag, upload, dan notifikasi tetap berfungsi
- Logout/login ulang
- Theme terang/gelap tetap sinkron
- Offline fallback muncul dengan aman

## 5. Play Console

- App access policy diisi
- Data safety diisi sesuai fitur:
  - account data
  - operational data
  - location (absensi)
  - camera / microphone (meeting, bukti, absensi)
- Privacy policy URL aktif
- Support email aktif
- Content rating selesai
- Countries/regions release dipilih

## 6. Asset store

- App icon 512x512
- Feature graphic 1024x500
- Minimal 2 screenshot phone
- Screenshot tablet jika target tablet aktif
- Short description
- Full description

## 7. Post release

- Cek install dari Play Store
- Cek `assetlinks.json` masih valid
- Cek login, absen, stok, kasir, notifikasi
- Monitor error log hari pertama
