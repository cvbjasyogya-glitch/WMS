from flask import Blueprint, Response, jsonify, render_template, request, session
from database import get_db
from services.notification_service import notify_operational_event
import csv
from io import StringIO

so_bp = Blueprint("so", __name__, url_prefix="/so")
SO_PAGE_SIZE = 20


def _normalize_so_search(value):
    return (value or "").strip()


def _build_so_search_clause(search, columns):
    search = _normalize_so_search(search)
    if not search:
        return "", []

    token = f"%{search}%"
    return (
        " AND (" + " OR ".join(f"{column} LIKE ?" for column in columns) + ")",
        [token for _ in columns],
    )


def _warehouse_exists(db, warehouse_id):
    return db.execute(
        "SELECT 1 FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone() is not None


def _resolve_so_actor_user_id(db, user_id):
    try:
        safe_user_id = int(user_id or 0)
    except (TypeError, ValueError):
        safe_user_id = 0

    if safe_user_id <= 0:
        return None

    row = db.execute(
        "SELECT id FROM users WHERE id=?",
        (safe_user_id,),
    ).fetchone()
    return safe_user_id if row else None


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

    if display_id == gudang_id and len(warehouses) >= 2:
        gudang_id = next((w["id"] for w in warehouses if w["id"] != display_id), display_id)

    return display_id, gudang_id


def _build_so_summary(rows):
    gap_count = 0
    total_display = 0
    total_gudang = 0

    for row in rows:
        total_display += int(row["display_qty"] or 0)
        total_gudang += int(row["gudang_qty"] or 0)
        if row["display_qty"] != row["gudang_qty"]:
            gap_count += 1

    return {
        "items": len(rows),
        "display_qty": total_display,
        "gudang_qty": total_gudang,
        "gap_count": gap_count,
    }


def _build_so_response_payload(payload, *, message=None, processed=None):
    response = {
        "data": payload["data"],
        "page": payload["page"],
        "total_pages": payload["total_pages"],
        "summary": payload["summary"],
        "search": payload["search"],
        "display_id": payload["display_id"],
        "gudang_id": payload["gudang_id"],
        "display_name": payload["display_name"],
        "gudang_name": payload["gudang_name"],
    }
    if message is not None:
        response["message"] = message
    if processed is not None:
        response["processed"] = processed
    return response


def _build_so_base_query(search):
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
    params = []

    search_clause, search_params = _build_so_search_clause(
        search,
        ("p.name", "p.sku", "pv.variant"),
    )
    base_query += search_clause
    params += search_params

    return base_query, params


def _build_so_page_payload(db, display_id, gudang_id, search="", page=1, limit=20):
    try:
        page = int(page or 1)
        if page < 1:
            page = 1
    except:
        page = 1

    search = _normalize_so_search(search)
    offset = (page - 1) * limit
    base_query, extra_params = _build_so_base_query(search)
    params = [display_id, gudang_id] + extra_params

    total = db.execute("SELECT COUNT(*) " + base_query, params).fetchone()[0]

    summary_row = db.execute(
        """
        SELECT
            COUNT(*) as items,
            COALESCE(SUM(COALESCE(sd.qty, 0)), 0) as display_qty,
            COALESCE(SUM(COALESCE(sg.qty, 0)), 0) as gudang_qty,
            COALESCE(SUM(CASE WHEN COALESCE(sd.qty, 0) != COALESCE(sg.qty, 0) THEN 1 ELSE 0 END), 0) as gap_count
        """
        + base_query,
        params,
    ).fetchone()

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

    warehouses = [dict(w) for w in db.execute("SELECT * FROM warehouses ORDER BY name").fetchall()]
    warehouse_lookup = {w["id"]: w["name"] for w in warehouses}
    summary = dict(summary_row) if summary_row else _build_so_summary(rows)

    return {
        "data": [dict(r) for r in rows],
        "page": page,
        "total_pages": max(1, (total + limit - 1) // limit),
        "summary": summary,
        "search": search,
        "display_id": display_id,
        "gudang_id": gudang_id,
        "display_name": warehouse_lookup.get(display_id, f"Gudang {display_id}"),
        "gudang_name": warehouse_lookup.get(gudang_id, f"Gudang {gudang_id}"),
        "warehouses": warehouses,
    }


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
    search = _normalize_so_search(request.args.get("q"))

    display_id, gudang_id = _resolve_so_warehouses(
        db,
        request.args.get("display_id"),
        request.args.get("gudang_id"),
    )
    payload = _build_so_page_payload(
        db,
        display_id,
        gudang_id,
        search=search,
        page=request.args.get("page", 1),
        limit=SO_PAGE_SIZE,
    )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(_build_so_response_payload(payload))

    return render_template(
        "stock_opname.html",
        data=payload["data"],
        search=payload["search"],
        page=payload["page"],
        total_pages=payload["total_pages"],
        display_id=payload["display_id"],
        gudang_id=payload["gudang_id"],
        display_name=payload["display_name"],
        gudang_name=payload["gudang_name"],
        warehouses=payload["warehouses"],
        summary=payload["summary"],
    )


@so_bp.route("/submit", methods=["POST"])
def submit_so():
    db = get_db()
    data = request.get_json(silent=True) or {}
    search = _normalize_so_search(data.get("q"))
    page = data.get("page", 1)

    display_id, gudang_id = _resolve_so_warehouses(
        db,
        data.get("display_id"),
        data.get("gudang_id"),
    )
    items = data.get("items", []) if isinstance(data.get("items", []), list) else []
    user_id = _resolve_so_actor_user_id(db, session.get("user_id"))

    if not items:
        return jsonify({"error": "Tidak ada item yang dikirim"}), 400

    try:
        db.execute("BEGIN IMMEDIATE")
        processed = 0
        valid_items = 0

        for item in items:
            try:
                product_id = int(item["product_id"])
                variant_id = int(item["variant_id"])
                display_physical = int(item.get("display_physical", 0) or 0)
                gudang_physical = int(item.get("gudang_physical", 0) or 0)
            except Exception:
                continue

            entity = db.execute(
                """
                SELECT p.id
                FROM products p
                JOIN product_variants pv ON pv.product_id = p.id
                WHERE p.id=? AND pv.id=?
                """,
                (product_id, variant_id),
            ).fetchone()

            if not entity:
                db.rollback()
                return jsonify({"error": "Produk atau variant tidak valid"}), 400

            if display_physical < 0 or gudang_physical < 0:
                db.rollback()
                return jsonify({"error": "Stock fisik tidak boleh negatif"}), 400

            valid_items += 1

            stock_row = db.execute(
                """
                SELECT
                    COALESCE(MAX(CASE WHEN warehouse_id = ? THEN qty END), 0) as display_qty,
                    COALESCE(MAX(CASE WHEN warehouse_id = ? THEN qty END), 0) as gudang_qty
                FROM stock
                WHERE product_id=? AND variant_id=? AND warehouse_id IN (?, ?)
                """,
                (display_id, gudang_id, product_id, variant_id, display_id, gudang_id),
            ).fetchone()

            display_system = int(stock_row["display_qty"] or 0) if stock_row else 0
            gudang_system = int(stock_row["gudang_qty"] or 0) if stock_row else 0

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

        if valid_items == 0:
            db.rollback()
            return jsonify({"error": "Tidak ada item valid yang bisa diproses"}), 400

        if processed == 0:
            db.rollback()
            payload = _build_so_page_payload(
                db,
                display_id,
                gudang_id,
                search=search,
                page=page,
                limit=SO_PAGE_SIZE,
            )
            return jsonify(
                _build_so_response_payload(
                    payload,
                    message="Tidak ada perubahan baru. Data stok sudah sinkron dengan hasil SO.",
                    processed=0,
                )
            )

        db.commit()
        payload = _build_so_page_payload(
            db,
            display_id,
            gudang_id,
            search=search,
            page=page,
            limit=SO_PAGE_SIZE,
        )
        response_payload = _build_so_response_payload(
            payload,
            message="SO berhasil disimpan dan stock sudah sinkron",
            processed=processed,
        )
        try:
            notify_operational_event(
                f"Stock opname tersimpan: {processed} penyesuaian",
                (
                    f"Hasil stock opname berhasil disimpan untuk "
                    f"{payload['display_name']} dan {payload['gudang_name']} "
                    f"dengan {processed} penyesuaian stok."
                ),
                category="inventory",
                link_url="/so",
                source_type="stock_opname_session",
                push_title="Stock opname tersimpan",
                push_body=f"{processed} penyesuaian | {payload['display_name']} & {payload['gudang_name']}",
            )
        except Exception as exc:
            print("STOCK OPNAME NOTIFICATION ERROR:", exc)
        return jsonify(response_payload)

    except Exception as e:
        db.rollback()
        print("SO ERROR:", e)
        return jsonify({"error": str(e)}), 500


@so_bp.route("/export")
def export_so():
    db = get_db()
    search = _normalize_so_search(request.args.get("q"))

    display_id, gudang_id = _resolve_so_warehouses(
        db,
        request.args.get("display_id"),
        request.args.get("gudang_id"),
    )
    base_query, extra_params = _build_so_base_query(search)
    params = [display_id, gudang_id] + extra_params

    data = db.execute(
        """
        SELECT
            p.sku,
            p.name,
            pv.variant,
            COALESCE(sd.qty,0) as display_qty,
            COALESCE(sg.qty,0) as gudang_qty
        """
        + base_query
        + """
        ORDER BY p.name ASC
        """,
        params,
    ).fetchall()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "SKU",
            "Nama Produk",
            "Variant",
            "Display System Qty",
            "Gudang System Qty",
        ]
    )

    for row in data:
        writer.writerow(
            [
                row["sku"],
                row["name"],
                row["variant"],
                row["display_qty"],
                row["gudang_qty"],
            ]
        )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment;filename=stock_opname_display_{display_id}_gudang_{gudang_id}.csv"
            )
        },
    )


@so_bp.route("/export_report")
def export_so_report():
    db = get_db()
    search = _normalize_so_search(request.args.get("q"))

    display_id, gudang_id = _resolve_so_warehouses(
        db,
        request.args.get("display_id"),
        request.args.get("gudang_id"),
    )
    params = [display_id, gudang_id]
    search_clause, search_params = _build_so_search_clause(
        search,
        ("p.sku", "p.name", "pv.variant"),
    )
    params.extend(search_params)

    data = db.execute(
        """
        SELECT
            p.sku,
            p.name,
            pv.variant,
            w.name as warehouse_name,
            r.system_qty,
            r.physical_qty,
            r.diff_qty,
            r.created_at,
            u.username
        FROM stock_opname_results r
        JOIN products p ON r.product_id = p.id
        JOIN product_variants pv ON r.variant_id = pv.id
        LEFT JOIN users u ON r.user_id = u.id
        LEFT JOIN warehouses w ON r.warehouse_id = w.id
        WHERE r.warehouse_id IN (?, ?)
        """
        + search_clause
        + """
        ORDER BY r.created_at DESC
        """,
        params,
    ).fetchall()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Tanggal",
            "User",
            "Gudang",
            "SKU",
            "Nama Produk",
            "Variant",
            "System",
            "Fisik",
            "Selisih",
        ]
    )

    for row in data:
        writer.writerow(
            [
                row["created_at"],
                row["username"] or "System",
                row["warehouse_name"] or "-",
                row["sku"],
                row["name"],
                row["variant"],
                row["system_qty"],
                row["physical_qty"],
                row["diff_qty"],
            ]
        )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment;filename=laporan_so_display_{display_id}_gudang_{gudang_id}.csv"
            )
        },
    )
