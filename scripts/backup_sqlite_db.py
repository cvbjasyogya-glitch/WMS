from __future__ import annotations

import argparse
import gc
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a safe SQLite backup using the SQLite backup API and "
            "optionally prune old backups."
        )
    )
    parser.add_argument(
        "--database",
        default="database.db",
        help="Path to source SQLite database. Default: database.db",
    )
    parser.add_argument(
        "--output-dir",
        default="db_backups",
        help="Directory for backup files. Default: db_backups",
    )
    parser.add_argument(
        "--retain-days",
        type=int,
        default=14,
        help="Delete backup files older than this many days. Set 0 to disable pruning.",
    )
    return parser.parse_args()


def print_step(message: str) -> None:
    print(f"[backup] {message}")


def ensure_source_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Database file not found: {path}")


def backup_database(source_db: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    temp_path = output_dir / f".backup_{timestamp}.tmp"
    final_path = output_dir / f"backup_{timestamp}.db"

    src_conn = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
    dest_conn = sqlite3.connect(str(temp_path))
    verify_conn = None

    try:
        src_conn.backup(dest_conn)
        dest_conn.commit()
    finally:
        try:
            dest_conn.close()
        finally:
            src_conn.close()

    try:
        verify_conn = sqlite3.connect(str(temp_path))
        rows = verify_conn.execute("PRAGMA integrity_check").fetchall()
    finally:
        if verify_conn is not None:
            verify_conn.close()
        # Ensure SQLite file handles are released before replacing the file.
        gc.collect()

    integrity = ", ".join(str(row[0]) for row in rows)
    if integrity.strip().lower() != "ok":
        temp_path.unlink(missing_ok=True)
        raise RuntimeError(f"Backup integrity_check failed: {integrity}")

    temp_path.replace(final_path)
    return final_path


def prune_old_backups(output_dir: Path, retain_days: int) -> int:
    if retain_days <= 0 or not output_dir.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=retain_days)
    removed = 0
    for path in output_dir.glob("backup_*.db"):
        if not path.is_file():
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        if modified < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def main() -> int:
    args = parse_args()
    source_db = Path(args.database).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    ensure_source_exists(source_db)
    print_step(f"Source database: {source_db}")
    print_step(f"Output directory: {output_dir}")

    backup_path = backup_database(source_db, output_dir)
    print_step(f"Backup created: {backup_path}")

    removed = prune_old_backups(output_dir, args.retain_days)
    if removed:
        print_step(f"Removed old backups: {removed}")
    else:
        print_step("No old backups removed.")

    print_step("Backup completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
