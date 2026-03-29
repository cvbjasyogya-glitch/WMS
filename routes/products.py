from flask import Blueprint, render_template, request, redirect, jsonify, flash, session
from database import get_db
from services.stock_service import add_stock
import csv
import uuid
from io import StringIO

try:
    import pandas as pd
except ImportError:
    pd = None

products_bp = Blueprint("products", __name__, url_prefix="/products")

IMPORT_PROGRESS = {}


def _to_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_variant_name(value):
    value = (value or "").strip()
    return value or "default"


def _resolve_products_warehouse(db):
    role = session.get("role")

    if role in ["leader", "admin"]:
        warehouse_id = session.get("warehouse_id") or 1
    else:
        try:
            warehouse_id = int(request.args.get("warehouse") or session.get("warehouse_id") or 1)
        except (TypeError, ValueError):
            warehouse_id = 1

    warehouse = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    if warehouse:
        return warehouse["id"]

    fallback = db.execute("SELECT id FROM warehouses ORDER BY id LIMIT 1").fetchone()
    return fallback["id"] if fallback else 1


def _read_import_file(file):
    if pd is None:
        raise RuntimeError("Fitur import membutuhkan dependency pandas dan openpyxl.")

    try:
        return pd.read_excel(file)
    except Exception:
        file.stream.seek(0)
        return pd.read_csv(file)


def _read_import_dataset(file):
    if pd is not None:
        df = _read_import_file(file)
        df.columns = [c.strip().lower() for c in df.columns]
        df = df.fillna("")
        return list(df.columns), df.to_dict(orient="records")

    filename = (file.filename or "").lower()
    if not filename.endswith(".csv"):
        raise RuntimeError(
            "Fitur import Excel membutuhkan dependency pandas dan openpyxl."
        )

    file.stream.seek(0)
    raw = file.stream.read()
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else str(raw)

    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise ValueError("Format tidak valid")

    original_fields = list(reader.fieldnames)
    normalized_fields = [(field or "").strip().lower() for field in original_fields]
    rows = []

    for raw_row in reader:
        row = {}
        for original, normalized in zip(original_fields, normalized_fields):
            if normalized:
                row[normalized] = raw_row.get(original) or ""
        rows.append(row)

    file.stream.seek(0)
    return normalized_fields, rows


def _upsert_variant(db, product_id, variant_name, price_retail, price_discount, price_nett):
    variant_name = _normalize_variant_name(variant_name)

    existing = db.execute("""
        SELECT id
        FROM product_variants
        WHERE product_id=? AND variant=?
    """, (product_id, variant_name)).fetchone()

    if existing:
        db.execute("""
            UPDATE product_variants
            SET price_retail=?,
                price_discount=?,
                price_nett=?
            WHERE id=?
        """, (price_retail, price_discount, price_nett, existing["id"]))
        return existing["id"]

    cur = db.execute("""
        INSERT INTO product_variants(
            product_id, variant, price_retail, price_discount, price_nett
        )
        VALUES (?,?,?,?,?)
    """, (product_id, variant_name, price_retail, price_discount, price_nett))

    return cur.lastrowid


@products_bp.route("/get_variants/<int:product_id>")
def get_variants(product_id):

    db = get_db()

    rows = db.execute("""
        SELECT id, variant, price_retail, price_discount, price_nett
        FROM product_variants
        WHERE product_id=?
        ORDER BY CASE WHEN LOWER(variant)='default' THEN 0 ELSE 1 END, variant
    """, (product_id,)).fetchall()

    return jsonify([dict(r) for r in rows])


@products_bp.route("/")
def products():

    db = get_db()
    warehouse_id = _resolve_products_warehouse(db)

    try:
        page = int(request.args.get("page", 1))
    except:
        page = 1

    search = request.args.get("search", "").strip()

    LIMIT = 50
    OFFSET = (page - 1) * LIMIT

    search_param = f"%{search}%"

    data_raw = db.execute("""
        SELECT 
            p.id,
            p.sku,
            p.name,
            c.name as category,

            COALESCE((
                SELECT SUM(qty) 
                FROM stock 
                WHERE product_id = p.id AND warehouse_id = ?
            ),0) as qty,

            MIN(b.created_at) as first_in,

            COALESCE(
                CAST((JULIANDAY('now') - JULIANDAY(MIN(b.created_at))) AS INTEGER),
                0
            ) as age_days

        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN stock_batches b
            ON p.id = b.product_id
            AND b.warehouse_id = ?
            AND b.remaining_qty > 0

        WHERE
            (? = '' OR 
             p.name LIKE ? OR 
             p.sku LIKE ? OR 
             c.name LIKE ?)

        GROUP BY p.id
        ORDER BY age_days DESC
        LIMIT ? OFFSET ?
    """, (
        warehouse_id,
        warehouse_id,
        search,
        search_param,
        search_param,
        search_param,
        LIMIT,
        OFFSET
    )).fetchall()

    total = db.execute("""
        SELECT COUNT(*) as total
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.id
        WHERE
            (? = '' OR 
             p.name LIKE ? OR 
             p.sku LIKE ? OR 
             c.name LIKE ?)
    """, (
        search,
        search_param,
        search_param,
        search_param
    )).fetchone()["total"]

    total_pages = max(1, (total + LIMIT - 1) // LIMIT)

    data = [dict(r) for r in data_raw]

    warehouses = db.execute("SELECT * FROM warehouses ORDER BY name").fetchall()

    return render_template(
        "produk.html",
        data=data,
        warehouses=warehouses,
        warehouse_id=warehouse_id,
        page=page,
        total_pages=total_pages
    )


@products_bp.route("/bulk-delete", methods=["POST"])
def bulk_delete():

    db = get_db()
    payload = request.get_json(silent=True) or {}
    raw_ids = payload.get("ids", [])
    ids = []

    for raw_id in raw_ids:
        try:
            ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    ids = sorted(set(ids))

    if not ids:
        return jsonify({"message": "No data"}), 400

    try:
        db.execute("BEGIN")

        placeholders = ",".join(["?"] * len(ids))

        db.execute(f"DELETE FROM stock_movements WHERE product_id IN ({placeholders})", ids)
        db.execute(f"DELETE FROM stock_history WHERE product_id IN ({placeholders})", ids)
        db.execute(f"DELETE FROM stock_batches WHERE product_id IN ({placeholders})", ids)
        db.execute(f"DELETE FROM stock WHERE product_id IN ({placeholders})", ids)
        db.execute(f"DELETE FROM product_variants WHERE product_id IN ({placeholders})", ids)
        db.execute(f"DELETE FROM products WHERE id IN ({placeholders})", ids)

        db.commit()
        return jsonify({"message": "OK"})

    except Exception as e:
        db.rollback()
        print("BULK DELETE ERROR:", e)
        return jsonify({"message": "Error"}), 500


@products_bp.route("/import/preview", methods=["POST"])
def preview_import():

    file = request.files.get("file")

    if not file:
        return jsonify({"error": "File tidak ada"})

    try:
        _, rows = _read_import_dataset(file)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    except Exception:
        return jsonify({"error": "Format tidak valid"}), 400

    return jsonify({"rows": rows[:10]})


@products_bp.route("/add", methods=["POST"])
def add_product():

    db = get_db()

    try:
        sku = request.form["sku"].strip()
        name = request.form["name"].strip()
        category_name = request.form["category_name"].strip()
        variants = request.form.get("variants", "")
        qty = int(request.form["qty"])
        warehouse_id = int(request.form["warehouse_id"])

        price_retail = _to_float(request.form.get("price_retail"))
        price_discount = _to_float(request.form.get("price_discount"))
        price_nett = _to_float(request.form.get("price_nett"))

    except:
        flash("Input tidak valid", "error")
        return redirect("/products")

    if qty <= 0:
        flash("Qty harus > 0", "error")
        return redirect("/products")

    try:
        db.execute("BEGIN")

        exist = db.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone()

        if exist:
            db.rollback()
            flash("SKU sudah ada", "error")
            return redirect("/products")

        category = db.execute("SELECT id FROM categories WHERE name=?", (category_name,)).fetchone()

        if category:
            category_id = category["id"]
        else:
            cur = db.execute("INSERT INTO categories(name) VALUES (?)", (category_name,))
            category_id = cur.lastrowid

        cur = db.execute("INSERT INTO products (sku,name,category_id) VALUES (?,?,?)", (sku, name, category_id))
        product_id = cur.lastrowid

        variant_list = [v.strip() for v in variants.split(",") if v.strip()] or ["default"]

        for v in variant_list:
            variant_id = _upsert_variant(
                db,
                product_id,
                v,
                price_retail,
                price_discount,
                price_nett
            )

            ok = add_stock(product_id, variant_id, warehouse_id, qty, note="Initial Stock")

            if not ok:
                raise Exception("Gagal add stock")

        db.commit()
        flash("Produk berhasil ditambahkan", "success")

    except Exception as e:
        db.rollback()
        print("ERROR ADD PRODUCT:", e)
        flash(str(e), "error")

    return redirect("/products")


@products_bp.route("/delete/<int:id>", methods=["POST"])
def delete_product(id):

    db = get_db()

    try:
        db.execute("BEGIN")

        db.execute("DELETE FROM stock_movements WHERE product_id=?", (id,))
        db.execute("DELETE FROM stock_history WHERE product_id=?", (id,))
        db.execute("DELETE FROM stock_batches WHERE product_id=?", (id,))
        db.execute("DELETE FROM stock WHERE product_id=?", (id,))
        db.execute("DELETE FROM product_variants WHERE product_id=?", (id,))
        db.execute("DELETE FROM products WHERE id=?", (id,))

        db.commit()
        flash("Produk berhasil dihapus", "success")

    except Exception as e:
        db.rollback()
        print("DELETE ERROR:", e)
        flash("Gagal menghapus produk", "error")

    return redirect("/products")


@products_bp.route("/import/progress/<job_id>")
def import_progress(job_id):

    data = IMPORT_PROGRESS.get(job_id)

    if not data:
        return jsonify({"error": "not found"}), 404

    percent = int((data["current"] / data["total"]) * 100) if data["total"] else 0

    return jsonify({
        "percent": percent,
        "current": data["current"],
        "total": data["total"],
        "status": data["status"]
    })


@products_bp.route("/import", methods=["POST"])
def import_products():

    db = get_db()
    file = request.files.get("file")

    if not file:
        return "No file", 400

    user_id = session.get("user_id")
    ip = request.remote_addr
    user_agent = request.headers.get("User-Agent")

    try:
        columns, rows = _read_import_dataset(file)
    except RuntimeError as e:
        return str(e), 500
    except Exception:
        return "Format tidak valid", 400

    required = ["sku", "name", "category", "qty"]
    for col in required:
        if col not in columns:
            return f"Kolom {col} tidak ada", 400

    job_id = str(uuid.uuid4())

    IMPORT_PROGRESS[job_id] = {
        "total": len(rows),
        "current": 0,
        "status": "processing"
    }

    wh = db.execute("SELECT id FROM warehouses WHERE id=?", (session.get("warehouse_id"),)).fetchone()
    if not wh:
        wh = db.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
    warehouse_id = wh["id"] if wh else 1

    CHUNK_SIZE = 200

    category_cache = {r["name"]: r["id"] for r in db.execute("SELECT id,name FROM categories")}
    product_cache = {r["sku"]: r["id"] for r in db.execute("SELECT id,sku FROM products")}

    for start in range(0, len(rows), CHUNK_SIZE):

        chunk = rows[start:start+CHUNK_SIZE]

        try:
            db.execute("BEGIN")

            variant_ids = []

            for row in chunk:
                try:
                    sku = str(row.get("sku")).strip()
                    name = str(row.get("name")).strip()
                    category_name = str(row.get("category") or "").strip() or "Uncategorized"
                    variant = _normalize_variant_name(str(row.get("variant") or "default"))

                    qty = int(row.get("qty") or 0)
                    if not sku or not name or qty <= 0:
                        continue

                    price_retail = _to_float(row.get("price_retail"))
                    price_discount = _to_float(row.get("price_discount"))
                    price_nett = _to_float(row.get("price_nett"))

                    if category_name in category_cache:
                        category_id = category_cache[category_name]
                    else:
                        cur = db.execute("INSERT INTO categories(name) VALUES (?)", (category_name,))
                        category_id = cur.lastrowid
                        category_cache[category_name] = category_id

                    if sku in product_cache:
                        product_id = product_cache[sku]
                        db.execute("""
                            UPDATE products
                            SET name=?, category_id=?
                            WHERE id=?
                        """, (name, category_id, product_id))
                    else:
                        cur = db.execute("INSERT INTO products(sku,name,category_id) VALUES (?,?,?)", (sku, name, category_id))
                        product_id = cur.lastrowid
                        product_cache[sku] = product_id

                    variant_id = _upsert_variant(
                        db,
                        product_id,
                        variant,
                        price_retail,
                        price_discount,
                        price_nett
                    )
                    variant_ids.append((product_id, variant_id, qty))

                except Exception as e:
                    print("ROW ERROR:", e)

                IMPORT_PROGRESS[job_id]["current"] += 1

            stock_final = []
            for p_id, v_id, qty in variant_ids:
                stock_final.append((p_id, v_id, warehouse_id, qty, qty))

            db.executemany("""
            INSERT INTO stock_batches(product_id,variant_id,warehouse_id,qty,remaining_qty,cost,created_at)
            VALUES (?,?,?,?,?,0,datetime('now'))
            """, stock_final)

            db.executemany("""
            INSERT INTO stock_movements(product_id,variant_id,warehouse_id,batch_id,qty,type,created_at)
            VALUES (?,?,?,?,?,'IN',datetime('now'))
            """, [(s[0], s[1], s[2], None, s[3]) for s in stock_final])

            db.executemany("""
            INSERT INTO stock_history(product_id,variant_id,warehouse_id,action,type,qty,note,user_id,ip_address,user_agent)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """, [
                (s[0], s[1], s[2], 'IMPORT', 'IN', s[3], 'Bulk Import', user_id, ip, user_agent)
                for s in stock_final
            ])

            db.execute("""
            INSERT INTO stock(product_id,variant_id,warehouse_id,qty)
            SELECT product_id,variant_id,warehouse_id,SUM(remaining_qty)
            FROM stock_batches
            GROUP BY product_id,variant_id,warehouse_id
            ON CONFLICT(product_id,variant_id,warehouse_id)
            DO UPDATE SET qty = excluded.qty
            """)

            db.commit()

        except Exception as e:
            db.rollback()
            print("CHUNK ERROR:", e)

    IMPORT_PROGRESS[job_id]["status"] = "done"

    return jsonify({"job_id": job_id})
