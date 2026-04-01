import os
import smtplib
import json
from email.message import EmailMessage

from flask import current_app

from database import get_db
from services.announcement_center import role_matches_audience, user_matches_scope

try:
    import requests as http_requests
except ImportError:
    http_requests = None

try:
    from pywebpush import WebPushException, webpush
except ImportError:
    WebPushException = Exception
    webpush = None


def _normalize_recipient(value):
    return (value or "").strip()


def _normalize_roles(roles):
    cleaned = []
    seen = set()
    for role in roles or []:
        normalized = (role or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def _normalize_user_ids(user_ids):
    cleaned = []
    seen = set()
    for value in user_ids or []:
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned.append(normalized)
    return cleaned


def _get_recipients_by_roles(roles):
    roles = _normalize_roles(roles)
    if not roles:
        return []

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


def _insert_notification_record(db, user_id, role, channel, recipient, subject, message, ok):
    try:
        db.execute(
            """
            INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status)
            VALUES (?,?,?,?,?,?,?)
            """,
            (user_id, role, channel, recipient, subject, message, _notification_status(ok)),
        )
    except Exception:
        pass


def _get_broadcast_recipients(audience="all", warehouse_id=None, user_ids=None, exclude_user_ids=None):
    db = get_db()
    params = []
    clauses = []
    user_ids = _normalize_user_ids(user_ids)
    exclude_user_ids = _normalize_user_ids(exclude_user_ids)

    if user_ids:
        clauses.append(f"id IN ({','.join('?' for _ in user_ids)})")
        params.extend(user_ids)

    if exclude_user_ids:
        clauses.append(f"id NOT IN ({','.join('?' for _ in exclude_user_ids)})")
        params.extend(exclude_user_ids)

    query = """
        SELECT id, username, email, phone, role, notify_email, notify_whatsapp, warehouse_id
        FROM users
    """
    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    rows = [dict(row) for row in db.execute(query, params).fetchall()]
    recipients = []
    for row in rows:
        role = row.get("role")
        if not role_matches_audience(role, audience):
            continue
        if not user_matches_scope(role, row.get("warehouse_id"), warehouse_id):
            continue
        recipients.append(row)
    return recipients


def _webpush_is_ready():
    if webpush is None:
        return False
    return bool(
        current_app.config.get("WEBPUSH_PRIVATE_KEY")
        and current_app.config.get("WEBPUSH_SUBJECT")
    )


def _send_web_push(db, subscription, payload):
    if not _webpush_is_ready():
        return None

    try:
        webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": {
                    "p256dh": subscription["p256dh_key"],
                    "auth": subscription["auth_key"],
                },
            },
            data=json.dumps(payload),
            vapid_private_key=current_app.config.get("WEBPUSH_PRIVATE_KEY"),
            vapid_claims={"sub": current_app.config.get("WEBPUSH_SUBJECT")},
        )
        db.execute(
            """
            UPDATE push_subscriptions
            SET last_notified_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (subscription["id"],),
        )
        return True
    except WebPushException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in {404, 410}:
            try:
                db.execute(
                    """
                    UPDATE push_subscriptions
                    SET is_active=0,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (subscription["id"],),
                )
            except Exception:
                pass
        print("WEB PUSH ERROR:", exc)
        return False
    except Exception as exc:
        print("WEB PUSH ERROR:", exc)
        return False


def send_email(recipient, subject, body):
    recipient = _normalize_recipient(recipient)
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    use_ssl = os.getenv("SMTP_SSL", "0") == "1"
    use_tls = os.getenv("SMTP_TLS", "1") != "0"

    if not recipient:
        return None

    if not host or not user or not password:
        print("EMAIL: SMTP not configured")
        return None

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = recipient
        msg.set_content(body)

        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
            if use_tls:
                server.ehlo()
                server.starttls()
                server.ehlo()

        server.login(user, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print("EMAIL SEND ERROR:", e)
        return False


def send_whatsapp(target, message):
    target = _normalize_recipient(target)
    api_key = os.getenv("FONNTE_API_KEY")

    if not target:
        return None

    if not api_key or http_requests is None:
        print("WA: not configured or requests missing")
        return None

    try:
        url = "https://api.fonnte.com/send"
        headers = {"Authorization": api_key}
        data = {"target": target, "message": message}
        response = http_requests.post(url, headers=headers, data=data, timeout=5)

        if not getattr(response, "ok", False):
            print("WA SEND ERROR: HTTP", getattr(response, "status_code", "unknown"))
            return False

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            status = payload.get("status")
            success = payload.get("success")
            normalized_status = str(status).strip().lower() if status is not None else ""
            if status is False or success is False:
                return False
            if normalized_status in {"false", "0", "error", "failed"}:
                return False

        return True
    except Exception as e:
        print("WA SEND ERROR:", e)
        return False


def notify_roles(roles, subject, message, warehouse_id=None):
    roles = _normalize_roles(roles)
    if not roles:
        return {"email": [], "wa": []}

    recipients = _get_recipients_by_roles(roles)

    # when warehouse_id provided, only notify the source-warehouse leader
    # plus global approvers (owner/super_admin)
    if warehouse_id is not None:
        combined = {}
        for r in recipients:
            role = r.get("role")
            user_warehouse = r.get("warehouse_id")

            if role == "leader":
                try:
                    if user_warehouse is None or int(user_warehouse) != int(warehouse_id):
                        continue
                except (TypeError, ValueError):
                    continue
            elif role not in ("owner", "super_admin"):
                continue

            combined[r.get('id')] = r

        recipients = list(combined.values())

    results = {"email": [], "wa": []}
    db = get_db()

    for r in recipients:
        # email (respect user preference)
        email = _normalize_recipient(r.get("email"))
        phone = _normalize_recipient(r.get("phone"))

        if email and r.get("notify_email"):
            if not _notification_exists_recent(db, email, 'email', subject, message):
                ok = send_email(email, subject, message)
                results["email"].append({"to": email, "ok": ok})
                try:
                    db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                               (r.get("id"), r.get("role"), 'email', email, subject, message, _notification_status(ok)))
                except Exception:
                    pass

        # whatsapp (respect user preference)
        if phone and r.get("notify_whatsapp"):
            if not _notification_exists_recent(db, phone, 'wa', subject, message):
                ok = send_whatsapp(phone, message)
                results["wa"].append({"to": phone, "ok": ok})
                try:
                    db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                               (r.get("id"), r.get("role"), 'wa', phone, subject, message, _notification_status(ok)))
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
        email = _normalize_recipient(u.get("email"))
        phone = _normalize_recipient(u.get("phone"))

        if email and u.get("notify_email"):
            if not _notification_exists_recent(db, email, 'email', subject, message):
                ok = send_email(email, subject, message)
                results["email"].append({"to": email, "ok": ok})
                try:
                    db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                               (u.get("id"), None, 'email', email, subject, message, _notification_status(ok)))
                except Exception:
                    pass

        if phone and u.get("notify_whatsapp"):
            if not _notification_exists_recent(db, phone, 'wa', subject, message):
                ok = send_whatsapp(phone, message)
                results["wa"].append({"to": phone, "ok": ok})
                try:
                    db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                               (u.get("id"), None, 'wa', phone, subject, message, _notification_status(ok)))
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


def notify_broadcast(
    subject,
    message,
    *,
    audience="all",
    warehouse_id=None,
    user_ids=None,
    exclude_user_ids=None,
    push_title=None,
    push_body=None,
    push_url="/announcements/",
    push_tag=None,
):
    recipients = _get_broadcast_recipients(
        audience=audience,
        warehouse_id=warehouse_id,
        user_ids=user_ids,
        exclude_user_ids=exclude_user_ids,
    )
    results = {"email": [], "wa": [], "push": []}
    db = get_db()

    for recipient_info in recipients:
        email = _normalize_recipient(recipient_info.get("email"))
        phone = _normalize_recipient(recipient_info.get("phone"))
        user_id = recipient_info.get("id")
        role = recipient_info.get("role")

        if email and recipient_info.get("notify_email"):
            if not _notification_exists_recent(db, email, "email", subject, message):
                ok = send_email(email, subject, message)
                results["email"].append({"to": email, "ok": ok})
                _insert_notification_record(db, user_id, role, "email", email, subject, message, ok)

        if phone and recipient_info.get("notify_whatsapp"):
            if not _notification_exists_recent(db, phone, "wa", subject, message):
                ok = send_whatsapp(phone, message)
                results["wa"].append({"to": phone, "ok": ok})
                _insert_notification_record(db, user_id, role, "wa", phone, subject, message, ok)

        push_payload = {
            "title": (push_title or subject or "Pengumuman Baru").strip(),
            "body": (push_body or message or "").strip()[:180],
            "url": push_url or "/announcements/",
            "tag": push_tag or f"broadcast-{user_id}",
            "icon": "/static/brand/mataram-logo.png",
            "badge": "/static/brand/mataram-logo.png",
        }
        subscriptions = db.execute(
            """
            SELECT id, endpoint, p256dh_key, auth_key
            FROM push_subscriptions
            WHERE user_id=? AND is_active=1
            ORDER BY updated_at DESC, id DESC
            """,
            (user_id,),
        ).fetchall()
        for subscription in subscriptions:
            endpoint = _normalize_recipient(subscription["endpoint"])
            if not endpoint:
                continue
            if _notification_exists_recent(db, endpoint, "push", subject, message):
                continue
            ok = _send_web_push(db, subscription, push_payload)
            if ok is None:
                continue
            results["push"].append({"to": endpoint, "ok": ok})
            _insert_notification_record(db, user_id, role, "push", endpoint, subject, message, ok)

    try:
        db.commit()
    except Exception:
        pass

    return results
