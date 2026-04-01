from flask import Blueprint, jsonify, render_template, request, session

from database import get_db
from services.rbac import is_scoped_role


product_lookup_bp = Blueprint("product_lookup", __name__, url_prefix="/info-produk")

PRODUCT_LOOKUP_LIMIT = 18


def _resolve_lookup_focus_warehouse(db, raw_warehouse_id):
    default_warehouse_id = session.get("warehouse_id") or 1
    fallback = db.execute("SELECT id FROM warehouses ORDER BY id LIMIT 1").fetchone()
    if fallback:
        default_warehouse_id = fallback["id"]

    if is_scoped_role(session.get("role")):
        return session.get("warehouse_id") or default_warehouse_id

    try:
        warehouse_id = int(raw_warehouse_id or session.get("warehouse_id") or default_warehouse_id)
    except (TypeError, ValueError):
        warehouse_id = default_warehouse_id

    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    return warehouse["id"] if warehouse else default_warehouse_id


def _normalize_lookup_query(raw_query):
    return " ".join(str(raw_query or "").strip().split())


def _build_lookup_search_conditions(query):
    if not query:
        return "", []

    clauses = []
    params = []
    for term in query.split():
        token = f"%{term}%"
        clauses.append(
            """
            (
                p.sku LIKE ?
                OR p.name LIKE ?
                OR COALESCE(c.name, '') LIKE ?
                OR COALESCE(v.variant, '') LIKE ?
                OR COALESCE(v.variant_code, '') LIKE ?
                OR COALESCE(v.color, '') LIKE ?
                OR COALESCE(v.gtin, '') LIKE ?
            )
            """
        )
        params.extend([token] * 7)

    return "WHERE " + " AND ".join(clauses), params


def _search_product_lookup_items(db, query, focus_warehouse_id):
    safe_query = _normalize_lookup_query(query)
    if not safe_query:
        return []

    where_clause, where_params = _build_lookup_search_conditions(safe_query)
    exact_token = safe_query.lower()
    prefix_token = f"{safe_query}%"

    rows = db.execute(
        f"""
        SELECT *
        FROM (
            SELECT
                p.id AS product_id,
                v.id AS variant_id,
                p.sku,
                p.name,
                COALESCE(c.name, '-') AS category,
                COALESCE(v.variant, 'default') AS variant,
                COALESCE(v.variant_code, '') AS variant_code,
                COALESCE(v.color, '') AS color,
                COALESCE(v.gtin, '') AS gtin,
                COALESCE(v.price_retail, 0) AS price_retail,
                COALESCE(v.price_discount, 0) AS price_discount,
                COALESCE(v.price_nett, 0) AS price_nett,
                COALESCE(SUM(s.qty), 0) AS total_qty,
                COALESCE(MAX(CASE WHEN s.warehouse_id = ? THEN s.qty END), 0) AS focus_qty
            FROM products p
            JOIN product_variants v ON v.product_id = p.id
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN stock s
                ON s.product_id = p.id
                AND s.variant_id = v.id
            {where_clause}
            GROUP BY
                p.id,
                v.id,
                p.sku,
                p.name,
                c.name,
                v.variant,
                v.variant_code,
                v.color,
                v.gtin,
                v.price_retail,
                v.price_discount,
                v.price_nett
        ) lookup_rows
        ORDER BY
            CASE
                WHEN lower(sku) = ? THEN 0
                WHEN lower(gtin) = ? THEN 1
                WHEN lower(variant_code) = ? THEN 2
                WHEN lower(name) = ? THEN 3
                WHEN lower(sku) LIKE lower(?) THEN 4
                WHEN lower(name) LIKE lower(?) THEN 5
                ELSE 6
            END,
            CASE WHEN focus_qty > 0 THEN 0 ELSE 1 END,
            focus_qty DESC,
            total_qty DESC,
            name COLLATE NOCASE ASC,
            CASE WHEN lower(variant) = 'default' THEN 0 ELSE 1 END,
            variant COLLATE NOCASE ASC
        LIMIT ?
        """,
        (
            focus_warehouse_id,
            *where_params,
            exact_token,
            exact_token,
            exact_token,
            exact_token,
            prefix_token,
            prefix_token,
            PRODUCT_LOOKUP_LIMIT,
        ),
    ).fetchall()

    if not rows:
        return []

    row_dicts = [dict(row) for row in rows]
    variant_ids = [row["variant_id"] for row in row_dicts]
    warehouses = [dict(row) for row in db.execute("SELECT id, name FROM warehouses ORDER BY id").fetchall()]

    placeholders = ",".join(["?"] * len(variant_ids))
    stock_rows = db.execute(
        f"""
        SELECT variant_id, warehouse_id, COALESCE(qty, 0) AS qty
        FROM stock
        WHERE variant_id IN ({placeholders})
        """,
        variant_ids,
    ).fetchall()

    stock_map = {}
    for row in stock_rows:
        stock_map[(row["variant_id"], row["warehouse_id"])] = int(row["qty"] or 0)

    items = []
    for row in row_dicts:
        variant_value = (row["variant"] or "default").strip()
        item_warehouses = []
        for warehouse in warehouses:
            qty = stock_map.get((row["variant_id"], warehouse["id"]), 0)
            item_warehouses.append(
                {
                    "id": warehouse["id"],
                    "name": warehouse["name"],
                    "qty": qty,
                    "is_focus": warehouse["id"] == focus_warehouse_id,
                    "has_stock": qty > 0,
                }
            )

        item = dict(row)
        item["variant_label"] = "Default" if variant_value.lower() == "default" else variant_value
        item["display_name"] = f'{row["sku"]} - {row["name"]}'
        item["best_price"] = (
            row["price_nett"]
            if row["price_nett"] > 0
            else (row["price_discount"] if row["price_discount"] > 0 else row["price_retail"])
        )
        item["warehouses"] = item_warehouses
        items.append(item)

    return items


@product_lookup_bp.route("/")
def index():
    db = get_db()
    warehouses = [dict(row) for row in db.execute("SELECT id, name FROM warehouses ORDER BY id").fetchall()]
    focus_warehouse_id = _resolve_lookup_focus_warehouse(db, request.args.get("warehouse_id"))
    return render_template(
        "product_lookup.html",
        lookup_warehouses=warehouses,
        lookup_focus_warehouse=focus_warehouse_id,
    )


@product_lookup_bp.route("/search")
def search():
    db = get_db()
    focus_warehouse_id = _resolve_lookup_focus_warehouse(db, request.args.get("warehouse_id"))
    query = _normalize_lookup_query(request.args.get("q"))
    items = _search_product_lookup_items(db, query, focus_warehouse_id)

    focus_warehouse = db.execute(
        "SELECT name FROM warehouses WHERE id=?",
        (focus_warehouse_id,),
    ).fetchone()

    return jsonify(
        {
            "status": "success",
            "query": query,
            "items": items,
            "count": len(items),
            "focus_warehouse_id": focus_warehouse_id,
            "focus_warehouse_name": focus_warehouse["name"] if focus_warehouse else "-",
        }
    )
