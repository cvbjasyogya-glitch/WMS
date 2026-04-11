from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sqlite3
import sys
import tempfile
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pgdumplib
    import pgdumplib.dump as pgdump_dump
    PGDUMPLIB_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover
    pgdumplib = None
    pgdump_dump = None
    PGDUMPLIB_IMPORT_ERROR = exc

from werkzeug.security import generate_password_hash

from init_db import init_db


MIRROR_METADATA_TABLE = "__ipos4_mirror_metadata"
IPOS_IMPORT_RUNS_TABLE = "ipos_import_runs"
IPOS_IMPORT_PRODUCT_MAP_TABLE = "ipos_import_product_map"
IMPORT_SQLITE_TIMEOUT_SECONDS = 300
IMPORT_SQLITE_BUSY_TIMEOUT_MS = 300000
DEFAULT_VARIANT_NAME = "default"
PRIMARY_SOURCE_WAREHOUSE_CODE = "MTR"
RECEIPT_PREFIX = "IPOS"
PAYMENT_FIELD_TO_METHOD = {
    "jmltunai": "cash",
    "jmldebit": "debit",
    "jmlkk": "card",
    "jmlkredit": "credit",
    "jmlemoney": "e_money",
    "jmldeposit": "deposit",
}
SOURCE_TABLES_FOR_PREVIEW = (
    "tbl_kantor",
    "tbl_item",
    "tbl_itemstok",
    "tbl_supel",
    "tbl_user",
    "tbl_ikhd",
    "tbl_ikdt",
    "tbl_imhd",
    "tbl_imdt",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import core iPOS4 data into the ERP SQLite database and mirror the full "
            "iPOS dump into a separate SQLite reference database."
        )
    )
    parser.add_argument("source_dump", help="Path ke file backup iPOS4 (.i4bu)")
    parser.add_argument(
        "--target-db",
        default="database.db",
        help="Path database SQLite ERP target. Default: database.db",
    )
    parser.add_argument(
        "--mirror-db",
        default="instance/ipos4_mirror.db",
        help="Path database SQLite mirror seluruh tabel iPOS. Default: instance/ipos4_mirror.db",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Hanya tampilkan ringkasan sumber dan target tanpa menulis data.",
    )
    parser.add_argument(
        "--skip-mirror",
        action="store_true",
        help="Lewati pembuatan mirror SQLite iPOS.",
    )
    parser.add_argument(
        "--skip-users",
        action="store_true",
        help="Lewati import user iPOS ke tabel users ERP.",
    )
    parser.add_argument(
        "--skip-warehouses",
        action="store_true",
        help="Jangan buat warehouse baru dari iPOS. Gunakan warehouse ERP yang sudah ada saja.",
    )
    parser.add_argument(
        "--skip-sales",
        action="store_true",
        help="Lewati import histori penjualan ke CRM/POS ERP.",
    )
    parser.add_argument(
        "--skip-stock",
        action="store_true",
        help="Lewati sinkron stok snapshot dari iPOS ke ERP.",
    )
    parser.add_argument(
        "--skip-customers",
        action="store_true",
        help="Lewati seed customer master dari iPOS.",
    )
    parser.add_argument(
        "--replace-mirror",
        action="store_true",
        help="Timpa file mirror SQLite yang sudah ada.",
    )
    parser.add_argument(
        "--update-existing-users",
        action="store_true",
        help="Update role/password user ERP jika username yang sama sudah ada.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Jangan membuat backup database target sebelum import.",
    )
    parser.add_argument(
        "--limit-sales",
        type=int,
        default=0,
        help="Batasi jumlah header penjualan yang diimport. Cocok untuk verifikasi cepat.",
    )
    parser.add_argument(
        "--products-only",
        action="store_true",
        help="Hanya sinkron master produk dan SKU iPOS. Lewati user, stok, customer, dan sales.",
    )
    parser.add_argument(
        "--sync-sku-only",
        action="store_true",
        help="Hanya sinkronkan SKU produk yang sudah/linkable ke iPOS tanpa import transaksi baru.",
    )
    parser.add_argument(
        "--workspace-dir",
        default="",
        help="Folder kerja sementara untuk ekstraksi/parser dump iPOS4.",
    )
    return parser.parse_args()


def print_step(message: str) -> None:
    print(f"[ipos-import] {message}")


def quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def normalize_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def normalize_unit_label(value: object) -> str:
    raw = str(value or "").strip()
    return raw or "pcs"


def clean_string(value: object) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    return raw or None


def unique_non_empty_strings(values: list[object]) -> list[str]:
    seen: set[str] = set()
    normalized_values: list[str] = []
    for value in values:
        safe_value = clean_string(value)
        if not safe_value:
            continue
        key = safe_value.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized_values.append(safe_value)
    return normalized_values


def build_ipos_sales_source_labels(header: dict) -> tuple[str | None, str | None, list[str]]:
    cashier_candidates = unique_non_empty_strings([
        header.get("user1"),
        header.get("user2"),
    ])
    sales_candidates = unique_non_empty_strings([
        header.get("kodesales"),
        header.get("kodesales2"),
        header.get("kodesales3"),
        header.get("kodesales4"),
    ])
    source_cashier_name = cashier_candidates[0] if cashier_candidates else None
    source_sales_name = " / ".join(sales_candidates) if sales_candidates else None
    actor_candidates = sales_candidates + cashier_candidates
    return source_cashier_name, source_sales_name, actor_candidates


def build_user_identity_lookup(conn: sqlite3.Connection) -> tuple[dict[str, int], list[dict]]:
    lookup: dict[str, int] = {}
    identity_rows: list[dict] = []
    rows = conn.execute(
        """
        SELECT
            u.id,
            u.username,
            COALESCE(NULLIF(TRIM(e.full_name), ''), '') AS employee_name
        FROM users u
        LEFT JOIN employees e ON e.id = u.employee_id
        """
    ).fetchall()

    for row in rows:
        user_id = int(row["id"])
        username_key = normalize_text(row["username"])
        employee_key = normalize_text(row["employee_name"])
        identity_rows.append(
            {
                "id": user_id,
                "username_key": username_key,
                "employee_key": employee_key,
            }
        )
        for key in (username_key, employee_key):
            if key and key not in lookup:
                lookup[key] = user_id

    return lookup, identity_rows


def resolve_user_id_from_candidates(
    candidates: list[object],
    imported_user_ids: dict[str, int],
    user_lookup: dict[str, int],
    identity_rows: list[dict],
) -> int | None:
    imported_lookup = {
        normalize_text(username_key): int(user_id)
        for username_key, user_id in imported_user_ids.items()
        if normalize_text(username_key)
    }
    normalized_candidates = [
        normalize_text(candidate)
        for candidate in candidates
        if clean_string(candidate)
    ]
    normalized_candidates = [candidate for candidate in normalized_candidates if candidate]
    if not normalized_candidates:
        return None

    for candidate in normalized_candidates:
        imported_match = imported_lookup.get(candidate)
        if imported_match:
            return int(imported_match)
        lookup_match = user_lookup.get(candidate)
        if lookup_match:
            return int(lookup_match)

    best_match: tuple[int, int, int] | None = None
    for candidate in normalized_candidates:
        if len(candidate) < 4:
            continue
        for row in identity_rows:
            for target_key in (row["username_key"], row["employee_key"]):
                if not target_key:
                    continue
                score = None
                if target_key.startswith(candidate):
                    score = 0
                elif candidate in target_key:
                    score = 1
                if score is None:
                    continue
                current_match = (score, len(target_key), int(row["id"]))
                if best_match is None or current_match < best_match:
                    best_match = current_match
    if best_match is not None:
        return best_match[2]
    return None


def pick_canonical_product_match(name_matches: list[dict]) -> dict | None:
    if not name_matches:
        return None
    return min(
        name_matches,
        key=lambda row: (
            int(row["id"]),
            str(row.get("sku") or "").strip().casefold(),
            str(row.get("name") or "").strip().casefold(),
        ),
    )


def resolve_existing_import_product_match(
    product_cache_by_id: dict[int, dict],
    product_cache_by_sku: dict[str, dict],
    product_cache_by_name: dict[str, list[dict]],
    linked_products: dict[str, dict],
    mapped_product_ids: set[int],
    sku: str | None,
    name: str | None,
) -> tuple[dict | None, str | None, bool]:
    safe_sku = clean_string(sku)
    if safe_sku:
        linked_product = linked_products.get(safe_sku)
        if linked_product:
            existing = product_cache_by_id.get(int(linked_product["product_id"]))
            if existing:
                return existing, "linked", False

        existing = product_cache_by_sku.get(safe_sku)
        if existing:
            return existing, "sku", False

    name_key = normalize_text(name)
    if not name_key:
        return None, None, False

    name_candidates = [
        candidate
        for candidate in product_cache_by_name.get(name_key, [])
        if int(candidate["id"]) not in mapped_product_ids
    ]
    if not name_candidates:
        return None, None, False

    return pick_canonical_product_match(name_candidates), "name", len(name_candidates) > 1


def to_float(value: object, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def round_half_up(value: float) -> int:
    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def parse_datetime(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw = raw.replace("T", " ").replace("Z", "")
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return raw


def slugify_receipt(source_value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", str(source_value or "").strip()).strip("-")
    safe = safe or uuid.uuid4().hex[:12]
    return f"{RECEIPT_PREFIX}-{safe}"


def build_note(*parts: object) -> str | None:
    cleaned = [str(part).strip() for part in parts if str(part or "").strip()]
    return " | ".join(cleaned) if cleaned else None


def _apply_sqlite_runtime_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute(f"PRAGMA busy_timeout = {IMPORT_SQLITE_BUSY_TIMEOUT_MS}")


def backup_database_files(database_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = database_path.parent / "db_import_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_root = backup_dir / f"{database_path.stem}-{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_file = backup_root / database_path.name

    src_conn = sqlite3.connect(
        f"file:{database_path}?mode=ro",
        uri=True,
        timeout=IMPORT_SQLITE_TIMEOUT_SECONDS,
        check_same_thread=False,
    )
    dest_conn = sqlite3.connect(
        str(backup_file),
        timeout=IMPORT_SQLITE_TIMEOUT_SECONDS,
        check_same_thread=False,
    )
    verify_conn = None

    try:
        _apply_sqlite_runtime_pragmas(src_conn)
        _apply_sqlite_runtime_pragmas(dest_conn)
        src_conn.backup(dest_conn, sleep=0.25)
        dest_conn.commit()
    finally:
        try:
            dest_conn.close()
        finally:
            src_conn.close()

    try:
        verify_conn = sqlite3.connect(
            str(backup_file),
            timeout=IMPORT_SQLITE_TIMEOUT_SECONDS,
            check_same_thread=False,
        )
        rows = verify_conn.execute("PRAGMA integrity_check").fetchall()
        integrity = ", ".join(str(row[0]) for row in rows)
        if integrity.strip().lower() != "ok":
            raise RuntimeError(f"Backup integrity_check failed: {integrity}")
    finally:
        if verify_conn is not None:
            verify_conn.close()

    return backup_root


class WorkspaceTempDir:
    def __init__(self, root: Path | str) -> None:
        base_root = Path(root).expanduser().resolve()
        base_root.mkdir(parents=True, exist_ok=True)
        self.path = base_root / f"session_{uuid.uuid4().hex}"
        self.path.mkdir(parents=True, exist_ok=True)
        self.name = str(self.path.resolve())

    def cleanup(self) -> None:
        shutil.rmtree(self.name, ignore_errors=True)


def build_workspace_temp_dir_factory(root: Path):
    class ScopedWorkspaceTempDir(WorkspaceTempDir):
        def __init__(self) -> None:
            super().__init__(root)

    return ScopedWorkspaceTempDir


def resolve_workspace_root(raw_value: object, target_db: Path) -> Path:
    candidate = clean_string(raw_value)
    if candidate:
        root = Path(candidate).expanduser()
    else:
        root = target_db.parent / "tmp_ipos_migration"

    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        root = Path(tempfile.gettempdir()) / "wms-erp-ipos4"
        root.mkdir(parents=True, exist_ok=True)

    return root.resolve()


class IposDumpReader:
    def __init__(self, path: Path, workspace_root: Path | None = None) -> None:
        if PGDUMPLIB_IMPORT_ERROR is not None:
            raise RuntimeError(
                "pgdumplib belum tersedia. Jalankan `pip install -r requirements.txt` terlebih dahulu."
            ) from PGDUMPLIB_IMPORT_ERROR
        self.path = path.resolve()
        self.workspace_root = (
            Path(workspace_root).expanduser().resolve()
            if workspace_root is not None
            else Path(tempfile.gettempdir()).resolve() / "wms-erp-ipos4"
        )
        self._patch_runtime(self.workspace_root)
        self.dump = pgdumplib.load(self.path)
        self.table_columns: dict[str, list[str]] = {}
        self._table_data_entries = {
            entry.tag: entry
            for entry in self.dump.entries
            if entry.desc == "TABLE DATA" and entry.tag and entry.copy_stmt
        }
        for table_name, entry in self._table_data_entries.items():
            self.table_columns[table_name] = self._extract_columns(entry.copy_stmt or "")

    @staticmethod
    def _patch_runtime(workspace_root: Path | None = None) -> None:
        scoped_root = (
            workspace_root
            if workspace_root is not None
            else Path(tempfile.gettempdir()) / "wms-erp-ipos4"
        )
        scoped_root.mkdir(parents=True, exist_ok=True)
        pgdump_dump.tempfile.TemporaryDirectory = build_workspace_temp_dir_factory(scoped_root)
        pgdump_dump.constants.MIN_VER = (1, 11, 0)

    @staticmethod
    def _extract_columns(copy_stmt: str) -> list[str]:
        match = re.search(r"\((.*)\)\s+FROM\s+stdin;$", copy_stmt.strip())
        if not match:
            raise ValueError(f"Gagal membaca kolom dari COPY statement: {copy_stmt}")
        raw_columns = match.group(1)
        return [col.strip() for col in raw_columns.split(",") if col.strip()]

    def has_table(self, table_name: str) -> bool:
        return table_name in self._table_data_entries

    def tables(self) -> list[str]:
        return sorted(self._table_data_entries)

    def iter_rows(self, table_name: str):
        columns = self.table_columns[table_name]
        for raw_row in self.dump.table_data("public", table_name):
            values = list(raw_row)
            if len(values) < len(columns):
                values.extend([None] * (len(columns) - len(values)))
            elif len(values) > len(columns):
                values = values[: len(columns)]
            yield dict(zip(columns, values))

    def count_rows(self, table_name: str) -> int:
        return sum(1 for _ in self.iter_rows(table_name))


def connect_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(path),
        timeout=IMPORT_SQLITE_TIMEOUT_SECONDS,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    _apply_sqlite_runtime_pragmas(conn)
    return conn


def ensure_import_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {IPOS_IMPORT_RUNS_TABLE}(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_dump TEXT NOT NULL,
            target_db TEXT NOT NULL,
            mirror_db TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            summary_json TEXT
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {IPOS_IMPORT_PRODUCT_MAP_TABLE}(
            source_item_code TEXT PRIMARY KEY,
            source_item_name TEXT,
            product_id INTEGER NOT NULL,
            source_dump TEXT,
            synced_at TEXT NOT NULL,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        f"""
        CREATE INDEX IF NOT EXISTS idx_ipos_import_product_map_product
        ON {IPOS_IMPORT_PRODUCT_MAP_TABLE}(product_id)
        """
    )
    conn.commit()


def load_ipos_product_map(conn: sqlite3.Connection) -> dict[str, dict]:
    product_map: dict[str, dict] = {}
    for row in conn.execute(
        f"""
        SELECT source_item_code, source_item_name, product_id, source_dump, synced_at
        FROM {IPOS_IMPORT_PRODUCT_MAP_TABLE}
        """
    ):
        source_item_code = clean_string(row["source_item_code"])
        if not source_item_code:
            continue
        product_map[source_item_code] = {
            "source_item_name": clean_string(row["source_item_name"]),
            "product_id": int(row["product_id"]),
            "source_dump": clean_string(row["source_dump"]),
            "synced_at": clean_string(row["synced_at"]),
        }
    return product_map


def upsert_ipos_product_map(
    conn: sqlite3.Connection,
    source_item_code: str,
    source_item_name: str | None,
    product_id: int,
    source_dump: Path | None,
) -> None:
    conn.execute(
        f"""
        INSERT INTO {IPOS_IMPORT_PRODUCT_MAP_TABLE}(
            source_item_code, source_item_name, product_id, source_dump, synced_at
        )
        VALUES (?,?,?,?,?)
        ON CONFLICT(source_item_code)
        DO UPDATE SET
            source_item_name=excluded.source_item_name,
            product_id=excluded.product_id,
            source_dump=excluded.source_dump,
            synced_at=excluded.synced_at
        """,
        (
            source_item_code,
            source_item_name,
            product_id,
            str(source_dump) if source_dump else None,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )


def start_import_run(
    conn: sqlite3.Connection,
    source_dump: Path,
    target_db: Path,
    mirror_db: Path | None,
) -> int:
    cursor = conn.execute(
        f"""
        INSERT INTO {IPOS_IMPORT_RUNS_TABLE}(source_dump, target_db, mirror_db, started_at)
        VALUES (?,?,?,?)
        """,
        (
            str(source_dump),
            str(target_db),
            str(mirror_db) if mirror_db else None,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def finish_import_run(conn: sqlite3.Connection, run_id: int, summary: dict) -> None:
    conn.execute(
        f"""
        UPDATE {IPOS_IMPORT_RUNS_TABLE}
        SET finished_at=?, summary_json=?
        WHERE id=?
        """,
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            json.dumps(summary, ensure_ascii=True, sort_keys=True),
            run_id,
        ),
    )
    conn.commit()


def preview_source(reader: IposDumpReader, target_db: Path, mirror_db: Path) -> dict:
    counts = {}
    for table_name in SOURCE_TABLES_FOR_PREVIEW:
        if reader.has_table(table_name):
            counts[table_name] = reader.count_rows(table_name)

    target_snapshot = {
        "target_db_exists": target_db.exists(),
        "mirror_db_exists": mirror_db.exists(),
    }

    if target_db.exists():
        conn = connect_sqlite(target_db)
        try:
            for table_name in (
                "warehouses",
                "users",
                "products",
                "product_variants",
                "crm_customers",
                "crm_purchase_records",
                "crm_purchase_items",
                "pos_sales",
            ):
                try:
                    target_snapshot[table_name] = int(
                        conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                    )
                except sqlite3.DatabaseError:
                    target_snapshot[table_name] = None
        finally:
            conn.close()

    return {
        "source_dump": str(reader.path),
        "dump_version": ".".join(str(part) for part in reader.dump.version),
        "table_count": len(reader.tables()),
        "source_counts": counts,
        "target_snapshot": target_snapshot,
    }


def mirror_dump_to_sqlite(reader: IposDumpReader, mirror_path: Path, replace_existing: bool) -> dict:
    if mirror_path.exists():
        if not replace_existing:
            raise FileExistsError(
                f"Mirror database sudah ada: {mirror_path}. "
                "Pakai --replace-mirror untuk menimpanya."
            )
        mirror_path.unlink()

    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect_sqlite(mirror_path)
    summary = {"tables": 0, "rows": 0}
    try:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {quote_ident(MIRROR_METADATA_TABLE)}(
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.executemany(
            f"INSERT OR REPLACE INTO {quote_ident(MIRROR_METADATA_TABLE)}(key, value) VALUES (?, ?)",
            [
                ("source_dump", str(reader.path)),
                ("dump_version", ".".join(str(part) for part in reader.dump.version)),
                ("mirrored_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ],
        )

        for table_name in reader.tables():
            columns = reader.table_columns[table_name]
            column_sql = ", ".join(f"{quote_ident(column)} TEXT" for column in columns)
            conn.execute(f"DROP TABLE IF EXISTS {quote_ident(table_name)}")
            conn.execute(f"CREATE TABLE {quote_ident(table_name)} ({column_sql})")

            placeholders = ",".join(["?"] * len(columns))
            insert_sql = (
                f"INSERT INTO {quote_ident(table_name)} "
                f"({', '.join(quote_ident(column) for column in columns)}) "
                f"VALUES ({placeholders})"
            )

            chunk: list[tuple] = []
            row_count = 0
            for row in reader.iter_rows(table_name):
                chunk.append(tuple(row.get(column) for column in columns))
                row_count += 1
                if len(chunk) >= 500:
                    conn.executemany(insert_sql, chunk)
                    chunk.clear()

            if chunk:
                conn.executemany(insert_sql, chunk)

            conn.commit()
            summary["tables"] += 1
            summary["rows"] += row_count
            print_step(f"Mirror table {table_name}: {row_count} rows")
    finally:
        conn.close()

    return summary


def fetch_source_table(reader: IposDumpReader, table_name: str) -> list[dict]:
    if not reader.has_table(table_name):
        return []
    return list(reader.iter_rows(table_name))


def map_user_role(source_group: object) -> str:
    normalized = normalize_text(source_group)
    if "administrator" in normalized:
        return "admin"
    if "leader" in normalized:
        return "leader"
    return "staff"


def resolve_warehouses(
    conn: sqlite3.Connection,
    offices: list[dict],
    summary: dict,
    allow_create: bool = True,
) -> dict[str, int]:
    existing = [dict(row) for row in conn.execute("SELECT id, name FROM warehouses ORDER BY id")]
    normalized_existing = {row["id"]: normalize_text(row["name"]) for row in existing}
    office_map: dict[str, int] = {}

    for office in offices:
        code = str(office.get("kodekantor") or "").strip()
        source_name = clean_string(office.get("namakantor"))
        if not code:
            continue

        name_hints = {
            normalize_text(code),
            normalize_text(source_name),
            normalize_text(f"gudang {source_name or code}"),
        }
        if code.upper() == "MTR":
            name_hints.add("mataram")
        elif code.upper() == "MG":
            name_hints.add("mega")

        matched_id = None
        for row in existing:
            normalized_name = normalized_existing[row["id"]]
            if normalized_name in name_hints or any(
                hint and hint in normalized_name for hint in name_hints
            ):
                matched_id = row["id"]
                break

        if matched_id is None:
            if not allow_create:
                continue
            preferred_name = source_name or code
            if "gudang" not in preferred_name.lower():
                preferred_name = f"Gudang {preferred_name.title()}"
            cursor = conn.execute(
                "INSERT INTO warehouses(name) VALUES (?)",
                (preferred_name,),
            )
            matched_id = int(cursor.lastrowid)
            existing.append({"id": matched_id, "name": preferred_name})
            normalized_existing[matched_id] = normalize_text(preferred_name)
            summary["warehouses_created"] += 1
        else:
            summary["warehouses_reused"] += 1

        office_map[code] = matched_id

    return office_map


def import_users(
    conn: sqlite3.Connection,
    users: list[dict],
    office_map: dict[str, int],
    update_existing: bool,
    summary: dict,
) -> dict[str, int]:
    existing = {
        str(row["username"]).strip().lower(): dict(row)
        for row in conn.execute(
            "SELECT id, username, role, warehouse_id FROM users WHERE username IS NOT NULL"
        )
    }
    imported_user_ids: dict[str, int] = {}

    for row in users:
        username = clean_string(row.get("userid"))
        if not username:
            continue

        username_key = username.lower()
        role = map_user_role(row.get("kelompok"))
        warehouse_id = office_map.get(str(row.get("loginkantor") or "").strip()) if role in {"admin", "leader", "staff"} else None
        password_hash = generate_password_hash(clean_string(row.get("password")) or "admin123")

        if username_key in existing:
            imported_user_ids[username_key] = int(existing[username_key]["id"])
            if update_existing:
                conn.execute(
                    """
                    UPDATE users
                    SET password=?, role=?, warehouse_id=?
                    WHERE id=?
                    """,
                    (
                        password_hash,
                        role,
                        warehouse_id,
                        existing[username_key]["id"],
                    ),
                )
                summary["users_updated"] += 1
            else:
                summary["users_skipped"] += 1
            continue

        cursor = conn.execute(
            """
            INSERT INTO users(username, password, role, warehouse_id)
            VALUES (?,?,?,?)
            """,
            (username, password_hash, role, warehouse_id),
        )
        user_id = int(cursor.lastrowid)
        existing[username_key] = {"id": user_id}
        imported_user_ids[username_key] = user_id
        summary["users_created"] += 1

    return imported_user_ids


def get_or_create_category(
    conn: sqlite3.Connection,
    category_name: str,
    category_cache: dict[str, int],
) -> int:
    safe_name = category_name or "Uncategorized"
    if safe_name in category_cache:
        return category_cache[safe_name]

    row = conn.execute("SELECT id FROM categories WHERE name=?", (safe_name,)).fetchone()
    if row:
        category_cache[safe_name] = int(row["id"])
        return category_cache[safe_name]

    cursor = conn.execute("INSERT INTO categories(name) VALUES (?)", (safe_name,))
    category_cache[safe_name] = int(cursor.lastrowid)
    return category_cache[safe_name]


def upsert_default_variant(
    conn: sqlite3.Connection,
    product_id: int,
    price_value: float,
    variant_cache: dict[int, int],
) -> int:
    if product_id in variant_cache:
        conn.execute(
            """
            UPDATE product_variants
            SET price_retail=?, price_discount=?, price_nett=?
            WHERE id=?
            """,
            (price_value, price_value, price_value, variant_cache[product_id]),
        )
        return variant_cache[product_id]

    row = conn.execute(
        """
        SELECT id FROM product_variants
        WHERE product_id=? AND variant=?
        """,
        (product_id, DEFAULT_VARIANT_NAME),
    ).fetchone()
    if row:
        variant_id = int(row["id"])
        conn.execute(
            """
            UPDATE product_variants
            SET price_retail=?, price_discount=?, price_nett=?
            WHERE id=?
            """,
            (price_value, price_value, price_value, variant_id),
        )
        variant_cache[product_id] = variant_id
        return variant_id

    cursor = conn.execute(
        """
        INSERT INTO product_variants(
            product_id, variant, price_retail, price_discount, price_nett, variant_code, color, gtin, no_gtin
        )
        VALUES (?,?,?,?,?,'','','',1)
        """,
        (product_id, DEFAULT_VARIANT_NAME, price_value, price_value, price_value),
    )
    variant_id = int(cursor.lastrowid)
    variant_cache[product_id] = variant_id
    return variant_id


def remember_product_cache_entry(
    product_cache_by_id: dict[int, dict],
    product_cache_by_sku: dict[str, dict],
    product_cache_by_name: dict[str, list[dict]],
    row: dict,
) -> dict:
    cached_row = dict(row)
    product_id = int(cached_row["id"])
    previous_row = product_cache_by_id.get(product_id) or {}
    previous_sku_key = clean_string(previous_row.get("sku"))
    if previous_sku_key:
        current_row = product_cache_by_sku.get(previous_sku_key)
        if current_row and int(current_row["id"]) == product_id:
            product_cache_by_sku.pop(previous_sku_key, None)

    previous_name_key = normalize_text(previous_row.get("name"))
    if previous_name_key:
        previous_rows = product_cache_by_name.get(previous_name_key, [])
        filtered_rows = [
            current_row
            for current_row in previous_rows
            if int(current_row["id"]) != product_id
        ]
        if filtered_rows:
            product_cache_by_name[previous_name_key] = filtered_rows
        else:
            product_cache_by_name.pop(previous_name_key, None)

    product_cache_by_id[product_id] = cached_row
    sku_key = clean_string(cached_row.get("sku"))
    if sku_key:
        product_cache_by_sku[sku_key] = cached_row

    name_key = normalize_text(cached_row.get("name"))
    if name_key:
        product_cache_by_name.setdefault(name_key, []).append(cached_row)

    return cached_row


def import_products(
    conn: sqlite3.Connection,
    items: list[dict],
    summary: dict,
    source_dump: Path | None = None,
    allow_create_products: bool = True,
) -> tuple[dict[str, dict], dict[int, int]]:
    category_cache = {
        str(row["name"]): int(row["id"])
        for row in conn.execute("SELECT id, name FROM categories")
    }
    product_rows = [
        dict(row)
        for row in conn.execute("SELECT id, sku, name, category_id, unit_label FROM products")
    ]
    product_cache_by_id = {int(row["id"]): row for row in product_rows}
    product_cache_by_sku = {}
    product_cache_by_name: dict[str, list[dict]] = {}
    for row in product_rows:
        sku_key = clean_string(row.get("sku"))
        if sku_key:
            product_cache_by_sku[sku_key] = row
        name_key = normalize_text(row.get("name"))
        if name_key:
            product_cache_by_name.setdefault(name_key, []).append(row)
    variant_cache = {
        int(row["product_id"]): int(row["id"])
        for row in conn.execute(
            "SELECT id, product_id FROM product_variants WHERE variant=?",
            (DEFAULT_VARIANT_NAME,),
        )
    }
    linked_products = load_ipos_product_map(conn)
    mapped_product_ids = {int(row["product_id"]) for row in linked_products.values()}
    product_map: dict[str, dict] = {}

    for row in items:
        sku = clean_string(row.get("kodeitem"))
        if not sku:
            continue

        name = clean_string(row.get("namaitem")) or sku
        category_name = clean_string(row.get("jenis")) or "Uncategorized"
        unit_label = normalize_unit_label(row.get("satuan"))
        category_id = get_or_create_category(conn, category_name, category_cache)
        price_value = to_float(row.get("hargajual1"))
        cost_value = to_float(row.get("hargapokok"))
        brand_value = clean_string(row.get("merek"))
        source_office = clean_string(row.get("dept"))

        existing, match_type, has_multiple_name_matches = resolve_existing_import_product_match(
            product_cache_by_id,
            product_cache_by_sku,
            product_cache_by_name,
            linked_products,
            mapped_product_ids,
            sku,
            name,
        )
        if existing and match_type == "name":
            summary["products_merged_by_name"] += 1
        elif has_multiple_name_matches:
            summary["products_name_conflicts"] += 1

        if existing:
            conn.execute(
                """
                UPDATE products
                SET name=?, category_id=?, unit_label=?, variant_mode='non_variant'
                WHERE id=?
                """,
                (name, category_id, unit_label, existing["id"]),
            )
            product_id = int(existing["id"])
            summary["products_updated"] += 1
        elif not allow_create_products:
            summary["products_skipped_unmapped"] += 1
            continue
        else:
            cursor = conn.execute(
                """
                INSERT INTO products(sku, name, category_id, unit_label, variant_mode)
                VALUES (?,?,?,?,?)
                """,
                (sku, name, category_id, unit_label, "non_variant"),
            )
            product_id = int(cursor.lastrowid)
            summary["products_created"] += 1

        remember_product_cache_entry(
            product_cache_by_id,
            product_cache_by_sku,
            product_cache_by_name,
            {
                "id": product_id,
                "sku": (existing or {}).get("sku") if existing else sku,
                "name": name,
                "category_id": category_id,
                "unit_label": unit_label,
            },
        )

        upsert_ipos_product_map(conn, sku, name, product_id, source_dump)
        linked_products[sku] = {
            "source_item_name": name,
            "product_id": product_id,
            "source_dump": str(source_dump) if source_dump else None,
            "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        mapped_product_ids.add(product_id)

        variant_id = upsert_default_variant(conn, product_id, price_value, variant_cache)
        product_map[sku] = {
            "product_id": product_id,
            "variant_id": variant_id,
            "cost": cost_value,
            "unit_label": unit_label,
            "brand": brand_value,
            "source_office": source_office,
        }

    return product_map, variant_cache


def sync_sku_to_ipos_codes(conn: sqlite3.Connection, summary: dict) -> None:
    sku_owner = {}
    for row in conn.execute("SELECT id, sku FROM products WHERE sku IS NOT NULL"):
        sku_key = clean_string(row["sku"])
        if sku_key:
            sku_owner[sku_key] = int(row["id"])

    for row in conn.execute(
        f"""
        SELECT
            map.source_item_code,
            map.product_id,
            product.id AS existing_product_id,
            product.sku
        FROM {IPOS_IMPORT_PRODUCT_MAP_TABLE} AS map
        LEFT JOIN products AS product
            ON product.id = map.product_id
        ORDER BY map.product_id
        """
    ):
        target_sku = clean_string(row["source_item_code"])
        if not target_sku:
            continue
        if row["existing_product_id"] is None:
            summary["sku_map_missing_product"] += 1
            continue

        product_id = int(row["product_id"])
        current_sku = clean_string(row["sku"])
        if current_sku == target_sku:
            summary["sku_already_ok"] += 1
            continue

        conflict_owner = sku_owner.get(target_sku)
        if conflict_owner is not None and conflict_owner != product_id:
            summary["sku_conflicts"] += 1
            continue

        conn.execute("UPDATE products SET sku=? WHERE id=?", (target_sku, product_id))
        if current_sku and sku_owner.get(current_sku) == product_id:
            sku_owner.pop(current_sku, None)
        sku_owner[target_sku] = product_id
        summary["sku_synced"] += 1


def validate_ipos_sku_consistency(conn: sqlite3.Connection, summary: dict) -> None:
    duplicate_links = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT product_id
                FROM {IPOS_IMPORT_PRODUCT_MAP_TABLE}
                GROUP BY product_id
                HAVING COUNT(*) > 1
            ) AS duplicate_products
            """
        ).fetchone()[0]
    )
    sku_mismatches = int(
        conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {IPOS_IMPORT_PRODUCT_MAP_TABLE} AS map
            JOIN products AS product
                ON product.id = map.product_id
            WHERE COALESCE(TRIM(product.sku), '') != COALESCE(TRIM(map.source_item_code), '')
            """
        ).fetchone()[0]
    )
    summary["sku_duplicate_product_links"] = duplicate_links
    summary["sku_mismatches"] = sku_mismatches

    if duplicate_links or sku_mismatches:
        raise RuntimeError(
            "Validasi SKU iPOS gagal: "
            f"duplicate_product_links={duplicate_links}, sku_mismatches={sku_mismatches}"
        )


def sync_stock_snapshot(
    conn: sqlite3.Connection,
    stock_rows: list[dict],
    product_map: dict[str, dict],
    office_map: dict[str, int],
    summary: dict,
) -> None:
    current_stock = {
        (int(row["product_id"]), int(row["variant_id"]), int(row["warehouse_id"])): int(row["qty"] or 0)
        for row in conn.execute(
            "SELECT product_id, variant_id, warehouse_id, qty FROM stock"
        )
    }

    for row in stock_rows:
        sku = clean_string(row.get("kodeitem"))
        office_code = clean_string(row.get("kantor"))
        if not sku or not office_code or sku not in product_map or office_code not in office_map:
            summary["stock_skipped"] += 1
            continue

        product_id = product_map[sku]["product_id"]
        variant_id = product_map[sku]["variant_id"]
        warehouse_id = office_map[office_code]
        source_qty = to_float(row.get("stok"))
        target_qty = round_half_up(source_qty)
        if target_qty < 0:
            target_qty = 0
            summary["stock_negative_clamped"] += 1
        current_qty = current_stock.get((product_id, variant_id, warehouse_id), 0)
        diff = target_qty - current_qty

        if diff == 0:
            summary["stock_unchanged"] += 1
            continue

        if diff > 0:
            cursor = conn.execute(
                """
                INSERT INTO stock_batches(
                    product_id, variant_id, warehouse_id, qty, remaining_qty, cost, expiry_date, created_at
                )
                VALUES (?,?,?,?,?,?,NULL,?)
                """,
                (
                    product_id,
                    variant_id,
                    warehouse_id,
                    diff,
                    diff,
                    product_map[sku]["cost"],
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            batch_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO stock_movements(product_id, variant_id, warehouse_id, batch_id, qty, type, created_at)
                VALUES (?,?,?,?,?,'IMPORT',?)
                """,
                (
                    product_id,
                    variant_id,
                    warehouse_id,
                    batch_id,
                    diff,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            final_qty = target_qty
        else:
            remaining = abs(diff)
            batches = conn.execute(
                """
                SELECT id, remaining_qty
                FROM stock_batches
                WHERE product_id=? AND variant_id=? AND warehouse_id=? AND remaining_qty > 0
                ORDER BY datetime(created_at) ASC, id ASC
                """,
                (product_id, variant_id, warehouse_id),
            ).fetchall()
            for batch in batches:
                if remaining <= 0:
                    break
                take = min(int(batch["remaining_qty"] or 0), remaining)
                if take <= 0:
                    continue
                conn.execute(
                    """
                    UPDATE stock_batches
                    SET remaining_qty = remaining_qty - ?
                    WHERE id=?
                    """,
                    (take, batch["id"]),
                )
                conn.execute(
                    """
                    INSERT INTO stock_movements(product_id, variant_id, warehouse_id, batch_id, qty, type, created_at)
                    VALUES (?,?,?,?,?,'IMPORT_OUT',?)
                    """,
                    (
                        product_id,
                        variant_id,
                        warehouse_id,
                        int(batch["id"]),
                        take,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                remaining -= take
            summary["stock_decreased"] += abs(diff) - remaining
            final_qty = current_qty - (abs(diff) - remaining)

        conn.execute(
            """
            INSERT INTO stock_history(
                product_id, variant_id, warehouse_id, action, type, qty, note, user_id, ip_address, user_agent, date
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                product_id,
                variant_id,
                warehouse_id,
                "IMPORT",
                "OPENING",
                abs(diff),
                build_note(
                    "iPOS4 stock snapshot sync",
                    f"source_qty={source_qty:g}",
                    "increase" if diff > 0 else "decrease",
                ),
                None,
                "127.0.0.1",
                "scripts/import_ipos4_dump.py",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.execute(
            """
            INSERT INTO stock(product_id, variant_id, warehouse_id, qty, updated_at)
            VALUES (?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(product_id, variant_id, warehouse_id)
            DO UPDATE SET qty=excluded.qty, updated_at=CURRENT_TIMESTAMP
            """,
            (product_id, variant_id, warehouse_id, final_qty),
        )
        current_stock[(product_id, variant_id, warehouse_id)] = final_qty
        summary["stock_synced"] += 1


def build_source_party_map(parties: list[dict]) -> dict[str, dict]:
    result = {}
    for row in parties:
        code = clean_string(row.get("kode"))
        if code:
            result[code] = row
    return result


def load_existing_customers(conn: sqlite3.Connection) -> dict[tuple[int, str, str], int]:
    cache: dict[tuple[int, str, str], int] = {}
    for row in conn.execute("SELECT id, warehouse_id, customer_name, phone FROM crm_customers"):
        key = (
            int(row["warehouse_id"]),
            normalize_text(row["customer_name"]),
            normalize_text(row["phone"]),
        )
        cache[key] = int(row["id"])
    return cache


def resolve_customer(
    conn: sqlite3.Connection,
    source_code: str | None,
    warehouse_id: int,
    source_parties: dict[str, dict],
    customer_cache: dict[tuple[int, str, str], int],
    summary: dict,
) -> int:
    source_key = clean_string(source_code) or "UMUM"
    source_party = source_parties.get(source_key)
    customer_name = clean_string(source_party.get("nama") if source_party else None) or source_key
    phone = clean_string(source_party.get("telepon") if source_party else None)
    city = clean_string(source_party.get("kota") if source_party else None)
    note = None
    if source_party and clean_string(source_party.get("tipe")) not in (None, "PL"):
        note = build_note(f"source_party_type={source_party.get('tipe')}", clean_string(source_party.get("alamat")))
    elif source_party:
        note = clean_string(source_party.get("alamat"))

    cache_key = (warehouse_id, normalize_text(customer_name), normalize_text(phone))
    if cache_key in customer_cache:
        summary["customers_reused"] += 1
        return customer_cache[cache_key]

    cursor = conn.execute(
        """
        INSERT INTO crm_customers(
            warehouse_id, customer_name, contact_person, phone, email, city, instagram_handle,
            customer_type, marketing_channel, note
        )
        VALUES (?,?,?,?,?,?,?,'retail','store',?)
        """,
        (
            warehouse_id,
            customer_name,
            None,
            phone,
            clean_string(source_party.get("email") if source_party else None),
            city,
            None,
            note,
        ),
    )
    customer_id = int(cursor.lastrowid)
    customer_cache[cache_key] = customer_id
    summary["customers_created"] += 1
    return customer_id


def seed_customer_master(
    conn: sqlite3.Connection,
    parties: list[dict],
    primary_warehouse_id: int,
    source_parties: dict[str, dict],
    customer_cache: dict[tuple[int, str, str], int],
    summary: dict,
) -> None:
    for row in parties:
        if clean_string(row.get("tipe")) != "PL":
            continue
        resolve_customer(
            conn,
            clean_string(row.get("kode")),
            primary_warehouse_id,
            source_parties,
            customer_cache,
            summary,
        )


def build_sales_item_groups(reader: IposDumpReader, summary: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    if not reader.has_table("tbl_ikdt"):
        return grouped

    for row in reader.iter_rows("tbl_ikdt"):
        transaction_no = clean_string(row.get("notransaksi"))
        if not transaction_no:
            continue

        qty_source = to_float(row.get("jumlah"))
        qty_integer = round_half_up(qty_source)
        if not math.isclose(qty_source, float(qty_integer), abs_tol=1e-9):
            summary["sales_fractional_lines"] += 1

        note = None
        source_unit = clean_string(row.get("satuan"))
        if source_unit:
            note = f"source_unit={source_unit}"
        if not math.isclose(qty_source, float(qty_integer), abs_tol=1e-9):
            note = build_note(note, f"source_qty={qty_source:g}")

        grouped[transaction_no].append(
            {
                "sku": clean_string(row.get("kodeitem")),
                "qty": max(1, qty_integer) if qty_integer != 0 else 1,
                "qty_source": qty_source,
                "unit_price": to_float(row.get("harga")),
                "line_total": to_float(row.get("total")),
                "note": note,
            }
        )
        summary["sales_items_grouped"] += 1

    return grouped


def payment_breakdown(header: dict) -> tuple[str, float]:
    active_methods = []
    paid_total = 0.0
    for field_name, method_name in PAYMENT_FIELD_TO_METHOD.items():
        amount = to_float(header.get(field_name))
        if amount > 0:
            active_methods.append(method_name)
            paid_total += amount

    if not active_methods:
        return "cash", paid_total
    if len(active_methods) == 1:
        return active_methods[0], paid_total
    return "mixed", paid_total


def ensure_product_for_sales(
    conn: sqlite3.Connection,
    sku: str | None,
    product_map: dict[str, dict],
    summary: dict,
) -> dict | None:
    if sku and sku in product_map:
        return product_map[sku]
    if not sku:
        return None

    row = conn.execute("SELECT id FROM categories WHERE name=?", ("iPOS4 Missing",)).fetchone()
    if row:
        category_id = int(row["id"])
    else:
        category_id = int(conn.execute("INSERT INTO categories(name) VALUES (?)", ("iPOS4 Missing",)).lastrowid)

    product_row = conn.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone()
    if product_row:
        product_id = int(product_row["id"])
    else:
        cursor = conn.execute(
            """
            INSERT INTO products(sku, name, category_id, unit_label, variant_mode)
            VALUES (?,?,?,?,?)
            """,
            (sku, f"Imported iPOS4 {sku}", category_id, "pcs", "non_variant"),
        )
        product_id = int(cursor.lastrowid)
        summary["products_placeholder_created"] += 1

    variant_row = conn.execute(
        """
        SELECT id FROM product_variants
        WHERE product_id=? AND variant=?
        """,
        (product_id, DEFAULT_VARIANT_NAME),
    ).fetchone()
    if variant_row:
        variant_id = int(variant_row["id"])
    else:
        cursor = conn.execute(
            """
            INSERT INTO product_variants(
                product_id, variant, price_retail, price_discount, price_nett, variant_code, color, gtin, no_gtin
            )
            VALUES (?,?,?,?,?,'','','',1)
            """,
            (product_id, DEFAULT_VARIANT_NAME, 0.0, 0.0, 0.0),
        )
        variant_id = int(cursor.lastrowid)

    product_map[sku] = {
        "product_id": product_id,
        "variant_id": variant_id,
        "cost": 0.0,
        "unit_label": "pcs",
        "brand": None,
        "source_office": None,
    }
    return product_map[sku]


def import_sales(
    conn: sqlite3.Connection,
    reader: IposDumpReader,
    source_parties: dict[str, dict],
    product_map: dict[str, dict],
    imported_user_ids: dict[str, int],
    office_map: dict[str, int],
    customer_cache: dict[tuple[int, str, str], int],
    limit_sales: int,
    summary: dict,
) -> None:
    if not reader.has_table("tbl_ikhd"):
        return

    existing_receipts = {
        str(row["receipt_no"])
        for row in conn.execute("SELECT receipt_no FROM pos_sales WHERE receipt_no IS NOT NULL")
    }
    sales_items_by_txn = build_sales_item_groups(reader, summary)
    user_lookup, user_identity_rows = build_user_identity_lookup(conn)
    primary_warehouse_id = office_map.get(PRIMARY_SOURCE_WAREHOUSE_CODE) or next(iter(office_map.values()))

    processed = 0
    for header in reader.iter_rows("tbl_ikhd"):
        source_txn = clean_string(header.get("notransaksi"))
        if not source_txn:
            continue

        receipt_no = slugify_receipt(source_txn)
        if receipt_no in existing_receipts:
            summary["sales_skipped_existing"] += 1
            continue

        warehouse_id = office_map.get(clean_string(header.get("kodekantor")) or "") or primary_warehouse_id
        customer_id = resolve_customer(
            conn,
            clean_string(header.get("kodesupel")),
            warehouse_id,
            source_parties,
            customer_cache,
            summary,
        )

        source_cashier_name, source_sales_name, actor_candidates = build_ipos_sales_source_labels(header)
        cashier_user_id = resolve_user_id_from_candidates(
            actor_candidates,
            imported_user_ids,
            user_lookup,
            user_identity_rows,
        )
        sale_lines = sales_items_by_txn.get(source_txn, [])

        total_items = max(
            1,
            round_half_up(to_float(header.get("totalitem")))
            or sum(int(line["qty"]) for line in sale_lines),
        )
        subtotal_amount = to_float(header.get("subtotal"))
        discount_amount = to_float(header.get("potfaktur")) + to_float(header.get("potnomfaktur"))
        tax_amount = to_float(header.get("pajak"))
        total_amount = to_float(header.get("totalakhir")) or subtotal_amount - discount_amount + tax_amount
        payment_method, paid_amount = payment_breakdown(header)
        if paid_amount <= 0:
            paid_amount = total_amount
        change_amount = max(paid_amount - total_amount, 0.0)
        purchase_date = parse_datetime(header.get("tanggal") or header.get("dateupd"))
        purchase_note = build_note(
            clean_string(header.get("keterangan")),
            f"Imported from iPOS4: {source_txn}",
            f"source_type={clean_string(header.get('tipe')) or '-'}",
            f"source_sales={source_sales_name}" if source_sales_name else None,
            f"source_cashier={source_cashier_name}" if source_cashier_name else None,
        )

        purchase_cursor = conn.execute(
            """
            INSERT INTO crm_purchase_records(
                customer_id, member_id, warehouse_id, purchase_date, invoice_no, channel,
                transaction_type, items_count, total_amount, note, handled_by, created_at, updated_at
            )
            VALUES (?,?,?,? ,? ,'store','purchase',?,?,?, ?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            """,
            (
                customer_id,
                None,
                warehouse_id,
                purchase_date,
                source_txn,
                total_items,
                total_amount,
                purchase_note,
                cashier_user_id,
            ),
        )
        purchase_id = int(purchase_cursor.lastrowid)

        if sale_lines:
            line_payload = []
            for line in sale_lines:
                product_data = ensure_product_for_sales(conn, line["sku"], product_map, summary)
                if not product_data:
                    summary["sales_items_skipped_missing_product"] += 1
                    continue
                line_payload.append(
                    (
                        purchase_id,
                        product_data["product_id"],
                        product_data["variant_id"],
                        int(line["qty"]),
                        float(line["unit_price"]),
                        float(line["line_total"]),
                        line["note"],
                    )
                )

            if line_payload:
                conn.executemany(
                    """
                    INSERT INTO crm_purchase_items(
                        purchase_id, product_id, variant_id, qty, unit_price, line_total, note
                    )
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    line_payload,
                )
                summary["sales_items_imported"] += len(line_payload)
        else:
            summary["sales_without_items"] += 1

        conn.execute(
            """
            INSERT INTO pos_sales(
                purchase_id, customer_id, warehouse_id, cashier_user_id, sale_date, receipt_no,
                source_cashier_name, source_sales_name,
                payment_method, total_items, subtotal_amount, discount_type, discount_value,
                discount_amount, tax_type, tax_value, tax_amount, total_amount, paid_amount,
                change_amount, status, note, created_at, updated_at
            )
            VALUES (
                ?,?,?,?,?,?,?,?,
                ?,?,?, 'amount', 0,
                ?, 'amount', 0, ?, ?, ?,
                ?, 'posted', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (
                purchase_id,
                customer_id,
                warehouse_id,
                cashier_user_id,
                purchase_date,
                receipt_no,
                source_cashier_name,
                source_sales_name,
                payment_method,
                total_items,
                subtotal_amount,
                discount_amount,
                tax_amount,
                total_amount,
                paid_amount,
                change_amount,
                build_note(
                    purchase_note,
                    f"paid_amount={paid_amount:g}",
                    f"payment_method={payment_method}",
                ),
            ),
        )
        existing_receipts.add(receipt_no)
        summary["sales_created"] += 1
        processed += 1

        if processed % 1000 == 0:
            conn.commit()
            print_step(f"Sales imported: {processed}")

        if limit_sales and processed >= limit_sales:
            break


def build_summary_template() -> dict:
    return {
        "warehouses_created": 0,
        "warehouses_reused": 0,
        "users_created": 0,
        "users_updated": 0,
        "users_skipped": 0,
        "products_created": 0,
        "products_updated": 0,
        "products_merged_by_name": 0,
        "products_name_conflicts": 0,
        "products_skipped_unmapped": 0,
        "products_placeholder_created": 0,
        "sku_synced": 0,
        "sku_already_ok": 0,
        "sku_conflicts": 0,
        "sku_map_missing_product": 0,
        "sku_duplicate_product_links": 0,
        "sku_mismatches": 0,
        "stock_synced": 0,
        "stock_unchanged": 0,
        "stock_skipped": 0,
        "stock_decreased": 0,
        "stock_negative_clamped": 0,
        "customers_created": 0,
        "customers_reused": 0,
        "sales_created": 0,
        "sales_skipped_existing": 0,
        "sales_items_grouped": 0,
        "sales_items_imported": 0,
        "sales_items_skipped_missing_product": 0,
        "sales_fractional_lines": 0,
        "sales_without_items": 0,
    }


def run_import(args: argparse.Namespace) -> dict:
    source_dump = Path(args.source_dump).expanduser().resolve()
    target_db = Path(args.target_db).expanduser().resolve()
    mirror_db = Path(args.mirror_db).expanduser().resolve()
    workspace_root = resolve_workspace_root(getattr(args, "workspace_dir", ""), target_db)
    products_only_mode = bool(args.products_only)
    sync_sku_only_mode = bool(args.sync_sku_only)
    skip_mirror = bool(args.skip_mirror or sync_sku_only_mode)
    skip_users = bool(args.skip_users or products_only_mode or sync_sku_only_mode)
    skip_warehouses = bool(args.skip_warehouses or products_only_mode or sync_sku_only_mode)
    skip_sales = bool(args.skip_sales or products_only_mode or sync_sku_only_mode)
    skip_stock = bool(args.skip_stock or products_only_mode or sync_sku_only_mode)
    skip_customers = bool(args.skip_customers or products_only_mode or sync_sku_only_mode)
    allow_create_products = not sync_sku_only_mode

    if not source_dump.exists():
        raise FileNotFoundError(f"File source dump tidak ditemukan: {source_dump}")

    print_step(f"Loading dump: {source_dump}")
    reader = IposDumpReader(source_dump, workspace_root=workspace_root)

    if args.preview:
        preview = preview_source(reader, target_db, mirror_db)
        print(json.dumps(preview, indent=2, ensure_ascii=True))
        return preview

    if not skip_mirror:
        print_step(f"Mirroring full iPOS dump to SQLite: {mirror_db}")
        mirror_summary = mirror_dump_to_sqlite(reader, mirror_db, args.replace_mirror)
    else:
        mirror_summary = {"tables": 0, "rows": 0}

    target_db.parent.mkdir(parents=True, exist_ok=True)
    if target_db.exists() and not args.no_backup:
        backup_dir = backup_database_files(target_db)
        print_step(f"Target DB backup created at: {backup_dir}")
    else:
        backup_dir = None

    print_step(f"Ensuring ERP schema at: {target_db}")
    init_db(str(target_db))

    offices = fetch_source_table(reader, "tbl_kantor")
    items = fetch_source_table(reader, "tbl_item")
    stock_rows = fetch_source_table(reader, "tbl_itemstok")
    parties = fetch_source_table(reader, "tbl_supel")
    users = fetch_source_table(reader, "tbl_user")

    conn = connect_sqlite(target_db)
    summary = build_summary_template()
    summary["mode"] = (
        "sync_sku_only"
        if sync_sku_only_mode
        else "products_only"
        if products_only_mode
        else "full"
    )
    summary["source_dump"] = str(source_dump)
    summary["target_db"] = str(target_db)
    summary["mirror_db"] = None if skip_mirror else str(mirror_db)
    summary["mirror_tables"] = mirror_summary["tables"]
    summary["mirror_rows"] = mirror_summary["rows"]
    summary["backup_dir"] = str(backup_dir) if backup_dir else None
    summary["source_counts"] = {
        "offices": len(offices),
        "items": len(items),
        "stock_rows": len(stock_rows),
        "parties": len(parties),
        "users": len(users),
    }

    try:
        ensure_import_tables(conn)
        run_id = start_import_run(
            conn,
            source_dump=source_dump,
            target_db=target_db,
            mirror_db=None if skip_mirror else mirror_db,
        )

        office_map: dict[str, int] = {}
        needs_office_mapping = not (skip_users and skip_stock and skip_customers and skip_sales)
        if needs_office_mapping:
            print_step("Resolving warehouses")
            office_map = resolve_warehouses(
                conn,
                offices,
                summary,
                allow_create=not skip_warehouses,
            )
            conn.commit()

        imported_user_ids: dict[str, int] = {}
        if not skip_users:
            print_step("Importing users")
            imported_user_ids = import_users(
                conn,
                users,
                office_map,
                update_existing=args.update_existing_users,
                summary=summary,
            )
            conn.commit()

        print_step("Importing products and default variants")
        product_map, _variant_cache = import_products(
            conn,
            items,
            summary,
            source_dump=source_dump,
            allow_create_products=allow_create_products,
        )
        print_step("Syncing SKU to iPOS item codes")
        sync_sku_to_ipos_codes(conn, summary)
        validate_ipos_sku_consistency(conn, summary)
        conn.commit()

        if not skip_stock:
            print_step("Syncing stock snapshot")
            sync_stock_snapshot(conn, stock_rows, product_map, office_map, summary)
            conn.commit()

        source_parties = build_source_party_map(parties)
        customer_cache = load_existing_customers(conn)
        if not skip_customers and office_map:
            print_step("Seeding customer master")
            primary_warehouse_id = office_map.get(PRIMARY_SOURCE_WAREHOUSE_CODE) or next(iter(office_map.values()))
            seed_customer_master(
                conn,
                parties,
                primary_warehouse_id,
                source_parties,
                customer_cache,
                summary,
            )
            conn.commit()

        if not skip_sales and office_map:
            print_step("Importing POS sales history")
            import_sales(
                conn,
                reader,
                source_parties,
                product_map,
                imported_user_ids,
                office_map,
                customer_cache,
                args.limit_sales,
                summary,
            )
            conn.commit()

        finish_import_run(conn, run_id, summary)
        return summary
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    summary = run_import(args)
    if not args.preview:
        print_step("Import completed.")
        print(json.dumps(summary, indent=2, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ipos-import] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
