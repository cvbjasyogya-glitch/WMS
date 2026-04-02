from datetime import date as date_cls, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session

from database import get_db
from services.announcement_center import (
    build_schedule_change_notification_payload,
    create_schedule_change_event,
    format_date_range,
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

LEAVE_OVERRIDE_STYLES = {
    "annual": ("CUTI", "Cuti Tahunan", "#f8d77f", "#5c3b00"),
    "sick": ("SAKIT", "Cuti Sakit", "#f3a58f", "#6d2117"),
    "permit": ("IZIN", "Izin", "#b7d6ff", "#17355a"),
    "unpaid": ("UNPAID", "Cuti Unpaid", "#e2d2ff", "#4a2d75"),
    "special": ("SPECIAL", "Cuti Khusus", "#c9f0d2", "#164029"),
}

ATTENDANCE_OVERRIDE_STYLES = {
    "leave": ("LEAVE", "Leave", "#f8d77f", "#5c3b00"),
    "absent": ("ABSEN", "Tidak Hadir", "#f28a8a", "#6e1717"),
    "half_day": ("HALF", "Half Day", "#bde3f7", "#114764"),
}

EMPLOYMENT_OVERRIDE_STYLES = {
    "leave": ("OFF", "Status Leave", "#f4a98f", "#6b2216"),
    "inactive": ("NA", "Tidak Aktif", "#d7dee8", "#33465b"),
}

OFFBOARDING_STYLE = ("OFFBD", "Offboarding", "#f49797", "#6d1616")
SCHEDULE_DAY_OPTIONS = (7, 14, 30, 60, 90)
MAX_SCHEDULE_DAY_RANGE = max(SCHEDULE_DAY_OPTIONS)


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
    day_names = [
        "Senin",
        "Selasa",
        "Rabu",
        "Kamis",
        "Jumat",
        "Sabtu",
        "Minggu",
    ]
    month_names = [
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
    ]
    return f"{day_names[value.weekday()]}, {value.day:02d} {month_names[value.month - 1]} {value.year}"


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
        entry_map[(row["employee_id"], row["schedule_date"])] = {
            "code": code,
            "label": label,
            "note": note,
            "bg_color": shift_meta.get("bg_color") or "#d9e4ef",
            "text_color": shift_meta.get("text_color") or "#25384c",
            "source": "manual",
            "title": title,
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
        "bg_color": payload["bg_color"],
        "text_color": payload["text_color"],
        "source": payload["source"],
        "title": payload["title"],
        "priority": priority,
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
        extra_note = (row["reason"] or "").strip() or (row["note"] or "").strip()
        title = label
        if extra_note:
            title = f"{title} - {extra_note}"

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
                    "note": extra_note,
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
        style = ATTENDANCE_OVERRIDE_STYLES.get((row["status"] or "").strip().lower())
        if not style:
            continue
        note = (row["note"] or "").strip()
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
    for current_day in _daterange(start_date, end_date):
        iso_date = current_day.isoformat()
        cells = []
        for member in schedule_members:
            cell = override_map.get((member["employee_id"], iso_date)) or entry_map.get(
                (member["employee_id"], iso_date)
            )
            cells.append(cell)

        board_rows.append(
            {
                "iso_date": iso_date,
                "label": _format_schedule_day(current_day),
                "day_short": short_day_names[current_day.weekday()],
                "day_number": f"{current_day.day:02d}",
                "month_number": f"{current_day.month:02d}",
                "is_weekend": current_day.weekday() >= 5,
                "cells": cells,
                "note": day_notes.get(iso_date, ""),
            }
        )
    return board_rows


def _build_live_schedule_sections(db, warehouses, selected_warehouse, start_date, end_date):
    if selected_warehouse:
        target_warehouses = [warehouse for warehouse in warehouses if warehouse["id"] == selected_warehouse]
    else:
        target_warehouses = list(warehouses)

    sections = []
    for warehouse in target_warehouses:
        rows = db.execute(
            """
            SELECT
                l.schedule_date,
                l.slot_key,
                l.channel_label,
                l.note,
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
            entry_map[(row["schedule_date"], row["slot_key"])] = {
                "employee_id": row["employee_id"],
                "display_name": _resolve_schedule_display_name(
                    row["full_name"],
                    row["custom_name"],
                    row["employee_code"],
                ),
                "channel_label": (row["channel_label"] or "").strip(),
                "note": (row["note"] or "").strip(),
                "location_label_display": _resolve_schedule_location_label(
                    row["location_label"],
                    row["warehouse_name"],
                    row["work_location"],
                ),
            }
            total_assignments += 1

        section_rows = []
        for current_day in _daterange(start_date, end_date):
            iso_date = current_day.isoformat()
            section_rows.append(
                {
                    "iso_date": iso_date,
                    "label": _format_schedule_day(current_day),
                    "is_weekend": current_day.weekday() >= 5,
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
        {"code": "CUTI", "label": "Approved leave dari HRIS", "bg_color": "#f8d77f", "text_color": "#5c3b00"},
        {"code": "SAKIT", "label": "Cuti sakit otomatis", "bg_color": "#f3a58f", "text_color": "#6d2117"},
        {"code": "OFFBD", "label": "Offboarding aktif", "bg_color": "#f49797", "text_color": "#6d1616"},
        {"code": "ABSEN", "label": "Absensi tidak hadir", "bg_color": "#f28a8a", "text_color": "#6e1717"},
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
        range_end=end_date.isoformat(),
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
                        updated_by
                    )
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(warehouse_id, schedule_date, slot_key) DO UPDATE SET
                        employee_id=excluded.employee_id,
                        channel_label=excluded.channel_label,
                        note=excluded.note,
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


@schedule_bp.route("/shift-code/save", methods=["POST"])
def save_shift_code():
    if not _require_schedule_manage():
        return _schedule_redirect()

    db = get_db()

    original_code = (request.form.get("original_code") or "").strip().upper()
    code = (request.form.get("code") or "").strip().upper()
    label = (request.form.get("label") or "").strip() or code
    bg_color = _normalize_hex_color(request.form.get("bg_color"), "#C6E5AB")
    text_color = _normalize_hex_color(request.form.get("text_color"), "#17351A")
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
            flash("Jadwal manual berhasil diterapkan.", "success")
        else:
            db.execute(
                """
                DELETE FROM schedule_entries
                WHERE employee_id=?
                  AND schedule_date BETWEEN ? AND ?
                """,
                (employee_id, start_date.isoformat(), end_date.isoformat()),
            )
            flash("Jadwal manual pada rentang tersebut berhasil dibersihkan.", "success")

        db.commit()
    except Exception:
        db.rollback()
        flash("Perubahan jadwal gagal disimpan.", "error")
        return _schedule_redirect()

    try:
        date_range_label = format_date_range(start_date.isoformat(), end_date.isoformat())
        employee_name = (employee["full_name"] or "Karyawan").strip()
        if shift_code:
            shift_label = (shift_meta["label"] or shift_code).strip()
            schedule_message = f"Jadwal {employee_name} untuk {date_range_label} diubah ke shift {shift_label} ({shift_code})."
            if note:
                schedule_message += f" Catatan: {note}"
            event_id = create_schedule_change_event(
                db,
                warehouse_id=employee["warehouse_id"],
                event_kind="entry_update",
                title=f"{employee_name} - {shift_label}",
                message=schedule_message,
                affected_employee_id=employee_id,
                affected_employee_name=employee_name,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                created_by=session.get("user_id"),
            )
        else:
            schedule_message = f"Jadwal manual {employee_name} untuk {date_range_label} dibersihkan."
            event_id = create_schedule_change_event(
                db,
                warehouse_id=employee["warehouse_id"],
                event_kind="entry_clear",
                title=f"{employee_name} - Jadwal Dibersihkan",
                message=schedule_message,
                affected_employee_id=employee_id,
                affected_employee_name=employee_name,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                created_by=session.get("user_id"),
            )
        db.commit()
        payload = build_schedule_change_notification_payload(
            {"id": event_id, "title": schedule_message.split(".")[0], "message": schedule_message}
        )
        notify_broadcast(
            payload["subject"],
            payload["message"],
            warehouse_id=employee["warehouse_id"],
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
        print("SCHEDULE CHANGE BROADCAST ERROR:", exc)

    return _schedule_redirect()


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
