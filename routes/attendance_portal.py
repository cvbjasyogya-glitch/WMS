from datetime import date as date_cls

from flask import Blueprint, flash, redirect, render_template, request, session

from database import get_db
from routes.hris import (
    _attach_biometric_display_meta,
    _current_timestamp,
    _get_self_service_employee,
    _insert_biometric_log_record,
    _normalize_accuracy,
    _normalize_biometric_punch_type,
    _normalize_datetime_input,
    _normalize_latitude,
    _normalize_longitude,
    _save_biometric_photo_data,
)


attendance_portal_bp = Blueprint("attendance_portal", __name__, url_prefix="/absen")


def _fetch_attendance_portal_state(db):
    linked_employee = _get_self_service_employee(db)
    today_date = date_cls.today().isoformat()
    attendance_today = None
    recent_logs = []

    if linked_employee:
        attendance_today = db.execute(
            """
            SELECT attendance_date, check_in, check_out, status, note
            FROM attendance_records
            WHERE employee_id=? AND attendance_date=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (linked_employee["id"], today_date),
        ).fetchone()

        recent_logs = [
            _attach_biometric_display_meta(dict(row))
            for row in db.execute(
                """
                SELECT
                    b.*,
                    w.name AS warehouse_name
                FROM biometric_logs b
                LEFT JOIN warehouses w ON b.warehouse_id = w.id
                WHERE b.employee_id=?
                ORDER BY b.punch_time DESC, b.id DESC
                LIMIT 6
                """,
                (linked_employee["id"],),
            ).fetchall()
        ]

    return linked_employee, attendance_today, recent_logs, today_date


@attendance_portal_bp.route("/")
def index():
    db = get_db()
    linked_employee, attendance_today, recent_logs, today_date = _fetch_attendance_portal_state(db)

    return render_template(
        "attendance_portal.html",
        linked_employee=linked_employee,
        attendance_today=attendance_today,
        recent_logs=recent_logs,
        today_date=today_date,
    )


@attendance_portal_bp.route("/submit", methods=["POST"])
def submit():
    db = get_db()
    linked_employee = _get_self_service_employee(db)
    if linked_employee is None:
        flash("Akun ini belum ditautkan ke data karyawan. Hubungkan dulu dari halaman Admin.", "error")
        return redirect("/absen/")

    location_label = (request.form.get("location_label") or "").strip()
    latitude = _normalize_latitude(request.form.get("latitude"))
    longitude = _normalize_longitude(request.form.get("longitude"))
    accuracy_m = _normalize_accuracy(request.form.get("accuracy_m"))
    punch_type = _normalize_biometric_punch_type(request.form.get("punch_type"))
    punch_time = _normalize_datetime_input(request.form.get("punch_time")) or _current_timestamp()
    note = (request.form.get("note") or "").strip()
    photo_data_url = request.form.get("photo_data_url")

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
    note_parts.append("Captured from attendance portal")

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
        photo_path=photo_path,
    )
    db.commit()

    flash("Absen foto berhasil direkam dan langsung masuk ke log HRIS Geotag.", "success")
    return redirect("/absen/")
