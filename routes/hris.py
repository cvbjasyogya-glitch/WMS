import base64
import binascii
import json
import os
import re
import sqlite3
from collections import defaultdict
from datetime import date as date_cls, datetime, timedelta
from uuid import uuid4

from flask import Blueprint, current_app, render_template, request, redirect, flash, session, url_for
from werkzeug.utils import secure_filename

from database import get_db, is_postgresql_backend
from routes.schedule import (
    LIVE_SCHEDULE_SLOTS,
    _build_board_rows as _build_schedule_board_rows,
    _build_day_notes as _build_schedule_day_notes,
    _daterange as _schedule_daterange,
    _build_entry_map as _build_schedule_entry_map,
    _build_override_map as _build_schedule_override_map,
    _build_schedule_members as _build_schedule_members,
    _fetch_employees_for_schedule as _fetch_schedule_employees,
    _fetch_shift_codes as _fetch_schedule_shift_codes,
    _seed_default_shift_codes as _seed_schedule_shift_codes,
    _validate_shift_swap_schedule as _validate_schedule_shift_swap_snapshot,
    resolve_employee_schedule_for_date,
)
from services.hris_catalog import (
    can_manage_hris_module,
    get_hris_module,
    get_hris_modules,
    is_self_service_hris_module,
    role_has_hris_access,
)
from services.announcement_center import (
    build_announcement_notification_payload,
    build_schedule_change_notification_payload,
    create_schedule_change_event,
    format_date_range,
)
from services.attendance_request_service import (
    build_attendance_request_summary,
    can_manage_attendance_request_approvals,
    fetch_attendance_requests,
    get_attendance_request_type_label,
    parse_attendance_request_payload,
    queue_attendance_request,
    split_attendance_requests,
)
from services.event_notification_policy import get_event_notification_policy
from services.kpi_catalog import (
    KPI_REPORT_STATUS_LABELS,
    KPI_REPORT_STATUSES,
    KPI_WEEK_OPTIONS,
    build_kpi_metric_entries,
    format_kpi_period_label,
    get_current_kpi_week_key,
    get_kpi_profiles,
    normalize_kpi_period_label,
    normalize_kpi_report_status,
    normalize_kpi_week_key,
    resolve_kpi_profile,
    summarize_kpi_metric_entries,
)
from services.notification_service import notify_broadcast, notify_operational_event, notify_user
from services.rbac import has_permission, is_scoped_role, normalize_role
from services.whatsapp_service import send_role_based_notification


hris_bp = Blueprint("hris", __name__, url_prefix="/hris")

EMPLOYEE_STATUSES = {"active", "probation", "leave", "inactive"}
ATTENDANCE_STATUSES = {"present", "late", "leave", "absent", "half_day"}
LEAVE_TYPES = {"annual", "sick", "permit", "unpaid", "special"}
LEAVE_STATUSES = {"pending", "approved", "rejected", "cancelled"}
LEAVE_TYPE_LABELS = {
    "annual": "Cuti Tahunan",
    "sick": "Sakit",
    "permit": "Izin",
    "unpaid": "Cuti Tanpa Bayar",
    "special": "Cuti Khusus",
}
LEAVE_ENTRY_TYPES = ("special", "unpaid")
LEAVE_ENTRY_TYPE_LABELS = {
    "special": "Cuti Khusus",
    "unpaid": "Cuti Tanpa Bayar",
}
SPECIAL_LEAVE_REASON_OPTIONS = {
    "annual": "Cuti Tahunan",
    "sick": "Sakit",
    "permit": "Izin / Urgent",
    "family": "Keperluan Keluarga",
    "other": "Lainnya",
}
LEGACY_LEAVE_TYPE_TO_SPECIAL_REASON = {
    "annual": "annual",
    "sick": "sick",
    "permit": "permit",
}
SPECIAL_LEAVE_REASON_PREFIX = "[special_reason:"
PAYROLL_STATUSES = {"draft", "approved", "paid", "cancelled"}
RECRUITMENT_STAGES = {"applied", "screening", "interview", "offer", "hired"}
RECRUITMENT_STATUSES = {"active", "on_hold", "rejected", "withdrawn", "closed"}
ONBOARDING_STAGES = {"preboarding", "orientation", "system_access", "training", "go_live"}
ONBOARDING_STATUSES = {"pending", "in_progress", "completed", "blocked"}
OFFBOARDING_STAGES = {"notice", "clearance", "handover", "exit_complete"}
OFFBOARDING_STATUSES = {"planned", "in_progress", "completed", "cancelled"}
PERFORMANCE_STATUSES = {"draft", "reviewed", "acknowledged", "closed"}
HELPDESK_CATEGORIES = {"system", "access", "attendance", "payroll", "asset", "other"}
HELPDESK_PRIORITIES = {"low", "medium", "high", "urgent"}
HELPDESK_STATUSES = {"open", "in_progress", "resolved", "closed"}
ASSET_STATUSES = {"allocated", "standby", "maintenance", "returned"}
ASSET_CONDITIONS = {"good", "fair", "damaged"}
PROJECT_PRIORITIES = {"low", "medium", "high", "critical"}
PROJECT_STATUSES = {"planning", "active", "on_hold", "completed", "cancelled"}
BIOMETRIC_PUNCH_TYPES = {"check_in", "free_attendance", "break_start", "break_finish", "check_out"}
BIOMETRIC_SYNC_STATUSES = {"queued", "synced", "failed", "manual"}
BIOMETRIC_PHOTO_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
BIOMETRIC_STATUS_LABELS = {
    "queued": "Perlu Review",
    "synced": "Terverifikasi",
    "manual": "Manual Override",
    "failed": "Flagged",
}
ATTENDANCE_STATUS_LABELS = {
    "present": "Present",
    "late": "Late",
    "leave": "Leave",
    "absent": "Absent",
    "half_day": "Half Day",
}
BREAK_STATUS_LABELS = {
    "break_not_started": "Belum",
    "break_started": "Baru Mulai",
    "break_finished": "Selesai",
    "break_over_limit": "Istirahat > 1 Jam",
}
ANNOUNCEMENT_AUDIENCES = {"all", "leaders", "warehouse_team"}
ANNOUNCEMENT_STATUSES = {"draft", "published", "archived"}
DOCUMENT_TYPES = {"policy", "sop", "form", "memo", "contract", "other"}
DOCUMENT_STATUSES = {"draft", "active", "archived"}
DOCUMENT_ATTACHMENT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
DAILY_LIVE_REPORT_TYPES = {"daily", "live"}
DAILY_LIVE_REPORT_STATUSES = {"submitted", "reviewed", "follow_up", "closed"}
DAILY_LIVE_REPORT_TYPE_LABELS = {
    "daily": "Harian",
    "live": "Live",
}
DAILY_LIVE_REPORT_STATUS_LABELS = {
    "submitted": "Menunggu Review",
    "reviewed": "Reviewed",
    "follow_up": "Perlu Follow Up",
    "closed": "Closed",
}
DAILY_LIVE_REPORT_ATTACHMENT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
DAILY_LIVE_REPORT_ACTIVE_STATUSES = ("submitted", "follow_up")
DAILY_LIVE_REPORT_ARCHIVE_STATUSES = ("reviewed", "closed")
DASHBOARD_REMINDER_STATUSES = {"open", "done"}
DASHBOARD_REMINDER_STATUS_LABELS = {
    "open": "Aktif",
    "done": "Selesai",
}
DASHBOARD_LEAVE_ALERT_LIMIT = 8
DASHBOARD_REMINDER_LIMIT = 10
BIOMETRIC_MANUAL_STATUS_ROLES = {"hr", "super_admin"}
BIOMETRIC_ADJUSTABLE_ATTENDANCE_STATUSES = {"present", "late"}
LIVE_SCHEDULE_SLOT_LABELS = dict(LIVE_SCHEDULE_SLOTS)
BIOMETRIC_SHIFT_SCHEDULES = {
    "mataram": {
        "pagi": {"label": "Shift Pagi", "start": "08:00", "end": "16:00"},
        "siang": {"label": "Shift Siang", "start": "13:00", "end": "21:00"},
    },
    "mega": {
        "pagi": {"label": "Shift Pagi", "start": "09:00", "end": "17:00"},
        "siang": {"label": "Shift Siang", "start": "13:00", "end": "21:00"},
    },
}
BIOMETRIC_SPECIAL_SHIFT_RULES = (
    {
        "shift_code": "bu_ika",
        "label": "Shift Khusus Bu Ika",
        "start": "11:30",
        "end": "21:00",
        "aliases": ("bu ika", "ibu ika", "ika"),
    },
)

GEO_ATTENDANCE_NOTE = "Synced from geotag"
DASHBOARD_SCHEDULE_DAY_OPTIONS = {7, 14, 21}
DASHBOARD_SCHEDULE_PREVIEW_LIMIT = 8
DASHBOARD_ANNOUNCEMENT_LIMIT = 6
OVERTIME_USAGE_HISTORY_LIMIT = 12
OVERTIME_BALANCE_CAP_MINUTES = 4 * 60
OVERTIME_WEEKLY_USAGE_LIMIT_MINUTES = 2 * 60


def _to_int(value, default=None):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _parse_iso_date(value):
    if not value:
        return None

    try:
        return date_cls.fromisoformat(value)
    except ValueError:
        return None


def _safe_hris_return_to(default="/hris/"):
    target = (request.form.get("return_to") or "").strip()
    if target.startswith("/hris"):
        return target
    return default


def _get_table_columns(db, table_name):
    safe_name = (table_name or "").strip()
    if not safe_name:
        return set()

    try:
        rows = db.execute(f"PRAGMA table_info({safe_name})").fetchall()
    except Exception:
        return set()

    columns = set()
    for row in rows:
        try:
            columns.add(row["name"])
        except Exception:
            if isinstance(row, (list, tuple)) and len(row) > 1:
                columns.add(row[1])
    return columns


def _ensure_postgresql_id_sequence(db, table_name):
    default_row = db.execute(
        """
        SELECT column_default
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name=?
          AND column_name='id'
        """,
        (table_name,),
    ).fetchone()
    try:
        column_default = str(default_row["column_default"] or "").lower()
    except Exception:
        column_default = ""
    if "nextval(" in column_default:
        return

    sequence_name = f"{table_name}_id_seq"
    db.execute(f"CREATE SEQUENCE IF NOT EXISTS {sequence_name}")
    db.execute(f"ALTER SEQUENCE {sequence_name} OWNED BY {table_name}.id")
    db.execute(
        f"ALTER TABLE {table_name} ALTER COLUMN id SET DEFAULT nextval('{sequence_name}')"
    )
    db.execute(
        f"SELECT setval('{sequence_name}', COALESCE((SELECT MAX(id) FROM {table_name}), 0) + 1, false)"
    )


def _ensure_overtime_feature_schema(db):
    runtime_state = current_app.extensions.setdefault("hris_overtime_runtime_state", {})
    backend = "postgresql" if is_postgresql_backend(current_app.config) else "sqlite"
    cache_key = f"schema_ready:{backend}"
    if runtime_state.get(cache_key):
        return

    if backend == "postgresql":
        statements = [
            """
            CREATE TABLE IF NOT EXISTS attendance_action_requests(
                id SERIAL PRIMARY KEY,
                request_type TEXT,
                warehouse_id INTEGER,
                employee_id INTEGER,
                summary_title TEXT,
                summary_note TEXT,
                payload TEXT,
                status TEXT DEFAULT 'pending',
                requested_by INTEGER,
                handled_by INTEGER,
                handled_at TIMESTAMP,
                decision_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS overtime_balance_adjustments(
                id SERIAL PRIMARY KEY,
                employee_id INTEGER,
                warehouse_id INTEGER,
                adjustment_date TEXT,
                minutes_delta INTEGER DEFAULT 0,
                note TEXT,
                handled_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS overtime_usage_records(
                id SERIAL PRIMARY KEY,
                employee_id INTEGER,
                warehouse_id INTEGER,
                usage_date TEXT,
                usage_mode TEXT DEFAULT 'regular',
                minutes_used INTEGER DEFAULT 0,
                note TEXT,
                handled_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS request_type TEXT",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS warehouse_id INTEGER",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS employee_id INTEGER",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS summary_title TEXT",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS summary_note TEXT",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS payload TEXT",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS requested_by INTEGER",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS handled_by INTEGER",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS handled_at TIMESTAMP",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS decision_note TEXT",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS employee_id INTEGER",
            "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS warehouse_id INTEGER",
            "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS adjustment_date TEXT",
            "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS minutes_delta INTEGER DEFAULT 0",
            "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS note TEXT",
            "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS handled_by INTEGER",
            "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS employee_id INTEGER",
            "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS warehouse_id INTEGER",
            "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS usage_date TEXT",
            "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS usage_mode TEXT DEFAULT 'regular'",
            "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS minutes_used INTEGER DEFAULT 0",
            "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS note TEXT",
            "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS handled_by INTEGER",
            "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "CREATE INDEX IF NOT EXISTS idx_overtime_usage_main ON overtime_usage_records(warehouse_id, usage_date, employee_id)",
            "CREATE INDEX IF NOT EXISTS idx_overtime_balance_adjustments_main ON overtime_balance_adjustments(warehouse_id, adjustment_date, employee_id)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_action_requests_main ON attendance_action_requests(status, warehouse_id, request_type, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_action_requests_employee ON attendance_action_requests(employee_id, status, created_at)",
        ]
        for statement in statements:
            db.execute(statement)
        for table_name in (
            "attendance_action_requests",
            "overtime_balance_adjustments",
            "overtime_usage_records",
        ):
            _ensure_postgresql_id_sequence(db, table_name)
    else:
        usage_columns = _get_table_columns(db, "overtime_usage_records")
        if usage_columns and "usage_mode" not in usage_columns:
            db.execute(
                "ALTER TABLE overtime_usage_records ADD COLUMN usage_mode TEXT DEFAULT 'regular'"
            )

    runtime_state[cache_key] = True


def can_view_hris_records(module_slug=None):
    role = session.get("role")
    if module_slug:
        return get_hris_module(module_slug, role=role) is not None
    return role_has_hris_access(role)


def can_manage_hris_records(module_slug=None):
    role = session.get("role")
    if module_slug:
        return can_manage_hris_module(role, module_slug)
    return any(module["can_manage"] for module in get_hris_modules(role))


def can_manage_employee_records():
    return can_manage_hris_records("employee")


def can_manage_attendance_records():
    return can_manage_hris_records("attendance")


def can_manage_leave_records():
    return can_manage_hris_records("leave")


def can_manage_approval_records():
    return can_manage_hris_records("approval")


def can_manage_payroll_records():
    return can_manage_hris_records("payroll")


def can_manage_recruitment_records():
    return can_manage_hris_records("recruitment")


def can_manage_onboarding_records():
    return can_manage_hris_records("onboarding")


def can_manage_offboarding_records():
    return can_manage_hris_records("offboarding")


def can_manage_performance_records():
    return can_manage_hris_records("pms")


def can_manage_helpdesk_records():
    return can_manage_hris_records("helpdesk")


def can_manage_asset_records():
    return can_manage_hris_records("asset")


def can_manage_project_records():
    return can_manage_hris_records("project")


def can_manage_biometric_records():
    return can_manage_hris_records("biometric")


def can_adjust_biometric_attendance_status():
    return normalize_role(session.get("role")) in BIOMETRIC_MANUAL_STATUS_ROLES


def can_manage_announcement_records():
    return can_manage_hris_records("announcement")


def can_manage_document_records():
    return can_manage_hris_records("documents")


def can_manage_dashboard_reminders():
    return session.get("role") == "hr"


def is_self_service_module(module_slug):
    return is_self_service_hris_module(session.get("role"), module_slug)


def _portal_redirect_for_module(module_slug):
    if module_slug == "leave":
        return redirect("/libur/")
    if module_slug == "biometric":
        return redirect("/absen/")
    return None


def _hris_access_denied_redirect():
    if has_permission(session.get("role"), "view_schedule"):
        return redirect("/schedule/")
    return redirect("/")


def get_hris_scope():
    if is_scoped_role(session.get("role")):
        return session.get("warehouse_id")
    return None


def _normalize_status(value):
    status = (value or "").strip().lower()
    return status if status in EMPLOYEE_STATUSES else "active"


def _normalize_attendance_status(value):
    status = (value or "").strip().lower()
    return status if status in ATTENDANCE_STATUSES else "present"


def _normalize_leave_type(value):
    leave_type = (value or "").strip().lower()
    return leave_type if leave_type in LEAVE_TYPES else "annual"


def _normalize_leave_entry_type(value):
    leave_type = (value or "").strip().lower()
    return "unpaid" if leave_type == "unpaid" else "special"


def _normalize_special_leave_reason(value):
    reason_code = (value or "").strip().lower()
    return reason_code if reason_code in SPECIAL_LEAVE_REASON_OPTIONS else "other"


def _strip_special_leave_reason_prefix(value):
    text = str(value or "").strip()
    if not text.startswith(SPECIAL_LEAVE_REASON_PREFIX):
        return text
    closing = text.find("]")
    if closing == -1:
        return text
    return text[closing + 1 :].strip()


def _extract_special_leave_reason_code(leave_type, reason_text):
    normalized_leave_type = (leave_type or "").strip().lower()
    if normalized_leave_type in LEGACY_LEAVE_TYPE_TO_SPECIAL_REASON:
        return LEGACY_LEAVE_TYPE_TO_SPECIAL_REASON[normalized_leave_type]
    if normalized_leave_type != "special":
        return ""

    text = str(reason_text or "").strip()
    if text.startswith(SPECIAL_LEAVE_REASON_PREFIX):
        closing = text.find("]")
        if closing != -1:
            return _normalize_special_leave_reason(
                text[len(SPECIAL_LEAVE_REASON_PREFIX) : closing]
            )
    return "other" if text else ""


def _compose_leave_reason_text(leave_type, special_leave_reason, reason_text):
    clean_reason = _strip_special_leave_reason_prefix(reason_text)
    if leave_type != "special":
        return clean_reason
    special_reason_code = _normalize_special_leave_reason(special_leave_reason)
    if clean_reason:
        return f"{SPECIAL_LEAVE_REASON_PREFIX}{special_reason_code}] {clean_reason}"
    return f"{SPECIAL_LEAVE_REASON_PREFIX}{special_reason_code}]"


def _build_leave_display_labels(leave_type, reason_text):
    normalized_leave_type = (leave_type or "").strip().lower()
    if normalized_leave_type == "unpaid":
        return LEAVE_ENTRY_TYPE_LABELS["unpaid"], ""
    if normalized_leave_type in LEGACY_LEAVE_TYPE_TO_SPECIAL_REASON or normalized_leave_type == "special":
        reason_code = _extract_special_leave_reason_code(normalized_leave_type, reason_text)
        return LEAVE_ENTRY_TYPE_LABELS["special"], SPECIAL_LEAVE_REASON_OPTIONS.get(reason_code, "")
    return LEAVE_TYPE_LABELS.get(normalized_leave_type, "Libur"), ""


def _decorate_leave_record(record):
    record = dict(record)
    leave_type_label, leave_type_detail_label = _build_leave_display_labels(
        record.get("leave_type"),
        record.get("reason"),
    )
    record["leave_type_label"] = leave_type_label
    record["leave_type_detail_label"] = leave_type_detail_label
    record["special_leave_reason_code"] = _extract_special_leave_reason_code(
        record.get("leave_type"),
        record.get("reason"),
    )
    record["special_leave_reason_label"] = SPECIAL_LEAVE_REASON_OPTIONS.get(
        record["special_leave_reason_code"],
        "",
    )
    record["reason_display"] = _strip_special_leave_reason_prefix(record.get("reason")) or "-"
    return record


def _resolve_leave_submission_payload(leave_type_value, special_leave_reason_value, reason_value):
    original_leave_type = (leave_type_value or "").strip().lower()
    leave_type = _normalize_leave_entry_type(original_leave_type)
    special_leave_reason = ""
    if leave_type == "special":
        special_leave_reason = _normalize_special_leave_reason(
            special_leave_reason_value or LEGACY_LEAVE_TYPE_TO_SPECIAL_REASON.get(original_leave_type)
        )
    reason = _compose_leave_reason_text(leave_type, special_leave_reason, reason_value)
    return leave_type, special_leave_reason, reason


def _normalize_leave_status(value):
    status = (value or "").strip().lower()
    return status if status in LEAVE_STATUSES else "pending"


def _normalize_payroll_status(value):
    status = (value or "").strip().lower()
    return status if status in PAYROLL_STATUSES else "draft"


def _normalize_recruitment_stage(value):
    stage = (value or "").strip().lower()
    return stage if stage in RECRUITMENT_STAGES else "applied"


def _normalize_recruitment_status(value):
    status = (value or "").strip().lower()
    return status if status in RECRUITMENT_STATUSES else "active"


def _normalize_onboarding_stage(value):
    stage = (value or "").strip().lower()
    return stage if stage in ONBOARDING_STAGES else "preboarding"


def _normalize_onboarding_status(value):
    status = (value or "").strip().lower()
    return status if status in ONBOARDING_STATUSES else "pending"


def _normalize_offboarding_stage(value):
    stage = (value or "").strip().lower()
    return stage if stage in OFFBOARDING_STAGES else "notice"


def _normalize_offboarding_status(value):
    status = (value or "").strip().lower()
    return status if status in OFFBOARDING_STATUSES else "planned"


def _normalize_performance_status(value):
    status = (value or "").strip().lower()
    return status if status in PERFORMANCE_STATUSES else "draft"


def _normalize_helpdesk_category(value):
    category = (value or "").strip().lower()
    return category if category in HELPDESK_CATEGORIES else "other"


def _normalize_helpdesk_priority(value):
    priority = (value or "").strip().lower()
    return priority if priority in HELPDESK_PRIORITIES else "medium"


def _normalize_helpdesk_status(value):
    status = (value or "").strip().lower()
    return status if status in HELPDESK_STATUSES else "open"


def _normalize_asset_status(value):
    status = (value or "").strip().lower()
    return status if status in ASSET_STATUSES else "allocated"


def _normalize_asset_condition(value):
    condition = (value or "").strip().lower()
    return condition if condition in ASSET_CONDITIONS else "good"


def _normalize_project_priority(value):
    priority = (value or "").strip().lower()
    return priority if priority in PROJECT_PRIORITIES else "medium"


def _normalize_project_status(value):
    status = (value or "").strip().lower()
    return status if status in PROJECT_STATUSES else "planning"


def _normalize_biometric_punch_type(value):
    punch_type = (value or "").strip().lower()
    return punch_type if punch_type in BIOMETRIC_PUNCH_TYPES else "check_in"


def _normalize_biometric_sync_status(value):
    status = (value or "").strip().lower()
    return status if status in BIOMETRIC_SYNC_STATUSES else "queued"


def _normalize_latitude(value):
    latitude = _to_float(value, default=None)
    if latitude is None or latitude < -90 or latitude > 90:
        return None
    return round(latitude, 6)


def _normalize_longitude(value):
    longitude = _to_float(value, default=None)
    if longitude is None or longitude < -180 or longitude > 180:
        return None
    return round(longitude, 6)


def _normalize_accuracy(value):
    accuracy = _to_float(value, default=None)
    if accuracy is None or accuracy < 0:
        return None
    return round(accuracy, 2)


_COORDINATE_LOCATION_PATTERN = re.compile(
    r"^\s*(?:lat(?:itude)?\s*[:=]?\s*)?(-?\d{1,3}(?:\.\d+)?)\s*[,;/|]\s*(?:lon(?:gitude)?|lng)?\s*[:=]?\s*(-?\d{1,3}(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)


def _normalize_biometric_location_text(value):
    return " ".join(str(value or "").replace("|", " | ").split()).strip(" |-")


def _looks_like_coordinate_location_label(value):
    safe_value = _normalize_biometric_location_text(value)
    if not safe_value:
        return False

    match = _COORDINATE_LOCATION_PATTERN.match(safe_value)
    if not match:
        return False

    latitude = _normalize_latitude(match.group(1))
    longitude = _normalize_longitude(match.group(2))
    return latitude is not None and longitude is not None


def _normalize_biometric_location_label(value, fallback_label=""):
    safe_value = _normalize_biometric_location_text(value)
    safe_fallback = _normalize_biometric_location_text(fallback_label)
    if not safe_value:
        return safe_fallback
    if _looks_like_coordinate_location_label(safe_value):
        return safe_fallback
    return safe_value


def _get_biometric_photo_upload_folder():
    upload_folder = current_app.config.get("BIOMETRIC_PHOTO_UPLOAD_FOLDER")
    if not upload_folder:
        upload_folder = os.path.join(current_app.root_path, "static", "uploads", "geotag")
    os.makedirs(upload_folder, exist_ok=True)
    return upload_folder


def _get_biometric_photo_url(photo_path):
    if not photo_path:
        return None

    safe_name = os.path.basename(photo_path)
    if not safe_name:
        return None

    base_prefix = current_app.config.get("BIOMETRIC_PHOTO_URL_PREFIX", "/static/uploads/geotag").rstrip("/")
    return f"{base_prefix}/{safe_name}"


def _delete_biometric_photo(photo_path):
    if not photo_path:
        return

    safe_name = os.path.basename(photo_path)
    if not safe_name:
        return

    file_path = os.path.join(_get_biometric_photo_upload_folder(), safe_name)
    if os.path.exists(file_path):
        os.remove(file_path)


def _save_biometric_photo_data(photo_data_url, existing_photo_path=None):
    raw_data = (photo_data_url or "").strip()
    if not raw_data:
        return existing_photo_path

    if "," not in raw_data or not raw_data.startswith("data:"):
        return None

    header, encoded = raw_data.split(",", 1)
    mime_type = header[5:].split(";")[0].strip().lower()
    extension = BIOMETRIC_PHOTO_MIME_TYPES.get(mime_type)
    if not extension:
        return None

    try:
        binary = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None

    if not binary or len(binary) > 5 * 1024 * 1024:
        return None

    file_name = f"geotag_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}{extension}"
    file_path = os.path.join(_get_biometric_photo_upload_folder(), file_name)
    with open(file_path, "wb") as file_handle:
        file_handle.write(binary)

    if existing_photo_path and os.path.basename(existing_photo_path) != file_name:
        _delete_biometric_photo(existing_photo_path)

    return file_name


def _normalize_announcement_audience(value):
    audience = (value or "").strip().lower()
    return audience if audience in ANNOUNCEMENT_AUDIENCES else "all"


def _normalize_announcement_status(value):
    status = (value or "").strip().lower()
    return status if status in ANNOUNCEMENT_STATUSES else "draft"


def _normalize_document_type(value):
    document_type = (value or "").strip().lower()
    return document_type if document_type in DOCUMENT_TYPES else "other"


def _normalize_document_status(value):
    status = (value or "").strip().lower()
    return status if status in DOCUMENT_STATUSES else "draft"


def _get_linked_employee_id():
    return _to_int(session.get("employee_id"))


def _calculate_leave_days(start_date, end_date):
    if not start_date or not end_date:
        return None

    try:
        start_value = date_cls.fromisoformat(start_date)
        end_value = date_cls.fromisoformat(end_date)
    except ValueError:
        return None

    if end_value < start_value:
        return None

    return (end_value - start_value).days + 1


def _current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _format_hris_datetime_display(raw_value, include_date=False):
    if raw_value is None:
        return "-"
    if isinstance(raw_value, datetime):
        parsed = raw_value
    else:
        safe_value = str(raw_value or "").strip()
        if not safe_value:
            return "-"
        normalized = safe_value.replace("T", " ")[:19]
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return safe_value
    return parsed.strftime("%d/%m/%Y %H:%M" if include_date else "%H:%M")


def _normalize_datetime_input(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    raw_value = str(value or "").strip()
    if not raw_value:
        return None

    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", ""))
    except ValueError:
        return None

    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def _normalize_time_of_day_input(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%H:%M")
    safe_value = str(value or "").strip()
    if not safe_value:
        return None
    try:
        parsed = datetime.strptime(safe_value, "%H:%M")
    except ValueError:
        return None
    return parsed.strftime("%H:%M")


def _build_leave_handling(status):
    if status == "pending":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_leave_notification_range_label(start_date, end_date):
    start_value = str(start_date or "").strip()
    end_value = str(end_date or "").strip()
    if start_value and end_value and start_value != end_value:
        return f"{start_value} s/d {end_value}"
    return start_value or end_value or "-"


def _notify_leave_request_status_change(db, leave_request, previous_status=None):
    if not leave_request:
        return

    record = dict(leave_request) if not isinstance(leave_request, dict) else leave_request
    current_status = _normalize_leave_status(record.get("status"))
    prior_status = _normalize_leave_status(previous_status) if previous_status else ""
    if current_status not in {"approved", "rejected"} or current_status == prior_status:
        return

    recipient = db.execute(
        """
        SELECT id
        FROM users
        WHERE employee_id=?
        ORDER BY id ASC
        LIMIT 1
        """,
        (record.get("employee_id"),),
    ).fetchone()
    recipient_id = recipient["id"] if recipient else None

    leave_type_label, leave_type_detail_label = _build_leave_display_labels(
        record.get("leave_type"),
        record.get("reason"),
    )
    leave_type_summary_label = (
        f"{leave_type_label} ({leave_type_detail_label})"
        if leave_type_detail_label
        else leave_type_label
    )
    range_label = _build_leave_notification_range_label(record.get("start_date"), record.get("end_date"))
    total_days = record.get("total_days") or 0
    approver_label = (
        (session.get("username") or "").strip()
        or (record.get("handled_by_name") or "").strip()
        or "HR / Super Admin"
    )
    status_label = "disetujui" if current_status == "approved" else "ditolak"
    status_title = "Disetujui" if current_status == "approved" else "Ditolak"
    event_type = f"leave.status_{'approved' if current_status == 'approved' else 'rejected'}"
    status_message = (
        f"Pengajuan {leave_type_summary_label.lower()} untuk {range_label} "
        f"({total_days} hari) telah {status_label} oleh {approver_label}."
    )
    note_reason = str(record.get("note") or "").strip()

    if recipient_id:
        notify_user(
            recipient_id,
            f"Pengajuan {leave_type_summary_label.lower()} {status_label}",
            status_message,
            category="leave",
            link_url="/libur/",
            source_type="leave_request_status",
            source_id=f"{record.get('id')}:{current_status}",
            dedupe_key=f"leave_request_status:{record.get('id')}:{current_status}",
            push_title=f"Libur {status_title}",
            push_body=f"{leave_type_summary_label} | {range_label}",
        )

    leave_policy = get_event_notification_policy(event_type)
    notify_operational_event(
        f"{leave_type_summary_label} {status_title}: {record.get('employee_name') or 'Karyawan'}",
        status_message,
        warehouse_id=record.get("warehouse_id"),
        include_actor=False,
        exclude_user_ids=[recipient_id] if recipient_id else None,
        recipient_roles=leave_policy["roles"],
        recipient_usernames=leave_policy["usernames"],
        recipient_user_ids=leave_policy["user_ids"],
        category="leave",
        link_url="/libur/",
        source_type="leave_request_status",
        source_id=f"{record.get('id')}:{current_status}",
        dedupe_key=f"leave_request_status:ops:{record.get('id')}:{current_status}",
        push_title=f"{leave_type_summary_label} {status_title}",
        push_body=f"{record.get('employee_name') or 'Karyawan'} | {range_label}",
    )

    send_role_based_notification(
        event_type,
        {
            "warehouse_id": record.get("warehouse_id"),
            "warehouse_name": record.get("warehouse_name") or "Gudang",
            "employee_name": record.get("employee_name") or "Karyawan",
            "leave_type_label": leave_type_summary_label,
            "range_label": range_label,
            "approver_name": approver_label,
            "reason": note_reason,
            "link_url": "/libur/",
            "exclude_user_ids": [recipient_id] if recipient_id else None,
        },
    )


def _build_payroll_handling(status):
    if status == "draft":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_recruitment_handling(status):
    if status == "active":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_onboarding_handling(status):
    if status == "pending":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_offboarding_handling(status):
    if status == "planned":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_performance_handling(status):
    if status == "draft":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_helpdesk_handling(status):
    if status == "open":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_asset_handling(status):
    if status == "standby":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_project_handling(status):
    if status == "planning":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_biometric_handling(status):
    if status == "queued":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_announcement_handling(status):
    if status == "draft":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _build_document_handling(status):
    if status == "draft":
        return None, None
    return session.get("user_id"), _current_timestamp()


def _normalize_daily_live_report_type(value):
    report_type = (value or "").strip().lower()
    return report_type if report_type in DAILY_LIVE_REPORT_TYPES else "daily"


def _normalize_daily_live_report_status(value):
    status = (value or "").strip().lower()
    return status if status in DAILY_LIVE_REPORT_STATUSES else "submitted"


def _format_upload_size(size_bytes):
    try:
        size = max(int(size_bytes or 0), 0)
    except (TypeError, ValueError):
        size = 0

    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _get_daily_live_report_attachment_max_bytes():
    configured = current_app.config.get("DAILY_LIVE_REPORT_ATTACHMENT_MAX_BYTES", 10 * 1024 * 1024)
    try:
        return max(int(configured), 0)
    except (TypeError, ValueError):
        return 10 * 1024 * 1024


def _get_daily_live_report_upload_folder():
    upload_folder = current_app.config.get("DAILY_LIVE_REPORT_UPLOAD_FOLDER")
    if not upload_folder:
        upload_folder = os.path.join(current_app.root_path, "static", "uploads", "daily_reports")
    os.makedirs(upload_folder, exist_ok=True)
    return upload_folder


def _get_daily_live_report_attachment_url(attachment_path):
    if not attachment_path:
        return None
    safe_name = os.path.basename(attachment_path)
    base_url = current_app.config.get("DAILY_LIVE_REPORT_UPLOAD_URL_PREFIX", "/static/uploads/daily_reports").rstrip("/")
    return f"{base_url}/{safe_name}"


def _store_daily_live_report_attachment(file_storage):
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        raise ValueError("File bukti report tidak valid.")

    extension = os.path.splitext(filename)[1].lower()
    if extension not in DAILY_LIVE_REPORT_ATTACHMENT_EXTENSIONS:
        raise ValueError("Lampiran bukti hanya mendukung JPG, PNG, WEBP, atau PDF.")

    upload_folder = _get_daily_live_report_upload_folder()
    stored_name = f"daily_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}{extension}"
    target_path = os.path.join(upload_folder, stored_name)
    file_storage.save(target_path)

    attachment_size = os.path.getsize(target_path)
    max_bytes = _get_daily_live_report_attachment_max_bytes()
    if max_bytes and attachment_size > max_bytes:
        try:
            os.remove(target_path)
        except OSError:
            pass
        raise ValueError(f"Ukuran lampiran maksimal {_format_upload_size(max_bytes)} per file.")

    return {
        "attachment_name": filename,
        "attachment_path": stored_name,
        "attachment_mime": (file_storage.mimetype or "").strip() or None,
        "attachment_size": attachment_size,
    }


def _get_document_attachment_max_bytes():
    configured = current_app.config.get("DOCUMENT_RECORD_ATTACHMENT_MAX_BYTES", 15 * 1024 * 1024)
    try:
        return max(int(configured), 0)
    except (TypeError, ValueError):
        return 15 * 1024 * 1024


def _get_document_signature_max_bytes():
    configured = current_app.config.get("DOCUMENT_RECORD_SIGNATURE_MAX_BYTES", 2 * 1024 * 1024)
    try:
        return max(int(configured), 0)
    except (TypeError, ValueError):
        return 2 * 1024 * 1024


def _get_document_upload_folder():
    upload_folder = current_app.config.get("DOCUMENT_RECORD_UPLOAD_FOLDER")
    if not upload_folder:
        upload_folder = os.path.join(current_app.root_path, "static", "uploads", "documents")
    os.makedirs(upload_folder, exist_ok=True)
    return upload_folder


def _get_document_signature_folder():
    upload_folder = current_app.config.get("DOCUMENT_RECORD_SIGNATURE_FOLDER")
    if not upload_folder:
        upload_folder = os.path.join(current_app.root_path, "static", "uploads", "document_signatures")
    os.makedirs(upload_folder, exist_ok=True)
    return upload_folder


def _get_document_attachment_url(attachment_path):
    if not attachment_path:
        return None
    safe_name = os.path.basename(attachment_path)
    base_url = current_app.config.get("DOCUMENT_RECORD_UPLOAD_URL_PREFIX", "/static/uploads/documents").rstrip("/")
    return f"{base_url}/{safe_name}"


def _get_document_signature_url(signature_path):
    if not signature_path:
        return None
    safe_name = os.path.basename(signature_path)
    base_url = current_app.config.get(
        "DOCUMENT_RECORD_SIGNATURE_URL_PREFIX",
        "/static/uploads/document_signatures",
    ).rstrip("/")
    return f"{base_url}/{safe_name}"


def _remove_document_file(stored_name, *, signature=False):
    if not stored_name:
        return

    safe_name = os.path.basename(stored_name)
    upload_folder = _get_document_signature_folder() if signature else _get_document_upload_folder()
    target_path = os.path.join(upload_folder, safe_name)
    if os.path.isfile(target_path):
        try:
            os.remove(target_path)
        except OSError:
            pass


def _store_document_attachment(file_storage):
    filename = secure_filename(file_storage.filename or "")
    if not filename:
        raise ValueError("File dokumen tidak valid.")

    extension = os.path.splitext(filename)[1].lower()
    if extension not in DOCUMENT_ATTACHMENT_EXTENSIONS:
        raise ValueError("Lampiran dokumen hanya mendukung PDF, JPG, PNG, atau WEBP.")

    upload_folder = _get_document_upload_folder()
    stored_name = f"document_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}{extension}"
    target_path = os.path.join(upload_folder, stored_name)
    file_storage.save(target_path)

    attachment_size = os.path.getsize(target_path)
    max_bytes = _get_document_attachment_max_bytes()
    if max_bytes and attachment_size > max_bytes:
        try:
            os.remove(target_path)
        except OSError:
            pass
        raise ValueError(f"Ukuran lampiran dokumen maksimal {_format_upload_size(max_bytes)} per file.")

    return {
        "attachment_name": filename,
        "attachment_path": stored_name,
        "attachment_mime": (file_storage.mimetype or "").strip() or None,
        "attachment_size": attachment_size,
    }


def _store_document_signature(signature_data):
    raw_value = (signature_data or "").strip()
    if not raw_value:
        raise ValueError("Tanda tangan digital wajib diisi.")

    if "," not in raw_value:
        raise ValueError("Format tanda tangan digital tidak valid.")

    header, encoded = raw_value.split(",", 1)
    if not header.startswith("data:image/") or ";base64" not in header:
        raise ValueError("Format tanda tangan digital tidak valid.")

    mime_type = header[5:].split(";", 1)[0].strip().lower()
    extension = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }.get(mime_type)
    if not extension:
        raise ValueError("Tanda tangan hanya mendukung format PNG, JPG, atau WEBP.")

    try:
        payload = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Data tanda tangan digital rusak atau tidak lengkap.") from exc

    if len(payload) < 32:
        raise ValueError("Tanda tangan digital terlalu pendek. Silakan ulangi tanda tangan.")

    max_bytes = _get_document_signature_max_bytes()
    if max_bytes and len(payload) > max_bytes:
        raise ValueError(f"Ukuran tanda tangan digital maksimal {_format_upload_size(max_bytes)}.")

    upload_folder = _get_document_signature_folder()
    stored_name = f"document_signature_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}{extension}"
    target_path = os.path.join(upload_folder, stored_name)
    with open(target_path, "wb") as file_handle:
        file_handle.write(payload)
    return stored_name


def _decorate_document_record(record):
    item = dict(record)
    item["attachment_url"] = _get_document_attachment_url(item.get("attachment_path"))
    item["signature_url"] = _get_document_signature_url(item.get("signature_path"))
    item["attachment_size_label"] = _format_upload_size(item.get("attachment_size"))
    attachment_source = (item.get("attachment_name") or item.get("attachment_path") or "").lower()
    attachment_mime = (item.get("attachment_mime") or "").strip().lower()
    item["attachment_is_pdf"] = attachment_mime == "application/pdf" or attachment_source.endswith(".pdf")
    item["attachment_is_image"] = attachment_mime.startswith("image/") or attachment_source.endswith(
        (".jpg", ".jpeg", ".png", ".webp")
    )
    item["signature_status_label"] = "Sudah Disahkan" if item.get("signed_at") else "Belum Disahkan"
    return item


def _insert_biometric_log_record(
    db,
    *,
    employee_id,
    warehouse_id,
    device_name,
    device_user_id,
    punch_time,
    punch_type,
    sync_status,
    location_label,
    latitude,
    longitude,
    accuracy_m,
    note=None,
    shift_code=None,
    shift_label=None,
    photo_path=None,
):
    handled_by, handled_at = _build_biometric_handling(sync_status)
    photo_captured_at = _current_timestamp() if photo_path else None
    cursor = db.execute(
        """
        INSERT INTO biometric_logs(
            employee_id,
            warehouse_id,
            device_name,
            device_user_id,
            punch_time,
            punch_type,
            sync_status,
            location_label,
            latitude,
            longitude,
            accuracy_m,
            shift_code,
            shift_label,
            photo_path,
            photo_captured_at,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            warehouse_id,
            device_name,
            device_user_id,
            punch_time,
            punch_type,
            sync_status,
            location_label,
            latitude,
            longitude,
            accuracy_m,
            shift_code,
            shift_label,
            photo_path,
            photo_captured_at,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    _resync_attendance_from_biometrics(db, employee_id, warehouse_id, punch_time[:10])
    return cursor.lastrowid


def _calculate_net_pay(base_salary, allowance, overtime_pay, deduction, leave_deduction):
    return round(base_salary + allowance + overtime_pay - deduction - leave_deduction, 2)


def _calculate_performance_score(goal_score, discipline_score, teamwork_score):
    return round((goal_score + discipline_score + teamwork_score) / 3.0, 2)


def _derive_performance_rating(final_score):
    if final_score >= 90:
        return "excellent"
    if final_score >= 75:
        return "good"
    if final_score >= 60:
        return "fair"
    return "needs_improvement"


def _derive_biometric_attendance_status(check_in_time):
    if not check_in_time:
        return "present"

    try:
        check_in_minutes = int(check_in_time[:2]) * 60 + int(check_in_time[3:5])
    except (TypeError, ValueError, IndexError):
        return "present"

    # Fallback lama tetap dipertahankan bila shift tidak tersedia.
    threshold_minutes = (8 * 60) + 30
    return "late" if check_in_minutes > threshold_minutes else "present"


def _parse_time_of_day_minutes(value):
    safe_value = (value or "").strip()
    if not safe_value:
        return None

    safe_value = safe_value.replace(".", ":")
    try:
        hour_part, minute_part = safe_value.split(":", 1)
        return (int(hour_part) * 60) + int(minute_part[:2])
    except (ValueError, TypeError):
        return None


def _extract_shift_time_range(shift_label):
    safe_label = (shift_label or "").strip()
    if not safe_label:
        return ("", "")

    if "|" in safe_label:
        safe_label = safe_label.split("|", 1)[1].strip()

    if "-" in safe_label:
        start_text, end_text = safe_label.split("-", 1)
        return start_text.strip(), end_text.strip()

    return safe_label, ""


def _extract_shift_start_minutes(shift_label):
    start_text, _ = _extract_shift_time_range(shift_label)
    return _parse_time_of_day_minutes(start_text)


def _extract_shift_end_minutes(shift_label):
    _, end_text = _extract_shift_time_range(shift_label)
    return _parse_time_of_day_minutes(end_text)


def _normalize_shift_identity_text(value):
    cleaned = "".join(
        char.lower() if str(char).isalnum() else " "
        for char in str(value or "").strip()
    )
    return " ".join(cleaned.split())


def _matches_shift_identity_alias(candidate, alias):
    normalized_candidate = _normalize_shift_identity_text(candidate)
    normalized_alias = _normalize_shift_identity_text(alias)
    if not normalized_candidate or not normalized_alias:
        return False
    return (
        normalized_candidate == normalized_alias
        or normalized_candidate.startswith(f"{normalized_alias} ")
    )


def _build_biometric_shift_label(schedule_item):
    if not schedule_item:
        return "-"
    return f"{schedule_item['label']} | {schedule_item['start'].replace(':', '.')} - {schedule_item['end'].replace(':', '.')}"


def _build_biometric_special_shift_option(rule):
    return {
        "value": rule["shift_code"],
        "label": _build_biometric_shift_label(rule),
        "time_label": f"{rule['start'].replace(':', '.')} - {rule['end'].replace(':', '.')}",
        "start": rule["start"],
        "end": rule["end"],
    }


def _normalize_biometric_shift_code(value):
    shift_code = (value or "").strip().lower()
    allowed_shift_codes = {
        str(code or "").strip().lower()
        for schedule_map in BIOMETRIC_SHIFT_SCHEDULES.values()
        for code in schedule_map.keys()
    } | {
        str(rule.get("shift_code") or "").strip().lower()
        for rule in BIOMETRIC_SPECIAL_SHIFT_RULES
        if str(rule.get("shift_code") or "").strip()
    }
    return shift_code if shift_code in allowed_shift_codes else None


def _resolve_biometric_special_shift_rule(source):
    safe_source = (
        dict(source)
        if source is not None and not isinstance(source, dict)
        else (source or {})
    )
    candidate_values = (
        safe_source.get("full_name"),
        safe_source.get("employee_code"),
        safe_source.get("username"),
    )
    for rule in BIOMETRIC_SPECIAL_SHIFT_RULES:
        aliases = rule.get("aliases") or ()
        for candidate in candidate_values:
            if any(_matches_shift_identity_alias(candidate, alias) for alias in aliases):
                return rule
    return None


def _resolve_biometric_shift_warehouse_key(source):
    safe_source = (
        dict(source)
        if source is not None and not isinstance(source, dict)
        else (source or {})
    )
    warehouse_name = str(safe_source.get("warehouse_name") or "").strip().lower()
    if "mega" in warehouse_name:
        return "mega"
    return "mataram"


def _resolve_biometric_shift_profile_key_from_label(shift_label, fallback_key="mataram"):
    safe_label = str(shift_label or "").strip().lower()
    if not safe_label:
        return fallback_key

    for profile_key, schedule_map in BIOMETRIC_SHIFT_SCHEDULES.items():
        for schedule_item in schedule_map.values():
            label = _build_biometric_shift_label(schedule_item).strip().lower()
            time_label = f"{schedule_item['start'].replace(':', '.')} - {schedule_item['end'].replace(':', '.')}".strip().lower()
            if safe_label == label or time_label in safe_label:
                return profile_key

    return fallback_key


def _build_biometric_shift_options(source, current_shift_label=None):
    special_rule = _resolve_biometric_special_shift_rule(source)
    if special_rule:
        return [_build_biometric_special_shift_option(special_rule)]

    fallback_key = _resolve_biometric_shift_warehouse_key(source)
    profile_key = _resolve_biometric_shift_profile_key_from_label(
        current_shift_label,
        fallback_key=fallback_key,
    )
    schedule_map = BIOMETRIC_SHIFT_SCHEDULES.get(
        profile_key,
        BIOMETRIC_SHIFT_SCHEDULES["mataram"],
    )
    return [
        {
            "value": shift_code,
            "label": _build_biometric_shift_label(schedule_item),
            "time_label": f"{schedule_item['start'].replace(':', '.')} - {schedule_item['end'].replace(':', '.')}",
            "start": schedule_item["start"],
            "end": schedule_item["end"],
        }
        for shift_code, schedule_item in schedule_map.items()
    ]


def _resolve_biometric_shift_code_from_label(shift_label, source=None):
    safe_label = str(shift_label or "").strip().lower()
    if not safe_label:
        return None

    for option in _build_biometric_shift_options(source, shift_label):
        option_label = str(option.get("label") or "").strip().lower()
        time_label = str(option.get("time_label") or "").strip().lower()
        if safe_label == option_label or (time_label and time_label in safe_label):
            return option["value"]
    return None


def _derive_biometric_attendance_status_with_shift(check_in_time, shift_label=None):
    if not check_in_time:
        return "present"

    try:
        check_in_minutes = int(check_in_time[:2]) * 60 + int(check_in_time[3:5])
    except (TypeError, ValueError, IndexError):
        return "present"

    shift_start_minutes = _extract_shift_start_minutes(shift_label)
    if shift_start_minutes is None:
        return _derive_biometric_attendance_status(check_in_time)

    return "late" if check_in_minutes > (shift_start_minutes + 10) else "present"


def _resolve_open_break_state(logs_sorted):
    break_summary = _summarize_break_activity(logs_sorted)
    if not break_summary["is_open"]:
        return None

    minutes_open = max(0, int(break_summary["open_seconds"] // 60))
    if minutes_open > 60:
        return {
            "status_key": "break_over_limit",
            "label": BREAK_STATUS_LABELS["break_over_limit"],
            "badge_class": "red",
        }

    return {
        "status_key": "break_started",
        "label": BREAK_STATUS_LABELS["break_started"],
        "badge_class": "orange",
    }


def _parse_biometric_datetime(value):
    safe_value = (value or "").strip()
    if not safe_value:
        return None
    try:
        return datetime.fromisoformat(safe_value)
    except ValueError:
        return None


def _format_break_duration_label(total_seconds, has_break_activity=False):
    total_seconds = int(max(0, total_seconds or 0))
    if total_seconds <= 0:
        return "< 1 mnt" if has_break_activity else "-"

    total_minutes = total_seconds // 60
    if total_minutes <= 0:
        return "< 1 mnt"

    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}j {minutes:02d}m"
    return f"{total_minutes} mnt"


def _format_duration_minutes_label(total_minutes, zero_label="-"):
    safe_minutes = int(max(0, total_minutes or 0))
    if safe_minutes <= 0:
        return zero_label
    return _format_break_duration_label(safe_minutes * 60, has_break_activity=True)


def _employee_allows_automatic_overtime(employee_name):
    safe_name = " ".join(str(employee_name or "").strip().lower().split())
    return bool(safe_name)


def _normalize_overtime_add_source_type(value):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"biometric_auto", "manual_request"} else "manual_request"


def _normalize_overtime_usage_mode(value):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"regular", "cashout_all"} else "regular"


def _get_overtime_usage_mode_label(value):
    normalized = _normalize_overtime_usage_mode(value)
    return "Uangkan Semua Saldo" if normalized == "cashout_all" else "Pakai Jam Lembur"


def _get_overtime_week_range(reference_date=None):
    safe_reference = (
        reference_date
        if isinstance(reference_date, date_cls)
        else _parse_iso_date(reference_date)
        if reference_date
        else date_cls.today()
    )
    safe_reference = safe_reference or date_cls.today()
    week_start = safe_reference - timedelta(days=safe_reference.weekday())
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def _sum_pending_overtime_use_minutes_for_week(db, employee_id, reference_date, exclude_request_id=None):
    safe_employee_id = _to_int(employee_id)
    if not safe_employee_id:
        return 0

    scope_warehouse = get_hris_scope()
    week_start, week_end = _get_overtime_week_range(reference_date)
    query = """
        SELECT id, payload
        FROM attendance_action_requests
        WHERE request_type='overtime_use'
          AND employee_id=?
          AND status='pending'
    """
    params = [safe_employee_id]
    if scope_warehouse:
        query += " AND warehouse_id=?"
        params.append(scope_warehouse)

    total_minutes = 0
    for row in db.execute(query, params).fetchall():
        if exclude_request_id and _to_int(row["id"]) == _to_int(exclude_request_id):
            continue
        payload = parse_attendance_request_payload(row.get("payload"))
        if _normalize_overtime_usage_mode(payload.get("usage_mode")) == "cashout_all":
            continue
        usage_date = _parse_iso_date(payload.get("usage_date"))
        minutes_used = max(0, _to_int(payload.get("minutes_used"), 0) or 0)
        if usage_date is not None and week_start <= usage_date <= week_end:
            total_minutes += minutes_used
    return total_minutes


def _build_weekly_overtime_usage_meta(
    db,
    employee_id,
    reference_date=None,
    *,
    include_pending_requests=False,
    exclude_request_id=None,
    usage_rows=None,
):
    week_start, week_end = _get_overtime_week_range(reference_date)
    safe_usage_rows = usage_rows if usage_rows is not None else _fetch_overtime_usage_records(db, employee_id=employee_id)
    used_minutes = 0
    for row in safe_usage_rows:
        usage_date = _parse_iso_date(row.get("usage_date"))
        if usage_date is None or not (week_start <= usage_date <= week_end):
            continue
        if _normalize_overtime_usage_mode(row.get("usage_mode")) == "cashout_all":
            continue
        used_minutes += max(0, int(row.get("minutes_used") or 0))

    pending_minutes = (
        _sum_pending_overtime_use_minutes_for_week(
            db,
            employee_id,
            week_start,
            exclude_request_id=exclude_request_id,
        )
        if include_pending_requests
        else 0
    )
    total_committed_minutes = used_minutes + pending_minutes
    remaining_minutes = max(0, OVERTIME_WEEKLY_USAGE_LIMIT_MINUTES - total_committed_minutes)
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "week_label": f"{week_start.isoformat()} s/d {week_end.isoformat()}",
        "used_minutes": used_minutes,
        "used_label": _format_duration_minutes_label(used_minutes, zero_label="0 mnt"),
        "pending_minutes": pending_minutes,
        "pending_label": _format_duration_minutes_label(pending_minutes, zero_label="0 mnt"),
        "committed_minutes": total_committed_minutes,
        "committed_label": _format_duration_minutes_label(total_committed_minutes, zero_label="0 mnt"),
        "remaining_minutes": remaining_minutes,
        "remaining_label": _format_duration_minutes_label(remaining_minutes, zero_label="0 mnt"),
        "limit_minutes": OVERTIME_WEEKLY_USAGE_LIMIT_MINUTES,
        "limit_label": _format_duration_minutes_label(OVERTIME_WEEKLY_USAGE_LIMIT_MINUTES),
    }


def _build_overtime_breakdown_label(early_overtime_seconds, late_overtime_seconds):
    segments = []
    if early_overtime_seconds > 0:
        segments.append(
            f"Masuk lebih awal {_format_break_duration_label(early_overtime_seconds, has_break_activity=True)}"
        )
    if late_overtime_seconds > 0:
        segments.append(
            f"Pulang lewat shift {_format_break_duration_label(late_overtime_seconds, has_break_activity=True)}"
        )
    return " + ".join(segments)


def _summarize_overtime_activity(check_in_time, check_out_time, shift_label, minimum_seconds=3600):
    check_in_minutes = _parse_time_of_day_minutes(check_in_time)
    shift_start_minutes = _extract_shift_start_minutes(shift_label)
    early_overtime_seconds = 0
    if (
        check_in_minutes is not None
        and shift_start_minutes is not None
        and check_in_minutes < shift_start_minutes
    ):
        early_overtime_seconds = (shift_start_minutes - check_in_minutes) * 60

    check_out_minutes = _parse_time_of_day_minutes(check_out_time)
    shift_end_minutes = _extract_shift_end_minutes(shift_label)
    late_overtime_seconds = 0
    if (
        check_out_minutes is not None
        and shift_end_minutes is not None
        and check_out_minutes > shift_end_minutes
    ):
        late_overtime_seconds = (check_out_minutes - shift_end_minutes) * 60

    overtime_seconds = early_overtime_seconds + late_overtime_seconds
    qualifies = overtime_seconds >= int(max(0, minimum_seconds or 0))
    breakdown_label = _build_overtime_breakdown_label(early_overtime_seconds, late_overtime_seconds)
    return {
        "qualifies": qualifies,
        "total_seconds": overtime_seconds if qualifies else 0,
        "duration_label": _format_break_duration_label(overtime_seconds, has_break_activity=True) if qualifies else "-",
        "early_seconds": early_overtime_seconds,
        "late_seconds": late_overtime_seconds,
        "breakdown_label": breakdown_label if qualifies else "",
    }


def _is_iso_date_within_range(iso_date, date_from=None, date_to=None):
    safe_date = (iso_date or "").strip()
    if not safe_date:
        return False
    if date_from and safe_date < date_from:
        return False
    if date_to and safe_date > date_to:
        return False
    return True


def _summarize_break_activity(logs_sorted, current_time=None):
    safe_logs = logs_sorted or []
    now_value = current_time or datetime.now()
    completed_seconds = 0
    open_break_started_at = None
    open_break_started_raw = ""
    has_break_activity = False

    for log in safe_logs:
        punch_type = (log.get("punch_type") or "").strip().lower()
        punch_time = (log.get("punch_time") or "").strip()
        punch_dt = _parse_biometric_datetime(punch_time)
        if punch_type == "break_start":
            has_break_activity = True
            open_break_started_at = punch_dt
            open_break_started_raw = punch_time if punch_dt else ""
        elif punch_type in {"break_finish", "check_out"}:
            if open_break_started_at and punch_dt and punch_dt >= open_break_started_at:
                completed_seconds += int((punch_dt - open_break_started_at).total_seconds())
            open_break_started_at = None
            open_break_started_raw = ""

    open_seconds = 0
    if open_break_started_at:
        open_seconds = max(0, int((now_value - open_break_started_at).total_seconds()))

    total_seconds = completed_seconds + open_seconds
    return {
        "has_break_activity": has_break_activity,
        "is_open": bool(open_break_started_at),
        "completed_seconds": completed_seconds,
        "open_seconds": open_seconds,
        "total_seconds": total_seconds,
        "open_started_at_iso": open_break_started_raw,
        "duration_label": _format_break_duration_label(total_seconds, has_break_activity),
    }


def _build_attendance_status_display(status, logs_sorted=None):
    safe_status = (status or "absent").strip().lower()
    if safe_status in {"present", "late"}:
        badge_class = "green"
    elif safe_status in {"half_day", "leave"}:
        badge_class = "orange"
    else:
        badge_class = "red"

    return {
        "status_key": safe_status,
        "label": ATTENDANCE_STATUS_LABELS.get(safe_status, safe_status.replace("_", " ").title()),
        "badge_class": badge_class,
    }


def _build_break_status_display(logs_sorted):
    safe_logs = logs_sorted or []
    break_summary = _summarize_break_activity(safe_logs)
    break_state = _resolve_open_break_state(safe_logs)
    if break_state:
        return break_state

    if break_summary["has_break_activity"]:
        return {
            "status_key": "break_finished",
            "label": BREAK_STATUS_LABELS["break_finished"],
            "badge_class": "green",
        }

    return {
        "status_key": "break_not_started",
        "label": BREAK_STATUS_LABELS["break_not_started"],
        "badge_class": "",
    }


def _format_coordinate_pair(latitude, longitude):
    if latitude in (None, "") or longitude in (None, ""):
        return "-"
    return f"{float(latitude):.5f}, {float(longitude):.5f}"


def _format_accuracy_label(accuracy_value):
    if accuracy_value in (None, ""):
        return "-"
    accuracy = float(accuracy_value)
    if accuracy.is_integer():
        return f"{int(accuracy)} m"
    return f"{accuracy:.2f} m"


def _attach_biometric_display_meta(log):
    log["location_display"] = (
        _normalize_biometric_location_label(log.get("location_label"), log.get("warehouse_name"))
        or _normalize_biometric_location_label(log.get("device_name"))
        or "-"
    )
    log["coordinate_display"] = _format_coordinate_pair(log.get("latitude"), log.get("longitude"))
    log["accuracy_display"] = _format_accuracy_label(log.get("accuracy_m"))
    log["sync_status_label"], log["status_badge_class"] = _build_biometric_status_meta(log["sync_status"])
    log["photo_url"] = _get_biometric_photo_url(log.get("photo_path"))
    log["has_photo"] = bool(log.get("photo_path"))
    return log


def _build_biometric_status_meta(status):
    safe_status = status if status in BIOMETRIC_SYNC_STATUSES else "queued"
    if safe_status in {"synced", "manual"}:
        badge_class = "green"
    elif safe_status == "queued":
        badge_class = "orange"
    else:
        badge_class = "red"
    return BIOMETRIC_STATUS_LABELS.get(safe_status, safe_status), badge_class


def _resolve_employee_warehouse(db, raw_warehouse_id):
    scope_warehouse = get_hris_scope()
    if scope_warehouse:
        return scope_warehouse

    warehouse_id = _to_int(raw_warehouse_id)
    if warehouse_id is None:
        return None

    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    return warehouse["id"] if warehouse else None


def _get_accessible_employee(db, employee_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            e.*,
            w.name AS warehouse_name
        FROM employees e
        LEFT JOIN warehouses w ON e.warehouse_id = w.id
        WHERE e.id=?
    """
    params = [employee_id]

    if scope_warehouse:
        query += " AND e.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_employee_by_id(db, employee_id):
    return _get_accessible_employee(db, employee_id)


def _get_self_service_employee(db):
    employee_id = _get_linked_employee_id()
    if not employee_id:
        return None
    return _get_accessible_employee(db, employee_id)


def _resolve_form_employee(db, raw_employee_id, module_slug):
    if is_self_service_module(module_slug):
        employee = _get_self_service_employee(db)
        requested_employee_id = _to_int(raw_employee_id)
        if employee is None:
            return None, "Akun ini belum ditautkan ke data karyawan. Hubungkan dulu dari halaman Admin."
        if requested_employee_id and requested_employee_id != employee["id"]:
            return None, "Akun ini hanya bisa mengisi form untuk profil karyawan sendiri."
        return employee, None

    employee_id = _to_int(raw_employee_id)
    if employee_id is None:
        return None, "Karyawan wajib dipilih."

    employee = _get_accessible_employee(db, employee_id)
    if employee is None:
        return None, "Data karyawan tidak tersedia untuk akun ini."
    return employee, None


def _get_attendance_by_id(db, attendance_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            a.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name
        FROM attendance_records a
        JOIN employees e ON a.employee_id = e.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        WHERE a.id=?
    """
    params = [attendance_id]

    if scope_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_attendance_by_employee_date(db, employee_id, attendance_date):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            a.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name
        FROM attendance_records a
        JOIN employees e ON a.employee_id = e.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        WHERE a.employee_id=? AND a.attendance_date=?
    """
    params = [employee_id, attendance_date]

    if scope_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(scope_warehouse)

    query += " ORDER BY a.id DESC LIMIT 1"
    return db.execute(query, params).fetchone()


def _get_leave_request_by_id(db, leave_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            l.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM leave_requests l
        JOIN employees e ON l.employee_id = e.id
        LEFT JOIN warehouses w ON l.warehouse_id = w.id
        LEFT JOIN users u ON l.handled_by = u.id
        WHERE l.id=?
    """
    params = [leave_id]

    if scope_warehouse:
        query += " AND l.warehouse_id=?"
        params.append(scope_warehouse)

    linked_employee_id = _get_linked_employee_id()
    if is_self_service_module("leave"):
        if linked_employee_id:
            query += " AND l.employee_id=?"
            params.append(linked_employee_id)
        else:
            query += " AND 1=0"

    return db.execute(query, params).fetchone()


def _get_payroll_by_id(db, payroll_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM payroll_runs p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE p.id=?
    """
    params = [payroll_id]

    if scope_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_recruitment_candidate_by_id(db, candidate_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            r.*,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM recruitment_candidates r
        LEFT JOIN warehouses w ON r.warehouse_id = w.id
        LEFT JOIN users u ON r.handled_by = u.id
        WHERE r.id=?
    """
    params = [candidate_id]

    if scope_warehouse:
        query += " AND r.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_onboarding_by_id(db, onboarding_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            o.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM onboarding_records o
        JOIN employees e ON o.employee_id = e.id
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        LEFT JOIN users u ON o.handled_by = u.id
        WHERE o.id=?
    """
    params = [onboarding_id]

    if scope_warehouse:
        query += " AND o.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_offboarding_by_id(db, offboarding_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            o.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM offboarding_records o
        JOIN employees e ON o.employee_id = e.id
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        LEFT JOIN users u ON o.handled_by = u.id
        WHERE o.id=?
    """
    params = [offboarding_id]

    if scope_warehouse:
        query += " AND o.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_performance_by_id(db, review_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM performance_reviews p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE p.id=?
    """
    params = [review_id]

    if scope_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_helpdesk_ticket_by_id(db, ticket_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            h.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM helpdesk_tickets h
        JOIN employees e ON h.employee_id = e.id
        LEFT JOIN warehouses w ON h.warehouse_id = w.id
        LEFT JOIN users u ON h.handled_by = u.id
        WHERE h.id=?
    """
    params = [ticket_id]

    if scope_warehouse:
        query += " AND h.warehouse_id=?"
        params.append(scope_warehouse)

    linked_employee_id = _get_linked_employee_id()
    if is_self_service_module("helpdesk"):
        if linked_employee_id:
            query += " AND h.employee_id=?"
            params.append(linked_employee_id)
        else:
            query += " AND 1=0"

    return db.execute(query, params).fetchone()


def _get_asset_record_by_id(db, asset_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            a.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM asset_records a
        JOIN employees e ON a.employee_id = e.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        LEFT JOIN users u ON a.handled_by = u.id
        WHERE a.id=?
    """
    params = [asset_id]

    if scope_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_project_by_id(db, project_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM project_records p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE p.id=?
    """
    params = [project_id]

    if scope_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_biometric_log_by_id(db, biometric_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            b.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM biometric_logs b
        JOIN employees e ON b.employee_id = e.id
        LEFT JOIN warehouses w ON b.warehouse_id = w.id
        LEFT JOIN users u ON b.handled_by = u.id
        WHERE b.id=?
    """
    params = [biometric_id]

    if scope_warehouse:
        query += " AND b.warehouse_id=?"
        params.append(scope_warehouse)

    linked_employee_id = _get_linked_employee_id()
    if is_self_service_module("biometric"):
        if linked_employee_id:
            query += " AND b.employee_id=?"
            params.append(linked_employee_id)
        else:
            query += " AND 1=0"

    return db.execute(query, params).fetchone()


def _get_announcement_by_id(db, announcement_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            a.*,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM announcement_posts a
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        LEFT JOIN users u ON a.handled_by = u.id
        WHERE a.id=?
    """
    params = [announcement_id]

    if scope_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _get_document_by_id(db, document_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            d.*,
            w.name AS warehouse_name,
            u.username AS handled_by_name,
            su.username AS signed_by_name
        FROM document_records d
        LEFT JOIN warehouses w ON d.warehouse_id = w.id
        LEFT JOIN users u ON d.handled_by = u.id
        LEFT JOIN users su ON d.signed_by = su.id
        WHERE d.id=?
    """
    params = [document_id]

    if scope_warehouse:
        query += " AND d.warehouse_id=?"
        params.append(scope_warehouse)

    return db.execute(query, params).fetchone()


def _resync_attendance_from_biometrics(db, employee_id, warehouse_id, attendance_date):
    if not employee_id or not warehouse_id or not attendance_date:
        return

    logs = [
        dict(row)
        for row in db.execute(
            """
            SELECT punch_time, punch_type, sync_status, shift_code, shift_label
            FROM biometric_logs
            WHERE employee_id=?
              AND warehouse_id=?
              AND substr(punch_time, 1, 10)=?
              AND sync_status IN (?,?)
            ORDER BY punch_time ASC, id ASC
            """,
            (employee_id, warehouse_id, attendance_date, "synced", "manual"),
        ).fetchall()
    ]
    existing = db.execute(
        """
        SELECT id, note, shift_code, shift_label, status_override
        FROM attendance_records
        WHERE employee_id=? AND attendance_date=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (employee_id, attendance_date),
    ).fetchone()

    if not logs:
        if existing and (existing["note"] or "") in {"Synced from biometric", GEO_ATTENDANCE_NOTE}:
            db.execute("DELETE FROM attendance_records WHERE id=?", (existing["id"],))
        return

    check_in = next(
        (
            datetime.fromisoformat(log["punch_time"]).strftime("%H:%M")
            for log in logs
            if log["punch_type"] == "check_in"
        ),
        None,
    )
    check_out = next(
        (
            datetime.fromisoformat(log["punch_time"]).strftime("%H:%M")
            for log in reversed(logs)
            if log["punch_type"] == "check_out"
        ),
        None,
    )
    shift_snapshot = next(
        (
            {
                "shift_code": (log.get("shift_code") or "").strip().lower() or None,
                "shift_label": (log.get("shift_label") or "").strip() or None,
            }
            for log in logs
            if (log.get("shift_code") or "").strip() or (log.get("shift_label") or "").strip()
        ),
        {
            "shift_code": (existing["shift_code"] if existing and existing["shift_code"] else None),
            "shift_label": (existing["shift_label"] if existing and existing["shift_label"] else None),
        },
    )
    derived_status = _derive_biometric_attendance_status_with_shift(
        check_in,
        shift_snapshot.get("shift_label"),
    )
    status_override = (existing["status_override"] if existing and existing["status_override"] else "").strip().lower()
    status = status_override if status_override in ATTENDANCE_STATUSES else derived_status

    if existing:
        db.execute(
            """
            UPDATE attendance_records
            SET warehouse_id=?,
                check_in=?,
                check_out=?,
                status=?,
                shift_code=?,
                shift_label=?,
                note=?,
                updated_at=?
            WHERE id=?
            """,
            (
                warehouse_id,
                check_in,
                check_out,
                status,
                shift_snapshot["shift_code"],
                shift_snapshot["shift_label"],
                GEO_ATTENDANCE_NOTE,
                _current_timestamp(),
                existing["id"],
            ),
        )
    else:
        db.execute(
            """
            INSERT INTO attendance_records(
                employee_id,
                warehouse_id,
                attendance_date,
                check_in,
                check_out,
                status,
                shift_code,
                shift_label,
                note,
                updated_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                employee_id,
                warehouse_id,
                attendance_date,
                check_in,
                check_out,
                status,
                shift_snapshot["shift_code"],
                shift_snapshot["shift_label"],
                GEO_ATTENDANCE_NOTE,
                _current_timestamp(),
            ),
        )


def _fetch_employee_options(db, module_slug=None):
    if module_slug and is_self_service_module(module_slug):
        employee = _get_self_service_employee(db)
        return [dict(employee)] if employee else []

    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            e.id,
            e.employee_code,
            e.full_name,
            e.employment_status,
            e.warehouse_id,
            w.name AS warehouse_name
        FROM employees e
        LEFT JOIN warehouses w ON e.warehouse_id = w.id
        WHERE 1=1
    """
    params = []

    if scope_warehouse:
        query += " AND e.warehouse_id=?"
        params.append(scope_warehouse)

    query += " ORDER BY e.full_name COLLATE NOCASE ASC, e.id DESC"
    return [dict(row) for row in db.execute(query, params).fetchall()]


def _fetch_overtime_recap_employees(db, selected_warehouse=None):
    scope_warehouse = get_hris_scope()
    safe_warehouse = scope_warehouse or selected_warehouse
    query = """
        SELECT
            e.id,
            e.employee_code,
            e.full_name,
            e.employment_status,
            e.warehouse_id,
            w.name AS warehouse_name
        FROM employees e
        LEFT JOIN warehouses w ON e.warehouse_id = w.id
        WHERE 1=1
    """
    params = []

    if safe_warehouse:
        query += " AND e.warehouse_id=?"
        params.append(safe_warehouse)

    query += " ORDER BY e.full_name COLLATE NOCASE ASC, e.id ASC"
    return [dict(row) for row in db.execute(query, params).fetchall()]


def _fetch_overtime_usage_records(db, selected_warehouse=None, employee_id=None, limit=None):
    _ensure_overtime_feature_schema(db)
    scope_warehouse = get_hris_scope()
    safe_warehouse = scope_warehouse or selected_warehouse
    usage_columns = _get_table_columns(db, "overtime_usage_records")
    query = """
        SELECT
            o.*,
            e.employee_code,
            e.full_name,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM overtime_usage_records o
        JOIN employees e ON o.employee_id = e.id
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        LEFT JOIN users u ON o.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if safe_warehouse:
        query += " AND o.warehouse_id=?"
        params.append(safe_warehouse)

    if employee_id:
        query += " AND o.employee_id=?"
        params.append(employee_id)

    query += " ORDER BY o.usage_date DESC, o.created_at DESC, o.id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(int(max(1, limit)))

    usage_rows = [dict(row) for row in db.execute(query, params).fetchall()]
    for row in usage_rows:
        row["usage_mode"] = _normalize_overtime_usage_mode(
            row.get("usage_mode") if "usage_mode" in usage_columns else "regular"
        )
        row["usage_mode_label"] = _get_overtime_usage_mode_label(row["usage_mode"])
        row["minutes_used"] = max(0, int(row.get("minutes_used") or 0))
        row["duration_label"] = _format_duration_minutes_label(row["minutes_used"])
        row["handled_by_name"] = row.get("handled_by_name") or "-"
        row["note"] = row.get("note") or "-"
    return usage_rows


def _fetch_overtime_balance_adjustment_records(db, selected_warehouse=None, employee_id=None, limit=None):
    _ensure_overtime_feature_schema(db)
    scope_warehouse = get_hris_scope()
    safe_warehouse = scope_warehouse or selected_warehouse
    query = """
        SELECT
            a.*,
            e.employee_code,
            e.full_name,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM overtime_balance_adjustments a
        JOIN employees e ON a.employee_id = e.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        LEFT JOIN users u ON a.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if safe_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(safe_warehouse)

    if employee_id:
        query += " AND a.employee_id=?"
        params.append(employee_id)

    query += " ORDER BY a.adjustment_date DESC, a.created_at DESC, a.id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(int(max(1, limit)))

    adjustment_rows = [dict(row) for row in db.execute(query, params).fetchall()]
    for row in adjustment_rows:
        row["minutes_delta"] = max(0, int(row.get("minutes_delta") or 0))
        row["duration_label"] = _format_duration_minutes_label(row["minutes_delta"])
        row["handled_by_name"] = row.get("handled_by_name") or "-"
        row["note"] = row.get("note") or "-"
    return adjustment_rows


def _fetch_overtime_add_request_records(
    db,
    *,
    status="approved",
    selected_warehouse=None,
    employee_id=None,
    employee_ids=None,
    limit=None,
):
    _ensure_overtime_feature_schema(db)
    scope_warehouse = get_hris_scope()
    safe_warehouse = scope_warehouse or selected_warehouse
    normalized_status = str(status or "all").strip().lower()
    safe_employee_ids = [int(item) for item in (employee_ids or []) if _to_int(item)]
    query = """
        SELECT
            r.*,
            e.employee_code,
            e.full_name,
            w.name AS warehouse_name,
            ru.username AS requested_by_name,
            hu.username AS handled_by_name
        FROM attendance_action_requests r
        LEFT JOIN employees e ON e.id = r.employee_id
        LEFT JOIN warehouses w ON w.id = r.warehouse_id
        LEFT JOIN users ru ON ru.id = r.requested_by
        LEFT JOIN users hu ON hu.id = r.handled_by
        WHERE r.request_type='overtime_add'
    """
    params = []

    if normalized_status in {"pending", "approved", "rejected", "cancelled"}:
        query += " AND r.status=?"
        params.append(normalized_status)

    if safe_warehouse:
        query += " AND r.warehouse_id=?"
        params.append(safe_warehouse)

    if employee_id:
        query += " AND r.employee_id=?"
        params.append(employee_id)
    elif safe_employee_ids:
        placeholders = ",".join("?" for _ in safe_employee_ids)
        query += f" AND r.employee_id IN ({placeholders})"
        params.extend(safe_employee_ids)

    query += " ORDER BY COALESCE(r.handled_at, r.created_at) DESC, r.id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(int(max(1, limit)))

    request_rows = []
    for row in db.execute(query, params).fetchall():
        record = dict(row)
        payload_map = parse_attendance_request_payload(record.get("payload"))
        record["payload_map"] = payload_map
        record["minutes_delta"] = max(0, _to_int(payload_map.get("minutes_delta"), 0) or 0)
        record["duration_label"] = _format_duration_minutes_label(record["minutes_delta"], zero_label="0 mnt")
        record["source_type"] = _normalize_overtime_add_source_type(payload_map.get("source_type"))
        record["attendance_date"] = (
            str(payload_map.get("attendance_date") or payload_map.get("adjustment_date") or "").strip()
        )
        request_rows.append(record)
    return request_rows


def _get_biometric_overtime_request_status_meta(status):
    normalized = str(status or "").strip().lower()
    if normalized == "approved":
        return {
            "label": "Approved",
            "badge_class": "green",
            "helper_text": "Sudah masuk ke saldo lembur.",
        }
    if normalized == "rejected":
        return {
            "label": "Declined",
            "badge_class": "red",
            "helper_text": "Tidak ditambahkan ke saldo lembur.",
        }
    if normalized == "pending":
        return {
            "label": "Pending",
            "badge_class": "orange",
            "helper_text": "Masih menunggu keputusan HR / Super Admin.",
        }
    return {
        "label": "-",
        "badge_class": "",
        "helper_text": "",
    }


def _build_biometric_auto_overtime_payload(employee, attendance_date, check_in_time, check_out_time, shift_label, overtime_summary):
    employee_record = dict(employee or {})
    safe_attendance_date = str(attendance_date or "").strip()
    total_seconds = max(0, int(overtime_summary.get("total_seconds") or 0))
    minutes_delta = total_seconds // 60
    breakdown_label = str(overtime_summary.get("breakdown_label") or "").strip()
    note_segments = [f"Lembur otomatis {safe_attendance_date}"]
    if breakdown_label:
        note_segments.append(breakdown_label)
    if check_in_time or check_out_time:
        note_segments.append(
            f"Check in {check_in_time or '-'} | Check out {check_out_time or '-'}"
        )
    if shift_label:
        note_segments.append(f"Shift {shift_label}")
    note_text = " | ".join(segment for segment in note_segments if segment)
    return {
        "source_type": "biometric_auto",
        "employee_id": employee_record.get("id"),
        "employee_name": employee_record.get("full_name"),
        "warehouse_id": employee_record.get("warehouse_id"),
        "attendance_date": safe_attendance_date,
        "adjustment_date": safe_attendance_date,
        "minutes_delta": minutes_delta,
        "duration_label": overtime_summary.get("duration_label") or _format_duration_minutes_label(minutes_delta),
        "check_in_time": check_in_time or "",
        "check_out_time": check_out_time or "",
        "shift_label": shift_label or "",
        "early_seconds": max(0, int(overtime_summary.get("early_seconds") or 0)),
        "late_seconds": max(0, int(overtime_summary.get("late_seconds") or 0)),
        "breakdown_label": breakdown_label,
        "note": note_text,
    }


def _build_biometric_overtime_request_index(db, employee_ids=None, attendance_dates=None):
    safe_employee_ids = [int(item) for item in (employee_ids or []) if _to_int(item)]
    safe_dates = {str(item or "").strip() for item in (attendance_dates or []) if str(item or "").strip()}
    request_rows = _fetch_overtime_add_request_records(
        db,
        status="all",
        employee_ids=safe_employee_ids,
    )
    request_index = {}
    for row in request_rows:
        if row.get("source_type") != "biometric_auto":
            continue
        attendance_date = str(row.get("attendance_date") or "").strip()
        if safe_dates and attendance_date not in safe_dates:
            continue
        employee_id = _to_int(row.get("employee_id"))
        if not employee_id or not attendance_date:
            continue
        request_index.setdefault((employee_id, attendance_date), row)
    return request_index


def _get_biometric_attendance_record(db, employee_id, attendance_date):
    safe_employee_id = _to_int(employee_id)
    safe_attendance_date = str(attendance_date or "").strip()
    if not safe_employee_id or not safe_attendance_date:
        return None

    attendance_columns = _get_table_columns(db, "attendance_records")
    if not {"employee_id", "attendance_date", "check_in", "check_out"}.issubset(attendance_columns):
        return None

    query = """
        SELECT
            id,
            employee_id,
            warehouse_id,
            attendance_date,
            check_in,
            check_out,
            status,
            shift_code,
            shift_label
        FROM attendance_records
        WHERE employee_id=? AND attendance_date=?
    """
    params = [safe_employee_id, safe_attendance_date]
    scope_warehouse = get_hris_scope()
    if scope_warehouse and "warehouse_id" in attendance_columns:
        query += " AND warehouse_id=?"
        params.append(scope_warehouse)
    query += " ORDER BY id DESC LIMIT 1"
    return db.execute(query, params).fetchone()


def _get_overtime_usage_by_id(db, usage_id):
    _ensure_overtime_feature_schema(db)
    scope_warehouse = get_hris_scope()
    usage_columns = _get_table_columns(db, "overtime_usage_records")
    query = """
        SELECT
            o.*,
            e.employee_code,
            e.full_name,
            w.name AS warehouse_name
        FROM overtime_usage_records o
        JOIN employees e ON o.employee_id = e.id
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        WHERE o.id=?
    """
    params = [usage_id]

    if scope_warehouse:
        query += " AND o.warehouse_id=?"
        params.append(scope_warehouse)

    row = db.execute(query, params).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["usage_mode"] = _normalize_overtime_usage_mode(
        record.get("usage_mode") if "usage_mode" in usage_columns else "regular"
    )
    record["usage_mode_label"] = _get_overtime_usage_mode_label(record["usage_mode"])
    return record


def _summarize_overtime_balance_ledger(
    overtime_add_rows=None,
    usage_rows=None,
    *,
    period_date_from=None,
    period_date_to=None,
):
    safe_overtime_add_rows = overtime_add_rows or []
    safe_usage_rows = usage_rows or []
    raw_earned_minutes = 0
    raw_added_minutes = 0
    raw_used_minutes = 0
    earned_total_minutes = 0
    added_total_minutes = 0
    used_total_minutes = 0
    earned_period_minutes = 0
    added_period_minutes = 0
    used_period_minutes = 0
    capped_credit_minutes = 0
    excess_usage_minutes = 0
    last_overtime_date = ""
    last_adjustment_date = ""
    last_usage_date = ""
    events = []

    for row in safe_overtime_add_rows:
        source_type = _normalize_overtime_add_source_type(row.get("source_type"))
        minutes_delta = max(0, int(row.get("minutes_delta") or 0))
        activity_date = str(row.get("attendance_date") or row.get("adjustment_date") or "").strip()
        if source_type == "biometric_auto":
            raw_earned_minutes += minutes_delta
            if activity_date > last_overtime_date:
                last_overtime_date = activity_date
        else:
            raw_added_minutes += minutes_delta
            if activity_date > last_adjustment_date:
                last_adjustment_date = activity_date

        event_timestamp = _normalize_datetime_input(
            row.get("handled_at") or row.get("updated_at") or row.get("created_at")
        )
        if not event_timestamp and activity_date:
            event_timestamp = f"{activity_date} 00:00:00"

        events.append(
            {
                "kind": "credit",
                "id": int(row.get("id") or 0),
                "minutes": minutes_delta,
                "source_type": source_type,
                "activity_date": activity_date,
                "event_timestamp": event_timestamp or "",
            }
        )

    for row in safe_usage_rows:
        minutes_used = max(0, int(row.get("minutes_used") or 0))
        usage_date = str(row.get("usage_date") or "").strip()
        raw_used_minutes += minutes_used
        if usage_date > last_usage_date:
            last_usage_date = usage_date

        event_timestamp = _normalize_datetime_input(row.get("updated_at") or row.get("created_at"))
        if not event_timestamp and usage_date:
            event_timestamp = f"{usage_date} 00:00:00"

        events.append(
            {
                "kind": "usage",
                "id": int(row.get("id") or 0),
                "minutes": minutes_used,
                "activity_date": usage_date,
                "event_timestamp": event_timestamp or "",
            }
        )

    events.sort(
        key=lambda event: (
            event.get("event_timestamp") or "",
            event.get("activity_date") or "",
            0 if event.get("kind") == "credit" else 1,
            int(event.get("id") or 0),
        )
    )

    available_minutes = 0
    for event in events:
        activity_date = event.get("activity_date") or ""
        is_in_period = _is_iso_date_within_range(activity_date, period_date_from, period_date_to)
        if event.get("kind") == "credit":
            credit_minutes = max(0, int(event.get("minutes") or 0))
            remaining_capacity = max(0, OVERTIME_BALANCE_CAP_MINUTES - available_minutes)
            applied_minutes = min(credit_minutes, remaining_capacity)
            capped_credit_minutes += max(0, credit_minutes - applied_minutes)
            if applied_minutes > 0:
                available_minutes += applied_minutes
                if event.get("source_type") == "biometric_auto":
                    earned_total_minutes += applied_minutes
                    if is_in_period:
                        earned_period_minutes += applied_minutes
                else:
                    added_total_minutes += applied_minutes
                    if is_in_period:
                        added_period_minutes += applied_minutes
            continue

        usage_minutes = max(0, int(event.get("minutes") or 0))
        applied_minutes = min(available_minutes, usage_minutes)
        excess_usage_minutes += max(0, usage_minutes - applied_minutes)
        if applied_minutes > 0:
            available_minutes = max(0, available_minutes - applied_minutes)
            used_total_minutes += applied_minutes
            if is_in_period:
                used_period_minutes += applied_minutes

    return {
        "raw_earned_minutes": raw_earned_minutes,
        "raw_added_minutes": raw_added_minutes,
        "raw_used_minutes": raw_used_minutes,
        "raw_available_minutes": max(0, raw_earned_minutes + raw_added_minutes - raw_used_minutes),
        "earned_total_minutes": earned_total_minutes,
        "added_total_minutes": added_total_minutes,
        "used_total_minutes": used_total_minutes,
        "earned_period_minutes": earned_period_minutes,
        "added_period_minutes": added_period_minutes,
        "used_period_minutes": used_period_minutes,
        "available_minutes": available_minutes,
        "capped_credit_minutes": capped_credit_minutes,
        "excess_usage_minutes": excess_usage_minutes,
        "last_overtime_date": last_overtime_date,
        "last_adjustment_date": last_adjustment_date,
        "last_usage_date": last_usage_date,
        "has_activity": bool(events),
    }


def _build_employee_overtime_balance(db, employee_id, reference_date=None, *, include_pending_weekly_usage=False):
    overtime_add_rows = _fetch_overtime_add_request_records(
        db,
        status="approved",
        employee_id=employee_id,
    )
    usage_rows = _fetch_overtime_usage_records(db, employee_id=employee_id)
    ledger_summary = _summarize_overtime_balance_ledger(overtime_add_rows, usage_rows)
    earned_minutes = ledger_summary["earned_total_minutes"]
    added_minutes = ledger_summary["added_total_minutes"]
    earned_seconds = earned_minutes * 60
    added_seconds = added_minutes * 60
    used_minutes = ledger_summary["used_total_minutes"]
    used_seconds = used_minutes * 60
    raw_available_minutes = ledger_summary["raw_available_minutes"]
    available_minutes = ledger_summary["available_minutes"]
    available_seconds = available_minutes * 60
    weekly_meta = _build_weekly_overtime_usage_meta(
        db,
        employee_id,
        reference_date=reference_date,
        include_pending_requests=include_pending_weekly_usage,
        usage_rows=usage_rows,
    )
    return {
        "earned_seconds": earned_seconds,
        "added_seconds": added_seconds,
        "added_minutes": added_minutes,
        "used_seconds": used_seconds,
        "used_minutes": used_minutes,
        "raw_earned_minutes": ledger_summary["raw_earned_minutes"],
        "raw_added_minutes": ledger_summary["raw_added_minutes"],
        "raw_used_minutes": ledger_summary["raw_used_minutes"],
        "raw_available_minutes": raw_available_minutes,
        "available_seconds": available_seconds,
        "available_minutes": available_minutes,
        "earned_label": _format_duration_minutes_label(earned_seconds // 60, zero_label="0 mnt"),
        "added_label": _format_duration_minutes_label(added_minutes, zero_label="0 mnt"),
        "used_label": _format_duration_minutes_label(used_minutes, zero_label="0 mnt"),
        "available_label": _format_duration_minutes_label(available_minutes, zero_label="0 mnt"),
        "capped_credit_minutes": ledger_summary["capped_credit_minutes"],
        "capped_credit_label": _format_duration_minutes_label(
            ledger_summary["capped_credit_minutes"],
            zero_label="0 mnt",
        ),
        "balance_cap_minutes": OVERTIME_BALANCE_CAP_MINUTES,
        "balance_cap_label": _format_duration_minutes_label(OVERTIME_BALANCE_CAP_MINUTES),
        "remaining_capacity_minutes": max(0, OVERTIME_BALANCE_CAP_MINUTES - available_minutes),
        "remaining_capacity_label": _format_duration_minutes_label(
            max(0, OVERTIME_BALANCE_CAP_MINUTES - available_minutes),
            zero_label="0 mnt",
        ),
        "weekly_used_minutes": weekly_meta["used_minutes"],
        "weekly_used_label": weekly_meta["used_label"],
        "weekly_pending_minutes": weekly_meta["pending_minutes"],
        "weekly_pending_label": weekly_meta["pending_label"],
        "weekly_committed_minutes": weekly_meta["committed_minutes"],
        "weekly_committed_label": weekly_meta["committed_label"],
        "weekly_remaining_minutes": weekly_meta["remaining_minutes"],
        "weekly_remaining_label": weekly_meta["remaining_label"],
        "weekly_limit_minutes": weekly_meta["limit_minutes"],
        "weekly_limit_label": weekly_meta["limit_label"],
        "weekly_period_label": weekly_meta["week_label"],
    }


def _build_overtime_recap(db, selected_warehouse=None, period_date_from=None, period_date_to=None):
    employees = _fetch_overtime_recap_employees(db, selected_warehouse)
    overtime_add_rows = _fetch_overtime_add_request_records(
        db,
        status="approved",
        selected_warehouse=selected_warehouse,
    )
    usage_rows = _fetch_overtime_usage_records(db, selected_warehouse=selected_warehouse)
    overtime_add_by_employee = {}
    for overtime_add_row in overtime_add_rows:
        overtime_add_by_employee.setdefault(overtime_add_row["employee_id"], []).append(overtime_add_row)
    usage_by_employee = {}
    for usage_row in usage_rows:
        usage_by_employee.setdefault(usage_row["employee_id"], []).append(usage_row)

    recap_rows = []
    for employee in employees:
        ledger_summary = _summarize_overtime_balance_ledger(
            overtime_add_by_employee.get(employee["id"]),
            usage_by_employee.get(employee["id"]),
            period_date_from=period_date_from,
            period_date_to=period_date_to,
        )
        earned_total_seconds = ledger_summary["earned_total_minutes"] * 60
        earned_period_seconds = ledger_summary["earned_period_minutes"] * 60
        added_total_seconds = ledger_summary["added_total_minutes"] * 60
        added_period_seconds = ledger_summary["added_period_minutes"] * 60
        used_total_seconds = ledger_summary["used_total_minutes"] * 60
        used_period_seconds = ledger_summary["used_period_minutes"] * 60
        available_minutes = ledger_summary["available_minutes"]
        available_seconds = available_minutes * 60
        if not ledger_summary["has_activity"]:
            continue
        recap_rows.append(
            {
                **employee,
                "earned_total_seconds": earned_total_seconds,
                "earned_period_seconds": earned_period_seconds,
                "added_total_seconds": added_total_seconds,
                "added_period_seconds": added_period_seconds,
                "used_total_seconds": used_total_seconds,
                "used_period_seconds": used_period_seconds,
                "last_overtime_date": ledger_summary["last_overtime_date"],
                "last_adjustment_date": ledger_summary["last_adjustment_date"],
                "last_usage_date": ledger_summary["last_usage_date"],
                "earned_total_label": _format_break_duration_label(
                    earned_total_seconds,
                    has_break_activity=earned_total_seconds > 0,
                ),
                "earned_period_label": _format_break_duration_label(
                    earned_period_seconds,
                    has_break_activity=earned_period_seconds > 0,
                ),
                "added_total_label": _format_break_duration_label(
                    added_total_seconds,
                    has_break_activity=added_total_seconds > 0,
                ),
                "added_period_label": _format_break_duration_label(
                    added_period_seconds,
                    has_break_activity=added_period_seconds > 0,
                ),
                "used_total_label": _format_break_duration_label(
                    used_total_seconds,
                    has_break_activity=used_total_seconds > 0,
                ),
                "used_period_label": _format_break_duration_label(
                    used_period_seconds,
                    has_break_activity=used_period_seconds > 0,
                ),
                "available_seconds": available_seconds,
                "available_minutes": available_minutes,
                "available_label": _format_duration_minutes_label(available_minutes, zero_label="0 mnt"),
                "has_available_balance": available_seconds > 0,
                "latest_activity_date": (
                    ledger_summary["last_usage_date"]
                    or ledger_summary["last_adjustment_date"]
                    or ledger_summary["last_overtime_date"]
                    or "-"
                ),
                "usage_hint_label": (
                    f"Saldo maks {_format_duration_minutes_label(OVERTIME_BALANCE_CAP_MINUTES)} | Pakai reguler maks {_format_duration_minutes_label(OVERTIME_WEEKLY_USAGE_LIMIT_MINUTES)} / minggu"
                    if available_seconds > 0
                    else "Belum ada saldo"
                ),
            }
        )

    recap_rows.sort(
        key=lambda row: (
            -row["available_seconds"],
            -row["earned_period_seconds"],
            (row["full_name"] or "").lower(),
            row["id"],
        )
    )

    summary = {
        "staff_total": len(recap_rows),
        "staff_with_balance": sum(1 for row in recap_rows if row["has_available_balance"]),
        "earned_period_seconds": sum(row["earned_period_seconds"] for row in recap_rows),
        "added_period_seconds": sum(row["added_period_seconds"] for row in recap_rows),
        "used_period_seconds": sum(row["used_period_seconds"] for row in recap_rows),
        "available_total_seconds": sum(row["available_seconds"] for row in recap_rows),
        "earned_period_label": _format_break_duration_label(
            sum(row["earned_period_seconds"] for row in recap_rows),
            has_break_activity=sum(row["earned_period_seconds"] for row in recap_rows) > 0,
        ),
        "added_period_label": _format_break_duration_label(
            sum(row["added_period_seconds"] for row in recap_rows),
            has_break_activity=sum(row["added_period_seconds"] for row in recap_rows) > 0,
        ),
        "used_period_label": _format_break_duration_label(
            sum(row["used_period_seconds"] for row in recap_rows),
            has_break_activity=sum(row["used_period_seconds"] for row in recap_rows) > 0,
        ),
        "available_total_label": _format_break_duration_label(
            sum(row["available_seconds"] for row in recap_rows),
            has_break_activity=sum(row["available_seconds"] for row in recap_rows) > 0,
        ),
        "history_count": min(len(usage_rows), OVERTIME_USAGE_HISTORY_LIMIT),
        "period_label": (
            f"{period_date_from} s/d {period_date_to}"
            if period_date_from and period_date_to
            else period_date_from
            or period_date_to
            or "Semua Periode"
        ),
    }
    return recap_rows, summary, usage_rows[:OVERTIME_USAGE_HISTORY_LIMIT]


def _build_employee_summary(employees):
    return {
        "total": len(employees),
        "active": sum(1 for employee in employees if employee["employment_status"] == "active"),
        "probation": sum(1 for employee in employees if employee["employment_status"] == "probation"),
        "leave": sum(1 for employee in employees if employee["employment_status"] == "leave"),
        "inactive": sum(1 for employee in employees if employee["employment_status"] == "inactive"),
        "with_email": sum(1 for employee in employees if employee["email"]),
        "with_phone": sum(1 for employee in employees if employee["phone"]),
    }


def _build_attendance_summary(attendance_records):
    return {
        "total": len(attendance_records),
        "present": sum(1 for record in attendance_records if record["status"] == "present"),
        "late": sum(1 for record in attendance_records if record["status"] == "late"),
        "leave": sum(1 for record in attendance_records if record["status"] == "leave"),
        "absent": sum(1 for record in attendance_records if record["status"] == "absent"),
        "half_day": sum(1 for record in attendance_records if record["status"] == "half_day"),
        "with_check_in": sum(1 for record in attendance_records if record["check_in"]),
        "with_check_out": sum(1 for record in attendance_records if record["check_out"]),
    }


def _build_leave_summary(leave_requests):
    return {
        "total": len(leave_requests),
        "pending": sum(1 for record in leave_requests if record["status"] == "pending"),
        "approved": sum(1 for record in leave_requests if record["status"] == "approved"),
        "rejected": sum(1 for record in leave_requests if record["status"] == "rejected"),
        "cancelled": sum(1 for record in leave_requests if record["status"] == "cancelled"),
        "total_days": sum((record["total_days"] or 0) for record in leave_requests),
    }


def _is_special_leave_bucket(leave_type):
    normalized = (leave_type or "").strip().lower()
    return normalized in {"special", "annual", "sick", "permit"}


def _build_approval_summary(approval_requests):
    summary = _build_leave_summary(approval_requests)
    today_iso = date_cls.today().isoformat()
    pending_requests = [record for record in approval_requests if record["status"] == "pending"]
    summary["due_today"] = sum(1 for record in pending_requests if (record.get("start_date") or "") <= today_iso)
    summary["recently_handled"] = sum(
        1 for record in approval_requests if record["status"] in {"approved", "rejected", "cancelled"}
    )
    return summary


def _split_approval_requests(approval_requests, recent_limit=20):
    pending_requests = sorted(
        (record for record in approval_requests if record["status"] == "pending"),
        key=lambda record: (
            record.get("start_date") or "9999-12-31",
            (record.get("full_name") or "").lower(),
            record.get("id") or 0,
        ),
    )
    recent_requests = sorted(
        (record for record in approval_requests if record["status"] != "pending"),
        key=lambda record: (
            record.get("handled_at")
            or record.get("updated_at")
            or record.get("created_at")
            or "",
            record.get("id") or 0,
        ),
        reverse=True,
    )
    return pending_requests, recent_requests[:recent_limit]


def _get_attendance_request_by_id(db, request_id):
    row = db.execute(
        """
        SELECT
            r.*,
            e.employee_code,
            e.full_name,
            e.position,
            w.name AS warehouse_name,
            ru.username AS requested_by_name,
            hu.username AS handled_by_name
        FROM attendance_action_requests r
        LEFT JOIN employees e ON e.id = r.employee_id
        LEFT JOIN warehouses w ON w.id = r.warehouse_id
        LEFT JOIN users ru ON ru.id = r.requested_by
        LEFT JOIN users hu ON hu.id = r.handled_by
        WHERE r.id=?
        LIMIT 1
        """,
        (request_id,),
    ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["request_type_label"] = get_attendance_request_type_label(record.get("request_type"))
    record["payload_map"] = parse_attendance_request_payload(record.get("payload"))
    return record


def _notify_attendance_request_decision(db, request_row, *, approved):
    if not request_row or not request_row.get("requested_by"):
        return

    outcome_label = "disetujui" if approved else "ditolak"
    requester_name = (
        str(request_row.get("requested_by_name") or "").strip()
        or str(request_row.get("requested_by") or "").strip()
        or "Requester"
    )
    approver_name = (
        str(session.get("username") or "").strip()
        or str(session.get("user_id") or "").strip()
        or "HR / Super Admin"
    )
    summary_title = str(request_row.get("summary_title") or request_row.get("request_type_label") or "Request Attendance").strip()
    decision_note = str(request_row.get("decision_note") or "").strip()
    message = (
        f"Request {summary_title} telah {outcome_label} oleh {approver_name}."
        f"{f' Catatan: {decision_note}.' if decision_note else ''}"
    )
    notify_user(
        request_row.get("requested_by"),
        f"{summary_title} {outcome_label.title()}",
        message,
        category="attendance",
        link_url="/hris/approval",
        source_type="attendance_request_status",
        source_id=f"{request_row.get('id')}:{'approved' if approved else 'rejected'}",
        dedupe_key=f"attendance_request_status:{request_row.get('id')}:{'approved' if approved else 'rejected'}",
        push_title=f"{summary_title} {outcome_label.title()}",
        push_body=f"{requester_name} | {outcome_label.title()}",
    )


def _apply_attendance_request(db, request_row):
    _ensure_overtime_feature_schema(db)
    if not request_row:
        raise ValueError("Request attendance tidak ditemukan.")

    request_type = str(request_row.get("request_type") or "").strip().lower()
    payload = parse_attendance_request_payload(request_row.get("payload"))

    if request_type == "schedule_entry":
        employee_id = _to_int(payload.get("employee_id"))
        start_date = _parse_iso_date(payload.get("start_date"))
        end_date = _parse_iso_date(payload.get("end_date"))
        shift_code = str(payload.get("shift_code") or "").strip().upper()
        note = str(payload.get("note") or "").strip()

        employee = db.execute(
            "SELECT id, full_name, warehouse_id FROM employees WHERE id=?",
            (employee_id,),
        ).fetchone()
        if employee is None:
            raise ValueError("Karyawan untuk perubahan shift tidak ditemukan.")
        if start_date is None or end_date is None or end_date < start_date:
            raise ValueError("Rentang tanggal perubahan shift tidak valid.")

        shift_meta = None
        if shift_code:
            shift_meta = db.execute(
                "SELECT code, label FROM schedule_shift_codes WHERE code=?",
                (shift_code,),
            ).fetchone()
            if shift_meta is None:
                raise ValueError("Kode shift request sudah tidak tersedia.")

        if shift_code:
            for current_day in _schedule_daterange(start_date, end_date):
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

        employee_name = (employee["full_name"] or "Karyawan").strip()
        date_range_label = format_date_range(start_date.isoformat(), end_date.isoformat())
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

        try:
            payload_notification = build_schedule_change_notification_payload(
                {"id": event_id, "title": schedule_message.split(".")[0], "message": schedule_message}
            )
            notify_broadcast(
                payload_notification["subject"],
                payload_notification["message"],
                warehouse_id=employee["warehouse_id"],
                push_title=payload_notification["push_title"],
                push_body=payload_notification["push_body"],
                push_url="/announcements/",
                push_tag=payload_notification["push_tag"],
                category="schedule",
                link_url="/announcements/",
                source_type="schedule_change",
                source_id=str(event_id),
            )
        except Exception as exc:
            print("ATTENDANCE REQUEST SCHEDULE BROADCAST ERROR:", exc)

        return (
            f"Perubahan shift {employee_name} untuk {date_range_label} berhasil diterapkan."
            if shift_code else
            f"Jadwal manual {employee_name} untuk {date_range_label} berhasil dibersihkan."
        )

    if request_type == "shift_swap":
        requester_id = _to_int(payload.get("employee_id"))
        partner_id = _to_int(payload.get("swap_with_employee_id"))
        schedule_date = _parse_iso_date(payload.get("schedule_date"))
        requester_original_code = str(payload.get("requester_current_shift_code") or "").strip().upper()
        partner_original_code = str(payload.get("partner_current_shift_code") or "").strip().upper()
        requester_original_note = str(payload.get("requester_current_note") or "").strip()
        partner_original_note = str(payload.get("partner_current_note") or "").strip()
        reason = str(payload.get("reason") or "").strip()

        if not requester_id or not partner_id or requester_id == partner_id:
            raise ValueError("Data request tuker shift tidak valid.")
        if schedule_date is None:
            raise ValueError("Tanggal tuker shift tidak valid.")
        if not requester_original_code or not partner_original_code:
            raise ValueError("Kode shift tuker shift tidak lengkap.")
        if requester_original_code == partner_original_code:
            raise ValueError("Tukar shift tidak bisa diproses karena kedua staff punya shift yang sama.")

        requester = db.execute(
            "SELECT id, full_name, warehouse_id FROM employees WHERE id=?",
            (requester_id,),
        ).fetchone()
        partner = db.execute(
            "SELECT id, full_name, warehouse_id FROM employees WHERE id=?",
            (partner_id,),
        ).fetchone()
        if requester is None or partner is None:
            raise ValueError("Salah satu staff pada request tuker shift sudah tidak ditemukan.")

        requester_name = str(requester["full_name"] or payload.get("employee_name") or "Staff").strip()
        partner_name = str(partner["full_name"] or payload.get("swap_with_employee_name") or "Staff").strip()
        requester_snapshot = resolve_employee_schedule_for_date(db, requester_id, schedule_date)
        partner_snapshot = resolve_employee_schedule_for_date(db, partner_id, schedule_date)

        try:
            current_requester_code = _validate_schedule_shift_swap_snapshot(requester_snapshot, requester_name)
            current_partner_code = _validate_schedule_shift_swap_snapshot(partner_snapshot, partner_name)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        if (
            current_requester_code != requester_original_code
            or current_partner_code != partner_original_code
        ):
            raise ValueError(
                "Jadwal salah satu staff sudah berubah sejak request dibuat. Minta pengaju kirim ulang tuker shift terbaru."
            )

        schedule_date_iso = schedule_date.isoformat()
        for employee_id, shift_code, note in (
            (requester_id, partner_original_code, partner_original_note),
            (partner_id, requester_original_code, requester_original_note),
        ):
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
                    schedule_date_iso,
                    shift_code,
                    note or None,
                    session.get("user_id"),
                ),
            )

        requester_applied_label = str(
            partner_snapshot.get("label")
            or payload.get("partner_current_shift_label")
            or partner_original_code
        ).strip()
        partner_applied_label = str(
            requester_snapshot.get("label")
            or payload.get("requester_current_shift_label")
            or requester_original_code
        ).strip()
        schedule_date_label = (
            str(payload.get("schedule_date_label") or "").strip()
            or requester_snapshot.get("full_label")
            or partner_snapshot.get("full_label")
            or schedule_date_iso
        )
        warehouse_id = (
            _to_int(requester["warehouse_id"])
            or _to_int(partner["warehouse_id"])
            or _to_int(request_row.get("warehouse_id"))
        )
        schedule_message = (
            f"Tukar shift {requester_name} dan {partner_name} untuk {schedule_date_label} diterapkan. "
            f"{requester_name} menjadi {requester_applied_label} ({partner_original_code}), "
            f"{partner_name} menjadi {partner_applied_label} ({requester_original_code})."
        )
        if reason:
            schedule_message += f" Alasan: {reason}"
        event_id = create_schedule_change_event(
            db,
            warehouse_id=warehouse_id,
            event_kind="entry_update",
            title=f"Tukar Shift {requester_name} x {partner_name}",
            message=schedule_message,
            affected_employee_id=requester_id,
            affected_employee_name=requester_name,
            start_date=schedule_date_iso,
            end_date=schedule_date_iso,
            created_by=session.get("user_id"),
        )

        try:
            payload_notification = build_schedule_change_notification_payload(
                {
                    "id": event_id,
                    "title": schedule_message.split(".")[0],
                    "message": schedule_message,
                }
            )
            notify_broadcast(
                payload_notification["subject"],
                payload_notification["message"],
                warehouse_id=warehouse_id,
                push_title=payload_notification["push_title"],
                push_body=payload_notification["push_body"],
                push_url="/announcements/",
                push_tag=payload_notification["push_tag"],
                category="schedule",
                link_url="/announcements/",
                source_type="schedule_change",
                source_id=str(event_id),
            )
        except Exception as exc:
            print("ATTENDANCE REQUEST SHIFT SWAP BROADCAST ERROR:", exc)

        return f"Tukar shift {requester_name} dengan {partner_name} untuk {schedule_date_label} berhasil diterapkan."

    if request_type == "overtime_add":
        employee_id = _to_int(payload.get("employee_id"))
        adjustment_date = _parse_iso_date(payload.get("adjustment_date"))
        minutes_delta = _to_int(payload.get("minutes_delta"), default=None)
        note = str(payload.get("note") or "").strip()
        source_type = _normalize_overtime_add_source_type(payload.get("source_type"))
        employee = _get_accessible_employee(db, employee_id)
        if employee is None:
            raise ValueError("Staff untuk penambahan lembur tidak ditemukan.")
        employee = dict(employee)
        if adjustment_date is None:
            raise ValueError("Tanggal penambahan lembur tidak valid.")
        if minutes_delta is None or minutes_delta <= 0:
            raise ValueError("Durasi penambahan lembur tidak valid.")
        requested_minutes_delta = minutes_delta
        current_balance = _build_employee_overtime_balance(db, employee["id"])
        remaining_capacity_minutes = max(0, OVERTIME_BALANCE_CAP_MINUTES - int(current_balance["available_minutes"] or 0))
        minutes_delta = min(requested_minutes_delta, remaining_capacity_minutes)
        credited_duration_label = _format_duration_minutes_label(minutes_delta, zero_label="0 mnt")
        requested_duration_label = _format_duration_minutes_label(requested_minutes_delta)
        updated_payload = dict(payload)
        updated_payload["minutes_delta"] = minutes_delta
        updated_payload["duration_label"] = credited_duration_label
        if minutes_delta < requested_minutes_delta:
            updated_payload["requested_minutes_delta"] = requested_minutes_delta
            updated_payload["requested_duration_label"] = requested_duration_label
            updated_payload["cap_notice"] = (
                f"Saldo lembur dibatasi maksimal {_format_duration_minutes_label(OVERTIME_BALANCE_CAP_MINUTES)}."
            )
        breakdown_label = str(updated_payload.get("breakdown_label") or "").strip()
        summary_segments = [f"{credited_duration_label} pada {adjustment_date.isoformat()}"]
        if breakdown_label:
            summary_segments.append(breakdown_label)
        if minutes_delta < requested_minutes_delta:
            summary_segments.append(
                f"Request awal {requested_duration_label}, masuk {credited_duration_label} karena batas saldo {_format_duration_minutes_label(OVERTIME_BALANCE_CAP_MINUTES)}"
            )
        if request_row.get("id"):
            db.execute(
                """
                UPDATE attendance_action_requests
                SET payload=?,
                    summary_note=?,
                    updated_at=?
                WHERE id=?
                """,
                (
                    json.dumps(updated_payload, sort_keys=True, ensure_ascii=True),
                    " | ".join(segment for segment in summary_segments if segment),
                    _current_timestamp(),
                    request_row["id"],
                ),
            )
        if minutes_delta > 0:
            db.execute(
                """
                INSERT INTO overtime_balance_adjustments(
                    employee_id,
                    warehouse_id,
                    adjustment_date,
                    minutes_delta,
                    note,
                    handled_by,
                    updated_at
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    employee["id"],
                    employee["warehouse_id"],
                    adjustment_date.isoformat(),
                    minutes_delta,
                    note,
                    session.get("user_id"),
                    _current_timestamp(),
                ),
            )
        if source_type == "biometric_auto":
            if minutes_delta <= 0:
                return (
                    f"Lembur otomatis {employee['full_name']} tidak menambah saldo karena jatah maksimal "
                    f"{_format_duration_minutes_label(OVERTIME_BALANCE_CAP_MINUTES)} sudah penuh."
                )
            if minutes_delta < requested_minutes_delta:
                return (
                    f"Lembur otomatis {employee['full_name']} hanya {credited_duration_label} yang masuk ke saldo "
                    f"karena jatah maksimal {_format_duration_minutes_label(OVERTIME_BALANCE_CAP_MINUTES)}."
                )
            return f"Lembur otomatis {employee['full_name']} sebesar {credited_duration_label} berhasil masuk ke saldo."
        if minutes_delta <= 0:
            return (
                f"Penambahan lembur {employee['full_name']} tidak menambah saldo karena jatah maksimal "
                f"{_format_duration_minutes_label(OVERTIME_BALANCE_CAP_MINUTES)} sudah penuh."
            )
        if minutes_delta < requested_minutes_delta:
            return (
                f"Penambahan lembur {employee['full_name']} hanya {credited_duration_label} yang masuk "
                f"karena jatah maksimal {_format_duration_minutes_label(OVERTIME_BALANCE_CAP_MINUTES)}."
            )
        return f"Penambahan lembur {employee['full_name']} sebesar {credited_duration_label} berhasil diterapkan."

    if request_type == "overtime_use":
        employee_id = _to_int(payload.get("employee_id"))
        usage_date = _parse_iso_date(payload.get("usage_date"))
        minutes_used = _to_int(payload.get("minutes_used"), default=None)
        note = str(payload.get("note") or "").strip()
        usage_mode = _normalize_overtime_usage_mode(payload.get("usage_mode"))
        employee = _get_accessible_employee(db, employee_id)
        if employee is None:
            raise ValueError("Staff untuk pengurangan lembur tidak ditemukan.")
        employee = dict(employee)
        if usage_date is None:
            raise ValueError("Tanggal pengurangan lembur tidak valid.")
        overtime_balance = _build_employee_overtime_balance(db, employee["id"])
        if usage_mode == "cashout_all":
            if minutes_used is None or minutes_used <= 0:
                minutes_used = int(overtime_balance["available_minutes"] or 0)
            if minutes_used <= 0:
                raise ValueError("Saldo lembur saat ini kosong, jadi tidak ada yang bisa diuangkan.")
        elif minutes_used is None or minutes_used <= 0:
            raise ValueError("Durasi pengurangan lembur tidak valid.")
        if minutes_used > overtime_balance["available_minutes"]:
            raise ValueError("Saldo lembur saat ini tidak cukup untuk request tersebut.")
        if usage_mode != "cashout_all":
            weekly_usage_meta = _build_weekly_overtime_usage_meta(
                db,
                employee["id"],
                reference_date=usage_date,
            )
            if minutes_used > weekly_usage_meta["remaining_minutes"]:
                raise ValueError(
                    f"Pemakaian lembur reguler maksimal {weekly_usage_meta['limit_label']} per minggu. "
                    f"Sisa minggu ini hanya {weekly_usage_meta['remaining_label']} untuk periode {weekly_usage_meta['week_label']}."
                )
        db.execute(
            """
            INSERT INTO overtime_usage_records(
                employee_id,
                warehouse_id,
                usage_date,
                usage_mode,
                minutes_used,
                note,
                handled_by,
                updated_at
            )
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                employee["id"],
                employee["warehouse_id"],
                usage_date.isoformat(),
                usage_mode,
                minutes_used,
                note,
                session.get("user_id"),
                _current_timestamp(),
            ),
        )
        if usage_mode == "cashout_all":
            return f"Saldo lembur {employee['full_name']} sebesar {_format_duration_minutes_label(minutes_used)} berhasil diuangkan."
        return f"Pengurangan lembur {employee['full_name']} sebesar {_format_duration_minutes_label(minutes_used)} berhasil diterapkan."

    if request_type == "overtime_usage_delete":
        usage_id = _to_int(payload.get("usage_id"))
        usage = _get_overtime_usage_by_id(db, usage_id)
        if usage is None:
            raise ValueError("Riwayat pemakaian lembur untuk request ini sudah tidak tersedia.")
        db.execute("DELETE FROM overtime_usage_records WHERE id=?", (usage_id,))
        return f"Pembatalan pemakaian lembur {usage['full_name']} pada {usage['usage_date']} berhasil diterapkan."

    raise ValueError("Tipe request attendance belum didukung.")


def _build_payroll_summary(payroll_runs):
    return {
        "total": len(payroll_runs),
        "draft": sum(1 for record in payroll_runs if record["status"] == "draft"),
        "approved": sum(1 for record in payroll_runs if record["status"] == "approved"),
        "paid": sum(1 for record in payroll_runs if record["status"] == "paid"),
        "cancelled": sum(1 for record in payroll_runs if record["status"] == "cancelled"),
        "total_base_salary": round(sum((record["base_salary"] or 0) for record in payroll_runs), 2),
        "total_net_pay": round(sum((record["net_pay"] or 0) for record in payroll_runs), 2),
    }


def _build_recruitment_summary(recruitment_candidates):
    return {
        "total": len(recruitment_candidates),
        "interview": sum(1 for candidate in recruitment_candidates if candidate["stage"] == "interview"),
        "offer": sum(1 for candidate in recruitment_candidates if candidate["stage"] == "offer"),
        "hired": sum(1 for candidate in recruitment_candidates if candidate["stage"] == "hired" or candidate["status"] == "closed"),
        "active": sum(1 for candidate in recruitment_candidates if candidate["status"] == "active"),
        "closed": sum(1 for candidate in recruitment_candidates if candidate["status"] in {"closed", "rejected", "withdrawn"}),
    }


def _build_onboarding_summary(onboarding_records):
    return {
        "total": len(onboarding_records),
        "pending": sum(1 for record in onboarding_records if record["status"] == "pending"),
        "in_progress": sum(1 for record in onboarding_records if record["status"] == "in_progress"),
        "completed": sum(1 for record in onboarding_records if record["status"] == "completed"),
        "blocked": sum(1 for record in onboarding_records if record["status"] == "blocked"),
        "preboarding": sum(1 for record in onboarding_records if record["stage"] == "preboarding"),
        "go_live": sum(1 for record in onboarding_records if record["stage"] == "go_live"),
    }


def _build_offboarding_summary(offboarding_records):
    return {
        "total": len(offboarding_records),
        "planned": sum(1 for record in offboarding_records if record["status"] == "planned"),
        "in_progress": sum(1 for record in offboarding_records if record["status"] == "in_progress"),
        "completed": sum(1 for record in offboarding_records if record["status"] == "completed"),
        "cancelled": sum(1 for record in offboarding_records if record["status"] == "cancelled"),
        "notice": sum(1 for record in offboarding_records if record["stage"] == "notice"),
        "exit_complete": sum(1 for record in offboarding_records if record["stage"] == "exit_complete"),
    }


def _build_performance_summary(performance_reviews):
    total_score = sum((record["final_score"] or 0) for record in performance_reviews)
    count = len(performance_reviews)
    return {
        "total": count,
        "draft": sum(1 for record in performance_reviews if record["status"] == "draft"),
        "reviewed": sum(1 for record in performance_reviews if record["status"] == "reviewed"),
        "acknowledged": sum(1 for record in performance_reviews if record["status"] == "acknowledged"),
        "closed": sum(1 for record in performance_reviews if record["status"] == "closed"),
        "avg_score": round(total_score / count, 2) if count else 0,
    }


def _safe_json_loads(payload, default):
    if not payload:
        return default
    try:
        return json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _format_kpi_value_label(value, *, currency=False):
    try:
        numeric_value = float(value or 0)
    except (TypeError, ValueError):
        numeric_value = 0.0

    rounded_value = round(numeric_value, 2)
    if currency:
        return f"Rp {int(round(rounded_value)):,}".replace(",", ".")
    if abs(rounded_value - int(round(rounded_value))) < 0.0001:
        return str(int(round(rounded_value)))
    return f"{rounded_value:.2f}".rstrip("0").rstrip(".")


def _build_kpi_profile_snapshot(profile):
    safe_profile = dict(profile or {})
    return {
        "key": safe_profile.get("key"),
        "display_name": safe_profile.get("display_name"),
        "warehouse_group": safe_profile.get("warehouse_group"),
        "warehouse_label": safe_profile.get("warehouse_label"),
        "team_focus": list(safe_profile.get("team_focus") or []),
        "minimum_pass_score": float(safe_profile.get("minimum_pass_score") or 0),
        "summary": safe_profile.get("summary") or "",
        "metrics": [
            {
                "code": metric.get("code"),
                "group": metric.get("group"),
                "label": metric.get("label"),
                "unit": metric.get("unit"),
                "target": float(metric.get("target") or 0),
                "weight": float(metric.get("weight") or 0),
            }
            for metric in safe_profile.get("metrics", [])
        ],
    }


def _decorate_kpi_metric_entries(metric_entries):
    items = []
    for entry in metric_entries or []:
        safe_entry = dict(entry)
        safe_entry["target_label"] = _format_kpi_value_label(
            safe_entry.get("target"),
            currency=(safe_entry.get("unit") == "Rp"),
        )
        safe_entry["actual_label"] = _format_kpi_value_label(
            safe_entry.get("actual_value"),
            currency=(safe_entry.get("unit") == "Rp"),
        )
        safe_entry["achievement_percent"] = int(round(float(safe_entry.get("achievement_ratio") or 0) * 100))
        safe_entry["score_label"] = f"{float(safe_entry.get('score_value') or 0):.2f}".rstrip("0").rstrip(".")
        items.append(safe_entry)
    return items


def _decorate_kpi_staff_report_row(row):
    report = dict(row)
    report["metric_entries"] = _decorate_kpi_metric_entries(_safe_json_loads(report.get("metric_payload"), []))
    report["target_snapshot"] = _safe_json_loads(report.get("target_payload"), {})
    report["team_focus_items"] = _safe_json_loads(report.get("team_focus_payload"), [])
    report["period_label_human"] = format_kpi_period_label(report.get("period_label"))
    report["status_label"] = KPI_REPORT_STATUS_LABELS.get(
        report.get("status"),
        str(report.get("status") or "").replace("_", " ").title(),
    )
    report["score_label"] = f"{float(report.get('weighted_score') or 0):.2f}".rstrip("0").rstrip(".")
    report["completion_percent"] = int(round(float(report.get("completion_ratio") or 0) * 100))
    report["created_at_label"] = _format_hris_datetime_display(report.get("created_at"), include_date=True)
    report["reviewed_at_label"] = _format_hris_datetime_display(report.get("reviewed_at"), include_date=True)
    report["minimum_pass_score"] = float(report.get("target_snapshot", {}).get("minimum_pass_score") or 0)
    report["is_passed"] = float(report.get("weighted_score") or 0) >= report["minimum_pass_score"]
    return report


def _normalize_kpi_metric_code(value, fallback_index=1):
    safe_value = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return safe_value or f"metric_{int(max(1, fallback_index))}"


def _normalize_kpi_team_focus_items(value):
    if isinstance(value, str):
        raw_items = str(value).replace("\r", "\n").replace(",", "\n").split("\n")
    else:
        raw_items = list(value or [])
    items = []
    seen = set()
    for raw_item in raw_items:
        item = str(raw_item or "").strip()
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items


def _normalize_kpi_plan_metric_rows(metric_rows):
    normalized_rows = []
    seen_codes = set()
    for index, metric in enumerate(metric_rows or [], start=1):
        label = str((metric or {}).get("label") or "").strip()
        group = str((metric or {}).get("group") or "").strip() or "General"
        unit = str((metric or {}).get("unit") or "").strip() or "Poin"
        if not label:
            continue
        code = _normalize_kpi_metric_code((metric or {}).get("code") or label, index)
        suffix = 2
        base_code = code
        while code in seen_codes:
            code = f"{base_code}_{suffix}"
            suffix += 1
        seen_codes.add(code)
        normalized_rows.append(
            {
                "code": code,
                "group": group,
                "label": label,
                "unit": unit,
                "target": float((metric or {}).get("target") or 0),
                "weight": float((metric or {}).get("weight") or 0),
            }
        )
    return normalized_rows


def _extract_kpi_metric_rows_from_form(form):
    codes = form.getlist("metric_code[]")
    groups = form.getlist("metric_group[]")
    labels = form.getlist("metric_label[]")
    units = form.getlist("metric_unit[]")
    targets = form.getlist("metric_target[]")
    weights = form.getlist("metric_weight[]")
    row_count = max(len(codes), len(groups), len(labels), len(units), len(targets), len(weights))
    metric_rows = []
    for index in range(row_count):
        label = str(labels[index] if index < len(labels) else "").strip()
        group = str(groups[index] if index < len(groups) else "").strip()
        unit = str(units[index] if index < len(units) else "").strip()
        code = str(codes[index] if index < len(codes) else "").strip()
        target_raw = targets[index] if index < len(targets) else ""
        weight_raw = weights[index] if index < len(weights) else ""
        if not any([label, group, unit, str(target_raw).strip(), str(weight_raw).strip(), code]):
            continue
        if not label:
            raise ValueError("Label target KPI tidak boleh kosong.")
        target_value = _to_float(target_raw)
        weight_percent = _to_float(weight_raw)
        weight_value = weight_percent / 100 if weight_percent > 1 else weight_percent
        metric_rows.append(
            {
                "code": code,
                "group": group or "General",
                "label": label,
                "unit": unit or "Poin",
                "target": float(target_value or 0),
                "weight": float(weight_value or 0),
            }
        )
    normalized_rows = _normalize_kpi_plan_metric_rows(metric_rows)
    if not normalized_rows:
        raise ValueError("Minimal satu target KPI wajib diisi.")
    return normalized_rows


def _build_kpi_profile_from_plan_row(row):
    plan = dict(row or {})
    metric_rows = _normalize_kpi_plan_metric_rows(_safe_json_loads(plan.get("metric_payload"), []))
    team_focus_items = _normalize_kpi_team_focus_items(_safe_json_loads(plan.get("team_focus_payload"), []))
    warehouse_label = (
        str(plan.get("warehouse_label") or "").strip()
        or str(plan.get("warehouse_name") or "").strip()
        or "Gudang"
    )
    warehouse_group = (
        str(plan.get("warehouse_group") or "").strip().lower()
        or ("mega" if "mega" in warehouse_label.lower() else "mataram")
    )
    return {
        "id": plan.get("id"),
        "key": str(plan.get("template_key") or f"kpi-plan-{plan.get('employee_id') or 'staff'}-{plan.get('period_label') or 'periode'}"),
        "display_name": str(plan.get("template_name") or plan.get("full_name") or "Target KPI Staff").strip(),
        "warehouse_group": warehouse_group,
        "warehouse_label": warehouse_label,
        "aliases": [str(plan.get("full_name") or plan.get("template_name") or "").strip()],
        "metrics": metric_rows,
        "team_focus": team_focus_items,
        "minimum_pass_score": float(plan.get("minimum_pass_score") or 0),
        "summary": str(plan.get("summary") or "").strip(),
        "period_label": normalize_kpi_period_label(plan.get("period_label")),
    }


def _decorate_kpi_target_plan_row(row):
    plan = dict(row or {})
    profile = _build_kpi_profile_from_plan_row(plan)
    plan["profile"] = profile
    plan["metric_rows"] = _decorate_kpi_metric_entries(profile.get("metrics", []))
    for metric in plan["metric_rows"]:
        metric["weight_percent_label"] = f"{float(metric.get('weight') or 0) * 100:.2f}".rstrip("0").rstrip(".")
    plan["team_focus_items"] = profile.get("team_focus", [])
    plan["team_focus_text"] = "\n".join(plan["team_focus_items"])
    plan["period_label"] = profile.get("period_label")
    plan["period_label_human"] = format_kpi_period_label(plan.get("period_label"))
    plan["pass_score_label"] = f"{float(profile.get('minimum_pass_score') or 0):.2f}".rstrip("0").rstrip(".")
    plan["created_at_label"] = _format_hris_datetime_display(plan.get("created_at"), include_date=True)
    plan["updated_at_label"] = _format_hris_datetime_display(plan.get("updated_at"), include_date=True)
    plan["metric_count"] = len(plan["metric_rows"])
    return plan


def _fetch_kpi_target_plan_by_employee_period(db, employee_id, period_label, selected_warehouse=None):
    safe_employee_id = _to_int(employee_id)
    if not safe_employee_id:
        return None

    safe_period_label = normalize_kpi_period_label(period_label)
    scope_warehouse = get_hris_scope()
    safe_warehouse = scope_warehouse or selected_warehouse
    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            cu.username AS created_by_name,
            uu.username AS updated_by_name
        FROM kpi_target_plans p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users cu ON p.created_by = cu.id
        LEFT JOIN users uu ON p.updated_by = uu.id
        WHERE p.employee_id=? AND p.period_label=?
    """
    params = [safe_employee_id, safe_period_label]
    if safe_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(safe_warehouse)
    query += " LIMIT 1"
    row = db.execute(query, params).fetchone()
    return _decorate_kpi_target_plan_row(row) if row else None


def _resolve_effective_kpi_profile(db, linked_employee, period_label=None):
    if linked_employee:
        safe_employee = dict(linked_employee)
        target_plan = _fetch_kpi_target_plan_by_employee_period(
            db,
            safe_employee.get("id"),
            period_label or date_cls.today().isoformat(),
        )
        if target_plan:
            return target_plan["profile"]
        return resolve_kpi_profile(
            employee_name=safe_employee.get("full_name"),
            warehouse_name=safe_employee.get("warehouse_name"),
            work_location=safe_employee.get("work_location"),
            position=safe_employee.get("position"),
        )
    return resolve_kpi_profile()


def _fetch_kpi_target_plans(db):
    search = (request.args.get("q") or "").strip()
    period_label = normalize_kpi_period_label(request.args.get("period"))
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            cu.username AS created_by_name,
            uu.username AS updated_by_name
        FROM kpi_target_plans p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users cu ON p.created_by = cu.id
        LEFT JOIN users uu ON p.updated_by = uu.id
        WHERE 1=1
    """
    params = []

    if search:
        like = f"%{search}%"
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
                OR COALESCE(p.summary, '') LIKE ?
                OR COALESCE(p.template_name, '') LIKE ?
            )
        """
        params.extend([like, like, like, like, like, like])

    if selected_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(selected_warehouse)

    if period_label:
        query += " AND p.period_label=?"
        params.append(period_label)

    query += " ORDER BY p.period_label DESC, e.full_name COLLATE NOCASE ASC, p.id DESC"
    plans = [_decorate_kpi_target_plan_row(row) for row in db.execute(query, params).fetchall()]
    return plans, search, selected_warehouse, period_label


def _build_kpi_target_plan_summary(plans):
    safe_plans = list(plans or [])
    return {
        "total": len(safe_plans),
        "metrics": sum(int(item.get("metric_count") or 0) for item in safe_plans),
        "employees": len({item.get("employee_id") for item in safe_plans if item.get("employee_id")}),
        "avg_pass_score": round(
            sum(float(item.get("profile", {}).get("minimum_pass_score") or 0) for item in safe_plans) / len(safe_plans),
            2,
        )
        if safe_plans
        else 0,
    }


def _build_kpi_target_seed_profiles(db, employee_rows, period_label):
    seed_map = {}
    for employee in employee_rows or []:
        safe_employee = dict(employee)
        profile = _resolve_effective_kpi_profile(db, safe_employee, period_label=period_label)
        if not profile:
            continue
        seed_map[str(safe_employee.get("id"))] = {
            "template_name": profile.get("display_name"),
            "minimum_pass_score": float(profile.get("minimum_pass_score") or 0),
            "summary": profile.get("summary") or "",
            "team_focus_text": "\n".join(_normalize_kpi_team_focus_items(profile.get("team_focus") or [])),
            "metrics": [
                {
                    "code": metric.get("code"),
                    "group": metric.get("group"),
                    "label": metric.get("label"),
                    "unit": metric.get("unit"),
                    "target": float(metric.get("target") or 0),
                    "weight_percent": round(float(metric.get("weight") or 0) * 100, 4),
                }
                for metric in profile.get("metrics", [])
            ],
        }
    return seed_map


def _build_kpi_summary(kpi_reports):
    count = len(kpi_reports)
    total_score = sum(float(report.get("weighted_score") or 0) for report in kpi_reports)
    total_completion = sum(float(report.get("completion_ratio") or 0) for report in kpi_reports)
    return {
        "total": count,
        "submitted": sum(1 for report in kpi_reports if report.get("status") == "submitted"),
        "reviewed": sum(1 for report in kpi_reports if report.get("status") == "reviewed"),
        "follow_up": sum(1 for report in kpi_reports if report.get("status") == "follow_up"),
        "avg_score": round(total_score / count, 2) if count else 0,
        "avg_completion": round((total_completion / count) * 100, 2) if count else 0,
    }


def _get_kpi_staff_report_by_id(db, report_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            r.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS submitter_username,
            ru.username AS reviewed_by_name
        FROM kpi_staff_reports r
        JOIN employees e ON r.employee_id = e.id
        LEFT JOIN warehouses w ON r.warehouse_id = w.id
        LEFT JOIN users u ON r.user_id = u.id
        LEFT JOIN users ru ON r.reviewed_by = ru.id
        WHERE r.id=?
    """
    params = [report_id]

    if scope_warehouse:
        query += " AND r.warehouse_id=?"
        params.append(scope_warehouse)

    row = db.execute(query, params).fetchone()
    return _decorate_kpi_staff_report_row(row) if row else None


def _get_kpi_target_plan_by_id(db, plan_id):
    scope_warehouse = get_hris_scope()
    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            cu.username AS created_by_name,
            uu.username AS updated_by_name
        FROM kpi_target_plans p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users cu ON p.created_by = cu.id
        LEFT JOIN users uu ON p.updated_by = uu.id
        WHERE p.id=?
    """
    params = [plan_id]

    if scope_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(scope_warehouse)

    row = db.execute(query, params).fetchone()
    return _decorate_kpi_target_plan_row(row) if row else None


def _fetch_kpi_staff_reports(db):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip().lower()
    period_label = normalize_kpi_period_label(request.args.get("period"))
    week_key = (request.args.get("week") or "all").strip().upper()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            r.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS submitter_username,
            ru.username AS reviewed_by_name
        FROM kpi_staff_reports r
        JOIN employees e ON r.employee_id = e.id
        LEFT JOIN warehouses w ON r.warehouse_id = w.id
        LEFT JOIN users u ON r.user_id = u.id
        LEFT JOIN users ru ON r.reviewed_by = ru.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
                OR COALESCE(r.template_name, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like, like])

    if status in KPI_REPORT_STATUSES:
        query += " AND r.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND r.warehouse_id=?"
        params.append(selected_warehouse)

    if period_label:
        query += " AND r.period_label=?"
        params.append(period_label)

    if week_key in KPI_WEEK_OPTIONS:
        query += " AND r.week_key=?"
        params.append(week_key)

    query += " ORDER BY r.period_label DESC, r.week_key DESC, e.full_name COLLATE NOCASE ASC, r.id DESC"

    kpi_reports = [_decorate_kpi_staff_report_row(row) for row in db.execute(query, params).fetchall()]
    return kpi_reports, search, status, selected_warehouse, period_label, week_key


def _build_kpi_profile_reference_cards(selected_warehouse=None, warehouse_rows=None, search=""):
    warehouse_name_map = {}
    for row in warehouse_rows or []:
        try:
            warehouse_id = int(row["id"])
            warehouse_name_map[warehouse_id] = row["name"]
        except Exception:
            continue
    warehouse_group = None
    if selected_warehouse:
        resolved_name = warehouse_name_map.get(int(selected_warehouse), "")
        warehouse_group = "mega" if "mega" in str(resolved_name).lower() else "mataram"

    cards = []
    safe_search = str(search or "").strip().lower()
    for profile in get_kpi_profiles(warehouse_group):
        if safe_search:
            haystack = " ".join(
                [
                    profile.get("display_name", ""),
                    profile.get("warehouse_label", ""),
                    profile.get("summary", ""),
                    " ".join(item.get("label", "") for item in profile.get("metrics", [])),
                ]
            ).lower()
            if safe_search not in haystack:
                continue
        cards.append(
            {
                **profile,
                "metrics": _decorate_kpi_metric_entries(profile.get("metrics", [])),
                "pass_score_label": f"{float(profile.get('minimum_pass_score') or 0):.2f}".rstrip("0").rstrip("."),
            }
        )
    return cards


def _build_helpdesk_summary(helpdesk_tickets):
    return {
        "total": len(helpdesk_tickets),
        "open": sum(1 for ticket in helpdesk_tickets if ticket["status"] == "open"),
        "in_progress": sum(1 for ticket in helpdesk_tickets if ticket["status"] == "in_progress"),
        "resolved": sum(1 for ticket in helpdesk_tickets if ticket["status"] == "resolved"),
        "closed": sum(1 for ticket in helpdesk_tickets if ticket["status"] == "closed"),
        "urgent": sum(1 for ticket in helpdesk_tickets if ticket["priority"] == "urgent"),
        "assigned": sum(1 for ticket in helpdesk_tickets if ticket["assigned_to"]),
    }


def _build_asset_summary(asset_records):
    return {
        "total": len(asset_records),
        "allocated": sum(1 for record in asset_records if record["asset_status"] == "allocated"),
        "standby": sum(1 for record in asset_records if record["asset_status"] == "standby"),
        "maintenance": sum(1 for record in asset_records if record["asset_status"] == "maintenance"),
        "returned": sum(1 for record in asset_records if record["asset_status"] == "returned"),
        "good": sum(1 for record in asset_records if record["condition_status"] == "good"),
        "damaged": sum(1 for record in asset_records if record["condition_status"] == "damaged"),
    }


def _build_project_summary(project_records):
    total_progress = sum((record["progress_percent"] or 0) for record in project_records)
    count = len(project_records)
    overdue_count = 0
    today_value = date_cls.today().isoformat()
    for record in project_records:
        due_date = record["due_date"] or ""
        if due_date and due_date < today_value and record["status"] not in {"completed", "cancelled"}:
            overdue_count += 1

    return {
        "total": count,
        "planning": sum(1 for record in project_records if record["status"] == "planning"),
        "active": sum(1 for record in project_records if record["status"] == "active"),
        "on_hold": sum(1 for record in project_records if record["status"] == "on_hold"),
        "completed": sum(1 for record in project_records if record["status"] == "completed"),
        "cancelled": sum(1 for record in project_records if record["status"] == "cancelled"),
        "critical": sum(1 for record in project_records if record["priority"] == "critical"),
        "avg_progress": round(total_progress / count, 2) if count else 0,
        "overdue": overdue_count,
    }


def _build_biometric_summary(biometric_logs):
    locations = {
        (log.get("location_display") or "").strip()
        for log in biometric_logs
        if (log.get("location_display") or "").strip() and (log.get("location_display") or "").strip() != "-"
    }
    employee_ids = {log["employee_id"] for log in biometric_logs if log.get("employee_id")}
    accuracies = [
        float(log["accuracy_m"])
        for log in biometric_logs
        if log.get("accuracy_m") not in (None, "")
    ]
    return {
        "total": len(biometric_logs),
        "queued": sum(1 for log in biometric_logs if log["sync_status"] == "queued"),
        "synced": sum(1 for log in biometric_logs if log["sync_status"] == "synced"),
        "manual": sum(1 for log in biometric_logs if log["sync_status"] == "manual"),
        "failed": sum(1 for log in biometric_logs if log["sync_status"] == "failed"),
        "check_in": sum(1 for log in biometric_logs if log["punch_type"] == "check_in"),
        "check_out": sum(1 for log in biometric_logs if log["punch_type"] == "check_out"),
        "verified": sum(1 for log in biometric_logs if log["sync_status"] in {"synced", "manual"}),
        "review": sum(1 for log in biometric_logs if log["sync_status"] == "queued"),
        "flagged": sum(1 for log in biometric_logs if log["sync_status"] == "failed"),
        "locations": len(locations),
        "employees": len(employee_ids),
        "avg_accuracy": round(sum(accuracies) / len(accuracies), 2) if accuracies else 0,
    }


def _build_announcement_summary(announcements):
    return {
        "total": len(announcements),
        "draft": sum(1 for record in announcements if record["status"] == "draft"),
        "published": sum(1 for record in announcements if record["status"] == "published"),
        "archived": sum(1 for record in announcements if record["status"] == "archived"),
        "leaders": sum(1 for record in announcements if record["audience"] == "leaders"),
        "warehouse_team": sum(1 for record in announcements if record["audience"] == "warehouse_team"),
    }


def _clamp_dashboard_schedule_days(value):
    days = _to_int(value, 14)
    return days if days in DASHBOARD_SCHEDULE_DAY_OPTIONS else 14


def _resolve_dashboard_warehouse(warehouses):
    selected_warehouse = _to_int(request.args.get("warehouse"))
    valid_ids = {warehouse["id"] for warehouse in warehouses}
    return selected_warehouse if selected_warehouse in valid_ids else None


def _build_dashboard_schedule_snapshot(db, selected_warehouse, start_date, days):
    _seed_schedule_shift_codes(db)
    _, _, shift_code_map = _fetch_schedule_shift_codes(db)

    employee_rows = _fetch_schedule_employees(db, selected_warehouse)
    schedule_members = _build_schedule_members(employee_rows)
    end_date = start_date + timedelta(days=days - 1)

    entry_map = _build_schedule_entry_map(
        db,
        [member["employee_id"] for member in schedule_members],
        start_date,
        end_date,
        shift_code_map,
    )
    override_map = _build_schedule_override_map(db, schedule_members, start_date, end_date)
    day_notes = _build_schedule_day_notes(db, start_date, end_date)
    board_rows = _build_schedule_board_rows(
        schedule_members,
        start_date,
        end_date,
        entry_map,
        override_map,
        day_notes,
    )

    preview_members = schedule_members[:DASHBOARD_SCHEDULE_PREVIEW_LIMIT]
    preview_count = len(preview_members)
    preview_rows = []
    total_assigned_cells = 0
    override_cells = 0
    manual_cells = 0

    for row in board_rows:
        row_assigned = 0
        row_override = 0
        row_manual = 0
        code_counts = defaultdict(int)

        for cell in row["cells"]:
            if not cell:
                continue
            row_assigned += 1
            total_assigned_cells += 1
            code_counts[cell["code"]] += 1
            if cell["source"] == "manual":
                row_manual += 1
                manual_cells += 1
            else:
                row_override += 1
                override_cells += 1

        highlight_items = [
            {"code": code, "count": count}
            for code, count in sorted(code_counts.items(), key=lambda item: (-item[1], item[0]))[:4]
        ]

        preview_rows.append(
            {
                "iso_date": row["iso_date"],
                "label": row["label"],
                "is_weekend": row["is_weekend"],
                "note": row["note"],
                "cells": row["cells"][:preview_count],
                "assigned_count": row_assigned,
                "override_count": row_override,
                "manual_count": row_manual,
                "highlights": highlight_items,
            }
        )

    return {
        "members": schedule_members,
        "preview_members": preview_members,
        "preview_rows": preview_rows,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "days": days,
        "assigned_cells": total_assigned_cells,
        "override_cells": override_cells,
        "manual_cells": manual_cells,
        "day_notes": sum(1 for row in preview_rows if row["note"]),
        "note_dates": [row["iso_date"] for row in preview_rows if row["note"]],
        "remaining_members": max(0, len(schedule_members) - preview_count),
    }


def _build_dashboard_schedule_sections(db, warehouses, selected_warehouse, start_date, days):
    selected_sections = []
    if selected_warehouse:
        selected_sections = [dict(warehouse) for warehouse in warehouses if warehouse["id"] == selected_warehouse]
    else:
        selected_sections = [dict(warehouse) for warehouse in warehouses]

    sections = []
    member_ids = set()
    note_dates = set()
    assigned_cells = 0
    override_cells = 0
    manual_cells = 0

    for warehouse in selected_sections:
        snapshot = _build_dashboard_schedule_snapshot(db, warehouse["id"], start_date, days)
        snapshot["warehouse_id"] = warehouse["id"]
        snapshot["warehouse_name"] = warehouse["name"]
        snapshot["board_url"] = (
            f"/schedule/?start={snapshot['start']}&days={snapshot['days']}&warehouse={warehouse['id']}"
        )
        sections.append(snapshot)

        member_ids.update(member["employee_id"] for member in snapshot["members"])
        note_dates.update(snapshot.get("note_dates", []))
        assigned_cells += snapshot["assigned_cells"]
        override_cells += snapshot["override_cells"]
        manual_cells += snapshot["manual_cells"]

    if not sections and selected_warehouse:
        fallback_snapshot = _build_dashboard_schedule_snapshot(db, selected_warehouse, start_date, days)
        fallback_snapshot["warehouse_id"] = selected_warehouse
        fallback_snapshot["warehouse_name"] = "Gudang"
        fallback_snapshot["board_url"] = (
            f"/schedule/?start={fallback_snapshot['start']}&days={fallback_snapshot['days']}&warehouse={selected_warehouse}"
        )
        sections.append(fallback_snapshot)
        member_ids.update(member["employee_id"] for member in fallback_snapshot["members"])
        note_dates.update(fallback_snapshot.get("note_dates", []))
        assigned_cells += fallback_snapshot["assigned_cells"]
        override_cells += fallback_snapshot["override_cells"]
        manual_cells += fallback_snapshot["manual_cells"]

    start_value = start_date.isoformat()
    end_value = (start_date + timedelta(days=days - 1)).isoformat()
    if sections:
        start_value = sections[0]["start"]
        end_value = sections[0]["end"]

    return {
        "sections": sections,
        "start": start_value,
        "end": end_value,
        "days": days,
        "member_total": len(member_ids),
        "assigned_cells": assigned_cells,
        "override_cells": override_cells,
        "manual_cells": manual_cells,
        "day_notes": len(note_dates),
    }


def _fetch_dashboard_leave_alerts(db, selected_warehouse):
    query = """
        SELECT
            l.id,
            l.leave_type,
            l.start_date,
            l.end_date,
            l.total_days,
            l.status,
            l.reason,
            l.note,
            l.created_at,
            l.updated_at,
            e.employee_code,
            e.full_name,
            w.name AS warehouse_name
        FROM leave_requests l
        LEFT JOIN employees e ON e.id = l.employee_id
        LEFT JOIN warehouses w ON w.id = l.warehouse_id
        WHERE l.status='pending'
    """
    params = []
    if selected_warehouse:
        query += " AND l.warehouse_id=?"
        params.append(selected_warehouse)
    query += " ORDER BY COALESCE(l.updated_at, l.created_at) DESC, l.id DESC LIMIT ?"
    params.append(DASHBOARD_LEAVE_ALERT_LIMIT)

    rows = [_decorate_leave_record(row) for row in db.execute(query, params).fetchall()]
    for row in rows:
        row["employee_label"] = row["full_name"] or row["employee_code"] or "Karyawan"
    return rows


def _build_dashboard_leave_alert_summary(rows):
    return {
        "total": len(rows),
        "sick": sum(1 for row in rows if row.get("special_leave_reason_code") == "sick"),
        "permit": sum(1 for row in rows if row.get("special_leave_reason_code") == "permit"),
        "annual": sum(1 for row in rows if row.get("special_leave_reason_code") == "annual"),
        "special": sum(1 for row in rows if _is_special_leave_bucket(row.get("leave_type"))),
    }


def _fetch_dashboard_reminders(db, selected_warehouse, reminder_date):
    query = """
        SELECT
            r.*,
            w.name AS warehouse_name,
            cu.username AS created_by_name,
            uu.username AS updated_by_name
        FROM dashboard_reminders r
        LEFT JOIN warehouses w ON w.id = r.warehouse_id
        LEFT JOIN users cu ON cu.id = r.created_by
        LEFT JOIN users uu ON uu.id = r.updated_by
        WHERE r.reminder_date=?
    """
    params = [reminder_date]

    if selected_warehouse:
        query += " AND (r.warehouse_id IS NULL OR r.warehouse_id=?)"
        params.append(selected_warehouse)

    query += " ORDER BY CASE WHEN r.status='open' THEN 0 ELSE 1 END, r.id DESC LIMIT ?"
    params.append(DASHBOARD_REMINDER_LIMIT)

    rows = [dict(row) for row in db.execute(query, params).fetchall()]
    for row in rows:
        row["status_label"] = DASHBOARD_REMINDER_STATUS_LABELS.get(row["status"], row["status"])
        row["scope_label"] = row["warehouse_name"] or "Semua Gudang"
    return rows


def _build_dashboard_reminder_summary(rows):
    return {
        "total": len(rows),
        "open": sum(1 for row in rows if row["status"] == "open"),
        "done": sum(1 for row in rows if row["status"] == "done"),
    }


def _build_dashboard_summary(db, warehouses):
    selected_warehouse = _resolve_dashboard_warehouse(warehouses)
    schedule_start = _parse_iso_date(request.args.get("schedule_start")) or date_cls.today()
    schedule_days = _clamp_dashboard_schedule_days(request.args.get("days"))
    today_value = date_cls.today().isoformat()

    announcement_query = """
        SELECT
            a.id,
            a.title,
            a.audience,
            a.publish_date,
            a.expires_at,
            a.status,
            a.channel,
            a.message,
            a.warehouse_id,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM announcement_posts a
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        LEFT JOIN users u ON a.handled_by = u.id
        WHERE a.status='published'
          AND (a.publish_date IS NULL OR a.publish_date='' OR a.publish_date<=?)
          AND (a.expires_at IS NULL OR a.expires_at='' OR a.expires_at>=?)
    """
    announcement_params = [today_value, today_value]
    if selected_warehouse:
        announcement_query += " AND a.warehouse_id=?"
        announcement_params.append(selected_warehouse)
    announcement_query += " ORDER BY a.publish_date DESC, a.id DESC LIMIT ?"
    announcement_params.append(DASHBOARD_ANNOUNCEMENT_LIMIT)
    active_announcements = [
        dict(row)
        for row in db.execute(announcement_query, announcement_params).fetchall()
    ]

    draft_query = "SELECT COUNT(*) FROM announcement_posts WHERE status='draft'"
    draft_params = []
    if selected_warehouse:
        draft_query += " AND warehouse_id=?"
        draft_params.append(selected_warehouse)
    announcement_draft_count = db.execute(draft_query, draft_params).fetchone()[0]

    schedule_snapshot = _build_dashboard_schedule_sections(
        db,
        warehouses,
        selected_warehouse,
        schedule_start,
        schedule_days,
    )
    leave_alerts = _fetch_dashboard_leave_alerts(db, selected_warehouse)
    leave_alert_summary = _build_dashboard_leave_alert_summary(leave_alerts)
    dashboard_reminders = _fetch_dashboard_reminders(db, selected_warehouse, schedule_snapshot["start"])
    reminder_summary = _build_dashboard_reminder_summary(dashboard_reminders)

    return {
        "filters": {
            "warehouse_id": selected_warehouse,
            "schedule_start": schedule_snapshot["start"],
            "days": schedule_snapshot["days"],
        },
        "announcements": active_announcements,
        "announcement_summary": {
            "active": len(active_announcements),
            "draft": announcement_draft_count,
            "leaders": sum(1 for item in active_announcements if item["audience"] == "leaders"),
            "warehouse_team": sum(
                1 for item in active_announcements if item["audience"] == "warehouse_team"
            ),
        },
        "leave_alerts": leave_alerts,
        "leave_alert_summary": leave_alert_summary,
        "reminders": dashboard_reminders,
        "reminder_summary": reminder_summary,
        "schedule": schedule_snapshot,
    }


def _build_document_summary(documents):
    today_value = date_cls.today().isoformat()
    return {
        "total": len(documents),
        "draft": sum(1 for record in documents if record["status"] == "draft"),
        "active": sum(1 for record in documents if record["status"] == "active"),
        "archived": sum(1 for record in documents if record["status"] == "archived"),
        "policy": sum(1 for record in documents if record["document_type"] == "policy"),
        "review_due": sum(
            1
            for record in documents
            if record["review_date"]
            and record["review_date"] <= today_value
            and record["status"] == "active"
        ),
    }


def _fetch_daily_live_reports(db, selected_warehouse):
    search = (request.args.get("daily_q") or "").strip()
    report_type = (request.args.get("daily_type") or "all").strip().lower()
    status = (request.args.get("daily_status") or "active").strip().lower()
    date_from = _parse_iso_date((request.args.get("daily_date_from") or "").strip())
    date_to = _parse_iso_date((request.args.get("daily_date_to") or "").strip())
    today_value = date_cls.today()

    if not date_from and not date_to:
        date_from = today_value
        date_to = today_value
    elif date_from and not date_to:
        date_to = date_from
    elif date_to and not date_from:
        date_from = date_to

    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from

    query = """
        SELECT
            r.*,
            u.username,
            u.role AS user_role,
            e.full_name AS employee_name,
            w.name AS warehouse_name,
            hu.username AS handled_username
        FROM daily_live_reports r
        LEFT JOIN users u ON u.id = r.user_id
        LEFT JOIN employees e ON e.id = r.employee_id
        LEFT JOIN warehouses w ON w.id = r.warehouse_id
        LEFT JOIN users hu ON hu.id = r.handled_by
        WHERE 1=1
    """
    params = []

    if selected_warehouse:
        query += " AND r.warehouse_id=?"
        params.append(selected_warehouse)

    if search:
        like = f"%{search}%"
        query += """
            AND (
                COALESCE(r.title, '') LIKE ?
                OR COALESCE(r.summary, '') LIKE ?
                OR COALESCE(r.blocker_note, '') LIKE ?
                OR COALESCE(r.follow_up_note, '') LIKE ?
                OR COALESCE(u.username, '') LIKE ?
                OR COALESCE(e.full_name, '') LIKE ?
            )
        """
        params.extend([like, like, like, like, like, like])

    if report_type in DAILY_LIVE_REPORT_TYPES:
        query += " AND r.report_type=?"
        params.append(report_type)
    else:
        report_type = "all"

    if status == "active":
        query += " AND r.status IN (?,?)"
        params.extend(DAILY_LIVE_REPORT_ACTIVE_STATUSES)
    elif status == "archived":
        query += " AND r.status IN (?,?)"
        params.extend(DAILY_LIVE_REPORT_ARCHIVE_STATUSES)
    elif status in DAILY_LIVE_REPORT_STATUSES:
        query += " AND r.status=?"
        params.append(status)
    else:
        status = "active"

    if date_from:
        query += " AND r.report_date >= ?"
        params.append(date_from.isoformat())

    if date_to:
        query += " AND r.report_date <= ?"
        params.append(date_to.isoformat())

    query += " ORDER BY r.report_date DESC, r.created_at DESC, r.id DESC"

    rows = [dict(row) for row in db.execute(query, params).fetchall()]
    live_schedule_lookup = _build_live_report_schedule_lookup(db, rows)
    for row in rows:
        row["report_type_label"] = DAILY_LIVE_REPORT_TYPE_LABELS.get(row["report_type"], row["report_type"])
        row["status_label"] = DAILY_LIVE_REPORT_STATUS_LABELS.get(row["status"], row["status"])
        row["display_name"] = row["employee_name"] or row["username"] or "User"
        row["attachment_url"] = _get_daily_live_report_attachment_url(row.get("attachment_path"))
        row["attachment_size_label"] = _format_upload_size(row.get("attachment_size"))
        if row.get("report_type") == "live":
            row.update(
                _build_live_report_schedule_match_meta(
                    row,
                    live_schedule_lookup.get(
                        (
                            row.get("employee_id"),
                            row.get("warehouse_id"),
                            row.get("report_date"),
                        ),
                        [],
                    ),
                )
            )
    return rows, {
        "search": search,
        "report_type": report_type,
        "status": status,
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
    }


def _build_daily_live_report_summary(rows):
    return {
        "total": len(rows),
        "daily": sum(1 for row in rows if row["report_type"] == "daily"),
        "live": sum(1 for row in rows if row["report_type"] == "live"),
        "submitted": sum(1 for row in rows if row["status"] == "submitted"),
        "reviewed": sum(1 for row in rows if row["status"] == "reviewed"),
        "follow_up": sum(1 for row in rows if row["status"] == "follow_up"),
        "closed": sum(1 for row in rows if row["status"] == "closed"),
        "archived": sum(1 for row in rows if row["status"] in DAILY_LIVE_REPORT_ARCHIVE_STATUSES),
    }


def _split_daily_live_report_rows(rows):
    return {
        "daily": [row for row in rows if row["report_type"] == "daily"],
        "live": [row for row in rows if row["report_type"] == "live"],
    }


def _format_live_report_time_label(raw_value):
    safe_value = (raw_value or "").strip()
    if not safe_value:
        return "-"
    try:
        parsed = datetime.fromisoformat(safe_value.replace("T", " "))
    except ValueError:
        return "-"
    return parsed.strftime("%H:%M")


def _parse_live_schedule_slot_window(slot_key):
    safe_key = (slot_key or "").strip()
    if not safe_key:
        return None, None
    if "-" in safe_key:
        start_text, end_text = [part.strip() for part in safe_key.split("-", 1)]
        return _parse_time_of_day_minutes(start_text), _parse_time_of_day_minutes(end_text)

    start_minutes = _parse_time_of_day_minutes(safe_key)
    if start_minutes is None:
        return None, None
    return start_minutes, start_minutes + 59


def _format_live_schedule_slot_display(slot_key, channel_label=None):
    slot_label = LIVE_SCHEDULE_SLOT_LABELS.get(slot_key, slot_key)
    safe_channel = (channel_label or "").strip()
    if safe_channel:
        return f"{slot_label} ({safe_channel})"
    return slot_label


def _build_live_report_schedule_lookup(db, rows):
    live_keys = {
        (row.get("employee_id"), row.get("warehouse_id"), row.get("report_date"))
        for row in rows
        if row.get("report_type") == "live"
        and row.get("employee_id")
        and row.get("warehouse_id")
        and row.get("report_date")
    }
    if not live_keys:
        return {}

    employee_ids = sorted({key[0] for key in live_keys})
    warehouse_ids = sorted({key[1] for key in live_keys})
    report_dates = sorted({key[2] for key in live_keys})
    employee_placeholders = ",".join(["?"] * len(employee_ids))
    warehouse_placeholders = ",".join(["?"] * len(warehouse_ids))
    date_placeholders = ",".join(["?"] * len(report_dates))

    schedule_rows = [
        dict(row)
        for row in db.execute(
            f"""
            SELECT warehouse_id, schedule_date, slot_key, employee_id, channel_label, note
            FROM schedule_live_entries
            WHERE employee_id IN ({employee_placeholders})
              AND warehouse_id IN ({warehouse_placeholders})
              AND schedule_date IN ({date_placeholders})
            ORDER BY schedule_date ASC, slot_key ASC, id ASC
            """,
            [*employee_ids, *warehouse_ids, *report_dates],
        ).fetchall()
    ]

    lookup = defaultdict(list)
    for row in schedule_rows:
        lookup[(row["employee_id"], row["warehouse_id"], row["schedule_date"])].append(row)
    return lookup


def _build_live_report_schedule_match_meta(report, scheduled_rows):
    submitted_time_label = _format_live_report_time_label(report.get("created_at"))
    submitted_minutes = _parse_time_of_day_minutes(submitted_time_label)
    scheduled_rows = list(scheduled_rows or [])
    scheduled_labels = [
        _format_live_schedule_slot_display(row.get("slot_key"), row.get("channel_label"))
        for row in scheduled_rows
    ]

    base_meta = {
        "live_submitted_time_label": submitted_time_label,
        "live_schedule_slots_label": " | ".join(scheduled_labels) if scheduled_labels else "-",
        "live_schedule_match_label": "Belum Dicek",
        "live_schedule_match_badge": "",
        "live_schedule_match_detail": "Belum ada evaluasi kecocokan jadwal live.",
    }

    if not report.get("employee_id"):
        return {
            **base_meta,
            "live_schedule_match_label": "Belum Tertaut",
            "live_schedule_match_badge": "orange",
            "live_schedule_match_detail": "Report live ini belum terhubung ke data staff, jadi jadwal live tidak bisa diverifikasi.",
        }

    if submitted_minutes is None:
        return {
            **base_meta,
            "live_schedule_match_label": "Jam Tidak Valid",
            "live_schedule_match_badge": "red",
            "live_schedule_match_detail": "Jam kirim report live tidak valid untuk dicek ke jadwal.",
        }

    if not scheduled_rows:
        return {
            **base_meta,
            "live_schedule_match_label": "Belum Dijadwal",
            "live_schedule_match_badge": "red",
            "live_schedule_match_detail": f"Dikirim {submitted_time_label}. Tidak ada jadwal live untuk staff ini pada tanggal report.",
        }

    matched_row = None
    for row in scheduled_rows:
        slot_start_minutes, slot_end_minutes = _parse_live_schedule_slot_window(row.get("slot_key"))
        if slot_start_minutes is None or slot_end_minutes is None:
            continue
        if slot_start_minutes <= submitted_minutes <= slot_end_minutes:
            matched_row = row
            break

    if matched_row:
        matched_label = _format_live_schedule_slot_display(
            matched_row.get("slot_key"),
            matched_row.get("channel_label"),
        )
        return {
            **base_meta,
            "live_schedule_match_label": "Sesuai Jadwal",
            "live_schedule_match_badge": "green",
            "live_schedule_match_detail": f"Dikirim {submitted_time_label}. Cocok dengan slot {matched_label}.",
        }

    return {
        **base_meta,
        "live_schedule_match_label": "Tidak Sesuai",
        "live_schedule_match_badge": "orange",
        "live_schedule_match_detail": f"Dikirim {submitted_time_label}. Jadwal live staff: {' | '.join(scheduled_labels)}.",
    }


def _build_report_snapshot(db):
    scope_warehouse = get_hris_scope()
    selected_warehouse = scope_warehouse or _to_int(request.args.get("warehouse"))
    base_params = [selected_warehouse] if selected_warehouse else []

    def count_from(table_name, extra_where="", extra_params=None):
        query = f"SELECT COUNT(*) FROM {table_name} WHERE 1=1"
        params = list(base_params)
        if selected_warehouse:
            query += " AND warehouse_id=?"
        if extra_where:
            query += f" AND {extra_where}"
            if extra_params:
                params.extend(extra_params)
        return db.execute(query, params).fetchone()[0]

    def avg_from(table_name, column_name):
        query = f"SELECT AVG({column_name}) FROM {table_name} WHERE 1=1"
        params = list(base_params)
        if selected_warehouse:
            query += " AND warehouse_id=?"
        value = db.execute(query, params).fetchone()[0]
        return round(value or 0, 2)

    total_employees = count_from("employees")
    active_employees = count_from("employees", "employment_status=?", ["active"])
    probation_employees = count_from("employees", "employment_status=?", ["probation"])
    leave_employees = count_from("employees", "employment_status=?", ["leave"])

    open_leave = count_from("leave_requests", "status=?", ["pending"])
    active_recruitment = count_from("recruitment_candidates", "status=?", ["active"])
    onboarding_live = count_from("onboarding_records", "status=?", ["in_progress"])
    offboarding_live = count_from("offboarding_records", "status IN (?,?)", ["planned", "in_progress"])
    helpdesk_open = count_from("helpdesk_tickets", "status IN (?,?)", ["open", "in_progress"])
    pending_approvals = open_leave
    biometric_queue = count_from("biometric_logs", "sync_status=?", ["queued"])
    published_announcements = count_from("announcement_posts", "status=?", ["published"])
    active_documents = count_from("document_records", "status=?", ["active"])
    pending_daily_reports = count_from("daily_live_reports", "status IN (?,?)", ["submitted", "follow_up"])
    pending_daily_report_logs = count_from(
        "daily_live_reports",
        "report_type=? AND status IN (?,?)",
        ["daily", "submitted", "follow_up"],
    )
    pending_live_report_logs = count_from(
        "daily_live_reports",
        "report_type=? AND status IN (?,?)",
        ["live", "submitted", "follow_up"],
    )
    paid_payroll = count_from("payroll_runs", "status=?", ["paid"])
    avg_score = avg_from("performance_reviews", "final_score")
    daily_reports, daily_report_filters = _fetch_daily_live_reports(db, selected_warehouse)
    daily_report_summary = _build_daily_live_report_summary(daily_reports)
    daily_report_groups = _split_daily_live_report_rows(daily_reports)

    warehouse_name = "Semua Gudang"
    if selected_warehouse:
        warehouse = db.execute("SELECT name FROM warehouses WHERE id=?", (selected_warehouse,)).fetchone()
        if warehouse:
            warehouse_name = warehouse["name"]

    summary = {
        "total_employees": total_employees,
        "open_ops": open_leave + onboarding_live + offboarding_live + helpdesk_open + biometric_queue + pending_daily_reports,
        "pending_approvals": pending_approvals,
        "avg_score": avg_score,
        "warehouse_name": warehouse_name,
        "snapshot_at": _current_timestamp(),
    }

    workforce_rows = [
        {"label": "Total Karyawan", "value": total_employees, "detail": "Headcount dalam scope report saat ini."},
        {"label": "Karyawan Aktif", "value": active_employees, "detail": "Resource inti yang siap operasional."},
        {"label": "Probation", "value": probation_employees, "detail": "Perlu onboarding dan evaluasi dekat."},
        {"label": "Status Leave", "value": leave_employees, "detail": "Karyawan yang sedang leave dari master status."},
    ]
    pipeline_rows = [
        {"module": "Leave", "value": open_leave, "detail": "Pengajuan leave yang masih menunggu proses."},
        {"module": "Recruitment", "value": active_recruitment, "detail": "Kandidat aktif dalam hiring pipeline."},
        {"module": "Onboarding", "value": onboarding_live, "detail": "Onboarding yang sedang berjalan."},
        {"module": "Offboarding", "value": offboarding_live, "detail": "Exit flow yang masih aktif."},
    ]
    service_rows = [
        {"module": "Helpdesk", "value": helpdesk_open, "detail": "Ticket support yang masih terbuka atau dikerjakan."},
        {"module": "Approval HR", "value": pending_approvals, "detail": "Leave request yang masih menunggu keputusan HR."},
        {"module": "Geotag Review", "value": biometric_queue, "detail": "Log geotag yang masih menunggu review atau verifikasi."},
        {"module": "Published Announcement", "value": published_announcements, "detail": "Pengumuman aktif yang sedang tayang."},
        {"module": "Active Documents", "value": active_documents, "detail": "Dokumen kerja yang sedang berlaku."},
        {"module": "Daily Report Log", "value": pending_daily_report_logs, "detail": "Report harian yang masih menunggu review atau follow up HR."},
        {"module": "Live Report Log", "value": pending_live_report_logs, "detail": "Live report yang masih menunggu review atau follow up HR."},
        {"module": "Payroll Paid", "value": paid_payroll, "detail": "Run payroll yang sudah dibayar."},
        {"module": "Avg Performance", "value": f'{avg_score:.2f}', "detail": "Rata-rata skor review performa."},
    ]

    filters = {"warehouse_id": selected_warehouse}
    filters.update(daily_report_filters)
    return (
        summary,
        filters,
        workforce_rows,
        pipeline_rows,
        service_rows,
        daily_reports,
        daily_report_summary,
        daily_report_groups,
    )


def _fetch_employees(db):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            e.*,
            w.name AS warehouse_name
        FROM employees e
        LEFT JOIN warehouses w ON e.warehouse_id = w.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if status in EMPLOYEE_STATUSES:
        query += " AND e.employment_status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND e.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY e.full_name COLLATE NOCASE ASC, e.id DESC"

    employees = [dict(row) for row in db.execute(query, params).fetchall()]
    return employees, search, status, selected_warehouse


def _fetch_attendance_records(db):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip().lower()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            a.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name
        FROM attendance_records a
        JOIN employees e ON a.employee_id = e.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if status in ATTENDANCE_STATUSES:
        query += " AND a.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(selected_warehouse)

    if date_from:
        query += " AND a.attendance_date>=?"
        params.append(date_from)

    if date_to:
        query += " AND a.attendance_date<=?"
        params.append(date_to)

    query += " ORDER BY a.attendance_date DESC, e.full_name COLLATE NOCASE ASC, a.id DESC"

    attendance_records = [dict(row) for row in db.execute(query, params).fetchall()]
    return attendance_records, search, status, selected_warehouse, date_from, date_to


def _fetch_leave_requests(db):
    search = (request.args.get("q") or "").strip()
    leave_type = (request.args.get("leave_type") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            l.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM leave_requests l
        JOIN employees e ON l.employee_id = e.id
        LEFT JOIN warehouses w ON l.warehouse_id = w.id
        LEFT JOIN users u ON l.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(l.reason, '') LIKE ?
                OR COALESCE(l.note, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if leave_type == "special":
        query += " AND l.leave_type IN (?,?,?,?)"
        params.extend(["special", "annual", "sick", "permit"])
    elif leave_type in LEAVE_TYPES:
        query += " AND l.leave_type=?"
        params.append(leave_type)

    if status in LEAVE_STATUSES:
        query += " AND l.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND l.warehouse_id=?"
        params.append(selected_warehouse)

    linked_employee_id = _get_linked_employee_id()
    if is_self_service_module("leave"):
        if linked_employee_id:
            query += " AND l.employee_id=?"
            params.append(linked_employee_id)
        else:
            query += " AND 1=0"

    if date_from:
        query += " AND l.start_date>=?"
        params.append(date_from)

    if date_to:
        query += " AND l.end_date<=?"
        params.append(date_to)

    query += " ORDER BY l.start_date DESC, e.full_name COLLATE NOCASE ASC, l.id DESC"

    leave_requests = [_decorate_leave_record(row) for row in db.execute(query, params).fetchall()]
    return leave_requests, search, leave_type, status, selected_warehouse, date_from, date_to


def _fetch_payroll_runs(db):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip().lower()
    period_month = _to_int(request.args.get("period_month"))
    period_year = _to_int(request.args.get("period_year"))
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM payroll_runs p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if status in PAYROLL_STATUSES:
        query += " AND p.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(selected_warehouse)

    if period_month:
        query += " AND p.period_month=?"
        params.append(period_month)

    if period_year:
        query += " AND p.period_year=?"
        params.append(period_year)

    query += " ORDER BY p.period_year DESC, p.period_month DESC, e.full_name COLLATE NOCASE ASC, p.id DESC"

    payroll_runs = [dict(row) for row in db.execute(query, params).fetchall()]
    return payroll_runs, search, status, selected_warehouse, period_month, period_year


def _fetch_recruitment_candidates(db):
    search = (request.args.get("q") or "").strip()
    stage = (request.args.get("stage") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            r.*,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM recruitment_candidates r
        LEFT JOIN warehouses w ON r.warehouse_id = w.id
        LEFT JOIN users u ON r.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                r.candidate_name LIKE ?
                OR r.position_title LIKE ?
                OR COALESCE(r.department, '') LIKE ?
                OR COALESCE(r.source, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if stage in RECRUITMENT_STAGES:
        query += " AND r.stage=?"
        params.append(stage)

    if status in RECRUITMENT_STATUSES:
        query += " AND r.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND r.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY r.created_at DESC, r.candidate_name COLLATE NOCASE ASC, r.id DESC"

    recruitment_candidates = [dict(row) for row in db.execute(query, params).fetchall()]
    return recruitment_candidates, search, stage, status, selected_warehouse


def _fetch_onboarding_records(db):
    search = (request.args.get("q") or "").strip()
    stage = (request.args.get("stage") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            o.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM onboarding_records o
        JOIN employees e ON o.employee_id = e.id
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        LEFT JOIN users u ON o.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if stage in ONBOARDING_STAGES:
        query += " AND o.stage=?"
        params.append(stage)

    if status in ONBOARDING_STATUSES:
        query += " AND o.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND o.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY o.start_date DESC, e.full_name COLLATE NOCASE ASC, o.id DESC"

    onboarding_records = [dict(row) for row in db.execute(query, params).fetchall()]
    return onboarding_records, search, stage, status, selected_warehouse


def _fetch_offboarding_records(db):
    search = (request.args.get("q") or "").strip()
    stage = (request.args.get("stage") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            o.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM offboarding_records o
        JOIN employees e ON o.employee_id = e.id
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        LEFT JOIN users u ON o.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(o.exit_reason, '') LIKE ?
                OR COALESCE(o.handover_pic, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if stage in OFFBOARDING_STAGES:
        query += " AND o.stage=?"
        params.append(stage)

    if status in OFFBOARDING_STATUSES:
        query += " AND o.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND o.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY o.notice_date DESC, e.full_name COLLATE NOCASE ASC, o.id DESC"

    offboarding_records = [dict(row) for row in db.execute(query, params).fetchall()]
    return offboarding_records, search, stage, status, selected_warehouse


def _fetch_performance_reviews(db):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip().lower()
    review_period = (request.args.get("review_period") or "").strip()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM performance_reviews p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(e.department, '') LIKE ?
                OR COALESCE(e.position, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if status in PERFORMANCE_STATUSES:
        query += " AND p.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(selected_warehouse)

    if review_period:
        query += " AND p.review_period=?"
        params.append(review_period)

    query += " ORDER BY p.review_period DESC, e.full_name COLLATE NOCASE ASC, p.id DESC"

    performance_reviews = [dict(row) for row in db.execute(query, params).fetchall()]
    return performance_reviews, search, status, selected_warehouse, review_period


def _fetch_helpdesk_tickets(db):
    search = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "all").strip().lower()
    priority = (request.args.get("priority") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            h.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM helpdesk_tickets h
        JOIN employees e ON h.employee_id = e.id
        LEFT JOIN warehouses w ON h.warehouse_id = w.id
        LEFT JOIN users u ON h.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR h.ticket_title LIKE ?
                OR COALESCE(h.assigned_to, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if category in HELPDESK_CATEGORIES:
        query += " AND h.category=?"
        params.append(category)

    if priority in HELPDESK_PRIORITIES:
        query += " AND h.priority=?"
        params.append(priority)

    if status in HELPDESK_STATUSES:
        query += " AND h.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND h.warehouse_id=?"
        params.append(selected_warehouse)

    linked_employee_id = _get_linked_employee_id()
    if is_self_service_module("helpdesk"):
        if linked_employee_id:
            query += " AND h.employee_id=?"
            params.append(linked_employee_id)
        else:
            query += " AND 1=0"

    query += " ORDER BY h.created_at DESC, e.full_name COLLATE NOCASE ASC, h.id DESC"

    helpdesk_tickets = [dict(row) for row in db.execute(query, params).fetchall()]
    return helpdesk_tickets, search, category, priority, status, selected_warehouse


def _fetch_asset_records(db):
    search = (request.args.get("q") or "").strip()
    status = (request.args.get("status") or "all").strip().lower()
    condition = (request.args.get("condition") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            a.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM asset_records a
        JOIN employees e ON a.employee_id = e.id
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        LEFT JOIN users u ON a.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR a.asset_name LIKE ?
                OR a.asset_code LIKE ?
                OR COALESCE(a.serial_number, '') LIKE ?
                OR COALESCE(a.category, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like, like, like])

    if status in ASSET_STATUSES:
        query += " AND a.asset_status=?"
        params.append(status)

    if condition in ASSET_CONDITIONS:
        query += " AND a.condition_status=?"
        params.append(condition)

    if selected_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY a.assigned_date DESC, e.full_name COLLATE NOCASE ASC, a.id DESC"

    asset_records = [dict(row) for row in db.execute(query, params).fetchall()]
    return asset_records, search, status, condition, selected_warehouse


def _fetch_project_records(db):
    search = (request.args.get("q") or "").strip()
    priority = (request.args.get("priority") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            p.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM project_records p
        JOIN employees e ON p.employee_id = e.id
        LEFT JOIN warehouses w ON p.warehouse_id = w.id
        LEFT JOIN users u ON p.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR p.project_name LIKE ?
                OR p.project_code LIKE ?
                OR COALESCE(p.owner_name, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like, like])

    if priority in PROJECT_PRIORITIES:
        query += " AND p.priority=?"
        params.append(priority)

    if status in PROJECT_STATUSES:
        query += " AND p.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND p.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY p.start_date DESC, e.full_name COLLATE NOCASE ASC, p.id DESC"

    project_records = [dict(row) for row in db.execute(query, params).fetchall()]
    return project_records, search, priority, status, selected_warehouse


def _fetch_biometric_logs(db):
    search = (request.args.get("q") or "").strip()
    punch_type = (request.args.get("punch_type") or "all").strip().lower()
    sync_status = (request.args.get("sync_status") or "all").strip().lower()
    date_from = (request.args.get("date_from") or "").strip()
    date_to = (request.args.get("date_to") or "").strip()
    today_label = date_cls.today().isoformat()
    if not date_from and not date_to:
        date_from = today_label
        date_to = today_label
    elif date_from and not date_to:
        date_to = date_from
    elif date_to and not date_from:
        date_from = date_to
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            b.*,
            e.employee_code,
            e.full_name,
            e.department,
            e.position,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM biometric_logs b
        JOIN employees e ON b.employee_id = e.id
        LEFT JOIN warehouses w ON b.warehouse_id = w.id
        LEFT JOIN users u ON b.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                e.employee_code LIKE ?
                OR e.full_name LIKE ?
                OR COALESCE(b.location_label, '') LIKE ?
                OR COALESCE(b.device_name, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if punch_type in BIOMETRIC_PUNCH_TYPES:
        query += " AND b.punch_type=?"
        params.append(punch_type)

    if sync_status in BIOMETRIC_SYNC_STATUSES:
        query += " AND b.sync_status=?"
        params.append(sync_status)

    if selected_warehouse:
        query += " AND b.warehouse_id=?"
        params.append(selected_warehouse)

    linked_employee_id = _get_linked_employee_id()
    if is_self_service_module("biometric"):
        if linked_employee_id:
            query += " AND b.employee_id=?"
            params.append(linked_employee_id)
        else:
            query += " AND 1=0"

    if date_from:
        query += " AND substr(b.punch_time, 1, 10)>=?"
        params.append(date_from)

    if date_to:
        query += " AND substr(b.punch_time, 1, 10)<=?"
        params.append(date_to)

    query += " ORDER BY b.punch_time DESC, e.full_name COLLATE NOCASE ASC, b.id DESC"

    biometric_logs = [dict(row) for row in db.execute(query, params).fetchall()]
    for log in biometric_logs:
        _attach_biometric_display_meta(log)
    return biometric_logs, search, punch_type, sync_status, selected_warehouse, date_from, date_to


def _build_biometric_recap_rows(db, biometric_logs):
    if not biometric_logs:
        return []

    grouped_logs = defaultdict(list)
    employee_ids = set()
    dates = set()

    for log in biometric_logs:
        punch_date = (log.get("punch_time") or "")[:10]
        if not punch_date:
            continue
        key = (log["employee_id"], punch_date)
        grouped_logs[key].append(log)
        employee_ids.add(log["employee_id"])
        dates.add(punch_date)

    if not grouped_logs:
        return []

    attendance_map = {}
    overtime_request_index = _build_biometric_overtime_request_index(
        db,
        employee_ids=sorted(employee_ids),
        attendance_dates=sorted(dates),
    )
    can_manage_overtime_approval = can_manage_attendance_request_approvals(session.get("role"))
    attendance_columns = _get_table_columns(db, "attendance_records")
    biometric_columns = _get_table_columns(db, "biometric_logs")
    required_columns = {"employee_id", "attendance_date"}
    can_edit_shift_storage = {"shift_code", "shift_label"}.issubset(attendance_columns) and {
        "shift_code",
        "shift_label",
    }.issubset(biometric_columns)
    if required_columns.issubset(attendance_columns):
        placeholders = ",".join(["?"] * len(employee_ids))
        attendance_select = [
            "employee_id",
            "attendance_date",
            ("check_in" if "check_in" in attendance_columns else "NULL AS check_in"),
            ("check_out" if "check_out" in attendance_columns else "NULL AS check_out"),
            ("status" if "status" in attendance_columns else "NULL AS status"),
            ("note" if "note" in attendance_columns else "NULL AS note"),
            ("shift_code" if "shift_code" in attendance_columns else "NULL AS shift_code"),
            ("shift_label" if "shift_label" in attendance_columns else "NULL AS shift_label"),
            ("status_override" if "status_override" in attendance_columns else "NULL AS status_override"),
        ]
        try:
            attendance_rows = db.execute(
                f"""
                SELECT {", ".join(attendance_select)}
                FROM attendance_records
                WHERE employee_id IN ({placeholders})
                  AND attendance_date BETWEEN ? AND ?
                """,
                list(employee_ids) + [min(dates), max(dates)],
            ).fetchall()
        except sqlite3.DatabaseError:
            attendance_rows = []

        attendance_map = {
            (row["employee_id"], row["attendance_date"]): dict(row)
            for row in attendance_rows
        }

    recap_rows = []
    for (employee_id, attendance_date), logs in grouped_logs.items():
        logs_sorted = sorted(logs, key=lambda item: item["punch_time"] or "")
        check_in_log = next((log for log in logs_sorted if log["punch_type"] == "check_in"), None)
        check_out_log = next((log for log in reversed(logs_sorted) if log["punch_type"] == "check_out"), None)
        latest_log = logs_sorted[-1]
        attendance = attendance_map.get((employee_id, attendance_date), {})

        # Rekap geotag hanya menampilkan hari yang benar-benar punya absensi inti.
        # Log tambahan seperti break tanpa check-in/check-out tidak perlu muncul sendiri.
        has_attendance_activity = bool(
            attendance.get("check_in")
            or attendance.get("check_out")
            or check_in_log
            or check_out_log
        )
        if not has_attendance_activity:
            continue

        locations = []
        for log in logs_sorted:
            location_display = log["location_display"]
            if location_display != "-" and location_display not in locations:
                locations.append(location_display)

        if any(log["sync_status"] == "failed" for log in logs_sorted):
            recap_status = "failed"
        elif any(log["sync_status"] == "queued" for log in logs_sorted):
            recap_status = "queued"
        elif any(log["sync_status"] == "manual" for log in logs_sorted):
            recap_status = "manual"
        else:
            recap_status = "synced"

        recap_status_label, recap_status_badge = _build_biometric_status_meta(recap_status)
        attendance_display = _build_attendance_status_display(attendance.get("status"), logs_sorted)
        break_display = _build_break_status_display(logs_sorted)
        break_summary = _summarize_break_activity(logs_sorted)
        syncable_logs = [
            log for log in logs_sorted if (log.get("sync_status") or "").strip().lower() in {"synced", "manual"}
        ]
        current_shift_label = (
            attendance.get("shift_label")
            or (check_out_log.get("shift_label") if check_out_log else None)
            or (check_in_log.get("shift_label") if check_in_log else None)
        )
        current_shift_code = _normalize_biometric_shift_code(
            attendance.get("shift_code")
            or (check_out_log.get("shift_code") if check_out_log else None)
            or (check_in_log.get("shift_code") if check_in_log else None)
        ) or _resolve_biometric_shift_code_from_label(current_shift_label, latest_log)
        shift_options = _build_biometric_shift_options(latest_log, current_shift_label)
        shift_options = [
            {
                **option,
                "selected": option["value"] == current_shift_code,
            }
            for option in shift_options
        ]
        if not current_shift_label and current_shift_code:
            current_shift_label = next(
                (
                    option["label"]
                    for option in shift_options
                    if option["value"] == current_shift_code
                ),
                None,
            )
        shift_display_label = current_shift_label or "-"
        attendance_check_in_value = (
            attendance.get("check_in")
            or (check_in_log["punch_time"][11:16] if check_in_log else "")
        )
        attendance_check_out_value = (
            attendance.get("check_out")
            or (check_out_log["punch_time"][11:16] if check_out_log else "")
        )
        overtime_summary = _summarize_overtime_activity(
            attendance_check_in_value,
            attendance_check_out_value,
            current_shift_label,
        )
        overtime_request = overtime_request_index.get((employee_id, attendance_date)) if overtime_summary["qualifies"] else None
        overtime_request_status = str((overtime_request or {}).get("status") or "").strip().lower()
        overtime_request_meta = (
            _get_biometric_overtime_request_status_meta(overtime_request_status)
            if overtime_request_status in {"approved", "rejected", "pending"}
            else {
                "label": "Pending",
                "badge_class": "orange",
                "helper_text": "Saldo belum bertambah sampai HR / Super Admin menekan Approve.",
            }
            if overtime_summary["qualifies"]
            else {
                "label": "",
                "badge_class": "",
                "helper_text": "",
            }
        )
        can_edit_check_in_time = bool(check_in_log)
        can_edit_check_out_time = bool(check_out_log)

        recap_rows.append(
            {
                "attendance_date": attendance_date,
                "employee_id": employee_id,
                "employee_code": latest_log["employee_code"],
                "full_name": latest_log["full_name"],
                "warehouse_name": latest_log["warehouse_name"],
                "shift_code": current_shift_code,
                "shift_label": current_shift_label,
                "shift_display_label": shift_display_label,
                "shift_options": shift_options,
                "can_edit_shift": can_adjust_biometric_attendance_status()
                and can_edit_shift_storage
                and bool(syncable_logs)
                and bool(shift_options),
                "attendance_status": (attendance.get("status") or "-"),
                "attendance_status_value": (attendance.get("status") or "present"),
                "attendance_status_label": attendance_display["label"],
                "attendance_status_badge": attendance_display["badge_class"],
                "break_status_label": break_display["label"],
                "break_status_badge": break_display["badge_class"],
                "break_duration_label": break_summary["duration_label"],
                "break_duration_seconds": break_summary["total_seconds"],
                "break_timer_active": break_summary["is_open"],
                "break_timer_started_at": break_summary["open_started_at_iso"],
                "break_timer_base_seconds": break_summary["completed_seconds"],
                "break_timer_over_limit": break_summary["open_seconds"] > 3600,
                "break_duration_note": (
                    "Lewat 1 jam"
                    if break_summary["open_seconds"] > 3600
                    else "Timer aktif"
                    if break_summary["is_open"]
                    else "Total istirahat"
                    if break_summary["has_break_activity"]
                    else ""
                ),
                "overtime_qualifies": overtime_summary["qualifies"],
                "overtime_duration_seconds": overtime_summary["total_seconds"],
                "overtime_duration_label": overtime_summary["duration_label"],
                "overtime_breakdown_label": overtime_summary["breakdown_label"],
                "overtime_request_status": overtime_request_status,
                "overtime_request_status_label": overtime_request_meta["label"],
                "overtime_request_badge": overtime_request_meta["badge_class"],
                "overtime_request_helper_text": overtime_request_meta["helper_text"],
                "overtime_can_decide": overtime_summary["qualifies"]
                and can_manage_overtime_approval
                and overtime_request_status not in {"approved", "rejected"},
                "status_override_active": bool(attendance.get("status_override")),
                "attendance_check_in": attendance.get("check_in") or "-",
                "attendance_check_out": attendance.get("check_out") or "-",
                "attendance_check_in_value": attendance_check_in_value,
                "attendance_check_out_value": attendance_check_out_value,
                "can_edit_check_in_time": can_edit_check_in_time,
                "can_edit_check_out_time": can_edit_check_out_time,
                "can_edit_attendance_time": can_adjust_biometric_attendance_status()
                and (can_edit_check_in_time or can_edit_check_out_time),
                "geo_check_in": (check_in_log["punch_time"][11:16] if check_in_log else "-"),
                "geo_check_out": (check_out_log["punch_time"][11:16] if check_out_log else "-"),
                "location_text": " | ".join(locations) if locations else "-",
                "latest_location": latest_log["location_display"] or "-",
                "latest_photo_url": latest_log.get("photo_url"),
                "log_count": len(logs_sorted),
                "recap_status_label": recap_status_label,
                "recap_status_badge": recap_status_badge,
            }
        )

    recap_rows.sort(key=lambda row: (row["attendance_date"], row["full_name"].lower()), reverse=True)
    return recap_rows


def _fetch_announcements(db):
    search = (request.args.get("q") or "").strip()
    audience = (request.args.get("audience") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            a.*,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM announcement_posts a
        LEFT JOIN warehouses w ON a.warehouse_id = w.id
        LEFT JOIN users u ON a.handled_by = u.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                a.title LIKE ?
                OR COALESCE(a.channel, '') LIKE ?
                OR COALESCE(a.message, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like])

    if audience in ANNOUNCEMENT_AUDIENCES:
        query += " AND a.audience=?"
        params.append(audience)

    if status in ANNOUNCEMENT_STATUSES:
        query += " AND a.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND a.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY a.publish_date DESC, a.id DESC"

    announcements = [dict(row) for row in db.execute(query, params).fetchall()]
    return announcements, search, audience, status, selected_warehouse


def _fetch_documents(db):
    search = (request.args.get("q") or "").strip()
    document_type = (request.args.get("document_type") or "all").strip().lower()
    status = (request.args.get("status") or "all").strip().lower()
    scope_warehouse = get_hris_scope()

    if scope_warehouse:
        selected_warehouse = scope_warehouse
    else:
        selected_warehouse = _to_int(request.args.get("warehouse"))

    query = """
        SELECT
            d.*,
            w.name AS warehouse_name,
            u.username AS handled_by_name,
            su.username AS signed_by_name
        FROM document_records d
        LEFT JOIN warehouses w ON d.warehouse_id = w.id
        LEFT JOIN users u ON d.handled_by = u.id
        LEFT JOIN users su ON d.signed_by = su.id
        WHERE 1=1
    """
    params = []

    if search:
        query += """
            AND (
                d.document_title LIKE ?
                OR d.document_code LIKE ?
                OR COALESCE(d.owner_name, '') LIKE ?
                OR COALESCE(d.note, '') LIKE ?
            )
        """
        like = f"%{search}%"
        params.extend([like, like, like, like])

    if document_type in DOCUMENT_TYPES:
        query += " AND d.document_type=?"
        params.append(document_type)

    if status in DOCUMENT_STATUSES:
        query += " AND d.status=?"
        params.append(status)

    if selected_warehouse:
        query += " AND d.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY d.effective_date DESC, d.id DESC"

    documents = [_decorate_document_record(row) for row in db.execute(query, params).fetchall()]
    return documents, search, document_type, status, selected_warehouse


@hris_bp.route("/")
@hris_bp.route("/<module_slug>")
def hris_index(module_slug=None):
    if not can_view_hris_records():
        flash("Role ini tidak punya akses ke halaman HRIS", "error")
        return _hris_access_denied_redirect()

    role = session.get("role")

    if module_slug == "attendance":
        if not can_manage_hris_records("biometric"):
            portal_redirect = _portal_redirect_for_module("biometric")
            if portal_redirect is not None:
                flash("Gunakan halaman self-service yang terpisah untuk modul attendance geotag.", "info")
                return portal_redirect
        redirect_target = url_for("hris.hris_index", module_slug="biometric")
        query_string = request.query_string.decode("utf-8")
        if query_string:
            redirect_target = f"{redirect_target}?{query_string}"
        return redirect(redirect_target)

    if module_slug in {"leave", "biometric"} and not can_manage_hris_records(module_slug):
        portal_redirect = _portal_redirect_for_module(module_slug)
        if portal_redirect is not None:
            flash("Gunakan halaman self-service yang terpisah untuk modul ini.", "info")
            return portal_redirect

    if module_slug in {"asset", "project"}:
        replacement_module = get_hris_module("approval", role)
        if replacement_module is not None:
            flash("Modul Asset dan Project sudah diganti menjadi Approval HR.", "info")
            return redirect(url_for("hris.hris_index", module_slug=replacement_module["slug"]))
        fallback_module = get_hris_module("helpdesk", role) or get_hris_module("dashboard", role)
        flash("Modul Asset dan Project sudah dihapus dari HRIS.", "info")
        if fallback_module is not None:
            return redirect(url_for("hris.hris_index", module_slug=fallback_module["slug"]))
        return _hris_access_denied_redirect()

    db = get_db()
    modules = get_hris_modules(role)
    if not modules:
        flash("Role ini tidak punya modul HRIS yang bisa dibuka", "error")
        return _hris_access_denied_redirect()

    root_module = get_hris_module("dashboard", role) or get_hris_module(modules[0]["slug"], role)
    fallback_module = get_hris_module("helpdesk", role) or root_module
    selected_module = get_hris_module(module_slug, role) if module_slug else root_module

    if selected_module is None:
        flash("Modul HRIS tidak tersedia untuk role ini", "error")
        return redirect(f"/hris/{fallback_module['slug']}")

    scope_warehouse = get_hris_scope()

    employees = []
    employee_summary = None
    employee_filters = None
    attendance_records = []
    attendance_summary = None
    attendance_filters = None
    attendance_employees = []
    leave_requests = []
    leave_summary = None
    leave_filters = None
    leave_employees = []
    approval_requests = []
    approval_summary = None
    approval_filters = None
    approval_pending_requests = []
    approval_recent_requests = []
    attendance_action_requests = []
    attendance_action_summary = None
    attendance_action_pending_requests = []
    attendance_action_recent_requests = []
    payroll_runs = []
    payroll_summary = None
    payroll_filters = None
    payroll_employees = []
    recruitment_candidates = []
    recruitment_summary = None
    recruitment_filters = None
    onboarding_records = []
    onboarding_summary = None
    onboarding_filters = None
    onboarding_employees = []
    offboarding_records = []
    offboarding_summary = None
    offboarding_filters = None
    offboarding_employees = []
    performance_reviews = []
    performance_summary = None
    performance_filters = None
    performance_employees = []
    kpi_reports = []
    kpi_summary = None
    kpi_filters = None
    kpi_profile_cards = []
    kpi_target_plans = []
    kpi_target_summary = None
    kpi_target_employees = []
    kpi_target_period_label = normalize_kpi_period_label(None)
    kpi_target_seed_profiles = {}
    helpdesk_tickets = []
    helpdesk_summary = None
    helpdesk_filters = None
    helpdesk_employees = []
    biometric_logs = []
    biometric_summary = None
    biometric_filters = None
    biometric_employees = []
    biometric_recap_rows = []
    overtime_recap_rows = []
    overtime_recap_summary = None
    overtime_usage_history = []
    announcements = []
    announcement_summary = None
    announcement_filters = None
    dashboard_summary = None
    dashboard_filters = None
    dashboard_announcements = []
    dashboard_announcement_summary = None
    dashboard_leave_alerts = []
    dashboard_leave_alert_summary = None
    dashboard_reminders = []
    dashboard_reminder_summary = None
    dashboard_schedule = None
    documents = []
    document_summary = None
    document_filters = None
    report_summary = None
    report_filters = None
    report_workforce_rows = []
    report_pipeline_rows = []
    report_service_rows = []
    daily_live_reports = []
    daily_live_report_summary = None
    daily_live_report_groups = {"daily": [], "live": []}
    warehouses = db.execute(
        "SELECT * FROM warehouses ORDER BY name"
    ).fetchall()

    if selected_module["slug"] == "dashboard":
        dashboard_summary = _build_dashboard_summary(db, warehouses)
        dashboard_filters = dashboard_summary["filters"]
        dashboard_announcements = dashboard_summary["announcements"]
        dashboard_announcement_summary = dashboard_summary["announcement_summary"]
        dashboard_leave_alerts = dashboard_summary["leave_alerts"]
        dashboard_leave_alert_summary = dashboard_summary["leave_alert_summary"]
        dashboard_reminders = dashboard_summary["reminders"]
        dashboard_reminder_summary = dashboard_summary["reminder_summary"]
        dashboard_schedule = dashboard_summary["schedule"]
    elif selected_module["slug"] == "employee":
        employees, search, status, selected_warehouse = _fetch_employees(db)
        employee_summary = _build_employee_summary(employees)
        employee_filters = {
            "search": search,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
    elif selected_module["slug"] == "attendance":
        attendance_records, search, status, selected_warehouse, date_from, date_to = _fetch_attendance_records(db)
        attendance_summary = _build_attendance_summary(attendance_records)
        attendance_filters = {
            "search": search,
            "status": status,
            "warehouse_id": selected_warehouse,
            "date_from": date_from,
            "date_to": date_to,
        }
        attendance_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "leave":
        leave_requests, search, leave_type, status, selected_warehouse, date_from, date_to = _fetch_leave_requests(db)
        leave_summary = _build_leave_summary(leave_requests)
        leave_filters = {
            "search": search,
            "leave_type": leave_type,
            "status": status,
            "warehouse_id": selected_warehouse,
            "date_from": date_from,
            "date_to": date_to,
        }
        leave_employees = _fetch_employee_options(db, "leave")
    elif selected_module["slug"] == "approval":
        approval_requests, search, leave_type, _status, selected_warehouse, date_from, date_to = _fetch_leave_requests(db)
        approval_summary = _build_approval_summary(approval_requests)
        approval_filters = {
            "search": search,
            "leave_type": leave_type,
            "warehouse_id": selected_warehouse,
            "date_from": date_from,
            "date_to": date_to,
        }
        approval_pending_requests, approval_recent_requests = _split_approval_requests(approval_requests)
        attendance_action_requests = fetch_attendance_requests(
            db,
            status="all",
            search=search,
            warehouse_id=selected_warehouse,
            date_from=date_from,
            date_to=date_to,
        )
        attendance_action_summary = build_attendance_request_summary(attendance_action_requests)
        attendance_action_pending_requests, attendance_action_recent_requests = split_attendance_requests(attendance_action_requests)
    elif selected_module["slug"] == "payroll":
        payroll_runs, search, status, selected_warehouse, period_month, period_year = _fetch_payroll_runs(db)
        payroll_summary = _build_payroll_summary(payroll_runs)
        payroll_filters = {
            "search": search,
            "status": status,
            "warehouse_id": selected_warehouse,
            "period_month": period_month,
            "period_year": period_year,
        }
        payroll_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "recruitment":
        recruitment_candidates, search, stage, status, selected_warehouse = _fetch_recruitment_candidates(db)
        recruitment_summary = _build_recruitment_summary(recruitment_candidates)
        recruitment_filters = {
            "search": search,
            "stage": stage,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
    elif selected_module["slug"] == "onboarding":
        onboarding_records, search, stage, status, selected_warehouse = _fetch_onboarding_records(db)
        onboarding_summary = _build_onboarding_summary(onboarding_records)
        onboarding_filters = {
            "search": search,
            "stage": stage,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
        onboarding_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "offboarding":
        offboarding_records, search, stage, status, selected_warehouse = _fetch_offboarding_records(db)
        offboarding_summary = _build_offboarding_summary(offboarding_records)
        offboarding_filters = {
            "search": search,
            "stage": stage,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
        offboarding_employees = _fetch_employee_options(db)
    elif selected_module["slug"] == "pms":
        kpi_reports, search, status, selected_warehouse, period_label, week_key = _fetch_kpi_staff_reports(db)
        kpi_summary = _build_kpi_summary(kpi_reports)
        kpi_filters = {
            "search": search,
            "status": status,
            "warehouse_id": selected_warehouse,
            "period_label": period_label,
            "week_key": week_key,
        }
        kpi_target_plans, _, _, kpi_target_period_label = _fetch_kpi_target_plans(db)
        kpi_target_summary = _build_kpi_target_plan_summary(kpi_target_plans)
        kpi_target_employees = _fetch_employee_options(db)
        kpi_target_seed_profiles = _build_kpi_target_seed_profiles(
            db,
            kpi_target_employees,
            kpi_target_period_label or period_label,
        )
        kpi_profile_cards = _build_kpi_profile_reference_cards(
            selected_warehouse=selected_warehouse,
            warehouse_rows=warehouses,
            search=search,
        )
    elif selected_module["slug"] == "helpdesk":
        helpdesk_tickets, search, category, priority, status, selected_warehouse = _fetch_helpdesk_tickets(db)
        helpdesk_summary = _build_helpdesk_summary(helpdesk_tickets)
        helpdesk_filters = {
            "search": search,
            "category": category,
            "priority": priority,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
        helpdesk_employees = _fetch_employee_options(db, "helpdesk")
    elif selected_module["slug"] == "report":
        (
            report_summary,
            report_filters,
            report_workforce_rows,
            report_pipeline_rows,
            report_service_rows,
            daily_live_reports,
            daily_live_report_summary,
            daily_live_report_groups,
        ) = _build_report_snapshot(db)
    elif selected_module["slug"] == "biometric":
        biometric_logs, search, punch_type, sync_status, selected_warehouse, date_from, date_to = _fetch_biometric_logs(db)
        biometric_summary = _build_biometric_summary(biometric_logs)
        try:
            biometric_recap_rows = _build_biometric_recap_rows(db, biometric_logs)
            overtime_recap_rows, overtime_recap_summary, overtime_usage_history = _build_overtime_recap(
                db,
                selected_warehouse=selected_warehouse,
                period_date_from=date_from,
                period_date_to=date_to,
            )
        except Exception as exc:
            current_app.logger.exception("HRIS BIOMETRIC OVERTIME RENDER ERROR: %s", exc)
            biometric_recap_rows = []
            overtime_recap_rows = []
            overtime_recap_summary = {
                "staff_total": 0,
                "staff_with_balance": 0,
                "earned_period_seconds": 0,
                "added_period_seconds": 0,
                "used_period_seconds": 0,
                "available_total_seconds": 0,
                "earned_period_label": "-",
                "added_period_label": "-",
                "used_period_label": "-",
                "available_total_label": "-",
                "history_count": 0,
                "period_label": (
                    f"{date_from} s/d {date_to}"
                    if date_from and date_to
                    else date_from
                    or date_to
                    or "Semua Periode"
                ),
            }
            overtime_usage_history = []
            flash(
                "Komponen lembur otomatis belum siap di server. Schema overtime di database VPS perlu disinkronkan dulu.",
                "error",
            )
        biometric_filters = {
            "search": search,
            "punch_type": punch_type,
            "sync_status": sync_status,
            "warehouse_id": selected_warehouse,
            "date_from": date_from,
            "date_to": date_to,
        }
        biometric_employees = _fetch_employee_options(db, "biometric")
    elif selected_module["slug"] == "announcement":
        announcements, search, audience, status, selected_warehouse = _fetch_announcements(db)
        announcement_summary = _build_announcement_summary(announcements)
        announcement_filters = {
            "search": search,
            "audience": audience,
            "status": status,
            "warehouse_id": selected_warehouse,
        }
    elif selected_module["slug"] == "documents":
        documents, search, document_type, status, selected_warehouse = _fetch_documents(db)
        document_summary = _build_document_summary(documents)
        document_filters = {
            "search": search,
            "document_type": document_type,
            "status": status,
            "warehouse_id": selected_warehouse,
        }

    report_return_to = request.full_path[:-1] if request.full_path.endswith("?") else request.full_path

    return render_template(
        "hris.html",
        modules=modules,
        selected_module=selected_module,
        employees=employees,
        employee_summary=employee_summary,
        employee_filters=employee_filters,
        attendance_records=attendance_records,
        attendance_summary=attendance_summary,
        attendance_filters=attendance_filters,
        attendance_employees=attendance_employees,
        leave_requests=leave_requests,
        leave_summary=leave_summary,
        leave_filters=leave_filters,
        leave_employees=leave_employees,
        approval_requests=approval_requests,
        approval_summary=approval_summary,
        approval_filters=approval_filters,
        approval_pending_requests=approval_pending_requests,
        approval_recent_requests=approval_recent_requests,
        attendance_action_requests=attendance_action_requests,
        attendance_action_summary=attendance_action_summary,
        attendance_action_pending_requests=attendance_action_pending_requests,
        attendance_action_recent_requests=attendance_action_recent_requests,
        payroll_runs=payroll_runs,
        payroll_summary=payroll_summary,
        payroll_filters=payroll_filters,
        payroll_employees=payroll_employees,
        recruitment_candidates=recruitment_candidates,
        recruitment_summary=recruitment_summary,
        recruitment_filters=recruitment_filters,
        onboarding_records=onboarding_records,
        onboarding_summary=onboarding_summary,
        onboarding_filters=onboarding_filters,
        onboarding_employees=onboarding_employees,
        offboarding_records=offboarding_records,
        offboarding_summary=offboarding_summary,
        offboarding_filters=offboarding_filters,
        offboarding_employees=offboarding_employees,
        performance_reviews=performance_reviews,
        performance_summary=performance_summary,
        performance_filters=performance_filters,
        performance_employees=performance_employees,
        kpi_reports=kpi_reports,
        kpi_summary=kpi_summary,
        kpi_filters=kpi_filters,
        kpi_target_plans=kpi_target_plans,
        kpi_target_summary=kpi_target_summary,
        kpi_target_employees=kpi_target_employees,
        kpi_target_period_label=(kpi_target_period_label if 'kpi_target_period_label' in locals() else normalize_kpi_period_label(None)),
        kpi_target_seed_profiles=kpi_target_seed_profiles,
        kpi_profile_cards=kpi_profile_cards,
        kpi_week_options=KPI_WEEK_OPTIONS,
        current_kpi_week_key=get_current_kpi_week_key(),
        current_kpi_period_label=normalize_kpi_period_label(None),
        format_kpi_period_label=format_kpi_period_label,
        helpdesk_tickets=helpdesk_tickets,
        helpdesk_summary=helpdesk_summary,
        helpdesk_filters=helpdesk_filters,
        helpdesk_employees=helpdesk_employees,
        biometric_logs=biometric_logs,
        biometric_summary=biometric_summary,
        biometric_filters=biometric_filters,
        biometric_employees=biometric_employees,
        biometric_recap_rows=biometric_recap_rows,
        overtime_recap_rows=overtime_recap_rows,
        overtime_recap_summary=overtime_recap_summary,
        overtime_usage_history=overtime_usage_history,
        announcements=announcements,
        announcement_summary=announcement_summary,
        announcement_filters=announcement_filters,
        dashboard_summary=dashboard_summary,
        dashboard_filters=dashboard_filters,
        dashboard_announcements=dashboard_announcements,
        dashboard_announcement_summary=dashboard_announcement_summary,
        dashboard_leave_alerts=dashboard_leave_alerts,
        dashboard_leave_alert_summary=dashboard_leave_alert_summary,
        dashboard_reminders=dashboard_reminders,
        dashboard_reminder_summary=dashboard_reminder_summary,
        dashboard_schedule=dashboard_schedule,
        documents=documents,
        document_summary=document_summary,
        document_filters=document_filters,
        report_summary=report_summary,
        report_filters=report_filters,
        report_workforce_rows=report_workforce_rows,
        report_pipeline_rows=report_pipeline_rows,
        report_service_rows=report_service_rows,
        daily_live_reports=daily_live_reports,
        daily_live_report_summary=daily_live_report_summary,
        daily_live_report_groups=daily_live_report_groups,
        warehouses=warehouses,
        can_manage_employee=can_manage_employee_records(),
        can_manage_attendance=can_manage_attendance_records(),
        can_manage_leave=can_manage_leave_records(),
        can_manage_approval=can_manage_approval_records(),
        can_manage_attendance_approval=can_manage_attendance_request_approvals(session.get("role")),
        can_manage_payroll=can_manage_payroll_records(),
        can_manage_recruitment=can_manage_recruitment_records(),
        can_manage_onboarding=can_manage_onboarding_records(),
        can_manage_offboarding=can_manage_offboarding_records(),
        can_manage_performance=can_manage_performance_records(),
        can_manage_helpdesk=can_manage_helpdesk_records(),
        can_manage_biometric=can_manage_biometric_records(),
        can_adjust_biometric_status=can_adjust_biometric_attendance_status(),
        can_manage_announcement=can_manage_announcement_records(),
        can_manage_document=can_manage_document_records(),
        can_manage_report=can_manage_hris_records("report"),
        can_manage_dashboard=can_manage_hris_records("dashboard"),
        can_manage_dashboard_reminders=can_manage_dashboard_reminders(),
        report_return_to=report_return_to,
        employee_scope_warehouse=scope_warehouse,
        attendance_scope_warehouse=scope_warehouse,
        leave_scope_warehouse=scope_warehouse,
        approval_scope_warehouse=scope_warehouse,
        payroll_scope_warehouse=scope_warehouse,
        recruitment_scope_warehouse=scope_warehouse,
        onboarding_scope_warehouse=scope_warehouse,
        offboarding_scope_warehouse=scope_warehouse,
        performance_scope_warehouse=scope_warehouse,
        helpdesk_scope_warehouse=scope_warehouse,
        biometric_scope_warehouse=scope_warehouse,
        announcement_scope_warehouse=scope_warehouse,
        document_scope_warehouse=scope_warehouse,
        report_scope_warehouse=scope_warehouse,
    )


@hris_bp.route("/dashboard/reminder/add", methods=["POST"])
def add_dashboard_reminder():
    return_to = _safe_hris_return_to("/hris/")
    if not can_manage_dashboard_reminders():
        flash("Tidak punya akses untuk mengelola pengingat harian dashboard.", "error")
        return redirect(return_to)

    db = get_db()
    reminder_date = _parse_iso_date((request.form.get("reminder_date") or "").strip())
    title = (request.form.get("title") or "").strip()
    note = (request.form.get("note") or "").strip()
    warehouse_id = _to_int(request.form.get("warehouse_id"))

    if reminder_date is None:
        flash("Tanggal pengingat harian tidak valid.", "error")
        return redirect(return_to)

    if not title:
        flash("Judul pengingat harian wajib diisi.", "error")
        return redirect(return_to)

    if warehouse_id:
        warehouse = db.execute("SELECT id FROM warehouses WHERE id=?", (warehouse_id,)).fetchone()
        if warehouse is None:
            flash("Gudang pengingat tidak ditemukan.", "error")
            return redirect(return_to)

    db.execute(
        """
        INSERT INTO dashboard_reminders(
            warehouse_id,
            reminder_date,
            title,
            note,
            status,
            created_by,
            updated_by,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            warehouse_id,
            reminder_date.isoformat(),
            title,
            note or None,
            "open",
            session.get("user_id"),
            session.get("user_id"),
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Pengingat harian berhasil ditambahkan ke dashboard HRIS.", "success")
    return redirect(return_to)


@hris_bp.route("/dashboard/reminder/toggle/<int:reminder_id>", methods=["POST"])
def toggle_dashboard_reminder(reminder_id):
    return_to = _safe_hris_return_to("/hris/")
    if not can_manage_dashboard_reminders():
        flash("Tidak punya akses untuk mengubah pengingat harian dashboard.", "error")
        return redirect(return_to)

    db = get_db()
    reminder = db.execute(
        "SELECT id, status FROM dashboard_reminders WHERE id=?",
        (reminder_id,),
    ).fetchone()
    if reminder is None:
        flash("Pengingat harian tidak ditemukan.", "error")
        return redirect(return_to)

    requested_status = (request.form.get("status") or "").strip().lower()
    if requested_status not in DASHBOARD_REMINDER_STATUSES:
        requested_status = "done" if reminder["status"] == "open" else "open"

    db.execute(
        """
        UPDATE dashboard_reminders
        SET status=?,
            updated_by=?,
            updated_at=?
        WHERE id=?
        """,
        (
            requested_status,
            session.get("user_id"),
            _current_timestamp(),
            reminder_id,
        ),
    )
    db.commit()

    flash("Status pengingat harian berhasil diperbarui.", "success")
    return redirect(return_to)


@hris_bp.route("/dashboard/reminder/delete/<int:reminder_id>", methods=["POST"])
def delete_dashboard_reminder(reminder_id):
    return_to = _safe_hris_return_to("/hris/")
    if not can_manage_dashboard_reminders():
        flash("Tidak punya akses untuk menghapus pengingat harian dashboard.", "error")
        return redirect(return_to)

    db = get_db()
    db.execute("DELETE FROM dashboard_reminders WHERE id=?", (reminder_id,))
    db.commit()

    flash("Pengingat harian berhasil dihapus.", "success")
    return redirect(return_to)


def _get_daily_live_report_by_id(db, report_id):
    row = db.execute(
        """
        SELECT
            r.*,
            w.name AS warehouse_name,
            e.full_name AS employee_name,
            u.username AS submitter_username,
            hu.username AS handled_by_name
        FROM daily_live_reports r
        LEFT JOIN warehouses w ON w.id = r.warehouse_id
        LEFT JOIN employees e ON e.id = r.employee_id
        LEFT JOIN users u ON u.id = r.user_id
        LEFT JOIN users hu ON hu.id = r.handled_by
        WHERE r.id=?
        LIMIT 1
        """,
        (report_id,),
    ).fetchone()
    return dict(row) if row else None


def _notify_daily_live_report_status_change(db, report_record, previous_status=None):
    if not report_record:
        return

    record = dict(report_record) if not isinstance(report_record, dict) else report_record
    current_status = _normalize_daily_live_report_status(record.get("status"))
    previous_status = _normalize_daily_live_report_status(previous_status)
    if current_status == previous_status or current_status == "submitted":
        return

    requester_id = _to_int(record.get("user_id"))
    employee_label = (
        (record.get("employee_name") or "").strip()
        or (record.get("submitter_username") or "").strip()
        or "Staff"
    )
    warehouse_label = (record.get("warehouse_name") or "Gudang").strip()
    report_type_label = "Live Report" if (record.get("report_type") or "").strip().lower() == "live" else "Daily Report"
    status_label = DAILY_LIVE_REPORT_STATUS_LABELS.get(current_status, current_status.replace("_", " ").title())
    approver_label = (
        (session.get("username") or "").strip()
        or (record.get("handled_by_name") or "").strip()
        or "HR / Super Admin"
    )
    hr_note = str(record.get("hr_note") or "").strip()
    title = str(record.get("title") or "").strip()
    approved_statuses = {"reviewed", "closed"}
    event_type = "report.status_approved" if current_status in approved_statuses else "report.status_rejected"
    requester_message = (
        f"{report_type_label} Anda untuk {record.get('report_date') or '-'} "
        f"ditandai {status_label.lower()} oleh {approver_label}."
        f"{f' Judul: {title}.' if title else ''}"
        f"{f' Catatan HR: {hr_note}.' if hr_note else ''}"
    )

    if requester_id:
        notify_user(
            requester_id,
            f"{report_type_label} {status_label}",
            requester_message,
            category="report",
            link_url="/laporan-harian/",
            source_type="daily_live_report_status",
            source_id=f"{record.get('id')}:{current_status}",
            dedupe_key=f"daily_live_report_status:{record.get('id')}:{current_status}",
            push_title=f"{report_type_label} {status_label}",
            push_body=f"{record.get('report_date') or '-'} | {status_label}",
        )

    report_policy = get_event_notification_policy(event_type)
    notify_operational_event(
        f"{report_type_label} {status_label}: {employee_label}",
        (
            f"{report_type_label} milik {employee_label} di {warehouse_label} "
            f"ditandai {status_label.lower()} oleh {approver_label}."
            f"{f' Judul: {title}.' if title else ''}"
            f"{f' Catatan HR: {hr_note}.' if hr_note else ''}"
        ),
        warehouse_id=record.get("warehouse_id"),
        include_actor=False,
        exclude_user_ids=[requester_id] if requester_id else None,
        recipient_roles=report_policy["roles"],
        recipient_usernames=report_policy["usernames"],
        recipient_user_ids=report_policy["user_ids"],
        category="report",
        link_url="/hris/report",
        source_type="daily_live_report_status",
        source_id=f"{record.get('id')}:{current_status}",
        dedupe_key=f"daily_live_report_status:ops:{record.get('id')}:{current_status}",
        push_title=f"{report_type_label} {status_label}",
        push_body=f"{employee_label} | {status_label}",
    )

    send_role_based_notification(
        event_type,
        {
            "warehouse_id": record.get("warehouse_id"),
            "warehouse_name": warehouse_label,
            "employee_name": employee_label,
            "report_type_label": report_type_label,
            "status_label": status_label,
            "approver_name": approver_label,
            "title": title,
            "reason": hr_note,
            "link_url": "/hris/report",
            "exclude_user_ids": [requester_id] if requester_id else None,
        },
    )


@hris_bp.route("/report/daily-live/update/<int:report_id>", methods=["POST"])
def update_daily_live_report(report_id):
    return_to = (request.form.get("return_to") or "").strip()
    if not return_to.startswith("/hris/report"):
        return_to = "/hris/report"

    if not can_manage_hris_records("report"):
        flash("Tidak punya akses untuk memproses report harian/live.", "error")
        return redirect(return_to)

    db = get_db()
    report = _get_daily_live_report_by_id(db, report_id)
    if report is None:
        flash("Report tidak ditemukan.", "error")
        return redirect(return_to)
    previous_status = report["status"]

    status = _normalize_daily_live_report_status(request.form.get("status"))
    hr_note = (request.form.get("hr_note") or "").strip()
    handled_by = None if status == "submitted" else session.get("user_id")
    handled_at = None if status == "submitted" else _current_timestamp()

    db.execute(
        """
        UPDATE daily_live_reports
        SET status=?,
            hr_note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            status,
            hr_note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            report_id,
        ),
    )
    db.commit()

    try:
        updated_report = _get_daily_live_report_by_id(db, report_id)
        _notify_daily_live_report_status_change(db, updated_report, previous_status=previous_status)
    except Exception as exc:
        print("DAILY LIVE REPORT STATUS NOTIFICATION ERROR:", exc)

    flash("Status report harian/live berhasil diperbarui.", "success")
    return redirect(return_to)


@hris_bp.route("/approval/attendance-request/<int:request_id>/process", methods=["POST"])
def process_attendance_request(request_id):
    return_to = _safe_hris_return_to("/hris/approval")
    if not can_manage_attendance_request_approvals(session.get("role")):
        flash("Hanya HR dan Super Admin yang bisa memproses request attendance ini.", "error")
        return redirect(return_to)

    db = get_db()
    request_row = _get_attendance_request_by_id(db, request_id)
    if request_row is None:
        flash("Request attendance tidak ditemukan.", "error")
        return redirect(return_to)

    if str(request_row.get("status") or "").lower() != "pending":
        flash("Request attendance ini sudah diproses sebelumnya.", "info")
        return redirect(return_to)

    decision = (request.form.get("decision") or "").strip().lower()
    decision_note = (request.form.get("decision_note") or "").strip()
    if decision not in {"approved", "rejected"}:
        flash("Keputusan approval attendance tidak valid.", "error")
        return redirect(return_to)

    try:
        if decision == "approved":
            success_message = _apply_attendance_request(db, request_row)
        else:
            success_message = "Request attendance ditolak."

        db.execute(
            """
            UPDATE attendance_action_requests
            SET status=?,
                handled_by=?,
                handled_at=?,
                decision_note=?,
                updated_at=?
            WHERE id=?
            """,
            (
                decision,
                session.get("user_id"),
                _current_timestamp(),
                decision_note or None,
                _current_timestamp(),
                request_id,
            ),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        flash(str(exc), "error")
        return redirect(return_to)

    try:
        updated_request = _get_attendance_request_by_id(db, request_id)
        if updated_request is not None:
            updated_request["decision_note"] = decision_note
            _notify_attendance_request_decision(
                db,
                updated_request,
                approved=decision == "approved",
            )
    except Exception as exc:
        print("ATTENDANCE REQUEST DECISION NOTIFICATION ERROR:", exc)

    flash(success_message, "success" if decision == "approved" else "info")
    return redirect(return_to)


@hris_bp.route("/employee/add", methods=["POST"])
def add_employee():
    if not can_manage_employee_records():
        flash("Tidak punya akses untuk mengelola data karyawan", "error")
        return redirect("/hris/employee")

    db = get_db()
    employee_code = (request.form.get("employee_code") or "").strip().upper()
    full_name = (request.form.get("full_name") or "").strip()
    department = (request.form.get("department") or "").strip()
    position = (request.form.get("position") or "").strip()
    employment_status = _normalize_status(request.form.get("employment_status"))
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    join_date = (request.form.get("join_date") or "").strip()
    work_location = (request.form.get("work_location") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))

    if not employee_code or not full_name:
        flash("Employee code dan nama lengkap wajib diisi", "error")
        return redirect("/hris/employee")

    if warehouse_id is None:
        flash("Gudang kerja wajib diisi", "error")
        return redirect("/hris/employee")

    duplicate = db.execute(
        "SELECT id FROM employees WHERE employee_code=?",
        (employee_code,),
    ).fetchone()
    if duplicate:
        flash("Employee code sudah digunakan", "error")
        return redirect("/hris/employee")

    db.execute(
        """
        INSERT INTO employees(
            employee_code,
            full_name,
            warehouse_id,
            department,
            position,
            employment_status,
            phone,
            email,
            join_date,
            work_location,
            notes,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        """,
        (
            employee_code,
            full_name,
            warehouse_id,
            department or None,
            position or None,
            employment_status,
            phone or None,
            email or None,
            join_date or None,
            work_location or None,
            notes or None,
        ),
    )
    db.commit()

    flash("Data karyawan berhasil ditambahkan", "success")
    return redirect("/hris/employee")


@hris_bp.route("/employee/update/<int:employee_id>", methods=["POST"])
def update_employee(employee_id):
    if not can_manage_employee_records():
        flash("Tidak punya akses untuk mengelola data karyawan", "error")
        return redirect("/hris/employee")

    db = get_db()
    employee = _get_employee_by_id(db, employee_id)
    if not employee:
        flash("Data karyawan tidak ditemukan", "error")
        return redirect("/hris/employee")

    employee_code = (request.form.get("employee_code") or "").strip().upper()
    full_name = (request.form.get("full_name") or "").strip()
    department = (request.form.get("department") or "").strip()
    position = (request.form.get("position") or "").strip()
    employment_status = _normalize_status(request.form.get("employment_status"))
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    join_date = (request.form.get("join_date") or "").strip()
    work_location = (request.form.get("work_location") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))

    if not employee_code or not full_name:
        flash("Employee code dan nama lengkap wajib diisi", "error")
        return redirect("/hris/employee")

    if warehouse_id is None:
        flash("Gudang kerja wajib diisi", "error")
        return redirect("/hris/employee")

    duplicate = db.execute(
        "SELECT id FROM employees WHERE employee_code=? AND id<>?",
        (employee_code, employee_id),
    ).fetchone()
    if duplicate:
        flash("Employee code sudah digunakan oleh karyawan lain", "error")
        return redirect("/hris/employee")

    db.execute(
        """
        UPDATE employees
        SET employee_code=?,
            full_name=?,
            warehouse_id=?,
            department=?,
            position=?,
            employment_status=?,
            phone=?,
            email=?,
            join_date=?,
            work_location=?,
            notes=?,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (
            employee_code,
            full_name,
            warehouse_id,
            department or None,
            position or None,
            employment_status,
            phone or None,
            email or None,
            join_date or None,
            work_location or None,
            notes or None,
            employee_id,
        ),
    )
    db.commit()

    flash("Data karyawan berhasil diupdate", "success")
    return redirect("/hris/employee")


@hris_bp.route("/employee/delete/<int:employee_id>", methods=["POST"])
def delete_employee(employee_id):
    if not can_manage_employee_records():
        flash("Tidak punya akses untuk mengelola data karyawan", "error")
        return redirect("/hris/employee")

    db = get_db()
    employee = _get_employee_by_id(db, employee_id)
    if not employee:
        flash("Data karyawan tidak ditemukan", "error")
        return redirect("/hris/employee")

    db.execute("DELETE FROM employees WHERE id=?", (employee_id,))
    db.commit()

    flash("Data karyawan berhasil dihapus", "success")
    return redirect("/hris/employee")


@hris_bp.route("/attendance/add", methods=["POST"])
def add_attendance():
    if not can_manage_attendance_records():
        flash("Tidak punya akses untuk mengelola attendance", "error")
        return redirect("/hris/attendance")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    attendance_date = (request.form.get("attendance_date") or "").strip()
    check_in = (request.form.get("check_in") or "").strip()
    check_out = (request.form.get("check_out") or "").strip()
    status = _normalize_attendance_status(request.form.get("status"))
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/attendance")

    if not attendance_date:
        flash("Tanggal attendance wajib diisi", "error")
        return redirect("/hris/attendance")

    duplicate = db.execute(
        "SELECT id FROM attendance_records WHERE employee_id=? AND attendance_date=?",
        (employee_id, attendance_date),
    ).fetchone()
    if duplicate:
        flash("Attendance untuk tanggal tersebut sudah ada", "error")
        return redirect("/hris/attendance")

    db.execute(
        """
        INSERT INTO attendance_records(
            employee_id,
            warehouse_id,
            attendance_date,
            check_in,
            check_out,
            status,
            note,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,datetime('now'))
        """,
        (
            employee_id,
            employee["warehouse_id"],
            attendance_date,
            check_in or None,
            check_out or None,
            status,
            note or None,
        ),
    )
    db.commit()

    flash("Data attendance berhasil ditambahkan", "success")
    return redirect("/hris/attendance")


@hris_bp.route("/attendance/update/<int:attendance_id>", methods=["POST"])
def update_attendance(attendance_id):
    if not can_manage_attendance_records():
        flash("Tidak punya akses untuk mengelola attendance", "error")
        return redirect("/hris/attendance")

    db = get_db()
    attendance = _get_attendance_by_id(db, attendance_id)
    if not attendance:
        flash("Data attendance tidak ditemukan", "error")
        return redirect("/hris/attendance")

    employee_id = _to_int(request.form.get("employee_id"))
    attendance_date = (request.form.get("attendance_date") or "").strip()
    check_in = (request.form.get("check_in") or "").strip()
    check_out = (request.form.get("check_out") or "").strip()
    status = _normalize_attendance_status(request.form.get("status"))
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/attendance")

    if not attendance_date:
        flash("Tanggal attendance wajib diisi", "error")
        return redirect("/hris/attendance")

    duplicate = db.execute(
        "SELECT id FROM attendance_records WHERE employee_id=? AND attendance_date=? AND id<>?",
        (employee_id, attendance_date, attendance_id),
    ).fetchone()
    if duplicate:
        flash("Attendance untuk tanggal tersebut sudah digunakan record lain", "error")
        return redirect("/hris/attendance")

    db.execute(
        """
        UPDATE attendance_records
        SET employee_id=?,
            warehouse_id=?,
            attendance_date=?,
            check_in=?,
            check_out=?,
            status=?,
            note=?,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            attendance_date,
            check_in or None,
            check_out or None,
            status,
            note or None,
            attendance_id,
        ),
    )
    db.commit()

    flash("Data attendance berhasil diupdate", "success")
    return redirect("/hris/attendance")


@hris_bp.route("/attendance/delete/<int:attendance_id>", methods=["POST"])
def delete_attendance(attendance_id):
    if not can_manage_attendance_records():
        flash("Tidak punya akses untuk mengelola attendance", "error")
        return redirect("/hris/attendance")

    db = get_db()
    attendance = _get_attendance_by_id(db, attendance_id)
    if not attendance:
        flash("Data attendance tidak ditemukan", "error")
        return redirect("/hris/attendance")

    db.execute("DELETE FROM attendance_records WHERE id=?", (attendance_id,))
    db.commit()

    flash("Data attendance berhasil dihapus", "success")
    return redirect("/hris/attendance")


@hris_bp.route("/leave/add", methods=["POST"])
def add_leave():
    if not can_manage_leave_records():
        flash("Tidak punya akses untuk mengelola leave", "error")
        return _portal_redirect_for_module("leave") or redirect("/hris/leave")

    db = get_db()
    leave_type, _special_leave_reason, reason = _resolve_leave_submission_payload(
        request.form.get("leave_type"),
        request.form.get("special_leave_reason"),
        request.form.get("reason"),
    )
    start_date = (request.form.get("start_date") or "").strip()
    end_date = (request.form.get("end_date") or "").strip()
    status = _normalize_leave_status(request.form.get("status"))
    note = (request.form.get("note") or "").strip()

    employee, employee_error = _resolve_form_employee(db, request.form.get("employee_id"), "leave")
    if employee is None:
        flash(employee_error or "Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/leave")
    employee_id = employee["id"]

    total_days = _calculate_leave_days(start_date, end_date)
    if total_days is None:
        flash("Rentang tanggal leave tidak valid", "error")
        return redirect("/hris/leave")

    if not _strip_special_leave_reason_prefix(reason):
        flash("Alasan leave wajib diisi", "error")
        return redirect("/hris/leave")

    duplicate = db.execute(
        """
        SELECT id
        FROM leave_requests
        WHERE employee_id=? AND leave_type=? AND start_date=? AND end_date=? AND status<>?
        """,
        (employee_id, leave_type, start_date, end_date, "cancelled"),
    ).fetchone()
    if duplicate:
        flash("Leave request serupa sudah ada", "error")
        return redirect("/hris/leave")

    handled_by, handled_at = _build_leave_handling(status)

    cursor = db.execute(
        """
        INSERT INTO leave_requests(
            employee_id,
            warehouse_id,
            leave_type,
            start_date,
            end_date,
            total_days,
            status,
            reason,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            leave_type,
            start_date,
            end_date,
            total_days,
            status,
            reason,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    if status in {"approved", "rejected"}:
        try:
            created_leave = _get_leave_request_by_id(db, cursor.lastrowid)
            _notify_leave_request_status_change(db, created_leave)
        except Exception as exc:
            print("LEAVE APPROVAL NOTIFICATION ERROR:", exc)

    flash("Leave request berhasil ditambahkan", "success")
    return redirect("/hris/leave")


@hris_bp.route("/leave/update/<int:leave_id>", methods=["POST"])
def update_leave(leave_id):
    if not can_manage_leave_records():
        flash("Tidak punya akses untuk mengelola leave", "error")
        return _portal_redirect_for_module("leave") or redirect("/hris/leave")

    db = get_db()
    leave_request = _get_leave_request_by_id(db, leave_id)
    if not leave_request:
        flash("Leave request tidak ditemukan", "error")
        return redirect("/hris/leave")

    previous_status = leave_request["status"]
    leave_type, _special_leave_reason, reason = _resolve_leave_submission_payload(
        request.form.get("leave_type"),
        request.form.get("special_leave_reason"),
        request.form.get("reason"),
    )
    start_date = (request.form.get("start_date") or "").strip()
    end_date = (request.form.get("end_date") or "").strip()
    status = _normalize_leave_status(request.form.get("status"))
    note = (request.form.get("note") or "").strip()

    employee, employee_error = _resolve_form_employee(db, request.form.get("employee_id"), "leave")
    if employee is None:
        flash(employee_error or "Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/leave")
    employee_id = employee["id"]

    total_days = _calculate_leave_days(start_date, end_date)
    if total_days is None:
        flash("Rentang tanggal leave tidak valid", "error")
        return redirect("/hris/leave")

    if not _strip_special_leave_reason_prefix(reason):
        flash("Alasan leave wajib diisi", "error")
        return redirect("/hris/leave")

    duplicate = db.execute(
        """
        SELECT id
        FROM leave_requests
        WHERE employee_id=? AND leave_type=? AND start_date=? AND end_date=? AND status<>? AND id<>?
        """,
        (employee_id, leave_type, start_date, end_date, "cancelled", leave_id),
    ).fetchone()
    if duplicate:
        flash("Leave request serupa sudah digunakan record lain", "error")
        return redirect("/hris/leave")

    handled_by, handled_at = _build_leave_handling(status)

    db.execute(
        """
        UPDATE leave_requests
        SET employee_id=?,
            warehouse_id=?,
            leave_type=?,
            start_date=?,
            end_date=?,
            total_days=?,
            status=?,
            reason=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            leave_type,
            start_date,
            end_date,
            total_days,
            status,
            reason,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            leave_id,
        ),
    )
    db.commit()

    if status in {"approved", "rejected"} and status != previous_status:
        try:
            updated_leave = _get_leave_request_by_id(db, leave_id)
            _notify_leave_request_status_change(db, updated_leave, previous_status=previous_status)
        except Exception as exc:
            print("LEAVE APPROVAL NOTIFICATION ERROR:", exc)

    flash("Leave request berhasil diupdate", "success")
    return redirect("/hris/leave")


@hris_bp.route("/leave/delete/<int:leave_id>", methods=["POST"])
def delete_leave(leave_id):
    if not can_manage_leave_records():
        flash("Tidak punya akses untuk mengelola leave", "error")
        return _portal_redirect_for_module("leave") or redirect("/hris/leave")

    db = get_db()
    leave_request = _get_leave_request_by_id(db, leave_id)
    if not leave_request:
        flash("Leave request tidak ditemukan", "error")
        return redirect("/hris/leave")

    db.execute("DELETE FROM leave_requests WHERE id=?", (leave_id,))
    db.commit()

    flash("Leave request berhasil dihapus", "success")
    return redirect("/hris/leave")


@hris_bp.route("/payroll/add", methods=["POST"])
def add_payroll():
    if not can_manage_payroll_records():
        flash("Tidak punya akses untuk mengelola payroll", "error")
        return redirect("/hris/payroll")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    period_month = _to_int(request.form.get("period_month"))
    period_year = _to_int(request.form.get("period_year"))
    base_salary = _to_float(request.form.get("base_salary"))
    allowance = _to_float(request.form.get("allowance"))
    overtime_pay = _to_float(request.form.get("overtime_pay"))
    deduction = _to_float(request.form.get("deduction"))
    leave_deduction = _to_float(request.form.get("leave_deduction"))
    status = _normalize_payroll_status(request.form.get("status"))
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/payroll")

    if period_month is None or period_month < 1 or period_month > 12:
        flash("Periode bulan payroll tidak valid", "error")
        return redirect("/hris/payroll")

    if period_year is None or period_year < 2000 or period_year > 2100:
        flash("Periode tahun payroll tidak valid", "error")
        return redirect("/hris/payroll")

    duplicate = db.execute(
        "SELECT id FROM payroll_runs WHERE employee_id=? AND period_month=? AND period_year=?",
        (employee_id, period_month, period_year),
    ).fetchone()
    if duplicate:
        flash("Payroll untuk periode tersebut sudah ada", "error")
        return redirect("/hris/payroll")

    net_pay = _calculate_net_pay(base_salary, allowance, overtime_pay, deduction, leave_deduction)
    handled_by, handled_at = _build_payroll_handling(status)

    db.execute(
        """
        INSERT INTO payroll_runs(
            employee_id,
            warehouse_id,
            period_month,
            period_year,
            base_salary,
            allowance,
            overtime_pay,
            deduction,
            leave_deduction,
            net_pay,
            status,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            period_month,
            period_year,
            base_salary,
            allowance,
            overtime_pay,
            deduction,
            leave_deduction,
            net_pay,
            status,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Payroll berhasil ditambahkan", "success")
    return redirect("/hris/payroll")


@hris_bp.route("/payroll/update/<int:payroll_id>", methods=["POST"])
def update_payroll(payroll_id):
    if not can_manage_payroll_records():
        flash("Tidak punya akses untuk mengelola payroll", "error")
        return redirect("/hris/payroll")

    db = get_db()
    payroll = _get_payroll_by_id(db, payroll_id)
    if not payroll:
        flash("Data payroll tidak ditemukan", "error")
        return redirect("/hris/payroll")

    employee_id = _to_int(request.form.get("employee_id"))
    period_month = _to_int(request.form.get("period_month"))
    period_year = _to_int(request.form.get("period_year"))
    base_salary = _to_float(request.form.get("base_salary"))
    allowance = _to_float(request.form.get("allowance"))
    overtime_pay = _to_float(request.form.get("overtime_pay"))
    deduction = _to_float(request.form.get("deduction"))
    leave_deduction = _to_float(request.form.get("leave_deduction"))
    status = _normalize_payroll_status(request.form.get("status"))
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/payroll")

    if period_month is None or period_month < 1 or period_month > 12:
        flash("Periode bulan payroll tidak valid", "error")
        return redirect("/hris/payroll")

    if period_year is None or period_year < 2000 or period_year > 2100:
        flash("Periode tahun payroll tidak valid", "error")
        return redirect("/hris/payroll")

    duplicate = db.execute(
        "SELECT id FROM payroll_runs WHERE employee_id=? AND period_month=? AND period_year=? AND id<>?",
        (employee_id, period_month, period_year, payroll_id),
    ).fetchone()
    if duplicate:
        flash("Payroll untuk periode tersebut sudah digunakan record lain", "error")
        return redirect("/hris/payroll")

    net_pay = _calculate_net_pay(base_salary, allowance, overtime_pay, deduction, leave_deduction)
    handled_by, handled_at = _build_payroll_handling(status)

    db.execute(
        """
        UPDATE payroll_runs
        SET employee_id=?,
            warehouse_id=?,
            period_month=?,
            period_year=?,
            base_salary=?,
            allowance=?,
            overtime_pay=?,
            deduction=?,
            leave_deduction=?,
            net_pay=?,
            status=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            period_month,
            period_year,
            base_salary,
            allowance,
            overtime_pay,
            deduction,
            leave_deduction,
            net_pay,
            status,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            payroll_id,
        ),
    )
    db.commit()

    flash("Payroll berhasil diupdate", "success")
    return redirect("/hris/payroll")


@hris_bp.route("/payroll/delete/<int:payroll_id>", methods=["POST"])
def delete_payroll(payroll_id):
    if not can_manage_payroll_records():
        flash("Tidak punya akses untuk mengelola payroll", "error")
        return redirect("/hris/payroll")

    db = get_db()
    payroll = _get_payroll_by_id(db, payroll_id)
    if not payroll:
        flash("Data payroll tidak ditemukan", "error")
        return redirect("/hris/payroll")

    db.execute("DELETE FROM payroll_runs WHERE id=?", (payroll_id,))
    db.commit()

    flash("Payroll berhasil dihapus", "success")
    return redirect("/hris/payroll")


@hris_bp.route("/recruitment/add", methods=["POST"])
def add_recruitment():
    if not can_manage_recruitment_records():
        flash("Tidak punya akses untuk mengelola recruitment", "error")
        return redirect("/hris/recruitment")

    db = get_db()
    candidate_name = (request.form.get("candidate_name") or "").strip()
    position_title = (request.form.get("position_title") or "").strip()
    department = (request.form.get("department") or "").strip()
    stage = _normalize_recruitment_stage(request.form.get("stage"))
    status = _normalize_recruitment_status(request.form.get("status"))
    source = (request.form.get("source") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    expected_join_date = (request.form.get("expected_join_date") or "").strip()
    note = (request.form.get("note") or "").strip()
    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))

    if not candidate_name or not position_title:
        flash("Nama kandidat dan posisi wajib diisi", "error")
        return redirect("/hris/recruitment")

    if warehouse_id is None:
        flash("Gudang hiring wajib diisi", "error")
        return redirect("/hris/recruitment")

    handled_by, handled_at = _build_recruitment_handling(status)

    db.execute(
        """
        INSERT INTO recruitment_candidates(
            candidate_name,
            warehouse_id,
            position_title,
            department,
            stage,
            status,
            source,
            phone,
            email,
            expected_join_date,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            candidate_name,
            warehouse_id,
            position_title,
            department or None,
            stage,
            status,
            source or None,
            phone or None,
            email or None,
            expected_join_date or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Kandidat recruitment berhasil ditambahkan", "success")
    return redirect("/hris/recruitment")


@hris_bp.route("/recruitment/update/<int:candidate_id>", methods=["POST"])
def update_recruitment(candidate_id):
    if not can_manage_recruitment_records():
        flash("Tidak punya akses untuk mengelola recruitment", "error")
        return redirect("/hris/recruitment")

    db = get_db()
    candidate = _get_recruitment_candidate_by_id(db, candidate_id)
    if not candidate:
        flash("Data recruitment tidak ditemukan", "error")
        return redirect("/hris/recruitment")

    candidate_name = (request.form.get("candidate_name") or "").strip()
    position_title = (request.form.get("position_title") or "").strip()
    department = (request.form.get("department") or "").strip()
    stage = _normalize_recruitment_stage(request.form.get("stage"))
    status = _normalize_recruitment_status(request.form.get("status"))
    source = (request.form.get("source") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    expected_join_date = (request.form.get("expected_join_date") or "").strip()
    note = (request.form.get("note") or "").strip()
    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))

    if not candidate_name or not position_title:
        flash("Nama kandidat dan posisi wajib diisi", "error")
        return redirect("/hris/recruitment")

    if warehouse_id is None:
        flash("Gudang hiring wajib diisi", "error")
        return redirect("/hris/recruitment")

    handled_by, handled_at = _build_recruitment_handling(status)

    db.execute(
        """
        UPDATE recruitment_candidates
        SET candidate_name=?,
            warehouse_id=?,
            position_title=?,
            department=?,
            stage=?,
            status=?,
            source=?,
            phone=?,
            email=?,
            expected_join_date=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            candidate_name,
            warehouse_id,
            position_title,
            department or None,
            stage,
            status,
            source or None,
            phone or None,
            email or None,
            expected_join_date or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            candidate_id,
        ),
    )
    db.commit()

    flash("Kandidat recruitment berhasil diupdate", "success")
    return redirect("/hris/recruitment")


@hris_bp.route("/recruitment/delete/<int:candidate_id>", methods=["POST"])
def delete_recruitment(candidate_id):
    if not can_manage_recruitment_records():
        flash("Tidak punya akses untuk mengelola recruitment", "error")
        return redirect("/hris/recruitment")

    db = get_db()
    candidate = _get_recruitment_candidate_by_id(db, candidate_id)
    if not candidate:
        flash("Data recruitment tidak ditemukan", "error")
        return redirect("/hris/recruitment")

    db.execute("DELETE FROM recruitment_candidates WHERE id=?", (candidate_id,))
    db.commit()

    flash("Kandidat recruitment berhasil dihapus", "success")
    return redirect("/hris/recruitment")


@hris_bp.route("/onboarding/add", methods=["POST"])
def add_onboarding():
    if not can_manage_onboarding_records():
        flash("Tidak punya akses untuk mengelola onboarding", "error")
        return redirect("/hris/onboarding")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    start_date = (request.form.get("start_date") or "").strip()
    target_date = (request.form.get("target_date") or "").strip()
    stage = _normalize_onboarding_stage(request.form.get("stage"))
    status = _normalize_onboarding_status(request.form.get("status"))
    buddy_name = (request.form.get("buddy_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/onboarding")

    if _calculate_leave_days(start_date, start_date) is None:
        flash("Tanggal mulai onboarding tidak valid", "error")
        return redirect("/hris/onboarding")

    if target_date and _calculate_leave_days(start_date, target_date) is None:
        flash("Rentang tanggal onboarding tidak valid", "error")
        return redirect("/hris/onboarding")

    duplicate = db.execute(
        "SELECT id FROM onboarding_records WHERE employee_id=?",
        (employee_id,),
    ).fetchone()
    if duplicate:
        flash("Onboarding untuk karyawan ini sudah ada", "error")
        return redirect("/hris/onboarding")

    handled_by, handled_at = _build_onboarding_handling(status)

    db.execute(
        """
        INSERT INTO onboarding_records(
            employee_id,
            warehouse_id,
            start_date,
            target_date,
            stage,
            status,
            buddy_name,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            start_date,
            target_date or None,
            stage,
            status,
            buddy_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Onboarding berhasil ditambahkan", "success")
    return redirect("/hris/onboarding")


@hris_bp.route("/onboarding/update/<int:onboarding_id>", methods=["POST"])
def update_onboarding(onboarding_id):
    if not can_manage_onboarding_records():
        flash("Tidak punya akses untuk mengelola onboarding", "error")
        return redirect("/hris/onboarding")

    db = get_db()
    onboarding = _get_onboarding_by_id(db, onboarding_id)
    if not onboarding:
        flash("Data onboarding tidak ditemukan", "error")
        return redirect("/hris/onboarding")

    employee_id = _to_int(request.form.get("employee_id"))
    start_date = (request.form.get("start_date") or "").strip()
    target_date = (request.form.get("target_date") or "").strip()
    stage = _normalize_onboarding_stage(request.form.get("stage"))
    status = _normalize_onboarding_status(request.form.get("status"))
    buddy_name = (request.form.get("buddy_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/onboarding")

    if _calculate_leave_days(start_date, start_date) is None:
        flash("Tanggal mulai onboarding tidak valid", "error")
        return redirect("/hris/onboarding")

    if target_date and _calculate_leave_days(start_date, target_date) is None:
        flash("Rentang tanggal onboarding tidak valid", "error")
        return redirect("/hris/onboarding")

    duplicate = db.execute(
        "SELECT id FROM onboarding_records WHERE employee_id=? AND id<>?",
        (employee_id, onboarding_id),
    ).fetchone()
    if duplicate:
        flash("Onboarding untuk karyawan ini sudah digunakan record lain", "error")
        return redirect("/hris/onboarding")

    handled_by, handled_at = _build_onboarding_handling(status)

    db.execute(
        """
        UPDATE onboarding_records
        SET employee_id=?,
            warehouse_id=?,
            start_date=?,
            target_date=?,
            stage=?,
            status=?,
            buddy_name=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            start_date,
            target_date or None,
            stage,
            status,
            buddy_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            onboarding_id,
        ),
    )
    db.commit()

    flash("Onboarding berhasil diupdate", "success")
    return redirect("/hris/onboarding")


@hris_bp.route("/onboarding/delete/<int:onboarding_id>", methods=["POST"])
def delete_onboarding(onboarding_id):
    if not can_manage_onboarding_records():
        flash("Tidak punya akses untuk mengelola onboarding", "error")
        return redirect("/hris/onboarding")

    db = get_db()
    onboarding = _get_onboarding_by_id(db, onboarding_id)
    if not onboarding:
        flash("Data onboarding tidak ditemukan", "error")
        return redirect("/hris/onboarding")

    db.execute("DELETE FROM onboarding_records WHERE id=?", (onboarding_id,))
    db.commit()

    flash("Onboarding berhasil dihapus", "success")
    return redirect("/hris/onboarding")


@hris_bp.route("/offboarding/add", methods=["POST"])
def add_offboarding():
    if not can_manage_offboarding_records():
        flash("Tidak punya akses untuk mengelola offboarding", "error")
        return redirect("/hris/offboarding")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    notice_date = (request.form.get("notice_date") or "").strip()
    last_working_date = (request.form.get("last_working_date") or "").strip()
    stage = _normalize_offboarding_stage(request.form.get("stage"))
    status = _normalize_offboarding_status(request.form.get("status"))
    exit_reason = (request.form.get("exit_reason") or "").strip()
    handover_pic = (request.form.get("handover_pic") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/offboarding")

    if _calculate_leave_days(notice_date, notice_date) is None:
        flash("Tanggal notice offboarding tidak valid", "error")
        return redirect("/hris/offboarding")

    if last_working_date and _calculate_leave_days(notice_date, last_working_date) is None:
        flash("Rentang tanggal offboarding tidak valid", "error")
        return redirect("/hris/offboarding")

    duplicate = db.execute(
        "SELECT id FROM offboarding_records WHERE employee_id=?",
        (employee_id,),
    ).fetchone()
    if duplicate:
        flash("Offboarding untuk karyawan ini sudah ada", "error")
        return redirect("/hris/offboarding")

    handled_by, handled_at = _build_offboarding_handling(status)

    db.execute(
        """
        INSERT INTO offboarding_records(
            employee_id,
            warehouse_id,
            notice_date,
            last_working_date,
            stage,
            status,
            exit_reason,
            handover_pic,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            notice_date,
            last_working_date or None,
            stage,
            status,
            exit_reason or None,
            handover_pic or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Offboarding berhasil ditambahkan", "success")
    return redirect("/hris/offboarding")


@hris_bp.route("/offboarding/update/<int:offboarding_id>", methods=["POST"])
def update_offboarding(offboarding_id):
    if not can_manage_offboarding_records():
        flash("Tidak punya akses untuk mengelola offboarding", "error")
        return redirect("/hris/offboarding")

    db = get_db()
    offboarding = _get_offboarding_by_id(db, offboarding_id)
    if not offboarding:
        flash("Data offboarding tidak ditemukan", "error")
        return redirect("/hris/offboarding")

    employee_id = _to_int(request.form.get("employee_id"))
    notice_date = (request.form.get("notice_date") or "").strip()
    last_working_date = (request.form.get("last_working_date") or "").strip()
    stage = _normalize_offboarding_stage(request.form.get("stage"))
    status = _normalize_offboarding_status(request.form.get("status"))
    exit_reason = (request.form.get("exit_reason") or "").strip()
    handover_pic = (request.form.get("handover_pic") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/offboarding")

    if _calculate_leave_days(notice_date, notice_date) is None:
        flash("Tanggal notice offboarding tidak valid", "error")
        return redirect("/hris/offboarding")

    if last_working_date and _calculate_leave_days(notice_date, last_working_date) is None:
        flash("Rentang tanggal offboarding tidak valid", "error")
        return redirect("/hris/offboarding")

    duplicate = db.execute(
        "SELECT id FROM offboarding_records WHERE employee_id=? AND id<>?",
        (employee_id, offboarding_id),
    ).fetchone()
    if duplicate:
        flash("Offboarding untuk karyawan ini sudah digunakan record lain", "error")
        return redirect("/hris/offboarding")

    handled_by, handled_at = _build_offboarding_handling(status)

    db.execute(
        """
        UPDATE offboarding_records
        SET employee_id=?,
            warehouse_id=?,
            notice_date=?,
            last_working_date=?,
            stage=?,
            status=?,
            exit_reason=?,
            handover_pic=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            notice_date,
            last_working_date or None,
            stage,
            status,
            exit_reason or None,
            handover_pic or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            offboarding_id,
        ),
    )
    db.commit()

    flash("Offboarding berhasil diupdate", "success")
    return redirect("/hris/offboarding")


@hris_bp.route("/offboarding/delete/<int:offboarding_id>", methods=["POST"])
def delete_offboarding(offboarding_id):
    if not can_manage_offboarding_records():
        flash("Tidak punya akses untuk mengelola offboarding", "error")
        return redirect("/hris/offboarding")

    db = get_db()
    offboarding = _get_offboarding_by_id(db, offboarding_id)
    if not offboarding:
        flash("Data offboarding tidak ditemukan", "error")
        return redirect("/hris/offboarding")

    db.execute("DELETE FROM offboarding_records WHERE id=?", (offboarding_id,))
    db.commit()

    flash("Offboarding berhasil dihapus", "success")
    return redirect("/hris/offboarding")


@hris_bp.route("/performance/add", methods=["POST"])
def add_performance():
    if not can_manage_performance_records():
        flash("Tidak punya akses untuk mengelola performance", "error")
        return redirect("/hris/pms")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    review_period = (request.form.get("review_period") or "").strip()
    goal_score = _to_float(request.form.get("goal_score"))
    discipline_score = _to_float(request.form.get("discipline_score"))
    teamwork_score = _to_float(request.form.get("teamwork_score"))
    status = _normalize_performance_status(request.form.get("status"))
    reviewer_name = (request.form.get("reviewer_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/pms")

    if not review_period:
        flash("Periode review wajib diisi", "error")
        return redirect("/hris/pms")

    duplicate = db.execute(
        "SELECT id FROM performance_reviews WHERE employee_id=? AND review_period=?",
        (employee_id, review_period),
    ).fetchone()
    if duplicate:
        flash("Performance review untuk periode tersebut sudah ada", "error")
        return redirect("/hris/pms")

    final_score = _calculate_performance_score(goal_score, discipline_score, teamwork_score)
    rating = _derive_performance_rating(final_score)
    handled_by, handled_at = _build_performance_handling(status)

    db.execute(
        """
        INSERT INTO performance_reviews(
            employee_id,
            warehouse_id,
            review_period,
            goal_score,
            discipline_score,
            teamwork_score,
            final_score,
            rating,
            status,
            reviewer_name,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            review_period,
            goal_score,
            discipline_score,
            teamwork_score,
            final_score,
            rating,
            status,
            reviewer_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Performance review berhasil ditambahkan", "success")
    return redirect("/hris/pms")


@hris_bp.route("/performance/update/<int:review_id>", methods=["POST"])
def update_performance(review_id):
    if not can_manage_performance_records():
        flash("Tidak punya akses untuk mengelola performance", "error")
        return redirect("/hris/pms")

    db = get_db()
    review = _get_performance_by_id(db, review_id)
    if not review:
        flash("Data performance tidak ditemukan", "error")
        return redirect("/hris/pms")

    employee_id = _to_int(request.form.get("employee_id"))
    review_period = (request.form.get("review_period") or "").strip()
    goal_score = _to_float(request.form.get("goal_score"))
    discipline_score = _to_float(request.form.get("discipline_score"))
    teamwork_score = _to_float(request.form.get("teamwork_score"))
    status = _normalize_performance_status(request.form.get("status"))
    reviewer_name = (request.form.get("reviewer_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/pms")

    if not review_period:
        flash("Periode review wajib diisi", "error")
        return redirect("/hris/pms")

    duplicate = db.execute(
        "SELECT id FROM performance_reviews WHERE employee_id=? AND review_period=? AND id<>?",
        (employee_id, review_period, review_id),
    ).fetchone()
    if duplicate:
        flash("Performance review untuk periode tersebut sudah digunakan record lain", "error")
        return redirect("/hris/pms")

    final_score = _calculate_performance_score(goal_score, discipline_score, teamwork_score)
    rating = _derive_performance_rating(final_score)
    handled_by, handled_at = _build_performance_handling(status)

    db.execute(
        """
        UPDATE performance_reviews
        SET employee_id=?,
            warehouse_id=?,
            review_period=?,
            goal_score=?,
            discipline_score=?,
            teamwork_score=?,
            final_score=?,
            rating=?,
            status=?,
            reviewer_name=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            review_period,
            goal_score,
            discipline_score,
            teamwork_score,
            final_score,
            rating,
            status,
            reviewer_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            review_id,
        ),
    )
    db.commit()

    flash("Performance review berhasil diupdate", "success")
    return redirect("/hris/pms")


@hris_bp.route("/performance/delete/<int:review_id>", methods=["POST"])
def delete_performance(review_id):
    if not can_manage_performance_records():
        flash("Tidak punya akses untuk mengelola performance", "error")
        return redirect("/hris/pms")

    db = get_db()
    review = _get_performance_by_id(db, review_id)
    if not review:
        flash("Data performance tidak ditemukan", "error")
        return redirect("/hris/pms")

    db.execute("DELETE FROM performance_reviews WHERE id=?", (review_id,))
    db.commit()

    flash("Performance review berhasil dihapus", "success")
    return redirect("/hris/pms")


@hris_bp.route("/pms/report/<int:report_id>/review", methods=["POST"])
def review_kpi_staff_report(report_id):
    return_to = _safe_hris_return_to("/hris/pms")
    if not can_manage_performance_records():
        flash("Tidak punya akses untuk mereview KPI staff.", "error")
        return redirect(return_to)

    db = get_db()
    report = _get_kpi_staff_report_by_id(db, report_id)
    if not report:
        flash("Data KPI staff tidak ditemukan.", "error")
        return redirect(return_to)

    status = normalize_kpi_report_status(request.form.get("status"))
    review_note = (request.form.get("review_note") or "").strip()
    reviewed_by = session.get("user_id") if status in {"reviewed", "follow_up"} else None
    reviewed_at = _current_timestamp() if reviewed_by else None

    db.execute(
        """
        UPDATE kpi_staff_reports
        SET status=?,
            review_note=?,
            reviewed_by=?,
            reviewed_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            status,
            review_note or None,
            reviewed_by,
            reviewed_at,
            _current_timestamp(),
            report_id,
        ),
    )
    db.commit()

    flash("Status KPI staff berhasil diperbarui.", "success")
    return redirect(return_to)


@hris_bp.route("/pms/target/add", methods=["POST"])
def add_kpi_target_plan():
    return_to = _safe_hris_return_to("/hris/pms")
    if not can_manage_performance_records():
        flash("Tidak punya akses untuk mengelola target KPI staff.", "error")
        return redirect(return_to)

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini.", "error")
        return redirect(return_to)
    employee = dict(employee)

    period_label = normalize_kpi_period_label(request.form.get("period_label"))
    minimum_pass_score = _to_float(request.form.get("minimum_pass_score"))
    summary = (request.form.get("summary") or "").strip()
    team_focus_items = _normalize_kpi_team_focus_items(request.form.get("team_focus_text"))

    try:
        metric_rows = _extract_kpi_metric_rows_from_form(request.form)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(return_to)

    duplicate = db.execute(
        "SELECT id FROM kpi_target_plans WHERE employee_id=? AND period_label=?",
        (employee["id"], period_label),
    ).fetchone()
    if duplicate:
        flash("Target KPI untuk staff dan periode tersebut sudah ada. Silakan edit yang sudah tersedia.", "error")
        return redirect(return_to)

    reference_profile = resolve_kpi_profile(
        employee_name=employee.get("full_name"),
        warehouse_name=employee.get("warehouse_name"),
        work_location=employee.get("work_location"),
        position=employee.get("position"),
    )
    warehouse_group = (
        reference_profile.get("warehouse_group")
        if reference_profile
        else ("mega" if "mega" in str(employee.get("warehouse_name") or "").lower() else "mataram")
    )
    warehouse_label = (
        reference_profile.get("warehouse_label")
        if reference_profile
        else str(employee.get("warehouse_name") or "Gudang").strip()
    )

    db.execute(
        """
        INSERT INTO kpi_target_plans(
            employee_id,
            warehouse_id,
            period_label,
            template_key,
            template_name,
            warehouse_group,
            warehouse_label,
            minimum_pass_score,
            summary,
            team_focus_payload,
            metric_payload,
            created_by,
            updated_by,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee["id"],
            employee["warehouse_id"],
            period_label,
            (reference_profile.get("key") if reference_profile else None),
            employee.get("full_name") or (reference_profile.get("display_name") if reference_profile else "Target KPI Staff"),
            warehouse_group,
            warehouse_label,
            float(minimum_pass_score or 0),
            summary or None,
            json.dumps(team_focus_items, ensure_ascii=False),
            json.dumps(metric_rows, ensure_ascii=False),
            session.get("user_id"),
            session.get("user_id"),
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Target KPI bulanan berhasil ditambahkan.", "success")
    return redirect(return_to)


@hris_bp.route("/pms/target/update/<int:plan_id>", methods=["POST"])
def update_kpi_target_plan(plan_id):
    return_to = _safe_hris_return_to("/hris/pms")
    if not can_manage_performance_records():
        flash("Tidak punya akses untuk mengelola target KPI staff.", "error")
        return redirect(return_to)

    db = get_db()
    plan = _get_kpi_target_plan_by_id(db, plan_id)
    if not plan:
        flash("Target KPI bulanan tidak ditemukan.", "error")
        return redirect(return_to)

    employee = _get_accessible_employee(db, plan["employee_id"])
    if not employee:
        flash("Karyawan target KPI tidak valid untuk scope akun ini.", "error")
        return redirect(return_to)
    employee = dict(employee)

    period_label = normalize_kpi_period_label(request.form.get("period_label"))
    minimum_pass_score = _to_float(request.form.get("minimum_pass_score"))
    summary = (request.form.get("summary") or "").strip()
    team_focus_items = _normalize_kpi_team_focus_items(request.form.get("team_focus_text"))

    try:
        metric_rows = _extract_kpi_metric_rows_from_form(request.form)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(return_to)

    duplicate = db.execute(
        "SELECT id FROM kpi_target_plans WHERE employee_id=? AND period_label=? AND id<>?",
        (employee["id"], period_label, plan_id),
    ).fetchone()
    if duplicate:
        flash("Periode target KPI ini sudah dipakai record lain untuk staff yang sama.", "error")
        return redirect(return_to)

    reference_profile = resolve_kpi_profile(
        employee_name=employee.get("full_name"),
        warehouse_name=employee.get("warehouse_name"),
        work_location=employee.get("work_location"),
        position=employee.get("position"),
    )
    warehouse_group = (
        reference_profile.get("warehouse_group")
        if reference_profile
        else ("mega" if "mega" in str(employee.get("warehouse_name") or "").lower() else "mataram")
    )
    warehouse_label = (
        reference_profile.get("warehouse_label")
        if reference_profile
        else str(employee.get("warehouse_name") or "Gudang").strip()
    )

    db.execute(
        """
        UPDATE kpi_target_plans
        SET period_label=?,
            template_key=?,
            template_name=?,
            warehouse_group=?,
            warehouse_label=?,
            minimum_pass_score=?,
            summary=?,
            team_focus_payload=?,
            metric_payload=?,
            updated_by=?,
            updated_at=?
        WHERE id=?
        """,
        (
            period_label,
            (reference_profile.get("key") if reference_profile else plan.get("template_key")),
            employee.get("full_name") or plan.get("template_name") or "Target KPI Staff",
            warehouse_group,
            warehouse_label,
            float(minimum_pass_score or 0),
            summary or None,
            json.dumps(team_focus_items, ensure_ascii=False),
            json.dumps(metric_rows, ensure_ascii=False),
            session.get("user_id"),
            _current_timestamp(),
            plan_id,
        ),
    )
    db.commit()

    flash("Target KPI bulanan berhasil diupdate.", "success")
    return redirect(return_to)


@hris_bp.route("/pms/target/delete/<int:plan_id>", methods=["POST"])
def delete_kpi_target_plan(plan_id):
    return_to = _safe_hris_return_to("/hris/pms")
    if not can_manage_performance_records():
        flash("Tidak punya akses untuk mengelola target KPI staff.", "error")
        return redirect(return_to)

    db = get_db()
    plan = _get_kpi_target_plan_by_id(db, plan_id)
    if not plan:
        flash("Target KPI bulanan tidak ditemukan.", "error")
        return redirect(return_to)

    db.execute("DELETE FROM kpi_target_plans WHERE id=?", (plan_id,))
    db.commit()

    flash("Target KPI bulanan berhasil dihapus.", "success")
    return redirect(return_to)


@hris_bp.route("/helpdesk/add", methods=["POST"])
def add_helpdesk():
    if not can_manage_helpdesk_records():
        flash("Tidak punya akses untuk mengelola helpdesk", "error")
        return redirect("/hris/helpdesk")

    db = get_db()
    ticket_title = (request.form.get("ticket_title") or "").strip()
    category = _normalize_helpdesk_category(request.form.get("category"))
    priority = _normalize_helpdesk_priority(request.form.get("priority"))
    status = _normalize_helpdesk_status(request.form.get("status"))
    channel = (request.form.get("channel") or "").strip()
    assigned_to = (request.form.get("assigned_to") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee, employee_error = _resolve_form_employee(db, request.form.get("employee_id"), "helpdesk")
    if employee is None:
        flash(employee_error or "Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/helpdesk")
    employee_id = employee["id"]

    if not ticket_title:
        flash("Judul ticket wajib diisi", "error")
        return redirect("/hris/helpdesk")

    handled_by, handled_at = _build_helpdesk_handling(status)

    db.execute(
        """
        INSERT INTO helpdesk_tickets(
            employee_id,
            warehouse_id,
            ticket_title,
            category,
            priority,
            status,
            channel,
            assigned_to,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            ticket_title,
            category,
            priority,
            status,
            channel or None,
            assigned_to or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Ticket helpdesk berhasil ditambahkan", "success")
    return redirect("/hris/helpdesk")


@hris_bp.route("/helpdesk/update/<int:ticket_id>", methods=["POST"])
def update_helpdesk(ticket_id):
    if not can_manage_helpdesk_records():
        flash("Tidak punya akses untuk mengelola helpdesk", "error")
        return redirect("/hris/helpdesk")

    db = get_db()
    ticket = _get_helpdesk_ticket_by_id(db, ticket_id)
    if not ticket:
        flash("Ticket helpdesk tidak ditemukan", "error")
        return redirect("/hris/helpdesk")

    ticket_title = (request.form.get("ticket_title") or "").strip()
    category = _normalize_helpdesk_category(request.form.get("category"))
    priority = _normalize_helpdesk_priority(request.form.get("priority"))
    status = _normalize_helpdesk_status(request.form.get("status"))
    channel = (request.form.get("channel") or "").strip()
    assigned_to = (request.form.get("assigned_to") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee, employee_error = _resolve_form_employee(db, request.form.get("employee_id"), "helpdesk")
    if employee is None:
        flash(employee_error or "Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/helpdesk")
    employee_id = employee["id"]

    if not ticket_title:
        flash("Judul ticket wajib diisi", "error")
        return redirect("/hris/helpdesk")

    handled_by, handled_at = _build_helpdesk_handling(status)

    db.execute(
        """
        UPDATE helpdesk_tickets
        SET employee_id=?,
            warehouse_id=?,
            ticket_title=?,
            category=?,
            priority=?,
            status=?,
            channel=?,
            assigned_to=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            ticket_title,
            category,
            priority,
            status,
            channel or None,
            assigned_to or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            ticket_id,
        ),
    )
    db.commit()

    flash("Ticket helpdesk berhasil diupdate", "success")
    return redirect("/hris/helpdesk")


@hris_bp.route("/helpdesk/delete/<int:ticket_id>", methods=["POST"])
def delete_helpdesk(ticket_id):
    if not can_manage_helpdesk_records():
        flash("Tidak punya akses untuk mengelola helpdesk", "error")
        return redirect("/hris/helpdesk")

    db = get_db()
    ticket = _get_helpdesk_ticket_by_id(db, ticket_id)
    if not ticket:
        flash("Ticket helpdesk tidak ditemukan", "error")
        return redirect("/hris/helpdesk")

    db.execute("DELETE FROM helpdesk_tickets WHERE id=?", (ticket_id,))
    db.commit()

    flash("Ticket helpdesk berhasil dihapus", "success")
    return redirect("/hris/helpdesk")


@hris_bp.route("/asset/add", methods=["POST"])
def add_asset():
    if not can_manage_asset_records():
        flash("Tidak punya akses untuk mengelola asset", "error")
        return redirect("/hris/asset")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    asset_name = (request.form.get("asset_name") or "").strip()
    asset_code = (request.form.get("asset_code") or "").strip().upper()
    serial_number = (request.form.get("serial_number") or "").strip()
    category = (request.form.get("category") or "").strip()
    asset_status = _normalize_asset_status(request.form.get("asset_status"))
    condition_status = _normalize_asset_condition(request.form.get("condition_status"))
    assigned_date = (request.form.get("assigned_date") or "").strip()
    return_date = (request.form.get("return_date") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/asset")

    if not asset_name or not asset_code or not assigned_date:
        flash("Nama asset, kode asset, dan tanggal assign wajib diisi", "error")
        return redirect("/hris/asset")

    if _calculate_leave_days(assigned_date, assigned_date) is None:
        flash("Tanggal assign asset tidak valid", "error")
        return redirect("/hris/asset")

    if return_date and _calculate_leave_days(assigned_date, return_date) is None:
        flash("Rentang tanggal asset tidak valid", "error")
        return redirect("/hris/asset")

    duplicate = db.execute(
        "SELECT id FROM asset_records WHERE asset_code=?",
        (asset_code,),
    ).fetchone()
    if duplicate:
        flash("Kode asset sudah digunakan", "error")
        return redirect("/hris/asset")

    handled_by, handled_at = _build_asset_handling(asset_status)

    db.execute(
        """
        INSERT INTO asset_records(
            employee_id,
            warehouse_id,
            asset_name,
            asset_code,
            serial_number,
            category,
            asset_status,
            condition_status,
            assigned_date,
            return_date,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            asset_name,
            asset_code,
            serial_number or None,
            category or None,
            asset_status,
            condition_status,
            assigned_date,
            return_date or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Asset record berhasil ditambahkan", "success")
    return redirect("/hris/asset")


@hris_bp.route("/asset/update/<int:asset_id>", methods=["POST"])
def update_asset(asset_id):
    if not can_manage_asset_records():
        flash("Tidak punya akses untuk mengelola asset", "error")
        return redirect("/hris/asset")

    db = get_db()
    asset = _get_asset_record_by_id(db, asset_id)
    if not asset:
        flash("Asset record tidak ditemukan", "error")
        return redirect("/hris/asset")

    employee_id = _to_int(request.form.get("employee_id"))
    asset_name = (request.form.get("asset_name") or "").strip()
    asset_code = (request.form.get("asset_code") or "").strip().upper()
    serial_number = (request.form.get("serial_number") or "").strip()
    category = (request.form.get("category") or "").strip()
    asset_status = _normalize_asset_status(request.form.get("asset_status"))
    condition_status = _normalize_asset_condition(request.form.get("condition_status"))
    assigned_date = (request.form.get("assigned_date") or "").strip()
    return_date = (request.form.get("return_date") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/asset")

    if not asset_name or not asset_code or not assigned_date:
        flash("Nama asset, kode asset, dan tanggal assign wajib diisi", "error")
        return redirect("/hris/asset")

    if _calculate_leave_days(assigned_date, assigned_date) is None:
        flash("Tanggal assign asset tidak valid", "error")
        return redirect("/hris/asset")

    if return_date and _calculate_leave_days(assigned_date, return_date) is None:
        flash("Rentang tanggal asset tidak valid", "error")
        return redirect("/hris/asset")

    duplicate = db.execute(
        "SELECT id FROM asset_records WHERE asset_code=? AND id<>?",
        (asset_code, asset_id),
    ).fetchone()
    if duplicate:
        flash("Kode asset sudah digunakan record lain", "error")
        return redirect("/hris/asset")

    handled_by, handled_at = _build_asset_handling(asset_status)

    db.execute(
        """
        UPDATE asset_records
        SET employee_id=?,
            warehouse_id=?,
            asset_name=?,
            asset_code=?,
            serial_number=?,
            category=?,
            asset_status=?,
            condition_status=?,
            assigned_date=?,
            return_date=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            asset_name,
            asset_code,
            serial_number or None,
            category or None,
            asset_status,
            condition_status,
            assigned_date,
            return_date or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            asset_id,
        ),
    )
    db.commit()

    flash("Asset record berhasil diupdate", "success")
    return redirect("/hris/asset")


@hris_bp.route("/asset/delete/<int:asset_id>", methods=["POST"])
def delete_asset(asset_id):
    if not can_manage_asset_records():
        flash("Tidak punya akses untuk mengelola asset", "error")
        return redirect("/hris/asset")

    db = get_db()
    asset = _get_asset_record_by_id(db, asset_id)
    if not asset:
        flash("Asset record tidak ditemukan", "error")
        return redirect("/hris/asset")

    db.execute("DELETE FROM asset_records WHERE id=?", (asset_id,))
    db.commit()

    flash("Asset record berhasil dihapus", "success")
    return redirect("/hris/asset")


@hris_bp.route("/project/add", methods=["POST"])
def add_project():
    if not can_manage_project_records():
        flash("Tidak punya akses untuk mengelola project", "error")
        return redirect("/hris/project")

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    project_name = (request.form.get("project_name") or "").strip()
    project_code = (request.form.get("project_code") or "").strip().upper()
    priority = _normalize_project_priority(request.form.get("priority"))
    status = _normalize_project_status(request.form.get("status"))
    start_date = (request.form.get("start_date") or "").strip()
    due_date = (request.form.get("due_date") or "").strip()
    progress_percent = max(0, min(100, _to_int(request.form.get("progress_percent"), 0) or 0))
    owner_name = (request.form.get("owner_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/project")

    if not project_name or not project_code or not start_date:
        flash("Nama project, kode project, dan start date wajib diisi", "error")
        return redirect("/hris/project")

    if _calculate_leave_days(start_date, start_date) is None:
        flash("Tanggal mulai project tidak valid", "error")
        return redirect("/hris/project")

    if due_date and _calculate_leave_days(start_date, due_date) is None:
        flash("Rentang tanggal project tidak valid", "error")
        return redirect("/hris/project")

    duplicate = db.execute(
        "SELECT id FROM project_records WHERE project_code=?",
        (project_code,),
    ).fetchone()
    if duplicate:
        flash("Kode project sudah digunakan", "error")
        return redirect("/hris/project")

    handled_by, handled_at = _build_project_handling(status)
    db.execute(
        """
        INSERT INTO project_records(
            employee_id,
            warehouse_id,
            project_name,
            project_code,
            priority,
            status,
            start_date,
            due_date,
            progress_percent,
            owner_name,
            note,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            employee_id,
            employee["warehouse_id"],
            project_name,
            project_code,
            priority,
            status,
            start_date,
            due_date or None,
            progress_percent,
            owner_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Project berhasil ditambahkan", "success")
    return redirect("/hris/project")


@hris_bp.route("/project/update/<int:project_id>", methods=["POST"])
def update_project(project_id):
    if not can_manage_project_records():
        flash("Tidak punya akses untuk mengelola project", "error")
        return redirect("/hris/project")

    db = get_db()
    project = _get_project_by_id(db, project_id)
    if not project:
        flash("Project tidak ditemukan", "error")
        return redirect("/hris/project")

    employee_id = _to_int(request.form.get("employee_id"))
    project_name = (request.form.get("project_name") or "").strip()
    project_code = (request.form.get("project_code") or "").strip().upper()
    priority = _normalize_project_priority(request.form.get("priority"))
    status = _normalize_project_status(request.form.get("status"))
    start_date = (request.form.get("start_date") or "").strip()
    due_date = (request.form.get("due_date") or "").strip()
    progress_percent = max(0, min(100, _to_int(request.form.get("progress_percent"), 0) or 0))
    owner_name = (request.form.get("owner_name") or "").strip()
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if not employee:
        flash("Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/project")

    if not project_name or not project_code or not start_date:
        flash("Nama project, kode project, dan start date wajib diisi", "error")
        return redirect("/hris/project")

    if _calculate_leave_days(start_date, start_date) is None:
        flash("Tanggal mulai project tidak valid", "error")
        return redirect("/hris/project")

    if due_date and _calculate_leave_days(start_date, due_date) is None:
        flash("Rentang tanggal project tidak valid", "error")
        return redirect("/hris/project")

    duplicate = db.execute(
        "SELECT id FROM project_records WHERE project_code=? AND id<>?",
        (project_code, project_id),
    ).fetchone()
    if duplicate:
        flash("Kode project sudah digunakan record lain", "error")
        return redirect("/hris/project")

    handled_by, handled_at = _build_project_handling(status)
    db.execute(
        """
        UPDATE project_records
        SET employee_id=?,
            warehouse_id=?,
            project_name=?,
            project_code=?,
            priority=?,
            status=?,
            start_date=?,
            due_date=?,
            progress_percent=?,
            owner_name=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            project_name,
            project_code,
            priority,
            status,
            start_date,
            due_date or None,
            progress_percent,
            owner_name or None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            project_id,
        ),
    )
    db.commit()

    flash("Project berhasil diupdate", "success")
    return redirect("/hris/project")


@hris_bp.route("/project/delete/<int:project_id>", methods=["POST"])
def delete_project(project_id):
    if not can_manage_project_records():
        flash("Tidak punya akses untuk mengelola project", "error")
        return redirect("/hris/project")

    db = get_db()
    project = _get_project_by_id(db, project_id)
    if not project:
        flash("Project tidak ditemukan", "error")
        return redirect("/hris/project")

    db.execute("DELETE FROM project_records WHERE id=?", (project_id,))
    db.commit()

    flash("Project berhasil dihapus", "success")
    return redirect("/hris/project")


@hris_bp.route("/biometric/add", methods=["POST"])
def add_biometric():
    if not can_manage_biometric_records():
        flash("Tidak punya akses untuk mengelola geotag absensi", "error")
        return _portal_redirect_for_module("biometric") or redirect("/hris/biometric")

    db = get_db()
    location_label = _normalize_biometric_location_label(request.form.get("location_label"))
    latitude = _normalize_latitude(request.form.get("latitude"))
    longitude = _normalize_longitude(request.form.get("longitude"))
    accuracy_m = _normalize_accuracy(request.form.get("accuracy_m"))
    punch_time = _normalize_datetime_input(request.form.get("punch_time"))
    punch_type = _normalize_biometric_punch_type(request.form.get("punch_type"))
    sync_status = _normalize_biometric_sync_status(request.form.get("sync_status"))
    photo_data_url = request.form.get("photo_data_url")
    note = (request.form.get("note") or "").strip()

    employee, employee_error = _resolve_form_employee(db, request.form.get("employee_id"), "biometric")
    if employee is None:
        flash(employee_error or "Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/biometric")
    employee_id = employee["id"]

    if not location_label or not punch_time:
        flash("Alamat atau tempat absen dan waktu wajib diisi", "error")
        return redirect("/hris/biometric")

    if latitude is None or longitude is None:
        flash("Latitude dan longitude geotag wajib valid", "error")
        return redirect("/hris/biometric")

    duplicate = db.execute(
        "SELECT id FROM biometric_logs WHERE employee_id=? AND punch_time=? AND punch_type=?",
        (employee_id, punch_time, punch_type),
    ).fetchone()
    if duplicate:
        flash("Log geotag dengan waktu dan tipe yang sama sudah ada", "error")
        return redirect("/hris/biometric")

    photo_path = None
    if (photo_data_url or "").strip():
        photo_path = _save_biometric_photo_data(photo_data_url)
        if not photo_path:
            flash("Foto absen tidak valid. Ambil ulang foto sebelum menyimpan.", "error")
            return redirect("/hris/biometric")

    _insert_biometric_log_record(
        db,
        employee_id=employee_id,
        warehouse_id=employee["warehouse_id"],
        device_name="Mobile Geotag",
        device_user_id=None,
        punch_time=punch_time,
        punch_type=punch_type,
        sync_status=sync_status,
        location_label=location_label,
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy_m,
        note=note or None,
        photo_path=photo_path,
    )
    db.commit()

    flash("Log geotag berhasil ditambahkan", "success")
    return redirect("/hris/biometric")


@hris_bp.route("/biometric/attendance-status", methods=["POST"])
def update_biometric_attendance_status():
    return_to = _safe_hris_return_to("/hris/biometric")
    if not can_adjust_biometric_attendance_status():
        flash("Hanya HR dan Super Admin yang bisa mengubah status absen geotag.", "error")
        return redirect(return_to)

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    attendance_date = (request.form.get("attendance_date") or "").strip()
    requested_status = _normalize_attendance_status(request.form.get("status"))

    if requested_status not in BIOMETRIC_ADJUSTABLE_ATTENDANCE_STATUSES:
        flash("Status geotag hanya bisa diubah ke Present atau Late.", "error")
        return redirect(return_to)

    employee = _get_accessible_employee(db, employee_id)
    if employee is None or not attendance_date:
        flash("Data attendance geotag tidak valid.", "error")
        return redirect(return_to)

    attendance = _get_attendance_by_employee_date(db, employee_id, attendance_date)
    attendance = dict(attendance) if attendance is not None else None
    if attendance is None:
        flash("Data attendance geotag tidak ditemukan.", "error")
        return redirect(return_to)

    derived_status = _derive_biometric_attendance_status_with_shift(
        attendance["check_in"],
        attendance["shift_label"],
    )
    status_override = requested_status if requested_status != derived_status else None
    override_timestamp = _current_timestamp()

    db.execute(
        """
        UPDATE attendance_records
        SET status=?,
            status_override=?,
            status_override_by=?,
            status_override_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            requested_status,
            status_override,
            session.get("user_id") if status_override else None,
            override_timestamp if status_override else None,
            override_timestamp,
            attendance["id"],
        ),
    )
    db.commit()

    if status_override:
        flash("Status absen geotag berhasil diubah manual.", "success")
    else:
        flash("Status absen geotag dikembalikan ke hitungan otomatis.", "success")
    return redirect(return_to)


@hris_bp.route("/biometric/attendance-time", methods=["POST"])
def update_biometric_attendance_time():
    return_to = _safe_hris_return_to("/hris/biometric")
    if not can_adjust_biometric_attendance_status():
        flash("Hanya HR dan Super Admin yang bisa mengubah waktu absen geotag.", "error")
        return redirect(return_to)

    db = get_db()
    employee_id = _to_int(request.form.get("employee_id"))
    attendance_date = (request.form.get("attendance_date") or "").strip()
    requested_check_in = (request.form.get("check_in_time") or "").strip()
    requested_check_out = (request.form.get("check_out_time") or "").strip()

    if not employee_id or not attendance_date:
        flash("Data karyawan atau tanggal absensi tidak valid.", "error")
        return redirect(return_to)

    try:
        date_cls.fromisoformat(attendance_date)
    except ValueError:
        flash("Format tanggal absensi tidak valid.", "error")
        return redirect(return_to)

    normalized_check_in = _normalize_time_of_day_input(requested_check_in)
    normalized_check_out = _normalize_time_of_day_input(requested_check_out)
    if requested_check_in and not normalized_check_in:
        flash("Format jam masuk tidak valid.", "error")
        return redirect(return_to)
    if requested_check_out and not normalized_check_out:
        flash("Format jam pulang tidak valid.", "error")
        return redirect(return_to)
    if not normalized_check_in and not normalized_check_out:
        flash("Isi minimal salah satu jam (masuk/pulang) untuk diperbarui.", "error")
        return redirect(return_to)

    employee = _get_accessible_employee(db, employee_id)
    if employee is None:
        flash("Karyawan tidak valid untuk scope akun ini.", "error")
        return redirect(return_to)
    employee = dict(employee)

    day_logs = [
        dict(row)
        for row in db.execute(
            """
            SELECT id, warehouse_id, punch_time, punch_type
            FROM biometric_logs
            WHERE employee_id=?
              AND substr(punch_time, 1, 10)=?
              AND sync_status IN (?,?)
            ORDER BY punch_time ASC, id ASC
            """,
            (employee_id, attendance_date, "synced", "manual"),
        ).fetchall()
    ]
    check_in_log = next((log for log in day_logs if log["punch_type"] == "check_in"), None)
    check_out_log = next((log for log in reversed(day_logs) if log["punch_type"] == "check_out"), None)

    if normalized_check_in and check_in_log is None:
        flash("Belum ada log check in pada tanggal ini untuk dikoreksi.", "error")
        return redirect(return_to)
    if normalized_check_out and check_out_log is None:
        flash("Belum ada log check out pada tanggal ini untuk dikoreksi.", "error")
        return redirect(return_to)

    target_check_in = (
        f"{attendance_date} {normalized_check_in}:00"
        if normalized_check_in
        else (check_in_log["punch_time"] if check_in_log else None)
    )
    target_check_out = (
        f"{attendance_date} {normalized_check_out}:00"
        if normalized_check_out
        else (check_out_log["punch_time"] if check_out_log else None)
    )

    if target_check_in and target_check_out and target_check_out <= target_check_in:
        flash("Jam pulang harus lebih akhir dari jam masuk.", "error")
        return redirect(return_to)

    if normalized_check_in and check_in_log and target_check_in != check_in_log["punch_time"]:
        duplicate_check_in = db.execute(
            """
            SELECT id
            FROM biometric_logs
            WHERE employee_id=? AND punch_time=? AND punch_type='check_in' AND id<>?
            """,
            (employee_id, target_check_in, check_in_log["id"]),
        ).fetchone()
        if duplicate_check_in:
            flash("Jam masuk itu sudah dipakai log check in lain.", "error")
            return redirect(return_to)

    if normalized_check_out and check_out_log and target_check_out != check_out_log["punch_time"]:
        duplicate_check_out = db.execute(
            """
            SELECT id
            FROM biometric_logs
            WHERE employee_id=? AND punch_time=? AND punch_type='check_out' AND id<>?
            """,
            (employee_id, target_check_out, check_out_log["id"]),
        ).fetchone()
        if duplicate_check_out:
            flash("Jam pulang itu sudah dipakai log check out lain.", "error")
            return redirect(return_to)

    updates = []
    handled_by, handled_at = _build_biometric_handling("manual")
    update_timestamp = _current_timestamp()

    if normalized_check_in and check_in_log and target_check_in != check_in_log["punch_time"]:
        db.execute(
            """
            UPDATE biometric_logs
            SET punch_time=?,
                sync_status=?,
                handled_by=?,
                handled_at=?,
                updated_at=?
            WHERE id=?
            """,
            (target_check_in, "manual", handled_by, handled_at, update_timestamp, check_in_log["id"]),
        )
        updates.append("jam masuk")

    if normalized_check_out and check_out_log and target_check_out != check_out_log["punch_time"]:
        db.execute(
            """
            UPDATE biometric_logs
            SET punch_time=?,
                sync_status=?,
                handled_by=?,
                handled_at=?,
                updated_at=?
            WHERE id=?
            """,
            (target_check_out, "manual", handled_by, handled_at, update_timestamp, check_out_log["id"]),
        )
        updates.append("jam pulang")

    if not updates:
        flash("Tidak ada perubahan waktu absen yang disimpan.", "info")
        return redirect(return_to)

    warehouse_id = (
        (check_in_log.get("warehouse_id") if check_in_log else None)
        or (check_out_log.get("warehouse_id") if check_out_log else None)
        or employee.get("warehouse_id")
    )
    _resync_attendance_from_biometrics(db, employee_id, warehouse_id, attendance_date)
    db.commit()

    flash(f"Perubahan {' dan '.join(updates)} berhasil disimpan.", "success")
    return redirect(return_to)


@hris_bp.route("/biometric/attendance-shift", methods=["POST"])
def update_biometric_attendance_shift():
    return_to = _safe_hris_return_to("/hris/biometric")
    if not can_adjust_biometric_attendance_status():
        flash("Hanya HR dan Super Admin yang bisa memperbaiki shift geotag.", "error")
        return redirect(return_to)

    db = get_db()
    attendance_columns = _get_table_columns(db, "attendance_records")
    biometric_columns = _get_table_columns(db, "biometric_logs")
    if not {"shift_code", "shift_label"}.issubset(attendance_columns) or not {
        "shift_code",
        "shift_label",
    }.issubset(biometric_columns):
        flash("Penyimpanan shift geotag belum tersedia pada database ini.", "error")
        return redirect(return_to)

    employee_id = _to_int(request.form.get("employee_id"))
    attendance_date = (request.form.get("attendance_date") or "").strip()
    requested_shift_code = _normalize_biometric_shift_code(request.form.get("shift_code"))

    if not employee_id or not attendance_date:
        flash("Data karyawan atau tanggal absensi tidak valid.", "error")
        return redirect(return_to)

    try:
        date_cls.fromisoformat(attendance_date)
    except ValueError:
        flash("Format tanggal absensi tidak valid.", "error")
        return redirect(return_to)

    if not requested_shift_code:
        flash("Pilih shift yang valid untuk disimpan.", "error")
        return redirect(return_to)

    employee = _get_accessible_employee(db, employee_id)
    if employee is None:
        flash("Karyawan tidak valid untuk scope akun ini.", "error")
        return redirect(return_to)
    employee = dict(employee)

    warehouse = db.execute(
        "SELECT name FROM warehouses WHERE id=?",
        (employee.get("warehouse_id"),),
    ).fetchone()
    if warehouse:
        employee["warehouse_name"] = warehouse["name"]

    day_logs = [
        dict(row)
        for row in db.execute(
            """
            SELECT id, warehouse_id, punch_time, punch_type, sync_status, shift_code, shift_label
            FROM biometric_logs
            WHERE employee_id=?
              AND substr(punch_time, 1, 10)=?
              AND sync_status IN (?,?)
            ORDER BY punch_time ASC, id ASC
            """,
            (employee_id, attendance_date, "synced", "manual"),
        ).fetchall()
    ]
    if not day_logs:
        flash("Belum ada log geotag tersinkron pada tanggal ini untuk dikoreksi shift-nya.", "error")
        return redirect(return_to)

    attendance = _get_attendance_by_employee_date(db, employee_id, attendance_date)
    attendance = dict(attendance) if attendance is not None else None
    current_shift_label = (
        (attendance["shift_label"] if attendance and attendance.get("shift_label") else None)
        or next(
            (
                (log.get("shift_label") or "").strip()
                for log in day_logs
                if (log.get("shift_label") or "").strip()
            ),
            None,
        )
    )
    shift_options = _build_biometric_shift_options(employee, current_shift_label)
    selected_shift = next(
        (option for option in shift_options if option["value"] == requested_shift_code),
        None,
    )
    if selected_shift is None:
        flash("Shift yang dipilih tidak tersedia untuk staff ini.", "error")
        return redirect(return_to)

    requested_shift_label = selected_shift["label"]
    current_shift_code = _normalize_biometric_shift_code(
        (attendance["shift_code"] if attendance and attendance.get("shift_code") else None)
        or next(
            (
                (log.get("shift_code") or "").strip()
                for log in day_logs
                if (log.get("shift_code") or "").strip()
            ),
            None,
        )
    ) or _resolve_biometric_shift_code_from_label(current_shift_label, employee)

    shift_changed = bool(
        requested_shift_code != current_shift_code
        or requested_shift_label != current_shift_label
        or any(
            (
                _normalize_biometric_shift_code(log.get("shift_code")) != requested_shift_code
                or (log.get("shift_label") or "").strip() != requested_shift_label
            )
            for log in day_logs
        )
    )
    if not shift_changed:
        flash("Shift geotag sudah sesuai, tidak ada perubahan yang disimpan.", "info")
        return redirect(return_to)

    handled_by, handled_at = _build_biometric_handling("manual")
    update_timestamp = _current_timestamp()
    for log in day_logs:
        db.execute(
            """
            UPDATE biometric_logs
            SET shift_code=?,
                shift_label=?,
                sync_status=?,
                handled_by=?,
                handled_at=?,
                updated_at=?
            WHERE id=?
            """,
            (
                requested_shift_code,
                requested_shift_label,
                "manual",
                handled_by,
                handled_at,
                update_timestamp,
                log["id"],
            ),
        )

    warehouse_id = next(
        (
            log.get("warehouse_id")
            for log in day_logs
            if log.get("warehouse_id")
        ),
        employee.get("warehouse_id"),
    )
    _resync_attendance_from_biometrics(db, employee_id, warehouse_id, attendance_date)
    db.commit()

    flash(f"Shift geotag {employee['full_name']} berhasil diperbarui ke {requested_shift_label}.", "success")
    return redirect(return_to)


@hris_bp.route("/biometric/overtime/use", methods=["POST"])
def use_biometric_overtime():
    return_to = _safe_hris_return_to("/hris/biometric")
    if not can_manage_biometric_records():
        flash("Tidak punya akses untuk mengurangi saldo lembur staff.", "error")
        return redirect(return_to)

    db = get_db()
    try:
        _ensure_overtime_feature_schema(db)
    except Exception as exc:
        current_app.logger.exception("HRIS BIOMETRIC OVERTIME USE SCHEMA ERROR: %s", exc)
        flash(
            "Fitur pemakaian lembur belum siap di server. Schema overtime di database VPS perlu disinkronkan dulu.",
            "error",
        )
        return redirect(return_to)
    employee_id = _to_int(request.form.get("employee_id"))
    usage_date = _parse_iso_date((request.form.get("usage_date") or "").strip())
    minutes_used = _to_int(request.form.get("minutes_used"), default=None)
    usage_mode = _normalize_overtime_usage_mode(request.form.get("usage_mode"))
    note = (request.form.get("note") or "").strip()

    employee = _get_accessible_employee(db, employee_id)
    if employee is None:
        flash("Data staff untuk pemakaian lembur tidak ditemukan.", "error")
        return redirect(return_to)
    employee = dict(employee)

    if usage_date is None:
        flash("Tanggal pemakaian lembur tidak valid.", "error")
        return redirect(return_to)

    if not note:
        flash("Catatan pemakaian lembur wajib diisi agar histori tetap jelas.", "error")
        return redirect(return_to)

    overtime_balance = _build_employee_overtime_balance(
        db,
        employee["id"],
        reference_date=usage_date,
        include_pending_weekly_usage=True,
    )
    if usage_mode == "cashout_all":
        minutes_used = int(overtime_balance["available_minutes"] or 0)
        if minutes_used <= 0:
            flash("Saldo lembur staff ini sedang kosong, jadi belum ada yang bisa diuangkan.", "error")
            return redirect(return_to)
    elif minutes_used is None or minutes_used <= 0:
        flash("Durasi pemakaian lembur wajib diisi dalam menit dan lebih dari 0.", "error")
        return redirect(return_to)
    if minutes_used > overtime_balance["available_minutes"]:
        flash(
            f"Saldo lembur staff ini tidak cukup. Sisa yang tersedia hanya { _format_duration_minutes_label(overtime_balance['available_minutes'], zero_label='0 mnt') }.",
            "error",
        )
        return redirect(return_to)
    if usage_mode != "cashout_all" and minutes_used > overtime_balance["weekly_remaining_minutes"]:
        flash(
            f"Pemakaian lembur reguler maksimal {overtime_balance['weekly_limit_label']} per minggu. "
            f"Sisa minggu ini hanya {overtime_balance['weekly_remaining_label']} untuk periode {overtime_balance['weekly_period_label']}.",
            "error",
        )
        return redirect(return_to)

    payload = {
        "employee_id": employee["id"],
        "employee_name": employee["full_name"],
        "warehouse_id": employee["warehouse_id"],
        "usage_date": usage_date.isoformat(),
        "usage_mode": usage_mode,
        "usage_mode_label": _get_overtime_usage_mode_label(usage_mode),
        "minutes_used": minutes_used,
        "duration_label": _format_duration_minutes_label(minutes_used),
        "note": note,
    }

    try:
        queue_result = queue_attendance_request(
            db,
            request_type="overtime_use",
            warehouse_id=employee["warehouse_id"],
            employee_id=employee["id"],
            requested_by=session.get("user_id"),
            summary_title=(
                f"{employee['full_name']} - Uangkan Lembur"
                if usage_mode == "cashout_all"
                else f"{employee['full_name']} - Pengurangan Lembur"
            ),
            summary_note=(
                f"{_format_duration_minutes_label(minutes_used)} pada {usage_date.isoformat()}"
                f"{' | Uangkan semua saldo' if usage_mode == 'cashout_all' else ''}"
                f"{f' | {note}' if note else ''}"
            ),
            payload=payload,
        )
        db.commit()
    except Exception:
        db.rollback()
        flash("Permintaan pengurangan saldo lembur gagal dikirim ke approval.", "error")
        return redirect(return_to)

    if queue_result.get("existing"):
        flash(
            "Permintaan uangkan lembur yang sama masih menunggu approval. Saldo belum berubah sebelum disetujui."
            if usage_mode == "cashout_all"
            else "Permintaan pengurangan saldo lembur yang sama masih menunggu approval. Saldo belum berubah sebelum disetujui.",
            "info",
        )
    else:
        flash(
            (
                f"Permintaan uangkan lembur {employee['full_name']} sebesar { _format_duration_minutes_label(minutes_used) } berhasil dikirim ke approval."
                if usage_mode == "cashout_all"
                else f"Permintaan pengurangan lembur {employee['full_name']} sebesar { _format_duration_minutes_label(minutes_used) } berhasil dikirim ke approval."
            ),
            "success",
        )
    return redirect(return_to)


@hris_bp.route("/biometric/overtime/decision", methods=["POST"])
def decide_biometric_overtime():
    return_to = _safe_hris_return_to("/hris/biometric")
    if not can_manage_attendance_request_approvals(session.get("role")):
        flash("Hanya HR dan Super Admin yang bisa memutuskan lembur otomatis.", "error")
        return redirect(return_to)

    decision = (request.form.get("decision") or "").strip().lower()
    employee_id = _to_int(request.form.get("employee_id"))
    attendance_date = (request.form.get("attendance_date") or "").strip()

    if decision not in {"approved", "rejected"}:
        flash("Keputusan lembur otomatis tidak valid.", "error")
        return redirect(return_to)
    if not employee_id or not attendance_date:
        flash("Data staff atau tanggal lembur tidak valid.", "error")
        return redirect(return_to)

    try:
        date_cls.fromisoformat(attendance_date)
    except ValueError:
        flash("Format tanggal lembur tidak valid.", "error")
        return redirect(return_to)

    db = get_db()
    try:
        _ensure_overtime_feature_schema(db)
    except Exception as exc:
        current_app.logger.exception("HRIS BIOMETRIC OVERTIME DECISION SCHEMA ERROR: %s", exc)
        flash(
            "Fitur approval lembur belum siap di server. Schema overtime di database VPS perlu disinkronkan dulu.",
            "error",
        )
        return redirect(return_to)
    employee = _get_accessible_employee(db, employee_id)
    if employee is None:
        flash("Staff lembur tidak ditemukan untuk scope akun ini.", "error")
        return redirect(return_to)
    employee = dict(employee)

    attendance = _get_biometric_attendance_record(db, employee_id, attendance_date)
    if attendance is None:
        flash("Data attendance untuk lembur otomatis tidak ditemukan.", "error")
        return redirect(return_to)
    attendance = dict(attendance)

    overtime_summary = _summarize_overtime_activity(
        attendance.get("check_in"),
        attendance.get("check_out"),
        attendance.get("shift_label"),
    )
    if not overtime_summary["qualifies"]:
        flash("Attendance ini belum memenuhi syarat lembur untuk diputuskan.", "error")
        return redirect(return_to)

    latest_request = _build_biometric_overtime_request_index(
        db,
        employee_ids=[employee_id],
        attendance_dates=[attendance_date],
    ).get((employee_id, attendance_date))
    latest_status = str((latest_request or {}).get("status") or "").strip().lower()
    if latest_status == "approved":
        flash("Lembur otomatis ini sudah pernah disetujui.", "info")
        return redirect(return_to)
    if latest_status == "rejected":
        flash("Lembur otomatis ini sudah pernah ditolak.", "info")
        return redirect(return_to)

    payload = _build_biometric_auto_overtime_payload(
        employee,
        attendance_date,
        attendance.get("check_in"),
        attendance.get("check_out"),
        attendance.get("shift_label"),
        overtime_summary,
    )
    summary_title = f"{employee['full_name']} - Lembur Otomatis"
    breakdown_label = str(payload.get("breakdown_label") or "").strip()
    summary_note = (
        f"{payload['duration_label']} pada {attendance_date}"
        f"{' | ' + breakdown_label if breakdown_label else ''}"
    )
    decision_note = (
        "Lembur otomatis disetujui dari rekap biometric."
        if decision == "approved"
        else "Lembur otomatis ditolak dari rekap biometric."
    )
    requested_by_user = db.execute(
        "SELECT id FROM users WHERE employee_id=? ORDER BY id ASC LIMIT 1",
        (employee_id,),
    ).fetchone()
    requested_by = requested_by_user["id"] if requested_by_user else None
    request_id = 0

    try:
        cursor = db.execute(
            """
            INSERT INTO attendance_action_requests(
                request_type,
                warehouse_id,
                employee_id,
                summary_title,
                summary_note,
                payload,
                status,
                requested_by,
                handled_by,
                handled_at,
                decision_note,
                updated_at
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "overtime_add",
                employee.get("warehouse_id"),
                employee_id,
                summary_title,
                summary_note,
                json.dumps(payload, sort_keys=True, ensure_ascii=True),
                "pending",
                requested_by,
                None,
                None,
                None,
                _current_timestamp(),
            ),
        )
        request_id = int(cursor.lastrowid)
        request_row = _get_attendance_request_by_id(db, request_id)
        if decision == "approved":
            success_message = _apply_attendance_request(db, request_row)
        else:
            success_message = f"Lembur otomatis {employee['full_name']} tidak ditambahkan ke saldo."
        db.execute(
            """
            UPDATE attendance_action_requests
            SET status=?,
                handled_by=?,
                handled_at=?,
                decision_note=?,
                updated_at=?
            WHERE id=?
            """,
            (
                decision,
                session.get("user_id"),
                _current_timestamp(),
                decision_note,
                _current_timestamp(),
                request_id,
            ),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        flash(str(exc), "error")
        return redirect(return_to)

    try:
        updated_request = _get_attendance_request_by_id(db, request_id)
        if updated_request is not None:
            _notify_attendance_request_decision(
                db,
                updated_request,
                approved=decision == "approved",
            )
    except Exception as exc:
        print("BIOMETRIC OVERTIME DECISION NOTIFICATION ERROR:", exc)

    flash(success_message, "success" if decision == "approved" else "info")
    return redirect(return_to)


@hris_bp.route("/biometric/overtime/usage/delete/<int:usage_id>", methods=["POST"])
def delete_biometric_overtime_usage(usage_id):
    return_to = _safe_hris_return_to("/hris/biometric")
    if not can_manage_biometric_records():
        flash("Tidak punya akses untuk membatalkan pemakaian lembur.", "error")
        return redirect(return_to)

    db = get_db()
    usage = _get_overtime_usage_by_id(db, usage_id)
    if usage is None:
        flash("Riwayat pemakaian lembur tidak ditemukan.", "error")
        return redirect(return_to)

    payload = {
        "usage_id": usage_id,
        "employee_id": usage["employee_id"],
        "employee_name": usage["full_name"],
        "warehouse_id": usage["warehouse_id"],
        "usage_date": usage["usage_date"],
        "minutes_used": usage["minutes_used"],
        "duration_label": usage["duration_label"],
        "note": usage["note"] or "",
    }

    summary_note = (
        f"Batalkan {_format_duration_minutes_label(usage['minutes_used'])} pada {usage['usage_date']}"
    )
    if usage["note"]:
        summary_note += f" | {usage['note']}"

    try:
        queue_result = queue_attendance_request(
            db,
            request_type="overtime_usage_delete",
            warehouse_id=usage["warehouse_id"],
            employee_id=usage["employee_id"],
            requested_by=session.get("user_id"),
            summary_title=f"{usage['full_name']} - Pembatalan Lembur",
            summary_note=summary_note,
            payload=payload,
        )
        db.commit()
    except Exception:
        db.rollback()
        flash("Permintaan pembatalan pemakaian lembur gagal dikirim ke approval.", "error")
        return redirect(return_to)

    if queue_result.get("existing"):
        flash("Permintaan pembatalan pemakaian lembur yang sama masih menunggu approval.", "info")
    else:
        flash(
            f"Permintaan pembatalan pemakaian lembur {usage['full_name']} berhasil dikirim ke approval.",
            "success",
        )
    return redirect(return_to)


@hris_bp.route("/biometric/update/<int:biometric_id>", methods=["POST"])
def update_biometric(biometric_id):
    if not can_manage_biometric_records():
        flash("Tidak punya akses untuk mengelola geotag absensi", "error")
        return _portal_redirect_for_module("biometric") or redirect("/hris/biometric")

    db = get_db()
    biometric = _get_biometric_log_by_id(db, biometric_id)
    if not biometric:
        flash("Log geotag tidak ditemukan", "error")
        return redirect("/hris/biometric")

    old_employee_id = biometric["employee_id"]
    old_warehouse_id = biometric["warehouse_id"]
    old_punch_date = (biometric["punch_time"] or "")[:10]

    location_label = _normalize_biometric_location_label(request.form.get("location_label"))
    latitude = _normalize_latitude(request.form.get("latitude"))
    longitude = _normalize_longitude(request.form.get("longitude"))
    accuracy_m = _normalize_accuracy(request.form.get("accuracy_m"))
    punch_time = _normalize_datetime_input(request.form.get("punch_time"))
    punch_type = _normalize_biometric_punch_type(request.form.get("punch_type"))
    sync_status = _normalize_biometric_sync_status(request.form.get("sync_status"))
    photo_data_url = request.form.get("photo_data_url")
    note = (request.form.get("note") or "").strip()

    employee, employee_error = _resolve_form_employee(db, request.form.get("employee_id"), "biometric")
    if employee is None:
        flash(employee_error or "Karyawan tidak valid untuk scope akun ini", "error")
        return redirect("/hris/biometric")
    employee_id = employee["id"]

    if not location_label or not punch_time:
        flash("Alamat atau tempat absen dan waktu wajib diisi", "error")
        return redirect("/hris/biometric")

    if latitude is None or longitude is None:
        flash("Latitude dan longitude geotag wajib valid", "error")
        return redirect("/hris/biometric")

    duplicate = db.execute(
        "SELECT id FROM biometric_logs WHERE employee_id=? AND punch_time=? AND punch_type=? AND id<>?",
        (employee_id, punch_time, punch_type, biometric_id),
    ).fetchone()
    if duplicate:
        flash("Log geotag dengan waktu dan tipe yang sama sudah digunakan record lain", "error")
        return redirect("/hris/biometric")

    photo_path = biometric["photo_path"]
    photo_captured_at = biometric["photo_captured_at"]
    if (photo_data_url or "").strip():
        photo_path = _save_biometric_photo_data(photo_data_url, existing_photo_path=biometric["photo_path"])
        if not photo_path:
            flash("Foto absen tidak valid. Ambil ulang foto sebelum menyimpan.", "error")
            return redirect("/hris/biometric")
        photo_captured_at = _current_timestamp()

    handled_by, handled_at = _build_biometric_handling(sync_status)
    db.execute(
        """
        UPDATE biometric_logs
        SET employee_id=?,
            warehouse_id=?,
            device_name=?,
            device_user_id=?,
            punch_time=?,
            punch_type=?,
            sync_status=?,
            location_label=?,
            latitude=?,
            longitude=?,
            accuracy_m=?,
            photo_path=?,
            photo_captured_at=?,
            note=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            employee_id,
            employee["warehouse_id"],
            "Mobile Geotag",
            None,
            punch_time,
            punch_type,
            sync_status,
            location_label,
            latitude,
            longitude,
            accuracy_m,
            photo_path,
            photo_captured_at if photo_path else None,
            note or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            biometric_id,
        ),
    )

    _resync_attendance_from_biometrics(db, old_employee_id, old_warehouse_id, old_punch_date)
    _resync_attendance_from_biometrics(db, employee_id, employee["warehouse_id"], punch_time[:10])
    db.commit()

    flash("Log geotag berhasil diupdate", "success")
    return redirect("/hris/biometric")


@hris_bp.route("/biometric/delete/<int:biometric_id>", methods=["POST"])
def delete_biometric(biometric_id):
    if not can_manage_biometric_records():
        flash("Tidak punya akses untuk mengelola geotag absensi", "error")
        return _portal_redirect_for_module("biometric") or redirect("/hris/biometric")

    db = get_db()
    biometric = _get_biometric_log_by_id(db, biometric_id)
    if not biometric:
        flash("Log geotag tidak ditemukan", "error")
        return redirect("/hris/biometric")

    employee_id = biometric["employee_id"]
    warehouse_id = biometric["warehouse_id"]
    punch_date = (biometric["punch_time"] or "")[:10]

    db.execute("DELETE FROM biometric_logs WHERE id=?", (biometric_id,))
    _delete_biometric_photo(biometric["photo_path"])
    _resync_attendance_from_biometrics(db, employee_id, warehouse_id, punch_date)
    db.commit()

    flash("Log geotag berhasil dihapus", "success")
    return redirect("/hris/biometric")


@hris_bp.route("/announcement/add", methods=["POST"])
def add_announcement():
    if not can_manage_announcement_records():
        flash("Tidak punya akses untuk mengelola announcement", "error")
        return redirect("/hris/announcement")

    db = get_db()
    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))
    title = (request.form.get("title") or "").strip()
    audience = _normalize_announcement_audience(request.form.get("audience"))
    publish_date = (request.form.get("publish_date") or "").strip()
    expires_at = (request.form.get("expires_at") or "").strip()
    status = _normalize_announcement_status(request.form.get("status"))
    channel = (request.form.get("channel") or "").strip()
    message = (request.form.get("message") or "").strip()

    if warehouse_id is None:
        flash("Gudang announcement wajib diisi", "error")
        return redirect("/hris/announcement")

    if not title or not publish_date:
        flash("Judul announcement dan publish date wajib diisi", "error")
        return redirect("/hris/announcement")

    if _calculate_leave_days(publish_date, publish_date) is None:
        flash("Tanggal publish announcement tidak valid", "error")
        return redirect("/hris/announcement")

    if expires_at and _calculate_leave_days(publish_date, expires_at) is None:
        flash("Rentang tanggal announcement tidak valid", "error")
        return redirect("/hris/announcement")

    handled_by, handled_at = _build_announcement_handling(status)
    db.execute(
        """
        INSERT INTO announcement_posts(
            warehouse_id,
            title,
            audience,
            publish_date,
            expires_at,
            status,
            channel,
            message,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            warehouse_id,
            title,
            audience,
            publish_date,
            expires_at or None,
            status,
            channel or None,
            message or None,
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    if status == "published":
        created_announcement = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        announcement = _get_announcement_by_id(db, created_announcement)
        if announcement:
            payload = build_announcement_notification_payload(dict(announcement))
            notify_broadcast(
                payload["subject"],
                payload["message"],
                audience=announcement["audience"],
                warehouse_id=announcement["warehouse_id"],
                push_title=payload["push_title"],
                push_body=payload["push_body"],
                push_url="/announcements/",
                push_tag=payload["push_tag"],
                category="announcement",
                link_url="/announcements/",
                source_type="announcement",
                source_id=str(created_announcement),
            )

    flash("Announcement berhasil ditambahkan", "success")
    return redirect("/hris/announcement")


@hris_bp.route("/announcement/update/<int:announcement_id>", methods=["POST"])
def update_announcement(announcement_id):
    if not can_manage_announcement_records():
        flash("Tidak punya akses untuk mengelola announcement", "error")
        return redirect("/hris/announcement")

    db = get_db()
    announcement = _get_announcement_by_id(db, announcement_id)
    if not announcement:
        flash("Announcement tidak ditemukan", "error")
        return redirect("/hris/announcement")

    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))
    title = (request.form.get("title") or "").strip()
    audience = _normalize_announcement_audience(request.form.get("audience"))
    publish_date = (request.form.get("publish_date") or "").strip()
    expires_at = (request.form.get("expires_at") or "").strip()
    status = _normalize_announcement_status(request.form.get("status"))
    channel = (request.form.get("channel") or "").strip()
    message = (request.form.get("message") or "").strip()

    if warehouse_id is None:
        flash("Gudang announcement wajib diisi", "error")
        return redirect("/hris/announcement")

    if not title or not publish_date:
        flash("Judul announcement dan publish date wajib diisi", "error")
        return redirect("/hris/announcement")

    if _calculate_leave_days(publish_date, publish_date) is None:
        flash("Tanggal publish announcement tidak valid", "error")
        return redirect("/hris/announcement")

    if expires_at and _calculate_leave_days(publish_date, expires_at) is None:
        flash("Rentang tanggal announcement tidak valid", "error")
        return redirect("/hris/announcement")

    handled_by, handled_at = _build_announcement_handling(status)
    db.execute(
        """
        UPDATE announcement_posts
        SET warehouse_id=?,
            title=?,
            audience=?,
            publish_date=?,
            expires_at=?,
            status=?,
            channel=?,
            message=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            warehouse_id,
            title,
            audience,
            publish_date,
            expires_at or None,
            status,
            channel or None,
            message or None,
            handled_by,
            handled_at,
            _current_timestamp(),
            announcement_id,
        ),
    )
    db.commit()

    if status == "published":
        refreshed_announcement = _get_announcement_by_id(db, announcement_id)
        if refreshed_announcement:
            payload = build_announcement_notification_payload(dict(refreshed_announcement))
            notify_broadcast(
                payload["subject"],
                payload["message"],
                audience=refreshed_announcement["audience"],
                warehouse_id=refreshed_announcement["warehouse_id"],
                push_title=payload["push_title"],
                push_body=payload["push_body"],
                push_url="/announcements/",
                push_tag=payload["push_tag"],
                category="announcement",
                link_url="/announcements/",
                source_type="announcement",
                source_id=str(announcement_id),
            )

    flash("Announcement berhasil diupdate", "success")
    return redirect("/hris/announcement")


@hris_bp.route("/announcement/delete/<int:announcement_id>", methods=["POST"])
def delete_announcement(announcement_id):
    if not can_manage_announcement_records():
        flash("Tidak punya akses untuk mengelola announcement", "error")
        return redirect("/hris/announcement")

    db = get_db()
    announcement = _get_announcement_by_id(db, announcement_id)
    if not announcement:
        flash("Announcement tidak ditemukan", "error")
        return redirect("/hris/announcement")

    db.execute("DELETE FROM announcement_posts WHERE id=?", (announcement_id,))
    db.commit()

    flash("Announcement berhasil dihapus", "success")
    return redirect("/hris/announcement")


@hris_bp.route("/documents/add", methods=["POST"])
def add_document():
    if not can_manage_document_records():
        flash("Tidak punya akses untuk mengelola documents", "error")
        return redirect("/hris/documents")

    db = get_db()
    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))
    document_title = (request.form.get("document_title") or "").strip()
    document_code = (request.form.get("document_code") or "").strip().upper()
    document_type = _normalize_document_type(request.form.get("document_type"))
    status = _normalize_document_status(request.form.get("status"))
    effective_date = (request.form.get("effective_date") or "").strip()
    review_date = (request.form.get("review_date") or "").strip()
    owner_name = (request.form.get("owner_name") or "").strip()
    note = (request.form.get("note") or "").strip()
    attachment = request.files.get("attachment")

    if warehouse_id is None:
        flash("Gudang dokumen wajib diisi", "error")
        return redirect("/hris/documents")

    if not document_title or not document_code or not effective_date:
        flash("Judul, kode, dan effective date dokumen wajib diisi", "error")
        return redirect("/hris/documents")

    if _calculate_leave_days(effective_date, effective_date) is None:
        flash("Tanggal efektif dokumen tidak valid", "error")
        return redirect("/hris/documents")

    if review_date and _calculate_leave_days(effective_date, review_date) is None:
        flash("Rentang tanggal dokumen tidak valid", "error")
        return redirect("/hris/documents")

    duplicate = db.execute(
        "SELECT id FROM document_records WHERE document_code=?",
        (document_code,),
    ).fetchone()
    if duplicate:
        flash("Kode dokumen sudah digunakan", "error")
        return redirect("/hris/documents")

    attachment_meta = {
        "attachment_name": None,
        "attachment_path": None,
        "attachment_mime": None,
        "attachment_size": 0,
    }
    if attachment and (attachment.filename or "").strip():
        try:
            attachment_meta = _store_document_attachment(attachment)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect("/hris/documents")

    handled_by, handled_at = _build_document_handling(status)
    db.execute(
        """
        INSERT INTO document_records(
            warehouse_id,
            document_title,
            document_code,
            document_type,
            status,
            effective_date,
            review_date,
            owner_name,
            note,
            attachment_name,
            attachment_path,
            attachment_mime,
            attachment_size,
            handled_by,
            handled_at,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            warehouse_id,
            document_title,
            document_code,
            document_type,
            status,
            effective_date,
            review_date or None,
            owner_name or None,
            note or None,
            attachment_meta["attachment_name"],
            attachment_meta["attachment_path"],
            attachment_meta["attachment_mime"],
            int(attachment_meta["attachment_size"] or 0),
            handled_by,
            handled_at,
            _current_timestamp(),
        ),
    )
    db.commit()

    flash("Document berhasil ditambahkan", "success")
    return redirect("/hris/documents")


@hris_bp.route("/documents/update/<int:document_id>", methods=["POST"])
def update_document(document_id):
    if not can_manage_document_records():
        flash("Tidak punya akses untuk mengelola documents", "error")
        return redirect("/hris/documents")

    db = get_db()
    document = _get_document_by_id(db, document_id)
    if not document:
        flash("Document tidak ditemukan", "error")
        return redirect("/hris/documents")

    warehouse_id = _resolve_employee_warehouse(db, request.form.get("warehouse_id"))
    document_title = (request.form.get("document_title") or "").strip()
    document_code = (request.form.get("document_code") or "").strip().upper()
    document_type = _normalize_document_type(request.form.get("document_type"))
    status = _normalize_document_status(request.form.get("status"))
    effective_date = (request.form.get("effective_date") or "").strip()
    review_date = (request.form.get("review_date") or "").strip()
    owner_name = (request.form.get("owner_name") or "").strip()
    note = (request.form.get("note") or "").strip()
    attachment = request.files.get("attachment")

    if warehouse_id is None:
        flash("Gudang dokumen wajib diisi", "error")
        return redirect("/hris/documents")

    if not document_title or not document_code or not effective_date:
        flash("Judul, kode, dan effective date dokumen wajib diisi", "error")
        return redirect("/hris/documents")

    if _calculate_leave_days(effective_date, effective_date) is None:
        flash("Tanggal efektif dokumen tidak valid", "error")
        return redirect("/hris/documents")

    if review_date and _calculate_leave_days(effective_date, review_date) is None:
        flash("Rentang tanggal dokumen tidak valid", "error")
        return redirect("/hris/documents")

    duplicate = db.execute(
        "SELECT id FROM document_records WHERE document_code=? AND id<>?",
        (document_code, document_id),
    ).fetchone()
    if duplicate:
        flash("Kode dokumen sudah digunakan record lain", "error")
        return redirect("/hris/documents")

    attachment_meta = {
        "attachment_name": document["attachment_name"],
        "attachment_path": document["attachment_path"],
        "attachment_mime": document["attachment_mime"],
        "attachment_size": int(document["attachment_size"] or 0),
    }
    reset_signature = False
    if attachment and (attachment.filename or "").strip():
        try:
            attachment_meta = _store_document_attachment(attachment)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect("/hris/documents")
        if document["attachment_path"]:
            _remove_document_file(document["attachment_path"])
        reset_signature = True

    handled_by, handled_at = _build_document_handling(status)
    db.execute(
        """
        UPDATE document_records
        SET warehouse_id=?,
            document_title=?,
            document_code=?,
            document_type=?,
            status=?,
            effective_date=?,
            review_date=?,
            owner_name=?,
            note=?,
            attachment_name=?,
            attachment_path=?,
            attachment_mime=?,
            attachment_size=?,
            signature_path=?,
            signed_by=?,
            signed_at=?,
            handled_by=?,
            handled_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            warehouse_id,
            document_title,
            document_code,
            document_type,
            status,
            effective_date,
            review_date or None,
            owner_name or None,
            note or None,
            attachment_meta["attachment_name"],
            attachment_meta["attachment_path"],
            attachment_meta["attachment_mime"],
            int(attachment_meta["attachment_size"] or 0),
            None if reset_signature else document["signature_path"],
            None if reset_signature else document["signed_by"],
            None if reset_signature else document["signed_at"],
            handled_by,
            handled_at,
            _current_timestamp(),
            document_id,
        ),
    )
    if reset_signature and document["signature_path"]:
        _remove_document_file(document["signature_path"], signature=True)
    db.commit()

    flash("Document berhasil diupdate", "success")
    return redirect("/hris/documents")


@hris_bp.route("/documents/approval/<int:document_id>")
def document_approval_sheet(document_id):
    if not can_manage_document_records():
        flash("Tidak punya akses untuk membuka lembar pengesahan documents", "error")
        return redirect("/hris/documents")

    db = get_db()
    document = _get_document_by_id(db, document_id)
    if not document:
        flash("Document tidak ditemukan", "error")
        return redirect("/hris/documents")

    decorated_document = _decorate_document_record(document)
    return render_template(
        "document_approval_sheet.html",
        document=decorated_document,
        document_return_to=f"/hris/documents/approval/{document_id}",
    )


@hris_bp.route("/documents/sign/<int:document_id>", methods=["POST"])
def sign_document(document_id):
    return_to = _safe_hris_return_to("/hris/documents")
    if not can_manage_document_records():
        flash("Tidak punya akses untuk mengesahkan documents", "error")
        return redirect(return_to)

    db = get_db()
    document = _get_document_by_id(db, document_id)
    if not document:
        flash("Document tidak ditemukan", "error")
        return redirect(return_to)

    if not document["attachment_path"]:
        flash("Upload lampiran dokumen dulu sebelum pengesahan digital.", "error")
        return redirect(return_to)

    signature_data = (request.form.get("signature_data") or "").strip()
    try:
        signature_path = _store_document_signature(signature_data)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(return_to)

    if document["signature_path"] and document["signature_path"] != signature_path:
        _remove_document_file(document["signature_path"], signature=True)

    db.execute(
        """
        UPDATE document_records
        SET signature_path=?,
            signed_by=?,
            signed_at=?,
            updated_at=?
        WHERE id=?
        """,
        (
            signature_path,
            session.get("user_id"),
            _current_timestamp(),
            _current_timestamp(),
            document_id,
        ),
    )
    db.commit()

    flash("Document berhasil disahkan dengan tanda tangan digital", "success")
    return redirect(return_to)


@hris_bp.route("/documents/delete/<int:document_id>", methods=["POST"])
def delete_document(document_id):
    if not can_manage_document_records():
        flash("Tidak punya akses untuk mengelola documents", "error")
        return redirect("/hris/documents")

    db = get_db()
    document = _get_document_by_id(db, document_id)
    if not document:
        flash("Document tidak ditemukan", "error")
        return redirect("/hris/documents")

    _remove_document_file(document["attachment_path"])
    _remove_document_file(document["signature_path"], signature=True)
    db.execute("DELETE FROM document_records WHERE id=?", (document_id,))
    db.commit()

    flash("Document berhasil dihapus", "success")
    return redirect("/hris/documents")
