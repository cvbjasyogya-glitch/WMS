Production deploy checklist for `erp.cvbjasyogya.cloud`.

1. Copy [.env.production.example](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/.env.production.example) to your VPS `.env` or `EnvironmentFile`.
2. Point Nginx to [deploy/nginx/erp.cvbjasyogya.cloud.conf](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/nginx/erp.cvbjasyogya.cloud.conf).
3. Point systemd to [deploy/systemd/wms.service.example](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/systemd/wms.service.example).
4. Pull the latest code, restart `wms.service`, then reload Nginx.

Notes:
- The example `EnvironmentFile` is optional, so `wms.service` can still boot even before `.env` exists.
- Keep only one active Nginx server block for `erp.cvbjasyogya.cloud`. If `nginx -t` warns about a conflicting `server_name`, disable the older duplicate site before reloading Nginx.
- `wms.service` now binds Gunicorn to `/run/wms/gunicorn.sock` instead of TCP port `8000`, so it avoids `Address already in use` conflicts during restart and keeps the app private behind Nginx.

Recommended VPS commands:

```bash
sudo hostnamectl set-hostname erp.cvbjasyogya.cloud
cd ~/WMS
cp .env.production.example .env
sudo cp deploy/systemd/wms.service.example /etc/systemd/system/wms.service
sudo cp deploy/nginx/erp.cvbjasyogya.cloud.conf /etc/nginx/sites-available/erp.cvbjasyogya.cloud.conf
sudo ln -sf /etc/nginx/sites-available/erp.cvbjasyogya.cloud.conf /etc/nginx/sites-enabled/erp.cvbjasyogya.cloud.conf
sudo systemctl daemon-reload
sudo systemctl restart wms.service
sudo nginx -t
sudo systemctl reload nginx
```

If Nginx reports a duplicate `server_name`, inspect and disable the older file:

```bash
sudo grep -R "server_name erp.cvbjasyogya.cloud" -n /etc/nginx/sites-available /etc/nginx/sites-enabled
ls -l /etc/nginx/sites-enabled
```

Quick checks:

```bash
curl --unix-socket /run/wms/gunicorn.sock http://localhost/login -I
curl -I https://erp.cvbjasyogya.cloud/login
sudo ss -lx | grep gunicorn.sock
sudo journalctl -u wms.service -n 50 --no-pager
sudo tail -n 50 /var/log/nginx/error.log
```
