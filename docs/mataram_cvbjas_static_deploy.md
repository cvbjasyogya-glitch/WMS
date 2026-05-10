# Deploy Static Web `mataram.cvbjas.com`

Sumber web:

`C:\Users\HYPE AMD\Downloads\Web mataram.zip`

Status kode:

- Web ini static: `index.html`, `style.css`, `script.js`, dan folder `assets`.
- Tidak ada backend/API/database di dalam ZIP.
- Tidak perlu penyesuaian PostgreSQL untuk tahap ini.
- PostgreSQL baru dibutuhkan kalau nanti produk, promo, kontak, order, atau admin dibuat dinamis.

Lokasi di repo:

- Static root: `deploy/static/mataram.cvbjas.com/`
- Public webroot VPS: `/var/www/mataram.cvbjas.com`
- Nginx bootstrap HTTP: `deploy/nginx/mataram.cvbjas.com.bootstrap.conf`
- Nginx final HTTPS: `deploy/nginx/mataram.cvbjas.com.conf`

## Flow Domain

1. Pengunjung membuka `https://mataram.cvbjas.com`.
2. Nginx serve file static langsung dari `/var/www/mataram.cvbjas.com`.
3. Tidak masuk ke Flask/Gunicorn.
4. Portal, recruitment, dan SMS tetap domain terpisah.
5. PostgreSQL ERP/WMS tidak disentuh.

## Step Deploy VPS

### 1. DNS

Buat record:

```text
Type: A
Name: mataram
Value: IP VPS
TTL: default / rendah
```

Tunggu DNS resolve:

```bash
dig +short mataram.cvbjas.com
```

### 2. Pull kode

```bash
cd /root/WMS
git pull
```

### 3. Copy static site ke public webroot

Nginx sebaiknya serve file public dari `/var/www`, bukan langsung dari `/root/WMS`.

```bash
sudo mkdir -p /var/www/mataram.cvbjas.com
sudo cp -a /root/WMS/deploy/static/mataram.cvbjas.com/. /var/www/mataram.cvbjas.com/
sudo chown -R www-data:www-data /var/www/mataram.cvbjas.com
```

### 4. Pasang Nginx bootstrap HTTP

Bootstrap dipakai dulu agar Let's Encrypt bisa validasi domain tanpa mematikan Nginx.

```bash
cd /root/WMS
sudo cp deploy/nginx/mataram.cvbjas.com.bootstrap.conf /etc/nginx/sites-available/mataram.cvbjas.com.conf
sudo ln -sf /etc/nginx/sites-available/mataram.cvbjas.com.conf /etc/nginx/sites-enabled/mataram.cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx
```

Cek HTTP:

```bash
curl -I http://mataram.cvbjas.com
```

Tes challenge manual sebelum certbot:

```bash
sudo mkdir -p /var/www/mataram.cvbjas.com/.well-known/acme-challenge
echo ok | sudo tee /var/www/mataram.cvbjas.com/.well-known/acme-challenge/test.txt
curl http://mataram.cvbjas.com/.well-known/acme-challenge/test.txt
```

Output harus `ok`. Kalau masih `404`, berarti Nginx config/domain belum mengarah ke site bootstrap yang benar.

### 5. Ambil SSL

```bash
sudo certbot certonly --webroot \
  -w /var/www/mataram.cvbjas.com \
  -d mataram.cvbjas.com
```

### 6. Aktifkan config HTTPS final

```bash
cd /root/WMS
sudo cp deploy/nginx/mataram.cvbjas.com.conf /etc/nginx/sites-available/mataram.cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx
```

### 7. Cek akhir

```bash
curl -I https://mataram.cvbjas.com
curl -I https://mataram.cvbjas.com/style.css
curl -I https://mataram.cvbjas.com/script.js
sudo tail -n 80 /var/log/nginx/error.log
```

## Troubleshooting Certbot 404

Kalau certbot menampilkan:

```text
Invalid response from http://mataram.cvbjas.com/.well-known/acme-challenge/...: 404
```

Jalankan:

```bash
sudo nginx -T | grep -n -A 30 -B 5 "server_name mataram.cvbjas.com"
sudo ls -lah /var/www/mataram.cvbjas.com/.well-known/acme-challenge/
curl -i http://mataram.cvbjas.com/.well-known/acme-challenge/test.txt
```

Yang harus benar:

- `server_name mataram.cvbjas.com` aktif di Nginx.
- `root` mengarah ke `/var/www/mataram.cvbjas.com`.
- File test challenge bisa dibuka via HTTP.
- Tidak ada duplicate server block lain yang mengambil domain `mataram.cvbjas.com`.

## Rollback

Kalau domain bermasalah:

```bash
sudo rm /etc/nginx/sites-enabled/mataram.cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx
```

Rollback ini hanya melepas static site Mataram dari Nginx. ERP/WMS, recruitment, SMS, dan PostgreSQL tidak ikut berubah.
