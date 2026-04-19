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
    psycopg = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


TABLE_QUERIES = {
    "products": "SELECT COUNT(*) FROM products",
    "product_variants": "SELECT COUNT(*) FROM product_variants",
    "stock": "SELECT COUNT(*) FROM stock",
    "users": "SELECT COUNT(*) FROM users",
    "warehouses": "SELECT COUNT(*) FROM warehouses",
    "requests": "SELECT COUNT(*) FROM requests",
    "stock_movements": "SELECT COUNT(*) FROM stock_movements",
    "attendance_action_requests": "SELECT COUNT(*) FROM attendance_action_requests",
    "overtime_usage_records": "SELECT COUNT(*) FROM overtime_usage_records",
    "overtime_balance_adjustments": "SELECT COUNT(*) FROM overtime_balance_adjustments",
    "career_openings": "SELECT COUNT(*) FROM career_openings",
    "recruitment_candidates": "SELECT COUNT(*) FROM recruitment_candidates",
    "recruitment_assessment_questions": "SELECT COUNT(*) FROM recruitment_assessment_questions",
    "career_public_account_requests": "SELECT COUNT(*) FROM career_public_account_requests",
}

DERIVED_QUERIES = {
    "requests_pending": "SELECT COUNT(*) FROM requests WHERE status = 'pending'",
}

SCHEMA_QUERIES = {
    "overtime_usage_records.usage_mode": """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'overtime_usage_records'
          AND column_name = 'usage_mode'
    """,
    "recruitment_candidates.application_channel": """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'recruitment_candidates'
          AND column_name = 'application_channel'
    """,
    "recruitment_candidates.assessment_code": """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'recruitment_candidates'
          AND column_name = 'assessment_code'
    """,
    "career_public_account_requests.email": """
        SELECT COUNT(*)
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'career_public_account_requests'
          AND column_name = 'email'
    """,
    "idx_recruitment_candidates_public_lookup": """
        SELECT COUNT(*)
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND indexname = 'idx_recruitment_candidates_public_lookup'
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


def _table_exists(cursor, table_name: str) -> bool:
    cursor.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    row = cursor.fetchone()
    return bool(row and row[0])


def main() -> int:
    if psycopg is None:
        raise SystemExit(
            "Dependency psycopg belum terpasang. Install requirements terbaru dulu sebelum menjalankan smoke test PostgreSQL."
        ) from _IMPORT_ERROR

    database_url = str(Config.DATABASE_URL or "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL belum diisi.")

    payload = {
        "database_backend": Config.DATABASE_BACKEND,
        "database_url_masked": _masked_database_url(database_url),
        "tables": {},
        "checks": {},
        "schema_checks": {},
        "missing_tables": [],
    }

    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cursor:
            for label, query in TABLE_QUERIES.items():
                exists = _table_exists(cursor, label)
                table_payload = {"exists": exists, "row_count": None}
                if exists:
                    cursor.execute(query)
                    row = cursor.fetchone()
                    table_payload["row_count"] = int(row[0] or 0) if row else 0
                else:
                    payload["missing_tables"].append(label)
                payload["tables"][label] = table_payload
            for label, query in DERIVED_QUERIES.items():
                try:
                    cursor.execute(query)
                    row = cursor.fetchone()
                    payload["checks"][label] = int(row[0] or 0) if row else 0
                except Exception as exc:
                    payload["checks"][label] = {"error": str(exc)}
            for label, query in SCHEMA_QUERIES.items():
                cursor.execute(query)
                row = cursor.fetchone()
                payload["schema_checks"][label] = bool(int(row[0] or 0)) if row else False

    payload["status"] = "ok" if not payload["missing_tables"] else "incomplete"

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
