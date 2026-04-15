import json
import sqlite3
import time
from urllib.parse import urlencode
from datetime import date as date_cls

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session

from database import get_db
from services.crm_excel_import import import_crm_workbook
from services.pagination import build_pagination_state
from services.crm_loyalty import (
    CRM_TRANSACTION_TYPES,
    CRM_TRANSACTION_TYPE_LABELS,
    DEFAULT_STRINGING_REWARD_AMOUNT,
    MEMBER_RECORD_TYPES,
    MEMBER_TYPE_LABELS,
    MEMBER_TYPES,
    MEMBERSHIP_STATUSES,
    STRINGING_PROGRESS_MIN_AMOUNT,
    STRINGING_REWARD_THRESHOLD,
    build_auto_member_record,
    build_member_snapshot_from_row,
    find_matching_customer_identity,
    find_matching_member_identity,
    get_member_snapshot,
    merge_member_identity_records,
    normalize_member_record_type,
    normalize_member_type,
    normalize_membership_status,
    normalize_customer_phone,
    normalize_transaction_type,
    reconcile_member_identity_duplicates,
)
from services.rbac import has_permission, is_scoped_role, normalize_role


crm_bp = Blueprint("crm", __name__, url_prefix="/crm")

CUSTOMER_TYPES = {"retail", "member", "reseller", "vip", "wholesale"}
PURCHASE_CHANNELS = {"store", "whatsapp", "marketplace", "live", "event", "other"}
MEMBERSHIP_TIERS = {"regular", "silver", "gold", "platinum", "vip"}
CRM_TABS = {"contacts", "purchases", "members"}
MEMBER_STAFF_ROLES = {"leader", "admin", "staff"}
CRM_SMART_SELECT_LIMIT = 60
CRM_SMART_SELECT_MAX_LIMIT = 100
CRM_PURCHASE_PAGE_SIZE = 25
CRM_PURCHASE_MAX_PAGE_SIZE = 100
CRM_PURCHASE_PAGE_SIZE_OPTIONS = (10, 25, 50, 100)
CRM_DB_LOCK_RETRY_ATTEMPTS = 2
CRM_DB_LOCK_RETRY_DELAY_SECONDS = 0.35


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
    return normalize_membership_status(value)


def _normalize_member_record_type(value):
    return normalize_member_record_type(value)


def _normalize_member_type(value):
    return normalize_member_type(value)


def _normalize_transaction_type(value):
    return normalize_transaction_type(value)


def _normalize_date(value):
    raw_value = (value or "").strip()
    if not raw_value:
        return None
    try:
        return date_cls.fromisoformat(raw_value).isoformat()
    except ValueError:
        return None


def _format_crm_currency_label(value):
    return "Rp {:,.0f}".format(_to_float(value, 0)).replace(",", ".")


def _crm_scope_warehouse():
    if is_scoped_role(session.get("role")):
        return session.get("warehouse_id")
    return None


def _can_view_crm_revenue():
    return normalize_role(session.get("role")) in {"owner", "super_admin"}


def _mask_crm_revenue(customers, purchases, memberships, member_records, summary):
    masked_summary = dict(summary or {})
    masked_summary["total_revenue"] = None

    masked_customers = [{**row, "total_spent": None} for row in customers]
    masked_purchases = [{**row, "total_amount": None} for row in purchases]
    masked_memberships = [{**row, "total_member_spend": None} for row in memberships]
    masked_member_records = [{**row, "amount": None} for row in member_records]
    return (
        masked_customers,
        masked_purchases,
        masked_memberships,
        masked_member_records,
        masked_summary,
    )


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
    params = {"tab": selected_tab}
    for key in ("search", "warehouse", "member_status", "page", "page_size"):
        value = request.form.get(key)
        if value in (None, ""):
            value = request.args.get(key)
        if value not in (None, ""):
            params[key] = value
    return redirect(f"/crm/?{urlencode(params)}")


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


def _is_sqlite_lock_error(exc):
    return "database is locked" in str(exc or "").lower()


def _build_scope_clause(alias):
    scope_warehouse = _crm_scope_warehouse()
    if not scope_warehouse:
        return "", []
    return f" AND {alias}.warehouse_id=?", [scope_warehouse]


def _coerce_crm_smart_select_limit(value, default=CRM_SMART_SELECT_LIMIT):
    limit = _to_int(value, default)
    if limit <= 0:
        return default
    return min(limit, CRM_SMART_SELECT_MAX_LIMIT)


def _coerce_crm_purchase_page_size(value, default=CRM_PURCHASE_PAGE_SIZE):
    page_size = _to_int(value, default)
    if page_size <= 0:
        return default
    if page_size not in CRM_PURCHASE_PAGE_SIZE_OPTIONS:
        page_size = default
    return min(page_size, CRM_PURCHASE_MAX_PAGE_SIZE)


def _serialize_customer_option(customer):
    warehouse_name = (customer.get("warehouse_name") or "").strip()
    contact_person = (customer.get("contact_person") or "").strip()
    label_parts = [(customer.get("customer_name") or "Customer").strip()]
    if contact_person:
        label_parts.append(contact_person)
    if warehouse_name:
        label_parts.append(warehouse_name)
    return {
        "value": str(customer.get("id") or ""),
        "label": " | ".join(part for part in label_parts if part),
        "dataset": {
            "warehouseId": str(customer.get("warehouse_id") or ""),
            "warehouseName": warehouse_name,
            "contactPerson": contact_person,
            "phone": str(customer.get("phone") or ""),
            "email": str(customer.get("email") or ""),
            "customerType": str(customer.get("customer_type") or ""),
        },
    }


def _serialize_member_option(member):
    member_type = (member.get("member_type") or "purchase").strip() or "purchase"
    reward_unit_amount = member.get("reward_unit_amount")
    return {
        "value": str(member.get("id") or ""),
        "label": " | ".join(
            part
            for part in [
                (member.get("member_code") or "Member").strip(),
                (member.get("customer_name") or "Customer").strip(),
                MEMBER_TYPE_LABELS.get(member_type, member_type.replace("_", " ").title()),
            ]
            if part
        ),
        "dataset": {
            "customerId": str(member.get("customer_id") or ""),
            "memberType": member_type,
            "rewardUnitAmount": str(
                reward_unit_amount if reward_unit_amount not in (None, "") else DEFAULT_STRINGING_REWARD_AMOUNT
            ),
            "status": str(member.get("status") or ""),
            "warehouseId": str(member.get("warehouse_id") or ""),
            "warehouseName": str(member.get("warehouse_name") or ""),
        },
    }


def _serialize_staff_option(staff):
    warehouse_name = (staff.get("warehouse_name") or "").strip()
    label_parts = [(staff.get("display_name") or staff.get("username") or "Staff").strip()]
    if warehouse_name:
        label_parts.append(warehouse_name)
    return {
        "value": str(staff.get("id") or ""),
        "label": " | ".join(part for part in label_parts if part),
        "dataset": {
            "role": str(staff.get("role") or ""),
            "warehouseId": str(staff.get("warehouse_id") or ""),
            "warehouseName": warehouse_name,
            "username": str(staff.get("username") or ""),
        },
    }


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
            c.phone,
            w.name AS warehouse_name
            ,
            ru.username AS requested_by_staff_username,
            COALESCE(NULLIF(TRIM(re.full_name), ''), NULLIF(TRIM(ru.username), ''), NULL) AS requested_by_staff_name
        FROM crm_memberships m
        JOIN crm_customers c ON c.id = m.customer_id
        LEFT JOIN warehouses w ON w.id = m.warehouse_id
        LEFT JOIN users ru ON ru.id = m.requested_by_staff_id
        LEFT JOIN employees re ON re.id = ru.employee_id
        WHERE m.id=? {scope_clause}
        """,
        [member_id, *params],
    ).fetchone()


def _get_latest_customer_member(db, customer_id, *, active_only=False):
    scope_clause, params = _build_scope_clause("m")
    active_filter = " AND m.status='active'" if active_only else ""
    return db.execute(
        f"""
        SELECT m.*
        FROM crm_memberships m
        WHERE m.customer_id=? {active_filter} {scope_clause}
        ORDER BY m.id DESC
        LIMIT 1
        """,
        [customer_id, *params],
    ).fetchone()


def _resolve_customer_identity_match(db, warehouse_id, customer_name="", phone="", *, exclude_customer_id=0):
    return find_matching_customer_identity(
        db,
        warehouse_id,
        phone=phone,
        customer_name=customer_name,
        exclude_customer_id=exclude_customer_id,
    )


def _build_next_crm_member_code(db, warehouse_id, *, member_type):
    safe_warehouse_id = max(_to_int(warehouse_id, 0), 0)
    normalized_member_type = _normalize_member_type(member_type)
    prefix_map = {
        "purchase": "CRM-POINT",
        "stringing": "CRM-SENAR",
    }
    prefix = f"{prefix_map.get(normalized_member_type, 'CRM-MEMBER')}-{safe_warehouse_id:02d}-"
    rows = db.execute(
        "SELECT member_code FROM crm_memberships WHERE member_code LIKE ?",
        (f"{prefix}%",),
    ).fetchall()

    latest_sequence = 0
    for row in rows:
        member_code = str(row["member_code"] or "").strip().upper()
        if not member_code.startswith(prefix):
            continue
        tail = member_code[len(prefix):]
        if tail.isdigit():
            latest_sequence = max(latest_sequence, int(tail))

    return f"{prefix}{latest_sequence + 1:04d}"


def _auto_create_crm_purchase_member(db, customer, join_date, *, requested_by_user_id=None):
    customer_id = _to_int(customer["id"], 0)
    if customer_id <= 0:
        raise ValueError("Customer member tidak valid.")

    if not str(customer["phone"] or "").strip():
        return None

    warehouse_id = _to_int(customer["warehouse_id"], 0)
    member_code = _build_next_crm_member_code(db, warehouse_id, member_type="purchase")
    db.execute(
        """
        UPDATE crm_customers
        SET customer_type='member', updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (customer_id,),
    )
    cursor = db.execute(
        """
        INSERT INTO crm_memberships(
            customer_id,
            warehouse_id,
            member_code,
            member_type,
            tier,
            status,
            join_date,
            expiry_date,
            points,
            requested_by_staff_id,
            reward_unit_amount,
            opening_stringing_visits,
            opening_reward_redeemed,
            benefit_note,
            note
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            customer_id,
            warehouse_id,
            member_code,
            "purchase",
            "regular",
            "active",
            join_date,
            None,
            0,
            _to_int(requested_by_user_id, 0) or None,
            DEFAULT_STRINGING_REWARD_AMOUNT,
            0,
            0,
            "Poin belanja aktif: 1 poin setiap total Rp 10.000.",
            "Auto-created by CRM purchase member enrollment.",
        ),
    )
    return _get_member_by_id(db, cursor.lastrowid)


def _auto_create_crm_stringing_member(db, customer, join_date, *, requested_by_user_id=None):
    customer_id = _to_int(customer["id"], 0)
    if customer_id <= 0:
        raise ValueError("Customer member tidak valid.")

    warehouse_id = _to_int(customer["warehouse_id"], 0)
    member_code = _build_next_crm_member_code(db, warehouse_id, member_type="stringing")
    threshold_label = _format_crm_currency_label(STRINGING_PROGRESS_MIN_AMOUNT)
    db.execute(
        """
        UPDATE crm_customers
        SET customer_type='member', updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (customer_id,),
    )
    cursor = db.execute(
        """
        INSERT INTO crm_memberships(
            customer_id,
            warehouse_id,
            member_code,
            member_type,
            tier,
            status,
            join_date,
            expiry_date,
            points,
            requested_by_staff_id,
            reward_unit_amount,
            opening_stringing_visits,
            opening_reward_redeemed,
            benefit_note,
            note
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            customer_id,
            warehouse_id,
            member_code,
            "stringing",
            "regular",
            "active",
            join_date,
            None,
            0,
            _to_int(requested_by_user_id, 0) or None,
            DEFAULT_STRINGING_REWARD_AMOUNT,
            0,
            0,
            (
                f"Free senar 1x setiap {STRINGING_REWARD_THRESHOLD} progres "
                f"senaran berbayar minimal {threshold_label}."
            ),
            "Auto-created by CRM purchase Senaran Berbayar.",
        ),
    )
    return _get_member_by_id(db, cursor.lastrowid)


def _ensure_active_stringing_member_for_crm(db, member_id):
    safe_member_id = _to_int(member_id, 0)
    if safe_member_id <= 0:
        return None

    db.execute(
        """
        UPDATE crm_memberships
        SET status='active', updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (safe_member_id,),
    )
    member = _get_member_by_id(db, safe_member_id)
    if member:
        db.execute(
            """
            UPDATE crm_customers
            SET customer_type='member', updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (member["customer_id"],),
        )
    return member


def _resolve_crm_purchase_member(db, customer, transaction_type, purchase_date):
    safe_transaction_type = _normalize_transaction_type(transaction_type)
    safe_customer = dict(customer or {})
    reconcile_member_identity_duplicates(db, warehouse_id=safe_customer["warehouse_id"])

    latest_active_member = _get_latest_customer_member(db, safe_customer["id"], active_only=True)
    if latest_active_member:
        member = _get_member_by_id(db, latest_active_member["id"]) or latest_active_member
        member_type = _normalize_member_type(member["member_type"] if "member_type" in member.keys() else None)
        if safe_transaction_type == "purchase":
            return member, get_member_snapshot(db, member["id"])
        if member_type != "stringing":
            raise ValueError("Jenis transaksi senaran hanya bisa dipakai untuk member senaran.")
        return member, get_member_snapshot(db, member["id"])

    matching_member = find_matching_member_identity(
        db,
        safe_customer["warehouse_id"],
        "stringing" if safe_transaction_type != "purchase" else "purchase",
        phone=safe_customer.get("phone"),
        customer_name=safe_customer.get("customer_name"),
    )
    if matching_member:
        member = _get_member_by_id(db, matching_member["id"]) or matching_member
        if safe_transaction_type == "purchase":
            return member, get_member_snapshot(db, member["id"])
        member = _ensure_active_stringing_member_for_crm(db, member["id"]) or member
        return member, get_member_snapshot(db, member["id"])

    if safe_transaction_type == "purchase":
        member = _auto_create_crm_purchase_member(
            db,
            safe_customer,
            purchase_date,
            requested_by_user_id=session.get("user_id"),
        )
        if not member:
            return None, None
        return member, get_member_snapshot(db, member["id"])

    if safe_transaction_type == "stringing_reward_redemption":
        return None, None

    latest_member = _get_latest_customer_member(db, safe_customer["id"], active_only=False)
    if latest_member:
        member = _get_member_by_id(db, latest_member["id"]) or latest_member
        member_type = _normalize_member_type(member["member_type"] if "member_type" in member.keys() else None)
        if member_type != "stringing":
            raise ValueError("Customer ini sudah punya member tipe lain. Pilih member yang sesuai dulu.")
        member = _ensure_active_stringing_member_for_crm(db, member["id"]) or member
        return member, get_member_snapshot(db, member["id"])

    member = _auto_create_crm_stringing_member(
        db,
        safe_customer,
        purchase_date,
        requested_by_user_id=session.get("user_id"),
    )
    return member, get_member_snapshot(db, member["id"])


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


def _get_staff_by_id(db, staff_id):
    if not staff_id:
        return None
    row = db.execute(
        """
        SELECT
            u.id,
            u.role,
            u.warehouse_id,
            u.username,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Staff') AS display_name
        FROM users u
        LEFT JOIN employees e ON e.id = u.employee_id
        WHERE u.id=?
        LIMIT 1
        """,
        (staff_id,),
    ).fetchone()
    return dict(row) if row else None


def _fetch_customer_options(db, selected_warehouse=None, search="", limit=CRM_SMART_SELECT_LIMIT):
    params = []
    query = """
        SELECT
            c.id,
            c.customer_name,
            c.contact_person,
            c.phone,
            c.email,
            c.customer_type,
            c.warehouse_id,
            w.name AS warehouse_name
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

    search_term = (search or "").strip()
    if search_term:
        like_term = f"%{search_term}%"
        query += """
            AND (
                c.customer_name LIKE ?
                OR COALESCE(c.contact_person, '') LIKE ?
                OR COALESCE(c.phone, '') LIKE ?
                OR COALESCE(c.email, '') LIKE ?
                OR COALESCE(w.name, '') LIKE ?
            )
        """
        params.extend([like_term] * 5)

    query += " ORDER BY c.customer_name ASC, c.id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(_coerce_crm_smart_select_limit(limit))
    return [dict(row) for row in db.execute(query, params).fetchall()]


def _fetch_member_options(db, selected_warehouse=None, search="", limit=CRM_SMART_SELECT_LIMIT, customer_id=None):
    params = []
    query = """
        SELECT
            m.id,
            m.member_code,
            m.member_type,
            m.status,
            m.reward_unit_amount,
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

    if customer_id:
        query += " AND m.customer_id=?"
        params.append(customer_id)

    search_term = (search or "").strip()
    if search_term:
        like_term = f"%{search_term}%"
        query += """
            AND (
                m.member_code LIKE ?
                OR COALESCE(c.customer_name, '') LIKE ?
                OR COALESCE(m.member_type, '') LIKE ?
                OR COALESCE(m.status, '') LIKE ?
                OR COALESCE(w.name, '') LIKE ?
            )
        """
        params.extend([like_term] * 5)

    query += " ORDER BY m.status='active' DESC, c.customer_name ASC, m.id DESC"
    if limit:
        query += " LIMIT ?"
        params.append(_coerce_crm_smart_select_limit(limit))
    return [dict(row) for row in db.execute(query, params).fetchall()]


def _fetch_staff_options(db, selected_warehouse=None, search="", limit=CRM_SMART_SELECT_LIMIT):
    params = []
    query = """
        SELECT
            u.id,
            u.role,
            u.warehouse_id,
            u.username,
            COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Staff') AS display_name,
            w.name AS warehouse_name
        FROM users u
        LEFT JOIN employees e ON e.id = u.employee_id
        LEFT JOIN warehouses w ON w.id = u.warehouse_id
        WHERE u.role IN ('leader', 'admin', 'staff')
    """

    scope_warehouse = _crm_scope_warehouse()
    if scope_warehouse:
        query += " AND u.warehouse_id=?"
        params.append(scope_warehouse)
    elif selected_warehouse:
        query += " AND u.warehouse_id=?"
        params.append(selected_warehouse)

    search_term = (search or "").strip()
    if search_term:
        like_term = f"%{search_term}%"
        query += """
            AND (
                COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Staff') LIKE ?
                OR COALESCE(u.username, '') LIKE ?
                OR COALESCE(w.name, '') LIKE ?
                OR COALESCE(u.role, '') LIKE ?
            )
        """
        params.extend([like_term] * 4)

    query += " ORDER BY COALESCE(NULLIF(TRIM(e.full_name), ''), NULLIF(TRIM(u.username), ''), 'Staff') ASC"
    if limit:
        query += " LIMIT ?"
        params.append(_coerce_crm_smart_select_limit(limit))
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
            mp.products_summary AS products_summary,
            COALESCE(ip.imported_products_summary, '') AS imported_products_summary,
            m.member_code,
            m.member_type,
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
        LEFT JOIN (
            SELECT
                pr.customer_id,
                GROUP_CONCAT(DISTINCT NULLIF(TRIM(pr.import_items_summary), '')) AS imported_products_summary
            FROM crm_purchase_records pr
            WHERE TRIM(COALESCE(pr.import_items_summary, '')) <> ''
            GROUP BY pr.customer_id
        ) ip ON ip.customer_id = c.id
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
                OR COALESCE(ip.imported_products_summary, '') LIKE ?
            )
        """
        params.extend([like, like, like, like, like, like, like])

    query += " ORDER BY p.last_purchase_date DESC, c.customer_name ASC, c.id DESC"
    rows = [dict(row) for row in db.execute(query, params).fetchall()]
    for row in rows:
        actual_summary = (row.get("products_summary") or "").strip()
        imported_summary = (row.get("imported_products_summary") or "").strip()
        if actual_summary and imported_summary:
            row["products_summary"] = f"{actual_summary} | {imported_summary}"
        elif imported_summary:
            row["products_summary"] = imported_summary
        elif actual_summary:
            row["products_summary"] = actual_summary
        else:
            row["products_summary"] = "-"
    return rows


def _build_purchase_record_filters(search="", selected_warehouse=None):
    params = []
    query = ""

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
                OR COALESCE(pr.transaction_type, '') LIKE ?
                OR COALESCE(pr.note, '') LIKE ?
                OR COALESCE(pr.import_items_summary, '') LIKE ?
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
        params.extend([like, like, like, like, like, like, like, like, like])

    return query, params


def _fetch_purchase_records(db, search="", selected_warehouse=None, limit=None, offset=None):
    filter_query, params = _build_purchase_record_filters(search, selected_warehouse)
    query = f"""
        SELECT
            pr.*,
            c.customer_name,
            c.contact_person,
            m.member_code,
            m.member_type,
            w.name AS warehouse_name,
            u.username AS handled_by_name
        FROM crm_purchase_records pr
        JOIN crm_customers c ON c.id = pr.customer_id
        LEFT JOIN crm_memberships m ON m.id = pr.member_id
        LEFT JOIN warehouses w ON w.id = pr.warehouse_id
        LEFT JOIN users u ON u.id = pr.handled_by
        WHERE 1=1
        {filter_query}
        ORDER BY pr.purchase_date DESC, pr.id DESC
    """

    query_params = list(params)
    if limit is not None:
        query += " LIMIT ?"
        query_params.append(max(1, int(limit)))
        if offset is not None:
            query += " OFFSET ?"
            query_params.append(max(0, int(offset)))

    rows = [dict(row) for row in db.execute(query, query_params).fetchall()]
    if not rows:
        return rows

    purchase_ids = [row["id"] for row in rows]
    item_map = {}
    chunk_size = 400
    for chunk_start in range(0, len(purchase_ids), chunk_size):
        chunk_ids = purchase_ids[chunk_start:chunk_start + chunk_size]
        chunk_placeholders = ",".join("?" for _ in chunk_ids)
        item_rows = db.execute(
            f"""
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
            WHERE pi.purchase_id IN ({chunk_placeholders})
            GROUP BY pi.purchase_id
            """,
            chunk_ids,
        ).fetchall()
        item_map.update({row["purchase_id"]: dict(row) for row in item_rows})

    for row in rows:
        item_snapshot = item_map.get(row["id"], {})
        fallback_total_qty = _to_int(row.get("import_total_qty"), 0)
        fallback_summary = (row.get("import_items_summary") or "").strip()
        row["total_qty"] = item_snapshot.get("total_qty") or fallback_total_qty
        row["items_summary"] = item_snapshot.get("items_summary") or fallback_summary or "-"

    return rows


def _count_purchase_records(db, search="", selected_warehouse=None):
    filter_query, params = _build_purchase_record_filters(search, selected_warehouse)
    row = db.execute(
        f"""
        SELECT COUNT(*)
        FROM crm_purchase_records pr
        JOIN crm_customers c ON c.id = pr.customer_id
        LEFT JOIN crm_memberships m ON m.id = pr.member_id
        WHERE 1=1
        {filter_query}
        """,
        params,
    ).fetchone()
    return int(row[0] if row else 0)


def _fetch_crm_summary_snapshot(db, search="", selected_warehouse=None, member_status=""):
    customer_params = []
    customer_query = """
        SELECT
            COUNT(*) AS customers,
            SUM(CASE WHEN COALESCE(p.purchase_count, 0) > 0 THEN 1 ELSE 0 END) AS customers_with_purchase,
            SUM(
                CASE
                    WHEN TRIM(COALESCE(c.phone, '')) <> '' OR TRIM(COALESCE(c.email, '')) <> '' THEN 1
                    ELSE 0
                END
            ) AS contact_ready
        FROM crm_customers c
        LEFT JOIN (
            SELECT
                customer_id,
                COUNT(*) AS purchase_count
            FROM crm_purchase_records
            GROUP BY customer_id
        ) p ON p.customer_id = c.id
        WHERE 1=1
    """
    scope_clause, scope_params = _build_scope_clause("c")
    customer_query += scope_clause
    customer_params.extend(scope_params)

    if selected_warehouse:
        customer_query += " AND c.warehouse_id=?"
        customer_params.append(selected_warehouse)

    if search:
        like = f"%{search}%"
        customer_query += """
            AND (
                c.customer_name LIKE ?
                OR COALESCE(c.contact_person, '') LIKE ?
                OR COALESCE(c.phone, '') LIKE ?
                OR COALESCE(c.email, '') LIKE ?
                OR COALESCE(c.instagram_handle, '') LIKE ?
                OR EXISTS (
                    SELECT 1
                    FROM crm_memberships cm
                    WHERE cm.customer_id = c.id
                      AND COALESCE(cm.member_code, '') LIKE ?
                )
            )
        """
        customer_params.extend([like, like, like, like, like, like])

    purchase_filter_query, purchase_filter_params = _build_purchase_record_filters(search, selected_warehouse)
    purchase_row = db.execute(
        f"""
        SELECT
            COALESCE(SUM(pr.total_amount), 0) AS total_revenue,
            MAX(pr.purchase_date) AS latest_purchase
        FROM crm_purchase_records pr
        JOIN crm_customers c ON c.id = pr.customer_id
        LEFT JOIN crm_memberships m ON m.id = pr.member_id
        WHERE 1=1
        {purchase_filter_query}
        """,
        purchase_filter_params,
    ).fetchone()

    membership_params = []
    membership_query = """
        SELECT
            SUM(CASE WHEN m.status='active' THEN 1 ELSE 0 END) AS active_members
        FROM crm_memberships m
        JOIN crm_customers c ON c.id = m.customer_id
        WHERE 1=1
    """
    scope_clause, scope_params = _build_scope_clause("m")
    membership_query += scope_clause
    membership_params.extend(scope_params)

    if selected_warehouse:
        membership_query += " AND m.warehouse_id=?"
        membership_params.append(selected_warehouse)

    if member_status in MEMBERSHIP_STATUSES:
        membership_query += " AND m.status=?"
        membership_params.append(member_status)

    if search:
        like = f"%{search}%"
        membership_query += """
            AND (
                m.member_code LIKE ?
                OR c.customer_name LIKE ?
                OR COALESCE(c.contact_person, '') LIKE ?
                OR COALESCE(c.phone, '') LIKE ?
                OR COALESCE(m.member_type, '') LIKE ?
                OR COALESCE(m.note, '') LIKE ?
            )
        """
        membership_params.extend([like, like, like, like, like, like])

    member_record_params = []
    member_record_query = """
        SELECT COUNT(*) AS member_records
        FROM crm_member_records mr
        JOIN crm_memberships m ON m.id = mr.member_id
        JOIN crm_customers c ON c.id = m.customer_id
        WHERE 1=1
    """
    scope_clause, scope_params = _build_scope_clause("mr")
    member_record_query += scope_clause
    member_record_params.extend(scope_params)

    if selected_warehouse:
        member_record_query += " AND mr.warehouse_id=?"
        member_record_params.append(selected_warehouse)

    if search:
        like = f"%{search}%"
        member_record_query += """
            AND (
                m.member_code LIKE ?
                OR c.customer_name LIKE ?
                OR COALESCE(mr.reference_no, '') LIKE ?
                OR COALESCE(mr.note, '') LIKE ?
            )
        """
        member_record_params.extend([like, like, like, like])

    customer_row = db.execute(customer_query, customer_params).fetchone()
    membership_row = db.execute(membership_query, membership_params).fetchone()
    member_record_row = db.execute(member_record_query, member_record_params).fetchone()

    return {
        "customers": int((customer_row["customers"] if customer_row else 0) or 0),
        "customers_with_purchase": int((customer_row["customers_with_purchase"] if customer_row else 0) or 0),
        "active_members": int((membership_row["active_members"] if membership_row else 0) or 0),
        "total_revenue": round(float((purchase_row["total_revenue"] if purchase_row else 0) or 0), 2),
        "contact_ready": int((customer_row["contact_ready"] if customer_row else 0) or 0),
        "member_records": int((member_record_row["member_records"] if member_record_row else 0) or 0),
        "latest_purchase": (purchase_row["latest_purchase"] if purchase_row else None) or "-",
    }


def _fetch_memberships(db, search="", selected_warehouse=None, member_status=""):
    params = []
    query = """
        SELECT
            m.*,
            c.customer_name,
            c.contact_person,
            c.phone,
            w.name AS warehouse_name,
            ru.username AS requested_by_staff_username,
            COALESCE(NULLIF(TRIM(re.full_name), ''), NULLIF(TRIM(ru.username), ''), NULL) AS requested_by_staff_name,
            COALESCE(stats.record_count, 0) AS record_count,
            stats.last_record_date,
            COALESCE(purchase_stats.total_member_spend, 0) AS total_member_spend,
            COALESCE(stats.points_delta_total, 0) AS points_delta_total,
            COALESCE(stats.service_count_total, 0) AS service_count_total,
            COALESCE(stats.reward_redeemed_total, 0) AS reward_redeemed_total,
            COALESCE(stats.benefit_value_total, 0) AS benefit_value_total
        FROM crm_memberships m
        JOIN crm_customers c ON c.id = m.customer_id
        LEFT JOIN warehouses w ON w.id = m.warehouse_id
        LEFT JOIN users ru ON ru.id = m.requested_by_staff_id
        LEFT JOIN employees re ON re.id = ru.employee_id
        LEFT JOIN (
            SELECT
                mr.member_id,
                COUNT(*) AS record_count,
                MAX(mr.record_date) AS last_record_date,
                SUM(COALESCE(mr.points_delta, 0)) AS points_delta_total,
                SUM(COALESCE(mr.service_count_delta, 0)) AS service_count_total,
                SUM(COALESCE(mr.reward_redeemed_delta, 0)) AS reward_redeemed_total,
                SUM(COALESCE(mr.benefit_value, 0)) AS benefit_value_total
            FROM crm_member_records mr
            GROUP BY mr.member_id
        ) stats ON stats.member_id = m.id
        LEFT JOIN (
            SELECT
                pr.member_id,
                SUM(COALESCE(pr.total_amount, 0)) AS total_member_spend
            FROM crm_purchase_records pr
            WHERE pr.member_id IS NOT NULL
            GROUP BY pr.member_id
        ) purchase_stats ON purchase_stats.member_id = m.id
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
                OR COALESCE(m.member_type, '') LIKE ?
                OR COALESCE(m.note, '') LIKE ?
            )
        """
        params.extend([like, like, like, like, like, like])

    query += " ORDER BY m.join_date DESC, m.id DESC"
    return [
        build_member_snapshot_from_row(dict(row))
        for row in db.execute(query, params).fetchall()
    ]


def _fetch_member_records(db, search="", selected_warehouse=None):
    params = []
    query = """
        SELECT
            mr.*,
            m.member_code,
            m.member_type,
            m.reward_unit_amount,
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
    reconcile_member_identity_duplicates(db)
    db.commit()
    can_view_crm_revenue = _can_view_crm_revenue()
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
    purchase_page_size = _coerce_crm_purchase_page_size(request.args.get("page_size"), CRM_PURCHASE_PAGE_SIZE)
    purchase_page = max(1, _to_int(request.args.get("page"), 1))
    purchase_total = 0
    purchase_page_start = 0
    purchase_page_end = 0
    purchase_pagination = None

    warehouses = db.execute("SELECT id, name FROM warehouses ORDER BY name").fetchall()
    customers = []
    purchases = []
    memberships = []
    member_records = []

    if selected_tab == "contacts":
        customers = _fetch_customers(db, search, selected_warehouse)
        summary = _fetch_crm_summary_snapshot(db, search, selected_warehouse, member_status)
    elif selected_tab == "purchases":
        purchase_total = _count_purchase_records(db, search, selected_warehouse)
        purchase_total_pages = max(1, (purchase_total + purchase_page_size - 1) // purchase_page_size)
        purchase_page = max(1, min(purchase_page, purchase_total_pages))
        purchase_offset = (purchase_page - 1) * purchase_page_size
        purchases = _fetch_purchase_records(
            db,
            search,
            selected_warehouse,
            limit=purchase_page_size,
            offset=purchase_offset,
        )
        purchase_page_start = purchase_offset + 1 if purchase_total else 0
        purchase_page_end = purchase_offset + len(purchases)
        purchase_pagination = build_pagination_state(
            "/crm/",
            purchase_page,
            purchase_total_pages,
            {
                "tab": selected_tab,
                "search": search,
                "warehouse": selected_warehouse,
                "page_size": purchase_page_size,
            },
            group_size=5,
            page_param="page",
        )
        summary = _fetch_crm_summary_snapshot(db, search, selected_warehouse, member_status)
    else:
        memberships = _fetch_memberships(db, search, selected_warehouse, member_status)
        member_records = _fetch_member_records(db, search, selected_warehouse)
        summary = _fetch_crm_summary_snapshot(db, search, selected_warehouse, member_status)

    customer_options = _fetch_customer_options(db, selected_warehouse, limit=CRM_SMART_SELECT_LIMIT)
    member_options = _fetch_member_options(db, selected_warehouse, limit=CRM_SMART_SELECT_LIMIT)
    staff_options = _fetch_staff_options(db, selected_warehouse, limit=CRM_SMART_SELECT_LIMIT)

    if not can_view_crm_revenue:
        customers, purchases, memberships, member_records, summary = _mask_crm_revenue(
            customers,
            purchases,
            memberships,
            member_records,
            summary,
        )

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
        staff_options=staff_options,
        summary=summary,
        purchase_pagination=purchase_pagination,
        purchase_total=purchase_total,
        purchase_page_size=purchase_page_size,
        purchase_page_start=purchase_page_start,
        purchase_page_end=purchase_page_end,
        purchase_page_size_options=CRM_PURCHASE_PAGE_SIZE_OPTIONS,
        customer_types=sorted(CUSTOMER_TYPES),
        purchase_channels=sorted(PURCHASE_CHANNELS),
        member_types=sorted(MEMBER_TYPES),
        member_type_labels=MEMBER_TYPE_LABELS,
        membership_tiers=sorted(MEMBERSHIP_TIERS),
        membership_statuses=sorted(MEMBERSHIP_STATUSES),
        member_record_types=sorted(MEMBER_RECORD_TYPES),
        transaction_types=["purchase", "stringing_service", "stringing_reward_redemption"],
        transaction_type_labels=CRM_TRANSACTION_TYPE_LABELS,
        crm_smart_select_limit=CRM_SMART_SELECT_LIMIT,
        default_stringing_reward_amount=DEFAULT_STRINGING_REWARD_AMOUNT,
        stringing_progress_min_amount=STRINGING_PROGRESS_MIN_AMOUNT,
        scoped_crm_warehouse=_crm_scope_warehouse(),
        can_manage_crm=has_permission(session.get("role"), "manage_crm"),
        can_view_crm_revenue=can_view_crm_revenue,
    )


@crm_bp.get("/options/<option_type>")
def crm_smart_select_options(option_type):
    if not has_permission(session.get("role"), "view_crm"):
        return jsonify({"status": "error", "message": "Tidak punya akses ke CRM"}), 403

    db = get_db()
    normalized_option_type = (option_type or "").strip().lower()
    selected_warehouse = _resolve_crm_warehouse(
        db,
        request.args.get("warehouse"),
        allow_empty=not is_scoped_role(session.get("role")),
    )
    search = (request.args.get("q") or "").strip()
    limit = _coerce_crm_smart_select_limit(request.args.get("limit"), CRM_SMART_SELECT_LIMIT)

    if normalized_option_type == "customers":
        options = [
            _serialize_customer_option(customer)
            for customer in _fetch_customer_options(db, selected_warehouse, search=search, limit=limit)
        ]
    elif normalized_option_type == "members":
        customer_id = _to_int(request.args.get("customer_id"), None)
        options = [
            _serialize_member_option(member)
            for member in _fetch_member_options(
                db,
                selected_warehouse,
                search=search,
                limit=limit,
                customer_id=customer_id,
            )
        ]
    elif normalized_option_type == "staff":
        options = [
            _serialize_staff_option(staff)
            for staff in _fetch_staff_options(db, selected_warehouse, search=search, limit=limit)
        ]
    else:
        return jsonify({"status": "error", "message": "Jenis opsi CRM tidak dikenali."}), 404

    return jsonify(
        {
            "status": "success",
            "option_type": normalized_option_type,
            "query": search,
            "count": len(options),
            "options": options,
        }
    )


@crm_bp.route("/import", methods=["POST"])
def import_crm_excel():
    selected_tab = request.form.get("tab") or "contacts"
    if not _require_crm_manage():
        return _crm_redirect(selected_tab)

    upload = request.files.get("crm_file")
    if not upload or not (upload.filename or "").strip():
        flash("File Excel CRM wajib dipilih dulu.", "error")
        return _crm_redirect(selected_tab)

    filename = (upload.filename or "").strip()
    if not filename.lower().endswith(".xlsx"):
        flash("Format file CRM harus .xlsx.", "error")
        return _crm_redirect(selected_tab)

    workbook_bytes = upload.read()
    if not workbook_bytes:
        flash("File CRM kosong atau gagal dibaca.", "error")
        return _crm_redirect(selected_tab)

    db = get_db()
    raw_import_warehouse = request.form.get("warehouse")
    if raw_import_warehouse in (None, "") and not _crm_scope_warehouse():
        selected_warehouse = None
    else:
        selected_warehouse = _resolve_crm_warehouse(
            db,
            raw_import_warehouse,
            allow_empty=not is_scoped_role(session.get("role")),
        )
    handled_by = _to_int(session.get("user_id"), 0) or None

    try:
        summary = import_crm_workbook(
            db,
            workbook_bytes,
            filename=filename,
            selected_warehouse_id=selected_warehouse,
            handled_by=handled_by,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return _crm_redirect(selected_tab)
    except sqlite3.OperationalError as exc:
        current_app.logger.exception("CRM IMPORT SQLITE ERROR")
        if _is_sqlite_lock_error(exc):
            flash("Import CRM gagal karena database sedang sibuk di server. Coba ulang saat traffic VPS lebih sepi.", "error")
        else:
            flash("Import CRM gagal diproses oleh database server.", "error")
        return _crm_redirect(selected_tab)
    except Exception:
        current_app.logger.exception("CRM IMPORT ERROR")
        flash("Import CRM gagal diproses. Cek log server untuk detail error.", "error")
        return _crm_redirect(selected_tab)

    warehouse_labels = []
    processed_warehouse_ids = summary.get("processed_warehouses") or []
    if processed_warehouse_ids:
        placeholders = ",".join("?" for _ in processed_warehouse_ids)
        warehouse_rows = db.execute(
            f"SELECT id, name FROM warehouses WHERE id IN ({placeholders}) ORDER BY name ASC",
            processed_warehouse_ids,
        ).fetchall()
        warehouse_labels = [row["name"] for row in warehouse_rows]

    summary_parts = [
        f"customer {summary['customers_created']} baru / {summary['customers_updated']} update",
        f"histori {summary['purchases_created']} baru / {summary['purchases_updated']} update",
        f"member {summary['memberships_created']} baru / {summary['memberships_updated']} update",
    ]
    if summary.get("purchases_skipped_conflict"):
        summary_parts.append(f"{summary['purchases_skipped_conflict']} invoice manual dilewati")
    if summary.get("memberships_skipped_conflict"):
        summary_parts.append(f"{summary['memberships_skipped_conflict']} member bentrok dilewati")
    if summary.get("skipped_unknown_warehouse"):
        summary_parts.append(f"{summary['skipped_unknown_warehouse']} baris lokasi tidak dikenali")

    total_changes = (
        int(summary.get("customers_created") or 0)
        + int(summary.get("customers_updated") or 0)
        + int(summary.get("purchases_created") or 0)
        + int(summary.get("purchases_updated") or 0)
        + int(summary.get("memberships_created") or 0)
        + int(summary.get("memberships_updated") or 0)
    )

    if total_changes <= 0:
        flash("Import CRM selesai, tapi tidak ada data yang berubah pada scope gudang ini.", "warning")
        return _crm_redirect(selected_tab)

    warehouse_suffix = ""
    if warehouse_labels:
        warehouse_suffix = f" Scope: {', '.join(warehouse_labels)}."
    flash("Import CRM Excel selesai: " + "; ".join(summary_parts) + warehouse_suffix, "success")
    return _crm_redirect(selected_tab)


@crm_bp.route("/customers/add", methods=["POST"])
def add_customer():
    if not _require_crm_manage():
        return _crm_redirect("contacts")

    db = get_db()
    warehouse_id = _resolve_crm_warehouse(db, request.form.get("warehouse_id"))
    customer_name = (request.form.get("customer_name") or "").strip()
    contact_person = (request.form.get("contact_person") or "").strip()
    phone = normalize_customer_phone(request.form.get("phone"))
    email = (request.form.get("email") or "").strip()
    city = (request.form.get("city") or "").strip()
    instagram_handle = (request.form.get("instagram_handle") or "").strip()
    customer_type = _normalize_customer_type(request.form.get("customer_type"))
    marketing_channel = (request.form.get("marketing_channel") or "").strip()
    note = (request.form.get("note") or "").strip()

    if warehouse_id is None or not customer_name:
        flash("Gudang dan nama customer wajib diisi.", "error")
        return _crm_redirect("contacts")

    duplicate = _resolve_customer_identity_match(
        db,
        warehouse_id,
        customer_name,
        phone,
    )
    if duplicate:
        db.execute(
            """
            UPDATE crm_customers
            SET
                customer_name=?,
                contact_person=COALESCE(NULLIF(?, ''), contact_person),
                phone=COALESCE(NULLIF(?, ''), phone),
                email=COALESCE(NULLIF(?, ''), email),
                city=COALESCE(NULLIF(?, ''), city),
                instagram_handle=COALESCE(NULLIF(?, ''), instagram_handle),
                customer_type=?,
                marketing_channel=COALESCE(NULLIF(?, ''), marketing_channel),
                note=COALESCE(NULLIF(?, ''), note),
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                customer_name,
                contact_person,
                phone,
                email,
                city,
                instagram_handle,
                customer_type,
                marketing_channel,
                note,
                duplicate["id"],
            ),
        )
        reconcile_member_identity_duplicates(db, warehouse_id=warehouse_id)
        db.commit()
        flash("Customer dengan identitas yang sama ditemukan, data digabung ke kontak yang sudah ada.", "info")
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
    transaction_type = _normalize_transaction_type(request.form.get("transaction_type"))
    note = (request.form.get("note") or "").strip()

    customer = _get_customer_by_id(db, customer_id)
    if not customer:
        flash("Customer tidak valid untuk scope CRM ini.", "error")
        return _crm_redirect("purchases")

    if warehouse_id != customer["warehouse_id"]:
        flash("Gudang transaksi harus sama dengan gudang customer.", "error")
        return _crm_redirect("purchases")

    member = None
    member_snapshot = None
    selected_member = None
    selected_member_snapshot = None
    if member_id:
        selected_member = _get_member_by_id(db, member_id)
        if not selected_member or selected_member["customer_id"] != customer_id:
            flash("Member tidak valid untuk customer yang dipilih.", "error")
            return _crm_redirect("purchases")
        selected_member_snapshot = get_member_snapshot(db, member_id)
        member_type = _normalize_member_type(
            selected_member["member_type"] if "member_type" in selected_member.keys() else None
        )
        if member_type != "stringing" and transaction_type in {"stringing_service", "stringing_reward_redemption"}:
            flash("Jenis transaksi senaran hanya bisa dipakai untuk member senaran.", "error")
            return _crm_redirect("purchases")

    if not purchase_date:
        flash("Tanggal pembelian wajib valid.", "error")
        return _crm_redirect("purchases")

    total_amount = round(sum(item["line_total"] for item in items), 2)
    total_qty = sum(item["qty"] for item in items)
    max_retries = max(
        0,
        int(current_app.config.get("CRM_DB_LOCK_RETRY_ATTEMPTS", CRM_DB_LOCK_RETRY_ATTEMPTS) or 0),
    )
    retry_delay = max(
        0.0,
        float(
            current_app.config.get(
                "CRM_DB_LOCK_RETRY_DELAY_SECONDS",
                CRM_DB_LOCK_RETRY_DELAY_SECONDS,
            )
            or 0.0
        ),
    )

    for attempt in range(max_retries + 1):
        try:
            member = None
            member_snapshot = None
            db.execute("BEGIN IMMEDIATE")
            if selected_member:
                member = selected_member
                member_snapshot = selected_member_snapshot
            else:
                member, member_snapshot = _resolve_crm_purchase_member(
                    db,
                    customer,
                    transaction_type,
                    purchase_date,
                )
                if member:
                    member_id = member["id"]

            if transaction_type == "stringing_reward_redemption" and not member:
                raise ValueError("Free reward senaran hanya bisa dicatat untuk member yang valid.")

            cursor = db.execute(
                """
                INSERT INTO crm_purchase_records(
                    customer_id,
                    member_id,
                    warehouse_id,
                    purchase_date,
                    invoice_no,
                    channel,
                    transaction_type,
                    items_count,
                    total_amount,
                    note,
                    handled_by
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    customer_id,
                    member_id or None,
                    warehouse_id,
                    purchase_date,
                    invoice_no or None,
                    channel,
                    transaction_type,
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
                auto_record = build_auto_member_record(
                    member_snapshot or member,
                    member_snapshot or member,
                    purchase_id=purchase_id,
                    warehouse_id=warehouse_id,
                    record_date=purchase_date,
                    reference_no=invoice_no or None,
                    amount=total_amount,
                    transaction_type=transaction_type,
                    note=note,
                    handled_by=session.get("user_id"),
                    source_label="purchase CRM",
                )
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
                        service_count_delta,
                        reward_redeemed_delta,
                        benefit_value,
                        note,
                        handled_by
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        auto_record["member_id"],
                        auto_record["purchase_id"],
                        auto_record["warehouse_id"],
                        auto_record["record_date"],
                        auto_record["record_type"],
                        auto_record["reference_no"],
                        auto_record["amount"],
                        auto_record["points_delta"],
                        auto_record["service_count_delta"],
                        auto_record["reward_redeemed_delta"],
                        auto_record["benefit_value"],
                        auto_record["note"],
                        auto_record["handled_by"],
                    ),
                )

            db.commit()
            break
        except ValueError as exc:
            db.rollback()
            flash(str(exc), "error")
            return _crm_redirect("purchases")
        except sqlite3.OperationalError as exc:
            db.rollback()
            if _is_sqlite_lock_error(exc) and attempt < max_retries:
                current_app.logger.warning(
                    "CRM purchase save hit SQLite lock, retry %s/%s",
                    attempt + 1,
                    max_retries,
                )
                time.sleep(retry_delay)
                continue
            if _is_sqlite_lock_error(exc):
                current_app.logger.warning("CRM purchase save failed after SQLite lock retries")
                flash(
                    "Purchase record gagal disimpan karena database sedang sibuk di server. Coba ulang beberapa detik lagi.",
                    "error",
                )
                return _crm_redirect("purchases")
            flash("Purchase record gagal disimpan.", "error")
            return _crm_redirect("purchases")
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
    member_type = _normalize_member_type(request.form.get("member_type"))
    tier = _normalize_member_tier(request.form.get("tier"))
    status = _normalize_member_status(request.form.get("status"))
    join_date = _normalize_date(request.form.get("join_date"))
    expiry_date = _normalize_date(request.form.get("expiry_date"))
    points = _to_int(request.form.get("points"), 0)
    requested_by_staff_id = _to_int(request.form.get("requested_by_staff_id"), 0)
    reward_unit_amount = round(
        _to_float(
            request.form.get("reward_unit_amount"),
            DEFAULT_STRINGING_REWARD_AMOUNT,
        ),
        2,
    )
    opening_stringing_visits = max(_to_int(request.form.get("opening_stringing_visits"), 0), 0)
    opening_reward_redeemed = max(_to_int(request.form.get("opening_reward_redeemed"), 0), 0)
    benefit_note = (request.form.get("benefit_note") or "").strip()
    note = (request.form.get("note") or "").strip()

    customer = _get_customer_by_id(db, customer_id)
    if not customer:
        flash("Customer member tidak valid.", "error")
        return _crm_redirect("members")

    if not member_code or not join_date:
        flash("Kode member dan tanggal join wajib diisi.", "error")
        return _crm_redirect("members")

    requesting_staff = None
    if requested_by_staff_id:
        requesting_staff = _get_staff_by_id(db, requested_by_staff_id)
        if not requesting_staff or requesting_staff["role"] not in MEMBER_STAFF_ROLES:
            flash("Staff pengusul member tidak valid.", "error")
            return _crm_redirect("members")
        if requesting_staff.get("warehouse_id") and requesting_staff["warehouse_id"] != customer["warehouse_id"]:
            flash("Staff pengusul harus berasal dari gudang customer yang sama.", "error")
            return _crm_redirect("members")

    if reward_unit_amount <= 0:
        reward_unit_amount = DEFAULT_STRINGING_REWARD_AMOUNT

    if member_type != "stringing":
        opening_stringing_visits = 0
        opening_reward_redeemed = 0

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
            member_type,
            tier,
            status,
            join_date,
            expiry_date,
            points,
            requested_by_staff_id,
            reward_unit_amount,
            opening_stringing_visits,
            opening_reward_redeemed,
            benefit_note,
            note
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            customer_id,
            customer["warehouse_id"],
            member_code,
            member_type,
            tier,
            status,
            join_date,
            expiry_date,
            points,
            requesting_staff["id"] if requesting_staff else None,
            reward_unit_amount,
            opening_stringing_visits,
            opening_reward_redeemed,
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
    member_snapshot = get_member_snapshot(db, member_id) or build_member_snapshot_from_row(member)

    record_date = _normalize_date(request.form.get("record_date"))
    record_type = _normalize_member_record_type(request.form.get("record_type"))
    reference_no = (request.form.get("reference_no") or "").strip()
    amount = round(_to_float(request.form.get("amount"), 0), 2)
    points_delta = _to_int(request.form.get("points_delta"), 0)
    service_count_delta = _to_int(request.form.get("service_count_delta"), 0)
    reward_redeemed_delta = _to_int(request.form.get("reward_redeemed_delta"), 0)
    benefit_value = round(_to_float(request.form.get("benefit_value"), 0), 2)
    note = (request.form.get("note") or "").strip()

    if not record_date:
        flash("Tanggal record member wajib valid.", "error")
        return _crm_redirect("members")

    if member_snapshot["member_type"] != "stringing" and (
        record_type in {"stringing_service", "reward_redemption"}
        or service_count_delta
        or reward_redeemed_delta
    ):
        flash("Member pembelian tidak memakai progres senaran.", "error")
        return _crm_redirect("members")

    if record_type == "stringing_service" and service_count_delta <= 0:
        service_count_delta = 1

    if record_type == "reward_redemption":
        reward_redeemed_delta = reward_redeemed_delta or 1
        if benefit_value <= 0:
            benefit_value = member_snapshot["reward_unit_amount"]

    if benefit_value < 0:
        flash("Nilai benefit tidak boleh negatif.", "error")
        return _crm_redirect("members")

    if reward_redeemed_delta > 0 and member_snapshot["available_reward_count"] < reward_redeemed_delta:
        flash("Saldo free senar member ini tidak cukup untuk diredeem.", "error")
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
            service_count_delta,
            reward_redeemed_delta,
            benefit_value,
            note,
            handled_by
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            member_id,
            member["warehouse_id"],
            record_date,
            record_type,
            reference_no or None,
            amount,
            points_delta,
            service_count_delta,
            reward_redeemed_delta,
            benefit_value,
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
