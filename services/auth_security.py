import math
import hashlib
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


def hash_user_email_verification_token(token):
    safe_token = (token or "").strip()
    if not safe_token:
        return ""
    return hashlib.sha256(safe_token.encode("utf-8")).hexdigest()


def issue_user_email_verification_challenge(db, user_id, ttl_hours=24):
    ttl_hours = max(1, int(ttl_hours or 24))
    token = secrets.token_urlsafe(32)
    code = generate_numeric_code(5)
    token_hash = hash_user_email_verification_token(token)
    code_hash = hash_user_email_verification_token(code)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
    db.execute(
        """
        UPDATE users
        SET email_verification_token_hash=?,
            email_verification_code_hash=?,
            email_verification_sent_at=CURRENT_TIMESTAMP,
            email_verification_expires_at=?
        WHERE id=?
        """,
        (
            token_hash,
            code_hash,
            expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            user_id,
        ),
    )
    return token, code


def issue_user_email_verification(db, user_id, ttl_hours=24):
    token, _code = issue_user_email_verification_challenge(db, user_id, ttl_hours=ttl_hours)
    return token


def get_user_by_email_verification_token(db, token):
    token_hash = hash_user_email_verification_token(token)
    if not token_hash:
        return None
    return db.execute(
        """
        SELECT *
        FROM users
        WHERE email_verification_token_hash=?
        LIMIT 1
        """,
        (token_hash,),
    ).fetchone()


def get_user_by_email_verification_code(db, user_id, code):
    code_hash = hash_user_email_verification_token(code)
    if not code_hash:
        return None
    return db.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
          AND email_verification_code_hash=?
        LIMIT 1
        """,
        (user_id, code_hash),
    ).fetchone()


def mark_user_email_verified(db, user_id):
    db.execute(
        """
        UPDATE users
        SET email_verified_at=CURRENT_TIMESTAMP,
            email_verification_token_hash=NULL,
            email_verification_code_hash=NULL,
            email_verification_sent_at=NULL,
            email_verification_expires_at=NULL,
            notify_email=1
        WHERE id=?
        """,
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
        SELECT COUNT(*) AS total,
               MIN(created_at) AS first_created_at,
               MAX(created_at) AS last_created_at
        FROM login_attempts
        WHERE success=0
          AND {clause}=?
          AND created_at >= datetime('now', ?)
        """,
        (param, f"-{window_seconds} seconds"),
    ).fetchone()


def _login_throttle_backoff_seconds():
    configured = current_app.config.get("LOGIN_THROTTLE_BACKOFF_SECONDS", "5,10,60")
    if isinstance(configured, str):
        raw_values = configured.replace(";", ",").split(",")
    else:
        raw_values = configured or ()

    backoffs = []
    for raw_value in raw_values:
        try:
            seconds = int(str(raw_value).strip())
        except (TypeError, ValueError):
            continue
        if seconds > 0:
            backoffs.append(seconds)

    return backoffs or [5, 10, 60]


def _seconds_since_timestamp(timestamp, now):
    if timestamp is None:
        return None
    elapsed = (now - timestamp).total_seconds()
    # PostgreSQL/SQLite deployments may store naive CURRENT_TIMESTAMP with a
    # different server timezone. Future-looking timestamps should never create
    # multi-hour lockouts; treat them as just happened.
    return max(0, elapsed)


def _failure_retry_after(failure_row, limit, backoffs, now):
    if not failure_row:
        return 0

    total = int(failure_row["total"] or 0)
    if total < limit:
        return 0

    backoff_index = min(max(0, total - limit), len(backoffs) - 1)
    backoff_seconds = backoffs[backoff_index]
    last_attempt = _parse_db_timestamp(failure_row["last_created_at"])
    elapsed = _seconds_since_timestamp(last_attempt, now)
    if elapsed is None:
        return backoff_seconds

    return max(0, math.ceil(backoff_seconds - elapsed))


def get_login_throttle_state(db, identifier, ip_address):
    cleanup_login_attempts(db)

    identifier = normalize_identifier(identifier)
    ip_address = (ip_address or "unknown").strip()
    limit = max(1, int(current_app.config.get("LOGIN_THROTTLE_LIMIT", 5)))
    backoffs = _login_throttle_backoff_seconds()
    window_seconds = max(max(backoffs), int(current_app.config.get("LOGIN_THROTTLE_WINDOW_SECONDS", 300)))

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

    now = datetime.now(timezone.utc)
    retry_after = max(
        _failure_retry_after(identifier_failures, limit, backoffs, now) if identifier else 0,
        _failure_retry_after(ip_failures, limit, backoffs, now),
    )

    if retry_after <= 0:
        return {"blocked": False, "retry_after": 0}

    return {"blocked": True, "retry_after": retry_after}
