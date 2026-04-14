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

Codebase saat ini masih memakai `sqlite3` secara langsung di banyak route dan service. Artinya:

- Migrasi data saja belum cukup
- Layer koneksi database perlu direfactor agar mendukung PostgreSQL
- Beberapa query SQLite-spesifik perlu diubah, misalnya `PRAGMA`, `sqlite_master`, dan beberapa fungsi tanggal

Untuk audit cepat file Python yang masih SQLite-spesifik, jalankan:

```bash
python3 scripts/find_sqlite_dependencies.py --root /root/WMS
```

## Rekomendasi Tahap Kerja

1. Siapkan PostgreSQL di VPS.
2. Export snapshot SQLite.
3. Refactor layer database agar dual-mode atau langsung PostgreSQL.
4. Import data ke PostgreSQL.
5. Jalankan smoke test.
6. Switch production saat hasil verifikasi cocok.
