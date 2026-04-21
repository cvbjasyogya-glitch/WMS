import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from database import get_db
from services.career_service import ensure_career_schema
from services.hris_catalog import can_manage_hris_module
from services.rbac import normalize_role


TABLES_TO_CHECK = (
    "career_openings",
    "recruitment_candidates",
    "career_public_accounts",
    "career_public_account_requests",
    "users",
    "warehouses",
)


def _as_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _masked_database_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw or "@" not in raw or "://" not in raw:
        return raw
    scheme, remainder = raw.split("://", 1)
    credentials, host_part = remainder.split("@", 1)
    if ":" not in credentials:
        return f"{scheme}://***@{host_part}"
    username, _password = credentials.split(":", 1)
    return f"{scheme}://{username}:***@{host_part}"


def _table_check(db, table_name: str) -> dict:
    try:
        row = db.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "row_count": _as_int(row[0] if row else 0)}


def _route_check(client, host: str, path: str) -> dict:
    response = client.get(path, base_url=f"https://{host}", follow_redirects=False)
    return {
        "status_code": response.status_code,
        "location": response.headers.get("Location") or "",
    }


def main() -> int:
    app = create_app()
    payload = {
        "status": "ok",
        "config": {},
        "routes": {},
        "tables": {},
        "hr_recruitment_users": {},
        "warnings": [],
        "failures": [],
    }

    recruitment_hosts = [str(item or "").strip() for item in (app.config.get("RECRUITMENT_PUBLIC_HOSTS") or []) if str(item or "").strip()]
    sms_hosts = [str(item or "").strip() for item in (app.config.get("SMS_PUBLIC_HOSTS") or []) if str(item or "").strip()]
    recruitment_host = recruitment_hosts[0] if recruitment_hosts else ""

    payload["config"] = {
        "database_backend": app.config.get("DATABASE_BACKEND"),
        "database_url_masked": _masked_database_url(app.config.get("DATABASE_URL") or ""),
        "canonical_host": str(app.config.get("CANONICAL_HOST") or "").strip(),
        "recruitment_hosts": recruitment_hosts,
        "sms_hosts": sms_hosts,
        "session_cookie_domain": str(app.config.get("SESSION_COOKIE_DOMAIN") or "").strip(),
        "recruitment_session_cookie_name": str(app.config.get("RECRUITMENT_SESSION_COOKIE_NAME") or "").strip(),
        "session_cookie_secure": bool(app.config.get("SESSION_COOKIE_SECURE")),
        "service_worker_enabled": bool(app.config.get("SERVICE_WORKER_ENABLED")),
        "smtp_host": str(os.getenv("SMTP_HOST") or "").strip(),
        "smtp_user_present": bool(str(os.getenv("SMTP_USER") or "").strip()),
        "smtp_pass_present": bool(str(os.getenv("SMTP_PASS") or "").strip()),
        "smtp_from_email": str(os.getenv("SMTP_FROM_EMAIL") or "").strip(),
    }

    if not recruitment_host:
        payload["failures"].append("RECRUITMENT_PUBLIC_HOSTS belum diisi.")
    if not payload["config"]["canonical_host"]:
        payload["failures"].append("CANONICAL_HOST belum diisi.")
    if not payload["config"]["recruitment_session_cookie_name"]:
        payload["failures"].append("RECRUITMENT_SESSION_COOKIE_NAME belum diisi.")
    if not payload["config"]["session_cookie_secure"]:
        payload["warnings"].append("SESSION_COOKIE_SECURE belum aktif. Di VPS production sebaiknya diisi 1.")
    if sms_hosts and not payload["config"]["session_cookie_domain"]:
        payload["warnings"].append("SESSION_COOKIE_DOMAIN belum diisi, jadi SSO ERP-SMS tidak akan berbagi login lintas subdomain.")
    if not payload["config"]["smtp_host"] or not payload["config"]["smtp_user_present"] or not payload["config"]["smtp_pass_present"]:
        payload["warnings"].append("Konfigurasi SMTP belum lengkap. Email verifikasi akun dan email kode tes recruitment bisa gagal terkirim.")
    if payload["config"]["service_worker_enabled"]:
        payload["warnings"].append("SERVICE_WORKER_ENABLED masih aktif. Untuk deployment ERP saat ini lebih aman dimatikan agar tidak memicu auto refresh.")

    with app.app_context():
        db = get_db()
        ensure_career_schema(db)
        for table_name in TABLES_TO_CHECK:
            payload["tables"][table_name] = _table_check(db, table_name)

        hr_users = []
        try:
            rows = db.execute("SELECT id, username, role FROM users ORDER BY id DESC").fetchall()
        except Exception as exc:
            payload["hr_recruitment_users"] = {"ok": False, "error": str(exc)}
        else:
            for row in rows:
                user = dict(row)
                normalized_role = normalize_role(user.get("role"))
                if can_manage_hris_module(normalized_role, "recruitment"):
                    hr_users.append(
                        {
                            "id": _as_int(user.get("id")),
                            "username": user.get("username"),
                            "role": user.get("role"),
                        }
                    )
            payload["hr_recruitment_users"] = {
                "ok": True,
                "count": len(hr_users),
                "sample": hr_users[:10],
            }
            if not hr_users:
                payload["warnings"].append("Belum ada user yang punya akses modul recruitment. Arsip kandidat ke SMS HR dan review HRIS tidak akan terlihat ke siapa pun.")

    if recruitment_host:
        with app.test_client() as client:
            payload["routes"]["root"] = _route_check(client, recruitment_host, "/")
            payload["routes"]["signin"] = _route_check(client, recruitment_host, "/signin")
            payload["routes"]["beranda"] = _route_check(client, recruitment_host, "/beranda")
            payload["routes"]["assessment_entry"] = _route_check(client, recruitment_host, "/karir/tes")

        if payload["routes"]["root"]["status_code"] not in {301, 302, 307, 308} or "/signin" not in payload["routes"]["root"]["location"]:
            payload["failures"].append("Route / pada host recruitment belum mengarah ke /signin.")
        if payload["routes"]["signin"]["status_code"] != 200:
            payload["failures"].append("Route /signin pada host recruitment tidak mengembalikan 200.")
        if payload["routes"]["beranda"]["status_code"] not in {301, 302, 307, 308} or "/signin" not in payload["routes"]["beranda"]["location"]:
            payload["failures"].append("Route /beranda untuk guest pada host recruitment belum diarahkan ke /signin.")
        if payload["routes"]["assessment_entry"]["status_code"] != 200:
            payload["failures"].append("Route /karir/tes pada host recruitment tidak mengembalikan 200.")

    payload["status"] = "ok" if not payload["failures"] else "failed"
    print(json.dumps(payload, indent=2))
    return 0 if not payload["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
