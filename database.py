import os
import sqlite3
from flask import current_app, g


def _normalize_sqlite_options(options=None):
    opts = options or {}
    journal_mode = str(opts.get("journal_mode") or "WAL").strip().upper()
    synchronous = str(opts.get("synchronous") or "FULL").strip().upper()
    temp_store = str(opts.get("temp_store") or "MEMORY").strip().upper()
    try:
        busy_timeout_ms = int(opts.get("busy_timeout_ms", 30000))
    except (TypeError, ValueError):
        busy_timeout_ms = 30000
    foreign_keys = bool(opts.get("foreign_keys", True))

    if journal_mode not in {"DELETE", "TRUNCATE", "PERSIST", "MEMORY", "WAL", "OFF"}:
        journal_mode = "WAL"
    if synchronous not in {"OFF", "NORMAL", "FULL", "EXTRA"}:
        synchronous = "FULL"
    if temp_store not in {"DEFAULT", "FILE", "MEMORY"}:
        temp_store = "MEMORY"
    busy_timeout_ms = max(1000, min(busy_timeout_ms, 300000))

    return {
        "journal_mode": journal_mode,
        "synchronous": synchronous,
        "temp_store": temp_store,
        "busy_timeout_ms": busy_timeout_ms,
        "foreign_keys": foreign_keys,
    }


def _database_error_with_repair_hint(path, exc):
    return sqlite3.DatabaseError(
        f"{exc}. Database '{path}' appears corrupted or unreadable. "
        f"Stop the app and run 'python3 scripts/repair_sqlite_db.py {path} --replace', "
        "or restore a valid backup before restarting the service."
    )


def get_db():
    db = g.get("db")

    if db is None:
        db_path = current_app.config["DATABASE"]

        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        db = sqlite3.connect(
            db_path,
            timeout=30,
            check_same_thread=False,
            isolation_level=None,
        )

        db.row_factory = sqlite3.Row

        sqlite_runtime = _normalize_sqlite_options(
            {
                "journal_mode": current_app.config.get("SQLITE_JOURNAL_MODE", "WAL"),
                "synchronous": current_app.config.get("SQLITE_SYNCHRONOUS", "FULL"),
                "busy_timeout_ms": current_app.config.get("SQLITE_BUSY_TIMEOUT_MS", 30000),
                "temp_store": current_app.config.get("SQLITE_TEMP_STORE", "MEMORY"),
                "foreign_keys": current_app.config.get("SQLITE_FOREIGN_KEYS", True),
            }
        )

        try:
            db.execute(
                f"PRAGMA foreign_keys = {'ON' if sqlite_runtime['foreign_keys'] else 'OFF'}"
            )
            db.execute(f"PRAGMA journal_mode = {sqlite_runtime['journal_mode']}")
            db.execute(f"PRAGMA synchronous = {sqlite_runtime['synchronous']}")
            db.execute(f"PRAGMA temp_store = {sqlite_runtime['temp_store']}")
            db.execute(f"PRAGMA busy_timeout = {sqlite_runtime['busy_timeout_ms']}")
        except sqlite3.DatabaseError as exc:
            try:
                db.close()
            except Exception:
                pass
            raise _database_error_with_repair_hint(db_path, exc) from exc
        except sqlite3.Error:
            pass

        g.db = db

    return db


def close_db(e=None):
    db = g.pop("db", None)

    if db is not None:
        try:
            db.close()
        except Exception:
            pass
