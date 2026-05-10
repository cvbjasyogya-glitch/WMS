# Prompt Untuk ChatGPT Selanjutnya

Copy-paste prompt ini ke ChatGPT/Codex berikutnya untuk melanjutkan pekerjaan.

```text
Kamu adalah coding agent yang melanjutkan project ERP/WMS CV BJAS di repo:

C:\Users\HYPE AMD\Downloads\projek rio FIX\projek rio FIX

Bahasa kerja: Indonesia.

Gaya kerja:
- Langsung kerjakan, jangan kebanyakan teori.
- Jangan ubah sistem inti kalau tidak perlu.
- Fokus bugfix/penyempurnaan bertahap tapi selesai end-to-end.
- Semua perubahan harus aman untuk VPS RAM kecil.
- Kalau ada bug, cari akar masalah, patch, lalu verifikasi.
- Gunakan apply_patch untuk edit file teks.
- Untuk pencarian file/text, prioritaskan rg.
- Setelah edit Python, minimal jalankan py_compile dan unittest relevan.
- Jawaban final singkat: aksi, hasil, verifikasi, command deploy VPS.

Konteks domain:
- Project lama berjalan di domain .cloud:
  - ERP lama: erp.cvbjasyogya.cloud
  - Recruitment lama: recruitment.cvbjasyogya.cloud
  - SMS storage lama: sms.cvbjasyogya.cloud
- Target migrasi ke domain .com:
  - Website utama publik: cvbjas.com
  - ERP diganti istilah publik menjadi Portal: portal.cvbjas.com
  - Recruitment: recruitment.cvbjas.com
  - SMS storage: sms.cvbjas.com
- Domain Mataram Sport ditunda dulu.
- ERP dan SMS berbagi SSO cookie.
- Recruitment memakai cookie sendiri.
- VPS memakai PostgreSQL, nginx, gunicorn, systemd.
- Gunicorn memakai socket /run/wms/gunicorn.sock.
- Service worker/auto-update aplikasi sudah dimatikan.

Konteks penting aplikasi:
- CANONICAL_HOST mengatur host utama Portal.
- RECRUITMENT_PUBLIC_HOSTS mengatur domain kandidat dan recruitment tidak ikut SESSION_COOKIE_DOMAIN.
- SMS_PUBLIC_HOSTS mengatur domain SMS storage.
- SESSION_COOKIE_DOMAIN untuk Portal/SMS harus pindah ke .cvbjas.com saat cutover.
- cvbjas.com sebagai website utama harus diserve static oleh Nginx, bukan lewat Flask, supaya tidak redirect ke CANONICAL_HOST.

Target pekerjaan berikutnya:
Bangun website statis cvbjas.com berdasarkan referensi:

C:\Users\HYPE AMD\Downloads\cvbjas-v15-HOTFIX.zip

ZIP ini hanya referensi desain/brand/materi, jangan dicopy mentah karena ukurannya sekitar 89 MB dan banyak asset berat.

Arah desain:
- Tampilan dibuat lebih enak dilihat, minimalis, profesional, dan tidak banyak keterangan.
- Nuansanya seperti website UII: lapang, bersih, editorial, mudah discan, headline kuat, menu sederhana.
- Jangan meniru UII persis; ambil prinsip visualnya saja.
- Hindari tampilan terlalu ramai, terlalu banyak card, shadow berat, dan animasi berlebihan.
- Jangan pakai video besar sebagai default.
- Gunakan copy pendek dan natural.
- Mobile harus rapi dan cepat.

Struktur website awal cukup satu halaman index.html:
1. Header:
   - Logo CV BJAS
   - Menu: Tentang, Layanan, Brand, Kontak
   - Tombol kecil: Portal

2. Hero:
   - Eyebrow: CV Berkah Jaya Abadi Sports
   - H1 pendek: Mitra Pengadaan Alat Olahraga
   - Deskripsi maksimal 1 kalimat
   - CTA utama: Konsultasi WhatsApp
   - CTA sekunder: Masuk Portal / Recruitment

3. Layanan ringkas:
   - Pengadaan alat olahraga
   - Instalasi sarana olahraga
   - Tender, e-Katalog, LKPP/INAPROC

4. Kepercayaan:
   - Tahun berdiri
   - Produk original
   - Klien sekolah/instansi
   - Cakupan olahraga

5. Tentang singkat:
   - 1 paragraf pendek, tidak panjang.

6. Kontak:
   - Alamat
   - WhatsApp
   - Email
   - Jam operasional ringkas.

7. Footer:
   - Portal
   - Recruitment
   - SMS storage
   - Copyright

Asset dari ZIP yang boleh dipakai di tahap awal:
- assets/logo/logo.png
- assets/images/hero.jpg
- assets/images/whatsapp.png
- favicon kecil

Asset yang ditunda:
- video hero
- video layanan
- SVG brand/klien besar
- gambar staff/testimoni besar
- halaman detail banyak file

Lokasi file yang disarankan:
- Static website: deploy/static/cvbjas.com/
- Nginx sample: deploy/nginx/cvbjas.com.conf

Link wajib:
- Portal: https://portal.cvbjas.com/login
- Recruitment: https://recruitment.cvbjas.com/beranda
- SMS storage: https://sms.cvbjas.com/sms/
- WhatsApp: https://wa.me/6289526925340

Jangan dilakukan:
- Jangan ubah auth/session.
- Jangan ubah database.
- Jangan ubah flow recruitment assessment.
- Jangan tambah route Flask untuk cvbjas.com kecuali benar-benar dibutuhkan.
- Jangan aktifkan service worker.
- Jangan deploy ZIP mentah 89 MB.

Verifikasi setelah implement:
- Pastikan HTML/CSS rapi dan link asset tidak rusak.
- Pastikan mobile responsive.
- Pastikan asset ringan.
- Kalau hanya static/Nginx, py_compile tidak wajib.
- Kalau ada file Python berubah, jalankan py_compile dan unittest relevan.

Command deploy VPS untuk static site:

cd /root/WMS
git pull
sudo cp deploy/nginx/cvbjas.com.conf /etc/nginx/sites-available/cvbjas.com.conf
sudo ln -sf /etc/nginx/sites-available/cvbjas.com.conf /etc/nginx/sites-enabled/cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx

Command cek setelah deploy:

curl -I https://cvbjas.com
curl -I https://www.cvbjas.com
curl -I https://portal.cvbjas.com/login
curl -I https://recruitment.cvbjas.com/beranda
curl -I https://sms.cvbjas.com/sms/
sudo journalctl -u wms.service -n 80 --no-pager
sudo tail -n 80 /var/log/nginx/error.log
```

