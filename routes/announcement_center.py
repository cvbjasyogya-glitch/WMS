from datetime import date as date_cls

from flask import Blueprint, current_app, jsonify, render_template, request, session

from database import get_db
from services.announcement_center import audience_label, format_long_date, role_matches_audience
from services.hris_catalog import can_manage_hris_module
from services.rbac import is_scoped_role


announcement_center_bp = Blueprint("announcement_center", __name__, url_prefix="/announcements")


def _current_scope_warehouse():
    if is_scoped_role(session.get("role")):
        return session.get("warehouse_id")
    return None


def _fetch_active_announcements(db):
    today_value = date_cls.today().isoformat()
    params = [today_value, today_value]
    query = """
        SELECT
            a.*,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM announcement_posts a
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        LEFT JOIN users u ON a.handled_by = u.id
        WHERE a.status='published'
          AND a.publish_date <= ?
          AND (a.expires_at IS NULL OR a.expires_at='' OR a.expires_at >= ?)
    """

    scope_warehouse = _current_scope_warehouse()
    if scope_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(scope_warehouse)

    query += " ORDER BY a.publish_date DESC, a.id DESC LIMIT 24"
    rows = [dict(row) for row in db.execute(query, params).fetchall()]

    visible_rows = []
    for row in rows:
        if not role_matches_audience(session.get("role"), row.get("audience")):
            continue
        row["audience_label"] = audience_label(row.get("audience"))
        row["publish_label"] = format_long_date(row.get("publish_date"))
        row["expires_label"] = format_long_date(row.get("expires_at")) if row.get("expires_at") else "-"
        visible_rows.append(row)
    return visible_rows


def _fetch_schedule_change_events(db):
    params = []
    query = """
        SELECT
            e.*,
            w.name AS warehouse_name,
            u.username AS created_by_name
        FROM schedule_change_events e
        LEFT JOIN warehouses w ON e.warehouse_id = w.id
        LEFT JOIN users u ON e.created_by = u.id
        WHERE 1=1
    """

    scope_warehouse = _current_scope_warehouse()
    if scope_warehouse:
        query += " AND (e.warehouse_id=? OR e.warehouse_id IS NULL)"
        params.append(scope_warehouse)

    query += " ORDER BY e.created_at DESC, e.id DESC LIMIT 30"
    rows = [dict(row) for row in db.execute(query, params).fetchall()]

    visible_rows = []
    for row in rows:
        if not role_matches_audience(session.get("role"), row.get("audience")):
            continue
        row["audience_label"] = audience_label(row.get("audience"))
        row["date_label"] = format_long_date(row.get("start_date"))
        row["range_label"] = (
            f"{format_long_date(row.get('start_date'))} s.d. {format_long_date(row.get('end_date'))}"
            if row.get("end_date") and row.get("end_date") != row.get("start_date")
            else format_long_date(row.get("start_date"))
        )
        visible_rows.append(row)
    return visible_rows


@announcement_center_bp.route("/")
def announcement_center_page():
    db = get_db()
    announcements = _fetch_active_announcements(db)
    all_schedule_changes = _fetch_schedule_change_events(db)
    schedule_changes = all_schedule_changes[:5]
    user_notification_settings = db.execute(
        """
        SELECT email, phone, notify_email, notify_whatsapp
        FROM users
        WHERE id=?
        """,
        (session.get("user_id"),),
    ).fetchone()
    active_push_subscriptions = db.execute(
        """
        SELECT COUNT(*)
        FROM push_subscriptions
        WHERE user_id=? AND is_active=1
        """,
        (session.get("user_id"),),
    ).fetchone()[0]

    today_value = date_cls.today().isoformat()
    schedule_changes_today = sum(
        1 for row in all_schedule_changes if (row.get("created_at") or "").startswith(today_value)
    )

    summary = {
        "announcements": len(announcements),
        "schedule_changes": len(all_schedule_changes),
        "schedule_changes_today": schedule_changes_today,
    }

    return render_template(
        "announcement_center.html",
        announcements=announcements,
        schedule_changes=schedule_changes,
        summary=summary,
        active_push_subscriptions=active_push_subscriptions,
        can_manage_announcements=can_manage_hris_module(session.get("role"), "announcement"),
        webpush_public_key=current_app.config.get("WEBPUSH_PUBLIC_KEY", ""),
        user_notification_settings=dict(user_notification_settings) if user_notification_settings else {},
    )


@announcement_center_bp.post("/push/subscribe")
def save_push_subscription():
    payload = request.get_json(silent=True) or {}
    endpoint = (payload.get("endpoint") or "").strip()
    keys = payload.get("keys") or {}
    p256dh_key = (keys.get("p256dh") or "").strip()
    auth_key = (keys.get("auth") or "").strip()

    if not endpoint or not p256dh_key or not auth_key:
        return jsonify({"status": "error", "message": "Subscription browser tidak valid"}), 400

    db = get_db()
    db.execute(
        """
        INSERT INTO push_subscriptions(
            user_id,
            endpoint,
            p256dh_key,
            auth_key,
            user_agent,
            is_active,
            updated_at
        )
        VALUES (?,?,?,?,?,1,CURRENT_TIMESTAMP)
        ON CONFLICT(endpoint) DO UPDATE SET
            user_id=excluded.user_id,
            p256dh_key=excluded.p256dh_key,
            auth_key=excluded.auth_key,
            user_agent=excluded.user_agent,
            is_active=1,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            session.get("user_id"),
            endpoint,
            p256dh_key,
            auth_key,
            (request.headers.get("User-Agent") or "")[:255],
        ),
    )
    db.commit()
    return jsonify({"status": "ok"})


@announcement_center_bp.post("/push/unsubscribe")
def disable_push_subscription():
    payload = request.get_json(silent=True) or {}
    endpoint = (payload.get("endpoint") or "").strip()
    db = get_db()

    if endpoint:
        db.execute(
            """
            UPDATE push_subscriptions
            SET is_active=0,
                updated_at=CURRENT_TIMESTAMP
            WHERE user_id=? AND endpoint=?
            """,
            (session.get("user_id"), endpoint),
        )
    else:
        db.execute(
            """
            UPDATE push_subscriptions
            SET is_active=0,
                updated_at=CURRENT_TIMESTAMP
            WHERE user_id=?
            """,
            (session.get("user_id"),),
        )
    db.commit()
    return jsonify({"status": "ok"})
