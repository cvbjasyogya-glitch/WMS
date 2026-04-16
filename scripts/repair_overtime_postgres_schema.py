import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config

try:
    import psycopg
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Dependency psycopg belum terpasang. Install requirements terbaru dulu sebelum menjalankan repair schema PostgreSQL."
    ) from exc


STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS attendance_action_requests(
        id SERIAL PRIMARY KEY,
        request_type TEXT,
        warehouse_id INTEGER,
        employee_id INTEGER,
        summary_title TEXT,
        summary_note TEXT,
        payload TEXT,
        status TEXT DEFAULT 'pending',
        requested_by INTEGER,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        decision_note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS overtime_balance_adjustments(
        id SERIAL PRIMARY KEY,
        employee_id INTEGER,
        warehouse_id INTEGER,
        adjustment_date TEXT,
        minutes_delta INTEGER DEFAULT 0,
        note TEXT,
        handled_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS overtime_usage_records(
        id SERIAL PRIMARY KEY,
        employee_id INTEGER,
        warehouse_id INTEGER,
        usage_date TEXT,
        usage_mode TEXT DEFAULT 'regular',
        minutes_used INTEGER DEFAULT 0,
        note TEXT,
        handled_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS request_type TEXT",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS warehouse_id INTEGER",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS employee_id INTEGER",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS summary_title TEXT",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS summary_note TEXT",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS payload TEXT",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'pending'",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS requested_by INTEGER",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS handled_by INTEGER",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS handled_at TIMESTAMP",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS decision_note TEXT",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE attendance_action_requests ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS employee_id INTEGER",
    "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS warehouse_id INTEGER",
    "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS adjustment_date TEXT",
    "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS minutes_delta INTEGER DEFAULT 0",
    "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS note TEXT",
    "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS handled_by INTEGER",
    "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE overtime_balance_adjustments ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS employee_id INTEGER",
    "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS warehouse_id INTEGER",
    "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS usage_date TEXT",
    "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS usage_mode TEXT DEFAULT 'regular'",
    "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS minutes_used INTEGER DEFAULT 0",
    "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS note TEXT",
    "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS handled_by INTEGER",
    "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE overtime_usage_records ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    "CREATE INDEX IF NOT EXISTS idx_overtime_usage_main ON overtime_usage_records(warehouse_id, usage_date, employee_id)",
    "CREATE INDEX IF NOT EXISTS idx_overtime_balance_adjustments_main ON overtime_balance_adjustments(warehouse_id, adjustment_date, employee_id)",
    "CREATE INDEX IF NOT EXISTS idx_attendance_action_requests_main ON attendance_action_requests(status, warehouse_id, request_type, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_attendance_action_requests_employee ON attendance_action_requests(employee_id, status, created_at)",
]

VERIFY_QUERIES = {
    "attendance_action_requests": """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'attendance_action_requests'
    """,
    "overtime_balance_adjustments": """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'overtime_balance_adjustments'
    """,
    "overtime_usage_records": """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'overtime_usage_records'
    """,
    "overtime_usage_records.usage_mode": """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'overtime_usage_records'
          AND column_name = 'usage_mode'
    """,
}


def _masked_database_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw or "@" not in raw or "://" not in raw:
        return raw
    scheme, remainder = raw.split("://", 1)
    credentials, host_part = remainder.split("@", 1)
    if ":" not in credentials:
        return f"{scheme}://***@{host_part}"
    username, _password = credentials.split(":", 1)
    return f"{scheme}://{username}:***@{host_part}"


def main() -> int:
    backend = str(Config.DATABASE_BACKEND or "").strip().lower()
    if backend != "postgresql":
        raise SystemExit(
            f"Repair schema ini khusus PostgreSQL. Backend aktif saat ini: {backend or 'sqlite'}."
        )

    database_url = str(Config.DATABASE_URL or "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL belum diisi.")

    payload = {
        "database_backend": backend,
        "database_url_masked": _masked_database_url(database_url),
        "applied_statements": len(STATEMENTS),
        "verification": {},
    }

    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cursor:
            for statement in STATEMENTS:
                cursor.execute(statement)
            for label, query in VERIFY_QUERIES.items():
                cursor.execute(query)
                row = cursor.fetchone()
                payload["verification"][label] = bool(int(row[0] or 0)) if row else False

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
