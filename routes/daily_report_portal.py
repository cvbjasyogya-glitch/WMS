import os
import sqlite3
import time
from datetime import date as date_cls

from flask import Blueprint, current_app, flash, redirect, render_template, request, session

from database import get_db
from routes.hris import (
    _current_timestamp,
    _get_self_service_employee,
    _get_daily_live_report_upload_folder,
    _get_daily_live_report_attachment_url,
    _normalize_daily_live_report_type,
    _store_daily_live_report_attachment,
    _format_upload_size,
)
from services.whatsapp_service import send_role_based_notification


daily_report_portal_bp = Blueprint("daily_report_portal", __name__, url_prefix="/laporan-harian")
DAILY_REPORT_DB_LOCK_RETRY_ATTEMPTS = 2
DAILY_REPORT_DB_LOCK_RETRY_DELAY_SECONDS = 0.35


def _is_sqlite_lock_error(exc):
    message = str(exc or "").strip().lower()
    return (
        "database is locked" in message
        or "database schema is locked" in message
        or "database table is locked" in message
    )


def _remove_daily_report_attachment(attachment_path):
    if not attachment_path:
        return
    safe_name = os.path.basename(attachment_path)
    if not safe_name:
        return
    file_path = os.path.join(_get_daily_live_report_upload_folder(), safe_name)
    if os.path.exists(file_path):
        os.remove(file_path)


def _build_daily_report_portal_context(db):
    linked_employee = _get_self_service_employee(db)
    if linked_employee:
        linked_employee = dict(linked_employee)
    user_id = session.get("user_id")
    recent_reports = [
        dict(row)
        for row in db.execute(
            """
            SELECT
                r.*,
                w.name AS warehouse_name,
                hu.username AS handled_username
            FROM daily_live_reports r
            LEFT JOIN warehouses w ON w.id = r.warehouse_id
            LEFT JOIN users hu ON hu.id = r.handled_by
            WHERE r.user_id=?
            ORDER BY r.report_date DESC, r.created_at DESC, r.id DESC
            LIMIT 8
            """,
            (user_id,),
        ).fetchall()
    ]
    for report in recent_reports:
        report["attachment_url"] = _get_daily_live_report_attachment_url(report.get("attachment_path"))
        report["attachment_size_label"] = _format_upload_size(report.get("attachment_size"))
    summary = {
        "total": len(recent_reports),
        "submitted": sum(1 for item in recent_reports if item["status"] == "submitted"),
        "follow_up": sum(1 for item in recent_reports if item["status"] == "follow_up"),
        "reviewed": sum(1 for item in recent_reports if item["status"] == "reviewed"),
        "closed": sum(1 for item in recent_reports if item["status"] == "closed"),
    }
    return {
        "linked_employee": linked_employee,
        "recent_reports": recent_reports,
        "daily_report_summary": summary,
        "today_value": date_cls.today().isoformat(),
    }


@daily_report_portal_bp.route("/")
def index():
    db = get_db()
    return render_template("daily_report_portal.html", **_build_daily_report_portal_context(db))


@daily_report_portal_bp.route("/submit", methods=["POST"])
def submit():
    db = get_db()
    linked_employee = _get_self_service_employee(db)
    if linked_employee:
        linked_employee = dict(linked_employee)

    report_type = _normalize_daily_live_report_type(request.form.get("report_type"))
    report_date = (request.form.get("report_date") or "").strip() or date_cls.today().isoformat()
    title = (request.form.get("title") or "").strip()
    summary = (request.form.get("summary") or "").strip()
    blocker_note = (request.form.get("blocker_note") or "").strip()
    follow_up_note = (request.form.get("follow_up_note") or "").strip()
    attachment = request.files.get("attachment")

    if not title or not summary or not blocker_note or not follow_up_note:
        flash("Judul, ringkasan, kendala, dan tindak lanjut wajib diisi.", "error")
        return redirect("/laporan-harian/")

    if not report_date:
        flash("Tanggal laporan wajib diisi.", "error")
        return redirect("/laporan-harian/")

    try:
        report_date = date_cls.fromisoformat(report_date).isoformat()
    except ValueError:
        flash("Tanggal laporan tidak valid.", "error")
        return redirect("/laporan-harian/")

    attachment_meta = {
        "attachment_name": None,
        "attachment_path": None,
        "attachment_mime": None,
        "attachment_size": 0,
    }
    if attachment and (attachment.filename or "").strip():
        if report_type != "live":
            flash("Lampiran bukti hanya tersedia untuk report live.", "error")
            return redirect("/laporan-harian/")
        try:
            attachment_meta = _store_daily_live_report_attachment(attachment)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect("/laporan-harian/")

    max_retries = max(
        0,
        int(
            current_app.config.get(
                "DAILY_REPORT_DB_LOCK_RETRY_ATTEMPTS",
                DAILY_REPORT_DB_LOCK_RETRY_ATTEMPTS,
            )
            or 0
        ),
    )
    retry_delay = max(
        0.0,
        float(
            current_app.config.get(
                "DAILY_REPORT_DB_LOCK_RETRY_DELAY_SECONDS",
                DAILY_REPORT_DB_LOCK_RETRY_DELAY_SECONDS,
            )
            or 0.0
        ),
    )

    for attempt in range(max_retries + 1):
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO daily_live_reports(
                    user_id,
                    employee_id,
                    warehouse_id,
                    report_type,
                    report_date,
                    title,
                    summary,
                    blocker_note,
                    follow_up_note,
                    status,
                    hr_note,
                    attachment_name,
                    attachment_path,
                    attachment_mime,
                    attachment_size,
                    handled_by,
                    handled_at,
                    updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    session.get("user_id"),
                    linked_employee["id"] if linked_employee else session.get("employee_id"),
                    (linked_employee["warehouse_id"] if linked_employee else session.get("warehouse_id")) or 1,
                    report_type,
                    report_date,
                    title,
                    summary,
                    blocker_note or None,
                    follow_up_note or None,
                    "submitted",
                    None,
                    attachment_meta["attachment_name"],
                    attachment_meta["attachment_path"],
                    attachment_meta["attachment_mime"],
                    int(attachment_meta["attachment_size"] or 0),
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
                    "Daily report submit hit SQLite lock, retry %s/%s",
                    attempt + 1,
                    max_retries,
                )
                time.sleep(retry_delay)
                continue
            _remove_daily_report_attachment(attachment_meta.get("attachment_path"))
            if _is_sqlite_lock_error(exc):
                current_app.logger.warning("Daily report submit failed after SQLite lock retries")
                flash(
                    "Report gagal disimpan karena database sedang sibuk di server. Coba ulangi beberapa detik lagi.",
                    "error",
                )
                return redirect("/laporan-harian/")
            flash("Report gagal disimpan. Coba ulangi beberapa detik lagi.", "error")
            return redirect("/laporan-harian/")
        except Exception:
            db.rollback()
            _remove_daily_report_attachment(attachment_meta.get("attachment_path"))
            flash("Report gagal disimpan. Coba ulangi beberapa detik lagi.", "error")
            return redirect("/laporan-harian/")

    try:
        employee_label = (
            (linked_employee["full_name"] if linked_employee and linked_employee.get("full_name") else None)
            or session.get("username")
            or "Staff"
        )
        warehouse_label = (
            (linked_employee["warehouse_name"] if linked_employee and linked_employee.get("warehouse_name") else None)
            or "Gudang"
        )
        send_role_based_notification(
            "report.live_submitted" if report_type == "live" else "report.daily_submitted",
            {
                "warehouse_id": (linked_employee["warehouse_id"] if linked_employee else session.get("warehouse_id")) or 1,
                "employee_name": employee_label,
                "warehouse_name": warehouse_label,
                "title": title,
                "time_label": _current_timestamp()[11:16],
                "link_url": "/hris/report",
            },
        )
    except Exception as exc:
        print("DAILY REPORT WHATSAPP ROLE NOTIFICATION ERROR:", exc)

    flash("Report berhasil dikirim. HR atau Super Admin akan memproses statusnya dari HRIS.", "success")
    return redirect("/laporan-harian/")


@daily_report_portal_bp.route("/kpi/submit", methods=["POST"])
def submit_kpi_staff_report():
    from routes.kpi_portal import _submit_kpi_staff_report_form

    return _submit_kpi_staff_report_form("/kpi-staff/#kpi-target-form")
