from flask import Blueprint, render_template, request, Response, session, redirect, flash
from database import get_db
import csv
from io import StringIO

audit_bp = Blueprint("audit", __name__, url_prefix="/audit")


def is_logged_in():
    return "user_id" in session


# ==========================
# BUILD QUERY (FIX FINAL)
# ==========================
def build_query(filters, warehouse_id=None):

    query = """
    SELECT 
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

    if filters.get("search"):
        query += " AND (p.name LIKE ? OR p.sku LIKE ?)"
        params += [f"%{filters['search']}%", f"%{filters['search']}%"]

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

    if role == "admin":
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

    if session.get("role") not in ["super_admin", "admin"]:
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
        query, params = build_query(filters, warehouse_id)
        query += " ORDER BY datetime(h.date, '+7 hours') DESC LIMIT ? OFFSET ?"
        params += [limit, offset]

        rows = db.execute(query, params).fetchall()
        data = [dict(r) for r in rows]

    except Exception as e:
        print("AUDIT ERROR:", e)
        data = []

    return render_template(
        "audit.html",
        data=data,
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

    if session.get("role") not in ["super_admin", "admin"]:
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
        query, params = build_query(filters, warehouse_id)
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
