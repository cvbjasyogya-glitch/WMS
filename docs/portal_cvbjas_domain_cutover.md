# Cutover ERP ke portal.cvbjas.com

Dokumen ini untuk memindahkan ERP dari `erp.cvbjasyogya.cloud` ke `portal.cvbjas.com` secara bertahap. Jalankan portal baru dulu, cek login, baru redirect domain lama.

## 1. DNS

Tambahkan record di DNS:

```text
A  portal  202.10.48.216
```

Sesuaikan IP jika VPS berubah. Tunggu propagasi, lalu cek:

```bash
dig +short portal.cvbjas.com
```

## 2. Pull kode di VPS

```bash
cd /root/WMS
git pull
```

## 3. Siapkan webroot certbot

```bash
sudo mkdir -p /var/www/portal.cvbjas.com/.well-known/acme-challenge
echo ok | sudo tee /var/www/portal.cvbjas.com/.well-known/acme-challenge/test.txt
sudo chown -R www-data:www-data /var/www/portal.cvbjas.com
```

## 4. Pasang Nginx bootstrap HTTP

```bash
cd /root/WMS
sudo cp deploy/nginx/portal.cvbjas.com.bootstrap.conf /etc/nginx/sites-available/portal.cvbjas.com.conf
sudo ln -sf /etc/nginx/sites-available/portal.cvbjas.com.conf /etc/nginx/sites-enabled/portal.cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx
curl -i http://portal.cvbjas.com/.well-known/acme-challenge/test.txt
```

Kalau curl belum menampilkan `ok`, jangan lanjut certbot dulu. Berarti DNS atau Nginx webroot belum benar.

## 5. Ambil SSL

```bash
sudo certbot certonly --webroot -w /var/www/portal.cvbjas.com -d portal.cvbjas.com
```

## 6. Aktifkan Nginx HTTPS portal

```bash
cd /root/WMS
sudo cp deploy/nginx/wms_upstream.conf /etc/nginx/conf.d/wms_upstream.conf
sudo cp deploy/nginx/portal.cvbjas.com.conf /etc/nginx/sites-available/portal.cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx
```

## 7. Update env aplikasi

Untuk cutover Portal saja, sementara SMS masih di domain `.cloud`, jangan pakai `SESSION_COOKIE_DOMAIN=.cvbjasyogya.cloud` karena cookie login tidak berlaku di `portal.cvbjas.com`.

Rekomendasi aman tahap pertama:

```env
CANONICAL_HOST=portal.cvbjas.com
ALLOWED_HOSTS=.cvbjas.com,.cvbjasyogya.cloud
SESSION_COOKIE_DOMAIN=
```

Kalau SMS juga sudah pindah ke `sms.cvbjas.com`, pakai cookie shared `.com`:

```env
CANONICAL_HOST=portal.cvbjas.com
SESSION_COOKIE_DOMAIN=.cvbjas.com
SMS_PUBLIC_HOSTS=sms.cvbjas.com
RECRUITMENT_PUBLIC_HOSTS=recruitment.cvbjas.com
ALLOWED_HOSTS=.cvbjas.com,.cvbjasyogya.cloud
```

Setelah ubah env:

```bash
sudo systemctl restart wms.service
```

## 8. Cek portal baru

```bash
curl --unix-socket /run/wms/gunicorn.sock http://localhost/ready
curl -I https://portal.cvbjas.com/login
curl -I https://portal.cvbjas.com/ready
sudo journalctl -u wms.service -n 80 --no-pager
sudo tail -n 80 /var/log/nginx/error.log
```

Cek manual di browser:

```text
https://portal.cvbjas.com/login
```

Pastikan login berhasil sebelum redirect domain lama.

## 9. Redirect ERP lama setelah portal aman

Jalankan ini hanya setelah `portal.cvbjas.com` sudah bisa login.

```bash
cd /root/WMS
sudo mkdir -p /var/www/erp.cvbjasyogya.cloud/.well-known/acme-challenge
sudo chown -R www-data:www-data /var/www/erp.cvbjasyogya.cloud
sudo cp deploy/nginx/erp.cvbjasyogya.cloud.redirect-to-portal.conf /etc/nginx/sites-available/erp.cvbjasyogya.cloud.conf
sudo nginx -t
sudo systemctl reload nginx
curl -I https://erp.cvbjasyogya.cloud/login
```

Hasil yang dicari: `301` ke `https://portal.cvbjas.com/login`.

## 10. Rollback cepat

Kalau portal bermasalah, balikin env:

```env
CANONICAL_HOST=erp.cvbjasyogya.cloud
SESSION_COOKIE_DOMAIN=.cvbjasyogya.cloud
```

Lalu restore config ERP lama:

```bash
cd /root/WMS
sudo cp deploy/nginx/erp.cvbjasyogya.cloud.conf /etc/nginx/sites-available/erp.cvbjasyogya.cloud.conf
sudo rm -f /etc/nginx/sites-enabled/portal.cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl restart wms.service
```
