from flask import Blueprint, render_template, request, redirect, flash, session
from database import get_db
from services.stock_service import add_stock
from services.notification_service import notify_roles
from services.rbac import has_permission, is_scoped_role

inbound_bp = Blueprint(
    "inbound",
    __name__,
    url_prefix="/inbound"
)


@inbound_bp.route("/", methods=["GET", "POST"])
def inbound():

    db = get_db()

    if request.method == "POST":

        try:
            product_id = int(request.form.get("product_id"))
            variant_id = int(request.form.get("variant_id"))
            warehouse_id = int(request.form.get("warehouse_id"))
            qty = int(request.form.get("qty", 0))
            note = (request.form.get("note") or "").strip()
            cost = float(request.form.get("cost", 0))
            expiry = request.form.get("expiry") or None
            custom_date = request.form.get("custom_date") or None

        except:
            flash("Input tidak valid", "error")
            return redirect("/inbound")

        if qty <= 0:
            flash("Qty harus lebih dari 0", "error")
            return redirect("/inbound")

        if not note:
            note = "Inbound Barang"

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
            return redirect("/inbound")

        if not warehouse:
            flash("Gudang tidak valid", "error")
            return redirect("/inbound")

        try:
            role = session.get("role")
            user_wh = session.get("warehouse_id")

            # leader/admin are scoped to a single warehouse
            if is_scoped_role(role) and warehouse_id != user_wh:
                flash("Tidak punya akses ke gudang ini", "error")
                return redirect("/inbound")

            if has_permission(role, "direct_stock_ops"):
                db.execute("BEGIN")

                success = add_stock(
                    product_id,
                    variant_id,
                    warehouse_id,
                    qty,
                    note=note,
                    cost=cost,
                    custom_date=custom_date,
                    expiry=expiry
                )

                if not success:
                    raise Exception("Gagal add stock")

                db.commit()
                flash("Inbound berhasil", "success")

            elif has_permission(role, "request_stock_ops"):
                # create approval record for leader to process
                db.execute("""
                INSERT INTO approvals(type, product_id, variant_id, warehouse_id, qty, note, requested_by)
                VALUES (?,?,?,?,?,?,?)
                """, ("INBOUND", product_id, variant_id, warehouse_id, qty, note, session.get("user_id")))
                db.commit()

                subj = "Permintaan Inbound Stok"
                msg = f"User meminta inbound. Produk:{product_id} Variant:{variant_id} Gudang:{warehouse_id} Qty:{qty}"
                try:
                    notify_roles(["leader", "owner", "super_admin"], subj, msg, warehouse_id=warehouse_id)
                except Exception as e:
                    print("NOTIFY ERROR:", e)

                flash("Permintaan inbound telah dikirim ke leader untuk approval", "success")

            else:
                flash("Tidak punya akses", "error")

        except Exception as e:
            db.rollback()
            print("INBOUND ERROR:", e)
            flash(str(e), "error")

        return redirect("/inbound")

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
    SELECT * FROM warehouses
    ORDER BY name
    """).fetchall()

    return render_template(
        "inbound.html",
        products=products,
        warehouses=warehouses,
        warehouse_id=session.get("warehouse_id")
    )
