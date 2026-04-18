import os
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


def normalize_career_opening_status(value):
    status = (value or "").strip().lower()
    return status if status in CAREER_OPENING_STATUSES else "draft"


def normalize_career_employment_type(value):
    employment_type = (value or "").strip().lower()
    return employment_type if employment_type in CAREER_EMPLOYMENT_TYPES else "full_time"


def normalize_career_application_channel(value):
    channel = (value or "").strip().lower()
    return channel if channel in CAREER_APPLICATION_CHANNELS else "manual_hr"


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
            "CREATE INDEX IF NOT EXISTS idx_career_openings_public ON career_openings(status, is_public, warehouse_id, sort_order)",
            "CREATE INDEX IF NOT EXISTS idx_recruitment_candidates_vacancy ON recruitment_candidates(vacancy_id, warehouse_id, created_at)",
        ]
        for statement in statements:
            db.execute(statement)
        _ensure_postgresql_id_sequence(db, "career_openings")
        _ensure_postgresql_id_sequence(db, "recruitment_candidates")
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
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_career_openings_public ON career_openings(status, is_public, warehouse_id, sort_order)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_recruitment_candidates_vacancy ON recruitment_candidates(vacancy_id, warehouse_id, created_at)"
        )

    runtime_state[cache_key] = True


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
