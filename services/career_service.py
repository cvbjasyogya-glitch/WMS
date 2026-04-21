import json
import os
import random
import re
import secrets
import hashlib
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from flask import current_app
from werkzeug.utils import secure_filename

from database import is_postgresql_backend


CAREER_OPENING_STATUSES = {"draft", "published", "closed", "archived"}
CAREER_EMPLOYMENT_TYPES = {
    "full_time",
    "part_time",
    "contract",
    "internship",
    "freelance",
}
CAREER_RESUME_EXTENSIONS = {".pdf", ".doc", ".docx"}
CAREER_APPLICATION_CHANNELS = {"public_portal", "manual_hr"}
CAREER_ASSESSMENT_STATUSES = {"pending", "started", "submitted", "reviewed"}
CAREER_ASSESSMENT_CORRECT_OPTIONS = {"a", "b", "c", "d"}
CAREER_PUBLIC_ACCOUNT_REQUEST_STATUSES = {"pending", "processed", "declined"}
CAREER_PUBLIC_ACCOUNT_STATUSES = {"pending", "active", "disabled"}
CAREER_DUPLICATE_APPLICATION_STATUSES = {"active", "on_hold"}
CAREER_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CAREER_PUBLIC_PROFILE_SECTION_KEYS = {
    "personal",
    "family",
    "education",
    "experience",
    "skills",
    "organization",
    "training",
    "achievement",
    "language",
    "passion",
    "additional",
    "documents",
}
CAREER_PUBLIC_PROFILE_COMPLETION_STATES = {"incomplete", "recommended", "complete"}


def normalize_career_opening_status(value):
    status = (value or "").strip().lower()
    return status if status in CAREER_OPENING_STATUSES else "draft"


def normalize_career_employment_type(value):
    employment_type = (value or "").strip().lower()
    return employment_type if employment_type in CAREER_EMPLOYMENT_TYPES else "full_time"


def normalize_career_application_channel(value):
    channel = (value or "").strip().lower()
    return channel if channel in CAREER_APPLICATION_CHANNELS else "manual_hr"


def normalize_career_assessment_status(value):
    status = (value or "").strip().lower()
    return status if status in CAREER_ASSESSMENT_STATUSES else "pending"


def normalize_career_public_account_request_status(value):
    status = (value or "").strip().lower()
    return status if status in CAREER_PUBLIC_ACCOUNT_REQUEST_STATUSES else "pending"


def normalize_career_public_account_status(value):
    status = (value or "").strip().lower()
    return status if status in CAREER_PUBLIC_ACCOUNT_STATUSES else "pending"


def normalize_career_public_profile_section_key(value):
    safe_key = str(value or "").strip().lower().replace("-", "_")
    return safe_key if safe_key in CAREER_PUBLIC_PROFILE_SECTION_KEYS else ""


def normalize_career_public_profile_completion_state(value):
    safe_state = str(value or "").strip().lower()
    return safe_state if safe_state in CAREER_PUBLIC_PROFILE_COMPLETION_STATES else "incomplete"


def normalize_candidate_identity_name(value):
    return " ".join(str(value or "").strip().split())


def normalize_candidate_email(value):
    safe_email = str(value or "").strip().lower()
    if not safe_email:
        return ""
    return safe_email if CAREER_EMAIL_PATTERN.match(safe_email) else ""


def normalize_candidate_phone(value):
    digits = "".join(char for char in str(value or "") if char.isdigit())
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0"):
        digits = f"62{digits[1:]}"
    elif not digits.startswith("62") and len(digits) >= 8:
        digits = f"62{digits.lstrip('0')}"
    return digits if len(digits) >= 10 else ""


def normalize_candidate_portfolio_url(value):
    safe_value = str(value or "").strip()
    if not safe_value:
        return ""
    if any(char.isspace() for char in safe_value):
        return ""
    if "://" not in safe_value:
        safe_value = f"https://{safe_value.lstrip('/')}"
    try:
        parsed = urlsplit(safe_value)
    except Exception:
        return ""
    scheme = str(parsed.scheme or "").strip().lower()
    host = str(parsed.hostname or "").strip().lower()
    if scheme not in {"http", "https"} or not host or "." not in host:
        return ""
    if parsed.username or parsed.password:
        return ""
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    return urlunsplit((scheme, netloc, parsed.path or "", parsed.query or "", parsed.fragment or ""))


def normalize_assessment_code(value):
    safe_value = "".join(ch for ch in str(value or "") if ch.isdigit())
    return safe_value if len(safe_value) == 5 else ""


def normalize_assessment_option(value):
    safe_value = (value or "").strip().lower()
    return safe_value if safe_value in CAREER_ASSESSMENT_CORRECT_OPTIONS else ""


def hash_career_public_verification_token(token):
    safe_token = str(token or "").strip()
    if not safe_token:
        return ""
    return hashlib.sha256(safe_token.encode("utf-8")).hexdigest()


def decode_career_public_profile_payload(raw_value):
    if raw_value in (None, ""):
        return {}
    try:
        payload = json.loads(raw_value)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def encode_career_public_profile_payload(payload):
    safe_payload = payload if isinstance(payload, dict) else {}
    return json.dumps(safe_payload, ensure_ascii=True, sort_keys=True)


def normalize_assessment_duration_minutes(value, default=0, maximum=720):
    try:
        safe_value = int(str(value or "").strip())
    except (TypeError, ValueError):
        return default
    if safe_value <= 0:
        return default
    if maximum and safe_value > int(maximum):
        return int(maximum)
    return safe_value


def normalize_recruitment_homebase_ids(values):
    if values is None:
        return []

    raw_items = values
    if isinstance(values, str):
        safe_value = values.strip()
        if not safe_value:
            return []
        try:
            parsed = json.loads(safe_value)
            raw_items = parsed if isinstance(parsed, (list, tuple, set)) else [parsed]
        except Exception:
            raw_items = re.split(r"[\s,|]+", safe_value)

    if not isinstance(raw_items, (list, tuple, set)):
        raw_items = [raw_items]

    normalized = []
    seen = set()
    for raw_item in raw_items:
        try:
            safe_id = int(str(raw_item or "").strip())
        except (TypeError, ValueError):
            continue
        if safe_id <= 0 or safe_id in seen:
            continue
        seen.add(safe_id)
        normalized.append(safe_id)
    return normalized


def encode_recruitment_homebase_ids(values):
    normalized = normalize_recruitment_homebase_ids(values)
    return json.dumps(normalized) if normalized else None


def _get_table_columns(db, table_name):
    safe_name = str(table_name or "").strip()
    if not safe_name:
        return set()
    try:
        rows = db.execute(f"PRAGMA table_info({safe_name})").fetchall()
    except Exception:
        return set()
    columns = set()
    for row in rows:
        try:
            columns.add(str(row["name"]))
        except Exception:
            if isinstance(row, (list, tuple)) and len(row) > 1:
                columns.add(str(row[1]))
    return columns


def _sqlite_ensure_column(db, table_name, column_name, definition):
    columns = _get_table_columns(db, table_name)
    if columns and column_name not in columns:
        db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _ensure_postgresql_id_sequence(db, table_name):
    default_row = db.execute(
        """
        SELECT column_default
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name=?
          AND column_name='id'
        """,
        (table_name,),
    ).fetchone()
    try:
        column_default = str(default_row["column_default"] or "").lower()
    except Exception:
        column_default = ""
    if "nextval(" in column_default:
        return

    sequence_name = f"{table_name}_id_seq"
    db.execute(f"CREATE SEQUENCE IF NOT EXISTS {sequence_name}")
    db.execute(f"ALTER SEQUENCE {sequence_name} OWNED BY {table_name}.id")
    db.execute(
        f"ALTER TABLE {table_name} ALTER COLUMN id SET DEFAULT nextval('{sequence_name}')"
    )
    db.execute(
        f"SELECT setval('{sequence_name}', COALESCE((SELECT MAX(id) FROM {table_name}), 0) + 1, false)"
    )


def extract_inserted_row_id(cursor):
    try:
        inserted_id = int(getattr(cursor, "lastrowid", 0) or 0)
    except (TypeError, ValueError):
        inserted_id = 0
    return inserted_id if inserted_id > 0 else 0


def find_duplicate_public_application(
    db,
    opening_id,
    *,
    email="",
    phone="",
    public_account_id=0,
    exclude_candidate_id=0,
):
    try:
        safe_opening_id = int(opening_id or 0)
    except (TypeError, ValueError):
        safe_opening_id = 0
    if safe_opening_id <= 0:
        return None

    normalized_email = normalize_candidate_email(email)
    normalized_phone = normalize_candidate_phone(phone)
    try:
        safe_public_account_id = int(public_account_id or 0)
    except (TypeError, ValueError):
        safe_public_account_id = 0
    if not normalized_email and not normalized_phone:
        return None

    rows = db.execute(
        """
        SELECT
            id,
            candidate_name,
            phone,
            email,
            public_account_id,
            assessment_code,
            stage,
            status,
            created_at
        FROM recruitment_candidates
        WHERE vacancy_id=?
          AND application_channel=?
          AND id<>?
          AND status IN (?, ?)
        ORDER BY created_at DESC, id DESC
        """,
        (
            safe_opening_id,
            normalize_career_application_channel("public_portal"),
            int(exclude_candidate_id or 0),
            "active",
            "on_hold",
        ),
    ).fetchall()

    for row in rows:
        row_dict = dict(row)
        row_email = normalize_candidate_email(row_dict.get("email"))
        row_phone = normalize_candidate_phone(row_dict.get("phone"))
        try:
            row_public_account_id = int(row_dict.get("public_account_id") or 0)
        except (TypeError, ValueError):
            row_public_account_id = 0
        if safe_public_account_id > 0 and row_public_account_id == safe_public_account_id:
            return row_dict
        if normalized_email and row_email == normalized_email:
            return row_dict
        if not normalized_email and normalized_phone and row_phone == normalized_phone:
            return row_dict
    return None


def ensure_career_schema(db):
    runtime_state = current_app.extensions.setdefault("career_runtime_state", {})
    backend = "postgresql" if is_postgresql_backend(current_app.config) else "sqlite"
    cache_key = f"schema_ready:{backend}"
    if runtime_state.get(cache_key):
        return

    if backend == "postgresql":
        statements = [
            """
            CREATE TABLE IF NOT EXISTS career_openings(
                id SERIAL PRIMARY KEY,
                warehouse_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                department TEXT,
                employment_type TEXT DEFAULT 'full_time',
                location_label TEXT,
                description TEXT,
                requirements TEXT,
                status TEXT DEFAULT 'draft',
                is_public INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_by INTEGER,
                updated_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS warehouse_id INTEGER",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS title TEXT",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS department TEXT",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS employment_type TEXT DEFAULT 'full_time'",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS location_label TEXT",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS description TEXT",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS requirements TEXT",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'draft'",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS is_public INTEGER DEFAULT 1",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS created_by INTEGER",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS updated_by INTEGER",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE career_openings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS vacancy_id INTEGER",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS application_channel TEXT DEFAULT 'manual_hr'",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS portfolio_url TEXT",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS resume_original_name TEXT",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS resume_path TEXT",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_code TEXT",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_status TEXT DEFAULT 'pending'",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_started_at TIMESTAMP",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_submitted_at TIMESTAMP",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_answers_json TEXT",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_auto_score DOUBLE PRECISION DEFAULT 0",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_manual_score DOUBLE PRECISION",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_final_score DOUBLE PRECISION DEFAULT 0",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_review_notes TEXT",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_reviewed_by INTEGER",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_reviewed_at TIMESTAMP",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_violation_count INTEGER DEFAULT 0",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_expires_at TIMESTAMP",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS assessment_duration_minutes INTEGER DEFAULT 0",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS placement_warehouse_ids TEXT",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS public_account_id INTEGER",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS profile_snapshot_json TEXT",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS profile_documents_json TEXT",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS hr_storage_folder TEXT",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS hr_storage_files_json TEXT",
            "ALTER TABLE recruitment_candidates ADD COLUMN IF NOT EXISTS hr_sms_targets_json TEXT",
            """
            CREATE TABLE IF NOT EXISTS recruitment_assessment_questions(
                id SERIAL PRIMARY KEY,
                warehouse_id INTEGER,
                prompt TEXT NOT NULL,
                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                option_c TEXT NOT NULL,
                option_d TEXT NOT NULL,
                correct_option TEXT NOT NULL,
                score_weight INTEGER DEFAULT 10,
                sort_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_by INTEGER,
                updated_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS warehouse_id INTEGER",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS prompt TEXT",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS option_a TEXT",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS option_b TEXT",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS option_c TEXT",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS option_d TEXT",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS correct_option TEXT",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS score_weight INTEGER DEFAULT 10",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS is_active INTEGER DEFAULT 1",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS created_by INTEGER",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS updated_by INTEGER",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE recruitment_assessment_questions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "CREATE INDEX IF NOT EXISTS idx_career_openings_public ON career_openings(status, is_public, warehouse_id, sort_order)",
            "CREATE INDEX IF NOT EXISTS idx_recruitment_candidates_vacancy ON recruitment_candidates(vacancy_id, warehouse_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_recruitment_candidates_public_lookup ON recruitment_candidates(vacancy_id, application_channel, status, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_recruitment_candidates_public_account ON recruitment_candidates(public_account_id, created_at)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_recruitment_candidates_assessment_code ON recruitment_candidates(assessment_code)",
            "CREATE INDEX IF NOT EXISTS idx_recruitment_assessment_questions_scope ON recruitment_assessment_questions(is_active, warehouse_id, sort_order)",
            """
            CREATE TABLE IF NOT EXISTS career_public_account_requests(
                id SERIAL PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                source TEXT DEFAULT 'career_public',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "ALTER TABLE career_public_account_requests ADD COLUMN IF NOT EXISTS full_name TEXT",
            "ALTER TABLE career_public_account_requests ADD COLUMN IF NOT EXISTS email TEXT",
            "ALTER TABLE career_public_account_requests ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'",
            "ALTER TABLE career_public_account_requests ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'career_public'",
            "ALTER TABLE career_public_account_requests ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE career_public_account_requests ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "CREATE INDEX IF NOT EXISTS idx_career_public_account_requests_email ON career_public_account_requests(email, status, created_at)",
            """
            CREATE TABLE IF NOT EXISTS career_public_accounts(
                id SERIAL PRIMARY KEY,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                email_verified_at TIMESTAMP,
                verification_token_hash TEXT,
                verification_sent_at TIMESTAMP,
                verification_expires_at TIMESTAMP,
                last_login_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "ALTER TABLE career_public_accounts ADD COLUMN IF NOT EXISTS full_name TEXT",
            "ALTER TABLE career_public_accounts ADD COLUMN IF NOT EXISTS email TEXT",
            "ALTER TABLE career_public_accounts ADD COLUMN IF NOT EXISTS password_hash TEXT",
            "ALTER TABLE career_public_accounts ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'",
            "ALTER TABLE career_public_accounts ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP",
            "ALTER TABLE career_public_accounts ADD COLUMN IF NOT EXISTS verification_token_hash TEXT",
            "ALTER TABLE career_public_accounts ADD COLUMN IF NOT EXISTS verification_sent_at TIMESTAMP",
            "ALTER TABLE career_public_accounts ADD COLUMN IF NOT EXISTS verification_expires_at TIMESTAMP",
            "ALTER TABLE career_public_accounts ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP",
            "ALTER TABLE career_public_accounts ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "ALTER TABLE career_public_accounts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_career_public_accounts_email ON career_public_accounts(email)",
            "CREATE INDEX IF NOT EXISTS idx_career_public_accounts_verification ON career_public_accounts(verification_token_hash, status)",
            """
            CREATE TABLE IF NOT EXISTS career_public_saved_openings(
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                opening_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_career_public_saved_openings_unique ON career_public_saved_openings(account_id, opening_id)",
            "CREATE INDEX IF NOT EXISTS idx_career_public_saved_openings_account ON career_public_saved_openings(account_id, created_at)",
            """
            CREATE TABLE IF NOT EXISTS career_public_profile_sections(
                id SERIAL PRIMARY KEY,
                account_id INTEGER NOT NULL,
                section_key TEXT NOT NULL,
                payload_json TEXT,
                completion_state TEXT DEFAULT 'incomplete',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """,
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_career_public_profile_sections_unique ON career_public_profile_sections(account_id, section_key)",
            "CREATE INDEX IF NOT EXISTS idx_career_public_profile_sections_account ON career_public_profile_sections(account_id, updated_at)",
        ]
        for statement in statements:
            db.execute(statement)
        _ensure_postgresql_id_sequence(db, "career_openings")
        _ensure_postgresql_id_sequence(db, "recruitment_candidates")
        _ensure_postgresql_id_sequence(db, "recruitment_assessment_questions")
        _ensure_postgresql_id_sequence(db, "career_public_account_requests")
        _ensure_postgresql_id_sequence(db, "career_public_accounts")
        _ensure_postgresql_id_sequence(db, "career_public_saved_openings")
        _ensure_postgresql_id_sequence(db, "career_public_profile_sections")
    else:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS career_openings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                warehouse_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                department TEXT,
                employment_type TEXT DEFAULT 'full_time',
                location_label TEXT,
                description TEXT,
                requirements TEXT,
                status TEXT DEFAULT 'draft',
                is_public INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_by INTEGER,
                updated_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
                FOREIGN KEY(created_by) REFERENCES users(id),
                FOREIGN KEY(updated_by) REFERENCES users(id)
            )
            """
        )
        _sqlite_ensure_column(db, "recruitment_candidates", "vacancy_id", "INTEGER")
        _sqlite_ensure_column(
            db,
            "recruitment_candidates",
            "application_channel",
            "TEXT DEFAULT 'manual_hr'",
        )
        _sqlite_ensure_column(db, "recruitment_candidates", "portfolio_url", "TEXT")
        _sqlite_ensure_column(db, "recruitment_candidates", "resume_original_name", "TEXT")
        _sqlite_ensure_column(db, "recruitment_candidates", "resume_path", "TEXT")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_code", "TEXT")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_status", "TEXT DEFAULT 'pending'")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_started_at", "TIMESTAMP")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_submitted_at", "TIMESTAMP")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_answers_json", "TEXT")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_auto_score", "REAL DEFAULT 0")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_manual_score", "REAL")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_final_score", "REAL DEFAULT 0")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_review_notes", "TEXT")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_reviewed_by", "INTEGER")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_reviewed_at", "TIMESTAMP")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_violation_count", "INTEGER DEFAULT 0")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_expires_at", "TIMESTAMP")
        _sqlite_ensure_column(db, "recruitment_candidates", "assessment_duration_minutes", "INTEGER DEFAULT 0")
        _sqlite_ensure_column(db, "recruitment_candidates", "placement_warehouse_ids", "TEXT")
        _sqlite_ensure_column(db, "recruitment_candidates", "public_account_id", "INTEGER")
        _sqlite_ensure_column(db, "recruitment_candidates", "profile_snapshot_json", "TEXT")
        _sqlite_ensure_column(db, "recruitment_candidates", "profile_documents_json", "TEXT")
        _sqlite_ensure_column(db, "recruitment_candidates", "hr_storage_folder", "TEXT")
        _sqlite_ensure_column(db, "recruitment_candidates", "hr_storage_files_json", "TEXT")
        _sqlite_ensure_column(db, "recruitment_candidates", "hr_sms_targets_json", "TEXT")
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS recruitment_assessment_questions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                warehouse_id INTEGER,
                prompt TEXT NOT NULL,
                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                option_c TEXT NOT NULL,
                option_d TEXT NOT NULL,
                correct_option TEXT NOT NULL,
                score_weight INTEGER DEFAULT 10,
                sort_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_by INTEGER,
                updated_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_career_openings_public ON career_openings(status, is_public, warehouse_id, sort_order)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_recruitment_candidates_vacancy ON recruitment_candidates(vacancy_id, warehouse_id, created_at)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_recruitment_candidates_public_lookup ON recruitment_candidates(vacancy_id, application_channel, status, created_at)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_recruitment_candidates_public_account ON recruitment_candidates(public_account_id, created_at)"
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_recruitment_candidates_assessment_code ON recruitment_candidates(assessment_code)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_recruitment_assessment_questions_scope ON recruitment_assessment_questions(is_active, warehouse_id, sort_order)"
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS career_public_account_requests(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                source TEXT DEFAULT 'career_public',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_career_public_account_requests_email ON career_public_account_requests(email, status, created_at)"
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS career_public_accounts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                email_verified_at TIMESTAMP,
                verification_token_hash TEXT,
                verification_sent_at TIMESTAMP,
                verification_expires_at TIMESTAMP,
                last_login_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _sqlite_ensure_column(db, "career_public_accounts", "full_name", "TEXT")
        _sqlite_ensure_column(db, "career_public_accounts", "email", "TEXT")
        _sqlite_ensure_column(db, "career_public_accounts", "password_hash", "TEXT")
        _sqlite_ensure_column(db, "career_public_accounts", "status", "TEXT DEFAULT 'pending'")
        _sqlite_ensure_column(db, "career_public_accounts", "email_verified_at", "TIMESTAMP")
        _sqlite_ensure_column(db, "career_public_accounts", "verification_token_hash", "TEXT")
        _sqlite_ensure_column(db, "career_public_accounts", "verification_sent_at", "TIMESTAMP")
        _sqlite_ensure_column(db, "career_public_accounts", "verification_expires_at", "TIMESTAMP")
        _sqlite_ensure_column(db, "career_public_accounts", "last_login_at", "TIMESTAMP")
        _sqlite_ensure_column(db, "career_public_accounts", "created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        _sqlite_ensure_column(db, "career_public_accounts", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_career_public_accounts_email ON career_public_accounts(email)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_career_public_accounts_verification ON career_public_accounts(verification_token_hash, status)"
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS career_public_saved_openings(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                opening_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_career_public_saved_openings_unique ON career_public_saved_openings(account_id, opening_id)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_career_public_saved_openings_account ON career_public_saved_openings(account_id, created_at)"
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS career_public_profile_sections(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                section_key TEXT NOT NULL,
                payload_json TEXT,
                completion_state TEXT DEFAULT 'incomplete',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_career_public_profile_sections_unique ON career_public_profile_sections(account_id, section_key)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_career_public_profile_sections_account ON career_public_profile_sections(account_id, updated_at)"
        )

    runtime_state[cache_key] = True


def create_public_account_request(db, full_name, email, source="career_public"):
    safe_name = " ".join(str(full_name or "").strip().split())
    safe_email = str(email or "").strip().lower()
    if not safe_name:
        raise ValueError("Nama lengkap wajib diisi.")
    if not safe_email or "@" not in safe_email:
        raise ValueError("Email wajib valid.")

    existing = db.execute(
        """
        SELECT id
        FROM career_public_account_requests
        WHERE LOWER(email)=LOWER(?)
          AND status=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (safe_email, normalize_career_public_account_request_status("pending")),
    ).fetchone()

    if existing:
        db.execute(
            """
            UPDATE career_public_account_requests
            SET full_name=?,
                source=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                safe_name,
                (source or "career_public").strip() or "career_public",
                existing["id"],
            ),
        )
        request_id = int(existing["id"])
    else:
        insert_cursor = db.execute(
            """
            INSERT INTO career_public_account_requests(
                full_name,
                email,
                status,
                source,
                updated_at
            )
            VALUES (?,?,?,?,CURRENT_TIMESTAMP)
            """,
            (
                safe_name,
                safe_email,
                normalize_career_public_account_request_status("pending"),
                (source or "career_public").strip() or "career_public",
            ),
        )
        request_id = extract_inserted_row_id(insert_cursor)
        if request_id <= 0:
            created = db.execute(
                """
                SELECT id
                FROM career_public_account_requests
                WHERE LOWER(email)=LOWER(?)
                ORDER BY id DESC
                LIMIT 1
                """,
                (safe_email,),
            ).fetchone()
            request_id = int(created["id"]) if created else 0

    row = db.execute(
        """
        SELECT *
        FROM career_public_account_requests
        WHERE id=?
        LIMIT 1
        """,
        (request_id,),
    ).fetchone()
    return dict(row) if row else None


def mark_public_account_request_status_by_email(db, email, status="processed"):
    safe_email = normalize_candidate_email(email)
    safe_status = normalize_career_public_account_request_status(status)
    if not safe_email:
        return 0
    result = db.execute(
        """
        UPDATE career_public_account_requests
        SET status=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE LOWER(email)=LOWER(?)
        """,
        (safe_status, safe_email),
    )
    return int(getattr(result, "rowcount", 0) or 0)


def get_career_public_account_by_email(db, email):
    safe_email = normalize_candidate_email(email)
    if not safe_email:
        return None
    row = db.execute(
        """
        SELECT *
        FROM career_public_accounts
        WHERE LOWER(email)=LOWER(?)
        LIMIT 1
        """,
        (safe_email,),
    ).fetchone()
    return dict(row) if row else None


def get_career_public_account_by_id(db, account_id):
    try:
        safe_account_id = int(account_id)
    except (TypeError, ValueError):
        return None
    if safe_account_id <= 0:
        return None
    row = db.execute(
        """
        SELECT *
        FROM career_public_accounts
        WHERE id=?
        LIMIT 1
        """,
        (safe_account_id,),
    ).fetchone()
    return dict(row) if row else None


def upsert_career_public_account(db, full_name, email, password_hash):
    safe_name = normalize_candidate_identity_name(full_name)
    safe_email = normalize_candidate_email(email)
    safe_password_hash = str(password_hash or "").strip()
    if not safe_name:
        raise ValueError("Nama lengkap wajib diisi.")
    if not safe_email:
        raise ValueError("Email wajib valid.")
    if not safe_password_hash:
        raise ValueError("Kata sandi akun belum valid.")

    existing = get_career_public_account_by_email(db, safe_email)
    if existing:
        current_status = normalize_career_public_account_status(existing.get("status"))
        if current_status == "active":
            raise ValueError("Email ini sudah terdaftar. Silakan masuk ke akun Anda.")
        if current_status == "disabled":
            raise ValueError("Akun ini dinonaktifkan. Silakan hubungi HR untuk bantuan lebih lanjut.")
        db.execute(
            """
            UPDATE career_public_accounts
            SET full_name=?,
                password_hash=?,
                status=?,
                email_verified_at=NULL,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                safe_name,
                safe_password_hash,
                normalize_career_public_account_status("pending"),
                existing["id"],
            ),
        )
        return get_career_public_account_by_id(db, existing["id"])

    insert_cursor = db.execute(
        """
        INSERT INTO career_public_accounts(
            full_name,
            email,
            password_hash,
            status,
            updated_at
        )
        VALUES (?,?,?,?,CURRENT_TIMESTAMP)
        """,
        (
            safe_name,
            safe_email,
            safe_password_hash,
            normalize_career_public_account_status("pending"),
        ),
    )
    account_id = extract_inserted_row_id(insert_cursor)
    if account_id <= 0:
        created = get_career_public_account_by_email(db, safe_email)
        account_id = int(created["id"]) if created else 0
    return get_career_public_account_by_id(db, account_id)


def issue_career_public_account_verification(db, account_id, ttl_hours=24):
    account = get_career_public_account_by_id(db, account_id)
    if not account:
        raise ValueError("Akun kandidat tidak ditemukan.")
    safe_ttl = max(int(ttl_hours or 24), 1)
    token = secrets.token_urlsafe(32)
    token_hash = hash_career_public_verification_token(token)
    expires_at = (datetime.now() + timedelta(hours=safe_ttl)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """
        UPDATE career_public_accounts
        SET verification_token_hash=?,
            verification_sent_at=CURRENT_TIMESTAMP,
            verification_expires_at=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (token_hash, expires_at, account["id"]),
    )
    return token


def get_career_public_account_by_verification_token(db, token):
    token_hash = hash_career_public_verification_token(token)
    if not token_hash:
        return None
    row = db.execute(
        """
        SELECT *
        FROM career_public_accounts
        WHERE verification_token_hash=?
        LIMIT 1
        """,
        (token_hash,),
    ).fetchone()
    return dict(row) if row else None


def activate_career_public_account(db, account_id):
    account = get_career_public_account_by_id(db, account_id)
    if not account:
        return None
    db.execute(
        """
        UPDATE career_public_accounts
        SET status=?,
            email_verified_at=COALESCE(email_verified_at, CURRENT_TIMESTAMP),
            verification_token_hash=NULL,
            verification_sent_at=NULL,
            verification_expires_at=NULL,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (
            normalize_career_public_account_status("active"),
            account["id"],
        ),
    )
    return get_career_public_account_by_id(db, account["id"])


def touch_career_public_account_login(db, account_id):
    account = get_career_public_account_by_id(db, account_id)
    if not account:
        return None
    db.execute(
        """
        UPDATE career_public_accounts
        SET last_login_at=CURRENT_TIMESTAMP,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (account["id"],),
    )
    return get_career_public_account_by_id(db, account["id"])


def update_career_public_account_password_hash(db, account_id, password_hash):
    account = get_career_public_account_by_id(db, account_id)
    safe_password_hash = str(password_hash or "").strip()
    if not account or not safe_password_hash:
        return None
    db.execute(
        """
        UPDATE career_public_accounts
        SET password_hash=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (safe_password_hash, account["id"]),
    )
    return get_career_public_account_by_id(db, account["id"])


def get_career_public_profile_sections(db, account_id):
    try:
        safe_account_id = int(account_id or 0)
    except (TypeError, ValueError):
        safe_account_id = 0
    if safe_account_id <= 0:
        return {}
    rows = db.execute(
        """
        SELECT section_key, payload_json, completion_state, updated_at
        FROM career_public_profile_sections
        WHERE account_id=?
        ORDER BY section_key ASC
        """,
        (safe_account_id,),
    ).fetchall()
    sections = {}
    for row in rows:
        row_dict = dict(row)
        section_key = normalize_career_public_profile_section_key(row_dict.get("section_key"))
        if not section_key:
            continue
        sections[section_key] = {
            "payload": decode_career_public_profile_payload(row_dict.get("payload_json")),
            "completion_state": normalize_career_public_profile_completion_state(row_dict.get("completion_state")),
            "updated_at": row_dict.get("updated_at"),
        }
    return sections


def upsert_career_public_profile_section(db, account_id, section_key, payload, completion_state="incomplete"):
    try:
        safe_account_id = int(account_id or 0)
    except (TypeError, ValueError):
        safe_account_id = 0
    safe_section_key = normalize_career_public_profile_section_key(section_key)
    safe_completion_state = normalize_career_public_profile_completion_state(completion_state)
    if safe_account_id <= 0 or not safe_section_key:
        raise ValueError("Bagian profil kandidat tidak valid.")

    payload_json = encode_career_public_profile_payload(payload)
    existing = db.execute(
        """
        SELECT id
        FROM career_public_profile_sections
        WHERE account_id=? AND section_key=?
        LIMIT 1
        """,
        (safe_account_id, safe_section_key),
    ).fetchone()
    if existing:
        db.execute(
            """
            UPDATE career_public_profile_sections
            SET payload_json=?,
                completion_state=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (payload_json, safe_completion_state, existing["id"]),
        )
    else:
        db.execute(
            """
            INSERT INTO career_public_profile_sections(
                account_id,
                section_key,
                payload_json,
                completion_state,
                updated_at
            )
            VALUES (?,?,?,?,CURRENT_TIMESTAMP)
            """,
            (safe_account_id, safe_section_key, payload_json, safe_completion_state),
        )
    return get_career_public_profile_sections(db, safe_account_id).get(safe_section_key)


def get_career_public_saved_opening_ids(db, account_id):
    try:
        safe_account_id = int(account_id or 0)
    except (TypeError, ValueError):
        safe_account_id = 0
    if safe_account_id <= 0:
        return set()
    rows = db.execute(
        """
        SELECT opening_id
        FROM career_public_saved_openings
        WHERE account_id=?
        ORDER BY created_at DESC, id DESC
        """,
        (safe_account_id,),
    ).fetchall()
    opening_ids = set()
    for row in rows:
        try:
            opening_id = int(row["opening_id"] or 0)
        except (TypeError, ValueError):
            opening_id = 0
        if opening_id > 0:
            opening_ids.add(opening_id)
    return opening_ids


def set_career_public_saved_opening_state(db, account_id, opening_id, is_saved=True):
    try:
        safe_account_id = int(account_id or 0)
        safe_opening_id = int(opening_id or 0)
    except (TypeError, ValueError):
        safe_account_id = 0
        safe_opening_id = 0
    if safe_account_id <= 0 or safe_opening_id <= 0:
        raise ValueError("Lowongan tersimpan tidak valid.")

    existing = db.execute(
        """
        SELECT id
        FROM career_public_saved_openings
        WHERE account_id=? AND opening_id=?
        LIMIT 1
        """,
        (safe_account_id, safe_opening_id),
    ).fetchone()
    if is_saved:
        if not existing:
            db.execute(
                """
                INSERT INTO career_public_saved_openings(account_id, opening_id)
                VALUES (?,?)
                """,
                (safe_account_id, safe_opening_id),
            )
        return True

    if existing:
        db.execute(
            "DELETE FROM career_public_saved_openings WHERE id=?",
            (existing["id"],),
        )
    return False


def generate_unique_assessment_code(db):
    for _ in range(120):
        code = f"{random.randint(0, 99999):05d}"
        existing = db.execute(
            "SELECT id FROM recruitment_candidates WHERE assessment_code=? LIMIT 1",
            (code,),
        ).fetchone()
        if not existing:
            return code
    raise RuntimeError("Tidak bisa membuat kode tes unik. Coba lagi.")


def _is_assessment_code_unique_violation(exc):
    safe_message = str(exc or "").lower()
    return "idx_recruitment_candidates_assessment_code" in safe_message or "assessment_code" in safe_message


def assign_candidate_assessment_code(db, candidate_id, preferred_code=""):
    safe_preferred = normalize_assessment_code(preferred_code)
    if safe_preferred:
        existing = db.execute(
            "SELECT id FROM recruitment_candidates WHERE assessment_code=? AND id<>? LIMIT 1",
            (safe_preferred, candidate_id),
        ).fetchone()
        if existing:
            raise ValueError("Kode tes sudah dipakai kandidat lain.")
        safe_code = safe_preferred
        db.execute(
            """
            UPDATE recruitment_candidates
            SET assessment_code=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (safe_code, candidate_id),
        )
        return safe_code

    for _ in range(20):
        safe_code = generate_unique_assessment_code(db)
        try:
            db.execute(
                """
                UPDATE recruitment_candidates
                SET assessment_code=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (safe_code, candidate_id),
            )
            return safe_code
        except sqlite3.IntegrityError as exc:
            if not _is_assessment_code_unique_violation(exc):
                raise
    raise RuntimeError("Tidak bisa membuat kode tes unik karena bentrok berulang. Coba lagi.")


def ensure_candidate_assessment_code(db, candidate_id, current_code=""):
    safe_current = normalize_assessment_code(current_code)
    if safe_current:
        return safe_current
    return assign_candidate_assessment_code(db, candidate_id)


def decode_assessment_answers(raw_value):
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    safe_payload = {}
    for key, value in payload.items():
        try:
            question_id = int(key)
        except Exception:
            continue
        answer = normalize_assessment_option(value)
        if answer:
            safe_payload[question_id] = answer
    return safe_payload


def encode_assessment_answers(answers):
    safe_payload = {}
    for key, value in (answers or {}).items():
        try:
            question_id = int(key)
        except Exception:
            continue
        answer = normalize_assessment_option(value)
        if answer:
            safe_payload[str(question_id)] = answer
    return json.dumps(safe_payload, ensure_ascii=True, sort_keys=True)


def score_assessment_questions(questions, answers):
    safe_answers = decode_assessment_answers(answers) if isinstance(answers, str) else {
        int(key): normalize_assessment_option(value)
        for key, value in (answers or {}).items()
        if str(key).strip().isdigit() and normalize_assessment_option(value)
    }
    total_weight = 0
    earned = 0
    answered = 0
    scored_questions = []

    for question in questions or []:
        question_id = int(question.get("id") or 0)
        if question_id <= 0:
            continue
        weight = max(int(question.get("score_weight") or 0), 0)
        total_weight += weight
        correct_option = normalize_assessment_option(question.get("correct_option"))
        candidate_option = normalize_assessment_option(safe_answers.get(question_id))
        is_correct = bool(candidate_option and candidate_option == correct_option)
        if candidate_option:
            answered += 1
        if is_correct:
            earned += weight
        scored_questions.append(
            {
                **question,
                "candidate_option": candidate_option,
                "is_correct": is_correct,
            }
        )

    percentage = round((earned / total_weight) * 100, 2) if total_weight > 0 else 0.0
    return {
        "answered": answered,
        "earned": earned,
        "total_weight": total_weight,
        "percentage": percentage,
        "questions": scored_questions,
    }


def get_career_resume_root():
    configured_root = (current_app.config.get("CAREER_RESUME_UPLOAD_FOLDER") or "").strip()
    root_path = configured_root or os.path.join(current_app.instance_path, "career_resumes")
    os.makedirs(root_path, exist_ok=True)
    return root_path


def save_career_resume(file_storage):
    if file_storage is None:
        return None, None

    original_name = secure_filename(file_storage.filename or "")
    if not original_name:
        return None, None

    extension = os.path.splitext(original_name)[1].lower()
    if extension not in CAREER_RESUME_EXTENSIONS:
        raise ValueError("Format CV harus PDF, DOC, atau DOCX.")

    storage_root = get_career_resume_root()
    stored_name = f"{uuid4().hex}{extension}"
    absolute_path = os.path.join(storage_root, stored_name)
    file_storage.save(absolute_path)
    return original_name, stored_name


def build_career_resume_path(stored_name):
    safe_name = secure_filename(stored_name or "")
    if not safe_name:
        return ""
    return os.path.join(get_career_resume_root(), safe_name)


def get_sms_storage_base_root():
    configured_root = str(current_app.config.get("SMS_STORAGE_ROOT") or "").strip()
    root_path = configured_root or os.path.join(current_app.instance_path, "sms_storage", "storage")
    os.makedirs(root_path, exist_ok=True)
    return os.path.abspath(root_path)


def build_sms_user_storage_root(user_id):
    try:
        safe_user_id = int(user_id or 0)
    except (TypeError, ValueError):
        safe_user_id = 0
    if safe_user_id <= 0:
        return ""
    root_path = os.path.join(get_sms_storage_base_root(), f"user_{safe_user_id}")
    os.makedirs(root_path, exist_ok=True)
    return os.path.abspath(root_path)


def build_sms_storage_absolute_path(relative_path=""):
    base_root = get_sms_storage_base_root()
    cleaned = str(relative_path or "").replace("\\", "/").strip().strip("/")
    if not cleaned:
        return base_root
    normalized = os.path.normpath(cleaned).replace("\\", "/").strip()
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        return ""
    absolute_path = os.path.abspath(os.path.join(base_root, normalized))
    if absolute_path != base_root and not absolute_path.startswith(base_root + os.sep):
        return ""
    return absolute_path


def sanitize_recruitment_storage_label(value, fallback="Kandidat"):
    safe_value = re.sub(r'[<>:"/\\\\|?*\x00-\x1f]+', " ", str(value or ""))
    safe_value = " ".join(safe_value.replace("_", " ").split())
    if not safe_value:
        safe_value = str(fallback or "Kandidat").strip() or "Kandidat"
    return safe_value[:96]


def build_recruitment_candidate_intake_relative_folder(candidate_id, candidate_name):
    try:
        safe_candidate_id = int(candidate_id or 0)
    except (TypeError, ValueError):
        safe_candidate_id = 0
    label = sanitize_recruitment_storage_label(candidate_name, "Kandidat")
    folder_name = f"{label} - Kandidat {safe_candidate_id}" if safe_candidate_id > 0 else label
    return "/".join(("_hr_recruitment_intake", folder_name))


def build_recruitment_candidate_intake_path(candidate_id, candidate_name):
    relative_folder = build_recruitment_candidate_intake_relative_folder(candidate_id, candidate_name)
    absolute_path = build_sms_storage_absolute_path(relative_folder)
    if not absolute_path:
        return ""
    os.makedirs(absolute_path, exist_ok=True)
    return absolute_path
