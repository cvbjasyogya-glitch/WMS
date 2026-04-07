import json

from flask import Blueprint, render_template, request, redirect, flash, session

from database import get_db
from services.event_notification_policy import get_event_notification_policy
from services.notification_service import notify_operational_event, notify_roles
from services.rbac import has_permission, is_scoped_role
from services.stock_service import remove_stock
from services.whatsapp_service import send_role_based_notification

outbound_bp = Blueprint(
    "outbound",
    __name__,
    url_prefix="/outbound"
)


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_outbound_items(form):
    raw_payload = (form.get("items_json") or "").strip()
    if raw_payload:
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("Format item outbound tidak valid") from exc

        if not isinstance(payload, list):
            raise ValueError("Format item outbound tidak valid")

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
                raise ValueError("Ada baris outbound yang belum lengkap atau qty tidak valid")

            items.append({
                "product_id": product_id,
                "variant_id": variant_id,
                "qty": qty,
                "note": note or "Barang Keluar",
                "display_name": display_name,
            })

        if not items:
            raise ValueError("Minimal pilih satu item outbound")

        return items

    product_id = _to_int(form.get("product_id"), 0)
    variant_id = _to_int(form.get("variant_id"), 0)
    qty = _to_int(form.get("qty"), 0)
    note = (form.get("note") or "").strip() or "Barang Keluar"

    if product_id <= 0 or variant_id <= 0 or qty <= 0:
        raise ValueError("Input tidak valid")

    return [{
        "product_id": product_id,
        "variant_id": variant_id,
        "qty": qty,
        "note": note,
        "display_name": "",
    }]


def _fetch_item_record(db, product_id, variant_id):
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


def _format_item_label(record):
    variant = record["variant"] or "default"
    variant_label = "Default" if str(variant).lower() == "default" else variant
    return f'{record["sku"]} - {record["name"]} / {variant_label}'


def _get_available_stock(db, product_id, variant_id, warehouse_id):
    row = db.execute("""
        SELECT COALESCE(qty, 0) AS qty
        FROM stock
        WHERE product_id=? AND variant_id=? AND warehouse_id=?
    """, (product_id, variant_id, warehouse_id)).fetchone()
    return row["qty"] if row else 0


@outbound_bp.route("/", methods=["GET", "POST"])
def outbound():

    db = get_db()

    if request.method == "POST":

        try:
            warehouse_id = _to_int(request.form.get("warehouse_id"), 0)
            items = _parse_outbound_items(request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect("/outbound")
        except Exception:
            flash("Input tidak valid", "error")
            return redirect("/outbound")

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
            return redirect("/outbound")

        if is_scoped_role(role) and warehouse_id != user_wh:
            flash("Tidak punya akses ke gudang ini", "error")
            return redirect("/outbound")

        try:
            if has_permission(role, "direct_stock_ops"):
                db.execute("BEGIN")

                processed = 0
                first_label = ""
                for item in items:
                    record = _fetch_item_record(
                        db,
                        item["product_id"],
                        item["variant_id"],
                    )
                    if not record:
                        raise Exception("Produk / variant tidak valid")

                    available_qty = _get_available_stock(
                        db,
                        item["product_id"],
                        item["variant_id"],
                        warehouse_id,
                    )
                    if available_qty < item["qty"]:
                        raise Exception(f'Stok tidak cukup untuk {_format_item_label(record)}')

                    if not remove_stock(
                        item["product_id"],
                        item["variant_id"],
                        warehouse_id,
                        item["qty"],
                        item["note"],
                    ):
                        raise Exception(f'Gagal memproses outbound untuk {_format_item_label(record)}')

                    if not first_label:
                        first_label = _format_item_label(record)
                    processed += 1

                db.commit()

                try:
                    inventory_policy = get_event_notification_policy("inventory.activity")
                    notify_operational_event(
                        f"Outbound selesai: {processed} item",
                        (
                            f"{processed} item outbound berhasil diproses di "
                            f"{(warehouse['name'] or f'Gudang {warehouse_id}').strip()}. "
                            f"Item pertama: {first_label or '-'}."
                        ),
                        warehouse_id=warehouse_id,
                        category="inventory",
                        link_url="/outbound/",
                        recipient_roles=inventory_policy["roles"],
                        recipient_usernames=inventory_policy["usernames"],
                        recipient_user_ids=inventory_policy["user_ids"],
                        source_type="outbound_batch",
                        push_title="Outbound berhasil diproses",
                        push_body=(
                            f"{processed} item | "
                            f"{(warehouse['name'] or f'Gudang {warehouse_id}').strip()}"
                        ),
                    )
                except Exception as exc:
                    print("OUTBOUND NOTIFICATION ERROR:", exc)

                flash(f"{processed} item outbound berhasil diproses", "success")

            elif has_permission(role, "request_stock_ops"):
                db.execute("BEGIN")

                for item in items:
                    record = _fetch_item_record(
                        db,
                        item["product_id"],
                        item["variant_id"],
                    )
                    if not record:
                        raise Exception("Produk / variant tidak valid")

                    db.execute("""
                        INSERT INTO approvals(
                            type,
                            product_id,
                            variant_id,
                            warehouse_id,
                            qty,
                            note,
                            requested_by
                        )
                        VALUES (?,?,?,?,?,?,?)
                    """, (
                        "OUTBOUND",
                        item["product_id"],
                        item["variant_id"],
                        warehouse_id,
                        item["qty"],
                        item["note"],
                        session.get("user_id"),
                    ))

                db.commit()

                try:
                    approval_policy = get_event_notification_policy("inventory.outbound_approval_requested")
                    notify_roles(
                        approval_policy["roles"],
                        "Permintaan Outbound Massal",
                        f"Ada {len(items)} item outbound yang menunggu approval.",
                        warehouse_id=warehouse_id,
                        usernames=approval_policy["usernames"],
                        user_ids=approval_policy["user_ids"],
                        send_whatsapp_channel=False,
                        category="approval",
                        link_url="/approvals",
                        source_type="approval_queue",
                    )
                except Exception as exc:
                    print("NOTIFY ERROR:", exc)

                try:
                    send_role_based_notification(
                        "inventory.outbound_approval_requested",
                        {
                            "warehouse_id": warehouse_id,
                            "warehouse_name": (warehouse["name"] or f"Gudang {warehouse_id}").strip(),
                            "requester_name": session.get("username") or "Staff",
                            "item_count": len(items),
                            "link_url": "/approvals",
                        },
                    )
                except Exception as exc:
                    print("OUTBOUND WHATSAPP ROLE NOTIFICATION ERROR:", exc)

                flash(
                    f"{len(items)} permintaan outbound telah dikirim ke leader untuk approval",
                    "success",
                )

            else:
                flash("Tidak punya akses", "error")

        except Exception as exc:
            db.rollback()
            print("OUTBOUND ERROR:", exc)
            flash(str(exc), "error")

        return redirect("/outbound")

    warehouses = db.execute("""
        SELECT *
        FROM warehouses
        ORDER BY name
    """).fetchall()

    return render_template(
        "outbound.html",
        warehouses=warehouses,
        warehouse_id=session.get("warehouse_id"),
    )
