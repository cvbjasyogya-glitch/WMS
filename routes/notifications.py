from flask import Blueprint, jsonify, render_template, request, session

from services.notification_service import (
    delete_all_user_web_notifications,
    delete_user_web_notification,
    fetch_user_web_notifications,
    get_user_web_notification_summary,
    mark_all_user_web_notifications_read,
    mark_user_web_notification_read,
)


notifications_bp = Blueprint("notifications_center", __name__, url_prefix="/notifications")


def _parse_limit(raw_value, default_value, minimum=1, maximum=120):
    try:
        return max(minimum, min(int(raw_value or default_value), maximum))
    except (TypeError, ValueError):
        return default_value


def _current_filter():
    return "all" if (request.args.get("filter") or "").strip().lower() == "all" else "unread"


@notifications_bp.get("/")
def notifications_page():
    current_filter = _current_filter()
    items = fetch_user_web_notifications(
        session.get("user_id"),
        unread_only=current_filter == "unread",
        hide_read=True,
        limit=_parse_limit(request.args.get("limit"), 80, maximum=150),
    )
    summary = get_user_web_notification_summary(session.get("user_id"))
    return render_template(
        "notifications.html",
        notifications=items,
        notifications_filter=current_filter,
        notification_summary=summary,
    )


@notifications_bp.get("/api")
def notifications_api():
    current_filter = _current_filter()
    since_id = request.args.get("since_id")
    limit = _parse_limit(request.args.get("limit"), 12)
    summary = get_user_web_notification_summary(session.get("user_id"))
    try:
        normalized_since_id = int(since_id) if since_id is not None else None
    except (TypeError, ValueError):
        normalized_since_id = None

    items = []
    if normalized_since_id is None or normalized_since_id < int(summary["latest_id"] or 0):
        items = fetch_user_web_notifications(
            session.get("user_id"),
            unread_only=current_filter == "unread",
            hide_read=True,
            limit=limit,
            since_id=since_id,
        )
    return jsonify(
        {
            "status": "ok",
            "filter": current_filter,
            "items": items,
            "unread_count": summary["unread"],
            "total_count": summary["total"],
            "latest_id": summary["latest_id"],
        }
    )


@notifications_bp.post("/api/<int:notification_id>/read")
def mark_notification_read(notification_id):
    mark_user_web_notification_read(session.get("user_id"), notification_id)
    summary = get_user_web_notification_summary(session.get("user_id"))
    return jsonify({"status": "ok", "unread_count": summary["unread"], "latest_id": summary["latest_id"]})


@notifications_bp.post("/api/mark-all-read")
def mark_all_notifications_read():
    updated = mark_all_user_web_notifications_read(session.get("user_id"))
    summary = get_user_web_notification_summary(session.get("user_id"))
    return jsonify(
        {
            "status": "ok",
            "updated": updated,
            "unread_count": summary["unread"],
            "latest_id": summary["latest_id"],
        }
    )


@notifications_bp.post("/api/<int:notification_id>/delete")
def delete_notification(notification_id):
    deleted = delete_user_web_notification(session.get("user_id"), notification_id)
    summary = get_user_web_notification_summary(session.get("user_id"))
    return jsonify(
        {
            "status": "ok",
            "deleted": bool(deleted),
            "unread_count": summary["unread"],
            "total_count": summary["total"],
            "latest_id": summary["latest_id"],
        }
    )


@notifications_bp.post("/api/delete-all")
def delete_all_notifications():
    deleted = delete_all_user_web_notifications(session.get("user_id"))
    summary = get_user_web_notification_summary(session.get("user_id"))
    return jsonify(
        {
            "status": "ok",
            "deleted": deleted,
            "unread_count": summary["unread"],
            "total_count": summary["total"],
            "latest_id": summary["latest_id"],
        }
    )
