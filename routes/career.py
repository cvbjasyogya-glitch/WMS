from flask import Blueprint, flash, redirect, render_template, request, url_for

from database import get_db
from services.career_service import (
    assign_candidate_assessment_code,
    decode_assessment_answers,
    encode_assessment_answers,
    ensure_candidate_assessment_code,
    ensure_career_schema,
    normalize_assessment_code,
    normalize_career_assessment_status,
    normalize_career_application_channel,
    save_career_resume,
    score_assessment_questions,
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


def _fetch_candidate_by_assessment_code(db, code):
    safe_code = normalize_assessment_code(code)
    if not safe_code:
        return None
    row = db.execute(
        """
        SELECT
            r.*,
            o.title AS vacancy_title,
            o.description AS vacancy_description,
            o.requirements AS vacancy_requirements,
            w.name AS warehouse_name
        FROM recruitment_candidates r
        LEFT JOIN career_openings o ON r.vacancy_id = o.id
        LEFT JOIN warehouses w ON r.warehouse_id = w.id
        WHERE r.assessment_code=?
        LIMIT 1
        """,
        (safe_code,),
    ).fetchone()
    return dict(row) if row else None


def _fetch_public_assessment_questions(db, warehouse_id=None):
    query = """
        SELECT *
        FROM recruitment_assessment_questions
        WHERE COALESCE(is_active, 1)=1
    """
    params = []
    if warehouse_id:
        query += " AND (warehouse_id IS NULL OR warehouse_id=?)"
        params.append(warehouse_id)
    else:
        query += " AND warehouse_id IS NULL"
    query += " ORDER BY COALESCE(sort_order, 0) ASC, id ASC"
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
    assessment_code = normalize_assessment_code(request.args.get("code"))
    latest_candidate = _fetch_candidate_by_assessment_code(db, assessment_code) if assessment_code else None

    return render_template(
        "career.html",
        openings=openings,
        warehouses=warehouses,
        selected_opening=selected_opening,
        selected_warehouse_id=selected_warehouse_id,
        latest_assessment_code=assessment_code,
        latest_candidate=latest_candidate,
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
    created_candidate = db.execute(
        """
        SELECT id, assessment_code
        FROM recruitment_candidates
        WHERE candidate_name=? AND vacancy_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (candidate_name, opening["id"]),
    ).fetchone()
    assessment_code = ensure_candidate_assessment_code(
        db,
        created_candidate["id"],
        created_candidate["assessment_code"] if created_candidate else "",
    )
    db.commit()

    flash(
        f"Lamaran berhasil dikirim. Simpan kode tes Anda: {assessment_code}.",
        "success",
    )
    return redirect(url_for("career.index", vacancy=opening["id"], code=assessment_code))


@career_bp.route("/karir/tes")
def assessment():
    db = get_db()
    ensure_career_schema(db)
    assessment_code = normalize_assessment_code(request.args.get("code"))
    if not assessment_code:
        flash("Masukkan kode tes 5 digit yang valid.", "error")
        return redirect(url_for("career.index"))

    candidate = _fetch_candidate_by_assessment_code(db, assessment_code)
    if not candidate:
        flash("Kode tes tidak ditemukan.", "error")
        return redirect(url_for("career.index"))

    questions = _fetch_public_assessment_questions(db, candidate.get("warehouse_id"))
    if not questions:
        flash("Soal tes belum disiapkan HR untuk posisi ini.", "error")
        return redirect(url_for("career.index", code=assessment_code))

    if candidate.get("assessment_status") in {"submitted", "reviewed"}:
        score_summary = score_assessment_questions(questions, candidate.get("assessment_answers_json"))
        final_score = candidate.get("assessment_manual_score")
        if final_score is None:
            final_score = candidate.get("assessment_final_score")
        if final_score is None:
            final_score = score_summary["percentage"]
        return render_template(
            "career_assessment.html",
            candidate=candidate,
            questions=score_summary["questions"],
            assessment_code=assessment_code,
            score_summary=score_summary,
            assessment_state="finished",
            final_score=round(float(final_score or 0), 2),
        )

    answers = decode_assessment_answers(candidate.get("assessment_answers_json"))
    if candidate.get("assessment_status") != "started":
        db.execute(
            """
            UPDATE recruitment_candidates
            SET assessment_status=?,
                assessment_started_at=COALESCE(assessment_started_at, CURRENT_TIMESTAMP),
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (normalize_career_assessment_status("started"), candidate["id"]),
        )
        db.commit()
        candidate["assessment_status"] = "started"

    return render_template(
        "career_assessment.html",
        candidate=candidate,
        questions=questions,
        assessment_code=assessment_code,
        assessment_state="active",
        existing_answers=answers,
        violation_count=int(candidate.get("assessment_violation_count") or 0),
    )


@career_bp.route("/karir/tes/submit", methods=["POST"])
def submit_assessment():
    db = get_db()
    ensure_career_schema(db)
    assessment_code = normalize_assessment_code(request.form.get("assessment_code"))
    candidate = _fetch_candidate_by_assessment_code(db, assessment_code)
    if not candidate:
        flash("Kode tes tidak ditemukan.", "error")
        return redirect(url_for("career.index"))

    questions = _fetch_public_assessment_questions(db, candidate.get("warehouse_id"))
    if not questions:
        flash("Soal tes belum tersedia.", "error")
        return redirect(url_for("career.index", code=assessment_code))

    answers = {}
    for question in questions:
        field_name = f"answer_{int(question['id'])}"
        safe_answer = request.form.get(field_name)
        if safe_answer:
            answers[int(question["id"])] = safe_answer

    score_summary = score_assessment_questions(questions, answers)
    violation_count = max(int(request.form.get("violation_count") or 0), 0)
    answers_json = encode_assessment_answers(answers)
    db.execute(
        """
        UPDATE recruitment_candidates
        SET assessment_status=?,
            assessment_answers_json=?,
            assessment_auto_score=?,
            assessment_final_score=CASE
                WHEN assessment_manual_score IS NOT NULL THEN assessment_manual_score
                ELSE ?
            END,
            assessment_submitted_at=CURRENT_TIMESTAMP,
            assessment_violation_count=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            normalize_career_assessment_status("submitted"),
            answers_json,
            score_summary["percentage"],
            score_summary["percentage"],
            violation_count,
            candidate["id"],
        ),
    )
    db.commit()
    return redirect(url_for("career.assessment", code=assessment_code))
