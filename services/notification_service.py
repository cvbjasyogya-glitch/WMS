import os
import smtplib
from email.message import EmailMessage

from database import get_db

try:
    import requests as http_requests
except ImportError:
    http_requests = None


def _get_recipients_by_roles(roles):
    db = get_db()
    q = f"SELECT id, username, email, phone, role, notify_email, notify_whatsapp, warehouse_id FROM users WHERE role IN ({','.join('?' for _ in roles)})"
    rows = db.execute(q, roles).fetchall()
    return [dict(r) for r in rows]


def _notification_exists_recent(db, recipient, channel, subject, message):
    row = db.execute(
        """
        SELECT id
        FROM notifications
        WHERE recipient=?
          AND channel=?
          AND subject=?
          AND message=?
          AND created_at >= datetime('now', '-2 minutes')
        LIMIT 1
        """,
        (recipient, channel, subject, message),
    ).fetchone()
    return row is not None


def _notification_status(ok):
    if ok is None:
        return "skipped"
    return "sent" if ok else "failed"


def send_email(recipient, subject, body):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    use_tls = os.getenv("SMTP_TLS", "1") != "0"

    if not host or not user or not password:
        print("EMAIL: SMTP not configured")
        return None

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = recipient
        msg.set_content(body)

        if use_tls and port == 587:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(host, port, timeout=10)

        server.login(user, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print("EMAIL SEND ERROR:", e)
        return False


def send_whatsapp(target, message):
    api_key = os.getenv("FONNTE_API_KEY")

    if not api_key or http_requests is None:
        print("WA: not configured or requests missing")
        return None

    try:
        url = "https://api.fonnte.com/send"
        headers = {"Authorization": api_key}
        data = {"target": target, "message": message}
        http_requests.post(url, headers=headers, data=data, timeout=5)
        return True
    except Exception as e:
        print("WA SEND ERROR:", e)
        return False


def notify_roles(roles, subject, message, warehouse_id=None):
    db = get_db()
    recipients = _get_recipients_by_roles(roles)

    # when warehouse_id provided, only notify stakeholders that actually own the scope:
    # target warehouse leaders/admins plus owner/super_admin
    if warehouse_id is not None:
        leaders_target = [
            r for r in recipients
            if r.get('role') == 'leader'
            and r.get('warehouse_id') is not None
            and int(r.get('warehouse_id')) == int(warehouse_id)
        ]

        owners_super = [
            r for r in recipients if r.get('role') in ('owner', 'super_admin')
        ]

        targeted_admins = [
            dict(r)
            for r in db.execute(
                """
                SELECT id, username, email, phone, role, notify_email, notify_whatsapp, warehouse_id
                FROM users
                WHERE role='admin' AND warehouse_id=?
                """,
                (warehouse_id,),
            ).fetchall()
        ]

        # combine, deduplicate by id
        combined = {}
        for r in leaders_target + owners_super + targeted_admins:
            combined[r.get('id')] = r

        recipients = list(combined.values())

    results = {"email": [], "wa": []}
    db = get_db()

    for r in recipients:
        # email (respect user preference)
        if r.get("email") and r.get("notify_email"):
            if not _notification_exists_recent(db, r.get("email"), 'email', subject, message):
                ok = send_email(r.get("email"), subject, message)
                results["email"].append({"to": r.get("email"), "ok": ok})
                try:
                    db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                               (r.get("id"), r.get("role"), 'email', r.get("email"), subject, message, _notification_status(ok)))
                except Exception:
                    pass

        # whatsapp (respect user preference)
        if r.get("phone") and r.get("notify_whatsapp"):
            if not _notification_exists_recent(db, r.get("phone"), 'wa', subject, message):
                ok = send_whatsapp(r.get("phone"), message)
                results["wa"].append({"to": r.get("phone"), "ok": ok})
                try:
                    db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                               (r.get("id"), r.get("role"), 'wa', r.get("phone"), subject, message, _notification_status(ok)))
                except Exception:
                    pass

    # fallback: if no specific contacts, send to configured FONNTE_TARGET and store a notification
    if not recipients and os.getenv("FONNTE_TARGET"):
        if not _notification_exists_recent(db, os.getenv("FONNTE_TARGET"), 'wa', subject, message):
            ok = send_whatsapp(os.getenv("FONNTE_TARGET"), message)
            try:
                db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                           (None, None, 'wa', os.getenv("FONNTE_TARGET"), subject, message, _notification_status(ok)))
            except Exception:
                pass

    try:
        db.commit()
    except Exception:
        pass

    return results


def notify_user(user_id, subject, message):
    db = get_db()
    try:
        u = db.execute("SELECT id, email, phone, notify_email, notify_whatsapp FROM users WHERE id=?", (user_id,)).fetchone()
        if not u:
            return {"email": [], "wa": []}

        u = dict(u)

        results = {"email": [], "wa": []}

        if u.get("email") and u.get("notify_email"):
            if not _notification_exists_recent(db, u.get("email"), 'email', subject, message):
                ok = send_email(u.get("email"), subject, message)
                results["email"].append({"to": u.get("email"), "ok": ok})
                try:
                    db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                               (u.get("id"), None, 'email', u.get("email"), subject, message, _notification_status(ok)))
                except Exception:
                    pass

        if u.get("phone") and u.get("notify_whatsapp"):
            if not _notification_exists_recent(db, u.get("phone"), 'wa', subject, message):
                ok = send_whatsapp(u.get("phone"), message)
                results["wa"].append({"to": u.get("phone"), "ok": ok})
                try:
                    db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                               (u.get("id"), None, 'wa', u.get("phone"), subject, message, _notification_status(ok)))
                except Exception:
                    pass

        try:
            db.commit()
        except Exception:
            pass

        return results
    except Exception as e:
        print("notify_user error:", e)
        return {"email": [], "wa": []}
