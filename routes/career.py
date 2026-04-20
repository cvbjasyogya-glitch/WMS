import hashlib
from datetime import datetime, timedelta

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

from database import get_db
from services.career_service import (
    create_public_account_request,
    assign_candidate_assessment_code,
    decode_assessment_answers,
    encode_assessment_answers,
    ensure_candidate_assessment_code,
    ensure_career_schema,
    extract_inserted_row_id,
    find_duplicate_public_application,
    normalize_assessment_code,
    normalize_assessment_duration_minutes,
    normalize_candidate_email,
    normalize_candidate_identity_name,
    normalize_candidate_phone,
    normalize_candidate_portfolio_url,
    normalize_career_assessment_status,
    normalize_career_application_channel,
    normalize_career_employment_type,
    save_career_resume,
    score_assessment_questions,
)
from services.notification_service import send_email


career_bp = Blueprint("career", __name__)
CAREER_ASSESSMENT_MAX_VIOLATIONS = 3


def _get_career_public_company_name():
    safe_name = str(
        current_app.config.get("CAREER_PUBLIC_COMPANY_NAME")
        or "CV Berkah Jaya Abadi Sports"
    ).strip()
    return safe_name or "CV Berkah Jaya Abadi Sports"


def _get_primary_recruitment_public_host():
    recruitment_hosts = current_app.config.get("RECRUITMENT_PUBLIC_HOSTS") or []
    for host in recruitment_hosts:
        safe_host = str(host or "").strip().lstrip(".").rstrip(".")
        if safe_host:
            return safe_host
    return ""


def build_career_public_url(endpoint, **values):
    target_path = url_for(endpoint, **values)
    recruitment_host = _get_primary_recruitment_public_host()
    if not recruitment_host:
        return target_path

    current_host = str(request.host or "").strip().split(":", 1)[0].lower()
    if current_host == recruitment_host.lower():
        return target_path

    target_scheme = (
        str(current_app.config.get("CANONICAL_SCHEME") or request.scheme or "https")
        .strip()
        .lower()
        or "https"
    )
    return f"{target_scheme}://{recruitment_host}{target_path}"


@career_bp.before_request
def enforce_career_public_host():
    recruitment_host = _get_primary_recruitment_public_host()
    if not recruitment_host:
        return

    current_host = str(request.host or "").strip().split(":", 1)[0].lower()
    if current_host == recruitment_host.lower():
        return

    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        return

    target_scheme = (
        str(current_app.config.get("CANONICAL_SCHEME") or request.scheme or "https")
        .strip()
        .lower()
        or "https"
    )
    target_path = request.full_path if request.query_string else request.path
    if target_path.endswith("?"):
        target_path = target_path[:-1]
    if not target_path.startswith("/"):
        target_path = f"/{target_path}"
    return redirect(f"{target_scheme}://{recruitment_host}{target_path or '/'}", code=302)


def _career_public_signin_url():
    return build_career_public_url("career.signin_page")


def _career_public_register_url():
    return build_career_public_url("career.signin_page", flow="signup")


def _redirect_career_public(endpoint, **values):
    return redirect(build_career_public_url(endpoint, **values))


def _resolve_career_public_media_url(configured_value, default_static_filename):
    safe_value = str(configured_value or "").strip()
    if not safe_value:
        safe_value = str(default_static_filename or "").strip()
    if safe_value.startswith(("http://", "https://", "data:", "/")):
        return safe_value
    return url_for("static", filename=safe_value)


@career_bp.context_processor
def inject_career_public_context():
    career_company_name = _get_career_public_company_name()
    return {
        "career_notice_text": str(
            current_app.config.get("CAREER_PUBLIC_NOTICE_TEXT")
            or f"{career_company_name} tidak memungut biaya apa pun selama proses pendaftaran dan seleksi karir berlangsung."
        ).strip(),
        "career_company_name": career_company_name,
        "career_home_hero_image_url": _resolve_career_public_media_url(
            current_app.config.get("CAREER_HOME_HERO_IMAGE"),
            "brand/login-hero-crowd.jpeg",
        ),
        "career_public_signin_url": build_career_public_url("career.signin_page"),
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


def _matches_public_opening_filters(opening, query="", department="", employment_type=""):
    safe_opening = dict(opening or {})
    safe_query = str(query or "").strip().lower()
    safe_department = str(department or "").strip().lower()
    safe_type = str(employment_type or "").strip().lower()

    title_value = str(safe_opening.get("title") or "").strip().lower()
    department_value = str(safe_opening.get("department") or "").strip().lower()
    location_value = str(
        safe_opening.get("location_label") or safe_opening.get("warehouse_name") or ""
    ).strip().lower()
    type_value = str(safe_opening.get("employment_type") or "full_time").replace("_", " ").strip().lower()

    if safe_query and safe_query not in " ".join(
        value for value in [title_value, department_value, location_value, type_value] if value
    ):
        return False
    if safe_department and department_value != safe_department:
        return False
    if safe_type and type_value != safe_type:
        return False
    return True


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


def _parse_career_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    safe_value = str(value or "").strip()
    if not safe_value:
        return None
    normalized = safe_value.replace("T", " ").replace("Z", "")[:19]
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _format_career_datetime_display(value):
    parsed = _parse_career_datetime(value)
    if not parsed:
        return "Tidak dibatasi"
    return parsed.strftime("%d/%m/%Y %H:%M")


def _format_career_datetime_iso(value):
    parsed = _parse_career_datetime(value)
    if not parsed:
        return ""
    return parsed.isoformat(timespec="seconds")


def _get_candidate_assessment_duration_minutes(candidate):
    return normalize_assessment_duration_minutes((candidate or {}).get("assessment_duration_minutes"))


def _get_candidate_assessment_deadline(candidate):
    started_at = _parse_career_datetime((candidate or {}).get("assessment_started_at"))
    duration_minutes = _get_candidate_assessment_duration_minutes(candidate)
    if not started_at or duration_minutes <= 0:
        return None
    return started_at + timedelta(minutes=duration_minutes)


def _get_candidate_assessment_remaining_seconds(candidate, now_dt=None):
    deadline = _get_candidate_assessment_deadline(candidate)
    if not deadline:
        return None
    current_dt = now_dt or datetime.now()
    return max(int((deadline - current_dt).total_seconds()), 0)


def _is_candidate_assessment_code_expired(candidate, now_dt=None):
    safe_candidate = dict(candidate or {})
    if safe_candidate.get("assessment_started_at"):
        return False
    expires_at = _parse_career_datetime(safe_candidate.get("assessment_expires_at"))
    if not expires_at:
        return False
    current_dt = now_dt or datetime.now()
    return current_dt > expires_at


def _is_candidate_assessment_duration_expired(candidate, now_dt=None, grace_seconds=5):
    deadline = _get_candidate_assessment_deadline(candidate)
    if not deadline:
        return False
    current_dt = now_dt or datetime.now()
    return current_dt > (deadline + timedelta(seconds=max(int(grace_seconds or 0), 0)))


def _parse_public_opening_filters():
    initial_query = (request.args.get("q") or "").strip()
    initial_department = (request.args.get("department") or "").strip().lower()
    initial_type_filter = (request.args.get("type") or "").strip().lower()
    selected_warehouse = request.args.get("warehouse", "").strip()
    try:
        selected_warehouse_id = int(selected_warehouse) if selected_warehouse else None
    except ValueError:
        selected_warehouse_id = None
    return initial_query, initial_department, initial_type_filter, selected_warehouse_id


def _build_public_opening_summary_payload(openings):
    safe_openings = [dict(opening) for opening in (openings or [])]
    department_counts = {}
    location_counts = {}
    employment_type_counts = {}

    for opening in safe_openings:
        department = str(opening.get("department") or "").strip()
        location_label = str(opening.get("location_label") or opening.get("warehouse_name") or "").strip()
        employment_type = normalize_career_employment_type(opening.get("employment_type"))

        if department:
            department_counts[department] = department_counts.get(department, 0) + 1
        if location_label:
            location_counts[location_label] = location_counts.get(location_label, 0) + 1
        employment_type_counts[employment_type] = employment_type_counts.get(employment_type, 0) + 1

    featured_openings = []
    for opening in safe_openings[:6]:
        featured_openings.append(
            {
                "id": int(opening.get("id") or 0),
                "title": str(opening.get("title") or "").strip(),
                "department": str(opening.get("department") or "").strip(),
                "location_label": str(opening.get("location_label") or opening.get("warehouse_name") or "").strip(),
                "employment_type": normalize_career_employment_type(opening.get("employment_type")),
                "detail_url": build_career_public_url(
                    "career.opening_detail",
                    opening_id=int(opening.get("id") or 0),
                ),
            }
        )

    return {
        "openings_total": len(safe_openings),
        "department_total": len(department_counts),
        "location_total": len(location_counts),
        "employment_type_total": len(employment_type_counts),
        "departments": [
            {"label": label, "count": count}
            for label, count in sorted(department_counts.items(), key=lambda item: item[0].lower())
        ],
        "locations": [
            {"label": label, "count": count}
            for label, count in sorted(location_counts.items(), key=lambda item: item[0].lower())
        ],
        "employment_types": [
            {
                "value": value,
                "label": value.replace("_", " ").title(),
                "count": count,
            }
            for value, count in sorted(employment_type_counts.items(), key=lambda item: item[0])
        ],
        "featured_openings": featured_openings,
    }


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

    initial_query, initial_department, initial_type_filter, selected_warehouse_id = _parse_public_opening_filters()

    openings = _fetch_public_openings(db, selected_warehouse_id)
    openings = [
        opening
        for opening in openings
        if _matches_public_opening_filters(
            opening,
            query=initial_query,
            department=initial_department,
            employment_type=initial_type_filter,
        )
    ]
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
        initial_query=initial_query,
        initial_department=initial_department,
        initial_type_filter=initial_type_filter,
        latest_assessment_code=assessment_code,
        latest_candidate=latest_candidate,
    )


@career_bp.route("/karir/summary")
def public_summary():
    db = get_db()
    ensure_career_schema(db)

    initial_query, initial_department, initial_type_filter, selected_warehouse_id = _parse_public_opening_filters()
    openings = _fetch_public_openings(db, selected_warehouse_id)
    openings = [
        opening
        for opening in openings
        if _matches_public_opening_filters(
            opening,
            query=initial_query,
            department=initial_department,
            employment_type=initial_type_filter,
        )
    ]
    return jsonify(
        {
            "ok": True,
            "summary": _build_public_opening_summary_payload(openings),
            "filters": {
                "q": initial_query,
                "department": initial_department,
                "type": initial_type_filter,
                "warehouse_id": selected_warehouse_id,
            },
        }
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
        signin_url=_career_public_signin_url(),
    )


@career_bp.route("/help")
def help_page():
    db = get_db()
    ensure_career_schema(db)
    openings = _fetch_public_openings(db)
    return render_template(
        "career_help.html",
        signin_url=_career_public_signin_url(),
        register_url=_career_public_register_url(),
        opening_count=len(openings),
    )


@career_bp.route("/signin")
def signin_page():
    db = get_db()
    ensure_career_schema(db)
    openings = _fetch_public_openings(db)
    flow = str(request.args.get("flow") or "signin").strip().lower()
    if flow not in {"signin", "signup"}:
        flow = "signin"
    registered = str(request.args.get("registered") or "").strip() in {"1", "true", "yes"}
    email = (request.args.get("email") or "").strip()
    registration_delivery = str(request.args.get("mail") or "sent").strip().lower()
    if registration_delivery not in {"sent", "pending"}:
        registration_delivery = "sent"
    return render_template(
        "career_signin.html",
        signin_url=_career_public_signin_url(),
        register_url=_career_public_register_url(),
        active_flow=flow,
        registration_success=registered,
        registration_email=email,
        registration_delivery=registration_delivery,
        opening_count=len(openings),
    )


@career_bp.route("/signin/auth", methods=["POST"])
def signin_submit():
    email = (request.form.get("email") or "").strip()
    password = (request.form.get("password") or "").strip()
    if not email or not password:
        flash("Email dan kata sandi wajib diisi.", "error")
        return _redirect_career_public("career.signin_page", flow="signin")

    flash(
        "Login kandidat publik sedang diaktifkan bertahap. Jika Anda sudah melamar, gunakan kode tes 5 digit atau hubungi HR.",
        "info",
    )
    return _redirect_career_public("career.signin_page", flow="signin")


@career_bp.route("/signin/register-request", methods=["POST"])
def signin_register_request():
    candidate_name = (request.form.get("candidate_name") or "").strip()
    email = (request.form.get("email") or "").strip()
    if not candidate_name or not email:
        flash("Nama lengkap dan email wajib diisi untuk mendaftarkan akun.", "error")
        return _redirect_career_public("career.signin_page", flow="signup")
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
        return _redirect_career_public("career.signin_page", flow="signup")

    career_company_name = _get_career_public_company_name()
    email_subject = f"Permintaan akun karir {career_company_name} diterima"
    email_body = (
        f"Halo {candidate_name},\n\n"
        f"Permintaan akun Anda untuk portal karir {career_company_name} sudah kami terima.\n"
        "Tim HR akan meninjau email ini sebelum akses kandidat publik diaktifkan.\n\n"
        "Sambil menunggu, Anda tetap bisa melihat lowongan aktif dan mengerjakan tes dengan kode 5 digit jika sudah diberikan HR.\n\n"
        f"Salam,\n{career_company_name}"
    )
    registration_delivery = "sent"
    try:
        email_result = send_email(email, email_subject, email_body)
        if email_result is not True:
            registration_delivery = "pending"
            current_app.logger.warning(
                "Career signup email was not sent for %s. Check SMTP/Brevo configuration.",
                email,
            )
    except Exception:
        registration_delivery = "pending"
        current_app.logger.exception("Career signup email failed for %s", email)
    return _redirect_career_public(
        "career.signin_page",
        flow="signup",
        registered=1,
        email=email,
        mail=registration_delivery,
    )


@career_bp.route("/karir/lowongan/<int:opening_id>")
def opening_detail(opening_id):
    db = get_db()
    ensure_career_schema(db)

    opening = _fetch_public_opening_by_id(db, opening_id)
    if not opening:
        flash("Lowongan yang dipilih tidak tersedia lagi.", "error")
        return redirect(build_career_public_url("career.index"))

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
        return redirect(build_career_public_url("career.index"))

    raw_candidate_name = request.form.get("candidate_name")
    raw_phone = request.form.get("phone")
    raw_email = request.form.get("email")
    raw_portfolio_url = request.form.get("portfolio_url")

    candidate_name = normalize_candidate_identity_name(raw_candidate_name)
    phone = normalize_candidate_phone(raw_phone)
    email = normalize_candidate_email(raw_email)
    portfolio_url = normalize_candidate_portfolio_url(raw_portfolio_url)
    note = (request.form.get("note") or "").strip()
    resume_file = request.files.get("resume_file")

    if not candidate_name or (not phone and not email):
        flash("Nama kandidat dan minimal satu kontak wajib diisi.", "error")
        return redirect(build_career_public_url("career.opening_detail", opening_id=opening["id"]))
    if (raw_email or "").strip() and not email:
        flash("Email kandidat tidak valid.", "error")
        return redirect(build_career_public_url("career.opening_detail", opening_id=opening["id"]))
    if (raw_phone or "").strip() and not phone:
        flash("Nomor telepon kandidat tidak valid.", "error")
        return redirect(build_career_public_url("career.opening_detail", opening_id=opening["id"]))
    if (raw_portfolio_url or "").strip() and not portfolio_url:
        flash("Link portofolio harus berupa URL http:// atau https:// yang valid.", "error")
        return redirect(build_career_public_url("career.opening_detail", opening_id=opening["id"]))

    duplicate_candidate = find_duplicate_public_application(
        db,
        opening["id"],
        email=email,
        phone=phone,
    )
    if duplicate_candidate:
        existing_code = ensure_candidate_assessment_code(
            db,
            int(duplicate_candidate["id"]),
            duplicate_candidate.get("assessment_code") or "",
        )
        db.commit()
        flash(
            "Lamaran untuk lowongan ini sudah pernah kami terima. Kami tampilkan kembali kode tes kandidat yang sama.",
            "info",
        )
        return redirect(
            build_career_public_url(
                "career.opening_detail",
                opening_id=opening["id"],
                code=existing_code,
            )
        )

    try:
        resume_original_name, resume_path = save_career_resume(resume_file)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(build_career_public_url("career.opening_detail", opening_id=opening["id"]))

    if not resume_path:
        flash("CV wajib diunggah agar HR bisa review lamaran.", "error")
        return redirect(build_career_public_url("career.opening_detail", opening_id=opening["id"]))

    insert_cursor = db.execute(
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
    created_candidate_id = extract_inserted_row_id(insert_cursor)
    created_candidate = None
    if created_candidate_id > 0:
        created_candidate = db.execute(
            """
            SELECT id, assessment_code
            FROM recruitment_candidates
            WHERE id=?
            LIMIT 1
            """,
            (created_candidate_id,),
        ).fetchone()
    if created_candidate is None:
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
        (created_candidate["assessment_code"] or "") if created_candidate else "",
    )
    db.commit()

    flash(
        "Lamaran berhasil dikirim. Simpan kode tes dari pop-up yang muncul setelah halaman terbuka.",
        "success",
    )
    return redirect(build_career_public_url("career.opening_detail", opening_id=opening["id"], code=assessment_code))


@career_bp.route("/karir/tes")
def assessment():
    db = get_db()
    ensure_career_schema(db)
    current_dt = datetime.now()
    assessment_code = normalize_assessment_code(request.args.get("code"))
    if not assessment_code:
        flash("Masukkan kode tes 5 digit yang valid.", "error")
        return redirect(build_career_public_url("career.index"))

    candidate = _fetch_candidate_by_assessment_code(db, assessment_code)
    if not candidate:
        flash("Kode tes tidak ditemukan.", "error")
        return redirect(build_career_public_url("career.index"))

    questions = _fetch_public_assessment_questions(db, candidate.get("warehouse_id"), shuffle_seed=assessment_code)
    if not questions:
        flash("Soal tes belum disiapkan HR untuk posisi ini.", "error")
        return redirect(build_career_public_url("career.index", code=assessment_code))

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
            assessment_duration_minutes=_get_candidate_assessment_duration_minutes(candidate),
            assessment_deadline_iso=_format_career_datetime_iso(_get_candidate_assessment_deadline(candidate)),
            assessment_remaining_seconds=_get_candidate_assessment_remaining_seconds(candidate, current_dt),
            assessment_code_expires_label=_format_career_datetime_display(candidate.get("assessment_expires_at")),
        )
    if _is_candidate_assessment_code_expired(candidate, current_dt):
        flash("Kode tes ini sudah melewati masa berlaku. Silakan hubungi HR untuk kode baru.", "error")
        return redirect(build_career_public_url("career.index"))

    answers = decode_assessment_answers(candidate.get("assessment_answers_json"))
    if candidate.get("assessment_status") != "started":
        started_at_value = current_dt.strftime("%Y-%m-%d %H:%M:%S")
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
        candidate["assessment_started_at"] = candidate.get("assessment_started_at") or started_at_value

    if _is_candidate_assessment_duration_expired(candidate, current_dt):
        flash("Waktu pengerjaan tes sudah habis. Silakan hubungi HR untuk tindak lanjut berikutnya.", "error")
        return redirect(build_career_public_url("career.index"))

    return render_template(
        "career_assessment.html",
        candidate=candidate,
        questions=questions,
        assessment_code=assessment_code,
        assessment_state="active",
        existing_answers=answers,
        violation_count=int(candidate.get("assessment_violation_count") or 0),
        max_violation_count=CAREER_ASSESSMENT_MAX_VIOLATIONS,
        assessment_duration_minutes=_get_candidate_assessment_duration_minutes(candidate),
        assessment_deadline_iso=_format_career_datetime_iso(_get_candidate_assessment_deadline(candidate)),
        assessment_remaining_seconds=_get_candidate_assessment_remaining_seconds(candidate, current_dt),
        assessment_code_expires_label=_format_career_datetime_display(candidate.get("assessment_expires_at")),
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
                "redirect_url": build_career_public_url("career.index"),
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
    current_dt = datetime.now()
    assessment_code = normalize_assessment_code(request.form.get("assessment_code"))
    candidate = _fetch_candidate_by_assessment_code(db, assessment_code)
    if not candidate:
        flash("Kode tes tidak ditemukan.", "error")
        return redirect(build_career_public_url("career.index"))

    questions = _fetch_public_assessment_questions(db, candidate.get("warehouse_id"), shuffle_seed=assessment_code)
    if not questions:
        flash("Soal tes belum tersedia.", "error")
        return redirect(build_career_public_url("career.index", code=assessment_code))

    if candidate.get("assessment_status") in {"submitted", "reviewed"}:
        flash("Assessment ini sudah selesai dan tidak bisa dikirim ulang.", "info")
        return redirect(build_career_public_url("career.assessment", code=assessment_code))
    if _is_candidate_assessment_code_expired(candidate, current_dt):
        flash("Kode tes ini sudah melewati masa berlaku. Silakan hubungi HR untuk kode baru.", "error")
        return redirect(build_career_public_url("career.index"))
    if _is_candidate_assessment_duration_expired(candidate, current_dt):
        flash("Waktu pengerjaan tes sudah habis dan jawaban tidak bisa dikirim ulang.", "error")
        return redirect(build_career_public_url("career.index"))

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
        return redirect(build_career_public_url("career.index"))

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
    return redirect(build_career_public_url("career.assessment", code=assessment_code))
