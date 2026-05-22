# Hasil Pengecekan & Perbaikan Front-End

## A. Ringkasan Masalah
Project berisi banyak halaman berbasis `base.html`, beberapa halaman standalone seperti login, SMS Storage, dan halaman print. Masalah utama ada pada layout yang terlalu sering mengunci tinggi viewport (`100vh`/`100dvh`), penggunaan `overflow: hidden`, beberapa panel/table yang punya `max-height`, dan style warna yang tersebar di beberapa CSS sehingga tampilan terasa kurang satu tema.

Perbaikan dibuat tanpa menghapus fitur yang sudah ada. Saya menambahkan file global override `static/css/layout_consistency_fixes.css` lalu memanggilnya setelah CSS utama supaya bisa menimpa aturan lama yang menyebabkan halaman kepotong.

## B. Daftar Bug per Area/File

### `templates/base.html`
- Belum ada CSS global terakhir untuk menjaga konsistensi semua halaman.
- Halaman turunan masih bisa terkena aturan lama dari `dashboard.css`, `internal_portal_zip.css`, atau CSS halaman khusus.
- Perbaikan: ditambahkan variable `layout_consistency_css_url` dan link CSS global setelah `{% block extra_head %}`.

### `templates/login.html`, `templates/login_email_required.html`, `templates/login_otp_required.html`
- Halaman login standalone tidak otomatis mendapat CSS override dari `base.html`.
- `login-shell` lama memakai `overflow: hidden`; di layar pendek/mobile landscape form bisa terasa kepotong.
- Perbaikan: link `layout_consistency_fixes.css` ditambahkan dan layout login dibuat scroll-safe.

### `templates/sms_storage.html`
- Halaman standalone tidak lewat `base.html`.
- Layout Drive memakai grid besar dengan sidebar/topbar; di tablet/mobile rawan melebar dan bagian workspace bisa kepotong.
- Perbaikan: link `layout_consistency_fixes.css` ditambahkan, sidebar dan workspace dibuat responsif.

### `templates/stok_gudang.html`
- Sudah memakai CSS khusus `wms_stock_reference.css`, tetapi area tabel/filter rawan terkunci tinggi.
- Perbaikan: body class `wms-stock-reference-shell` dipakai sebagai target override agar halaman stok aman scroll normal.

### `static/css/dashboard.css`
- Ditemukan pola berisiko: `overflow: hidden`, `height: 100vh`, `max-height`, layout grid/flex fixed, dan beberapa table/panel dengan batas tinggi.
- Perbaikan dilakukan melalui override global agar tidak mengubah banyak logic CSS lama.

### `static/css/internal_portal_zip.css`
- Shell internal menggunakan layout grid dua kolom dan beberapa area `overflow: hidden`.
- Perbaikan: internal shell, module shell, content panel, dan sidebar dibuat lebih fleksibel di tablet/mobile.

### `static/css/sms_storage.css`
- Ada layout desktop kuat yang bagus, tetapi butuh guard agar tidak memotong konten saat viewport kecil.
- Perbaikan: `app-shell`, `topbar`, `sidebar`, dan `workspace` dibuat turun ke satu kolom di layar kecil.

### `static/css/career_public_common.css`
- Beberapa shell kandidat memakai `overflow: hidden` dan tinggi minimum tertentu.
- Perbaikan: candidate shell dibuat auto height dan scroll-safe.

## C. Penyebab Halaman Kepotong
Penyebab utama yang ditemukan:

1. `height: 100vh` atau `height: 100dvh` pada shell/sidebar/main tertentu membuat tinggi halaman terkunci setinggi layar.
2. `overflow: hidden` pada shell besar seperti login, internal shell, candidate shell, atau panel membuat konten yang lebih panjang tidak bisa terlihat.
3. `max-height` pada panel/table membuat area bawah tidak selalu terlihat ketika isi panjang.
4. Grid/flex dengan kolom fixed atau `min-width` besar menyebabkan horizontal overflow di tablet/mobile.
5. Tombol/filter/action yang tidak wrap membuat header dan toolbar melebar keluar layar.

Kode perbaikannya ada di:

```css
static/css/layout_consistency_fixes.css
```

## D. Solusi Perbaikan
Solusi yang diterapkan:

1. Menambahkan CSS variable brand global:
   - `--primary-color`
   - `--secondary-color`
   - `--background-color`
   - `--text-color`
   - `--accent-color`
   - `--border-color`
2. Menyamakan warna button, form, card, panel, table, navbar/internal shell, dan background.
3. Mengubah shell besar agar memakai `min-height` + `height: auto`, bukan terkunci `height: 100vh`.
4. Mengatur `overflow-y: auto` pada body dan panel yang perlu scroll.
5. Menambahkan table wrapper yang aman untuk scroll horizontal.
6. Menambahkan breakpoint responsive untuk 1180px, 900px, dan 640px.
7. Menghindari tombol icon menjadi full-width di mobile agar navbar/action tetap rapi.
8. Mempertahankan fitur, teks utama, route, Jinja block, dan JavaScript yang sudah ada.

## E. Kode CSS yang Sudah Dirapikan
Kode final ada di file baru:

```text
static/css/layout_consistency_fixes.css
```

File ini dipasang setelah CSS utama, sehingga menjadi lapisan final untuk:
- scroll normal,
- konsistensi warna,
- table responsive,
- card/panel lebih rapi,
- login scroll-safe,
- internal shell scroll-safe,
- WMS stock scroll-safe,
- SMS Storage responsive.

## F. Kode HTML yang Perlu Diperbaiki
Bagian HTML yang diperbaiki hanya pemanggilan CSS, bukan mengganti struktur fitur.

### `base.html`
Ditambahkan variable dan link CSS global:

```jinja2
{% set layout_consistency_css_url = asset_url('css/layout_consistency_fixes.css') ~ '?v=' ~ (app_version|default('20260522-layout-consistency', true)) %}
...
{% block extra_head %}{% endblock %}
<link rel="stylesheet" href="{{ layout_consistency_css_url }}">
```

### Halaman standalone login
Ditambahkan:

```jinja2
<link rel="stylesheet" href="{{ asset_url('css/layout_consistency_fixes.css') }}?v={{ app_version|default('20260522-layout-consistency', true) }}">
```

### `sms_storage.html`
Ditambahkan:

```jinja2
<link rel="stylesheet" href="{{ url_for('static', filename='css/layout_consistency_fixes.css') }}?v=20260522-layout-consistency">
```

## G. Rekomendasi Struktur Folder
Struktur final yang disarankan dan sudah dipakai di ZIP hasil:

```text
project/
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── stok_gudang.html
│   ├── sms_storage.html
│   └── partials/
├── static/
│   ├── css/
│   │   ├── dashboard.css
│   │   ├── internal_portal_zip.css
│   │   ├── wms_stock_reference.css
│   │   ├── sms_storage.css
│   │   ├── career_public_common.css
│   │   └── layout_consistency_fixes.css
│   ├── js/
│   ├── brand/
│   ├── icons/
│   └── assets/
└── FRONTEND_FIX_REPORT.md
```

Saran lanjutan: ke depannya pindahkan token warna utama ke satu file khusus, misalnya `static/css/theme.css`, lalu import/route file itu sebelum CSS halaman.

## H. Catatan Responsive Design

### Desktop & Laptop
- Layout utama tetap lebar dan card/table tetap nyaman.
- Sidebar internal tetap ada, tetapi konten tidak terkunci tinggi.
- Header/action bisa wrap jika ruang mengecil.

### Tablet
- Module layout turun ke satu kolom ketika ruang tidak cukup.
- Sidebar/panel tidak memaksa lebar tetap.
- Table besar dapat scroll horizontal, bukan memotong halaman.

### Mobile
- Form input full-width.
- Tombol aksi utama full-width, tetapi tombol icon/navbar tidak dipaksa full-width.
- Page hero/action turun vertikal.
- SMS Storage berubah ke layout satu kolom.
- Login bisa scroll normal, terutama di layar pendek/mobile landscape.

## File yang Diubah/Ditambahkan

### Ditambahkan
- `static/css/layout_consistency_fixes.css`
- `FRONTEND_FIX_REPORT.md`

### Diubah
- `templates/base.html`
- `templates/login.html`
- `templates/login_email_required.html`
- `templates/login_otp_required.html`
- `templates/sms_storage.html`

## Cara Pakai
1. Extract ZIP hasil.
2. Copy folder `templates/` dan `static/` ke project Flask kamu.
3. Replace file lama dengan file dari ZIP ini.
4. Restart server Flask.
5. Hard refresh browser: `Ctrl + F5`.
6. Cek halaman penting: login, dashboard, stok gudang, input item, SMS Storage, career, POS, dan halaman admin.
