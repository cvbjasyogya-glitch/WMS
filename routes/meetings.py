from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify, render_template, request, session

from database import get_db


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


def _meeting_domain():
    domain = str(current_app.config.get("JITSI_MEETING_DOMAIN") or "meet.jit.si").strip().lower()
    if domain.startswith("http://") or domain.startswith("https://"):
        parsed = urlsplit(domain)
        domain = parsed.netloc or parsed.path
    return domain or "meet.jit.si"


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
    return f"https://{_meeting_domain()}/{room_name}"


def _build_meeting_payload(source):
    profile = _resolve_join_profile(source.get("profile"))
    display_name = _sanitize_display_name(source.get("displayName") or session.get("username") or "Guest")
    topic = _sanitize_topic(source.get("topic"))
    room_name = _sanitize_room_name(
        source.get("roomName") or source.get("meetingNumber"),
        fallback=topic or display_name or _meeting_room_prefix(),
    )
    language = str(
        source.get("language")
        or current_app.config.get("MEETING_DEFAULT_LANGUAGE")
        or current_app.config.get("ZOOM_MEETING_DEFAULT_LANGUAGE")
        or "id-ID"
    ).strip()
    participant_limit = max(6, min(int(current_app.config.get("JITSI_ROOM_MAX_PARTICIPANTS", 10)), 12))

    return {
        "status": "success",
        "provider": "jitsi",
        "domain": _meeting_domain(),
        "roomName": room_name,
        "roomUrl": _build_meeting_url(room_name),
        "displayName": display_name,
        "email": _sanitize_email(source.get("email")),
        "language": language or "id-ID",
        "profile": profile["slug"],
        "profileLabel": profile["label"],
        "topic": topic or f"Meeting {room_name}",
        "leaveUrl": "/meetings/",
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
    return render_template(
        "meetings.html",
        meeting_provider="jitsi",
        meeting_ready=True,
        meeting_backend_label="Browser Room",
        meeting_embed_domain=_meeting_domain(),
        meeting_join_profiles=MEETING_JOIN_PROFILES,
        meeting_language_options=MEETING_LANGUAGE_OPTIONS,
        default_meeting_profile=DEFAULT_MEETING_PROFILE,
        default_display_name=_sanitize_display_name(session.get("username") or "Guest"),
        default_email=_get_current_user_email(),
        meeting_participant_limit=max(6, min(int(current_app.config.get("JITSI_ROOM_MAX_PARTICIPANTS", 10)), 12)),
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
    )
