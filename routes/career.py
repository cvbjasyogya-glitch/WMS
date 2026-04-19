import hashlib

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

from database import get_db
from services.career_service import (
    create_public_account_request,
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
from services.notification_service import send_email


career_bp = Blueprint("career", __name__)
CAREER_ASSESSMENT_MAX_VIOLATIONS = 3


def _career_public_signin_url():
    return url_for("career.signin_page")


def _career_public_register_url():
    return url_for("career.signin_page")


def _resolve_career_public_media_url(configured_value, default_static_filename):
    safe_value = str(configured_value or "").strip()
    if not safe_value:
        safe_value = str(default_static_filename or "").strip()
    if safe_value.startswith(("http://", "https://", "data:", "/")):
        return safe_value
    return url_for("static", filename=safe_value)


@career_bp.context_processor
def inject_career_public_context():
    return {
        "career_notice_text": str(
            current_app.config.get("CAREER_PUBLIC_NOTICE_TEXT")
            or "ERP-CV.BJAS tidak memungut biaya apa pun selama proses pendaftaran dan seleksi karir berlangsung."
        ).strip(),
        "career_home_hero_image_url": _resolve_career_public_media_url(
            current_app.config.get("CAREER_HOME_HERO_IMAGE"),
            "brand/login-hero-crowd.jpeg",
        ),
        "career_public_signin_url": url_for("career.signin_page"),
    }


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


def _fetch_public_opening_by_id(db, opening_id):
    try:
        safe_opening_id = int(opening_id)
    except (TypeError, ValueError):
        return None
    if safe_opening_id <= 0:
        return None
    row = db.execute(
        """
        SELECT
            o.*,
            w.name AS warehouse_name
        FROM career_openings o
        LEFT JOIN warehouses w ON o.warehouse_id = w.id
        WHERE o.id=?
          AND o.status=?
          AND COALESCE(o.is_public, 1)=1
        LIMIT 1
        """,
        (safe_opening_id, "published"),
    ).fetchone()
    return dict(row) if row else None


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


def _fetch_public_assessment_questions(db, warehouse_id=None, shuffle_seed=""):
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
    questions = [dict(row) for row in db.execute(query, params).fetchall()]
    safe_seed = str(shuffle_seed or "").strip()
    if safe_seed:
        questions.sort(
            key=lambda question: hashlib.sha1(
                f"{safe_seed}:{int(question.get('id') or 0)}".encode("utf-8")
            ).hexdigest()
        )
    return questions


def _reset_candidate_assessment_session(db, candidate):
    safe_candidate = dict(candidate or {})
    candidate_id = int(safe_candidate.get("id") or 0)
    if candidate_id <= 0:
        raise ValueError("Kandidat tes tidak valid.")

    new_code = assign_candidate_assessment_code(db, candidate_id)
    db.execute(
        """
        UPDATE recruitment_candidates
        SET assessment_status=?,
            assessment_answers_json=NULL,
            assessment_auto_score=NULL,
            assessment_manual_score=NULL,
            assessment_final_score=NULL,
            assessment_review_notes=NULL,
            assessment_reviewed_by=NULL,
            assessment_reviewed_at=NULL,
            assessment_started_at=NULL,
            assessment_submitted_at=NULL,
            assessment_violation_count=0,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            normalize_career_assessment_status("pending"),
            candidate_id,
        ),
    )
    return new_code


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


@career_bp.route("/beranda")
def home():
    db = get_db()
    ensure_career_schema(db)
    openings = _fetch_public_openings(db)
    return render_template(
        "career_home.html",
        openings=openings,
        opening_count=len(openings),
    )


@career_bp.route("/about")
def about_page():
    db = get_db()
    ensure_career_schema(db)
    openings = _fetch_public_openings(db)
    return render_template(
        "career_about.html",
        openings=openings,
        opening_count=len(openings),
    )


@career_bp.route("/help")
def help_page():
    db = get_db()
    ensure_career_schema(db)
    return render_template(
        "career_help.html",
        signin_url=_career_public_signin_url(),
    )


@career_bp.route("/signin")
def signin_page():
    db = get_db()
    ensure_career_schema(db)
    flow = str(request.args.get("flow") or "signin").strip().lower()
    if flow not in {"signin", "signup"}:
        flow = "signin"
    registered = str(request.args.get("registered") or "").strip() in {"1", "true", "yes"}
    email = (request.args.get("email") or "").strip()
    return render_template(
        "career_signin.html",
        signin_url=_career_public_signin_url(),
        register_url=_career_public_register_url(),
        active_flow=flow,
        registration_success=registered,
        registration_email=email,
    )


@career_bp.route("/signin/auth", methods=["POST"])
def signin_submit():
    email = (request.form.get("email") or "").strip()
    password = (request.form.get("password") or "").strip()
    if not email or not password:
        flash("Email dan kata sandi wajib diisi.", "error")
        return redirect(url_for("career.signin_page", flow="signin"))

    flash(
        "Login kandidat publik sedang diaktifkan bertahap. Jika Anda sudah melamar, gunakan kode tes 5 digit atau hubungi HR.",
        "info",
    )
    return redirect(url_for("career.signin_page", flow="signin"))


@career_bp.route("/signin/register-request", methods=["POST"])
def signin_register_request():
    candidate_name = (request.form.get("candidate_name") or "").strip()
    email = (request.form.get("email") or "").strip()
    if not candidate_name or not email:
        flash("Nama lengkap dan email wajib diisi untuk mendaftarkan akun.", "error")
        return redirect(url_for("career.signin_page", flow="signup"))
    db = get_db()
    ensure_career_schema(db)
    try:
        create_public_account_request(
            db,
            candidate_name,
            email,
            source="career_public_signup",
        )
        db.commit()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("career.signin_page", flow="signup"))

    email_subject = "Permintaan akun ERP-CV.BJAS Career diterima"
    email_body = (
        f"Halo {candidate_name},\n\n"
        "Permintaan akun Anda untuk ERP-CV.BJAS Career sudah kami terima.\n"
        "Tim HR akan meninjau email ini sebelum akses kandidat publik diaktifkan.\n\n"
        "Sambil menunggu, Anda tetap bisa melihat lowongan aktif dan mengerjakan tes dengan kode 5 digit jika sudah diberikan HR.\n\n"
        "Salam,\nERP-CV.BJAS Career"
    )
    try:
        send_email(email, email_subject, email_body)
    except Exception:
        pass
    return redirect(
        url_for(
            "career.signin_page",
            flow="signup",
            registered=1,
            email=email,
        )
    )


@career_bp.route("/karir/lowongan/<int:opening_id>")
def opening_detail(opening_id):
    db = get_db()
    ensure_career_schema(db)

    opening = _fetch_public_opening_by_id(db, opening_id)
    if not opening:
        flash("Lowongan yang dipilih tidak tersedia lagi.", "error")
        return redirect(url_for("career.index"))

    assessment_code = normalize_assessment_code(request.args.get("code"))
    latest_candidate = _fetch_candidate_by_assessment_code(db, assessment_code) if assessment_code else None

    return render_template(
        "career_detail.html",
        opening=opening,
        latest_assessment_code=assessment_code,
        latest_candidate=latest_candidate,
        signin_url=_career_public_signin_url(),
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
        return redirect(url_for("career.opening_detail", opening_id=opening["id"]))

    try:
        resume_original_name, resume_path = save_career_resume(resume_file)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("career.opening_detail", opening_id=opening["id"]))

    if not resume_path:
        flash("CV wajib diunggah agar HR bisa review lamaran.", "error")
        return redirect(url_for("career.opening_detail", opening_id=opening["id"]))

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
    return redirect(url_for("career.opening_detail", opening_id=opening["id"], code=assessment_code))


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

    questions = _fetch_public_assessment_questions(db, candidate.get("warehouse_id"), shuffle_seed=assessment_code)
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
        max_violation_count=CAREER_ASSESSMENT_MAX_VIOLATIONS,
    )


@career_bp.route("/karir/tes/violation", methods=["POST"])
def record_assessment_violation():
    db = get_db()
    ensure_career_schema(db)

    assessment_code = normalize_assessment_code(request.form.get("assessment_code"))
    candidate = _fetch_candidate_by_assessment_code(db, assessment_code)
    if not candidate:
        return jsonify({"ok": False, "message": "Kode tes tidak ditemukan."}), 404

    if candidate.get("assessment_status") in {"submitted", "reviewed"}:
        return jsonify(
            {
                "ok": True,
                "reset": False,
                "violation_count": int(candidate.get("assessment_violation_count") or 0),
            }
        )

    violation_count = max(int(request.form.get("violation_count") or 0), 0)
    if violation_count >= CAREER_ASSESSMENT_MAX_VIOLATIONS:
        new_code = _reset_candidate_assessment_session(db, candidate)
        db.commit()
        return jsonify(
            {
                "ok": True,
                "reset": True,
                "new_code": new_code,
                "redirect_url": url_for("career.index"),
                "message": (
                    f"Pelanggaran sudah {CAREER_ASSESSMENT_MAX_VIOLATIONS} kali. "
                    f"Tes direset dari awal. Gunakan kode baru {new_code} untuk memulai lagi."
                ),
            }
        )

    db.execute(
        """
        UPDATE recruitment_candidates
        SET assessment_violation_count=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            violation_count,
            candidate["id"],
        ),
    )
    db.commit()
    return jsonify(
        {
            "ok": True,
            "reset": False,
            "violation_count": violation_count,
            "max_violation_count": CAREER_ASSESSMENT_MAX_VIOLATIONS,
        }
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

    questions = _fetch_public_assessment_questions(db, candidate.get("warehouse_id"), shuffle_seed=assessment_code)
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
    if violation_count >= CAREER_ASSESSMENT_MAX_VIOLATIONS:
        new_code = _reset_candidate_assessment_session(db, candidate)
        db.commit()
        flash(
            (
                f"Pelanggaran sudah {CAREER_ASSESSMENT_MAX_VIOLATIONS} kali. "
                f"Tes direset dari awal. Gunakan kode baru {new_code} untuk memulai lagi."
            ),
            "error",
        )
        return redirect(url_for("career.index"))

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
