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
- `/layar-monitor` - layar TV/customer display tanpa login
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
SECRET_KEY=<random panjang dan unik>
SESSION_COOKIE_SECURE=true
FLASK_DEBUG=false
DEFAULT_ADMIN_PASSWORD=<password awal kuat untuk init pertama>
```

Catatan:

- Jangan gunakan password default atau password mudah ditebak untuk production.
- `SECRET_KEY` wajib random, panjang, dan tidak dibagikan.
- Set `SESSION_COOKIE_SECURE=true` jika aplikasi diakses lewat HTTPS.
- Jalankan production dengan `FLASK_DEBUG=false`.
- Gunakan HTTPS saat aplikasi mulai online.
- Jangan taruh `antrian.db` di dalam folder `static`.
- Route public hanya `/layar-monitor` dan `/api/antrian/monitor`; keduanya read-only.
- Backup file `antrian.db` secara berkala.
- Ganti password akun secara berkala.

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
10. Buka `http://127.0.0.1:5000/layar-monitor` untuk Customer Display.

## Catatan deploy di repo WMS

- File database dari ZIP tidak disertakan di repo ini.
- Untuk VPS, gunakan environment `SENARAN_DATABASE=/var/lib/senaran/antrian.db`.
- Jalankan `python3 init_db.py` untuk membuat atau migrate SQLite.
- Aplikasi ini berdiri sendiri dan tidak memakai database PostgreSQL ERP/WMS.

## Catatan lokal

- Database menggunakan SQLite di file `antrian.db`.
- `init_db.py` aman dijalankan ulang untuk membuat tabel baru dan menambah kolom migration.
- Cabang input saat ini hanya `Mega Sports`.
- Layanan input saat ini hanya `Stringing Badminton` dan `Stringing Tenis`.
- Nomor antrian reset per hari dengan format `MGA-001`, `MGA-002`.
- Slot jadwal tersedia dari 14:00 sampai 20:00, kapasitas dasar 2 raket per jam.
- Jika satu slot berisi 4 raket atau lebih, slot jam berikutnya otomatis terblokir.
