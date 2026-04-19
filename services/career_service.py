import json
import os
import random
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


def normalize_assessment_code(value):
    safe_value = "".join(ch for ch in str(value or "") if ch.isdigit())
    return safe_value if len(safe_value) == 5 else ""


def normalize_assessment_option(value):
    safe_value = (value or "").strip().lower()
    return safe_value if safe_value in CAREER_ASSESSMENT_CORRECT_OPTIONS else ""


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
        ]
        for statement in statements:
            db.execute(statement)
        _ensure_postgresql_id_sequence(db, "career_openings")
        _ensure_postgresql_id_sequence(db, "recruitment_candidates")
        _ensure_postgresql_id_sequence(db, "recruitment_assessment_questions")
        _ensure_postgresql_id_sequence(db, "career_public_account_requests")
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
        db.execute(
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
    else:
        safe_code = generate_unique_assessment_code(db)

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
