Production deploy checklist for `erp.cvbjasyogya.cloud`.

1. Copy [.env.production.example](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/.env.production.example) to your VPS `.env` or `EnvironmentFile`.
2. Point Nginx to [deploy/nginx/erp.cvbjasyogya.cloud.conf](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/nginx/erp.cvbjasyogya.cloud.conf).
3. Point systemd to [deploy/systemd/wms.service.example](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/systemd/wms.service.example).
4. Pull the latest code, restart `wms.service`, then reload Nginx.
5. (Optional but recommended) Enable scheduled DB backups with [deploy/systemd/wms-db-backup.service.example](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/systemd/wms-db-backup.service.example) and [deploy/systemd/wms-db-backup.timer.example](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/systemd/wms-db-backup.timer.example).

Notes:
- The example `EnvironmentFile` is optional, so `wms.service` can still boot even before `.env` exists.
- Keep only one active Nginx server block for `erp.cvbjasyogya.cloud`. If `nginx -t` warns about a conflicting `server_name`, disable the older duplicate site before reloading Nginx.
- `wms.service` now binds Gunicorn to `/run/wms/gunicorn.sock` instead of TCP port `8000`, so it avoids `Address already in use` conflicts during restart and keeps the app private behind Nginx.
- `wms.service` also runs a pre-start SQLite backup (`/root/WMS/db_backups`) before launching Gunicorn.
- The sample Gunicorn/Nginx config keeps longer timeouts so heavy operations such as iPOS4 import are less likely to be cut off mid-request on the VPS.
- If you want WhatsApp receipt PDFs to match the browser print layout, install a headless browser on the VPS (for example `chromium-browser`) and set `POS_RECEIPT_PDF_RENDERER=auto` or `html` in `.env`. You can also set `POS_RECEIPT_PDF_BROWSER` explicitly if the binary is in a custom path.

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

Set up automatic DB backups (02:00, 14:00, 19:00 server time):

```bash
cd ~/WMS
sudo cp deploy/systemd/wms-db-backup.service.example /etc/systemd/system/wms-db-backup.service
sudo cp deploy/systemd/wms-db-backup.timer.example /etc/systemd/system/wms-db-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now wms-db-backup.timer
sudo systemctl start wms-db-backup.service
sudo systemctl status wms-db-backup.timer --no-pager
sudo systemctl list-timers --all | grep wms-db-backup
ls -lh /root/WMS/db_backups
```

Notes for scheduled backups:
- Backup files are stored in `/root/WMS/db_backups` using names like `backup_2026-04-03_14-00-00.db`.
- Old backups older than 14 days are deleted automatically by `scripts/backup_sqlite_db.py` (adjust `--retain-days` in the service file if needed).
- Schedule follows server local time. Check with `timedatectl` and set timezone if needed.

Safe update workflow before `git pull` + restart:

```bash
cd ~/WMS
sudo systemctl stop wms.service
python3 scripts/backup_sqlite_db.py --database /root/WMS/database.db --output-dir /root/WMS/db_backups --retain-days 14
git pull
sudo cp deploy/systemd/wms.service.example /etc/systemd/system/wms.service
sudo cp deploy/nginx/erp.cvbjasyogya.cloud.conf /etc/nginx/sites-available/erp.cvbjasyogya.cloud.conf
sudo systemctl daemon-reload
sudo systemctl restart wms.service
sudo nginx -t
sudo systemctl reload nginx
sudo journalctl -u wms.service -n 80 --no-pager
```

If `journalctl` shows `sqlite3.DatabaseError: database disk image is malformed`:

```bash
cd ~/WMS
sudo systemctl stop wms.service
python3 scripts/repair_sqlite_db.py /root/WMS/database.db --replace
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect('/root/WMS/database.db')
print(conn.execute('PRAGMA integrity_check').fetchall())
conn.close()
PY
sudo systemctl start wms.service
sudo journalctl -u wms.service -n 50 --no-pager
```

Notes for SQLite recovery:
- The repair script creates a timestamped backup in `/root/WMS/db_repair_backups` before replacing the broken database.
- If the service log still shows Gunicorn binding to `0.0.0.0:8000`, the VPS is still using the older `wms.service` file. Copy the latest [deploy/systemd/wms.service.example](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/systemd/wms.service.example) and reload `systemd` before testing again.
