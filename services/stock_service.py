from database import get_db
from flask import session, request, has_request_context


# ==========================
# SAFE CONTEXT
# ==========================
def _get_user_context():
    if has_request_context():
        return (
            session.get("user_id"),
            request.remote_addr,
            request.headers.get("User-Agent")
        )
    return (None, None, None)


# ==========================
# HELPER
# ==========================
def _get_total_available(db, product_id, variant_id, warehouse_id):
    row = db.execute("""
        SELECT COALESCE(SUM(remaining_qty),0) as total
        FROM stock_batches
        WHERE product_id=? AND variant_id=? AND warehouse_id=?
    """,(product_id, variant_id, warehouse_id)).fetchone()
    return row["total"]


def _get_total_pos_negative_overdraft(db, product_id, variant_id, warehouse_id):
    row = db.execute(
        """
        SELECT COALESCE(SUM(remaining_qty),0) as total
        FROM pos_negative_stock_overdrafts
        WHERE product_id=? AND variant_id=? AND warehouse_id=? AND COALESCE(remaining_qty, 0) > 0
        """,
        (product_id, variant_id, warehouse_id),
    ).fetchone()
    return row["total"] if row else 0


def _sync_stock(db, product_id, variant_id, warehouse_id):
    total = _get_total_available(db, product_id, variant_id, warehouse_id) - _get_total_pos_negative_overdraft(
        db,
        product_id,
        variant_id,
        warehouse_id,
    )

    db.execute("""
    INSERT INTO stock(product_id,variant_id,warehouse_id,qty)
    VALUES (?,?,?,?)
    ON CONFLICT(product_id,variant_id,warehouse_id)
    DO UPDATE SET qty = excluded.qty, updated_at = CURRENT_TIMESTAMP
    """,(product_id, variant_id, warehouse_id, total))


def _validate_entities(db, product_id, variant_id, warehouse_id):
    product = db.execute("SELECT id FROM products WHERE id=?", (product_id,)).fetchone()
    variant = db.execute("SELECT id FROM product_variants WHERE id=? AND product_id=?", (variant_id, product_id)).fetchone()
    warehouse = db.execute("SELECT id FROM warehouses WHERE id=?", (warehouse_id,)).fetchone()
    return product and variant and warehouse


def _get_default_warehouse(db):
    wh = db.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
    return wh["id"] if wh else 1


def _ensure_legacy_stock_batch_shadow(db, product_id, variant_id, warehouse_id):
    open_batch = db.execute(
        """
        SELECT id
        FROM stock_batches
        WHERE product_id=? AND variant_id=? AND warehouse_id=? AND COALESCE(remaining_qty, 0) > 0
        LIMIT 1
        """,
        (product_id, variant_id, warehouse_id),
    ).fetchone()
    if open_batch:
        return

    stock_row = db.execute(
        """
        SELECT COALESCE(qty, 0) AS qty
        FROM stock
        WHERE product_id=? AND variant_id=? AND warehouse_id=?
        LIMIT 1
        """,
        (product_id, variant_id, warehouse_id),
    ).fetchone()
    if not stock_row:
        return

    try:
        available_qty = int(stock_row["qty"] or 0)
    except (TypeError, ValueError):
        available_qty = 0
    if available_qty <= 0:
        return

    db.execute(
        """
        INSERT INTO stock_batches(
            product_id,
            variant_id,
            warehouse_id,
            qty,
            remaining_qty,
            cost,
            created_at
        )
        VALUES (?,?,?,?,?,0,datetime('now'))
        """,
        (product_id, variant_id, warehouse_id, available_qty, available_qty),
    )


# ==========================
# ADD STOCK (FIX IMPORT SAFE)
# ==========================
def add_stock(product_id, variant_id, warehouse_id, qty,
              note="Barang masuk", cost=0, custom_date=None, expiry=None):

    db = get_db()

    try:
        product_id = int(product_id)
        variant_id = int(variant_id)
        warehouse_id = int(warehouse_id)
        qty = int(qty)
    except:
        return False

    if qty <= 0:
        return False

    # 🔥 FIX: fallback warehouse
    if not db.execute("SELECT id FROM warehouses WHERE id=?", (warehouse_id,)).fetchone():
        warehouse_id = _get_default_warehouse(db)

    if not _validate_entities(db, product_id, variant_id, warehouse_id):
        print("VALIDATION FAIL:", product_id, variant_id, warehouse_id)
        return False

    user_id, ip, ua = _get_user_context()

    try:
        # 🔥 FIX: jangan paksa BEGIN kalau sudah ada transaction
        try:
            db.execute("BEGIN")
            started = True
        except:
            started = False

        db.execute("""
        INSERT INTO stock_batches(
            product_id, variant_id, warehouse_id,
            qty, remaining_qty, cost, expiry_date, created_at
        )
        VALUES (?,?,?,?,?,?,?, COALESCE(?, datetime('now')))
        """,(
            product_id,
            variant_id,
            warehouse_id,
            qty,
            qty,
            cost,
            expiry,
            custom_date
        ))

        batch_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        db.execute("""
        INSERT INTO stock_movements(
            product_id,variant_id,warehouse_id,
            batch_id,qty,type,created_at
        )
        VALUES (?, ?, ?, ?, ?, 'IN', datetime('now'))
        """,(product_id, variant_id, warehouse_id, batch_id, qty))

        _sync_stock(db, product_id, variant_id, warehouse_id)

        db.execute("""
        INSERT INTO stock_history(
            product_id,variant_id,warehouse_id,
            action,type,qty,note,
            user_id,ip_address,user_agent
        )
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,(
            product_id, variant_id, warehouse_id,
            'INBOUND','IN', qty, note,
            user_id, ip, ua
        ))

        if started:
            db.commit()

        return True

    except Exception as e:
        print("ADD STOCK ERROR:", e)
        try:
            db.rollback()
        except:
            pass
        return False


# ==========================
# REMOVE STOCK (UNCHANGED)
# ==========================
def remove_stock(product_id, variant_id, warehouse_id, qty, note="Barang keluar"):

    db = get_db()

    try:
        product_id = int(product_id)
        variant_id = int(variant_id)
        warehouse_id = int(warehouse_id)
        qty = int(qty)
    except:
        return False

    if qty <= 0:
        return False

    if not _validate_entities(db, product_id, variant_id, warehouse_id):
        return False

    user_id, ip, ua = _get_user_context()

    try:
        try:
            db.execute("BEGIN")
            started = True
        except:
            started = False

        _ensure_legacy_stock_batch_shadow(db, product_id, variant_id, warehouse_id)
        total = _get_total_available(db, product_id, variant_id, warehouse_id)
        if total < qty:
            try:
                db.rollback()
            except:
                pass
            return False

        batches = db.execute("""
        SELECT id, remaining_qty
        FROM stock_batches
        WHERE product_id=? AND variant_id=? AND warehouse_id=?
        AND remaining_qty > 0
        ORDER BY datetime(created_at) ASC
        """,(product_id, variant_id, warehouse_id)).fetchall()

        remaining = qty

        for b in batches:
            if remaining <= 0:
                break

            take = min(b["remaining_qty"], remaining)

            db.execute("""
            UPDATE stock_batches
            SET remaining_qty = remaining_qty - ?
            WHERE id=?
            """,(take, b["id"]))

            db.execute("""
            INSERT INTO stock_movements(
                product_id,variant_id,warehouse_id,
                batch_id,qty,type,created_at
            )
            VALUES (?,?,?,?,?,'OUT',datetime('now'))
            """,(product_id, variant_id, warehouse_id, b["id"], take))

            remaining -= take

        if remaining > 0:
            db.rollback()
            return False

        _sync_stock(db, product_id, variant_id, warehouse_id)

        db.execute("""
        INSERT INTO stock_history(
            product_id,variant_id,warehouse_id,
            action,type,qty,note,
            user_id,ip_address,user_agent
        )
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,(
            product_id, variant_id, warehouse_id,
            'OUTBOUND','OUT', qty, note,
            user_id, ip, ua
        ))

        if started:
            db.commit()
        return True

    except Exception:
        try:
            db.rollback()
        except:
            pass
        return False


# ==========================
# ADJUST STOCK (UNCHANGED)
# ==========================
def adjust_stock(product_id, variant_id, warehouse_id, qty, note="Stock Adjustment"):

    db = get_db()

    try:
        product_id = int(product_id)
        variant_id = int(variant_id)
        warehouse_id = int(warehouse_id)
        qty = int(qty)
    except:
        return False

    if qty == 0:
        return False

    if not _validate_entities(db, product_id, variant_id, warehouse_id):
        return False

    user_id, ip, ua = _get_user_context()

    try:
        db.execute("BEGIN")

        if qty > 0:
            db.execute("""
            INSERT INTO stock_batches(
                product_id, variant_id, warehouse_id,
                qty, remaining_qty, cost, created_at
            )
            VALUES (?,?,?,?,?,?, datetime('now'))
            """,(product_id, variant_id, warehouse_id, qty, qty, 0))

            batch_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            db.execute("""
            INSERT INTO stock_movements(
                product_id,variant_id,warehouse_id,
                batch_id,qty,type,created_at
            )
            VALUES (?,?,?,?,?,'ADJUST_IN',datetime('now'))
            """,(product_id, variant_id, warehouse_id, batch_id, qty))

        elif qty < 0:

            need = abs(qty)

            _ensure_legacy_stock_batch_shadow(db, product_id, variant_id, warehouse_id)
            total = _get_total_available(db, product_id, variant_id, warehouse_id)
            if total < need:
                db.rollback()
                return False

            batches = db.execute("""
            SELECT id, remaining_qty
            FROM stock_batches
            WHERE product_id=? AND variant_id=? AND warehouse_id=?
            AND remaining_qty > 0
            ORDER BY datetime(created_at) ASC
            """,(product_id, variant_id, warehouse_id)).fetchall()

            for b in batches:

                if need <= 0:
                    break

                take = min(b["remaining_qty"], need)

                db.execute("""
                UPDATE stock_batches
                SET remaining_qty = remaining_qty - ?
                WHERE id=?
                """,(take, b["id"]))

                db.execute("""
                INSERT INTO stock_movements(
                    product_id,variant_id,warehouse_id,
                    batch_id,qty,type,created_at
                )
                VALUES (?,?,?,?,?,'ADJUST_OUT',datetime('now'))
                """,(product_id, variant_id, warehouse_id, b["id"], take))

                need -= take

        _sync_stock(db, product_id, variant_id, warehouse_id)

        db.execute("""
        INSERT INTO stock_history(
            product_id,variant_id,warehouse_id,
            action,type,qty,note,
            user_id,ip_address,user_agent
        )
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,(
            product_id, variant_id, warehouse_id,
            'ADJUST','EDIT', qty, note,
            user_id, ip, ua
        ))

        db.commit()
        return True

    except Exception as e:
        db.rollback()
        print("ADJUST ERROR:", e)
        return False
