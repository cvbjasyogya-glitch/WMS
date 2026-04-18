from flask import Blueprint, flash, redirect, render_template, request, url_for

from database import get_db
from services.career_service import (
    ensure_career_schema,
    normalize_career_application_channel,
    save_career_resume,
)


career_bp = Blueprint("career", __name__)


def _fetch_public_openings(db, selected_warehouse=None):
    query = """
        SELECT
            o.*,
            w.name AS warehouse_name
        FROM career_openings o
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        WHERE o.status=?
          AND COALESCE(o.is_public, 1)=1
    """
    params = ["published"]
    if selected_warehouse:
        query += " AND o.warehouse_id=?"
        params.append(selected_warehouse)
    query += " ORDER BY COALESCE(o.sort_order, 0) ASC, o.created_at DESC, o.id DESC"
    return [dict(row) for row in db.execute(query, params).fetchall()]


@career_bp.route("/karir")
def index():
    db = get_db()
    ensure_career_schema(db)

    selected_warehouse = request.args.get("warehouse", "").strip()
    try:
        selected_warehouse_id = int(selected_warehouse) if selected_warehouse else None
    except ValueError:
        selected_warehouse_id = None

    openings = _fetch_public_openings(db, selected_warehouse_id)
    warehouses = [dict(row) for row in db.execute("SELECT id, name FROM warehouses ORDER BY name ASC").fetchall()]
    selected_opening_id = request.args.get("vacancy", "").strip()
    try:
        selected_opening_id = int(selected_opening_id) if selected_opening_id else None
    except ValueError:
        selected_opening_id = None
    selected_opening = next((opening for opening in openings if opening["id"] == selected_opening_id), None)
    if selected_opening is None and openings:
        selected_opening = openings[0]

    return render_template(
        "career.html",
        openings=openings,
        warehouses=warehouses,
        selected_opening=selected_opening,
        selected_warehouse_id=selected_warehouse_id,
    )


@career_bp.route("/karir/apply", methods=["POST"])
def apply():
    db = get_db()
    ensure_career_schema(db)

    opening_id_raw = (request.form.get("opening_id") or "").strip()
    try:
        opening_id = int(opening_id_raw)
    except (TypeError, ValueError):
        opening_id = None

    opening = None
    if opening_id:
        opening = db.execute(
            """
            SELECT id, warehouse_id, title, department, status, is_public
            FROM career_openings
            WHERE id=?
            """,
            (opening_id,),
        ).fetchone()

    if not opening or opening["status"] != "published" or int(opening["is_public"] or 0) != 1:
        flash("Lowongan yang dipilih tidak tersedia lagi.", "error")
        return redirect(url_for("career.index"))

    candidate_name = (request.form.get("candidate_name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    portfolio_url = (request.form.get("portfolio_url") or "").strip()
    note = (request.form.get("note") or "").strip()
    resume_file = request.files.get("resume_file")

    if not candidate_name or (not phone and not email):
        flash("Nama kandidat dan minimal satu kontak wajib diisi.", "error")
        return redirect(url_for("career.index", vacancy=opening["id"]))

    try:
        resume_original_name, resume_path = save_career_resume(resume_file)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("career.index", vacancy=opening["id"]))

    if not resume_path:
        flash("CV wajib diunggah agar HR bisa review lamaran.", "error")
        return redirect(url_for("career.index", vacancy=opening["id"]))

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
            note,
            vacancy_id,
            application_channel,
            portfolio_url,
            resume_original_name,
            resume_path,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        """,
        (
            candidate_name,
            opening["warehouse_id"],
            opening["title"],
            opening["department"],
            "applied",
            "active",
            "Halaman Karir",
            phone or None,
            email or None,
            note or None,
            opening["id"],
            normalize_career_application_channel("public_portal"),
            portfolio_url or None,
            resume_original_name,
            resume_path,
        ),
    )
    db.commit()

    flash("Lamaran berhasil dikirim. Tim HR akan review data Anda.", "success")
    return redirect(url_for("career.index", vacancy=opening["id"]))
