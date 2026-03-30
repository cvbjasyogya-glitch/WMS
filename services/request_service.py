from database import get_db
from flask import session, has_request_context


def _get_user():
    if has_request_context():
        return session.get("user_id")
    return None


def _validate_entities(db, product_id, variant_id, from_wh, to_wh):
    product = db.execute("SELECT id FROM products WHERE id=?", (product_id,)).fetchone()
    variant = db.execute(
        "SELECT id FROM product_variants WHERE id=? AND product_id=?",
        (variant_id, product_id),
    ).fetchone()
    wh1 = db.execute("SELECT id FROM warehouses WHERE id=?", (from_wh,)).fetchone()
    wh2 = db.execute("SELECT id FROM warehouses WHERE id=?", (to_wh,)).fetchone()
    return product and variant and wh1 and wh2


def _sync_stock(db, product_id, variant_id, warehouse_id):
    total = db.execute(
        """
        SELECT COALESCE(SUM(remaining_qty), 0)
        FROM stock_batches
        WHERE product_id=? AND variant_id=? AND warehouse_id=?
        """,
        (product_id, variant_id, warehouse_id),
    ).fetchone()[0]

    db.execute(
        """
        INSERT INTO stock(product_id,variant_id,warehouse_id,qty)
        VALUES (?,?,?,?)
        ON CONFLICT(product_id,variant_id,warehouse_id)
        DO UPDATE SET qty=excluded.qty
        """,
        (product_id, variant_id, warehouse_id, total),
    )


def create_request(product_id, variant_id, from_wh, to_wh, qty):
    db = get_db()

    try:
        product_id = int(product_id)
        variant_id = int(variant_id)
        from_wh = int(from_wh)
        to_wh = int(to_wh)
        qty = int(qty)
    except:
        return None

    if qty <= 0 or from_wh == to_wh:
        return None

    if not _validate_entities(db, product_id, variant_id, from_wh, to_wh):
        return None

    stock = db.execute(
        """
        SELECT COALESCE(SUM(remaining_qty),0)
        FROM stock_batches
        WHERE product_id=? AND variant_id=? AND warehouse_id=?
        """,
        (product_id, variant_id, from_wh),
    ).fetchone()[0]

    if stock < qty:
        return None

    started = False

    try:
        try:
            db.execute("BEGIN")
            started = True
        except Exception:
            started = False

        requested_by = _get_user()
        cur = db.execute(
            """
            INSERT INTO requests(
                product_id,variant_id,from_warehouse,to_warehouse,
                qty,status,created_at,requested_by
            )
            VALUES (?,?,?,?,?,'pending',datetime('now'),?)
            """,
            (product_id, variant_id, from_wh, to_wh, qty, requested_by),
        )

        if started:
            db.commit()
        return cur.lastrowid

    except Exception:
        if started:
            db.rollback()
        return None


def approve_request(request_id):
    db = get_db()

    try:
        request_id = int(request_id)
    except:
        return False

    user_id = _get_user()
    started = False

    try:
        try:
            db.execute("BEGIN IMMEDIATE")
            started = True
        except Exception:
            started = False

        req = db.execute(
            """
            SELECT *
            FROM requests
            WHERE id=? AND status='pending'
            """,
            (request_id,),
        ).fetchone()

        if not req:
            if started:
                db.rollback()
            return False

        product_id = req["product_id"]
        variant_id = req["variant_id"]
        from_wh = req["from_warehouse"]
        to_wh = req["to_warehouse"]
        qty_needed = req["qty"]

        if not _validate_entities(db, product_id, variant_id, from_wh, to_wh):
            if started:
                db.rollback()
            return False

        total = db.execute(
            """
            SELECT COALESCE(SUM(remaining_qty),0)
            FROM stock_batches
            WHERE product_id=? AND variant_id=? AND warehouse_id=?
            """,
            (product_id, variant_id, from_wh),
        ).fetchone()[0]

        if total < qty_needed:
            db.execute(
                """
                UPDATE requests
                SET status='rejected',
                    reason='Stok tidak cukup',
                    approved_at=datetime('now'),
                    approved_by=?
                WHERE id=?
                """,
                (user_id, request_id),
            )
            if started:
                db.commit()
            return False

        batches = db.execute(
            """
            SELECT *
            FROM stock_batches
            WHERE product_id=? AND variant_id=? AND warehouse_id=?
              AND remaining_qty > 0
            ORDER BY datetime(created_at) ASC
            """,
            (product_id, variant_id, from_wh),
        ).fetchall()

        for batch in batches:
            if qty_needed <= 0:
                break

            take = min(batch["remaining_qty"], qty_needed)

            db.execute(
                """
                UPDATE stock_batches
                SET remaining_qty = remaining_qty - ?
                WHERE id=?
                """,
                (take, batch["id"]),
            )

            db.execute(
                """
                INSERT INTO stock_batches(
                    product_id, variant_id, warehouse_id,
                    qty, remaining_qty, cost, expiry_date, created_at
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    product_id,
                    variant_id,
                    to_wh,
                    take,
                    take,
                    batch["cost"],
                    batch["expiry_date"],
                    batch["created_at"],
                ),
            )

            new_batch_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            db.execute(
                """
                INSERT INTO stock_movements(
                    product_id,variant_id,warehouse_id,
                    batch_id,qty,type,created_at
                )
                VALUES (?,?,?,?,?,'TRANSFER_OUT',datetime('now'))
                """,
                (product_id, variant_id, from_wh, batch["id"], take),
            )

            db.execute(
                """
                INSERT INTO stock_movements(
                    product_id,variant_id,warehouse_id,
                    batch_id,qty,type,created_at
                )
                VALUES (?,?,?,?,?,'TRANSFER_IN',datetime('now'))
                """,
                (product_id, variant_id, to_wh, new_batch_id, take),
            )

            db.execute(
                """
                INSERT INTO stock_history(
                    action,type,qty,note,
                    user_id,warehouse_id,product_id,variant_id
                )
                VALUES ('TRANSFER','OUT',?, 'Transfer keluar', ?, ?, ?, ?)
                """,
                (take, user_id, from_wh, product_id, variant_id),
            )

            db.execute(
                """
                INSERT INTO stock_history(
                    action,type,qty,note,
                    user_id,warehouse_id,product_id,variant_id
                )
                VALUES ('TRANSFER','IN',?, 'Transfer masuk', ?, ?, ?, ?)
                """,
                (take, user_id, to_wh, product_id, variant_id),
            )

            qty_needed -= take

        for warehouse_id in [from_wh, to_wh]:
            _sync_stock(db, product_id, variant_id, warehouse_id)

        db.execute(
            """
            UPDATE requests
            SET status='approved',
                reason=NULL,
                approved_at=datetime('now'),
                approved_by=?
            WHERE id=?
            """,
            (user_id, request_id),
        )

        if started:
            db.commit()
        return True

    except Exception as exc:
        print("APPROVE REQUEST ERROR:", exc)
        if started:
            db.rollback()
        return False
