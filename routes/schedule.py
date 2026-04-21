import json
from datetime import date as date_cls, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session

from database import get_db
from services.announcement_center import (
    build_schedule_change_notification_payload,
    create_schedule_change_event,
    format_date_range,
)
from services.attendance_request_service import (
    can_manage_attendance_request_approvals,
    queue_attendance_request,
)
from services.notification_service import notify_broadcast
from services.rbac import has_permission, is_scoped_role


schedule_bp = Blueprint("schedule", __name__, url_prefix="/schedule")

DEFAULT_SHIFT_CODES = (
    ("P", "Pagi", "#c6e5ab", "#17351a", 10),
    ("S", "Siang", "#ffe8a2", "#4b3500", 20),
    ("PM", "Pagi Menengah", "#b7dfc7", "#0f3a2b", 30),
    ("PS10", "Pagi 10", "#b9e8f2", "#0e4354", 40),
    ("OFF", "Off", "#f59c8b", "#7c1f1f", 50),
    ("SM", "Shift Malam", "#d7c2f5", "#35205d", 60),
    ("SO1", "Stock Opname 1", "#e5ecf6", "#23384e", 70),
    ("SO2", "Stock Opname 2", "#d8e4ff", "#234a87", 80),
)

LIVE_SCHEDULE_SLOTS = (
    ("09:00", "9:00"),
    ("10:00", "10:00"),
    ("11:00", "11:00"),
    ("12:00", "12:00"),
    ("13:00", "13:00"),
    ("14:00", "14:00"),
    ("15:00", "15:00"),
    ("16:00", "16:00"),
    ("17:00", "17:00"),
    ("18:00", "18:00"),
    ("19:00", "19:00"),
    ("20:00-20:45", "20:00 - 20:45"),
)
LIVE_SCHEDULE_SLOT_KEYS = {slot_key for slot_key, _ in LIVE_SCHEDULE_SLOTS}
LEGACY_LIVE_SCHEDULE_DEFAULT_BG = "#C6E5AB"
LEGACY_LIVE_SCHEDULE_DEFAULT_TEXT = "#17351A"
SCHEDULE_DEFAULT_BG = "#D7E3F4"
SCHEDULE_DEFAULT_TEXT = "#17304A"
LIVE_SCHEDULE_DEFAULT_BG = SCHEDULE_DEFAULT_BG
LIVE_SCHEDULE_DEFAULT_TEXT = SCHEDULE_DEFAULT_TEXT
SCHEDULE_LIGHT_SURFACE = "#F6FAFE"
SCHEDULE_DARK_SURFACE = "#132033"
LIVE_SCHEDULE_LIGHT_SURFACE = "#F7FAFD"
LIVE_SCHEDULE_DARK_SURFACE = "#0F1928"
SCHEDULE_LIGHT_TEXT = "#17304A"
SCHEDULE_DARK_TEXT = "#F6FBFF"
SCHEDULE_OFF_STYLE = ("OFF", "Off", "#f59c8b", "#7c1f1f")

LEAVE_OVERRIDE_STYLES = {
    "annual": SCHEDULE_OFF_STYLE,
    "sick": SCHEDULE_OFF_STYLE,
    "permit": SCHEDULE_OFF_STYLE,
    "unpaid": SCHEDULE_OFF_STYLE,
    "special": SCHEDULE_OFF_STYLE,
}

ATTENDANCE_OVERRIDE_STYLES = {
    "leave": SCHEDULE_OFF_STYLE,
    "absent": ("ABSEN", "Tidak Hadir", "#f28a8a", "#6e1717"),
    "half_day": ("HALF", "Half Day", "#bde3f7", "#114764"),
}

EMPLOYMENT_OVERRIDE_STYLES = {
    "leave": SCHEDULE_OFF_STYLE,
    "inactive": ("NA", "Tidak Aktif", "#d7dee8", "#33465b"),
}

OFFBOARDING_STYLE = ("OFFBD", "Offboarding", "#f49797", "#6d1616")
SCHEDULE_DAY_OPTIONS = (7, 14, 30, 60, 90)
MAX_SCHEDULE_DAY_RANGE = max(SCHEDULE_DAY_OPTIONS)
SCHEDULE_DAY_NAMES = (
    "Senin",
    "Selasa",
    "Rabu",
    "Kamis",
    "Jumat",
    "Sabtu",
    "Minggu",
)
SCHEDULE_MONTH_NAMES = (
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)


def _to_int(value, default=None):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_iso_date(value):
    if not value:
        return None

    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        return None


def _normalize_hex_color(value, fallback):
    color = (value or "").strip()
    if len(color) == 7 and color.startswith("#"):
        return color.upper()
    return fallback


def _hex_to_rgb_components(value, fallback):
    safe_color = _normalize_hex_color(value, fallback)
    return tuple(int(safe_color[index:index + 2], 16) for index in (1, 3, 5))


def _rgba_from_hex(value, alpha, fallback):
    red, green, blue = _hex_to_rgb_components(value, fallback)
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _blend_hex_colors(primary, secondary, ratio, fallback):
    safe_ratio = max(0.0, min(float(ratio or 0), 1.0))
    first = _hex_to_rgb_components(primary, fallback)
    second = _hex_to_rgb_components(secondary, fallback)
    mixed = tuple(round((left * (1 - safe_ratio)) + (right * safe_ratio)) for left, right in zip(first, second))
    return "#{:02X}{:02X}{:02X}".format(*mixed)


def _relative_luminance(value, fallback):
    red, green, blue = _hex_to_rgb_components(value, fallback)

    def _srgb_to_linear(channel):
        normalized = channel / 255
        if normalized <= 0.04045:
            return normalized / 12.92
        return ((normalized + 0.055) / 1.055) ** 2.4

    return (
        (0.2126 * _srgb_to_linear(red))
        + (0.7152 * _srgb_to_linear(green))
        + (0.0722 * _srgb_to_linear(blue))
    )


def _contrast_ratio(color_a, color_b, fallback):
    luminance_a = _relative_luminance(color_a, fallback)
    luminance_b = _relative_luminance(color_b, fallback)
    lighter = max(luminance_a, luminance_b)
    darker = min(luminance_a, luminance_b)
    return (lighter + 0.05) / (darker + 0.05)


def _pick_accessible_text(background_color, preferred_color, dark_fallback, light_fallback):
    safe_background = _normalize_hex_color(background_color, dark_fallback)
    safe_preferred = _normalize_hex_color(preferred_color, dark_fallback)
    safe_dark = _normalize_hex_color(dark_fallback, dark_fallback)
    safe_light = _normalize_hex_color(light_fallback, light_fallback)

    preferred_ratio = _contrast_ratio(safe_background, safe_preferred, safe_dark)
    if preferred_ratio >= 4.25:
        return safe_preferred

    candidates = [safe_dark, safe_light]
    return max(
        candidates,
        key=lambda candidate: _contrast_ratio(safe_background, candidate, safe_dark),
    )


def _build_schedule_chip_color_tokens(bg_color=None, text_color=None):
    safe_bg = _normalize_hex_color(bg_color, SCHEDULE_DEFAULT_BG)
    safe_text = _normalize_hex_color(text_color, SCHEDULE_DEFAULT_TEXT)
    light_bg = _blend_hex_colors(SCHEDULE_LIGHT_SURFACE, safe_bg, 0.34, SCHEDULE_LIGHT_SURFACE)
    dark_bg = _blend_hex_colors(SCHEDULE_DARK_SURFACE, safe_bg, 0.32, SCHEDULE_DARK_SURFACE)
    light_text = _pick_accessible_text(light_bg, safe_text, SCHEDULE_LIGHT_TEXT, SCHEDULE_DARK_TEXT)
    dark_text = _pick_accessible_text(dark_bg, safe_text, SCHEDULE_LIGHT_TEXT, SCHEDULE_DARK_TEXT)
    return {
        "bg_color": safe_bg,
        "text_color": safe_text,
        "light_bg_color": light_bg,
        "dark_bg_color": dark_bg,
        "light_text_color": light_text,
        "dark_text_color": dark_text,
        "light_border_color": _rgba_from_hex(safe_bg, 0.18, SCHEDULE_DEFAULT_BG),
        "dark_border_color": _rgba_from_hex(safe_bg, 0.24, SCHEDULE_DEFAULT_BG),
    }


def _build_live_schedule_color_tokens(bg_color=None, text_color=None):
    safe_bg = _normalize_hex_color(bg_color, LIVE_SCHEDULE_DEFAULT_BG)
    safe_text = _normalize_hex_color(text_color, LIVE_SCHEDULE_DEFAULT_TEXT)
    light_bg = _blend_hex_colors(LIVE_SCHEDULE_LIGHT_SURFACE, safe_bg, 0.24, LIVE_SCHEDULE_LIGHT_SURFACE)
    dark_bg = _blend_hex_colors(LIVE_SCHEDULE_DARK_SURFACE, safe_bg, 0.32, LIVE_SCHEDULE_DARK_SURFACE)
    light_text = _pick_accessible_text(light_bg, safe_text, SCHEDULE_LIGHT_TEXT, SCHEDULE_DARK_TEXT)
    dark_text = _pick_accessible_text(dark_bg, safe_text, SCHEDULE_LIGHT_TEXT, SCHEDULE_DARK_TEXT)
    return {
        "bg_color": safe_bg,
        "text_color": safe_text,
        "light_bg_color": light_bg,
        "dark_bg_color": dark_bg,
        "light_text_color": light_text,
        "dark_text_color": dark_text,
        "light_channel_color": _rgba_from_hex(light_text, 0.72, SCHEDULE_LIGHT_TEXT),
        "dark_channel_color": _rgba_from_hex(dark_text, 0.78, SCHEDULE_DARK_TEXT),
        "light_note_color": _rgba_from_hex(light_text, 0.84, SCHEDULE_LIGHT_TEXT),
        "dark_note_color": _rgba_from_hex(dark_text, 0.88, SCHEDULE_DARK_TEXT),
        "light_border_color": _rgba_from_hex(safe_bg, 0.18, LIVE_SCHEDULE_DEFAULT_BG),
        "dark_border_color": _rgba_from_hex(safe_bg, 0.28, LIVE_SCHEDULE_DEFAULT_BG),
        "light_shadow_color": _rgba_from_hex(safe_bg, 0.12, LIVE_SCHEDULE_DEFAULT_BG),
        "dark_shadow_color": _rgba_from_hex(safe_bg, 0.22, LIVE_SCHEDULE_DEFAULT_BG),
        "light_check_bg_color": _blend_hex_colors(light_bg, "#FFFFFF", 0.42, light_bg),
        "dark_check_bg_color": _blend_hex_colors(dark_bg, "#FFFFFF", 0.08, dark_bg),
        "light_check_border_color": _rgba_from_hex(light_text, 0.18, SCHEDULE_LIGHT_TEXT),
        "dark_check_border_color": _rgba_from_hex(dark_text, 0.22, SCHEDULE_DARK_TEXT),
        "light_check_color": light_text,
        "dark_check_color": dark_text,
    }


def _parse_live_check_updates_json(raw_value):
    payload = (raw_value or "").strip()
    if not payload:
        return []

    try:
        loaded = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []

    if not isinstance(loaded, list):
        return []

    updates = []
    seen_keys = set()
    for item in loaded:
        if not isinstance(item, dict):
            continue

        warehouse_id = _to_int(item.get("warehouse_id"))
        schedule_date = _parse_iso_date(item.get("schedule_date"))
        slot_key = (item.get("slot_key") or "").strip()
        if not warehouse_id or not schedule_date or slot_key not in LIVE_SCHEDULE_SLOT_KEYS:
            continue

        unique_key = (warehouse_id, schedule_date.isoformat(), slot_key)
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        updates.append(
            {
                "warehouse_id": warehouse_id,
                "schedule_date": schedule_date,
                "slot_key": slot_key,
                "is_checked": _is_checked_form_value(item.get("is_checked")),
            }
        )
    return updates


def _default_schedule_start():
    today = date_cls.today()
    return today - timedelta(days=today.weekday())


def _clamp_days(value):
    days = _to_int(value, SCHEDULE_DAY_OPTIONS[0])
    if days in SCHEDULE_DAY_OPTIONS:
        return days
    return SCHEDULE_DAY_OPTIONS[0]


def _daterange(start_date, end_date):
    total_days = (end_date - start_date).days
    for offset in range(total_days + 1):
        yield start_date + timedelta(days=offset)


def _format_schedule_day(value):
    parts = _build_schedule_day_parts(value)
    return parts["full_label"]


def _default_shift_code_map():
    shift_code_map = {}
    for code, label, bg_color, text_color, sort_order in DEFAULT_SHIFT_CODES:
        shift_code_map[code] = {
            "code": code,
            "label": label,
            "sort_order": sort_order,
            "is_active": True,
            **_build_schedule_chip_color_tokens(bg_color, text_color),
        }
    return shift_code_map


def _build_schedule_day_parts(value):
    day_name = SCHEDULE_DAY_NAMES[value.weekday()]
    date_label = f"{value.day:02d} {SCHEDULE_MONTH_NAMES[value.month - 1]} {value.year}"
    return {
        "day_name": day_name,
        "date_label": date_label,
        "full_label": f"{day_name}, {date_label}",
    }


def _is_checked_form_value(value):
    return 1 if str(value or "").strip().lower() in {"1", "true", "on", "yes"} else 0


def _schedule_redirect():
    args = {}
    for key in ("start", "days", "warehouse"):
        value = request.form.get(key)
        if value not in (None, ""):
            args[key] = value

    if not args:
        return redirect("/schedule/")

    query_parts = "&".join(f"{key}={value}" for key, value in args.items())
    return redirect(f"/schedule/?{query_parts}")


def _shift_swap_redirect():
    args = {}
    for key in ("start", "days", "warehouse"):
        value = request.form.get(key)
        if value not in (None, ""):
            args[key] = value

    if not args:
        return redirect("/schedule/swap-request")

    query_parts = "&".join(f"{key}={value}" for key, value in args.items())
    return redirect(f"/schedule/swap-request?{query_parts}")


def _can_view_schedule():
    return has_permission(session.get("role"), "view_schedule")


def _can_manage_schedule():
    return has_permission(session.get("role"), "manage_schedule")


def _schedule_scope_warehouse():
    if is_scoped_role(session.get("role")):
        return session.get("warehouse_id")
    return None


def _require_schedule_view():
    if _can_view_schedule():
        return True

    flash("Akses penjadwalan ditolak.", "error")
    return False


def _require_schedule_manage():
    if _can_manage_schedule():
        return True

    flash("Hanya HR dan Super Admin yang bisa mengatur jadwal.", "error")
    return False


def _build_placeholders(values):
    return ",".join(["?"] * len(values))


def _get_selected_warehouse(warehouses):
    scoped_warehouse = _schedule_scope_warehouse()
    if scoped_warehouse:
        return scoped_warehouse

    selected_warehouse = _to_int(request.args.get("warehouse"))
    valid_ids = {warehouse["id"] for warehouse in warehouses}
    if selected_warehouse in valid_ids:
        return selected_warehouse
    return None


def _get_warehouse_label(warehouses, warehouse_id):
    if not warehouse_id:
        return "Semua Gudang"

    for warehouse in warehouses:
        if warehouse["id"] == warehouse_id:
            return warehouse["name"]
    return "Semua Gudang"


def _get_schedule_linked_employee(db):
    linked_employee_id = _to_int(session.get("employee_id"))
    if not linked_employee_id:
        linked_user_id = _to_int(session.get("user_id"))
        if linked_user_id:
            user_row = db.execute(
                "SELECT employee_id FROM users WHERE id=? LIMIT 1",
                (linked_user_id,),
            ).fetchone()
            linked_employee_id = _to_int(user_row["employee_id"] if user_row else None)

    if not linked_employee_id:
        return None

    return next(
        (
            row
            for row in _fetch_employees_for_schedule(db)
            if _to_int(row.get("employee_id")) == linked_employee_id
        ),
        None,
    )


def _build_shift_swap_partner_options(db, linked_employee):
    if not linked_employee:
        return []

    warehouse_id = _to_int(linked_employee.get("warehouse_id"))
    if not warehouse_id:
        return []
    partner_rows = _build_schedule_members(_fetch_employees_for_schedule(db, warehouse_id))
    partner_options = []
    for row in partner_rows:
        employee_id = _to_int(row.get("employee_id"))
        if not employee_id or employee_id == _to_int(linked_employee.get("employee_id")):
            continue
        partner_options.append(
            {
                "employee_id": employee_id,
                "full_name": row.get("full_name") or row.get("display_name") or "Staf",
                "display_name": row.get("display_name") or row.get("full_name") or "Staf",
                "position": row.get("position") or row.get("department") or "",
                "warehouse_name": row.get("warehouse_name") or linked_employee.get("warehouse_name") or "-",
                "label": " | ".join(
                    part
                    for part in [
                        str(row.get("full_name") or row.get("display_name") or "Staf").strip(),
                        str(row.get("position") or row.get("department") or "").strip(),
                        str(row.get("warehouse_name") or linked_employee.get("warehouse_name") or "").strip(),
                    ]
                    if part
                ),
            }
        )
    return partner_options


def _build_shift_swap_request_context(db, selected_warehouse):
    linked_employee = _get_schedule_linked_employee(db)
    if not linked_employee:
        return {
            "enabled": False,
            "linked_employee": None,
            "partner_options": [],
            "reason": "Form tuker shift muncul otomatis setelah akun ditautkan ke data karyawan.",
        }

    linked_employee = dict(linked_employee)
    linked_warehouse_id = _to_int(linked_employee.get("warehouse_id"))
    if not linked_warehouse_id:
        return {
            "enabled": False,
            "linked_employee": linked_employee,
            "partner_options": [],
            "reason": "Homebase karyawan belum diatur, jadi form tuker shift belum bisa dipakai.",
        }

    if selected_warehouse and linked_warehouse_id and int(selected_warehouse) != linked_warehouse_id:
        return {
            "enabled": False,
            "linked_employee": linked_employee,
            "partner_options": [],
            "reason": "Pengajuan tuker shift hanya tampil saat scope board sesuai homebase Anda.",
        }

    partner_options = _build_shift_swap_partner_options(db, linked_employee)
    if not partner_options:
        return {
            "enabled": False,
            "linked_employee": linked_employee,
            "partner_options": [],
            "reason": "Belum ada partner shift lain yang aktif di homebase Anda.",
        }

    return {
        "enabled": True,
        "linked_employee": linked_employee,
        "partner_options": partner_options,
        "reason": "",
    }


def _resolve_schedule_display_name(full_name, custom_name=None, employee_code=None):
    custom_label = (custom_name or "").strip()
    if custom_label:
        return custom_label

    safe_name = (full_name or "").strip()
    if safe_name:
        return safe_name.split()[0]

    fallback_code = (employee_code or "").strip()
    return fallback_code or "Staf"


def _resolve_schedule_location_label(location_label=None, warehouse_name=None, work_location=None):
    custom_label = (location_label or "").strip()
    if custom_label:
        return custom_label

    safe_warehouse = (warehouse_name or "").strip()
    if safe_warehouse:
        return safe_warehouse

    safe_work_location = (work_location or "").strip()
    return safe_work_location or "-"


def _seed_default_shift_codes(db):
    db.executemany(
        """
        INSERT OR IGNORE INTO schedule_shift_codes(
            code,
            label,
            bg_color,
            text_color,
            sort_order,
            is_active
        )
        VALUES (?,?,?,?,?,1)
        """,
        DEFAULT_SHIFT_CODES,
    )
    db.commit()


def _fetch_shift_codes(db):
    shift_codes = [
        dict(row)
        for row in db.execute(
            """
            SELECT code, label, bg_color, text_color, sort_order, is_active
            FROM schedule_shift_codes
            ORDER BY sort_order, code
            """
        ).fetchall()
    ]

    for shift_code in shift_codes:
        shift_code["is_active"] = bool(shift_code["is_active"])
        shift_code.update(_build_schedule_chip_color_tokens(shift_code["bg_color"], shift_code["text_color"]))

    active_shift_codes = [shift_code for shift_code in shift_codes if shift_code["is_active"]]
    shift_code_map = {shift_code["code"]: shift_code for shift_code in shift_codes}
    return shift_codes, active_shift_codes, shift_code_map


def _fetch_employees_for_schedule(db, warehouse_id=None):
    params = []
    query = """
        SELECT
            e.id AS employee_id,
            e.employee_code,
            e.full_name,
            e.warehouse_id,
            w.name AS warehouse_name,
            e.department,
            e.position,
            e.employment_status,
            e.work_location,
            COALESCE(sp.custom_name, '') AS custom_name,
            COALESCE(sp.display_group, '') AS display_group,
            COALESCE(sp.location_label, '') AS location_label,
            COALESCE(sp.display_order, 0) AS display_order,
            COALESCE(sp.include_in_schedule, 1) AS include_in_schedule,
            COALESCE(sp.note, '') AS profile_note,
            CASE WHEN ob.employee_id IS NULL THEN 0 ELSE 1 END AS has_offboarding
        FROM employees e
        LEFT JOIN warehouses w ON w.id = e.warehouse_id
        LEFT JOIN schedule_employee_profiles sp ON sp.employee_id = e.id
        LEFT JOIN (
            SELECT DISTINCT employee_id
            FROM offboarding_records
            WHERE status IN ('planned', 'in_progress', 'completed')
        ) ob ON ob.employee_id = e.id
        WHERE 1=1
    """

    if warehouse_id:
        query += " AND e.warehouse_id=?"
        params.append(warehouse_id)

    rows = [dict(row) for row in db.execute(query, params).fetchall()]

    for row in rows:
        row["display_name"] = _resolve_schedule_display_name(
            row["full_name"],
            row["custom_name"],
            row["employee_code"],
        )
        row["display_group_label"] = (
            (row["display_group"] or "").strip()
            or (row["position"] or "").strip()
            or (row["department"] or "").strip()
            or "Tim Operasional"
        )
        row["location_label_display"] = _resolve_schedule_location_label(
            row["location_label"],
            row["warehouse_name"],
            row["work_location"],
        )
        row["include_in_schedule"] = bool(row["include_in_schedule"])
        row["has_offboarding"] = bool(row["has_offboarding"])

    rows.sort(
        key=lambda row: (
            row["display_group_label"].lower(),
            row["display_order"],
            row["location_label_display"].lower(),
            row["display_name"].lower(),
            row["employee_id"],
        )
    )
    return rows


def _build_schedule_members(employee_rows):
    members = []
    for row in employee_rows:
        if not row["include_in_schedule"]:
            continue

        if row["employment_status"] == "inactive" and not row["has_offboarding"]:
            continue

        row["board_index"] = len(members)
        members.append(row)
    return members


def _build_schedule_groups(schedule_members):
    groups = []
    current_group = None
    for member in schedule_members:
        label = member["display_group_label"]
        if current_group is None or current_group["label"] != label:
            current_group = {"label": label, "members": []}
            groups.append(current_group)
        current_group["members"].append(member)
    return groups


def _build_entry_map(db, employee_ids, start_date, end_date, shift_code_map):
    if not employee_ids:
        return {}

    placeholders = _build_placeholders(employee_ids)
    params = list(employee_ids)
    params.extend([start_date.isoformat(), end_date.isoformat()])

    rows = db.execute(
        f"""
        SELECT employee_id, schedule_date, shift_code, note, updated_at
        FROM schedule_entries
        WHERE employee_id IN ({placeholders})
          AND schedule_date BETWEEN ? AND ?
        """,
        params,
    ).fetchall()

    entry_map = {}
    for row in rows:
        shift_meta = shift_code_map.get(row["shift_code"], {})
        code = row["shift_code"] or "-"
        label = shift_meta.get("label") or code
        note = (row["note"] or "").strip()
        title = f"{label} (manual)"
        if note:
            title = f"{title} - {note}"
        color_tokens = _build_schedule_chip_color_tokens(
            shift_meta.get("bg_color"),
            shift_meta.get("text_color"),
        )
        entry_map[(row["employee_id"], row["schedule_date"])] = {
            "code": code,
            "shift_code": row["shift_code"] or code,
            "label": label,
            "note": note,
            "source": "manual",
            "title": title,
            **color_tokens,
        }
    return entry_map


def _set_override(override_map, employee_id, schedule_date, payload, priority):
    key = (employee_id, schedule_date)
    current = override_map.get(key)
    if current and current["priority"] > priority:
        return

    override_map[key] = {
        "code": payload["code"],
        "label": payload["label"],
        "note": payload.get("note", ""),
        "source": payload["source"],
        "title": payload["title"],
        "priority": priority,
        **_build_schedule_chip_color_tokens(payload["bg_color"], payload["text_color"]),
    }


def _build_override_map(db, employees, start_date, end_date):
    if not employees:
        return {}

    employee_ids = [employee["employee_id"] for employee in employees]
    placeholders = _build_placeholders(employee_ids)
    params_range = [start_date.isoformat(), end_date.isoformat()]
    employee_lookup = {employee["employee_id"]: employee for employee in employees}
    override_map = {}

    offboarding_rows = db.execute(
        f"""
        SELECT employee_id, last_working_date, note
        FROM offboarding_records
        WHERE employee_id IN ({placeholders})
          AND status IN ('planned', 'in_progress', 'completed')
          AND last_working_date IS NOT NULL
        """,
        employee_ids,
    ).fetchall()

    for row in offboarding_rows:
        effective_date = _parse_iso_date(row["last_working_date"])
        if not effective_date:
            continue
        effective_start = max(effective_date, start_date)
        for current_day in _daterange(effective_start, end_date):
            note = (row["note"] or "").strip()
            title = OFFBOARDING_STYLE[1]
            if note:
                title = f"{title} - {note}"
            _set_override(
                override_map,
                row["employee_id"],
                current_day.isoformat(),
                {
                    "code": OFFBOARDING_STYLE[0],
                    "label": OFFBOARDING_STYLE[1],
                    "bg_color": OFFBOARDING_STYLE[2],
                    "text_color": OFFBOARDING_STYLE[3],
                    "source": "offboarding",
                    "note": note,
                    "title": title,
                },
                400,
            )

    leave_rows = db.execute(
        f"""
        SELECT employee_id, leave_type, start_date, end_date, reason, note
        FROM leave_requests
        WHERE employee_id IN ({placeholders})
          AND status='approved'
          AND NOT (end_date < ? OR start_date > ?)
        """,
        employee_ids + params_range,
    ).fetchall()

    for row in leave_rows:
        leave_start = _parse_iso_date(row["start_date"])
        leave_end = _parse_iso_date(row["end_date"])
        if not leave_start or not leave_end:
            continue

        effective_start = max(leave_start, start_date)
        effective_end = min(leave_end, end_date)
        if effective_end < effective_start:
            continue

        code, label, bg_color, text_color = LEAVE_OVERRIDE_STYLES.get(
            (row["leave_type"] or "").strip().lower(),
            LEAVE_OVERRIDE_STYLES["annual"],
        )
        title = label

        for current_day in _daterange(effective_start, effective_end):
            _set_override(
                override_map,
                row["employee_id"],
                current_day.isoformat(),
                {
                    "code": code,
                    "label": label,
                    "bg_color": bg_color,
                    "text_color": text_color,
                    "source": "leave",
                    "note": "",
                    "title": title,
                },
                300,
            )

    attendance_rows = db.execute(
        f"""
        SELECT employee_id, attendance_date, status, note
        FROM attendance_records
        WHERE employee_id IN ({placeholders})
          AND attendance_date BETWEEN ? AND ?
          AND status IN ('leave', 'absent', 'half_day')
        """,
        employee_ids + params_range,
    ).fetchall()

    for row in attendance_rows:
        status_key = (row["status"] or "").strip().lower()
        style = ATTENDANCE_OVERRIDE_STYLES.get(status_key)
        if not style:
            continue
        note = "" if status_key == "leave" else (row["note"] or "").strip()
        title = style[1]
        if note:
            title = f"{title} - {note}"
        _set_override(
            override_map,
            row["employee_id"],
            row["attendance_date"],
            {
                "code": style[0],
                "label": style[1],
                "bg_color": style[2],
                "text_color": style[3],
                "source": "attendance",
                "note": note,
                "title": title,
            },
            200,
        )

    for employee in employees:
        style = EMPLOYMENT_OVERRIDE_STYLES.get((employee["employment_status"] or "").strip().lower())
        if not style:
            continue

        for current_day in _daterange(start_date, end_date):
            _set_override(
                override_map,
                employee["employee_id"],
                current_day.isoformat(),
                {
                    "code": style[0],
                    "label": style[1],
                    "bg_color": style[2],
                    "text_color": style[3],
                    "source": "employment",
                    "title": style[1],
                },
                100,
            )

    return override_map


def _build_day_notes(db, start_date, end_date):
    day_notes = {}
    rows = db.execute(
        """
        SELECT schedule_date, note
        FROM schedule_day_notes
        WHERE schedule_date BETWEEN ? AND ?
        """,
        (start_date.isoformat(), end_date.isoformat()),
    ).fetchall()
    for row in rows:
        day_notes[row["schedule_date"]] = (row["note"] or "").strip()
    return day_notes


def _build_board_rows(schedule_members, start_date, end_date, entry_map, override_map, day_notes):
    board_rows = []
    short_day_names = [
        "Sen",
        "Sel",
        "Rab",
        "Kam",
        "Jum",
        "Sab",
        "Min",
    ]
    today_value = date_cls.today()
    for current_day in _daterange(start_date, end_date):
        iso_date = current_day.isoformat()
        day_parts = _build_schedule_day_parts(current_day)
        cells = []
        for member in schedule_members:
            cell = override_map.get((member["employee_id"], iso_date)) or entry_map.get(
                (member["employee_id"], iso_date)
            )
            cells.append(cell)

        board_rows.append(
            {
                "iso_date": iso_date,
                "label": day_parts["full_label"],
                "day_name": day_parts["day_name"],
                "date_label": day_parts["date_label"],
                "day_short": short_day_names[current_day.weekday()],
                "day_number": f"{current_day.day:02d}",
                "month_number": f"{current_day.month:02d}",
                "is_weekend": current_day.weekday() >= 5,
                "is_today": current_day == today_value,
                "cells": cells,
                "note": day_notes.get(iso_date, ""),
            }
        )
    return board_rows


def resolve_employee_schedule_for_date(db, employee_id, target_date):
    target_day = target_date if isinstance(target_date, date_cls) else _parse_iso_date(target_date)
    if not target_day:
        return None

    try:
        safe_employee_id = int(employee_id or 0)
    except (TypeError, ValueError):
        safe_employee_id = 0
    if safe_employee_id <= 0:
        return None

    employee = next(
        (
            row
            for row in _fetch_employees_for_schedule(db)
            if int(row.get("employee_id") or 0) == safe_employee_id
        ),
        None,
    )
    if not employee:
        return None

    _, _, stored_shift_code_map = _fetch_shift_codes(db)
    shift_code_map = _default_shift_code_map()
    shift_code_map.update(stored_shift_code_map)
    iso_date = target_day.isoformat()
    entry_map = _build_entry_map(
        db,
        [safe_employee_id],
        target_day,
        target_day,
        shift_code_map,
    )
    override_map = _build_override_map(db, [employee], target_day, target_day)
    cell = override_map.get((safe_employee_id, iso_date)) or entry_map.get((safe_employee_id, iso_date))
    day_parts = _build_schedule_day_parts(target_day)
    return {
        "employee_id": safe_employee_id,
        "iso_date": iso_date,
        "day_name": day_parts["day_name"],
        "date_label": day_parts["date_label"],
        "full_label": day_parts["full_label"],
        "warehouse_name": employee.get("warehouse_name") or "",
        "display_name": employee.get("display_name") or employee.get("full_name") or "Staf",
        "has_schedule": bool(cell),
        "code": (cell or {}).get("code") or "",
        "shift_code": (cell or {}).get("shift_code") or (cell or {}).get("code") or "",
        "label": (cell or {}).get("label") or "",
        "note": (cell or {}).get("note") or "",
        "source": (cell or {}).get("source") or "",
        "title": (cell or {}).get("title") or "",
    }


def _validate_shift_swap_schedule(schedule_snapshot, actor_label):
    actor_name = str(actor_label or "Staff").strip() or "Staff"
    if not schedule_snapshot or not schedule_snapshot.get("has_schedule"):
        raise ValueError(f"{actor_name} belum punya shift aktif pada tanggal tersebut.")

    source = str(schedule_snapshot.get("source") or "").strip().lower()
    if source != "manual":
        raise ValueError(
            f"Shift {actor_name} pada tanggal tersebut bukan jadwal manual, jadi belum bisa dipakai untuk tuker shift."
        )

    shift_code = str(schedule_snapshot.get("shift_code") or schedule_snapshot.get("code") or "").strip().upper()
    if not shift_code:
        raise ValueError(f"Shift {actor_name} pada tanggal tersebut belum valid.")
    return shift_code


def resolve_employee_live_schedule_for_date(db, employee_id, target_date):
    target_day = target_date if isinstance(target_date, date_cls) else _parse_iso_date(target_date)
    if not target_day:
        return []

    try:
        safe_employee_id = int(employee_id or 0)
    except (TypeError, ValueError):
        safe_employee_id = 0
    if safe_employee_id <= 0:
        return []

    slot_label_map = dict(LIVE_SCHEDULE_SLOTS)
    slot_order_map = {slot_key: index for index, (slot_key, _) in enumerate(LIVE_SCHEDULE_SLOTS)}
    day_parts = _build_schedule_day_parts(target_day)
    rows = db.execute(
        """
        SELECT
            l.warehouse_id,
            l.schedule_date,
            l.slot_key,
            l.channel_label,
            l.note,
            l.bg_color,
            l.text_color,
            COALESCE(l.is_checked, 0) AS is_checked,
            w.name AS warehouse_name
        FROM schedule_live_entries l
        LEFT JOIN warehouses w ON w.id = l.warehouse_id
        WHERE l.employee_id=?
          AND l.schedule_date=?
        ORDER BY l.schedule_date ASC, l.slot_key ASC, l.id ASC
        """,
        (safe_employee_id, target_day.isoformat()),
    ).fetchall()

    live_entries = []
    for row in rows:
        slot_key = str(row["slot_key"] or "").strip()
        live_entries.append(
            {
                "employee_id": safe_employee_id,
                "warehouse_id": row["warehouse_id"],
                "warehouse_name": (row["warehouse_name"] or "").strip(),
                "iso_date": target_day.isoformat(),
                "day_name": day_parts["day_name"],
                "date_label": day_parts["date_label"],
                "full_label": day_parts["full_label"],
                "slot_key": slot_key,
                "slot_label": slot_label_map.get(slot_key, slot_key),
                "slot_order": slot_order_map.get(slot_key, 999),
                "channel_label": (row["channel_label"] or "").strip(),
                "note": (row["note"] or "").strip(),
                "is_checked": bool(row["is_checked"]),
                "bg_color": _normalize_hex_color(row["bg_color"], LIVE_SCHEDULE_DEFAULT_BG),
                "text_color": _normalize_hex_color(row["text_color"], LIVE_SCHEDULE_DEFAULT_TEXT),
            }
        )

    live_entries.sort(key=lambda item: (item["slot_order"], item["slot_key"]))
    return live_entries


def _build_live_schedule_sections(db, warehouses, selected_warehouse, start_date, end_date):
    if selected_warehouse:
        target_warehouses = [warehouse for warehouse in warehouses if warehouse["id"] == selected_warehouse]
    else:
        target_warehouses = list(warehouses)

    sections = []
    today_value = date_cls.today()
    for warehouse in target_warehouses:
        rows = db.execute(
            """
            SELECT
                l.schedule_date,
                l.slot_key,
                l.channel_label,
                l.note,
                l.bg_color,
                l.text_color,
                COALESCE(l.is_checked, 0) AS is_checked,
                l.employee_id,
                e.full_name,
                e.employee_code,
                w.name AS warehouse_name,
                e.work_location,
                COALESCE(sp.custom_name, '') AS custom_name,
                COALESCE(sp.location_label, '') AS location_label
            FROM schedule_live_entries l
            LEFT JOIN employees e ON e.id = l.employee_id
            LEFT JOIN warehouses w ON w.id = e.warehouse_id
            LEFT JOIN schedule_employee_profiles sp ON sp.employee_id = e.id
            WHERE l.warehouse_id=?
              AND l.schedule_date BETWEEN ? AND ?
            ORDER BY l.schedule_date, l.slot_key, l.id
            """,
            (warehouse["id"], start_date.isoformat(), end_date.isoformat()),
        ).fetchall()

        entry_map = {}
        total_assignments = 0
        for row in rows:
            color_tokens = _build_live_schedule_color_tokens(row["bg_color"], row["text_color"])
            entry_map[(row["schedule_date"], row["slot_key"])] = {
                "employee_id": row["employee_id"],
                "warehouse_id": warehouse["id"],
                "schedule_date": row["schedule_date"],
                "slot_key": row["slot_key"],
                "display_name": _resolve_schedule_display_name(
                    row["full_name"],
                    row["custom_name"],
                    row["employee_code"],
                ),
                "is_checked": bool(row["is_checked"]),
                "channel_label": (row["channel_label"] or "").strip(),
                "note": (row["note"] or "").strip(),
                "location_label_display": _resolve_schedule_location_label(
                    row["location_label"],
                    row["warehouse_name"],
                    row["work_location"],
                ),
                **color_tokens,
            }
            total_assignments += 1

        section_rows = []
        for current_day in _daterange(start_date, end_date):
            iso_date = current_day.isoformat()
            day_parts = _build_schedule_day_parts(current_day)
            section_rows.append(
                {
                    "iso_date": iso_date,
                    "label": day_parts["full_label"],
                    "day_name": day_parts["day_name"],
                    "date_label": day_parts["date_label"],
                    "is_weekend": current_day.weekday() >= 5,
                    "is_today": current_day == today_value,
                    "cells": [
                        entry_map.get((iso_date, slot_key))
                        for slot_key, _ in LIVE_SCHEDULE_SLOTS
                    ],
                }
            )

        sections.append(
            {
                "warehouse_id": warehouse["id"],
                "warehouse_name": warehouse["name"],
                "title": f"Jadwal Live {warehouse['name']}",
                "rows": section_rows,
                "total_assignments": total_assignments,
                "slot_count": len(LIVE_SCHEDULE_SLOTS),
            }
        )

    return sections


@schedule_bp.route("/")
def schedule_page():
    if not _require_schedule_view():
        return redirect("/")

    db = get_db()
    _seed_default_shift_codes(db)

    warehouses = db.execute(
        "SELECT id, name FROM warehouses ORDER BY id"
    ).fetchall()
    selected_warehouse = _get_selected_warehouse(warehouses)

    start_date = _parse_iso_date(request.args.get("start")) or _default_schedule_start()
    days = _clamp_days(request.args.get("days"))
    end_date = start_date + timedelta(days=days - 1)

    shift_codes, active_shift_codes, shift_code_map = _fetch_shift_codes(db)
    employee_rows = _fetch_employees_for_schedule(db, selected_warehouse)
    schedule_members = _build_schedule_members(employee_rows)
    schedule_groups = _build_schedule_groups(schedule_members)
    entry_map = _build_entry_map(
        db,
        [member["employee_id"] for member in schedule_members],
        start_date,
        end_date,
        shift_code_map,
    )
    override_map = _build_override_map(db, schedule_members, start_date, end_date)
    day_notes = _build_day_notes(db, start_date, end_date)
    board_rows = _build_board_rows(
        schedule_members,
        start_date,
        end_date,
        entry_map,
        override_map,
        day_notes,
    )
    live_sections = _build_live_schedule_sections(
        db,
        warehouses,
        selected_warehouse,
        start_date,
        end_date,
    )

    legend_items = [
        {
            "code": code,
            "label": label,
            **_build_schedule_chip_color_tokens(bg_color, text_color),
        }
        for code, label, bg_color, text_color in (
            ("OFF", "Leave / cuti tampil sebagai OFF", "#f59c8b", "#7c1f1f"),
            ("OFFBD", "Offboarding aktif", "#f49797", "#6d1616"),
            ("ABSEN", "Absensi tidak hadir", "#f28a8a", "#6e1717"),
        )
    ]

    summary = {
        "employees": len(schedule_members),
        "shift_codes": len(shift_codes),
        "manual_cells": len(entry_map),
        "override_cells": len(override_map),
    }

    filters = {
        "start": start_date.isoformat(),
        "days": days,
        "warehouse": selected_warehouse,
    }

    return render_template(
        "schedule.html",
        warehouses=warehouses,
        selected_warehouse_name=_get_warehouse_label(warehouses, selected_warehouse),
        selected_warehouse=selected_warehouse,
        schedule_members=schedule_members,
        schedule_groups=schedule_groups,
        board_rows=board_rows,
        live_sections=live_sections,
        live_slots=[{"key": slot_key, "label": slot_label} for slot_key, slot_label in LIVE_SCHEDULE_SLOTS],
        shift_codes=shift_codes,
        active_shift_codes=active_shift_codes,
        employee_rows=employee_rows,
        summary=summary,
        filters=filters,
        schedule_day_options=SCHEDULE_DAY_OPTIONS,
        can_manage_schedule=_can_manage_schedule(),
        scoped_schedule_warehouse=_schedule_scope_warehouse(),
        legend_items=legend_items,
        schedule_color_defaults={
            "bg_color": SCHEDULE_DEFAULT_BG,
            "text_color": SCHEDULE_DEFAULT_TEXT,
        },
        live_schedule_defaults={
            "bg_color": LIVE_SCHEDULE_DEFAULT_BG,
            "text_color": LIVE_SCHEDULE_DEFAULT_TEXT,
        },
        range_end=end_date.isoformat(),
    )


@schedule_bp.route("/swap-request")
def shift_swap_request_page():
    if not _require_schedule_view():
        return redirect("/")

    db = get_db()
    _seed_default_shift_codes(db)

    warehouses = db.execute(
        "SELECT id, name FROM warehouses ORDER BY id"
    ).fetchall()
    selected_warehouse = _get_selected_warehouse(warehouses)
    start_date = _parse_iso_date(request.args.get("start")) or _default_schedule_start()
    days = _clamp_days(request.args.get("days"))
    end_date = start_date + timedelta(days=days - 1)
    shift_swap_request = _build_shift_swap_request_context(db, selected_warehouse)
    filters = {
        "start": start_date.isoformat(),
        "days": days,
        "warehouse": selected_warehouse,
    }

    return render_template(
        "schedule_shift_swap.html",
        warehouses=warehouses,
        selected_warehouse=selected_warehouse,
        selected_warehouse_name=_get_warehouse_label(warehouses, selected_warehouse),
        scoped_schedule_warehouse=_schedule_scope_warehouse(),
        filters=filters,
        range_end=end_date.isoformat(),
        shift_swap_request=shift_swap_request,
    )


@schedule_bp.route("/live/save", methods=["POST"])
def save_live_schedule_entry():
    if not _require_schedule_manage():
        return _schedule_redirect()

    db = get_db()
    scoped_warehouse = _schedule_scope_warehouse()
    warehouse_id = scoped_warehouse or _to_int(request.form.get("live_warehouse_id"))
    legacy_schedule_date = _parse_iso_date(request.form.get("live_schedule_date"))
    schedule_start = _parse_iso_date(request.form.get("live_schedule_start")) or legacy_schedule_date
    schedule_end = _parse_iso_date(request.form.get("live_schedule_end")) or schedule_start
    slot_key = (request.form.get("slot_key") or "").strip()
    employee_id = _to_int(request.form.get("employee_id"))
    channel_label = (request.form.get("channel_label") or "").strip()
    note = (request.form.get("note") or "").strip()
    is_checked = _is_checked_form_value(request.form.get("is_checked"))
    bg_color = _normalize_hex_color(request.form.get("bg_color"), LIVE_SCHEDULE_DEFAULT_BG)
    text_color = _normalize_hex_color(request.form.get("text_color"), LIVE_SCHEDULE_DEFAULT_TEXT)

    if not warehouse_id or not schedule_start or not schedule_end or slot_key not in LIVE_SCHEDULE_SLOT_KEYS:
        flash("Gudang, rentang tanggal, dan slot live wajib diisi.", "error")
        return _schedule_redirect()

    if schedule_end < schedule_start:
        flash("Tanggal selesai live tidak boleh lebih kecil dari tanggal mulai.", "error")
        return _schedule_redirect()

    if (schedule_end - schedule_start).days > (MAX_SCHEDULE_DAY_RANGE - 1):
        flash(f"Rentang jadwal live maksimal {MAX_SCHEDULE_DAY_RANGE} hari per simpan.", "error")
        return _schedule_redirect()

    warehouse = db.execute(
        "SELECT id, name FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    if not warehouse:
        flash("Gudang live tidak ditemukan.", "error")
        return _schedule_redirect()

    employee = None
    if employee_id:
        employee = db.execute(
            """
            SELECT id, full_name, warehouse_id
            FROM employees
            WHERE id=?
            """,
            (employee_id,),
        ).fetchone()
        if not employee:
            flash("Staf live tidak ditemukan.", "error")
            return _schedule_redirect()
        if employee["warehouse_id"] != warehouse_id:
            flash("Staf live harus berasal dari gudang yang sama dengan board live yang dipilih.", "error")
            return _schedule_redirect()

    schedule_dates = [day.isoformat() for day in _daterange(schedule_start, schedule_end)]
    total_days = len(schedule_dates)

    try:
        if employee_id:
            for schedule_date in schedule_dates:
                db.execute(
                    """
                    INSERT INTO schedule_live_entries(
                        warehouse_id,
                        schedule_date,
                        slot_key,
                        employee_id,
                        channel_label,
                        note,
                        bg_color,
                        text_color,
                        is_checked,
                        checked_by,
                        checked_at,
                        updated_by
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(warehouse_id, schedule_date, slot_key) DO UPDATE SET
                        employee_id=excluded.employee_id,
                        channel_label=excluded.channel_label,
                        note=excluded.note,
                        bg_color=excluded.bg_color,
                        text_color=excluded.text_color,
                        is_checked=excluded.is_checked,
                        checked_by=excluded.checked_by,
                        checked_at=excluded.checked_at,
                        updated_by=excluded.updated_by,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        warehouse_id,
                        schedule_date,
                        slot_key,
                        employee_id,
                        channel_label or None,
                        note or None,
                        bg_color,
                        text_color,
                        is_checked,
                        session.get("user_id") if is_checked else None,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S") if is_checked else None,
                        session.get("user_id"),
                    ),
                )
            if total_days == 1:
                flash("Jadwal live berhasil disimpan.", "success")
            else:
                flash(f"Jadwal live berhasil disimpan untuk {total_days} hari.", "success")
        else:
            for schedule_date in schedule_dates:
                db.execute(
                    """
                    DELETE FROM schedule_live_entries
                    WHERE warehouse_id=?
                      AND schedule_date=?
                      AND slot_key=?
                    """,
                    (warehouse_id, schedule_date, slot_key),
                )
            if total_days == 1:
                flash("Slot jadwal live berhasil dibersihkan.", "success")
            else:
                flash(f"Slot jadwal live berhasil dibersihkan untuk {total_days} hari.", "success")
        db.commit()
    except Exception:
        db.rollback()
        flash("Jadwal live gagal disimpan.", "error")
        return _schedule_redirect()

    try:
        slot_label = dict(LIVE_SCHEDULE_SLOTS).get(slot_key, slot_key)
        date_label = format_date_range(schedule_start.isoformat(), schedule_end.isoformat())
        if employee:
            employee_name = (employee["full_name"] or "Staf").strip()
            detail_label = channel_label or "Live Session"
            live_message = (
                f"Jadwal live {employee_name} untuk {date_label} slot {slot_label} di {warehouse['name']} "
                f"diatur ke {detail_label}."
            )
            if note:
                live_message += f" Catatan: {note}"
            event_title = f"Live {slot_label} - {employee_name}"
            event_kind = "live_schedule_update"
        else:
            live_message = f"Jadwal live untuk {date_label} slot {slot_label} di {warehouse['name']} dibersihkan."
            event_title = f"Live {slot_label} Dibersihkan"
            event_kind = "live_schedule_clear"

        event_id = create_schedule_change_event(
            db,
            warehouse_id=warehouse_id,
            event_kind=event_kind,
            title=event_title,
            message=live_message,
            affected_employee_id=employee["id"] if employee else None,
            affected_employee_name=(employee["full_name"] if employee else None),
            start_date=schedule_start.isoformat(),
            end_date=schedule_end.isoformat(),
            created_by=session.get("user_id"),
        )
        db.commit()
        payload = build_schedule_change_notification_payload(
            {"id": event_id, "title": event_title, "message": live_message}
        )
        notify_broadcast(
            payload["subject"],
            payload["message"],
            warehouse_id=warehouse_id,
            push_title=payload["push_title"],
            push_body=payload["push_body"],
            push_url="/announcements/",
            push_tag=payload["push_tag"],
            category="schedule",
            link_url="/announcements/",
            source_type="schedule_change",
            source_id=str(event_id),
        )
    except Exception as exc:
        print("LIVE SCHEDULE BROADCAST ERROR:", exc)

    return _schedule_redirect()


@schedule_bp.route("/live/check", methods=["POST"])
def update_live_schedule_check_status():
    if not _require_schedule_manage():
        return _schedule_redirect()

    db = get_db()
    scoped_warehouse = _schedule_scope_warehouse()
    batch_updates = _parse_live_check_updates_json(request.form.get("changes_json"))

    if batch_updates:
        if scoped_warehouse:
            batch_updates = [item for item in batch_updates if item["warehouse_id"] == scoped_warehouse]
        if not batch_updates:
            flash("Belum ada perubahan checklist live yang valid untuk disimpan.", "error")
            return _schedule_redirect()

        updated_count = 0
        current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            for item in batch_updates:
                live_entry = db.execute(
                    """
                    SELECT id, employee_id
                    FROM schedule_live_entries
                    WHERE warehouse_id=?
                      AND schedule_date=?
                      AND slot_key=?
                    LIMIT 1
                    """,
                    (item["warehouse_id"], item["schedule_date"].isoformat(), item["slot_key"]),
                ).fetchone()
                if not live_entry or not live_entry["employee_id"]:
                    continue

                is_checked = item["is_checked"]
                db.execute(
                    """
                    UPDATE schedule_live_entries
                    SET is_checked=?,
                        checked_by=?,
                        checked_at=?,
                        updated_by=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        is_checked,
                        session.get("user_id") if is_checked else None,
                        current_timestamp if is_checked else None,
                        session.get("user_id"),
                        live_entry["id"],
                    ),
                )
                updated_count += 1
            db.commit()
        except Exception:
            db.rollback()
            flash("Checklist jadwal live gagal disimpan.", "error")
            return _schedule_redirect()

        if not updated_count:
            flash("Belum ada checklist live yang bisa diperbarui.", "error")
            return _schedule_redirect()

        flash(
            "Checklist jadwal live berhasil disimpan."
            if updated_count == 1
            else f"{updated_count} checklist jadwal live berhasil disimpan.",
            "success",
        )
        return _schedule_redirect()

    warehouse_id = scoped_warehouse or _to_int(request.form.get("live_warehouse_id"))
    schedule_date = _parse_iso_date(request.form.get("live_schedule_date"))
    slot_key = (request.form.get("slot_key") or "").strip()
    is_checked = _is_checked_form_value(request.form.get("is_checked"))

    if not warehouse_id or not schedule_date or slot_key not in LIVE_SCHEDULE_SLOT_KEYS:
        flash("Slot live yang dipilih belum valid untuk di-check.", "error")
        return _schedule_redirect()

    live_entry = db.execute(
        """
        SELECT id, employee_id
        FROM schedule_live_entries
        WHERE warehouse_id=?
          AND schedule_date=?
          AND slot_key=?
        LIMIT 1
        """,
        (warehouse_id, schedule_date.isoformat(), slot_key),
    ).fetchone()
    if not live_entry or not live_entry["employee_id"]:
        flash("Checklist live hanya bisa diubah pada slot yang sudah terisi staf.", "error")
        return _schedule_redirect()

    try:
        db.execute(
            """
            UPDATE schedule_live_entries
            SET is_checked=?,
                checked_by=?,
                checked_at=?,
                updated_by=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                is_checked,
                session.get("user_id") if is_checked else None,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S") if is_checked else None,
                session.get("user_id"),
                live_entry["id"],
            ),
        )
        db.commit()
    except Exception:
        db.rollback()
        flash("Checklist jadwal live gagal diperbarui.", "error")
        return _schedule_redirect()

    flash(
        "Checklist jadwal live ditandai." if is_checked else "Checklist jadwal live dibatalkan.",
        "success",
    )
    return _schedule_redirect()


@schedule_bp.route("/shift-code/save", methods=["POST"])
def save_shift_code():
    if not _require_schedule_manage():
        return _schedule_redirect()

    db = get_db()

    original_code = (request.form.get("original_code") or "").strip().upper()
    code = (request.form.get("code") or "").strip().upper()
    label = (request.form.get("label") or "").strip() or code
    bg_color = _normalize_hex_color(request.form.get("bg_color"), SCHEDULE_DEFAULT_BG)
    text_color = _normalize_hex_color(request.form.get("text_color"), SCHEDULE_DEFAULT_TEXT)
    sort_order = _to_int(request.form.get("sort_order"), 0)
    is_active = 1 if request.form.get("is_active") == "on" else 0

    if not code:
        flash("Kode shift wajib diisi.", "error")
        return _schedule_redirect()

    try:
        if original_code and original_code != code:
            existing_target = db.execute(
                "SELECT code FROM schedule_shift_codes WHERE code=?",
                (code,),
            ).fetchone()
            if existing_target:
                flash("Kode shift tujuan sudah dipakai.", "error")
                return _schedule_redirect()

            existing_original = db.execute(
                "SELECT code FROM schedule_shift_codes WHERE code=?",
                (original_code,),
            ).fetchone()
            if existing_original:
                db.execute(
                    """
                    INSERT INTO schedule_shift_codes(code, label, bg_color, text_color, sort_order, is_active)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (code, label, bg_color, text_color, sort_order, is_active),
                )
                db.execute(
                    "UPDATE schedule_entries SET shift_code=? WHERE shift_code=?",
                    (code, original_code),
                )
                db.execute(
                    "DELETE FROM schedule_shift_codes WHERE code=?",
                    (original_code,),
                )
            else:
                db.execute(
                    """
                    INSERT INTO schedule_shift_codes(code, label, bg_color, text_color, sort_order, is_active)
                    VALUES (?,?,?,?,?,?)
                    """,
                    (code, label, bg_color, text_color, sort_order, is_active),
                )
        else:
            db.execute(
                """
                INSERT INTO schedule_shift_codes(code, label, bg_color, text_color, sort_order, is_active)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(code) DO UPDATE SET
                    label=excluded.label,
                    bg_color=excluded.bg_color,
                    text_color=excluded.text_color,
                    sort_order=excluded.sort_order,
                    is_active=excluded.is_active
                """,
                (code, label, bg_color, text_color, sort_order, is_active),
            )
        db.commit()
        flash("Master shift berhasil disimpan.", "success")
    except Exception:
        db.rollback()
        flash("Master shift gagal disimpan.", "error")

    return _schedule_redirect()


@schedule_bp.route("/entry/save", methods=["POST"])
def save_schedule_entry():
    if not _require_schedule_manage():
        return _schedule_redirect()

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    shift_code = (request.form.get("shift_code") or "").strip().upper()
    note = (request.form.get("note") or "").strip()
    start_date = _parse_iso_date(request.form.get("entry_start_date"))
    end_date = _parse_iso_date(request.form.get("entry_end_date"))

    if not employee_id or not start_date or not end_date:
        flash("Karyawan dan rentang tanggal wajib diisi.", "error")
        return _schedule_redirect()

    if end_date < start_date:
        flash("Tanggal selesai tidak boleh lebih kecil dari tanggal mulai.", "error")
        return _schedule_redirect()

    if (end_date - start_date).days > (MAX_SCHEDULE_DAY_RANGE - 1):
        flash(f"Rentang jadwal maksimal {MAX_SCHEDULE_DAY_RANGE} hari per simpan.", "error")
        return _schedule_redirect()

    employee = db.execute(
        "SELECT id, full_name, warehouse_id FROM employees WHERE id=?",
        (employee_id,),
    ).fetchone()
    if not employee:
        flash("Karyawan tidak ditemukan.", "error")
        return _schedule_redirect()

    shift_meta = None
    if shift_code:
        shift_meta = db.execute(
            "SELECT code, label FROM schedule_shift_codes WHERE code=?",
            (shift_code,),
        ).fetchone()
        if not shift_meta:
            flash("Kode shift tidak ditemukan.", "error")
            return _schedule_redirect()

    employee_name = (employee["full_name"] or "Karyawan").strip()
    date_range_label = format_date_range(start_date.isoformat(), end_date.isoformat())
    if shift_code:
        shift_label = (shift_meta["label"] or shift_code).strip()
        summary_title = f"{employee_name} - {shift_label}"
        summary_note = f"Shift {shift_label} ({shift_code}) untuk {date_range_label}"
        if note:
            summary_note += f" | {note}"
    else:
        summary_title = f"{employee_name} - Jadwal Dibersihkan"
        summary_note = f"Membersihkan jadwal manual untuk {date_range_label}"
        if note:
            summary_note += f" | {note}"

    payload = {
        "employee_id": employee_id,
        "employee_name": employee_name,
        "warehouse_id": employee["warehouse_id"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "shift_code": shift_code,
        "shift_label": (shift_meta["label"] if shift_meta else ""),
        "note": note,
        "date_range_label": date_range_label,
    }

    if can_manage_attendance_request_approvals(session.get("role")):
        try:
            if shift_code:
                for current_day in _daterange(start_date, end_date):
                    db.execute(
                        """
                        INSERT INTO schedule_entries(
                            employee_id,
                            schedule_date,
                            shift_code,
                            note,
                            updated_by
                        )
                        VALUES (?,?,?,?,?)
                        ON CONFLICT(employee_id, schedule_date) DO UPDATE SET
                            shift_code=excluded.shift_code,
                            note=excluded.note,
                            updated_by=excluded.updated_by,
                            updated_at=CURRENT_TIMESTAMP
                        """,
                        (
                            employee_id,
                            current_day.isoformat(),
                            shift_code,
                            note or None,
                            session.get("user_id"),
                        ),
                    )
            else:
                db.execute(
                    """
                    DELETE FROM schedule_entries
                    WHERE employee_id=?
                      AND schedule_date BETWEEN ? AND ?
                    """,
                    (employee_id, start_date.isoformat(), end_date.isoformat()),
                )

            if shift_code:
                shift_label = (shift_meta["label"] or shift_code).strip()
                schedule_message = f"Jadwal {employee_name} untuk {date_range_label} diubah ke shift {shift_label} ({shift_code})."
                if note:
                    schedule_message += f" Catatan: {note}"
                event_title = f"Perubahan Jadwal {employee_name}"
                event_kind = "entry_update"
            else:
                schedule_message = f"Jadwal manual {employee_name} pada {date_range_label} dibersihkan."
                if note:
                    schedule_message += f" Catatan: {note}"
                event_title = f"Jadwal Manual {employee_name} Dibersihkan"
                event_kind = "entry_clear"

            event_id = create_schedule_change_event(
                db,
                warehouse_id=employee["warehouse_id"],
                event_kind=event_kind,
                title=event_title,
                message=schedule_message,
                affected_employee_id=employee_id,
                affected_employee_name=employee_name,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                created_by=session.get("user_id"),
            )
            db.commit()
        except Exception:
            db.rollback()
            flash("Jadwal manual gagal disimpan.", "error")
            return _schedule_redirect()

        try:
            notification_payload = build_schedule_change_notification_payload(
                {
                    "id": event_id,
                    "title": event_title,
                    "message": schedule_message,
                }
            )
            notify_broadcast(
                notification_payload["subject"],
                notification_payload["message"],
                warehouse_id=employee["warehouse_id"],
                push_title=notification_payload["push_title"],
                push_body=notification_payload["push_body"],
                push_url="/announcements/",
                push_tag=notification_payload["push_tag"],
                category="schedule",
            )
        except Exception:
            pass

        if shift_code:
            flash("Jadwal manual berhasil diterapkan.", "success")
        else:
            flash("Jadwal manual pada rentang tersebut berhasil dibersihkan.", "success")
        return _schedule_redirect()

    try:
        queue_result = queue_attendance_request(
            db,
            request_type="schedule_entry",
            warehouse_id=employee["warehouse_id"],
            employee_id=employee_id,
            requested_by=session.get("user_id"),
            summary_title=summary_title,
            summary_note=summary_note,
            payload=payload,
        )
        db.commit()
    except Exception:
        db.rollback()
        flash("Permintaan perubahan jadwal gagal dikirim ke approval.", "error")
        return _schedule_redirect()

    if queue_result.get("existing"):
        flash("Perubahan shift dengan detail yang sama masih menunggu approval HR / Super Admin.", "info")
    else:
        flash("Permintaan perubahan shift berhasil dikirim ke approval HR / Super Admin.", "success")

    return _schedule_redirect()


@schedule_bp.route("/swap-request/save", methods=["POST"])
def save_shift_swap_request():
    if not _require_schedule_view():
        return _shift_swap_redirect()

    db = get_db()
    linked_employee = _get_schedule_linked_employee(db)
    if not linked_employee:
        flash("Akun Anda belum ditautkan ke data karyawan, jadi belum bisa mengajukan tuker shift.", "error")
        return _shift_swap_redirect()

    linked_employee = dict(linked_employee)
    linked_employee_id = _to_int(linked_employee.get("employee_id"))
    linked_warehouse_id = _to_int(linked_employee.get("warehouse_id"))
    if not linked_employee_id or not linked_warehouse_id:
        flash("Homebase atau data karyawan akun Anda belum lengkap untuk pengajuan tuker shift.", "error")
        return _shift_swap_redirect()

    selected_warehouse = _to_int(request.form.get("warehouse"))
    if selected_warehouse and selected_warehouse != linked_warehouse_id:
        flash("Pengajuan tuker shift hanya bisa dibuat saat board diarahkan ke homebase Anda.", "error")
        return _shift_swap_redirect()

    swap_date = _parse_iso_date(request.form.get("swap_date"))
    partner_employee_id = _to_int(request.form.get("swap_with_employee_id"))
    reason = (request.form.get("reason") or "").strip()

    if not swap_date or not partner_employee_id or not reason:
        flash("Tanggal, partner tuker shift, dan alasan wajib diisi.", "error")
        return _shift_swap_redirect()

    if partner_employee_id == linked_employee_id:
        flash("Partner tuker shift harus staf lain.", "error")
        return _shift_swap_redirect()

    partner_options = {
        option["employee_id"]: option
        for option in _build_shift_swap_partner_options(db, linked_employee)
    }
    partner_option = partner_options.get(partner_employee_id)
    if not partner_option:
        flash("Partner tuker shift tidak valid untuk homebase Anda.", "error")
        return _shift_swap_redirect()

    requester_name = str(linked_employee.get("full_name") or linked_employee.get("display_name") or "Staf").strip()
    partner_name = str(partner_option.get("full_name") or partner_option.get("display_name") or "Staf").strip()
    requester_snapshot = resolve_employee_schedule_for_date(db, linked_employee_id, swap_date)
    partner_snapshot = resolve_employee_schedule_for_date(db, partner_employee_id, swap_date)

    try:
        requester_shift_code = _validate_shift_swap_schedule(requester_snapshot, requester_name)
        partner_shift_code = _validate_shift_swap_schedule(partner_snapshot, partner_name)
    except ValueError as exc:
        flash(str(exc), "error")
        return _shift_swap_redirect()

    if requester_shift_code == partner_shift_code:
        flash("Shift Anda dan partner pada tanggal tersebut masih sama, jadi tidak ada yang perlu ditukar.", "error")
        return _shift_swap_redirect()

    requester_shift_label = str(requester_snapshot.get("label") or requester_shift_code).strip()
    partner_shift_label = str(partner_snapshot.get("label") or partner_shift_code).strip()
    schedule_date_label = (
        requester_snapshot.get("full_label")
        or partner_snapshot.get("full_label")
        or swap_date.isoformat()
    )
    payload = {
        "employee_id": linked_employee_id,
        "employee_name": requester_name,
        "warehouse_id": linked_warehouse_id,
        "schedule_date": swap_date.isoformat(),
        "schedule_date_label": schedule_date_label,
        "swap_with_employee_id": partner_employee_id,
        "swap_with_employee_name": partner_name,
        "requester_current_shift_code": requester_shift_code,
        "requester_current_shift_label": requester_shift_label,
        "requester_current_note": str(requester_snapshot.get("note") or "").strip(),
        "partner_current_shift_code": partner_shift_code,
        "partner_current_shift_label": partner_shift_label,
        "partner_current_note": str(partner_snapshot.get("note") or "").strip(),
        "reason": reason,
    }
    summary_title = f"Tukar Shift {requester_name} x {partner_name}"
    summary_note = (
        f"{schedule_date_label} | "
        f"{requester_name}: {requester_shift_label} ({requester_shift_code}) "
        f"<-> {partner_name}: {partner_shift_label} ({partner_shift_code})"
    )
    if reason:
        summary_note += f" | {reason}"

    try:
        queue_result = queue_attendance_request(
            db,
            request_type="shift_swap",
            warehouse_id=linked_warehouse_id,
            employee_id=linked_employee_id,
            requested_by=session.get("user_id"),
            summary_title=summary_title,
            summary_note=summary_note,
            payload=payload,
        )
        db.commit()
    except Exception:
        db.rollback()
        flash("Pengajuan tuker shift gagal dikirim ke approval.", "error")
        return _shift_swap_redirect()

    if queue_result.get("existing"):
        flash("Pengajuan tuker shift dengan detail yang sama masih menunggu approval HR / Super Admin.", "info")
    else:
        flash("Pengajuan tuker shift berhasil dikirim ke approval HR / Super Admin.", "success")
    return _shift_swap_redirect()


@schedule_bp.route("/day-note/save", methods=["POST"])
def save_day_note():
    if not _require_schedule_manage():
        return _schedule_redirect()

    db = get_db()
    schedule_date = _parse_iso_date(request.form.get("schedule_date"))
    note = (request.form.get("note") or "").strip()

    if not schedule_date:
        flash("Tanggal catatan wajib diisi.", "error")
        return _schedule_redirect()

    try:
        if note:
            db.execute(
                """
                INSERT INTO schedule_day_notes(schedule_date, note, updated_by)
                VALUES (?,?,?)
                ON CONFLICT(schedule_date) DO UPDATE SET
                    note=excluded.note,
                    updated_by=excluded.updated_by,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (schedule_date.isoformat(), note, session.get("user_id")),
            )
            flash("Catatan harian berhasil disimpan.", "success")
        else:
            db.execute(
                "DELETE FROM schedule_day_notes WHERE schedule_date=?",
                (schedule_date.isoformat(),),
            )
            flash("Catatan harian berhasil dibersihkan.", "success")
        db.commit()
    except Exception:
        db.rollback()
        flash("Catatan harian gagal disimpan.", "error")
        return _schedule_redirect()

    try:
        selected_warehouse = _to_int(request.form.get("warehouse")) or _schedule_scope_warehouse()
        date_label = format_date_range(schedule_date.isoformat())
        if note:
            note_message = f"Catatan jadwal untuk {date_label} diperbarui. Isi: {note}"
            event_title = f"Catatan Jadwal {date_label}"
        else:
            note_message = f"Catatan jadwal untuk {date_label} dibersihkan."
            event_title = f"Catatan Jadwal {date_label} Dibersihkan"
        event_id = create_schedule_change_event(
            db,
            warehouse_id=selected_warehouse,
            event_kind="day_note",
            title=event_title,
            message=note_message,
            start_date=schedule_date.isoformat(),
            end_date=schedule_date.isoformat(),
            created_by=session.get("user_id"),
        )
        db.commit()
        payload = build_schedule_change_notification_payload(
            {"id": event_id, "title": event_title, "message": note_message}
        )
        notify_broadcast(
            payload["subject"],
            payload["message"],
            warehouse_id=selected_warehouse,
            push_title=payload["push_title"],
            push_body=payload["push_body"],
            push_url="/announcements/",
            push_tag=payload["push_tag"],
            category="schedule",
            link_url="/announcements/",
            source_type="schedule_change",
            source_id=str(event_id),
        )
    except Exception as exc:
        print("SCHEDULE DAY NOTE BROADCAST ERROR:", exc)

    return _schedule_redirect()


@schedule_bp.route("/profile/save/<int:employee_id>", methods=["POST"])
def save_schedule_profile(employee_id):
    if not _require_schedule_manage():
        return _schedule_redirect()

    db = get_db()
    employee = db.execute(
        "SELECT id FROM employees WHERE id=?",
        (employee_id,),
    ).fetchone()
    if not employee:
        flash("Karyawan tidak ditemukan.", "error")
        return _schedule_redirect()

    custom_name = (request.form.get("custom_name") or "").strip()
    display_group = (request.form.get("display_group") or "").strip()
    location_label = (request.form.get("location_label") or "").strip()
    display_order = _to_int(request.form.get("display_order"), 0)
    include_in_schedule = 1 if request.form.get("include_in_schedule") == "on" else 0
    note = (request.form.get("profile_note") or "").strip()

    try:
        if not any([custom_name, display_group, location_label, display_order, note]) and include_in_schedule == 1:
            db.execute(
                "DELETE FROM schedule_employee_profiles WHERE employee_id=?",
                (employee_id,),
            )
        else:
            db.execute(
                """
                INSERT INTO schedule_employee_profiles(
                    employee_id,
                    custom_name,
                    display_group,
                    location_label,
                    display_order,
                    include_in_schedule,
                    note
                )
                VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(employee_id) DO UPDATE SET
                    custom_name=excluded.custom_name,
                    display_group=excluded.display_group,
                    location_label=excluded.location_label,
                    display_order=excluded.display_order,
                    include_in_schedule=excluded.include_in_schedule,
                    note=excluded.note
                """,
                (
                    employee_id,
                    custom_name or None,
                    display_group or None,
                    location_label or None,
                    display_order,
                    include_in_schedule,
                    note or None,
                ),
            )
        db.commit()
        flash("Preferensi tampilan staf berhasil disimpan.", "success")
    except Exception:
        db.rollback()
        flash("Preferensi tampilan staf gagal disimpan.", "error")

    return _schedule_redirect()
