from flask import Blueprint, render_template, session, request, jsonify
from database import get_db
from services.rbac import is_scoped_role

dashboard_bp = Blueprint("dashboard", __name__)


def default_dashboard():
    return {
        "total_product": 0,
        "total_stock": 0,
        "stock_out": 0,
        "inventory_value": 0,
        "expiring_alert": 0,
        "pending_requests": 0,
        "aging": [0, 0, 0, 0]
    }


def validate_warehouse(db, warehouse_id):
    exist = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,)
    ).fetchone()
    return warehouse_id if exist else 1


# ==========================
# DASHBOARD QUERY
# ==========================
def get_dashboard_safe(db, warehouse_id):

    data = default_dashboard()

    try:
        data["total_product"] = db.execute("""
            SELECT COUNT(*) FROM products
        """).fetchone()[0]

        data["total_stock"] = db.execute("""
            SELECT COALESCE(SUM(qty),0)
            FROM stock
            WHERE warehouse_id=?
        """, (warehouse_id,)).fetchone()[0]

        data["stock_out"] = db.execute("""
            SELECT COUNT(*) 
            FROM stock
            WHERE warehouse_id=? AND qty <= 0
        """, (warehouse_id,)).fetchone()[0]

        data["pending_requests"] = db.execute("""
            SELECT COUNT(*)
            FROM requests
            WHERE status='pending'
              AND (from_warehouse=? OR to_warehouse=?)
        """, (warehouse_id, warehouse_id)).fetchone()[0]

        data["inventory_value"] = db.execute("""
            SELECT COALESCE(SUM(
                s.qty * CASE
                    WHEN COALESCE(v.price_nett, 0) > 0 THEN v.price_nett
                    WHEN COALESCE(v.price_discount, 0) > 0 THEN v.price_discount
                    ELSE COALESCE(v.price_retail, 0)
                END
            ), 0)
            FROM stock s
            JOIN product_variants v ON v.id = s.variant_id
            WHERE s.warehouse_id=?
        """, (warehouse_id,)).fetchone()[0]

        data["expiring_alert"] = db.execute("""
            SELECT COUNT(*)
            FROM stock_batches
            WHERE warehouse_id=?
              AND remaining_qty > 0
              AND expiry_date IS NOT NULL
              AND date(expiry_date) <= date('now', '+30 day')
        """, (warehouse_id,)).fetchone()[0]

        aging = db.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN age_days <= 30 THEN 1 ELSE 0 END), 0) AS bucket_1,
                COALESCE(SUM(CASE WHEN age_days BETWEEN 31 AND 90 THEN 1 ELSE 0 END), 0) AS bucket_2,
                COALESCE(SUM(CASE WHEN age_days BETWEEN 91 AND 180 THEN 1 ELSE 0 END), 0) AS bucket_3,
                COALESCE(SUM(CASE WHEN age_days > 180 THEN 1 ELSE 0 END), 0) AS bucket_4
            FROM (
                SELECT CAST(julianday('now') - julianday(MIN(created_at)) AS INTEGER) AS age_days
                FROM stock_batches
                WHERE warehouse_id=? AND remaining_qty > 0
                GROUP BY product_id, variant_id
            )
        """, (warehouse_id,)).fetchone()

        if aging:
            data["aging"] = [
                aging["bucket_1"],
                aging["bucket_2"],
                aging["bucket_3"],
                aging["bucket_4"],
            ]

    except Exception as e:
        print("DASHBOARD QUERY ERROR:", e)
        pass

    return data


# ==========================
# DASHBOARD PAGE
# ==========================
@dashboard_bp.route("/")
def dashboard():

    db = get_db()

    warehouse_id = session.get("warehouse_id")
    if not warehouse_id:
        warehouse = db.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
        warehouse_id = warehouse["id"] if warehouse else 1
        session["warehouse_id"] = warehouse_id

    warehouse_id = validate_warehouse(db, warehouse_id)

    data = get_dashboard_safe(db, warehouse_id)

    try:
        logs_raw = db.execute("""
            SELECT
                sm.created_at AS date,
                sm.type,
                sm.qty,
                p.name AS product_name,
                v.variant
            FROM stock_movements sm
            LEFT JOIN products p ON sm.product_id = p.id
            LEFT JOIN product_variants v ON sm.variant_id = v.id
            WHERE sm.warehouse_id=?
            ORDER BY datetime(sm.created_at) DESC
            LIMIT 20
        """, (warehouse_id,)).fetchall()

        logs = [dict(r) for r in logs_raw]

    except:
        logs = []

    warehouses = db.execute("""
        SELECT * FROM warehouses ORDER BY name
    """).fetchall()

    return render_template(
        "index.html",
        data=data,
        logs=logs,
        warehouses=warehouses,
        warehouse_id=warehouse_id
    )


# ==========================
# REALTIME API
# ==========================
@dashboard_bp.route("/api/realtime")
def dashboard_realtime():

    db = get_db()

    warehouse_id = session.get("warehouse_id")
    if not warehouse_id:
        warehouse = db.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
        warehouse_id = warehouse["id"] if warehouse else 1
        session["warehouse_id"] = warehouse_id

    warehouse_id = validate_warehouse(db, warehouse_id)

    data = get_dashboard_safe(db, warehouse_id)

    return jsonify(data)


# ==========================
# SET WAREHOUSE
# ==========================
@dashboard_bp.route("/set_warehouse", methods=["POST"])
def set_warehouse():

    try:
        db = get_db()
        warehouse_id = int(request.form.get("warehouse_id"))
        warehouse = db.execute(
            "SELECT id FROM warehouses WHERE id=?",
            (warehouse_id,),
        ).fetchone()
        if not warehouse:
            return jsonify({"status": "error", "message": "Gudang tidak valid"}), 400

        role = session.get("role")
        if is_scoped_role(role):
            allowed_warehouse = session.get("warehouse_id")
            session["warehouse_id"] = allowed_warehouse or warehouse_id
            return jsonify({"status": "ok", "warehouse_id": session["warehouse_id"]})

        session["warehouse_id"] = warehouse_id
        return jsonify({"status": "ok", "warehouse_id": warehouse_id})
    except:
        return jsonify({"status": "error"}), 400
