# Queue Stringing System

Aplikasi lokal untuk sistem antrian layanan stringing Mega Sports. Stack dibuat ringan dengan Flask, SQLite, HTML, CSS, JavaScript vanilla, Bootstrap, dan Bootstrap Icons.

## Cara install

Windows:

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python init_db.py
python app.py
```

Linux/Mac:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 init_db.py
python3 app.py
```

Aplikasi berjalan di:

```text
http://127.0.0.1:5000
```

Halaman utama `/` langsung menampilkan Customer Display. Halaman admin tetap tersedia lewat `/login`.

## Akun default

```text
username: megasports
role: admin
```

Untuk instalasi baru, set password awal lewat environment variable `DEFAULT_ADMIN_PASSWORD` sebelum menjalankan `python init_db.py`. Password disimpan sebagai hash menggunakan `werkzeug.security`. Setelah login pertama, segera ganti password dari menu `Akun Saya`.

## Struktur project

```text
queue-stringing-system/
|-- app.py
|-- init_db.py
|-- antrian.db
|-- requirements.txt
|-- README.md
|-- templates/
|   |-- base.html
|   |-- login.html
|   |-- dashboard.html
|   |-- antrian_list.html
|   |-- antrian_form.html
|   |-- layar_monitor.html
|   |-- monitoring.html
|   |-- laporan.html
|   |-- users.html
|   |-- account.html
|   `-- settings.html
`-- static/
    |-- css/
    |   `-- style.css
    |-- js/
    |   |-- dashboard.js
    |   |-- antrian.js
    |   `-- monitor.js
    `-- assets/
        `-- placeholder-logo.png
```

## Endpoint penting

- `/login` - halaman login, termasuk tombol Customer Display
- `/dashboard` - statistik harian dan jadwal slot senaran 14:00-20:00
- `/antrian/tambah` - input antrian baru dengan detail per raket
- `/antrian` - daftar antrian hari ini dan update status
- `/` dan `/layar-monitor` - layar TV/customer display tanpa login
- `/api/antrian/monitor` - API JSON monitor dan slot jadwal tanpa login
- `/api/schedule-slots` - API slot untuk form input, wajib login
- `/monitoring` - monitoring antrian dengan filter status/cabang
- `/laporan` - laporan periode dan export CSV
- `/users` - daftar user
- `/account` - ubah nama akun, username, dan password
- `/settings` - informasi setting aplikasi

## Environment security

Untuk production atau akses online, siapkan environment variable berikut:

```text
APP_ENV=production
SECRET_KEY=<random panjang dan unik>
SESSION_COOKIE_SECURE=true
FLASK_DEBUG=false
APP_TIMEZONE=Asia/Jakarta
SENARAN_DATABASE=/var/www/queue-stringing-system/antrian.db
DEFAULT_ADMIN_PASSWORD=<password awal kuat untuk init pertama>
BEHIND_PROXY=true
TRUSTED_HOSTS=senaran.cvbjas.com,127.0.0.1,localhost
```

Catatan:

- Jangan gunakan password default atau password mudah ditebak untuk production.
- Saat `APP_ENV=production`, aplikasi tidak akan start kalau `SECRET_KEY` belum diset.
- `SECRET_KEY` wajib random, panjang, dan tidak dibagikan.
- Set `SESSION_COOKIE_SECURE=true` jika aplikasi diakses lewat HTTPS.
- Jalankan production dengan `FLASK_DEBUG=false`.
- Set `APP_TIMEZONE=Asia/Jakarta` supaya tanggal dan jam operasional tersimpan dalam WIB.
- Gunakan HTTPS saat aplikasi mulai online.
- Jangan taruh `antrian.db` di dalam folder `static`.
- Route public hanya `/layar-monitor` dan `/api/antrian/monitor`; keduanya read-only.
- Backup file `antrian.db` secara berkala.
- Ganti password akun secara berkala.

## Deploy VPS

Contoh flow deploy Linux dengan Gunicorn di belakang Nginx/Caddy:

```bash
cd /var/www/queue-stringing-system
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-production.txt
export APP_ENV=production
export SECRET_KEY="<random panjang>"
export DEFAULT_ADMIN_PASSWORD="<password awal kuat>"
export SENARAN_DATABASE="/var/www/queue-stringing-system/antrian.db"
export SESSION_COOKIE_SECURE=true
export BEHIND_PROXY=true
export TRUSTED_HOSTS="senaran.cvbjas.com,127.0.0.1,localhost"
python init_db.py
gunicorn --bind 127.0.0.1:8000 wsgi:application
```

Reverse proxy domain `senaran.cvbjas.com` diarahkan ke `http://127.0.0.1:8000`. Pastikan HTTPS aktif, port publik hanya `80/443`, dan service Gunicorn dikelola lewat systemd/supervisor agar otomatis hidup setelah reboot.

## Flow coba cepat

1. Jalankan `python init_db.py`.
2. Jalankan `python app.py`.
3. Buka `http://127.0.0.1:5000/login`.
4. Login dengan username `megasports` dan password awal yang diset lewat `DEFAULT_ADMIN_PASSWORD`.
5. Buka menu `Input Antrian Baru`.
6. Pilih layanan, jumlah raket, detail setiap raket, tanggal, dan slot jam 14:00-20:00.
7. Simpan antrian.
8. Buka `Dashboard` untuk melihat jadwal slot dan daftar senaran hari ini.
9. Klik `Panggil` dari `Daftar Antrian Hari Ini`.
10. Buka `http://127.0.0.1:5000/` untuk Customer Display.

## Catatan lokal

- Database menggunakan SQLite di file `antrian.db`.
- `init_db.py` aman dijalankan ulang untuk membuat tabel baru dan menambah kolom migration.
- Cabang input saat ini hanya `Mega Sports`.
- Layanan input saat ini hanya `Stringing Badminton` dan `Stringing Tenis`.
- Nomor antrian reset per hari dengan format `MGA-001`, `MGA-002`.
- Slot jadwal tersedia dari 14:00 sampai 20:00, kapasitas dasar 2 raket per jam.
- Jika satu slot berisi 4 raket atau lebih, slot jam berikutnya otomatis terblokir.
- Untuk deploy VPS, jalankan lewat Gunicorn dan reverse proxy, bukan Flask development server.
