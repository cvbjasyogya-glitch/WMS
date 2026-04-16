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
        "Dependency psycopg belum terpasang. Install requirements terbaru dulu sebelum menjalankan smoke test PostgreSQL."
    ) from exc


SMOKE_QUERIES = {
    "products": "SELECT COUNT(*) FROM products",
    "product_variants": "SELECT COUNT(*) FROM product_variants",
    "stock": "SELECT COUNT(*) FROM stock",
    "users": "SELECT COUNT(*) FROM users",
    "warehouses": "SELECT COUNT(*) FROM warehouses",
    "requests_pending": "SELECT COUNT(*) FROM requests WHERE status = 'pending'",
    "latest_stock_movement": "SELECT COUNT(*) FROM stock_movements",
    "attendance_action_requests": "SELECT COUNT(*) FROM attendance_action_requests",
    "overtime_usage_records": "SELECT COUNT(*) FROM overtime_usage_records",
    "overtime_balance_adjustments": "SELECT COUNT(*) FROM overtime_balance_adjustments",
}

SCHEMA_QUERIES = {
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
    database_url = str(Config.DATABASE_URL or "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL belum diisi.")

    payload = {
        "database_backend": Config.DATABASE_BACKEND,
        "database_url_masked": _masked_database_url(database_url),
        "checks": {},
        "schema_checks": {},
    }

    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cursor:
            for label, query in SMOKE_QUERIES.items():
                cursor.execute(query)
                row = cursor.fetchone()
                payload["checks"][label] = int(row[0] or 0) if row else 0
            for label, query in SCHEMA_QUERIES.items():
                cursor.execute(query)
                row = cursor.fetchone()
                payload["schema_checks"][label] = bool(int(row[0] or 0)) if row else False

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
