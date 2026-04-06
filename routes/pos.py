from datetime import date as date_cls, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session

from database import get_db
from services.notification_service import notify_operational_event
from services.rbac import has_permission, is_scoped_role
from services.stock_service import remove_stock


pos_bp = Blueprint("pos", __name__, url_prefix="/kasir")

PAYMENT_METHODS = ("cash", "qris", "transfer", "debit", "credit")


def _to_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_decimal(value, default="0"):
    try:
        if value in (None, ""):
            value = default
        return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal(default).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _currency(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _normalize_sale_date(raw_value):
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return date_cls.today().isoformat()
    try:
        return date_cls.fromisoformat(raw_value).isoformat()
    except ValueError:
        return date_cls.today().isoformat()


def _normalize_payment_method(raw_value):
    method = (raw_value or "").strip().lower()
    return method if method in PAYMENT_METHODS else "cash"


def _normalize_sale_month(raw_value):
    safe_value = str(raw_value or "").strip()
    if not safe_value:
        today = date_cls.today()
        return f"{today.year:04d}-{today.month:02d}"

    try:
        normalized = date_cls.fromisoformat(f"{safe_value}-01")
        return f"{normalized.year:04d}-{normalized.month:02d}"
    except ValueError:
        today = date_cls.today()
        return f"{today.year:04d}-{today.month:02d}"


def _json_error(message, status=400):
    return jsonify({"status": "error", "message": message}), status


def _require_pos_access(json_mode=False):
    if has_permission(session.get("role"), "view_pos"):
        return None

    message = "Akses kasir hanya tersedia untuk role operasional."
    if json_mode:
        return _json_error(message, 403)

    flash(message, "error")
    return redirect("/workspace/")


def _default_warehouse_id(db):
    warehouse = db.execute(
        "SELECT id FROM warehouses ORDER BY id LIMIT 1"
    ).fetchone()
    return warehouse["id"] if warehouse else 1


def _resolve_pos_warehouse(db, raw_warehouse_id):
    default_warehouse = _default_warehouse_id(db)

    if is_scoped_role(session.get("role")):
        return session.get("warehouse_id") or default_warehouse

    selected = _to_int(raw_warehouse_id, session.get("warehouse_id") or default_warehouse)
    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (selected,),
    ).fetchone()
    return warehouse["id"] if warehouse else default_warehouse


def _resolve_pos_report_warehouse(db, raw_warehouse_id):
    if is_scoped_role(session.get("role")):
        return _resolve_pos_warehouse(db, raw_warehouse_id)

    safe_value = str(raw_warehouse_id or "").strip()
    if not safe_value:
        return None

    selected = _to_int(safe_value, None)
    if selected is None:
        return None

    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (selected,),
    ).fetchone()
    return warehouse["id"] if warehouse else None


def _fetch_pos_customers(db, warehouse_id):
    return [
        dict(row)
        for row in db.execute(
            """
            SELECT id, customer_name, contact_person, phone
            FROM crm_customers
            WHERE warehouse_id=?
            ORDER BY customer_name ASC
            LIMIT 300
            """,
            (warehouse_id,),
        ).fetchall()
    ]


def _fetch_pos_categories(db, warehouse_id):
    rows = db.execute(
        """
        SELECT DISTINCT c.name
        FROM products p
        JOIN product_variants v ON v.product_id = p.id
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN stock s
            ON s.product_id = p.id
           AND s.variant_id = v.id
           AND s.warehouse_id = ?
        WHERE COALESCE(c.name, '') <> ''
        ORDER BY c.name ASC
        """,
        (warehouse_id,),
    ).fetchall()
    return [row["name"] for row in rows if row["name"]]


def _build_pos_staff_option(row, warehouse_id):
    if row is None:
        return None

    role = row["role"]
    if not has_permission(role, "manage_pos"):
        return None

    employment_status = str(row["employment_status"] or "").strip().lower()
    if employment_status in {"inactive", "terminated", "resigned", "former", "nonactive", "non-active"}:
        return None

    assigned_warehouse_id = _to_int(
        row["employee_warehouse_id"],
        _to_int(row["user_warehouse_id"], 0),
    )
    if warehouse_id is not None and is_scoped_role(role) and assigned_warehouse_id > 0 and int(assigned_warehouse_id) != int(warehouse_id):
        return None

    display_name = (row["full_name"] or row["username"] or "").strip() or f"User {row['id']}"
    meta_parts = []
    if row["position"]:
        meta_parts.append(str(row["position"]).strip())
    if row["warehouse_name"]:
        meta_parts.append(str(row["warehouse_name"]).strip())

    label = display_name
    if meta_parts:
        label = f"{display_name} | {' · '.join(part for part in meta_parts if part)}"

    return {
        "id": int(row["id"]),
        "username": row["username"],
        "display_name": display_name,
        "label": label,
        "role": role,
        "warehouse_id": assigned_warehouse_id or None,
    }


def _fetch_pos_staff_options(db, warehouse_id):
    rows = db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.role,
            u.warehouse_id AS user_warehouse_id,
            u.employee_id,
            e.full_name,
            e.position,
            e.warehouse_id AS employee_warehouse_id,
            e.employment_status,
            w.name AS warehouse_name
        FROM users u
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses w ON w.id = COALESCE(e.warehouse_id, u.warehouse_id)
        ORDER BY COALESCE(NULLIF(TRIM(e.full_name), ''), u.username) ASC, u.id ASC
        """
    ).fetchall()

    options = []
    for row in rows:
        option = _build_pos_staff_option(row, warehouse_id)
        if option:
            options.append(option)
    return options


def _resolve_pos_cashier_option(db, warehouse_id, raw_user_id):
    selected_user_id = _to_int(raw_user_id, session.get("user_id") or 0)
    row = db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.role,
            u.warehouse_id AS user_warehouse_id,
            u.employee_id,
            e.full_name,
            e.position,
            e.warehouse_id AS employee_warehouse_id,
            e.employment_status,
            w.name AS warehouse_name
        FROM users u
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses w ON w.id = COALESCE(e.warehouse_id, u.warehouse_id)
        WHERE u.id=?
        LIMIT 1
        """,
        (selected_user_id,),
    ).fetchone()
    option = _build_pos_staff_option(row, warehouse_id)
    if not option:
        raise ValueError("Kasir / Sales yang dipilih tidak valid untuk gudang aktif.")
    return option


def _fetch_pos_summary(db, warehouse_id, sale_date):
    total_tx = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM pos_sales
        WHERE warehouse_id=? AND sale_date=?
        """,
        (warehouse_id, sale_date),
    ).fetchone()["total"]

    total_revenue = db.execute(
        """
        SELECT COALESCE(SUM(total_amount), 0) AS total
        FROM pos_sales
        WHERE warehouse_id=? AND sale_date=?
        """,
        (warehouse_id, sale_date),
    ).fetchone()["total"]

    total_items = db.execute(
        """
        SELECT COALESCE(SUM(total_items), 0) AS total
        FROM pos_sales
        WHERE warehouse_id=? AND sale_date=?
        """,
        (warehouse_id, sale_date),
    ).fetchone()["total"]

    cashier_total = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM pos_sales
        WHERE warehouse_id=? AND sale_date=? AND cashier_user_id=?
        """,
        (warehouse_id, sale_date, session.get("user_id")),
    ).fetchone()["total"]

    return {
        "total_tx": int(total_tx or 0),
        "total_revenue": _currency(total_revenue or 0),
        "total_items": int(total_items or 0),
        "cashier_total": int(cashier_total or 0),
    }


def _fetch_recent_sales(db, warehouse_id, sale_date):
    rows = db.execute(
        """
        SELECT
            ps.id,
            ps.receipt_no,
            ps.sale_date,
            ps.payment_method,
            ps.total_items,
            ps.total_amount,
            ps.paid_amount,
            ps.change_amount,
            c.customer_name,
            u.username AS cashier_name
        FROM pos_sales ps
        JOIN crm_customers c ON c.id = ps.customer_id
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        WHERE ps.warehouse_id=? AND ps.sale_date=?
        ORDER BY ps.id DESC
        LIMIT 20
        """,
        (warehouse_id, sale_date),
    ).fetchall()
    return [dict(row) for row in rows]


def _normalize_pos_log_date_range(raw_date_from, raw_date_to):
    date_from = date_cls.fromisoformat(_normalize_sale_date(raw_date_from))
    date_to = date_cls.fromisoformat(_normalize_sale_date(raw_date_to))
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "label": _format_pos_period_label(date_from.isoformat(), date_to.isoformat()),
    }


def _format_pos_time_label(raw_value):
    safe_value = str(raw_value or "").strip()
    if len(safe_value) >= 16:
        return safe_value[11:16]
    return "-"


def _fetch_pos_sale_item_map(db, purchase_ids):
    normalized_ids = [int(purchase_id) for purchase_id in purchase_ids if _to_int(purchase_id, 0) > 0]
    if not normalized_ids:
        return {}

    placeholders = ",".join("?" for _ in normalized_ids)
    rows = db.execute(
        f"""
        SELECT
            cpi.purchase_id,
            COALESCE(NULLIF(TRIM(p.sku), ''), '-') AS sku,
            COALESCE(NULLIF(TRIM(p.name), ''), 'Produk') AS product_name,
            COALESCE(NULLIF(TRIM(pv.variant), ''), 'default') AS variant_name,
            COALESCE(cpi.qty, 0) AS qty,
            COALESCE(cpi.unit_price, 0) AS unit_price,
            COALESCE(cpi.line_total, 0) AS line_total
        FROM crm_purchase_items cpi
        LEFT JOIN products p ON p.id = cpi.product_id
        LEFT JOIN product_variants pv ON pv.id = cpi.variant_id
        WHERE cpi.purchase_id IN ({placeholders})
        ORDER BY cpi.purchase_id ASC, cpi.id ASC
        """,
        normalized_ids,
    ).fetchall()

    item_map = {}
    for row in rows:
        purchase_id = int(row["purchase_id"])
        unit_price = _currency(row["unit_price"] or 0)
        line_total = _currency(row["line_total"] or 0)
        item_map.setdefault(purchase_id, []).append(
            {
                "sku": row["sku"],
                "product_name": row["product_name"],
                "variant_name": row["variant_name"],
                "qty": int(row["qty"] or 0),
                "unit_price": unit_price,
                "line_total": line_total,
                "unit_price_label": _format_pos_currency_label(unit_price),
                "line_total_label": _format_pos_currency_label(line_total),
                "summary_label": f"{row['sku']} · {row['product_name']} · {row['variant_name']} x{int(row['qty'] or 0)}",
            }
        )
    return item_map


def _fetch_pos_sale_logs(db, date_from, date_to, selected_warehouse=None, cashier_user_id=None, search_query="", limit=60):
    safe_limit = max(1, min(_to_int(limit, 60), 200))
    params = [date_from, date_to]
    query = """
        SELECT
            ps.id,
            ps.purchase_id,
            ps.customer_id,
            ps.cashier_user_id,
            ps.warehouse_id,
            ps.sale_date,
            ps.receipt_no,
            ps.payment_method,
            ps.total_items,
            ps.total_amount,
            ps.paid_amount,
            ps.change_amount,
            ps.note,
            ps.created_at,
            COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
            COALESCE(NULLIF(TRIM(c.phone), ''), '-') AS customer_phone,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Tanpa Staff') AS cashier_name,
            COALESCE(NULLIF(TRIM(u.username), ''), '-') AS cashier_username,
            COALESCE(NULLIF(TRIM(e.position), ''), COALESCE(NULLIF(TRIM(u.role), ''), 'Staff')) AS cashier_position,
            COALESCE(NULLIF(TRIM(w.name), ''), '-') AS warehouse_name
        FROM pos_sales ps
        JOIN crm_customers c ON c.id = ps.customer_id
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses w ON w.id = ps.warehouse_id
        WHERE ps.sale_date BETWEEN ? AND ?
    """

    if selected_warehouse:
        query += " AND ps.warehouse_id=?"
        params.append(int(selected_warehouse))

    if cashier_user_id:
        query += " AND ps.cashier_user_id=?"
        params.append(int(cashier_user_id))

    safe_search_query = str(search_query or "").strip()
    if safe_search_query:
        search_pattern = f"%{safe_search_query}%"
        query += """
            AND (
                ps.receipt_no LIKE ?
                OR COALESCE(c.customer_name, '') LIKE ?
                OR COALESCE(c.phone, '') LIKE ?
                OR COALESCE(e.full_name, u.username, '') LIKE ?
                OR COALESCE(ps.note, '') LIKE ?
            )
        """
        params.extend([search_pattern] * 5)

    query += """
        ORDER BY ps.sale_date DESC, ps.id DESC
        LIMIT ?
    """
    params.append(safe_limit)

    header_rows = [dict(row) for row in db.execute(query, params).fetchall()]
    item_map = _fetch_pos_sale_item_map(db, [row["purchase_id"] for row in header_rows])
    normalized_rows = []

    for row in header_rows:
        items = item_map.get(int(row["purchase_id"]), [])
        total_amount = _currency(row.get("total_amount") or 0)
        paid_amount = _currency(row.get("paid_amount") or 0)
        change_amount = _currency(row.get("change_amount") or 0)
        payment_method = str(row.get("payment_method") or "cash").upper()
        created_time_label = _format_pos_time_label(row.get("created_at"))
        item_preview_lines = items[:3]

        normalized_rows.append(
            {
                **row,
                "total_items": int(row.get("total_items") or 0),
                "total_amount": total_amount,
                "paid_amount": paid_amount,
                "change_amount": change_amount,
                "total_amount_label": _format_pos_currency_label(total_amount),
                "paid_amount_label": _format_pos_currency_label(paid_amount),
                "change_amount_label": _format_pos_currency_label(change_amount),
                "payment_method_label": payment_method,
                "created_time_label": created_time_label,
                "created_datetime_label": f"{row['sale_date']} {created_time_label}" if created_time_label != "-" else row["sale_date"],
                "customer_phone_label": row["customer_phone"] if row.get("customer_phone") and row["customer_phone"] != "-" else "Tanpa nomor",
                "cashier_identity_label": f"{row['cashier_name']} · {row['cashier_position']}",
                "items": items,
                "item_preview_lines": item_preview_lines,
                "item_preview_more": max(len(items) - len(item_preview_lines), 0),
                "receipt_print_url": f"/kasir/receipt/{row['receipt_no']}/print",
                "receipt_pdf_url": f"/kasir/receipt/{row['receipt_no']}/print?autoprint=1",
            }
        )

    return normalized_rows


def _build_pos_sale_log_summary(rows, period_label):
    total_items = sum(int(row.get("total_items") or 0) for row in rows)
    total_revenue = sum(float(row.get("total_amount") or 0) for row in rows)
    customer_total = len({int(row.get("customer_id") or 0) for row in rows if _to_int(row.get("customer_id"), 0) > 0})
    staff_total = len({int(row.get("cashier_user_id") or 0) for row in rows if _to_int(row.get("cashier_user_id"), 0) > 0})
    return {
        "period_label": period_label,
        "transaction_total": len(rows),
        "total_items": total_items,
        "customer_total": customer_total,
        "staff_total": staff_total,
        "total_revenue": total_revenue,
        "total_revenue_label": _format_pos_currency_label(total_revenue),
        "average_ticket_label": _format_pos_currency_label(total_revenue / len(rows) if rows else 0),
    }


def _fetch_pos_sale_detail_by_receipt(db, receipt_no):
    safe_receipt = str(receipt_no or "").strip()
    if not safe_receipt:
        return None

    params = [safe_receipt]
    query = """
        SELECT
            ps.id,
            ps.purchase_id,
            ps.customer_id,
            ps.cashier_user_id,
            ps.warehouse_id,
            ps.sale_date,
            ps.receipt_no,
            ps.payment_method,
            ps.total_items,
            ps.total_amount,
            ps.paid_amount,
            ps.change_amount,
            ps.note,
            ps.created_at,
            COALESCE(NULLIF(TRIM(c.customer_name), ''), 'Walk-in Customer') AS customer_name,
            COALESCE(NULLIF(TRIM(c.phone), ''), '-') AS customer_phone,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Tanpa Staff') AS cashier_name,
            COALESCE(NULLIF(TRIM(u.username), ''), '-') AS cashier_username,
            COALESCE(NULLIF(TRIM(e.position), ''), COALESCE(NULLIF(TRIM(u.role), ''), 'Staff')) AS cashier_position,
            COALESCE(NULLIF(TRIM(w.name), ''), '-') AS warehouse_name
        FROM pos_sales ps
        JOIN crm_customers c ON c.id = ps.customer_id
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses w ON w.id = ps.warehouse_id
        WHERE ps.receipt_no=?
    """

    if is_scoped_role(session.get("role")):
        query += " AND ps.warehouse_id=?"
        params.append(session.get("warehouse_id"))

    query += " LIMIT 1"

    row = db.execute(query, params).fetchone()
    if not row:
        return None

    sale = dict(row)
    items = _fetch_pos_sale_item_map(db, [sale["purchase_id"]]).get(int(sale["purchase_id"]), [])
    total_amount = _currency(sale.get("total_amount") or 0)
    paid_amount = _currency(sale.get("paid_amount") or 0)
    change_amount = _currency(sale.get("change_amount") or 0)
    created_time_label = _format_pos_time_label(sale.get("created_at"))

    return {
        **sale,
        "items": items,
        "total_items": int(sale.get("total_items") or 0),
        "total_amount": total_amount,
        "paid_amount": paid_amount,
        "change_amount": change_amount,
        "total_amount_label": _format_pos_currency_label(total_amount),
        "paid_amount_label": _format_pos_currency_label(paid_amount),
        "change_amount_label": _format_pos_currency_label(change_amount),
        "payment_method_label": str(sale.get("payment_method") or "cash").upper(),
        "created_time_label": created_time_label,
        "created_datetime_label": f"{sale['sale_date']} {created_time_label}" if created_time_label != "-" else sale["sale_date"],
        "customer_phone_label": sale["customer_phone"] if sale.get("customer_phone") and sale["customer_phone"] != "-" else "Tanpa nomor",
        "cashier_identity_label": f"{sale['cashier_name']} · {sale['cashier_position']}",
    }


def _format_pos_currency_label(value):
    return f"Rp {int(round(float(value or 0))):,}".replace(",", ".")


def _format_pos_period_label(date_from, date_to):
    if not date_from:
        return "-"
    if date_from == date_to:
        return date_from
    return f"{date_from} s/d {date_to}"


def _format_pos_month_label(month_value):
    try:
        target = date_cls.fromisoformat(f"{month_value}-01")
    except ValueError:
        return month_value or "-"

    month_names = [
        "Januari",
        "Februari",
        "Maret",
        "April",
        "Mei",
        "Juni",
        "Juli",
        "Agustus",
        "September",
        "Oktober",
        "November",
        "Desember",
    ]
    return f"{month_names[target.month - 1]} {target.year}"


def _resolve_week_range(raw_reference_date):
    reference_date = date_cls.fromisoformat(_normalize_sale_date(raw_reference_date))
    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)
    return {
        "reference_date": reference_date.isoformat(),
        "date_from": week_start.isoformat(),
        "date_to": week_end.isoformat(),
        "label": _format_pos_period_label(week_start.isoformat(), week_end.isoformat()),
    }


def _resolve_month_range(raw_month_value):
    month_value = _normalize_sale_month(raw_month_value)
    month_start = date_cls.fromisoformat(f"{month_value}-01")
    if month_start.month == 12:
        next_month_start = date_cls(month_start.year + 1, 1, 1)
    else:
        next_month_start = date_cls(month_start.year, month_start.month + 1, 1)
    month_end = next_month_start - timedelta(days=1)
    return {
        "month_value": month_value,
        "date_from": month_start.isoformat(),
        "date_to": month_end.isoformat(),
        "label": _format_pos_month_label(month_value),
    }


def _fetch_pos_staff_sales_rows(db, date_from, date_to, selected_warehouse=None):
    params = [date_from, date_to]
    query = """
        SELECT
            ps.cashier_user_id,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Tanpa Staff') AS staff_name,
            COALESCE(NULLIF(TRIM(u.username), ''), '-') AS username,
            COALESCE(NULLIF(TRIM(e.position), ''), 'Staff') AS position,
            COALESCE(NULLIF(TRIM(home_w.name), ''), '-') AS home_warehouse_name,
            COUNT(ps.id) AS total_transactions,
            COALESCE(SUM(ps.total_items), 0) AS total_items,
            COALESCE(SUM(ps.total_amount), 0) AS total_revenue,
            COALESCE(AVG(ps.total_amount), 0) AS average_ticket,
            COUNT(DISTINCT ps.customer_id) AS total_customers,
            COUNT(DISTINCT ps.warehouse_id) AS total_warehouses,
            GROUP_CONCAT(DISTINCT sale_w.name) AS warehouse_names,
            MIN(ps.sale_date) AS first_sale_date,
            MAX(ps.sale_date) AS last_sale_date
        FROM pos_sales ps
        LEFT JOIN users u ON u.id = ps.cashier_user_id
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses home_w ON home_w.id = COALESCE(e.warehouse_id, u.warehouse_id)
        LEFT JOIN warehouses sale_w ON sale_w.id = ps.warehouse_id
        WHERE ps.sale_date BETWEEN ? AND ?
    """
    if selected_warehouse:
        query += " AND ps.warehouse_id=?"
        params.append(selected_warehouse)

    query += """
        GROUP BY
            ps.cashier_user_id,
            staff_name,
            username,
            position,
            home_warehouse_name
        ORDER BY total_revenue DESC, total_transactions DESC, staff_name COLLATE NOCASE ASC
    """

    rows = [dict(row) for row in db.execute(query, params).fetchall()]
    normalized_rows = []
    for index, row in enumerate(rows, start=1):
        total_revenue = _currency(row.get("total_revenue") or 0)
        average_ticket = _currency(row.get("average_ticket") or 0)
        warehouse_scope_label = (row.get("warehouse_names") or "").strip() or row.get("home_warehouse_name") or "-"
        normalized_rows.append(
            {
                **row,
                "rank": index,
                "total_transactions": int(row.get("total_transactions") or 0),
                "total_items": int(row.get("total_items") or 0),
                "total_customers": int(row.get("total_customers") or 0),
                "total_warehouses": int(row.get("total_warehouses") or 0),
                "total_revenue": total_revenue,
                "average_ticket": average_ticket,
                "total_revenue_label": _format_pos_currency_label(total_revenue),
                "average_ticket_label": _format_pos_currency_label(average_ticket),
                "warehouse_scope_label": warehouse_scope_label,
                "activity_label": _format_pos_period_label(row.get("first_sale_date"), row.get("last_sale_date")),
            }
        )
    return normalized_rows


def _build_pos_staff_sales_summary(rows, period_label):
    total_transactions = sum(int(row.get("total_transactions") or 0) for row in rows)
    total_items = sum(int(row.get("total_items") or 0) for row in rows)
    total_revenue = sum(float(row.get("total_revenue") or 0) for row in rows)
    top_staff = rows[0] if rows else None
    return {
        "period_label": period_label,
        "staff_total": len(rows),
        "total_transactions": total_transactions,
        "total_items": total_items,
        "total_revenue": total_revenue,
        "total_revenue_label": _format_pos_currency_label(total_revenue),
        "average_ticket_label": _format_pos_currency_label(total_revenue / total_transactions if total_transactions else 0),
        "top_staff_name": top_staff["staff_name"] if top_staff else "-",
        "top_staff_revenue_label": top_staff["total_revenue_label"] if top_staff else _format_pos_currency_label(0),
    }


def _build_next_receipt_no(db, sale_date):
    date_key = sale_date.replace("-", "")
    prefix = f"POS-{date_key}-"
    latest = db.execute(
        """
        SELECT receipt_no
        FROM pos_sales
        WHERE receipt_no LIKE ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (f"{prefix}%",),
    ).fetchone()

    if not latest or not latest["receipt_no"]:
        return f"{prefix}0001"

    tail = str(latest["receipt_no"]).replace(prefix, "", 1)
    next_seq = _to_int(tail, 0) + 1
    return f"{prefix}{str(next_seq).zfill(4)}"


def _resolve_or_create_customer(db, warehouse_id, customer_id, customer_name, customer_phone):
    if customer_id > 0:
        customer = db.execute(
            """
            SELECT id, warehouse_id, customer_name, phone
            FROM crm_customers
            WHERE id=?
            """,
            (customer_id,),
        ).fetchone()
        if not customer or int(customer["warehouse_id"] or 0) != int(warehouse_id):
            raise ValueError("Customer tidak valid untuk gudang aktif.")
        return customer

    safe_name = (customer_name or "").strip() or "Walk-in Customer"
    safe_phone = (customer_phone or "").strip()

    existing = db.execute(
        """
        SELECT id, warehouse_id, customer_name, phone
        FROM crm_customers
        WHERE warehouse_id=?
          AND customer_name=?
          AND COALESCE(phone, '')=?
        LIMIT 1
        """,
        (warehouse_id, safe_name, safe_phone),
    ).fetchone()
    if existing:
        return existing

    cursor = db.execute(
        """
        INSERT INTO crm_customers(
            warehouse_id,
            customer_name,
            contact_person,
            phone,
            customer_type,
            marketing_channel,
            note
        )
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            warehouse_id,
            safe_name,
            safe_name if safe_name.lower() != "walk-in customer" else None,
            safe_phone or None,
            "retail",
            "pos",
            "Auto-created by POS checkout",
        ),
    )
    created = db.execute(
        """
        SELECT id, warehouse_id, customer_name, phone
        FROM crm_customers
        WHERE id=?
        """,
        (cursor.lastrowid,),
    ).fetchone()
    return created


def _validate_and_build_items(db, warehouse_id, raw_items):
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("Keranjang kasir masih kosong.")

    prepared = []

    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue

        product_id = _to_int(raw_item.get("product_id"), 0)
        variant_id = _to_int(raw_item.get("variant_id"), 0)
        qty = _to_int(raw_item.get("qty"), 0)
        unit_price = _to_decimal(raw_item.get("unit_price"), "0")

        if product_id <= 0 or variant_id <= 0 or qty <= 0:
            raise ValueError("Item kasir tidak valid. Periksa produk, variant, dan qty.")

        product = db.execute(
            """
            SELECT
                p.id AS product_id,
                p.sku,
                p.name AS product_name,
                v.id AS variant_id,
                COALESCE(v.variant, 'default') AS variant_name,
                COALESCE(v.price_nett, 0) AS price_nett,
                COALESCE(v.price_discount, 0) AS price_discount,
                COALESCE(v.price_retail, 0) AS price_retail,
                COALESCE(s.qty, 0) AS stock_qty
            FROM products p
            JOIN product_variants v
                ON v.id = ?
               AND v.product_id = p.id
            LEFT JOIN stock s
                ON s.product_id = p.id
               AND s.variant_id = v.id
               AND s.warehouse_id = ?
            WHERE p.id = ?
            LIMIT 1
            """,
            (variant_id, warehouse_id, product_id),
        ).fetchone()

        if not product:
            raise ValueError("Produk atau variant tidak ditemukan.")

        available_qty = int(product["stock_qty"] or 0)
        if available_qty < qty:
            label_variant = product["variant_name"] or "default"
            raise ValueError(
                f"Stok tidak cukup untuk {product['sku']} / {label_variant}. Tersedia {available_qty}, diminta {qty}."
            )

        if unit_price <= 0:
            unit_price = _to_decimal(
                product["price_nett"] or product["price_discount"] or product["price_retail"] or 0,
                "0",
            )
            if unit_price <= 0:
                raise ValueError(f"Harga jual untuk {product['sku']} belum diatur.")

        line_total = (unit_price * Decimal(qty)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        prepared.append(
            {
                "product_id": int(product["product_id"]),
                "variant_id": int(product["variant_id"]),
                "sku": product["sku"],
                "product_name": product["product_name"],
                "variant_name": product["variant_name"] or "default",
                "qty": qty,
                "unit_price": unit_price,
                "line_total": line_total,
            }
        )

    if not prepared:
        raise ValueError("Keranjang kasir masih kosong.")

    return prepared


@pos_bp.route("/")
def pos_page():
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    selected_warehouse = _resolve_pos_warehouse(db, request.args.get("warehouse"))
    sale_date = _normalize_sale_date(request.args.get("sale_date"))
    scoped_warehouse = session.get("warehouse_id") if is_scoped_role(session.get("role")) else None

    warehouses = db.execute(
        "SELECT id, name FROM warehouses ORDER BY name"
    ).fetchall()
    selected_warehouse_name = next(
        (
            warehouse["name"]
            for warehouse in warehouses
            if int(warehouse["id"] or 0) == int(selected_warehouse)
        ),
        f"WH {selected_warehouse}",
    )
    pos_staff_options = _fetch_pos_staff_options(db, selected_warehouse)
    selected_pos_staff_option = next(
        (option for option in pos_staff_options if option["id"] == _to_int(session.get("user_id"), 0)),
        pos_staff_options[0] if pos_staff_options else None,
    )

    if selected_pos_staff_option is None:
        selected_pos_staff_option = {
            "id": _to_int(session.get("user_id"), 0),
            "username": session.get("username", "-"),
            "display_name": session.get("username", "-"),
            "label": session.get("username", "-"),
            "role": session.get("role"),
            "warehouse_id": selected_warehouse,
        }
        pos_staff_options = [selected_pos_staff_option]

    sales_log_rows = _fetch_pos_sale_logs(
        db,
        sale_date,
        sale_date,
        selected_warehouse=selected_warehouse,
        limit=24,
    )

    return render_template(
        "pos.html",
        payment_methods=PAYMENT_METHODS,
        warehouses=warehouses,
        selected_warehouse=selected_warehouse,
        selected_warehouse_name=selected_warehouse_name,
        scoped_warehouse=scoped_warehouse,
        sale_date=sale_date,
        catalog_categories=_fetch_pos_categories(db, selected_warehouse),
        customer_options=_fetch_pos_customers(db, selected_warehouse),
        pos_staff_options=pos_staff_options,
        selected_pos_staff_id=selected_pos_staff_option["id"],
        selected_pos_staff_label=selected_pos_staff_option["display_name"],
        summary=_fetch_pos_summary(db, selected_warehouse, sale_date),
        recent_sales=_fetch_recent_sales(db, selected_warehouse, sale_date),
        sales_log_rows=sales_log_rows,
        sales_log_summary=_build_pos_sale_log_summary(sales_log_rows, sale_date),
    )


@pos_bp.get("/staff-sales")
def pos_staff_sales_report():
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    warehouses = db.execute("SELECT id, name FROM warehouses ORDER BY name").fetchall()
    scoped_warehouse = session.get("warehouse_id") if is_scoped_role(session.get("role")) else None
    selected_warehouse = _resolve_pos_report_warehouse(db, request.args.get("warehouse"))
    week_period = _resolve_week_range(request.args.get("week_date"))
    month_period = _resolve_month_range(request.args.get("month"))

    selected_warehouse_name = next(
        (
            warehouse["name"]
            for warehouse in warehouses
            if selected_warehouse and int(warehouse["id"] or 0) == int(selected_warehouse)
        ),
        "Semua Gudang" if not selected_warehouse else f"WH {selected_warehouse}",
    )

    weekly_rows = _fetch_pos_staff_sales_rows(
        db,
        week_period["date_from"],
        week_period["date_to"],
        selected_warehouse=selected_warehouse,
    )
    monthly_rows = _fetch_pos_staff_sales_rows(
        db,
        month_period["date_from"],
        month_period["date_to"],
        selected_warehouse=selected_warehouse,
    )

    return render_template(
        "pos_staff_sales_report.html",
        warehouses=warehouses,
        scoped_warehouse=scoped_warehouse,
        selected_warehouse=selected_warehouse,
        selected_warehouse_name=selected_warehouse_name,
        week_period=week_period,
        month_period=month_period,
        weekly_rows=weekly_rows,
        monthly_rows=monthly_rows,
        weekly_summary=_build_pos_staff_sales_summary(weekly_rows, week_period["label"]),
        monthly_summary=_build_pos_staff_sales_summary(monthly_rows, month_period["label"]),
    )


@pos_bp.get("/log")
def pos_sales_log_page():
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    warehouses = db.execute("SELECT id, name FROM warehouses ORDER BY name").fetchall()
    scoped_warehouse = session.get("warehouse_id") if is_scoped_role(session.get("role")) else None
    selected_warehouse = _resolve_pos_report_warehouse(db, request.args.get("warehouse"))
    date_range = _normalize_pos_log_date_range(request.args.get("date_from"), request.args.get("date_to"))
    cashier_filter_id = _to_int(request.args.get("cashier_user_id"), 0)
    selected_cashier_user_id = cashier_filter_id if cashier_filter_id > 0 else None
    cashier_filter_options = _fetch_pos_staff_options(db, selected_warehouse)

    selected_warehouse_name = next(
        (
            warehouse["name"]
            for warehouse in warehouses
            if selected_warehouse and int(warehouse["id"] or 0) == int(selected_warehouse)
        ),
        "Semua Gudang" if not selected_warehouse else f"WH {selected_warehouse}",
    )

    sales_log_rows = _fetch_pos_sale_logs(
        db,
        date_range["date_from"],
        date_range["date_to"],
        selected_warehouse=selected_warehouse,
        cashier_user_id=selected_cashier_user_id,
        search_query=request.args.get("search"),
        limit=120,
    )

    return render_template(
        "pos_sales_log.html",
        warehouses=warehouses,
        scoped_warehouse=scoped_warehouse,
        selected_warehouse=selected_warehouse,
        selected_warehouse_name=selected_warehouse_name,
        cashier_filter_options=cashier_filter_options,
        selected_cashier_user_id=selected_cashier_user_id,
        search_query=str(request.args.get("search") or "").strip(),
        date_range=date_range,
        sales_log_rows=sales_log_rows,
        sales_log_summary=_build_pos_sale_log_summary(sales_log_rows, date_range["label"]),
    )


@pos_bp.get("/receipt/<receipt_no>/print")
def pos_receipt_print(receipt_no):
    denied = _require_pos_access()
    if denied:
        return denied

    db = get_db()
    sale = _fetch_pos_sale_detail_by_receipt(db, receipt_no)
    if sale is None:
        flash("Nota penjualan tidak ditemukan atau tidak bisa diakses.", "error")
        return redirect("/kasir/log")

    return render_template(
        "pos_receipt_print.html",
        sale=sale,
        auto_print=request.args.get("autoprint") == "1",
    )


@pos_bp.post("/checkout")
def pos_checkout():
    denied = _require_pos_access(json_mode=True)
    if denied:
        return denied

    if not has_permission(session.get("role"), "manage_pos"):
        return _json_error("Role ini belum punya izin melakukan checkout kasir.", 403)

    payload = request.get_json(silent=True) or {}
    db = get_db()

    warehouse_id = _resolve_pos_warehouse(db, payload.get("warehouse_id"))
    sale_date = _normalize_sale_date(payload.get("sale_date"))
    payment_method = _normalize_payment_method(payload.get("payment_method"))
    note = (payload.get("note") or "").strip() or None
    customer_id = _to_int(payload.get("customer_id"), 0)
    customer_name = (payload.get("customer_name") or "").strip()
    customer_phone = (payload.get("customer_phone") or "").strip()
    try:
        selected_cashier = _resolve_pos_cashier_option(db, warehouse_id, payload.get("cashier_user_id"))
    except ValueError as exc:
        return _json_error(str(exc), 400)

    try:
        items = _validate_and_build_items(db, warehouse_id, payload.get("items"))
    except ValueError as exc:
        return _json_error(str(exc), 400)

    total_items = sum(int(item["qty"]) for item in items)
    total_amount = sum(item["line_total"] for item in items)

    paid_amount = _to_decimal(payload.get("paid_amount"), str(total_amount))
    if paid_amount < total_amount:
        return _json_error("Nominal bayar kurang dari total transaksi.", 400)

    change_amount = (paid_amount - total_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    member_id = None
    receipt_no = (payload.get("receipt_no") or "").strip()

    try:
        db.execute("BEGIN")
        customer = _resolve_or_create_customer(
            db,
            warehouse_id,
            customer_id,
            customer_name,
            customer_phone,
        )

        active_member = db.execute(
            """
            SELECT id
            FROM crm_memberships
            WHERE customer_id=? AND status='active'
            ORDER BY id DESC
            LIMIT 1
            """,
            (customer["id"],),
        ).fetchone()
        if active_member:
            member_id = active_member["id"]

        if not receipt_no:
            receipt_no = _build_next_receipt_no(db, sale_date)

        duplicate_receipt = db.execute(
            "SELECT id FROM pos_sales WHERE receipt_no=? LIMIT 1",
            (receipt_no,),
        ).fetchone()
        if duplicate_receipt:
            receipt_no = _build_next_receipt_no(db, sale_date)

        purchase_cursor = db.execute(
            """
            INSERT INTO crm_purchase_records(
                customer_id,
                member_id,
                warehouse_id,
                purchase_date,
                invoice_no,
                channel,
                items_count,
                total_amount,
                note,
                handled_by
            )
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                customer["id"],
                member_id,
                warehouse_id,
                sale_date,
                receipt_no,
                "pos",
                total_items,
                _currency(total_amount),
                note,
                session.get("user_id"),
            ),
        )
        purchase_id = purchase_cursor.lastrowid

        db.executemany(
            """
            INSERT INTO crm_purchase_items(
                purchase_id,
                product_id,
                variant_id,
                qty,
                unit_price,
                line_total,
                note
            )
            VALUES (?,?,?,?,?,?,?)
            """,
            [
                (
                    purchase_id,
                    item["product_id"],
                    item["variant_id"],
                    item["qty"],
                    _currency(item["unit_price"]),
                    _currency(item["line_total"]),
                    "POS Checkout",
                )
                for item in items
            ],
        )

        if member_id:
            db.execute(
                """
                INSERT INTO crm_member_records(
                    member_id,
                    purchase_id,
                    warehouse_id,
                    record_date,
                    record_type,
                    reference_no,
                    amount,
                    points_delta,
                    note,
                    handled_by
                )
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    member_id,
                    purchase_id,
                    warehouse_id,
                    sale_date,
                    "purchase",
                    receipt_no,
                    _currency(total_amount),
                    0,
                    "Auto-generated dari POS checkout",
                    session.get("user_id"),
                ),
            )

        pos_cursor = db.execute(
            """
            INSERT INTO pos_sales(
                purchase_id,
                customer_id,
                warehouse_id,
                cashier_user_id,
                sale_date,
                receipt_no,
                payment_method,
                total_items,
                total_amount,
                paid_amount,
                change_amount,
                note
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                purchase_id,
                customer["id"],
                warehouse_id,
                selected_cashier["id"],
                sale_date,
                receipt_no,
                payment_method,
                total_items,
                _currency(total_amount),
                _currency(paid_amount),
                _currency(change_amount),
                note,
            ),
        )
        sale_id = pos_cursor.lastrowid

        for item in items:
            removed = remove_stock(
                item["product_id"],
                item["variant_id"],
                warehouse_id,
                item["qty"],
                note=f"POS {receipt_no}",
            )
            if not removed:
                raise ValueError(
                    f"Gagal memotong stok {item['sku']} / {item['variant_name']}. Silakan refresh data stok."
                )

        db.commit()

    except ValueError as exc:
        db.rollback()
        return _json_error(str(exc), 400)
    except Exception:
        db.rollback()
        return _json_error("Checkout kasir gagal disimpan. Coba ulangi beberapa detik lagi.", 500)

    try:
        notify_operational_event(
            f"Transaksi POS {receipt_no}",
            (
                f"{customer['customer_name']} | {total_items} item | "
                f"Total Rp {int(_currency(total_amount)):,}".replace(",", ".")
            ),
            warehouse_id=warehouse_id,
            category="inventory",
            link_url="/kasir/",
            source_type="pos_sale",
            source_id=sale_id,
            push_title="Checkout POS berhasil",
            push_body=f"{receipt_no} | {total_items} item",
        )
    except Exception as exc:
        print("POS NOTIFICATION ERROR:", exc)

    return jsonify(
        {
            "status": "success",
            "message": "Checkout kasir berhasil disimpan.",
            "sale_id": sale_id,
            "receipt_no": receipt_no,
            "purchase_id": purchase_id,
            "customer_name": customer["customer_name"],
            "total_items": total_items,
            "total_amount": _currency(total_amount),
            "paid_amount": _currency(paid_amount),
            "change_amount": _currency(change_amount),
            "receipt_print_url": f"/kasir/receipt/{receipt_no}/print?autoprint=1",
        }
    )
