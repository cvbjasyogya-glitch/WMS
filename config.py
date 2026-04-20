import base64
import json
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


def _load_optional_json(path):
    candidate = str(path or "").strip()
    if not candidate or not os.path.exists(candidate):
        return {}

    try:
        with open(candidate, "r", encoding="utf-8") as file_handle:
            payload = json.load(file_handle)
    except Exception:
        return {}

    return payload if isinstance(payload, dict) else {}


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
MEETING_LOCAL_CONFIG = _load_optional_json(
    os.getenv(
        "MEETING_LOCAL_CONFIG_PATH",
        os.path.join(BASE_DIR, "instance", "meeting_jaas.json"),
    )
)


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
    SESSION_COOKIE_DOMAIN = (os.getenv("SESSION_COOKIE_DOMAIN") or "").strip() or None
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
    RECRUITMENT_PUBLIC_HOSTS = _csv_env("RECRUITMENT_PUBLIC_HOSTS", "")
    SMS_PUBLIC_HOSTS = _csv_env("SMS_PUBLIC_HOSTS", "")
    CANONICAL_HOST = (os.getenv("CANONICAL_HOST") or "").strip()
    CANONICAL_SCHEME = (
        (os.getenv("CANONICAL_SCHEME") or PREFERRED_URL_SCHEME or "https")
        .strip()
        .lower()
    )
    PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    STORE_NAME = (os.getenv("STORE_NAME") or "CV BERKAH JAYA ABADI SPORTS").strip()
    STORE_PHONE = (os.getenv("STORE_PHONE") or "").strip()
    POS_RECEIPT_ADDRESS = (os.getenv("POS_RECEIPT_ADDRESS") or "").strip()
    POS_RECEIPT_ADDRESS_MATARAM = (os.getenv("POS_RECEIPT_ADDRESS_MATARAM") or "").strip()
    POS_RECEIPT_ADDRESS_MEGA = (os.getenv("POS_RECEIPT_ADDRESS_MEGA") or "").strip()
    POS_RECEIPT_CUSTOMER_SERVICE = (os.getenv("POS_RECEIPT_CUSTOMER_SERVICE") or "").strip()
    POS_RECEIPT_CUSTOMER_SERVICE_MATARAM = (os.getenv("POS_RECEIPT_CUSTOMER_SERVICE_MATARAM") or "").strip()
    POS_RECEIPT_CUSTOMER_SERVICE_MEGA = (os.getenv("POS_RECEIPT_CUSTOMER_SERVICE_MEGA") or "").strip()
    POS_RECEIPT_FOOTER_IDENTITY = (os.getenv("POS_RECEIPT_FOOTER_IDENTITY") or "").strip()
    POS_RECEIPT_FOOTER_IDENTITY_MATARAM = (os.getenv("POS_RECEIPT_FOOTER_IDENTITY_MATARAM") or "").strip()
    POS_RECEIPT_FOOTER_IDENTITY_MEGA = (os.getenv("POS_RECEIPT_FOOTER_IDENTITY_MEGA") or "").strip()
    POS_RECEIPT_FOOTER_NOTE = (os.getenv("POS_RECEIPT_FOOTER_NOTE") or "").strip()
    POS_RECEIPT_FOOTER_NOTE_MATARAM = (os.getenv("POS_RECEIPT_FOOTER_NOTE_MATARAM") or "").strip()
    POS_RECEIPT_FOOTER_NOTE_MEGA = (os.getenv("POS_RECEIPT_FOOTER_NOTE_MEGA") or "").strip()
    POS_RECEIPT_RETURN_POLICY = (os.getenv("POS_RECEIPT_RETURN_POLICY") or "").strip()
    POS_RECEIPT_RETURN_POLICY_MATARAM = (os.getenv("POS_RECEIPT_RETURN_POLICY_MATARAM") or "").strip()
    POS_RECEIPT_RETURN_POLICY_MEGA = (os.getenv("POS_RECEIPT_RETURN_POLICY_MEGA") or "").strip()
    POS_RECEIPT_THANK_YOU_TEXT = (os.getenv("POS_RECEIPT_THANK_YOU_TEXT") or "").strip()
    POS_RECEIPT_THANK_YOU_TEXT_MATARAM = (os.getenv("POS_RECEIPT_THANK_YOU_TEXT_MATARAM") or "").strip()
    POS_RECEIPT_THANK_YOU_TEXT_MEGA = (os.getenv("POS_RECEIPT_THANK_YOU_TEXT_MEGA") or "").strip()
    POS_RECEIPT_FEEDBACK_LINE = (os.getenv("POS_RECEIPT_FEEDBACK_LINE") or "").strip()
    POS_RECEIPT_FEEDBACK_LINE_MATARAM = (os.getenv("POS_RECEIPT_FEEDBACK_LINE_MATARAM") or "").strip()
    POS_RECEIPT_FEEDBACK_LINE_MEGA = (os.getenv("POS_RECEIPT_FEEDBACK_LINE_MEGA") or "").strip()
    POS_RECEIPT_SOCIAL_LABEL = (os.getenv("POS_RECEIPT_SOCIAL_LABEL") or "").strip()
    POS_RECEIPT_SOCIAL_LABEL_MATARAM = (os.getenv("POS_RECEIPT_SOCIAL_LABEL_MATARAM") or "").strip()
    POS_RECEIPT_SOCIAL_LABEL_MEGA = (os.getenv("POS_RECEIPT_SOCIAL_LABEL_MEGA") or "").strip()
    POS_RECEIPT_SOCIAL_URL = (os.getenv("POS_RECEIPT_SOCIAL_URL") or "").strip()
    POS_RECEIPT_SOCIAL_URL_MATARAM = (os.getenv("POS_RECEIPT_SOCIAL_URL_MATARAM") or "").strip()
    POS_RECEIPT_SOCIAL_URL_MEGA = (os.getenv("POS_RECEIPT_SOCIAL_URL_MEGA") or "").strip()
    POS_RECEIPT_SOCIAL_QR_IMAGE = (os.getenv("POS_RECEIPT_SOCIAL_QR_IMAGE") or "").strip()
    POS_RECEIPT_SOCIAL_QR_IMAGE_MATARAM = (os.getenv("POS_RECEIPT_SOCIAL_QR_IMAGE_MATARAM") or "").strip()
    POS_RECEIPT_SOCIAL_QR_IMAGE_MEGA = (os.getenv("POS_RECEIPT_SOCIAL_QR_IMAGE_MEGA") or "").strip()
    POS_RECEIPT_PDF_RENDERER = _first_env_value("POS_RECEIPT_PDF_RENDERER", default="auto")
    POS_RECEIPT_PDF_LAYOUT = _first_env_value("POS_RECEIPT_PDF_LAYOUT", default="a4")
    POS_RECEIPT_PDF_BROWSER = _first_env_value("POS_RECEIPT_PDF_BROWSER")
    POS_RECEIPT_PDF_BROWSER_TIMEOUT_SECONDS = _int_env("POS_RECEIPT_PDF_BROWSER_TIMEOUT_SECONDS", 25)
    POS_AUTO_PRINT_AFTER_CHECKOUT = _env_flag("POS_AUTO_PRINT_AFTER_CHECKOUT", False)
    # Temporary cashier exception: POS may continue checkout while stock is 0 and let it go minus.
    # Set to 0 to restore strict stock validation.
    POS_ALLOW_NEGATIVE_STOCK_TEMP = _env_flag("POS_ALLOW_NEGATIVE_STOCK_TEMP", True)
    ENFORCE_SAME_ORIGIN_POSTS = _env_flag("ENFORCE_SAME_ORIGIN_POSTS", True)
    ENFORCE_SAME_ORIGIN_POSTS_DURING_TESTS = _env_flag(
        "ENFORCE_SAME_ORIGIN_POSTS_DURING_TESTS",
        False,
    )

    PERMANENT_SESSION_LIFETIME = timedelta(hours=1)
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", str(12 * 1024 * 1024)))
    CHAT_ATTACHMENT_MAX_BYTES = int(os.getenv("CHAT_ATTACHMENT_MAX_BYTES", str(10 * 1024 * 1024)))
    CHAT_SOUND_VOLUME_DEFAULT = float(os.getenv("CHAT_SOUND_VOLUME_DEFAULT", "0.85"))
    NOTIFICATION_LOG_RETENTION_DAYS = _int_env("NOTIFICATION_LOG_RETENTION_DAYS", 90)
    WEB_NOTIFICATION_RETENTION_DAYS = _int_env("WEB_NOTIFICATION_RETENTION_DAYS", 90)
    NOTIFICATION_LOG_CLEANUP_INTERVAL_SECONDS = _int_env(
        "NOTIFICATION_LOG_CLEANUP_INTERVAL_SECONDS",
        3600,
    )
    POS_HIDDEN_ARCHIVE_PASSWORD = _first_env_value("POS_HIDDEN_ARCHIVE_PASSWORD", default="susu")
    POS_HIDDEN_ARCHIVE_UNLOCK_SECONDS = _int_env("POS_HIDDEN_ARCHIVE_UNLOCK_SECONDS", 1800)
    IPOS4_IMPORT_RUNTIME_DIR = os.getenv(
        "IPOS4_IMPORT_RUNTIME_DIR",
        os.path.join(BASE_DIR, "instance", "ipos4_runtime"),
    )
    SMS_STORAGE_ROOT = os.getenv(
        "SMS_STORAGE_ROOT",
        os.path.join(BASE_DIR, "instance", "sms_storage", "storage"),
    )
    SMS_STORAGE_DATA_ROOT = os.getenv(
        "SMS_STORAGE_DATA_ROOT",
        os.path.join(BASE_DIR, "instance", "sms_storage", "data"),
    )
    SMS_STORAGE_MAX_UPLOAD_BYTES = _int_env(
        "SMS_STORAGE_MAX_UPLOAD_BYTES",
        100 * 1024 * 1024 * 1024,
    )
    SMS_STORAGE_PER_USER_QUOTA_BYTES = _int_env(
        "SMS_STORAGE_PER_USER_QUOTA_BYTES",
        500 * 1024 * 1024,
    )
    SMS_STORAGE_ACTIVITY_LIMIT = _int_env("SMS_STORAGE_ACTIVITY_LIMIT", 40)
    SMS_STORAGE_ACTIVITY_FEED_LIMIT = _int_env("SMS_STORAGE_ACTIVITY_FEED_LIMIT", 10)
    CAREER_HOME_HERO_IMAGE = _first_env_value(
        "CAREER_HOME_HERO_IMAGE",
        default="brand/login-hero-crowd.jpeg",
    )
    CAREER_PUBLIC_NOTICE_TEXT = _first_env_value(
        "CAREER_PUBLIC_NOTICE_TEXT",
        default="ERP-CV.BJAS tidak memungut biaya apa pun selama proses pendaftaran dan seleksi karir berlangsung.",
    )
    IPOS4_MIRROR_DB_PATH = os.getenv(
        "IPOS4_MIRROR_DB_PATH",
        os.path.join(BASE_DIR, "instance", "ipos4_mirror.db"),
    )
    KIRIMI_BASE_URL = _first_env_value("KIRIMI_BASE_URL", default="https://api.kirimi.id")
    KIRIMI_USER_CODE = _first_env_value("KIRIMI_USER_CODE")
    KIRIMI_DEVICE_ID = _first_env_value("KIRIMI_DEVICE_ID")
    KIRIMI_SECRET = _first_env_value("KIRIMI_SECRET")
    KIRIMI_USER_CODE_MATARAM = _first_env_value("KIRIMI_USER_CODE_MATARAM")
    KIRIMI_DEVICE_ID_MATARAM = _first_env_value("KIRIMI_DEVICE_ID_MATARAM")
    KIRIMI_SECRET_MATARAM = _first_env_value("KIRIMI_SECRET_MATARAM")
    KIRIMI_USER_CODE_MEGA = _first_env_value("KIRIMI_USER_CODE_MEGA")
    KIRIMI_DEVICE_ID_MEGA = _first_env_value("KIRIMI_DEVICE_ID_MEGA")
    KIRIMI_SECRET_MEGA = _first_env_value("KIRIMI_SECRET_MEGA")
    CASH_CLOSING_WHATSAPP_GROUP = _first_env_value("CASH_CLOSING_WHATSAPP_GROUP")
    CASH_CLOSING_WHATSAPP_GROUP_MATARAM = _first_env_value("CASH_CLOSING_WHATSAPP_GROUP_MATARAM")
    CASH_CLOSING_WHATSAPP_GROUP_MEGA = _first_env_value("CASH_CLOSING_WHATSAPP_GROUP_MEGA")
    KIRIMI_SEND_MESSAGE_PATH = _first_env_value(
        "KIRIMI_SEND_MESSAGE_PATH",
        "KIRIMI_SEND_PATH",
        default="/v1/send-message-fast",
    )
    KIRIMI_TIMEOUT_SECONDS = _int_env("KIRIMI_TIMEOUT_SECONDS", 15)
    CHAT_WEBRTC_ICE_SERVERS = [
        {
            "urls": [
                "stun:stun.l.google.com:19302",
                "stun:stun1.l.google.com:19302",
            ]
        }
    ]
    MEETING_PROVIDER = (os.getenv("MEETING_PROVIDER") or "jitsi").strip().lower()
    JITSI_MEETING_DOMAIN = _first_env_value(
        "JITSI_MEETING_DOMAIN",
        default=str(
            MEETING_LOCAL_CONFIG.get("domain")
            or ("8x8.vc" if MEETING_LOCAL_CONFIG.get("app_id") else "meet.jit.si")
        ),
    )
    JITSI_ROOM_PREFIX = (os.getenv("JITSI_ROOM_PREFIX") or "erp-bjas").strip()
    JITSI_ROOM_MAX_PARTICIPANTS = int(os.getenv("JITSI_ROOM_MAX_PARTICIPANTS", "10"))
    JITSI_JAAS_APP_ID = _first_env_value(
        "JITSI_JAAS_APP_ID",
        default=str(MEETING_LOCAL_CONFIG.get("app_id") or ""),
    )
    JITSI_JAAS_KEY_ID = _first_env_value(
        "JITSI_JAAS_KEY_ID",
        default=str(MEETING_LOCAL_CONFIG.get("key_id") or ""),
    )
    JITSI_JAAS_PRIVATE_KEY_PATH = _first_env_value(
        "JITSI_JAAS_PRIVATE_KEY_PATH",
        default=str(MEETING_LOCAL_CONFIG.get("private_key_path") or ""),
    )
    JITSI_JAAS_PUBLIC_KEY_PATH = _first_env_value(
        "JITSI_JAAS_PUBLIC_KEY_PATH",
        default=str(MEETING_LOCAL_CONFIG.get("public_key_path") or ""),
    )
    JITSI_JAAS_KID = _first_env_value(
        "JITSI_JAAS_KID",
        default=str(MEETING_LOCAL_CONFIG.get("kid") or ""),
    )
    JITSI_JAAS_TOKEN_TTL_SECONDS = int(
        os.getenv(
            "JITSI_JAAS_TOKEN_TTL_SECONDS",
            str(MEETING_LOCAL_CONFIG.get("token_ttl_seconds") or 2 * 60 * 60),
        )
    )
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
    ANDROID_APP_PACKAGE = _first_env_value(
        "ANDROID_APP_PACKAGE",
        default="cloud.cvbjasyogya.erp",
    ).lower()
    ANDROID_SHA256_CERT_FINGERPRINTS = _csv_env("ANDROID_SHA256_CERT_FINGERPRINTS", "")
    ANDROID_TWA_START_URL = _first_env_value(
        "ANDROID_TWA_START_URL",
        default="https://erp.cvbjasyogya.cloud/workspace/?source=android-app",
    )
    IOS_APP_IDS = _csv_env("IOS_APP_IDS", "")
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
    AUTOMATIC_OVERTIME_EMPLOYEE_NAMES = _csv_env(
        "AUTOMATIC_OVERTIME_EMPLOYEE_NAMES",
        "Naufal,Ajeng",
    )
    OVERTIME_BALANCE_CAP_MINUTES = _int_env("OVERTIME_BALANCE_CAP_MINUTES", 0)

    # ==========================
    # DATABASE (SINGLE SOURCE)
    # ==========================
    DATABASE_BACKEND = (os.getenv("DATABASE_BACKEND") or "sqlite").strip().lower()
    DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
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
