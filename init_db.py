import sqlite3
import os
from werkzeug.security import generate_password_hash

# ==========================
# SINGLE SOURCE DATABASE (FIX)
# ==========================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")


def get_connection(db_path=None):
    path = db_path or DB_PATH
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")

    return conn


def _table_exists(cursor, table_name):
    row = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(cursor, table_name, column_name):
    if not _table_exists(cursor, table_name):
        return False

    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def _ensure_column(cursor, table_name, column_name, definition):
    if _table_exists(cursor, table_name) and not _column_exists(cursor, table_name, column_name):
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )


def migrate_schema(cursor):
    # Keep existing databases compatible with the newer routes/services.
    _ensure_column(cursor, "product_variants", "price_retail", "REAL DEFAULT 0")
    _ensure_column(cursor, "product_variants", "price_discount", "REAL DEFAULT 0")
    _ensure_column(cursor, "product_variants", "price_nett", "REAL DEFAULT 0")
    _ensure_column(cursor, "product_variants", "variant_code", "TEXT")
    _ensure_column(cursor, "product_variants", "color", "TEXT")
    _ensure_column(cursor, "product_variants", "gtin", "TEXT")
    _ensure_column(cursor, "product_variants", "no_gtin", "INTEGER DEFAULT 0")

    _ensure_column(cursor, "requests", "reason", "TEXT")
    _ensure_column(cursor, "requests", "approved_at", "TIMESTAMP")
    _ensure_column(cursor, "requests", "approved_by", "INTEGER")
    _ensure_column(cursor, "requests", "requested_by", "INTEGER")
    # add contact fields for user notifications
    _ensure_column(cursor, "users", "email", "TEXT")
    _ensure_column(cursor, "users", "phone", "TEXT")
    # per-account notification preferences
    _ensure_column(cursor, "users", "notify_email", "INTEGER DEFAULT 1")
    _ensure_column(cursor, "users", "notify_whatsapp", "INTEGER DEFAULT 0")
    _ensure_column(cursor, "users", "chat_sound_volume", "REAL DEFAULT 0.85")
    # user assigned warehouse (for single-warehouse roles)
    _ensure_column(cursor, "users", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "users", "employee_id", "INTEGER")
    _ensure_column(cursor, "owner_requests", "note", "TEXT")
    _ensure_column(cursor, "owner_requests", "status", "TEXT DEFAULT 'pending'")
    _ensure_column(cursor, "owner_requests", "requested_by", "INTEGER")
    _ensure_column(cursor, "owner_requests", "handled_by", "INTEGER")
    _ensure_column(cursor, "owner_requests", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "employees", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "employees", "department", "TEXT")
    _ensure_column(cursor, "employees", "position", "TEXT")
    _ensure_column(cursor, "employees", "employment_status", "TEXT DEFAULT 'active'")
    _ensure_column(cursor, "employees", "phone", "TEXT")
    _ensure_column(cursor, "employees", "email", "TEXT")
    _ensure_column(cursor, "employees", "join_date", "TEXT")
    _ensure_column(cursor, "employees", "work_location", "TEXT")
    _ensure_column(cursor, "employees", "notes", "TEXT")
    _ensure_column(cursor, "employees", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "attendance_records", "employee_id", "INTEGER")
    _ensure_column(cursor, "attendance_records", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "attendance_records", "attendance_date", "TEXT")
    _ensure_column(cursor, "attendance_records", "check_in", "TEXT")
    _ensure_column(cursor, "attendance_records", "check_out", "TEXT")
    _ensure_column(cursor, "attendance_records", "status", "TEXT DEFAULT 'present'")
    _ensure_column(cursor, "attendance_records", "shift_code", "TEXT")
    _ensure_column(cursor, "attendance_records", "shift_label", "TEXT")
    _ensure_column(cursor, "attendance_records", "note", "TEXT")
    _ensure_column(cursor, "attendance_records", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "leave_requests", "employee_id", "INTEGER")
    _ensure_column(cursor, "leave_requests", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "leave_requests", "leave_type", "TEXT DEFAULT 'annual'")
    _ensure_column(cursor, "leave_requests", "start_date", "TEXT")
    _ensure_column(cursor, "leave_requests", "end_date", "TEXT")
    _ensure_column(cursor, "leave_requests", "total_days", "INTEGER DEFAULT 1")
    _ensure_column(cursor, "leave_requests", "status", "TEXT DEFAULT 'pending'")
    _ensure_column(cursor, "leave_requests", "reason", "TEXT")
    _ensure_column(cursor, "leave_requests", "note", "TEXT")
    _ensure_column(cursor, "leave_requests", "handled_by", "INTEGER")
    _ensure_column(cursor, "leave_requests", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "leave_requests", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "payroll_runs", "employee_id", "INTEGER")
    _ensure_column(cursor, "payroll_runs", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "payroll_runs", "period_month", "INTEGER")
    _ensure_column(cursor, "payroll_runs", "period_year", "INTEGER")
    _ensure_column(cursor, "payroll_runs", "base_salary", "REAL DEFAULT 0")
    _ensure_column(cursor, "payroll_runs", "allowance", "REAL DEFAULT 0")
    _ensure_column(cursor, "payroll_runs", "overtime_pay", "REAL DEFAULT 0")
    _ensure_column(cursor, "payroll_runs", "deduction", "REAL DEFAULT 0")
    _ensure_column(cursor, "payroll_runs", "leave_deduction", "REAL DEFAULT 0")
    _ensure_column(cursor, "payroll_runs", "net_pay", "REAL DEFAULT 0")
    _ensure_column(cursor, "payroll_runs", "status", "TEXT DEFAULT 'draft'")
    _ensure_column(cursor, "payroll_runs", "note", "TEXT")
    _ensure_column(cursor, "payroll_runs", "handled_by", "INTEGER")
    _ensure_column(cursor, "payroll_runs", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "payroll_runs", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "recruitment_candidates", "candidate_name", "TEXT")
    _ensure_column(cursor, "recruitment_candidates", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "recruitment_candidates", "position_title", "TEXT")
    _ensure_column(cursor, "recruitment_candidates", "department", "TEXT")
    _ensure_column(cursor, "recruitment_candidates", "stage", "TEXT DEFAULT 'applied'")
    _ensure_column(cursor, "recruitment_candidates", "status", "TEXT DEFAULT 'active'")
    _ensure_column(cursor, "recruitment_candidates", "source", "TEXT")
    _ensure_column(cursor, "recruitment_candidates", "phone", "TEXT")
    _ensure_column(cursor, "recruitment_candidates", "email", "TEXT")
    _ensure_column(cursor, "recruitment_candidates", "expected_join_date", "TEXT")
    _ensure_column(cursor, "recruitment_candidates", "note", "TEXT")
    _ensure_column(cursor, "recruitment_candidates", "handled_by", "INTEGER")
    _ensure_column(cursor, "recruitment_candidates", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "recruitment_candidates", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "onboarding_records", "employee_id", "INTEGER")
    _ensure_column(cursor, "onboarding_records", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "onboarding_records", "start_date", "TEXT")
    _ensure_column(cursor, "onboarding_records", "target_date", "TEXT")
    _ensure_column(cursor, "onboarding_records", "stage", "TEXT DEFAULT 'preboarding'")
    _ensure_column(cursor, "onboarding_records", "status", "TEXT DEFAULT 'pending'")
    _ensure_column(cursor, "onboarding_records", "buddy_name", "TEXT")
    _ensure_column(cursor, "onboarding_records", "note", "TEXT")
    _ensure_column(cursor, "onboarding_records", "handled_by", "INTEGER")
    _ensure_column(cursor, "onboarding_records", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "onboarding_records", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "offboarding_records", "employee_id", "INTEGER")
    _ensure_column(cursor, "offboarding_records", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "offboarding_records", "notice_date", "TEXT")
    _ensure_column(cursor, "offboarding_records", "last_working_date", "TEXT")
    _ensure_column(cursor, "offboarding_records", "stage", "TEXT DEFAULT 'notice'")
    _ensure_column(cursor, "offboarding_records", "status", "TEXT DEFAULT 'planned'")
    _ensure_column(cursor, "offboarding_records", "exit_reason", "TEXT")
    _ensure_column(cursor, "offboarding_records", "handover_pic", "TEXT")
    _ensure_column(cursor, "offboarding_records", "note", "TEXT")
    _ensure_column(cursor, "offboarding_records", "handled_by", "INTEGER")
    _ensure_column(cursor, "offboarding_records", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "offboarding_records", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "performance_reviews", "employee_id", "INTEGER")
    _ensure_column(cursor, "performance_reviews", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "performance_reviews", "review_period", "TEXT")
    _ensure_column(cursor, "performance_reviews", "goal_score", "REAL DEFAULT 0")
    _ensure_column(cursor, "performance_reviews", "discipline_score", "REAL DEFAULT 0")
    _ensure_column(cursor, "performance_reviews", "teamwork_score", "REAL DEFAULT 0")
    _ensure_column(cursor, "performance_reviews", "final_score", "REAL DEFAULT 0")
    _ensure_column(cursor, "performance_reviews", "rating", "TEXT DEFAULT 'fair'")
    _ensure_column(cursor, "performance_reviews", "status", "TEXT DEFAULT 'draft'")
    _ensure_column(cursor, "performance_reviews", "reviewer_name", "TEXT")
    _ensure_column(cursor, "performance_reviews", "note", "TEXT")
    _ensure_column(cursor, "performance_reviews", "handled_by", "INTEGER")
    _ensure_column(cursor, "performance_reviews", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "performance_reviews", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "helpdesk_tickets", "employee_id", "INTEGER")
    _ensure_column(cursor, "helpdesk_tickets", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "helpdesk_tickets", "ticket_title", "TEXT")
    _ensure_column(cursor, "helpdesk_tickets", "category", "TEXT DEFAULT 'other'")
    _ensure_column(cursor, "helpdesk_tickets", "priority", "TEXT DEFAULT 'medium'")
    _ensure_column(cursor, "helpdesk_tickets", "status", "TEXT DEFAULT 'open'")
    _ensure_column(cursor, "helpdesk_tickets", "channel", "TEXT")
    _ensure_column(cursor, "helpdesk_tickets", "assigned_to", "TEXT")
    _ensure_column(cursor, "helpdesk_tickets", "note", "TEXT")
    _ensure_column(cursor, "helpdesk_tickets", "handled_by", "INTEGER")
    _ensure_column(cursor, "helpdesk_tickets", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "helpdesk_tickets", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "asset_records", "employee_id", "INTEGER")
    _ensure_column(cursor, "asset_records", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "asset_records", "asset_name", "TEXT")
    _ensure_column(cursor, "asset_records", "asset_code", "TEXT")
    _ensure_column(cursor, "asset_records", "serial_number", "TEXT")
    _ensure_column(cursor, "asset_records", "category", "TEXT")
    _ensure_column(cursor, "asset_records", "asset_status", "TEXT DEFAULT 'allocated'")
    _ensure_column(cursor, "asset_records", "condition_status", "TEXT DEFAULT 'good'")
    _ensure_column(cursor, "asset_records", "assigned_date", "TEXT")
    _ensure_column(cursor, "asset_records", "return_date", "TEXT")
    _ensure_column(cursor, "asset_records", "note", "TEXT")
    _ensure_column(cursor, "asset_records", "handled_by", "INTEGER")
    _ensure_column(cursor, "asset_records", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "asset_records", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "project_records", "employee_id", "INTEGER")
    _ensure_column(cursor, "project_records", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "project_records", "project_name", "TEXT")
    _ensure_column(cursor, "project_records", "project_code", "TEXT")
    _ensure_column(cursor, "project_records", "priority", "TEXT DEFAULT 'medium'")
    _ensure_column(cursor, "project_records", "status", "TEXT DEFAULT 'planning'")
    _ensure_column(cursor, "project_records", "start_date", "TEXT")
    _ensure_column(cursor, "project_records", "due_date", "TEXT")
    _ensure_column(cursor, "project_records", "progress_percent", "INTEGER DEFAULT 0")
    _ensure_column(cursor, "project_records", "owner_name", "TEXT")
    _ensure_column(cursor, "project_records", "note", "TEXT")
    _ensure_column(cursor, "project_records", "handled_by", "INTEGER")
    _ensure_column(cursor, "project_records", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "project_records", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "biometric_logs", "employee_id", "INTEGER")
    _ensure_column(cursor, "biometric_logs", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "biometric_logs", "device_name", "TEXT")
    _ensure_column(cursor, "biometric_logs", "device_user_id", "TEXT")
    _ensure_column(cursor, "biometric_logs", "punch_time", "TEXT")
    _ensure_column(cursor, "biometric_logs", "punch_type", "TEXT DEFAULT 'check_in'")
    _ensure_column(cursor, "biometric_logs", "sync_status", "TEXT DEFAULT 'queued'")
    _ensure_column(cursor, "biometric_logs", "location_label", "TEXT")
    _ensure_column(cursor, "biometric_logs", "latitude", "REAL")
    _ensure_column(cursor, "biometric_logs", "longitude", "REAL")
    _ensure_column(cursor, "biometric_logs", "accuracy_m", "REAL DEFAULT 0")
    _ensure_column(cursor, "biometric_logs", "shift_code", "TEXT")
    _ensure_column(cursor, "biometric_logs", "shift_label", "TEXT")
    _ensure_column(cursor, "biometric_logs", "photo_path", "TEXT")
    _ensure_column(cursor, "biometric_logs", "photo_captured_at", "TEXT")
    _ensure_column(cursor, "biometric_logs", "note", "TEXT")
    _ensure_column(cursor, "biometric_logs", "handled_by", "INTEGER")
    _ensure_column(cursor, "biometric_logs", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "biometric_logs", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "announcement_posts", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "announcement_posts", "title", "TEXT")
    _ensure_column(cursor, "announcement_posts", "audience", "TEXT DEFAULT 'all'")
    _ensure_column(cursor, "announcement_posts", "publish_date", "TEXT")
    _ensure_column(cursor, "announcement_posts", "expires_at", "TEXT")
    _ensure_column(cursor, "announcement_posts", "status", "TEXT DEFAULT 'draft'")
    _ensure_column(cursor, "announcement_posts", "channel", "TEXT")
    _ensure_column(cursor, "announcement_posts", "message", "TEXT")
    _ensure_column(cursor, "announcement_posts", "handled_by", "INTEGER")
    _ensure_column(cursor, "announcement_posts", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "announcement_posts", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "document_records", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "document_records", "document_title", "TEXT")
    _ensure_column(cursor, "document_records", "document_code", "TEXT")
    _ensure_column(cursor, "document_records", "document_type", "TEXT DEFAULT 'other'")
    _ensure_column(cursor, "document_records", "status", "TEXT DEFAULT 'draft'")
    _ensure_column(cursor, "document_records", "effective_date", "TEXT")
    _ensure_column(cursor, "document_records", "review_date", "TEXT")
    _ensure_column(cursor, "document_records", "owner_name", "TEXT")
    _ensure_column(cursor, "document_records", "note", "TEXT")
    _ensure_column(cursor, "document_records", "handled_by", "INTEGER")
    _ensure_column(cursor, "document_records", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "document_records", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "daily_live_reports", "user_id", "INTEGER")
    _ensure_column(cursor, "daily_live_reports", "employee_id", "INTEGER")
    _ensure_column(cursor, "daily_live_reports", "warehouse_id", "INTEGER")
    _ensure_column(cursor, "daily_live_reports", "report_type", "TEXT DEFAULT 'daily'")
    _ensure_column(cursor, "daily_live_reports", "report_date", "TEXT")
    _ensure_column(cursor, "daily_live_reports", "title", "TEXT")
    _ensure_column(cursor, "daily_live_reports", "summary", "TEXT")
    _ensure_column(cursor, "daily_live_reports", "blocker_note", "TEXT")
    _ensure_column(cursor, "daily_live_reports", "follow_up_note", "TEXT")
    _ensure_column(cursor, "daily_live_reports", "status", "TEXT DEFAULT 'submitted'")
    _ensure_column(cursor, "daily_live_reports", "hr_note", "TEXT")
    _ensure_column(cursor, "daily_live_reports", "handled_by", "INTEGER")
    _ensure_column(cursor, "daily_live_reports", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "daily_live_reports", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    _ensure_column(cursor, "chat_threads", "thread_type", "TEXT DEFAULT 'direct'")
    _ensure_column(cursor, "chat_threads", "group_name", "TEXT")
    _ensure_column(cursor, "chat_threads", "group_description", "TEXT")
    _ensure_column(cursor, "chat_messages", "message_type", "TEXT DEFAULT 'text'")
    _ensure_column(cursor, "chat_messages", "attachment_name", "TEXT")
    _ensure_column(cursor, "chat_messages", "attachment_path", "TEXT")
    _ensure_column(cursor, "chat_messages", "attachment_mime", "TEXT")
    _ensure_column(cursor, "chat_messages", "attachment_size", "INTEGER DEFAULT 0")
    _ensure_column(cursor, "chat_messages", "sticker_code", "TEXT")
    _ensure_column(cursor, "chat_messages", "call_mode", "TEXT")


def init_db(db_path=None):
    conn = get_connection(db_path)
    c = conn.cursor()

    # ==========================
    # CATEGORY
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS categories(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )
    """)

    # ==========================
    # PRODUCTS
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE,
        name TEXT,
        category_id INTEGER,
        FOREIGN KEY(category_id) REFERENCES categories(id)
    )
    """)

    # ==========================
    # VARIANTS
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS product_variants(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        variant TEXT,
        price_retail REAL DEFAULT 0,
        price_discount REAL DEFAULT 0,
        price_nett REAL DEFAULT 0,
        variant_code TEXT,
        color TEXT,
        gtin TEXT,
        no_gtin INTEGER DEFAULT 0,
        UNIQUE(product_id, variant),
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
    )
    """)

    # ==========================
    # WAREHOUSES
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS warehouses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )
    """)

    # ==========================
    # STOCK
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS stock(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        variant_id INTEGER,
        warehouse_id INTEGER,
        qty INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(product_id, variant_id, warehouse_id),
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
        FOREIGN KEY(variant_id) REFERENCES product_variants(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id)
    )
    """)

    # ==========================
    # STOCK BATCHES
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS stock_batches(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        variant_id INTEGER,
        warehouse_id INTEGER,
        qty INTEGER,
        remaining_qty INTEGER,
        cost REAL DEFAULT 0,
        expiry_date TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
        FOREIGN KEY(variant_id) REFERENCES product_variants(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id)
    )
    """)

    # ==========================
    # STOCK MOVEMENTS
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS stock_movements(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        variant_id INTEGER,
        warehouse_id INTEGER,
        batch_id INTEGER,
        qty INTEGER,
        type TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(batch_id) REFERENCES stock_batches(id) ON DELETE CASCADE
    )
    """)

    # ==========================
    # STOCK HISTORY
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS stock_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        variant_id INTEGER,
        warehouse_id INTEGER,
        action TEXT,
        type TEXT,
        qty INTEGER,
        note TEXT,
        user_id INTEGER,
        ip_address TEXT,
        user_agent TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
        FOREIGN KEY(variant_id) REFERENCES product_variants(id) ON DELETE CASCADE
    )
    """)

    # ==========================
    # REQUESTS
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        variant_id INTEGER,
        from_warehouse INTEGER,
        to_warehouse INTEGER,
        qty INTEGER,
        status TEXT DEFAULT 'pending',
        reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        approved_at TIMESTAMP,
        approved_by INTEGER
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS owner_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        variant_id INTEGER,
        warehouse_id INTEGER,
        qty INTEGER,
        note TEXT,
        status TEXT DEFAULT 'pending',
        requested_by INTEGER,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
        FOREIGN KEY(variant_id) REFERENCES product_variants(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(requested_by) REFERENCES users(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    # ==========================
    # USERS
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT
    )
    """)

    # If existing users table has a restrictive CHECK(role IN (...)) constraint,
    # rebuild the table without the CHECK to allow adding new roles.
    try:
        cur = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
        row = cur.fetchone()
        if row and 'CHECK(role IN' in (row[0] or ''):
            # rename old table
            c.execute("ALTER TABLE users RENAME TO users_old")

            # create new users table with email/phone fields
            c.execute("""
            CREATE TABLE users(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                role TEXT,
                email TEXT,
                phone TEXT
            )
            """)

            # copy data preserving ids
            c.execute("""
            INSERT INTO users(id, username, password, role, email, phone)
            SELECT id, username, password, role, email, phone FROM users_old
            """)

            c.execute("DROP TABLE users_old")
    except Exception:
        pass

    migrate_schema(c)

    c.execute("""
    CREATE TABLE IF NOT EXISTS employees(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_code TEXT UNIQUE,
        full_name TEXT,
        warehouse_id INTEGER,
        department TEXT,
        position TEXT,
        employment_status TEXT DEFAULT 'active',
        phone TEXT,
        email TEXT,
        join_date TEXT,
        work_location TEXT,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS attendance_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        attendance_date TEXT NOT NULL,
        check_in TEXT,
        check_out TEXT,
        status TEXT DEFAULT 'present',
        shift_code TEXT,
        shift_label TEXT,
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(employee_id, attendance_date),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS leave_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        leave_type TEXT DEFAULT 'annual',
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        total_days INTEGER DEFAULT 1,
        status TEXT DEFAULT 'pending',
        reason TEXT,
        note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS payroll_runs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        period_month INTEGER NOT NULL,
        period_year INTEGER NOT NULL,
        base_salary REAL DEFAULT 0,
        allowance REAL DEFAULT 0,
        overtime_pay REAL DEFAULT 0,
        deduction REAL DEFAULT 0,
        leave_deduction REAL DEFAULT 0,
        net_pay REAL DEFAULT 0,
        status TEXT DEFAULT 'draft',
        note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(employee_id, period_month, period_year),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS recruitment_candidates(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_name TEXT NOT NULL,
        warehouse_id INTEGER NOT NULL,
        position_title TEXT NOT NULL,
        department TEXT,
        stage TEXT DEFAULT 'applied',
        status TEXT DEFAULT 'active',
        source TEXT,
        phone TEXT,
        email TEXT,
        expected_join_date TEXT,
        note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS onboarding_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        start_date TEXT NOT NULL,
        target_date TEXT,
        stage TEXT DEFAULT 'preboarding',
        status TEXT DEFAULT 'pending',
        buddy_name TEXT,
        note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(employee_id),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS offboarding_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        notice_date TEXT NOT NULL,
        last_working_date TEXT,
        stage TEXT DEFAULT 'notice',
        status TEXT DEFAULT 'planned',
        exit_reason TEXT,
        handover_pic TEXT,
        note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(employee_id),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS performance_reviews(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        review_period TEXT NOT NULL,
        goal_score REAL DEFAULT 0,
        discipline_score REAL DEFAULT 0,
        teamwork_score REAL DEFAULT 0,
        final_score REAL DEFAULT 0,
        rating TEXT DEFAULT 'fair',
        status TEXT DEFAULT 'draft',
        reviewer_name TEXT,
        note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(employee_id, review_period),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS helpdesk_tickets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        ticket_title TEXT NOT NULL,
        category TEXT DEFAULT 'other',
        priority TEXT DEFAULT 'medium',
        status TEXT DEFAULT 'open',
        channel TEXT,
        assigned_to TEXT,
        note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS asset_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        asset_name TEXT NOT NULL,
        asset_code TEXT NOT NULL UNIQUE,
        serial_number TEXT,
        category TEXT,
        asset_status TEXT DEFAULT 'allocated',
        condition_status TEXT DEFAULT 'good',
        assigned_date TEXT NOT NULL,
        return_date TEXT,
        note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS project_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        project_name TEXT NOT NULL,
        project_code TEXT NOT NULL UNIQUE,
        priority TEXT DEFAULT 'medium',
        status TEXT DEFAULT 'planning',
        start_date TEXT NOT NULL,
        due_date TEXT,
        progress_percent INTEGER DEFAULT 0,
        owner_name TEXT,
        note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS biometric_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        warehouse_id INTEGER NOT NULL,
        device_name TEXT NOT NULL,
        device_user_id TEXT,
        punch_time TEXT NOT NULL,
        punch_type TEXT DEFAULT 'check_in',
        sync_status TEXT DEFAULT 'queued',
        location_label TEXT,
        latitude REAL,
        longitude REAL,
        accuracy_m REAL DEFAULT 0,
        shift_code TEXT,
        shift_label TEXT,
        photo_path TEXT,
        photo_captured_at TEXT,
        note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(employee_id, punch_time, punch_type),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS announcement_posts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        audience TEXT DEFAULT 'all',
        publish_date TEXT NOT NULL,
        expires_at TEXT,
        status TEXT DEFAULT 'draft',
        channel TEXT,
        message TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS document_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id INTEGER NOT NULL,
        document_title TEXT NOT NULL,
        document_code TEXT NOT NULL UNIQUE,
        document_type TEXT DEFAULT 'other',
        status TEXT DEFAULT 'draft',
        effective_date TEXT NOT NULL,
        review_date TEXT,
        owner_name TEXT,
        note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS daily_live_reports(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        employee_id INTEGER,
        warehouse_id INTEGER NOT NULL,
        report_type TEXT DEFAULT 'daily',
        report_date TEXT NOT NULL,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        blocker_note TEXT,
        follow_up_note TEXT,
        status TEXT DEFAULT 'submitted',
        hr_note TEXT,
        handled_by INTEGER,
        handled_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE SET NULL,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS dashboard_reminders(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id INTEGER,
        reminder_date TEXT NOT NULL,
        title TEXT NOT NULL,
        note TEXT,
        status TEXT DEFAULT 'open',
        created_by INTEGER,
        updated_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(created_by) REFERENCES users(id),
        FOREIGN KEY(updated_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS crm_customers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id INTEGER NOT NULL,
        customer_name TEXT NOT NULL,
        contact_person TEXT,
        phone TEXT,
        email TEXT,
        city TEXT,
        instagram_handle TEXT,
        customer_type TEXT DEFAULT 'retail',
        marketing_channel TEXT,
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(warehouse_id, customer_name, phone),
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS crm_memberships(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL UNIQUE,
        warehouse_id INTEGER NOT NULL,
        member_code TEXT NOT NULL UNIQUE,
        tier TEXT DEFAULT 'regular',
        status TEXT DEFAULT 'active',
        join_date TEXT NOT NULL,
        expiry_date TEXT,
        points INTEGER DEFAULT 0,
        benefit_note TEXT,
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(customer_id) REFERENCES crm_customers(id),
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS crm_purchase_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        member_id INTEGER,
        warehouse_id INTEGER NOT NULL,
        purchase_date TEXT NOT NULL,
        invoice_no TEXT,
        channel TEXT DEFAULT 'store',
        items_count INTEGER DEFAULT 0,
        total_amount REAL DEFAULT 0,
        note TEXT,
        handled_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(customer_id) REFERENCES crm_customers(id),
        FOREIGN KEY(member_id) REFERENCES crm_memberships(id),
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS crm_purchase_items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        purchase_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        variant_id INTEGER NOT NULL,
        qty INTEGER DEFAULT 1,
        unit_price REAL DEFAULT 0,
        line_total REAL DEFAULT 0,
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(purchase_id) REFERENCES crm_purchase_records(id) ON DELETE CASCADE,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
        FOREIGN KEY(variant_id) REFERENCES product_variants(id) ON DELETE CASCADE
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS crm_member_records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER NOT NULL,
        purchase_id INTEGER,
        warehouse_id INTEGER NOT NULL,
        record_date TEXT NOT NULL,
        record_type TEXT DEFAULT 'note',
        reference_no TEXT,
        amount REAL DEFAULT 0,
        points_delta INTEGER DEFAULT 0,
        note TEXT,
        handled_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(member_id) REFERENCES crm_memberships(id) ON DELETE CASCADE,
        FOREIGN KEY(purchase_id) REFERENCES crm_purchase_records(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(handled_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS chat_threads(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        direct_key TEXT NOT NULL UNIQUE,
        thread_type TEXT DEFAULT 'direct',
        group_name TEXT,
        group_description TEXT,
        created_by INTEGER,
        last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(created_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS chat_thread_members(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        last_read_message_id INTEGER,
        last_read_at TIMESTAMP,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(thread_id, user_id),
        FOREIGN KEY(thread_id) REFERENCES chat_threads(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        body TEXT NOT NULL,
        message_type TEXT DEFAULT 'text',
        attachment_name TEXT,
        attachment_path TEXT,
        attachment_mime TEXT,
        attachment_size INTEGER DEFAULT 0,
        sticker_code TEXT,
        call_mode TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(thread_id) REFERENCES chat_threads(id) ON DELETE CASCADE,
        FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS user_presence(
        user_id INTEGER PRIMARY KEY,
        current_path TEXT,
        active_thread_id INTEGER,
        last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(active_thread_id) REFERENCES chat_threads(id) ON DELETE SET NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS chat_call_sessions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id INTEGER NOT NULL,
        initiator_id INTEGER NOT NULL,
        receiver_id INTEGER NOT NULL,
        call_mode TEXT NOT NULL DEFAULT 'voice',
        status TEXT NOT NULL DEFAULT 'pending',
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        answered_at TIMESTAMP,
        ended_at TIMESTAMP,
        ended_by INTEGER,
        last_signal_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(thread_id) REFERENCES chat_threads(id) ON DELETE CASCADE,
        FOREIGN KEY(initiator_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(ended_by) REFERENCES users(id) ON DELETE SET NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS chat_call_signals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        call_id INTEGER NOT NULL,
        thread_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        recipient_id INTEGER NOT NULL,
        signal_type TEXT NOT NULL,
        payload TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(call_id) REFERENCES chat_call_sessions(id) ON DELETE CASCADE,
        FOREIGN KEY(thread_id) REFERENCES chat_threads(id) ON DELETE CASCADE,
        FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(recipient_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS schedule_shift_codes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL,
        bg_color TEXT DEFAULT '#C6E5AB',
        text_color TEXT DEFAULT '#17351A',
        sort_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS schedule_employee_profiles(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL UNIQUE,
        custom_name TEXT,
        display_group TEXT,
        location_label TEXT,
        display_order INTEGER DEFAULT 0,
        include_in_schedule INTEGER DEFAULT 1,
        note TEXT,
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS schedule_entries(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id INTEGER NOT NULL,
        schedule_date TEXT NOT NULL,
        shift_code TEXT,
        note TEXT,
        updated_by INTEGER,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(employee_id, schedule_date),
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE,
        FOREIGN KEY(shift_code) REFERENCES schedule_shift_codes(code),
        FOREIGN KEY(updated_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS schedule_day_notes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_date TEXT NOT NULL UNIQUE,
        note TEXT,
        updated_by INTEGER,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(updated_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS schedule_live_entries(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id INTEGER NOT NULL,
        schedule_date TEXT NOT NULL,
        slot_key TEXT NOT NULL,
        employee_id INTEGER,
        channel_label TEXT,
        note TEXT,
        updated_by INTEGER,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(warehouse_id, schedule_date, slot_key),
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id) ON DELETE CASCADE,
        FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE SET NULL,
        FOREIGN KEY(updated_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS schedule_change_events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        warehouse_id INTEGER,
        audience TEXT DEFAULT 'all',
        event_kind TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT,
        affected_employee_id INTEGER,
        affected_employee_name TEXT,
        start_date TEXT,
        end_date TEXT,
        target_url TEXT DEFAULT '/schedule/',
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(affected_employee_id) REFERENCES employees(id) ON DELETE SET NULL,
        FOREIGN KEY(created_by) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS push_subscriptions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        endpoint TEXT NOT NULL UNIQUE,
        p256dh_key TEXT NOT NULL,
        auth_key TEXT NOT NULL,
        user_agent TEXT,
        is_active INTEGER DEFAULT 1,
        last_notified_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # ==========================
    # STOCK OPNAME RESULTS
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS stock_opname_results(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        variant_id INTEGER,
        warehouse_id INTEGER,
        system_qty INTEGER DEFAULT 0,
        physical_qty INTEGER DEFAULT 0,
        diff_qty INTEGER DEFAULT 0,
        user_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE,
        FOREIGN KEY(variant_id) REFERENCES product_variants(id) ON DELETE CASCADE,
        FOREIGN KEY(warehouse_id) REFERENCES warehouses(id),
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    # ==========================
    # INDEX
    # ==========================
    c.execute("CREATE INDEX IF NOT EXISTS idx_batches_main ON stock_batches(product_id, variant_id, warehouse_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_batches_remaining ON stock_batches(remaining_qty)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_history_main ON stock_history(product_id, warehouse_id, date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_stock_main ON stock(product_id, variant_id, warehouse_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_so_results_main ON stock_opname_results(product_id, variant_id, warehouse_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_owner_requests_main ON owner_requests(warehouse_id, status, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_employees_main ON employees(warehouse_id, employment_status, full_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_attendance_main ON attendance_records(warehouse_id, attendance_date, status, employee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_leave_requests_main ON leave_requests(warehouse_id, start_date, end_date, status, employee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_payroll_runs_main ON payroll_runs(warehouse_id, period_year, period_month, status, employee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_recruitment_candidates_main ON recruitment_candidates(warehouse_id, stage, status, candidate_name)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_onboarding_records_main ON onboarding_records(warehouse_id, stage, status, employee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_offboarding_records_main ON offboarding_records(warehouse_id, stage, status, employee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_performance_reviews_main ON performance_reviews(warehouse_id, review_period, status, employee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_helpdesk_tickets_main ON helpdesk_tickets(warehouse_id, category, priority, status, employee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_asset_records_main ON asset_records(warehouse_id, asset_status, condition_status, employee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_project_records_main ON project_records(warehouse_id, priority, status, employee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_biometric_logs_main ON biometric_logs(warehouse_id, punch_time, punch_type, sync_status, employee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_announcement_posts_main ON announcement_posts(warehouse_id, audience, status, publish_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_document_records_main ON document_records(warehouse_id, document_type, status, effective_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_daily_live_reports_main ON daily_live_reports(warehouse_id, report_date, report_type, status, user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_dashboard_reminders_main ON dashboard_reminders(reminder_date, warehouse_id, status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crm_customers_main ON crm_customers(warehouse_id, customer_name, customer_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crm_memberships_main ON crm_memberships(warehouse_id, tier, status, join_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crm_purchase_records_main ON crm_purchase_records(warehouse_id, purchase_date, customer_id, member_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crm_purchase_items_main ON crm_purchase_items(purchase_id, product_id, variant_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_crm_member_records_main ON crm_member_records(warehouse_id, record_date, member_id, record_type)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_threads_main ON chat_threads(last_message_at, updated_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_threads_group ON chat_threads(thread_type, group_name, updated_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_members_user ON chat_thread_members(user_id, thread_id, last_read_message_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_thread ON chat_messages(thread_id, id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_sender ON chat_messages(sender_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_type ON chat_messages(thread_id, message_type, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_user_presence_last_seen ON user_presence(last_seen_at, active_thread_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_call_sessions_open ON chat_call_sessions(status, initiator_id, receiver_id, thread_id, started_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_call_sessions_thread ON chat_call_sessions(thread_id, status, started_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_call_signals_recipient ON chat_call_signals(recipient_id, id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_chat_call_signals_call ON chat_call_signals(call_id, id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_schedule_shift_codes_main ON schedule_shift_codes(sort_order, code, is_active)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_schedule_profiles_main ON schedule_employee_profiles(display_group, display_order, employee_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_schedule_entries_main ON schedule_entries(employee_id, schedule_date, shift_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_schedule_day_notes_main ON schedule_day_notes(schedule_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_schedule_live_entries_main ON schedule_live_entries(warehouse_id, schedule_date, slot_key)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_schedule_change_events_main ON schedule_change_events(warehouse_id, created_at, event_kind)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user ON push_subscriptions(user_id, is_active, updated_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_users_scope_role ON users(role, warehouse_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_requests_flow ON requests(status, from_warehouse, to_warehouse, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_requests_requester ON requests(requested_by, status, created_at)")

    # ==========================
    # APPROVALS (for inbound/outbound/adjust requests)
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS approvals(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT,
        product_id INTEGER,
        variant_id INTEGER,
        warehouse_id INTEGER,
        qty INTEGER,
        note TEXT,
        payload TEXT,
        status TEXT DEFAULT 'pending',
        requested_by INTEGER,
        approved_by INTEGER,
        approved_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ==========================
    # NOTIFICATIONS (store sent/queued notifications)
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS notifications(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        role TEXT,
        channel TEXT,
        recipient TEXT,
        subject TEXT,
        message TEXT,
        status TEXT DEFAULT 'queued',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # ==========================
    # PASSWORD RESETS
    # ==========================
    c.execute("""
    CREATE TABLE IF NOT EXISTS password_resets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        code TEXT,
        used INTEGER DEFAULT 0,
        expires_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS login_attempts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        identifier TEXT,
        ip_address TEXT,
        success INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_notifications_dedupe ON notifications(recipient, channel, subject, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_password_resets_lookup ON password_resets(user_id, code, used, expires_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_identifier ON login_attempts(identifier, success, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip_address, success, created_at)")

    # ==========================
    # SEED
    # ==========================
    if c.execute("SELECT COUNT(*) FROM warehouses").fetchone()[0] == 0:
        c.executemany(
            "INSERT INTO warehouses(name) VALUES (?)",
            [("Gudang Mataram",), ("Gudang Mega",)]
        )

    if not c.execute("SELECT id FROM users WHERE username=?", ("admin",)).fetchone():
        c.execute(
            "INSERT INTO users(username,password,role) VALUES (?,?,?)",
            ("admin", generate_password_hash("admin123"), "admin")
        )

    c.executemany(
        """
        INSERT OR IGNORE INTO schedule_shift_codes(
            code,
            label,
            bg_color,
            text_color,
            sort_order,
            is_active
        )
        VALUES (?,?,?,?,?,1)
        """,
        [
            ("P", "Pagi", "#C6E5AB", "#17351A", 10),
            ("S", "Siang", "#FFE8A2", "#4B3500", 20),
            ("PM", "Pagi Menengah", "#B7DFC7", "#0F3A2B", 30),
            ("PS10", "Pagi 10", "#B9E8F2", "#0E4354", 40),
            ("OFF", "Off", "#F59C8B", "#7C1F1F", 50),
            ("SM", "Shift Malam", "#D7C2F5", "#35205D", 60),
            ("SO1", "Stock Opname 1", "#E5ECF6", "#23384E", 70),
            ("SO2", "Stock Opname 2", "#D8E4FF", "#234A87", 80),
        ],
    )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("✅ Database initialized successfully")
