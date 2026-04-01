import base64
import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

try:
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid
except ImportError:
    serialization = None
    Vapid = None


def _csv_env(name, default=""):
    raw_value = os.getenv(name)
    source = raw_value if raw_value is not None else default
    return [
        item.strip()
        for item in str(source).split(",")
        if item and item.strip()
    ]


def _env_flag(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return bool(default)
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _encode_vapid_public_key(public_key):
    raw_key = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(raw_key).rstrip(b"=").decode("ascii")


def _load_or_create_webpush_keys():
    env_public = (os.getenv("WEBPUSH_PUBLIC_KEY") or "").strip()
    env_private = (os.getenv("WEBPUSH_PRIVATE_KEY") or "").strip()
    if env_public and env_private:
        return env_public, env_private

    if Vapid is None or serialization is None:
        return env_public, env_private

    key_path = os.getenv(
        "WEBPUSH_PRIVATE_KEY_PATH",
        os.path.join(BASE_DIR, "instance", "webpush_private.pem"),
    )

    try:
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        if os.path.exists(key_path):
            vapid = Vapid.from_file(key_path)
        else:
            vapid = Vapid()
            vapid.generate_keys()
            private_bytes = vapid.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            with open(key_path, "wb") as file_handle:
                file_handle.write(private_bytes)
        return _encode_vapid_public_key(vapid.public_key), key_path
    except Exception:
        return env_public, env_private


WEBPUSH_PUBLIC_KEY_DEFAULT, WEBPUSH_PRIVATE_KEY_DEFAULT = _load_or_create_webpush_keys()


class Config:

    # ==========================
    # ENVIRONMENT
    # ==========================
    ENV = os.getenv("FLASK_ENV", "production")
    DEBUG = ENV == "development"
    IS_PRODUCTION = ENV == "production"

    # ==========================
    # SECURITY
    # ==========================
    SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Default dibuat aman untuk akses lokal/non-HTTPS agar session login tidak hilang.
    # Aktifkan explicit via SESSION_COOKIE_SECURE=1 saat deploy di HTTPS.
    SESSION_COOKIE_SECURE = _env_flag("SESSION_COOKIE_SECURE", False)

    PERMANENT_SESSION_LIFETIME = timedelta(hours=1)
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(12 * 1024 * 1024)))
    CHAT_ATTACHMENT_MAX_BYTES = int(os.getenv("CHAT_ATTACHMENT_MAX_BYTES", str(10 * 1024 * 1024)))
    CHAT_SOUND_VOLUME_DEFAULT = float(os.getenv("CHAT_SOUND_VOLUME_DEFAULT", "0.85"))
    CHAT_WEBRTC_ICE_SERVERS = [
        {
            "urls": [
                "stun:stun.l.google.com:19302",
                "stun:stun1.l.google.com:19302",
            ]
        }
    ]
    WEBPUSH_PUBLIC_KEY = WEBPUSH_PUBLIC_KEY_DEFAULT
    WEBPUSH_PRIVATE_KEY = WEBPUSH_PRIVATE_KEY_DEFAULT
    WEBPUSH_SUBJECT = os.getenv("WEBPUSH_SUBJECT", "mailto:admin@example.com")
    PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))
    PASSWORD_RESET_TTL_MINUTES = int(os.getenv("PASSWORD_RESET_TTL_MINUTES", "15"))
    LOGIN_THROTTLE_LIMIT = int(os.getenv("LOGIN_THROTTLE_LIMIT", "5"))
    LOGIN_THROTTLE_WINDOW_SECONDS = int(os.getenv("LOGIN_THROTTLE_WINDOW_SECONDS", "300"))
    REQUEST_ID_HEADER = "X-Request-ID"
    APP_VERSION = os.getenv("APP_VERSION", "2026.03.31")

    RESTORE_SUPER_ADMINS = _csv_env(
        "RESTORE_SUPER_ADMINS",
        "Rio,superadmin,akmalyk21",
    )
    RESTORE_BOOTSTRAP_ADMINS = _csv_env(
        "RESTORE_BOOTSTRAP_ADMINS",
        "admin",
    )
    RESTORE_BOOTSTRAP_LEADERS = _csv_env(
        "RESTORE_BOOTSTRAP_LEADERS",
        "leader",
    )

    # ==========================
    # DATABASE (SINGLE SOURCE)
    # ==========================
    DATABASE = os.getenv(
        "DATABASE_PATH",
        os.path.join(BASE_DIR, "database.db")
    )

    # ==========================
    # PAGINATION
    # ==========================
    PRODUCTS_PER_PAGE = 50

    # ==========================
    # STOCK
    # ==========================
    MIN_STOCK_ALERT = int(os.getenv("MIN_STOCK_ALERT", 10))

    # ==========================
    # SEARCH
    # ==========================
    SEARCH_LIMIT = int(os.getenv("SEARCH_LIMIT", 20))

    # ==========================
    # CHART
    # ==========================
    CHART_DAYS = int(os.getenv("CHART_DAYS", 7))
