from flask import Blueprint, Response, render_template, request, session, redirect, flash, jsonify
from database import get_db
from datetime import datetime
from io import StringIO
import csv

from services.stock_service import adjust_stock
from services.notification_service import notify_roles

stock_bp = Blueprint("stock", __name__, url_prefix="/stock")
LOW_STOCK_THRESHOLD = 5


def parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
    except:
        return None


def validate_warehouse(db, warehouse_id):
    exist = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    return warehouse_id if exist else 1


def _resolve_stock_warehouse(db):
    role = session.get("role")

    if role in ["leader", "admin"]:
        warehouse_id = session.get("warehouse_id") or 1
    else:
        try:
            warehouse_id = int(request.args.get("warehouse") or session.get("warehouse_id") or 1)
        except:
            warehouse_id = session.get("warehouse_id") or 1

    return validate_warehouse(db, warehouse_id)


def _get_stock_state():
    state = (request.args.get("stock_state") or "all").strip().lower()
    if state not in ["all", "zero", "low", "ready"]:
        return "all"
    return state


def _get_sort_clause(sort):
    if sort == "qty_desc":
        return "qty DESC, p.name ASC"
    if sort == "name_asc":
        return "p.name ASC, qty ASC"
    if sort == "name_desc":
        return "p.name DESC, qty ASC"
    if sort == "age_desc":
        return "age_days DESC, p.name ASC"
    return "qty ASC, p.name ASC"


def _build_stock_query(warehouse_id, search, start_date, end_date, stock_state):
    query = """
    SELECT
        p.id as product_id,
        v.id as variant_id,
        ? as warehouse_id,
        p.sku,
        p.name,
        v.variant,
        COALESCE(v.price_retail, 0) as price_retail,
        COALESCE(v.price_discount, 0) as price_discount,
        COALESCE(v.price_nett, 0) as price_nett,
        COALESCE(s.qty, 0) as qty,
        CASE
            WHEN MIN(CASE WHEN COALESCE(b.remaining_qty, 0) > 0 THEN b.created_at END) IS NOT NULL
            THEN CAST(
                (
                    julianday('now')
                    - julianday(MIN(CASE WHEN COALESCE(b.remaining_qty, 0) > 0 THEN b.created_at END))
                ) AS INTEGER
            )
            ELSE 0
        END as age_days,
        MIN(CASE WHEN COALESCE(b.remaining_qty, 0) > 0 THEN b.created_at END) as created_at,
        MIN(
            CASE
                WHEN COALESCE(b.remaining_qty, 0) > 0 AND b.expiry_date IS NOT NULL THEN b.expiry_date
            END
        ) as expiry_date
    FROM products p
    JOIN product_variants v ON v.product_id = p.id
    LEFT JOIN stock s
        ON s.product_id = p.id
        AND s.variant_id = v.id
        AND s.warehouse_id = ?
    LEFT JOIN stock_batches b
        ON b.product_id = p.id
        AND b.variant_id = v.id
        AND b.warehouse_id = ?
    """

    params = [warehouse_id, warehouse_id, warehouse_id]
    conditions = []

    if start_date:
        conditions.append("(b.created_at IS NULL OR date(b.created_at) >= date(?))")
        params.append(start_date)

    if end_date:
        conditions.append("(b.created_at IS NULL OR date(b.created_at) <= date(?))")
        params.append(end_date)

    if search:
        conditions.append("(p.name LIKE ? OR p.sku LIKE ? OR v.variant LIKE ?)")
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]

    if stock_state == "zero":
        conditions.append("COALESCE(s.qty, 0) <= 0")
    elif stock_state == "low":
        conditions.append("COALESCE(s.qty, 0) > 0 AND COALESCE(s.qty, 0) < ?")
        params.append(LOW_STOCK_THRESHOLD)
    elif stock_state == "ready":
        conditions.append("COALESCE(s.qty, 0) >= ?")
        params.append(LOW_STOCK_THRESHOLD)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += """
    GROUP BY
        p.id,
        v.id,
        p.sku,
        p.name,
        v.variant,
        v.price_retail,
        v.price_discount,
        v.price_nett,
        s.qty
    """

    return query, params


def _best_price(row):
    if row["price_nett"] > 0:
        return row["price_nett"]
    if row["price_discount"] > 0:
        return row["price_discount"]
    return row["price_retail"]


def _build_stock_summary(rows):
    zero_count = 0
    low_count = 0
    ready_count = 0
    total_qty = 0
    inventory_value = 0
    expiring_count = 0

    for row in rows:
        qty = int(row["qty"] or 0)
        total_qty += qty
        inventory_value += qty * _best_price(row)

        if qty <= 0:
            zero_count += 1
        elif qty < LOW_STOCK_THRESHOLD:
            low_count += 1
        else:
            ready_count += 1

        expiry_date = row.get("expiry_date")
        if expiry_date and qty > 0:
            try:
                expiry_days = (
                    datetime.strptime(expiry_date[:10], "%Y-%m-%d").date()
                    - datetime.utcnow().date()
                ).days
                if expiry_days <= 30:
                    expiring_count += 1
            except Exception:
                pass

    return {
        "total_variants": len(rows),
        "total_qty": total_qty,
        "zero_count": zero_count,
        "low_count": low_count,
        "ready_count": ready_count,
        "inventory_value": inventory_value,
        "expiring_count": expiring_count,
    }


@stock_bp.route("/")
def stock_table():
    db = get_db()

    search = (request.args.get("q") or "").strip()
    sort = (request.args.get("sort") or "qty_asc").strip()
    stock_state = _get_stock_state()
    warehouse_id = _resolve_stock_warehouse(db)

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
    order_by = _get_sort_clause(sort)

    base_query, params = _build_stock_query(
        warehouse_id,
        search,
        start_date,
        end_date,
        stock_state,
    )

    rows = db.execute(
        f"""
        {base_query}
        ORDER BY {order_by}, age_days DESC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()
    data = [dict(r) for r in rows]

    total = db.execute(
        f"SELECT COUNT(*) FROM ({base_query}) stock_rows",
        params,
    ).fetchone()[0]

    summary_rows = [
        dict(r)
        for r in db.execute(
            f"{base_query} ORDER BY {order_by}, age_days DESC",
            params,
        ).fetchall()
    ]
    summary = _build_stock_summary(summary_rows)
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
        sort=sort,
        stock_state=stock_state,
        summary=summary,
    )


@stock_bp.route("/export")
def export_stock():
    db = get_db()

    search = (request.args.get("q") or "").strip()
    sort = (request.args.get("sort") or "qty_asc").strip()
    stock_state = _get_stock_state()
    warehouse_id = _resolve_stock_warehouse(db)
    start_date = parse_date(request.args.get("start_date"))
    end_date = parse_date(request.args.get("end_date"))
    order_by = _get_sort_clause(sort)

    base_query, params = _build_stock_query(
        warehouse_id,
        search,
        start_date,
        end_date,
        stock_state,
    )

    rows = [
        dict(r)
        for r in db.execute(
            f"{base_query} ORDER BY {order_by}, age_days DESC",
            params,
        ).fetchall()
    ]

    warehouse = db.execute(
        "SELECT name FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    warehouse_name = (warehouse["name"] if warehouse else f"warehouse_{warehouse_id}").replace(" ", "_")

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "SKU",
            "Nama Produk",
            "Variant",
            "Qty",
            "Harga Retail",
            "Harga Discount",
            "Harga Nett",
            "Aging (Hari)",
            "Tanggal Masuk",
            "Expiry",
        ]
    )

    for row in rows:
        writer.writerow(
            [
                row["sku"],
                row["name"],
                row["variant"],
                row["qty"],
                row["price_retail"],
                row["price_discount"],
                row["price_nett"],
                row["age_days"],
                row["created_at"][:10] if row["created_at"] else "",
                row["expiry_date"][:10] if row["expiry_date"] else "",
            ]
        )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=stok_gudang_{warehouse_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )
        },
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
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "error", "message": "Tidak punya akses ke gudang ini"})
        flash("Tidak punya akses ke gudang ini", "error")
        return redirect("/stock")

    try:
        if role in ["leader", "owner", "super_admin"]:
            ok = adjust_stock(product_id, variant_id, warehouse_id, qty)

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                if ok:
                    return jsonify({"status": "success"})
                return jsonify({"status": "error", "message": "Stock gagal / tidak cukup"})

            if ok:
                flash("Stock berhasil diupdate", "success")
            else:
                flash("Stock gagal / tidak cukup", "error")

        elif role == "admin":
            db.execute(
                """
                INSERT INTO approvals(type, product_id, variant_id, warehouse_id, qty, note, requested_by)
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    "ADJUST",
                    product_id,
                    variant_id,
                    warehouse_id,
                    qty,
                    request.form.get("note") or "Adjustment request",
                    session.get("user_id"),
                ),
            )
            db.commit()

            subj = "Permintaan Adjustment Stok"
            msg = (
                f"User {session.get('user_id')} meminta adjustment stok. "
                f"Produk:{product_id} Variant:{variant_id} Gudang:{warehouse_id} Qty:{qty}"
            )
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
            return jsonify({"status": "error", "message": "Tidak boleh kosong"})

        if field == "sku":
            exist = db.execute(
                "SELECT id FROM products WHERE sku=? AND id!=?",
                (value, product_id),
            ).fetchone()

            if exist:
                return jsonify({"status": "error", "message": "SKU sudah ada"})

            db.execute("UPDATE products SET sku=? WHERE id=?", (value, product_id))

        elif field == "name":
            db.execute("UPDATE products SET name=? WHERE id=?", (value, product_id))

        elif field == "variant":
            db.execute("UPDATE product_variants SET variant=? WHERE id=?", (value, variant_id))

        elif field in ["price_retail", "price_discount", "price_nett"]:
            try:
                val = float(value)
            except:
                return jsonify({"status": "error", "message": "Harus angka"})
            db.execute(f"UPDATE product_variants SET {field}=? WHERE id=?", (val, variant_id))
        else:
            return jsonify({"status": "error", "message": "Field tidak dikenal"})

        db.commit()
        return jsonify({"status": "success"})

    except Exception as e:
        print("UPDATE ERROR:", e)
        db.rollback()
        return jsonify({"status": "error"})


@stock_bp.route("/bulk-adjust", methods=["POST"])
def bulk_adjust():
    try:
        data = request.get_json(silent=True) or {}
        items = data.get("items", [])
    except:
        return jsonify({"status": "error"})

    if not items:
        return jsonify({"status": "error", "message": "No data"})

    role = session.get("role")
    user_wh = session.get("warehouse_id")

    if role == "admin":
        return jsonify(
            {
                "status": "error",
                "message": "Bulk adjust untuk admin dinonaktifkan. Gunakan adjust per item agar approval tercatat.",
            }
        )

    if role not in ["leader", "owner", "super_admin"]:
        return jsonify({"status": "error", "message": "Tidak punya akses"})

    try:
        failed = 0
        for item in items:
            warehouse_id = int(item.get("warehouse_id", 0))
            if role == "leader" and warehouse_id != user_wh:
                failed += 1
                continue

            ok = adjust_stock(
                int(item.get("product_id", 0)),
                int(item.get("variant_id", 0)),
                warehouse_id,
                int(item.get("qty", 0)),
            )

            if not ok:
                failed += 1

        if failed:
            return jsonify({"status": "error", "message": f"{failed} item gagal di-adjust"})

        return jsonify({"status": "success"})

    except Exception as e:
        print("BULK ERROR:", e)
        return jsonify({"status": "error"})
