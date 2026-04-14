import os
import re
import sqlite3
from collections.abc import Iterator, Mapping

from flask import current_app, g

try:
    import psycopg
    from psycopg.rows import tuple_row
    from psycopg import errors as psycopg_errors
except ImportError:  # pragma: no cover - exercised only when psycopg is absent
    psycopg = None
    tuple_row = None
    psycopg_errors = None


_QMARK_PATTERN = re.compile(r"\?")


class CompatRow(Mapping):
    def __init__(self, columns, values):
        self._columns = [str(column) for column in (columns or [])]
        self._values = list(values or [])
        self._mapping = dict(zip(self._columns, self._values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._mapping)

    def __len__(self) -> int:
        return len(self._mapping)

    def keys(self):
        return self._mapping.keys()

    def values(self):
        return self._mapping.values()

    def items(self):
        return self._mapping.items()


class CompatCursor:
    def __init__(self, connection, base_cursor=None, rows=None, columns=None, lastrowid=None):
        self._connection = connection
        self._base_cursor = base_cursor
        self._rows = rows
        self._columns = list(columns or [])
        self.lastrowid = lastrowid

    def _build_rows(self):
        if self._rows is not None:
            return list(self._rows)
        if self._base_cursor is None:
            return []
        fetched = self._base_cursor.fetchall()
        description = getattr(self._base_cursor, "description", None) or []
        columns = [str(item[0]) for item in description]
        return [CompatRow(columns, row) for row in fetched]

    def fetchone(self):
        rows = self._build_rows()
        if self._rows is None:
            self._rows = rows
        return rows[0] if rows else None

    def fetchall(self):
        rows = self._build_rows()
        if self._rows is None:
            self._rows = rows
        return list(rows)

    def __iter__(self):
        return iter(self.fetchall())


class PostgresCompatConnection:
    def __init__(self, connection):
        self._connection = connection

    def _run_query(self, query, parameters=()):
        translated = _translate_sqlite_query_to_postgres(query)
        converted_parameters = tuple(parameters or ())
        try:
            cursor = self._connection.cursor(row_factory=tuple_row)
            cursor.execute(translated, converted_parameters)
            lastrowid = _infer_postgres_lastrowid(
                self._connection,
                translated,
            )
            return CompatCursor(self, base_cursor=cursor, lastrowid=lastrowid)
        except Exception as exc:  # pragma: no cover - depends on psycopg runtime
            raise _coerce_db_exception(exc) from exc

    def execute(self, query, parameters=()):
        special_cursor = _handle_special_postgres_query(
            self,
            query,
            parameters,
            database_url=current_app.config.get("DATABASE_URL", ""),
        )
        if special_cursor is not None:
            return special_cursor
        return self._run_query(query, parameters)

    def executemany(self, query, seq_of_parameters):
        translated = _translate_sqlite_query_to_postgres(query)
        try:
            cursor = self._connection.cursor(row_factory=tuple_row)
            cursor.executemany(translated, list(seq_of_parameters or []))
            return CompatCursor(self, base_cursor=cursor)
        except Exception as exc:  # pragma: no cover - depends on psycopg runtime
            raise _coerce_db_exception(exc) from exc

    def commit(self):
        try:
            self._connection.commit()
        except Exception as exc:  # pragma: no cover - depends on psycopg runtime
            raise _coerce_db_exception(exc) from exc

    def rollback(self):
        try:
            self._connection.rollback()
        except Exception as exc:  # pragma: no cover - depends on psycopg runtime
            raise _coerce_db_exception(exc) from exc

    def close(self):
        self._connection.close()

    def cursor(self):
        return self._connection.cursor(row_factory=tuple_row)


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


def get_database_backend(config_source=None):
    source = config_source or current_app.config
    return str(source.get("DATABASE_BACKEND") or "sqlite").strip().lower()


def is_postgresql_backend(config_source=None):
    return get_database_backend(config_source) == "postgresql"


def is_sqlite_backend(config_source=None):
    return get_database_backend(config_source) == "sqlite"


def _database_error_with_repair_hint(path, exc):
    return sqlite3.DatabaseError(
        f"{exc}. Database '{path}' appears corrupted or unreadable. "
        f"Stop the app and run 'python3 scripts/repair_sqlite_db.py {path} --replace', "
        "or restore a valid backup before restarting the service."
    )


def _replace_qmark_placeholders(query):
    result = []
    in_single_quote = False
    in_double_quote = False

    for character in str(query or ""):
        if character == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            result.append(character)
            continue
        if character == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            result.append(character)
            continue
        if character == "?" and not in_single_quote and not in_double_quote:
            result.append("%s")
            continue
        result.append(character)

    return "".join(result)


def _translate_sqlite_query_to_postgres(query):
    translated = _replace_qmark_placeholders(query)
    translated = _replace_like_operators(translated)
    translated = re.sub(r"\s+COLLATE\s+NOCASE\b", "", translated, flags=re.IGNORECASE)
    translated = re.sub(r"\bBEGIN\s+IMMEDIATE\b", "BEGIN", translated, flags=re.IGNORECASE)
    translated = re.sub(r"\bBEGIN\s+EXCLUSIVE\b", "BEGIN", translated, flags=re.IGNORECASE)
    translated = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        translated,
        flags=re.IGNORECASE,
    )
    translated = _replace_sql_function_calls(translated, "group_concat", _translate_group_concat_call)
    translated = _replace_sql_function_calls(translated, "julianday", _translate_julianday_call)
    translated = _replace_sql_function_calls(translated, "strftime", _translate_strftime_call)
    translated = _replace_sql_function_calls(translated, "datetime", _translate_datetime_call)
    translated = _replace_sql_function_calls(translated, "date", _translate_date_call)
    translated = translated.replace("SELECT last_insert_rowid()", "SELECT LASTVAL()")
    translated = translated.replace("last_insert_rowid()", "LASTVAL()")
    translated = translated.replace("AUTOINCREMENT", "")
    if "INSERT OR IGNORE" not in str(query or "").upper() and "ON CONFLICT" in translated.upper():
        return translated
    if "INSERT OR IGNORE" in str(query or "").upper() and "ON CONFLICT" not in translated.upper():
        translated = translated.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return translated


def _replace_like_operators(query):
    source = str(query or "")
    result = []
    index = 0
    in_single_quote = False
    in_double_quote = False

    while index < len(source):
        character = source[index]
        if character == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            result.append(character)
            index += 1
            continue
        if character == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            result.append(character)
            index += 1
            continue

        if not in_single_quote and not in_double_quote:
            upper_fragment = source[index:index + 8].upper()
            if upper_fragment.startswith("NOT LIKE"):
                result.append("NOT ILIKE")
                index += 8
                continue
            upper_fragment = source[index:index + 4].upper()
            if upper_fragment == "LIKE":
                previous = source[index - 1] if index > 0 else " "
                following = source[index + 4] if index + 4 < len(source) else " "
                if not (previous.isalnum() or previous == "_") and not (following.isalnum() or following == "_"):
                    result.append("ILIKE")
                    index += 4
                    continue

        result.append(character)
        index += 1

    return "".join(result)


def _split_sql_arguments(argument_string):
    parts = []
    current = []
    depth = 0
    in_single_quote = False
    in_double_quote = False

    for character in str(argument_string or ""):
        if character == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(character)
            continue
        if character == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(character)
            continue
        if character == "," and depth == 0 and not in_single_quote and not in_double_quote:
            parts.append("".join(current).strip())
            current = []
            continue
        if character == "(" and not in_single_quote and not in_double_quote:
            depth += 1
        elif character == ")" and depth > 0 and not in_single_quote and not in_double_quote:
            depth -= 1
        current.append(character)

    if current:
        parts.append("".join(current).strip())
    return parts


def _replace_sql_function_calls(query, function_name, replacer):
    source = str(query or "")
    lower_source = source.lower()
    lower_function = str(function_name or "").strip().lower()
    result = []
    cursor = 0
    search_token = f"{lower_function}("

    while cursor < len(source):
        match_index = lower_source.find(search_token, cursor)
        if match_index < 0:
            result.append(source[cursor:])
            break

        result.append(source[cursor:match_index])
        open_paren_index = match_index + len(lower_function)
        depth = 0
        in_single_quote = False
        in_double_quote = False
        close_paren_index = None

        for index in range(open_paren_index, len(source)):
            character = source[index]
            if character == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
            elif character == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
            elif not in_single_quote and not in_double_quote:
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0:
                        close_paren_index = index
                        break

        if close_paren_index is None:
            result.append(source[match_index:])
            break

        raw_call = source[match_index:close_paren_index + 1]
        argument_string = source[open_paren_index + 1:close_paren_index]
        replacement = replacer(argument_string, raw_call=raw_call)
        result.append(replacement)
        cursor = close_paren_index + 1

    return "".join(result)


def _normalize_sql_literal(value):
    return str(value or "").strip().strip("'").strip('"').strip().lower()


def _translate_julianday_call(argument_string, raw_call=""):
    argument = str(argument_string or "").strip()
    if _normalize_sql_literal(argument) == "now":
        return "(EXTRACT(EPOCH FROM CURRENT_TIMESTAMP) / 86400.0)"
    return f"(EXTRACT(EPOCH FROM CAST({argument} AS timestamp)) / 86400.0)"


def _translate_group_concat_call(argument_string, raw_call=""):
    arguments = _split_sql_arguments(argument_string)
    if not arguments:
        return raw_call

    expression = str(arguments[0] or "").strip()
    separator = arguments[1] if len(arguments) > 1 else "','"
    distinct_prefix = ""
    upper_expression = expression.upper()
    if upper_expression.startswith("DISTINCT "):
        distinct_prefix = "DISTINCT "
        expression = expression[9:].strip()

    if not expression:
        return raw_call

    return f"STRING_AGG({distinct_prefix}{expression}, {separator})"


def _build_temporal_base_expression(argument, *, date_only=False):
    normalized = _normalize_sql_literal(argument)
    if normalized == "now":
        return "CURRENT_DATE" if date_only else "CURRENT_TIMESTAMP"
    cast_type = "date" if date_only else "timestamp"
    return f"CAST({str(argument or '').strip()} AS {cast_type})"


def _apply_temporal_modifiers(base_expression, modifiers, *, date_only=False):
    expression = str(base_expression or "").strip()
    for modifier in modifiers:
        raw_modifier = str(modifier or "").strip()
        safe_modifier = _normalize_sql_literal(raw_modifier)
        if not raw_modifier:
            continue
        if raw_modifier == "%s":
            expression = f"({expression} + CAST(%s AS interval))"
            continue
        expression = f"({expression} + INTERVAL '{safe_modifier}')"
    if date_only:
        return f"{expression}::date"
    return expression


def _translate_datetime_call(argument_string, raw_call=""):
    arguments = _split_sql_arguments(argument_string)
    if not arguments:
        return raw_call
    base_expression = _build_temporal_base_expression(arguments[0], date_only=False)
    return _apply_temporal_modifiers(base_expression, arguments[1:], date_only=False)


def _translate_date_call(argument_string, raw_call=""):
    arguments = _split_sql_arguments(argument_string)
    if not arguments:
        return raw_call
    base_expression = _build_temporal_base_expression(arguments[0], date_only=True)
    return _apply_temporal_modifiers(base_expression, arguments[1:], date_only=True)


def _translate_strftime_call(argument_string, raw_call=""):
    arguments = _split_sql_arguments(argument_string)
    if len(arguments) < 2:
        return raw_call

    pattern = _normalize_sql_literal(arguments[0])
    expression = arguments[1]
    timestamp_expr = f"CAST({expression} AS timestamp)"

    if pattern == "%w":
        return f"CAST(EXTRACT(DOW FROM {timestamp_expr}) AS integer)"
    if pattern == "%y-%m":
        return f"TO_CHAR({timestamp_expr}, 'YY-MM')"
    if pattern == "%y-%m-%d":
        return f"TO_CHAR({timestamp_expr}, 'YY-MM-DD')"
    if pattern == "%h:%m":
        return f"TO_CHAR({timestamp_expr}, 'HH24:MI')"

    return raw_call


def _coerce_db_exception(exc):
    message = str(exc)
    if psycopg_errors is not None:
        if isinstance(exc, psycopg_errors.IntegrityError):
            return sqlite3.IntegrityError(message)
        if isinstance(exc, psycopg_errors.OperationalError):
            return sqlite3.OperationalError(message)
        if isinstance(exc, psycopg_errors.DatabaseError):
            return sqlite3.DatabaseError(message)
    return sqlite3.DatabaseError(message)


def _pragma_name_from_query(query):
    safe_query = str(query or "").strip().rstrip(";")
    if not safe_query.upper().startswith("PRAGMA"):
        return ""
    remainder = safe_query[6:].strip()
    return remainder.split("=", 1)[0].strip().split("(", 1)[0].strip().lower()


def _extract_pragma_table_name(query):
    safe_query = str(query or "").strip().rstrip(";")
    match = re.search(r"table_info\(([^)]+)\)", safe_query, re.IGNORECASE)
    if not match:
        return ""
    return str(match.group(1)).strip().strip('"').strip("'")


def _build_synthetic_cursor(connection, columns, rows):
    compat_rows = [CompatRow(columns, row) for row in (rows or [])]
    return CompatCursor(connection, rows=compat_rows, columns=columns)


def _handle_special_postgres_query(connection, query, parameters=(), database_url=""):
    safe_query = str(query or "").strip()
    upper_query = safe_query.upper()

    if not safe_query:
        return _build_synthetic_cursor(connection, [], [])

    if upper_query.startswith("PRAGMA "):
        pragma_name = _pragma_name_from_query(safe_query)
        if pragma_name in {"foreign_keys", "journal_mode", "synchronous", "temp_store", "busy_timeout", "wal_checkpoint"}:
            return _build_synthetic_cursor(connection, [], [])
        if pragma_name == "integrity_check":
            return _build_synthetic_cursor(connection, ["integrity_check"], [("ok",)])
        if pragma_name == "database_list":
            return _build_synthetic_cursor(
                connection,
                ["seq", "name", "file"],
                [(0, "main", str(database_url or ""))],
            )
        if pragma_name == "table_info":
            table_name = _extract_pragma_table_name(safe_query)
            rows = connection._run_query(
                """
                SELECT
                    ordinal_position - 1 AS cid,
                    column_name AS name,
                    data_type AS type,
                    CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull,
                    column_default AS dflt_value,
                    CASE WHEN ordinal_position = 1
                              AND column_name = 'id'
                              AND EXISTS (
                                  SELECT 1
                                  FROM information_schema.table_constraints tc
                                  JOIN information_schema.key_column_usage kcu
                                    ON tc.constraint_name = kcu.constraint_name
                                   AND tc.table_schema = kcu.table_schema
                                 WHERE tc.table_schema = 'public'
                                   AND tc.table_name = %s
                                   AND tc.constraint_type = 'PRIMARY KEY'
                                   AND kcu.column_name = column_name
                              )
                         THEN 1 ELSE 0 END AS pk
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table_name, table_name),
            ).fetchall()
            return CompatCursor(connection, rows=rows)

    if "FROM SQLITE_MASTER" in upper_query and "TYPE='TABLE'" in upper_query:
        if "SELECT 1" in upper_query:
            target_name = parameters[0] if parameters else ""
            rows = connection._run_query(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (target_name,),
            ).fetchall()
            return CompatCursor(connection, rows=rows)
        if "SELECT SQL" in upper_query:
            return _build_synthetic_cursor(connection, ["sql"], [(None,)])

    return None


def _infer_postgres_lastrowid(connection, translated_query):
    stripped = str(translated_query or "").strip().upper()
    if not stripped.startswith("INSERT"):
        return None
    if " RETURNING " in f" {stripped} ":
        return None
    try:
        cursor = connection.cursor(row_factory=tuple_row)
        cursor.execute("SELECT LASTVAL()")
        row = cursor.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _connect_sqlite():
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

    return db


def _connect_postgresql():
    if psycopg is None:  # pragma: no cover - depends on optional dependency install
        raise RuntimeError(
            "DATABASE_BACKEND=postgresql membutuhkan dependency psycopg. "
            "Install dependency terbaru dari requirements.txt terlebih dulu."
        )
    database_url = str(current_app.config.get("DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL wajib diisi saat DATABASE_BACKEND=postgresql.")

    connection = psycopg.connect(
        database_url,
        autocommit=True,
    )
    return PostgresCompatConnection(connection)


def get_db():
    db = g.get("db")

    if db is None:
        backend = str(current_app.config.get("DATABASE_BACKEND") or "sqlite").strip().lower()
        if backend == "postgresql":
            db = _connect_postgresql()
        else:
            db = _connect_sqlite()
        g.db = db

    return db


def close_db(e=None):
    db = g.pop("db", None)

    if db is not None:
        try:
            db.close()
        except Exception:
            pass
