from datetime import date as date_cls, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session

from database import get_db
from routes.schedule import (
    resolve_employee_live_schedule_for_date,
    resolve_employee_schedule_for_date,
)
from routes.hris import (
    _build_biometric_handling,
    _current_timestamp,
    _get_biometric_photo_url,
    _get_self_service_employee,
    _insert_biometric_log_record,
    _normalize_accuracy,
    _normalize_biometric_location_label,
    _normalize_datetime_input,
    _normalize_latitude,
    _normalize_longitude,
    _resync_attendance_from_biometrics,
    _save_biometric_photo_data,
)
from services.event_notification_policy import get_event_notification_policy
from services.rbac import normalize_role
from services.notification_service import notify_operational_event
from services.whatsapp_service import send_role_based_notification, send_user_whatsapp_notification


attendance_portal_bp = Blueprint("attendance_portal", __name__, url_prefix="/absen")


ATTENDANCE_PORTAL_PUNCH_LABELS = {
    "check_in": "Check In",
    "free_attendance": "Absen Bebas",
    "break_start": "Break Start",
    "break_finish": "Break Finish",
    "check_out": "Check Out",
    "complete": "Sudah Lengkap",
}

ATTENDANCE_PORTAL_CORRECTABLE_PUNCH_TYPES = {
    "check_out": "Check Out",
    "free_attendance": "Absen Bebas",
    "break_start": "Break Start",
}

ATTENDANCE_PORTAL_STATUS_LABELS = {
    "present": "Present",
    "late": "Late",
    "leave": "Leave",
    "absent": "Absent",
    "half_day": "Half Day",
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

ATTENDANCE_SPECIAL_SHIFT_RULES = (
    {
        "shift_code": "bu_ika",
        "label": "Shift Khusus Bu Ika",
        "start": "11:30",
        "end": "21:00",
        "helper_text": "Jam khusus Bu Ika: 11.30 - 21.00.",
        "aliases": ("bu ika", "ibu ika", "ika"),
    },
)

ATTENDANCE_CHECKOUT_REPORT_BYPASS_RULES = (
    {
        "label": "Prapti",
        "aliases": ("prapti", "bu prapti", "ibu prapti"),
    },
    {
        "label": "Ika",
        "aliases": ("ika", "bu ika", "ibu ika"),
    },
)

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


def _has_completed_daily_report_for_date(db, linked_employee, report_date, user_id=None):
    safe_report_date = str(report_date or "").strip()
    if not safe_report_date:
        return False

    employee_id = 0
    if linked_employee:
        employee_id = int((linked_employee.get("id") or 0))
    safe_user_id = int(user_id or session.get("user_id") or 0)

    row = db.execute(
        """
        SELECT id
        FROM daily_live_reports
        WHERE report_type='daily'
          AND report_date=?
          AND COALESCE(summary, '') <> ''
          AND COALESCE(blocker_note, '') <> ''
          AND COALESCE(follow_up_note, '') <> ''
          AND (
                (? > 0 AND COALESCE(employee_id, 0)=?)
             OR (? > 0 AND COALESCE(user_id, 0)=?)
          )
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (
            safe_report_date,
            employee_id,
            employee_id,
            safe_user_id,
            safe_user_id,
        ),
    ).fetchone()
    return row is not None


def _normalize_attendance_location_text(value):
    return " ".join(str(value or "").replace("|", " | ").split()).strip(" |-")


def _merge_attendance_location_label(scope_label, resolved_label):
    safe_scope_label = _normalize_attendance_location_text(scope_label)
    safe_resolved_label = _normalize_attendance_location_text(resolved_label)
    if not safe_scope_label:
        return safe_resolved_label
    if not safe_resolved_label:
        return safe_scope_label

    safe_scope_key = safe_scope_label.lower()
    safe_resolved_key = safe_resolved_label.lower()
    if (
        safe_resolved_key == safe_scope_key
        or safe_resolved_key.startswith(f"{safe_scope_key} |")
        or safe_resolved_key.startswith(f"{safe_scope_key} -")
    ):
        return safe_resolved_label
    return f"{safe_scope_label} | {safe_resolved_label}"


def _build_attendance_location_label(location_scope, location_other_detail, location_label):
    safe_scope = (location_scope or "").strip().lower()
    safe_other_detail = _normalize_attendance_location_text(location_other_detail)
    safe_location_label = _normalize_attendance_location_text(
        _normalize_biometric_location_label(location_label)
    )
    scope_label = ATTENDANCE_LOCATION_SCOPE_LABELS.get(safe_scope, "")

    if safe_scope == "other":
        if safe_other_detail and safe_location_label:
            if safe_location_label.lower().startswith("lainnya - "):
                return safe_location_label
            return f"Lainnya - {safe_other_detail} | {safe_location_label}"
        if safe_other_detail:
            return f"Lainnya - {safe_other_detail}"
        if safe_location_label:
            if safe_location_label.lower().startswith("lainnya |"):
                return safe_location_label
            return f"Lainnya | {safe_location_label}"
        return ""

    if scope_label:
        return _merge_attendance_location_label(scope_label, safe_location_label)
    return safe_location_label


def _build_google_maps_url(latitude, longitude):
    try:
        latitude_value = float(latitude)
        longitude_value = float(longitude)
    except (TypeError, ValueError):
        return None
    return f"https://www.google.com/maps?q={latitude_value:.6f},{longitude_value:.6f}"


def _normalize_identity_text(value):
    cleaned = "".join(
        char.lower() if str(char).isalnum() else " "
        for char in str(value or "").strip()
    )
    return " ".join(cleaned.split())


def _matches_identity_alias(candidate, alias):
    normalized_candidate = _normalize_identity_text(candidate)
    normalized_alias = _normalize_identity_text(alias)
    if not normalized_candidate or not normalized_alias:
        return False
    return (
        normalized_candidate == normalized_alias
        or normalized_candidate.startswith(f"{normalized_alias} ")
    )


def _resolve_special_shift_rule(linked_employee):
    source = (
        dict(linked_employee)
        if linked_employee is not None and not isinstance(linked_employee, dict)
        else (linked_employee or {})
    )
    candidate_values = (
        source.get("full_name"),
        source.get("employee_code"),
        session.get("username"),
    )
    for rule in ATTENDANCE_SPECIAL_SHIFT_RULES:
        aliases = rule.get("aliases") or ()
        for candidate in candidate_values:
            if any(_matches_identity_alias(candidate, alias) for alias in aliases):
                return rule
    return None


def _resolve_checkout_report_bypass_rule(linked_employee):
    source = (
        dict(linked_employee)
        if linked_employee is not None and not isinstance(linked_employee, dict)
        else (linked_employee or {})
    )
    candidate_values = (
        source.get("full_name"),
        source.get("employee_code"),
        session.get("username"),
    )
    for rule in ATTENDANCE_CHECKOUT_REPORT_BYPASS_RULES:
        aliases = rule.get("aliases") or ()
        for candidate in candidate_values:
            if any(_matches_identity_alias(candidate, alias) for alias in aliases):
                return rule
    return None


def _build_special_shift_option(rule):
    return {
        "value": rule["shift_code"],
        "label": _build_shift_label(rule),
        "time_label": f"{rule['start'].replace(':', '.')} - {rule['end'].replace(':', '.')}",
        "start": rule["start"],
        "end": rule["end"],
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
    allowed_shift_codes = {"pagi", "siang"} | {
        str(rule.get("shift_code") or "").strip().lower()
        for rule in ATTENDANCE_SPECIAL_SHIFT_RULES
        if str(rule.get("shift_code") or "").strip()
    }
    return shift_code if shift_code in allowed_shift_codes else None


def _normalize_shift_profile_key(value):
    shift_profile_key = (value or "").strip().lower()
    return shift_profile_key if shift_profile_key in ATTENDANCE_SHIFT_SCHEDULES else None


def _can_choose_shift_profile():
    return normalize_role(session.get("role")) in {"hr", "super_admin"}


def _can_correct_attendance_portal_logs():
    return normalize_role(session.get("role")) in {"hr", "super_admin"}


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


def _build_shift_profiles_payload(linked_employee=None):
    special_rule = _resolve_special_shift_rule(linked_employee)
    payload = {}
    for profile_key in ("mataram", "mega"):
        schedule_map = ATTENDANCE_SHIFT_SCHEDULES.get(profile_key, ATTENDANCE_SHIFT_SCHEDULES["mataram"])
        if special_rule:
            helper_text = special_rule["helper_text"]
            options = [_build_special_shift_option(special_rule)]
        else:
            helper_text = ATTENDANCE_SHIFT_PROFILE_HELPERS.get(profile_key, "")
            options = [
                {
                    "value": shift_code,
                    "label": _build_shift_label(schedule_item),
                    "time_label": f"{schedule_item['start'].replace(':', '.')} - {schedule_item['end'].replace(':', '.')}",
                }
                for shift_code, schedule_item in schedule_map.items()
            ]
        payload[profile_key] = {
            "label": ATTENDANCE_SHIFT_PROFILE_LABELS.get(profile_key, "Gudang Mataram"),
            "helper_text": helper_text,
            "options": options,
        }
    return payload


def _build_shift_options(linked_employee, shift_profile_key=None):
    special_rule = _resolve_special_shift_rule(linked_employee)
    if special_rule:
        return [_build_special_shift_option(special_rule)]

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
    special_rule = _resolve_special_shift_rule(linked_employee)
    if special_rule:
        return special_rule["shift_code"]

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

    options = ["free_attendance"]
    if break_open:
        options.append("break_finish")
    else:
        options.append("break_start")
    options.append("check_out")
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


def _build_attendance_punch_helper_text(punch_options):
    safe_options = [option for option in punch_options if option in ATTENDANCE_PORTAL_PUNCH_LABELS]
    if not safe_options:
        return "Check in dan check out hari ini sudah lengkap. Jika perlu koreksi, lanjutkan dari riwayat absen."
    if safe_options == ["check_in"]:
        return "Mulai dulu dengan Check In. Setelah itu dropdown ini otomatis menampilkan pilihan absen lainnya."

    if "free_attendance" in safe_options:
        follow_up_labels = [
            _get_attendance_punch_label(option)
            for option in safe_options
            if option != "free_attendance"
        ]
        if not follow_up_labels:
            return "Absen Bebas bisa dipakai berkali-kali selama shift belum diakhiri dengan Check Out."
        if len(follow_up_labels) == 1:
            follow_up_text = follow_up_labels[0]
        elif len(follow_up_labels) == 2:
            follow_up_text = f"{follow_up_labels[0]} atau {follow_up_labels[1]}"
        else:
            follow_up_text = f"{', '.join(follow_up_labels[:-1])}, atau {follow_up_labels[-1]}"
        return (
            f"Pilihan absen berikutnya: {follow_up_text}. "
            "Absen Bebas bisa dipakai berkali-kali selama shift belum diakhiri dengan Check Out."
        )

    option_labels = [_get_attendance_punch_label(option) for option in safe_options]
    if len(option_labels) == 1:
        return f"Pilihan absen berikutnya: {option_labels[0]}."
    if len(option_labels) == 2:
        return f"Setelah Check In, dropdown ini menampilkan pilihan absen lainnya: {option_labels[0]} atau {option_labels[1]}."
    return (
        "Setelah Check In, dropdown ini menampilkan pilihan absen lainnya: "
        f"{', '.join(option_labels[:-1])}, atau {option_labels[-1]}."
    )


def _build_attendance_status_badge(status):
    safe_status = (status or "absent").strip().lower()
    if safe_status == "present":
        badge_class = "green"
    elif safe_status in {"late", "leave", "half_day"}:
        badge_class = "orange"
    else:
        badge_class = "red"
    return {
        "value": safe_status,
        "label": ATTENDANCE_PORTAL_STATUS_LABELS.get(safe_status, safe_status.replace("_", " ").title()),
        "badge_class": badge_class,
    }


def _format_portal_datetime_display(raw_value, include_date=False):
    safe_value = (raw_value or "").strip()
    if not safe_value:
        return "-"
    try:
        parsed = datetime.fromisoformat(safe_value.replace("T", " "))
    except ValueError:
        return safe_value
    if include_date:
        return parsed.strftime("%d %b %Y %H:%M")
    return parsed.strftime("%H:%M")


def _parse_attendance_portal_datetime(raw_value):
    safe_value = (raw_value or "").strip()
    if not safe_value:
        return None
    try:
        return datetime.fromisoformat(safe_value.replace("T", " "))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(safe_value, fmt)
            except ValueError:
                continue
    return None


def _format_attendance_duration_label(total_seconds):
    safe_seconds = max(0, int(total_seconds or 0))
    total_minutes = safe_seconds // 60
    if total_minutes <= 0:
        return "kurang dari 1 menit"

    days, remainder_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remainder_minutes, 60)
    parts = []
    if days:
        parts.append(f"{days} hari")
    if hours:
        parts.append(f"{hours} jam")
    if minutes:
        parts.append(f"{minutes} menit")
    return " ".join(parts) if parts else "kurang dari 1 menit"


def _build_attendance_duration_meta(day_logs, punch_time, punch_type):
    current_punch_at = _parse_attendance_portal_datetime(punch_time)
    safe_punch_type = (punch_type or "").strip().lower()
    if current_punch_at is None or safe_punch_type not in {"break_finish", "check_out"}:
        return {"duration_kind": "", "duration_label": "", "duration_text": ""}

    normalized_logs = []
    for log in day_logs or []:
        log_time = _parse_attendance_portal_datetime(log.get("punch_time"))
        log_type = (log.get("punch_type") or "").strip().lower()
        if log_time is None or not log_type:
            continue
        normalized_logs.append({"punch_time": log_time, "punch_type": log_type})
    normalized_logs.sort(key=lambda item: item["punch_time"])

    if safe_punch_type == "break_finish":
        break_started_at = None
        for log in normalized_logs:
            if log["punch_type"] == "break_start":
                break_started_at = log["punch_time"]
            elif log["punch_type"] in {"break_finish", "check_out"}:
                break_started_at = None
        if break_started_at is None or current_punch_at <= break_started_at:
            return {"duration_kind": "", "duration_label": "", "duration_text": ""}

        duration_label = _format_attendance_duration_label(
            (current_punch_at - break_started_at).total_seconds()
        )
        return {
            "duration_kind": "break",
            "duration_label": duration_label,
            "duration_text": f"Durasi istirahat: {duration_label}.",
        }

    check_in_at = next(
        (
            log["punch_time"]
            for log in normalized_logs
            if log["punch_type"] == "check_in"
        ),
        None,
    )
    if check_in_at is None or current_punch_at <= check_in_at:
        return {"duration_kind": "", "duration_label": "", "duration_text": ""}

    break_started_at = None
    break_seconds = 0
    for log in normalized_logs:
        if log["punch_type"] == "break_start":
            break_started_at = log["punch_time"]
        elif log["punch_type"] in {"break_finish", "check_out"} and break_started_at is not None:
            if log["punch_time"] > break_started_at:
                break_seconds += (log["punch_time"] - break_started_at).total_seconds()
            break_started_at = None

    if break_started_at is not None and current_punch_at > break_started_at:
        break_seconds += (current_punch_at - break_started_at).total_seconds()

    total_seconds = (current_punch_at - check_in_at).total_seconds() - break_seconds
    if total_seconds <= 0:
        return {"duration_kind": "", "duration_label": "", "duration_text": ""}

    duration_label = _format_attendance_duration_label(total_seconds)
    return {
        "duration_kind": "work",
        "duration_label": duration_label,
        "duration_text": f"Durasi kerja efektif: {duration_label}.",
    }


def _build_checkout_edit_value(punch_time, attendance_date, fallback_check_out):
    normalized = _normalize_datetime_input(punch_time)
    if normalized:
        return normalized[:16].replace(" ", "T")
    if attendance_date and fallback_check_out:
        return f"{attendance_date}T{fallback_check_out}"
    return ""


def _build_next_day_schedule_whatsapp_payload(linked_employee, schedule_snapshot, live_schedule_entries=None):
    if not linked_employee:
        return None

    schedule_snapshot = schedule_snapshot or {}
    live_schedule_entries = [entry for entry in (live_schedule_entries or []) if entry]
    employee_name = str(linked_employee.get("full_name") or schedule_snapshot.get("display_name") or "Karyawan").strip()
    first_name = employee_name.split()[0] if employee_name else "Kamu"
    warehouse_label = str(
        schedule_snapshot.get("warehouse_name")
        or (live_schedule_entries[0].get("warehouse_name") if live_schedule_entries else "")
        or linked_employee.get("warehouse_name")
        or "Gudang"
    ).strip()
    schedule_day_label = str(
        schedule_snapshot.get("full_label")
        or (live_schedule_entries[0].get("full_label") if live_schedule_entries else "")
        or "besok"
    ).strip()
    schedule_label = str(schedule_snapshot.get("label") or schedule_snapshot.get("code") or "").strip()
    schedule_note = str(schedule_snapshot.get("note") or "").strip()
    schedule_code = str(schedule_snapshot.get("code") or "").strip().upper()
    schedule_source = str(schedule_snapshot.get("source") or "").strip().lower()

    subject = f"Pengingat Jadwal Besok: {employee_name}"
    message_lines = [
        f"Halo {first_name}, pengingat jadwal untuk {schedule_day_label} di {warehouse_label}.",
        "",
        "Shift utama:",
    ]

    if schedule_snapshot and schedule_snapshot.get("has_schedule"):
        if schedule_source == "manual" and schedule_code and schedule_code != "OFF":
            message_lines.append(f"- Besok kamu masuk {schedule_label}")
        else:
            message_lines.append(f"- {schedule_label}")
        if schedule_note:
            message_lines.append(f"- Catatan shift: {schedule_note}")
    elif live_schedule_entries:
        message_lines.append("- Jadwal shift utama besok belum diisi di board.")
    else:
        message_lines.append(
            "- Jadwal besok belum diisi di board. Silakan cek ke HR atau atasan untuk konfirmasi shift."
        )

    if live_schedule_entries:
        message_lines.extend(["", "Jadwal live kamu:"])
        for entry in live_schedule_entries:
            slot_label = str(entry.get("slot_label") or entry.get("slot_key") or "").strip()
            channel_label = str(entry.get("channel_label") or "").strip()
            note_label = str(entry.get("note") or "").strip()
            if channel_label:
                live_line = f"- {slot_label} | {channel_label}"
            elif note_label:
                live_line = f"- {slot_label} | {note_label}"
            else:
                live_line = f"- {slot_label}"
            message_lines.append(live_line)

    message_lines.extend(["", "Silakan cek board jadwal bila ada perubahan terbaru."])
    message = "\n".join(line for line in message_lines if line is not None)
    return {"subject": subject, "message": message}


def _build_portal_log_correction_options(current_punch_type):
    safe_current = (current_punch_type or "check_out").strip().lower()
    return [
        {
            "value": value,
            "label": label,
            "selected": value == safe_current,
        }
        for value, label in ATTENDANCE_PORTAL_CORRECTABLE_PUNCH_TYPES.items()
    ]


def _fetch_attendance_history(db, linked_employee, limit=8):
    if not linked_employee:
        return []
    can_correct_logs = _can_correct_attendance_portal_logs()

    attendance_rows = [
        dict(row)
        for row in db.execute(
            """
            SELECT id, attendance_date, check_in, check_out, status, shift_code, shift_label, note, updated_at
            FROM attendance_records
            WHERE employee_id=?
            ORDER BY attendance_date DESC, id DESC
            LIMIT ?
            """,
            (linked_employee["id"], limit),
        ).fetchall()
    ]
    if not attendance_rows:
        return []

    history_dates = [row["attendance_date"] for row in attendance_rows if row.get("attendance_date")]
    history_logs_by_date = {}
    if history_dates:
        placeholders = ",".join(["?"] * len(history_dates))
        log_rows = [
            dict(row)
            for row in db.execute(
                f"""
                SELECT id, punch_time, punch_type, sync_status, location_label, note, photo_path
                       , latitude, longitude
                FROM biometric_logs
                WHERE employee_id=?
                  AND substr(punch_time, 1, 10) IN ({placeholders})
                ORDER BY punch_time ASC, id ASC
                """,
                [linked_employee["id"], *history_dates],
            ).fetchall()
        ]
        for row in log_rows:
            history_logs_by_date.setdefault((row.get("punch_time") or "")[:10], []).append(row)

    history_items = []
    for row in attendance_rows:
        attendance_date = row.get("attendance_date")
        day_logs = history_logs_by_date.get(attendance_date, [])
        latest_checkout_log = next(
            (log for log in reversed(day_logs) if (log.get("punch_type") or "").strip().lower() == "check_out"),
            None,
        )
        status_meta = _build_attendance_status_badge(row.get("status"))
        history_items.append(
            {
                "attendance_date": attendance_date,
                "check_in": row.get("check_in") or "-",
                "check_out": row.get("check_out") or "-",
                "status_label": status_meta["label"],
                "status_badge": status_meta["badge_class"],
                "shift_label": row.get("shift_label") or "-",
                "note": row.get("note") or "Belum ada catatan",
                "updated_at_label": _format_portal_datetime_display(row.get("updated_at"), include_date=True),
                "log_count": len(day_logs),
                "logs": [
                    {
                        "id": log["id"],
                        "punch_label": _get_attendance_punch_label(log.get("punch_type")),
                        "punch_time_label": _format_portal_datetime_display(log.get("punch_time")),
                        "location_label": (log.get("location_label") or "-").strip() or "-",
                        "gmaps_url": _build_google_maps_url(log.get("latitude"), log.get("longitude")),
                        "note": (log.get("note") or "").strip(),
                        "photo_url": _get_biometric_photo_url(log.get("photo_path")),
                        "has_photo": bool(log.get("photo_path")),
                        "sync_status": (log.get("sync_status") or "").strip().lower() or "queued",
                    }
                    for log in day_logs
                ],
                "can_edit_check_out": bool(latest_checkout_log) and can_correct_logs,
                "check_out_log_id": latest_checkout_log["id"] if latest_checkout_log else None,
                "edit_punch_type_options": _build_portal_log_correction_options(
                    latest_checkout_log.get("punch_type") if latest_checkout_log else "check_out"
                ),
                "edit_check_out_value": _build_checkout_edit_value(
                    latest_checkout_log.get("punch_time") if latest_checkout_log else None,
                    attendance_date,
                    row.get("check_out"),
                ),
                "show_correction_hint": bool(latest_checkout_log) and not can_correct_logs,
            }
        )
    return history_items


def _normalize_cash_closing_date(value):
    safe_value = str(value or "").strip()
    if not safe_value:
        return date_cls.today().isoformat()
    try:
        return date_cls.fromisoformat(safe_value).isoformat()
    except ValueError:
        return date_cls.today().isoformat()


def _parse_cash_closing_amount(value):
    raw_value = str(value or "").strip()
    if not raw_value:
        return 0
    normalized = (
        raw_value.replace("Rp", "")
        .replace("rp", "")
        .replace(".", "")
        .replace(",", "")
        .replace(" ", "")
    )
    digits = []
    for index, char in enumerate(normalized):
        if char.isdigit():
            digits.append(char)
        elif char == "-" and index == 0:
            digits.append(char)
    try:
        parsed = int("".join(digits))
    except ValueError:
        return 0
    return max(parsed, 0)


def _format_cash_closing_amount(value, zero_label="-"):
    try:
        amount = int(round(float(value or 0)))
    except (TypeError, ValueError):
        amount = 0
    amount = max(amount, 0)
    if amount <= 0:
        return zero_label
    return f"{amount:,}".replace(",", ".")


def _format_cash_closing_date_label(value):
    safe_value = _normalize_cash_closing_date(value)
    try:
        return date_cls.fromisoformat(safe_value).strftime("%d/%m/%Y")
    except ValueError:
        return safe_value


def _build_cash_closing_warehouse_label(linked_employee):
    warehouse_name = str((linked_employee or {}).get("warehouse_name") or "").strip()
    warehouse_key = warehouse_name.lower()
    if "mega" in warehouse_key:
        return "Mega"
    if "mataram" in warehouse_key:
        return "Mataram"
    if warehouse_name.lower().startswith("gudang "):
        warehouse_name = warehouse_name[7:].strip()
    return warehouse_name or "Mataram"


def _build_cash_closing_summary_line(label, amount, zero_label="-"):
    return f"{label:<11} = {_format_cash_closing_amount(amount, zero_label=zero_label)}"


def _build_cash_closing_summary_message(
    linked_employee,
    closing_date,
    *,
    cash_amount=0,
    debit_amount=0,
    qris_amount=0,
    mb_amount=0,
    cv_amount=0,
    expense_amount=0,
    cash_on_hand_amount=0,
    combined_total_amount=0,
    note="",
):
    warehouse_label = _build_cash_closing_warehouse_label(linked_employee)
    summary_total_amount = max(
        int(cash_amount or 0)
        + int(debit_amount or 0)
        + int(qris_amount or 0)
        + int(mb_amount or 0)
        + int(cv_amount or 0),
        0,
    )
    message_lines = [
        f'Laporan "{warehouse_label}" {_format_cash_closing_date_label(closing_date)}',
        "",
        _build_cash_closing_summary_line("Tunai", cash_amount),
        _build_cash_closing_summary_line("Debet", debit_amount),
        _build_cash_closing_summary_line("QRIS", qris_amount),
        _build_cash_closing_summary_line("Mb", mb_amount),
        _build_cash_closing_summary_line("CV", cv_amount),
        "------------------------------",
        _build_cash_closing_summary_line("Tot.", summary_total_amount, zero_label="0"),
        _build_cash_closing_summary_line("Pengeluaran", expense_amount),
        _build_cash_closing_summary_line("T.Uang", cash_on_hand_amount),
        "",
        f"Total Mataram dan Mega = {_format_cash_closing_amount(combined_total_amount)}",
    ]
    safe_note = str(note or "").strip()
    if safe_note:
        message_lines.extend(["", f"Catatan: {safe_note}"])
    message_lines.extend(["", "Alhamdulillah"])
    return "\n".join(message_lines)


def _build_cash_closing_preview_seed(linked_employee, closing_date=None):
    return _build_cash_closing_summary_message(
        linked_employee,
        closing_date or date_cls.today().isoformat(),
        cash_amount=0,
        debit_amount=0,
        qris_amount=0,
        mb_amount=0,
        cv_amount=0,
        expense_amount=0,
        cash_on_hand_amount=0,
        combined_total_amount=0,
        note="",
    )


def _build_cash_closing_wa_status_meta(status):
    safe_status = str(status or "").strip().lower()
    status_map = {
        "sent": {"label": "WA Terkirim", "badge_class": "green"},
        "partial": {"label": "WA Sebagian", "badge_class": "orange"},
        "failed": {"label": "WA Gagal", "badge_class": "red"},
        "skipped": {"label": "WA Belum Terkirim", "badge_class": ""},
        "pending": {"label": "WA Pending", "badge_class": ""},
    }
    return status_map.get(safe_status, status_map["pending"])


def _fetch_cash_closing_reports(db, linked_employee, limit=6):
    if not linked_employee:
        return []

    rows = [
        dict(row)
        for row in db.execute(
            """
            SELECT
                id,
                closing_date,
                cash_amount,
                debit_amount,
                qris_amount,
                mb_amount,
                cv_amount,
                reported_total_amount,
                expense_amount,
                cash_on_hand_amount,
                combined_total_amount,
                note,
                summary_message,
                wa_status,
                wa_error,
                wa_delivery_count,
                wa_success_count,
                created_at
            FROM cash_closing_reports
            WHERE employee_id=?
            ORDER BY closing_date DESC, id DESC
            LIMIT ?
            """,
            (linked_employee["id"], limit),
        ).fetchall()
    ]
    report_items = []
    for row in rows:
        wa_meta = _build_cash_closing_wa_status_meta(row.get("wa_status"))
        delivery_count = int(row.get("wa_delivery_count") or 0)
        success_count = int(row.get("wa_success_count") or 0)
        report_items.append(
            {
                "id": row["id"],
                "closing_date_label": _format_cash_closing_date_label(row.get("closing_date")),
                "created_at_label": _format_portal_datetime_display(row.get("created_at"), include_date=True),
                "summary_message": (row.get("summary_message") or "").strip() or _build_cash_closing_preview_seed(
                    linked_employee,
                    row.get("closing_date"),
                ),
                "note": (row.get("note") or "").strip(),
                "wa_status": (row.get("wa_status") or "pending").strip().lower() or "pending",
                "wa_status_label": wa_meta["label"],
                "wa_status_badge": wa_meta["badge_class"],
                "wa_error": (row.get("wa_error") or "").strip(),
                "wa_delivery_count": delivery_count,
                "wa_success_count": success_count,
                "summary_total_label": _format_cash_closing_amount(row.get("reported_total_amount"), zero_label="0"),
            }
        )
    return report_items


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
    if _resolve_special_shift_rule(linked_employee):
        return fallback_key
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
    special_shift_rule = _resolve_special_shift_rule(linked_employee)
    shift_options = _build_shift_options(linked_employee, selected_shift_profile_key) if linked_employee else []
    selected_shift_code = _normalize_shift_code(selected_shift.get("shift_code"))
    if not selected_shift_code and linked_employee:
        selected_shift_code = _resolve_default_shift_code(linked_employee)
    selected_shift_option = next(
        (option for option in shift_options if option["value"] == selected_shift_code),
        shift_options[0] if shift_options else None,
    )
    attendance_history = _fetch_attendance_history(db, linked_employee)
    cash_closing_reports = _fetch_cash_closing_reports(db, linked_employee)
    checkout_report_bypass_rule = _resolve_checkout_report_bypass_rule(linked_employee)
    check_out_daily_report_required = bool(linked_employee and checkout_report_bypass_rule is None)
    today_daily_report_submitted = _has_completed_daily_report_for_date(
        db,
        linked_employee,
        today_date,
        user_id=session.get("user_id"),
    ) if linked_employee else False

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
        "shift_profile_helper": (
            special_shift_rule["helper_text"]
            if special_shift_rule
            else ATTENDANCE_SHIFT_PROFILE_HELPERS.get(selected_shift_profile_key, "")
        ),
        "shift_profile_options": _build_shift_profile_options(selected_shift_profile_key) if linked_employee and _can_choose_shift_profile() else [],
        "shift_profiles_payload": _build_shift_profiles_payload(linked_employee) if linked_employee else {},
        "location_scope_options": _build_location_scope_options(linked_employee) if linked_employee else [],
        "default_location_scope": _resolve_default_location_scope(linked_employee) if linked_employee else "mataram",
        "attendance_history": attendance_history,
        "cash_closing_reports": cash_closing_reports,
        "cash_closing_preview_text": _build_cash_closing_preview_seed(linked_employee, today_date) if linked_employee else "",
        "cash_closing_default_date": today_date,
        "cash_closing_warehouse_label": _build_cash_closing_warehouse_label(linked_employee) if linked_employee else "Mataram",
        "show_follow_up_punch_group": len(punch_options) > 1 and punch_mode != "check_in",
        "today_daily_report_submitted": today_daily_report_submitted,
        "check_out_daily_report_required": check_out_daily_report_required,
        "check_out_daily_report_bypass_label": (
            str(checkout_report_bypass_rule.get("label") or "").strip()
            if checkout_report_bypass_rule
            else ""
        ),
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
        portal_punch_helper_text=_build_attendance_punch_helper_text(portal_state["punch_options"]),
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
        attendance_history=portal_state["attendance_history"],
        cash_closing_reports=portal_state["cash_closing_reports"],
        cash_closing_preview_text=portal_state["cash_closing_preview_text"],
        cash_closing_default_date=portal_state["cash_closing_default_date"],
        cash_closing_warehouse_label=portal_state["cash_closing_warehouse_label"],
        portal_show_follow_up_punch_group=portal_state["show_follow_up_punch_group"],
        portal_today_daily_report_submitted=portal_state["today_daily_report_submitted"],
        portal_check_out_daily_report_required=portal_state["check_out_daily_report_required"],
        portal_check_out_daily_report_bypass_label=portal_state["check_out_daily_report_bypass_label"],
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

    location_label = _build_attendance_location_label(
        location_scope,
        location_other_detail,
        location_label,
    )

    if location_scope == "other" and not location_label:
        flash("Kalau pilih lokasi Lainnya, isi alamat atau jelaskan dulu tempat absennya.", "error")
        return redirect("/absen/")

    if punch_mode == "complete":
        flash("Absensi hari ini sudah lengkap. Jika perlu koreksi, lanjutkan dari HR atau Super Admin.", "error")
        return redirect("/absen/")

    if requested_punch_type and requested_punch_type not in allowed_punch_types:
        flash("Tipe absen tidak sesuai urutan harian. Pilih tipe yang tersedia di form.", "error")
        return redirect("/absen/")

    if (
        punch_type == "check_out"
        and portal_state["check_out_daily_report_required"]
        and not _has_completed_daily_report_for_date(
        db,
        linked_employee,
        punch_time[:10],
        user_id=session.get("user_id"),
    )):
        flash(
            "Sebelum check out, kirim report harian dulu. Isi ringkasan kerja, kendala, dan tindak lanjut sampai lengkap.",
            "error",
        )
        return redirect("/laporan-harian/")

    if not location_label:
        flash("Alamat atau tempat absen wajib diisi sebelum absen.", "error")
        return redirect("/absen/")

    if latitude is None or longitude is None:
        flash("Lokasi GPS belum valid. Ambil lokasi dulu sebelum absen.", "error")
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

    employee_label = (linked_employee.get("full_name") or session.get("username") or "Karyawan").strip()
    warehouse_label = (linked_employee.get("warehouse_name") or "Gudang").strip()
    punch_label = _get_attendance_punch_label(punch_type)
    duration_meta = _build_attendance_duration_meta(day_logs, punch_time, punch_type)

    try:
        attendance_message = (
            f"{employee_label} merekam {punch_label} di {warehouse_label}"
            f" pada {punch_time[11:16]} di {location_label}."
        )
        if shift_label:
            attendance_message += f" Shift aktif: {shift_label}."
        if duration_meta["duration_text"]:
            attendance_message += f" {duration_meta['duration_text']}"

        attendance_policy = get_event_notification_policy("attendance.activity")
        push_segments = [employee_label, warehouse_label, punch_time[11:16]]
        if duration_meta["duration_label"]:
            duration_prefix = "istirahat" if duration_meta["duration_kind"] == "break" else "kerja"
            push_segments.append(f"{duration_prefix} {duration_meta['duration_label']}")
        notify_operational_event(
            f"Absensi {punch_label}: {employee_label}",
            attendance_message,
            warehouse_id=linked_employee["warehouse_id"],
            include_actor=False,
            exclude_user_ids=[session.get("user_id")],
            category="attendance",
            link_url="/absen/",
            recipient_roles=attendance_policy["roles"],
            recipient_usernames=attendance_policy["usernames"],
            recipient_user_ids=attendance_policy["user_ids"],
            source_type="biometric_log",
            source_id=str(biometric_log_id),
            push_title=f"Absensi {punch_label}",
            push_body=" | ".join(push_segments),
        )
    except Exception as exc:
        print("ATTENDANCE NOTIFICATION ERROR:", exc)

    try:
        send_role_based_notification(
            "attendance.activity",
            {
                "warehouse_id": linked_employee["warehouse_id"],
                "employee_name": employee_label,
                "warehouse_name": warehouse_label,
                "punch_label": punch_label,
                "time_label": punch_time[11:16],
                "location_label": location_label,
                "duration_kind": duration_meta["duration_kind"],
                "duration_label": duration_meta["duration_label"],
                "duration_text": duration_meta["duration_text"],
                "link_url": "/absen/",
                "exclude_user_ids": [session.get("user_id")],
            },
        )
    except Exception as exc:
        print("ATTENDANCE WHATSAPP ROLE NOTIFICATION ERROR:", exc)

    if punch_type == "check_out" and session.get("user_id"):
        try:
            schedule_target_date = date_cls.fromisoformat(punch_time[:10]) + timedelta(days=1)
            schedule_snapshot = resolve_employee_schedule_for_date(
                db,
                linked_employee["id"],
                schedule_target_date,
            )
            live_schedule_entries = resolve_employee_live_schedule_for_date(
                db,
                linked_employee["id"],
                schedule_target_date,
            )
            schedule_whatsapp_payload = _build_next_day_schedule_whatsapp_payload(
                linked_employee,
                schedule_snapshot,
                live_schedule_entries,
            )
            if schedule_whatsapp_payload:
                send_user_whatsapp_notification(
                    session.get("user_id"),
                    schedule_whatsapp_payload["subject"],
                    schedule_whatsapp_payload["message"],
                )
        except Exception as exc:
            print("ATTENDANCE NEXT DAY SCHEDULE WHATSAPP ERROR:", exc)

    flash(f"{_get_attendance_punch_label(punch_type)} berhasil direkam.", "success")
    return redirect("/absen/")


@attendance_portal_bp.route("/cash-closing/submit", methods=["POST"])
def submit_cash_closing():
    db = get_db()
    linked_employee = _get_self_service_employee(db)
    if linked_employee is None:
        flash("Akun ini belum ditautkan ke data karyawan. Hubungkan dulu dari halaman Admin.", "error")
        return redirect("/absen/#tutup-kasir")
    linked_employee = dict(linked_employee)

    closing_date = _normalize_cash_closing_date(request.form.get("closing_date"))
    cash_amount = _parse_cash_closing_amount(request.form.get("cash_amount"))
    debit_amount = _parse_cash_closing_amount(request.form.get("debit_amount"))
    qris_amount = _parse_cash_closing_amount(request.form.get("qris_amount"))
    mb_amount = _parse_cash_closing_amount(request.form.get("mb_amount"))
    cv_amount = _parse_cash_closing_amount(request.form.get("cv_amount"))
    expense_amount = _parse_cash_closing_amount(request.form.get("expense_amount"))
    cash_on_hand_amount = _parse_cash_closing_amount(request.form.get("cash_on_hand_amount"))
    combined_total_amount = _parse_cash_closing_amount(request.form.get("combined_total_amount"))
    note = (request.form.get("note") or "").strip()

    if not any(
        (
            cash_amount,
            debit_amount,
            qris_amount,
            mb_amount,
            cv_amount,
            expense_amount,
            cash_on_hand_amount,
            combined_total_amount,
        )
    ):
        flash("Isi minimal satu nominal sebelum mengirim tutup kasir.", "error")
        return redirect("/absen/#tutup-kasir")

    reported_total_amount = cash_amount + debit_amount + qris_amount + mb_amount + cv_amount
    summary_message = _build_cash_closing_summary_message(
        linked_employee,
        closing_date,
        cash_amount=cash_amount,
        debit_amount=debit_amount,
        qris_amount=qris_amount,
        mb_amount=mb_amount,
        cv_amount=cv_amount,
        expense_amount=expense_amount,
        cash_on_hand_amount=cash_on_hand_amount,
        combined_total_amount=combined_total_amount,
        note=note,
    )
    warehouse_label = _build_cash_closing_warehouse_label(linked_employee)
    employee_label = (linked_employee.get("full_name") or session.get("username") or "Staff").strip()
    submitted_at = _current_timestamp()
    submitted_time_label = submitted_at[11:16] if len(submitted_at) >= 16 else datetime.now().strftime("%H:%M")
    subject = (
        f"Tutup Kasir {warehouse_label} "
        f"{_format_cash_closing_date_label(closing_date)} | {employee_label} | {submitted_time_label}"
    )

    cursor = db.execute(
        """
        INSERT INTO cash_closing_reports(
            user_id,
            employee_id,
            warehouse_id,
            closing_date,
            cash_amount,
            debit_amount,
            qris_amount,
            mb_amount,
            cv_amount,
            reported_total_amount,
            expense_amount,
            cash_on_hand_amount,
            combined_total_amount,
            note,
            summary_message,
            wa_status,
            created_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            session.get("user_id"),
            linked_employee["id"],
            linked_employee.get("warehouse_id"),
            closing_date,
            cash_amount,
            debit_amount,
            qris_amount,
            mb_amount,
            cv_amount,
            reported_total_amount,
            expense_amount,
            cash_on_hand_amount,
            combined_total_amount,
            note,
            summary_message,
            "pending",
            submitted_at,
            submitted_at,
        ),
    )
    report_id = cursor.lastrowid
    db.commit()

    wa_status = "pending"
    wa_error = ""
    delivery_count = 0
    success_count = 0

    try:
        wa_result = send_role_based_notification(
            "attendance.cash_closing",
            {
                "roles": ("leader",),
                "warehouse_id": linked_employee.get("warehouse_id"),
                "employee_name": employee_label,
                "warehouse_name": linked_employee.get("warehouse_name") or warehouse_label,
                "subject": subject,
                "message": summary_message,
                "link_url": "/absen/#tutup-kasir",
            },
        )
        deliveries = wa_result.get("deliveries") or []
        delivery_count = len(deliveries)
        success_count = sum(1 for item in deliveries if item.get("ok"))
        error_messages = []
        for item in deliveries:
            error_text = str(item.get("error") or "").strip()
            if error_text and error_text not in error_messages:
                error_messages.append(error_text)
        wa_error = " | ".join(error_messages)
        if delivery_count <= 0:
            wa_status = "skipped"
        elif success_count >= delivery_count:
            wa_status = "sent"
        elif success_count > 0:
            wa_status = "partial"
        else:
            wa_status = "failed"
    except Exception as exc:
        wa_status = "failed"
        wa_error = str(exc).strip()

    db.execute(
        """
        UPDATE cash_closing_reports
        SET wa_status=?,
            wa_error=?,
            wa_delivery_count=?,
            wa_success_count=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            wa_status,
            wa_error,
            delivery_count,
            success_count,
            report_id,
        ),
    )
    db.commit()

    if wa_status == "sent":
        flash("Tutup kasir tersimpan dan WA leader berhasil dikirim.", "success")
    elif wa_status == "partial":
        flash("Tutup kasir tersimpan, tapi WA leader hanya terkirim sebagian.", "warning")
    elif wa_status == "failed":
        flash("Tutup kasir tersimpan, tapi kirim WA leader gagal. Cek nomor atau gateway WA.", "error")
    else:
        flash("Tutup kasir tersimpan. Belum ada leader tujuan yang menerima WA untuk gudang ini.", "warning")
    return redirect("/absen/#tutup-kasir")


@attendance_portal_bp.route("/log/<int:biometric_id>/edit", methods=["POST"])
def edit_punch_log(biometric_id):
    db = get_db()
    if not _can_correct_attendance_portal_logs():
        flash("Perbaikan log absensi hanya bisa dilakukan oleh HR atau Super Admin.", "error")
        return redirect("/absen/#riwayat-absen")

    linked_employee = _get_self_service_employee(db)
    if linked_employee is None:
        flash("Akun ini belum ditautkan ke data karyawan. Hubungkan dulu dari halaman Admin.", "error")
        return redirect("/absen/")
    linked_employee = dict(linked_employee)

    biometric = db.execute(
        """
        SELECT id, employee_id, warehouse_id, punch_time, punch_type, sync_status, note
        FROM biometric_logs
        WHERE id=? AND employee_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (biometric_id, linked_employee["id"]),
    ).fetchone()
    if not biometric:
        flash("Log absensi tidak ditemukan untuk akun ini.", "error")
        return redirect("/absen/#riwayat-absen")
    biometric = dict(biometric)

    if (biometric.get("punch_type") or "").strip().lower() != "check_out":
        flash("Yang bisa dikoreksi dari portal ini hanya log terakhir yang sempat tercatat sebagai check out.", "error")
        return redirect("/absen/#riwayat-absen")

    updated_punch_time = _normalize_datetime_input(request.form.get("punch_time"))
    if not updated_punch_time:
        flash("Jam log baru wajib diisi dengan format waktu yang valid.", "error")
        return redirect("/absen/#riwayat-absen")

    requested_punch_type = (request.form.get("punch_type") or "").strip().lower()
    updated_punch_type = (
        requested_punch_type
        if requested_punch_type in ATTENDANCE_PORTAL_CORRECTABLE_PUNCH_TYPES
        else "check_out"
    )

    original_attendance_date = (biometric.get("punch_time") or "")[:10]
    updated_attendance_date = updated_punch_time[:10]
    if not original_attendance_date or updated_attendance_date != original_attendance_date:
        flash("Tanggal log tidak boleh pindah hari. Ubah jamnya saja pada tanggal yang sama.", "error")
        return redirect("/absen/#riwayat-absen")

    other_day_logs = [
        dict(row)
        for row in db.execute(
            """
            SELECT id, punch_time, punch_type
            FROM biometric_logs
            WHERE employee_id=?
              AND warehouse_id=?
              AND substr(punch_time, 1, 10)=?
              AND id<>?
              AND sync_status IN (?,?)
            ORDER BY punch_time ASC, id ASC
            """,
            (
                linked_employee["id"],
                biometric["warehouse_id"],
                original_attendance_date,
                biometric_id,
                "synced",
                "manual",
            ),
        ).fetchall()
    ]
    latest_other_log = db.execute(
        """
        SELECT punch_time
        FROM biometric_logs
        WHERE employee_id=?
          AND warehouse_id=?
          AND substr(punch_time, 1, 10)=?
          AND id<>?
          AND sync_status IN (?,?)
        ORDER BY punch_time DESC, id DESC
        LIMIT 1
        """,
        (
            linked_employee["id"],
            biometric["warehouse_id"],
            original_attendance_date,
            biometric_id,
            "synced",
            "manual",
        ),
    ).fetchone()
    if latest_other_log and updated_punch_time <= latest_other_log["punch_time"]:
        flash("Jam log baru harus lebih akhir dari log absen terakhir lain di hari itu.", "error")
        return redirect("/absen/#riwayat-absen")

    if updated_punch_type == "break_start" and _has_open_break(other_day_logs):
        flash("Tidak bisa mengubah jadi istirahat mulai karena hari itu sudah ada sesi istirahat yang masih terbuka.", "error")
        return redirect("/absen/#riwayat-absen")

    duplicate = db.execute(
        """
        SELECT id
        FROM biometric_logs
        WHERE employee_id=? AND punch_time=? AND punch_type=? AND id<>?
        """,
        (linked_employee["id"], updated_punch_time, updated_punch_type, biometric_id),
    ).fetchone()
    if duplicate:
        flash("Sudah ada log absensi lain dengan waktu dan tipe yang sama.", "error")
        return redirect("/absen/#riwayat-absen")

    correction_note = (request.form.get("note") or "").strip()
    correction_marker = "Koreksi log portal:"
    base_note = (biometric.get("note") or "").strip()
    if f" | {correction_marker}" in base_note:
        base_note = base_note.split(f" | {correction_marker}", 1)[0].strip()
    elif base_note.startswith(correction_marker):
        base_note = ""
    corrected_label = _get_attendance_punch_label(updated_punch_type)
    final_correction_note = correction_note or (
        f"Diubah menjadi {corrected_label} pada {updated_punch_time[11:16]}"
    )
    updated_note = " | ".join(
        part
        for part in [
            base_note,
            f"{correction_marker} {final_correction_note}",
        ]
        if part
    )

    handled_by, handled_at = _build_biometric_handling("manual")
    db.execute(
        """
        UPDATE biometric_logs
        SET punch_time=?,
            punch_type=?,
            sync_status=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            updated_punch_time,
            updated_punch_type,
            "manual",
            updated_note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            biometric_id,
        ),
    )
    _resync_attendance_from_biometrics(
        db,
        linked_employee["id"],
        biometric["warehouse_id"],
        original_attendance_date,
    )
    db.commit()

    try:
        employee_label = (linked_employee.get("full_name") or session.get("username") or "Karyawan").strip()
        warehouse_label = (linked_employee.get("warehouse_name") or "Gudang").strip()
        attendance_policy = get_event_notification_policy("attendance.activity")
        notify_operational_event(
            f"Koreksi Log Absen: {employee_label}",
            f"{employee_label} memperbarui log terakhir menjadi {corrected_label} pada {updated_punch_time[11:16]} di {warehouse_label} untuk tanggal {original_attendance_date}.",
            warehouse_id=linked_employee["warehouse_id"],
            include_actor=False,
            exclude_user_ids=[session.get("user_id")],
            category="attendance",
            link_url="/absen/#riwayat-absen",
            recipient_roles=attendance_policy["roles"],
            recipient_usernames=attendance_policy["usernames"],
            recipient_user_ids=attendance_policy["user_ids"],
            source_type="biometric_log",
            source_id=str(biometric_id),
            push_title="Koreksi Log Absen",
            push_body=f"{employee_label} | {corrected_label} | {updated_punch_time[11:16]}",
        )
    except Exception as exc:
        print("ATTENDANCE LOG EDIT NOTIFICATION ERROR:", exc)

    flash("Log absensi berhasil diperbarui.", "success")
    return redirect("/absen/#riwayat-absen")
