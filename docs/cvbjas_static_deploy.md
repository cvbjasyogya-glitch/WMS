# Deploy Static Web `cvbjas.com`

Sumber web:

`C:\Users\HYPE AMD\Downloads\cvbjas-v15-HOTFIX.zip`

Status kode:

- Web ini static: HTML, CSS, JS, assets, dan video.
- Tidak ada backend/API/database di paket ini.
- Tidak perlu penyesuaian PostgreSQL untuk tahap static.
- Ukuran hasil extract sekitar 106 MB, jadi pastikan storage VPS aman.

Lokasi di repo:

- Static root: `deploy/static/cvbjas.com/`
- Public webroot VPS: `/var/www/cvbjas.com`
- Nginx bootstrap HTTP: `deploy/nginx/cvbjas.com.bootstrap.conf`
- Nginx final HTTPS: `deploy/nginx/cvbjas.com.conf`

## Flow Domain

1. Pengunjung membuka `https://cvbjas.com`.
2. `www.cvbjas.com` redirect ke `https://cvbjas.com`.
3. Nginx serve file static langsung dari `/var/www/cvbjas.com`.
4. Tidak masuk ke Flask/Gunicorn.
5. Portal, recruitment, SMS, dan Mataram tetap domain terpisah.
6. PostgreSQL ERP/WMS tidak disentuh.

## Step Deploy VPS

### 1. DNS

Buat record:

```text
Type: A
Name: @
Value: IP VPS

Type: A
Name: www
Value: IP VPS
```

Tunggu DNS resolve:

```bash
dig +short cvbjas.com
dig +short www.cvbjas.com
```

### 2. Pull kode

```bash
cd /root/WMS
git pull
```

### 3. Copy static site ke public webroot

```bash
sudo mkdir -p /var/www/cvbjas.com
sudo cp -a /root/WMS/deploy/static/cvbjas.com/. /var/www/cvbjas.com/
sudo chown -R www-data:www-data /var/www/cvbjas.com
```

### 4. Pasang Nginx bootstrap HTTP

```bash
cd /root/WMS
sudo cp deploy/nginx/cvbjas.com.bootstrap.conf /etc/nginx/sites-available/cvbjas.com.conf
sudo ln -sf /etc/nginx/sites-available/cvbjas.com.conf /etc/nginx/sites-enabled/cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx
```

Tes HTTP:

```bash
curl -I http://cvbjas.com
curl -I http://www.cvbjas.com
```

Tes challenge manual sebelum certbot:

```bash
sudo mkdir -p /var/www/cvbjas.com/.well-known/acme-challenge
echo ok | sudo tee /var/www/cvbjas.com/.well-known/acme-challenge/test.txt
curl http://cvbjas.com/.well-known/acme-challenge/test.txt
curl http://www.cvbjas.com/.well-known/acme-challenge/test.txt
```

Output harus `ok`.

### 5. Ambil SSL

```bash
sudo certbot certonly --webroot \
  -w /var/www/cvbjas.com \
  -d cvbjas.com \
  -d www.cvbjas.com
```

### 6. Aktifkan config HTTPS final

```bash
cd /root/WMS
sudo cp deploy/nginx/cvbjas.com.conf /etc/nginx/sites-available/cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx
```

### 7. Cek akhir

```bash
curl -I https://cvbjas.com
curl -I https://www.cvbjas.com
curl -I https://cvbjas.com/css/global.css
curl -I https://cvbjas.com/script.js
sudo tail -n 80 /var/log/nginx/error.log
```

## Update Konten

Edit lokal:

```text
deploy/static/cvbjas.com/
```

Setelah push ke GitHub dan pull di VPS:

```bash
cd /root/WMS
git pull
sudo cp -a /root/WMS/deploy/static/cvbjas.com/. /var/www/cvbjas.com/
sudo chown -R www-data:www-data /var/www/cvbjas.com
sudo nginx -t
sudo systemctl reload nginx
```

## Rollback

```bash
sudo rm /etc/nginx/sites-enabled/cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx
```

Rollback ini hanya melepas static site `cvbjas.com`. ERP/WMS, recruitment, SMS, Mataram, dan PostgreSQL tidak ikut berubah.

