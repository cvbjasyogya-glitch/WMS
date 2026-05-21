import hashlib
import re
import secrets
from html import escape
from urllib.parse import urlsplit

from flask import Blueprint, current_app, g, render_template, request, redirect, session, url_for, flash
from database import get_db, is_postgresql_backend
from services.notification_service import create_web_notification, send_email, send_whatsapp
from services.whatsapp_service import record_whatsapp_delivery
from services.rbac import is_scoped_role, load_user_permission_override_snapshot, normalize_role
from services.auth_security import (
    clear_login_failures,
    generate_numeric_code,
    get_client_ip,
    get_login_throttle_state,
    get_user_by_email_verification_code,
    get_user_by_email_verification_token,
    hash_user_email_verification_token,
    issue_user_email_verification_challenge,
    mark_user_email_verified,
    issue_password_reset_code,
    mark_password_resets_used,
    normalize_identifier,
    _parse_db_timestamp,
    record_login_attempt,
    cleanup_password_resets,
)
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta, timezone

auth_bp = Blueprint("auth", __name__)


def _ensure_sqlite_column(db, table_name, column_name, definition):
    rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing = {row["name"] if hasattr(row, "keys") and "name" in row.keys() else row[1] for row in rows}
    if column_name not in existing:
        db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _ensure_portal_auth_schema(db):
    if getattr(g, "_portal_auth_schema_ready", False):
        return

    if is_postgresql_backend(current_app.config):
        statements = (
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_token_hash TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_code_hash TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_sent_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verification_expires_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS login_otp_required INTEGER",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS login_otp_code_hash TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS login_otp_sent_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS login_otp_expires_at TIMESTAMP",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS login_otp_attempts INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS login_otp_channel TEXT",
            "CREATE INDEX IF NOT EXISTS idx_users_email_lookup ON users(email)",
            "CREATE INDEX IF NOT EXISTS idx_users_email_verification ON users(email_verification_token_hash)",
            "CREATE INDEX IF NOT EXISTS idx_users_email_verification_code ON users(email_verification_code_hash)",
            """
            CREATE TABLE IF NOT EXISTS user_login_devices(
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                device_hash TEXT NOT NULL,
                user_agent TEXT,
                label TEXT,
                first_ip TEXT,
                last_ip TEXT,
                otp_verified_at TIMESTAMP,
                otp_verified_date TEXT,
                first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, device_hash)
            )
            """,
            "ALTER TABLE user_login_devices ADD COLUMN IF NOT EXISTS otp_verified_at TIMESTAMP",
            "ALTER TABLE user_login_devices ADD COLUMN IF NOT EXISTS otp_verified_date TEXT",
            "CREATE INDEX IF NOT EXISTS idx_user_login_devices_user ON user_login_devices(user_id, last_seen_at DESC)",
        )
        for statement in statements:
            db.execute(statement)
        db.commit()
    else:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_login_devices(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                device_hash TEXT NOT NULL,
                user_agent TEXT,
                label TEXT,
                first_ip TEXT,
                last_ip TEXT,
                otp_verified_at TIMESTAMP,
                otp_verified_date TEXT,
                first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, device_hash),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        db.execute("CREATE INDEX IF NOT EXISTS idx_user_login_devices_user ON user_login_devices(user_id, last_seen_at DESC)")
        for column_name, definition in (
            ("email", "TEXT"),
            ("phone", "TEXT"),
            ("email_verified_at", "TIMESTAMP"),
            ("email_verification_token_hash", "TEXT"),
            ("email_verification_code_hash", "TEXT"),
            ("email_verification_sent_at", "TIMESTAMP"),
            ("email_verification_expires_at", "TIMESTAMP"),
            ("login_otp_required", "INTEGER"),
            ("login_otp_code_hash", "TEXT"),
            ("login_otp_sent_at", "TIMESTAMP"),
            ("login_otp_expires_at", "TIMESTAMP"),
            ("login_otp_attempts", "INTEGER DEFAULT 0"),
            ("login_otp_channel", "TEXT"),
        ):
            _ensure_sqlite_column(db, "users", column_name, definition)
        for column_name, definition in (
            ("otp_verified_at", "TIMESTAMP"),
            ("otp_verified_date", "TEXT"),
        ):
            _ensure_sqlite_column(db, "user_login_devices", column_name, definition)

    g._portal_auth_schema_ready = True


def _safe_login_redirect_target(raw_target):
    candidate = (raw_target or "").strip()
    if not candidate:
        return None

    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return None

    if not candidate.startswith("/") or candidate.startswith("//"):
        return None

    return candidate


def _redirect_to_login(next_target=None):
    safe_target = _safe_login_redirect_target(next_target)
    if safe_target:
        return redirect(url_for("auth.login", next=safe_target))
    return redirect(url_for("auth.login"))


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(value):
    return (value or "").strip().lower()


def _is_valid_email(value):
    email = _normalize_email(value)
    return bool(email and len(email) <= 254 and _EMAIL_RE.match(email))


def _masked_email(value):
    email = _normalize_email(value)
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        safe_local = local[:1] + "***"
    else:
        safe_local = local[:2] + "***" + local[-1:]
    return f"{safe_local}@{domain}"


def _masked_phone(value):
    digits = re.sub(r"\D+", "", str(value or ""))
    if not digits:
        return ""
    if len(digits) <= 6:
        return digits[:2] + "***"
    return f"{digits[:4]}***{digits[-3:]}"


def _normalize_portal_verification_code(value):
    code = re.sub(r"\D+", "", str(value or ""))
    return code if len(code) == 5 else ""


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "off", "no", "none"}
    return bool(value)


def _portal_email_login_required():
    return bool(current_app.config.get("PORTAL_EMAIL_LOGIN_REQUIRED", True))


def _lookup_portal_login_user(db, identifier):
    normalized = normalize_identifier(identifier)
    if not normalized:
        return None

    if _is_valid_email(normalized):
        user = db.execute(
            "SELECT * FROM users WHERE lower(email)=? LIMIT 1",
            (normalized,),
        ).fetchone()
        if user:
            return user

    return db.execute(
        """
        SELECT *
        FROM users
        WHERE lower(username)=?
          AND (
                email IS NULL
             OR trim(email)=''
             OR email_verified_at IS NULL
          )
        LIMIT 1
        """,
        (normalized,),
    ).fetchone()


def _user_portal_email_ready(user):
    return bool(_is_valid_email(user.get("email")) and user.get("email_verified_at"))


def _set_pending_email_session(user, next_target=None):
    safe_target = _safe_login_redirect_target(next_target) or ""
    session.clear()
    session["pending_email_user_id"] = user["id"]
    session["pending_email_username"] = user["username"]
    session["pending_email_next"] = safe_target
    session["pending_email_started_at"] = datetime.now(timezone.utc).timestamp()


def _get_pending_email_user(db):
    user_id = session.get("pending_email_user_id")
    started_at = session.get("pending_email_started_at")
    if not user_id or not started_at:
        return None

    try:
        started_at = float(started_at)
    except (TypeError, ValueError):
        session.clear()
        return None

    ttl_minutes = max(1, int(current_app.config.get("PORTAL_EMAIL_ENROLLMENT_SESSION_MINUTES", 20)))
    if datetime.now(timezone.utc).timestamp() - started_at > ttl_minutes * 60:
        session.clear()
        return None

    user = db.execute("SELECT * FROM users WHERE id=? LIMIT 1", (user_id,)).fetchone()
    return dict(user) if user else None


def _build_portal_verification_url(token):
    path = url_for("auth.verify_portal_email", token=token)
    configured_base = _portal_public_base_url()
    if configured_base:
        return f"{configured_base}{path}"
    return url_for("auth.verify_portal_email", token=token, _external=True)


def _portal_public_base_url():
    configured_base = (
        (current_app.config.get("PORTAL_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        or (
            f"{current_app.config.get('CANONICAL_SCHEME', 'https')}://{current_app.config.get('CANONICAL_HOST')}"
            if current_app.config.get("CANONICAL_HOST")
            else ""
        ).strip().rstrip("/")
        or (current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    )
    return configured_base


def _build_portal_static_url(filename):
    safe_filename = str(filename or "").strip().lstrip("/")
    if not safe_filename:
        return ""
    configured_base = _portal_public_base_url()
    if configured_base:
        return f"{configured_base}/static/{safe_filename}"
    return url_for("static", filename=safe_filename, _external=True)


def _issue_portal_verification_challenge(db, user):
    token, code = issue_user_email_verification_challenge(
        db,
        user["id"],
        ttl_hours=current_app.config.get("PORTAL_EMAIL_VERIFICATION_TTL_HOURS", 24),
    )
    db.commit()
    return _build_portal_verification_url(token), code


def _verification_recently_sent(user):
    sent_at = _parse_db_timestamp(user.get("email_verification_sent_at"))
    if sent_at is None:
        return False
    cooldown_seconds = max(0, int(current_app.config.get("PORTAL_EMAIL_VERIFICATION_RESEND_SECONDS", 300)))
    return (datetime.now(timezone.utc) - sent_at) < timedelta(seconds=cooldown_seconds)


def _send_portal_email_verification(db, user, force=False):
    user = dict(user)
    if not _is_valid_email(user.get("email")):
        return False, "Email akun belum valid."

    if (
        not force
        and user.get("email_verification_token_hash")
        and user.get("email_verification_code_hash")
        and _verification_recently_sent(user)
    ):
        return True, "Email konfirmasi sudah dikirim. Cek inbox atau folder spam."

    verification_url, verification_code = _issue_portal_verification_challenge(db, user)
    subject = "Konfirmasi Email Portal CV BJAS"
    body = (
        f"Halo {user.get('username') or 'User'},\n\n"
        "Email ini dipakai untuk login Portal CV BJAS.\n"
        "Pilih salah satu cara konfirmasi:\n"
        f"1. Klik tautan berikut:\n{verification_url}\n"
        f"2. Atau masukkan kode verifikasi: {verification_code}\n\n"
        f"Tautan berlaku selama {current_app.config.get('PORTAL_EMAIL_VERIFICATION_TTL_HOURS', 24)} jam.\n"
        "Jika kamu tidak meminta perubahan ini, abaikan email ini.\n\n"
        "CV Berkah Jaya Abadi Sports"
    )
    sent = send_email(user["email"], subject, body)
    if sent:
        return True, "Email konfirmasi sudah dikirim. Cek inbox atau folder spam."
    return False, "Email tersimpan, tapi konfirmasi belum terkirim. Cek konfigurasi SMTP/Brevo."


def _send_portal_whatsapp_verification(db, user):
    user = dict(user)
    if not _is_valid_email(user.get("email")):
        return False, "Email akun belum valid."
    if not str(user.get("phone") or "").strip():
        return False, "Nomor WhatsApp belum terdaftar di akun ERP. Minta HR atau admin melengkapi nomor dulu."

    verification_url, verification_code = _issue_portal_verification_challenge(db, user)
    ttl_hours = current_app.config.get("PORTAL_EMAIL_VERIFICATION_TTL_HOURS", 24)
    message = (
        f"Halo {user.get('username') or 'User'},\n\n"
        "Verifikasi email untuk login Portal CV BJAS. Pilih salah satu:\n"
        f"1. Klik link: {verification_url}\n"
        f"2. Atau masukkan kode: {verification_code}\n\n"
        f"Link/kode berlaku {ttl_hours} jam. Gunakan yang terbaru jika sebelumnya sudah pernah dikirim.\n\n"
        "CV Berkah Jaya Abadi Sports"
    )
    sent = send_whatsapp(user["phone"], message)
    if sent:
        return True, "Link verifikasi sudah dikirim ke WhatsApp terdaftar."
    return False, "Link WhatsApp belum terkirim. Cek konfigurasi WhatsApp atau kirim ulang lewat email."


def _portal_login_otp_default_required():
    return bool(current_app.config.get("PORTAL_LOGIN_OTP_DEFAULT_REQUIRED", True))


def _user_login_otp_required(user):
    raw_value = user.get("login_otp_required") if user else None
    if raw_value is None:
        return _portal_login_otp_default_required()
    return _truthy(raw_value)


def _normalize_portal_login_otp_code(value):
    code = re.sub(r"\D+", "", str(value or ""))
    return code if len(code) == 5 else ""


def _portal_login_otp_ttl_minutes():
    return max(1, int(current_app.config.get("PORTAL_LOGIN_OTP_TTL_MINUTES", 10)))


def _portal_login_otp_session_minutes():
    return max(1, int(current_app.config.get("PORTAL_LOGIN_OTP_SESSION_MINUTES", 10)))


def _portal_login_otp_max_attempts():
    return max(1, int(current_app.config.get("PORTAL_LOGIN_OTP_MAX_ATTEMPTS", 5)))


def _login_otp_available_channels(user):
    channels = []
    if str(user.get("phone") or "").strip():
        channels.append("whatsapp")
    if _is_valid_email(user.get("email")):
        channels.append("email")
    return channels


def _preferred_login_otp_channels(user, requested_channel=None):
    available = _login_otp_available_channels(user)
    if not available:
        return []

    preferred = []
    requested = (requested_channel or "").strip().lower()
    if requested:
        return [requested] if requested in available else []

    default_channel = str(current_app.config.get("PORTAL_LOGIN_OTP_DEFAULT_CHANNEL") or "whatsapp").strip().lower()
    if default_channel in available and default_channel not in preferred:
        preferred.append(default_channel)

    for channel in ("whatsapp", "email"):
        if channel in available and channel not in preferred:
            preferred.append(channel)

    return preferred


def _set_pending_login_otp_session(user, next_target=None, login_location=None):
    safe_target = _safe_login_redirect_target(next_target) or ""
    session.clear()
    session["pending_login_otp_user_id"] = user["id"]
    session["pending_login_otp_username"] = user["username"]
    session["pending_login_otp_next"] = safe_target
    session["pending_login_otp_started_at"] = datetime.now(timezone.utc).timestamp()
    if login_location:
        session["pending_login_otp_location"] = login_location


def _get_pending_login_otp_user(db):
    user_id = session.get("pending_login_otp_user_id")
    started_at = session.get("pending_login_otp_started_at")
    if not user_id or not started_at:
        return None

    try:
        started_at = float(started_at)
    except (TypeError, ValueError):
        session.clear()
        return None

    if datetime.now(timezone.utc).timestamp() - started_at > _portal_login_otp_session_minutes() * 60:
        session.clear()
        return None

    user = db.execute("SELECT * FROM users WHERE id=? LIMIT 1", (user_id,)).fetchone()
    return dict(user) if user else None


def _issue_portal_login_otp_challenge(db, user, channel):
    code = generate_numeric_code(5)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_portal_login_otp_ttl_minutes())
    return code, expires_at


def _store_portal_login_otp_challenge(db, user, channel, code, expires_at):
    code_hash = hash_user_email_verification_token(code)
    db.execute(
        """
        UPDATE users
        SET login_otp_code_hash=?,
            login_otp_sent_at=CURRENT_TIMESTAMP,
            login_otp_expires_at=?,
            login_otp_attempts=0,
            login_otp_channel=?
        WHERE id=?
        """,
        (
            code_hash,
            expires_at.strftime("%Y-%m-%d %H:%M:%S"),
            channel,
            user["id"],
        ),
    )


def _format_portal_otp_expiry(expires_at):
    month_labels = (
        "Januari",
        "Februari",
        "Maret",
        "April",
        "Mei",
        "Juni",
        "Juli",
        "Agustus",
        "September",
        "Oktober",
        "November",
        "Desember",
    )
    jakarta_tz = timezone(timedelta(hours=7))
    if not expires_at:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=_portal_login_otp_ttl_minutes())
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    local_expiry = expires_at.astimezone(jakarta_tz)
    return (
        f"{local_expiry.day} {month_labels[local_expiry.month - 1]} "
        f"{local_expiry.year}, {local_expiry.strftime('%H:%M')} WIB"
    )


def _portal_login_otp_display_name(db, user):
    employee_id = user.get("employee_id") if user else None
    if employee_id:
        try:
            employee = db.execute(
                "SELECT full_name FROM employees WHERE id=? LIMIT 1",
                (employee_id,),
            ).fetchone()
            employee_name = str(employee["full_name"] or "").strip() if employee else ""
            if employee_name:
                return employee_name
        except Exception:
            pass
    return str(user.get("username") or "User").strip() or "User"


def _build_portal_login_otp_email(db, user, code, expires_at):
    display_name = _portal_login_otp_display_name(db, user)
    company_label = (current_app.config.get("STORE_NAME") or "CV BJAS").strip()
    expiry_label = _format_portal_otp_expiry(expires_at)
    logo_url = _build_portal_static_url("brand/mataram-logo.png")
    safe_display_name = escape(display_name)
    safe_company = escape(company_label)
    safe_code = escape(code)
    safe_expiry = escape(expiry_label)
    safe_logo_url = escape(logo_url, quote=True)
    subject = "Kode Verifikasi Login Portal CV BJAS"
    text_body = (
        f"Halo {display_name} ({company_label}),\n\n"
        "Berikut adalah kode verifikasi Anda untuk login ke Portal CV BJAS:\n\n"
        f"{code}\n\n"
        f"Kode ini valid hingga {expiry_label} dan hanya bisa digunakan sekali.\n\n"
        "Jika Anda tidak merasa melakukan login Portal CV BJAS, abaikan email ini dan segera lakukan reset password.\n\n"
        "Best Regards,\n"
        "CV BJAS Team"
    )
    html_body = f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(subject)}</title>
</head>
<body style="margin:0;padding:0;background:#f5f7fb;font-family:Arial,Helvetica,sans-serif;color:#1f2937;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">Kode verifikasi login Portal CV BJAS: {safe_code}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f5f7fb;padding:28px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:680px;background:#ffffff;border-radius:14px;border:1px solid #e5e7eb;overflow:hidden;">
          <tr>
            <td style="padding:36px 42px 18px 42px;">
              <img src="{safe_logo_url}" alt="CV BJAS" width="128" style="display:block;max-width:128px;height:auto;border:0;margin:0 0 24px 0;">
              <div style="border-top:1px solid #edf0f5;padding-top:28px;">
                <p style="font-size:17px;line-height:1.6;margin:0 0 22px 0;">Halo <strong>{safe_display_name} ({safe_company})</strong>,</p>
                <p style="font-size:17px;line-height:1.6;margin:0 0 22px 0;">Berikut adalah kode verifikasi Anda untuk login ke Portal CV BJAS:</p>
                <div style="font-size:56px;line-height:1;font-weight:800;letter-spacing:6px;color:#3578d8;margin:30px 0 30px 0;">{safe_code}</div>
                <p style="font-size:16px;line-height:1.7;margin:0 0 22px 0;">Kode ini valid hingga <strong>{safe_expiry}</strong> dan hanya bisa digunakan sekali.</p>
                <p style="font-size:16px;line-height:1.7;margin:0 0 28px 0;">Jika Anda tidak merasa melakukan login Portal CV BJAS, mohon abaikan email ini dan segera lakukan reset password.</p>
                <p style="font-size:16px;line-height:1.6;margin:0;">Best Regards,<br>CV BJAS Team</p>
              </div>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return subject, text_body, html_body


def _clear_portal_login_otp(db, user_id):
    db.execute(
        """
        UPDATE users
        SET login_otp_code_hash=NULL,
            login_otp_sent_at=NULL,
            login_otp_expires_at=NULL,
            login_otp_attempts=0,
            login_otp_channel=NULL
        WHERE id=?
        """,
        (user_id,),
    )


def _normalize_portal_login_otp_delivery_result(delivery, target):
    if isinstance(delivery, dict):
        return delivery
    return {
        "ok": bool(delivery),
        "provider": "portal_login_otp",
        "receiver": target,
        "error": "" if delivery else "whatsapp_send_failed",
    }


def _record_portal_login_otp_whatsapp_delivery(user, subject, message, delivery):
    redacted_message = re.sub(
        r"(Kode OTP kamu:\s*)\d{5}",
        r"\1*****",
        str(message or ""),
        flags=re.IGNORECASE,
    )
    try:
        record_whatsapp_delivery(
            user.get("id"),
            user.get("role") or "",
            user.get("phone"),
            subject,
            redacted_message,
            delivery,
            channel="otp_wa",
        )
    except Exception as exc:
        print("PORTAL LOGIN OTP WA LOG ERROR:", exc)


def _send_portal_login_otp(db, user, requested_channel=None):
    user = dict(user)
    channels = _preferred_login_otp_channels(user, requested_channel=requested_channel)
    if not channels:
        return False, "Akun ini wajib OTP, tetapi email atau WhatsApp belum terdaftar. Hubungi admin."

    ttl_minutes = _portal_login_otp_ttl_minutes()
    username = user.get("username") or "User"
    subject = "Kode OTP Login Portal CV BJAS"

    last_message = "Kode OTP belum terkirim. Cek konfigurasi email/WhatsApp."
    for channel in channels:
        code, expires_at = _issue_portal_login_otp_challenge(db, user, channel)
        resend_reference = secrets.token_hex(3).upper()
        sent_at_label = datetime.now(timezone(timedelta(hours=7))).strftime("%d/%m/%Y %H:%M:%S WIB")
        body = (
            f"Halo {username},\n\n"
            "Ada percobaan login ke Portal CV BJAS.\n"
            f"Kode OTP kamu: {code}\n\n"
            f"Dikirim: {sent_at_label}\n"
            f"Ref: {resend_reference}\n\n"
            f"Kode berlaku {ttl_minutes} menit dan hanya untuk satu kali login.\n"
            "Kalau ini bukan kamu, segera ganti password dan hubungi admin.\n\n"
            "CV Berkah Jaya Abadi Sports"
        )

        try:
            if channel == "whatsapp":
                delivery = send_whatsapp(user["phone"], f"*{subject}*\n\n{body}", return_detail=True)
                delivery = _normalize_portal_login_otp_delivery_result(delivery, user.get("phone"))
                _record_portal_login_otp_whatsapp_delivery(user, subject, body, delivery)
                sent = delivery.get("ok")
                if sent:
                    _store_portal_login_otp_challenge(db, user, channel, code, expires_at)
                    return True, f"Kode OTP sudah dikirim ke WhatsApp {_masked_phone(user.get('phone'))}."
                detail = ""
                if delivery.get("error"):
                    detail = f" Detail teknis: {delivery.get('error')}."
                last_message = f"Kode OTP WhatsApp belum terkirim. Coba kirim via email atau cek konfigurasi WhatsApp.{detail}"
            else:
                email_subject, email_body, email_html = _build_portal_login_otp_email(db, user, code, expires_at)
                sent = send_email(user["email"], email_subject, email_body, html_body=email_html)
                if sent:
                    _store_portal_login_otp_challenge(db, user, channel, code, expires_at)
                    return True, f"Kode OTP sudah dikirim ke email {_masked_email(user.get('email'))}."
                last_message = "Kode OTP email belum terkirim. Coba kirim via WhatsApp atau cek konfigurasi SMTP/Brevo."
        except Exception as exc:
            print("PORTAL LOGIN OTP SEND ERROR:", exc)
            last_message = "Kode OTP belum terkirim karena layanan notifikasi bermasalah."

    return False, last_message


def _verify_portal_login_otp(db, user, submitted_code):
    code = _normalize_portal_login_otp_code(submitted_code)
    if not code:
        return False, "Kode OTP harus 5 digit."

    expires_at = _parse_db_timestamp(user.get("login_otp_expires_at"))
    if not user.get("login_otp_code_hash") or expires_at is None or expires_at < datetime.now(timezone.utc):
        return False, "Kode OTP sudah kedaluwarsa. Kirim ulang kode untuk lanjut."

    expected_hash = hash_user_email_verification_token(code)
    if expected_hash == user.get("login_otp_code_hash"):
        _clear_portal_login_otp(db, user["id"])
        return True, "OTP valid."

    attempts = int(user.get("login_otp_attempts") or 0) + 1
    db.execute(
        "UPDATE users SET login_otp_attempts=? WHERE id=?",
        (attempts, user["id"]),
    )
    remaining = _portal_login_otp_max_attempts() - attempts
    if remaining <= 0:
        _clear_portal_login_otp(db, user["id"])
        session.clear()
        return False, "Kode OTP salah terlalu banyak. Silakan login ulang."

    return False, f"Kode OTP salah. Sisa percobaan {remaining} kali."


def _format_otp_channel_label(channel):
    if channel == "whatsapp":
        return "WhatsApp"
    if channel == "email":
        return "Email"
    return "kontak"


def _email_used_by_other_user(db, email, user_id):
    row = db.execute(
        """
        SELECT id
        FROM users
        WHERE lower(email)=?
          AND id<>?
        LIMIT 1
        """,
        (_normalize_email(email), user_id),
    ).fetchone()
    return row is not None


def _portal_login_device_cookie_name():
    configured = str(current_app.config.get("PORTAL_LOGIN_DEVICE_COOKIE_NAME") or "").strip()
    return configured or "portal_device_id"


def _sanitize_portal_device_id(value):
    safe_value = str(value or "").strip()
    if not safe_value or len(safe_value) > 160:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", safe_value):
        return ""
    return safe_value


def _hash_portal_device_id(value):
    safe_value = _sanitize_portal_device_id(value)
    if not safe_value:
        return ""
    return hashlib.sha256(safe_value.encode("utf-8")).hexdigest()


def _portal_otp_today_key():
    return datetime.now(timezone(timedelta(hours=7))).date().isoformat()


def _current_portal_device_id_from_cookie():
    return _sanitize_portal_device_id(request.cookies.get(_portal_login_device_cookie_name()))


def _get_current_portal_login_device(db, user_id):
    device_id = _current_portal_device_id_from_cookie()
    device_hash = _hash_portal_device_id(device_id)
    if not device_hash:
        return None

    row = db.execute(
        """
        SELECT *
        FROM user_login_devices
        WHERE user_id=? AND device_hash=?
        LIMIT 1
        """,
        (user_id, device_hash),
    ).fetchone()
    return dict(row) if row else None


def _portal_login_device_otp_valid_today(device_row):
    if not device_row:
        return False
    return str(device_row.get("otp_verified_date") or "") == _portal_otp_today_key()


def _portal_login_otp_required_for_request(db, user):
    if not _user_login_otp_required(user):
        return False
    return not _portal_login_device_otp_valid_today(
        _get_current_portal_login_device(db, user["id"])
    )


def _resolve_portal_device_id():
    cookie_name = _portal_login_device_cookie_name()
    device_id = _sanitize_portal_device_id(request.cookies.get(cookie_name))
    if device_id:
        return device_id
    return secrets.token_urlsafe(32)


def _format_login_device_label(user_agent):
    agent = str(user_agent or "").strip()
    lowered = agent.lower()
    if not lowered:
        return "Perangkat tidak dikenal"

    if "edg/" in lowered or "edge/" in lowered:
        browser = "Microsoft Edge"
    elif "opr/" in lowered or "opera" in lowered:
        browser = "Opera"
    elif "firefox/" in lowered:
        browser = "Firefox"
    elif "samsungbrowser/" in lowered:
        browser = "Samsung Internet"
    elif "chrome/" in lowered or "crios/" in lowered:
        browser = "Chrome"
    elif "safari/" in lowered:
        browser = "Safari"
    else:
        browser = "Browser"

    if "android" in lowered:
        platform = "Android"
    elif "iphone" in lowered:
        platform = "iPhone"
    elif "ipad" in lowered:
        platform = "iPad"
    elif "windows" in lowered:
        platform = "Windows"
    elif "mac os" in lowered or "macintosh" in lowered:
        platform = "Mac"
    elif "linux" in lowered:
        platform = "Linux"
    else:
        platform = "perangkat baru"

    return f"{browser} di {platform}"


def _format_jakarta_login_time():
    jakarta_tz = timezone(timedelta(hours=7))
    return datetime.now(jakarta_tz).strftime("%d/%m/%Y %H:%M WIB")


def _normalize_login_coordinate(value, minimum, maximum):
    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        return None
    if coordinate < minimum or coordinate > maximum:
        return None
    return round(coordinate, 6)


def _normalize_login_accuracy(value):
    try:
        accuracy = float(value)
    except (TypeError, ValueError):
        return None
    if accuracy < 0:
        return None
    return round(accuracy, 1)


def _get_portal_login_location_from_form():
    latitude = _normalize_login_coordinate(request.form.get("login_latitude"), -90, 90)
    longitude = _normalize_login_coordinate(request.form.get("login_longitude"), -180, 180)
    if latitude is None or longitude is None:
        return None
    accuracy = _normalize_login_accuracy(request.form.get("login_accuracy"))
    return {
        "latitude": latitude,
        "longitude": longitude,
        "accuracy": accuracy,
        "maps_url": f"https://www.google.com/maps?q={latitude:.6f},{longitude:.6f}",
    }


def _format_login_location_line(login_location):
    if not login_location:
        return "Lokasi: tidak dibagikan browser"
    accuracy = login_location.get("accuracy")
    accuracy_label = f" (akurasi +/- {accuracy:g} m)" if accuracy is not None else ""
    return f"Lokasi: {login_location['maps_url']}{accuracy_label}"


def _notify_new_portal_login_device(user, device_label, ip_address, login_location=None):
    username = user.get("username") or "User"
    login_time = _format_jakarta_login_time()
    location_line = _format_login_location_line(login_location)
    subject = "Login Baru Portal CV BJAS"
    message = (
        "Ada login baru ke Portal CV BJAS.\n\n"
        f"Akun: {username}\n"
        f"Perangkat: {device_label}\n"
        f"IP: {ip_address or 'tidak terbaca'}\n"
        f"{location_line}\n"
        f"Waktu: {login_time}\n\n"
        "Kalau ini kamu, abaikan pesan ini. Kalau bukan kamu, segera ganti password dan hubungi admin."
    )

    try:
        create_web_notification(
            user["id"],
            subject,
            f"{device_label} login pada {login_time}. IP: {ip_address or 'tidak terbaca'}. {location_line}.",
            category="security",
            link_url="/account/",
            source_type="login_device",
            source_id=str(user["id"]),
            dedupe_key=f"login-device:{user['id']}:{device_label}:{ip_address or ''}",
        )
    except Exception as exc:
        print("NEW DEVICE WEB NOTIFICATION ERROR:", exc)

    try:
        if user.get("email") and _truthy(user.get("notify_email")):
            send_email(user["email"], subject, message)
    except Exception as exc:
        print("NEW DEVICE EMAIL NOTIFICATION ERROR:", exc)

    try:
        if user.get("phone") and _truthy(user.get("notify_whatsapp")):
            send_whatsapp(user["phone"], f"*{subject}*\n\n{message}")
    except Exception as exc:
        print("NEW DEVICE WHATSAPP NOTIFICATION ERROR:", exc)


def _remember_portal_login_device(db, user, login_location=None, otp_verified=False):
    notify_enabled = bool(current_app.config.get("PORTAL_NEW_DEVICE_NOTIFICATION_ENABLED", True))
    device_id = _resolve_portal_device_id()
    device_hash = _hash_portal_device_id(device_id)
    if not device_hash:
        return None

    user_agent = str(request.headers.get("User-Agent") or "").strip()[:500]
    device_label = _format_login_device_label(user_agent)
    ip_address = (get_client_ip() or "unknown").strip()[:80]
    if login_location is None:
        login_location = _get_portal_login_location_from_form()
    user_id = user["id"]

    existing = db.execute(
        """
        SELECT id
        FROM user_login_devices
        WHERE user_id=? AND device_hash=?
        LIMIT 1
        """,
        (user_id, device_hash),
    ).fetchone()

    known_count_row = db.execute(
        "SELECT COUNT(*) AS total FROM user_login_devices WHERE user_id=?",
        (user_id,),
    ).fetchone()
    known_count = int(known_count_row["total"] or 0) if known_count_row else 0

    if existing:
        if otp_verified:
            db.execute(
                """
                UPDATE user_login_devices
                SET user_agent=?,
                    label=?,
                    last_ip=?,
                    last_seen_at=CURRENT_TIMESTAMP,
                    otp_verified_at=CURRENT_TIMESTAMP,
                    otp_verified_date=?
                WHERE id=?
                """,
                (user_agent, device_label, ip_address, _portal_otp_today_key(), existing["id"]),
            )
        else:
            db.execute(
                """
                UPDATE user_login_devices
                SET user_agent=?,
                    label=?,
                    last_ip=?,
                    last_seen_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (user_agent, device_label, ip_address, existing["id"]),
            )
    else:
        otp_verified_at_sql = "CURRENT_TIMESTAMP" if otp_verified else "NULL"
        db.execute(
            f"""
            INSERT INTO user_login_devices(
                user_id,
                device_hash,
                user_agent,
                label,
                first_ip,
                last_ip,
                otp_verified_at,
                otp_verified_date
            )
            VALUES (?,?,?,?,?,?,{otp_verified_at_sql},?)
            """,
            (
                user_id,
                device_hash,
                user_agent,
                device_label,
                ip_address,
                ip_address,
                _portal_otp_today_key() if otp_verified else None,
            ),
        )
        if notify_enabled and known_count > 0:
            _notify_new_portal_login_device(user, device_label, ip_address, login_location)

    return device_id


def _complete_user_login(db, user, next_target=None, login_location=None, otp_verified=False):
    session.clear()

    normalized_role = normalize_role(user["role"])

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = normalized_role
    session["employee_id"] = user.get("employee_id")
    permission_snapshot = load_user_permission_override_snapshot(db, user["id"])
    session["permission_grants"] = sorted(permission_snapshot["allow"])
    session["permission_denies"] = sorted(permission_snapshot["deny"])
    session["chat_sound_volume"] = float(
        user.get("chat_sound_volume")
        if user.get("chat_sound_volume") is not None
        else current_app.config.get("CHAT_SOUND_VOLUME_DEFAULT", 0.85)
    )

    try:
        user_wh = user.get("warehouse_id") if user else None
    except Exception:
        user_wh = None

    if user_wh and is_scoped_role(normalized_role):
        session["warehouse_id"] = user_wh
    else:
        warehouse = db.execute(
            """
            SELECT id FROM warehouses ORDER BY id LIMIT 1
            """
        ).fetchone()

        session["warehouse_id"] = warehouse["id"] if warehouse else 1

    if is_scoped_role(normalized_role) and session.get("warehouse_id"):
        last_seen = db.execute(
            """
            SELECT COALESCE(MAX(id), 0)
            FROM requests
            WHERE from_warehouse=? OR to_warehouse=?
            """,
            (session["warehouse_id"], session["warehouse_id"]),
        ).fetchone()[0]
    else:
        last_seen = db.execute("SELECT COALESCE(MAX(id), 0) FROM requests").fetchone()[0]

    session["request_last_seen_id"] = last_seen
    session["last_active"] = datetime.now(timezone.utc).timestamp()
    session.permanent = True

    default_target = url_for("dashboard.workspace_gateway")
    device_id = None
    try:
        device_id = _remember_portal_login_device(
            db,
            user,
            login_location=login_location,
            otp_verified=otp_verified,
        )
    except Exception as exc:
        print("PORTAL LOGIN DEVICE TRACKING ERROR:", exc)

    response = redirect(next_target or default_target)
    if device_id:
        response.set_cookie(
            _portal_login_device_cookie_name(),
            device_id,
            max_age=max(86400, int(current_app.config.get("PORTAL_LOGIN_DEVICE_COOKIE_MAX_AGE", 60 * 60 * 24 * 180))),
            httponly=True,
            secure=bool(current_app.config.get("SESSION_COOKIE_SECURE") or request.is_secure),
            samesite="Lax",
        )
    return response


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    next_target = _safe_login_redirect_target(
        request.form.get("next") or request.args.get("next")
    )
    default_target = url_for("dashboard.workspace_gateway")

    if request.method == "GET" and session.get("user_id"):
        return redirect(next_target or default_target)

    if request.method == "POST":

        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        if not username or not password:
            flash("Email / Password wajib diisi", "error")
            return _redirect_to_login(next_target)

        db = get_db()
        _ensure_portal_auth_schema(db)
        identifier = normalize_identifier(username)
        client_ip = get_client_ip()
        throttle_state = get_login_throttle_state(db, identifier, client_ip)

        if throttle_state["blocked"]:
            flash(
                f"Terlalu banyak percobaan login. Coba lagi dalam {throttle_state['retry_after']} detik.",
                "error",
            )
            return _redirect_to_login(next_target)

        if _portal_email_login_required():
            user = _lookup_portal_login_user(db, identifier)
        else:
            user = db.execute(
                "SELECT * FROM users WHERE lower(username)=? LIMIT 1",
                (identifier,),
            ).fetchone()

        if not user:
            record_login_attempt(db, identifier, client_ip, False)
            flash("Email / Password salah", "error")
            return _redirect_to_login(next_target)

        user = dict(user)

        try:
            valid = check_password_hash(user["password"], password)
        except:
            valid = False

        if not valid:
            record_login_attempt(db, identifier, client_ip, False)
            flash("Email / Password salah", "error")
            return _redirect_to_login(next_target)

        clear_login_failures(db, identifier, client_ip)

        if _portal_email_login_required() and not _user_portal_email_ready(user):
            _set_pending_email_session(user, next_target)
            if _is_valid_email(user.get("email")):
                ok, message = _send_portal_email_verification(db, user)
                flash(message, "success" if ok else "error")
            else:
                flash("Daftarkan email dulu untuk melanjutkan akses portal.", "info")
            return redirect(url_for("auth.portal_email_required"))

        if _portal_login_otp_required_for_request(db, user):
            _set_pending_login_otp_session(
                user,
                next_target,
                login_location=_get_portal_login_location_from_form(),
            )
            ok, message = _send_portal_login_otp(db, user)
            flash(message, "success" if ok else "error")
            return redirect(url_for("auth.portal_login_otp"))

        record_login_attempt(db, identifier, client_ip, True)
        return _complete_user_login(db, user, next_target)

    return render_template("login.html", next_url=next_target or "")


@auth_bp.route("/login/otp", methods=["GET", "POST"])
def portal_login_otp():
    db = get_db()
    _ensure_portal_auth_schema(db)
    user = _get_pending_login_otp_user(db)
    if not user:
        flash("Sesi OTP habis. Login ulang untuk melanjutkan.", "error")
        return redirect(url_for("auth.login"))

    next_target = _safe_login_redirect_target(session.get("pending_login_otp_next")) or ""
    available_channels = _login_otp_available_channels(user)
    if not _user_login_otp_required(user):
        return _complete_user_login(
            db,
            user,
            next_target,
            login_location=session.get("pending_login_otp_location"),
        )

    if request.method == "POST":
        action = (request.form.get("action") or "verify_code").strip()

        if action == "verify_code":
            ok, message = _verify_portal_login_otp(db, user, request.form.get("otp_code"))
            if ok:
                identifier = normalize_identifier(user.get("email") or user.get("username"))
                record_login_attempt(db, identifier, get_client_ip(), True)
                login_location = session.get("pending_login_otp_location")
                flash("Login berhasil.", "success")
                return _complete_user_login(
                    db,
                    user,
                    next_target,
                    login_location=login_location,
                    otp_verified=True,
                )

            flash(message, "error")
            if "login ulang" in message.lower():
                return redirect(url_for("auth.login"))
            return redirect(url_for("auth.portal_login_otp"))

        if action in {"resend_email", "resend_whatsapp"}:
            requested_channel = "email" if action == "resend_email" else "whatsapp"
            ok, message = _send_portal_login_otp(db, user, requested_channel=requested_channel)
            flash(message, "success" if ok else "error")
            return redirect(url_for("auth.portal_login_otp"))

        flash("Aksi OTP tidak valid.", "error")
        return redirect(url_for("auth.portal_login_otp"))

    return render_template(
        "login_otp_required.html",
        username=user.get("username"),
        masked_email=_masked_email(user.get("email")),
        masked_phone=_masked_phone(user.get("phone")),
        has_email="email" in available_channels,
        has_phone="whatsapp" in available_channels,
        active_channel_label=_format_otp_channel_label(user.get("login_otp_channel")),
        has_active_otp=bool(user.get("login_otp_code_hash") and user.get("login_otp_channel")),
        next_url=next_target,
        ttl_minutes=_portal_login_otp_ttl_minutes(),
    )


@auth_bp.route("/login/email-required", methods=["GET", "POST"])
def portal_email_required():
    db = get_db()
    _ensure_portal_auth_schema(db)
    user = _get_pending_email_user(db)
    if not user:
        flash("Sesi verifikasi email habis. Login ulang untuk melanjutkan.", "error")
        return redirect(url_for("auth.login"))

    if _user_portal_email_ready(user):
        flash("Email akun sudah terverifikasi. Silakan login memakai email.", "success")
        session.clear()
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        action = (request.form.get("action") or "save_email").strip()
        submitted_email = _normalize_email(request.form.get("email")) or _normalize_email(user.get("email"))

        if action == "change_email":
            submitted_email = ""

        if action == "verify_code":
            verification_code = _normalize_portal_verification_code(request.form.get("verification_code"))
            if not verification_code:
                flash("Kode verifikasi harus 5 digit.", "error")
                return redirect(url_for("auth.portal_email_required"))
            if not _is_valid_email(user.get("email")):
                flash("Email akun belum valid. Simpan email aktif dulu.", "error")
                return redirect(url_for("auth.portal_email_required"))

            verified_user = get_user_by_email_verification_code(db, user["id"], verification_code)
            verified_user = dict(verified_user) if verified_user else None
            expires_at = _parse_db_timestamp(verified_user.get("email_verification_expires_at")) if verified_user else None
            if not verified_user or expires_at is None or expires_at < datetime.now(timezone.utc):
                flash("Kode verifikasi tidak valid atau sudah kedaluwarsa. Kirim ulang kode jika perlu.", "error")
                return redirect(url_for("auth.portal_email_required"))

            mark_user_email_verified(db, user["id"])
            db.commit()
            session.clear()
            flash("Email berhasil dikonfirmasi. Silakan login memakai email.", "success")
            return redirect(url_for("auth.login"))

        if action in {"save_email", "resend", "send_whatsapp"}:
            if not _is_valid_email(submitted_email):
                flash("Masukkan email aktif dengan format yang benar.", "error")
                return redirect(url_for("auth.portal_email_required"))
            if _email_used_by_other_user(db, submitted_email, user["id"]):
                flash("Email ini sudah dipakai akun lain.", "error")
                return redirect(url_for("auth.portal_email_required"))

            if submitted_email != _normalize_email(user.get("email")):
                db.execute(
                    """
                    UPDATE users
                    SET email=?,
                        email_verified_at=NULL,
                        email_verification_token_hash=NULL,
                        email_verification_code_hash=NULL,
                        email_verification_sent_at=NULL,
                        email_verification_expires_at=NULL,
                        notify_email=1
                    WHERE id=?
                    """,
                    (submitted_email, user["id"]),
                )
                db.commit()
                user = dict(db.execute("SELECT * FROM users WHERE id=? LIMIT 1", (user["id"],)).fetchone())

            if action == "send_whatsapp":
                ok, message = _send_portal_whatsapp_verification(db, user)
            else:
                ok, message = _send_portal_email_verification(db, user, force=(action == "resend"))
            flash(message, "success" if ok else "error")
            return redirect(url_for("auth.portal_email_required"))

        flash("Aksi tidak valid.", "error")
        return redirect(url_for("auth.portal_email_required"))

    return render_template(
        "login_email_required.html",
        username=user.get("username"),
        email=user.get("email") or "",
        masked_email=_masked_email(user.get("email")),
        has_email=_is_valid_email(user.get("email")),
        masked_phone=_masked_phone(user.get("phone")),
        has_phone=bool(str(user.get("phone") or "").strip()),
        next_url=session.get("pending_email_next") or "",
    )


@auth_bp.route("/login/verify-email")
def verify_portal_email():
    token = (request.args.get("token") or "").strip()
    db = get_db()
    _ensure_portal_auth_schema(db)
    user = get_user_by_email_verification_token(db, token)
    user = dict(user) if user else None
    if not user:
        flash("Tautan verifikasi email tidak valid atau sudah dipakai.", "error")
        return redirect(url_for("auth.login"))

    expires_at = _parse_db_timestamp(user.get("email_verification_expires_at"))
    if expires_at is None or expires_at < datetime.now(timezone.utc):
        flash("Tautan verifikasi email sudah kedaluwarsa. Login ulang untuk kirim tautan baru.", "error")
        return redirect(url_for("auth.login"))

    mark_user_email_verified(db, user["id"])
    db.commit()
    session.clear()
    flash("Email berhasil dikonfirmasi. Silakan login memakai email.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


# ==========================
# FORGOT / RESET PASSWORD
# ==========================


@auth_bp.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        identifier = (request.form.get('identifier') or '').strip()
        if not identifier:
            flash('Masukkan username, email, atau nomor telepon', 'error')
            return redirect(url_for('auth.forgot_password'))

        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username=? OR email=? OR phone=? LIMIT 1', (identifier, identifier, identifier)).fetchone()

        # Always respond with same message to avoid enumeration
        flash('Jika data cocok, kode reset telah dikirim ke kontak terdaftar.', 'info')

        if not user:
            return redirect(url_for('auth.login'))

        user = dict(user)

        ttl_minutes = current_app.config.get("PASSWORD_RESET_TTL_MINUTES", 15)
        code = issue_password_reset_code(db, user['id'], ttl_minutes)

        subj = 'Kode Reset Password'
        msg = f"Kode reset password Anda: {code}. Berlaku {ttl_minutes} menit."

        try:
            if user.get('email') and user.get('notify_email'):
                send_email(user['email'], subj, msg)
        except Exception:
            pass

        try:
            if user.get('phone') and user.get('notify_whatsapp'):
                send_whatsapp(user['phone'], msg)
        except Exception:
            pass

        return redirect(url_for('auth.login'))

    return render_template('forgot.html')


@auth_bp.route('/reset', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        code = (request.form.get('code') or '').strip()
        newpw = (request.form.get('password') or '').strip()

        if not username or not code or not newpw:
            flash('Semua field wajib diisi', 'error')
            return redirect(url_for('auth.reset_password'))

        min_length = int(current_app.config.get("PASSWORD_MIN_LENGTH", 8))
        if len(newpw) < min_length:
            flash(f'Password minimal {min_length} karakter', 'error')
            return redirect(url_for('auth.reset_password'))

        db = get_db()
        cleanup_password_resets(db)
        user = db.execute('SELECT * FROM users WHERE username=? LIMIT 1', (username,)).fetchone()
        if not user:
            flash('Kode tidak valid atau kadaluarsa', 'error')
            return redirect(url_for('auth.reset_password'))

        pr = db.execute('SELECT * FROM password_resets WHERE user_id=? AND code=? AND used=0 AND expires_at > datetime("now") ORDER BY id DESC LIMIT 1', (user['id'], code)).fetchone()
        if not pr:
            flash('Kode tidak valid atau kadaluarsa', 'error')
            return redirect(url_for('auth.reset_password'))

        # perform reset
        from werkzeug.security import generate_password_hash
        db.execute('UPDATE users SET password=? WHERE id=?', (generate_password_hash(newpw), user['id']))
        mark_password_resets_used(db, user['id'])

        flash('Password berhasil direset. Silakan login.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset.html')
