# Deploy iOS ERP-CV.BJAS

Folder ini berisi kebutuhan release iOS wrapper ERP-CV.BJAS.

## File

- `apple-app-site-association.example.json`
- `app-store-release-checklist.md`

## Langkah Produksi

1. Buka folder:
   - `mobile/ios-wrapper`
2. Generate project dengan XcodeGen.
3. Buka project di Xcode.
4. Atur:
   - Development Team
   - Bundle identifier
   - Associated Domains
5. Isi env server:
   - `IOS_APP_IDS`
6. Verifikasi endpoint:
   - `https://erp.cvbjasyogya.cloud/.well-known/apple-app-site-association`
7. Archive app dan upload ke TestFlight / App Store Connect.

## Catatan

- Route `/.well-known/apple-app-site-association` sekarang disediakan backend ERP.
- Jika `IOS_APP_IDS` belum diisi, route tetap aman dan hanya mengembalikan daftar kosong.
