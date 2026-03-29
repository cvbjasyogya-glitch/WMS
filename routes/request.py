from flask import Blueprint, render_template, request, redirect, flash, session
from database import get_db
from services.request_service import create_request, approve_request
from services.notification_service import notify_roles
import os

try:
    import requests as http_requests
except ImportError:
    http_requests = None

request_bp = Blueprint(
    "request",
    __name__,
    url_prefix="/request"
)


def is_admin():
    # approval rights: leader, owner and super_admin
    return session.get("role") in ["leader", "owner", "super_admin", "admin"]


# ==========================
# WA NOTIFICATION
# ==========================
def send_wa(product_name, variant, qty, from_wh, to_wh):
    api_key = os.getenv("FONNTE_API_KEY")
    target = os.getenv("FONNTE_TARGET")

    if not api_key or not target or http_requests is None:
        return False

    try:
        url = "https://api.fonnte.com/send"

        headers = {
            "Authorization": api_key
        }

        message = f"""
🔥 REQUEST BARU

Produk : {product_name}
Variant : {variant}
Qty : {qty}

Dari : {from_wh}
Ke : {to_wh}
"""

        data = {
            "target": target,
            "message": message
        }

        http_requests.post(url, headers=headers, data=data, timeout=5)
        return True

    except Exception as e:
        print("WA ERROR:", e)
        return False


# ==========================
# CHECK NOTIF (FIX GHOST)
# ==========================
@request_bp.route("/check_new")
def check_new():

    db = get_db()

    try:
        last_id = int(request.args.get("last_id", 0))
    except:
        last_id = 0

    warehouse_id = session.get("warehouse_id")

    if not warehouse_id:
        return {"status": "no"}

    # 🔥 AMBIL NEXT ID (ASC, BUKAN DESC)
    row = db.execute("""
    SELECT id, qty
    FROM requests
    WHERE id > ?
    AND status = 'pending'
    AND (from_warehouse=? OR to_warehouse=?)
    ORDER BY id ASC
    LIMIT 1
    """, (last_id, warehouse_id, warehouse_id)).fetchone()

    if not row:
        return {"status": "no"}

    return {
        "status": "yes",
        "id": row["id"],
        "qty": row["qty"]
    }


# ==========================
# MAIN REQUEST
# ==========================
@request_bp.route("/", methods=["GET", "POST"])
def request_barang():

    db = get_db()

    if request.method == "POST":

        try:
            product_id = int(request.form.get("product_id"))
            variant_id = int(request.form.get("variant_id"))
            from_wh = int(request.form.get("from_warehouse"))
            to_wh = int(request.form.get("to_warehouse"))
            qty = int(request.form.get("qty", 0))
        except:
            flash("Input tidak valid", "error")
            return redirect("/request")

        if qty <= 0:
            flash("Qty harus > 0", "error")
            return redirect("/request")

        if from_wh == to_wh:
            flash("Gudang tidak boleh sama", "error")
            return redirect("/request")

        product = db.execute(
            "SELECT id, name FROM products WHERE id=?",
            (product_id,)
        ).fetchone()

        variant = db.execute(
            "SELECT id, variant FROM product_variants WHERE id=? AND product_id=?",
            (variant_id, product_id)
        ).fetchone()

        w1 = db.execute("SELECT id, name FROM warehouses WHERE id=?", (from_wh,)).fetchone()
        w2 = db.execute("SELECT id, name FROM warehouses WHERE id=?", (to_wh,)).fetchone()

        if not product or not variant or not w1 or not w2:
            flash("Data tidak valid", "error")
            return redirect("/request")

        # enforce single-warehouse scope for leader/admin: from_wh must match assigned warehouse
        role = session.get("role")
        user_wh = session.get("warehouse_id")
        if role in ["leader", "admin"] and from_wh != user_wh:
            flash("Tidak punya akses untuk membuat request dari gudang ini", "error")
            return redirect("/request")

        request_id = create_request(product_id, variant_id, from_wh, to_wh, qty)

        if request_id:

            # send notifications to leaders/super admins
            subj = "Request Baru: %s" % product["name"]
            msg = f"Request baru\nProduk: {product['name']}\nVariant: {variant['variant']}\nQty: {qty}\nDari: {w1['name']}\nKe: {w2['name']}"
            try:
                notify_roles(["leader", "owner", "super_admin"], subj, msg, warehouse_id=from_wh)
            except Exception as e:
                print("NOTIFY ERROR:", e)

            flash("Request berhasil dibuat", "success")
        else:
            flash("Gagal membuat request", "error")

        return redirect("/request")

    products = db.execute("""
        SELECT id, sku, name
        FROM products
        ORDER BY name
    """).fetchall()

    warehouses = db.execute("""
        SELECT * FROM warehouses ORDER BY name
    """).fetchall()

    warehouse_id = session.get("warehouse_id")

    if warehouse_id:
        rows = db.execute("""
        SELECT 
            r.*,
            p.name as product_name,
            v.variant,
            w1.name as from_name,
            w2.name as to_name
        FROM requests r
        JOIN products p ON r.product_id = p.id
        JOIN product_variants v ON r.variant_id = v.id
        JOIN warehouses w1 ON r.from_warehouse = w1.id
        JOIN warehouses w2 ON r.to_warehouse = w2.id
        WHERE (r.from_warehouse=? OR r.to_warehouse=?)
        ORDER BY r.id DESC
        """, (warehouse_id, warehouse_id)).fetchall()
    else:
        rows = db.execute("""
        SELECT 
            r.*,
            p.name as product_name,
            v.variant,
            w1.name as from_name,
            w2.name as to_name
        FROM requests r
        JOIN products p ON r.product_id = p.id
        JOIN product_variants v ON r.variant_id = v.id
        JOIN warehouses w1 ON r.from_warehouse = w1.id
        JOIN warehouses w2 ON r.to_warehouse = w2.id
        ORDER BY r.id DESC
        """).fetchall()

    requests_data = [dict(r) for r in rows]

    return render_template(
        "request.html",
        products=products,
        warehouses=warehouses,
        requests=requests_data,
        warehouse_id=warehouse_id
    )


# ==========================
# APPROVE
# ==========================
@request_bp.route("/approve/<int:id>", methods=["POST"])
def approve_request_route(id):

    if not is_admin():
        flash("Tidak punya akses", "error")
        return redirect("/request")

    success = approve_request(id)

    if success:
        flash("Request disetujui", "success")
    else:
        flash("Gagal approve", "error")

    return redirect("/request")
