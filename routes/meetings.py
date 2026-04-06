import base64
import json
import time
from functools import lru_cache
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify, render_template, request, session

from database import get_db

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
except ImportError:
    hashes = None
    serialization = None
    padding = None


meetings_bp = Blueprint("meetings", __name__, url_prefix="/meetings")


MEETING_LANGUAGE_OPTIONS = [
    ("id-ID", "Bahasa Indonesia"),
    ("en-US", "English"),
]

MEETING_JOIN_PROFILES = [
    {
        "slug": "audio-first",
        "label": "Audio First",
        "badge": "Recommended",
        "description": "Masuk dengan audio dulu, kamera tetap mati di awal supaya paling ringan untuk briefing dan koordinasi cepat.",
        "summary": "Paling aman untuk 6-10 orang di jaringan campuran.",
        "camera_strategy": "manual",
        "start_audio_only": True,
        "start_with_video_muted": True,
        "video_resolution": 360,
        "channel_last_n": 6,
        "toolbar_compact": True,
    },
    {
        "slug": "smart-saver",
        "label": "Smart Saver",
        "badge": "Hemat",
        "description": "Tetap fokus ke performa ringan. Audio aktif, kamera mati di awal, cocok untuk mobile dan laptop operasional.",
        "summary": "Bagus untuk daily check dan follow up gudang.",
        "camera_strategy": "manual",
        "start_audio_only": False,
        "start_with_video_muted": True,
        "video_resolution": 360,
        "channel_last_n": 6,
        "toolbar_compact": True,
    },
    {
        "slug": "balanced",
        "label": "Balanced",
        "badge": "Stabil",
        "description": "Masuk dengan setting moderat, tetap aman untuk diskusi rutin tanpa terlalu membebani browser.",
        "summary": "Cocok untuk standup tim dan review operasional.",
        "camera_strategy": "optional",
        "start_audio_only": False,
        "start_with_video_muted": True,
        "video_resolution": 540,
        "channel_last_n": 8,
        "toolbar_compact": False,
    },
    {
        "slug": "presentation",
        "label": "Presentation",
        "badge": "Visual",
        "description": "Dipakai saat perlu share layar, demo, atau presentasi yang lebih visual. Kamera boleh aktif dari awal.",
        "summary": "Pakai saat koneksi peserta cukup stabil.",
        "camera_strategy": "ready",
        "start_audio_only": False,
        "start_with_video_muted": False,
        "video_resolution": 720,
        "channel_last_n": 10,
        "toolbar_compact": False,
    },
]

DEFAULT_MEETING_PROFILE = MEETING_JOIN_PROFILES[0]["slug"]
DEFAULT_TOOLBAR_BUTTONS = [
    "microphone",
    "camera",
    "desktop",
    "chat",
    "participants-pane",
    "tileview",
    "raisehand",
    "hangup",
    "settings",
    "fullscreen",
]
COMPACT_TOOLBAR_BUTTONS = [
    "microphone",
    "camera",
    "chat",
    "participants-pane",
    "hangup",
    "settings",
]


def _jaas_app_id():
    return str(current_app.config.get("JITSI_JAAS_APP_ID") or "").strip()


def _jaas_key_id():
    explicit_kid = str(current_app.config.get("JITSI_JAAS_KID") or "").strip()
    if explicit_kid:
        return explicit_kid

    app_id = _jaas_app_id()
    key_id = str(current_app.config.get("JITSI_JAAS_KEY_ID") or "").strip()
    if not app_id or not key_id:
        return ""
    if "/" in key_id:
        return key_id
    return f"{app_id}/{key_id}"


def _jaas_private_key_path():
    return str(current_app.config.get("JITSI_JAAS_PRIVATE_KEY_PATH") or "").strip()


def _jaas_enabled():
    return bool(_jaas_app_id())


def _jaas_token_enabled():
    return bool(_jaas_enabled() and _jaas_key_id() and _jaas_private_key_path())


def _meeting_domain():
    default_domain = "8x8.vc" if _jaas_enabled() else "meet.jit.si"
    domain = str(current_app.config.get("JITSI_MEETING_DOMAIN") or default_domain).strip().lower()
    if domain.startswith("http://") or domain.startswith("https://"):
        parsed = urlsplit(domain)
        domain = parsed.netloc or parsed.path
    return domain or default_domain


def _meeting_room_prefix():
    raw_value = str(current_app.config.get("JITSI_ROOM_PREFIX") or "erp-bjas").strip().lower()
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw_value)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned or "erp-bjas"


def _sanitize_room_name(raw_value, fallback=""):
    candidate = str(raw_value or "").strip()
    if candidate.startswith("http://") or candidate.startswith("https://"):
        parsed = urlsplit(candidate)
        path_segments = [segment for segment in parsed.path.split("/") if segment]
        candidate = path_segments[-1] if path_segments else ""

    if not candidate:
        candidate = str(fallback or "").strip()

    candidate = candidate.replace(" ", "-").replace("/", "-").replace("\\", "-").lower()
    cleaned = []
    last_dash = False
    for char in candidate:
        if char.isalnum() or char in {"-", "_"}:
            cleaned.append(char)
            last_dash = False
            continue
        if not last_dash:
            cleaned.append("-")
            last_dash = True

    room_name = "".join(cleaned).strip("-_")
    room_name = "-".join(part for part in room_name.split("-") if part)

    if not room_name:
        room_name = _meeting_room_prefix()

    if len(room_name) < 6:
        room_name = f"{_meeting_room_prefix()}-{room_name}"

    return room_name[:72]


def _sanitize_display_name(raw_value):
    safe_name = " ".join(str(raw_value or "").strip().split())
    return safe_name[:64]


def _sanitize_topic(raw_value):
    return " ".join(str(raw_value or "").strip().split())[:120]


def _sanitize_email(raw_value):
    return str(raw_value or "").strip()[:120]


def _resolve_join_profile(raw_value):
    chosen = str(raw_value or "").strip().lower()
    for profile in MEETING_JOIN_PROFILES:
        if profile["slug"] == chosen:
            return profile
    return MEETING_JOIN_PROFILES[0]


def _get_current_user_email():
    db = get_db()
    user = db.execute(
        "SELECT email FROM users WHERE id=?",
        (session.get("user_id"),),
    ).fetchone()
    return (user["email"] if user and user["email"] else "").strip()


def _build_meeting_url(room_name):
    return f"https://{_meeting_domain()}/{_build_embed_room_name(room_name)}"


def _build_embed_room_name(room_name):
    clean_room_name = _sanitize_room_name(room_name, fallback=_meeting_room_prefix())
    if _jaas_enabled():
        return f"{_jaas_app_id()}/{clean_room_name}"
    return clean_room_name


def _base64url_encode(raw_bytes):
    return base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")


@lru_cache(maxsize=4)
def _load_signing_key(path):
    if not path or serialization is None:
        return None

    with open(path, "rb") as file_handle:
        return serialization.load_pem_private_key(file_handle.read(), password=None)


def _build_jaas_jwt(room_name, display_name, email):
    if not _jaas_token_enabled() or hashes is None or padding is None:
        return ""

    try:
        private_key = _load_signing_key(_jaas_private_key_path())
    except Exception:
        return ""

    if private_key is None:
        return ""

    issued_at = int(time.time())
    expires_at = issued_at + max(300, int(current_app.config.get("JITSI_JAAS_TOKEN_TTL_SECONDS", 2 * 60 * 60)))
    user_role = str(session.get("role") or "").strip().lower()
    is_moderator = user_role in {"super_admin", "owner", "hr", "admin", "leader"}
    app_id = _jaas_app_id()

    header = {
        "alg": "RS256",
        "typ": "JWT",
        "kid": _jaas_key_id(),
    }
    payload = {
        "aud": "jitsi",
        "iss": "chat",
        "sub": app_id,
        "room": "*",
        "nbf": issued_at - 5,
        "iat": issued_at,
        "exp": expires_at,
        "context": {
            "features": {
                "livestreaming": False,
                "recording": False,
                "transcription": False,
                "outbound-call": False,
                "sip-outbound-call": False,
                "file-upload": False,
                "list-visitors": False,
                "flip": False,
            },
            "user": {
                "id": str(session.get("user_id") or session.get("username") or display_name or "guest"),
                "name": display_name,
                "email": email or "",
                "avatar": "",
                "moderator": is_moderator,
                "hidden-from-recorder": False,
            },
        },
    }

    signing_input = ".".join(
        [
            _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8")),
            _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
        ]
    )
    signature = private_key.sign(signing_input.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_base64url_encode(signature)}"


def _build_meeting_payload(source):
    profile = _resolve_join_profile(source.get("profile"))
    display_name = _sanitize_display_name(source.get("displayName") or session.get("username") or "Guest")
    topic = _sanitize_topic(source.get("topic"))
    room_name = _sanitize_room_name(
        source.get("roomName") or source.get("meetingNumber"),
        fallback=topic or display_name or _meeting_room_prefix(),
    )
    embed_room_name = _build_embed_room_name(room_name)
    language = str(
        source.get("language")
        or current_app.config.get("MEETING_DEFAULT_LANGUAGE")
        or current_app.config.get("ZOOM_MEETING_DEFAULT_LANGUAGE")
        or "id-ID"
    ).strip()
    email = _sanitize_email(source.get("email"))
    participant_limit = max(6, min(int(current_app.config.get("JITSI_ROOM_MAX_PARTICIPANTS", 10)), 12))
    jwt_token = _build_jaas_jwt(room_name, display_name, email)
    backend_label = "8x8 JaaS" if _jaas_enabled() else "Browser Room"

    return {
        "status": "success",
        "provider": "jitsi",
        "domain": _meeting_domain(),
        "roomName": room_name,
        "embedRoomName": embed_room_name,
        "roomUrl": _build_meeting_url(room_name),
        "displayName": display_name,
        "email": email,
        "language": language or "id-ID",
        "profile": profile["slug"],
        "profileLabel": profile["label"],
        "topic": topic or f"Meeting {room_name}",
        "leaveUrl": "/meetings/",
        "backendLabel": backend_label,
        "usesJaas": _jaas_enabled(),
        "jwt": jwt_token,
        "cameraStrategy": profile["camera_strategy"],
        "startAudioOnly": bool(profile["start_audio_only"]),
        "startWithVideoMuted": bool(profile["start_with_video_muted"]),
        "videoResolution": int(profile["video_resolution"]),
        "channelLastN": int(profile["channel_last_n"]),
        "participantLimit": participant_limit,
        "toolbarButtons": COMPACT_TOOLBAR_BUTTONS if profile["toolbar_compact"] else DEFAULT_TOOLBAR_BUTTONS,
    }


@meetings_bp.route("/")
def portal():
    meeting_backend_label = "8x8 JaaS" if _jaas_enabled() else "Browser Room"
    return render_template(
        "meetings.html",
        meeting_provider="jitsi",
        meeting_ready=True,
        meeting_backend_label=meeting_backend_label,
        meeting_embed_domain=_meeting_domain(),
        meeting_join_profiles=MEETING_JOIN_PROFILES,
        meeting_language_options=MEETING_LANGUAGE_OPTIONS,
        default_meeting_profile=DEFAULT_MEETING_PROFILE,
        default_display_name=_sanitize_display_name(session.get("username") or "Guest"),
        default_email=_get_current_user_email(),
        meeting_participant_limit=max(6, min(int(current_app.config.get("JITSI_ROOM_MAX_PARTICIPANTS", 10)), 12)),
        meeting_uses_jaas=_jaas_enabled(),
    )


@meetings_bp.post("/signature")
def signature():
    payload = request.get_json(silent=True) or request.form
    prepared = _build_meeting_payload(payload)
    if not prepared["roomName"]:
        return jsonify({"status": "error", "message": "Nama room meeting wajib diisi."}), 400
    if not prepared["displayName"]:
        return jsonify({"status": "error", "message": "Nama tampilan meeting wajib diisi."}), 400
    return jsonify(prepared)


@meetings_bp.route("/session")
def session_page():
    return render_template(
        "meeting_session.html",
        meeting_provider="jitsi",
        meeting_embed_domain=_meeting_domain(),
        default_leave_url="/meetings/",
        meeting_join_profiles=MEETING_JOIN_PROFILES,
        meeting_participant_limit=max(6, min(int(current_app.config.get("JITSI_ROOM_MAX_PARTICIPANTS", 10)), 12)),
        meeting_uses_jaas=_jaas_enabled(),
    )
