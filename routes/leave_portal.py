from flask import Blueprint, flash, redirect, render_template
from flask import request

from database import get_db
from routes.hris import (
    _calculate_leave_days,
    _current_timestamp,
    _get_self_service_employee,
    _normalize_leave_type,
)


leave_portal_bp = Blueprint("leave_portal", __name__, url_prefix="/libur")


def _build_leave_portal_context(db):
    linked_employee = _get_self_service_employee(db)
    return {
        "linked_employee": linked_employee,
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

    flash("Pengajuan libur berhasil dikirim. Status akan diproses oleh HR atau Super Admin.", "success")
    return redirect("/libur/")
