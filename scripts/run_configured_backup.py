import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from scripts.backup_sqlite_db import backup_database, ensure_source_exists, print_step, prune_old_backups


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the configured database backup safely for the active backend.",
    )
    parser.add_argument(
        "--output-dir",
        default="/root/WMS/db_backups",
        help="Directory for backup files when backend is sqlite.",
    )
    parser.add_argument(
        "--retain-days",
        type=int,
        default=14,
        help="Prune backups older than this many days. Set 0 to disable pruning.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    backend = str(Config.DATABASE_BACKEND or "sqlite").strip().lower()

    if backend != "sqlite":
        print_step(
            f"Configured backend is '{backend}'. SQLite file backup skipped on purpose."
        )
        return 0

    source_db = Path(Config.DATABASE).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
