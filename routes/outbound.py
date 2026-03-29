from flask import Blueprint, render_template, request, redirect, flash, session
from database import get_db
from services.stock_service import remove_stock
from services.notification_service import notify_roles
from services.rbac import has_permission, is_scoped_role

outbound_bp = Blueprint(
    "outbound",
    __name__,
    url_prefix="/outbound"
)


# ==========================
# OUTBOUND
# ==========================
@outbound_bp.route("/", methods=["GET", "POST"])
def outbound():

    db = get_db()

    if request.method == "POST":

        try:
            product_id = int(request.form.get("product_id"))
            variant_id = int(request.form.get("variant_id"))

            warehouse_id = session.get("warehouse_id")
            if not warehouse_id:
                warehouse_id = int(request.form.get("warehouse_id"))

            qty = int(request.form.get("qty", 0))
            note = (request.form.get("note") or "").strip()
        except:
            flash("Input tidak valid", "error")
            return redirect("/outbound")

        if qty <= 0:
            flash("Qty harus lebih dari 0", "error")
            return redirect("/outbound")

        if not note:
            note = "Barang Keluar"

        product = db.execute(
            "SELECT id FROM products WHERE id=?",
            (product_id,)
        ).fetchone()

        variant = db.execute(
            "SELECT id FROM product_variants WHERE id=? AND product_id=?",
            (variant_id, product_id)
        ).fetchone()

        warehouse = db.execute(
            "SELECT id FROM warehouses WHERE id=?",
            (warehouse_id,)
        ).fetchone()

        if not product or not variant:
            flash("Produk / variant tidak valid", "error")
            return redirect("/outbound")

        if not warehouse:
            flash("Gudang tidak valid", "error")
            return redirect("/outbound")

        role = session.get("role")

        try:
            user_wh = session.get("warehouse_id")
            if is_scoped_role(role) and warehouse_id != user_wh:
                flash("Tidak punya akses ke gudang ini", "error")
                return redirect("/outbound")
            if has_permission(role, "direct_stock_ops"):
                success = remove_stock(
                    product_id,
                    variant_id,
                    warehouse_id,
                    qty,
                    note
                )

                if success:
                    flash("Outbound berhasil", "success")
                else:
                    flash("Stok tidak cukup atau terjadi error", "error")

            elif has_permission(role, "request_stock_ops"):
                # create approval record
                db.execute("""
                INSERT INTO approvals(type, product_id, variant_id, warehouse_id, qty, note, requested_by)
                VALUES (?,?,?,?,?,?,?)
                """, ("OUTBOUND", product_id, variant_id, warehouse_id, qty, note, session.get("user_id")))
                db.commit()

                subj = "Permintaan Outbound Stok"
                msg = f"User meminta outbound. Produk:{product_id} Variant:{variant_id} Gudang:{warehouse_id} Qty:{qty}"
                try:
                    notify_roles(["leader", "owner", "super_admin"], subj, msg, warehouse_id=warehouse_id)
                except Exception as e:
                    print("NOTIFY ERROR:", e)

                flash("Permintaan outbound telah dikirim ke leader untuk approval", "success")

            else:
                flash("Tidak punya akses", "error")

        except Exception as e:
            print("OUTBOUND ERROR:", e)
            flash("Terjadi error", "error")

        return redirect("/outbound")

    rows = db.execute("""
    SELECT 
        p.id,
        p.sku,
        p.name,
        c.name as category
    FROM products p
    LEFT JOIN categories c ON p.category_id = c.id
    ORDER BY p.name
    """).fetchall()

    products = [dict(r) for r in rows]

    warehouses = db.execute("""
    SELECT * FROM warehouses ORDER BY name
    """).fetchall()

    return render_template(
        "outbound.html",
        products=products,
        warehouses=warehouses,
        warehouse_id=session.get("warehouse_id")
    )
