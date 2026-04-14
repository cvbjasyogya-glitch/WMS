import argparse
import json
from pathlib import Path


DEFAULT_PATTERNS = [
    "import sqlite3",
    "sqlite3.",
    "sqlite_master",
    "PRAGMA ",
    "datetime('now'",
    "date('now'",
    "julianday(",
    "last_insert_rowid(",
    "INSERT OR REPLACE",
    "ON CONFLICT",
]

IGNORED_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
}


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if any(part in IGNORED_DIR_NAMES for part in path.parts):
            continue
        yield path


def build_sqlite_dependency_report(root: Path, patterns: list[str]) -> dict:
    findings = []
    for path in sorted(_iter_python_files(root)):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue

        relative_path = path.relative_to(root).as_posix()
        for line_number, line in enumerate(lines, start=1):
            for pattern in patterns:
                if pattern in line:
                    findings.append(
                        {
                            "file": relative_path,
                            "line": line_number,
                            "pattern": pattern,
                            "snippet": line.strip(),
                        }
                    )

    summary = {}
    for item in findings:
        summary[item["pattern"]] = summary.get(item["pattern"], 0) + 1

    return {
        "root": str(root),
        "total_findings": len(findings),
        "patterns": patterns,
        "summary": summary,
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit Python files for SQLite-specific dependencies before PostgreSQL migration.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Project root to scan. Defaults to current directory.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output instead of plain text.",
    )
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    report = build_sqlite_dependency_report(root, DEFAULT_PATTERNS)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f"Root scan: {report['root']}")
    print(f"Total temuan SQLite-spesifik: {report['total_findings']}")
    print("")
    print("Ringkasan pattern:")
    for pattern in report["patterns"]:
        print(f"- {pattern}: {report['summary'].get(pattern, 0)}")

    print("")
    print("Temuan:")
    for item in report["findings"]:
        print(f"- {item['file']}:{item['line']} [{item['pattern']}] {item['snippet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
