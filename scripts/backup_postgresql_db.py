from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a PostgreSQL backup with pg_dump and prune old dumps.",
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="PostgreSQL connection URL, for example postgresql://user:pass@127.0.0.1:5432/ERP",
    )
    parser.add_argument(
        "--output-dir",
        default="db_backups/postgresql",
        help="Directory for backup files. Default: db_backups/postgresql",
    )
    parser.add_argument(
        "--retain-days",
        type=int,
        default=14,
        help="Delete backup files older than this many days. Set 0 to disable pruning.",
    )
    parser.add_argument(
        "--format",
        choices=("custom", "plain"),
        default="custom",
        help="Backup format: custom (.dump) or plain SQL (.sql). Default: custom",
    )
    return parser.parse_args()


def print_step(message: str) -> None:
    print(f"[backup] {message}")


def _mask_database_url(database_url: str) -> str:
    parsed = urlparse(database_url)
    username = parsed.username or ""
    password_mask = "***" if parsed.password else ""
    auth = username
    if username and password_mask:
        auth = f"{username}:{password_mask}"
    elif password_mask:
        auth = password_mask
    host = parsed.hostname or "localhost"
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or ""
    return f"{parsed.scheme}://{auth}@{host}{port}{path}" if auth else f"{parsed.scheme}://{host}{port}{path}"


def _build_pg_dump_command(database_url: str, output_path: Path, dump_format: str) -> tuple[list[str], dict[str, str], str]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise ValueError("DATABASE_URL harus memakai skema postgresql:// atau postgres://")
    if not parsed.path or parsed.path == "/":
        raise ValueError("Nama database PostgreSQL tidak ditemukan di DATABASE_URL")

    executable = shutil.which("pg_dump")
    if not executable:
        raise FileNotFoundError("pg_dump tidak ditemukan di PATH server.")

    database_name = parsed.path.lstrip("/")
    command = [
        executable,
        "-h",
        parsed.hostname or "127.0.0.1",
        "-p",
        str(parsed.port or 5432),
        "-U",
        parsed.username or "postgres",
        "-d",
        database_name,
        "-f",
        str(output_path),
    ]
    if dump_format == "custom":
        command.insert(len(command) - 2, "-Fc")

    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password
    return command, env, database_name


def backup_database(database_url: str, output_dir: Path, dump_format: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    extension = ".dump" if dump_format == "custom" else ".sql"
    temp_path = output_dir / f".backup_{timestamp}.tmp{extension}"
    final_path = output_dir / f"backup_{timestamp}{extension}"

    command, env, database_name = _build_pg_dump_command(database_url, temp_path, dump_format)
    print_step(f"Backing up PostgreSQL database: {database_name}")
    subprocess.run(command, check=True, env=env)

    if not temp_path.exists() or temp_path.stat().st_size <= 0:
        temp_path.unlink(missing_ok=True)
        raise RuntimeError("pg_dump selesai tetapi file backup kosong.")

    temp_path.replace(final_path)
    return final_path


def prune_old_backups(output_dir: Path, retain_days: int) -> int:
    if retain_days <= 0 or not output_dir.exists():
        return 0

    cutoff = datetime.now() - timedelta(days=retain_days)
    removed = 0
    for pattern in ("backup_*.dump", "backup_*.sql"):
        for path in output_dir.glob(pattern):
            if not path.is_file():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime)
            if modified < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
    return removed


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()

    print_step(f"Database URL: {_mask_database_url(args.database_url)}")
    print_step(f"Output directory: {output_dir}")
    print_step(f"Backup format: {args.format}")

    backup_path = backup_database(args.database_url, output_dir, args.format)
    print_step(f"Backup created: {backup_path}")

    removed = prune_old_backups(output_dir, args.retain_days)
    if removed:
        print_step(f"Removed old backups: {removed}")
    else:
        print_step("No old backups removed.")

    print_step("PostgreSQL backup completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
