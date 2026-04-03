from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Repair a malformed SQLite database by backing it up, recovering SQL, "
            "rebuilding a fresh database, and optionally replacing the original file."
        )
    )
    parser.add_argument("database", help="Path to the SQLite database file")
    parser.add_argument(
        "--output",
        help="Path for the recovered database. Default: <database>.recovered.db",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace the original database with the recovered database after backup.",
    )
    parser.add_argument(
        "--backup-dir",
        help="Directory for backups. Default: <database dir>/db_repair_backups",
    )
    return parser.parse_args()


def wal_path_for(database_path: Path) -> Path:
    return database_path.with_name(f"{database_path.name}-wal")


def shm_path_for(database_path: Path) -> Path:
    return database_path.with_name(f"{database_path.name}-shm")


def print_step(message: str) -> None:
    print(f"[repair] {message}")


def ensure_file_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Database file not found: {path}")


def run_integrity_check(path: Path) -> tuple[bool, str]:
    try:
        with sqlite3.connect(str(path)) as conn:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
        if not rows:
            return False, "integrity_check returned no rows"
        messages = ", ".join(str(row[0]) for row in rows)
        return messages.strip().lower() == "ok", messages
    except sqlite3.DatabaseError as exc:
        return False, str(exc)


def backup_database_files(database_path: Path, backup_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = backup_root / f"{database_path.stem}-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    for path in (database_path, wal_path_for(database_path), shm_path_for(database_path)):
        if path.exists():
            shutil.copy2(path, backup_dir / path.name)

    return backup_dir


def recover_with_sqlite_shell(database_path: Path, output_path: Path) -> None:
    sqlite_cli = shutil.which("sqlite3")
    if not sqlite_cli:
        raise RuntimeError(
            "sqlite3 CLI tidak ditemukan. Install sqlite3 di server, "
            "atau jalankan recovery manual dari backup."
        )

    with tempfile.TemporaryDirectory(prefix="sqlite-recover-") as temp_dir:
        recover_sql_path = Path(temp_dir) / "recover.sql"

        print_step("Recovering SQL payload with sqlite3 .recover")
        with recover_sql_path.open("wb") as recover_sql_file:
            subprocess.run(
                [sqlite_cli, str(database_path), ".recover"],
                check=True,
                stdout=recover_sql_file,
                stderr=subprocess.PIPE,
            )

        if recover_sql_path.stat().st_size == 0:
            raise RuntimeError("sqlite3 .recover menghasilkan file SQL kosong.")

        print_step("Rebuilding recovered database from recovered SQL")
        sql_payload = recover_sql_path.read_text(encoding="utf-8", errors="replace")
        subprocess.run(
            [sqlite_cli, str(output_path)],
            input=sql_payload.encode("utf-8"),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def replace_original_database(database_path: Path, output_path: Path) -> None:
    if wal_path_for(database_path).exists():
        wal_path_for(database_path).unlink()
    if shm_path_for(database_path).exists():
        shm_path_for(database_path).unlink()
    if database_path.exists():
        database_path.unlink()

    shutil.move(str(output_path), str(database_path))


def main() -> int:
    args = parse_args()
    database_path = Path(args.database).expanduser().resolve()
    ensure_file_exists(database_path)

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else database_path.with_name(f"{database_path.stem}.recovered{database_path.suffix}")
    )
    backup_root = (
        Path(args.backup_dir).expanduser().resolve()
        if args.backup_dir
        else database_path.parent / "db_repair_backups"
    )

    print_step(f"Target database: {database_path}")
    okay, integrity_message = run_integrity_check(database_path)
    print_step(f"Initial integrity_check: {integrity_message}")
    if okay:
        print_step("Database terlihat sehat. Recovery tidak diperlukan.")
        return 0

    backup_dir = backup_database_files(database_path, backup_root)
    print_step(f"Backup created at: {backup_dir}")

    if output_path.exists():
        output_path.unlink()

    recover_with_sqlite_shell(database_path, output_path)

    recovered_ok, recovered_message = run_integrity_check(output_path)
    print_step(f"Recovered integrity_check: {recovered_message}")
    if not recovered_ok:
        raise RuntimeError(
            f"Recovered database masih bermasalah: {recovered_message}. "
            f"Backup aman ada di {backup_dir}."
        )

    if args.replace:
        replace_original_database(database_path, output_path)
        print_step(f"Original database replaced: {database_path}")
    else:
        print_step(f"Recovered database ready: {output_path}")

    print_step("Recovery selesai.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[repair] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
