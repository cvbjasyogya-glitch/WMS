import os
import sys
from uuid import uuid4

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

temp_root = os.path.join(ROOT_DIR, "scripts", ".tmp")
os.makedirs(temp_root, exist_ok=True)
db_path = os.path.join(temp_root, f"e2e_test_{uuid4().hex}.db")
os.environ["DATABASE_PATH"] = db_path

from app import create_app
from database import get_db
from werkzeug.security import generate_password_hash

app = create_app()

with app.app_context():
    db = get_db()

    def ensure_user(username, role, warehouse_id=None, email=None, phone=None):
        user = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if user:
            return user["id"]
        db.execute(
            """
            INSERT INTO users(username,password,role,email,phone,notify_email,notify_whatsapp,warehouse_id)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (username, generate_password_hash("pass1234"), role, email, phone, 1, 0, warehouse_id),
        )
        db.commit()
        return db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]

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

    warehouses = db.execute("SELECT id,name FROM warehouses ORDER BY id").fetchall()
    if len(warehouses) < 2:
        raise SystemExit("Need 2 warehouses")
    wh1 = warehouses[0]["id"]
    wh2 = warehouses[1]["id"]

    ensure_user("leader_e2e", "leader", wh1, "leader_e2e@example.test", "62810101")
    ensure_user("admin_e2e", "admin", wh1, "admin_e2e@example.test", "62820202")
    ensure_user("leader_e2e2", "leader", wh2, "leader_e2e2@example.test", "62830303")

    db.execute(
        """
        INSERT INTO stock_batches(product_id,variant_id,warehouse_id,qty,remaining_qty,cost,expiry_date,created_at)
        VALUES (?,?,?,?,?,?,?,datetime('now'))
        """,
        (product_id, variant_id, wh1, 50, 50, 1000, None),
    )
    db.commit()

print("Setup complete; performing web flow")

with app.test_client() as client:
    response = client.post("/login", data={"username": "admin_e2e", "password": "pass1234"}, follow_redirects=True)
    print("Login admin status:", response.status_code)

    response = client.post(
        "/request/",
        data={
            "product_id": product_id,
            "variant_id": variant_id,
            "from_warehouse": wh1,
            "to_warehouse": wh2,
            "qty": 5,
        },
        follow_redirects=True,
    )
    print("Create request status:", response.status_code)

    with app.app_context():
        db = get_db()
        request_row = db.execute(
            "SELECT id, status, requested_by FROM requests ORDER BY id DESC LIMIT 1"
        ).fetchone()
        print("Newest request:", dict(request_row))
        request_id = request_row["id"]

    client.get("/logout")

    response = client.post("/login", data={"username": "leader_e2e", "password": "pass1234"}, follow_redirects=True)
    print("Login leader status:", response.status_code)

    response = client.post(f"/request/approve/{request_id}", follow_redirects=True)
    print("Approve status:", response.status_code)

    with app.app_context():
        db = get_db()
        request_row = db.execute(
            "SELECT id, status, approved_by FROM requests WHERE id=?",
            (request_id,),
        ).fetchone()
        print("After approve:", dict(request_row))

    if request_row:
        print("Approved_by:", request_row["approved_by"])

print("E2E finished")
for suffix in ("", "-wal", "-shm"):
    db_file = db_path + suffix
    if os.path.exists(db_file):
        os.remove(db_file)
