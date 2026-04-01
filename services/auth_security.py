import math
import secrets
import string
from datetime import datetime, timedelta, timezone

from flask import current_app, request


def normalize_identifier(identifier):
    return (identifier or "").strip().lower()


def get_client_ip():
    forwarded_for = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded_for or (request.remote_addr or "unknown")


def generate_numeric_code(length=6):
    digits = string.digits
    return "".join(secrets.choice(digits) for _ in range(max(1, int(length))))


def cleanup_password_resets(db):
    db.execute(
        """
        DELETE FROM password_resets
        WHERE expires_at <= datetime('now', '-1 day')
           OR (used = 1 AND created_at <= datetime('now', '-7 day'))
        """
    )


def issue_password_reset_code(db, user_id, ttl_minutes):
    ttl_minutes = max(1, int(ttl_minutes))
    cleanup_password_resets(db)
    db.execute(
        "UPDATE password_resets SET used=1 WHERE user_id=? AND used=0",
        (user_id,),
    )
    code = generate_numeric_code(6)
    db.execute(
        """
        INSERT INTO password_resets(user_id, code, expires_at)
        VALUES (?,?,datetime('now', ?))
        """,
        (user_id, code, f"+{ttl_minutes} minutes"),
    )
    return code


def mark_password_resets_used(db, user_id):
    db.execute(
        "UPDATE password_resets SET used=1 WHERE user_id=? AND used=0",
        (user_id,),
    )


def cleanup_login_attempts(db):
    retention_seconds = max(
        int(current_app.config.get("LOGIN_THROTTLE_WINDOW_SECONDS", 300)) * 12,
        86400,
    )
    db.execute(
        "DELETE FROM login_attempts WHERE created_at < datetime('now', ?)",
        (f"-{retention_seconds} seconds",),
    )


def record_login_attempt(db, identifier, ip_address, success):
    cleanup_login_attempts(db)
    db.execute(
        """
        INSERT INTO login_attempts(identifier, ip_address, success)
        VALUES (?,?,?)
        """,
        (
            normalize_identifier(identifier),
            (ip_address or "unknown").strip(),
            1 if success else 0,
        ),
    )


def clear_login_failures(db, identifier, ip_address):
    identifier = normalize_identifier(identifier)
    ip_address = (ip_address or "unknown").strip()
    db.execute(
        """
        DELETE FROM login_attempts
        WHERE success=0
          AND (identifier=? OR ip_address=?)
        """,
        (identifier, ip_address),
    )


def _parse_db_timestamp(value):
    if not value:
        return None

    raw = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _count_recent_failures(db, clause, param, window_seconds):
    return db.execute(
        f"""
        SELECT COUNT(*) AS total, MIN(created_at) AS first_created_at
        FROM login_attempts
        WHERE success=0
          AND {clause}=?
          AND created_at >= datetime('now', ?)
        """,
        (param, f"-{window_seconds} seconds"),
    ).fetchone()


def get_login_throttle_state(db, identifier, ip_address):
    cleanup_login_attempts(db)

    identifier = normalize_identifier(identifier)
    ip_address = (ip_address or "unknown").strip()
    limit = max(1, int(current_app.config.get("LOGIN_THROTTLE_LIMIT", 5)))
    window_seconds = max(60, int(current_app.config.get("LOGIN_THROTTLE_WINDOW_SECONDS", 300)))

    identifier_failures = _count_recent_failures(
        db,
        "identifier",
        identifier,
        window_seconds,
    )
    ip_failures = _count_recent_failures(
        db,
        "ip_address",
        ip_address,
        window_seconds,
    )

    blocked = (
        (identifier_failures["total"] if identifier else 0) >= limit
        or ip_failures["total"] >= limit
    )

    if not blocked:
        return {"blocked": False, "retry_after": 0}

    oldest_candidates = []
    if identifier and identifier_failures["total"] >= limit:
        oldest_candidates.append(_parse_db_timestamp(identifier_failures["first_created_at"]))
    if ip_failures["total"] >= limit:
        oldest_candidates.append(_parse_db_timestamp(ip_failures["first_created_at"]))

    oldest_attempt = min(
        (timestamp for timestamp in oldest_candidates if timestamp is not None),
        default=None,
    )
    if oldest_attempt is None:
        return {"blocked": True, "retry_after": window_seconds}

    retry_after = max(
        1,
        math.ceil(
            (
                oldest_attempt + timedelta(seconds=window_seconds)
                - datetime.now(timezone.utc)
            ).total_seconds()
        ),
    )
    return {"blocked": True, "retry_after": retry_after}
