import os
import sqlite3
from flask import current_app, g


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

        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = NORMAL")
            db.execute("PRAGMA temp_store = MEMORY")
            db.execute("PRAGMA busy_timeout = 30000")
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
