import json
from datetime import date as date_cls

from flask import Blueprint, flash, redirect, render_template, request, session

from database import get_db
from services.rbac import has_permission, is_scoped_role


crm_bp = Blueprint("crm", __name__, url_prefix="/crm")

CUSTOMER_TYPES = {"retail", "member", "reseller", "vip", "wholesale"}
PURCHASE_CHANNELS = {"store", "whatsapp", "marketplace", "live", "event", "other"}
MEMBERSHIP_TIERS = {"regular", "silver", "gold", "platinum", "vip"}
MEMBERSHIP_STATUSES = {"active", "inactive", "expired"}
MEMBER_RECORD_TYPES = {"join", "purchase", "renewal", "tier_update", "point_adjustment", "note"}
CRM_TABS = {"contacts", "purchases", "members"}


def _to_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _normalize_tab(value):
    tab = (value or "").strip().lower()
    return tab if tab in CRM_TABS else "contacts"


def _normalize_customer_type(value):
    customer_type = (value or "").strip().lower()
    return customer_type if customer_type in CUSTOMER_TYPES else "retail"


def _normalize_purchase_channel(value):
    channel = (value or "").strip().lower()
    return channel if channel in PURCHASE_CHANNELS else "store"


def _normalize_member_tier(value):
    tier = (value or "").strip().lower()
    return tier if tier in MEMBERSHIP_TIERS else "regular"


def _normalize_member_status(value):
    status = (value or "").strip().lower()
    return status if status in MEMBERSHIP_STATUSES else "active"


def _normalize_member_record_type(value):
    record_type = (value or "").strip().lower()
    return record_type if record_type in MEMBER_RECORD_TYPES else "note"


def _normalize_date(value):
    raw_value = (value or "").strip()
    if not raw_value:
        return None
    try:
        return date_cls.fromisoformat(raw_value).isoformat()
    except ValueError:
        return None


def _crm_scope_warehouse():
    if is_scoped_role(session.get("role")):
        return session.get("warehouse_id")
    return None


def _resolve_crm_warehouse(db, raw_warehouse_id, allow_empty=False):
    default_warehouse = db.execute(
        "SELECT id FROM warehouses ORDER BY id LIMIT 1"
    ).fetchone()
    default_id = default_warehouse["id"] if default_warehouse else 1

    scope_warehouse = _crm_scope_warehouse()
    if scope_warehouse:
        return scope_warehouse

    warehouse_id = _to_int(raw_warehouse_id, None)
    if warehouse_id is None:
        return None if allow_empty else default_id

    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    return warehouse["id"] if warehouse else (None if allow_empty else default_id)


def _crm_redirect(tab=None):
    selected_tab = _normalize_tab(tab or request.form.get("tab") or request.args.get("tab"))
    return redirect(f"/crm/?tab={selected_tab}")


def _crm_access_denied_redirect():
    if has_permission(session.get("role"), "view_schedule"):
        return redirect("/schedule/")
    return redirect("/")


def _require_crm_view():
    if has_permission(session.get("role"), "view_crm"):
        return True
    flash("Tidak punya akses ke CRM", "error")
    return False


def _require_crm_manage():
    if has_permission(session.get("role"), "manage_crm"):
        return True
    flash("Tidak punya akses untuk mengelola CRM", "error")
    return False


def _build_scope_clause(alias):
    scope_warehouse = _crm_scope_warehouse()
    if not scope_warehouse:
        return "", []
    return f" AND {alias}.warehouse_id=?", [scope_warehouse]


def _parse_purchase_items(form):
    raw_payload = (form.get("items_json") or "").strip()
    if not raw_payload:
        raise ValueError("Minimal tambah satu item pembelian.")

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValueError("Format item pembelian tidak valid.") from exc

    if not isinstance(payload, list):
        raise ValueError("Format item pembelian tidak valid.")

    items = []
    for item in payload:
        if not isinstance(item, dict):
            continue

        product_id = _to_int(item.get("product_id"), 0)
        variant_id = _to_int(item.get("variant_id"), 0)
        qty = _to_int(item.get("qty"), 0)
        unit_price = round(_to_float(item.get("unit_price"), 0), 2)
        display_name = (item.get("display_name") or "").strip()

        if not any([product_id, variant_id, qty, unit_price, display_name]):
            continue

        if product_id <= 0 or variant_id <= 0 or qty <= 0:
            raise ValueError("Ada baris pembelian yang belum lengkap atau qty tidak valid.")

        if unit_price < 0:
            raise ValueError("Harga jual tidak boleh negatif.")

        items.append(
            {
                "product_id": product_id,
                "variant_id": variant_id,
                "qty": qty,
                "unit_price": unit_price,
                "line_total": round(qty * unit_price, 2),
                "display_name": display_name,
            }
        )

    if not items:
        raise ValueError("Minimal tambah satu item pembelian.")

    return items


def _get_customer_by_id(db, customer_id):
    scope_clause, params = _build_scope_clause("c")
    return db.execute(
        f"""
        SELECT c.*, w.name AS warehouse_name
        FROM crm_customers c
        LEFT JOIN warehouses w ON w.id = c.warehouse_id
        WHERE c.id=? {scope_clause}
        """,
        [customer_id, *params],
    ).fetchone()


def _get_member_by_id(db, member_id):
    scope_clause, params = _build_scope_clause("m")
    return db.execute(
        f"""
        SELECT
            m.*,
            c.customer_name,
            c.contact_person,
            w.name AS warehouse_name
        FROM crm_memberships m
        JOIN crm_customers c ON c.id = m.customer_id
        LEFT JOIN warehouses w ON w.id = m.warehouse_id
        WHERE m.id=? {scope_clause}
        """,
        [member_id, *params],
    ).fetchone()


def _get_purchase_by_id(db, purchase_id):
    scope_clause, params = _build_scope_clause("pr")
    return db.execute(
        f"""
        SELECT
            pr.*,
            c.customer_name,
            m.member_code,
            w.name AS warehouse_name
        FROM crm_purchase_records pr
        JOIN crm_customers c ON c.id = pr.customer_id
        LEFT JOIN crm_memberships m ON m.id = pr.member_id
        LEFT JOIN warehouses w ON w.id = pr.warehouse_id
        WHERE pr.id=? {scope_clause}
        """,
        [purchase_id, *params],
    ).fetchone()


def _get_member_record_by_id(db, record_id):
    scope_clause, params = _build_scope_clause("mr")
    return db.execute(
        f"""
        SELECT
            mr.*,
            m.member_code,
            c.customer_name
        FROM crm_member_records mr
        JOIN crm_memberships m ON m.id = mr.member_id
        JOIN crm_customers c ON c.id = m.customer_id
        WHERE mr.id=? {scope_clause}
        """,
        [record_id, *params],
    ).fetchone()


def _fetch_customer_options(db, selected_warehouse=None):
    params = []
    query = """
        SELECT c.id, c.customer_name, c.contact_person, c.warehouse_id, w.name AS warehouse_name
        FROM crm_customers c
        LEFT JOIN warehouses w ON w.id = c.warehouse_id
        WHERE 1=1
    """

    scope_clause, scope_params = _build_scope_clause("c")
    query += scope_clause
    params.extend(scope_params)

    if selected_warehouse:
        query += " AND c.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY c.customer_name ASC, c.id DESC"
    return [dict(row) for row in db.execute(query, params).fetchall()]


def _fetch_member_options(db, selected_warehouse=None):
    params = []
    query = """
        SELECT
            m.id,
            m.member_code,
            m.status,
            c.id AS customer_id,
            c.customer_name,
            m.warehouse_id,
            w.name AS warehouse_name
        FROM crm_memberships m
        JOIN crm_customers c ON c.id = m.customer_id
        LEFT JOIN warehouses w ON w.id = m.warehouse_id
        WHERE 1=1
    """

    scope_clause, scope_params = _build_scope_clause("m")
    query += scope_clause
    params.extend(scope_params)

    if selected_warehouse:
        query += " AND m.warehouse_id=?"
        params.append(selected_warehouse)

    query += " ORDER BY m.status='active' DESC, c.customer_name ASC, m.id DESC"
    return [dict(row) for row in db.execute(query, params).fetchall()]


def _fetch_customers(db, search="", selected_warehouse=None):
    params = []
    query = """
        SELECT
            c.*,
            w.name AS warehouse_name,
            COALESCE(p.purchase_count, 0) AS purchase_count,
            COALESCE(p.total_spent, 0) AS total_spent,
            p.last_purchase_date,
            COALESCE(mp.products_summary, '-') AS products_summary,
            m.member_code,
            COALESCE(m.status, 'non_member') AS membership_status
        FROM crm_customers c
        LEFT JOIN warehouses w ON w.id = c.warehouse_id
        LEFT JOIN (
            SELECT
                customer_id,
                COUNT(*) AS purchase_count,
                SUM(total_amount) AS total_spent,
                MAX(purchase_date) AS last_purchase_date
            FROM crm_purchase_records
            GROUP BY customer_id
        ) p ON p.customer_id = c.id
        LEFT JOIN (
            SELECT
                pr.customer_id,
                GROUP_CONCAT(
                    DISTINCT p.name || CASE
                        WHEN LOWER(COALESCE(v.variant, 'default')) = 'default' THEN ''
                        ELSE ' / ' || v.variant
                    END
                ) AS products_summary
            FROM crm_purchase_records pr
            JOIN crm_purchase_items pi ON pi.purchase_id = pr.id
            JOIN products p ON p.id = pi.product_id
            JOIN product_variants v ON v.id = pi.variant_id
            GROUP BY pr.customer_id
        ) mp ON mp.customer_id = c.id
        LEFT JOIN crm_memberships m ON m.customer_id = c.id
        WHERE 1=1
    """

    scope_clause, scope_params = _build_scope_clause("c")
    query += scope_clause
    params.extend(scope_params)

    if selected_warehouse:
        query += " AND c.warehouse_id=?"
        params.append(selected_warehouse)

    if search:
        like = f"%{search}%"
        query += """
            AND (
                c.customer_name LIKE ?
                OR COALESCE(c.contact_person, '') LIKE ?
                OR COALESCE(c.phone, '') LIKE ?
                OR COALESCE(c.email, '') LIKE ?
                OR COALESCE(c.instagram_handle, '') LIKE ?
                OR COALESCE(m.member_code, '') LIKE ?
            )
        """
        params.extend([like, like, like, like, like, like])

    query += " ORDER BY p.last_purchase_date DESC, c.customer_name ASC, c.id DESC"
    return [dict(row) for row in db.execute(query, params).fetchall()]


def _fetch_purchase_records(db, search="", selected_warehouse=None):
    params = []
    query = """
        SELECT
            pr.*,
            c.customer_name,
            c.contact_person,
            m.member_code,
            w.name AS warehouse_name,
            u.username AS handled_by_name,
            COALESCE(pi.total_qty, 0) AS total_qty,
            COALESCE(pi.items_summary, '-') AS items_summary
        FROM crm_purchase_records pr
        JOIN crm_customers c ON c.id = pr.customer_id
        LEFT JOIN crm_memberships m ON m.id = pr.member_id
        LEFT JOIN warehouses w ON w.id = pr.warehouse_id
        LEFT JOIN users u ON u.id = pr.handled_by
        LEFT JOIN (
            SELECT
                pi.purchase_id,
                SUM(pi.qty) AS total_qty,
                GROUP_CONCAT(
                    p.sku || ' - ' || p.name || CASE
                        WHEN LOWER(COALESCE(v.variant, 'default')) = 'default' THEN ''
                        ELSE ' / ' || v.variant
                    END || ' x' || pi.qty,
                    ' | '
                ) AS items_summary
            FROM crm_purchase_items pi
            JOIN products p ON p.id = pi.product_id
            JOIN product_variants v ON v.id = pi.variant_id
            GROUP BY pi.purchase_id
        ) pi ON pi.purchase_id = pr.id
        WHERE 1=1
    """

    scope_clause, scope_params = _build_scope_clause("pr")
    query += scope_clause
    params.extend(scope_params)

    if selected_warehouse:
        query += " AND pr.warehouse_id=?"
        params.append(selected_warehouse)

    if search:
        like = f"%{search}%"
        query += """
            AND (
                c.customer_name LIKE ?
                OR COALESCE(pr.invoice_no, '') LIKE ?
                OR COALESCE(pr.channel, '') LIKE ?
                OR COALESCE(pr.note, '') LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM crm_purchase_items spi
                    JOIN products sp ON sp.id = spi.product_id
                    LEFT JOIN product_variants sv ON sv.id = spi.variant_id
                    WHERE spi.purchase_id = pr.id
                      AND (
                          sp.sku LIKE ?
                          OR sp.name LIKE ?
                          OR COALESCE(sv.variant, '') LIKE ?
                      )
                )
            )
        """
        params.extend([like, like, like, like, like, like, like])

    query += " ORDER BY pr.purchase_date DESC, pr.id DESC"
    return [dict(row) for row in db.execute(query, params).fetchall()]


def _fetch_memberships(db, search="", selected_warehouse=None, member_status=""):
    params = []
    query = """
        SELECT
            m.*,
            c.customer_name,
            c.contact_person,
            c.phone,
            w.name AS warehouse_name,
            COALESCE(stats.record_count, 0) AS record_count,
            stats.last_record_date,
            COALESCE(stats.total_member_spend, 0) AS total_member_spend
        FROM crm_memberships m
        JOIN crm_customers c ON c.id = m.customer_id
        LEFT JOIN warehouses w ON w.id = m.warehouse_id
        LEFT JOIN (
            SELECT
                m.id AS member_id,
                COUNT(DISTINCT mr.id) AS record_count,
                MAX(mr.record_date) AS last_record_date,
                SUM(COALESCE(pr.total_amount, 0)) AS total_member_spend
            FROM crm_memberships m
            LEFT JOIN crm_member_records mr ON mr.member_id = m.id
            LEFT JOIN crm_purchase_records pr ON pr.member_id = m.id
            GROUP BY m.id
        ) stats ON stats.member_id = m.id
        WHERE 1=1
    """

    scope_clause, scope_params = _build_scope_clause("m")
    query += scope_clause
    params.extend(scope_params)

    if selected_warehouse:
        query += " AND m.warehouse_id=?"
        params.append(selected_warehouse)

    if member_status in MEMBERSHIP_STATUSES:
        query += " AND m.status=?"
        params.append(member_status)

    if search:
        like = f"%{search}%"
        query += """
            AND (
                m.member_code LIKE ?
                OR c.customer_name LIKE ?
                OR COALESCE(c.contact_person, '') LIKE ?
                OR COALESCE(c.phone, '') LIKE ?
                OR COALESCE(m.note, '') LIKE ?
            )
        """
        params.extend([like, like, like, like, like])

    query += " ORDER BY m.join_date DESC, m.id DESC"
    return [dict(row) for row in db.execute(query, params).fetchall()]


def _fetch_member_records(db, search="", selected_warehouse=None):
    params = []
    query = """
        SELECT
            mr.*,
            m.member_code,
            c.customer_name,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM crm_member_records mr
        JOIN crm_memberships m ON m.id = mr.member_id
        JOIN crm_customers c ON c.id = m.customer_id
        LEFT JOIN warehouses w ON w.id = mr.warehouse_id
        LEFT JOIN users u ON u.id = mr.handled_by
        WHERE 1=1
    """

    scope_clause, scope_params = _build_scope_clause("mr")
    query += scope_clause
    params.extend(scope_params)

    if selected_warehouse:
        query += " AND mr.warehouse_id=?"
        params.append(selected_warehouse)

    if search:
        like = f"%{search}%"
        query += """
            AND (
                m.member_code LIKE ?
                OR c.customer_name LIKE ?
                OR COALESCE(mr.reference_no, '') LIKE ?
                OR COALESCE(mr.note, '') LIKE ?
            )
        """
        params.extend([like, like, like, like])

    query += " ORDER BY mr.record_date DESC, mr.id DESC LIMIT 120"
    return [dict(row) for row in db.execute(query, params).fetchall()]


def _build_crm_summary(customers, purchases, memberships, member_records):
    return {
        "customers": len(customers),
        "customers_with_purchase": sum(1 for customer in customers if customer["purchase_count"]),
        "active_members": sum(1 for member in memberships if member["status"] == "active"),
        "total_revenue": round(sum(purchase["total_amount"] or 0 for purchase in purchases), 2),
        "contact_ready": sum(1 for customer in customers if customer.get("phone") or customer.get("email")),
        "member_records": len(member_records),
        "latest_purchase": purchases[0]["purchase_date"] if purchases else "-",
    }


@crm_bp.route("/")
def crm_page():
    if not _require_crm_view():
        return _crm_access_denied_redirect()

    db = get_db()
    selected_tab = _normalize_tab(request.args.get("tab"))
    search = (request.args.get("search") or "").strip()
    member_status = (request.args.get("member_status") or "").strip().lower()
    if member_status not in MEMBERSHIP_STATUSES:
        member_status = ""

    selected_warehouse = _resolve_crm_warehouse(
        db,
        request.args.get("warehouse"),
        allow_empty=not is_scoped_role(session.get("role")),
    )

    warehouses = db.execute("SELECT id, name FROM warehouses ORDER BY name").fetchall()
    customers = _fetch_customers(db, search, selected_warehouse)
    purchases = _fetch_purchase_records(db, search, selected_warehouse)
    memberships = _fetch_memberships(db, search, selected_warehouse, member_status)
    member_records = _fetch_member_records(db, search, selected_warehouse)
    customer_options = _fetch_customer_options(db, selected_warehouse)
    member_options = _fetch_member_options(db, selected_warehouse)
    summary = _build_crm_summary(customers, purchases, memberships, member_records)

    return render_template(
        "crm.html",
        selected_tab=selected_tab,
        search=search,
        selected_warehouse=selected_warehouse,
        member_status=member_status,
        warehouses=warehouses,
        customers=customers,
        purchases=purchases,
        memberships=memberships,
        member_records=member_records,
        customer_options=customer_options,
        member_options=member_options,
        summary=summary,
        customer_types=sorted(CUSTOMER_TYPES),
        purchase_channels=sorted(PURCHASE_CHANNELS),
        membership_tiers=sorted(MEMBERSHIP_TIERS),
        membership_statuses=sorted(MEMBERSHIP_STATUSES),
        member_record_types=sorted(MEMBER_RECORD_TYPES),
        scoped_crm_warehouse=_crm_scope_warehouse(),
        can_manage_crm=has_permission(session.get("role"), "manage_crm"),
    )


@crm_bp.route("/customers/add", methods=["POST"])
def add_customer():
    if not _require_crm_manage():
        return _crm_redirect("contacts")

    db = get_db()
    warehouse_id = _resolve_crm_warehouse(db, request.form.get("warehouse_id"))
    customer_name = (request.form.get("customer_name") or "").strip()
    contact_person = (request.form.get("contact_person") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    city = (request.form.get("city") or "").strip()
    instagram_handle = (request.form.get("instagram_handle") or "").strip()
    customer_type = _normalize_customer_type(request.form.get("customer_type"))
    marketing_channel = (request.form.get("marketing_channel") or "").strip()
    note = (request.form.get("note") or "").strip()

    if warehouse_id is None or not customer_name:
        flash("Gudang dan nama customer wajib diisi.", "error")
        return _crm_redirect("contacts")

    duplicate = db.execute(
        """
        SELECT id
        FROM crm_customers
        WHERE warehouse_id=?
          AND customer_name=?
          AND COALESCE(phone, '')=?
        """,
        (warehouse_id, customer_name, phone),
    ).fetchone()
    if duplicate:
        flash("Customer dengan nama dan kontak yang sama sudah ada.", "error")
        return _crm_redirect("contacts")

    db.execute(
        """
        INSERT INTO crm_customers(
            warehouse_id,
            customer_name,
            contact_person,
            phone,
            email,
            city,
            instagram_handle,
            customer_type,
            marketing_channel,
            note
        )
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            warehouse_id,
            customer_name,
            contact_person or None,
            phone or None,
            email or None,
            city or None,
            instagram_handle or None,
            customer_type,
            marketing_channel or None,
            note or None,
        ),
    )
    db.commit()

    flash("Contact customer berhasil ditambahkan.", "success")
    return _crm_redirect("contacts")


@crm_bp.route("/customers/delete/<int:customer_id>", methods=["POST"])
def delete_customer(customer_id):
    if not _require_crm_manage():
        return _crm_redirect("contacts")

    db = get_db()
    customer = _get_customer_by_id(db, customer_id)
    if not customer:
        flash("Customer CRM tidak ditemukan.", "error")
        return _crm_redirect("contacts")

    purchase_count = db.execute(
        "SELECT COUNT(*) FROM crm_purchase_records WHERE customer_id=?",
        (customer_id,),
    ).fetchone()[0]
    member_count = db.execute(
        "SELECT COUNT(*) FROM crm_memberships WHERE customer_id=?",
        (customer_id,),
    ).fetchone()[0]

    if purchase_count or member_count:
        flash("Customer yang sudah punya purchase history atau member tidak bisa dihapus.", "error")
        return _crm_redirect("contacts")

    db.execute("DELETE FROM crm_customers WHERE id=?", (customer_id,))
    db.commit()

    flash("Contact customer berhasil dihapus.", "success")
    return _crm_redirect("contacts")


@crm_bp.route("/purchases/add", methods=["POST"])
def add_purchase():
    if not _require_crm_manage():
        return _crm_redirect("purchases")

    db = get_db()

    try:
        items = _parse_purchase_items(request.form)
    except ValueError as exc:
        flash(str(exc), "error")
        return _crm_redirect("purchases")

    warehouse_id = _resolve_crm_warehouse(db, request.form.get("warehouse_id"))
    customer_id = _to_int(request.form.get("customer_id"), 0)
    member_id = _to_int(request.form.get("member_id"), 0)
    purchase_date = _normalize_date(request.form.get("purchase_date"))
    invoice_no = (request.form.get("invoice_no") or "").strip()
    channel = _normalize_purchase_channel(request.form.get("channel"))
    note = (request.form.get("note") or "").strip()

    customer = _get_customer_by_id(db, customer_id)
    if not customer:
        flash("Customer tidak valid untuk scope CRM ini.", "error")
        return _crm_redirect("purchases")

    if warehouse_id != customer["warehouse_id"]:
        flash("Gudang transaksi harus sama dengan gudang customer.", "error")
        return _crm_redirect("purchases")

    member = None
    if member_id:
        member = _get_member_by_id(db, member_id)
        if not member or member["customer_id"] != customer_id:
            flash("Member tidak valid untuk customer yang dipilih.", "error")
            return _crm_redirect("purchases")

    if not purchase_date:
        flash("Tanggal pembelian wajib valid.", "error")
        return _crm_redirect("purchases")

    total_amount = round(sum(item["line_total"] for item in items), 2)
    total_qty = sum(item["qty"] for item in items)

    try:
        db.execute("BEGIN")
        cursor = db.execute(
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
                customer_id,
                member_id or None,
                warehouse_id,
                purchase_date,
                invoice_no or None,
                channel,
                total_qty,
                total_amount,
                note or None,
                session.get("user_id"),
            ),
        )
        purchase_id = cursor.lastrowid

        db.executemany(
            """
            INSERT INTO crm_purchase_items(
                purchase_id,
                product_id,
                variant_id,
                qty,
                unit_price,
                line_total
            )
            VALUES (?,?,?,?,?,?)
            """,
            [
                (
                    purchase_id,
                    item["product_id"],
                    item["variant_id"],
                    item["qty"],
                    item["unit_price"],
                    item["line_total"],
                )
                for item in items
            ],
        )

        if member:
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
                    purchase_date,
                    "purchase",
                    invoice_no or None,
                    total_amount,
                    0,
                    note or "Auto-generated dari purchase CRM",
                    session.get("user_id"),
                ),
            )

        db.commit()
    except Exception:
        db.rollback()
        flash("Purchase record gagal disimpan.", "error")
        return _crm_redirect("purchases")

    flash("Purchase record customer berhasil disimpan.", "success")
    return _crm_redirect("purchases")


@crm_bp.route("/purchases/delete/<int:purchase_id>", methods=["POST"])
def delete_purchase(purchase_id):
    if not _require_crm_manage():
        return _crm_redirect("purchases")

    db = get_db()
    purchase = _get_purchase_by_id(db, purchase_id)
    if not purchase:
        flash("Purchase record tidak ditemukan.", "error")
        return _crm_redirect("purchases")

    db.execute("DELETE FROM crm_purchase_records WHERE id=?", (purchase_id,))
    db.commit()

    flash("Purchase record berhasil dihapus.", "success")
    return _crm_redirect("purchases")


@crm_bp.route("/members/add", methods=["POST"])
def add_member():
    if not _require_crm_manage():
        return _crm_redirect("members")

    db = get_db()
    customer_id = _to_int(request.form.get("customer_id"), 0)
    member_code = (request.form.get("member_code") or "").strip().upper()
    tier = _normalize_member_tier(request.form.get("tier"))
    status = _normalize_member_status(request.form.get("status"))
    join_date = _normalize_date(request.form.get("join_date"))
    expiry_date = _normalize_date(request.form.get("expiry_date"))
    points = _to_int(request.form.get("points"), 0)
    benefit_note = (request.form.get("benefit_note") or "").strip()
    note = (request.form.get("note") or "").strip()

    customer = _get_customer_by_id(db, customer_id)
    if not customer:
        flash("Customer member tidak valid.", "error")
        return _crm_redirect("members")

    if not member_code or not join_date:
        flash("Kode member dan tanggal join wajib diisi.", "error")
        return _crm_redirect("members")

    duplicate_code = db.execute(
        "SELECT id FROM crm_memberships WHERE member_code=?",
        (member_code,),
    ).fetchone()
    if duplicate_code:
        flash("Kode member sudah digunakan.", "error")
        return _crm_redirect("members")

    duplicate_customer = db.execute(
        "SELECT id FROM crm_memberships WHERE customer_id=?",
        (customer_id,),
    ).fetchone()
    if duplicate_customer:
        flash("Customer ini sudah terdaftar sebagai member.", "error")
        return _crm_redirect("members")

    db.execute(
        """
        INSERT INTO crm_memberships(
            customer_id,
            warehouse_id,
            member_code,
            tier,
            status,
            join_date,
            expiry_date,
            points,
            benefit_note,
            note
        )
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            customer_id,
            customer["warehouse_id"],
            member_code,
            tier,
            status,
            join_date,
            expiry_date,
            points,
            benefit_note or None,
            note or None,
        ),
    )
    db.commit()

    flash("Member CRM berhasil ditambahkan.", "success")
    return _crm_redirect("members")


@crm_bp.route("/members/delete/<int:member_id>", methods=["POST"])
def delete_member(member_id):
    if not _require_crm_manage():
        return _crm_redirect("members")

    db = get_db()
    member = _get_member_by_id(db, member_id)
    if not member:
        flash("Member CRM tidak ditemukan.", "error")
        return _crm_redirect("members")

    purchase_count = db.execute(
        "SELECT COUNT(*) FROM crm_purchase_records WHERE member_id=?",
        (member_id,),
    ).fetchone()[0]
    if purchase_count:
        flash("Member yang sudah punya purchase history tidak bisa dihapus.", "error")
        return _crm_redirect("members")

    db.execute("DELETE FROM crm_memberships WHERE id=?", (member_id,))
    db.commit()

    flash("Member CRM berhasil dihapus.", "success")
    return _crm_redirect("members")


@crm_bp.route("/member-records/add", methods=["POST"])
def add_member_record():
    if not _require_crm_manage():
        return _crm_redirect("members")

    db = get_db()
    member_id = _to_int(request.form.get("member_id"), 0)
    member = _get_member_by_id(db, member_id)
    if not member:
        flash("Member tidak valid.", "error")
        return _crm_redirect("members")

    record_date = _normalize_date(request.form.get("record_date"))
    record_type = _normalize_member_record_type(request.form.get("record_type"))
    reference_no = (request.form.get("reference_no") or "").strip()
    amount = round(_to_float(request.form.get("amount"), 0), 2)
    points_delta = _to_int(request.form.get("points_delta"), 0)
    note = (request.form.get("note") or "").strip()

    if not record_date:
        flash("Tanggal record member wajib valid.", "error")
        return _crm_redirect("members")

    db.execute(
        """
        INSERT INTO crm_member_records(
            member_id,
            warehouse_id,
            record_date,
            record_type,
            reference_no,
            amount,
            points_delta,
            note,
            handled_by
        )
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            member_id,
            member["warehouse_id"],
            record_date,
            record_type,
            reference_no or None,
            amount,
            points_delta,
            note or None,
            session.get("user_id"),
        ),
    )
    db.commit()

    flash("Record member berhasil ditambahkan.", "success")
    return _crm_redirect("members")


@crm_bp.route("/member-records/delete/<int:record_id>", methods=["POST"])
def delete_member_record(record_id):
    if not _require_crm_manage():
        return _crm_redirect("members")

    db = get_db()
    record = _get_member_record_by_id(db, record_id)
    if not record:
        flash("Record member tidak ditemukan.", "error")
        return _crm_redirect("members")

    if record["purchase_id"]:
        flash("Record pembelian otomatis ikut purchase history. Hapus purchase record jika ingin menghapus histori ini.", "error")
        return _crm_redirect("members")

    db.execute("DELETE FROM crm_member_records WHERE id=?", (record_id,))
    db.commit()

    flash("Record member berhasil dihapus.", "success")
    return _crm_redirect("members")
