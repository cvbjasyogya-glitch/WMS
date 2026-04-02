import base64
import hashlib
import hmac
import json
import time

from flask import Blueprint, current_app, jsonify, render_template, request, session

from database import get_db


meetings_bp = Blueprint("meetings", __name__, url_prefix="/meetings")


MEETING_LANGUAGE_OPTIONS = [
    ("id-ID", "Bahasa Indonesia"),
    ("en-US", "English"),
    ("zh-CN", "Chinese"),
    ("ja-JP", "Japanese"),
]

MEETING_JOIN_PROFILES = [
    {
        "slug": "smart-saver",
        "label": "Smart Saver",
        "badge": "Default",
        "description": "Preview kamera dimatikan, cocok untuk meeting harian yang perlu hemat daya dan kuota.",
        "summary": "Paling aman untuk mobile dan jaringan campuran.",
        "disable_preview": True,
        "camera_strategy": "manual",
    },
    {
        "slug": "audio-first",
        "label": "Audio First",
        "badge": "Kuota Rendah",
        "description": "Masuk dengan fokus audio dulu. Aktifkan kamera manual hanya saat benar-benar perlu.",
        "summary": "Cocok untuk follow up cepat dan jaringan lemah.",
        "disable_preview": True,
        "camera_strategy": "manual",
    },
    {
        "slug": "balanced",
        "label": "Balanced",
        "badge": "Stabil",
        "description": "Experience standar dengan ruang untuk diskusi audio dan video saat diperlukan.",
        "summary": "Pilihan aman untuk desktop dan laptop kantor.",
        "disable_preview": False,
        "camera_strategy": "optional",
    },
    {
        "slug": "presentation",
        "label": "Presentation",
        "badge": "Presentasi",
        "description": "Lebih cocok saat perlu screen sharing, demo produk, atau rapat eksternal formal.",
        "summary": "Kualitas visual diutamakan, konsumsi daya lebih tinggi.",
        "disable_preview": False,
        "camera_strategy": "ready",
    },
]

DEFAULT_MEETING_PROFILE = MEETING_JOIN_PROFILES[0]["slug"]


def _b64url_encode(raw_bytes):
    return base64.urlsafe_b64encode(raw_bytes).rstrip(b"=").decode("ascii")


def _zoom_sdk_ready():
    return bool(
        current_app.config.get("ZOOM_MEETING_SDK_KEY")
        and current_app.config.get("ZOOM_MEETING_SDK_SECRET")
    )


def _sanitize_meeting_number(raw_value):
    digits_only = "".join(ch for ch in str(raw_value or "") if ch.isdigit())
    if len(digits_only) < 9 or len(digits_only) > 12:
        return ""
    return digits_only


def _sanitize_display_name(raw_value):
    safe_name = " ".join(str(raw_value or "").strip().split())
    return safe_name[:64]


def _sanitize_passcode(raw_value):
    return str(raw_value or "").strip()[:64]


def _resolve_join_profile(raw_value):
    chosen = str(raw_value or "").strip().lower()
    for profile in MEETING_JOIN_PROFILES:
        if profile["slug"] == chosen:
            return profile
    return MEETING_JOIN_PROFILES[0]


def _create_meeting_signature(meeting_number, role):
    sdk_key = current_app.config.get("ZOOM_MEETING_SDK_KEY", "")
    sdk_secret = current_app.config.get("ZOOM_MEETING_SDK_SECRET", "")
    issued_at = int(time.time()) - 30
    expires_at = issued_at + int(current_app.config.get("ZOOM_MEETING_SIGNATURE_TTL_SECONDS", 7200))

    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sdkKey": sdk_key,
        "mn": str(meeting_number),
        "role": int(role),
        "iat": issued_at,
        "exp": expires_at,
        "appKey": sdk_key,
        "tokenExp": expires_at,
    }

    encoded_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
    signature = hmac.new(
        sdk_secret.encode("utf-8"),
        signing_input,
        hashlib.sha256,
    ).digest()
    encoded_signature = _b64url_encode(signature)
    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def _get_current_user_email():
    db = get_db()
    user = db.execute(
        "SELECT email FROM users WHERE id=?",
        (session.get("user_id"),),
    ).fetchone()
    return (user["email"] if user and user["email"] else "").strip()


@meetings_bp.route("/")
def portal():
    configured = _zoom_sdk_ready()
    return render_template(
        "meetings.html",
        zoom_sdk_ready=configured,
        zoom_sdk_version=current_app.config.get("ZOOM_MEETING_SDK_VERSION", "5.1.4"),
        zoom_default_language=current_app.config.get("ZOOM_MEETING_DEFAULT_LANGUAGE", "id-ID"),
        zoom_web_endpoint=current_app.config.get("ZOOM_MEETING_WEB_ENDPOINT", "zoom.us"),
        meeting_join_profiles=MEETING_JOIN_PROFILES,
        meeting_language_options=MEETING_LANGUAGE_OPTIONS,
        default_meeting_profile=DEFAULT_MEETING_PROFILE,
        default_display_name=_sanitize_display_name(session.get("username") or "Guest"),
        default_email=_get_current_user_email(),
    )


@meetings_bp.post("/signature")
def signature():
    if not _zoom_sdk_ready():
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Meeting SDK belum dikonfigurasi di server. Isi ZOOM_MEETING_SDK_KEY/CLIENT_ID dan ZOOM_MEETING_SDK_SECRET/CLIENT_SECRET dulu.",
                }
            ),
            503,
        )

    payload = request.get_json(silent=True) or request.form
    meeting_number = _sanitize_meeting_number(payload.get("meetingNumber"))
    display_name = _sanitize_display_name(payload.get("displayName") or session.get("username"))
    passcode = _sanitize_passcode(payload.get("passcode"))
    email = str(payload.get("email") or "").strip()[:120]
    language = str(payload.get("language") or current_app.config.get("ZOOM_MEETING_DEFAULT_LANGUAGE", "id-ID")).strip()
    profile = _resolve_join_profile(payload.get("profile"))
    topic = " ".join(str(payload.get("topic") or "").strip().split())[:120]

    if not meeting_number:
        return jsonify({"status": "error", "message": "Nomor meeting Zoom wajib diisi dengan format angka yang valid."}), 400
    if not display_name:
        return jsonify({"status": "error", "message": "Nama tampilan meeting wajib diisi."}), 400

    signature_value = _create_meeting_signature(meeting_number, 0)
    return jsonify(
        {
            "status": "success",
            "signature": signature_value,
            "sdkKey": current_app.config.get("ZOOM_MEETING_SDK_KEY", ""),
            "meetingNumber": meeting_number,
            "displayName": display_name,
            "passcode": passcode,
            "email": email,
            "language": language,
            "profile": profile["slug"],
            "profileLabel": profile["label"],
            "topic": topic,
            "leaveUrl": "/meetings/",
            "webEndpoint": current_app.config.get("ZOOM_MEETING_WEB_ENDPOINT", "zoom.us"),
            "sdkVersion": current_app.config.get("ZOOM_MEETING_SDK_VERSION", "5.1.4"),
            "cameraStrategy": profile["camera_strategy"],
            "disablePreview": bool(profile["disable_preview"]),
        }
    )


@meetings_bp.route("/session")
def session_page():
    return render_template(
        "meeting_session.html",
        zoom_sdk_ready=_zoom_sdk_ready(),
        zoom_sdk_version=current_app.config.get("ZOOM_MEETING_SDK_VERSION", "5.1.4"),
        zoom_web_endpoint=current_app.config.get("ZOOM_MEETING_WEB_ENDPOINT", "zoom.us"),
        default_leave_url="/meetings/",
        meeting_join_profiles=MEETING_JOIN_PROFILES,
    )
