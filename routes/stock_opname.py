import csv
import json
import sqlite3
import time
from io import StringIO

from flask import Blueprint, Response, current_app, jsonify, render_template, request, session

from database import get_db
from services.notification_service import notify_operational_event
from services.rbac import is_scoped_role

so_bp = Blueprint("so", __name__, url_prefix="/so")
SO_PAGE_SIZE = 20
SO_DB_LOCK_RETRY_ATTEMPTS = 2
SO_DB_LOCK_RETRY_DELAY_SECONDS = 0.35
SO_AREA_DISPLAY = "display"
SO_AREA_GUDANG = "gudang"


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


def _resolve_so_warehouse(db, warehouse_id=None, legacy_display_id=None, legacy_gudang_id=None):
    all_warehouses = [dict(row) for row in db.execute("SELECT * FROM warehouses ORDER BY name").fetchall()]
    if not all_warehouses:
        return 1, [], False

    default_warehouse_id = all_warehouses[0]["id"]
    warehouse_lookup = {warehouse["id"]: warehouse for warehouse in all_warehouses}
    scoped_warehouse = is_scoped_role(session.get("role"))

    if scoped_warehouse:
        raw_selected = session.get("warehouse_id") or default_warehouse_id
    else:
        raw_selected = warehouse_id
        if raw_selected in (None, ""):
            raw_selected = legacy_display_id
        if raw_selected in (None, ""):
            raw_selected = legacy_gudang_id
        if raw_selected in (None, ""):
            raw_selected = session.get("warehouse_id") or default_warehouse_id

    try:
        selected_warehouse_id = int(raw_selected or default_warehouse_id)
    except (TypeError, ValueError):
        selected_warehouse_id = default_warehouse_id

    if selected_warehouse_id not in warehouse_lookup:
        selected_warehouse_id = default_warehouse_id

    if scoped_warehouse:
        available_warehouses = [warehouse_lookup[selected_warehouse_id]]
    else:
        available_warehouses = all_warehouses

    return selected_warehouse_id, available_warehouses, scoped_warehouse


def _build_so_summary(rows):
    display_item_count = 0
    total_display = 0
    total_gudang = 0
    total_qty = 0

    for raw_row in rows:
        row = dict(raw_row)
        display_qty = int(row.get("display_qty") or 0)
        gudang_qty = int(row.get("gudang_qty") or 0)
        total_display += display_qty
        total_gudang += gudang_qty
        total_qty += int(row.get("total_qty") or (display_qty + gudang_qty))
        if display_qty > 0:
            display_item_count += 1

    return {
        "items": len(rows),
        "display_qty": total_display,
        "gudang_qty": total_gudang,
        "total_qty": total_qty,
        "gap_count": display_item_count,
    }


def _build_so_response_payload(payload, *, message=None, processed=None):
    response = {
        "data": payload["data"],
        "page": payload["page"],
        "total_pages": payload["total_pages"],
        "summary": payload["summary"],
        "search": payload["search"],
        "warehouse_id": payload["warehouse_id"],
        "warehouse_name": payload["warehouse_name"],
        "is_scoped_warehouse": payload["is_scoped_warehouse"],
        # Backward-compatible keys for any stale frontend/cache still reading legacy payloads.
        "display_id": payload["warehouse_id"],
        "gudang_id": payload["warehouse_id"],
        "display_name": payload["warehouse_name"],
        "gudang_name": payload["warehouse_name"],
    }
    if message is not None:
        response["message"] = message
    if processed is not None:
        response["processed"] = processed
    return response


def _load_so_request_payload():
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload

    raw_payload = (request.form.get("payload") or "").strip()
    if raw_payload:
        try:
            parsed = json.loads(raw_payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    form_payload = request.form.to_dict()
    return form_payload if form_payload else {}


def _is_sqlite_lock_error(exc):
    message = str(exc or "").strip().lower()
    return "locked" in message and "database" in message


def _is_foreign_key_constraint_error(exc):
    message = str(exc or "").strip().lower()
    return "foreign key constraint failed" in message


def _rollback_so_transaction(db):
    try:
        db.rollback()
    except Exception:
        pass


def _build_so_display_qty_expression(total_expression, display_balance_expression):
    total = f"COALESCE({total_expression}, 0)"
    display_balance = f"COALESCE({display_balance_expression}, 0)"
    return (
        "CASE "
        f"WHEN {total} <= 0 THEN 0 "
        f"WHEN {display_balance} <= 0 THEN 0 "
        f"WHEN {display_balance} >= {total} THEN {total} "
        f"ELSE {display_balance} "
        "END"
    )


def _build_so_gudang_qty_expression(total_expression, display_expression):
    total = f"COALESCE({total_expression}, 0)"
    return (
        "CASE "
        f"WHEN {total} - ({display_expression}) > 0 THEN {total} - ({display_expression}) "
        "ELSE 0 "
        "END"
    )


def _build_so_inventory_query(warehouse_id, search):
    display_qty_expression = _build_so_display_qty_expression("s.qty", "sad.qty")
    gudang_qty_expression = _build_so_gudang_qty_expression("s.qty", display_qty_expression)

    query = f"""
        SELECT
            p.id AS product_id,
            p.sku,
            p.name,
            pv.id AS variant_id,
            pv.variant,
            COALESCE(s.qty, 0) AS total_qty,
            {display_qty_expression} AS display_qty,
            {gudang_qty_expression} AS gudang_qty
        FROM products p
        JOIN product_variants pv ON p.id = pv.product_id
        LEFT JOIN stock s
            ON s.product_id = p.id
            AND s.variant_id = pv.id
            AND s.warehouse_id = ?
        LEFT JOIN stock_area_balances sad
            ON sad.product_id = p.id
            AND sad.variant_id = pv.id
            AND sad.warehouse_id = ?
            AND sad.area_kind = '{SO_AREA_DISPLAY}'
        WHERE 1=1
    """
    params = [warehouse_id, warehouse_id]

    search_clause, search_params = _build_so_search_clause(
        search,
        ("p.name", "p.sku", "pv.variant"),
    )
    query += search_clause
    params.extend(search_params)
    return query, params


def _build_so_page_payload(
    db,
    warehouse_id,
    search="",
    page=1,
    limit=20,
    *,
    scoped_warehouse=False,
    available_warehouses=None,
):
    try:
        page = int(page or 1)
        if page < 1:
            page = 1
    except (TypeError, ValueError):
        page = 1

    search = _normalize_so_search(search)
    offset = (page - 1) * limit
    inventory_query, params = _build_so_inventory_query(warehouse_id, search)

    total = db.execute(
        f"SELECT COUNT(*) FROM ({inventory_query}) inventory_rows",
        params,
    ).fetchone()[0]

    summary_row = db.execute(
        f"""
        SELECT
            COUNT(*) AS items,
            COALESCE(SUM(display_qty), 0) AS display_qty,
            COALESCE(SUM(gudang_qty), 0) AS gudang_qty,
            COALESCE(SUM(total_qty), 0) AS total_qty,
            COALESCE(SUM(CASE WHEN display_qty > 0 THEN 1 ELSE 0 END), 0) AS gap_count
        FROM ({inventory_query}) inventory_rows
        """,
        params,
    ).fetchone()

    rows = db.execute(
        f"""
        SELECT *
        FROM ({inventory_query}) inventory_rows
        ORDER BY name ASC, variant ASC
        LIMIT ? OFFSET ?
        """,
        (*params, limit, offset),
    ).fetchall()

    warehouses = available_warehouses or [dict(row) for row in db.execute("SELECT * FROM warehouses ORDER BY name").fetchall()]
    warehouse_lookup = {warehouse["id"]: warehouse["name"] for warehouse in warehouses}
    summary = dict(summary_row) if summary_row else _build_so_summary(rows)

    return {
        "data": [dict(row) for row in rows],
        "page": page,
        "total_pages": max(1, (total + limit - 1) // limit),
        "summary": summary,
        "search": search,
        "warehouse_id": warehouse_id,
        "warehouse_name": warehouse_lookup.get(warehouse_id, f"Gudang {warehouse_id}"),
        "warehouses": warehouses,
        "is_scoped_warehouse": scoped_warehouse,
    }


def _record_so_result(
    db,
    product_id,
    variant_id,
    warehouse_id,
    area_kind,
    system_qty,
    physical_qty,
    diff_qty,
    user_id,
):
    params = (
        product_id,
        variant_id,
        warehouse_id,
        area_kind,
        system_qty,
        physical_qty,
        diff_qty,
        user_id,
    )
    try:
        db.execute(
            """
            INSERT INTO stock_opname_results(
                product_id, variant_id, warehouse_id,
                area_kind, system_qty, physical_qty, diff_qty, user_id
            )
            VALUES (?,?,?,?,?,?,?,?)
            """,
            params,
        )
    except sqlite3.IntegrityError as exc:
        if not (_is_foreign_key_constraint_error(exc) and user_id is not None):
            raise
        current_app.logger.warning(
            "SO result insert retried without actor because user FK is stale",
            extra={
                "product_id": product_id,
                "variant_id": variant_id,
                "warehouse_id": warehouse_id,
                "area_kind": area_kind,
                "stale_user_id": user_id,
            },
        )
        db.execute(
            """
            INSERT INTO stock_opname_results(
                product_id, variant_id, warehouse_id,
                area_kind, system_qty, physical_qty, diff_qty, user_id
            )
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                product_id,
                variant_id,
                warehouse_id,
                area_kind,
                system_qty,
                physical_qty,
                diff_qty,
                None,
            ),
        )


def _apply_so_total_adjustment(
    db,
    product_id,
    variant_id,
    warehouse_id,
    system_qty,
    physical_qty,
    diff_qty,
    user_id,
    note,
):
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

    if diff_qty == 0:
        return

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


def _apply_so_adjustment(db, product_id, variant_id, warehouse_id, system_qty, physical_qty, diff_qty, user_id, note):
    normalized_note = str(note or "").strip().lower()
    if "display" in normalized_note:
        area_kind = SO_AREA_DISPLAY
    elif "gudang" in normalized_note:
        area_kind = SO_AREA_GUDANG
    else:
        area_kind = "total"

    _record_so_result(
        db,
        product_id,
        variant_id,
        warehouse_id,
        area_kind,
        system_qty,
        physical_qty,
        diff_qty,
        user_id,
    )
    _apply_so_total_adjustment(
        db,
        product_id,
        variant_id,
        warehouse_id,
        system_qty,
        physical_qty,
        diff_qty,
        user_id,
        note,
    )


def _upsert_so_area_balance(db, product_id, variant_id, warehouse_id, area_kind, qty, user_id):
    sql = """
        INSERT INTO stock_area_balances(
            product_id,
            variant_id,
            warehouse_id,
            area_kind,
            qty,
            updated_by
        )
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(product_id, variant_id, warehouse_id, area_kind)
        DO UPDATE SET
            qty = excluded.qty,
            updated_by = excluded.updated_by,
            updated_at = CURRENT_TIMESTAMP
    """
    params = (
        product_id,
        variant_id,
        warehouse_id,
        area_kind,
        qty,
        user_id,
    )
    try:
        db.execute(sql, params)
    except sqlite3.IntegrityError as exc:
        if not (_is_foreign_key_constraint_error(exc) and user_id is not None):
            raise
        current_app.logger.warning(
            "SO area balance upsert retried without actor because user FK is stale",
            extra={
                "product_id": product_id,
                "variant_id": variant_id,
                "warehouse_id": warehouse_id,
                "area_kind": area_kind,
                "stale_user_id": user_id,
            },
        )
        db.execute(
            sql,
            (
                product_id,
                variant_id,
                warehouse_id,
                area_kind,
                qty,
                None,
            ),
        )


def _resolve_so_area_system_quantities(total_qty, display_saved_qty):
    total_qty = max(int(total_qty or 0), 0)
    display_qty = max(int(display_saved_qty or 0), 0)
    if display_qty > total_qty:
        display_qty = total_qty
    gudang_qty = max(total_qty - display_qty, 0)
    return display_qty, gudang_qty, total_qty


@so_bp.route("/")
def so_page():
    db = get_db()
    search = _normalize_so_search(request.args.get("q"))
    warehouse_id, available_warehouses, scoped_warehouse = _resolve_so_warehouse(
        db,
        request.args.get("warehouse"),
        request.args.get("display_id"),
        request.args.get("gudang_id"),
    )
    payload = _build_so_page_payload(
        db,
        warehouse_id,
        search=search,
        page=request.args.get("page", 1),
        limit=SO_PAGE_SIZE,
        scoped_warehouse=scoped_warehouse,
        available_warehouses=available_warehouses,
    )

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify(_build_so_response_payload(payload))

    return render_template(
        "stock_opname.html",
        data=payload["data"],
        search=payload["search"],
        page=payload["page"],
        total_pages=payload["total_pages"],
        warehouse_id=payload["warehouse_id"],
        warehouse_name=payload["warehouse_name"],
        warehouses=payload["warehouses"],
        summary=payload["summary"],
        is_scoped_warehouse=payload["is_scoped_warehouse"],
    )


@so_bp.route("/submit", methods=["POST"])
def submit_so():
    db = get_db()
    data = _load_so_request_payload()
    search = _normalize_so_search(data.get("q"))
    page = data.get("page", 1)

    warehouse_id, available_warehouses, scoped_warehouse = _resolve_so_warehouse(
        db,
        data.get("warehouse_id") or data.get("warehouse"),
        data.get("display_id"),
        data.get("gudang_id"),
    )
    items = data.get("items", []) if isinstance(data.get("items", []), list) else []
    user_id = _resolve_so_actor_user_id(db, session.get("user_id"))

    if not items:
        return jsonify({"error": "Tidak ada item yang dikirim"}), 400

    max_retries = max(
        0,
        int(current_app.config.get("SO_DB_LOCK_RETRY_ATTEMPTS", SO_DB_LOCK_RETRY_ATTEMPTS) or 0),
    )
    retry_delay = max(
        0.0,
        float(
            current_app.config.get(
                "SO_DB_LOCK_RETRY_DELAY_SECONDS",
                SO_DB_LOCK_RETRY_DELAY_SECONDS,
            )
            or 0.0
        ),
    )

    for attempt in range(max_retries + 1):
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
                    _rollback_so_transaction(db)
                    return jsonify({"error": "Produk atau variant tidak valid"}), 400

                if display_physical < 0 or gudang_physical < 0:
                    _rollback_so_transaction(db)
                    return jsonify({"error": "Stock fisik tidak boleh negatif"}), 400

                valid_items += 1

                stock_row = db.execute(
                    f"""
                    SELECT
                        COALESCE(s.qty, 0) AS total_qty,
                        COALESCE(sad.qty, 0) AS display_saved_qty
                    FROM products p
                    JOIN product_variants pv ON pv.product_id = p.id
                    LEFT JOIN stock s
                        ON s.product_id = p.id
                        AND s.variant_id = pv.id
                        AND s.warehouse_id = ?
                    LEFT JOIN stock_area_balances sad
                        ON sad.product_id = p.id
                        AND sad.variant_id = pv.id
                        AND sad.warehouse_id = ?
                        AND sad.area_kind = '{SO_AREA_DISPLAY}'
                    WHERE p.id=? AND pv.id=?
                    """,
                    (warehouse_id, warehouse_id, product_id, variant_id),
                ).fetchone()

                display_system, gudang_system, total_system = _resolve_so_area_system_quantities(
                    stock_row["total_qty"] if stock_row else 0,
                    stock_row["display_saved_qty"] if stock_row else 0,
                )

                display_diff = display_physical - display_system
                gudang_diff = gudang_physical - gudang_system
                total_physical = display_physical + gudang_physical
                total_diff = total_physical - total_system

                if display_diff == 0 and gudang_diff == 0:
                    continue

                _upsert_so_area_balance(
                    db,
                    product_id,
                    variant_id,
                    warehouse_id,
                    SO_AREA_DISPLAY,
                    display_physical,
                    user_id,
                )
                _upsert_so_area_balance(
                    db,
                    product_id,
                    variant_id,
                    warehouse_id,
                    SO_AREA_GUDANG,
                    gudang_physical,
                    user_id,
                )

                if display_diff != 0:
                    _record_so_result(
                        db,
                        product_id,
                        variant_id,
                        warehouse_id,
                        SO_AREA_DISPLAY,
                        display_system,
                        display_physical,
                        display_diff,
                        user_id,
                    )

                if gudang_diff != 0:
                    _record_so_result(
                        db,
                        product_id,
                        variant_id,
                        warehouse_id,
                        SO_AREA_GUDANG,
                        gudang_system,
                        gudang_physical,
                        gudang_diff,
                        user_id,
                    )

                if total_diff != 0:
                    _apply_so_total_adjustment(
                        db,
                        product_id,
                        variant_id,
                        warehouse_id,
                        total_system,
                        total_physical,
                        total_diff,
                        user_id,
                        (
                            "Stock Opname Total Toko "
                            f"(Display {display_physical}, Gudang {gudang_physical})"
                        ),
                    )

                processed += 1

            if valid_items == 0:
                _rollback_so_transaction(db)
                return jsonify({"error": "Tidak ada item valid yang bisa diproses"}), 400

            if processed == 0:
                _rollback_so_transaction(db)
                payload = _build_so_page_payload(
                    db,
                    warehouse_id,
                    search=search,
                    page=page,
                    limit=SO_PAGE_SIZE,
                    scoped_warehouse=scoped_warehouse,
                    available_warehouses=available_warehouses,
                )
                return jsonify(
                    _build_so_response_payload(
                        payload,
                        message="Tidak ada perubahan baru. Data stok toko sudah sinkron dengan hasil SO.",
                        processed=0,
                    )
                )

            db.commit()
            payload = _build_so_page_payload(
                db,
                warehouse_id,
                search=search,
                page=page,
                limit=SO_PAGE_SIZE,
                scoped_warehouse=scoped_warehouse,
                available_warehouses=available_warehouses,
            )
            response_payload = _build_so_response_payload(
                payload,
                message="SO berhasil disimpan dan total stok toko sudah sinkron",
                processed=processed,
            )
            try:
                notify_operational_event(
                    f"Stock opname tersimpan: {processed} produk",
                    (
                        f"Hasil stock opname untuk {payload['warehouse_name']} berhasil disimpan. "
                        f"{processed} produk diperbarui dan total stok toko sudah disinkronkan."
                    ),
                    category="inventory",
                    link_url=f"/so?warehouse={warehouse_id}",
                    source_type="stock_opname_session",
                    push_title="Stock opname tersimpan",
                    push_body=f"{processed} produk | {payload['warehouse_name']}",
                )
            except Exception as exc:
                print("STOCK OPNAME NOTIFICATION ERROR:", exc)
            return jsonify(response_payload)

        except sqlite3.OperationalError as exc:
            _rollback_so_transaction(db)
            if _is_sqlite_lock_error(exc) and attempt < max_retries:
                current_app.logger.warning(
                    "SO submit hit SQLite lock, retry %s/%s",
                    attempt + 1,
                    max_retries,
                )
                time.sleep(retry_delay)
                continue
            if _is_sqlite_lock_error(exc):
                current_app.logger.warning("SO submit failed after SQLite lock retries")
                return jsonify(
                    {
                        "error": (
                            "SO gagal disimpan: database sedang sibuk di server. "
                            "Coba ulang beberapa detik lagi."
                        )
                    }
                ), 503
            current_app.logger.exception("SO ERROR")
            return jsonify({"error": str(exc)}), 500
        except Exception as exc:
            _rollback_so_transaction(db)
            current_app.logger.exception("SO ERROR")
            return jsonify({"error": str(exc)}), 500


@so_bp.route("/export")
def export_so():
    db = get_db()
    search = _normalize_so_search(request.args.get("q"))
    warehouse_id, available_warehouses, _ = _resolve_so_warehouse(
        db,
        request.args.get("warehouse"),
        request.args.get("display_id"),
        request.args.get("gudang_id"),
    )
    inventory_query, params = _build_so_inventory_query(warehouse_id, search)
    data = db.execute(
        f"""
        SELECT sku, name, variant, display_qty, gudang_qty, total_qty
        FROM ({inventory_query}) inventory_rows
        ORDER BY name ASC, variant ASC
        """,
        params,
    ).fetchall()

    warehouse_lookup = {warehouse["id"]: warehouse["name"] for warehouse in available_warehouses}
    warehouse_name = (warehouse_lookup.get(warehouse_id, f"warehouse_{warehouse_id}") or f"warehouse_{warehouse_id}").replace(" ", "_")

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "SKU",
            "Nama Produk",
            "Variant",
            "Display System Qty",
            "Gudang System Qty",
            "Total System Qty",
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
                row["total_qty"],
            ]
        )

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment;filename=stock_opname_{warehouse_name}.csv"
            )
        },
    )


@so_bp.route("/export_report")
def export_so_report():
    db = get_db()
    search = _normalize_so_search(request.args.get("q"))
    warehouse_id, available_warehouses, _ = _resolve_so_warehouse(
        db,
        request.args.get("warehouse"),
        request.args.get("display_id"),
        request.args.get("gudang_id"),
    )
    params = [warehouse_id]
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
            w.name AS warehouse_name,
            CASE
                WHEN LOWER(COALESCE(h.area_kind, '')) = 'display' THEN 'Display'
                WHEN LOWER(COALESCE(h.area_kind, '')) = 'gudang' THEN 'Gudang'
                ELSE 'Total'
            END AS area_label,
            h.system_qty,
            h.physical_qty,
            h.diff_qty,
            h.created_at,
            u.username
        FROM stock_opname_results h
        JOIN products p ON h.product_id = p.id
        JOIN product_variants pv ON h.variant_id = pv.id
        LEFT JOIN users u ON h.user_id = u.id
        LEFT JOIN warehouses w ON h.warehouse_id = w.id
        WHERE h.warehouse_id = ?
        """
        + search_clause
        + """
        ORDER BY h.created_at DESC
        """,
        params,
    ).fetchall()

    warehouse_lookup = {warehouse["id"]: warehouse["name"] for warehouse in available_warehouses}
    warehouse_name = (warehouse_lookup.get(warehouse_id, f"warehouse_{warehouse_id}") or f"warehouse_{warehouse_id}").replace(" ", "_")

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Tanggal",
            "User",
            "Gudang",
            "Area",
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
                row["area_label"],
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
                f"attachment;filename=laporan_so_{warehouse_name}.csv"
            )
        },
    )
