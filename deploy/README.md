Production deploy checklist for `erp.cvbjasyogya.cloud`.

1. Copy [.env.production.example](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/.env.production.example) to your VPS `.env` or `EnvironmentFile`.
   Important:
   For VPS PostgreSQL, set `DATABASE_BACKEND=postgresql` and fill `DATABASE_URL` with the production DSN before restarting `wms.service`.
2. Copy [deploy/nginx/wms_upstream.conf](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/nginx/wms_upstream.conf) to `/etc/nginx/conf.d/wms_upstream.conf`.
3. Point Nginx to [deploy/nginx/erp.cvbjasyogya.cloud.conf](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/nginx/erp.cvbjasyogya.cloud.conf).
4. Point systemd to [deploy/systemd/wms.service.example](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/systemd/wms.service.example).
5. Pull the latest code, restart `wms.service`, then reload Nginx.
6. (Optional but recommended) Enable scheduled DB backups with [deploy/systemd/wms-db-backup.service.example](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/systemd/wms-db-backup.service.example) and [deploy/systemd/wms-db-backup.timer.example](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/systemd/wms-db-backup.timer.example).

Brevo SMTP for career and auth emails:
- The app already sends career/account emails through `services.notification_service.send_email()`, so Brevo works without extra plugin.
- Fill `.env` with:
  `SMTP_HOST=smtp-relay.brevo.com`
  `SMTP_PORT=587`
  `SMTP_USER=<brevo-login>`
  `SMTP_PASS=<brevo-smtp-key>`
  `SMTP_TLS=1`
  `SMTP_SSL=0`
  `SMTP_FROM_EMAIL=<verified-sender@domain>`
  `SMTP_FROM_NAME=CV Berkah Jaya Abadi Sports Career`
- `SMTP_FROM_EMAIL` and `SMTP_FROM_NAME` are optional overrides for the sender shown to candidates. If omitted, the app falls back to `SMTP_USER`.

Public recruitment domain:
- Use [deploy/nginx/recruitment.cvbjasyogya.cloud.conf](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/nginx/recruitment.cvbjasyogya.cloud.conf) if you want `recruitment.cvbjasyogya.cloud` to point to the same Gunicorn socket.
- Add `RECRUITMENT_PUBLIC_HOSTS=recruitment.cvbjasyogya.cloud` to `.env`.
- Keep `CANONICAL_HOST=erp.cvbjasyogya.cloud` so the ERP stays on the main domain while the recruitment host stays on the career experience and routes `/` directly to `/signin` instead of bouncing to ERP.

Public SMS cloud storage domain:
- Use [deploy/nginx/sms.cvbjasyogya.cloud.conf](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/deploy/nginx/sms.cvbjasyogya.cloud.conf) if you want `sms.cvbjasyogya.cloud` to point to the same Gunicorn socket.
- Add `SMS_PUBLIC_HOSTS=sms.cvbjasyogya.cloud` to `.env`.
- Keep `CANONICAL_HOST=erp.cvbjasyogya.cloud` so the ERP stays on the main domain while the SMS host routes `/` directly to `/sms/`.
- Point DNS `sms.cvbjasyogya.cloud` to the same VPS as the main ERP before requesting the TLS certificate.

Notes:
- The example `EnvironmentFile` is optional, so `wms.service` can still boot even before `.env` exists.
- Keep only one active Nginx server block for `erp.cvbjasyogya.cloud`. If `nginx -t` warns about a conflicting `server_name`, disable the older duplicate site before reloading Nginx.
- `wms.service` now binds Gunicorn to `/run/wms/gunicorn.sock` instead of TCP port `8000`, so it avoids `Address already in use` conflicts during restart and keeps the app private behind Nginx.
- `wms.service` runs a configured backup hook before launching Gunicorn. When backend is `sqlite`, it writes file backups to `/root/WMS/db_backups`. When backend is `postgresql`, it writes `pg_dump` backups to `/root/WMS/db_backups/postgresql`.
- The sample Gunicorn/Nginx config keeps longer timeouts so heavy operations such as iPOS4 import are less likely to be cut off mid-request on the VPS.
- Endpoint `GET /ready` already checks the active database connection. Use it after every restart, especially after switching to PostgreSQL.
- Fresh empty PostgreSQL is not enough on its own. The app expects the base ERP schema and data to already exist after migration/import. Use [docs/postgresql_migration_vps.md](/c:/Users/Editing%20PC%20Mega/Downloads/projek%20rio%20FIX/projek%20rio%20FIX/docs/postgresql_migration_vps.md) plus `python3 scripts/postgresql_smoke_test.py` before pointing production traffic to PostgreSQL.
- If you want WhatsApp receipt PDFs to match the browser print layout, install a headless browser on the VPS (for example `chromium-browser`) and set `POS_RECEIPT_PDF_RENDERER=auto` or `html` in `.env`. You can also set `POS_RECEIPT_PDF_BROWSER` explicitly if the binary is in a custom path.

Recommended VPS commands:

```bash
sudo hostnamectl set-hostname erp.cvbjasyogya.cloud
cd ~/WMS
cp .env.production.example .env
sudo cp deploy/systemd/wms.service.example /etc/systemd/system/wms.service
sudo cp deploy/nginx/wms_upstream.conf /etc/nginx/conf.d/wms_upstream.conf
sudo cp deploy/nginx/erp.cvbjasyogya.cloud.conf /etc/nginx/sites-available/erp.cvbjasyogya.cloud.conf
sudo ln -sf /etc/nginx/sites-available/erp.cvbjasyogya.cloud.conf /etc/nginx/sites-enabled/erp.cvbjasyogya.cloud.conf
sudo systemctl daemon-reload
sudo systemctl restart wms.service
sudo nginx -t
sudo systemctl reload nginx
```

Enable the recruitment domain on the same VPS:

```bash
cd ~/WMS
sudo cp deploy/nginx/recruitment.cvbjasyogya.cloud.conf /etc/nginx/sites-available/recruitment.cvbjasyogya.cloud.conf
sudo ln -sf /etc/nginx/sites-available/recruitment.cvbjasyogya.cloud.conf /etc/nginx/sites-enabled/recruitment.cvbjasyogya.cloud.conf
sudo cp deploy/nginx/wms_upstream.conf /etc/nginx/conf.d/wms_upstream.conf
echo "RECRUITMENT_PUBLIC_HOSTS=recruitment.cvbjasyogya.cloud" | sudo tee -a /root/WMS/.env
sudo systemctl restart wms.service
sudo nginx -t
sudo systemctl reload nginx
```

Enable the SMS cloud storage domain on the same VPS:

```bash
cd ~/WMS
sudo cp deploy/nginx/sms.cvbjasyogya.cloud.conf /etc/nginx/sites-available/sms.cvbjasyogya.cloud.conf
sudo ln -sf /etc/nginx/sites-available/sms.cvbjasyogya.cloud.conf /etc/nginx/sites-enabled/sms.cvbjasyogya.cloud.conf
sudo cp deploy/nginx/wms_upstream.conf /etc/nginx/conf.d/wms_upstream.conf
grep -q '^SMS_PUBLIC_HOSTS=' /root/WMS/.env \
  && sudo sed -i 's/^SMS_PUBLIC_HOSTS=.*/SMS_PUBLIC_HOSTS=sms.cvbjasyogya.cloud/' /root/WMS/.env \
  || echo "SMS_PUBLIC_HOSTS=sms.cvbjasyogya.cloud" | sudo tee -a /root/WMS/.env
sudo systemctl restart wms.service
sudo nginx -t
sudo systemctl reload nginx
```

If Nginx reports a duplicate `server_name`, inspect and disable the older file:

```bash
sudo grep -R "server_name erp.cvbjasyogya.cloud" -n /etc/nginx/sites-available /etc/nginx/sites-enabled
ls -l /etc/nginx/sites-enabled
```

Troubleshooting `recruitment.cvbjasyogya.cloud` if it still shows the old offline page:

```bash
cd ~/WMS
git pull
grep -E '^(ALLOWED_HOSTS|RECRUITMENT_PUBLIC_HOSTS|SMS_PUBLIC_HOSTS|CANONICAL_HOST|APP_VERSION)=' /root/WMS/.env
sudo grep -R "server_name erp.cvbjasyogya.cloud" -n /etc/nginx/sites-available /etc/nginx/sites-enabled
ls -l /etc/nginx/sites-enabled
sudo systemctl restart wms.service
sudo nginx -t
sudo systemctl reload nginx
curl -I https://recruitment.cvbjasyogya.cloud/beranda
curl -I https://recruitment.cvbjasyogya.cloud/service-worker.js
sudo journalctl -u wms.service -n 80 --no-pager
```

Expected result:
- only one active Nginx site should own `server_name erp.cvbjasyogya.cloud`,
- `.env` should keep `RECRUITMENT_PUBLIC_HOSTS=recruitment.cvbjasyogya.cloud` and `CANONICAL_HOST=erp.cvbjasyogya.cloud`,
- the latest recruitment host build no longer shows the old offline CTA text `Kembali ke ERP`; it should use the updated public-host cleanup flow instead.

If the server checks are already healthy but the browser still shows the old offline card, clear site data or unregister the stale service worker for `recruitment.cvbjasyogya.cloud`, then reload the page.

Quick checks:

```bash
curl --unix-socket /run/wms/gunicorn.sock http://localhost/login -I
curl --unix-socket /run/wms/gunicorn.sock http://localhost/ready
curl -I https://erp.cvbjasyogya.cloud/login
curl https://erp.cvbjasyogya.cloud/ready
python3 scripts/show_database_target.py
python3 scripts/postgresql_smoke_test.py
sudo ss -lx | grep gunicorn.sock
sudo journalctl -u wms.service -n 50 --no-pager
sudo tail -n 50 /var/log/nginx/error.log
```

Set up automatic DB backups (02:00 and 12:00 server time):

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
- SQLite backups are stored in `/root/WMS/db_backups` using names like `backup_2026-04-03_14-00-00.db`.
- PostgreSQL backups are stored in `/root/WMS/db_backups/postgresql` using names like `backup_2026-04-15_03-55-00.dump`.
- Old backups older than 14 days are deleted automatically by the matching backup script (adjust `--retain-days` in the service file if needed).
- Schedule follows server local time. Check with `timedatectl` and set timezone if needed.

Safe update workflow before `git pull` + restart:

```bash
cd ~/WMS
sudo systemctl stop wms.service
python3 scripts/run_configured_backup.py --output-dir /root/WMS/db_backups --retain-days 14
git pull
sudo cp deploy/systemd/wms.service.example /etc/systemd/system/wms.service
sudo cp deploy/nginx/wms_upstream.conf /etc/nginx/conf.d/wms_upstream.conf
sudo cp deploy/nginx/erp.cvbjasyogya.cloud.conf /etc/nginx/sites-available/erp.cvbjasyogya.cloud.conf
sudo systemctl daemon-reload
sudo systemctl restart wms.service
sudo nginx -t
sudo systemctl reload nginx
sudo journalctl -u wms.service -n 80 --no-pager
```

If `journalctl` shows `sqlite3.DatabaseError: database disk image is malformed` while backend is still SQLite:

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
