from datetime import date as date_cls

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session

from database import get_db
from services.rbac import has_permission


chat_bp = Blueprint("chat", __name__, url_prefix="/chat")

ONLINE_WINDOW_SECONDS = 45
INITIAL_MESSAGE_LIMIT = 120
POLL_MESSAGE_LIMIT = 60
INCOMING_TOAST_LIMIT = 12


def _to_int(value, default=None):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _clip_text(value, limit=120):
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def _get_initials(name):
    parts = [part for part in (name or "").strip().split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _format_timestamp_label(value):
    raw = str(value or "").strip()
    if len(raw) < 10:
        return "-"

    raw_date = raw[:10]
    raw_time = raw[11:16] if len(raw) >= 16 else ""
    if raw_date == date_cls.today().isoformat():
        return raw_time or raw_date
    if raw_time:
        return f"{raw_date[8:10]}/{raw_date[5:7]} {raw_time}"
    return f"{raw_date[8:10]}/{raw_date[5:7]}"


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
        SELECT u.id, u.username, u.role, u.warehouse_id, w.name AS warehouse_name
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
        SELECT u.id, u.username, u.role, u.warehouse_id, w.name AS warehouse_name
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
    data["status_label"] = "Online" if data["is_online"] else "Offline"
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


def _fetch_thread_summaries(db, current_user_id, thread_id=None):
    where_clause = ""
    params = [
        f"-{ONLINE_WINDOW_SECONDS} seconds",
        current_user_id,
        current_user_id,
        current_user_id,
    ]
    if thread_id:
        where_clause = " AND t.id=?"
        params.append(thread_id)

    rows = db.execute(
        f"""
        SELECT
            t.id,
            t.created_at,
            t.last_message_at,
            partner.id AS partner_id,
            partner.username AS partner_name,
            partner.role AS partner_role,
            partner.warehouse_id AS partner_warehouse_id,
            w.name AS partner_warehouse_name,
            CASE WHEN up.last_seen_at >= datetime('now', ?) THEN 1 ELSE 0 END AS partner_online,
            up.current_path AS partner_path,
            up.last_seen_at AS partner_last_seen_at,
            member.last_read_message_id,
            last_msg.id AS last_message_id,
            last_msg.body AS last_message_body,
            last_msg.created_at AS last_message_created_at,
            last_msg.sender_id AS last_message_sender_id,
            sender.username AS last_message_sender_name,
            COALESCE(
                (
                    SELECT COUNT(*)
                    FROM chat_messages unread_msg
                    WHERE unread_msg.thread_id = t.id
                      AND unread_msg.sender_id != ?
                      AND unread_msg.id > COALESCE(member.last_read_message_id, 0)
                ),
                0
            ) AS unread_count
        FROM chat_threads t
        JOIN chat_thread_members member
          ON member.thread_id = t.id
         AND member.user_id = ?
        JOIN chat_thread_members partner_member
          ON partner_member.thread_id = t.id
         AND partner_member.user_id != ?
        JOIN users partner ON partner.id = partner_member.user_id
        LEFT JOIN warehouses w ON w.id = partner.warehouse_id
        LEFT JOIN user_presence up ON up.user_id = partner.id
        LEFT JOIN chat_messages last_msg
          ON last_msg.id = (
              SELECT id
              FROM chat_messages
              WHERE thread_id = t.id
              ORDER BY id DESC
              LIMIT 1
          )
        LEFT JOIN users sender ON sender.id = last_msg.sender_id
        WHERE 1=1 {where_clause}
        ORDER BY COALESCE(t.last_message_at, t.created_at) DESC, t.id DESC
        """,
        params,
    ).fetchall()

    threads = []
    for row in rows:
        item = dict(row)
        item["partner_online"] = bool(item.get("partner_online"))
        item["unread_count"] = int(item.get("unread_count") or 0)
        item["partner_initials"] = _get_initials(item.get("partner_name"))
        item["partner_role_label"] = (item.get("partner_role") or "-").replace("_", " ").title()
        item["partner_warehouse_label"] = item.get("partner_warehouse_name") or "Global"
        item["last_message_preview"] = _clip_text(item.get("last_message_body") or "Mulai percakapan baru.")
        item["last_message_label"] = _format_timestamp_label(
            item.get("last_message_created_at") or item.get("last_message_at") or item.get("created_at")
        )
        item["last_message_prefix"] = "Anda: " if item.get("last_message_sender_id") == current_user_id else ""
        item["search_blob"] = " ".join(
            [
                item.get("partner_name") or "",
                item.get("partner_role_label") or "",
                item.get("partner_warehouse_label") or "",
                item.get("last_message_preview") or "",
            ]
        ).strip()
        threads.append(item)
    return threads


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
                cm.created_at
            FROM chat_messages cm
            JOIN users sender ON sender.id = cm.sender_id
            WHERE cm.thread_id=?
              AND cm.id > ?
            ORDER BY cm.id ASC
            """,
            (thread_id, after_message_id),
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

    messages = []
    for row in rows:
        item = dict(row)
        item["is_mine"] = item.get("sender_id") == current_user_id
        item["sender_initials"] = _get_initials(item.get("sender_name"))
        item["created_label"] = _format_timestamp_label(item.get("created_at"))
        item["preview"] = _clip_text(item.get("body"), 80)
        messages.append(item)
    return messages


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


def _fetch_incoming_messages(db, current_user_id, since_message_id):
    rows = db.execute(
        """
        SELECT
            cm.id,
            cm.thread_id,
            cm.body,
            cm.created_at,
            sender.username AS sender_name
        FROM chat_messages cm
        JOIN chat_thread_members member
          ON member.thread_id = cm.thread_id
         AND member.user_id = ?
        JOIN users sender ON sender.id = cm.sender_id
        WHERE cm.sender_id != ?
          AND cm.id > ?
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
                "preview": _clip_text(item["body"], 80),
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
            INSERT INTO chat_threads(direct_key, created_by)
            VALUES (?, ?)
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

    messages = _fetch_messages(db, selected_thread["id"], current_user["id"]) if selected_thread else []
    contacts = _fetch_contacts(db, current_user)
    unread_total = _compute_unread_total(db, current_user["id"])

    summary = {
        "threads": len(threads),
        "leaders": sum(1 for contact in contacts if contact["is_leader"]),
        "online": sum(1 for contact in contacts if contact["is_online"]),
        "unread": unread_total,
    }

    return render_template(
        "chat.html",
        current_user=current_user,
        threads=threads,
        contacts=contacts,
        selected_thread=selected_thread,
        messages=messages,
        unread_total=unread_total,
        summary=summary,
        current_thread_id=selected_thread["id"] if selected_thread else None,
        current_thread_last_message_id=messages[-1]["id"] if messages else 0,
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


@chat_bp.route("/thread/<int:thread_id>/send", methods=["POST"])
def send_message(thread_id):
    if not _require_chat_manage():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    payload = request.get_json(silent=True) or request.form
    body = (payload.get("message") or "").strip()
    if not body:
        return jsonify({"status": "error", "message": "Pesan tidak boleh kosong"}), 400

    db = get_db()
    current_user = _fetch_current_user(db)
    thread_rows = _fetch_thread_summaries(db, current_user["id"], thread_id)
    thread = thread_rows[0] if thread_rows else None
    if not thread:
        return jsonify({"status": "error", "message": "Thread chat tidak ditemukan"}), 404

    cursor = db.execute(
        """
        INSERT INTO chat_messages(thread_id, sender_id, body)
        VALUES (?, ?, ?)
        """,
        (thread_id, current_user["id"], body),
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
        (message_id, thread_id, current_user["id"]),
    )

    try:
        db.execute(
            """
            INSERT INTO notifications(user_id, role, channel, recipient, subject, message, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread["partner_id"],
                thread["partner_role"],
                "chat",
                thread["partner_name"],
                f"Chat baru dari {current_user['username']}",
                _clip_text(body, 200),
                "queued",
            ),
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
        payload["selected_thread"] = {
            "id": selected_thread["id"],
            "messages": new_messages,
            "partner_name": selected_thread["partner_name"],
            "partner_online": selected_thread["partner_online"],
            "partner_role_label": selected_thread["partner_role_label"],
            "partner_warehouse_label": selected_thread["partner_warehouse_label"],
        }

    return jsonify(payload)


@chat_bp.route("/presence", methods=["POST"])
def update_presence():
    if not _require_chat_view():
        return jsonify({"status": "error", "message": "Akses ditolak"}), 403

    db = get_db()
    payload = request.get_json(silent=True) or {}
    current_path = (payload.get("path") or request.path or "").strip()[:255] or "/"
    active_thread_id = _to_int(payload.get("thread_id"))

    if active_thread_id:
        thread_rows = _fetch_thread_summaries(db, session.get("user_id"), active_thread_id)
        if not thread_rows:
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
        (session.get("user_id"), current_path, active_thread_id),
    )

    return jsonify({"status": "ok"})
