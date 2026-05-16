# Deploy Senaran Queue

Domain: `senaran.cvbjas.com`

Aplikasi ini berdiri sendiri di:

```text
deploy/apps/senaran.cvbjas.com/
```

Catatan aman:

- Tidak memakai database ERP.
- Tidak menyentuh PostgreSQL.
- SQLite dipisah di `/var/lib/senaran/antrian.db`.
- Database dari ZIP tidak ikut dipakai, sehingga data awal reset/kosong.
- Service terpisah dari `wms.service`: `senaran.service`.

## Environment

Buat file:

```bash
sudo nano /root/WMS/.env.senaran
```

Isi minimal:

```env
SECRET_KEY=ganti-dengan-random-panjang
DEFAULT_ADMIN_PASSWORD=ganti-password-awal-yang-kuat
SESSION_COOKIE_SECURE=true
APP_TIMEZONE=Asia/Jakarta
SENARAN_DATABASE=/var/lib/senaran/antrian.db
```

`DEFAULT_ADMIN_PASSWORD` hanya dipakai saat database baru pertama dibuat. Setelah login pertama, ganti password dari menu akun.

## Install Service

```bash
cd /root/WMS
git pull
sudo cp deploy/systemd/senaran.service.example /etc/systemd/system/senaran.service
sudo systemctl daemon-reload
sudo systemctl enable --now senaran.service
sudo systemctl status senaran.service --no-pager
```

## Nginx dan SSL

Pastikan DNS `senaran.cvbjas.com` sudah mengarah ke IP VPS.

Bootstrap HTTP untuk Certbot:

```bash
sudo mkdir -p /var/www/senaran.cvbjas.com/.well-known/acme-challenge
sudo cp deploy/nginx/senaran.cvbjas.com.bootstrap.conf /etc/nginx/sites-available/senaran.cvbjas.com.conf
sudo ln -sf /etc/nginx/sites-available/senaran.cvbjas.com.conf /etc/nginx/sites-enabled/senaran.cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/senaran.cvbjas.com -d senaran.cvbjas.com
```

Aktifkan config HTTPS:

```bash
sudo cp deploy/nginx/senaran.cvbjas.com.conf /etc/nginx/sites-available/senaran.cvbjas.com.conf
sudo nginx -t
sudo systemctl reload nginx
```

## Cek

```bash
curl -I https://senaran.cvbjas.com/login
curl -I https://senaran.cvbjas.com/layar-monitor
sudo journalctl -u senaran.service -n 80 --no-pager
sudo tail -n 80 /var/log/nginx/error.log
```
