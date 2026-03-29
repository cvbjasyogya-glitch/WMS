import sqlite3
import os
from werkzeug.security import generate_password_hash

# ==========================
# SINGLE SOURCE DATABASE (FIX)
# ==========================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")

    return conn


def _column_exists(cursor, table_name, column_name):
    rows = cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def _ensure_column(cursor, table_name, column_name, definition):
    if not _column_exists(cursor, table_name, column_name):
        cursor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )


def migrate_schema(cursor):
    # Keep existing databases compatible with the newer routes/services.
    _ensure_column(cursor, "product_variants", "price_retail", "REAL DEFAULT 0")
    _ensure_column(cursor, "product_variants", "price_discount", "REAL DEFAULT 0")
    _ensure_column(cursor, "product_variants", "price_nett", "REAL DEFAULT 0")

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


def init_db():
    conn = get_connection()
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

    migrate_schema(c)

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

    # ==========================
    # INDEX
    # ==========================
    c.execute("CREATE INDEX IF NOT EXISTS idx_batches_main ON stock_batches(product_id, variant_id, warehouse_id, created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_batches_remaining ON stock_batches(remaining_qty)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_history_main ON stock_history(product_id, warehouse_id, date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_stock_main ON stock(product_id, variant_id, warehouse_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_so_results_main ON stock_opname_results(product_id, variant_id, warehouse_id, created_at)")

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
