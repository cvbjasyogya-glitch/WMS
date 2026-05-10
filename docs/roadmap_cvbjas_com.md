# Roadmap Migrasi Domain Ke `cvbjas.com`

Fokus utama: pindah dari keluarga domain `.cloud` ke `.com` dengan risiko kecil. Domain Mataram Sport ditunda dulu supaya cutover CV BJAS tidak melebar.

## Mapping Domain

| Fungsi | Domain Lama | Domain Baru |
| --- | --- | --- |
| Website utama | - | `cvbjas.com` |
| Website utama www | - | `www.cvbjas.com` redirect ke `cvbjas.com` |
| Portal internal | `erp.cvbjasyogya.cloud` | `portal.cvbjas.com` |
| Recruitment publik | `recruitment.cvbjasyogya.cloud` | `recruitment.cvbjas.com` |
| SMS storage | `sms.cvbjasyogya.cloud` | `sms.cvbjas.com` |

## Flow Aplikasi Yang Perlu Dijaga

- `CANONICAL_HOST` mengatur host utama Portal. Semua host yang bukan recruitment/SMS akan diarahkan ke canonical host.
- `RECRUITMENT_PUBLIC_HOSTS` mengatur domain khusus kandidat. Recruitment memakai cookie sendiri dan tidak ikut `SESSION_COOKIE_DOMAIN`.
- `SMS_PUBLIC_HOSTS` mengatur domain SMS storage. SMS berbagi login dengan Portal, jadi ikut `SESSION_COOKIE_DOMAIN`.
- `SESSION_COOKIE_DOMAIN` untuk Portal/SMS harus pindah dari `.cvbjasyogya.cloud` ke `.cvbjas.com`.
- `cvbjas.com` sebagai website utama sebaiknya dibuat static di Nginx dulu. Kalau langsung diproxy ke Flask saat ini, aplikasi akan menganggapnya host non-public dan redirect ke `portal.cvbjas.com`.
- Nama publiknya menjadi Portal, tetapi service aplikasi di VPS tetap `wms.service` dan codebase yang sama.

## Referensi Website Statis

Referensi desain: `cvbjas-v15-HOTFIX.zip`.

Isi ZIP:

- Halaman static: `index.html`, `tentang.html`, `layanan.html`, `brand.html`, `klien.html`, `kontak.html`, `kebijakan-privasi.html`.
- Asset brand: logo, favicon, gambar hero, ikon WhatsApp, gambar berita, logo brand/klien, dan video hero/layanan.
- Arah visual: header cream, logo besar, hero visual, CTA WhatsApp, statistik, berita, brand partner, lokasi Google Maps, footer gelap.

Keputusan untuk VPS:

- Jangan deploy ZIP mentah 89 MB.
- Jangan pakai video besar sebagai default, terutama `assets/videos/layanan.mp4`.
- Gunakan versi statis ringan yang mengambil gaya visual dari ZIP.
- Asset awal cukup:
  - logo
  - favicon
  - hero image ringan
  - ikon WhatsApp
  - 1 gambar berita jika perlu
- Logo brand/klien besar dan SVG berat ditunda atau dikompresi dulu.
- Halaman awal cukup `index.html` satu halaman. Halaman detail bisa menyusul setelah domain stabil.
- Website utama diserve langsung oleh Nginx dari folder static, bukan lewat Flask.

Arahan tampilan baru:

- Lebih minimalis, lapang, dan mudah discan.
- Ambil prinsip website UII: headline kuat, whitespace lega, struktur editorial, menu sederhana, dan konten ringkas.
- Jangan meniru desain UII persis; gunakan sebagai rasa visual saja.
- Kurangi keterangan panjang. Satu section cukup 1 headline, 1 kalimat pendek, lalu CTA/link.
- Hindari card terlalu banyak, shadow berat, animasi ramai, dan warna terlalu gelap.
- Gunakan warna corporate yang bersih: putih/cream muda, teks gelap, aksen hijau atau coklat secukupnya.
- Prioritaskan mobile: header ringkas, CTA jelas, tidak ada teks saling menumpuk.

Flow menu website utama:

- Beranda: `https://cvbjas.com`
- Tentang: section di halaman utama atau `tentang.html` fase lanjutan
- Layanan: section di halaman utama atau `layanan.html` fase lanjutan
- Brand: section ringkas dulu
- Klien: section ringkas dulu
- Kontak: WhatsApp dan alamat
- Portal: `https://portal.cvbjas.com/login`
- Recruitment: `https://recruitment.cvbjas.com/beranda`

Prompt implementasi lanjutan disimpan di:

- `docs/prompt_cvbjas_static_site.md`

## Flow Setelah Cutover

### Publik

1. Pengunjung membuka `https://cvbjas.com`.
2. `www.cvbjas.com` redirect ke `https://cvbjas.com`.
3. Menu publik mengarah ke:
   - Portal: `https://portal.cvbjas.com/login`
   - Recruitment: `https://recruitment.cvbjas.com/beranda`
   - SMS storage: `https://sms.cvbjas.com/sms/`

### Internal

1. Staff login melalui `https://portal.cvbjas.com`.
2. Portal dan SMS berbagi SSO cookie di `.cvbjas.com`.
3. HR tetap review kandidat lewat Portal/HRIS.
4. Kandidat baru diarahkan ke `recruitment.cvbjas.com`.
5. Kandidat lama yang masih punya sesi di `recruitment.cvbjasyogya.cloud` dibiarkan selesai dulu sebelum domain lama recruitment di-redirect.

## Prinsip Migrasi

- Jangan langsung pakai redirect permanen `301`. Pakai `302` dulu saat masa transisi agar rollback tidak ketahan cache browser.
- Domain ERP lama boleh langsung diarahkan ke Portal baru setelah cutover.
- SMS lama sebaiknya diarahkan ke SMS baru setelah cutover karena cookie SSO hanya bisa stabil di satu root domain.
- Recruitment lama jangan langsung redirect kalau masih ada kandidat aktif.
- Database tidak perlu disentuh untuk migrasi domain.
- Titik perubahan utama: DNS, Nginx, SSL, `.env`, dan link/copy publik.

## Roadmap Bertahap

### Tahap 0 - Persiapan

- Turunkan TTL DNS kalau panel domain mendukung.
- Pastikan DNS berikut mengarah ke IP VPS:
  - `cvbjas.com`
  - `www.cvbjas.com`
  - `portal.cvbjas.com`
  - `recruitment.cvbjas.com`
  - `sms.cvbjas.com`
- Backup database manual.
- Snapshot konfigurasi:
  - `/root/WMS/.env`
  - `/etc/nginx/sites-available`
  - `/etc/nginx/sites-enabled`
  - status `wms.service`
  - status `wms-db-backup.timer`
- Pastikan tidak ada duplicate Nginx `server_name`.

### Tahap 1 - Siapkan Nginx Dan SSL Domain Baru

- Buat Nginx site baru untuk `portal.cvbjas.com`, `recruitment.cvbjas.com`, dan `sms.cvbjas.com`.
- Semua subdomain aplikasi tetap proxy ke upstream yang sama: `/run/wms/gunicorn.sock`.
- Buat Nginx static ringan untuk `cvbjas.com` dengan referensi desain dari `cvbjas-v15-HOTFIX.zip`.
- `www.cvbjas.com` redirect ke `cvbjas.com`.
- Pasang SSL Let's Encrypt untuk semua host baru.

Catatan:

- Sebelum `.env` diganti, subdomain aplikasi `.com` bisa saja masih redirect ke domain lama karena `CANONICAL_HOST` masih `.cloud`. Itu normal.
- Tes final aplikasi dilakukan setelah `.env` cutover.

### Tahap 2 - Cutover `.env`

Update `.env` production:

```bash
CANONICAL_HOST=portal.cvbjas.com
SESSION_COOKIE_DOMAIN=.cvbjas.com
RECRUITMENT_PUBLIC_HOSTS=recruitment.cvbjas.com,recruitment.cvbjasyogya.cloud
SMS_PUBLIC_HOSTS=sms.cvbjas.com
```

Opsional selama transisi, kalau `ALLOWED_HOSTS` aktif ketat:

```bash
ALLOWED_HOSTS=.cvbjas.com,.cvbjasyogya.cloud
```

Catatan:

- Staff Portal/SMS kemungkinan perlu login ulang.
- Jangan cutover saat kasir/HR sedang aktif berat.
- Jangan redirect recruitment lama saat ada kandidat sedang mengerjakan assessment.

### Tahap 3 - Redirect Domain Lama Dengan Urutan Aman

Setelah `.env` cutover:

- `erp.cvbjasyogya.cloud` redirect `302` ke `portal.cvbjas.com`.
- `sms.cvbjasyogya.cloud` redirect `302` ke `sms.cvbjas.com`.
- `recruitment.cvbjasyogya.cloud` tetap proxy dulu selama kandidat aktif masih mungkin ada.
- Setelah beberapa hari aman, `recruitment.cvbjasyogya.cloud` baru redirect `302` ke `recruitment.cvbjas.com`.
- Setelah semua stabil, redirect bisa dinaikkan dari `302` ke `301`.

### Tahap 4 - Update Link Dan Copy

- Landing `cvbjas.com` mengarah ke domain baru `.com`.
- Menu Portal/internal mengarah ke `portal.cvbjas.com`.
- Link recruitment mengarah ke `recruitment.cvbjas.com`.
- Link SMS storage mengarah ke `sms.cvbjas.com`.
- Template email, WhatsApp, dokumen, bio, dan SOP internal diganti bertahap ke domain `.com`.

### Tahap 4A - Penyempurnaan Website Statis

Setelah domain utama stabil:

- Tambah halaman `tentang.html`, `layanan.html`, `brand.html`, `klien.html`, dan `kontak.html` jika memang dibutuhkan.
- Kompres asset dari ZIP sebelum deploy.
- Ubah video menjadi gambar poster dulu, video hanya dipakai kalau performa VPS dan bandwidth aman.
- Pastikan semua gambar memakai ukuran jelas dan lazy loading.
- Tambahkan sitemap dan meta description final.
- Pastikan tombol Portal, Recruitment, dan WhatsApp jelas terlihat di mobile.

### Tahap 5 - Verifikasi

Checklist wajib:

- `nginx -t` sukses.
- `wms.service` active.
- Socket `/run/wms/gunicorn.sock` ada.
- `/ready` sehat lewat socket dan domain baru.
- `https://cvbjas.com` membuka halaman utama.
- `https://www.cvbjas.com` redirect ke `https://cvbjas.com`.
- `https://portal.cvbjas.com/login` bisa dibuka dan login berhasil.
- `https://recruitment.cvbjas.com/beranda` bisa dibuka.
- `https://sms.cvbjas.com/sms/` bisa dibuka.
- Domain ERP lama dan SMS lama redirect ke domain baru.
- Domain recruitment lama masih bisa dipakai sampai kandidat aktif selesai.
- Tidak ada error baru di journal WMS dan Nginx.

### Tahap 6 - Monitoring

- Pantau login ulang staff.
- Pantau akses recruitment lama dan baru.
- Pantau Nginx access/error log.
- Pantau RAM dan swap.
- Pantau complaint link lama di WhatsApp atau browser bookmark.

## Domain Mataram Sport

Ditunda dulu. Setelah domain CV BJAS stabil:

- Tentukan domain final Mataram Sport.
- Tentukan apakah butuh website publik, POS/customer page, atau hanya redirect.
- Pisahkan branding, asset, SEO, dan copy dari CV BJAS.
- Jangan dicampur dengan migrasi domain `.com`.

## Timeline Eksekusi Malam

- 19:30 - 19:45: backup database dan snapshot konfigurasi.
- 19:45 - 20:15: cek DNS, Nginx, dan SSL domain baru.
- 20:15 - 20:35: siapkan static landing `cvbjas.com` versi ringan dari referensi ZIP.
- 20:35 - 20:50: update `.env` cutover.
- 20:50 - 21:05: restart `wms.service` dan reload Nginx.
- 21:05 - 21:40: smoke test Portal, recruitment, SMS, landing, dan redirect.
- 21:40 - 22:00: keputusan lanjut, tahan transisi, atau rollback.

## Rollback

Rollback utama cukup dari `.env` dan Nginx:

```bash
CANONICAL_HOST=erp.cvbjasyogya.cloud
SESSION_COOKIE_DOMAIN=.cvbjasyogya.cloud
RECRUITMENT_PUBLIC_HOSTS=recruitment.cvbjasyogya.cloud
SMS_PUBLIC_HOSTS=sms.cvbjasyogya.cloud
```

Lalu:

- Disable redirect Nginx domain lama kalau sudah dibuat.
- Restart `wms.service`.
- Reload Nginx.
- Tes domain `.cloud` lama.

Tidak perlu restore database selama perubahan hanya domain/config.

## Command Cek VPS

```bash
cd /root/WMS
git status --short
sudo systemctl status wms.service --no-pager
sudo systemctl status wms-db-backup.timer --no-pager
sudo nginx -t
sudo grep -R "server_name .*cvbjas.com\\|server_name .*cvbjasyogya.cloud" -n /etc/nginx/sites-available /etc/nginx/sites-enabled
curl --unix-socket /run/wms/gunicorn.sock http://localhost/ready
curl -I https://cvbjas.com
curl -I https://www.cvbjas.com
curl -I https://portal.cvbjas.com/login
curl -I https://erp.cvbjasyogya.cloud/login
curl -I https://recruitment.cvbjas.com/beranda
curl -I https://recruitment.cvbjasyogya.cloud/beranda
curl -I https://sms.cvbjas.com/sms/
curl -I https://sms.cvbjasyogya.cloud/sms/
sudo journalctl -u wms.service -n 80 --no-pager
sudo tail -n 80 /var/log/nginx/error.log
```
