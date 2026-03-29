from flask import Flask, session, redirect, url_for, request, flash
from config import Config
from database import close_db, get_db
from datetime import datetime, timezone
from services.notification_service import send_email, send_whatsapp
from werkzeug.security import generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from init_db import init_db
import sqlite3


# ==============================
# IMPORT ROUTES
# ==============================
from routes.dashboard import dashboard_bp
from routes.products import products_bp
from routes.transfers import transfers_bp
from routes.request import request_bp
from routes.stock import stock_bp
from routes.inbound import inbound_bp
from routes.outbound import outbound_bp
from routes.auth import auth_bp
from routes.audit import audit_bp
from routes.admin import admin_bp
from routes.approvals import approvals_bp

# 🔥 TAMBAHAN WAJIB
from routes.stock_opname import so_bp


SESSION_TIMEOUT = 15 * 60


# ==============================
# AUTO SUPER ADMIN
# ==============================
def ensure_super_admin(app):
    with app.app_context():
        db = get_db()

        try:
            admin_exist = db.execute("""
                SELECT id FROM users
                WHERE role IN ('super_admin','leader','admin')
                LIMIT 1
            """).fetchone()
        except Exception:
            return

        if not admin_exist:
            db.execute("""
                INSERT INTO users(username,password,role)
                VALUES (?,?,?)
            """, (
                "superadmin",
                generate_password_hash("admin123"),
                "super_admin"
            ))
            db.commit()


# ==============================
# CREATE APP
# ==============================
def create_app():

    app = Flask(__name__)
    app.config.from_object(Config)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    init_db(app.config["DATABASE"])

    app.teardown_appcontext(close_db)

    # ==========================
    # AUTH CHECK
    # ==========================
    @app.before_request
    def require_login():

        if request.endpoint is None:
            return

        if request.endpoint.startswith("static"):
            return

        if request.endpoint.startswith("auth."):
            return

        user_id = session.get("user_id")

        if not user_id:
            return redirect(url_for("auth.login", next=request.path))

        now = datetime.now(timezone.utc).timestamp()
        last_active = session.get("last_active", now)

        if now - last_active > SESSION_TIMEOUT:
            # notify user about auto-logout based on their preferences
            try:
                uid = session.get("user_id")
                if uid:
                    db = get_db()
                    user = db.execute("SELECT id, email, phone, notify_email, notify_whatsapp FROM users WHERE id=?", (uid,)).fetchone()
                    if user:
                        subj = "Sesi berakhir - Auto logout"
                        msg = f"Sesi Anda telah berakhir karena tidak aktif sejak {datetime.fromtimestamp(last_active, timezone.utc).isoformat()} UTC. Silakan login kembali jika perlu."
                        try:
                            if user["email"] and user["notify_email"]:
                                ok = send_email(user["email"], subj, msg)
                                db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                                           (user["id"], None, 'email', user["email"], subj, msg, 'sent' if ok else 'failed'))
                        except Exception:
                            try:
                                db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                                           (user["id"], None, 'email', user["email"], subj, msg, 'failed'))
                            except Exception:
                                pass

                        try:
                            if user["phone"] and user["notify_whatsapp"]:
                                ok = send_whatsapp(user["phone"], msg)
                                db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                                           (user["id"], None, 'wa', user["phone"], subj, msg, 'sent' if ok else 'failed'))
                        except Exception:
                            try:
                                db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                                           (user["id"], None, 'wa', user["phone"], subj, msg, 'failed'))
                            except Exception:
                                pass

                        try:
                            db.commit()
                        except Exception:
                            pass
            except Exception as e:
                print("AUTOLOGOUT NOTIFY ERROR:", e)

            session.clear()
            flash("Session expired, silakan login kembali", "error")
            return redirect(url_for("auth.login"))

        session["last_active"] = now

    # ==========================
    # ERROR HANDLER
    # ==========================
    @app.errorhandler(500)
    def internal_error(e):
        return "Terjadi kesalahan pada server", 500

    @app.errorhandler(404)
    def not_found(e):
        return "Halaman tidak ditemukan", 404

    @app.errorhandler(403)
    def forbidden(e):
        return "Akses ditolak", 403

    # ==========================
    # REGISTER BP
    # ==========================
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(request_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(inbound_bp)
    app.register_blueprint(outbound_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(approvals_bp)

    # 🔥 TAMBAHAN WAJIB
    app.register_blueprint(so_bp)

    ensure_super_admin(app)

    return app


# ==============================
# RUN
# ==============================
if __name__ == "__main__":

    app = create_app()

    app.run(
        debug=Config.DEBUG,
        host="0.0.0.0",
        port=5001
    )
