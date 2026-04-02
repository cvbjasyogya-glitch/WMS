from urllib.parse import urlsplit

from flask import Blueprint, current_app, render_template, request, redirect, session, url_for, flash
from database import get_db
from services.notification_service import send_email, send_whatsapp
from services.rbac import is_scoped_role, normalize_role
from services.auth_security import (
    clear_login_failures,
    get_client_ip,
    get_login_throttle_state,
    issue_password_reset_code,
    mark_password_resets_used,
    normalize_identifier,
    record_login_attempt,
    cleanup_password_resets,
)
from werkzeug.security import check_password_hash
from datetime import datetime, timezone

auth_bp = Blueprint("auth", __name__)


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


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    next_target = _safe_login_redirect_target(
        request.form.get("next") or request.args.get("next")
    )

    if request.method == "GET" and session.get("user_id"):
        return redirect(next_target or "/")

    if request.method == "POST":

        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        if not username or not password:
            flash("Username / Password wajib diisi", "error")
            return _redirect_to_login(next_target)

        db = get_db()
        identifier = normalize_identifier(username)
        client_ip = get_client_ip()
        throttle_state = get_login_throttle_state(db, identifier, client_ip)

        if throttle_state["blocked"]:
            flash(
                f"Terlalu banyak percobaan login. Coba lagi dalam {throttle_state['retry_after']} detik.",
                "error",
            )
            return _redirect_to_login(next_target)

        user = db.execute(
            "SELECT * FROM users WHERE lower(username)=? LIMIT 1",
            (identifier,)
        ).fetchone()

        if not user:
            record_login_attempt(db, identifier, client_ip, False)
            flash("Username / Password salah", "error")
            return _redirect_to_login(next_target)

        user = dict(user)

        try:
            valid = check_password_hash(user["password"], password)
        except:
            valid = False

        if not valid:
            record_login_attempt(db, identifier, client_ip, False)
            flash("Username / Password salah", "error")
            return _redirect_to_login(next_target)

        clear_login_failures(db, identifier, client_ip)
        record_login_attempt(db, identifier, client_ip, True)

        # ==============================
        # LOGIN SUCCESS
        # ==============================
        session.clear()

        normalized_role = normalize_role(user["role"])

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = normalized_role
        session["employee_id"] = user.get("employee_id")
        session["chat_sound_volume"] = float(
            user.get("chat_sound_volume")
            if user.get("chat_sound_volume") is not None
            else current_app.config.get("CHAT_SOUND_VOLUME_DEFAULT", 0.85)
        )
        # set warehouse scope: use user assigned warehouse for scoped roles, otherwise default first warehouse
        try:
            user_wh = user.get('warehouse_id') if user else None
        except Exception:
            user_wh = None

        if user_wh and is_scoped_role(normalized_role):
            session["warehouse_id"] = user_wh
        else:
            warehouse = db.execute("""
                SELECT id FROM warehouses ORDER BY id LIMIT 1
            """).fetchone()

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
            last_seen = db.execute(
                "SELECT COALESCE(MAX(id), 0) FROM requests"
            ).fetchone()[0]

        session["request_last_seen_id"] = last_seen

        session["last_active"] = datetime.now(timezone.utc).timestamp()
        session.permanent = True

        return redirect(next_target or "/")

    return render_template("login.html", next_url=next_target or "")


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
