from flask import Blueprint, render_template, request, session, redirect, flash, jsonify
from database import get_db
from datetime import datetime
from services.stock_service import adjust_stock
from services.notification_service import notify_roles

stock_bp = Blueprint("stock", __name__, url_prefix="/stock")


def parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
    except:
        return None


def validate_warehouse(db, warehouse_id):
    exist = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,)
    ).fetchone()
    return warehouse_id if exist else 1


@stock_bp.route("/")
def stock_table():

    db = get_db()

    search = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "qty_asc")  # 🔥 TAMBAHAN

    warehouse_id = session.get("warehouse_id")

    if not warehouse_id:
        try:
            warehouse_id = int(request.args.get("warehouse", 1))
        except:
            warehouse_id = 1

    warehouse_id = validate_warehouse(db, warehouse_id)

    start_date = parse_date(request.args.get("start_date"))
    end_date = parse_date(request.args.get("end_date"))

    try:
        page = int(request.args.get("page", 1))
        if page < 1:
            page = 1
    except:
        page = 1

    limit = 50
    offset = (page - 1) * limit

    # 🔥 SORT LOGIC
    if sort == "qty_desc":
        order_by = "qty DESC"
    elif sort == "name_asc":
        order_by = "p.name ASC"
    elif sort == "name_desc":
        order_by = "p.name DESC"
    else:
        order_by = "qty ASC"

    query = f"""
    SELECT 
        p.id as product_id,
        v.id as variant_id,
        ? as warehouse_id,

        p.sku,
        p.name,
        v.variant,

        COALESCE(v.price_retail,0) as price_retail,
        COALESCE(v.price_discount,0) as price_discount,
        COALESCE(v.price_nett,0) as price_nett,

        COALESCE(SUM(b.remaining_qty),0) as qty,

        CASE 
            WHEN MIN(b.created_at) IS NOT NULL
            THEN CAST((julianday('now') - julianday(MIN(b.created_at))) AS INTEGER)
            ELSE 0
        END as age_days,

        MIN(b.created_at) as created_at,
        MAX(b.expiry_date) as expiry_date

    FROM products p
    JOIN product_variants v ON v.product_id = p.id

    LEFT JOIN stock_batches b
        ON p.id = b.product_id
        AND v.id = b.variant_id
        AND b.warehouse_id = ?
    """

    params = [warehouse_id, warehouse_id]

    conditions = []

    if start_date:
        conditions.append("(b.created_at IS NULL OR date(b.created_at) >= date(?))")
        params.append(start_date)

    if end_date:
        conditions.append("(b.created_at IS NULL OR date(b.created_at) <= date(?))")
        params.append(end_date)

    if search:
        conditions.append("(p.name LIKE ? OR p.sku LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    count_query = """
    SELECT COUNT(*)
    FROM (
        SELECT p.id, v.id
        FROM products p
        JOIN product_variants v ON v.product_id = p.id
        LEFT JOIN stock_batches b
            ON p.id = b.product_id
            AND v.id = b.variant_id
            AND b.warehouse_id = ?
    """

    count_params = [warehouse_id]

    if conditions:
        count_query += " WHERE " + " AND ".join(conditions)
        count_params.extend(params[2:])

    count_query += """
        GROUP BY p.id, v.id
    )
    """

    query += f"""
    GROUP BY p.id, v.id, p.sku, p.name, v.variant
    ORDER BY {order_by}, age_days DESC
    LIMIT ? OFFSET ?
    """

    params += [limit, offset]

    rows = db.execute(query, params).fetchall()
    data = [dict(r) for r in rows]

    total = db.execute(count_query, count_params).fetchone()[0]

    total_pages = max(1, (total + limit - 1) // limit)

    warehouses = db.execute("SELECT * FROM warehouses ORDER BY name").fetchall()

    return render_template(
        "stok_gudang.html",
        data=data,
        search=search,
        warehouses=warehouses,
        warehouse_id=warehouse_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        total_pages=total_pages,
        sort=sort  # 🔥 TAMBAHAN
    )


@stock_bp.route("/adjust", methods=["POST"])
def adjust():

    db = get_db()

    try:
        product_id = int(request.form.get("product_id"))
        variant_id = int(request.form.get("variant_id"))
        warehouse_id = int(request.form.get("warehouse_id"))
        qty = int(request.form.get("qty"))

        if qty == 0:
            raise Exception("qty nol")
    except:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "error", "message": "Input tidak valid"})
        flash("Input tidak valid", "error")
        return redirect("/stock")

    role = session.get("role")
    user_wh = session.get("warehouse_id")
    if role in ["leader", "admin"] and warehouse_id != user_wh:
        flash("Tidak punya akses ke gudang ini", "error")
        return redirect("/stock")

    try:
        # direct adjust allowed only for leader and super_admin
        if role in ["leader", "owner", "super_admin"]:
            ok = adjust_stock(product_id, variant_id, warehouse_id, qty)

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                if ok:
                    return jsonify({"status": "success"})
                else:
                    return jsonify({"status": "error", "message": "Stock gagal / tidak cukup"})

            if ok:
                flash("Stock berhasil diupdate", "success")
            else:
                flash("Stock gagal / tidak cukup", "error")

        elif role == "admin":
            # create approval record for leader to review
            db.execute("""
            INSERT INTO approvals(type, product_id, variant_id, warehouse_id, qty, note, requested_by)
            VALUES (?,?,?,?,?,?,?)
            """, ("ADJUST", product_id, variant_id, warehouse_id, qty, request.form.get('note') or 'Adjustment request', session.get('user_id')))
            db.commit()

            subj = "Permintaan Adjustment Stok"
            msg = f"User {session.get('user_id')} meminta adjustment stok. Produk:{product_id} Variant:{variant_id} Gudang:{warehouse_id} Qty:{qty}"
            try:
                notify_roles(["leader", "owner", "super_admin"], subj, msg, warehouse_id=warehouse_id)
            except Exception as e:
                print("NOTIFY ERROR:", e)

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"status": "pending", "message": "Permintaan dikirim ke leader untuk approval"})

            flash("Permintaan adjustment telah dikirim ke leader untuk approval", "success")

        else:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"status": "error", "message": "Tidak punya akses"})
            flash("Tidak punya akses", "error")

    except Exception as e:
        print("ADJUST ERROR:", e)

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "error", "message": "Error system"})

        flash("Error system", "error")

    return redirect("/stock")


@stock_bp.route("/update-field", methods=["POST"])
def update_field():

    db = get_db()

    try:
        product_id = int(request.form.get("product_id") or 0)
        variant_id = int(request.form.get("variant_id") or 0)
        field = request.form.get("field")
        value = (request.form.get("value") or "").strip()
    except:
        return jsonify({"status": "error"})

    try:

        if not value:
            return jsonify({"status":"error","message":"Tidak boleh kosong"})

        if field == "sku":
            exist = db.execute(
                "SELECT id FROM products WHERE sku=? AND id!=?",
                (value, product_id)
            ).fetchone()

            if exist:
                return jsonify({"status":"error","message":"SKU sudah ada"})

            db.execute("UPDATE products SET sku=? WHERE id=?", (value, product_id))

        elif field == "name":
            db.execute("UPDATE products SET name=? WHERE id=?", (value, product_id))

        elif field == "variant":
            db.execute("UPDATE product_variants SET variant=? WHERE id=?", (value, variant_id))

        elif field in ["price_retail", "price_discount", "price_nett"]:
            try:
                val = float(value)
            except:
                return jsonify({"status":"error","message":"Harus angka"})
            db.execute(f"UPDATE product_variants SET {field}=? WHERE id=?", (val, variant_id))
        else:
            return jsonify({"status":"error","message":"Field tidak dikenal"})

        db.commit()

        return jsonify({"status":"success"})

    except Exception as e:
        print("UPDATE ERROR:", e)
        db.rollback()
        return jsonify({"status":"error"})


@stock_bp.route("/bulk-adjust", methods=["POST"])
def bulk_adjust():

    db = get_db()

    try:
        data = request.get_json(silent=True) or {}
        items = data.get("items", [])
    except:
        return jsonify({"status":"error"})

    if not items:
        return jsonify({"status":"error","message":"No data"})

    try:
        failed = 0
        for it in items:
            ok = adjust_stock(
                int(it.get("product_id",0)),
                int(it.get("variant_id",0)),
                int(it.get("warehouse_id",0)),
                int(it.get("qty",0))
            )

            if not ok:
                failed += 1

        if failed:
            return jsonify({"status":"error","message":f"{failed} item gagal di-adjust"})

        return jsonify({"status":"success"})

    except Exception as e:
        print("BULK ERROR:", e)
        return jsonify({"status":"error"})
