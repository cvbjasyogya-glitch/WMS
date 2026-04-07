import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session
from werkzeug.utils import secure_filename

from database import get_db
from services.notification_service import push_user_notification
from services.rbac import has_permission


chat_bp = Blueprint("chat", __name__, url_prefix="/chat")

ONLINE_WINDOW_SECONDS = 45
INITIAL_MESSAGE_LIMIT = 120
POLL_MESSAGE_LIMIT = 60
INCOMING_TOAST_LIMIT = 12
CHAT_DISPLAY_UTC_OFFSET_HOURS = 7
CHAT_THREAD_SEARCH_LIMIT = 24
CHAT_MESSAGE_FOCUS_WINDOW = 24
CHAT_TYPING_TTL_SECONDS = 8
ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
    ".pdf", ".txt", ".csv", ".zip",
    ".doc", ".docx", ".xls", ".xlsx",
}
ALLOWED_STICKER_IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp",
}
CHAT_STICKERS = [
    {"code": "ok", "emoji": "\U0001F44D", "label": "Sip"},
    {"code": "gas", "emoji": "\U0001F525", "label": "Gas"},
    {"code": "ping", "emoji": "\U0001F4E3", "label": "Ping"},
    {"code": "wait", "emoji": "\U0001F64F", "label": "Mohon"},
    {"code": "star", "emoji": "\u2B50", "label": "Mantap"},
    {"code": "rocket", "emoji": "\U0001F680", "label": "Jalan"},
]
CHAT_STICKER_MAP = {item["code"]: item for item in CHAT_STICKERS}
OPEN_CALL_STATUSES = {"pending", "ringing", "connecting", "active"}
CALL_SIGNAL_TYPES = {"invite", "accept", "offer", "answer", "ice", "decline", "end"}
SUPPORTED_CALL_MODES = {"voice", "video"}
CALL_SIGNAL_LIMIT = 80
CALL_RING_TIMEOUT_SECONDS = 90
CHAT_LOCAL_DAY_NAMES = [
    "Senin",
    "Selasa",
    "Rabu",
    "Kamis",
    "Jumat",
    "Sabtu",
    "Minggu",
]
CHAT_LOCAL_MONTH_NAMES = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Mei",
    "Jun",
    "Jul",
    "Agu",
    "Sep",
    "Okt",
    "Nov",
    "Des",
]


def _to_int(value, default=None):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default

def _get_initials(name):
    parts = [part for part in (name or "").strip().split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _clip_text(value, limit=120):
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)].rstrip() + "..."


def _parse_chat_timestamp(value):
    raw = str(value or "").strip()
    if not raw:
        return None

    normalized = raw.replace("T", " ")
    if len(normalized) == 16:
        normalized = f"{normalized}:00"

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _to_chat_local_time(value):
    parsed = value if isinstance(value, datetime) else _parse_chat_timestamp(value)
    if not parsed:
        return None
    return parsed + timedelta(hours=CHAT_DISPLAY_UTC_OFFSET_HOURS)


def _chat_local_now():
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=CHAT_DISPLAY_UTC_OFFSET_HOURS)


def _format_chat_day_label(value):
    local_time = _to_chat_local_time(value)
    if not local_time:
        return "-"

    today = _chat_local_now().date()
    local_date = local_time.date()
    if local_date == today:
        return "Hari Ini"
    if local_date == today - timedelta(days=1):
        return "Kemarin"

    day_name = CHAT_LOCAL_DAY_NAMES[local_time.weekday()]
    month_name = CHAT_LOCAL_MONTH_NAMES[local_time.month - 1]
    if local_time.year == today.year:
        return f"{day_name}, {local_time.day} {month_name}"
    return f"{day_name}, {local_time.day} {month_name} {local_time.year}"


def _format_presence_status(value, is_online=False):
    if is_online:
        return "Online sekarang"

    local_time = _to_chat_local_time(value)
    if not local_time:
        return "Offline"

    now_local = _chat_local_now()
    delta_seconds = max(int((now_local - local_time).total_seconds()), 0)

    if delta_seconds < 60:
        return "Aktif barusan"
    if delta_seconds < 3600:
        minutes = max(delta_seconds // 60, 1)
        return f"Aktif {minutes} m lalu"
    if local_time.date() == now_local.date():
        return f"Aktif {local_time.strftime('%H:%M')}"
    if local_time.date() == now_local.date() - timedelta(days=1):
        return f"Aktif kemarin {local_time.strftime('%H:%M')}"
    return f"Aktif {local_time.strftime('%d/%m %H:%M')}"


def _format_timestamp_label(value):
    raw = str(value or "").strip()
    if not raw:
        return "-"

    normalized = raw.replace("T", " ")
    if len(normalized) == 16:
        normalized = f"{normalized}:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return raw[:16] if len(raw) >= 16 else raw

    local_time = parsed + timedelta(hours=CHAT_DISPLAY_UTC_OFFSET_HOURS)
    local_today = (datetime.now(timezone.utc) + timedelta(hours=CHAT_DISPLAY_UTC_OFFSET_HOURS)).date()
    if local_time.date() == local_today:
        return local_time.strftime("%H:%M")
    if local_time.year == local_today.year:
        return local_time.strftime("%d/%m %H:%M")
    return local_time.strftime("%d/%m/%Y %H:%M")


def _format_file_size(size_bytes):
    try:
        size = max(int(size_bytes or 0), 0)
    except (TypeError, ValueError):
        size = 0

    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _serialize_reply_preview(row):
    item = dict(row)
    return {
        "id": int(item["id"]),
        "sender_name": item.get("sender_name") or "User",
        "sender_initials": _get_initials(item.get("sender_name")),
        "message_type": (item.get("message_type") or "text").strip().lower(),
        "preview": _build_message_preview(item, 84),
        "call_label": _call_label_for_mode(item.get("call_mode")),
    }


def _get_chat_attachment_max_bytes():
    configured = current_app.config.get("CHAT_ATTACHMENT_MAX_BYTES", 10 * 1024 * 1024)
    try:
        return max(int(configured), 0)
    except (TypeError, ValueError):
        return 10 * 1024 * 1024


def _sticker_meta(code):
    return CHAT_STICKER_MAP.get(code or "", {"code": "", "emoji": "\U0001F7E6", "label": "Sticker"})


def _custom_sticker_meta(message):
    attachment_name = (message.get("attachment_name") or "").strip()
    attachment_stem = os.path.splitext(attachment_name)[0].replace("_", " ").replace("-", " ").strip()
    label = (message.get("body") or "").strip() or attachment_stem or "Sticker Gambar"
    return {
        "code": "custom",
        "emoji": "\U0001F5BC\uFE0F",
        "label": _clip_text(label, 32) or "Sticker Gambar",
        "is_custom": True,
    }


def _message_sticker_meta(message):
    if (message.get("attachment_path") or "").strip() or (message.get("attachment_name") or "").strip():
        return _custom_sticker_meta(message)
    item = dict(_sticker_meta(message.get("sticker_code")))
    item["is_custom"] = False
    return item


def _build_message_preview(message, limit=120):
    data = dict(message) if isinstance(message, sqlite3.Row) else (message or {})
    message_type = (data.get("message_type") or "text").strip().lower()
    if message_type == "attachment":
        attachment_name = data.get("attachment_name") or "Lampiran"
        caption = (data.get("body") or "").strip()
        preview = f"Lampiran: {attachment_name}"
        if caption:
            preview = f"{preview} - {caption}"
        return _clip_text(preview, limit)
    if message_type == "sticker":
        if (data.get("attachment_name") or "").strip():
            return _clip_text("Sticker Gambar", limit)
        sticker = _sticker_meta(data.get("sticker_code"))
        return _clip_text(f"{sticker['emoji']} Sticker {sticker['label']}", limit)
    if message_type == "call":
        call_mode = "Video Call" if (data.get("call_mode") or "").lower() == "video" else "Telp"
        body = (data.get("body") or "").strip() or f"Permintaan {call_mode}"
        return _clip_text(body, limit)
    return _clip_text(data.get("body") or "Pesan baru", limit)


def _chat_access_denied_redirect():
    if has_permission(session.get("role"), "view_schedule"):
        return redirect("/schedule/")
    return redirect("/")


def _require_chat_view():
    if has_permission(session.get("role"), "view_chat"):
        return True
    flash("Akses chat internal ditolak.", "error")
    return False


def _require_chat_manage():
    if has_permission(session.get("role"), "manage_chat"):
        return True
    flash("Anda tidak punya akses untuk mengirim chat.", "error")
    return False


def _fetch_current_user(db):
    row = db.execute(
        """
        SELECT u.id, u.username, u.role, u.phone, u.warehouse_id, w.name AS warehouse_name
        FROM users u
        LEFT JOIN warehouses w ON w.id = u.warehouse_id
        WHERE u.id=?
        """,
        (session.get("user_id"),),
    ).fetchone()
    return dict(row) if row else None


def _fetch_contact_row(db, user_id):
    row = db.execute(
        """
        SELECT u.id, u.username, u.role, u.phone, u.warehouse_id, w.name AS warehouse_name
        FROM users u
        LEFT JOIN warehouses w ON w.id = u.warehouse_id
        WHERE u.id=?
        """,
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def _serialize_contact(row):
    data = dict(row)
    data["is_online"] = bool(data.get("is_online"))
    data["is_leader"] = data.get("role") == "leader"
    data["is_same_warehouse"] = bool(data.get("is_same_warehouse"))
    data["initials"] = _get_initials(data.get("username"))
    data["status_label"] = _format_presence_status(data.get("last_seen_at"), data["is_online"])
    data["role_label"] = (data.get("role") or "-").replace("_", " ").title()
    data["warehouse_label"] = data.get("warehouse_name") or "Global"
    data["search_blob"] = " ".join(
        [
            data.get("username") or "",
            data.get("role_label") or "",
            data.get("warehouse_label") or "",
            "leader" if data["is_leader"] else "",
            "online" if data["is_online"] else "",
        ]
    ).strip()
    return data


def _fetch_contacts(db, current_user):
    current_warehouse_id = current_user.get("warehouse_id")
    rows = db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.role,
            u.phone,
            u.warehouse_id,
            w.name AS warehouse_name,
            CASE WHEN up.last_seen_at >= datetime('now', ?) THEN 1 ELSE 0 END AS is_online,
            CASE WHEN u.role='leader' THEN 1 ELSE 0 END AS is_leader,
            CASE WHEN ? IS NOT NULL AND u.warehouse_id=? THEN 1 ELSE 0 END AS is_same_warehouse,
            up.current_path,
            up.last_seen_at
        FROM users u
        LEFT JOIN warehouses w ON w.id = u.warehouse_id
        LEFT JOIN user_presence up ON up.user_id = u.id
        WHERE u.id != ?
        ORDER BY
            CASE WHEN u.role='leader' THEN 0 ELSE 1 END,
            CASE WHEN up.last_seen_at >= datetime('now', ?) THEN 0 ELSE 1 END,
            CASE WHEN ? IS NOT NULL AND u.warehouse_id=? THEN 0 ELSE 1 END,
            LOWER(u.username) ASC
        """,
        (
            f"-{ONLINE_WINDOW_SECONDS} seconds",
            current_warehouse_id,
            current_warehouse_id,
            current_user["id"],
            f"-{ONLINE_WINDOW_SECONDS} seconds",
            current_warehouse_id,
            current_warehouse_id,
        ),
    ).fetchall()
    return [_serialize_contact(row) for row in rows]


def _serialize_current_user(current_user):
    if not current_user:
        return None
    return {
        "id": int(current_user["id"]),
        "username": current_user["username"],
        "role": current_user["role"],
        "role_label": (current_user.get("role") or "-").replace("_", " ").title(),
        "warehouse_name": current_user.get("warehouse_name") or "Global",
        "initials": _get_initials(current_user.get("username")),
    }


def _fetch_thread_summaries(db, current_user_id, thread_id=None):
    rows = db.execute(
        """
        SELECT
            t.id,
            t.direct_key,
            COALESCE(t.thread_type, 'direct') AS thread_type,
            t.group_name,
            t.group_description,
            t.created_at,
            t.last_message_at,
            member.last_read_message_id,
            COALESCE(member.is_pinned, 0) AS is_pinned,
            member.pinned_at,
            last_msg.id AS last_message_id,
            last_msg.body AS last_message_body,
            last_msg.created_at AS last_message_created_at,
            last_msg.sender_id AS last_message_sender_id,
            last_msg.message_type AS last_message_type,
            last_msg.attachment_name AS last_attachment_name,
            last_msg.sticker_code AS last_sticker_code,
            last_msg.call_mode AS last_call_mode
        FROM chat_threads t
        JOIN chat_thread_members member
          ON member.thread_id = t.id
         AND member.user_id = ?
        LEFT JOIN chat_messages last_msg
          ON last_msg.id = (
              SELECT id
              FROM chat_messages
              WHERE thread_id = t.id
              ORDER BY id DESC
              LIMIT 1
          )
        WHERE (? IS NULL OR t.id = ?)
        ORDER BY
            CASE WHEN COALESCE(member.is_pinned, 0) = 1 THEN 0 ELSE 1 END,
            CASE
                WHEN COALESCE(member.is_pinned, 0) = 1 THEN COALESCE(member.pinned_at, t.last_message_at, t.created_at)
                ELSE COALESCE(t.last_message_at, t.created_at)
            END DESC,
            t.id DESC
        """,
        (current_user_id, thread_id, thread_id),
    ).fetchall()

    if not rows:
        return []

    thread_ids = [int(row["id"]) for row in rows]
    placeholders = ",".join("?" for _ in thread_ids)

    participant_rows = db.execute(
        f"""
        SELECT
            member.thread_id,
            u.id,
            u.username,
            u.role,
            u.phone,
            w.name AS warehouse_name,
            CASE WHEN up.last_seen_at >= datetime('now', ?) THEN 1 ELSE 0 END AS is_online,
            CASE WHEN u.id=? THEN 1 ELSE 0 END AS is_current
        FROM chat_thread_members member
        JOIN users u ON u.id = member.user_id
        LEFT JOIN warehouses w ON w.id = u.warehouse_id
        LEFT JOIN user_presence up ON up.user_id = u.id
        WHERE member.thread_id IN ({placeholders})
        ORDER BY LOWER(u.username) ASC
        """,
        [f"-{ONLINE_WINDOW_SECONDS} seconds", current_user_id, *thread_ids],
    ).fetchall()

    participants_by_thread = {}
    for participant_row in participant_rows:
        participant = dict(participant_row)
        participant["is_online"] = bool(participant.get("is_online"))
        participant["is_current"] = bool(participant.get("is_current"))
        participant["initials"] = _get_initials(participant.get("username"))
        participant["role_label"] = (participant.get("role") or "-").replace("_", " ").title()
        participant["warehouse_label"] = participant.get("warehouse_name") or "Global"
        participants_by_thread.setdefault(participant["thread_id"], []).append(participant)

    unread_rows = db.execute(
        f"""
        SELECT cm.thread_id, COUNT(*) AS unread_count
        FROM chat_messages cm
        JOIN chat_thread_members member
          ON member.thread_id = cm.thread_id
         AND member.user_id = ?
        WHERE cm.sender_id != ?
          AND cm.id > COALESCE(member.last_read_message_id, 0)
          AND cm.thread_id IN ({placeholders})
        GROUP BY cm.thread_id
        """,
        [current_user_id, current_user_id, *thread_ids],
    ).fetchall()
    unread_map = {int(row["thread_id"]): int(row["unread_count"] or 0) for row in unread_rows}

    threads = []
    for row in rows:
        item = dict(row)
        participants = participants_by_thread.get(item["id"], [])
        others = [participant for participant in participants if not participant.get("is_current")]
        item["thread_type"] = (item.get("thread_type") or "direct").strip().lower()
        item["is_pinned"] = bool(item.get("is_pinned"))
        item["participants"] = participants
        item["member_count"] = len(participants)
        item["online_count"] = sum(1 for participant in others if participant.get("is_online"))
        item["unread_count"] = unread_map.get(int(item["id"]), 0)
        item["last_message_preview"] = _build_message_preview(
            {
                "body": item.get("last_message_body"),
                "message_type": item.get("last_message_type"),
                "attachment_name": item.get("last_attachment_name"),
                "sticker_code": item.get("last_sticker_code"),
                "call_mode": item.get("last_call_mode"),
            }
        )
        item["last_message_label"] = _format_timestamp_label(
            item.get("last_message_created_at") or item.get("last_message_at") or item.get("created_at")
        )
        item["last_message_prefix"] = "Anda: " if item.get("last_message_sender_id") == current_user_id else ""

        if item["thread_type"] == "group":
            group_name = (item.get("group_name") or "").strip()
            if not group_name:
                fallback_names = [participant.get("username") for participant in others[:3] if participant.get("username")]
                group_name = "Grup " + ", ".join(fallback_names) if fallback_names else "Grup Baru"
            warehouse_labels = []
            for participant in others:
                label = participant.get("warehouse_label") or "Global"
                if label not in warehouse_labels:
                    warehouse_labels.append(label)
            if len(warehouse_labels) <= 2:
                warehouse_label = " / ".join(warehouse_labels) if warehouse_labels else "Global"
            else:
                warehouse_label = " / ".join(warehouse_labels[:2]) + f" +{len(warehouse_labels) - 2}"
            item["partner_id"] = None
            item["partner_name"] = group_name
            item["partner_role"] = "group"
            item["partner_phone"] = None
            item["partner_online"] = item["online_count"] > 0
            item["partner_initials"] = _get_initials(group_name)
            item["partner_role_label"] = f"Grup | {item['member_count']} member"
            item["partner_warehouse_label"] = warehouse_label
            item["partner_status_label"] = (
                f"{item['online_count']} online"
                if item["online_count"] > 0
                else "Semua offline"
            )
            item["search_blob"] = " ".join(
                [group_name, item.get("group_description") or "", " ".join(participant.get("username") or "" for participant in participants), item["last_message_preview"]]
            ).strip()
        else:
            partner = others[0] if others else {}
            item["partner_id"] = partner.get("id")
            item["partner_name"] = partner.get("username") or "-"
            item["partner_role"] = partner.get("role")
            item["partner_phone"] = partner.get("phone")
            item["partner_online"] = bool(partner.get("is_online"))
            item["partner_initials"] = partner.get("initials") or _get_initials(partner.get("username"))
            item["partner_role_label"] = partner.get("role_label") or "-"
            item["partner_warehouse_label"] = partner.get("warehouse_label") or "Global"
            item["partner_status_label"] = _format_presence_status(
                partner.get("last_seen_at"),
                bool(partner.get("is_online")),
            )
            item["search_blob"] = " ".join(
                [item.get("partner_name") or "", item["partner_role_label"], item["partner_warehouse_label"], item["last_message_preview"]]
            ).strip()
        threads.append(item)

    return threads


def _user_can_access_thread(db, current_user_id, thread_id):
    if not thread_id:
        return False

    row = db.execute(
        """
        SELECT 1
        FROM chat_thread_members
        WHERE thread_id=? AND user_id=?
        LIMIT 1
        """,
        (thread_id, current_user_id),
    ).fetchone()
    return bool(row)


def _fetch_reply_preview_map(db, reply_ids):
    unique_reply_ids = sorted({int(reply_id) for reply_id in reply_ids if reply_id})
    if not unique_reply_ids:
        return {}

    rows = db.execute(
        f"""
        SELECT
            cm.id,
            cm.body,
            cm.message_type,
            cm.attachment_name,
            cm.sticker_code,
            cm.call_mode,
            sender.username AS sender_name
        FROM chat_messages cm
        JOIN users sender ON sender.id = cm.sender_id
        WHERE cm.id IN ({",".join("?" for _ in unique_reply_ids)})
        """,
        tuple(unique_reply_ids),
    ).fetchall()
    return {
        int(row["id"]): _serialize_reply_preview(row)
        for row in rows
    }


def _serialize_chat_message_rows(db, rows, current_user_id):
    raw_rows = [dict(row) for row in rows]
    reply_preview_map = _fetch_reply_preview_map(
        db,
        [_to_int(item.get("reply_to_message_id")) for item in raw_rows],
    )

    messages = []
    for item in raw_rows:
        item["message_type"] = (item.get("message_type") or "text").strip().lower()
        item["is_mine"] = item.get("sender_id") == current_user_id
        item["sender_initials"] = _get_initials(item.get("sender_name"))
        item["created_label"] = _format_timestamp_label(item.get("created_at"))
        local_time = _to_chat_local_time(item.get("created_at"))
        item["day_key"] = local_time.strftime("%Y-%m-%d") if local_time else str(item.get("created_at") or "")[:10]
        item["day_label"] = _format_chat_day_label(item.get("created_at"))
        item["preview"] = _build_message_preview(item, 80)
        item["sticker"] = _message_sticker_meta(item) if item["message_type"] == "sticker" else None
        item["call_label"] = "Video Call" if item.get("call_mode") == "video" else "Telp"
        if item.get("attachment_path"):
            item["attachment_url"] = f"{current_app.config['CHAT_UPLOAD_URL_PREFIX'].rstrip('/')}/{item['attachment_path']}"
        else:
            item["attachment_url"] = ""
        item["sticker_image_url"] = item["attachment_url"] if item["message_type"] == "sticker" else ""
        item["attachment_size_label"] = _format_file_size(item.get("attachment_size"))
        reply_to_message_id = _to_int(item.get("reply_to_message_id"))
        item["reply_to_message_id"] = reply_to_message_id
        item["reply_preview"] = reply_preview_map.get(reply_to_message_id)
        messages.append(item)
    return messages


def _fetch_messages_by_ids(db, thread_id, current_user_id, message_ids):
    unique_message_ids = sorted({int(message_id) for message_id in message_ids if message_id})
    if not unique_message_ids:
        return []

    rows = db.execute(
        f"""
        SELECT
            cm.id,
            cm.thread_id,
            cm.sender_id,
            sender.username AS sender_name,
            sender.role AS sender_role,
            cm.body,
            cm.message_type,
            cm.attachment_name,
            cm.attachment_path,
            cm.attachment_mime,
            cm.attachment_size,
            cm.sticker_code,
            cm.call_mode,
            cm.reply_to_message_id,
            cm.created_at
        FROM chat_messages cm
        JOIN users sender ON sender.id = cm.sender_id
        WHERE cm.thread_id=?
          AND cm.id IN ({",".join("?" for _ in unique_message_ids)})
        ORDER BY cm.id ASC
        """,
        (thread_id, *unique_message_ids),
    ).fetchall()
    return _serialize_chat_message_rows(db, rows, current_user_id)


def _fetch_messages(db, thread_id, current_user_id, after_message_id=0):
    after_message_id = max(after_message_id or 0, 0)
    if after_message_id:
        rows = db.execute(
            """
            SELECT
                cm.id,
                cm.thread_id,
                cm.sender_id,
                sender.username AS sender_name,
                sender.role AS sender_role,
                cm.body,
                cm.message_type,
                cm.attachment_name,
                cm.attachment_path,
                cm.attachment_mime,
                cm.attachment_size,
                cm.sticker_code,
                cm.call_mode,
                cm.reply_to_message_id,
                cm.created_at
            FROM chat_messages cm
            JOIN users sender ON sender.id = cm.sender_id
            WHERE cm.thread_id=?
              AND cm.id > ?
            ORDER BY cm.id ASC
            LIMIT ?
            """,
            (thread_id, after_message_id, POLL_MESSAGE_LIMIT),
        ).fetchall()
    else:
        rows = db.execute(
            """
            SELECT *
            FROM (
                SELECT
                    cm.id,
                    cm.thread_id,
                    cm.sender_id,
                    sender.username AS sender_name,
                    sender.role AS sender_role,
                    cm.body,
                    cm.message_type,
                    cm.attachment_name,
                    cm.attachment_path,
                    cm.attachment_mime,
                    cm.attachment_size,
                    cm.sticker_code,
                    cm.call_mode,
                    cm.reply_to_message_id,
                    cm.created_at
                FROM chat_messages cm
                JOIN users sender ON sender.id = cm.sender_id
                WHERE cm.thread_id=?
                ORDER BY cm.id DESC
                LIMIT ?
            )
            ORDER BY id ASC
            """,
            (thread_id, INITIAL_MESSAGE_LIMIT),
        ).fetchall()

    return _serialize_chat_message_rows(db, rows, current_user_id)


def _mark_thread_read(db, thread_id, current_user_id):
    latest = db.execute(
        "SELECT COALESCE(MAX(id), 0) AS last_id FROM chat_messages WHERE thread_id=?",
        (thread_id,),
    ).fetchone()
    last_id = int(latest["last_id"] if latest else 0)

    if last_id > 0:
        db.execute(
            """
            UPDATE chat_thread_members
            SET last_read_message_id=?,
                last_read_at=CURRENT_TIMESTAMP
            WHERE thread_id=?
              AND user_id=?
              AND COALESCE(last_read_message_id, 0) < ?
            """,
            (last_id, thread_id, current_user_id, last_id),
        )
    else:
        db.execute(
            """
            UPDATE chat_thread_members
            SET last_read_at=CURRENT_TIMESTAMP
            WHERE thread_id=? AND user_id=?
            """,
            (thread_id, current_user_id),
        )
    return last_id


def _compute_unread_total(db, current_user_id):
    row = db.execute(
        """
        SELECT COALESCE(COUNT(*), 0) AS unread_total
        FROM chat_messages cm
        JOIN chat_thread_members member
          ON member.thread_id = cm.thread_id
         AND member.user_id = ?
        WHERE cm.sender_id != ?
          AND cm.id > COALESCE(member.last_read_message_id, 0)
        """,
        (current_user_id, current_user_id),
    ).fetchone()
    return int(row["unread_total"] if row else 0)


def _set_thread_pin_state(db, thread_id, current_user_id, pinned=None):
    membership = db.execute(
        """
        SELECT COALESCE(is_pinned, 0) AS is_pinned
        FROM chat_thread_members
        WHERE thread_id=? AND user_id=?
        LIMIT 1
        """,
        (thread_id, current_user_id),
    ).fetchone()
    if not membership:
        raise ValueError("Thread chat tidak ditemukan")

    current_state = bool(membership["is_pinned"])
    next_state = (not current_state) if pinned is None else bool(pinned)
    db.execute(
        """
        UPDATE chat_thread_members
        SET is_pinned=?,
            pinned_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE NULL END
        WHERE thread_id=? AND user_id=?
        """,
        (1 if next_state else 0, 1 if next_state else 0, thread_id, current_user_id),
    )
    return next_state


def _build_thread_search_terms(raw_query):
    return [term for term in dict.fromkeys(str(raw_query or "").strip().lower().split()) if term]


def _search_thread_messages(db, thread_id, query, limit=CHAT_THREAD_SEARCH_LIMIT):
    terms = _build_thread_search_terms(query)
    if not terms:
        return []

    filters = []
    params = [thread_id]
    for term in terms:
        like_term = f"%{term}%"
        filters.append(
            """
            (
                LOWER(COALESCE(cm.body, '')) LIKE ?
                OR LOWER(COALESCE(cm.attachment_name, '')) LIKE ?
                OR LOWER(COALESCE(cm.sticker_code, '')) LIKE ?
            )
            """
        )
        params.extend([like_term, like_term, like_term])

    params.append(max(int(limit or CHAT_THREAD_SEARCH_LIMIT), 1))
    rows = db.execute(
        f"""
        SELECT
            cm.id,
            cm.sender_id,
            sender.username AS sender_name,
            cm.body,
            cm.message_type,
            cm.attachment_name,
            cm.sticker_code,
            cm.call_mode,
            cm.created_at
        FROM chat_messages cm
        JOIN users sender ON sender.id = cm.sender_id
        WHERE cm.thread_id=?
          AND {" AND ".join(filters)}
        ORDER BY cm.id DESC
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()

    return [
        {
            "id": int(row["id"]),
            "sender_name": row["sender_name"],
            "sender_initials": _get_initials(row["sender_name"]),
            "created_at": row["created_at"],
            "created_label": _format_timestamp_label(row["created_at"]),
            "preview": _build_message_preview(row, 120),
            "message_type": (row["message_type"] or "text").strip().lower(),
        }
        for row in rows
    ]


def _fetch_thread_message_focus_context(db, thread_id, current_user_id, focus_message_id, window=CHAT_MESSAGE_FOCUS_WINDOW):
    focus_message_id = _to_int(focus_message_id)
    if not focus_message_id:
        return []

    focus_row = db.execute(
        "SELECT id FROM chat_messages WHERE thread_id=? AND id=? LIMIT 1",
        (thread_id, focus_message_id),
    ).fetchone()
    if not focus_row:
        return []

    before_ids = [
        int(row["id"])
        for row in db.execute(
            """
            SELECT id
            FROM chat_messages
            WHERE thread_id=? AND id<=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (thread_id, focus_message_id, max(int(window or CHAT_MESSAGE_FOCUS_WINDOW), 1)),
        ).fetchall()
    ]
    after_ids = [
        int(row["id"])
        for row in db.execute(
            """
            SELECT id
            FROM chat_messages
            WHERE thread_id=? AND id>?
            ORDER BY id ASC
            LIMIT ?
            """,
            (thread_id, focus_message_id, max(int(window or CHAT_MESSAGE_FOCUS_WINDOW), 1)),
        ).fetchall()
    ]
    return _fetch_messages_by_ids(db, thread_id, current_user_id, before_ids + after_ids)


def _fetch_thread_typing_state(db, thread_id, current_user_id):
    rows = db.execute(
        """
        SELECT u.id, u.username
        FROM user_presence up
        JOIN users u ON u.id = up.user_id
        JOIN chat_thread_members member
          ON member.thread_id = ?
         AND member.user_id = u.id
        WHERE up.typing_thread_id=?
          AND up.typing_until >= CURRENT_TIMESTAMP
          AND u.id != ?
        ORDER BY up.typing_until DESC, LOWER(u.username) ASC
        LIMIT 3
        """,
        (thread_id, thread_id, current_user_id),
    ).fetchall()

    users = [
        {
            "id": int(row["id"]),
            "username": row["username"],
            "initials": _get_initials(row["username"]),
        }
        for row in rows
    ]
    if not users:
        return {"users": [], "label": ""}
    if len(users) == 1:
        label = f"{users[0]['username']} sedang mengetik..."
    elif len(users) == 2:
        label = f"{users[0]['username']} dan {users[1]['username']} sedang mengetik..."
    else:
        label = f"{users[0]['username']}, {users[1]['username']}, dan lainnya sedang mengetik..."
    return {"users": users, "label": label}


def _fetch_incoming_messages(db, current_user_id, since_message_id):
    rows = db.execute(
        """
        SELECT
            cm.id,
            cm.thread_id,
            cm.body,
            cm.message_type,
            cm.attachment_name,
            cm.sticker_code,
            cm.call_mode,
            cm.created_at,
            sender.username AS sender_name,
            COALESCE(t.thread_type, 'direct') AS thread_type,
            t.group_name
        FROM chat_messages cm
        JOIN chat_thread_members member
          ON member.thread_id = cm.thread_id
         AND member.user_id = ?
        JOIN users sender ON sender.id = cm.sender_id
        JOIN chat_threads t ON t.id = cm.thread_id
        WHERE cm.sender_id != ?
          AND cm.id > ?
          AND cm.id > COALESCE(member.last_read_message_id, 0)
        ORDER BY cm.id ASC
        LIMIT ?
        """,
        (current_user_id, current_user_id, max(since_message_id or 0, 0), INCOMING_TOAST_LIMIT),
    ).fetchall()

    incoming = []
    latest_id = max(since_message_id or 0, 0)
    for row in rows:
        item = dict(row)
        latest_id = max(latest_id, int(item["id"]))
        incoming.append(
            {
                "id": int(item["id"]),
                "thread_id": int(item["thread_id"]),
                "sender_name": item["sender_name"],
                "thread_label": item["group_name"] if item.get("thread_type") == "group" else item["sender_name"],
                "preview": _build_message_preview(item, 80),
                "created_at": item["created_at"],
                "created_label": _format_timestamp_label(item["created_at"]),
            }
        )
    return incoming, latest_id


def _get_or_create_direct_thread(db, current_user_id, target_user_id):
    left_id, right_id = sorted([int(current_user_id), int(target_user_id)])
    direct_key = f"{left_id}:{right_id}"

    thread = db.execute(
        "SELECT id FROM chat_threads WHERE direct_key=?",
        (direct_key,),
    ).fetchone()

    if thread:
        thread_id = int(thread["id"])
    else:
        cursor = db.execute(
            """
            INSERT INTO chat_threads(direct_key, thread_type, created_by)
            VALUES (?, 'direct', ?)
            """,
            (direct_key, current_user_id),
        )
        thread_id = int(cursor.lastrowid)

    for user_id in (left_id, right_id):
        db.execute(
            """
            INSERT OR IGNORE INTO chat_thread_members(thread_id, user_id)
            VALUES (?, ?)
            """,
            (thread_id, user_id),
        )

    return thread_id


def _create_group_thread(db, current_user_id, group_name, member_ids, description=""):
    unique_members = {int(current_user_id)}
    for member_id in member_ids:
        parsed = _to_int(member_id)
        if parsed and parsed != int(current_user_id):
            unique_members.add(parsed)

    if len(unique_members) < 3:
        raise ValueError("Minimal pilih dua member lain untuk membuat grup")

    rows = db.execute(
        f"SELECT id FROM users WHERE id IN ({','.join('?' for _ in unique_members)})",
        tuple(unique_members),
    ).fetchall()
    found_ids = {int(row["id"]) for row in rows}
    if found_ids != unique_members:
        raise ValueError("Ada member grup yang tidak valid")

    cursor = db.execute(
        """
        INSERT INTO chat_threads(direct_key, thread_type, group_name, group_description, created_by)
        VALUES (?, 'group', ?, ?, ?)
        """,
        (f"group:{uuid4().hex}", group_name.strip(), (description or "").strip(), current_user_id),
    )
    thread_id = int(cursor.lastrowid)

    for user_id in sorted(unique_members):
        db.execute(
            "INSERT INTO chat_thread_members(thread_id, user_id) VALUES (?, ?)",
            (thread_id, user_id),
        )

    db.execute(
        """
        INSERT INTO chat_messages(thread_id, sender_id, body, message_type)
        VALUES (?, ?, ?, 'text')
        """,
        (thread_id, current_user_id, f"Grup {group_name.strip()} dibuat dan siap dipakai."),
    )
    db.execute(
        """
        UPDATE chat_threads
        SET last_message_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (thread_id,),
    )
    return thread_id


def _store_chat_upload(file_storage, allowed_extensions, invalid_type_message, prefix=""):
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        raise ValueError("File lampiran tidak valid")

    extension = os.path.splitext(filename)[1].lower()
    if extension not in allowed_extensions:
        raise ValueError(invalid_type_message)

    upload_folder = current_app.config["CHAT_UPLOAD_FOLDER"]
    os.makedirs(upload_folder, exist_ok=True)

    stored_name = f"{prefix}{uuid4().hex}{extension}"
    target_path = os.path.join(upload_folder, stored_name)
    file_storage.save(target_path)
    attachment_size = os.path.getsize(target_path)
    max_bytes = _get_chat_attachment_max_bytes()
    if max_bytes and attachment_size > max_bytes:
        try:
            os.remove(target_path)
        except OSError:
            pass
        raise ValueError(f"Ukuran lampiran maksimal {_format_file_size(max_bytes)} per file")

    return {
        "attachment_name": filename,
        "attachment_path": stored_name,
        "attachment_mime": (file_storage.mimetype or "").strip(),
        "attachment_size": attachment_size,
    }


def _store_chat_attachment(file_storage):
    return _store_chat_upload(
        file_storage,
        ALLOWED_ATTACHMENT_EXTENSIONS,
        "Format file belum didukung untuk chat",
    )


def _store_chat_sticker_image(file_storage):
    return _store_chat_upload(
        file_storage,
        ALLOWED_STICKER_IMAGE_EXTENSIONS,
        "Sticker custom hanya mendukung file gambar PNG, JPG, GIF, atau WEBP",
        prefix="sticker-",
    )


def _insert_chat_message(db, thread_id, sender_id, body, message_type, extra):
    cursor = db.execute(
        """
        INSERT INTO chat_messages(
            thread_id,
            sender_id,
            body,
            message_type,
            attachment_name,
            attachment_path,
            attachment_mime,
            attachment_size,
            sticker_code,
            call_mode
            ,
            reply_to_message_id
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            thread_id,
            sender_id,
            body,
            message_type,
            extra.get("attachment_name"),
            extra.get("attachment_path"),
            extra.get("attachment_mime"),
            int(extra.get("attachment_size") or 0),
            extra.get("sticker_code"),
            extra.get("call_mode"),
            _to_int(extra.get("reply_to_message_id")),
        ),
    )
    message_id = int(cursor.lastrowid)

    db.execute(
        """
        UPDATE chat_threads
        SET last_message_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (thread_id,),
    )
    db.execute(
        """
        UPDATE chat_thread_members
        SET last_read_message_id=?,
            last_read_at=CURRENT_TIMESTAMP
        WHERE thread_id=? AND user_id=?
        """,
        (message_id, thread_id, sender_id),
    )
    db.execute(
        """
        UPDATE user_presence
        SET active_thread_id=?,
            typing_thread_id=NULL,
            typing_until=NULL,
            last_seen_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP
        WHERE user_id=?
        """,
        (thread_id, sender_id),
    )
    return message_id


def _call_label_for_mode(call_mode):
    return "Video Call" if (call_mode or "").lower() == "video" else "Telp"


def _parse_signal_payload(raw_payload):
    if not raw_payload:
        return {}
    try:
        parsed = json.loads(raw_payload)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _expire_stale_calls(db):
    db.execute(
        """
        UPDATE chat_call_sessions
        SET status='missed',
            ended_at=COALESCE(ended_at, CURRENT_TIMESTAMP),
            last_signal_at=CURRENT_TIMESTAMP
        WHERE status IN ('pending', 'ringing', 'connecting')
          AND COALESCE(last_signal_at, started_at) <= datetime('now', ?)
        """,
        (f"-{CALL_RING_TIMEOUT_SECONDS} seconds",),
    )


def _serialize_call_session(row, current_user_id):
    item = dict(row)
    is_initiator = int(item["initiator_id"]) == int(current_user_id)
    partner_prefix = "receiver" if is_initiator else "initiator"
    partner_name = item.get(f"{partner_prefix}_name") or "-"
    partner_role = item.get(f"{partner_prefix}_role") or "-"
    partner_warehouse_name = item.get(f"{partner_prefix}_warehouse_name") or "Global"

    return {
        "id": int(item["id"]),
        "thread_id": int(item["thread_id"]),
        "initiator_id": int(item["initiator_id"]),
        "receiver_id": int(item["receiver_id"]),
        "call_mode": (item.get("call_mode") or "voice").strip().lower(),
        "call_label": _call_label_for_mode(item.get("call_mode")),
        "status": (item.get("status") or "pending").strip().lower(),
        "started_at": item.get("started_at"),
        "started_label": _format_timestamp_label(item.get("started_at")),
        "answered_at": item.get("answered_at"),
        "ended_at": item.get("ended_at"),
        "thread_type": (item.get("thread_type") or "direct").strip().lower(),
        "is_initiator": is_initiator,
        "can_accept": (not is_initiator) and (item.get("status") in {"pending", "ringing"}),
        "partner_id": int(item["receiver_id"] if is_initiator else item["initiator_id"]),
        "partner_name": partner_name,
        "partner_initials": _get_initials(partner_name),
        "partner_role_label": partner_role.replace("_", " ").title(),
        "partner_warehouse_label": partner_warehouse_name,
    }


def _fetch_call_session_row(db, call_id, current_user_id=None):
    _expire_stale_calls(db)
    params = [call_id]
    scope_sql = ""
    if current_user_id is not None:
        scope_sql = " AND (? IN (cs.initiator_id, cs.receiver_id))"
        params.append(current_user_id)

    row = db.execute(
        f"""
        SELECT
            cs.*,
            COALESCE(t.thread_type, 'direct') AS thread_type,
            initiator.username AS initiator_name,
            initiator.role AS initiator_role,
            initiator_wh.name AS initiator_warehouse_name,
            receiver.username AS receiver_name,
            receiver.role AS receiver_role,
            receiver_wh.name AS receiver_warehouse_name
        FROM chat_call_sessions cs
        JOIN chat_threads t ON t.id = cs.thread_id
        JOIN users initiator ON initiator.id = cs.initiator_id
        LEFT JOIN warehouses initiator_wh ON initiator_wh.id = initiator.warehouse_id
        JOIN users receiver ON receiver.id = cs.receiver_id
        LEFT JOIN warehouses receiver_wh ON receiver_wh.id = receiver.warehouse_id
        WHERE cs.id=?{scope_sql}
        """,
        tuple(params),
    ).fetchone()
    return dict(row) if row else None


def _fetch_open_call_sessions(db, current_user_id):
    _expire_stale_calls(db)
    placeholders = ",".join("?" for _ in OPEN_CALL_STATUSES)
    rows = db.execute(
        f"""
        SELECT
            cs.*,
            COALESCE(t.thread_type, 'direct') AS thread_type,
            initiator.username AS initiator_name,
            initiator.role AS initiator_role,
            initiator_wh.name AS initiator_warehouse_name,
            receiver.username AS receiver_name,
            receiver.role AS receiver_role,
            receiver_wh.name AS receiver_warehouse_name
        FROM chat_call_sessions cs
        JOIN chat_threads t ON t.id = cs.thread_id
        JOIN users initiator ON initiator.id = cs.initiator_id
        LEFT JOIN warehouses initiator_wh ON initiator_wh.id = initiator.warehouse_id
        JOIN users receiver ON receiver.id = cs.receiver_id
        LEFT JOIN warehouses receiver_wh ON receiver_wh.id = receiver.warehouse_id
        WHERE (cs.initiator_id=? OR cs.receiver_id=?)
          AND cs.status IN ({placeholders})
        ORDER BY
            CASE
                WHEN cs.receiver_id=? AND cs.status IN ('pending', 'ringing') THEN 0
                WHEN cs.status='active' THEN 1
                ELSE 2
            END,
            COALESCE(cs.answered_at, cs.started_at) DESC,
            cs.id DESC
        """,
        (current_user_id, current_user_id, *sorted(OPEN_CALL_STATUSES), current_user_id),
    ).fetchall()
    return [_serialize_call_session(row, current_user_id) for row in rows]


def _find_busy_call(db, user_ids):
    _expire_stale_calls(db)
    unique_user_ids = sorted({int(user_id) for user_id in user_ids if user_id})
    if not unique_user_ids:
        return None
    placeholders = ",".join("?" for _ in unique_user_ids)
    status_placeholders = ",".join("?" for _ in OPEN_CALL_STATUSES)
    row = db.execute(
        f"""
        SELECT id
        FROM chat_call_sessions
        WHERE status IN ({status_placeholders})
          AND (
              initiator_id IN ({placeholders})
              OR receiver_id IN ({placeholders})
          )
        ORDER BY id DESC
        LIMIT 1
        """,
        (*sorted(OPEN_CALL_STATUSES), *unique_user_ids, *unique_user_ids),
    ).fetchone()
    return int(row["id"]) if row else None


def _create_call_session(db, thread_id, initiator_id, receiver_id, call_mode):
    cursor = db.execute(
        """
        INSERT INTO chat_call_sessions(
            thread_id,
            initiator_id,
            receiver_id,
            call_mode,
            status,
            last_signal_at
        )
        VALUES (?, ?, ?, ?, 'ringing', CURRENT_TIMESTAMP)
        """,
        (thread_id, initiator_id, receiver_id, call_mode),
    )
    return int(cursor.lastrowid)


def _insert_call_signal(db, call_id, thread_id, sender_id, recipient_id, signal_type, payload=None):
    if signal_type not in CALL_SIGNAL_TYPES:
        raise ValueError("Signal call tidak valid")

    payload_json = json.dumps(payload or {}, separators=(",", ":"), ensure_ascii=False)
    cursor = db.execute(
        """
        INSERT INTO chat_call_signals(
            call_id,
            thread_id,
            sender_id,
            recipient_id,
            signal_type,
            payload
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (call_id, thread_id, sender_id, recipient_id, signal_type, payload_json),
    )
    db.execute(
        """
        UPDATE chat_call_sessions
        SET last_signal_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (call_id,),
    )
    return int(cursor.lastrowid)


def _update_call_status(db, call_id, status, *, ended_by=None, answered=False):
    updates = ["status=?"]
    params = [status]
    if answered:
        updates.append("answered_at=COALESCE(answered_at, CURRENT_TIMESTAMP)")
    if ended_by is not None:
        updates.append("ended_at=CURRENT_TIMESTAMP")
        updates.append("ended_by=?")
        params.append(ended_by)
    params.append(call_id)
    db.execute(
        f"""
        UPDATE chat_call_sessions
        SET {', '.join(updates)},
            last_signal_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        tuple(params),
    )


def _fetch_call_signals(db, current_user_id, after_signal_id=0):
    _expire_stale_calls(db)
    rows = db.execute(
        """
        SELECT
            signal.id,
            signal.call_id,
            signal.thread_id,
            signal.sender_id,
            signal.recipient_id,
            signal.signal_type,
            signal.payload,
            signal.created_at,
            session.call_mode,
            session.status
        FROM chat_call_signals signal
        JOIN chat_call_sessions session ON session.id = signal.call_id
        WHERE signal.recipient_id=?
          AND signal.id > ?
        ORDER BY signal.id ASC
        LIMIT ?
        """,
        (current_user_id, max(after_signal_id or 0, 0), CALL_SIGNAL_LIMIT),
    ).fetchall()

    signals = []
    latest_signal_id = max(after_signal_id or 0, 0)
    for row in rows:
        item = dict(row)
        signal_id = int(item["id"])
        latest_signal_id = max(latest_signal_id, signal_id)
        signals.append(
            {
                "id": signal_id,
                "call_id": int(item["call_id"]),
                "thread_id": int(item["thread_id"]),
                "sender_id": int(item["sender_id"]),
                "recipient_id": int(item["recipient_id"]),
                "signal_type": item["signal_type"],
                "payload": _parse_signal_payload(item.get("payload")),
                "created_at": item.get("created_at"),
                "call_mode": (item.get("call_mode") or "voice").strip().lower(),
                "status": (item.get("status") or "pending").strip().lower(),
            }
        )
    return signals, latest_signal_id


@chat_bp.route("/")
def chat_page():
    if not _require_chat_view():
        return _chat_access_denied_redirect()

    db = get_db()
    current_user = _fetch_current_user(db)
    if not current_user:
        flash("User chat tidak ditemukan.", "error")
        return redirect("/")

    target_user_id = _to_int(request.args.get("target"))
    if target_user_id:
        target_user = _fetch_contact_row(db, target_user_id)
        if not target_user or target_user["id"] == current_user["id"]:
            flash("Target chat tidak valid.", "error")
            return redirect("/chat/")
        thread_id = _get_or_create_direct_thread(db, current_user["id"], target_user_id)
        return redirect(f"/chat/?thread={thread_id}")

    selected_thread_id = _to_int(request.args.get("thread"))
    focused_message_id = _to_int(request.args.get("focus_message"))
    selected_thread = None

    if selected_thread_id:
        candidate_threads = _fetch_thread_summaries(db, current_user["id"], selected_thread_id)
        selected_thread = candidate_threads[0] if candidate_threads else None

    if selected_thread:
        _mark_thread_read(db, selected_thread["id"], current_user["id"])

    threads = _fetch_thread_summaries(db, current_user["id"])
    if not selected_thread and threads:
        selected_thread = threads[0]
        _mark_thread_read(db, selected_thread["id"], current_user["id"])
        threads = _fetch_thread_summaries(db, current_user["id"])

    if selected_thread:
        selected_thread = next((thread for thread in threads if thread["id"] == selected_thread["id"]), selected_thread)
        typing_state = _fetch_thread_typing_state(db, selected_thread["id"], current_user["id"])
        selected_thread["typing_users"] = typing_state["users"]
        selected_thread["typing_label"] = typing_state["label"]

    if selected_thread:
        if focused_message_id:
            messages = _fetch_thread_message_focus_context(
                db,
                selected_thread["id"],
                current_user["id"],
                focused_message_id,
            ) or _fetch_messages(db, selected_thread["id"], current_user["id"])
        else:
            messages = _fetch_messages(db, selected_thread["id"], current_user["id"])
    else:
        messages = []
    contacts = _fetch_contacts(db, current_user)
    unread_total = _compute_unread_total(db, current_user["id"])
    auto_start_call_mode = ((request.args.get("call") or "").strip().lower()) or None
    if auto_start_call_mode not in SUPPORTED_CALL_MODES:
        auto_start_call_mode = None

    auto_pickup_call_id = _to_int(request.args.get("pickup_call"))
    if auto_pickup_call_id:
        call_scope = _fetch_call_session_row(db, auto_pickup_call_id, current_user["id"])
        if not call_scope or int(call_scope["thread_id"]) != int(selected_thread["id"] if selected_thread else 0):
            auto_pickup_call_id = None

    summary = {
        "threads": len(threads),
        "leaders": sum(1 for contact in contacts if contact["is_leader"]),
        "online": sum(1 for contact in contacts if contact["is_online"]),
        "unread": unread_total,
        "groups": sum(1 for thread in threads if thread.get("thread_type") == "group"),
    }

    return render_template(
        "chat.html",
        current_user=current_user,
        threads=threads,
        contacts=contacts,
        selected_thread=selected_thread,
        messages=messages,
        stickers=CHAT_STICKERS,
        unread_total=unread_total,
        summary=summary,
        current_thread_id=selected_thread["id"] if selected_thread else None,
        current_thread_last_message_id=messages[-1]["id"] if messages else 0,
        focused_message_id=focused_message_id,
        chat_attachment_max_bytes=_get_chat_attachment_max_bytes(),
        current_user_payload=_serialize_current_user(current_user),
        auto_start_call_mode=auto_start_call_mode,
        auto_pickup_call_id=auto_pickup_call_id,
        chat_webrtc_ice_servers=current_app.config.get("CHAT_WEBRTC_ICE_SERVERS", []),
    )


@chat_bp.route("/widget/bootstrap")
def widget_bootstrap():
    if not _require_chat_view():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    db = get_db()
    current_user = _fetch_current_user(db)
    if not current_user:
        return jsonify({"status": "error", "message": "User chat tidak ditemukan"}), 404

    threads = _fetch_thread_summaries(db, current_user["id"])
    contacts = _fetch_contacts(db, current_user)
    unread_total = _compute_unread_total(db, current_user["id"])

    return jsonify(
        {
            "status": "ok",
            "current_user": _serialize_current_user(current_user),
            "threads": threads,
            "contacts": contacts,
            "stickers": CHAT_STICKERS,
            "unread_total": unread_total,
            "attachment_max_bytes": _get_chat_attachment_max_bytes(),
        }
    )


@chat_bp.route("/thread/start", methods=["POST"])
def start_thread():
    if not _require_chat_manage():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    payload = request.get_json(silent=True) or request.form
    target_user_id = _to_int(payload.get("target_user_id"))

    if not target_user_id or target_user_id == session.get("user_id"):
        return jsonify({"status": "error", "message": "Target user tidak valid"}), 400

    db = get_db()
    target_user = _fetch_contact_row(db, target_user_id)
    if not target_user:
        return jsonify({"status": "error", "message": "Target user tidak ditemukan"}), 404

    thread_id = _get_or_create_direct_thread(db, session.get("user_id"), target_user_id)
    return jsonify(
        {
            "status": "ok",
            "thread_id": thread_id,
            "redirect_url": f"/chat/?thread={thread_id}",
        }
    )


@chat_bp.route("/group/create", methods=["POST"])
def create_group():
    if not _require_chat_manage():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    payload = request.get_json(silent=True) or request.form
    group_name = (payload.get("group_name") or "").strip()
    if len(group_name) < 3:
        return jsonify({"status": "error", "message": "Nama grup minimal 3 karakter"}), 400

    member_ids = payload.get("member_ids") if request.is_json else request.form.getlist("member_ids")
    member_ids = member_ids or []
    description = (payload.get("group_description") or "").strip()

    db = get_db()
    try:
        thread_id = _create_group_thread(
            db,
            session.get("user_id"),
            group_name,
            member_ids,
            description=description,
        )
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify(
        {
            "status": "ok",
            "thread_id": thread_id,
            "redirect_url": f"/chat/?thread={thread_id}",
        }
    )


@chat_bp.route("/thread/<int:thread_id>/send", methods=["POST"])
def send_message(thread_id):
    if not _require_chat_manage():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    payload = request.get_json(silent=True) if request.is_json else request.form
    body = ((payload.get("message") if payload else "") or "").strip()
    sticker_code = ((payload.get("sticker_code") if payload else "") or "").strip()
    call_mode = ((payload.get("call_mode") if payload else "") or "").strip().lower()
    reply_to_message_id = _to_int(payload.get("reply_to_message_id") if payload else None)
    attachment = request.files.get("attachment")
    sticker_image = request.files.get("sticker_image")

    db = get_db()
    current_user = _fetch_current_user(db)
    thread_rows = _fetch_thread_summaries(db, current_user["id"], thread_id)
    thread = thread_rows[0] if thread_rows else None
    if not thread:
        return jsonify({"status": "error", "message": "Thread chat tidak ditemukan"}), 404

    message_type = "text"
    extra = {
        "attachment_name": None,
        "attachment_path": None,
        "attachment_mime": None,
        "attachment_size": 0,
        "sticker_code": None,
        "call_mode": None,
        "reply_to_message_id": None,
    }

    if reply_to_message_id:
        reply_row = db.execute(
            "SELECT id FROM chat_messages WHERE id=? AND thread_id=? LIMIT 1",
            (reply_to_message_id, thread_id),
        ).fetchone()
        if not reply_row:
            return jsonify({"status": "error", "message": "Pesan yang ingin dibalas tidak ditemukan"}), 404
        extra["reply_to_message_id"] = reply_to_message_id

    if sticker_image and (sticker_image.filename or "").strip():
        try:
            extra.update(_store_chat_sticker_image(sticker_image))
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        message_type = "sticker"
        if not body:
            body = "Sticker Gambar"
    elif attachment and (attachment.filename or "").strip():
        try:
            extra.update(_store_chat_attachment(attachment))
        except ValueError as exc:
            return jsonify({"status": "error", "message": str(exc)}), 400
        message_type = "attachment"
        if not body:
            body = f"Mengirim lampiran {extra['attachment_name']}"
    elif sticker_code:
        if sticker_code not in CHAT_STICKER_MAP:
            return jsonify({"status": "error", "message": "Sticker tidak valid"}), 400
        message_type = "sticker"
        extra["sticker_code"] = sticker_code
        if not body:
            body = CHAT_STICKER_MAP[sticker_code]["label"]
    elif call_mode in {"voice", "video"}:
        message_type = "call"
        extra["call_mode"] = call_mode
        if not body:
            body = f"Permintaan {'Video Call' if call_mode == 'video' else 'Telp'}"
    elif not body:
        return jsonify({"status": "error", "message": "Pesan tidak boleh kosong"}), 400

    message_id = _insert_chat_message(db, thread_id, current_user["id"], body, message_type, extra)

    recipients = db.execute(
        """
        SELECT u.id, u.username, u.role
        FROM chat_thread_members member
        JOIN users u ON u.id = member.user_id
        WHERE member.thread_id=?
          AND member.user_id != ?
        """,
        (thread_id, current_user["id"]),
    ).fetchall()
    preview = _build_message_preview(
        {
            "body": body,
            "message_type": message_type,
            "attachment_name": extra.get("attachment_name"),
            "sticker_code": extra.get("sticker_code"),
            "call_mode": extra.get("call_mode"),
        },
        200,
    )
    subject = (
        f"Pesan grup baru di {thread['partner_name']}"
        if thread.get("thread_type") == "group"
        else f"Chat baru dari {current_user['username']}"
    )
    for recipient in recipients:
        try:
            db.execute(
                """
                INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status)
                VALUES (?, ?, 'chat', ?, ?, ?, 'queued')
                """,
                (recipient["id"], recipient["role"], recipient["username"], subject, preview),
            )
        except Exception:
            pass
        try:
            push_user_notification(
                recipient["id"],
                subject,
                preview,
                category="chat",
                link_url=f"/chat/?thread={thread_id}",
                actor_user_id=current_user["id"],
                actor_name=current_user["username"],
                source_type="chat_message",
                source_id=str(message_id),
                dedupe_key=f"chat-message:{message_id}",
                push_title=subject,
                push_body=preview,
                push_tag=f"chat-thread-{thread_id}-message-{message_id}",
            )
        except Exception:
            pass

    message = _fetch_messages(db, thread_id, current_user["id"], message_id - 1)
    return jsonify(
        {
            "status": "ok",
            "message": message[0] if message else None,
            "unread_total": _compute_unread_total(db, current_user["id"]),
        }
    )


@chat_bp.route("/thread/<int:thread_id>/pin", methods=["POST"])
def toggle_thread_pin(thread_id):
    if not _require_chat_manage():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    payload = request.get_json(silent=True) or request.form
    pinned_value = payload.get("pinned") if payload else None
    if isinstance(pinned_value, str):
        normalized_pinned = pinned_value.strip().lower()
        pinned = normalized_pinned in {"1", "true", "yes", "on"}
        if normalized_pinned in {"", "toggle"}:
            pinned = None
    elif pinned_value is None:
        pinned = None
    else:
        pinned = bool(pinned_value)

    db = get_db()
    current_user = _fetch_current_user(db)
    if not _user_can_access_thread(db, current_user["id"], thread_id):
        return jsonify({"status": "error", "message": "Thread chat tidak ditemukan"}), 404

    try:
        is_pinned = _set_thread_pin_state(db, thread_id, current_user["id"], pinned)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 404

    threads = _fetch_thread_summaries(db, current_user["id"])
    selected_thread = next((thread for thread in threads if int(thread["id"]) == int(thread_id)), None)
    return jsonify(
        {
            "status": "ok",
            "thread_id": thread_id,
            "is_pinned": is_pinned,
            "threads": threads,
            "selected_thread": selected_thread,
        }
    )


@chat_bp.route("/thread/<int:thread_id>/search")
def search_thread_messages(thread_id):
    if not _require_chat_view():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    db = get_db()
    current_user = _fetch_current_user(db)
    if not _user_can_access_thread(db, current_user["id"], thread_id):
        return jsonify({"status": "error", "message": "Thread chat tidak ditemukan"}), 404

    query = (request.args.get("q") or "").strip()
    if len(query) < 2:
        return jsonify({"status": "ok", "results": []})

    return jsonify(
        {
            "status": "ok",
            "results": _search_thread_messages(db, thread_id, query),
        }
    )


@chat_bp.route("/thread/<int:thread_id>/focus")
def focus_thread_message(thread_id):
    if not _require_chat_view():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    db = get_db()
    current_user = _fetch_current_user(db)
    if not _user_can_access_thread(db, current_user["id"], thread_id):
        return jsonify({"status": "error", "message": "Thread chat tidak ditemukan"}), 404

    message_id = _to_int(request.args.get("message_id"))
    if not message_id:
        return jsonify({"status": "error", "message": "Pesan target tidak valid"}), 400

    messages = _fetch_thread_message_focus_context(db, thread_id, current_user["id"], message_id)
    if not messages:
        return jsonify({"status": "error", "message": "Pesan target tidak ditemukan"}), 404

    _mark_thread_read(db, thread_id, current_user["id"])
    typing_state = _fetch_thread_typing_state(db, thread_id, current_user["id"])
    return jsonify(
        {
            "status": "ok",
            "focus_message_id": message_id,
            "messages": messages,
            "typing_label": typing_state["label"],
            "typing_users": typing_state["users"],
        }
    )


@chat_bp.route("/thread/<int:thread_id>/call/start", methods=["POST"])
def start_call(thread_id):
    if not _require_chat_manage():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    payload = request.get_json(silent=True) or request.form
    call_mode = ((payload.get("mode") if payload else "") or "").strip().lower()
    if call_mode not in SUPPORTED_CALL_MODES:
        return jsonify({"status": "error", "message": "Mode call tidak valid"}), 400

    db = get_db()
    current_user = _fetch_current_user(db)
    thread_rows = _fetch_thread_summaries(db, current_user["id"], thread_id)
    thread = thread_rows[0] if thread_rows else None
    if not thread:
        return jsonify({"status": "error", "message": "Thread chat tidak ditemukan"}), 404
    if thread.get("thread_type") != "direct" or not thread.get("partner_id"):
        return jsonify({"status": "error", "message": "Real call baru tersedia untuk chat direct"}), 400

    partner_id = int(thread["partner_id"])
    busy_call_id = _find_busy_call(db, [current_user["id"], partner_id])
    if busy_call_id:
        busy_row = _fetch_call_session_row(db, busy_call_id, current_user["id"])
        return jsonify(
            {
                "status": "error",
                "message": "Masih ada panggilan yang sedang berjalan. Selesaikan dulu sebelum memulai panggilan baru.",
                "call": _serialize_call_session(busy_row, current_user["id"]) if busy_row else None,
            }
        ), 409

    call_id = _create_call_session(db, thread_id, current_user["id"], partner_id, call_mode)
    _insert_call_signal(
        db,
        call_id,
        thread_id,
        current_user["id"],
        partner_id,
        "invite",
        {"mode": call_mode},
    )
    _insert_chat_message(
        db,
        thread_id,
        current_user["id"],
        f"Memulai {_call_label_for_mode(call_mode)} dengan {thread['partner_name']}.",
        "call",
        {
            "attachment_name": None,
            "attachment_path": None,
            "attachment_mime": None,
            "attachment_size": 0,
            "sticker_code": None,
            "call_mode": call_mode,
        },
    )
    try:
        push_user_notification(
            partner_id,
            f"{_call_label_for_mode(call_mode)} dari {current_user['username']}",
            f"{current_user['username']} mencoba menghubungi Anda lewat chat.",
            category="chat",
            link_url=f"/chat/?thread={thread_id}&pickup_call={call_id}",
            actor_user_id=current_user["id"],
            actor_name=current_user["username"],
            source_type="chat_call",
            source_id=str(call_id),
            dedupe_key=f"chat-call:{call_id}:invite",
            push_title=f"{_call_label_for_mode(call_mode)} masuk",
            push_body=f"{current_user['username']} menelepon Anda. Ketuk untuk membuka panggilan.",
            push_tag=f"chat-call-{call_id}",
            require_interaction=True,
            renotify=True,
            actions=[{"action": "open", "title": "Buka Call"}],
            vibrate=[300, 150, 300, 150, 300],
        )
    except Exception:
        pass

    call_row = _fetch_call_session_row(db, call_id, current_user["id"])
    return jsonify(
        {
            "status": "ok",
            "call": _serialize_call_session(call_row, current_user["id"]) if call_row else None,
        }
    )


@chat_bp.route("/call/<int:call_id>/accept", methods=["POST"])
def accept_call(call_id):
    if not _require_chat_manage():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    db = get_db()
    current_user = _fetch_current_user(db)
    call_row = _fetch_call_session_row(db, call_id, current_user["id"])
    if not call_row:
        return jsonify({"status": "error", "message": "Sesi call tidak ditemukan"}), 404
    if int(call_row["receiver_id"]) != int(current_user["id"]):
        return jsonify({"status": "error", "message": "Anda bukan penerima panggilan ini"}), 403
    if (call_row.get("thread_type") or "direct").strip().lower() != "direct":
        return jsonify({"status": "error", "message": "Call grup belum didukung"}), 400

    status = (call_row.get("status") or "pending").strip().lower()
    if status in {"connecting", "active"}:
        return jsonify(
            {
                "status": "ok",
                "call": _serialize_call_session(call_row, current_user["id"]),
            }
        )
    if status not in {"pending", "ringing"}:
        return jsonify({"status": "error", "message": "Panggilan ini sudah tidak bisa diterima"}), 400

    busy_call_id = _find_busy_call(db, [current_user["id"]])
    if busy_call_id and int(busy_call_id) != int(call_id):
        return jsonify({"status": "error", "message": "Anda sedang berada di panggilan lain"}), 409

    _update_call_status(db, call_id, "connecting", answered=True)
    _insert_call_signal(
        db,
        call_id,
        int(call_row["thread_id"]),
        current_user["id"],
        int(call_row["initiator_id"]),
        "accept",
        {"accepted": True},
    )
    updated_row = _fetch_call_session_row(db, call_id, current_user["id"])
    return jsonify(
        {
            "status": "ok",
            "call": _serialize_call_session(updated_row, current_user["id"]) if updated_row else None,
        }
    )


@chat_bp.route("/call/<int:call_id>/decline", methods=["POST"])
def decline_call(call_id):
    if not _require_chat_manage():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    db = get_db()
    current_user = _fetch_current_user(db)
    call_row = _fetch_call_session_row(db, call_id, current_user["id"])
    if not call_row:
        return jsonify({"status": "error", "message": "Sesi call tidak ditemukan"}), 404

    current_user_id = int(current_user["id"])
    if current_user_id not in {int(call_row["initiator_id"]), int(call_row["receiver_id"])}:
        return jsonify({"status": "error", "message": "Anda tidak terlibat di panggilan ini"}), 403

    status = (call_row.get("status") or "pending").strip().lower()
    if status not in OPEN_CALL_STATUSES:
        return jsonify(
            {
                "status": "ok",
                "call": _serialize_call_session(call_row, current_user_id),
            }
        )

    recipient_id = int(call_row["receiver_id"] if current_user_id == int(call_row["initiator_id"]) else call_row["initiator_id"])
    _update_call_status(db, call_id, "declined", ended_by=current_user_id)
    _insert_call_signal(
        db,
        call_id,
        int(call_row["thread_id"]),
        current_user_id,
        recipient_id,
        "decline",
        {"reason": "declined"},
    )
    updated_row = _fetch_call_session_row(db, call_id, current_user_id)
    return jsonify(
        {
            "status": "ok",
            "call": _serialize_call_session(updated_row, current_user_id) if updated_row else None,
        }
    )


@chat_bp.route("/call/<int:call_id>/end", methods=["POST"])
def end_call(call_id):
    if not _require_chat_manage():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    db = get_db()
    current_user = _fetch_current_user(db)
    call_row = _fetch_call_session_row(db, call_id, current_user["id"])
    if not call_row:
        return jsonify({"status": "error", "message": "Sesi call tidak ditemukan"}), 404

    current_user_id = int(current_user["id"])
    if current_user_id not in {int(call_row["initiator_id"]), int(call_row["receiver_id"])}:
        return jsonify({"status": "error", "message": "Anda tidak terlibat di panggilan ini"}), 403

    status = (call_row.get("status") or "pending").strip().lower()
    if status not in OPEN_CALL_STATUSES:
        return jsonify(
            {
                "status": "ok",
                "call": _serialize_call_session(call_row, current_user_id),
            }
        )

    recipient_id = int(call_row["receiver_id"] if current_user_id == int(call_row["initiator_id"]) else call_row["initiator_id"])
    _update_call_status(db, call_id, "ended", ended_by=current_user_id)
    _insert_call_signal(
        db,
        call_id,
        int(call_row["thread_id"]),
        current_user_id,
        recipient_id,
        "end",
        {"reason": "ended"},
    )
    updated_row = _fetch_call_session_row(db, call_id, current_user_id)
    return jsonify(
        {
            "status": "ok",
            "call": _serialize_call_session(updated_row, current_user_id) if updated_row else None,
        }
    )


@chat_bp.route("/call/<int:call_id>/signal", methods=["POST"])
def relay_call_signal(call_id):
    if not _require_chat_manage():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    payload = request.get_json(silent=True) or {}
    signal_type = (payload.get("signal_type") or "").strip().lower()
    if signal_type not in {"offer", "answer", "ice"}:
        return jsonify({"status": "error", "message": "Signal WebRTC tidak valid"}), 400

    signal_payload = payload.get("payload")
    if signal_payload is None:
        signal_payload = {}
    if not isinstance(signal_payload, dict):
        return jsonify({"status": "error", "message": "Payload signal harus berbentuk object"}), 400

    db = get_db()
    current_user = _fetch_current_user(db)
    call_row = _fetch_call_session_row(db, call_id, current_user["id"])
    if not call_row:
        return jsonify({"status": "error", "message": "Sesi call tidak ditemukan"}), 404

    current_user_id = int(current_user["id"])
    if current_user_id not in {int(call_row["initiator_id"]), int(call_row["receiver_id"])}:
        return jsonify({"status": "error", "message": "Anda tidak terlibat di panggilan ini"}), 403

    status = (call_row.get("status") or "pending").strip().lower()
    if status not in OPEN_CALL_STATUSES:
        return jsonify({"status": "error", "message": "Panggilan ini sudah selesai"}), 400

    recipient_id = int(call_row["receiver_id"] if current_user_id == int(call_row["initiator_id"]) else call_row["initiator_id"])
    signal_id = _insert_call_signal(
        db,
        call_id,
        int(call_row["thread_id"]),
        current_user_id,
        recipient_id,
        signal_type,
        signal_payload,
    )

    if signal_type == "offer" and status in {"pending", "ringing"}:
        _update_call_status(db, call_id, "connecting")
    elif signal_type == "answer":
        _update_call_status(db, call_id, "active", answered=True)

    updated_row = _fetch_call_session_row(db, call_id, current_user_id)
    return jsonify(
        {
            "status": "ok",
            "signal_id": signal_id,
            "call": _serialize_call_session(updated_row, current_user_id) if updated_row else None,
        }
    )


@chat_bp.route("/call/poll")
def poll_calls():
    if not _require_chat_view():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    db = get_db()
    current_user = _fetch_current_user(db)
    after_signal_id = _to_int(request.args.get("after_signal_id"), 0) or 0
    calls = _fetch_open_call_sessions(db, current_user["id"])
    signals, latest_signal_id = _fetch_call_signals(db, current_user["id"], after_signal_id)

    return jsonify(
        {
            "status": "ok",
            "calls": calls,
            "signals": signals,
            "latest_signal_id": latest_signal_id,
        }
    )


@chat_bp.route("/realtime")
def chat_realtime():
    if not _require_chat_view():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    db = get_db()
    current_user = _fetch_current_user(db)
    since_message_id = _to_int(request.args.get("since_message_id"), 0) or 0
    selected_thread_id = _to_int(request.args.get("selected_thread_id"))
    after_message_id = _to_int(request.args.get("after_message_id"), 0) or 0
    include_threads = request.args.get("include_threads") == "1"

    selected_thread = None
    new_messages = []
    if selected_thread_id:
        thread_rows = _fetch_thread_summaries(db, current_user["id"], selected_thread_id)
        selected_thread = thread_rows[0] if thread_rows else None
        if selected_thread:
            new_messages = _fetch_messages(db, selected_thread_id, current_user["id"], after_message_id)
            _mark_thread_read(db, selected_thread_id, current_user["id"])

    unread_total = _compute_unread_total(db, current_user["id"])
    incoming, latest_incoming_id = _fetch_incoming_messages(db, current_user["id"], since_message_id)

    payload = {
        "status": "ok",
        "unread_total": unread_total,
        "incoming": incoming,
        "latest_incoming_id": latest_incoming_id,
    }

    if include_threads:
        payload["threads"] = _fetch_thread_summaries(db, current_user["id"])

    if selected_thread:
        typing_state = _fetch_thread_typing_state(db, selected_thread["id"], current_user["id"])
        payload["selected_thread"] = {
            "id": selected_thread["id"],
            "thread_type": selected_thread.get("thread_type"),
            "messages": new_messages,
            "partner_name": selected_thread["partner_name"],
            "partner_online": selected_thread["partner_online"],
            "partner_role_label": selected_thread["partner_role_label"],
            "partner_warehouse_label": selected_thread["partner_warehouse_label"],
            "partner_status_label": selected_thread.get("partner_status_label"),
            "partner_phone": selected_thread.get("partner_phone"),
            "participants": selected_thread.get("participants", []),
            "member_count": selected_thread.get("member_count", 0),
            "online_count": selected_thread.get("online_count", 0),
            "is_pinned": bool(selected_thread.get("is_pinned")),
            "typing_users": typing_state["users"],
            "typing_label": typing_state["label"],
        }

    return jsonify(payload)


@chat_bp.route("/typing", methods=["POST"])
def update_typing():
    if not _require_chat_view():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    payload = request.get_json(silent=True) or {}
    current_user_id = session.get("user_id")
    thread_id = _to_int(payload.get("thread_id"))
    is_typing = bool(payload.get("is_typing"))
    current_path = (payload.get("path") or "/chat/").strip()[:255] or "/chat/"

    try:
        db = get_db()
        try:
            db.execute("PRAGMA busy_timeout = 1200")
        except sqlite3.Error:
            pass

        if thread_id and not _user_can_access_thread(db, current_user_id, thread_id):
            return jsonify({"status": "error", "message": "Thread chat tidak ditemukan"}), 404

        if is_typing and thread_id:
            db.execute(
                """
                INSERT INTO user_presence(
                    user_id,
                    current_path,
                    active_thread_id,
                    typing_thread_id,
                    typing_until,
                    last_seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, datetime('now', ?), CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    current_path=excluded.current_path,
                    active_thread_id=excluded.active_thread_id,
                    typing_thread_id=excluded.typing_thread_id,
                    typing_until=excluded.typing_until,
                    last_seen_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (current_user_id, current_path, thread_id, thread_id, f"+{CHAT_TYPING_TTL_SECONDS} seconds"),
            )
        else:
            db.execute(
                """
                INSERT INTO user_presence(
                    user_id,
                    current_path,
                    active_thread_id,
                    typing_thread_id,
                    typing_until,
                    last_seen_at,
                    updated_at
                )
                VALUES (?, ?, ?, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    current_path=excluded.current_path,
                    active_thread_id=excluded.active_thread_id,
                    typing_thread_id=NULL,
                    typing_until=NULL,
                    last_seen_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (current_user_id, current_path, thread_id),
            )
    except sqlite3.Error as exc:
        current_app.logger.warning("CHAT TYPING SQLITE ERROR: %s", exc)
        return jsonify({"status": "ok", "degraded": True})
    except Exception as exc:
        current_app.logger.warning("CHAT TYPING ERROR: %s", exc)
        return jsonify({"status": "ok", "degraded": True})

    return jsonify({"status": "ok"})


@chat_bp.route("/presence", methods=["POST"])
def update_presence():
    if not _require_chat_view():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    payload = request.get_json(silent=True) or {}
    current_path = (payload.get("path") or request.path or "").strip()[:255] or "/"
    active_thread_id = _to_int(payload.get("thread_id"))
    current_user_id = session.get("user_id")

    try:
        db = get_db()
        try:
            db.execute("PRAGMA busy_timeout = 1200")
        except sqlite3.Error:
            pass

        if active_thread_id and not _user_can_access_thread(db, current_user_id, active_thread_id):
            active_thread_id = None

        db.execute(
            """
            INSERT INTO user_presence(user_id, current_path, active_thread_id, last_seen_at, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                current_path=excluded.current_path,
                active_thread_id=excluded.active_thread_id,
                last_seen_at=CURRENT_TIMESTAMP,
                updated_at=CURRENT_TIMESTAMP
            """,
            (current_user_id, current_path, active_thread_id),
        )
    except sqlite3.Error as exc:
        current_app.logger.warning("CHAT PRESENCE SQLITE ERROR: %s", exc)
        return jsonify({"status": "ok", "degraded": True})
    except Exception as exc:
        current_app.logger.warning("CHAT PRESENCE ERROR: %s", exc)
        return jsonify({"status": "ok", "degraded": True})

    return jsonify({"status": "ok"})

