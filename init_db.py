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
    # user assigned warehouse (for single-warehouse roles)
    _ensure_column(cursor, "users", "warehouse_id", "INTEGER")
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
    _ensure_column(cursor, "biometric_logs", "note", "TEXT")
    _ensure_column(cursor, "biometric_logs", "handled_by", "INTEGER")
    _ensure_column(cursor, "biometric_logs", "handled_at", "TIMESTAMP")
    _ensure_column(cursor, "biometric_logs", "updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")


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

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("✅ Database initialized successfully")
