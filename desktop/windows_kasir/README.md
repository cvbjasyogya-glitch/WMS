# Kasir ERP Desktop Windows

Fondasi aplikasi `KasirERP.exe` untuk Windows yang tetap memakai **ERP web** sebagai pusat sistem.

Wrapper ini cocok untuk PC kasir yang ingin:

- membuka ERP langsung ke modul `/kasir/`
- tetap bisa pindah ke modul gudang `/stock/`
- menyimpan sesi login di app desktop
- punya mode launcher Windows yang stabil untuk Edge/Chrome
- tetap punya jembatan native awal untuk cek printer Windows dan perintah `window.print()` saat `pywebview` tersedia

## Model arsitektur

- Backend tetap ERP web yang sudah ada
- App desktop hanya menjadi shell Windows
- URL default kasir:
  - `https://erp.cvbjasyogya.cloud/kasir/?source=desktop-kasir`
- Modul gudang:
  - `https://erp.cvbjasyogya.cloud/stock/?source=desktop-kasir`

## Isi folder

- `app.py` launcher desktop berbasis `pywebview` dengan fallback ke Edge/Chrome app mode
- `kasir_config.example.json` contoh config runtime
- `requirements.txt` dependensi inti build desktop
- `requirements-webview.txt` dependensi opsional untuk mode `pywebview`
- `build_exe.bat` build `.exe` via PyInstaller
- `run_dev.bat` jalankan wrapper dari Python saat development

## Cara kerja

Saat app dibuka:

1. App membaca `kasir_config.json` di folder yang sama dengan `.exe`
2. Jika file config belum ada, app membuat config default
3. App mencoba membuka ERP web di jendela desktop `pywebview`
4. Jika `pywebview` belum ada, app otomatis fallback membuka ERP di Edge/Chrome app mode
5. Sesi web disimpan di folder AppData agar login tidak hilang setiap kali dibuka

## Fitur pondasi yang sudah disiapkan

- start langsung ke modul kasir atau gudang
- config base URL ERP
- storage sesi lokal desktop
- mode launcher browser yang langsung cocok untuk ERP web production
- bridge native yang siap dipanggil dari web ERP nanti saat mode `pywebview`
- cek koneksi ERP
- cek printer Windows via PowerShell
- bridge lokal `localhost` untuk komunikasi ERP web -> desktop app
- aktivasi printer pilihan seperti `Xprinter` sebelum print
- restore default printer Windows setelah nota selesai dicetak
- perintah print halaman aktif

## Mode aplikasi

- `browser.mode = "auto"`: coba `pywebview`, lalu fallback ke Edge/Chrome
- `browser.mode = "external"`: selalu buka ERP lewat Edge/Chrome app mode
- `browser.mode = "webview"`: paksa `pywebview`, tapi jika dependency belum ada tetap fallback ke browser agar app tidak mentok

Mode `external` cocok untuk kasir harian karena:

- ringan
- tidak tergantung package GUI tambahan
- bisa memakai `--kiosk-printing` untuk alur print ke Xprinter
- tetap mempertahankan sesi login lewat profile browser lokal app

## API bridge yang siap dipakai dari web ERP

Ketika halaman ERP dibuka dari app desktop ini dalam mode `pywebview`, frontend bisa memanggil:

```js
window.pywebview.api.get_app_info()
window.pywebview.api.ping_erp()
window.pywebview.api.open_module("kasir")
window.pywebview.api.open_module("gudang")
window.pywebview.api.print_current_page()
window.pywebview.api.get_printer_snapshot()
window.pywebview.api.get_default_printer()
```

Ini penting untuk tahap berikutnya jika Anda ingin:

- pilih printer Xprinter tertentu dari app kasir
- auto print tanpa dialog browser
- scanner barcode native
- shortcut tombol kasir di Windows

## Bridge lokal desktop

Saat `KasirERP.exe` berjalan, app desktop bisa membuka bridge lokal seperti:

- `http://127.0.0.1:17844/health`
- `http://127.0.0.1:17844/app/info`
- `http://127.0.0.1:17844/printer/snapshot`
- `http://127.0.0.1:17844/printer/default`
- `POST /printer/activate-preferred`
- `POST /printer/restore-default`

ERP web kasir memakai bridge ini untuk alur:

1. checkout selesai
2. kasir pilih mau print atau tidak
3. jika `Ya`, desktop bridge mengaktifkan printer preferensi seperti `Xprinter`
4. halaman nota thermal melakukan print
5. setelah `afterprint`, default printer Windows dikembalikan lagi

## Jalankan versi Python

```powershell
cd desktop\windows_kasir
py -m venv .venv
.venv\Scripts\activate
py -m pip install -r requirements.txt
py app.py --target kasir
```

Kalau ingin mode `pywebview`, install tambahan:

```powershell
py -m pip install -r requirements-webview.txt
```

## Build jadi `.exe`

```powershell
cd desktop\windows_kasir
build_exe.bat
```

Hasil build:

- `desktop\windows_kasir\dist\KasirERP\KasirERP.exe`

## Config runtime

Copy:

- `kasir_config.example.json`

menjadi:

- `kasir_config.json`

Lalu sesuaikan jika perlu.

Contoh field penting:

- `base_url`
- `modules.kasir`
- `modules.gudang`
- `browser.mode`
- `browser.preferred`
- `browser.kiosk_printing`
- `bridge.enabled`
- `bridge.port`
- `window.width`
- `window.height`
- `printer.preferred_printer_name`

## Catatan penting tentang print

Pondasi ini sudah siap untuk:

- mengetahui printer default Windows
- membaca daftar printer Windows
- memicu `window.print()` dari app desktop mode `pywebview`
- membuka ERP lewat Edge/Chrome dengan `--kiosk-printing` saat mode browser aktif

Tetapi pemilihan printer **langsung ke Xprinter tertentu tanpa dialog** belum dihardcode di tahap ini. Itu akan jadi tahap berikutnya dengan native print bridge khusus Windows.

## Tahap lanjutan yang paling masuk akal setelah ini

1. Tambahkan mode login kasir khusus desktop
2. Tambahkan pemilihan printer `Xprinter` by name
3. Tambahkan auto print nota thermal tanpa dialog
4. Tambahkan endpoint handshake ERP web <-> desktop app
5. Tambahkan shortcut native: kasir, gudang, log penjualan, printer status

## Catatan deploy

- Windows target ideal: Windows 10/11
- Untuk mode browser, pastikan Microsoft Edge atau Google Chrome tersedia di Windows
- Untuk mode `pywebview`, pastikan **Microsoft Edge WebView2 Runtime** sudah terpasang
- ERP web tetap harus online agar app bisa dipakai normal
