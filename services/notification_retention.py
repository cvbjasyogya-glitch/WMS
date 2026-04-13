import time

from flask import current_app


_NOTIFICATION_HISTORY_CLEANUP_LAST_RUN = 0.0


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _delete_by_retention_days(db, table_name, retention_days):
    if retention_days <= 0:
        return 0

    cursor = db.execute(
        f"DELETE FROM {table_name} WHERE created_at < datetime('now', ?)",
        (f"-{retention_days} days",),
    )
    return int(cursor.rowcount or 0)


def cleanup_notification_history(db, *, force=False):
    global _NOTIFICATION_HISTORY_CLEANUP_LAST_RUN

    interval_seconds = max(
        60,
        _safe_int(
            current_app.config.get("NOTIFICATION_LOG_CLEANUP_INTERVAL_SECONDS", 3600),
            3600,
        ),
    )
    now = time.time()
    if (
        not force
        and _NOTIFICATION_HISTORY_CLEANUP_LAST_RUN
        and (now - _NOTIFICATION_HISTORY_CLEANUP_LAST_RUN) < interval_seconds
    ):
        return {
            "notifications": 0,
            "web_notifications": 0,
            "skipped": True,
        }

    deleted_notifications = 0
    deleted_web_notifications = 0

    try:
        deleted_notifications = _delete_by_retention_days(
            db,
            "notifications",
            _safe_int(current_app.config.get("NOTIFICATION_LOG_RETENTION_DAYS", 90), 90),
        )
    except Exception:
        deleted_notifications = 0

    try:
        deleted_web_notifications = _delete_by_retention_days(
            db,
            "web_notifications",
            _safe_int(current_app.config.get("WEB_NOTIFICATION_RETENTION_DAYS", 90), 90),
        )
    except Exception:
        deleted_web_notifications = 0

    _NOTIFICATION_HISTORY_CLEANUP_LAST_RUN = now
    return {
        "notifications": deleted_notifications,
        "web_notifications": deleted_web_notifications,
        "skipped": False,
    }
