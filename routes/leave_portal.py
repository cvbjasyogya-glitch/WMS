import sqlite3
import time
from datetime import date as date_cls, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template
from flask import request

from database import get_db
from routes.hris import (
    LEAVE_TYPE_LABELS,
    _build_leave_summary,
    _calculate_leave_days,
    _current_timestamp,
    _get_self_service_employee,
    _normalize_leave_type,
)


leave_portal_bp = Blueprint("leave_portal", __name__, url_prefix="/libur")
LEAVE_PORTAL_DB_LOCK_RETRY_ATTEMPTS = 2
LEAVE_PORTAL_DB_LOCK_RETRY_DELAY_SECONDS = 0.35


MONTH_NAMES_ID = [
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


def _is_sqlite_lock_error(exc):
    message = str(exc or "").strip().lower()
    return (
        "database is locked" in message
        or "database schema is locked" in message
        or "database table is locked" in message
    )


def _normalize_leave_log_month(value):
    raw_value = str(value or "").strip()
    if len(raw_value) == 7 and raw_value[4] == "-":
        try:
            return date_cls(int(raw_value[:4]), int(raw_value[5:7]), 1)
        except ValueError:
            pass
    today = date_cls.today()
    return today.replace(day=1)


def _build_leave_log_month_range(selected_month):
    if selected_month.month == 12:
        next_month = date_cls(selected_month.year + 1, 1, 1)
    else:
        next_month = date_cls(selected_month.year, selected_month.month + 1, 1)
    month_end = next_month - timedelta(days=1)
    return selected_month.isoformat(), month_end.isoformat()


def _format_leave_log_month_label(selected_month):
    return f"{MONTH_NAMES_ID[selected_month.month - 1]} {selected_month.year}"


def _format_leave_portal_status_label(status):
    value = (status or "").strip().lower()
    return value.replace("_", " ").title() if value else "-"


def _build_leave_range_label(start_date, end_date):
    start_value = str(start_date or "").strip()
    end_value = str(end_date or "").strip()
    if start_value and end_value and start_value != end_value:
        return f"{start_value} s/d {end_value}"
    return start_value or end_value or "-"


def _build_leave_status_badge_class(status):
    normalized = (status or "").strip().lower()
    if normalized == "approved":
        return "green"
    if normalized == "pending":
        return "orange"
    if normalized in {"rejected", "cancelled"}:
        return "red"
    return ""


def _format_leave_portal_timestamp(value):
    text = str(value or "").strip()
    return text[:16] if len(text) >= 16 else (text or "-")


def _fetch_leave_portal_history(db, linked_employee, selected_month):
    if not linked_employee:
        return []

    month_start, month_end = _build_leave_log_month_range(selected_month)
    history_rows = db.execute(
        """
        SELECT
            l.*,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM leave_requests l
        LEFT JOIN warehouses w ON l.warehouse_id = w.id
        LEFT JOIN users u ON l.handled_by = u.id
        WHERE l.employee_id=?
          AND NOT (l.end_date < ? OR l.start_date > ?)
        ORDER BY l.start_date DESC, l.id DESC
        """,
        (linked_employee["id"], month_start, month_end),
    ).fetchall()

    history = []
    for row in history_rows:
        record = dict(row)
        record["leave_type_label"] = LEAVE_TYPE_LABELS.get(record.get("leave_type"), "Libur")
        record["status_label"] = _format_leave_portal_status_label(record.get("status"))
        record["status_badge_class"] = _build_leave_status_badge_class(record.get("status"))
        record["range_label"] = _build_leave_range_label(record.get("start_date"), record.get("end_date"))
        record["created_at_label"] = _format_leave_portal_timestamp(record.get("created_at"))
        record["handled_at_label"] = _format_leave_portal_timestamp(record.get("handled_at"))
        history.append(record)
    return history


def _build_leave_portal_context(db):
    linked_employee = _get_self_service_employee(db)
    selected_month = _normalize_leave_log_month(request.args.get("month"))
    leave_history = _fetch_leave_portal_history(db, linked_employee, selected_month)
    return {
        "linked_employee": linked_employee,
        "leave_history": leave_history,
        "leave_history_summary": _build_leave_summary(leave_history),
        "leave_log_month_value": selected_month.strftime("%Y-%m"),
        "leave_log_month_label": _format_leave_log_month_label(selected_month),
    }


@leave_portal_bp.route("/")
def index():
    db = get_db()
    return render_template("leave_portal.html", **_build_leave_portal_context(db))


@leave_portal_bp.route("/submit", methods=["POST"])
def submit():
    db = get_db()
    linked_employee = _get_self_service_employee(db)
    if linked_employee is None:
        flash("Akun ini belum ditautkan ke data karyawan. Hubungkan dulu dari halaman Admin.", "error")
        return redirect("/libur/")

    leave_type = _normalize_leave_type(request.form.get("leave_type"))
    start_date = (request.form.get("start_date") or "").strip()
    end_date = (request.form.get("end_date") or "").strip()
    reason = (request.form.get("reason") or "").strip()
    note = (request.form.get("note") or "").strip()

    total_days = _calculate_leave_days(start_date, end_date)
    if total_days is None:
        flash("Rentang tanggal libur tidak valid.", "error")
        return redirect("/libur/")

    if not reason:
        flash("Alasan libur wajib diisi.", "error")
        return redirect("/libur/")

    duplicate = db.execute(
        """
        SELECT id
        FROM leave_requests
        WHERE employee_id=? AND leave_type=? AND start_date=? AND end_date=? AND status<>?
        """,
        (linked_employee["id"], leave_type, start_date, end_date, "cancelled"),
    ).fetchone()
    if duplicate:
        flash("Pengajuan libur dengan tanggal yang sama sudah ada.", "error")
        return redirect("/libur/")
    max_retries = max(
        0,
        int(
            current_app.config.get(
                "LEAVE_PORTAL_DB_LOCK_RETRY_ATTEMPTS",
                LEAVE_PORTAL_DB_LOCK_RETRY_ATTEMPTS,
            )
            or 0
        ),
    )
    retry_delay = max(
        0.0,
        float(
            current_app.config.get(
                "LEAVE_PORTAL_DB_LOCK_RETRY_DELAY_SECONDS",
                LEAVE_PORTAL_DB_LOCK_RETRY_DELAY_SECONDS,
            )
            or 0.0
        ),
    )

    for attempt in range(max_retries + 1):
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
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
                    linked_employee["id"],
                    linked_employee["warehouse_id"],
                    leave_type,
                    start_date,
                    end_date,
                    total_days,
                    "pending",
                    reason,
                    note or None,
                    None,
                    None,
                    _current_timestamp(),
                ),
            )
            db.commit()
            break
        except sqlite3.OperationalError as exc:
            db.rollback()
            if _is_sqlite_lock_error(exc) and attempt < max_retries:
                current_app.logger.warning(
                    "Leave portal submit hit SQLite lock, retry %s/%s",
                    attempt + 1,
                    max_retries,
                )
                time.sleep(retry_delay)
                continue
            if _is_sqlite_lock_error(exc):
                current_app.logger.warning("Leave portal submit failed after SQLite lock retries")
                flash(
                    "Pengajuan libur gagal disimpan karena database sedang sibuk di server. Coba ulangi beberapa detik lagi.",
                    "error",
                )
                return redirect("/libur/")
            flash("Pengajuan libur gagal disimpan. Coba ulangi beberapa detik lagi.", "error")
            return redirect("/libur/")
        except Exception:
            db.rollback()
            flash("Pengajuan libur gagal disimpan. Coba ulangi beberapa detik lagi.", "error")
            return redirect("/libur/")

    flash("Pengajuan libur berhasil dikirim. Status akan diproses oleh HR atau Super Admin.", "success")
    return redirect("/libur/")
