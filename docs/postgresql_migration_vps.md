# PostgreSQL Migration Notes

Dokumen ini menyiapkan perpindahan data dari SQLite ke PostgreSQL di VPS yang sama tanpa menghapus data lama.

## Prinsip Aman

1. Backup file SQLite aktif.
2. Export semua tabel dari SQLite ke CSV.
3. Siapkan database PostgreSQL baru.
4. Import data ke PostgreSQL.
5. Verifikasi jumlah baris dan sampel data.
6. Setelah verifikasi lolos, baru aplikasi diarahkan ke PostgreSQL.

## Backup SQLite

Contoh pola backup yang aman:

```bash
cp -a /root/WMS/backup_2026-04-03.db /root/WMS/backup_2026-04-03.pre-pg-$(date +%F-%H%M%S).db
```

Jika file aktif aplikasi berbeda dari backup tersebut, backup juga file SQLite aktifnya.

## Cek Target Database Aktif

Jalankan dari root project di VPS:

```bash
python3 scripts/show_database_target.py
```

Kalau backend masih `sqlite`, hasil `database_path` itulah file yang harus dibackup.

## Backup SQLite Yang Disarankan

Untuk backup aman, pakai script backup API SQLite yang sudah ada di project:

```bash
python3 scripts/backup_sqlite_db.py --database /root/WMS/database.db --output-dir /root/WMS/db_backups --retain-days 30
```

Jika `database_path` dari script cek target berbeda, ganti argumen `--database` sesuai path aktif tersebut.

## Export Data SQLite

Jalankan dari root project:

```bash
python3 scripts/export_sqlite_to_csv.py /path/to/database.db --output-dir /root/WMS/sqlite_export_$(date +%F-%H%M%S)
```

Output:

- Satu file CSV per tabel
- `manifest.json` berisi daftar tabel, kolom, dan jumlah baris

## Setup PostgreSQL

Contoh nama database:

- Database: `ERP`
- User: isi lewat env atau command server, jangan hardcode ke repo

Contoh variabel env aplikasi yang nanti akan dipakai:

```bash
export DATABASE_BACKEND=postgresql
export DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/ERP
```

## Catatan Teknis Penting

Codebase sekarang sudah punya layer kompatibilitas PostgreSQL di `database.py`, jadi aplikasi bisa berjalan dengan `DATABASE_BACKEND=postgresql` selama schema inti ERP dan datanya memang sudah ada di PostgreSQL.

Yang perlu diingat:

- `create_app()` hanya menjalankan `init_db()` otomatis untuk backend SQLite.
- Jadi PostgreSQL kosong yang benar-benar fresh tidak akan otomatis dibuatkan seluruh schema ERP dasar saat service start.
- Jalur aman di VPS adalah migrasikan atau import dulu schema+data inti ke PostgreSQL, baru arahkan aplikasi ke backend PostgreSQL.
- Setelah itu, schema tambahan seperti career, overtime, dan beberapa repair sequence PostgreSQL akan disinkronkan oleh helper runtime saat modulnya dipakai.

Untuk audit cepat file Python yang masih mengandung pola SQLite-spesifik, kamu masih bisa jalankan:

```bash
python3 scripts/find_sqlite_dependencies.py --root /root/WMS
```

Untuk verifikasi target backend aktif:

```bash
python3 scripts/show_database_target.py
```

Untuk smoke test PostgreSQL yang sekarang juga memeriksa tabel karir/recruitment:

```bash
python3 scripts/postgresql_smoke_test.py
```

Kalau output `status` masih `incomplete`, berarti masih ada tabel inti yang belum ada di PostgreSQL.

## Rekomendasi Tahap Kerja

1. Siapkan PostgreSQL di VPS.
2. Export snapshot SQLite.
3. Import schema dan data inti ERP ke PostgreSQL.
4. Set `DATABASE_BACKEND=postgresql` dan `DATABASE_URL=...` di `.env` VPS.
5. Jalankan `python3 scripts/show_database_target.py` untuk memastikan app memang mengarah ke PostgreSQL yang benar.
6. Jalankan `python3 scripts/postgresql_smoke_test.py` sampai tabel inti dan tabel recruitment/career sudah terbaca.
7. Restart `wms.service`, lalu cek readiness:

```bash
curl --unix-socket /run/wms/gunicorn.sock http://localhost/ready
curl https://erp.cvbjasyogya.cloud/ready
```

8. Cek halaman publik utama:

```bash
curl -I https://erp.cvbjasyogya.cloud/login
curl -I https://recruitment.cvbjasyogya.cloud/beranda
curl -I "https://recruitment.cvbjasyogya.cloud/karir/summary"
```

9. Baru switch penuh ke production traffic setelah semua check lolos.
