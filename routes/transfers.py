import json

from flask import Blueprint, render_template, request, redirect, flash, jsonify, session

from database import get_db
from services.notification_service import notify_operational_event, notify_roles
from services.request_service import create_request, approve_request
from services.rbac import has_permission, is_scoped_role

transfers_bp = Blueprint(
    "transfers",
    __name__,
    url_prefix="/transfers"
)


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_transfer_items(form):
    raw_payload = (form.get("items_json") or "").strip()
    if raw_payload:
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("Format item transfer tidak valid") from exc

        if not isinstance(payload, list):
            raise ValueError("Format item transfer tidak valid")

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
                raise ValueError("Ada item transfer yang belum lengkap atau qty tidak valid")

            items.append({
                "product_id": product_id,
                "variant_id": variant_id,
                "qty": qty,
                "display_name": display_name,
            })

        if not items:
            raise ValueError("Minimal tambahkan satu item transfer")

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


def _fetch_transfer_item_record(db, product_id, variant_id):
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


def _format_transfer_item_label(record):
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


@transfers_bp.route("/", methods=["GET", "POST"])
def transfer():
    db = get_db()

    user_id = session.get("user_id")
    if not user_id:
        return redirect("/login")

    if not session.get("warehouse_id"):
        warehouse = db.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
        session["warehouse_id"] = warehouse["id"] if warehouse else 1

    if request.method == "POST":

        try:
            from_wh = _to_int(request.form.get("from_warehouse"), 0)
            to_wh = _to_int(request.form.get("to_warehouse"), 0)
            items = _parse_transfer_items(request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect("/transfers")
        except Exception:
            flash("Input tidak valid", "error")
            return redirect("/transfers")

        if from_wh == to_wh:
            flash("Gudang asal dan tujuan tidak boleh sama", "error")
            return redirect("/transfers")

        wh1 = db.execute("SELECT id, name FROM warehouses WHERE id=?", (from_wh,)).fetchone()
        wh2 = db.execute("SELECT id, name FROM warehouses WHERE id=?", (to_wh,)).fetchone()

        if not wh1 or not wh2:
            flash("Data gudang tidak valid", "error")
            return redirect("/transfers")

        role = session.get("role")
        user_wh = session.get("warehouse_id")

        if is_scoped_role(role) and from_wh != user_wh:
            flash("Tidak punya akses untuk melakukan transfer dari gudang ini", "error")
            return redirect("/transfers")

        aggregates = {}
        labels = {}

        for item in items:
            record = _fetch_transfer_item_record(
                db,
                item["product_id"],
                item["variant_id"],
            )
            if not record:
                flash("Produk / variant tidak valid", "error")
                return redirect("/transfers")

            key = (item["product_id"], item["variant_id"])
            aggregates[key] = aggregates.get(key, 0) + item["qty"]
            labels[key] = _format_transfer_item_label(record)

        for (product_id, variant_id), total_qty in aggregates.items():
            available_qty = _get_available_stock(
                db,
                product_id,
                variant_id,
                from_wh,
            )
            if available_qty < total_qty:
                flash(f"Stok tidak cukup untuk {labels[(product_id, variant_id)]}", "error")
                return redirect("/transfers")

        if has_permission(role, "direct_transfer"):
            try:
                db.execute("BEGIN")

                processed = 0
                first_label = ""
                for item in items:
                    req_id = create_request(
                        item["product_id"],
                        item["variant_id"],
                        from_wh,
                        to_wh,
                        item["qty"],
                    )
                    if not req_id:
                        raise Exception(
                            f'Gagal membuat transfer untuk {labels[(item["product_id"], item["variant_id"])]}'
                        )

                    success = approve_request(req_id)
                    if not success:
                        raise Exception(
                            f'Transfer gagal untuk {labels[(item["product_id"], item["variant_id"])]}'
                        )

                    if not first_label:
                        first_label = labels[(item["product_id"], item["variant_id"])]
                    processed += 1

                db.commit()

                try:
                    notify_operational_event(
                        f"Transfer selesai: {processed} item",
                        (
                            f"{processed} item berhasil dipindahkan dari {wh1['name']} ke {wh2['name']}. "
                            f"Item pertama: {first_label or '-'}."
                        ),
                        warehouse_id=from_wh,
                        category="inventory",
                        link_url="/transfers/",
                        source_type="direct_transfer_batch",
                        push_title="Transfer gudang selesai",
                        push_body=f"{processed} item | {wh1['name']} -> {wh2['name']}",
                    )
                except Exception as exc:
                    print("TRANSFER NOTIFICATION ERROR:", exc)

                flash(f"{processed} item transfer berhasil diproses (FIFO)", "success")
            except Exception as exc:
                db.rollback()
                print("TRANSFER BULK ERROR:", exc)
                flash(str(exc), "error")

            return redirect("/transfers")

        if has_permission(role, "request_transfer"):
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

                subj = f"Permintaan Transfer: {len(items)} item"
                msg = (
                    f"Transfer request sebanyak {len(items)} item\n"
                    f"Dari: {wh1['name']}\n"
                    f"Ke: {wh2['name']}"
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
                except Exception:
                    pass

                flash(f"{len(items)} permintaan transfer telah dikirim ke leader untuk approval", "success")
            except Exception as exc:
                db.rollback()
                print("TRANSFER REQUEST ERROR:", exc)
                flash("Gagal membuat transfer", "error")

            return redirect("/transfers")

        flash("Tidak punya akses", "error")
        return redirect("/transfers")

    warehouses = db.execute("""
    SELECT * FROM warehouses ORDER BY name
    """).fetchall()

    return render_template(
        "transfer.html",
        warehouses=warehouses,
        warehouse_id=session.get("warehouse_id")
    )


@transfers_bp.route("/get_stock")
def get_stock():
    db = get_db()

    try:
        product_id = int(request.args.get("product_id"))
        variant_id = int(request.args.get("variant_id"))
        warehouse_id = int(request.args.get("warehouse_id"))
    except:
        return jsonify({"qty": 0})

    stock = db.execute("""
    SELECT qty FROM stock
    WHERE product_id=? AND variant_id=? AND warehouse_id=?
    """,(product_id, variant_id, warehouse_id)).fetchone()

    qty = stock["qty"] if stock else 0

    return jsonify({"qty": qty})
