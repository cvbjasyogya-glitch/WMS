import json
import hashlib
import os
import re
import shutil
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from database import get_db
from services.career_service import (
    CAREER_RESUME_EXTENSIONS,
    activate_career_public_account,
    create_public_account_request,
    decode_career_public_profile_payload,
    encode_recruitment_homebase_ids,
    get_career_public_account_by_email,
    get_career_public_account_by_id,
    get_career_public_profile_sections,
    get_career_public_saved_opening_ids,
    get_career_public_account_by_verification_token,
    issue_career_public_account_verification,
    mark_public_account_request_status_by_email,
    assign_candidate_assessment_code,
    decode_assessment_answers,
    encode_assessment_answers,
    extract_inserted_row_id,
    ensure_career_schema,
    find_duplicate_public_application,
    normalize_assessment_code,
    normalize_assessment_duration_minutes,
    normalize_candidate_email,
    normalize_candidate_identity_name,
    normalize_candidate_phone,
    normalize_candidate_portfolio_url,
    normalize_career_public_account_status,
    normalize_career_public_profile_section_key,
    normalize_career_assessment_status,
    normalize_career_application_channel,
    normalize_career_employment_type,
    build_career_resume_path,
    build_recruitment_candidate_intake_path,
    build_recruitment_candidate_intake_relative_folder,
    build_sms_storage_absolute_path,
    build_sms_user_storage_root,
    save_career_resume,
    score_assessment_questions,
    set_career_public_saved_opening_state,
    touch_career_public_account_login,
    update_career_public_account_password_hash,
    upsert_career_public_account,
    upsert_career_public_profile_section,
)
from services.notification_service import send_email


career_bp = Blueprint("career", __name__)
CAREER_ASSESSMENT_MAX_VIOLATIONS = 3
PUBLIC_CAREER_SITE_DISPLAY = {
    "mega": {
        "unit_label": "Mega Sports Seturan",
        "area_label": "Sleman",
    },
    "mataram": {
        "unit_label": "Mataram Sports Yogyakarta",
        "area_label": "Yogyakarta",
    },
}
CAREER_PROFILE_SECTION_DEFINITIONS = [
    {
        "key": "personal",
        "label": "Pribadi",
        "title": "Data Pribadi",
        "empty_label": "Harus dilengkapi",
        "summary": "Lengkapi identitas dasar, data KTP, domisili, dan kontak aktif agar HR lebih mudah membaca profil kandidat Anda.",
    },
    {
        "key": "family",
        "label": "Keluarga",
        "title": "Data Keluarga",
        "empty_label": "Harus dilengkapi",
        "summary": "Tambahkan kontak keluarga atau pihak yang bisa dihubungi saat dibutuhkan untuk verifikasi lanjutan.",
    },
    {
        "key": "education",
        "label": "Pendidikan",
        "title": "Riwayat Pendidikan",
        "empty_label": "Harus dilengkapi",
        "summary": "Cantumkan sekolah, jurusan, dan ringkasan pendidikan formal yang paling relevan dengan posisi pilihan Anda.",
    },
    {
        "key": "experience",
        "label": "Pengalaman",
        "title": "Pengalaman Kerja",
        "empty_label": "Lebih baik dilengkapi",
        "summary": "Jelaskan pengalaman kerja, magang, freelance, atau proyek yang pernah Anda jalankan.",
    },
    {
        "key": "skills",
        "label": "Keterampilan",
        "title": "Keterampilan",
        "empty_label": "Lebih baik dilengkapi",
        "summary": "Masukkan keterampilan utama, tools, dan sertifikasi yang ingin Anda tonjolkan ke tim rekrutmen.",
    },
    {
        "key": "organization",
        "label": "Organisasi",
        "title": "Pengalaman Organisasi",
        "empty_label": "Lebih baik dilengkapi",
        "summary": "Isi pengalaman organisasi, volunteer, atau kepanitiaan yang menunjukkan kepemimpinan dan kolaborasi.",
    },
    {
        "key": "training",
        "label": "Training",
        "title": "Training & Workshop",
        "empty_label": "Lebih baik dilengkapi",
        "summary": "Sebutkan pelatihan, workshop, dan pembelajaran nonformal yang pernah Anda ikuti.",
    },
    {
        "key": "achievement",
        "label": "Prestasi",
        "title": "Prestasi",
        "empty_label": "Lebih baik dilengkapi",
        "summary": "Tampilkan pencapaian akademik, profesional, atau penghargaan yang relevan dengan peran yang Anda incar.",
    },
    {
        "key": "language",
        "label": "Bahasa",
        "title": "Kemampuan Bahasa",
        "empty_label": "Lebih baik dilengkapi",
        "summary": "Jelaskan bahasa yang Anda kuasai beserta tingkat kemampuan yang Anda miliki.",
    },
    {
        "key": "passion",
        "label": "Passion",
        "title": "Passion & Minat Karier",
        "empty_label": "Lebih baik dilengkapi",
        "summary": "Ceritakan bidang yang paling Anda minati dan peran seperti apa yang paling cocok dengan karakter Anda.",
    },
    {
        "key": "additional",
        "label": "Info Lain",
        "title": "Informasi Tambahan",
        "empty_label": "Harus dilengkapi",
        "summary": "Tambahkan domisili, preferensi penempatan, ekspektasi gaji, dan catatan lain yang perlu diketahui HR.",
    },
    {
        "key": "documents",
        "label": "Upload Berkas",
        "title": "Upload Berkas Pendukung",
        "empty_label": "Harus dilengkapi",
        "summary": "Unggah scan KTP, CV / Resume, ijazah terakhir, dan dokumen pendukung lain agar profil kandidat siap diproses HR.",
    },
]
CAREER_PROFILE_SECTION_KEYS = {section["key"] for section in CAREER_PROFILE_SECTION_DEFINITIONS}
CAREER_PUBLIC_MEDIA_EXTENSIONS = {
    "photo": {".jpg", ".jpeg", ".png", ".webp"},
    "document": {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"},
}
CAREER_PUBLIC_MEDIA_LIMITS = {
    "photo": 2 * 1024 * 1024,
    "document": 5 * 1024 * 1024,
}
CAREER_PROFILE_RELIGION_OPTIONS = [
    ("islam", "Islam"),
    ("kristen", "Kristen"),
    ("katolik", "Katolik"),
    ("hindu", "Hindu"),
    ("buddha", "Buddha"),
    ("konghucu", "Konghucu"),
    ("other", "Lainnya"),
]
CAREER_PROFILE_GENDER_OPTIONS = [
    ("male", "Laki-laki"),
    ("female", "Perempuan"),
]
CAREER_PROFILE_MARITAL_STATUS_OPTIONS = [
    ("single", "Lajang"),
    ("married", "Menikah"),
    ("divorced", "Cerai"),
    ("other", "Lainnya"),
]
CAREER_PROFILE_DOCUMENT_DEFINITIONS = [
    {"key": "ktp_scan", "label": "Scan KTP", "required": True},
    {"key": "cv_resume", "label": "CV / Resume", "required": True},
    {"key": "last_diploma", "label": "Ijazah Terakhir", "required": True},
    {"key": "npwp_scan", "label": "Scan NPWP", "required": False},
    {"key": "transcript", "label": "Transkrip Nilai", "required": False},
    {"key": "certificate", "label": "Sertifikat Pendukung", "required": False},
    {"key": "other", "label": "Dokumen Lain", "required": False},
]
CAREER_PROFILE_DOCUMENT_TYPE_MAP = {
    item["key"]: item for item in CAREER_PROFILE_DOCUMENT_DEFINITIONS
}
CAREER_PROFILE_REQUIRED_DOCUMENT_TYPES = {
    item["key"] for item in CAREER_PROFILE_DOCUMENT_DEFINITIONS if item.get("required")
}
CAREER_PROFILE_REQUIRED_GATE_SECTION_KEYS = ("personal", "documents")


def _get_career_public_company_name():
    safe_name = str(
        current_app.config.get("CAREER_PUBLIC_COMPANY_NAME")
        or "CV Berkah Jaya Abadi Sports"
    ).strip()
    return safe_name or "CV Berkah Jaya Abadi Sports"


def _canonicalize_public_career_label(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def _resolve_public_career_site_key(*values):
    for value in values:
        canonical_value = _canonicalize_public_career_label(value)
        if not canonical_value:
            continue
        if "mega" in canonical_value:
            return "mega"
        if "mataram" in canonical_value:
            return "mataram"
    return ""


def _should_override_public_career_area(raw_area_label, site_key):
    canonical_area = _canonicalize_public_career_label(raw_area_label)
    if not canonical_area:
        return True

    if site_key == "mega":
        return canonical_area.startswith(
            ("mega", "gudang mega", "homebase mega", "mega sports", "seturan")
        ) or canonical_area in {"sleman", "yogyakarta", "yogyakarta wfo"}

    if site_key == "mataram":
        return canonical_area.startswith(
            ("mataram", "gudang mataram", "homebase mataram", "mataram sports")
        ) or canonical_area in {"yogyakarta", "yogyakarta wfo"}

    return False


def _get_public_career_display_labels(warehouse_name="", location_label=""):
    safe_warehouse_name = str(warehouse_name or "").strip()
    safe_location_label = str(location_label or "").strip()
    site_key = _resolve_public_career_site_key(safe_warehouse_name, safe_location_label)
    profile = PUBLIC_CAREER_SITE_DISPLAY.get(site_key) or {}

    unit_label = profile.get("unit_label") or safe_warehouse_name or _get_career_public_company_name()
    area_label = safe_location_label
    if profile and _should_override_public_career_area(safe_location_label, site_key):
        area_label = profile.get("area_label") or area_label

    if not area_label:
        area_label = profile.get("area_label") or "Penempatan fleksibel"

    return {
        "site_key": site_key,
        "unit_label": unit_label,
        "area_label": area_label,
    }


def _annotate_public_opening_display(opening):
    safe_opening = dict(opening or {})
    display_labels = _get_public_career_display_labels(
        safe_opening.get("warehouse_name"),
        safe_opening.get("location_label"),
    )
    safe_opening["warehouse_name_display"] = display_labels["unit_label"]
    safe_opening["location_label_display"] = display_labels["area_label"]
    safe_opening["public_site_key"] = display_labels["site_key"]
    return safe_opening


def _annotate_public_candidate_display(candidate):
    safe_candidate = dict(candidate or {})
    display_labels = _get_public_career_display_labels(
        safe_candidate.get("warehouse_name"),
        safe_candidate.get("location_label"),
    )
    safe_candidate["warehouse_name_display"] = display_labels["unit_label"]
    safe_candidate["location_label_display"] = display_labels["area_label"]
    safe_candidate["public_site_key"] = display_labels["site_key"]
    return safe_candidate


def _annotate_public_warehouse_display(warehouse):
    safe_warehouse = dict(warehouse or {})
    display_labels = _get_public_career_display_labels(
        safe_warehouse.get("name"),
        safe_warehouse.get("name"),
    )
    safe_warehouse["display_name"] = display_labels["area_label"]
    safe_warehouse["unit_display_name"] = display_labels["unit_label"]
    return safe_warehouse


def _get_primary_recruitment_public_host():
    recruitment_hosts = current_app.config.get("RECRUITMENT_PUBLIC_HOSTS") or []
    for host in recruitment_hosts:
        safe_host = str(host or "").strip().lstrip(".").rstrip(".")
        if safe_host:
            return safe_host
    return ""


def build_career_public_url(endpoint, force_external=False, **values):
    target_path = url_for(endpoint, **values)
    recruitment_host = _get_primary_recruitment_public_host()
    current_host = str(request.host or "").strip().split(":", 1)[0].lower()
    if not recruitment_host and not force_external:
        return target_path

    if recruitment_host and current_host == recruitment_host.lower() and not force_external:
        return target_path

    target_scheme = (
        str(current_app.config.get("CANONICAL_SCHEME") or request.scheme or "https")
        .strip()
        .lower()
        or "https"
    )
    target_host = recruitment_host or current_host
    if not target_host:
        return target_path
    return f"{target_scheme}://{target_host}{target_path}"


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


def _redirect_career_public_with_next(endpoint, next_target=None, **values):
    if next_target:
        values["next"] = next_target
    return _redirect_career_public(endpoint, **values)


def _safe_career_public_next_target(raw_target):
    candidate = str(raw_target or "").strip()
    if not candidate:
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return None
    if not candidate.startswith("/") or candidate.startswith("//"):
        return None
    return candidate


def _get_career_public_verification_ttl_hours():
    try:
        ttl_hours = int(current_app.config.get("CAREER_PUBLIC_VERIFICATION_TTL_HOURS", 24))
    except (TypeError, ValueError):
        ttl_hours = 24
    return max(ttl_hours, 1)


def _clear_career_public_session():
    for key in (
        "career_public_account_id",
        "career_public_account_email",
        "career_public_account_name",
        "career_public_signed_in_at",
    ):
        session.pop(key, None)


def _set_career_public_session(account):
    safe_account = dict(account or {})
    _clear_career_public_session()
    session["career_public_account_id"] = safe_account.get("id")
    session["career_public_account_email"] = safe_account.get("email")
    session["career_public_account_name"] = safe_account.get("full_name")
    session["career_public_signed_in_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get_current_career_public_account(db=None):
    account_id = session.get("career_public_account_id")
    if not account_id:
        return None
    local_db = db or get_db()
    ensure_career_schema(local_db)
    account = get_career_public_account_by_id(local_db, account_id)
    if not account:
        _clear_career_public_session()
        return None
    if normalize_career_public_account_status(account.get("status")) != "active":
        _clear_career_public_session()
        return None
    return account


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
    active_account = _get_current_career_public_account()
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
        "career_public_authenticated": active_account is not None,
        "career_public_account_name": active_account.get("full_name") if active_account else "",
        "career_public_account_email": active_account.get("email") if active_account else "",
    }


def _resolve_career_public_post_auth_target(next_target=None):
    safe_target = _safe_career_public_next_target(next_target)
    active_account = _get_current_career_public_account()
    if active_account:
        profile_gate = _get_candidate_profile_gate(get_db(), active_account)
        if not profile_gate["is_ready"]:
            return build_career_public_url(
                "career.profile_page",
                section=profile_gate["next_section_key"],
            )
    public_jobs_path = url_for("career.index")
    signin_path = url_for("career.signin_page")
    if not safe_target or safe_target in {public_jobs_path, signin_path}:
        return build_career_public_url("career.portal_page")
    return safe_target


def _get_career_public_request_path():
    target_path = request.full_path if request.query_string else request.path
    if target_path.endswith("?"):
        target_path = target_path[:-1]
    if not target_path.startswith("/"):
        target_path = f"/{target_path}"
    return _safe_career_public_next_target(target_path) or "/karir"


def _redirect_career_public_signin(next_target=None, flow="signin"):
    return _redirect_career_public_with_next(
        "career.signin_page",
        flow=flow,
        next_target=next_target or _get_career_public_request_path(),
    )


def _require_career_public_account(db=None):
    account = _get_current_career_public_account(db)
    if account:
        return account, None
    flash("Silakan masuk ke akun kandidat terlebih dahulu.", "error")
    return None, _redirect_career_public_signin()


def _normalize_profile_text(value):
    return " ".join(str(value or "").strip().split())


def _normalize_profile_textarea(value):
    return str(value or "").replace("\r\n", "\n").strip()


def _normalize_profile_date(value):
    safe_value = str(value or "").strip()
    if not safe_value:
        return ""
    try:
        return datetime.strptime(safe_value[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _normalize_profile_document_type(value):
    safe_value = str(value or "").strip().lower()
    return safe_value if safe_value in CAREER_PROFILE_DOCUMENT_TYPE_MAP else ""


def _resolve_profile_document_label(document_type, custom_label=""):
    safe_type = _normalize_profile_document_type(document_type)
    safe_custom_label = _normalize_profile_text(custom_label)
    if safe_type == "other" and safe_custom_label:
        return safe_custom_label
    return (
        (CAREER_PROFILE_DOCUMENT_TYPE_MAP.get(safe_type) or {}).get("label")
        or safe_custom_label
        or "Dokumen"
    )


def _guess_profile_document_type_from_filename(filename):
    safe_name = secure_filename(filename or "").lower()
    if not safe_name:
        return "other"

    if "ktp" in safe_name:
        return "ktp_scan"
    if "npwp" in safe_name:
        return "npwp_scan"
    if "ijazah" in safe_name or "diploma" in safe_name:
        return "last_diploma"
    if "transkrip" in safe_name or "transcript" in safe_name or "nilai" in safe_name:
        return "transcript"
    if "sertifikat" in safe_name or "certificate" in safe_name or "sertifikasi" in safe_name:
        return "certificate"
    if "resume" in safe_name or re.search(r"(^|[-_ ])cv($|[-_ .])", safe_name) or "curriculum" in safe_name:
        return "cv_resume"
    return "other"


def _normalize_career_profile_section_payload(section_key, form_data, *, existing_payload=None):
    safe_key = normalize_career_public_profile_section_key(section_key)
    current_payload = dict(existing_payload or {})
    if not safe_key:
        return {}

    if safe_key == "personal":
        photo_path = current_payload.get("photo_path") or ""
        gender_value = str(form_data.get("gender") or "").strip().lower()
        marital_status_value = str(form_data.get("marital_status") or "").strip().lower()
        religion_value = str(form_data.get("religion") or "").strip().lower()
        return {
            "full_name": normalize_candidate_identity_name(form_data.get("full_name")),
            "email": normalize_candidate_email(form_data.get("email")),
            "phone": normalize_candidate_phone(form_data.get("phone")),
            "ktp_number": "".join(ch for ch in str(form_data.get("ktp_number") or "") if ch.isdigit())[:24],
            "npwp_number": "".join(ch for ch in str(form_data.get("npwp_number") or "") if ch.isdigit())[:24],
            "linkedin_url": normalize_candidate_portfolio_url(form_data.get("linkedin_url")),
            "instagram_handle": _normalize_profile_text(form_data.get("instagram_handle")).lstrip("@"),
            "birth_place": _normalize_profile_text(form_data.get("birth_place")),
            "birth_date": _normalize_profile_date(form_data.get("birth_date")),
            "gender": gender_value if gender_value in {value for value, _ in CAREER_PROFILE_GENDER_OPTIONS} else "",
            "marital_status": (
                marital_status_value
                if marital_status_value in {value for value, _ in CAREER_PROFILE_MARITAL_STATUS_OPTIONS}
                else ""
            ),
            "religion": (
                religion_value
                if religion_value in {value for value, _ in CAREER_PROFILE_RELIGION_OPTIONS}
                else ""
            ),
            "ktp_province": _normalize_profile_text(form_data.get("ktp_province")),
            "ktp_city": _normalize_profile_text(form_data.get("ktp_city")),
            "ktp_address": _normalize_profile_textarea(form_data.get("ktp_address")),
            "ktp_postal_code": "".join(ch for ch in str(form_data.get("ktp_postal_code") or "") if ch.isdigit())[:10],
            "domicile_city": _normalize_profile_text(form_data.get("domicile_city")),
            "domicile_address": _normalize_profile_textarea(form_data.get("domicile_address")),
            "address": _normalize_profile_textarea(form_data.get("address") or form_data.get("ktp_address")),
            "city": _normalize_profile_text(form_data.get("city") or form_data.get("ktp_city")),
            "province": _normalize_profile_text(form_data.get("province") or form_data.get("ktp_province")),
            "summary": _normalize_profile_textarea(form_data.get("summary")),
            "photo_path": photo_path,
        }

    if safe_key == "family":
        return {
            "contact_name": _normalize_profile_text(form_data.get("contact_name")),
            "relationship": _normalize_profile_text(form_data.get("relationship")),
            "contact_phone": normalize_candidate_phone(form_data.get("contact_phone")),
            "notes": _normalize_profile_textarea(form_data.get("notes")),
        }

    if safe_key == "skills":
        return {
            "core_skills": _normalize_profile_textarea(form_data.get("core_skills")),
            "tools": _normalize_profile_textarea(form_data.get("tools")),
            "certifications": _normalize_profile_textarea(form_data.get("certifications")),
        }

    if safe_key == "additional":
        return {
            "domicile": _normalize_profile_text(form_data.get("domicile")),
            "preferred_area": _normalize_profile_text(form_data.get("preferred_area")),
            "salary_expectation": _normalize_profile_text(form_data.get("salary_expectation")),
            "notes": _normalize_profile_textarea(form_data.get("notes")),
        }

    if safe_key == "documents":
        files = current_payload.get("files")
        if not isinstance(files, list):
            files = []
        return {"files": files}

    return {"summary": _normalize_profile_textarea(form_data.get("summary"))}


def _is_profile_payload_complete(section_key, payload, account=None):
    safe_key = normalize_career_public_profile_section_key(section_key)
    safe_payload = dict(payload or {})
    if safe_key == "personal":
        full_name = normalize_candidate_identity_name(safe_payload.get("full_name") or (account or {}).get("full_name"))
        email = normalize_candidate_email(safe_payload.get("email") or (account or {}).get("email"))
        phone = normalize_candidate_phone(safe_payload.get("phone"))
        ktp_number = "".join(ch for ch in str(safe_payload.get("ktp_number") or "") if ch.isdigit())
        linkedin_url = normalize_candidate_portfolio_url(safe_payload.get("linkedin_url"))
        instagram_handle = _normalize_profile_text(safe_payload.get("instagram_handle")).lstrip("@")
        birth_place = _normalize_profile_text(safe_payload.get("birth_place"))
        birth_date = _normalize_profile_date(safe_payload.get("birth_date"))
        gender = str(safe_payload.get("gender") or "").strip().lower()
        marital_status = str(safe_payload.get("marital_status") or "").strip().lower()
        religion = str(safe_payload.get("religion") or "").strip().lower()
        ktp_province = _normalize_profile_text(safe_payload.get("ktp_province"))
        ktp_city = _normalize_profile_text(safe_payload.get("ktp_city"))
        ktp_address = _normalize_profile_textarea(safe_payload.get("ktp_address"))
        ktp_postal_code = "".join(ch for ch in str(safe_payload.get("ktp_postal_code") or "") if ch.isdigit())
        domicile_city = _normalize_profile_text(safe_payload.get("domicile_city"))
        domicile_address = _normalize_profile_textarea(safe_payload.get("domicile_address"))
        return bool(
            full_name
            and email
            and phone
            and ktp_number
            and linkedin_url
            and instagram_handle
            and birth_place
            and birth_date
            and gender
            and marital_status
            and religion
            and ktp_province
            and ktp_city
            and ktp_address
            and ktp_postal_code
            and domicile_city
            and domicile_address
        )

    if safe_key == "family":
        return bool(
            _normalize_profile_text(safe_payload.get("contact_name"))
            and normalize_candidate_phone(safe_payload.get("contact_phone"))
        )

    if safe_key == "education":
        return bool(_normalize_profile_textarea(safe_payload.get("summary")))

    if safe_key == "additional":
        return bool(
            _normalize_profile_text(safe_payload.get("domicile"))
            and _normalize_profile_text(safe_payload.get("preferred_area"))
        )

    if safe_key == "documents":
        files = safe_payload.get("files")
        if not isinstance(files, list):
            return False
        existing_types = {
            _normalize_profile_document_type(item.get("document_type"))
            for item in files
            if isinstance(item, dict)
        }
        return CAREER_PROFILE_REQUIRED_DOCUMENT_TYPES.issubset(existing_types)

    return any(
        bool(_normalize_profile_textarea(value) if isinstance(value, str) else value)
        for value in safe_payload.values()
    )


def _build_profile_section_state(account, stored_sections):
    safe_account = dict(account or {})
    states = []
    for definition in CAREER_PROFILE_SECTION_DEFINITIONS:
        section_key = definition["key"]
        stored_state = dict((stored_sections or {}).get(section_key) or {})
        payload = dict(stored_state.get("payload") or {})
        completion_state = "complete" if _is_profile_payload_complete(section_key, payload, safe_account) else "incomplete"
        states.append(
            {
                **definition,
                "payload": payload,
                "completion_state": completion_state,
                "status_label": "Lengkap" if completion_state == "complete" else definition["empty_label"],
            }
        )
    return states


def _build_candidate_profile_gate(account, stored_sections):
    section_states = _build_profile_section_state(account, stored_sections)
    section_state_map = {item["key"]: item for item in section_states}
    missing_sections = []
    for section_key in CAREER_PROFILE_REQUIRED_GATE_SECTION_KEYS:
        section_state = section_state_map.get(section_key)
        if not section_state or section_state.get("completion_state") != "complete":
            definition = section_state or _get_profile_section_definition(section_key)
            missing_sections.append(
                {
                    "key": section_key,
                    "label": definition.get("label") or section_key.title(),
                    "title": definition.get("title") or section_key.title(),
                }
            )
    return {
        "is_ready": not missing_sections,
        "next_section_key": missing_sections[0]["key"] if missing_sections else "personal",
        "missing_sections": missing_sections,
        "missing_labels": [item["label"] for item in missing_sections],
        "missing_titles": [item["title"] for item in missing_sections],
        "section_states": section_states,
    }


def _get_candidate_profile_gate(db, account, stored_sections=None):
    safe_account = dict(account or {})
    if not safe_account:
        return _build_candidate_profile_gate({}, stored_sections or {})
    resolved_sections = (
        stored_sections
        if stored_sections is not None
        else get_career_public_profile_sections(db, safe_account.get("id"))
    )
    return _build_candidate_profile_gate(safe_account, resolved_sections)


def _redirect_candidate_back_to_profile(profile_gate, *, message=None, category="error"):
    safe_gate = dict(profile_gate or {})
    next_section_key = normalize_career_public_profile_section_key(
        safe_gate.get("next_section_key")
    ) or "personal"
    if message:
        flash(message, category)
    return redirect(build_career_public_url("career.profile_page", section=next_section_key))


def _guard_candidate_profile_completion(db, account, *, message=None, category="error"):
    profile_gate = _get_candidate_profile_gate(db, account)
    if profile_gate["is_ready"]:
        return profile_gate, None
    return profile_gate, _redirect_candidate_back_to_profile(
        profile_gate,
        message=message
        or "Lengkapi Data Pribadi dan Upload Berkas wajib terlebih dahulu sebelum melanjutkan.",
        category=category,
    )


def _get_profile_section_definition(section_key):
    safe_key = normalize_career_public_profile_section_key(section_key)
    for definition in CAREER_PROFILE_SECTION_DEFINITIONS:
        if definition["key"] == safe_key:
            return definition
    return CAREER_PROFILE_SECTION_DEFINITIONS[0]


def _get_candidate_personal_profile_payload(db, account_id):
    sections = get_career_public_profile_sections(db, account_id)
    payload = dict((sections.get("personal") or {}).get("payload") or {})
    return payload


def _get_candidate_additional_profile_payload(db, account_id):
    sections = get_career_public_profile_sections(db, account_id)
    payload = dict((sections.get("additional") or {}).get("payload") or {})
    return payload


def _get_candidate_profile_photo_url(db, account_id):
    if not account_id:
        return ""
    payload = _get_candidate_personal_profile_payload(db, account_id)
    return _career_public_media_url("photo", payload.get("photo_path"))


def _get_career_public_media_root(media_kind):
    safe_kind = "photo" if str(media_kind or "").strip().lower() == "photo" else "document"
    root_path = os.path.join(current_app.instance_path, "career_public_media", safe_kind)
    os.makedirs(root_path, exist_ok=True)
    return root_path


def _save_career_public_media(file_storage, media_kind):
    if file_storage is None:
        return ""
    original_name = secure_filename(file_storage.filename or "")
    if not original_name:
        return ""

    safe_kind = "photo" if str(media_kind or "").strip().lower() == "photo" else "document"
    extension = os.path.splitext(original_name)[1].lower()
    if extension not in CAREER_PUBLIC_MEDIA_EXTENSIONS[safe_kind]:
        raise ValueError(
            "Format foto harus JPG, JPEG, PNG, atau WEBP."
            if safe_kind == "photo"
            else "Format dokumen harus PDF, DOC, DOCX, JPG, JPEG, atau PNG."
        )

    content_length = getattr(file_storage, "content_length", None)
    max_bytes = CAREER_PUBLIC_MEDIA_LIMITS[safe_kind]
    if content_length and int(content_length or 0) > max_bytes:
        raise ValueError(
            "Ukuran foto maksimal 2 MB." if safe_kind == "photo" else "Ukuran dokumen maksimal 5 MB."
        )

    stored_name = f"{uuid4().hex}{extension}"
    file_storage.save(os.path.join(_get_career_public_media_root(safe_kind), stored_name))
    return stored_name


def _career_public_media_url(media_kind, stored_name):
    safe_name = secure_filename(stored_name or "")
    if not safe_name:
        return ""
    safe_kind = "photo" if str(media_kind or "").strip().lower() == "photo" else "document"
    return url_for("career.public_media", media_kind=safe_kind, filename=safe_name, v=safe_name)


def _get_career_public_media_absolute_path(media_kind, stored_name):
    safe_name = secure_filename(stored_name or "")
    if not safe_name:
        return ""
    safe_kind = "photo" if str(media_kind or "").strip().lower() == "photo" else "document"
    absolute_path = os.path.abspath(os.path.join(_get_career_public_media_root(safe_kind), safe_name))
    root_path = os.path.abspath(_get_career_public_media_root(safe_kind))
    if absolute_path != root_path and not absolute_path.startswith(root_path + os.sep):
        return ""
    return absolute_path


def _build_candidate_profile_snapshot(account, profile_sections):
    safe_account = dict(account or {})
    safe_sections = {}
    for raw_key, raw_section in dict(profile_sections or {}).items():
        safe_key = normalize_career_public_profile_section_key(raw_key)
        if not safe_key or not isinstance(raw_section, dict):
            continue
        safe_sections[safe_key] = {
            "payload": dict(raw_section.get("payload") or {}),
            "completion_state": str(raw_section.get("completion_state") or "incomplete").strip().lower() or "incomplete",
            "updated_at": raw_section.get("updated_at"),
        }
    return {
        "account_id": int(safe_account.get("id") or 0) or None,
        "account_name": safe_account.get("full_name") or "",
        "account_email": normalize_candidate_email(safe_account.get("email")),
        "personal": dict((safe_sections.get("personal") or {}).get("payload") or {}),
        "additional": dict((safe_sections.get("additional") or {}).get("payload") or {}),
        "sections": safe_sections,
        "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _collect_candidate_profile_documents(profile_sections):
    documents_payload = dict((dict(profile_sections or {}).get("documents") or {}).get("payload") or {})
    files = documents_payload.get("files")
    if not isinstance(files, list):
        return []

    collected = []
    for file_entry in files:
        if not isinstance(file_entry, dict):
            continue
        safe_stored_name = secure_filename(file_entry.get("stored_name") or "")
        if not safe_stored_name:
            continue
        document_type = _normalize_profile_document_type(file_entry.get("document_type")) or "other"
        source_path = _get_career_public_media_absolute_path("document", safe_stored_name)
        collected.append(
            {
                "document_type": document_type,
                "label": _resolve_profile_document_label(document_type, file_entry.get("label")),
                "stored_name": safe_stored_name,
                "uploaded_at": file_entry.get("uploaded_at"),
                "source_path": source_path,
                "source_exists": bool(source_path and os.path.exists(source_path)),
            }
        )
    return collected


def _get_primary_profile_resume_document(profile_documents):
    for document_entry in profile_documents or []:
        safe_entry = dict(document_entry or {})
        if _normalize_profile_document_type(safe_entry.get("document_type")) != "cv_resume":
            continue
        return safe_entry
    return None


def _save_career_resume_from_profile_document(document_entry):
    safe_entry = dict(document_entry or {})
    source_path = safe_entry.get("source_path") or ""
    if not source_path or not os.path.exists(source_path):
        raise ValueError(
            "CV pada profil kandidat tidak ditemukan. Perbarui CV di profil atau unggah file baru saat melamar."
        )

    original_name = secure_filename(safe_entry.get("stored_name") or "")
    extension = os.path.splitext(original_name)[1].lower()
    if not extension:
        extension = os.path.splitext(source_path)[1].lower()
    if extension not in CAREER_RESUME_EXTENSIONS:
        raise ValueError("Format CV pada profil harus PDF, DOC, atau DOCX.")

    if not original_name:
        original_name = f"cv-resume{extension}"

    stored_name = f"{uuid4().hex}{extension}"
    target_path = build_career_resume_path(stored_name)
    shutil.copy2(source_path, target_path)
    return original_name, stored_name


def _allocate_candidate_intake_file_path(directory, preferred_name):
    base_name = secure_filename(preferred_name or "")
    if not base_name:
        base_name = f"file-{uuid4().hex[:8]}.bin"
    stem, extension = os.path.splitext(base_name)
    candidate_path = os.path.join(directory, base_name)
    counter = 2
    while os.path.exists(candidate_path):
        candidate_path = os.path.join(directory, f"{stem}-{counter}{extension}")
        counter += 1
    return candidate_path


def _copy_candidate_file_to_hr_intake(source_path, intake_root, preferred_name):
    if not source_path or not os.path.exists(source_path) or not intake_root:
        return ""
    base_name = preferred_name or os.path.basename(source_path)
    if not os.path.splitext(base_name)[1]:
        base_name = f"{base_name}{os.path.splitext(source_path)[1].lower()}"
    target_path = _allocate_candidate_intake_file_path(intake_root, base_name)
    shutil.copy2(source_path, target_path)
    return target_path


def _sync_candidate_hr_intake_storage(
    *,
    candidate_id,
    candidate_name,
    profile_snapshot,
    profile_documents,
    resume_original_name,
    resume_stored_name,
):
    intake_root = build_recruitment_candidate_intake_path(candidate_id, candidate_name)
    intake_folder = build_recruitment_candidate_intake_relative_folder(candidate_id, candidate_name)
    if not intake_root or not intake_folder:
        return "", [], []

    archived_files = []
    archived_documents = []

    def register_archived_file(category, label, source_path, preferred_name):
        copied_path = _copy_candidate_file_to_hr_intake(source_path, intake_root, preferred_name)
        if not copied_path:
            return ""
        relative_path = "/".join(filter(None, [intake_folder, os.path.basename(copied_path)]))
        archived_files.append(
            {
                "category": category,
                "label": label,
                "file_name": os.path.basename(copied_path),
                "relative_path": relative_path,
            }
        )
        return relative_path

    resume_source_path = build_career_resume_path(resume_stored_name)
    if resume_source_path and os.path.exists(resume_source_path):
        register_archived_file(
            "resume",
            resume_original_name or "CV Lamaran",
            resume_source_path,
            resume_original_name or os.path.basename(resume_source_path),
        )

    personal_payload = dict((dict(profile_snapshot or {}).get("personal") or {}))
    profile_photo_path = _get_career_public_media_absolute_path("photo", personal_payload.get("photo_path"))
    if profile_photo_path and os.path.exists(profile_photo_path):
        register_archived_file(
            "photo",
            "Foto Profil Kandidat",
            profile_photo_path,
            f"foto-profil{os.path.splitext(profile_photo_path)[1].lower()}",
        )

    for document_entry in profile_documents or []:
        safe_entry = dict(document_entry or {})
        relative_path = register_archived_file(
            "profile_document",
            safe_entry.get("label") or "Dokumen Kandidat",
            safe_entry.get("source_path"),
            safe_entry.get("label") or safe_entry.get("stored_name") or "dokumen-kandidat",
        )
        archived_documents.append(
            {
                "document_type": safe_entry.get("document_type") or "other",
                "label": safe_entry.get("label") or "Dokumen Kandidat",
                "stored_name": safe_entry.get("stored_name") or "",
                "uploaded_at": safe_entry.get("uploaded_at"),
                "available_in_hr_storage": bool(relative_path),
                "hr_storage_relative_path": relative_path,
            }
        )

    manifest_payload = {
        "candidate_id": int(candidate_id or 0) or None,
        "candidate_name": candidate_name or "",
        "copied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "profile_snapshot": profile_snapshot or {},
        "profile_documents": archived_documents,
    }
    manifest_path = _allocate_candidate_intake_file_path(intake_root, "Ringkasan Profil Kandidat.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest_payload, handle, ensure_ascii=False, indent=2)
    archived_files.insert(
        0,
        {
            "category": "manifest",
            "label": "Ringkasan Profil Kandidat",
            "file_name": os.path.basename(manifest_path),
            "relative_path": "/".join(filter(None, [intake_folder, os.path.basename(manifest_path)])),
        },
    )
    return intake_folder, archived_files, archived_documents


def _get_hr_sms_recipient_users(db):
    try:
        rows = db.execute(
            """
            SELECT id, username, role
            FROM users
            WHERE role IN (?, ?)
            ORDER BY role ASC, username COLLATE NOCASE ASC, id ASC
            """,
            ("hr", "super_admin"),
        ).fetchall()
    except Exception:
        return []
    if not isinstance(rows, (list, tuple)):
        return []
    recipients = []
    seen_user_ids = set()
    for row in rows:
        try:
            user_id = int(row["id"] or 0)
        except (TypeError, ValueError):
            user_id = 0
        if user_id <= 0 or user_id in seen_user_ids:
            continue
        seen_user_ids.add(user_id)
        recipients.append({"id": user_id, "username": row["username"], "role": row["role"]})
    return recipients


def _sync_candidate_intake_to_hr_sms_workspaces(db, hr_storage_folder):
    source_root = build_sms_storage_absolute_path(hr_storage_folder)
    if not source_root or not os.path.isdir(source_root):
        return []

    mirrored_targets = []
    candidate_folder_name = os.path.basename(source_root)
    for user in _get_hr_sms_recipient_users(db):
        user_root = build_sms_user_storage_root(user["id"])
        if not user_root:
            continue
        intake_root = os.path.join(user_root, "Recruitment Intake")
        os.makedirs(intake_root, exist_ok=True)
        target_root = os.path.join(intake_root, candidate_folder_name)
        shutil.copytree(source_root, target_root, dirs_exist_ok=True)
        mirrored_targets.append(
            {
                "user_id": user["id"],
                "username": user.get("username") or f"user_{user['id']}",
                "role": user.get("role") or "",
                "relative_path": "/".join(("Recruitment Intake", candidate_folder_name)),
            }
        )
    return mirrored_targets


def _resolve_created_public_candidate_id(db, candidate_id, *, opening_id, public_account_id, resume_path):
    try:
        safe_candidate_id = int(candidate_id or 0)
    except (TypeError, ValueError):
        safe_candidate_id = 0
    if safe_candidate_id > 0:
        return safe_candidate_id

    row = db.execute(
        """
        SELECT id
        FROM recruitment_candidates
        WHERE public_account_id=?
          AND vacancy_id=?
          AND resume_path=?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (
            int(public_account_id or 0),
            int(opening_id or 0),
            resume_path or "",
        ),
    ).fetchone()
    return int(row["id"] or 0) if row else 0


def _render_candidate_jobs_portal(
    db,
    account,
    *,
    initial_query="",
    initial_department="",
    initial_type_filter="",
    selected_warehouse_id=None,
    profile_gate=None,
):
    openings = _fetch_public_opening_summaries(db, selected_warehouse_id)
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
    applications = _fetch_candidate_workspace_applications(db, account)
    saved_opening_ids = get_career_public_saved_opening_ids(db, account["id"])
    openings = _decorate_workspace_openings(
        openings,
        saved_opening_ids=saved_opening_ids,
        applications=applications,
    )
    selected_opening_id = request.args.get("vacancy", "").strip()
    try:
        selected_opening_id = int(selected_opening_id) if selected_opening_id else None
    except ValueError:
        selected_opening_id = None
    selected_opening = None
    if selected_opening_id:
        selected_summary = next((opening for opening in openings if opening["id"] == selected_opening_id), None)
        if selected_summary:
            selected_opening = _fetch_public_opening_by_id(db, selected_opening_id) or dict(selected_summary)
            if selected_opening:
                selected_opening["is_saved"] = selected_summary.get("is_saved")
                selected_opening["has_applied"] = selected_summary.get("has_applied")
                selected_opening["application"] = selected_summary.get("application")
    application_feedback_modal = None
    application_notice = str(request.args.get("application_notice") or "").strip().lower()
    if selected_opening is not None:
        if str(request.args.get("applied") or "").strip() == "1":
            application_feedback_modal = {
                "kicker": "Lamaran Terkirim",
                "title": "Terima kasih sudah melamar.",
                "body": [
                    f"Lamaran Anda untuk posisi {selected_opening.get('title') or 'ini'} sudah kami terima. Tim HR akan melakukan screening terlebih dahulu.",
                    "Silakan cek email secara berkala untuk melihat update tahap berikutnya, termasuk pemberitahuan lolos screening atau kode tes jika Anda lanjut ke tahap assessment.",
                ],
                "primary_label": "Lihat Lamaran",
                "primary_url": url_for("career.applications_page"),
                "secondary_label": "Tutup",
            }
        elif application_notice == "duplicate_pending":
            application_feedback_modal = {
                "kicker": "Lamaran Sudah Masuk",
                "title": "Lamaran Anda sudah kami terima.",
                "body": [
                    f"Posisi {selected_opening.get('title') or 'ini'} sudah pernah Anda lamar dan saat ini masih menunggu screening HR.",
                    "Silakan cek email secara berkala. Jika Anda lolos review awal, undangan atau kode tes akan kami kirim otomatis ke email Anda.",
                ],
                "primary_label": "Lihat Lamaran",
                "primary_url": url_for("career.applications_page"),
                "secondary_label": "Tutup",
            }
        elif application_notice == "duplicate_ready":
            application_feedback_modal = {
                "kicker": "Lamaran Sudah Tercatat",
                "title": "Lamaran ini sudah pernah Anda kirim.",
                "body": [
                    f"Lamaran untuk posisi {selected_opening.get('title') or 'ini'} sudah ada di dashboard Anda.",
                    "Jika Anda sudah lolos screening HR, kode tes atau tautan tahap berikutnya bisa dilihat dari email dan halaman lamaran kandidat.",
                ],
                "primary_label": "Lihat Lamaran",
                "primary_url": url_for("career.applications_page"),
                "secondary_label": "Tutup",
            }
    return render_template(
        "career_candidate_jobs.html",
        candidate_account=account,
        candidate_profile_photo_url=_get_candidate_profile_photo_url(db, account["id"]),
        candidate_profile_gate=profile_gate or _get_candidate_profile_gate(db, account),
        openings=openings,
        selected_opening=selected_opening,
        initial_query=initial_query,
        initial_department=initial_department,
        initial_type_filter=initial_type_filter,
        selected_warehouse_id=selected_warehouse_id,
        candidate_application_count=len(applications),
        candidate_saved_count=len(saved_opening_ids),
        application_feedback_modal=application_feedback_modal,
    )


def _attach_legacy_public_applications_to_account(db, account):
    safe_account = dict(account or {})
    try:
        account_id = int(safe_account.get("id") or 0)
    except (TypeError, ValueError):
        account_id = 0
    if account_id <= 0:
        return 0

    account_email = normalize_candidate_email(safe_account.get("email"))
    personal_payload = _get_candidate_personal_profile_payload(db, account_id)
    account_phone = normalize_candidate_phone(personal_payload.get("phone"))
    if not account_email and not account_phone:
        return 0

    rows = db.execute(
        """
        SELECT id, email, phone
        FROM recruitment_candidates
        WHERE public_account_id IS NULL
          AND (
              application_channel=?
              OR LOWER(COALESCE(source, ''))='halaman karir'
          )
        ORDER BY created_at DESC, id DESC
        """,
        (normalize_career_application_channel("public_portal"),),
    ).fetchall()

    matched_candidate_ids = []
    for row in rows:
        row_data = dict(row)
        row_email = normalize_candidate_email(row_data.get("email"))
        row_phone = normalize_candidate_phone(row_data.get("phone"))
        email_match = bool(account_email and row_email and row_email == account_email)
        phone_match = bool(account_phone and row_phone and row_phone == account_phone)
        if email_match or phone_match:
            try:
                candidate_id = int(row_data.get("id") or 0)
            except (TypeError, ValueError):
                candidate_id = 0
            if candidate_id > 0:
                matched_candidate_ids.append(candidate_id)

    if not matched_candidate_ids:
        return 0

    db.executemany(
        """
        UPDATE recruitment_candidates
        SET public_account_id=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
          AND public_account_id IS NULL
        """,
        [(account_id, candidate_id) for candidate_id in matched_candidate_ids],
    )
    db.commit()
    return len(matched_candidate_ids)


def _fetch_candidate_workspace_applications(db, account):
    safe_account = dict(account or {})
    try:
        account_id = int(safe_account.get("id") or 0)
    except (TypeError, ValueError):
        account_id = 0
    account_email = normalize_candidate_email(safe_account.get("email"))
    if account_id <= 0 and not account_email:
        return []

    _attach_legacy_public_applications_to_account(db, safe_account)

    rows = db.execute(
        """
        SELECT
            r.*,
            o.title AS vacancy_title,
            o.description AS vacancy_description,
            o.requirements AS vacancy_requirements,
            o.location_label AS opening_location_label,
            o.employment_type AS opening_employment_type,
            w.name AS warehouse_name
        FROM recruitment_candidates r
        LEFT JOIN career_openings o ON r.vacancy_id = o.id
        LEFT JOIN warehouses w ON r.warehouse_id = w.id
        WHERE (
              r.application_channel=?
              OR LOWER(COALESCE(r.source, ''))='halaman karir'
          )
          AND (
              r.public_account_id=?
              OR (r.public_account_id IS NULL AND LOWER(COALESCE(r.email, ''))=LOWER(?))
          )
        ORDER BY r.created_at DESC, r.id DESC
        """,
        (
            normalize_career_application_channel("public_portal"),
            account_id,
            account_email,
        ),
    ).fetchall()
    applications = []
    for row in rows:
        application = _annotate_public_candidate_display(dict(row))
        application["title_display"] = application.get("vacancy_title") or application.get("position_title") or "Posisi aktif"
        application["employment_type_display"] = normalize_career_employment_type(
            application.get("opening_employment_type") or application.get("employment_type")
        ).replace("_", " ").title()
        application["status_label"] = str(application.get("status") or "active").replace("_", " ").title()
        application["stage_label"] = str(application.get("stage") or "applied").replace("_", " ").title()
        application["detail_url"] = (
            build_career_public_url("career.opening_detail", opening_id=int(application["vacancy_id"]))
            if int(application.get("vacancy_id") or 0) > 0
            else build_career_public_url("career.index")
        )
        application["assessment_ready"] = bool(
            normalize_assessment_code(application.get("assessment_code"))
        )
        application["assessment_url"] = (
            build_career_public_url("career.assessment", code=application.get("assessment_code"))
            if application["assessment_ready"]
            else ""
        )
        application["assessment_code_display"] = (
            application.get("assessment_code")
            if application["assessment_ready"]
            else "Menunggu screening HR"
        )
        application["progress_note"] = (
            "Kode tes sudah tersedia. Silakan cek email atau lanjut dari tombol tes ketika siap mengerjakan."
            if application["assessment_ready"]
            else "Lamaran sudah masuk ke pipeline rekrutmen. Tim HR akan melakukan screening awal terlebih dahulu sebelum mengirim kode tes ke email Anda."
        )
        applications.append(application)
    return applications


def _fetch_candidate_workspace_saved_openings(db, account_id):
    saved_opening_ids = get_career_public_saved_opening_ids(db, account_id)
    if not saved_opening_ids:
        return []
    openings = _fetch_public_openings(db)
    saved_openings = []
    for opening in openings:
        if int(opening.get("id") or 0) in saved_opening_ids:
            safe_opening = dict(opening)
            safe_opening["is_saved"] = True
            saved_openings.append(safe_opening)
    return saved_openings


def _decorate_workspace_openings(openings, saved_opening_ids=None, applications=None):
    saved_ids = {int(item) for item in (saved_opening_ids or set()) if str(item).isdigit()}
    application_map = {}
    for application in applications or []:
        vacancy_id = int(application.get("vacancy_id") or 0)
        if vacancy_id > 0 and vacancy_id not in application_map:
            application_map[vacancy_id] = application

    decorated = []
    for opening in openings or []:
        safe_opening = dict(opening)
        opening_id = int(safe_opening.get("id") or 0)
        application = application_map.get(opening_id)
        safe_opening["is_saved"] = opening_id in saved_ids
        safe_opening["has_applied"] = application is not None
        safe_opening["application"] = application
        decorated.append(safe_opening)
    return decorated


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
    return [_annotate_public_opening_display(dict(row)) for row in db.execute(query, params).fetchall()]


def _fetch_public_opening_summaries(db, selected_warehouse=None):
    query = """
        SELECT
            o.id,
            o.warehouse_id,
            o.title,
            o.department,
            o.employment_type,
            o.location_label,
            o.status,
            o.is_public,
            o.sort_order,
            o.created_at,
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
    return [_annotate_public_opening_display(dict(row)) for row in db.execute(query, params).fetchall()]


def _matches_public_opening_filters(opening, query="", department="", employment_type=""):
    safe_opening = dict(opening or {})
    safe_query = str(query or "").strip().lower()
    safe_department = str(department or "").strip().lower()
    safe_type = str(employment_type or "").strip().lower()

    title_value = str(safe_opening.get("title") or "").strip().lower()
    department_value = str(safe_opening.get("department") or "").strip().lower()
    location_value = str(
        safe_opening.get("location_label_display")
        or safe_opening.get("location_label")
        or safe_opening.get("warehouse_name_display")
        or safe_opening.get("warehouse_name")
        or ""
    ).strip().lower()
    unit_value = str(
        safe_opening.get("warehouse_name_display") or safe_opening.get("warehouse_name") or ""
    ).strip().lower()
    type_value = str(safe_opening.get("employment_type") or "full_time").replace("_", " ").strip().lower()

    if safe_query and safe_query not in " ".join(
        value for value in [title_value, department_value, location_value, unit_value, type_value] if value
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
    return _annotate_public_opening_display(dict(row)) if row else None


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
    return _annotate_public_candidate_display(dict(row)) if row else None


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
        location_label = str(
            opening.get("location_label_display")
            or opening.get("location_label")
            or opening.get("warehouse_name_display")
            or opening.get("warehouse_name")
            or ""
        ).strip()
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
                "location_label": str(
                    opening.get("location_label_display")
                    or opening.get("location_label")
                    or opening.get("warehouse_name_display")
                    or opening.get("warehouse_name")
                    or ""
                ).strip(),
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
    warehouses = [
        _annotate_public_warehouse_display(dict(row))
        for row in db.execute("SELECT id, name FROM warehouses ORDER BY name ASC").fetchall()
    ]
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


@career_bp.route("/karir/portal")
def portal_page():
    db = get_db()
    ensure_career_schema(db)
    account, redirect_response = _require_career_public_account(db)
    if redirect_response:
        return redirect_response
    profile_gate, redirect_response = _guard_candidate_profile_completion(
        db,
        account,
        message="Lengkapi Data Pribadi dan Upload Berkas wajib terlebih dahulu sebelum masuk ke portal kandidat.",
    )
    if redirect_response:
        return redirect_response

    initial_query, initial_department, initial_type_filter, selected_warehouse_id = _parse_public_opening_filters()
    return _render_candidate_jobs_portal(
        db,
        account,
        initial_query=initial_query,
        initial_department=initial_department,
        initial_type_filter=initial_type_filter,
        selected_warehouse_id=selected_warehouse_id,
        profile_gate=profile_gate,
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
    recruitment_host = _get_primary_recruitment_public_host()
    current_host = str(request.host or "").strip().split(":", 1)[0].lower()
    active_account = _get_current_career_public_account(db)
    if recruitment_host and current_host == recruitment_host.lower() and not active_account:
        return redirect(build_career_public_url("career.signin_page"))
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
    active_account = _get_current_career_public_account(db)
    flow = str(request.args.get("flow") or "signin").strip().lower()
    if flow not in {"signin", "signup"}:
        flow = "signin"
    registered = str(request.args.get("registered") or "").strip() in {"1", "true", "yes"}
    email = (request.args.get("email") or "").strip()
    registration_delivery = str(request.args.get("mail") or "sent").strip().lower()
    if registration_delivery not in {"sent", "pending"}:
        registration_delivery = "sent"
    verification_success = str(request.args.get("verified") or "").strip() in {"1", "true", "yes"}
    next_target = _safe_career_public_next_target(request.args.get("next"))
    if active_account:
        return redirect(_resolve_career_public_post_auth_target(next_target))
    return render_template(
        "career_signin.html",
        signin_url=_career_public_signin_url(),
        register_url=_career_public_register_url(),
        active_flow=flow,
        registration_success=registered,
        registration_email=email,
        registration_delivery=registration_delivery,
        verification_success=verification_success,
        next_target=next_target or "",
        opening_count=len(openings),
    )


@career_bp.route("/signin/auth", methods=["POST"])
def signin_submit():
    db = get_db()
    ensure_career_schema(db)
    email = (request.form.get("email") or "").strip()
    password = (request.form.get("password") or "").strip()
    next_target = _safe_career_public_next_target(request.form.get("next"))
    if not email or not password:
        flash("Email dan kata sandi wajib diisi.", "error")
        return _redirect_career_public_with_next("career.signin_page", flow="signin", next_target=next_target)

    account = get_career_public_account_by_email(db, email)
    if not account:
        flash("Akun kandidat belum ditemukan. Silakan daftar akun terlebih dahulu.", "error")
        return _redirect_career_public_with_next("career.signin_page", flow="signup", next_target=next_target)

    account_status = normalize_career_public_account_status(account.get("status"))
    if account_status != "active":
        flash("Email belum diverifikasi. Silakan cek inbox dan klik link verifikasi yang kami kirimkan.", "error")
        return _redirect_career_public_with_next("career.signin_page", flow="signin", next_target=next_target)

    if not check_password_hash(account.get("password_hash") or "", password):
        flash("Email atau kata sandi tidak sesuai.", "error")
        return _redirect_career_public_with_next("career.signin_page", flow="signin", next_target=next_target)

    account = touch_career_public_account_login(db, account["id"]) or account
    db.commit()
    _set_career_public_session(account)
    flash("Akun kandidat berhasil masuk.", "success")
    return redirect(_resolve_career_public_post_auth_target(next_target))


@career_bp.route("/signin/register-request", methods=["POST"])
def signin_register_request():
    candidate_name = (request.form.get("candidate_name") or "").strip()
    email = (request.form.get("email") or "").strip()
    password = (request.form.get("password") or "").strip()
    password_confirmation = (request.form.get("password_confirmation") or "").strip()
    next_target = _safe_career_public_next_target(request.form.get("next"))
    if not candidate_name or not email or not password or not password_confirmation:
        flash("Nama lengkap, email, kata sandi, dan konfirmasi kata sandi wajib diisi.", "error")
        return _redirect_career_public_with_next("career.signin_page", flow="signup", next_target=next_target)
    if len(password) < 8:
        flash("Kata sandi minimal 8 karakter.", "error")
        return _redirect_career_public_with_next("career.signin_page", flow="signup", next_target=next_target)
    if password != password_confirmation:
        flash("Konfirmasi kata sandi belum sama.", "error")
        return _redirect_career_public_with_next("career.signin_page", flow="signup", next_target=next_target)

    db = get_db()
    ensure_career_schema(db)
    try:
        create_public_account_request(
            db,
            candidate_name,
            email,
            source="career_public_signup",
        )
        account = upsert_career_public_account(
            db,
            candidate_name,
            email,
            generate_password_hash(password),
        )
        verification_token = issue_career_public_account_verification(
            db,
            account["id"],
            ttl_hours=_get_career_public_verification_ttl_hours(),
        )
        db.commit()
    except ValueError as exc:
        flash(str(exc), "error")
        return _redirect_career_public_with_next("career.signin_page", flow="signup", next_target=next_target)

    career_company_name = _get_career_public_company_name()
    verification_url = build_career_public_url(
        "career.verify_public_account",
        force_external=True,
        token=verification_token,
        **({"next": next_target} if next_target else {}),
    )
    email_subject = f"Verifikasi akun karir {career_company_name}"
    email_body = (
        f"Halo {candidate_name},\n\n"
        f"Akun kandidat untuk portal karir {career_company_name} hampir siap digunakan.\n"
        "Klik tautan verifikasi di bawah ini untuk mengaktifkan akun Anda secara otomatis:\n\n"
        f"{verification_url}\n\n"
        f"Tautan ini berlaku selama {_get_career_public_verification_ttl_hours()} jam.\n"
        "Sesudah akun aktif, Anda bisa masuk lalu melamar posisi yang tersedia di portal karir.\n\n"
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
    return _redirect_career_public_with_next(
        "career.signin_page",
        next_target=next_target,
        flow="signup",
        registered=1,
        email=email,
        mail=registration_delivery,
    )


@career_bp.route("/signin/verify")
def verify_public_account():
    db = get_db()
    ensure_career_schema(db)
    token = (request.args.get("token") or "").strip()
    next_target = _safe_career_public_next_target(request.args.get("next"))
    account = get_career_public_account_by_verification_token(db, token)
    if not account:
        flash("Link verifikasi tidak valid atau sudah tidak bisa digunakan.", "error")
        return _redirect_career_public_with_next("career.signin_page", flow="signup", next_target=next_target)

    expires_at = _parse_career_datetime(account.get("verification_expires_at"))
    if expires_at and datetime.now() > expires_at:
        flash("Link verifikasi sudah kedaluwarsa. Silakan daftar ulang untuk mengirim tautan baru.", "error")
        return _redirect_career_public_with_next("career.signin_page", flow="signup", next_target=next_target)

    if normalize_career_public_account_status(account.get("status")) != "active":
        account = activate_career_public_account(db, account["id"]) or account
        mark_public_account_request_status_by_email(db, account.get("email"), status="processed")
        db.commit()

    _set_career_public_session(account)
    flash("Akun kandidat berhasil diaktifkan. Anda sudah bisa melamar lowongan.", "success")
    return redirect(_resolve_career_public_post_auth_target(next_target))


@career_bp.route("/signin/logout")
def signout_public_account():
    _clear_career_public_session()
    flash("Akun kandidat sudah keluar.", "info")
    return _redirect_career_public("career.signin_page", flow="signin")


@career_bp.route("/karir/media/<media_kind>/<path:filename>")
def public_media(media_kind, filename):
    account, redirect_response = _require_career_public_account()
    if redirect_response:
        return redirect_response
    del account

    safe_kind = "photo" if str(media_kind or "").strip().lower() == "photo" else "document"
    safe_name = secure_filename(filename or "")
    if not safe_name:
        return redirect(build_career_public_url("career.profile_page"))
    return send_from_directory(
        _get_career_public_media_root(safe_kind),
        safe_name,
        as_attachment=safe_kind == "document",
    )


@career_bp.route("/karir/lamaran")
def applications_page():
    db = get_db()
    ensure_career_schema(db)
    account, redirect_response = _require_career_public_account(db)
    if redirect_response:
        return redirect_response
    profile_gate, redirect_response = _guard_candidate_profile_completion(
        db,
        account,
        message="Lengkapi Data Pribadi dan Upload Berkas wajib terlebih dahulu sebelum membuka riwayat lamaran.",
    )
    if redirect_response:
        return redirect_response

    applications = _fetch_candidate_workspace_applications(db, account)
    saved_openings = get_career_public_saved_opening_ids(db, account["id"])
    return render_template(
        "career_candidate_applications.html",
        candidate_account=account,
        candidate_profile_photo_url=_get_candidate_profile_photo_url(db, account["id"]),
        candidate_profile_gate=profile_gate,
        applications=applications,
        candidate_application_count=len(applications),
        candidate_saved_count=len(saved_openings),
    )


@career_bp.route("/karir/tersimpan")
def saved_openings_page():
    db = get_db()
    ensure_career_schema(db)
    account, redirect_response = _require_career_public_account(db)
    if redirect_response:
        return redirect_response
    profile_gate, redirect_response = _guard_candidate_profile_completion(
        db,
        account,
        message="Lengkapi Data Pribadi dan Upload Berkas wajib terlebih dahulu sebelum membuka lowongan tersimpan.",
    )
    if redirect_response:
        return redirect_response

    saved_openings = _fetch_candidate_workspace_saved_openings(db, account["id"])
    applications = _fetch_candidate_workspace_applications(db, account)
    application_map = {int(item.get("vacancy_id") or 0): item for item in applications if int(item.get("vacancy_id") or 0) > 0}
    for opening in saved_openings:
        opening["has_applied"] = int(opening.get("id") or 0) in application_map
        opening["application"] = application_map.get(int(opening.get("id") or 0))

    return render_template(
        "career_candidate_saved.html",
        candidate_account=account,
        candidate_profile_photo_url=_get_candidate_profile_photo_url(db, account["id"]),
        candidate_profile_gate=profile_gate,
        saved_openings=saved_openings,
        candidate_application_count=len(applications),
        candidate_saved_count=len(saved_openings),
    )


@career_bp.route("/karir/tersimpan/toggle", methods=["POST"])
def toggle_saved_opening():
    db = get_db()
    ensure_career_schema(db)
    account, redirect_response = _require_career_public_account(db)
    if redirect_response:
        return redirect_response
    profile_gate, redirect_response = _guard_candidate_profile_completion(
        db,
        account,
        message="Lengkapi profil kandidat wajib terlebih dahulu sebelum menyimpan lowongan.",
    )
    if redirect_response:
        return redirect_response

    payload = request.get_json(silent=True) if request.is_json else {}
    opening_id_raw = (
        request.form.get("opening_id")
        or (payload or {}).get("opening_id")
        or ""
    )
    next_target = _safe_career_public_next_target(
        request.form.get("next") or (payload or {}).get("next")
    )
    try:
        opening_id = int(str(opening_id_raw or "").strip())
    except (TypeError, ValueError):
        opening_id = 0
    opening = _fetch_public_opening_by_id(db, opening_id)
    if not opening:
        flash("Lowongan tidak ditemukan.", "error")
        if request.is_json:
            return jsonify({"ok": False, "message": "Lowongan tidak ditemukan."}), 404
        return redirect(next_target or build_career_public_url("career.index"))

    saved_ids = get_career_public_saved_opening_ids(db, account["id"])
    is_saved = int(opening["id"]) not in saved_ids
    set_career_public_saved_opening_state(db, account["id"], opening["id"], is_saved=is_saved)
    db.commit()
    message = "Lowongan disimpan ke daftar tersimpan." if is_saved else "Lowongan dihapus dari daftar tersimpan."
    if request.is_json:
        return jsonify({"ok": True, "saved": is_saved, "message": message})
    flash(message, "success" if is_saved else "info")
    return redirect(next_target or build_career_public_url("career.index", vacancy=opening["id"]))


@career_bp.route("/karir/profil", methods=["GET", "POST"])
def profile_page():
    db = get_db()
    ensure_career_schema(db)
    account, redirect_response = _require_career_public_account(db)
    if redirect_response:
        return redirect_response

    selected_section_key = normalize_career_public_profile_section_key(
        request.values.get("section") or request.args.get("tab")
    ) or "personal"
    stored_sections = get_career_public_profile_sections(db, account["id"])
    current_payload = dict((stored_sections.get(selected_section_key) or {}).get("payload") or {})

    if request.method == "POST":
        payload = _normalize_career_profile_section_payload(
            selected_section_key,
            request.form,
            existing_payload=current_payload,
        )
        if selected_section_key == "personal":
            photo_file = request.files.get("photo_file")
            if photo_file and (photo_file.filename or "").strip():
                try:
                    payload["photo_path"] = _save_career_public_media(photo_file, "photo")
                except ValueError as exc:
                    flash(str(exc), "error")
                    return redirect(build_career_public_url("career.profile_page", section=selected_section_key))

            full_name = normalize_candidate_identity_name(payload.get("full_name")) or account.get("full_name") or ""
            db.execute(
                """
                UPDATE career_public_accounts
                SET full_name=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (full_name, account["id"]),
            )
        elif selected_section_key == "documents":
            files = payload.get("files")
            if not isinstance(files, list):
                files = []
            remove_index_raw = request.form.get("remove_document_index")
            try:
                remove_index = int(remove_index_raw) if str(remove_index_raw or "").strip() else -1
            except (TypeError, ValueError):
                remove_index = -1
            if 0 <= remove_index < len(files):
                files.pop(remove_index)
            uploaded_single = request.files.get("document_file")
            selected_document_type = _normalize_profile_document_type(request.form.get("document_type"))
            custom_document_label = _normalize_profile_text(request.form.get("document_label"))

            uploaded_files = []
            if uploaded_single and (uploaded_single.filename or "").strip():
                uploaded_files.append((uploaded_single, selected_document_type, custom_document_label))
            else:
                for uploaded in request.files.getlist("documents"):
                    if not uploaded or not (uploaded.filename or "").strip():
                        continue
                    inferred_type = _guess_profile_document_type_from_filename(uploaded.filename)
                    inferred_label = "" if inferred_type != "other" else secure_filename(uploaded.filename or "")
                    uploaded_files.append((uploaded, inferred_type, inferred_label))

            if uploaded_files and not selected_document_type and uploaded_single and (uploaded_single.filename or "").strip():
                flash("Pilih jenis berkas terlebih dahulu sebelum upload dokumen.", "error")
                return redirect(build_career_public_url("career.profile_page", section=selected_section_key))

            for uploaded, document_type, custom_label in uploaded_files:
                try:
                    stored_name = _save_career_public_media(uploaded, "document")
                except ValueError as exc:
                    flash(str(exc), "error")
                    return redirect(build_career_public_url("career.profile_page", section=selected_section_key))
                normalized_type = _normalize_profile_document_type(document_type) or "other"
                normalized_label = _resolve_profile_document_label(normalized_type, custom_label or secure_filename(uploaded.filename or ""))
                files = [
                    item
                    for item in files
                    if not (
                        isinstance(item, dict)
                        and _normalize_profile_document_type(item.get("document_type")) == normalized_type
                        and normalized_type != "other"
                    )
                ]
                files.append(
                    {
                        "document_type": normalized_type,
                        "label": normalized_label,
                        "stored_name": stored_name,
                        "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )
            payload["files"] = files

        completion_state = "complete" if _is_profile_payload_complete(selected_section_key, payload, account) else "incomplete"
        upsert_career_public_profile_section(
            db,
            account["id"],
            selected_section_key,
            payload,
            completion_state=completion_state,
        )
        db.commit()
        if selected_section_key == "personal":
            account = get_career_public_account_by_id(db, account["id"]) or account
            _set_career_public_session(account)
        flash("Profil kandidat berhasil diperbarui.", "success")
        return redirect(build_career_public_url("career.profile_page", section=selected_section_key))

    stored_sections = get_career_public_profile_sections(db, account["id"])
    profile_gate = _get_candidate_profile_gate(db, account, stored_sections=stored_sections)
    section_states = profile_gate["section_states"]
    selected_section = next(
        (item for item in section_states if item["key"] == selected_section_key),
        section_states[0],
    )
    selected_payload = dict(selected_section.get("payload") or {})
    personal_section_payload = dict((stored_sections.get("personal") or {}).get("payload") or {})
    if selected_section_key == "personal":
        selected_payload.setdefault("full_name", account.get("full_name") or "")
        selected_payload.setdefault("email", account.get("email") or "")
    selected_photo_url = _career_public_media_url("photo", selected_payload.get("photo_path")) if selected_section_key == "personal" else ""
    account_photo_url = _career_public_media_url("photo", personal_section_payload.get("photo_path"))
    document_files = []
    for file_entry in (selected_payload.get("files") if selected_section_key == "documents" else []) or []:
        if not isinstance(file_entry, dict):
            continue
        safe_name = secure_filename(file_entry.get("stored_name") or "")
        if not safe_name:
            continue
        document_files.append(
            {
                **file_entry,
                "document_type": _normalize_profile_document_type(file_entry.get("document_type")) or "other",
                "resolved_label": _resolve_profile_document_label(
                    file_entry.get("document_type"),
                    file_entry.get("label"),
                ),
                "type_label": _resolve_profile_document_label(file_entry.get("document_type")),
                "url": _career_public_media_url("document", safe_name),
            }
        )
    document_files.sort(
        key=lambda item: (
            next(
                (
                    index
                    for index, definition in enumerate(CAREER_PROFILE_DOCUMENT_DEFINITIONS)
                    if definition["key"] == item.get("document_type")
                ),
                len(CAREER_PROFILE_DOCUMENT_DEFINITIONS),
            ),
            (item.get("resolved_label") or "").lower(),
        )
    )
    document_status_cards = []
    document_file_map = {
        _normalize_profile_document_type(item.get("document_type")): item
        for item in document_files
        if item.get("document_type") != "other"
    }
    for definition in CAREER_PROFILE_DOCUMENT_DEFINITIONS:
        matched_file = document_file_map.get(definition["key"])
        document_status_cards.append(
            {
                **definition,
                "uploaded": matched_file is not None,
                "file": matched_file,
            }
        )

    applications = _fetch_candidate_workspace_applications(db, account)
    saved_openings = get_career_public_saved_opening_ids(db, account["id"])
    return render_template(
        "career_candidate_profile.html",
        candidate_account=account,
        candidate_profile_gate=profile_gate,
        profile_sections=section_states,
        selected_profile_section=selected_section,
        selected_profile_payload=selected_payload,
        candidate_profile_photo_url=account_photo_url,
        selected_profile_photo_url=selected_photo_url,
        selected_profile_documents=document_files,
        selected_profile_document_statuses=document_status_cards,
        profile_document_definitions=CAREER_PROFILE_DOCUMENT_DEFINITIONS,
        profile_gender_options=CAREER_PROFILE_GENDER_OPTIONS,
        profile_marital_status_options=CAREER_PROFILE_MARITAL_STATUS_OPTIONS,
        profile_religion_options=CAREER_PROFILE_RELIGION_OPTIONS,
        candidate_application_count=len(applications),
        candidate_saved_count=len(saved_openings),
    )


@career_bp.route("/karir/password", methods=["GET", "POST"])
def password_page():
    db = get_db()
    ensure_career_schema(db)
    account, redirect_response = _require_career_public_account(db)
    if redirect_response:
        return redirect_response
    profile_gate, redirect_response = _guard_candidate_profile_completion(
        db,
        account,
        message="Lengkapi Data Pribadi dan Upload Berkas wajib terlebih dahulu sebelum keluar dari halaman profil.",
    )
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        current_password = (request.form.get("current_password") or "").strip()
        new_password = (request.form.get("new_password") or "").strip()
        confirmation = (request.form.get("password_confirmation") or "").strip()

        if not current_password or not new_password or not confirmation:
            flash("Kata sandi lama, kata sandi baru, dan konfirmasi wajib diisi.", "error")
            return redirect(build_career_public_url("career.password_page"))
        if not check_password_hash(account.get("password_hash") or "", current_password):
            flash("Kata sandi lama tidak sesuai.", "error")
            return redirect(build_career_public_url("career.password_page"))
        if len(new_password) < 8:
            flash("Kata sandi baru minimal 8 karakter.", "error")
            return redirect(build_career_public_url("career.password_page"))
        if new_password != confirmation:
            flash("Konfirmasi kata sandi belum sama.", "error")
            return redirect(build_career_public_url("career.password_page"))

        updated_account = update_career_public_account_password_hash(
            db,
            account["id"],
            generate_password_hash(new_password),
        )
        db.commit()
        if updated_account:
            _set_career_public_session(updated_account)
        flash("Kata sandi akun kandidat berhasil diperbarui.", "success")
        return redirect(build_career_public_url("career.password_page"))

    applications = _fetch_candidate_workspace_applications(db, account)
    saved_openings = get_career_public_saved_opening_ids(db, account["id"])
    return render_template(
        "career_candidate_password.html",
        candidate_account=account,
        candidate_profile_photo_url=_get_candidate_profile_photo_url(db, account["id"]),
        candidate_profile_gate=profile_gate,
        candidate_application_count=len(applications),
        candidate_saved_count=len(saved_openings),
    )


@career_bp.route("/karir/lowongan/<int:opening_id>")
def opening_detail(opening_id):
    db = get_db()
    ensure_career_schema(db)
    active_account = _get_current_career_public_account(db)
    try:
        profile_sections = get_career_public_profile_sections(db, active_account["id"]) if active_account else {}
    except TypeError:
        profile_sections = {}
    if active_account:
        profile_gate, redirect_response = _guard_candidate_profile_completion(
            db,
            active_account,
            message="Lengkapi Data Pribadi dan Upload Berkas wajib terlebih dahulu sebelum membuka detail lowongan atau melamar.",
        )
        if redirect_response:
            return redirect_response
    personal_payload = _get_candidate_personal_profile_payload(db, active_account["id"]) if active_account else {}
    additional_payload = _get_candidate_additional_profile_payload(db, active_account["id"]) if active_account else {}
    profile_documents = _collect_candidate_profile_documents(profile_sections)
    profile_resume_document = _get_primary_profile_resume_document(profile_documents)
    if profile_resume_document:
        resume_file_name = profile_resume_document.get("stored_name") or "cv-resume"
        resume_extension = os.path.splitext(resume_file_name)[1].lower()
        profile_resume_document = {
            **profile_resume_document,
            "download_url": _career_public_media_url("document", profile_resume_document.get("stored_name")),
            "is_valid_resume_format": resume_extension in CAREER_RESUME_EXTENSIONS,
            "file_name": resume_file_name,
        }

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
        register_url=_career_public_register_url(),
        public_account=active_account,
        opening_is_saved=bool(
            active_account
            and int(opening["id"]) in get_career_public_saved_opening_ids(db, active_account["id"])
        ),
        prefill_candidate_name=normalize_candidate_identity_name(
            personal_payload.get("full_name") or (active_account.get("full_name") if active_account else "")
        ),
        prefill_candidate_phone=normalize_candidate_phone(personal_payload.get("phone")),
        prefill_candidate_portfolio=normalize_candidate_portfolio_url(personal_payload.get("linkedin_url")),
        prefill_candidate_note=_normalize_profile_textarea(
            additional_payload.get("notes") or personal_payload.get("summary")
        ),
        profile_resume_document=profile_resume_document,
        opening_signin_url=build_career_public_url(
            "career.signin_page",
            flow="signin",
            next=url_for("career.opening_detail", opening_id=opening["id"]),
        ),
        opening_register_url=build_career_public_url(
            "career.signin_page",
            flow="signup",
            next=url_for("career.opening_detail", opening_id=opening["id"]),
        ),
    )


@career_bp.route("/karir/apply", methods=["POST"])
def apply():
    db = get_db()
    ensure_career_schema(db)
    active_account = _get_current_career_public_account(db)
    source_view = str(request.form.get("source_view") or "").strip().lower()
    personal_payload = _get_candidate_personal_profile_payload(db, active_account["id"]) if active_account else {}
    additional_payload = _get_candidate_additional_profile_payload(db, active_account["id"]) if active_account else {}
    try:
        profile_sections = get_career_public_profile_sections(db, active_account["id"]) if active_account else {}
    except TypeError:
        profile_sections = {}
    if personal_payload:
        profile_sections.setdefault("personal", {"payload": dict(personal_payload), "completion_state": "complete"})
    if additional_payload:
        profile_sections.setdefault("additional", {"payload": dict(additional_payload), "completion_state": "complete"})

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
    success_redirect_url = build_career_public_url("career.opening_detail", opening_id=opening["id"])
    if source_view == "portal_candidate":
        success_redirect_url = build_career_public_url(
            "career.portal_page",
            vacancy=opening["id"],
            applied=1,
        )
    failure_redirect_url = build_career_public_url("career.opening_detail", opening_id=opening["id"])
    if source_view == "portal_candidate":
        failure_redirect_url = build_career_public_url("career.portal_page", vacancy=opening["id"])
    if not active_account:
        flash("Silakan daftar atau masuk ke akun kandidat terlebih dahulu sebelum melamar posisi ini.", "error")
        return redirect(
            build_career_public_url(
                "career.signin_page",
                flow="signup",
                next=url_for("career.opening_detail", opening_id=opening["id"]),
            )
        )
    profile_gate, redirect_response = _guard_candidate_profile_completion(
        db,
        active_account,
        message="Lengkapi Data Pribadi dan Upload Berkas wajib terlebih dahulu sebelum mengirim lamaran.",
    )
    if redirect_response:
        return redirect_response

    raw_candidate_name = request.form.get("candidate_name")
    raw_phone = request.form.get("phone")
    raw_portfolio_url = request.form.get("portfolio_url")
    raw_phone_normalized = normalize_candidate_phone(raw_phone)
    raw_portfolio_url_normalized = normalize_candidate_portfolio_url(raw_portfolio_url)

    candidate_name = (
        normalize_candidate_identity_name(raw_candidate_name)
        or normalize_candidate_identity_name(personal_payload.get("full_name"))
        or active_account.get("full_name")
        or ""
    )
    phone = raw_phone_normalized or normalize_candidate_phone(personal_payload.get("phone"))
    email = normalize_candidate_email(active_account.get("email"))
    portfolio_url = raw_portfolio_url_normalized or normalize_candidate_portfolio_url(personal_payload.get("linkedin_url"))
    note = (request.form.get("note") or "").strip() or _normalize_profile_textarea(additional_payload.get("notes"))
    resume_file = request.files.get("resume_file")
    profile_documents = _collect_candidate_profile_documents(profile_sections)
    profile_resume_document = _get_primary_profile_resume_document(profile_documents)

    if not candidate_name or (not phone and not email):
        flash("Nama kandidat dan minimal satu kontak wajib diisi.", "error")
        return redirect(failure_redirect_url)
    if (raw_phone or "").strip() and not raw_phone_normalized:
        flash("Nomor telepon kandidat tidak valid.", "error")
        return redirect(failure_redirect_url)
    if (raw_portfolio_url or "").strip() and not raw_portfolio_url_normalized:
        flash("Link portofolio harus berupa URL http:// atau https:// yang valid.", "error")
        return redirect(failure_redirect_url)

    duplicate_candidate = find_duplicate_public_application(
        db,
        opening["id"],
        email=email,
        phone=phone,
    )
    if duplicate_candidate:
        existing_code = normalize_assessment_code(duplicate_candidate.get("assessment_code"))
        if source_view == "portal_candidate":
            return redirect(
                build_career_public_url(
                    "career.portal_page",
                    vacancy=opening["id"],
                    application_notice="duplicate_ready" if existing_code else "duplicate_pending",
                )
            )
        if existing_code:
            flash(
                "Lamaran untuk lowongan ini sudah pernah kami terima. Jika Anda sudah lolos screening HR, kode tes tetap bisa dilihat dari email atau dashboard lamaran kandidat.",
                "info",
            )
        else:
            flash(
                "Lamaran untuk lowongan ini sudah pernah kami terima dan masih menunggu screening HR. Silakan pantau email untuk update tahap berikutnya.",
                "info",
            )
        return redirect(failure_redirect_url)

    try:
        if resume_file and secure_filename(resume_file.filename or ""):
            resume_original_name, resume_path = save_career_resume(resume_file)
        else:
            resume_original_name, resume_path = _save_career_resume_from_profile_document(profile_resume_document)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(failure_redirect_url)

    if not resume_path:
        flash(
            "CV belum tersedia. Lengkapi upload CV / Resume di profil atau unggah file baru saat melamar.",
            "error",
        )
        return redirect(failure_redirect_url)

    profile_snapshot = _build_candidate_profile_snapshot(active_account, profile_sections)

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
            placement_warehouse_ids,
            resume_original_name,
            resume_path,
            public_account_id,
            profile_snapshot_json,
            profile_documents_json,
            updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
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
            encode_recruitment_homebase_ids([opening["warehouse_id"]]),
            resume_original_name,
            resume_path,
            int(active_account["id"] or 0),
            json.dumps(profile_snapshot, ensure_ascii=True, sort_keys=True),
            json.dumps(
                [
                    {
                        "document_type": item.get("document_type") or "other",
                        "label": item.get("label") or "Dokumen Kandidat",
                        "stored_name": item.get("stored_name") or "",
                        "uploaded_at": item.get("uploaded_at"),
                        "available_in_hr_storage": False,
                        "hr_storage_relative_path": "",
                    }
                    for item in profile_documents
                ],
                ensure_ascii=True,
                sort_keys=True,
            ),
        ),
    )

    created_candidate_id = _resolve_created_public_candidate_id(
        db,
        extract_inserted_row_id(insert_cursor),
        opening_id=opening["id"],
        public_account_id=active_account["id"],
        resume_path=resume_path,
    )
    if created_candidate_id > 0:
        hr_storage_folder, archived_files, archived_documents = _sync_candidate_hr_intake_storage(
            candidate_id=created_candidate_id,
            candidate_name=candidate_name,
            profile_snapshot=profile_snapshot,
            profile_documents=profile_documents,
            resume_original_name=resume_original_name,
            resume_stored_name=resume_path,
        )
        hr_sms_targets = _sync_candidate_intake_to_hr_sms_workspaces(db, hr_storage_folder)
        db.execute(
            """
            UPDATE recruitment_candidates
            SET profile_documents_json=?,
                hr_storage_folder=?,
                hr_storage_files_json=?,
                hr_sms_targets_json=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                json.dumps(archived_documents, ensure_ascii=True, sort_keys=True),
                hr_storage_folder or None,
                json.dumps(archived_files, ensure_ascii=True, sort_keys=True),
                json.dumps(hr_sms_targets, ensure_ascii=True, sort_keys=True),
                created_candidate_id,
            ),
        )
    db.commit()

    if source_view != "portal_candidate":
        flash(
            "Lamaran berhasil dikirim dan sudah masuk ke HRIS untuk screening. Jika lolos review awal, kode tes akan dikirim otomatis ke email Anda.",
            "success",
        )
    return redirect(success_redirect_url)


@career_bp.route("/karir/tes", methods=["GET", "POST"])
def assessment():
    db = get_db()
    ensure_career_schema(db)
    if request.method == "POST":
        assessment_code = normalize_assessment_code(request.form.get("assessment_code"))
        if not assessment_code:
            flash("Masukkan kode tes 5 digit yang valid.", "error")
            return redirect(build_career_public_url("career.assessment"))
        return redirect(build_career_public_url("career.assessment", code=assessment_code))

    current_dt = datetime.now()
    assessment_code = normalize_assessment_code(request.args.get("code"))
    if not assessment_code:
        return render_template(
            "career_assessment_entry.html",
            assessment_entry_action=build_career_public_url("career.assessment"),
            assessment_prefill_code="",
        )

    candidate = _fetch_candidate_by_assessment_code(db, assessment_code)
    if not candidate:
        flash("Kode tes tidak ditemukan.", "error")
        return redirect(build_career_public_url("career.assessment"))
    if str(candidate.get("status") or "").strip().lower() != "active":
        flash("Sesi tes ini sudah tidak aktif. Silakan tunggu update terbaru dari tim HR.", "error")
        return redirect(build_career_public_url("career.assessment"))

    questions = _fetch_public_assessment_questions(db, candidate.get("warehouse_id"), shuffle_seed=assessment_code)
    if not questions:
        flash("Soal tes belum disiapkan HR untuk posisi ini.", "error")
        return redirect(build_career_public_url("career.assessment"))

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
        return redirect(build_career_public_url("career.assessment"))

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
        return redirect(build_career_public_url("career.assessment"))

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
    if str(candidate.get("status") or "").strip().lower() != "active":
        return jsonify({"ok": False, "message": "Sesi tes ini sudah tidak aktif."}), 403

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
    if str(candidate.get("status") or "").strip().lower() != "active":
        flash("Sesi tes ini sudah tidak aktif. Silakan tunggu update terbaru dari tim HR.", "error")
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
