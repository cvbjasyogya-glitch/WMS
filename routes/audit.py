from flask import Blueprint, render_template, request, Response, session, redirect, flash
from database import get_db
from services.private_activity_policy import can_view_super_admin_private_audit
from services.rbac import has_permission, is_scoped_role
import csv
import re
from io import StringIO

audit_bp = Blueprint("audit", __name__, url_prefix="/audit")

VARIANT_CATEGORY_PRIORITY = {
    "Warna": 0,
    "Size": 1,
    "Varian": 2,
    "Default": 3,
}

COLOR_VARIANT_KEYWORDS = (
    "PINK",
    "BIRU",
    "ABU",
    "ABU-ABU",
    "HITAM",
    "PUTIH",
    "NAVY",
    "MERAH",
    "HIJAU",
    "KUNING",
    "ORANGE",
    "COKLAT",
    "CREAM",
    "UNGU",
    "GREY",
    "GRAY",
    "MAROON",
    "BEIGE",
    "GOLD",
    "SILVER",
)

SIZE_VARIANT_KEYWORDS = (
    "SIZE",
    "UK",
    "EU",
    "US",
    "CM",
)


def is_logged_in():
    return "user_id" in session


def _classify_variant_category(raw_variant):
    variant = (raw_variant or "").strip()
    if not variant or variant.lower() == "default":
        return "Default"

    normalized = variant.upper().replace("_", " ").strip()
    compact = re.sub(r"\s+", "", normalized)

    if any(keyword in normalized for keyword in SIZE_VARIANT_KEYWORDS):
        return "Size"

    if re.fullmatch(r"\d{1,3}([./-]\d{1,3})?", compact):
        return "Size"

    if "/" in normalized:
        lead_token = normalized.split("/", 1)[0].strip()
        if re.fullmatch(r"\d{1,3}([./-]\d{1,3})?", lead_token.replace(" ", "")):
            return "Size"

    if any(keyword in normalized for keyword in COLOR_VARIANT_KEYWORDS):
        return "Warna"

    return "Varian"


def _build_variant_category_caption(categories):
    if not categories:
        return "Tanpa kategori"

    if len(categories) == 1:
        return f"Kategori {categories[0]['label']}"

    return "Kategori campuran"


def group_audit_rows(rows):
    grouped_rows = []
    grouped_lookup = {}

    for row in rows:
        item = dict(row)
        action = (item.get("action") or "").upper()
        username = item.get("username") or "System"
        product_name = item.get("product_name") or "-"
        variant_value = (item.get("variant") or "").strip() or "Default"

        if action == "IMPORT":
            group_key = (
                item.get("date"),
                username,
                action,
                item.get("warehouse_name") or "-",
                product_name,
                item.get("note") or "-",
                item.get("ip_address") or "-",
            )
        else:
            group_key = ("single", item.get("history_id"))

        group = grouped_lookup.get(group_key)
        if group is None:
            group = {
                "date": item.get("date") or "-",
                "username": username,
                "action": action or "-",
                "warehouse_name": item.get("warehouse_name") or "-",
                "product_name": product_name,
                "note": item.get("note") or "-",
                "ip_address": item.get("ip_address") or "-",
                "items": [],
                "category_counts": {},
                "item_count": 0,
                "qty_total": 0,
                "category_caption": "",
                "has_dropdown": False,
            }
            grouped_lookup[group_key] = group
            grouped_rows.append(group)

        category_label = _classify_variant_category(variant_value)
        try:
            qty_value = int(item.get("qty") or 0)
        except (TypeError, ValueError):
            qty_value = 0

        group["items"].append(
            {
                "sku": item.get("sku") or "-",
                "variant": variant_value,
                "qty": qty_value,
                "category": category_label,
            }
        )
        group["item_count"] += 1
        group["qty_total"] += qty_value
        group["category_counts"][category_label] = group["category_counts"].get(category_label, 0) + 1

    for group in grouped_rows:
        sorted_categories = sorted(
            group["category_counts"].items(),
            key=lambda item: (VARIANT_CATEGORY_PRIORITY.get(item[0], 99), item[0]),
        )
        categories = []
        for label, _count in sorted_categories:
            category_items = [
                item
                for item in group["items"]
                if item["category"] == label
            ]
            category_items.sort(key=lambda item: (item["variant"], item["sku"]))
            categories.append(
                {
                    "label": label,
                    "count": len(category_items),
                    "items": category_items,
                }
            )

        group["categories"] = categories
        group["category_caption"] = _build_variant_category_caption(categories)
        group["has_dropdown"] = group["item_count"] > 1

    return grouped_rows


# ==========================
# BUILD QUERY (FIX FINAL)
# ==========================
def build_query(filters, warehouse_id=None, viewer_role=None):

    query = """
    SELECT 
        h.id as history_id,
        datetime(h.date, '+7 hours') as date,
        p.name as product_name,
        p.sku,
        v.variant,
        w.name as warehouse_name,
        COALESCE(u.username,'System') as username,
        h.action,
        h.qty,
        h.note,
        h.ip_address
    FROM stock_history h
    LEFT JOIN products p ON h.product_id = p.id
    LEFT JOIN product_variants v ON h.variant_id = v.id
    LEFT JOIN warehouses w ON h.warehouse_id = w.id
    LEFT JOIN users u ON h.user_id = u.id
    WHERE 1=1
    """

    params = []

    # 🔥 OPTIONAL: kalau mau semua gudang, comment ini
    if warehouse_id:
        query += " AND h.warehouse_id=?"
        params.append(warehouse_id)

    if not can_view_super_admin_private_audit(viewer_role):
        query += " AND COALESCE(u.role, '') <> 'super_admin'"

    if filters.get("search"):
        query += " AND (p.name LIKE ? OR p.sku LIKE ? OR v.variant LIKE ?)"
        params += [
            f"%{filters['search']}%",
            f"%{filters['search']}%",
            f"%{filters['search']}%",
        ]

    if filters.get("action"):
        query += " AND h.action=?"
        params.append(filters["action"])

    if filters.get("user"):
        query += " AND (u.username=? OR u.username IS NULL)"
        params.append(filters["user"])

    if filters.get("start") and filters["start"] != "":
        query += " AND date(h.date) >= date(?)"
        params.append(filters["start"])

    if filters.get("end") and filters["end"] != "":
        query += " AND date(h.date) <= date(?)"
        params.append(filters["end"])

    return query, params


def resolve_audit_warehouse(db):
    role = session.get("role")

    if is_scoped_role(role):
        warehouse_id = session.get("warehouse_id")
        if warehouse_id:
            return warehouse_id, warehouse_id

        fallback = db.execute("SELECT id FROM warehouses ORDER BY id LIMIT 1").fetchone()
        selected = fallback["id"] if fallback else None
        return selected, selected

    raw_warehouse = request.args.get("warehouse")
    if not raw_warehouse:
        return None, None

    try:
        selected = int(raw_warehouse)
    except (TypeError, ValueError):
        return None, None

    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (selected,),
    ).fetchone()
    if not warehouse:
        return None, None

    return selected, selected


# ==========================
# AUDIT PAGE
# ==========================
@audit_bp.route("/")
def audit_page():

    if not is_logged_in():
        return redirect("/login")

    if not has_permission(session.get("role"), "view_audit"):
        flash("Akses ditolak", "error")
        return redirect("/")

    db = get_db()

    filters = {
        "search": request.args.get("q"),
        "action": request.args.get("action"),
        "user": request.args.get("user"),
        "start": request.args.get("start_date"),
        "end": request.args.get("end_date"),
    }

    try:
        page = int(request.args.get("page", 1))
        if page < 1:
            page = 1
    except:
        page = 1

    limit = 50
    offset = (page - 1) * limit

    warehouse_id, selected_warehouse = resolve_audit_warehouse(db)
    warehouses = db.execute("SELECT * FROM warehouses ORDER BY name").fetchall()

    try:
        query, params = build_query(filters, warehouse_id, viewer_role=session.get("role"))
        query += " ORDER BY datetime(h.date, '+7 hours') DESC LIMIT ? OFFSET ?"
        params += [limit, offset]

        rows = db.execute(query, params).fetchall()
        data = [dict(r) for r in rows]
        grouped_data = group_audit_rows(data)

    except Exception as e:
        print("AUDIT ERROR:", e)
        data = []
        grouped_data = []

    return render_template(
        "audit.html",
        data=data,
        grouped_data=grouped_data,
        page=page,
        warehouses=warehouses,
        selected_warehouse=selected_warehouse,
    )


# ==========================
# EXPORT CSV
# ==========================
@audit_bp.route("/export")
def export_csv():

    if not is_logged_in():
        return redirect("/login")

    if not has_permission(session.get("role"), "view_audit"):
        flash("Akses ditolak", "error")
        return redirect("/")

    db = get_db()

    filters = {
        "search": request.args.get("q"),
        "action": request.args.get("action"),
        "user": request.args.get("user"),
        "start": request.args.get("start_date"),
        "end": request.args.get("end_date"),
    }

    warehouse_id, _ = resolve_audit_warehouse(db)

    try:
        query, params = build_query(filters, warehouse_id, viewer_role=session.get("role"))
        query += " ORDER BY datetime(h.date, '+7 hours') DESC LIMIT 2000"

        rows = db.execute(query, params).fetchall()
        data = [dict(r) for r in rows]

    except:
        data = []

    si = StringIO()
    writer = csv.writer(si)

    writer.writerow([
        "Tanggal","User","Aksi","SKU","Produk",
        "Variant","Gudang","Qty","Note","IP"
    ])

    for r in data:
        writer.writerow([
            r.get("date"),
            r.get("username"),
            r.get("action"),
            r.get("sku"),
            r.get("product_name"),
            r.get("variant"),
            r.get("warehouse_name"),
            r.get("qty"),
            r.get("note"),
            r.get("ip_address")
        ])

    return Response(
        si.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=audit_log.csv"}
    )
