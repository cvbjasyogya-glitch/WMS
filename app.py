import os
from uuid import uuid4
from urllib.parse import urlsplit

from flask import Flask, session, redirect, url_for, request, flash, g, jsonify, current_app
from flask.sessions import SecureCookieSessionInterface
from config import Config
from database import close_db, get_db
from datetime import datetime, timezone
from services.notification_service import send_email, send_whatsapp
from services.rbac import has_permission, is_scoped_role, normalize_role
from werkzeug.security import generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import RequestEntityTooLarge
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
from routes.hris import hris_bp
from routes.schedule import schedule_bp
from routes.crm import crm_bp
from routes.product_lookup import product_lookup_bp
from routes.chat import chat_bp
from routes.attendance_portal import attendance_portal_bp
from routes.daily_report_portal import daily_report_portal_bp
from routes.leave_portal import leave_portal_bp
from routes.account import account_bp
from routes.announcement_center import announcement_center_bp
from routes.meetings import meetings_bp
from routes.notifications import notifications_bp

# ðŸ”¥ TAMBAHAN WAJIB
from routes.stock_opname import so_bp
from services.hris_catalog import (
    can_manage_hris_module,
    can_view_hris_module,
    get_hris_navigation_modules,
    get_hris_modules,
    is_self_service_hris_module,
    role_can_see_hris_navigation,
)


SESSION_TIMEOUT = int(getattr(Config, "PERMANENT_SESSION_LIFETIME").total_seconds())


def _normalized_restore_usernames(raw_value):
    if isinstance(raw_value, str):
        items = raw_value.split(",")
    else:
        items = raw_value or []
    return [
        str(item).strip()
        for item in items
        if str(item).strip()
    ]


def _build_security_headers():
    meeting_domain = (current_app.config.get("JITSI_MEETING_DOMAIN") or "meet.jit.si").strip()
    meeting_origin = f"https://{meeting_domain}" if meeting_domain else "https://meet.jit.si"
    return {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(self), geolocation=(self), microphone=(self), interest-cohort=()",
        "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Origin-Agent-Cluster": "?1",
        "X-Permitted-Cross-Domain-Policies": "none",
        "Content-Security-Policy": (
            f"default-src 'self' data: blob: https://source.zoom.us {meeting_origin}; "
            f"img-src 'self' data: blob: https://source.zoom.us https://*.zoom.us {meeting_origin}; "
            f"media-src 'self' data: blob: https://*.zoom.us {meeting_origin}; "
            f"style-src 'self' 'unsafe-inline' https://source.zoom.us https://fonts.googleapis.com {meeting_origin}; "
            f"script-src 'self' 'unsafe-inline' https://source.zoom.us {meeting_origin}; "
            f"font-src 'self' data: https://source.zoom.us https://fonts.gstatic.com {meeting_origin}; "
            f"connect-src 'self' blob: https://source.zoom.us https://*.zoom.us wss://*.zoom.us {meeting_origin} wss://*.jit.si; "
            f"frame-src 'self' https://*.zoom.us {meeting_origin}; "
            "worker-src 'self' blob:; "
            "frame-ancestors 'self'; "
            "base-uri 'self'; "
            "form-action 'self'"
        ),
    }


class RequestAwareSessionInterface(SecureCookieSessionInterface):
    def get_cookie_secure(self, app):
        return bool(app.config.get("SESSION_COOKIE_SECURE")) or request.is_secure


def _first_forwarded_value(raw_value):
    return str(raw_value or "").split(",", 1)[0].strip()


def _normalized_host_name(raw_value):
    candidate = str(raw_value or "").strip()
    if not candidate:
        return ""

    if "://" in candidate:
        parsed = urlsplit(candidate)
        return (parsed.hostname or "").strip().lower().rstrip(".")

    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1:candidate.index("]")]
    else:
        candidate = candidate.split(":", 1)[0]

    return candidate.strip().lower().rstrip(".")


def _normalized_port(scheme, port):
    if port is not None:
        try:
            return int(port)
        except (TypeError, ValueError):
            pass
    return 443 if str(scheme or "").lower() == "https" else 80


def _split_host_port(raw_host):
    candidate = str(raw_host or "").strip()
    if not candidate:
        return "", None

    parsed = urlsplit(f"//{candidate}")
    return _normalized_host_name(parsed.hostname or candidate), parsed.port


def _request_origin_signatures():
    signatures = set()

    request_host_name, request_host_port = _split_host_port(request.host)
    request_scheme = str(request.scheme or "").strip().lower() or "http"
    if request_host_name:
        signatures.add(
            (
                request_scheme,
                request_host_name,
                _normalized_port(request_scheme, request_host_port),
            )
        )

    forwarded_proto = _first_forwarded_value(request.headers.get("X-Forwarded-Proto"))
    forwarded_host = _first_forwarded_value(
        request.headers.get("X-Forwarded-Host") or request.headers.get("Host")
    )
    forwarded_port = _first_forwarded_value(request.headers.get("X-Forwarded-Port"))

    if forwarded_proto and forwarded_host:
        forwarded_host_name, forwarded_host_port = _split_host_port(forwarded_host)
        if forwarded_host_name:
            signatures.add(
                (
                    forwarded_proto.lower(),
                    forwarded_host_name,
                    _normalized_port(
                        forwarded_proto.lower(),
                        forwarded_port or forwarded_host_port,
                    ),
                )
            )

    return signatures


def _is_same_origin_url(candidate_url):
    candidate = str(candidate_url or "").strip()
    if not candidate:
        return False

    parsed_candidate = urlsplit(candidate)
    if not parsed_candidate.scheme or not parsed_candidate.hostname:
        return False

    candidate_signature = (
        parsed_candidate.scheme.lower(),
        _normalized_host_name(parsed_candidate.hostname or ""),
        _normalized_port(parsed_candidate.scheme, parsed_candidate.port),
    )
    request_signatures = _request_origin_signatures()

    if candidate_signature in request_signatures:
        return True

    candidate_scheme, candidate_host, candidate_port = candidate_signature
    if candidate_scheme not in {"http", "https"}:
        return False

    for request_scheme, request_host, request_port in request_signatures:
        # Allow same host across HTTP/HTTPS boundary for reverse-proxy TLS termination.
        if (
            request_host == candidate_host
            and request_scheme in {"http", "https"}
            and candidate_port == _normalized_port(candidate_scheme, None)
            and request_port == _normalized_port(request_scheme, None)
        ):
            return True

    return False


def _is_allowed_host(candidate_host, allowed_hosts):
    normalized_candidate = _normalized_host_name(candidate_host)
    if not normalized_candidate:
        return False

    normalized_allowed = [
        str(item).strip().lower()
        for item in (allowed_hosts or [])
        if str(item).strip()
    ]
    if not normalized_allowed:
        return True

    for allowed_host in normalized_allowed:
        if allowed_host.startswith("."):
            suffix = allowed_host[1:].strip().lower().rstrip(".")
            if normalized_candidate == suffix or normalized_candidate.endswith(f".{suffix}"):
                return True
            continue

        if normalized_candidate == _normalized_host_name(allowed_host):
            return True

    return False


def _canonical_request_location(app):
    canonical_host_name, canonical_host_port = _split_host_port(
        app.config.get("CANONICAL_HOST")
    )
    if not canonical_host_name:
        return ""

    canonical_scheme = (
        str(app.config.get("CANONICAL_SCHEME") or request.scheme or "https")
        .strip()
        .lower()
        or "https"
    )
    request_host_name, request_host_port = _split_host_port(request.host)
    request_scheme = str(request.scheme or "http").strip().lower() or "http"

    if (
        request_host_name == canonical_host_name
        and _normalized_port(request_scheme, request_host_port)
        == _normalized_port(canonical_scheme, canonical_host_port)
    ):
        return ""

    display_host = canonical_host_name
    default_port = _normalized_port(canonical_scheme, None)
    if canonical_host_port not in (None, default_port):
        display_host = f"{display_host}:{canonical_host_port}"

    target_path = request.full_path if request.query_string else request.path
    if target_path.endswith("?"):
        target_path = target_path[:-1]
    if not target_path.startswith("/"):
        target_path = f"/{target_path}"

    return f"{canonical_scheme}://{display_host}{target_path or '/'}"


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


def repair_restored_data(app):
    with app.app_context():
        db = get_db()

        warehouses = db.execute(
            "SELECT id FROM warehouses ORDER BY id"
        ).fetchall()
        if not warehouses:
            return

        default_warehouse_id = warehouses[0]["id"]
        valid_warehouse_ids = {row["id"] for row in warehouses}
        super_admin_usernames = _normalized_restore_usernames(
            app.config.get("RESTORE_SUPER_ADMINS", [])
        )
        bootstrap_admin_usernames = _normalized_restore_usernames(
            app.config.get("RESTORE_BOOTSTRAP_ADMINS", [])
        )
        bootstrap_leader_usernames = _normalized_restore_usernames(
            app.config.get("RESTORE_BOOTSTRAP_LEADERS", [])
        )
        protected_super_admins = {username.lower() for username in super_admin_usernames}

        try:
            scoped_users = db.execute(
                """
                SELECT id, warehouse_id
                FROM users
                WHERE role IN ('leader', 'admin', 'staff')
                """
            ).fetchall()

            for user in scoped_users:
                if user["warehouse_id"] not in valid_warehouse_ids:
                    db.execute(
                        "UPDATE users SET warehouse_id=? WHERE id=?",
                        (default_warehouse_id, user["id"]),
                    )

            db.execute(
                "UPDATE users SET notify_email=1 WHERE notify_email IS NULL"
            )
            db.execute(
                "UPDATE users SET notify_whatsapp=0 WHERE notify_whatsapp IS NULL"
            )
            db.execute(
                "UPDATE users SET chat_sound_volume=? WHERE chat_sound_volume IS NULL",
                (float(app.config.get("CHAT_SOUND_VOLUME_DEFAULT", 0.85)),),
            )

            for username in super_admin_usernames:
                db.execute(
                    """
                    UPDATE users
                    SET role='super_admin', warehouse_id=NULL
                    WHERE lower(username)=lower(?)
                    """,
                    (username,),
                )

            for username in bootstrap_admin_usernames:
                if username.lower() in protected_super_admins:
                    continue
                db.execute(
                    """
                    UPDATE users
                    SET role='admin', warehouse_id=?
                    WHERE lower(username)=lower(?)
                    """,
                    (default_warehouse_id, username),
                )

            for username in bootstrap_leader_usernames:
                if username.lower() in protected_super_admins:
                    continue
                db.execute(
                    """
                    UPDATE users
                    SET role='leader', warehouse_id=?
                    WHERE lower(username)=lower(?)
                    """,
                    (default_warehouse_id, username),
                )

            db.execute(
                """
                UPDATE stock_batches
                SET remaining_qty = qty
                WHERE remaining_qty IS NULL
                """
            )

            db.execute(
                """
                INSERT INTO stock_batches(
                    product_id,
                    variant_id,
                    warehouse_id,
                    qty,
                    remaining_qty,
                    cost,
                    created_at
                )
                SELECT
                    s.product_id,
                    s.variant_id,
                    s.warehouse_id,
                    s.qty,
                    s.qty,
                    0,
                    datetime('now')
                FROM stock s
                WHERE COALESCE(s.qty, 0) > 0
                  AND NOT EXISTS (
                      SELECT 1
                      FROM stock_batches b
                      WHERE b.product_id = s.product_id
                        AND b.variant_id = s.variant_id
                        AND b.warehouse_id = s.warehouse_id
                        AND COALESCE(b.remaining_qty, 0) > 0
                  )
                """
            )

            db.execute(
                """
                INSERT INTO stock(product_id, variant_id, warehouse_id, qty)
                SELECT
                    product_id,
                    variant_id,
                    warehouse_id,
                    COALESCE(SUM(remaining_qty), 0)
                FROM stock_batches
                GROUP BY product_id, variant_id, warehouse_id
                ON CONFLICT(product_id, variant_id, warehouse_id)
                DO UPDATE SET qty = excluded.qty
                """
            )

            db.commit()
        except Exception as e:
            db.rollback()
            print("RESTORE REPAIR ERROR:", e)


def seed_request_notification_cursor(db):
    role = session.get("role")
    warehouse_id = session.get("warehouse_id")

    if is_scoped_role(role) and warehouse_id:
        row = db.execute(
            """
            SELECT COALESCE(MAX(id), 0)
            FROM requests
            WHERE from_warehouse=? OR to_warehouse=?
            """,
            (warehouse_id, warehouse_id),
        ).fetchone()
    else:
        row = db.execute(
            "SELECT COALESCE(MAX(id), 0) FROM requests"
        ).fetchone()

    session["request_last_seen_id"] = row[0] if row else 0


# ==============================
# CREATE APP
# ==============================
def create_app():

    app = Flask(__name__)
    app.config.from_object(Config)
    app.config.setdefault(
        "BIOMETRIC_PHOTO_UPLOAD_FOLDER",
        os.path.join(app.root_path, "static", "uploads", "geotag"),
    )
    app.config.setdefault("BIOMETRIC_PHOTO_URL_PREFIX", "/static/uploads/geotag")
    app.config.setdefault(
        "CHAT_UPLOAD_FOLDER",
        os.path.join(app.root_path, "static", "uploads", "chat"),
    )
    app.config.setdefault("CHAT_UPLOAD_URL_PREFIX", "/static/uploads/chat")
    app.config.setdefault(
        "DAILY_LIVE_REPORT_UPLOAD_FOLDER",
        os.path.join(app.root_path, "static", "uploads", "daily_reports"),
    )
    app.config.setdefault("DAILY_LIVE_REPORT_UPLOAD_URL_PREFIX", "/static/uploads/daily_reports")
    app.config.setdefault("DAILY_LIVE_REPORT_ATTACHMENT_MAX_BYTES", 10 * 1024 * 1024)
    app.config.setdefault(
        "DOCUMENT_RECORD_UPLOAD_FOLDER",
        os.path.join(app.root_path, "static", "uploads", "documents"),
    )
    app.config.setdefault("DOCUMENT_RECORD_UPLOAD_URL_PREFIX", "/static/uploads/documents")
    app.config.setdefault("DOCUMENT_RECORD_ATTACHMENT_MAX_BYTES", 15 * 1024 * 1024)
    app.config.setdefault(
        "DOCUMENT_RECORD_SIGNATURE_FOLDER",
        os.path.join(app.root_path, "static", "uploads", "document_signatures"),
    )
    app.config.setdefault(
        "DOCUMENT_RECORD_SIGNATURE_URL_PREFIX",
        "/static/uploads/document_signatures",
    )
    app.config.setdefault("DOCUMENT_RECORD_SIGNATURE_MAX_BYTES", 2 * 1024 * 1024)

    app.session_interface = RequestAwareSessionInterface()
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_proto=max(0, int(app.config.get("PROXY_FIX_X_PROTO", 1))),
        x_host=max(0, int(app.config.get("PROXY_FIX_X_HOST", 0))),
    )
    init_db(app.config["DATABASE"])

    app.teardown_appcontext(close_db)

    @app.before_request
    def attach_request_context():
        request_id_header = app.config.get("REQUEST_ID_HEADER", "X-Request-ID")
        g.request_id = (
            (request.headers.get(request_id_header) or "").strip()
            or uuid4().hex
        )

    @app.before_request
    def enforce_canonical_host():
        canonical_location = _canonical_request_location(app)
        if not canonical_location:
            return

        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return redirect(canonical_location, code=308)

        return "Host tidak diizinkan", 400

    @app.before_request
    def enforce_allowed_hosts():
        allowed_hosts = app.config.get("ALLOWED_HOSTS") or []
        canonical_host_name = _normalized_host_name(app.config.get("CANONICAL_HOST"))
        if canonical_host_name and canonical_host_name not in {
            _normalized_host_name(item)
            for item in allowed_hosts
        }:
            allowed_hosts = list(allowed_hosts) + [canonical_host_name]
        if not allowed_hosts:
            return

        if _is_allowed_host(request.host, allowed_hosts):
            return

        return "Host tidak diizinkan", 400

    @app.before_request
    def enforce_same_origin_writes():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return

        if not app.config.get("ENFORCE_SAME_ORIGIN_POSTS", True):
            return

        if app.config.get("TESTING") and not app.config.get(
            "ENFORCE_SAME_ORIGIN_POSTS_DURING_TESTS",
            False,
        ):
            return

        origin = (request.headers.get("Origin") or "").strip()
        referer = (request.headers.get("Referer") or "").strip()

        if origin and not _is_same_origin_url(origin):
            return "Permintaan lintas situs ditolak", 403

        if not origin and referer and not _is_same_origin_url(referer):
            return "Permintaan lintas situs ditolak", 403

    @app.after_request
    def apply_response_hardening(response):
        request_id_header = app.config.get("REQUEST_ID_HEADER", "X-Request-ID")
        response.headers.setdefault(request_id_header, getattr(g, "request_id", uuid4().hex))

        for header_name, header_value in _build_security_headers().items():
            response.headers.setdefault(header_name, header_value)

        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        if (
            (request.endpoint or "").startswith("auth.")
            or (response.mimetype == "text/html" and session.get("user_id"))
        ):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"

        return response

    @app.get("/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "service": "erp-upgrade",
                "version": app.config.get("APP_VERSION"),
                "request_id": g.request_id,
            }
        )

    @app.get("/ready")
    def ready():
        try:
            db = get_db()
            db.execute("SELECT 1").fetchone()
            db.execute("SELECT COUNT(*) FROM warehouses").fetchone()
        except sqlite3.Error as exc:
            return jsonify(
                {
                    "status": "degraded",
                    "database": "error",
                    "request_id": g.request_id,
                    "detail": str(exc),
                }
            ), 503

        return jsonify(
            {
                "status": "ready",
                "database": "ok",
                "request_id": g.request_id,
                "version": app.config.get("APP_VERSION"),
            }
        )

    @app.get("/service-worker.js")
    def service_worker():
        service_worker_path = os.path.join(app.static_folder, "js", "push_service_worker.js")
        with open(service_worker_path, "r", encoding="utf-8") as file_handle:
            response = app.response_class(file_handle.read(), mimetype="application/javascript")
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Service-Worker-Allowed"] = "/"
        return response

    @app.context_processor
    def inject_permissions():
        role = session.get("role")
        return {
            "can": lambda permission: has_permission(role, permission),
            "is_scoped_user": is_scoped_role(role),
            "can_view_hris_module": lambda slug: can_view_hris_module(role, slug),
            "can_manage_hris_module": lambda slug: can_manage_hris_module(role, slug),
            "is_self_service_hris_module": lambda slug: is_self_service_hris_module(role, slug),
            "hris_modules": get_hris_modules(role),
            "sidebar_hris_modules": get_hris_navigation_modules(role),
            "show_hris_navigation": role_can_see_hris_navigation(role),
        }

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

        if request.endpoint in {"health", "ready", "service_worker"}:
            return

        user_id = session.get("user_id")

        if not user_id:
            next_target = request.full_path if request.query_string else request.path
            if next_target.endswith("?"):
                next_target = next_target[:-1]
            return redirect(url_for("auth.login", next=next_target))

        db = get_db()
        user = db.execute(
            "SELECT id, username, role, warehouse_id, employee_id, chat_sound_volume FROM users WHERE id=?",
            (user_id,),
        ).fetchone()

        if not user:
            session.clear()
            flash("User tidak ditemukan, silakan login kembali", "error")
            return redirect(url_for("auth.login"))

        normalized_role = normalize_role(user["role"])
        session["username"] = user["username"]
        session["role"] = normalized_role
        session["employee_id"] = user["employee_id"]
        session["chat_sound_volume"] = float(
            user["chat_sound_volume"]
            if user["chat_sound_volume"] is not None
            else app.config.get("CHAT_SOUND_VOLUME_DEFAULT", 0.85)
        )

        if is_scoped_role(normalized_role):
            session["warehouse_id"] = user["warehouse_id"] or 1
        elif not session.get("warehouse_id"):
            warehouse = db.execute(
                "SELECT id FROM warehouses ORDER BY id LIMIT 1"
            ).fetchone()
            session["warehouse_id"] = warehouse["id"] if warehouse else 1

        if "request_last_seen_id" not in session:
            seed_request_notification_cursor(db)

        now = datetime.now(timezone.utc).timestamp()
        last_active = session.get("last_active", now)

        if now - last_active > SESSION_TIMEOUT:
            # notify user about auto-logout based on their preferences
            try:
                uid = session.get("user_id")
                if uid:
                    user = db.execute("SELECT id, email, phone, notify_email, notify_whatsapp FROM users WHERE id=?", (uid,)).fetchone()
                    if user:
                        subj = "Sesi berakhir - Auto logout"
                        msg = f"Sesi Anda telah berakhir karena tidak aktif sejak {datetime.fromtimestamp(last_active, timezone.utc).isoformat()} UTC. Silakan login kembali jika perlu."
                        try:
                            if user["email"] and user["notify_email"]:
                                ok = send_email(user["email"], subj, msg)
                                status = "skipped" if ok is None else ("sent" if ok else "failed")
                                db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                                           (user["id"], None, 'email', user["email"], subj, msg, status))
                        except Exception:
                            try:
                                db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                                           (user["id"], None, 'email', user["email"], subj, msg, 'failed'))
                            except Exception:
                                pass

                        try:
                            if user["phone"] and user["notify_whatsapp"]:
                                ok = send_whatsapp(user["phone"], msg)
                                status = "skipped" if ok is None else ("sent" if ok else "failed")
                                db.execute("INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status) VALUES (?,?,?,?,?,?,?)",
                                           (user["id"], None, 'wa', user["phone"], subj, msg, status))
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

    @app.errorhandler(RequestEntityTooLarge)
    def request_too_large(e):
        if request.path.startswith("/absen"):
            flash(
                "Ukuran foto absen terlalu besar. Ambil ulang foto atau pakai kamera perangkat supaya file lebih kecil.",
                "error",
            )
            return redirect("/absen/")

        if request.path.startswith("/hris/biometric"):
            flash(
                "Ukuran foto geotag terlalu besar. Ambil ulang foto dengan ukuran lebih kecil lalu simpan lagi.",
                "error",
            )
            return redirect("/hris/biometric")

        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"ok": False, "message": "Ukuran data yang dikirim terlalu besar"}), 413

        return "Ukuran data yang dikirim terlalu besar", 413

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
    app.register_blueprint(hris_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(crm_bp)
    app.register_blueprint(product_lookup_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(attendance_portal_bp)
    app.register_blueprint(daily_report_portal_bp)
    app.register_blueprint(leave_portal_bp)
    app.register_blueprint(meetings_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(announcement_center_bp)
    app.register_blueprint(notifications_bp)

    # ðŸ”¥ TAMBAHAN WAJIB
    app.register_blueprint(so_bp)

    ensure_super_admin(app)
    repair_restored_data(app)

    return app


app = create_app()
application = app


# ==============================
# RUN
# ==============================
if __name__ == "__main__":
    app.run(
        debug=Config.DEBUG,
        host="0.0.0.0",
        port=5001
    )
