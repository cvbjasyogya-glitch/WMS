from flask import Blueprint, render_template, request, redirect, flash, jsonify, session
from database import get_db
from services.request_service import create_request, approve_request

transfers_bp = Blueprint(
    "transfers",
    __name__,
    url_prefix="/transfers"
)


@transfers_bp.route("/", methods=["GET", "POST"])
def transfer():

    db = get_db()

    user_id = session.get("user_id")
    if not user_id:
        return redirect("/login")

    if not session.get("warehouse_id"):
        warehouse = db.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
        session["warehouse_id"] = warehouse["id"] if warehouse else 1

    if request.method == "POST":

        try:
            product_id = int(request.form.get("product_id"))
            variant_id = int(request.form.get("variant_id"))
            from_wh = int(request.form.get("from_warehouse"))
            to_wh = int(request.form.get("to_warehouse"))
            qty = int(request.form.get("qty", 0))
        except:
            flash("Input tidak valid", "error")
            return redirect("/transfers")

        if qty <= 0:
            flash("Qty harus lebih dari 0", "error")
            return redirect("/transfers")

        if from_wh == to_wh:
            flash("Gudang asal dan tujuan tidak boleh sama", "error")
            return redirect("/transfers")

        product = db.execute(
            "SELECT id FROM products WHERE id=?",
            (product_id,)
        ).fetchone()

        variant = db.execute(
            "SELECT id FROM product_variants WHERE id=? AND product_id=?",
            (variant_id, product_id)
        ).fetchone()

        wh1 = db.execute("SELECT id FROM warehouses WHERE id=?", (from_wh,)).fetchone()
        wh2 = db.execute("SELECT id FROM warehouses WHERE id=?", (to_wh,)).fetchone()

        if not product or not variant or not wh1 or not wh2:
            flash("Data tidak valid", "error")
            return redirect("/transfers")

        role = session.get("role")

        # enforce single-warehouse scope for leader/admin: from_wh must match assigned warehouse
        user_wh = session.get("warehouse_id")
        if role in ["leader", "admin"] and from_wh != user_wh:
            flash("Tidak punya akses untuk melakukan transfer dari gudang ini", "error")
            return redirect("/transfers")

        # ==========================
        # CREATE + APPROVE (leader/owner/super_admin do immediate),
        # admin creates approval record for leader to review
        # ==========================
        if role in ["leader", "owner", "super_admin"]:
            req_id = create_request(
                product_id,
                variant_id,
                from_wh,
                to_wh,
                qty
            )

            if not req_id:
                flash("Gagal membuat transfer", "error")
                return redirect("/transfers")

            success = approve_request(req_id)

            if not success:
                flash("Transfer gagal (stok tidak cukup)", "error")
                return redirect("/transfers")

            flash("Transfer berhasil (FIFO)", "success")
            return redirect("/transfers")

        elif role == "admin":
            req_id = create_request(
                product_id,
                variant_id,
                from_wh,
                to_wh,
                qty
            )

            if not req_id:
                flash("Gagal membuat transfer", "error")
                return redirect("/transfers")

            # notify leaders/owners for approval
            subj = "Permintaan Transfer: %s" % product_id
            msg = f"Transfer request\nProduk: {product_id} Variant: {variant_id} Qty: {qty} Dari: {from_wh} Ke: {to_wh}"
            try:
                from services.notification_service import notify_roles
                notify_roles(["leader", "owner", "super_admin"], subj, msg, warehouse_id=from_wh)
            except Exception:
                pass

            flash("Permintaan transfer telah dikirim ke leader untuk approval", "success")
            return redirect("/transfers")

        else:
            flash("Tidak punya akses", "error")
            return redirect("/transfers")

    products = db.execute("""
    SELECT 
        p.id,
        p.sku,
        p.name,
        c.name as category_name
    FROM products p
    LEFT JOIN categories c ON p.category_id = c.id
    ORDER BY p.name
    """).fetchall()

    warehouses = db.execute("""
    SELECT * FROM warehouses ORDER BY name
    """).fetchall()

    return render_template(
        "transfer.html",
        products=products,
        warehouses=warehouses,
        warehouse_id=session.get("warehouse_id")
    )


@transfers_bp.route("/get_stock")
def get_stock():

    db = get_db()

    try:
        product_id = int(request.args.get("product_id"))
        variant_id = int(request.args.get("variant_id"))
        warehouse_id = int(request.args.get("warehouse_id"))
    except:
        return jsonify({"qty": 0})

    stock = db.execute("""
    SELECT qty FROM stock
    WHERE product_id=? AND variant_id=? AND warehouse_id=?
    """,(product_id, variant_id, warehouse_id)).fetchone()

    qty = stock["qty"] if stock else 0

    return jsonify({"qty": qty})
