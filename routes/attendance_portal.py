from datetime import date as date_cls, datetime

from flask import Blueprint, flash, redirect, render_template, request, session

from database import get_db
from routes.hris import (
    _current_timestamp,
    _get_self_service_employee,
    _insert_biometric_log_record,
    _normalize_accuracy,
    _normalize_datetime_input,
    _normalize_latitude,
    _normalize_longitude,
    _save_biometric_photo_data,
)


attendance_portal_bp = Blueprint("attendance_portal", __name__, url_prefix="/absen")


ATTENDANCE_PORTAL_PUNCH_LABELS = {
    "check_in": "Check In",
    "break_start": "Break Start",
    "break_finish": "Break Finish",
    "check_out": "Check Out",
    "complete": "Sudah Lengkap",
}

ATTENDANCE_SHIFT_SCHEDULES = {
    "mataram": {
        "pagi": {"label": "Shift Pagi", "start": "08:00", "end": "16:00"},
        "siang": {"label": "Shift Siang", "start": "13:00", "end": "21:00"},
    },
    "mega": {
        "pagi": {"label": "Shift Pagi", "start": "09:00", "end": "17:00"},
        "siang": {"label": "Shift Siang", "start": "13:00", "end": "21:00"},
    },
}


def _resolve_shift_warehouse_key(linked_employee):
    source = dict(linked_employee) if linked_employee is not None and not isinstance(linked_employee, dict) else (linked_employee or {})
    warehouse_name = str(source.get("warehouse_name") or "").strip().lower()
    if "mega" in warehouse_name:
        return "mega"
    return "mataram"


def _normalize_shift_code(value):
    shift_code = (value or "").strip().lower()
    return shift_code if shift_code in {"pagi", "siang"} else None


def _build_shift_label(schedule_item):
    if not schedule_item:
        return "-"
    return f"{schedule_item['label']} | {schedule_item['start'].replace(':', '.')} - {schedule_item['end'].replace(':', '.')}"


def _build_shift_options(linked_employee):
    warehouse_key = _resolve_shift_warehouse_key(linked_employee)
    schedule_map = ATTENDANCE_SHIFT_SCHEDULES.get(warehouse_key, ATTENDANCE_SHIFT_SCHEDULES["mataram"])
    return [
        {
            "value": shift_code,
            "label": _build_shift_label(schedule_item),
            "time_label": f"{schedule_item['start'].replace(':', '.')} - {schedule_item['end'].replace(':', '.')}",
            "start": schedule_item["start"],
            "end": schedule_item["end"],
        }
        for shift_code, schedule_item in schedule_map.items()
    ]


def _resolve_default_shift_code(linked_employee, requested_time=None):
    if requested_time and len(requested_time) >= 16:
        hour_value = int(requested_time[11:13])
    else:
        hour_value = datetime.now().hour
    return "siang" if hour_value >= 13 else "pagi"


def _has_open_break(day_logs):
    break_open = False
    for log in day_logs:
        punch_type = log["punch_type"]
        if punch_type == "break_start":
            break_open = True
        elif punch_type == "break_finish":
            break_open = False
    return break_open


def _build_attendance_punch_options(attendance_today, day_logs):
    has_check_in = bool(attendance_today and attendance_today["check_in"]) or any(
        log["punch_type"] == "check_in" for log in day_logs
    )
    has_check_out = bool(attendance_today and attendance_today["check_out"]) or any(
        log["punch_type"] == "check_out" for log in day_logs
    )
    break_open = _has_open_break(day_logs)

    if not has_check_in:
        return ["check_in"]
    if has_check_out:
        return []

    options = []
    options.append("check_out")
    if break_open:
        options.append("break_finish")
    else:
        options.append("break_start")
    return options


def _resolve_attendance_punch_mode(attendance_today, day_logs):
    has_check_in = bool(attendance_today and attendance_today["check_in"]) or any(
        log["punch_type"] == "check_in" for log in day_logs
    )
    has_check_out = bool(attendance_today and attendance_today["check_out"]) or any(
        log["punch_type"] == "check_out" for log in day_logs
    )
    if not has_check_in:
        return "check_in"
    if has_check_out:
        return "complete"
    if _has_open_break(day_logs):
        return "break_finish"
    return "check_out"


def _get_attendance_punch_label(mode):
    return ATTENDANCE_PORTAL_PUNCH_LABELS.get(mode, "Check In")


def _resolve_selected_shift(attendance_today, day_logs):
    if attendance_today and attendance_today.get("shift_code"):
        return {
            "shift_code": attendance_today.get("shift_code"),
            "shift_label": attendance_today.get("shift_label"),
        }

    for log in day_logs:
        shift_code = _normalize_shift_code(log.get("shift_code"))
        shift_label = (log.get("shift_label") or "").strip()
        if shift_code or shift_label:
            return {
                "shift_code": shift_code,
                "shift_label": shift_label or None,
            }

    return {"shift_code": None, "shift_label": None}


def _fetch_attendance_portal_state(db):
    linked_employee = _get_self_service_employee(db)
    if linked_employee:
        linked_employee = dict(linked_employee)
    today_date = date_cls.today().isoformat()
    attendance_today = None
    day_logs = []

    if linked_employee:
        attendance_today = db.execute(
            """
            SELECT attendance_date, check_in, check_out, status, shift_code, shift_label, note
            FROM attendance_records
            WHERE employee_id=? AND attendance_date=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (linked_employee["id"], today_date),
        ).fetchone()
        if attendance_today:
            attendance_today = dict(attendance_today)
        day_logs = [
            dict(row)
            for row in db.execute(
                """
                SELECT punch_type, punch_time, shift_code, shift_label
                FROM biometric_logs
                WHERE employee_id=? AND substr(punch_time, 1, 10)=?
                ORDER BY punch_time ASC, id ASC
                """,
                (linked_employee["id"], today_date),
            ).fetchall()
        ]

    punch_mode = _resolve_attendance_punch_mode(attendance_today, day_logs)
    punch_options = _build_attendance_punch_options(attendance_today, day_logs)
    shift_options = _build_shift_options(linked_employee) if linked_employee else []
    selected_shift = _resolve_selected_shift(attendance_today, day_logs)
    selected_shift_code = _normalize_shift_code(selected_shift.get("shift_code"))
    if not selected_shift_code and linked_employee:
        selected_shift_code = _resolve_default_shift_code(linked_employee)
    selected_shift_option = next(
        (option for option in shift_options if option["value"] == selected_shift_code),
        shift_options[0] if shift_options else None,
    )

    return {
        "linked_employee": linked_employee,
        "attendance_today": attendance_today,
        "today_date": today_date,
        "punch_mode": punch_mode,
        "punch_options": punch_options,
        "shift_options": shift_options,
        "selected_shift_code": selected_shift_option["value"] if selected_shift_option else None,
        "selected_shift_label": selected_shift_option["label"] if selected_shift_option else "-",
        "selected_shift_time_label": selected_shift_option["time_label"] if selected_shift_option else "-",
        "shift_locked": bool(selected_shift.get("shift_code") or (attendance_today and attendance_today.get("check_in"))),
        "warehouse_shift_key": _resolve_shift_warehouse_key(linked_employee) if linked_employee else "mataram",
    }


@attendance_portal_bp.route("/")
def index():
    db = get_db()
    portal_state = _fetch_attendance_portal_state(db)

    return render_template(
        "attendance_portal.html",
        linked_employee=portal_state["linked_employee"],
        attendance_today=portal_state["attendance_today"],
        today_date=portal_state["today_date"],
        portal_punch_mode=portal_state["punch_mode"],
        portal_punch_label=_get_attendance_punch_label(portal_state["punch_mode"]),
        portal_punch_options=[
            {"value": option, "label": _get_attendance_punch_label(option)}
            for option in portal_state["punch_options"]
        ],
        portal_shift_options=portal_state["shift_options"],
        portal_selected_shift=portal_state["selected_shift_code"],
        portal_selected_shift_label=portal_state["selected_shift_label"],
        portal_selected_shift_time_label=portal_state["selected_shift_time_label"],
        portal_shift_locked=portal_state["shift_locked"],
        portal_warehouse_shift_key=portal_state["warehouse_shift_key"],
    )


@attendance_portal_bp.route("/submit", methods=["POST"])
def submit():
    db = get_db()
    linked_employee = _get_self_service_employee(db)
    if linked_employee is None:
        flash("Akun ini belum ditautkan ke data karyawan. Hubungkan dulu dari halaman Admin.", "error")
        return redirect("/absen/")

    portal_state = _fetch_attendance_portal_state(db)
    attendance_today = portal_state["attendance_today"]
    punch_mode = portal_state["punch_mode"]
    punch_options = portal_state["punch_options"]
    location_label = (request.form.get("location_label") or "").strip()
    latitude = _normalize_latitude(request.form.get("latitude"))
    longitude = _normalize_longitude(request.form.get("longitude"))
    accuracy_m = _normalize_accuracy(request.form.get("accuracy_m"))
    allowed_punch_types = set(punch_options)
    requested_punch_type = (request.form.get("punch_type") or "").strip().lower()
    if requested_punch_type in allowed_punch_types:
        punch_type = requested_punch_type
    elif punch_mode in allowed_punch_types:
        punch_type = punch_mode
    else:
        punch_type = "check_in"
    normalized_punch_time = _normalize_datetime_input(request.form.get("punch_time"))
    if normalized_punch_time:
        punch_time = f"{date_cls.today().isoformat()} {normalized_punch_time[11:19]}"
    else:
        punch_time = _current_timestamp()
    requested_shift_code = _normalize_shift_code(request.form.get("shift_code"))
    if portal_state["shift_locked"] and portal_state["selected_shift_code"]:
        shift_code = portal_state["selected_shift_code"]
    elif requested_shift_code:
        shift_code = requested_shift_code
    else:
        shift_code = _resolve_default_shift_code(linked_employee, normalized_punch_time)
    shift_option = next(
        (option for option in portal_state["shift_options"] if option["value"] == shift_code),
        portal_state["shift_options"][0] if portal_state["shift_options"] else None,
    )
    shift_code = shift_option["value"] if shift_option else None
    shift_label = shift_option["label"] if shift_option else None
    note = (request.form.get("note") or "").strip()
    photo_data_url = request.form.get("photo_data_url")

    if punch_mode == "complete":
        flash("Absensi hari ini sudah lengkap. Jika perlu koreksi, lanjutkan dari HR atau Super Admin.", "error")
        return redirect("/absen/")

    if requested_punch_type and requested_punch_type not in allowed_punch_types:
        flash("Tipe absen tidak sesuai urutan harian. Pilih tipe yang tersedia di form.", "error")
        return redirect("/absen/")

    if not location_label:
        flash("Titik lokasi wajib diisi sebelum absen.", "error")
        return redirect("/absen/")

    if latitude is None or longitude is None:
        flash("Koordinat geotag belum valid. Ambil lokasi dulu sebelum absen.", "error")
        return redirect("/absen/")

    duplicate = db.execute(
        "SELECT id FROM biometric_logs WHERE employee_id=? AND punch_time=? AND punch_type=?",
        (linked_employee["id"], punch_time, punch_type),
    ).fetchone()
    if duplicate:
        flash("Log absen dengan waktu dan tipe yang sama sudah tercatat.", "error")
        return redirect("/absen/")

    photo_path = _save_biometric_photo_data(photo_data_url)
    if not photo_path:
        flash("Foto absen wajib diambil dari kamera sebelum disimpan.", "error")
        return redirect("/absen/")

    note_parts = [note] if note else []
    note_parts.append(f"Attendance portal {punch_type.replace('_', ' ')}")
    if shift_label:
        note_parts.append(f"Shift {shift_label}")
    if attendance_today and attendance_today["attendance_date"]:
        note_parts.append(f"Daily attendance {attendance_today['attendance_date']}")

    _insert_biometric_log_record(
        db,
        employee_id=linked_employee["id"],
        warehouse_id=linked_employee["warehouse_id"],
        device_name="Attendance Photo Portal",
        device_user_id=session.get("username"),
        punch_time=punch_time,
        punch_type=punch_type,
        sync_status="synced",
        location_label=location_label,
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy_m,
        note=" | ".join(note_parts),
        shift_code=shift_code,
        shift_label=shift_label,
        photo_path=photo_path,
    )
    db.commit()

    flash(f"{_get_attendance_punch_label(punch_type)} berhasil direkam.", "success")
    return redirect("/absen/")
