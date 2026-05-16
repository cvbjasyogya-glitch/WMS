from __future__ import annotations

import csv
import hmac
import logging
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import (
    abort,
    Flask,
    Response,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
APP_TIMEZONE = ZoneInfo(os.environ.get("APP_TIMEZONE", "Asia/Jakarta"))
DATABASE = Path(os.environ.get("SENARAN_DATABASE", BASE_DIR / "antrian.db")).expanduser()

BRANCHES = ["Mega Sports"]
STATUSES = ["MENUNGGU", "DIPANGGIL", "DIPROSES", "SELESAI", "DIAMBIL", "BATAL"]
SERVICE_TYPES = [
    "Stringing Badminton",
    "Stringing Tenis",
]
PAYMENT_STATUSES = ["BELUM BAYAR", "SUDAH BAYAR"]
SCHEDULE_TIMES = ["14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
SLOT_CAPACITY = 2
MAX_RACKET_COUNT = 6
MAX_SLOT_LOAD = 6
STRINGERS = ["Ika", "Abi", "Ahmad"]
DEFAULT_STAFF = ["Bu ika", "Lifia", "Caca", "Afif", "Ziza", "Edi", "Ahmad", "Lainnya"]
KNOT_TYPES = ["S-2", "S-4"]
VARIATIONS = ["Full", "L-1", "L-2", "Custom"]
GROMMET_OPTIONS = ["Tidak", "Ya"]
COMMON_PASSWORDS = {"admin123", "password", "megasports", "123456", "qwerty", "susukambing65"}
LOGIN_LIMIT = 5
LOGIN_WINDOW_MINUTES = 10
LOGIN_LOCK_MINUTES = 10
ANTRIAN_FORM_DRAFT_KEY = "antrian_add_draft"
PHONE_PATTERN = re.compile(r"^[0-9+\-\s]+$")
MONTH_LABELS = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "Mei",
    6: "Jun",
    7: "Jul",
    8: "Agu",
    9: "Sep",
    10: "Okt",
    11: "Nov",
    12: "Des",
}


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-this-secret-key")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error: Exception | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def today_iso() -> str:
    return current_datetime().date().isoformat()


def now_sql() -> str:
    return current_datetime().strftime("%Y-%m-%d %H:%M:%S")


def current_datetime() -> datetime:
    return datetime.now(APP_TIMEZONE).replace(tzinfo=None)


def parse_iso_date(value: str | None, fallback: str | None = None) -> str:
    candidate = value or fallback or today_iso()
    try:
        return datetime.strptime(candidate, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return today_iso()


def clamp_iso_date(value: str | None, min_offset: int = -1, max_offset: int = 3) -> str:
    today = current_datetime().date()
    min_date = today + timedelta(days=min_offset)
    max_date = today + timedelta(days=max_offset)
    selected = datetime.strptime(parse_iso_date(value, today_iso()), "%Y-%m-%d").date()
    if selected < min_date:
        return min_date.isoformat()
    if selected > max_date:
        return max_date.isoformat()
    return selected.isoformat()


def build_date_options(selected_date: str) -> list[dict]:
    today = current_datetime().date()
    selected = datetime.strptime(parse_iso_date(selected_date), "%Y-%m-%d").date()
    options = []
    for offset in range(-7, 8):
        current = today + timedelta(days=offset)
        date_label = f"{current.day:02d} {MONTH_LABELS[current.month]}"
        if offset == 0:
            label = f"Hari Ini {date_label}"
        else:
            label = date_label
        options.append(
            {
                "date": current.isoformat(),
                "label": label,
                "active": current == selected,
                "today": offset == 0,
            }
        )
    return options


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            logger.warning("Login required endpoint=%s ip=%s", request.endpoint, get_client_ip())
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def generate_csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def validate_csrf_token() -> bool:
    expected = session.get("_csrf_token")
    supplied = request.form.get("csrf_token", "")
    return bool(expected and supplied and hmac.compare_digest(str(expected), str(supplied)))


def get_client_ip() -> str:
    return request.remote_addr or "unknown"


def record_login_attempt(username: str, ip_address: str, success: bool) -> None:
    db = get_db()
    if success:
        db.execute(
            "DELETE FROM login_attempts WHERE lower(username) = lower(?) AND ip_address = ? AND success = 0",
            (username, ip_address),
        )
    db.execute(
        """
        INSERT INTO login_attempts (username, ip_address, success, attempted_at)
        VALUES (?, ?, ?, ?)
        """,
        (username, ip_address, 1 if success else 0, now_sql()),
    )
    db.commit()


def is_login_locked(username: str, ip_address: str) -> bool:
    cutoff = (current_datetime() - timedelta(minutes=LOGIN_WINDOW_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    rows = get_db().execute(
        """
        SELECT attempted_at
        FROM login_attempts
        WHERE lower(username) = lower(?)
          AND ip_address = ?
          AND success = 0
          AND attempted_at >= ?
        ORDER BY attempted_at DESC
        LIMIT ?
        """,
        (username, ip_address, cutoff, LOGIN_LIMIT),
    ).fetchall()
    if len(rows) < LOGIN_LIMIT:
        return False
    latest_failure = datetime.strptime(rows[0]["attempted_at"], "%Y-%m-%d %H:%M:%S")
    return current_datetime() < latest_failure + timedelta(minutes=LOGIN_LOCK_MINUTES)


def validate_password_policy(password: str) -> list[str]:
    errors = []
    normalized = password.strip().lower()
    if len(password) < 10:
        errors.append("Password baru minimal 10 karakter.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        errors.append("Password baru harus mengandung huruf dan angka.")
    if normalized in COMMON_PASSWORDS:
        errors.append("Password baru terlalu umum. Gunakan kombinasi lain.")
    return errors


def build_antrian_form_draft(form_data, item_values: list[dict]) -> dict:
    draft_form = {}
    for key in form_data.keys():
        if key == "csrf_token":
            continue
        draft_form[key] = form_data.get(key, "")
    return {
        "form": draft_form,
        "item_values": item_values,
    }


def save_antrian_form_draft(form_data, item_values: list[dict]) -> None:
    session[ANTRIAN_FORM_DRAFT_KEY] = build_antrian_form_draft(form_data, item_values)
    session.modified = True


def pop_antrian_form_draft() -> dict | None:
    draft = session.pop(ANTRIAN_FORM_DRAFT_KEY, None)
    if draft is not None:
        session.modified = True
    return draft


def get_antrian_form_draft() -> dict | None:
    draft = session.get(ANTRIAN_FORM_DRAFT_KEY)
    return draft if isinstance(draft, dict) else None


@app.before_request
def protect_post_and_forced_password_change():
    if session.get(ANTRIAN_FORM_DRAFT_KEY) and request.endpoint not in {"antrian_add", "api_schedule_slots", "static"}:
        pop_antrian_form_draft()

    if request.method == "POST" and not validate_csrf_token():
        logger.warning("CSRF validation failed endpoint=%s ip=%s", request.endpoint, get_client_ip())
        abort(400)

    if (
        session.get("user_id")
        and session.get("must_change_password")
        and request.endpoint not in {"account", "logout", "static"}
    ):
        flash("Silakan ganti password akun terlebih dahulu.", "warning")
        return redirect(url_for("account"))


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return response


def get_active_services() -> list[str]:
    return SERVICE_TYPES


def get_active_staff() -> list[str]:
    rows = get_db().execute(
        "SELECT staff_name FROM staff WHERE is_active = 1 ORDER BY id ASC"
    ).fetchall()
    if rows:
        return [row["staff_name"] for row in rows]
    return DEFAULT_STAFF


def branch_aliases(branch: str) -> list[str]:
    if branch == "Mega Sports":
        return ["Mega Sports", "Mega"]
    return [branch]


def generate_queue_number(branch: str) -> str:
    prefix_map = {"Mega Sports": "MGA", "Mega": "MGA"}
    prefix = prefix_map.get(branch, "MGA")
    db = get_db()
    aliases = branch_aliases(branch)
    placeholders = ",".join("?" for _ in aliases)
    row = db.execute(
        f"""
        SELECT COUNT(*) AS total
        FROM queue_tickets
        WHERE queue_date = ? AND branch IN ({placeholders})
        """,
        (today_iso(), *aliases),
    ).fetchone()
    next_number = (row["total"] if row else 0) + 1
    return f"{prefix}-{next_number:03d}"


def get_racket_type_for_service(service_type: str) -> str:
    if service_type == "Stringing Tenis":
        return "Tenis"
    return "Badminton"


def build_estimated_finish(schedule_date: str, schedule_time: str) -> str | None:
    if schedule_time not in SCHEDULE_TIMES:
        return None
    try:
        parsed = datetime.strptime(f"{schedule_date} {schedule_time}", "%Y-%m-%d %H:%M")
        return parsed.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def collect_ticket_items(form, racket_count: int, service_type: str) -> tuple[list[dict], list[str]]:
    items = []
    errors = []
    racket_type = get_racket_type_for_service(service_type)

    for number in range(1, racket_count + 1):
        item = {
            "item_number": number,
            "racket_type": racket_type,
            "racket_brand": form.get(f"racket_brand_{number}", "").strip(),
            "string_type": form.get(f"string_type_{number}", "").strip(),
            "tension_lbs": form.get(f"tension_lbs_{number}", "").strip(),
            "knot_type": form.get(f"knot_type_{number}", "").strip(),
            "variation": form.get(f"variation_{number}", "").strip(),
            "grommet": form.get(f"grommet_{number}", "Tidak").strip() or "Tidak",
            "racket_note": form.get(f"racket_note_{number}", "").strip(),
        }
        if item["grommet"] not in GROMMET_OPTIONS:
            item["grommet"] = "Tidak"
        if item["knot_type"] not in KNOT_TYPES:
            errors.append(f"Simpul raket {number} wajib dipilih.")
        if item["variation"] not in VARIATIONS:
            errors.append(f"Variasi raket {number} wajib dipilih.")
        if not item["racket_brand"]:
            errors.append(f"Merk dan seri raket {number} wajib diisi.")
        if not item["string_type"]:
            errors.append(f"Jenis senar raket {number} wajib diisi.")
        if not item["tension_lbs"]:
            errors.append(f"Tarikan LBS raket {number} wajib diisi.")
        items.append(item)

    return items, errors


def get_slot_capacity(slot_time: str) -> int:
    if slot_time == "20:00":
        return MAX_SLOT_LOAD
    return SLOT_CAPACITY


def get_slot_max_load(slot_time: str) -> int:
    return MAX_SLOT_LOAD


def get_schedule_slots(schedule_date: str | None = None, express_mode: bool = False) -> list[dict]:
    selected_date = parse_iso_date(schedule_date)
    db = get_db()
    rows = db.execute(
        """
        SELECT substr(estimated_finish, 12, 5) AS slot_time,
               COALESCE(SUM(COALESCE(NULLIF(racket_count, 0), 1)), 0) AS used
        FROM queue_tickets
        WHERE date(estimated_finish) = ?
          AND status != 'BATAL'
          AND estimated_finish IS NOT NULL
        GROUP BY slot_time
        """,
        (selected_date,),
    ).fetchall()
    used_by_time = {row["slot_time"]: int(row["used"] or 0) for row in rows}
    slot_item_rows = db.execute(
        """
        SELECT
            substr(estimated_finish, 12, 5) AS slot_time,
            queue_number,
            customer_name,
            status,
            racket_count,
            stringer_name
        FROM queue_tickets
        WHERE date(estimated_finish) = ?
          AND status != 'BATAL'
          AND estimated_finish IS NOT NULL
        ORDER BY estimated_finish ASC, created_at ASC, id ASC
        """,
        (selected_date,),
    ).fetchall()
    items_by_time: dict[str, list[dict]] = {slot_time: [] for slot_time in SCHEDULE_TIMES}
    for row in slot_item_rows:
        slot_time = row["slot_time"]
        if slot_time not in items_by_time:
            continue
        items_by_time[slot_time].append(
            {
                "queue_number": row["queue_number"],
                "customer_name": row["customer_name"],
                "status": row["status"],
                "racket_count": row["racket_count"] or 1,
                "stringer_name": row["stringer_name"] or "",
                "estimated_time": slot_time,
            }
        )
    unavailable_sources: dict[str, str] = {}
    time_locked_slots: set[str] = set()

    if selected_date == today_iso() and not express_mode:
        cutoff = current_datetime() + timedelta(hours=3)
        for slot_time in SCHEDULE_TIMES:
            slot_finish = build_estimated_finish(selected_date, slot_time)
            if not slot_finish:
                continue
            slot_datetime = datetime.strptime(slot_finish, "%Y-%m-%d %H:%M:%S")
            if slot_datetime <= cutoff:
                time_locked_slots.add(slot_time)

    for index, slot_time in enumerate(SCHEDULE_TIMES):
        used = used_by_time.get(slot_time, 0)
        if slot_time not in {"14:00", "15:00", "16:00", "17:00", "18:00"}:
            continue

        spill_hours = 0
        if used >= 6:
            spill_hours = 2
        elif used >= 4:
            spill_hours = 1

        for hour_offset in range(1, spill_hours + 1):
            if index + hour_offset >= len(SCHEDULE_TIMES):
                continue
            affected_time = SCHEDULE_TIMES[index + hour_offset]
            unavailable_sources.setdefault(affected_time, slot_time)

    slots = []
    for slot_time in SCHEDULE_TIMES:
        used = used_by_time.get(slot_time, 0)
        capacity = get_slot_capacity(slot_time)
        unavailable = (slot_time in unavailable_sources or slot_time in time_locked_slots) and not express_mode
        reason = ""
        if slot_time in time_locked_slots and not express_mode:
            reason = "Melewati batas 3 jam dari waktu sekarang"
        elif unavailable:
            source_time = unavailable_sources[slot_time]
            reason = f"Mengikuti beban slot {source_time}"

        if express_mode:
            label = "Tersedia"
        elif unavailable:
            label = "Tidak tersedia"
        elif used >= capacity:
            label = "Penuh"
        else:
            label = "Tersedia"

        slots.append(
            {
                "time": slot_time,
                "used": used,
                "capacity": capacity,
                "available": True if express_mode else (not unavailable and used < capacity),
                "unavailable": unavailable,
                "label": label,
                "reason": reason,
                "items": items_by_time.get(slot_time, []),
            }
        )
    return slots


def validate_selected_slot(schedule_date: str, schedule_time: str, racket_count: int, is_express: bool = False) -> tuple[bool, str]:
    slot = next(
        (item for item in get_schedule_slots(schedule_date, express_mode=is_express) if item["time"] == schedule_time),
        None,
    )
    if slot is None:
        return False, "Jam estimasi selesai tidak valid."
    if is_express:
        return True, ""
    if slot["unavailable"] or slot["used"] >= slot["capacity"]:
        return False, "Slot jam ini sudah penuh atau tidak tersedia. Silakan pilih jam lain."
    if slot["used"] + racket_count > get_slot_max_load(schedule_time):
        return False, "Slot jam ini sudah penuh atau tidak tersedia. Silakan pilih jam lain."
    return True, ""


def redirect_back(default_endpoint: str = "antrian_list"):
    next_url = request.form.get("next") or request.args.get("next")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for(default_endpoint))


def ticket_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    estimated_finish = row["estimated_finish"] if "estimated_finish" in row.keys() else None
    return {
        "queue_number": row["queue_number"],
        "customer_name": row["customer_name"],
        "service_type": row["service_type"],
        "status": row["status"],
        "branch": row["branch"],
        "racket_count": row["racket_count"] if "racket_count" in row.keys() else 1,
        "is_express": bool(row["is_express"]) if "is_express" in row.keys() else False,
        "estimated_finish": estimated_finish,
        "estimated_time": estimated_finish[11:16] if estimated_finish else "",
        "stringer_name": row["stringer_name"] if "stringer_name" in row.keys() else "",
    }


@app.context_processor
def inject_globals():
    return {
        "current_year": current_datetime().year,
        "statuses": STATUSES,
        "branches": BRANCHES,
        "schedule_times": SCHEDULE_TIMES,
        "stringers": STRINGERS,
        "csrf_token": generate_csrf_token,
    }


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip_address = get_client_ip()
        db = get_db()

        if is_login_locked(username, ip_address):
            logger.warning("Login locked username=%s ip=%s", username, ip_address)
            flash("Terlalu banyak percobaan login. Coba lagi beberapa menit lagi.", "danger")
            return render_template("login.html")

        user = db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            record_login_attempt(username, ip_address, True)
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            session["must_change_password"] = bool(user["must_change_password"]) if "must_change_password" in user.keys() else False
            logger.info("Login success username=%s ip=%s", username, ip_address)
            flash("Login berhasil. Selamat bekerja.", "success")
            if session["must_change_password"]:
                flash("Akun default wajib mengganti password terlebih dahulu.", "warning")
                return redirect(url_for("account"))
            return redirect(url_for("dashboard"))

        record_login_attempt(username, ip_address, False)
        logger.warning("Login failed username=%s ip=%s", username, ip_address)
        flash("Username atau password salah.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Anda sudah logout.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    today = today_iso()

    status_rows = db.execute(
        """
        SELECT status, COUNT(*) AS total
        FROM queue_tickets
        WHERE queue_date = ?
        GROUP BY status
        """,
        (today,),
    ).fetchall()
    status_counts = {status: 0 for status in STATUSES}
    for row in status_rows:
        status_counts[row["status"]] = row["total"]
    total_today = sum(status_counts.values())

    total_rackets_row = db.execute(
        """
        SELECT COALESCE(SUM(COALESCE(NULLIF(racket_count, 0), 1)), 0) AS total_rackets
        FROM queue_tickets
        WHERE queue_date = ?
          AND status != 'BATAL'
        """,
        (today,),
    ).fetchone()
    total_rackets = int(total_rackets_row["total_rackets"] or 0)

    latest_tickets = db.execute(
        """
        SELECT *
        FROM queue_tickets
        WHERE queue_date = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 8
        """,
        (today,),
    ).fetchall()

    schedule_slots = get_schedule_slots(today)
    schedule_tickets = db.execute(
        """
        SELECT *
        FROM queue_tickets
        WHERE date(estimated_finish) = ?
          AND status != 'BATAL'
        ORDER BY estimated_finish ASC, created_at ASC, id ASC
        """,
        (today,),
    ).fetchall()

    branch_summary = []
    for branch in BRANCHES:
        aliases = branch_aliases(branch)
        placeholders = ",".join("?" for _ in aliases)
        row = db.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN status = 'MENUNGGU' THEN 1 ELSE 0 END), 0) AS waiting,
                COALESCE(SUM(CASE WHEN status IN ('SELESAI', 'DIAMBIL') THEN 1 ELSE 0 END), 0) AS done
            FROM queue_tickets
            WHERE queue_date = ? AND branch IN ({placeholders})
            """,
            (today, *aliases),
        ).fetchone()
        branch_summary.append({"branch": branch, "total": row["total"], "waiting": row["waiting"], "done": row["done"]})

    return render_template(
        "dashboard.html",
        status_counts=status_counts,
        total_today=total_today,
        total_rackets=total_rackets,
        latest_tickets=latest_tickets,
        branch_summary=branch_summary,
        schedule_slots=schedule_slots,
        schedule_tickets=schedule_tickets,
    )


@app.route("/antrian")
@login_required
def antrian_list():
    selected_date = parse_iso_date(request.args.get("date"), today_iso())
    db = get_db()
    tickets = db.execute(
        """
        SELECT *
        FROM queue_tickets
        WHERE queue_date = ?
        ORDER BY created_at DESC, id DESC
        """,
        (selected_date,),
    ).fetchall()
    ticket_ids = [ticket["id"] for ticket in tickets]
    items_by_ticket: dict[int, list[sqlite3.Row]] = {}
    if ticket_ids:
        placeholders = ",".join("?" for _ in ticket_ids)
        item_rows = db.execute(
            f"""
            SELECT *
            FROM queue_ticket_items
            WHERE ticket_id IN ({placeholders})
            ORDER BY ticket_id ASC, item_number ASC
            """,
            ticket_ids,
        ).fetchall()
        for item in item_rows:
            items_by_ticket.setdefault(item["ticket_id"], []).append(item)

    return render_template(
        "antrian_list.html",
        tickets=tickets,
        items_by_ticket=items_by_ticket,
        selected_date=selected_date,
        date_options=build_date_options(selected_date),
    )


def render_antrian_form(form=None, item_values=None, selected_date: str | None = None):
    schedule_date = parse_iso_date(
        selected_date or (form.get("schedule_date") if form else None),
        today_iso(),
    )
    is_express = (form.get("is_express") if form else "0") == "1"
    return render_template(
        "antrian_form.html",
        form=form or {},
        item_values=item_values or [],
        services=get_active_services(),
        payment_statuses=PAYMENT_STATUSES,
        schedule_slots=get_schedule_slots(schedule_date, express_mode=is_express),
        schedule_date=schedule_date,
        staff_options=get_active_staff(),
        stringers=STRINGERS,
        knot_types=KNOT_TYPES,
        variations=VARIATIONS,
        grommet_options=GROMMET_OPTIONS,
        max_racket_count=MAX_RACKET_COUNT,
    )


@app.route("/antrian/tambah", methods=["GET", "POST"])
@login_required
def antrian_add():
    if request.method == "POST":
        def fail_with_draft(message: str, category: str = "danger"):
            save_antrian_form_draft(request.form, item_values)
            flash(message, category)
            return render_antrian_form(request.form, item_values, schedule_date)

        manual_queue_number = request.form.get("queue_number", "").strip()
        customer_name = request.form.get("customer_name", "").strip()
        phone = request.form.get("phone", "").strip()
        branch = request.form.get("branch", "Mega Sports").strip()
        service_type = request.form.get("service_type", "").strip()
        staff_name = request.form.get("staff_name", "").strip()
        payment_status = request.form.get("payment_status", "BELUM BAYAR").strip()
        schedule_date = parse_iso_date(request.form.get("schedule_date"), today_iso())
        schedule_time = request.form.get("schedule_time", "").strip()
        stringer_name = request.form.get("stringer_name", "").strip()
        express_value = request.form.get("is_express", "0")
        is_express = 1 if express_value == "1" else 0
        note = request.form.get("note", "").strip()

        try:
            racket_count = int(request.form.get("racket_count", "1"))
        except ValueError:
            racket_count = 0

        item_values, item_errors = collect_ticket_items(
            request.form,
            racket_count if 1 <= racket_count <= MAX_RACKET_COUNT else 1,
            service_type,
        )

        if not customer_name:
            return fail_with_draft("Nama customer wajib diisi.")
        if phone and not PHONE_PATTERN.fullmatch(phone):
            return fail_with_draft("Nomor WhatsApp hanya boleh berisi angka, +, spasi, atau strip.")
        if branch not in BRANCHES:
            return fail_with_draft("Cabang tidak valid.")
        if service_type not in SERVICE_TYPES:
            return fail_with_draft("Jenis layanan tidak valid.")
        if staff_name not in get_active_staff():
            return fail_with_draft("Nama staff yang menjuali wajib dipilih.")
        if not 1 <= racket_count <= MAX_RACKET_COUNT:
            return fail_with_draft(f"Jumlah raket harus antara 1 sampai {MAX_RACKET_COUNT}.")
        if stringer_name not in STRINGERS:
            return fail_with_draft("Nama stringer wajib dipilih.")
        if payment_status not in PAYMENT_STATUSES:
            return fail_with_draft("Status pembayaran tidak valid.")
        if express_value not in {"0", "1"}:
            return fail_with_draft("Pilihan express tidak valid.")
        estimated_finish = build_estimated_finish(schedule_date, schedule_time)
        if estimated_finish is None:
            return fail_with_draft("Tanggal atau jam estimasi selesai tidak valid.")
        slot_ok, slot_error = validate_selected_slot(schedule_date, schedule_time, racket_count, is_express=bool(is_express))
        if not slot_ok:
            return fail_with_draft(slot_error)
        if item_errors:
            save_antrian_form_draft(request.form, item_values)
            for error in item_errors:
                flash(error, "danger")
            return render_antrian_form(request.form, item_values, schedule_date)

        db = get_db()
        queue_number = manual_queue_number or generate_queue_number(branch)
        if not queue_number:
            return fail_with_draft("Nomor antrian wajib diisi.")
        duplicate = db.execute(
            """
            SELECT id
            FROM queue_tickets
            WHERE queue_date = ? AND queue_number = ?
            LIMIT 1
            """,
            (today_iso(), queue_number),
        ).fetchone()
        if duplicate:
            return fail_with_draft("Nomor antrian/nota sudah digunakan pada tanggal hari ini.")

        first_item = item_values[0]
        try:
            db.execute("BEGIN")
            cursor = db.execute(
                """
                INSERT INTO queue_tickets (
                    queue_number, queue_date, customer_name, phone, branch, service_type,
                    racket_type, racket_brand, string_type, tension_lbs, racket_count,
                    staff_name,
                    is_express, stringer_name, note, status, payment_status, estimated_finish
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'MENUNGGU', ?, ?)
                """,
                (
                    queue_number,
                    today_iso(),
                    customer_name,
                    phone,
                    branch,
                    service_type,
                    first_item["racket_type"],
                    first_item["racket_brand"],
                    first_item["string_type"],
                    first_item["tension_lbs"],
                    racket_count,
                    staff_name,
                    is_express,
                    stringer_name,
                    note,
                    payment_status,
                    estimated_finish,
                ),
            )
            ticket_id = cursor.lastrowid
            db.executemany(
                """
                INSERT INTO queue_ticket_items (
                    ticket_id, item_number, racket_type, racket_brand, string_type,
                    tension_lbs, knot_type, variation, grommet, racket_note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        ticket_id,
                        item["item_number"],
                        item["racket_type"],
                        item["racket_brand"],
                        item["string_type"],
                        item["tension_lbs"],
                        item["knot_type"],
                        item["variation"],
                        item["grommet"],
                        item["racket_note"],
                    )
                    for item in item_values
                ],
            )
            db.commit()
        except sqlite3.Error:
            db.rollback()
            logger.exception("Failed to save queue ticket")
            return fail_with_draft("Gagal menyimpan antrian. Silakan coba lagi.")

        pop_antrian_form_draft()
        flash(f"Antrian {queue_number} berhasil dibuat.", "success")
        return redirect(url_for("antrian_list"))

    draft = get_antrian_form_draft()
    if draft:
        draft_form = draft.get("form") or {}
        draft_items = draft.get("item_values") or []
        return render_antrian_form(draft_form, draft_items, draft_form.get("schedule_date"))
    return render_antrian_form(selected_date=today_iso())


@app.route("/antrian/status/<int:ticket_id>/<action>", methods=["POST"])
@login_required
def update_status(ticket_id: int, action: str):
    action_map = {
        "panggil": ("DIPANGGIL", "called_at"),
        "proses": ("DIPROSES", "started_at"),
        "selesai": ("SELESAI", "finished_at"),
        "diambil": ("DIAMBIL", "picked_up_at"),
        "batal": ("BATAL", "canceled_at"),
    }
    if action not in action_map:
        flash("Aksi status tidak valid.", "danger")
        return redirect_back()

    status, timestamp_column = action_map[action]
    db = get_db()
    db.execute(
        f"UPDATE queue_tickets SET status = ?, {timestamp_column} = ? WHERE id = ?",
        (status, now_sql(), ticket_id),
    )
    db.commit()
    logger.info("Ticket status updated ticket_id=%s status=%s", ticket_id, status)
    flash(f"Status antrian diperbarui menjadi {status}.", "success")
    return redirect_back()


@app.route("/layar-monitor")
def layar_monitor():
    return render_template("layar_monitor.html")


@app.route("/api/antrian/monitor")
def api_antrian_monitor():
    db = get_db()
    selected_date = clamp_iso_date(request.args.get("date"))
    current = db.execute(
        """
        SELECT queue_number, customer_name, service_type, status, branch, racket_count, is_express, estimated_finish, stringer_name
        FROM queue_tickets
        WHERE (date(estimated_finish) = ? OR (estimated_finish IS NULL AND queue_date = ?))
          AND status IN ('DIPANGGIL', 'DIPROSES')
        ORDER BY
          CASE WHEN status = 'DIPANGGIL' THEN 0 ELSE 1 END,
          COALESCE(called_at, started_at, created_at) DESC,
          id DESC
        LIMIT 1
        """,
        (selected_date, selected_date),
    ).fetchone()
    waiting_rows = db.execute(
        """
        SELECT queue_number, customer_name, service_type, status, branch, racket_count, is_express, estimated_finish, stringer_name
        FROM queue_tickets
        WHERE (date(estimated_finish) = ? OR (estimated_finish IS NULL AND queue_date = ?))
          AND status = 'MENUNGGU'
        ORDER BY created_at ASC, id ASC
        LIMIT 10
        """,
        (selected_date, selected_date),
    ).fetchall()
    waiting_process_rows = db.execute(
        """
        SELECT queue_number, customer_name, service_type, status, branch, racket_count, is_express, estimated_finish, stringer_name
        FROM queue_tickets
        WHERE (date(estimated_finish) = ? OR (estimated_finish IS NULL AND queue_date = ?))
          AND status IN ('MENUNGGU', 'DIPANGGIL')
        ORDER BY COALESCE(called_at, created_at) DESC, created_at DESC, id DESC
        """,
        (selected_date, selected_date),
    ).fetchall()
    in_process_rows = db.execute(
        """
        SELECT queue_number, customer_name, service_type, status, branch, racket_count, is_express, estimated_finish, stringer_name
        FROM queue_tickets
        WHERE (date(estimated_finish) = ? OR (estimated_finish IS NULL AND queue_date = ?))
          AND status = 'DIPROSES'
        ORDER BY COALESCE(started_at, called_at, created_at) DESC, id DESC
        """,
        (selected_date, selected_date),
    ).fetchall()
    completed_rows = db.execute(
        """
        SELECT queue_number, customer_name, service_type, status, branch, racket_count, is_express, estimated_finish, stringer_name
        FROM queue_tickets
        WHERE (date(estimated_finish) = ? OR (estimated_finish IS NULL AND queue_date = ?))
          AND status = 'SELESAI'
        ORDER BY COALESCE(finished_at, estimated_finish, created_at) DESC, id DESC
        """,
        (selected_date, selected_date),
    ).fetchall()

    return jsonify(
        {
            "current": ticket_to_dict(current),
            "waiting": [ticket_to_dict(row) for row in waiting_rows],
            "schedule_slots": get_schedule_slots(selected_date),
            "waiting_process": [ticket_to_dict(row) for row in waiting_process_rows],
            "in_process": [ticket_to_dict(row) for row in in_process_rows],
            "completed": [ticket_to_dict(row) for row in completed_rows],
            "selected_date": selected_date,
            "updated_at": now_sql(),
        }
    )


@app.route("/api/schedule-slots")
@login_required
def api_schedule_slots():
    schedule_date = clamp_iso_date(request.args.get("date"))
    express_mode = request.args.get("express") == "1"
    return jsonify({"schedule_slots": get_schedule_slots(schedule_date, express_mode=express_mode), "date": schedule_date})


@app.route("/monitoring")
@login_required
def monitoring():
    selected_status = request.args.get("status", "").strip()
    selected_branch = request.args.get("branch", "").strip()
    conditions = ["queue_date = ?"]
    params: list[str] = [today_iso()]

    if selected_status in STATUSES:
        conditions.append("status = ?")
        params.append(selected_status)
    else:
        selected_status = ""

    if selected_branch in BRANCHES:
        aliases = branch_aliases(selected_branch)
        placeholders = ",".join("?" for _ in aliases)
        conditions.append(f"branch IN ({placeholders})")
        params.extend(aliases)
    else:
        selected_branch = ""

    db = get_db()
    tickets = db.execute(
        f"""
        SELECT *
        FROM queue_tickets
        WHERE {" AND ".join(conditions)}
        ORDER BY created_at DESC, id DESC
        """,
        params,
    ).fetchall()
    return render_template(
        "monitoring.html",
        tickets=tickets,
        selected_status=selected_status,
        selected_branch=selected_branch,
    )


@app.route("/laporan")
@login_required
def laporan():
    today = today_iso()
    start_date = request.args.get("start_date") or today
    end_date = request.args.get("end_date") or today

    try:
        start_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        flash("Format tanggal tidak valid.", "danger")
        start_obj = end_obj = current_datetime().date()
        start_date = end_date = today

    if end_obj < start_obj:
        start_obj, end_obj = end_obj, start_obj
        start_date, end_date = start_obj.isoformat(), end_obj.isoformat()

    db = get_db()
    tickets = db.execute(
        """
        SELECT *
        FROM queue_tickets
        WHERE queue_date BETWEEN ? AND ?
        ORDER BY queue_date DESC, created_at DESC, id DESC
        """,
        (start_date, end_date),
    ).fetchall()
    summary = {
        "total": len(tickets),
        "selesai": sum(1 for ticket in tickets if ticket["status"] in ("SELESAI", "DIAMBIL")),
        "batal": sum(1 for ticket in tickets if ticket["status"] == "BATAL"),
    }
    avg_row = db.execute(
        """
        SELECT AVG((julianday(finished_at) - julianday(started_at)) * 24 * 60) AS avg_minutes
        FROM queue_tickets
        WHERE queue_date BETWEEN ? AND ?
          AND started_at IS NOT NULL
          AND finished_at IS NOT NULL
        """,
        (start_date, end_date),
    ).fetchone()
    summary["avg_minutes"] = round(avg_row["avg_minutes"] or 0)

    if request.args.get("export") == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Tanggal",
                "Nomor Antrian",
                "Nama Customer",
                "Cabang",
                "Layanan",
                "Jumlah Raket",
                "Raket Utama",
                "Senar",
                "Tarikan LBS",
                "Stringer",
                "Status",
                "Express",
                "Pembayaran",
                "Estimasi Selesai",
            ]
        )
        for ticket in tickets:
            writer.writerow(
                [
                    ticket["queue_date"],
                    ticket["queue_number"],
                    ticket["customer_name"],
                    ticket["branch"],
                    ticket["service_type"],
                    ticket["racket_count"] or 1,
                    ticket["racket_brand"] or ticket["racket_type"] or "",
                    ticket["string_type"] or "",
                    ticket["tension_lbs"] or "",
                    ticket["stringer_name"] or "",
                    ticket["status"],
                    "Ya" if ticket["is_express"] else "Tidak",
                    ticket["payment_status"],
                    ticket["estimated_finish"] or "",
                ]
            )
        filename = f"laporan-antrian-{start_date}-sd-{end_date}.csv"
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    return render_template(
        "laporan.html",
        tickets=tickets,
        summary=summary,
        start_date=start_date,
        end_date=end_date,
    )


@app.route("/users")
@login_required
def users():
    db = get_db()
    user_rows = db.execute(
        "SELECT id, name, username, role, created_at FROM users ORDER BY created_at DESC, id DESC"
    ).fetchall()
    return render_template("users.html", users=user_rows)


@app.route("/account", methods=["GET", "POST"])
@login_required
def account():
    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE id = ?",
        (session["user_id"],),
    ).fetchone()
    if user is None:
        session.clear()
        flash("Sesi akun tidak valid. Silakan login ulang.", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        old_password = request.form.get("old_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        must_change_password = bool(user["must_change_password"]) if "must_change_password" in user.keys() else False

        if not name or not username:
            flash("Nama dan username wajib diisi.", "danger")
            return render_template("account.html", user=user)

        duplicate = db.execute(
            "SELECT id FROM users WHERE username = ? AND id != ?",
            (username, user["id"]),
        ).fetchone()
        if duplicate:
            flash("Username sudah digunakan akun lain.", "danger")
            return render_template("account.html", user=user)

        password_hash = user["password_hash"]
        password_changed = False
        if must_change_password and not new_password:
            flash("Akun ini wajib mengganti password sebelum lanjut.", "danger")
            return render_template("account.html", user=user)

        if new_password or confirm_password or old_password:
            if not check_password_hash(user["password_hash"], old_password):
                flash("Password lama tidak benar.", "danger")
                return render_template("account.html", user=user)
            if new_password != confirm_password:
                flash("Konfirmasi password baru tidak sama.", "danger")
                return render_template("account.html", user=user)
            password_errors = validate_password_policy(new_password)
            if password_errors:
                for error in password_errors:
                    flash(error, "danger")
                return render_template("account.html", user=user)
            password_hash = generate_password_hash(new_password)
            password_changed = True

        db.execute(
            """
            UPDATE users
            SET name = ?, username = ?, password_hash = ?, must_change_password = ?
            WHERE id = ?
            """,
            (name, username, password_hash, 0 if password_changed else int(must_change_password), user["id"]),
        )
        db.commit()
        session["name"] = name
        session["must_change_password"] = False if password_changed else must_change_password
        if password_changed:
            logger.info("Password updated user_id=%s", user["id"])
        flash("Akun berhasil diperbarui.", "success")
        return redirect(url_for("account"))

    return render_template("account.html", user=user)


@app.route("/settings")
@login_required
def settings():
    db = get_db()
    setting_rows = db.execute("SELECT setting_key, setting_value FROM settings ORDER BY id").fetchall()
    settings_map = {row["setting_key"]: row["setting_value"] for row in setting_rows}
    return render_template("settings.html", settings=settings_map)


@app.errorhandler(400)
def bad_request(error):
    return "Permintaan tidak valid.", 400


@app.errorhandler(404)
def not_found(error):
    return "Halaman tidak ditemukan.", 404


@app.errorhandler(500)
def internal_error(error):
    logger.exception("Unhandled application error")
    return "Terjadi kesalahan aplikasi.", 500


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
