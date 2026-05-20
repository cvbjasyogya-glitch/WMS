# Roadmap Audit dan Penyederhanaan UX Operasional

Dokumen ini menjadi pegangan audit bertahap untuk membuat ERP/WMS lebih mudah dipakai, lebih ringan di HP, dan lebih aman untuk VPS kecil. Perbaikan dilakukan per batch supaya tidak merusak flow inti.

## Batasan

- Barcode Studio tidak disentuh dulu.
- Jangan refactor besar lintas modul kalau bug bisa ditutup dengan patch kecil.
- Setiap batch wajib punya verifikasi minimal `py_compile` dan unittest relevan.
- Perubahan UI harus menjaga role, permission, dan alur approval yang sudah ada.
- Fokus utama: mengurangi input berlebihan, reload yang mengganggu, halaman berat, dan flow yang bikin user ragu.

## Audit Full 2026-05-19

Cakupan audit:
- 97 file HTML produksi.
- 17 file CSS produksi.
- 26 file JavaScript produksi.
- 81 file Python produksi.
- Folder `tmp_*` dianggap referensi dan tidak masuk target patch.
- Barcode Studio tetap dikecualikan sesuai batasan.

Temuan prioritas:
- Import preview produk/stok memasukkan data file ke `innerHTML` tanpa escape.
- Preview upload dokumen kandidat menampilkan nama file via `innerHTML` tanpa escape.
- POS dan log penjualan masih memakai reload paksa setelah aksi kecil.
- App shell masih punya jalur reload otomatis dari service worker lama.
- Profil kandidat masih menampilkan terlalu banyak field opsional di tahap awal.
- Review KPI/PMS masih reload halaman.
- Admin hapus user belum punya ringkasan jumlah data terdampak.
- HRIS dan CSS dashboard terlalu besar; refactor dilakukan bertahap setelah bug/UX harian tertutup.

Checklist audit full:
- [x] Inventaris HTML/CSS/JS/Python produksi.
- [x] Identifikasi file besar dan area rawan reload.
- [x] Identifikasi risiko frontend injection.
- [x] Patch import/upload preview yang belum escape.
- [x] Patch reload paksa POS/produk/stok/app shell.
- [x] Ringkas profil recruitment tahap awal.
- [x] Review KPI/PMS tanpa reload.
- [x] Preview dampak hapus user.

Progress eksekusi:
- Import preview produk/stok dan preview upload dokumen kandidat sudah memakai escape HTML sebelum masuk `innerHTML`.
- Undo import produk/stok dan void item POS tidak lagi memaksa reload halaman penuh.
- Profil kandidat tahap awal dibuat lebih pendek; detail tambahan disembunyikan sebagai opsional.
- Review KPI/PMS memakai handler AJAX yang sama dengan report harian/live.
- Admin hapus user menampilkan ringkasan dampak data yang akan dihapus atau dilepas dari akun.
- Cek kompatibilitas VPS PostgreSQL dilakukan pada perubahan admin/HRIS dan schema overtime; aturan pakai saldo lembur maksimal 2 jam per minggu dihapus, sehingga pemakaian reguler bebas selama saldo tersedia dan tetap lewat approval.

## Audit Menyeluruh Lanjutan 2026-05-20

Cakupan scan lanjutan:
- Tetap memakai cakupan produksi audit full: HTML, CSS, JS, Python, route, service, dan template.
- `templates/hris.html` dan `routes/hris.py` masih menjadi modul paling besar.
- `static/css/dashboard.css` masih menjadi stylesheet terbesar dan mempengaruhi banyak halaman.
- Pola dialog browser/reload masih tersebar di POS, stok, produk, request, HRIS, CRM, SMS storage, dan beberapa modul pendukung.
- Pola `innerHTML` masih ada di beberapa builder UI dinamis. Sebagian sudah aman dengan escape helper, tapi tetap jadi area audit setiap patch.
- Barcode Studio tetap dikecualikan sesuai batasan.

Temuan fitur yang ribet, rawan tidak bekerja, atau bisa ditunda:

| Prioritas | Area | Masalah | Alasan | Saran perbaikan |
| --- | --- | --- | --- | --- |
| P0 | HRIS / rekap absensi | Satu halaman memuat terlalu banyak kerja: absensi, jadwal, lembur, payroll, recruitment, dokumen, dan review. | Berat di HP, rawan scroll hilang, dan bug kecil sulit dilacak karena file sangat besar. | Pecah bertahap per tab dengan lazy section dan endpoint AJAX kecil. Mulai dari absensi, report, dan jadwal karena dipakai harian. |
| P0 | POS kasir dan log penjualan | Banyak `alert`, `confirm`, `prompt`, dan redirect setelah aksi kecil. | Kasir bisa kehilangan konteks transaksi, terutama saat void, ubah metode bayar, arsip, atau kirim ulang WA. | Ganti aksi berisiko menjadi modal/action sheet internal, inline validation, dan toast hasil aksi tanpa reload. |
| P0 | Request, inbound, outbound, transfer | Validasi banyak memakai alert umum. | User baru tidak tahu baris atau field mana yang salah. | Tambahkan error inline per baris draft, disable submit sampai data minimal valid, dan pertahankan notifikasi sukses tanpa reload. |
| P0 | Attendance mobile | Kamera, GPS, homebase, shift, dan report gate masih terasa banyak syarat. | HP tertentu sering gagal permission/lokasi; user mengira sistem rusak. | Tampilkan preflight status ringkas: kamera, lokasi, homebase, shift. Fallback lokasi gagal harus jelas untuk role yang diizinkan. |
| P1 | Produk dan stok gudang | Banyak fungsi mirip: import iPOS4, preview, delete, varian, update stok. | Patch satu layar bisa tidak konsisten dengan layar lain. | Ekstrak helper/partial bertahap untuk preview import, konfirmasi hapus, dan card produk. |
| P1 | CRM member dan contact | Daftar besar sudah mulai lazy, tapi filter, member, purchase, dan contact masih padat. | Halaman cepat terasa penuh dan berat ketika user hanya butuh cari 1 pelanggan. | Jadikan search sebagai entry utama, sembunyikan list besar sampai user klik atau filter. |
| P1 | SMS Storage | Folder, rename, delete, dan empty trash masih mengandalkan prompt/confirm browser. | Di mobile rawan typo dan batal tanpa konteks. | Pakai modal kecil untuk folder/rename/delete dengan ringkasan dampak. |
| P1 | Schedule / jadwal | Quick override mulai ada, tapi aksi ubah shift/status masih perlu lebih enak untuk kerja cepat. | HR/leader sering melakukan aksi berulang di banyak tanggal. | Tambahkan toast undo untuk override ringan, dan confirm hanya untuk hapus rentang besar. |
| P1 | Recruitment assessment | Anti-cheat, generate soal, status selesai, dan tampilan mobile masih sensitif. | Kandidat memakai device beragam; Jinja inline di CSS/JS pernah bermasalah. | Jaga JS/CSS bebas inline Jinja kompleks, tes selesai read-only, dan mobile dibuat stepper sederhana. |
| P1 | Login, OTP, device alert | Email, WA, OTP, device baru, dan lokasi login sudah kuat tapi channel-nya banyak. | User bisa bingung kapan harus cek WA, email, atau hubungi admin. | Tambahkan status pengiriman per channel dan copy ringkas: terkirim, gagal provider, atau perangkat WA tidak terhubung. |
| P2 | App shell, service worker, push | Kode service worker/push masih ada walau auto-update dimatikan. | Bisa membuat bug berbeda antara web normal dan app/WebView jika cache lama tersisa. | Tetap nonaktifkan auto-update, tambah halaman diagnosa app/cache, dan jangan aktifkan cache agresif sebelum stabil. |
| P2 | Chat, call, attachment, sticker | Fitur lengkap tapi berat dan memakai media permission. | Tidak semua role butuh call/sticker; bisa menambah beban JS. | Lazy-load fitur call/sticker dan buat feature flag per role. |
| P2 | Print dokumen POS, invoice manual, delivery note | Beberapa flow print mirip tapi terpisah. | Risiko PDF/print beda perilaku antar halaman. | Buat helper print bersama dan fallback PDF konsisten. |
| P2 | Stock opname | Area scan, draft, dan submit bisa panjang. | User bisa kehilangan progress kalau pindah halaman. | Tambahkan status draft tersimpan dan warning keluar jika ada perubahan belum submit. |

Yang bisa dikurangi atau ditunda:
- Service worker auto-update tetap tidak perlu diaktifkan dulu.
- Chat video/call untuk semua role tidak wajib; cukup lazy dan role-based.
- Duplikasi UI produk/stok sebaiknya dikurangi sebelum tambah fitur besar baru.
- Fitur cPanel tidak perlu dijadikan dependensi aplikasi karena VPS ini berjalan via nginx, gunicorn, systemd, dan PostgreSQL.

Backlog eksekusi berikutnya:
- P0.1: Ganti prompt/confirm paling mengganggu di POS dan request menjadi modal internal.
- P0.2: Buat preflight absensi mobile agar user tahu izin kamera/lokasi/homebase/shift sebelum submit.
- P0.4: Kurangi reload/redirect tersisa di aksi kecil HRIS dan POS sales log.
- P1.1: Pecah helper produk/stok untuk import preview dan konfirmasi hapus.
- P1.2: SMS Storage modal folder/rename/delete.
- P1.3: Recruitment mobile stepper dan guard read-only hasil tes.
- P2.1: Diagnosa app/cache untuk membedakan bug web, app, cache, dan permission.
- P2.2: Lazy-load chat call/sticker dan print helper bersama.

Verifikasi wajib saat mulai patch dari audit ini:
- Jalankan `py_compile` untuk route/service yang disentuh.
- Jalankan unittest relevan per area: POS, request, attendance, recruitment, SMS, admin, atau HRIS.
- Jika hanya dokumen roadmap berubah, tidak perlu restart service.

## Batch 1 - Login, App Android, Session, Notifikasi

Status saat roadmap dibuat: fondasi utama sudah masuk di codebase. Tetap perlu regression test saat deploy.

Target:
- Login portal stabil di web dan aplikasi Android.
- Pesan error login manusiawi, bukan lockout berjam-jam.
- App Android/TWA konsisten ke `portal.cvbjas.com`.
- Notifikasi device baru jelas tapi tidak spam.

Audit:
- Login lama masih rawan kebingungan karena transisi username ke email.
- Aplikasi Android bisa terasa bug walau web normal jika masih cache/domain lama.
- Rate limit harus bertahap, bukan langsung lama.
- Notifikasi device baru perlu aktif hanya setelah device pertama tercatat.

Saran patch:
- Pertahankan backoff `5,10,60` detik.
- Pastikan TWA start URL, shortcut, dan app link pakai `portal.cvbjas.com`.
- Tambahkan pesan operasional untuk user yang perlu update/clear data app.
- Tambahkan checklist deploy khusus app Android dan assetlinks.

Verifikasi yang harus dipertahankan:
- `test_login_rate_limit_blocks_repeated_failures`
- `test_login_rate_limit_uses_short_backoff_for_future_timestamps`
- `test_login_new_device_creates_web_email_and_whatsapp_alert`
- `test_android_twa_config_points_to_portal_domain`

Progress eksekusi:
- Checklist QA Android ditambah langkah `Force stop` dan `Clear storage` untuk user/build lama setelah migrasi domain ke `portal.cvbjas.com`.

## Batch 2 - Absensi, Jadwal, Report Harian/Live

Status saat roadmap dibuat: sebagian besar guard penting sudah ada di codebase. Perlu regression test dan patch kecil bila ditemukan flow yang masih reload atau role lintas homebase masih salah.

Target:
- Staff, intern, HR, dan super admin bisa absen sesuai aturan role tanpa tersandung homebase.
- Review report tidak reload halaman.
- Jadwal bisa diedit cepat tanpa dropdown berlapis.

Audit:
- Absensi mobile terlalu tergantung GPS/kamera/homebase sehingga mudah gagal di HP tertentu.
- Review report yang reload membuat HR/leader kehilangan posisi scroll.
- Dropdown shift/status di HRIS terlalu padat untuk kerja cepat.
- Keterangan jadwal seperti OFF dan override perlu satu sumber kebenaran.

Saran patch:
- Mode submit absen tetap jalan saat lokasi gagal, dengan catatan `lokasi tidak terbaca`.
- Role HR dan intern tidak dihitung telat karena beda homebase saat absen lintas cabang.
- Review report memakai AJAX inline.
- Quick action shift/keterangan: `Pagi`, `Siang`, `TS`, `OFF`, `Present`, `Izin`, `Sakit`.

Verifikasi yang harus dipertahankan:
- `test_attendance_portal_allows_intern_submit_when_gps_fails`
- `test_attendance_portal_still_requires_gps_for_non_intern`
- `test_attendance_portal_intern_mega_location_uses_mega_warehouse_and_shift`
- `test_biometric_inline_shift_update_supports_ajax_without_redirect`
- `test_biometric_inline_status_update_supports_ajax_without_redirect`
- `test_daily_report_review_ajax_updates_status_without_redirect`

Progress eksekusi:
- Quick action HRIS rekap absensi ditambahkan di dropdown shift/status. Klik kanan pada dropdown membuka menu cepat dan tetap memakai endpoint AJAX yang sama.
- Quick override jadwal board (`Pagi`, `Siang`, `TS`, dan shift cepat lain) tidak lagi meminta confirm browser setiap klik; aksi langsung submit dengan toast agar HR tidak tersendat saat koreksi banyak tanggal. Confirm tetap dipertahankan untuk aksi hapus jadwal/live.

## Batch 3 - Recruitment Kandidat, Profil, Tes, HR Pipeline

Status saat roadmap dibuat: guard utama sudah ada di codebase dan perlu dijaga lewat regression test. Area lanjutan lebih banyak di polish mobile dan copy.

Target:
- Kandidat bisa daftar cepat.
- CV dan KTP wajib, detail tambahan bertahap.
- Kandidat yang sudah tes tidak bisa mulai ulang dari portal.
- HR menerima data cepat dan rapi.

Audit:
- Profil kandidat terlalu banyak isian untuk tahap melamar.
- Assessment perlu guard agar tidak restart/duplikasi.
- Generate soal harus konsisten untuk kemampuan dasar, TPA, dan studi kasus.
- Tampilan mobile kandidat dan tes harus ringan.

Saran patch:
- Form profil tahap awal: nama, WA, email, posisi, CV, KTP.
- Detail tambahan masuk tahap `lengkapi data` setelah screening.
- Portal kandidat menampilkan status tes: belum mulai, sedang berjalan, selesai.
- Tombol WA untuk kirim link/kode tes dari HR tetap tersedia.

Verifikasi yang harus dipertahankan:
- `test_public_career_profile_page_renders_candidate_sections`
- `test_public_career_candidate_can_upload_required_documents`
- `test_public_career_complete_profile_auto_creates_hr_pipeline_candidate`
- `test_finished_career_assessment_cannot_be_submitted_again`
- `test_finished_public_career_assessment_opens_read_only_from_candidate_portal`
- `test_hr_can_generate_selected_sports_retail_assessment_sections`
- `test_hr_recruitment_pipeline_shows_whatsapp_assessment_share_link`

## Batch 4 - POS, CRM Member, Stock, Request/Approval

Status saat roadmap dibuat: sebagian besar UX berat sudah mulai dipecah. CRM member sudah lazy-load, POS punya smart search, dan request/approval punya test notifikasi/permission.

Target:
- Kasir dan staff fokus ke aksi cepat.
- CRM tidak langsung memuat daftar berat.
- Stock/request lebih mudah dipahami.

Audit:
- POS terlalu banyak fitur dalam satu layar untuk kasir harian.
- CRM member berat karena daftar besar langsung tampil.
- Stock gudang mencampur cek stok, kelola produk, dan mutasi.
- Request owner/approval butuh timeline status yang lebih jelas.

Saran patch:
- POS dibagi secara UI: mode kasir cepat dan mode admin.
- CRM tab member default kosong sampai user search/filter.
- Stock punya pintu kerja: `Cek Stok`, `Update Stok`, `Kelola Produk`.
- Request/approval memakai ringkasan status dan timeline sederhana.

Verifikasi yang harus dipertahankan:
- `test_crm_contacts_tab_defers_contact_matrix_until_requested`
- `test_crm_member_tab_defers_member_lists_until_requested`
- `test_pos_page_directly_adds_selected_item_without_draft_panel`
- `test_pos_customer_options_endpoint_finds_member_beyond_initial_dropdown_limit`
- `test_request_page_supports_custom_non_wms_inputs_and_rows`
- `test_admin_can_create_owner_request_batch_and_notify_owner`
- `test_approval_page_keeps_sticky_action_column_and_buttons_visible`

Progress eksekusi:
- Request Owner sekarang punya timeline status ringkas `Diajukan -> Diproses -> Selesai/Ditolak`.
- Update status Request Owner memakai AJAX ketika browser mendukung, jadi owner/super admin tidak kehilangan posisi halaman setelah klik `Proses`, `Selesai`, atau `Tolak`.
- Halaman Approval diberi alur ringkas agar user paham status kerja: `Diajukan -> Review -> Setujui/Tolak -> Notifikasi requester`.
- Request antar gudang dan Request Owner tidak lagi memakai `alert/confirm` browser untuk validasi batch; feedback tampil inline dan lewat toast.
- Inbound dan outbound batch tidak lagi memakai `alert()` browser untuk validasi item kosong, qty salah, biaya modal salah, atau stok melebihi; pesan tampil inline dan data item dirender dengan escape HTML.
- Transfer antar gudang tidak lagi memakai `alert()` browser saat validasi batch; error gudang, item kosong, dan stok melebihi tampil inline tanpa memutus konteks user.
- POS kasir mulai memakai helper toast/internal dialog untuk validasi dasar dan void barang, sehingga kasir tidak diputus oleh prompt browser.
- POS Sales Log memakai input tanggal langsung di menu aksi, modal void internal, dan resend WA tanpa confirm browser. Aksi Hidden Archive sengaja tidak diubah.
- Studio Produk pada workspace stok mulai memakai modal internal untuk aksi berisiko: undo import iPOS4, hapus produk terpilih, hapus satu produk, dan hapus semua produk. Dialog browser `prompt/confirm/alert` tidak lagi dipakai pada jalur destruktif produk ini.
- Bulk adjust stok tidak lagi memakai `prompt()` browser untuk qty penyesuaian; qty masuk lewat modal internal dengan validasi inline.

## Batch 5 - Admin, Permission, SMS Storage, Modul Pendukung

Status saat roadmap dibuat: guard penting sudah ada untuk hapus user, permission, SMS storage, audit, dan notification policy. Lanjutan fokus pada copy konfirmasi dan ringkasan dampak agar admin tidak salah klik.

Target:
- Admin aman dipakai tanpa takut salah hapus/ubah role.
- SMS storage dan arsip mudah dicari.
- Permission lebih jelas untuk super admin.

Audit:
- Admin user dan permission punya risiko tinggi karena dampaknya lintas sistem.
- Hapus user harus punya ringkasan data yang ikut terhapus.
- SMS storage cukup ringan, tapi domain/cookie/link sering membingungkan.

Saran patch:
- Wizard konfirmasi untuk hapus user: tampilkan data yang akan ikut dihapus.
- Permission admin diberi label dampak, bukan hanya nama teknis.
- SMS storage dashboard: arsip hari ini, cari kandidat, download TXT.

Verifikasi yang harus dipertahankan:
- `test_super_admin_can_delete_user_even_if_view_admin_override_denied`
- `test_super_admin_delete_user_clears_biometric_handled_by_reference`
- `test_super_admin_delete_user_removes_owned_user_data`
- `test_super_admin_can_grant_crm_access_to_intern_via_admin_permission_page`
- `test_sms_storage_dashboard_renders_awanark_like_workspace`
- `test_sms_storage_isolated_per_logged_in_user`
- `test_owner_audit_page_hides_super_admin_private_rows`

Progress eksekusi:
- Konfirmasi hapus user diperjelas agar super admin sadar data terkait ikut dibersihkan atau dilepas dari akun sebelum submit.
- SMS Storage Home diberi aksi cepat HR: `Arsip hari ini`, `Cari kandidat`, dan `File TXT`, memakai search/index existing supaya ringan dan tidak menambah beban backend.
- Permission admin diberi label dampak (`Dampak tinggi`, `Dampak operasional`, `Dampak ringan`) dan copy pendek agar super admin lebih sadar risiko saat grant/cabut akses.
- SMS Storage folder baru, rename, pindah ke trash, hapus permanen, dan empty trash memakai dialog internal, bukan prompt/confirm browser.

## Pengecualian Saat Ini

Jangan patch dulu:
- `templates/barcode.html`
- UI Barcode Studio
- endpoint dan schema barcode di `routes/stock.py`, kecuali ada bug keamanan kritis
- asset/domain `barcode.cvbjas.com`

## Urutan Eksekusi

1. Selesaikan Batch 1 karena menyangkut akses semua user.
2. Lanjut Batch 2 karena absensi dan report paling sering dipakai harian.
3. Lanjut Batch 3 untuk mengurangi hambatan recruitment.
4. Lanjut Batch 4 untuk performa POS/CRM/Stock.
5. Lanjut Batch 5 untuk keamanan admin dan arsip.

## Format Output Setiap Batch

Setiap batch harus menghasilkan:
- temuan utama
- file yang disentuh
- patch kecil yang sudah dilakukan
- command verifikasi
- command deploy VPS
