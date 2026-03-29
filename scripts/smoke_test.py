import os
import sys
from uuid import uuid4

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

temp_root = os.path.join(ROOT_DIR, "scripts", ".tmp")
os.makedirs(temp_root, exist_ok=True)
db_path = os.path.join(temp_root, f"smoke_test_{uuid4().hex}.db")
os.environ["DATABASE_PATH"] = db_path

from app import create_app
from database import get_db
from werkzeug.security import generate_password_hash
from services.request_service import create_request
from services.notification_service import notify_roles, notify_user

app = create_app()

with app.app_context():
    db = get_db()
    whs = db.execute("SELECT id, name FROM warehouses").fetchall()
    print("Warehouses:", [dict(w) for w in whs])
    mega = db.execute("SELECT id FROM warehouses WHERE name LIKE '%Mega%' LIMIT 1").fetchone()
    matar = db.execute("SELECT id FROM warehouses WHERE name LIKE '%Mataram%' LIMIT 1").fetchone()
    if not mega or not matar:
        raise SystemExit("Expected two warehouses")
    mega_id = int(mega["id"])
    matar_id = int(matar["id"])

    def ensure_user(username, role, warehouse_id=None, email=None, phone=None, notify_email=1, notify_whatsapp=0):
        user = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if user:
            return user["id"]
        db.execute(
            """
            INSERT INTO users(username,password,role,email,phone,notify_email,notify_whatsapp,warehouse_id)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (username, generate_password_hash("pass1234"), role, email, phone, notify_email, notify_whatsapp, warehouse_id),
        )
        db.commit()
        return db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]

    ensure_user("leader_mega", "leader", mega_id, "lmega@example.test", "628111111", 1, 0)
    ensure_user("admin_mega", "admin", mega_id, "amega@example.test", "628222222", 1, 1)
    ensure_user("leader_matar", "leader", matar_id, "lmatar@example.test", "628333333", 1, 0)
    ensure_user("admin_matar", "admin", matar_id, "amatar@example.test", "628444444", 1, 1)

    product = db.execute("SELECT id FROM products WHERE sku=?", ("TESTSKU",)).fetchone()
    if not product:
        db.execute(
            "INSERT INTO products(sku,name,category_id) VALUES (?,?,?)",
            ("TESTSKU", "Product Test", None),
        )
        db.commit()
        product = db.execute("SELECT id FROM products WHERE sku=?", ("TESTSKU",)).fetchone()
    product_id = product["id"]

    variant = db.execute("SELECT id FROM product_variants WHERE product_id=?", (product_id,)).fetchone()
    if not variant:
        db.execute("INSERT INTO product_variants(product_id,variant) VALUES (?,?)", (product_id, "Default"))
        db.commit()
        variant = db.execute("SELECT id FROM product_variants WHERE product_id=?", (product_id,)).fetchone()
    variant_id = variant["id"]

    db.execute(
        """
        INSERT INTO stock_batches(product_id,variant_id,warehouse_id,qty,remaining_qty,cost,expiry_date,created_at)
        VALUES (?,?,?,?,?,?,?,datetime('now'))
        """,
        (product_id, variant_id, mega_id, 100, 100, 10000, None),
    )
    db.commit()

    request_id = create_request(product_id, variant_id, mega_id, matar_id, 10)
    print("Created request id:", request_id)

    subject = "Request Baru Test"
    message = f"Request #{request_id} Produk:{product_id} Qty:10 Dari:{mega_id} Ke:{matar_id}"
    result = notify_roles(["leader", "owner", "super_admin"], subject, message, warehouse_id=mega_id)
    print("notify_roles result:", result)

    rows = db.execute(
        """
        SELECT id, user_id, role, channel, recipient, subject, status, created_at
        FROM notifications
        ORDER BY id DESC LIMIT 10
        """
    ).fetchall()
    print("Recent notifications:")
    for row in rows:
        print(dict(row))

    requester = db.execute("SELECT requested_by FROM requests WHERE id=?", (request_id,)).fetchone()["requested_by"]
    print("Requester id:", requester)
    notify_user(requester, "Test: your request is pending", "This is a test message")
    rows2 = db.execute(
        """
        SELECT id, user_id, channel, recipient, subject, status
        FROM notifications
        WHERE user_id=?
        ORDER BY id DESC LIMIT 5
        """,
        (requester,),
    ).fetchall()
    print("Notifications for requester:", [dict(row) for row in rows2])

print("SMOKE TEST DONE")
for suffix in ("", "-wal", "-shm"):
    db_file = db_path + suffix
    if os.path.exists(db_file):
        os.remove(db_file)
