# iOS Release Checklist

## 1. Branding

- Nama app final benar
- App icon sudah final
- Launch screen sudah benar
- Bundle identifier final sudah ditetapkan

## 2. Universal link

- Isi env server:
  - `IOS_APP_IDS`
- Verifikasi endpoint:
  - `https://erp.cvbjasyogya.cloud/.well-known/apple-app-site-association`
- Associated Domains aktif di entitlements dan Xcode signing

## 3. Build

- Install `XcodeGen`
- Generate project dari `mobile/ios-wrapper/project.yml`
- Build ke simulator
- Build ke device fisik
- Archive ke App Store Connect

## 4. QA utama

- App launch normal
- Login normal
- Universal link membuka halaman ERP dalam app
- Quick Actions membuka:
  - Absen
  - Stok
  - Kasir
  - Notifikasi
- Kamera, lokasi, mikrofon tampil prompt dengan benar
- Upload foto, geotag, meeting, notifikasi, dan theme tetap stabil

## 5. App Store Connect

- Privacy nutrition labels diisi
- App Privacy Policy URL aktif
- Support URL aktif
- Screenshot iPhone siap
- Screenshot iPad siap jika target iPad aktif
- Review notes disiapkan untuk akses login jika diminta reviewer
