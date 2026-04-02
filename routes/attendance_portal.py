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
from services.notification_service import notify_operational_event


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

ATTENDANCE_SHIFT_PROFILE_LABELS = {
    "mataram": "Gudang Mataram",
    "mega": "Gudang Mega",
}

ATTENDANCE_SHIFT_PROFILE_HELPERS = {
    "mataram": "Gudang Mataram: Shift Pagi 08.00 - 16.00, Shift Siang 13.00 - 21.00.",
    "mega": "Gudang Mega: Shift Pagi 09.00 - 17.00, Shift Siang 13.00 - 21.00.",
}
ATTENDANCE_LOCATION_SCOPE_LABELS = {
    "mataram": "Gudang Mataram",
    "mega": "Gudang Mega",
    "event": "Event",
    "other": "Lainnya",
}


def _resolve_shift_warehouse_key(linked_employee):
    source = dict(linked_employee) if linked_employee is not None and not isinstance(linked_employee, dict) else (linked_employee or {})
    warehouse_name = str(source.get("warehouse_name") or "").strip().lower()
    if "mega" in warehouse_name:
        return "mega"
    return "mataram"


def _resolve_default_location_scope(linked_employee):
    warehouse_key = _resolve_shift_warehouse_key(linked_employee)
    return "mega" if warehouse_key == "mega" else "mataram"


def _build_location_scope_options(linked_employee):
    default_scope = _resolve_default_location_scope(linked_employee)
    return [
        {
            "value": value,
            "label": label,
            "selected": value == default_scope,
        }
        for value, label in ATTENDANCE_LOCATION_SCOPE_LABELS.items()
    ]


def _normalize_shift_code(value):
    shift_code = (value or "").strip().lower()
    return shift_code if shift_code in {"pagi", "siang"} else None


def _normalize_shift_profile_key(value):
    shift_profile_key = (value or "").strip().lower()
    return shift_profile_key if shift_profile_key in ATTENDANCE_SHIFT_SCHEDULES else None


def _can_choose_shift_profile():
    return session.get("role") in {"hr", "super_admin"}


def _resolve_shift_profile_key_from_label(shift_label, fallback_key="mataram"):
    safe_label = str(shift_label or "").strip().lower()
    if not safe_label:
        return fallback_key

    for profile_key, schedule_map in ATTENDANCE_SHIFT_SCHEDULES.items():
        for schedule_item in schedule_map.values():
            label = _build_shift_label(schedule_item).strip().lower()
            time_label = f"{schedule_item['start'].replace(':', '.')} - {schedule_item['end'].replace(':', '.')}".strip().lower()
            if safe_label == label or time_label in safe_label:
                return profile_key

    return fallback_key


def _build_shift_label(schedule_item):
    if not schedule_item:
        return "-"
    return f"{schedule_item['label']} | {schedule_item['start'].replace(':', '.')} - {schedule_item['end'].replace(':', '.')}"


def _build_shift_profile_options(selected_profile_key):
    return [
        {
            "value": profile_key,
            "label": ATTENDANCE_SHIFT_PROFILE_LABELS.get(profile_key, "Gudang Mataram"),
            "helper_text": ATTENDANCE_SHIFT_PROFILE_HELPERS.get(profile_key, ""),
            "selected": profile_key == selected_profile_key,
        }
        for profile_key in ("mataram", "mega")
    ]


def _build_shift_profiles_payload():
    payload = {}
    for profile_key in ("mataram", "mega"):
        schedule_map = ATTENDANCE_SHIFT_SCHEDULES.get(profile_key, ATTENDANCE_SHIFT_SCHEDULES["mataram"])
        payload[profile_key] = {
            "label": ATTENDANCE_SHIFT_PROFILE_LABELS.get(profile_key, "Gudang Mataram"),
            "helper_text": ATTENDANCE_SHIFT_PROFILE_HELPERS.get(profile_key, ""),
            "options": [
                {
                    "value": shift_code,
                    "label": _build_shift_label(schedule_item),
                    "time_label": f"{schedule_item['start'].replace(':', '.')} - {schedule_item['end'].replace(':', '.')}",
                }
                for shift_code, schedule_item in schedule_map.items()
            ],
        }
    return payload


def _build_shift_options(linked_employee, shift_profile_key=None):
    warehouse_key = _normalize_shift_profile_key(shift_profile_key) or _resolve_shift_warehouse_key(linked_employee)
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
        elif punch_type in {"break_finish", "check_out"}:
            break_open = False
    return break_open


def _extract_latest_day_punch_time(day_logs):
    latest_punch_time = None
    for log in day_logs:
        safe_punch_time = (log.get("punch_time") or "").strip()
        if safe_punch_time and (latest_punch_time is None or safe_punch_time > latest_punch_time):
            latest_punch_time = safe_punch_time
    return latest_punch_time


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


def _resolve_selected_shift_profile_key(linked_employee, selected_shift):
    fallback_key = _resolve_shift_warehouse_key(linked_employee) if linked_employee else "mataram"
    return _resolve_shift_profile_key_from_label(selected_shift.get("shift_label"), fallback_key)


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
    selected_shift = _resolve_selected_shift(attendance_today, day_logs)
    selected_shift_profile_key = _resolve_selected_shift_profile_key(linked_employee, selected_shift)
    shift_options = _build_shift_options(linked_employee, selected_shift_profile_key) if linked_employee else []
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
        "day_logs": day_logs,
        "today_date": today_date,
        "punch_mode": punch_mode,
        "punch_options": punch_options,
        "shift_options": shift_options,
        "selected_shift_code": selected_shift_option["value"] if selected_shift_option else None,
        "selected_shift_label": selected_shift_option["label"] if selected_shift_option else "-",
        "selected_shift_time_label": selected_shift_option["time_label"] if selected_shift_option else "-",
        "shift_locked": bool(selected_shift.get("shift_code") or (attendance_today and attendance_today.get("check_in"))),
        "warehouse_shift_key": _resolve_shift_warehouse_key(linked_employee) if linked_employee else "mataram",
        "allow_shift_profile_choice": bool(linked_employee and _can_choose_shift_profile()),
        "shift_profile_key": selected_shift_profile_key,
        "shift_profile_label": ATTENDANCE_SHIFT_PROFILE_LABELS.get(selected_shift_profile_key, "Gudang Mataram"),
        "shift_profile_helper": ATTENDANCE_SHIFT_PROFILE_HELPERS.get(selected_shift_profile_key, ""),
        "shift_profile_options": _build_shift_profile_options(selected_shift_profile_key) if linked_employee and _can_choose_shift_profile() else [],
        "shift_profiles_payload": _build_shift_profiles_payload() if linked_employee else {},
        "location_scope_options": _build_location_scope_options(linked_employee) if linked_employee else [],
        "default_location_scope": _resolve_default_location_scope(linked_employee) if linked_employee else "mataram",
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
        portal_allow_shift_profile_choice=portal_state["allow_shift_profile_choice"],
        portal_selected_shift_profile_key=portal_state["shift_profile_key"],
        portal_selected_shift_profile_label=portal_state["shift_profile_label"],
        portal_selected_shift_profile_helper=portal_state["shift_profile_helper"],
        portal_shift_profile_options=portal_state["shift_profile_options"],
        portal_shift_profiles_payload=portal_state["shift_profiles_payload"],
        portal_location_scope_options=portal_state["location_scope_options"],
        portal_default_location_scope=portal_state["default_location_scope"],
    )


@attendance_portal_bp.route("/submit", methods=["POST"])
def submit():
    db = get_db()
    linked_employee = _get_self_service_employee(db)
    if linked_employee is None:
        flash("Akun ini belum ditautkan ke data karyawan. Hubungkan dulu dari halaman Admin.", "error")
        return redirect("/absen/")
    linked_employee = dict(linked_employee)

    portal_state = _fetch_attendance_portal_state(db)
    attendance_today = portal_state["attendance_today"]
    day_logs = portal_state["day_logs"]
    punch_mode = portal_state["punch_mode"]
    punch_options = portal_state["punch_options"]
    location_scope = (request.form.get("location_scope") or "").strip().lower()
    location_other_detail = (request.form.get("location_other_detail") or "").strip()
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
    requested_shift_profile_key = (
        portal_state["shift_profile_key"]
        if portal_state["shift_locked"]
        else (
            _normalize_shift_profile_key(request.form.get("shift_profile_key")) or portal_state["shift_profile_key"]
            if portal_state["allow_shift_profile_choice"]
            else portal_state["shift_profile_key"]
        )
    )
    requested_shift_code = _normalize_shift_code(request.form.get("shift_code"))
    active_shift_options = _build_shift_options(linked_employee, requested_shift_profile_key)
    if portal_state["shift_locked"] and portal_state["selected_shift_code"]:
        shift_code = portal_state["selected_shift_code"]
    elif requested_shift_code:
        shift_code = requested_shift_code
    else:
        shift_code = _resolve_default_shift_code(linked_employee, normalized_punch_time)
    shift_option = next(
        (option for option in active_shift_options if option["value"] == shift_code),
        active_shift_options[0] if active_shift_options else None,
    )
    shift_code = shift_option["value"] if shift_option else None
    shift_label = shift_option["label"] if shift_option else None
    note = (request.form.get("note") or "").strip()
    photo_data_url = request.form.get("photo_data_url")

    if location_scope in ATTENDANCE_LOCATION_SCOPE_LABELS:
        if location_scope == "other":
            if not location_other_detail:
                flash("Kalau pilih lokasi Lainnya, jelaskan dulu lokasinya secara singkat.", "error")
                return redirect("/absen/")
            location_label = f"Lainnya - {location_other_detail}"
        else:
            location_label = ATTENDANCE_LOCATION_SCOPE_LABELS[location_scope]

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

    latest_day_punch_time = _extract_latest_day_punch_time(day_logs)
    if latest_day_punch_time and punch_time < latest_day_punch_time:
        latest_display = latest_day_punch_time[11:16]
        flash(
            f"Jam absen tidak boleh lebih awal dari log terakhir hari ini ({latest_display}). Cek lagi urutan check in, break, atau check out.",
            "error",
        )
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

    biometric_log_id = _insert_biometric_log_record(
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

    try:
        employee_label = (linked_employee.get("full_name") or session.get("username") or "Karyawan").strip()
        warehouse_label = (linked_employee.get("warehouse_name") or "Gudang").strip()
        punch_label = _get_attendance_punch_label(punch_type)
        attendance_message = (
            f"{employee_label} merekam {punch_label} di {warehouse_label}"
            f" pada {punch_time[11:16]} dari titik {location_label}."
        )
        if shift_label:
            attendance_message += f" Shift aktif: {shift_label}."

        notify_operational_event(
            f"Absensi {punch_label}: {employee_label}",
            attendance_message,
            warehouse_id=linked_employee["warehouse_id"],
            category="attendance",
            link_url="/absen/",
            source_type="biometric_log",
            source_id=str(biometric_log_id),
            push_title=f"Absensi {punch_label}",
            push_body=f"{employee_label} | {warehouse_label} | {punch_time[11:16]}",
        )
    except Exception as exc:
        print("ATTENDANCE NOTIFICATION ERROR:", exc)

    flash(f"{_get_attendance_punch_label(punch_type)} berhasil direkam.", "success")
    return redirect("/absen/")
