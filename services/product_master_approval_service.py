import json

from services.rbac import normalize_role

PRODUCT_EDIT_APPROVAL_TYPE = "PRODUCT_EDIT"
PRODUCT_DELETE_APPROVAL_TYPE = "PRODUCT_DELETE"
PRODUCT_MASTER_APPROVAL_TYPES = {
    PRODUCT_EDIT_APPROVAL_TYPE,
    PRODUCT_DELETE_APPROVAL_TYPE,
}
PRODUCT_MASTER_APPROVER_ROLES = {"leader", "super_admin"}
PRODUCT_MASTER_DIRECT_ROLES = {"leader", "owner", "super_admin"}


def is_product_master_approval_type(value):
    return str(value or "").strip().upper() in PRODUCT_MASTER_APPROVAL_TYPES


def can_queue_product_master_approval(role):
    return normalize_role(role) == "admin"


def can_direct_manage_product_master(role):
    return normalize_role(role) in PRODUCT_MASTER_DIRECT_ROLES


def can_approve_product_master(role):
    return normalize_role(role) in PRODUCT_MASTER_APPROVER_ROLES


def payload_has_product_edit_changes(payload):
    payload = payload or {}
    current = payload.get("current") or {}
    target = payload.get("target") or {}
    fields = (
        "sku",
        "name",
        "category_name",
        "unit_label",
        "variant",
        "price_retail",
        "price_discount",
        "price_nett",
    )
    return any(
        _normalize_compare_value(current.get(field)) != _normalize_compare_value(target.get(field))
        for field in fields
    )


def find_pending_product_edit_approval(db, *, product_id, variant_id=0):
    try:
        product_id = int(product_id or 0)
    except (TypeError, ValueError):
        product_id = 0
    try:
        variant_id = int(variant_id or 0)
    except (TypeError, ValueError):
        variant_id = 0
    if not product_id:
        return None

    row = db.execute(
        """
        SELECT id, type, status, note, payload, requested_by, created_at
        FROM approvals
        WHERE type=? AND product_id=? AND variant_id=? AND status='pending'
        ORDER BY id DESC
        LIMIT 1
        """,
        (PRODUCT_EDIT_APPROVAL_TYPE, product_id, variant_id),
    ).fetchone()
    return dict(row) if row else None


def find_pending_product_delete_approvals(db, product_ids):
    cleaned_ids = []
    for raw_product_id in product_ids or []:
        try:
            normalized = int(raw_product_id or 0)
        except (TypeError, ValueError):
            normalized = 0
        if normalized and normalized not in cleaned_ids:
            cleaned_ids.append(normalized)

    if not cleaned_ids:
        return {}

    placeholders = ",".join(["?"] * len(cleaned_ids))
    rows = db.execute(
        f"""
        SELECT id, product_id, type, status, note, payload, requested_by, created_at
        FROM approvals
        WHERE type=? AND status='pending' AND product_id IN ({placeholders})
        ORDER BY id DESC
        """,
        (PRODUCT_DELETE_APPROVAL_TYPE, *cleaned_ids),
    ).fetchall()

    pending = {}
    for row in rows:
        mapped = dict(row)
        product_id = int(mapped.get("product_id") or 0)
        if product_id and product_id not in pending:
            pending[product_id] = mapped
    return pending


def load_product_snapshot(db, product_id, variant_id=0):
    try:
        product_id = int(product_id or 0)
    except (TypeError, ValueError):
        product_id = 0
    try:
        variant_id = int(variant_id or 0)
    except (TypeError, ValueError):
        variant_id = 0

    if not product_id:
        return None

    params = []
    variant_join = ""
    if variant_id:
        variant_join = "AND v.id = ?"
        params.append(variant_id)
    params.append(product_id)

    row = db.execute(
        f"""
        SELECT
            p.id AS product_id,
            p.sku,
            p.name,
            p.unit_label,
            p.variant_mode,
            COALESCE(c.name, '') AS category_name,
            v.id AS variant_id,
            COALESCE(v.variant, '') AS variant,
            COALESCE(v.price_retail, 0) AS price_retail,
            COALESCE(v.price_discount, 0) AS price_discount,
            COALESCE(v.price_nett, 0) AS price_nett,
            COALESCE(v.variant_code, '') AS variant_code,
            COALESCE(v.color, '') AS color,
            COALESCE(v.gtin, '') AS gtin
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        LEFT JOIN product_variants v ON v.product_id = p.id {variant_join}
        WHERE p.id = ?
        ORDER BY CASE WHEN LOWER(COALESCE(v.variant, '')) = 'default' THEN 0 ELSE 1 END, v.id
        LIMIT 1
        """,
        tuple(params),
    ).fetchone()

    if not row:
        return None
    return dict(row)


def build_product_edit_payload(db, *, product_id, variant_id=0, updates=None):
    snapshot = load_product_snapshot(db, product_id, variant_id)
    if not snapshot:
        raise ValueError("Produk tidak ditemukan")

    updates = updates or {}
    target = {
        "sku": str(updates.get("sku", snapshot.get("sku") or "")).strip(),
        "name": str(updates.get("name", snapshot.get("name") or "")).strip(),
        "category_name": str(updates.get("category_name", snapshot.get("category_name") or "")).strip(),
        "unit_label": " ".join(str(updates.get("unit_label", snapshot.get("unit_label") or "pcs")).strip().split()) or "pcs",
        "variant": str(updates.get("variant", snapshot.get("variant") or "")).strip(),
        "price_retail": _to_float(updates.get("price_retail", snapshot.get("price_retail") or 0)),
        "price_discount": _to_float(updates.get("price_discount", snapshot.get("price_discount") or 0)),
        "price_nett": _to_float(updates.get("price_nett", snapshot.get("price_nett") or 0)),
    }

    payload = {
        "product_id": int(snapshot.get("product_id") or product_id or 0),
        "variant_id": int(snapshot.get("variant_id") or variant_id or 0),
        "current": {
            "sku": str(snapshot.get("sku") or "").strip(),
            "name": str(snapshot.get("name") or "").strip(),
            "category_name": str(snapshot.get("category_name") or "").strip(),
            "unit_label": str(snapshot.get("unit_label") or "pcs").strip(),
            "variant": str(snapshot.get("variant") or "").strip(),
            "price_retail": _to_float(snapshot.get("price_retail") or 0),
            "price_discount": _to_float(snapshot.get("price_discount") or 0),
            "price_nett": _to_float(snapshot.get("price_nett") or 0),
        },
        "target": target,
    }
    return payload


def summarize_product_edit_payload(payload):
    payload = payload or {}
    current = payload.get("current") or {}
    target = payload.get("target") or {}
    labels = {
        "sku": "SKU",
        "name": "Nama",
        "category_name": "Kategori",
        "unit_label": "Satuan",
        "variant": "Variant",
        "price_retail": "Retail",
        "price_discount": "Discount",
        "price_nett": "Nett",
    }

    changes = []
    for key, label in labels.items():
        current_value = _normalize_compare_value(current.get(key))
        target_value = _normalize_compare_value(target.get(key))
        if current_value == target_value:
            continue
        if key.startswith("price_"):
            target_display = f"Rp {_format_money(target.get(key))}"
        else:
            target_display = str(target.get(key) or "-").strip() or "-"
        changes.append(f"{label}: {target_display}")

    if not changes:
        return "Edit detail produk"
    return "Edit produk -> " + ", ".join(changes[:4])


def queue_product_edit_approval(db, *, warehouse_id, requested_by, payload):
    note = summarize_product_edit_payload(payload)
    cursor = db.execute(
        """
        INSERT INTO approvals(type, product_id, variant_id, warehouse_id, qty, note, payload, requested_by)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            PRODUCT_EDIT_APPROVAL_TYPE,
            int(payload.get("product_id") or 0),
            int(payload.get("variant_id") or 0),
            int(warehouse_id or 0),
            None,
            note,
            json.dumps(payload, ensure_ascii=True, sort_keys=True),
            int(requested_by or 0),
        ),
    )
    return cursor.lastrowid


def queue_product_delete_approvals(db, *, warehouse_id, requested_by, product_ids):
    approval_ids = []
    for raw_product_id in product_ids or []:
        snapshot = load_product_snapshot(db, raw_product_id)
        if not snapshot:
            continue
        payload = {
            "product_id": int(snapshot.get("product_id") or raw_product_id or 0),
            "variant_id": 0,
            "current": snapshot,
        }
        cursor = db.execute(
            """
            INSERT INTO approvals(type, product_id, variant_id, warehouse_id, qty, note, payload, requested_by)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                PRODUCT_DELETE_APPROVAL_TYPE,
                int(snapshot.get("product_id") or raw_product_id or 0),
                0,
                int(warehouse_id or 0),
                None,
                f"Hapus produk {snapshot.get('sku') or '-'} - {snapshot.get('name') or 'Tanpa Nama'}",
                json.dumps(payload, ensure_ascii=True, sort_keys=True),
                int(requested_by or 0),
            ),
        )
        approval_ids.append(cursor.lastrowid)
    return approval_ids


def parse_product_master_payload(raw_payload):
    if isinstance(raw_payload, dict):
        return raw_payload
    try:
        parsed = json.loads(str(raw_payload or "").strip() or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_product_master_context(db, approval_row):
    approval_row = dict(approval_row or {})
    payload = parse_product_master_payload(approval_row.get("payload"))
    snapshot = load_product_snapshot(
        db,
        payload.get("product_id") or approval_row.get("product_id"),
        payload.get("variant_id") or approval_row.get("variant_id"),
    )
    current = payload.get("current") or {}
    target = payload.get("target") or {}
    source = snapshot or current or target
    variant_value = (
        (snapshot or {}).get("variant")
        or current.get("variant")
        or target.get("variant")
        or ""
    )
    variant_name = str(variant_value or "").strip()
    if not variant_name:
        variant_name = "-"
    elif variant_name.lower() == "default":
        variant_name = "Default"

    return {
        "sku": str((snapshot or {}).get("sku") or current.get("sku") or target.get("sku") or "").strip(),
        "product_name": str((snapshot or {}).get("name") or current.get("name") or target.get("name") or "").strip(),
        "variant_name": variant_name,
        "warehouse_name": str(approval_row.get("warehouse_name") or "").strip(),
        "payload": payload,
        "summary_note": summarize_product_edit_payload(payload)
        if is_product_master_approval_type(approval_row.get("type")) and str(approval_row.get("type") or "").upper() == PRODUCT_EDIT_APPROVAL_TYPE
        else str(approval_row.get("note") or "").strip(),
        "category_name": str(source.get("category_name") or "").strip(),
        "unit_label": str(source.get("unit_label") or "").strip(),
    }


def apply_product_edit_approval(db, approval_row):
    payload = parse_product_master_payload(approval_row.get("payload"))
    product_id = int(payload.get("product_id") or approval_row.get("product_id") or 0)
    variant_id = int(payload.get("variant_id") or approval_row.get("variant_id") or 0)
    target = payload.get("target") or {}

    if not product_id:
        raise ValueError("Produk tidak valid")

    sku = str(target.get("sku") or "").strip()
    name = str(target.get("name") or "").strip()
    category_name = str(target.get("category_name") or "").strip()
    unit_label = " ".join(str(target.get("unit_label") or "pcs").strip().split()) or "pcs"
    variant = str(target.get("variant") or "").strip()
    price_retail = _to_float(target.get("price_retail") or 0)
    price_discount = _to_float(target.get("price_discount") or 0)
    price_nett = _to_float(target.get("price_nett") or 0)

    if not sku or not name or not category_name or not unit_label:
        raise ValueError("Payload edit produk tidak lengkap")
    if min(price_retail, price_discount, price_nett) < 0:
        raise ValueError("Harga tidak boleh minus")

    duplicate = db.execute(
        "SELECT id FROM products WHERE sku=? AND id!=?",
        (sku, product_id),
    ).fetchone()
    if duplicate:
        raise ValueError("SKU sudah dipakai produk lain")

    category_id = _resolve_category_id(db, category_name)
    db.execute(
        "UPDATE products SET sku=?, name=?, category_id=?, unit_label=? WHERE id=?",
        (sku, name, category_id, unit_label, product_id),
    )

    if variant_id:
        if not variant:
            raise ValueError("Variant wajib diisi untuk detail produk ini")
        db.execute(
            """
            UPDATE product_variants
            SET variant=?, price_retail=?, price_discount=?, price_nett=?
            WHERE id=? AND product_id=?
            """,
            (variant, price_retail, price_discount, price_nett, variant_id, product_id),
        )
    return True


def apply_product_delete_approval(db, approval_row):
    payload = parse_product_master_payload(approval_row.get("payload"))
    product_id = int(payload.get("product_id") or approval_row.get("product_id") or 0)
    approval_id = int(approval_row.get("id") or 0)
    if not product_id:
        raise ValueError("Produk tidak valid")

    return _delete_product_bundle(
        db,
        [product_id],
        preserve_approval_ids=[approval_id] if approval_id else None,
    )


def _delete_product_bundle(db, product_ids, preserve_approval_ids=None):
    cleaned_ids = []
    for product_id in product_ids or []:
        try:
            normalized = int(product_id or 0)
        except (TypeError, ValueError):
            normalized = 0
        if normalized and normalized not in cleaned_ids:
            cleaned_ids.append(normalized)

    if not cleaned_ids:
        return 0

    placeholders = ",".join(["?"] * len(cleaned_ids))
    params = list(cleaned_ids)

    db.execute(f"DELETE FROM requests WHERE product_id IN ({placeholders})", params)

    preserved_ids = []
    for approval_id in preserve_approval_ids or []:
        try:
            normalized = int(approval_id or 0)
        except (TypeError, ValueError):
            normalized = 0
        if normalized:
            preserved_ids.append(normalized)

    if preserved_ids:
        approval_placeholders = ",".join(["?"] * len(preserved_ids))
        db.execute(
            f"DELETE FROM approvals WHERE product_id IN ({placeholders}) AND id NOT IN ({approval_placeholders})",
            tuple(params + preserved_ids),
        )
    else:
        db.execute(f"DELETE FROM approvals WHERE product_id IN ({placeholders})", params)

    db.execute(f"DELETE FROM stock_movements WHERE product_id IN ({placeholders})", params)
    db.execute(f"DELETE FROM stock_history WHERE product_id IN ({placeholders})", params)
    db.execute(f"DELETE FROM stock_batches WHERE product_id IN ({placeholders})", params)
    db.execute(f"DELETE FROM stock WHERE product_id IN ({placeholders})", params)
    db.execute(f"DELETE FROM product_variants WHERE product_id IN ({placeholders})", params)
    result = db.execute(f"DELETE FROM products WHERE id IN ({placeholders})", params)
    return result.rowcount if result.rowcount is not None else 0


def _resolve_category_id(db, category_name):
    category_name = str(category_name or "").strip()
    row = db.execute("SELECT id FROM categories WHERE name=?", (category_name,)).fetchone()
    if row:
        return row["id"]
    cursor = db.execute("INSERT INTO categories(name) VALUES (?)", (category_name,))
    return cursor.lastrowid


def _to_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_compare_value(value):
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return str(value or "").strip()


def _format_money(value):
    return f"{round(_to_float(value)):,}".replace(",", ".")
