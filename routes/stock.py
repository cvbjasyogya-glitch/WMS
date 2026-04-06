import csv
from datetime import datetime
from io import StringIO
from urllib.parse import urlencode

from flask import Blueprint, Response, render_template, request, session, redirect, flash, jsonify

from database import get_db

from services.stock_service import adjust_stock
from services.notification_service import notify_operational_event, notify_roles
from services.whatsapp_service import send_role_based_notification
from services.pagination import build_pagination_state
from services.rbac import has_permission, is_scoped_role, normalize_role
from routes.products import build_product_studio_context

stock_bp = Blueprint("stock", __name__, url_prefix="/stock")
LOW_STOCK_THRESHOLD = 5
WORKSPACE_MODES = {"inventory", "products"}


def _can_view_inventory_value():
    return normalize_role(session.get("role")) in {"owner", "super_admin"}
DEFAULT_SORT = "qty_asc"

SORT_DEFINITIONS = {
    "sku_asc": {
        "field": "sku",
        "direction": "asc",
        "clause": "p.sku ASC, p.name ASC, v.variant ASC",
    },
    "sku_desc": {
        "field": "sku",
        "direction": "desc",
        "clause": "p.sku DESC, p.name ASC, v.variant ASC",
    },
    "name_asc": {
        "field": "name",
        "direction": "asc",
        "clause": "p.name ASC, v.variant ASC, p.sku ASC",
    },
    "name_desc": {
        "field": "name",
        "direction": "desc",
        "clause": "p.name DESC, v.variant ASC, p.sku ASC",
    },
    "variant_asc": {
        "field": "variant",
        "direction": "asc",
        "clause": "v.variant ASC, p.name ASC, p.sku ASC",
    },
    "variant_desc": {
        "field": "variant",
        "direction": "desc",
        "clause": "v.variant DESC, p.name ASC, p.sku ASC",
    },
    "qty_asc": {
        "field": "qty",
        "direction": "asc",
        "clause": "qty ASC, p.name ASC, v.variant ASC",
    },
    "qty_desc": {
        "field": "qty",
        "direction": "desc",
        "clause": "qty DESC, p.name ASC, v.variant ASC",
    },
    "status_asc": {
        "field": "status",
        "direction": "asc",
        "clause": """
            CASE
                WHEN COALESCE(s.qty, 0) <= 0 THEN 0
                WHEN COALESCE(s.qty, 0) < 5 THEN 1
                ELSE 2
            END ASC,
            p.name ASC,
            v.variant ASC
        """,
    },
    "status_desc": {
        "field": "status",
        "direction": "desc",
        "clause": """
            CASE
                WHEN COALESCE(s.qty, 0) <= 0 THEN 0
                WHEN COALESCE(s.qty, 0) < 5 THEN 1
                ELSE 2
            END DESC,
            p.name ASC,
            v.variant ASC
        """,
    },
    "price_retail_asc": {
        "field": "price_retail",
        "direction": "asc",
        "clause": "v.price_retail ASC, p.name ASC, v.variant ASC",
    },
    "price_retail_desc": {
        "field": "price_retail",
        "direction": "desc",
        "clause": "v.price_retail DESC, p.name ASC, v.variant ASC",
    },
    "price_discount_asc": {
        "field": "price_discount",
        "direction": "asc",
        "clause": "v.price_discount ASC, p.name ASC, v.variant ASC",
    },
    "price_discount_desc": {
        "field": "price_discount",
        "direction": "desc",
        "clause": "v.price_discount DESC, p.name ASC, v.variant ASC",
    },
    "price_nett_asc": {
        "field": "price_nett",
        "direction": "asc",
        "clause": "v.price_nett ASC, p.name ASC, v.variant ASC",
    },
    "price_nett_desc": {
        "field": "price_nett",
        "direction": "desc",
        "clause": "v.price_nett DESC, p.name ASC, v.variant ASC",
    },
    "age_asc": {
        "field": "age",
        "direction": "asc",
        "clause": "age_days ASC, p.name ASC, v.variant ASC",
    },
    "age_desc": {
        "field": "age",
        "direction": "desc",
        "clause": "age_days DESC, p.name ASC, v.variant ASC",
    },
    "created_asc": {
        "field": "created_at",
        "direction": "asc",
        "clause": "created_at ASC, p.name ASC, v.variant ASC",
    },
    "created_desc": {
        "field": "created_at",
        "direction": "desc",
        "clause": "created_at DESC, p.name ASC, v.variant ASC",
    },
}

SORTABLE_FIELDS = {
    "sku": ("sku_asc", "sku_desc"),
    "name": ("name_asc", "name_desc"),
    "variant": ("variant_asc", "variant_desc"),
    "qty": ("qty_asc", "qty_desc"),
    "status": ("status_asc", "status_desc"),
    "price_retail": ("price_retail_asc", "price_retail_desc"),
    "price_discount": ("price_discount_asc", "price_discount_desc"),
    "price_nett": ("price_nett_asc", "price_nett_desc"),
    "age": ("age_desc", "age_asc"),
    "created_at": ("created_desc", "created_asc"),
}


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

    if is_scoped_role(role):
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


def _normalize_sort(sort):
    sort = (sort or DEFAULT_SORT).strip().lower()
    return sort if sort in SORT_DEFINITIONS else DEFAULT_SORT


def _get_sort_clause(sort):
    return SORT_DEFINITIONS[_normalize_sort(sort)]["clause"]


def _get_sort_state(sort):
    normalized = _normalize_sort(sort)
    config = SORT_DEFINITIONS[normalized]
    return {
        "code": normalized,
        "field": config["field"],
        "direction": config["direction"],
    }


def _build_sort_links():
    current_params = request.args.to_dict(flat=True)
    links = {}

    for field, (primary_sort, alternate_sort) in SORTABLE_FIELDS.items():
        next_sort = primary_sort
        current_state = _get_sort_state(current_params.get("sort"))

        if current_state["field"] == field and current_state["code"] == primary_sort:
            next_sort = alternate_sort

        params = dict(current_params)
        params["sort"] = next_sort
        params["page"] = 1
        links[field] = "?" + urlencode(params)

    return links


def _build_stock_query(warehouse_id, search, start_date, end_date, stock_state):
    query = """
    SELECT
        p.id as product_id,
        v.id as variant_id,
        ? as warehouse_id,
        p.sku,
        p.name,
        COALESCE(NULLIF(TRIM(p.unit_label), ''), 'pcs') as unit_label,
        COALESCE(NULLIF(TRIM(p.variant_mode), ''), 'variant') as variant_mode,
        COALESCE(c.name, '') as category_name,
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
    LEFT JOIN categories c ON c.id = p.category_id
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
        p.unit_label,
        p.variant_mode,
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


def _build_stock_group(rows):
    total_qty = 0
    zero_count = 0
    low_count = 0
    ready_count = 0
    variants = []
    skus = []
    created_dates = []
    oldest_age_days = 0
    product_ids = []
    unit_labels = []
    variant_modes = []

    for row in rows:
        qty = int(row.get("qty") or 0)
        total_qty += qty
        oldest_age_days = max(oldest_age_days, int(row.get("age_days") or 0))
        product_ids.append(row["product_id"])

        if qty <= 0:
            zero_count += 1
        elif qty < LOW_STOCK_THRESHOLD:
            low_count += 1
        else:
            ready_count += 1

        variant_name = (row.get("variant") or "-").strip() or "-"
        variants.append(variant_name)
        skus.append((row.get("sku") or "-").strip() or "-")
        unit_labels.append((row.get("unit_label") or "pcs").strip() or "pcs")
        variant_modes.append((row.get("variant_mode") or "variant").strip() or "variant")

        created_at = row.get("created_at")
        if created_at:
            created_dates.append(created_at[:10])

    variant_count = len(rows)
    unique_product_ids = list(dict.fromkeys(product_ids))
    unique_skus = list(dict.fromkeys(skus))
    product_count = len(unique_product_ids)
    preview_items = variants[:3]
    variant_preview = ", ".join(preview_items)
    if variant_count > len(preview_items):
        variant_preview = f"{variant_preview}, +{variant_count - len(preview_items)} lainnya"

    sku_preview_items = unique_skus[:3]
    sku_preview = ", ".join(sku_preview_items)
    if len(unique_skus) > len(sku_preview_items):
        sku_preview = f"{sku_preview}, +{len(unique_skus) - len(sku_preview_items)} lainnya"

    unique_unit_labels = list(dict.fromkeys(unit_labels))
    unit_label = unique_unit_labels[0] if unique_unit_labels else "pcs"
    unit_summary = unit_label if len(unique_unit_labels) == 1 else ", ".join(unique_unit_labels[:2])
    if len(unique_unit_labels) > 2:
        unit_summary = f"{unit_summary}, +{len(unique_unit_labels) - 2} lagi"

    unique_variant_modes = list(dict.fromkeys(variant_modes))
    variant_mode = unique_variant_modes[0] if len(unique_variant_modes) == 1 else "variant"

    if zero_count == variant_count:
        status_label = "Semua kosong"
        status_tone = "red"
    elif zero_count > 0:
        status_label = f"{zero_count} kosong, {low_count} menipis"
        status_tone = "red"
    elif low_count > 0:
        status_label = f"{low_count} menipis"
        status_tone = "orange"
    else:
        status_label = f"{ready_count} aman"
        status_tone = "green"

    if total_qty <= 0:
        qty_tone = "red"
    elif zero_count > 0 or low_count > 0:
        qty_tone = "orange"
    else:
        qty_tone = "green"

    return {
        "product_id": rows[0]["product_id"],
        "sku": rows[0]["sku"],
        "name": rows[0]["name"],
        "unit_label": unit_label,
        "unit_summary": unit_summary,
        "variant_mode": variant_mode,
        "category_name": rows[0].get("category_name") or "",
        "rows": rows,
        "is_grouped": variant_count > 1,
        "product_count": product_count,
        "multiple_products": product_count > 1,
        "editable_master": product_count == 1,
        "sku_count": len(unique_skus),
        "sku_preview": sku_preview,
        "variant_count": variant_count,
        "variant_preview": variant_preview,
        "total_qty": total_qty,
        "qty_tone": qty_tone,
        "status_label": status_label,
        "status_tone": status_tone,
        "oldest_age_days": oldest_age_days,
        "oldest_created_at": min(created_dates) if created_dates else None,
    }


def _group_stock_rows(rows):
    grouped_rows = []
    groups_by_name = {}

    for row in rows:
        normalized_name = " ".join(str(row.get("name") or "").strip().lower().split())
        group_key = normalized_name or f"product:{row['product_id']}"
        if group_key not in groups_by_name:
            groups_by_name[group_key] = []
            grouped_rows.append(groups_by_name[group_key])
        groups_by_name[group_key].append(row)

    return [_build_stock_group(group_rows) for group_rows in grouped_rows]


def _flatten_grouped_stock_rows(grouped_rows):
    flattened_rows = []
    for group in grouped_rows:
        flattened_rows.extend(group.get("rows", []))
    return flattened_rows


def _fetch_current_stock_qty(db, product_id, variant_id, warehouse_id):
    row = db.execute(
        """
        SELECT COALESCE(qty, 0) AS qty
        FROM stock
        WHERE product_id=? AND variant_id=? AND warehouse_id=?
        """,
        (product_id, variant_id, warehouse_id),
    ).fetchone()
    return int(row["qty"] or 0) if row else 0


def _resolve_category_id(db, category_name):
    category_name = (category_name or "").strip()
    if not category_name:
        raise ValueError("Kategori tidak boleh kosong")

    category = db.execute(
        "SELECT id FROM categories WHERE name=?",
        (category_name,),
    ).fetchone()
    if category:
        return category["id"]

    cursor = db.execute(
        "INSERT INTO categories(name) VALUES (?)",
        (category_name,),
    )
    return cursor.lastrowid


def _get_workspace_mode():
    workspace = (request.args.get("workspace") or "inventory").strip().lower()
    return workspace if workspace in WORKSPACE_MODES else "inventory"


def _can_manage_product_master():
    return has_permission(session.get("role"), "manage_product_master")


def _can_render_stock_adjust_controls():
    role = session.get("role")
    if role == "staff":
        return False
    return has_permission(role, "direct_stock_ops") or has_permission(role, "request_stock_ops")


def _stock_json_error(message, status_code=400):
    return jsonify({"status": "error", "message": message}), status_code


@stock_bp.route("/")
def stock_table():
    db = get_db()

    search = (request.args.get("q") or "").strip()
    product_search = (request.args.get("product_search") or "").strip()
    sort = _normalize_sort(request.args.get("sort"))
    stock_state = _get_stock_state()
    warehouse_id = _resolve_stock_warehouse(db)
    workspace = _get_workspace_mode()

    start_date = parse_date(request.args.get("start_date"))
    end_date = parse_date(request.args.get("end_date"))

    try:
        page = int(request.args.get("page", 1))
        if page < 1:
            page = 1
    except:
        page = 1

    try:
        product_page = int(request.args.get("product_page", 1))
        if product_page < 1:
            product_page = 1
    except:
        product_page = 1

    limit = 10
    offset = (page - 1) * limit
    order_by = _get_sort_clause(sort)

    base_query, params = _build_stock_query(
        warehouse_id,
        search,
        start_date,
        end_date,
        stock_state,
    )

    all_filtered_rows = [
        dict(r)
        for r in db.execute(
            f"{base_query} ORDER BY {order_by}, age_days DESC",
            params,
        ).fetchall()
    ]
    grouped_stock_rows = _group_stock_rows(all_filtered_rows)
    total_groups = len(grouped_stock_rows)
    grouped_data = grouped_stock_rows[offset: offset + limit]
    data = _flatten_grouped_stock_rows(grouped_data)

    summary = _build_stock_summary(all_filtered_rows)
    can_view_inventory_value = _can_view_inventory_value()
    if not can_view_inventory_value:
        summary["inventory_value"] = 0
    total_pages = max(1, (total_groups + limit - 1) // limit)
    pagination = build_pagination_state(
        "/stock/",
        page,
        total_pages,
        {
            "q": search,
            "warehouse": warehouse_id,
            "sort": sort,
            "stock_state": stock_state,
            "start_date": start_date.isoformat() if start_date else "",
            "end_date": end_date.isoformat() if end_date else "",
        },
        group_size=5,
    )
    warehouses = db.execute("SELECT * FROM warehouses ORDER BY name").fetchall()
    can_adjust_stock_ui = _can_render_stock_adjust_controls()
    can_bulk_adjust_ui = has_permission(session.get("role"), "direct_stock_ops")
    product_studio = build_product_studio_context(
        db,
        warehouse_id=warehouse_id,
        search=product_search,
        page=product_page,
        base_path="/stock/",
        extra_params={
            "workspace": "products",
            "warehouse": warehouse_id,
            "q": search,
            "sort": sort,
            "stock_state": stock_state,
            "start_date": start_date.isoformat() if start_date else "",
            "end_date": end_date.isoformat() if end_date else "",
        },
        page_param="product_page",
    )

    return render_template(
        "stok_gudang.html",
        data=data,
        grouped_data=grouped_data,
        search=search,
        warehouses=warehouses,
        warehouse_id=warehouse_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        total_pages=total_pages,
        sort=sort,
        sort_state=_get_sort_state(sort),
        sort_links=_build_sort_links(),
        stock_state=stock_state,
        summary=summary,
        can_view_inventory_value=can_view_inventory_value,
        pagination=pagination,
        can_adjust_stock_ui=can_adjust_stock_ui,
        can_bulk_adjust_ui=can_bulk_adjust_ui,
        stock_group_colspan=8 + (1 if can_adjust_stock_ui else 0),
        product_studio=product_studio,
        active_workspace=workspace,
    )


@stock_bp.route("/export")
def export_stock():
    db = get_db()

    search = (request.args.get("q") or "").strip()
    sort = _normalize_sort(request.args.get("sort"))
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
            "Satuan",
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
                row.get("unit_label") or "pcs",
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
    if is_scoped_role(role) and warehouse_id != user_wh:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"status": "error", "message": "Tidak punya akses ke gudang ini"})
        flash("Tidak punya akses ke gudang ini", "error")
        return redirect("/stock")

    try:
        if has_permission(role, "direct_stock_ops"):
            ok = adjust_stock(product_id, variant_id, warehouse_id, qty)

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                if ok:
                    try:
                        stock_item = db.execute(
                            """
                            SELECT
                                p.sku,
                                p.name AS product_name,
                                COALESCE(v.variant, 'default') AS variant_name,
                                w.name AS warehouse_name
                            FROM products p
                            JOIN product_variants v ON v.product_id = p.id
                            JOIN warehouses w ON w.id = ?
                            WHERE p.id=? AND v.id=?
                            """,
                            (warehouse_id, product_id, variant_id),
                        ).fetchone()
                        if stock_item:
                            variant_label = (
                                "Default"
                                if str(stock_item["variant_name"]).lower() == "default"
                                else stock_item["variant_name"]
                            )
                            qty_label = f"+{qty}" if qty > 0 else str(qty)
                            notify_operational_event(
                                f"Adjustment stok: {stock_item['sku']} - {stock_item['product_name']}",
                                (
                                    f"Stok {stock_item['sku']} - {stock_item['product_name']} / {variant_label} "
                                    f"di {(stock_item['warehouse_name'] or f'Gudang {warehouse_id}').strip()} "
                                    f"diubah sebanyak {qty_label}."
                                ),
                                warehouse_id=warehouse_id,
                                category="inventory",
                                link_url="/stock/",
                                source_type="stock_adjustment",
                                push_title="Adjustment stok",
                                push_body=f"{stock_item['sku']} | {qty_label}",
                            )
                    except Exception as exc:
                        print("STOCK ADJUST NOTIFICATION ERROR:", exc)
                    updated_qty = _fetch_current_stock_qty(db, product_id, variant_id, warehouse_id)
                    return jsonify(
                        {
                            "status": "success",
                            "message": "Stock berhasil diupdate",
                            "qty": updated_qty,
                        }
                    )
                return jsonify({"status": "error", "message": "Stock gagal / tidak cukup"})

            if ok:
                try:
                    stock_item = db.execute(
                        """
                        SELECT
                            p.sku,
                            p.name AS product_name,
                            COALESCE(v.variant, 'default') AS variant_name,
                            w.name AS warehouse_name
                        FROM products p
                        JOIN product_variants v ON v.product_id = p.id
                        JOIN warehouses w ON w.id = ?
                        WHERE p.id=? AND v.id=?
                        """,
                        (warehouse_id, product_id, variant_id),
                    ).fetchone()
                    if stock_item:
                        variant_label = (
                            "Default"
                            if str(stock_item["variant_name"]).lower() == "default"
                            else stock_item["variant_name"]
                        )
                        qty_label = f"+{qty}" if qty > 0 else str(qty)
                        notify_operational_event(
                            f"Adjustment stok: {stock_item['sku']} - {stock_item['product_name']}",
                            (
                                f"Stok {stock_item['sku']} - {stock_item['product_name']} / {variant_label} "
                                f"di {(stock_item['warehouse_name'] or f'Gudang {warehouse_id}').strip()} "
                                f"diubah sebanyak {qty_label}."
                            ),
                            warehouse_id=warehouse_id,
                            category="inventory",
                            link_url="/stock/",
                            source_type="stock_adjustment",
                            push_title="Adjustment stok",
                            push_body=f"{stock_item['sku']} | {qty_label}",
                        )
                except Exception as exc:
                    print("STOCK ADJUST NOTIFICATION ERROR:", exc)
                flash("Stock berhasil diupdate", "success")
            else:
                flash("Stock gagal / tidak cukup", "error")

        elif has_permission(role, "request_stock_ops"):
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
                notify_roles(
                    ["leader", "owner", "super_admin"],
                    subj,
                    msg,
                    warehouse_id=warehouse_id,
                    category="approval",
                    link_url="/approvals",
                    source_type="approval_queue",
                )
            except Exception as e:
                print("NOTIFY ERROR:", e)

            try:
                warehouse_row = db.execute(
                    "SELECT name FROM warehouses WHERE id=?",
                    (warehouse_id,),
                ).fetchone()
                send_role_based_notification(
                    "inventory.adjust_approval_requested",
                    {
                        "warehouse_id": warehouse_id,
                        "warehouse_name": ((warehouse_row["name"] if warehouse_row else "") or f"Gudang {warehouse_id}").strip(),
                        "requester_name": session.get("username") or "Staff",
                        "item_count": 1,
                        "link_url": "/approvals",
                    },
                )
            except Exception as exc:
                print("ADJUST WHATSAPP ROLE NOTIFICATION ERROR:", exc)

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
    if not _can_manage_product_master():
        return _stock_json_error(
            "Akses edit master produk hanya tersedia untuk admin, leader, owner, atau super admin.",
            403,
        )

    db = get_db()

    try:
        product_id = int(request.form.get("product_id") or 0)
        variant_id = int(request.form.get("variant_id") or 0)
        field = request.form.get("field")
        value = (request.form.get("value") or "").strip()
    except:
        return _stock_json_error("Input tidak valid")

    try:
        if not value:
            return _stock_json_error("Tidak boleh kosong")

        if field == "sku":
            exist = db.execute(
                "SELECT id FROM products WHERE sku=? AND id!=?",
                (value, product_id),
            ).fetchone()

            if exist:
                return _stock_json_error("SKU sudah ada")

            db.execute("UPDATE products SET sku=? WHERE id=?", (value, product_id))

        elif field == "name":
            db.execute("UPDATE products SET name=? WHERE id=?", (value, product_id))

        elif field == "variant":
            db.execute("UPDATE product_variants SET variant=? WHERE id=?", (value, variant_id))

        elif field in ["price_retail", "price_discount", "price_nett"]:
            try:
                val = float(value)
            except:
                return _stock_json_error("Harus angka")
            db.execute(f"UPDATE product_variants SET {field}=? WHERE id=?", (val, variant_id))
        else:
            return _stock_json_error("Field tidak dikenal")

        db.commit()
        return jsonify({"status": "success"})

    except Exception as e:
        print("UPDATE ERROR:", e)
        db.rollback()
        return _stock_json_error("Update gagal disimpan", 500)


@stock_bp.route("/update-detail", methods=["POST"])
def update_detail():
    if not _can_manage_product_master():
        return _stock_json_error(
            "Akses edit master produk hanya tersedia untuk admin, leader, owner, atau super admin.",
            403,
        )

    db = get_db()

    try:
        product_id = int(request.form.get("product_id") or 0)
        variant_id = int(request.form.get("variant_id") or 0)
        sku = (request.form.get("sku") or "").strip()
        name = (request.form.get("name") or "").strip()
        category_name = (request.form.get("category_name") or "").strip()
        unit_label = " ".join((request.form.get("unit_label") or "").strip().split()) or "pcs"
        variant = (request.form.get("variant") or "").strip()
        price_retail = float(request.form.get("price_retail") or 0)
        price_discount = float(request.form.get("price_discount") or 0)
        price_nett = float(request.form.get("price_nett") or 0)
    except (TypeError, ValueError):
        return _stock_json_error("Input detail produk tidak valid")

    if not product_id or not sku or not name or not category_name or not unit_label:
        return _stock_json_error("SKU, nama produk, kategori, dan satuan wajib diisi")

    if min(price_retail, price_discount, price_nett) < 0:
        return _stock_json_error("Harga tidak boleh minus")

    try:
        duplicate = db.execute(
            "SELECT id FROM products WHERE sku=? AND id!=?",
            (sku, product_id),
        ).fetchone()
        if duplicate:
            return _stock_json_error("SKU sudah dipakai produk lain")

        category_id = _resolve_category_id(db, category_name)

        db.execute("BEGIN")
        db.execute(
            "UPDATE products SET sku=?, name=?, category_id=?, unit_label=? WHERE id=?",
            (sku, name, category_id, unit_label, product_id),
        )

        if variant_id:
            if not variant:
                db.rollback()
                return _stock_json_error("Variant wajib diisi untuk baris detail")

            db.execute(
                """
                UPDATE product_variants
                SET variant=?, price_retail=?, price_discount=?, price_nett=?
                WHERE id=? AND product_id=?
                """,
                (variant, price_retail, price_discount, price_nett, variant_id, product_id),
            )

        db.commit()
        return jsonify({"status": "success", "message": "Detail produk berhasil diperbarui."})
    except Exception as error:
        print("UPDATE DETAIL ERROR:", error)
        db.rollback()
        return _stock_json_error("Detail produk gagal diperbarui", 500)


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

    if has_permission(role, "request_stock_ops"):
        return jsonify(
            {
                "status": "error",
                "message": "Bulk adjust untuk admin dinonaktifkan. Gunakan adjust per item agar approval tercatat.",
            }
        )

    if not has_permission(role, "direct_stock_ops"):
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
