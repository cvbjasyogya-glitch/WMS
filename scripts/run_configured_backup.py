import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from scripts.backup_postgresql_db import backup_database as backup_postgresql_database
from scripts.backup_postgresql_db import print_step as print_postgresql_step
from scripts.backup_postgresql_db import prune_old_backups as prune_postgresql_backups
from scripts.backup_sqlite_db import backup_database, ensure_source_exists, print_step, prune_old_backups


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the configured database backup safely for the active backend.",
    )
    parser.add_argument(
        "--output-dir",
        default="/root/WMS/db_backups",
        help="Base directory for backup files.",
    )
    parser.add_argument(
        "--retain-days",
        type=int,
        default=14,
        help="Prune backups older than this many days. Set 0 to disable pruning.",
    )
    return parser.parse_args()


def _log_non_fatal_backup_error(step_logger, exc):
    step_logger(f"Backup gagal dijalankan: {exc}")
    step_logger("Startup service tetap dilanjutkan tanpa menghentikan aplikasi.")


def main():
    args = parse_args()
    backend = str(Config.DATABASE_BACKEND or "sqlite").strip().lower()
    output_dir = Path(args.output_dir).expanduser().resolve()

    if backend == "sqlite":
        try:
            source_db = Path(Config.DATABASE).expanduser().resolve()
            ensure_source_exists(source_db)
            print_step(f"Configured backend: {backend}")
            print_step(f"Source database: {source_db}")
            print_step(f"Output directory: {output_dir}")

            backup_path = backup_database(source_db, output_dir)
            print_step(f"Backup created: {backup_path}")

            removed = prune_old_backups(output_dir, args.retain_days)
            if removed:
                print_step(f"Removed old backups: {removed}")
            else:
                print_step("No old backups removed.")

            print_step("Configured backup completed successfully.")
        except Exception as exc:
            _log_non_fatal_backup_error(print_step, exc)
        return 0

    if backend == "postgresql":
        try:
            database_url = str(Config.DATABASE_URL or "").strip()
            if not database_url:
                raise RuntimeError("DATABASE_URL wajib diisi untuk backup PostgreSQL.")
            postgres_output_dir = output_dir / "postgresql"
            print_postgresql_step(f"Configured backend: {backend}")
            print_postgresql_step(f"Output directory: {postgres_output_dir}")
            backup_path = backup_postgresql_database(database_url, postgres_output_dir, "custom")
            print_postgresql_step(f"Backup created: {backup_path}")

            removed = prune_postgresql_backups(postgres_output_dir, args.retain_days)
            if removed:
                print_postgresql_step(f"Removed old backups: {removed}")
            else:
                print_postgresql_step("No old backups removed.")

            print_postgresql_step("Configured backup completed successfully.")
        except Exception as exc:
            _log_non_fatal_backup_error(print_postgresql_step, exc)
        return 0

    print_step(f"Configured backend '{backend}' belum didukung oleh hook backup ini.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
