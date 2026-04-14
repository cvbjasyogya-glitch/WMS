import argparse
import csv
import json
import sqlite3
from pathlib import Path


IGNORED_TABLES = {"sqlite_sequence"}


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _load_table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        ORDER BY name ASC
        """
    ).fetchall()
    return [str(row[0]) for row in rows if str(row[0]) not in IGNORED_TABLES]


def _load_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    return [str(row[1]) for row in rows]


def export_sqlite_to_csv(sqlite_path: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    manifest = {
        "sqlite_path": str(sqlite_path),
        "output_dir": str(output_dir),
        "tables": [],
    }

    try:
        table_names = _load_table_names(conn)
        for table_name in table_names:
            columns = _load_columns(conn, table_name)
            csv_path = output_dir / f"{table_name}.csv"
            query = f"SELECT * FROM {_quote_identifier(table_name)}"
            rows = conn.execute(query).fetchall()

            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                for row in rows:
                    writer.writerow([row[column] for column in columns])

            manifest["tables"].append(
                {
                    "table": table_name,
                    "row_count": len(rows),
                    "columns": columns,
                    "csv_file": csv_path.name,
                }
            )
    finally:
        conn.close()

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Export all SQLite tables into CSV files.")
    parser.add_argument("sqlite_path", help="Path to the SQLite database file.")
    parser.add_argument(
        "--output-dir",
        default="sqlite_export",
        help="Folder for CSV output and manifest.json.",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite_path).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()

    if not sqlite_path.exists():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")

    manifest = export_sqlite_to_csv(sqlite_path, output_dir)
    table_total = len(manifest["tables"])
    row_total = sum(int(item["row_count"]) for item in manifest["tables"])
    print(f"Export selesai: {table_total} tabel, {row_total} baris, folder {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
