import json

from flask import Blueprint, render_template, request, redirect, flash, session
from database import get_db
from services.request_service import approve_request
from services.notification_service import notify_operational_event, notify_roles, notify_user
from services.rbac import has_permission, is_scoped_role
import os

try:
    import requests as http_requests
except ImportError:
    http_requests = None

request_bp = Blueprint(
    "request",
    __name__,
    url_prefix="/request"
)


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_request_items(form):
    raw_payload = (form.get("items_json") or "").strip()
    if raw_payload:
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("Format item request tidak valid") from exc

        if not isinstance(payload, list):
            raise ValueError("Format item request tidak valid")

        items = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            product_id = _to_int(item.get("product_id"), 0)
            variant_id = _to_int(item.get("variant_id"), 0)
            qty = _to_int(item.get("qty"), 0)
            display_name = (item.get("display_name") or "").strip()

            if not any([product_id, variant_id, qty, display_name]):
                continue

            if product_id <= 0 or variant_id <= 0 or qty <= 0:
                raise ValueError("Ada item request yang belum lengkap atau qty tidak valid")

            items.append({
                "product_id": product_id,
                "variant_id": variant_id,
                "qty": qty,
                "display_name": display_name,
            })

        if not items:
            raise ValueError("Minimal tambahkan satu item request")

        return items

    product_id = _to_int(form.get("product_id"), 0)
    variant_id = _to_int(form.get("variant_id"), 0)
    qty = _to_int(form.get("qty"), 0)

    if product_id <= 0 or variant_id <= 0 or qty <= 0:
        raise ValueError("Input tidak valid")

    return [{
        "product_id": product_id,
        "variant_id": variant_id,
        "qty": qty,
        "display_name": "",
    }]


def _parse_owner_request_items(form):
    raw_payload = (form.get("items_json") or "").strip()
    if raw_payload:
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("Format item request owner tidak valid") from exc

        if not isinstance(payload, list):
            raise ValueError("Format item request owner tidak valid")

        items = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            product_id = _to_int(item.get("product_id"), 0)
            variant_id = _to_int(item.get("variant_id"), 0)
            qty = _to_int(item.get("qty"), 0)
            note = (item.get("note") or "").strip()
            display_name = (item.get("display_name") or "").strip()

            if not any([product_id, variant_id, qty, note, display_name]):
                continue

            if product_id <= 0 or variant_id <= 0 or qty <= 0:
                raise ValueError("Ada item request owner yang belum lengkap atau qty tidak valid")

            items.append({
                "product_id": product_id,
                "variant_id": variant_id,
                "qty": qty,
                "note": note,
                "display_name": display_name,
            })

        if not items:
            raise ValueError("Minimal tambahkan satu item request owner")

        return items

    product_id = _to_int(form.get("product_id"), 0)
    variant_id = _to_int(form.get("variant_id"), 0)
    qty = _to_int(form.get("qty"), 0)
    note = (form.get("note") or "").strip()

    if product_id <= 0 or variant_id <= 0 or qty <= 0:
        raise ValueError("Input tidak valid")

    return [{
        "product_id": product_id,
        "variant_id": variant_id,
        "qty": qty,
        "note": note,
        "display_name": "",
    }]


def _fetch_request_item_record(db, product_id, variant_id):
    return db.execute("""
        SELECT
            p.id AS product_id,
            v.id AS variant_id,
            p.sku,
            p.name,
            COALESCE(v.variant, 'default') AS variant
        FROM products p
        JOIN product_variants v ON v.product_id = p.id
        WHERE p.id=? AND v.id=?
    """, (product_id, variant_id)).fetchone()


def _format_request_item_label(record):
    variant = record["variant"] or "default"
    variant_label = "Default" if str(variant).lower() == "default" else variant
    return f'{record["sku"]} - {record["name"]} / {variant_label}'


def _get_request_available_stock(db, product_id, variant_id, warehouse_id):
    row = db.execute("""
        SELECT COALESCE(qty, 0) AS qty
        FROM stock
        WHERE product_id=? AND variant_id=? AND warehouse_id=?
    """, (product_id, variant_id, warehouse_id)).fetchone()
    return row["qty"] if row else 0


def _fetch_request_row(db, request_id):
    return db.execute("""
        SELECT
            r.*,
            p.sku,
            p.name AS product_name,
            COALESCE(v.variant, 'default') AS variant,
            w1.name AS from_name,
            w2.name AS to_name
        FROM requests r
        LEFT JOIN products p ON r.product_id = p.id
        LEFT JOIN product_variants v ON r.variant_id = v.id
        LEFT JOIN warehouses w1 ON r.from_warehouse = w1.id
        LEFT JOIN warehouses w2 ON r.to_warehouse = w2.id
        WHERE r.id=?
    """, (request_id,)).fetchone()


def _notify_request_requester(request_row, verb):
    if not request_row or not request_row["requested_by"]:
        return

    variant = request_row["variant"] or "default"
    variant_label = "Default" if str(variant).lower() == "default" else variant
    reason = (request_row["reason"] or "").strip()
    reason_line = f"\nAlasan: {reason}" if reason else ""

    notify_user(
        request_row["requested_by"],
        f"Request antar gudang #{request_row['id']} {verb}",
        (
            f"Request {request_row['sku']} - {request_row['product_name']} / {variant_label} "
            f"sebanyak {request_row['qty']} item dari {request_row['from_name']} ke {request_row['to_name']} "
            f"telah {verb}.{reason_line}"
        ),
        category="request",
        link_url="/request/",
        source_type="warehouse_request",
        source_id=str(request_row["id"]),
    )


def can_approve_request():
    return has_permission(session.get("role"), "approve_requests")


def get_request_scope():
    role = session.get("role")
    warehouse_id = session.get("warehouse_id")

    if is_scoped_role(role) and warehouse_id:
        return warehouse_id

    return None


def _get_locked_request_direction(db):
    destination_warehouse = get_request_scope()
    if not destination_warehouse:
        return None, None

    to_warehouse = db.execute(
        "SELECT id, name FROM warehouses WHERE id=?",
        (destination_warehouse,),
    ).fetchone()
    from_warehouse = db.execute(
        "SELECT id, name FROM warehouses WHERE id<>? ORDER BY id ASC LIMIT 1",
        (destination_warehouse,),
    ).fetchone()

    return from_warehouse, to_warehouse


def can_manage_owner_request():
    return session.get("role") in {"owner", "super_admin"}


def get_owner_request_scope():
    role = session.get("role")
    warehouse_id = session.get("warehouse_id")

    if is_scoped_role(role) and warehouse_id:
        return warehouse_id

    return None


def _fetch_owner_request_rows(db):
    scope = get_owner_request_scope()

    base_query = """
        SELECT
            r.*,
            p.sku,
            p.name AS product_name,
            COALESCE(v.variant, 'default') AS variant,
            w.name AS warehouse_name,
            u.username AS requester_name,
            h.username AS handler_name
        FROM owner_requests r
        JOIN products p ON r.product_id = p.id
        JOIN product_variants v ON r.variant_id = v.id
        JOIN warehouses w ON r.warehouse_id = w.id
        LEFT JOIN users u ON r.requested_by = u.id
        LEFT JOIN users h ON r.handled_by = h.id
    """

    if scope:
        rows = db.execute(
            base_query + " WHERE r.warehouse_id=? ORDER BY r.id DESC",
            (scope,),
        ).fetchall()
    else:
        rows = db.execute(
            base_query + " ORDER BY r.id DESC"
        ).fetchall()

    return [dict(row) for row in rows]


# ==========================
# WA NOTIFICATION
# ==========================
def send_wa(product_name, variant, qty, from_wh, to_wh):
    api_key = os.getenv("FONNTE_API_KEY")
    target = os.getenv("FONNTE_TARGET")

    if not api_key or not target or http_requests is None:
        return False

    try:
        url = "https://api.fonnte.com/send"

        headers = {
            "Authorization": api_key
        }

        message = f"""
🔥 REQUEST BARU

Produk : {product_name}
Variant : {variant}
Qty : {qty}

Dari : {from_wh}
Ke : {to_wh}
"""

        data = {
            "target": target,
            "message": message
        }

        http_requests.post(url, headers=headers, data=data, timeout=5)
        return True

    except Exception as e:
        print("WA ERROR:", e)
        return False


# ==========================
# CHECK NOTIF (FIX GHOST)
# ==========================
@request_bp.route("/check_new")
def check_new():

    db = get_db()

    try:
        last_id = int(request.args.get("last_id", 0))
    except:
        last_id = 0

    try:
        session_last_seen = int(session.get("request_last_seen_id", 0) or 0)
    except:
        session_last_seen = 0

    baseline_id = max(last_id, session_last_seen)
    session["request_last_seen_id"] = baseline_id

    warehouse_id = get_request_scope()

    if not warehouse_id:
        return {"status": "no"}

    # 🔥 AMBIL NEXT ID (ASC, BUKAN DESC)
    row = db.execute("""
    SELECT id, qty
    FROM requests
    WHERE id > ?
    AND status = 'pending'
    AND (from_warehouse=? OR to_warehouse=?)
    ORDER BY id ASC
    LIMIT 1
    """, (baseline_id, warehouse_id, warehouse_id)).fetchone()

    if not row:
        return {"status": "no"}

    session["request_last_seen_id"] = row["id"]

    return {
        "status": "yes",
        "id": row["id"],
        "qty": row["qty"]
    }


# ==========================
# MAIN REQUEST
# ==========================
@request_bp.route("/", methods=["GET", "POST"])
def request_barang():

    db = get_db()

    if request.method == "POST":

        try:
            items = _parse_request_items(request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect("/request")
        except Exception:
            flash("Input tidak valid", "error")
            return redirect("/request")

        locked_from, locked_to = _get_locked_request_direction(db)
        if locked_to:
            if not locked_from:
                flash("Request antar gudang belum bisa dipakai karena gudang lawan belum tersedia", "error")
                return redirect("/request")
            from_wh = locked_from["id"]
            to_wh = locked_to["id"]
        else:
            from_wh = _to_int(request.form.get("from_warehouse"))
            to_wh = _to_int(request.form.get("to_warehouse"))

        if from_wh == to_wh:
            flash("Gudang tidak boleh sama", "error")
            return redirect("/request")

        w1 = db.execute("SELECT id, name FROM warehouses WHERE id=?", (from_wh,)).fetchone()
        w2 = db.execute("SELECT id, name FROM warehouses WHERE id=?", (to_wh,)).fetchone()

        if not w1 or not w2:
            flash("Data tidak valid", "error")
            return redirect("/request")

        # scoped users always request stock into their own warehouse from the counterpart warehouse
        role = session.get("role")
        user_wh = session.get("warehouse_id")
        if is_scoped_role(role) and to_wh != user_wh:
            flash("Tidak punya akses untuk membuat request ke gudang ini", "error")
            return redirect("/request")

        aggregates = {}
        labels = {}

        for item in items:
            record = _fetch_request_item_record(
                db,
                item["product_id"],
                item["variant_id"],
            )
            if not record:
                flash("Produk / variant tidak valid", "error")
                return redirect("/request")

            key = (item["product_id"], item["variant_id"])
            aggregates[key] = aggregates.get(key, 0) + item["qty"]
            labels[key] = _format_request_item_label(record)

        for (product_id, variant_id), total_qty in aggregates.items():
            available_qty = _get_request_available_stock(
                db,
                product_id,
                variant_id,
                from_wh,
            )
            if available_qty < total_qty:
                flash(f"Stok tidak cukup untuk {labels[(product_id, variant_id)]}", "error")
                return redirect("/request")

        try:
            db.execute("BEGIN")

            for item in items:
                db.execute("""
                    INSERT INTO requests(
                        product_id,
                        variant_id,
                        from_warehouse,
                        to_warehouse,
                        qty,
                        status,
                        created_at,
                        requested_by
                    )
                    VALUES (?,?,?,?,?,'pending',datetime('now'),?)
                """, (
                    item["product_id"],
                    item["variant_id"],
                    from_wh,
                    to_wh,
                    item["qty"],
                    session.get("user_id"),
                ))

            db.commit()

            subj = f"Request Baru: {len(items)} item"
            msg = (
                f"Request baru sebanyak {len(items)} item\n"
                f"Dari: {w1['name']}\n"
                f"Ke: {w2['name']}"
            )
            try:
                notify_roles(
                    ["leader", "owner", "super_admin"],
                    subj,
                    msg,
                    warehouse_id=from_wh,
                    category="request",
                    link_url="/request/",
                    source_type="warehouse_request",
                )
            except Exception as e:
                print("NOTIFY ERROR:", e)

            flash(f"{len(items)} request berhasil dibuat", "success")
        except Exception as exc:
            db.rollback()
            print("REQUEST BULK ERROR:", exc)
            flash("Gagal membuat request", "error")

        return redirect("/request")

    warehouses = db.execute("""
        SELECT * FROM warehouses ORDER BY name
    """).fetchall()

    warehouse_id = session.get("warehouse_id")
    warehouse_scope = get_request_scope()
    locked_from, locked_to = _get_locked_request_direction(db)

    if warehouse_scope:
        rows = db.execute("""
        SELECT 
            r.*,
            p.name as product_name,
            v.variant,
            w1.name as from_name,
            w2.name as to_name
        FROM requests r
        JOIN products p ON r.product_id = p.id
        JOIN product_variants v ON r.variant_id = v.id
        JOIN warehouses w1 ON r.from_warehouse = w1.id
        JOIN warehouses w2 ON r.to_warehouse = w2.id
        WHERE (r.from_warehouse=? OR r.to_warehouse=?)
        ORDER BY r.id DESC
        """, (warehouse_scope, warehouse_scope)).fetchall()
    else:
        rows = db.execute("""
        SELECT 
            r.*,
            p.name as product_name,
            v.variant,
            w1.name as from_name,
            w2.name as to_name
        FROM requests r
        JOIN products p ON r.product_id = p.id
        JOIN product_variants v ON r.variant_id = v.id
        JOIN warehouses w1 ON r.from_warehouse = w1.id
        JOIN warehouses w2 ON r.to_warehouse = w2.id
        ORDER BY r.id DESC
        """).fetchall()

    requests_data = []
    for row in rows:
        item = dict(row)
        item["can_approve"] = can_approve_request() and (
            not warehouse_scope or item["from_warehouse"] == warehouse_scope
        )
        requests_data.append(item)

    return render_template(
        "request.html",
        warehouses=warehouses,
        requests=requests_data,
        warehouse_id=warehouse_id,
        request_locked_from_id=locked_from["id"] if locked_from else None,
        request_locked_to_id=locked_to["id"] if locked_to else None,
    )


@request_bp.route("/owner", methods=["GET", "POST"])
def request_owner_barang():

    db = get_db()

    if request.method == "POST":

        try:
            warehouse_id = _to_int(request.form.get("warehouse_id"))
            items = _parse_owner_request_items(request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect("/request/owner")
        except Exception:
            flash("Input tidak valid", "error")
            return redirect("/request/owner")

        role = session.get("role")
        user_wh = session.get("warehouse_id")

        if is_scoped_role(role):
            warehouse_id = user_wh or warehouse_id

        warehouse = db.execute(
            "SELECT id, name FROM warehouses WHERE id=?",
            (warehouse_id,),
        ).fetchone()

        if not warehouse:
            flash("Gudang tidak valid", "error")
            return redirect("/request/owner")

        if is_scoped_role(role) and warehouse_id != user_wh:
            flash("Tidak punya akses ke gudang ini", "error")
            return redirect("/request/owner")

        labels = []
        for item in items:
            record = _fetch_request_item_record(
                db,
                item["product_id"],
                item["variant_id"],
            )
            if not record:
                flash("Produk / variant tidak valid", "error")
                return redirect("/request/owner")
            labels.append(_format_request_item_label(record))

        try:
            db.execute("BEGIN")

            for item in items:
                db.execute("""
                    INSERT INTO owner_requests(
                        product_id,
                        variant_id,
                        warehouse_id,
                        qty,
                        note,
                        status,
                        requested_by
                    )
                    VALUES (?,?,?,?,?,'pending',?)
                """, (
                    item["product_id"],
                    item["variant_id"],
                    warehouse_id,
                    item["qty"],
                    item["note"],
                    session.get("user_id"),
                ))

            db.commit()

            subject = f"Request Khusus ke Owner: {len(items)} item"
            message = (
                f"Ada request khusus ke owner sebanyak {len(items)} item.\n"
                f"Gudang: {warehouse['name']}\n"
                f"Item pertama: {labels[0]}"
            )
            try:
                notify_roles(
                    ["owner"],
                    subject,
                    message,
                    category="owner_request",
                    link_url="/request/owner",
                    source_type="owner_request",
                )
            except Exception as exc:
                print("OWNER REQUEST NOTIFY ERROR:", exc)

            flash(f"{len(items)} request ke owner berhasil dikirim", "success")
        except Exception as exc:
            db.rollback()
            print("OWNER REQUEST ERROR:", exc)
            flash("Gagal membuat request ke owner", "error")

        return redirect("/request/owner")

    warehouses = db.execute("""
        SELECT * FROM warehouses ORDER BY name
    """).fetchall()

    return render_template(
        "request_owner.html",
        warehouses=warehouses,
        requests=_fetch_owner_request_rows(db),
        warehouse_id=session.get("warehouse_id"),
        can_manage_owner_request=can_manage_owner_request(),
    )


@request_bp.route("/owner/update/<int:id>", methods=["POST"])
def update_owner_request(id):

    if not can_manage_owner_request():
        flash("Tidak punya akses", "error")
        return redirect("/request/owner")

    status = (request.form.get("status") or "").strip().lower()
    allowed_statuses = {
        "in_progress": "Diproses",
        "done": "Selesai",
        "rejected": "Ditolak",
    }

    if status not in allowed_statuses:
        flash("Status tidak valid", "error")
        return redirect("/request/owner")

    db = get_db()
    owner_request = db.execute("""
        SELECT id, requested_by, status
        FROM owner_requests
        WHERE id=?
    """, (id,)).fetchone()

    if not owner_request:
        flash("Request owner tidak ditemukan", "error")
        return redirect("/request/owner")

    try:
        db.execute("""
            UPDATE owner_requests
            SET status=?,
                handled_by=?,
                handled_at=datetime('now')
            WHERE id=?
        """, (
            status,
            session.get("user_id"),
            id,
        ))
        db.commit()

        try:
            if owner_request["requested_by"]:
                notify_user(
                    owner_request["requested_by"],
                    f"Request ke owner #{id} {allowed_statuses[status]}",
                    f"Request ke owner dengan ID #{id} telah diubah menjadi status {allowed_statuses[status]}.",
                    category="owner_request",
                    link_url="/request/owner",
                    source_type="owner_request",
                    source_id=str(id),
                )
        except Exception as exc:
            print("OWNER REQUEST USER NOTIFY ERROR:", exc)

        flash(f"Request owner berhasil diubah menjadi {allowed_statuses[status]}", "success")
    except Exception as exc:
        db.rollback()
        print("OWNER REQUEST UPDATE ERROR:", exc)
        flash("Gagal mengubah status request owner", "error")

    return redirect("/request/owner")


# ==========================
# APPROVE
# ==========================
@request_bp.route("/approve/<int:id>", methods=["POST"])
def approve_request_route(id):

    if not can_approve_request():
        flash("Tidak punya akses", "error")
        return redirect("/request")

    db = get_db()
    req = _fetch_request_row(db, id)

    if not req:
        flash("Request tidak ditemukan", "error")
        return redirect("/request")

    warehouse_scope = get_request_scope()
    if warehouse_scope and warehouse_scope != req["from_warehouse"]:
        flash("Hanya leader gudang pengirim yang bisa approve request ini", "error")
        return redirect("/request")

    success = approve_request(id)
    updated_request = _fetch_request_row(db, id)

    if success:
        try:
            if updated_request:
                variant_label = (
                    "Default"
                    if str(updated_request["variant"]).lower() == "default"
                    else updated_request["variant"]
                )
                notify_operational_event(
                    f"Transfer antar gudang diproses: {updated_request['sku']}",
                    (
                        f"{updated_request['sku']} - {updated_request['product_name']} / {variant_label} "
                        f"sebanyak {updated_request['qty']} item dipindahkan dari "
                        f"{updated_request['from_name']} ke {updated_request['to_name']}."
                    ),
                    warehouse_id=updated_request["from_warehouse"],
                    category="inventory",
                    link_url="/request/",
                    source_type="warehouse_transfer",
                    source_id=str(updated_request["id"]),
                    push_title="Transfer antar gudang",
                    push_body=(
                        f"{updated_request['sku']} | "
                        f"{updated_request['from_name']} -> {updated_request['to_name']}"
                    ),
                )
        except Exception as exc:
            print("REQUEST TRANSFER NOTIFICATION ERROR:", exc)

        try:
            _notify_request_requester(updated_request, "disetujui")
        except Exception as exc:
            print("REQUEST APPROVE USER NOTIFY ERROR:", exc)
        flash("Request disetujui", "success")
    elif updated_request and updated_request["status"] == "rejected":
        try:
            _notify_request_requester(updated_request, "ditolak")
        except Exception as exc:
            print("REQUEST AUTO REJECT USER NOTIFY ERROR:", exc)
        flash(updated_request["reason"] or "Request ditolak", "error")
    else:
        flash("Gagal approve", "error")

    return redirect("/request")


@request_bp.route("/reject/<int:id>", methods=["POST"])
def reject_request_route(id):

    if not can_approve_request():
        flash("Tidak punya akses", "error")
        return redirect("/request")

    db = get_db()
    req = _fetch_request_row(db, id)

    if not req:
        flash("Request tidak ditemukan", "error")
        return redirect("/request")

    warehouse_scope = get_request_scope()
    if warehouse_scope and warehouse_scope != req["from_warehouse"]:
        flash("Hanya leader gudang pengirim yang bisa menolak request ini", "error")
        return redirect("/request")

    if req["status"] != "pending":
        flash("Request ini sudah diproses", "error")
        return redirect("/request")

    reason = (request.form.get("reason") or "").strip() or "Ditolak oleh approver"

    try:
        db.execute(
            """
            UPDATE requests
            SET status='rejected',
                reason=?,
                approved_at=datetime('now'),
                approved_by=?
            WHERE id=? AND status='pending'
            """,
            (reason, session.get("user_id"), id),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        print("REQUEST REJECT ERROR:", exc)
        flash("Gagal menolak request", "error")
        return redirect("/request")

    updated_request = _fetch_request_row(db, id)
    try:
        _notify_request_requester(updated_request, "ditolak")
    except Exception as exc:
        print("REQUEST REJECT USER NOTIFY ERROR:", exc)

    flash("Request ditolak", "success")
    return redirect("/request")
