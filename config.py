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


def _int_env(name, default=0):
    raw_value = os.getenv(name)
    if raw_value is None:
        return int(default)
    try:
        return int(str(raw_value).strip())
    except (TypeError, ValueError):
        return int(default)


def _first_env_value(*names, default=""):
    for name in names:
        raw_value = os.getenv(name)
        if raw_value is None:
            continue
        normalized = str(raw_value).strip()
        if normalized:
            return normalized
    return str(default).strip()


def _load_or_create_secret_key():
    env_secret = (os.getenv("SECRET_KEY") or "").strip()
    if env_secret:
        return env_secret

    key_path = os.getenv(
        "SECRET_KEY_PATH",
        os.path.join(BASE_DIR, "instance", "secret_key.txt"),
    )

    try:
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        if os.path.exists(key_path):
            with open(key_path, "r", encoding="utf-8") as file_handle:
                persisted_key = file_handle.read().strip()
            if persisted_key:
                return persisted_key

        generated_key = secrets.token_hex(32)
        with open(key_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(generated_key)
        return generated_key
    except Exception:
        return secrets.token_hex(32)


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
SECRET_KEY_DEFAULT = _load_or_create_secret_key()


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
    SECRET_KEY = SECRET_KEY_DEFAULT

    SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "wms_session")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Cookie session akan otomatis ditandai Secure saat request datang lewat HTTPS.
    # Nilai config ini tetap bisa dipaksa aktif via SESSION_COOKIE_SECURE=1.
    SESSION_COOKIE_SECURE = _env_flag("SESSION_COOKIE_SECURE", False)
    SESSION_REFRESH_EACH_REQUEST = False
    PREFERRED_URL_SCHEME = os.getenv(
        "PREFERRED_URL_SCHEME",
        "https" if IS_PRODUCTION else "http",
    )
    PROXY_FIX_X_PROTO = _int_env("PROXY_FIX_X_PROTO", 1)
    PROXY_FIX_X_HOST = _int_env("PROXY_FIX_X_HOST", 1 if IS_PRODUCTION else 0)
    ALLOWED_HOSTS = _csv_env("ALLOWED_HOSTS", "")
    CANONICAL_HOST = (os.getenv("CANONICAL_HOST") or "").strip()
    CANONICAL_SCHEME = (
        (os.getenv("CANONICAL_SCHEME") or PREFERRED_URL_SCHEME or "https")
        .strip()
        .lower()
    )
    ENFORCE_SAME_ORIGIN_POSTS = _env_flag("ENFORCE_SAME_ORIGIN_POSTS", True)
    ENFORCE_SAME_ORIGIN_POSTS_DURING_TESTS = _env_flag(
        "ENFORCE_SAME_ORIGIN_POSTS_DURING_TESTS",
        False,
    )

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
    MEETING_PROVIDER = (os.getenv("MEETING_PROVIDER") or "jitsi").strip().lower()
    JITSI_MEETING_DOMAIN = (os.getenv("JITSI_MEETING_DOMAIN") or "meet.jit.si").strip()
    JITSI_ROOM_PREFIX = (os.getenv("JITSI_ROOM_PREFIX") or "erp-bjas").strip()
    JITSI_ROOM_MAX_PARTICIPANTS = int(os.getenv("JITSI_ROOM_MAX_PARTICIPANTS", "10"))
    MEETING_DEFAULT_LANGUAGE = (os.getenv("MEETING_DEFAULT_LANGUAGE") or "id-ID").strip()
    ZOOM_MEETING_SDK_KEY = _first_env_value(
        "ZOOM_MEETING_SDK_KEY",
        "CLIENT_ID",
        "ZOOM_CLIENT_ID",
        "ZOOM_SDK_KEY",
        "ZOOM_SDK_CLIENT_ID",
    )
    ZOOM_MEETING_SDK_SECRET = _first_env_value(
        "ZOOM_MEETING_SDK_SECRET",
        "CLIENT_SECRET",
        "ZOOM_CLIENT_SECRET",
        "ZOOM_SDK_SECRET",
    )
    ZOOM_MEETING_SDK_VERSION = (os.getenv("ZOOM_MEETING_SDK_VERSION") or "5.1.4").strip()
    ZOOM_MEETING_WEB_ENDPOINT = (os.getenv("ZOOM_MEETING_WEB_ENDPOINT") or "zoom.us").strip()
    ZOOM_MEETING_DEFAULT_LANGUAGE = (os.getenv("ZOOM_MEETING_DEFAULT_LANGUAGE") or "id-ID").strip()
    ZOOM_MEETING_SIGNATURE_TTL_SECONDS = int(
        os.getenv("ZOOM_MEETING_SIGNATURE_TTL_SECONDS", str(2 * 60 * 60))
    )
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
    SQLITE_JOURNAL_MODE = (os.getenv("SQLITE_JOURNAL_MODE") or "WAL").strip().upper()
    SQLITE_SYNCHRONOUS = (
        (os.getenv("SQLITE_SYNCHRONOUS") or ("FULL" if IS_PRODUCTION else "NORMAL"))
        .strip()
        .upper()
    )
    SQLITE_BUSY_TIMEOUT_MS = _int_env("SQLITE_BUSY_TIMEOUT_MS", 30000)
    SQLITE_TEMP_STORE = (os.getenv("SQLITE_TEMP_STORE") or "MEMORY").strip().upper()
    SQLITE_FOREIGN_KEYS = _env_flag("SQLITE_FOREIGN_KEYS", True)

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
