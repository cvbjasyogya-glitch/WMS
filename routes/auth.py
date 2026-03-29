from flask import Blueprint, render_template, request, redirect, session, url_for, flash
from database import get_db
import random
from services.notification_service import send_email, send_whatsapp
from werkzeug.security import check_password_hash
from datetime import datetime, timezone

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()

        if not username or not password:
            flash("Username / Password wajib diisi", "error")
            return redirect(url_for("auth.login"))

        db = get_db()

        user = db.execute(
            "SELECT * FROM users WHERE username=?",
            (username,)
        ).fetchone()

        if not user:
            flash("Username / Password salah", "error")
            return redirect(url_for("auth.login"))

        try:
            valid = check_password_hash(user["password"], password)
        except:
            valid = False

        if not valid:
            flash("Username / Password salah", "error")
            return redirect(url_for("auth.login"))

        # ==============================
        # LOGIN SUCCESS
        # ==============================
        session.clear()

        session["user_id"] = user["id"]
        session["role"] = user["role"]
        # set warehouse scope: use user assigned warehouse for leader/admin, otherwise default first warehouse
        try:
            user_wh = user.get('warehouse_id') if user else None
        except Exception:
            user_wh = None

        if user_wh and user["role"] in ["leader", "admin"]:
            session["warehouse_id"] = user_wh
        else:
            warehouse = db.execute("""
                SELECT id FROM warehouses ORDER BY id LIMIT 1
            """).fetchone()

            session["warehouse_id"] = warehouse["id"] if warehouse else 1

        session["last_active"] = datetime.now(timezone.utc).timestamp()
        session.permanent = True

        return redirect("/")

    return render_template("login.html")


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

        # generate 6 digit code
        code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        db.execute("INSERT INTO password_resets(user_id, code, expires_at) VALUES (?,?,datetime('now','+15 minutes'))", (user['id'], code))
        db.commit()

        subj = 'Kode Reset Password'
        msg = f"Kode reset password Anda: {code}. Berlaku 15 menit."

        try:
            if user.get('email') and user.get('notify_email'):
                send_email(user.get('email'), subj, msg)
        except Exception:
            pass

        try:
            if user.get('phone') and user.get('notify_whatsapp'):
                send_whatsapp(user.get('phone'), msg)
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

        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username=? LIMIT 1', (username,)).fetchone()
        if not user:
            flash('User tidak ditemukan', 'error')
            return redirect(url_for('auth.reset_password'))

        pr = db.execute('SELECT * FROM password_resets WHERE user_id=? AND code=? AND used=0 AND expires_at > datetime("now") ORDER BY id DESC LIMIT 1', (user['id'], code)).fetchone()
        if not pr:
            flash('Kode tidak valid atau kadaluarsa', 'error')
            return redirect(url_for('auth.reset_password'))

        # perform reset
        from werkzeug.security import generate_password_hash
        db.execute('UPDATE users SET password=? WHERE id=?', (generate_password_hash(newpw), user['id']))
        db.execute('UPDATE password_resets SET used=1 WHERE id=?', (pr['id'],))
        db.commit()

        flash('Password berhasil direset. Silakan login.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset.html')
