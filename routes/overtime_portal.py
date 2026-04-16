from datetime import date as date_cls

from flask import Blueprint, current_app, flash, redirect, render_template, request, session

from database import get_db
from routes.hris import (
    OVERTIME_BALANCE_CAP_MINUTES,
    OVERTIME_WEEKLY_USAGE_LIMIT_MINUTES,
    _build_employee_overtime_balance,
    _ensure_overtime_feature_schema,
    _format_duration_minutes_label,
    _get_overtime_usage_mode_label,
    _get_self_service_employee,
    _normalize_overtime_usage_mode,
    _parse_iso_date,
    _to_int,
)
from services.attendance_request_service import (
    get_attendance_request_type_label,
    parse_attendance_request_payload,
    queue_attendance_request,
)
from services.rbac import has_permission, normalize_role


overtime_portal_bp = Blueprint("overtime_portal", __name__, url_prefix="/lembur")


def _empty_overtime_portal_context():
    return {
        "linked_employee": None,
        "balance": None,
        "request_history": [],
        "request_history_summary": {
            "total": 0,
            "pending": 0,
            "approved": 0,
            "rejected": 0,
        },
        "today_value": date_cls.today().isoformat(),
        "can_request_overtime_add": _can_request_overtime_add(),
        "overtime_balance_cap_label": _format_duration_minutes_label(OVERTIME_BALANCE_CAP_MINUTES),
        "overtime_weekly_limit_label": _format_duration_minutes_label(OVERTIME_WEEKLY_USAGE_LIMIT_MINUTES),
    }


def _has_overtime_portal_access():
    return has_permission(session.get("role"), "access_overtime_portal")


def _can_request_overtime_add():
    return normalize_role(session.get("role")) == "hr"


def _format_portal_timestamp(value):
    text = str(value or "").strip()
    return text[:16] if len(text) >= 16 else (text or "-")


def _build_request_status_meta(status):
    normalized = str(status or "").strip().lower()
    if normalized == "approved":
        return {"label": "Approved", "badge_class": "green"}
    if normalized == "pending":
        return {"label": "Pending", "badge_class": "orange"}
    if normalized in {"rejected", "cancelled"}:
        return {"label": "Rejected", "badge_class": "red"}
    return {"label": normalized.replace("_", " ").title() or "-", "badge_class": ""}


def _fetch_overtime_request_history(db, linked_employee, limit=20):
    if not linked_employee:
        return []
    _ensure_overtime_feature_schema(db)

    rows = db.execute(
        """
        SELECT
            r.*,
            w.name AS warehouse_name,
            ru.username AS requested_by_name,
            hu.username AS handled_by_name
        FROM attendance_action_requests r
        LEFT JOIN warehouses w ON w.id = r.warehouse_id
        LEFT JOIN users ru ON ru.id = r.requested_by
        LEFT JOIN users hu ON hu.id = r.handled_by
        WHERE r.employee_id=?
          AND r.request_type IN ('overtime_add', 'overtime_use', 'overtime_usage_delete')
        ORDER BY
            CASE WHEN r.status='pending' THEN 0 ELSE 1 END,
            COALESCE(r.handled_at, r.created_at) DESC,
            r.id DESC
        LIMIT ?
        """,
        (linked_employee["id"], int(max(1, limit))),
    ).fetchall()

    history = []
    for row in rows:
        record = dict(row)
        status_meta = _build_request_status_meta(record.get("status"))
        record["status_label"] = status_meta["label"]
        record["status_badge_class"] = status_meta["badge_class"]
        record["request_type_label"] = get_attendance_request_type_label(record.get("request_type"))
        record["payload_map"] = parse_attendance_request_payload(record.get("payload"))
        record["created_at_label"] = _format_portal_timestamp(record.get("created_at"))
        record["handled_at_label"] = _format_portal_timestamp(record.get("handled_at"))
        history.append(record)
    return history


def _build_overtime_portal_context(db):
    linked_employee = _get_self_service_employee(db)
    if linked_employee:
        linked_employee = dict(linked_employee)
    balance = (
        _build_employee_overtime_balance(
            db,
            linked_employee["id"],
            include_pending_weekly_usage=True,
        )
        if linked_employee
        else None
    )
    request_history = _fetch_overtime_request_history(db, linked_employee)
    return {
        "linked_employee": linked_employee,
        "balance": balance,
        "request_history": request_history,
        "request_history_summary": {
            "total": len(request_history),
            "pending": sum(1 for item in request_history if str(item.get("status") or "").lower() == "pending"),
            "approved": sum(1 for item in request_history if str(item.get("status") or "").lower() == "approved"),
            "rejected": sum(1 for item in request_history if str(item.get("status") or "").lower() == "rejected"),
        },
        "today_value": date_cls.today().isoformat(),
        "can_request_overtime_add": _can_request_overtime_add(),
        "overtime_balance_cap_label": _format_duration_minutes_label(OVERTIME_BALANCE_CAP_MINUTES),
        "overtime_weekly_limit_label": _format_duration_minutes_label(OVERTIME_WEEKLY_USAGE_LIMIT_MINUTES),
    }


@overtime_portal_bp.route("/")
def index():
    if not _has_overtime_portal_access():
        flash("Akses halaman lembur hanya tersedia untuk role yang diizinkan.", "error")
        return redirect("/workspace/")

    db = get_db()
    try:
        _ensure_overtime_feature_schema(db)
        context = _build_overtime_portal_context(db)
    except Exception as exc:
        current_app.logger.exception("OVERTIME PORTAL INDEX ERROR: %s", exc)
        flash(
            "Portal lembur belum siap di server. Schema overtime di database VPS perlu disinkronkan dulu.",
            "error",
        )
        context = _empty_overtime_portal_context()
    return render_template("overtime_portal.html", **context)


@overtime_portal_bp.route("/submit", methods=["POST"])
def submit():
    if not _has_overtime_portal_access():
        flash("Akses halaman lembur hanya tersedia untuk role yang diizinkan.", "error")
        return redirect("/workspace/")

    db = get_db()
    try:
        _ensure_overtime_feature_schema(db)
    except Exception as exc:
        current_app.logger.exception("OVERTIME PORTAL SCHEMA ERROR: %s", exc)
        flash(
            "Portal lembur belum siap di server. Schema overtime di database VPS perlu disinkronkan dulu.",
            "error",
        )
        return redirect("/lembur/")
    linked_employee = _get_self_service_employee(db)
    if linked_employee is None:
        flash("Akun ini belum ditautkan ke data karyawan. Hubungkan dulu dari halaman Admin.", "error")
        return redirect("/lembur/")
    linked_employee = dict(linked_employee)

    request_mode = (request.form.get("request_mode") or "").strip().lower()
    request_date = _parse_iso_date((request.form.get("request_date") or "").strip())
    minutes_value = _to_int(request.form.get("minutes_amount"), default=None)
    usage_mode = _normalize_overtime_usage_mode(request.form.get("usage_mode"))
    reason = (request.form.get("reason") or "").strip()

    allowed_request_modes = {"reduce"}
    if _can_request_overtime_add():
        allowed_request_modes.add("add")

    if request_mode not in allowed_request_modes:
        if request_mode == "add":
            flash("Penambahan lembur hanya bisa diajukan oleh HR.", "error")
        else:
            flash("Jenis pengajuan lembur tidak valid.", "error")
        return redirect("/lembur/")

    if request_date is None:
        flash("Tanggal pengajuan lembur tidak valid.", "error")
        return redirect("/lembur/")

    if not reason:
        flash("Alasan pengajuan lembur wajib diisi.", "error")
        return redirect("/lembur/")

    try:
        balance = _build_employee_overtime_balance(
            db,
            linked_employee["id"],
            reference_date=request_date,
            include_pending_weekly_usage=True,
        )
    except Exception as exc:
        current_app.logger.exception("OVERTIME PORTAL BALANCE ERROR: %s", exc)
        flash(
            "Portal lembur belum siap di server. Schema overtime di database VPS perlu disinkronkan dulu.",
            "error",
        )
        return redirect("/lembur/")

    if request_mode == "add":
        if minutes_value is None or minutes_value <= 0:
            flash("Durasi lembur wajib diisi dalam menit dan lebih dari 0.", "error")
            return redirect("/lembur/")
        duration_label = _format_duration_minutes_label(minutes_value)
        request_type = "overtime_add"
        summary_title = f"{linked_employee['full_name']} - Tambah Lembur"
        payload = {
            "employee_id": linked_employee["id"],
            "employee_name": linked_employee["full_name"],
            "warehouse_id": linked_employee["warehouse_id"],
            "adjustment_date": request_date.isoformat(),
            "minutes_delta": minutes_value,
            "duration_label": duration_label,
            "note": reason,
        }
        success_message = f"Pengajuan penambahan lembur {duration_label} berhasil dikirim ke approval."
        duplicate_message = "Pengajuan penambahan lembur yang sama masih menunggu approval."
    else:
        if usage_mode == "cashout_all":
            minutes_value = int(balance.get("available_minutes") or 0)
            if minutes_value <= 0:
                flash("Saldo lembur saat ini kosong, jadi belum ada yang bisa diuangkan.", "error")
                return redirect("/lembur/")
        elif minutes_value is None or minutes_value <= 0:
            flash("Durasi lembur wajib diisi dalam menit dan lebih dari 0.", "error")
            return redirect("/lembur/")

        duration_label = _format_duration_minutes_label(minutes_value)
        if minutes_value > int(balance.get("available_minutes") or 0):
            flash(
                f"Saldo lembur saat ini tidak cukup. Sisa tersedia hanya {balance.get('available_label') or _format_duration_minutes_label(balance.get('available_minutes'), zero_label='0 mnt')}.",
                "error",
            )
            return redirect("/lembur/")
        if usage_mode != "cashout_all" and minutes_value > int(balance.get("weekly_remaining_minutes") or 0):
            flash(
                f"Pemakaian lembur reguler maksimal {balance.get('weekly_limit_label')} per minggu. "
                f"Sisa minggu ini hanya {balance.get('weekly_remaining_label')} untuk periode {balance.get('weekly_period_label')}.",
                "error",
            )
            return redirect("/lembur/")
        request_type = "overtime_use"
        summary_title = (
            f"{linked_employee['full_name']} - Uangkan Lembur"
            if usage_mode == "cashout_all"
            else f"{linked_employee['full_name']} - Kurangi Lembur"
        )
        payload = {
            "employee_id": linked_employee["id"],
            "employee_name": linked_employee["full_name"],
            "warehouse_id": linked_employee["warehouse_id"],
            "usage_date": request_date.isoformat(),
            "usage_mode": usage_mode,
            "usage_mode_label": _get_overtime_usage_mode_label(usage_mode),
            "minutes_used": minutes_value,
            "duration_label": duration_label,
            "note": reason,
        }
        success_message = (
            f"Pengajuan uangkan saldo lembur {duration_label} berhasil dikirim ke approval."
            if usage_mode == "cashout_all"
            else f"Pengajuan pengurangan lembur {duration_label} berhasil dikirim ke approval."
        )
        duplicate_message = (
            "Pengajuan uangkan saldo lembur yang sama masih menunggu approval."
            if usage_mode == "cashout_all"
            else "Pengajuan pengurangan lembur yang sama masih menunggu approval."
        )

    try:
        queue_result = queue_attendance_request(
            db,
            request_type=request_type,
            warehouse_id=linked_employee["warehouse_id"],
            employee_id=linked_employee["id"],
            requested_by=session.get("user_id"),
            summary_title=summary_title,
            summary_note=(
                f"{duration_label} pada {request_date.isoformat()}"
                f"{' | Uangkan semua saldo' if request_mode == 'reduce' and usage_mode == 'cashout_all' else ''}"
                f" | {reason}"
            ),
            payload=payload,
        )
        db.commit()
    except Exception as exc:
        current_app.logger.exception("OVERTIME PORTAL SUBMIT ERROR: %s", exc)
        db.rollback()
        flash("Pengajuan lembur gagal dikirim ke approval.", "error")
        return redirect("/lembur/")

    if queue_result.get("existing"):
        flash(duplicate_message, "info")
    else:
        flash(success_message, "success")
    return redirect("/lembur/")
