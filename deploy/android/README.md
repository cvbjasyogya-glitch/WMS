# Deploy Android ERP-CV.BJAS

Folder ini berisi kebutuhan deploy sisi Android wrapper dan verifikasi domain.

## File

- `assetlinks.example.json`:
  template untuk isi `/.well-known/assetlinks.json`
- `play-store-release-checklist.md`:
  checklist release Android production
- `store-listing-template.md`:
  template teks listing Play Store

## Langkah Produksi

1. Build app release dari folder:
   - `mobile/android-twa`
2. Sign app dengan keystore final.
3. Ambil SHA-256 certificate fingerprint release.
4. Isi env server:
   - `ANDROID_APP_PACKAGE`
   - `ANDROID_SHA256_CERT_FINGERPRINTS`
   - `ANDROID_TWA_START_URL`
5. Verifikasi endpoint publik:
   - `https://erp.cvbjasyogya.cloud/.well-known/assetlinks.json`
6. Upload AAB/APK hasil build ke jalur distribusi yang dipakai.
7. Lengkapi metadata store memakai:
   - `play-store-release-checklist.md`
   - `store-listing-template.md`

## Catatan

- Route `/.well-known/assetlinks.json` sekarang sudah disediakan oleh backend ERP.
- Jika fingerprint belum diisi, endpoint akan mengembalikan array kosong agar web tetap aman.
