from flask import Blueprint, Response, jsonify, render_template, request, session
from database import get_db
import csv
from io import StringIO

so_bp = Blueprint("so", __name__, url_prefix="/so")


def _warehouse_exists(db, warehouse_id):
    return db.execute(
        "SELECT 1 FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone() is not None


def _resolve_so_warehouses(db, display_id=None, gudang_id=None):
    warehouses = db.execute("SELECT * FROM warehouses ORDER BY id").fetchall()
    if not warehouses:
        return 1, 1

    default_display = warehouses[0]["id"]
    default_gudang = warehouses[1]["id"] if len(warehouses) >= 2 else default_display

    try:
        display_id = int(display_id or default_display)
    except:
        display_id = default_display

    try:
        gudang_id = int(gudang_id or default_gudang)
    except:
        gudang_id = default_gudang

    if not _warehouse_exists(db, display_id):
        display_id = default_display
    if not _warehouse_exists(db, gudang_id):
        gudang_id = default_gudang

    return display_id, gudang_id


def _apply_so_adjustment(db, product_id, variant_id, warehouse_id, system_qty, physical_qty, diff_qty, user_id, note):
    db.execute(
        """
        INSERT INTO stock_opname_results(
            product_id, variant_id, warehouse_id,
            system_qty, physical_qty, diff_qty, user_id
        )
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            product_id,
            variant_id,
            warehouse_id,
            system_qty,
            physical_qty,
            diff_qty,
            user_id,
        ),
    )

    db.execute(
        """
        INSERT INTO stock(product_id, variant_id, warehouse_id, qty)
        VALUES (?,?,?,?)
        ON CONFLICT(product_id,variant_id,warehouse_id)
        DO UPDATE SET qty = excluded.qty
        """,
        (product_id, variant_id, warehouse_id, physical_qty),
    )

    db.execute(
        """
        INSERT INTO stock_movements(
            product_id, variant_id, warehouse_id,
            batch_id, qty, type, created_at
        )
        VALUES (?,?,?,?,?,?,datetime('now'))
        """,
        (
            product_id,
            variant_id,
            warehouse_id,
            None,
            abs(diff_qty),
            "SO_ADJUST_IN" if diff_qty > 0 else "SO_ADJUST_OUT",
        ),
    )

    db.execute(
        """
        INSERT INTO stock_history(
            product_id, variant_id, warehouse_id,
            action, type, qty, note, user_id
        )
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            product_id,
            variant_id,
            warehouse_id,
            "STOCK_OPNAME",
            "ADJUST",
            diff_qty,
            note,
            user_id,
        ),
    )

    db.execute(
        """
        DELETE FROM stock_batches
        WHERE product_id=? AND variant_id=? AND warehouse_id=?
        """,
        (product_id, variant_id, warehouse_id),
    )

    if physical_qty > 0:
        db.execute(
            """
            INSERT INTO stock_batches(
                product_id, variant_id, warehouse_id,
                qty, remaining_qty, cost, created_at
            )
            VALUES (?,?,?,?,?,?,datetime('now'))
            """,
            (
                product_id,
                variant_id,
                warehouse_id,
                physical_qty,
                physical_qty,
                0,
            ),
        )


@so_bp.route("/")
def so_page():
    db = get_db()

    search = (request.args.get("q") or "").strip()

    try:
        page = int(request.args.get("page", 1))
        if page < 1:
            page = 1
    except:
        page = 1

    limit = 20
    offset = (page - 1) * limit

    display_id, gudang_id = _resolve_so_warehouses(
        db,
        request.args.get("display_id"),
        request.args.get("gudang_id"),
    )

    base_query = """
        FROM products p
        JOIN product_variants pv ON p.id = pv.product_id
        LEFT JOIN stock sd
            ON sd.product_id = p.id
            AND sd.variant_id = pv.id
            AND sd.warehouse_id = ?
        LEFT JOIN stock sg
            ON sg.product_id = p.id
            AND sg.variant_id = pv.id
            AND sg.warehouse_id = ?
        WHERE 1=1
    """

    params = [display_id, gudang_id]

    if search:
        base_query += " AND (p.name LIKE ? OR p.sku LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]

    total = db.execute("SELECT COUNT(*) " + base_query, params).fetchone()[0]

    rows = db.execute(
        """
        SELECT
            p.id as product_id,
            p.sku,
            p.name,
            pv.id as variant_id,
            pv.variant,
            COALESCE(sd.qty,0) as display_qty,
            COALESCE(sg.qty,0) as gudang_qty
        """
        + base_query
        + """
        ORDER BY p.name ASC
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()

    data = [dict(r) for r in rows]
    total_pages = max(1, (total + limit - 1) // limit)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(
            {
                "data": data,
                "page": page,
                "total_pages": total_pages,
            }
        )

    return render_template(
        "stock_opname.html",
        data=data,
        search=search,
        page=page,
        total_pages=total_pages,
        display_id=display_id,
        gudang_id=gudang_id,
    )


@so_bp.route("/submit", methods=["POST"])
def submit_so():
    db = get_db()
    data = request.get_json(silent=True) or {}

    display_id, gudang_id = _resolve_so_warehouses(
        db,
        data.get("display_id"),
        data.get("gudang_id"),
    )
    items = data.get("items", []) if isinstance(data.get("items", []), list) else []
    user_id = session.get("user_id")

    if not items:
        return jsonify({"error": "Tidak ada item yang dikirim"}), 400

    try:
        db.execute("BEGIN IMMEDIATE")
        processed = 0

        for item in items:
            try:
                product_id = int(item["product_id"])
                variant_id = int(item["variant_id"])
                display_system = int(item.get("display_system", 0) or 0)
                display_physical = int(item.get("display_physical", 0) or 0)
                gudang_system = int(item.get("gudang_system", 0) or 0)
                gudang_physical = int(item.get("gudang_physical", 0) or 0)
            except:
                continue

            if display_physical < 0 or gudang_physical < 0:
                db.rollback()
                return jsonify({"error": "Stock fisik tidak boleh negatif"}), 400

            diff_display = display_physical - display_system
            diff_gudang = gudang_physical - gudang_system

            if diff_display != 0:
                _apply_so_adjustment(
                    db,
                    product_id,
                    variant_id,
                    display_id,
                    display_system,
                    display_physical,
                    diff_display,
                    user_id,
                    "Stock Opname Display",
                )
                processed += 1

            if diff_gudang != 0:
                _apply_so_adjustment(
                    db,
                    product_id,
                    variant_id,
                    gudang_id,
                    gudang_system,
                    gudang_physical,
                    diff_gudang,
                    user_id,
                    "Stock Opname Gudang",
                )
                processed += 1

        if processed == 0:
            db.rollback()
            return jsonify({"error": "Tidak ada perubahan valid untuk disimpan"}), 400

        db.commit()
        return jsonify(
            {
                "message": "SO berhasil disimpan & stock sinkron",
                "processed": processed,
            }
        )

    except Exception as e:
        db.rollback()
        print("SO ERROR:", e)
        return jsonify({"error": str(e)}), 500


@so_bp.route("/export")
def export_so():
    db = get_db()

    try:
        warehouse_id = int(request.args.get("warehouse", 1))
    except:
        warehouse_id = 1

    data = db.execute(
        """
        SELECT
            p.sku,
            p.name,
            pv.variant,
            COALESCE(s.qty,0) as system_qty
        FROM products p
        JOIN product_variants pv ON p.id = pv.product_id
        LEFT JOIN stock s
            ON s.product_id = p.id
            AND s.variant_id = pv.id
            AND s.warehouse_id = ?
        ORDER BY p.name ASC
        """,
        (warehouse_id,),
    ).fetchall()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["SKU", "Nama Produk", "Variant", "System Qty"])

    for r in data:
        writer.writerow([r["sku"], r["name"], r["variant"], r["system_qty"]])

    output.seek(0)

    return Response(
        output,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename=stock_opname_{warehouse_id}.csv"
        },
    )


@so_bp.route("/export_report")
def export_so_report():
    db = get_db()

    try:
        warehouse_id = int(request.args.get("warehouse", 1))
    except:
        warehouse_id = 1

    data = db.execute(
        """
        SELECT
            p.sku,
            p.name,
            pv.variant,
            r.system_qty,
            r.physical_qty,
            r.diff_qty,
            r.created_at,
            u.username
        FROM stock_opname_results r
        JOIN products p ON r.product_id = p.id
        JOIN product_variants pv ON r.variant_id = pv.id
        LEFT JOIN users u ON r.user_id = u.id
        WHERE r.warehouse_id = ?
        ORDER BY r.created_at DESC
        """,
        (warehouse_id,),
    ).fetchall()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Tanggal",
            "User",
            "SKU",
            "Nama Produk",
            "Variant",
            "System",
            "Fisik",
            "Selisih",
        ]
    )

    for r in data:
        writer.writerow(
            [
                r["created_at"],
                r["username"] or "System",
                r["sku"],
                r["name"],
                r["variant"],
                r["system_qty"],
                r["physical_qty"],
                r["diff_qty"],
            ]
        )

    output.seek(0)

    return Response(
        output,
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename=laporan_so_{warehouse_id}.csv"
        },
    )
