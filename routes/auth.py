import re
from urllib.parse import urlsplit

from flask import Blueprint, current_app, g, render_template, request, redirect, session, url_for, flash
from database import get_db, is_postgresql_backend
from services.notification_service import send_email, send_whatsapp
from services.rbac import is_scoped_role, load_user_permission_override_snapshot, normalize_role
from services.auth_security import (
    clear_login_failures,
    get_client_ip,
    get_login_throttle_state,
    get_user_by_email_verification_code,
    get_user_by_email_verification_token,
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
            "CREATE INDEX IF NOT EXISTS idx_users_email_lookup ON users(email)",
            "CREATE INDEX IF NOT EXISTS idx_users_email_verification ON users(email_verification_token_hash)",
            "CREATE INDEX IF NOT EXISTS idx_users_email_verification_code ON users(email_verification_code_hash)",
        )
        for statement in statements:
            db.execute(statement)
        db.commit()

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
    configured_base = (
        (current_app.config.get("PORTAL_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        or (
            f"{current_app.config.get('CANONICAL_SCHEME', 'https')}://{current_app.config.get('CANONICAL_HOST')}"
            if current_app.config.get("CANONICAL_HOST")
            else ""
        ).strip().rstrip("/")
        or (current_app.config.get("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    )
    if configured_base:
        return f"{configured_base}{path}"
    return url_for("auth.verify_portal_email", token=token, _external=True)


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


def _complete_user_login(db, user, next_target=None):
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
    return redirect(next_target or default_target)


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
        record_login_attempt(db, identifier, client_ip, True)

        if _portal_email_login_required() and not _user_portal_email_ready(user):
            _set_pending_email_session(user, next_target)
            if _is_valid_email(user.get("email")):
                ok, message = _send_portal_email_verification(db, user)
                flash(message, "success" if ok else "error")
            else:
                flash("Daftarkan email dulu untuk melanjutkan akses portal.", "info")
            return redirect(url_for("auth.portal_email_required"))

        return _complete_user_login(db, user, next_target)

    return render_template("login.html", next_url=next_target or "")


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
