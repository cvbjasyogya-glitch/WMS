import json

from flask import Blueprint, render_template, request, redirect, flash, session

from database import get_db
from services.notification_service import notify_operational_event, notify_roles
from services.rbac import has_permission, is_scoped_role
from services.stock_service import add_stock

inbound_bp = Blueprint(
    "inbound",
    __name__,
    url_prefix="/inbound"
)


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


def _parse_inbound_items(form):
    raw_payload = (form.get("items_json") or "").strip()
    if raw_payload:
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("Format item inbound tidak valid") from exc

        if not isinstance(payload, list):
            raise ValueError("Format item inbound tidak valid")

        items = []
        for item in payload:
            if not isinstance(item, dict):
                continue

            product_id = _to_int(item.get("product_id"), 0)
            variant_id = _to_int(item.get("variant_id"), 0)
            qty = _to_int(item.get("qty"), 0)
            note = (item.get("note") or "").strip()
            cost = _to_float(item.get("cost"), 0)
            expiry = (item.get("expiry") or "").strip() or None
            custom_date = (item.get("custom_date") or "").strip() or None
            display_name = (item.get("display_name") or "").strip()

            if not any([
                product_id,
                variant_id,
                qty,
                note,
                cost,
                expiry,
                custom_date,
                display_name,
            ]):
                continue

            if product_id <= 0 or variant_id <= 0 or qty <= 0:
                raise ValueError("Ada baris inbound yang belum lengkap atau qty tidak valid")

            items.append({
                "product_id": product_id,
                "variant_id": variant_id,
                "qty": qty,
                "note": note or "Inbound Barang",
                "cost": cost,
                "expiry": expiry,
                "custom_date": custom_date,
                "display_name": display_name,
            })

        if not items:
            raise ValueError("Minimal pilih satu item inbound")

        return items

    product_id = _to_int(form.get("product_id"), 0)
    variant_id = _to_int(form.get("variant_id"), 0)
    qty = _to_int(form.get("qty"), 0)
    note = (form.get("note") or "").strip() or "Inbound Barang"
    cost = _to_float(form.get("cost"), 0)
    expiry = (form.get("expiry") or "").strip() or None
    custom_date = (form.get("custom_date") or "").strip() or None

    if product_id <= 0 or variant_id <= 0 or qty <= 0:
        raise ValueError("Input tidak valid")

    return [{
        "product_id": product_id,
        "variant_id": variant_id,
        "qty": qty,
        "note": note,
        "cost": cost,
        "expiry": expiry,
        "custom_date": custom_date,
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


@inbound_bp.route("/", methods=["GET", "POST"])
def inbound():

    db = get_db()

    if request.method == "POST":

        try:
            warehouse_id = _to_int(request.form.get("warehouse_id"), 0)
            items = _parse_inbound_items(request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect("/inbound")
        except Exception:
            flash("Input tidak valid", "error")
            return redirect("/inbound")

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
            return redirect("/inbound")

        if is_scoped_role(role) and warehouse_id != user_wh:
            flash("Tidak punya akses ke gudang ini", "error")
            return redirect("/inbound")

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

                    if not add_stock(
                        item["product_id"],
                        item["variant_id"],
                        warehouse_id,
                        item["qty"],
                        note=item["note"],
                        cost=item["cost"],
                        custom_date=item["custom_date"],
                        expiry=item["expiry"],
                    ):
                        raise Exception(f'Gagal memproses inbound untuk {_format_item_label(record)}')

                    if not first_label:
                        first_label = _format_item_label(record)
                    processed += 1

                db.commit()

                try:
                    notify_operational_event(
                        f"Inbound selesai: {processed} item",
                        (
                            f"{processed} item inbound berhasil diproses di "
                            f"{(warehouse['name'] or f'Gudang {warehouse_id}').strip()}. "
                            f"Item pertama: {first_label or '-'}."
                        ),
                        warehouse_id=warehouse_id,
                        category="inventory",
                        link_url="/inbound/",
                        source_type="inbound_batch",
                        push_title="Inbound berhasil diproses",
                        push_body=(
                            f"{processed} item | "
                            f"{(warehouse['name'] or f'Gudang {warehouse_id}').strip()}"
                        ),
                    )
                except Exception as exc:
                    print("INBOUND NOTIFICATION ERROR:", exc)

                flash(f"{processed} item inbound berhasil diproses", "success")

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
                        "INBOUND",
                        item["product_id"],
                        item["variant_id"],
                        warehouse_id,
                        item["qty"],
                        item["note"],
                        session.get("user_id"),
                    ))

                db.commit()

                try:
                    notify_roles(
                        ["leader", "owner", "super_admin"],
                        "Permintaan Inbound Massal",
                        f"Ada {len(items)} item inbound yang menunggu approval.",
                        warehouse_id=warehouse_id,
                        category="approval",
                        link_url="/approvals",
                        source_type="approval_queue",
                    )
                except Exception as exc:
                    print("NOTIFY ERROR:", exc)

                flash(
                    f"{len(items)} permintaan inbound telah dikirim ke leader untuk approval",
                    "success",
                )

            else:
                flash("Tidak punya akses", "error")

        except Exception as exc:
            db.rollback()
            print("INBOUND ERROR:", exc)
            flash(str(exc), "error")

        return redirect("/inbound")

    warehouses = db.execute("""
        SELECT *
        FROM warehouses
        ORDER BY name
    """).fetchall()

    return render_template(
        "inbound.html",
        warehouses=warehouses,
        warehouse_id=session.get("warehouse_id"),
    )
