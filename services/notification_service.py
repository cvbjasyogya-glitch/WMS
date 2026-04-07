import os
import smtplib
import json
from email.message import EmailMessage
from urllib.parse import urlsplit

from flask import current_app, has_request_context, request, session

from database import get_db
from services.announcement_center import role_matches_audience, user_matches_scope
from services.event_notification_policy import row_matches_notification_aliases
from services.whatsapp_service import send_whatsapp_text

try:
    import requests as http_requests
except ImportError:
    http_requests = None

try:
    from pywebpush import WebPushException, webpush
except ImportError:
    WebPushException = Exception
    webpush = None


NOTIFICATION_BLUEPRINT_LINKS = {
    "announcement_center": "/announcements/",
    "approvals": "/approvals",
    "attendance_portal": "/absen/",
    "audit": "/audit/",
    "chat": "/chat/",
    "crm": "/crm/",
    "daily_report_portal": "/laporan-harian/",
    "dashboard": "/",
    "hris": "/hris/",
    "inbound": "/approvals",
    "leave_portal": "/libur/",
    "meetings": "/meetings/",
    "outbound": "/approvals",
    "product_lookup": "/info-produk/",
    "products": "/products/",
    "request": "/request/",
    "schedule": "/announcements/",
    "so": "/so",
    "stock": "/approvals",
    "transfers": "/request/",
}

NOTIFICATION_CATEGORY_PREFIXES = [
    ("/request/owner", "owner_request"),
    ("/announcements", "announcement"),
    ("/approvals", "approval"),
    ("/chat", "chat"),
    ("/crm", "crm"),
    ("/hris", "hris"),
    ("/absen", "attendance"),
    ("/libur", "leave"),
    ("/laporan-harian", "report"),
    ("/request", "request"),
    ("/schedule", "schedule"),
    ("/stock", "inventory"),
    ("/inbound", "inventory"),
    ("/outbound", "inventory"),
    ("/products", "inventory"),
    ("/transfers", "request"),
    ("/audit", "audit"),
    ("/meetings", "meeting"),
]

OPERATIONAL_MONITOR_ROLES = ("hr", "admin", "leader", "owner", "super_admin")


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


def _safe_relative_url(value):
    candidate = str(value or "").strip()
    if not candidate:
        return ""

    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate

    if not has_request_context():
        return ""

    parsed = urlsplit(candidate)
    if not parsed.scheme or not parsed.netloc:
        return ""

    request_origin = urlsplit(request.host_url)
    if (
        parsed.scheme.lower() != request_origin.scheme.lower()
        or parsed.netloc.lower() != request_origin.netloc.lower()
    ):
        return ""

    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path


def _current_request_path():
    if not has_request_context():
        return ""

    target = request.full_path if request.query_string else request.path
    if target.endswith("?"):
        target = target[:-1]
    return target if target.startswith("/") else ""


def _default_notification_link():
    if not has_request_context():
        return "/notifications/"

    referrer_path = _safe_relative_url(request.referrer)
    if referrer_path:
        return referrer_path

    if request.method == "GET":
        current_path = _current_request_path()
        if current_path:
            return current_path

    return NOTIFICATION_BLUEPRINT_LINKS.get(request.blueprint or "", "/notifications/")


def _resolve_notification_link_url(link_url=None):
    explicit_link = _safe_relative_url(link_url)
    if explicit_link:
        return explicit_link
    return _default_notification_link()


def _guess_notification_category(link_url=None, explicit_category=None):
    normalized_category = (explicit_category or "").strip().lower()
    if normalized_category:
        return normalized_category

    target_url = _resolve_notification_link_url(link_url)
    for prefix, category in NOTIFICATION_CATEGORY_PREFIXES:
        if target_url.startswith(prefix):
            return category

    return "system"


def _current_actor_meta():
    if not has_request_context():
        return None, ""

    actor_user_id = session.get("user_id")
    actor_name = (session.get("username") or "").strip()
    return actor_user_id, actor_name


def _normalize_source_identifier(source_id):
    value = str(source_id or "").strip()
    return value[:120] if value else None


def _build_web_notification_dedupe_key(
    title,
    message,
    link_url,
    category,
    source_type=None,
    source_id=None,
    dedupe_key=None,
):
    explicit = str(dedupe_key or "").strip()
    if explicit:
        return explicit[:255]

    normalized_source_id = _normalize_source_identifier(source_id)
    normalized_source_type = (source_type or "").strip().lower()
    if normalized_source_type and normalized_source_id:
        return f"{normalized_source_type}:{normalized_source_id}"[:255]

    basis = " | ".join(
        part.strip()
        for part in [category or "system", title or "", message or "", link_url or ""]
        if part and str(part).strip()
    )
    return basis[:255] if basis else None


def _web_notification_exists_recent(db, user_id, dedupe_key, title, message, link_url):
    if dedupe_key:
        row = db.execute(
            """
            SELECT id
            FROM web_notifications
            WHERE user_id=?
              AND dedupe_key=?
              AND created_at >= datetime('now', '-2 minutes')
            LIMIT 1
            """,
            (user_id, dedupe_key),
        ).fetchone()
        return row is not None

    row = db.execute(
        """
        SELECT id
        FROM web_notifications
        WHERE user_id=?
          AND title=?
          AND message=?
          AND COALESCE(link_url, '')=COALESCE(?, '')
          AND created_at >= datetime('now', '-2 minutes')
        LIMIT 1
        """,
        (user_id, title, message, link_url),
    ).fetchone()
    return row is not None


def _created_at_to_iso(value):
    text = str(value or "").strip()
    if not text:
        return ""
    return f"{text.replace(' ', 'T')}Z"


def create_web_notification(
    user_id,
    title,
    message,
    *,
    category=None,
    link_url=None,
    actor_user_id=None,
    actor_name=None,
    source_type=None,
    source_id=None,
    dedupe_key=None,
):
    try:
        normalized_user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    normalized_title = (title or "").strip()
    normalized_message = (message or "").strip()
    if not normalized_title and not normalized_message:
        return None

    resolved_link = _resolve_notification_link_url(link_url)
    resolved_category = _guess_notification_category(resolved_link, category)

    current_actor_user_id, current_actor_name = _current_actor_meta()
    if actor_user_id is None:
        actor_user_id = current_actor_user_id
    if actor_name is None:
        actor_name = current_actor_name

    normalized_source_type = (source_type or resolved_category or "system").strip().lower()[:64]
    normalized_source_id = _normalize_source_identifier(source_id)
    normalized_dedupe_key = _build_web_notification_dedupe_key(
        normalized_title,
        normalized_message,
        resolved_link,
        resolved_category,
        source_type=normalized_source_type,
        source_id=normalized_source_id,
        dedupe_key=dedupe_key,
    )

    db = get_db()
    if _web_notification_exists_recent(
        db,
        normalized_user_id,
        normalized_dedupe_key,
        normalized_title,
        normalized_message,
        resolved_link,
    ):
        return None

    try:
        cursor = db.execute(
            """
            INSERT INTO web_notifications(
                user_id,
                category,
                title,
                message,
                link_url,
                actor_user_id,
                actor_name,
                source_type,
                source_id,
                dedupe_key
            )
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                normalized_user_id,
                resolved_category,
                normalized_title[:160],
                normalized_message[:800],
                resolved_link[:255],
                actor_user_id,
                (actor_name or "").strip()[:80] or None,
                normalized_source_type or None,
                normalized_source_id,
                normalized_dedupe_key,
            ),
        )
        return int(cursor.lastrowid)
    except Exception as exc:
        print("WEB NOTIFICATION INSERT ERROR:", exc)
        return None


def push_user_notification(
    user_id,
    title,
    message,
    *,
    category=None,
    link_url=None,
    actor_user_id=None,
    actor_name=None,
    source_type=None,
    source_id=None,
    dedupe_key=None,
    push_title=None,
    push_body=None,
    push_tag=None,
    push_icon=None,
    push_badge=None,
    require_interaction=False,
    renotify=False,
    silent=False,
    actions=None,
    vibrate=None,
):
    try:
        normalized_user_id = int(user_id)
    except (TypeError, ValueError):
        return {"web": [], "push": []}

    normalized_title = (title or "").strip()
    normalized_message = (message or "").strip()
    if not normalized_title and not normalized_message:
        return {"web": [], "push": []}

    db = get_db()
    recipient = db.execute(
        """
        SELECT id, role
        FROM users
        WHERE id=?
        LIMIT 1
        """,
        (normalized_user_id,),
    ).fetchone()
    if recipient is None:
        return {"web": [], "push": []}

    notification_id = create_web_notification(
        normalized_user_id,
        normalized_title,
        normalized_message,
        category=category,
        link_url=link_url,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
        source_type=source_type or "user_push_notification",
        source_id=source_id,
        dedupe_key=dedupe_key,
    )
    if not notification_id:
        return {"web": [], "push": []}

    resolved_link = _resolve_notification_link_url(link_url)
    results = {"web": [{"user_id": normalized_user_id}], "push": []}
    push_payload = {
        "title": (push_title or normalized_title or "Notifikasi Baru").strip()[:120],
        "body": (push_body or normalized_message or "").strip()[:180],
        "url": resolved_link,
        "tag": (push_tag or f"user-event-{notification_id}").strip()[:120],
        "icon": push_icon or "/static/brand/mataram-logo.png",
        "badge": push_badge or "/static/brand/mataram-logo.png",
        "notification_id": notification_id,
        "requireInteraction": bool(require_interaction),
        "renotify": bool(renotify),
        "silent": bool(silent),
    }
    if isinstance(actions, list) and actions:
        push_payload["actions"] = [
            {
                "action": str(item.get("action") or "").strip()[:40],
                "title": str(item.get("title") or "").strip()[:40],
            }
            for item in actions
            if isinstance(item, dict)
            and str(item.get("action") or "").strip()
            and str(item.get("title") or "").strip()
        ][:2]
        if push_payload["actions"]:
            push_payload["actionUrls"] = {
                item["action"]: resolved_link
                for item in push_payload["actions"]
            }
    if isinstance(vibrate, (list, tuple)) and vibrate:
        push_payload["vibrate"] = [
            int(value)
            for value in vibrate
            if isinstance(value, (int, float)) and int(value) >= 0
        ][:8]

    subscriptions = db.execute(
        """
        SELECT id, endpoint, p256dh_key, auth_key
        FROM push_subscriptions
        WHERE user_id=? AND is_active=1
        ORDER BY updated_at DESC, id DESC
        """,
        (normalized_user_id,),
    ).fetchall()
    for subscription in subscriptions:
        endpoint = _normalize_recipient(subscription["endpoint"])
        if not endpoint:
            continue
        if _notification_exists_recent(db, endpoint, "push", normalized_title, normalized_message):
            continue
        ok = _send_web_push(db, subscription, push_payload)
        if ok is None:
            continue
        results["push"].append({"to": endpoint, "ok": ok})
        _insert_notification_record(
            db,
            normalized_user_id,
            recipient["role"],
            "push",
            endpoint,
            normalized_title,
            normalized_message,
            ok,
        )

    try:
        db.commit()
    except Exception:
        pass

    return results


def fetch_user_web_notifications(user_id, *, unread_only=False, hide_read=True, limit=12, since_id=None):
    try:
        normalized_user_id = int(user_id)
    except (TypeError, ValueError):
        return []

    try:
        normalized_limit = max(1, min(int(limit or 12), 120))
    except (TypeError, ValueError):
        normalized_limit = 12

    params = [normalized_user_id]
    query = """
        SELECT
            id,
            category,
            title,
            message,
            link_url,
            actor_name,
            is_read,
            read_at,
            created_at
        FROM web_notifications
        WHERE user_id=?
    """

    if hide_read or unread_only:
        query += " AND is_read=0"

    try:
        normalized_since_id = int(since_id) if since_id is not None else None
    except (TypeError, ValueError):
        normalized_since_id = None

    if normalized_since_id is not None and normalized_since_id > 0:
        query += " AND id > ?"
        params.append(normalized_since_id)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(normalized_limit)

    db = get_db()
    rows = db.execute(query, params).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        item["is_read"] = bool(item.get("is_read"))
        item["link_url"] = _safe_relative_url(item.get("link_url")) or "/notifications/"
        item["created_at_iso"] = _created_at_to_iso(item.get("created_at"))
        item["read_at_iso"] = _created_at_to_iso(item.get("read_at"))
        items.append(item)
    return items


def get_user_web_notification_summary(user_id):
    try:
        normalized_user_id = int(user_id)
    except (TypeError, ValueError):
        return {"total": 0, "unread": 0, "latest_id": 0}

    db = get_db()
    row = db.execute(
        """
        SELECT
            COUNT(*) AS total_count,
            COALESCE(SUM(CASE WHEN is_read=0 THEN 1 ELSE 0 END), 0) AS unread_count,
            COALESCE(MAX(id), 0) AS latest_id
        FROM web_notifications
        WHERE user_id=?
        """,
        (normalized_user_id,),
    ).fetchone()
    if not row:
        return {"total": 0, "unread": 0, "latest_id": 0}

    return {
        "total": int(row["total_count"] or 0),
        "unread": int(row["unread_count"] or 0),
        "latest_id": int(row["latest_id"] or 0),
    }


def mark_user_web_notification_read(user_id, notification_id):
    try:
        normalized_user_id = int(user_id)
        normalized_notification_id = int(notification_id)
    except (TypeError, ValueError):
        return False

    db = get_db()
    cursor = db.execute(
        """
        UPDATE web_notifications
        SET is_read=1,
            read_at=COALESCE(read_at, CURRENT_TIMESTAMP)
        WHERE id=?
          AND user_id=?
          AND is_read=0
        """,
        (normalized_notification_id, normalized_user_id),
    )
    return bool(cursor.rowcount)


def mark_all_user_web_notifications_read(user_id):
    try:
        normalized_user_id = int(user_id)
    except (TypeError, ValueError):
        return 0

    db = get_db()
    cursor = db.execute(
        """
        UPDATE web_notifications
        SET is_read=1,
            read_at=COALESCE(read_at, CURRENT_TIMESTAMP)
        WHERE user_id=?
          AND is_read=0
        """,
        (normalized_user_id,),
    )
    return int(cursor.rowcount or 0)


def delete_user_web_notification(user_id, notification_id):
    try:
        normalized_user_id = int(user_id)
        normalized_notification_id = int(notification_id)
    except (TypeError, ValueError):
        return False

    db = get_db()
    cursor = db.execute(
        """
        DELETE FROM web_notifications
        WHERE id=?
          AND user_id=?
        """,
        (normalized_notification_id, normalized_user_id),
    )
    return bool(cursor.rowcount)


def delete_all_user_web_notifications(user_id):
    try:
        normalized_user_id = int(user_id)
    except (TypeError, ValueError):
        return 0

    db = get_db()
    cursor = db.execute(
        """
        DELETE FROM web_notifications
        WHERE user_id=?
        """,
        (normalized_user_id,),
    )
    return int(cursor.rowcount or 0)


def _get_recipients_by_roles(roles):
    roles = _normalize_roles(roles)
    if not roles:
        return []

    db = get_db()
    q = f"SELECT id, username, email, phone, role, notify_email, notify_whatsapp, warehouse_id FROM users WHERE role IN ({','.join('?' for _ in roles)})"
    rows = db.execute(q, roles).fetchall()
    return [dict(r) for r in rows]


def _get_recipients_by_aliases(aliases):
    if not aliases:
        return []

    db = get_db()
    rows = db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.email,
            u.phone,
            u.role,
            u.notify_email,
            u.notify_whatsapp,
            u.warehouse_id,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'User') AS display_name,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), '') AS full_name
        FROM users u
        LEFT JOIN employees e ON e.id = u.employee_id
        ORDER BY u.id ASC
        """
    ).fetchall()
    return [dict(row) for row in rows if row_matches_notification_aliases(dict(row), aliases)]


def _get_users_by_ids(user_ids):
    user_ids = _normalize_user_ids(user_ids)
    if not user_ids:
        return []

    db = get_db()
    query = (
        "SELECT id, username, email, phone, role, notify_email, notify_whatsapp, warehouse_id "
        f"FROM users WHERE id IN ({','.join('?' for _ in user_ids)})"
    )
    rows = db.execute(query, user_ids).fetchall()
    return [dict(row) for row in rows]


def notify_operational_event(
    subject,
    message,
    *,
    warehouse_id=None,
    include_actor=True,
    include_user_ids=None,
    exclude_user_ids=None,
    recipient_roles=None,
    recipient_usernames=None,
    recipient_user_ids=None,
    push_title=None,
    push_body=None,
    push_tag=None,
    category=None,
    link_url=None,
    source_type=None,
    source_id=None,
    dedupe_key=None,
):
    db = get_db()
    recipient_map = {}
    exclude_ids = set(_normalize_user_ids(exclude_user_ids))

    role_recipients = (
        _get_recipients_by_roles(recipient_roles)
        if recipient_roles is not None
        else _get_recipients_by_roles(OPERATIONAL_MONITOR_ROLES)
    )
    for recipient in role_recipients:
        recipient_id = recipient.get("id")
        if not recipient_id or recipient_id in exclude_ids:
            continue
        if not user_matches_scope(recipient.get("role"), recipient.get("warehouse_id"), warehouse_id):
            continue
        recipient_map[recipient_id] = recipient

    for recipient in _get_recipients_by_aliases(recipient_usernames):
        recipient_id = recipient.get("id")
        if not recipient_id or recipient_id in exclude_ids:
            continue
        if not user_matches_scope(recipient.get("role"), recipient.get("warehouse_id"), warehouse_id):
            continue
        recipient_map[recipient_id] = recipient

    for recipient in _get_users_by_ids(recipient_user_ids):
        recipient_id = recipient.get("id")
        if not recipient_id or recipient_id in exclude_ids:
            continue
        if not user_matches_scope(recipient.get("role"), recipient.get("warehouse_id"), warehouse_id):
            continue
        recipient_map[recipient_id] = recipient

    explicit_user_ids = _normalize_user_ids(include_user_ids)
    actor_user_id, _ = _current_actor_meta()
    if include_actor and actor_user_id:
        explicit_user_ids.append(actor_user_id)

    for recipient in _get_users_by_ids(explicit_user_ids):
        recipient_id = recipient.get("id")
        if not recipient_id or recipient_id in exclude_ids:
            continue
        recipient_map[recipient_id] = recipient

    results = {"web": [], "push": []}
    resolved_link = _resolve_notification_link_url(link_url)

    for recipient in recipient_map.values():
        user_id = recipient.get("id")
        if not user_id:
            continue

        notification_id = create_web_notification(
            user_id,
            subject,
            message,
            category=category,
            link_url=resolved_link,
            source_type=source_type or "operational_event",
            source_id=source_id,
            dedupe_key=dedupe_key,
        )

        if not notification_id:
            continue

        results["web"].append({"user_id": user_id})

        push_payload = {
            "title": (push_title or subject or "Aktivitas Baru").strip()[:120],
            "body": (push_body or message or "").strip()[:180],
            "url": resolved_link,
            "tag": push_tag or f"ops-{source_type or category or 'event'}-{notification_id}",
            "icon": "/static/brand/mataram-logo.png",
            "badge": "/static/brand/mataram-logo.png",
            "notification_id": notification_id,
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
            _insert_notification_record(
                db,
                user_id,
                recipient.get("role"),
                "push",
                endpoint,
                subject,
                message,
                ok,
            )

    try:
        db.commit()
    except Exception:
        pass

    return results


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
    result = send_whatsapp_text(target, message)
    return result.get("ok")


def notify_roles(
    roles,
    subject,
    message,
    warehouse_id=None,
    *,
    usernames=None,
    user_ids=None,
    send_whatsapp_channel=True,
    category=None,
    link_url=None,
    source_type=None,
    source_id=None,
    dedupe_key=None,
):
    roles = _normalize_roles(roles)
    usernames = usernames or ()
    user_ids = _normalize_user_ids(user_ids)
    if not roles and not usernames and not user_ids:
        return {"email": [], "wa": []}

    recipients = _get_recipients_by_roles(roles)
    recipient_map = {recipient.get("id"): recipient for recipient in recipients if recipient.get("id")}
    for recipient in _get_recipients_by_aliases(usernames):
        recipient_id = recipient.get("id")
        if recipient_id:
            recipient_map[recipient_id] = recipient
    for recipient in _get_users_by_ids(user_ids):
        recipient_id = recipient.get("id")
        if recipient_id:
            recipient_map[recipient_id] = recipient
    recipients = list(recipient_map.values())

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
            elif role in ("admin", "staff"):
                try:
                    if user_warehouse is None or int(user_warehouse) != int(warehouse_id):
                        continue
                except (TypeError, ValueError):
                    continue
            elif role not in ("owner", "super_admin", "hr"):
                continue

            combined[r.get('id')] = r

        recipients = list(combined.values())

    results = {"email": [], "wa": []}
    db = get_db()

    for r in recipients:
        # email (respect user preference)
        email = _normalize_recipient(r.get("email"))
        phone = _normalize_recipient(r.get("phone"))

        create_web_notification(
            r.get("id"),
            subject,
            message,
            category=category,
            link_url=link_url,
            source_type=source_type or "role_notification",
            source_id=source_id,
            dedupe_key=dedupe_key,
        )

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
        if send_whatsapp_channel and phone and r.get("notify_whatsapp"):
            if not _notification_exists_recent(db, phone, 'wa', subject, message):
                ok = send_whatsapp(phone, message)
                results["wa"].append({"to": phone, "ok": ok})
                try:
                    db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                               (r.get("id"), r.get("role"), 'wa', phone, subject, message, _notification_status(ok)))
                except Exception:
                    pass

    # fallback: if no specific contacts, send to configured FONNTE_TARGET and store a notification
    if send_whatsapp_channel and not recipients and os.getenv("FONNTE_TARGET"):
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


def notify_user(
    user_id,
    subject,
    message,
    *,
    category=None,
    link_url=None,
    source_type=None,
    source_id=None,
    dedupe_key=None,
    push_title=None,
    push_body=None,
    push_tag=None,
    require_interaction=False,
    renotify=False,
    silent=False,
    actions=None,
    vibrate=None,
):
    db = get_db()
    try:
        u = db.execute("SELECT id, email, phone, notify_email, notify_whatsapp FROM users WHERE id=?", (user_id,)).fetchone()
        if not u:
            return {"email": [], "wa": [], "push": []}

        u = dict(u)

        results = {"email": [], "wa": [], "push": []}
        email = _normalize_recipient(u.get("email"))
        phone = _normalize_recipient(u.get("phone"))

        push_results = push_user_notification(
            u.get("id"),
            subject,
            message,
            category=category,
            link_url=link_url,
            source_type=source_type or "user_notification",
            source_id=source_id,
            dedupe_key=dedupe_key,
            push_title=push_title,
            push_body=push_body,
            push_tag=push_tag,
            require_interaction=require_interaction,
            renotify=renotify,
            silent=silent,
            actions=actions,
            vibrate=vibrate,
        )
        results["push"] = push_results.get("push", [])

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
        return {"email": [], "wa": [], "push": []}


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
    category=None,
    link_url=None,
    source_type=None,
    source_id=None,
    dedupe_key=None,
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

        notification_id = create_web_notification(
            user_id,
            subject,
            message,
            category=category,
            link_url=link_url or push_url,
            source_type=source_type or "broadcast",
            source_id=source_id or push_tag,
            dedupe_key=dedupe_key or push_tag,
        )

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
            "url": _resolve_notification_link_url(link_url or push_url),
            "tag": push_tag or f"broadcast-{user_id}",
            "icon": "/static/brand/mataram-logo.png",
            "badge": "/static/brand/mataram-logo.png",
            "notification_id": notification_id,
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
