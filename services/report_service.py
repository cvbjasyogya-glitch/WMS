from database import get_db


# ==========================
# NORMALIZE WEEK
# ==========================
def normalize_week(data):
    result = {str(i): 0 for i in range(7)}

    for d in data:
        result[str(d.get("day"))] = d.get("total", 0)

    order = ["1", "2", "3", "4", "5", "6", "0"]
    return [result[d] for d in order]


# ==========================
# DEFAULT DATA (ANTI CRASH)
# ==========================
def default_dashboard():
    return {
        "total_product": 0,
        "total_stock": 0,
        "stock_out": 0,
        "inventory_value": 0,
        "expiring_alert": 0,
        "chart_in": [0,0,0,0,0,0,0],
        "chart_out": [0,0,0,0,0,0,0],
        "dist_labels": [],
        "dist_values": [],
        "aging": [0,0,0,0]
    }


# ==========================
# DASHBOARD DATA
# ==========================
def get_dashboard_data(warehouse_id):

    db = get_db()

    try:
        total_product = db.execute("""
            SELECT COUNT(*) as total FROM products
        """).fetchone()["total"]

        total_stock = db.execute("""
            SELECT COALESCE(SUM(qty),0) as total
            FROM stock
            WHERE warehouse_id=?
        """, (warehouse_id,)).fetchone()["total"]

        stock_out = db.execute("""
            SELECT COUNT(*) as total
            FROM stock
            WHERE warehouse_id=? AND qty <= 0
        """, (warehouse_id,)).fetchone()["total"]

        inventory_value = db.execute("""
            SELECT COALESCE(SUM(remaining_qty * cost),0) as total
            FROM stock_batches
            WHERE warehouse_id=?
        """, (warehouse_id,)).fetchone()["total"]

        aging = db.execute("""
        SELECT 
            CASE 
                WHEN age <= 30 THEN '<30'
                WHEN age <= 90 THEN '30-90'
                WHEN age <= 180 THEN '90-180'
                ELSE '>180'
            END as range,
            SUM(remaining_qty) as total
        FROM (
            SELECT 
                remaining_qty,
                CAST((julianday('now') - julianday(created_at)) AS INTEGER) as age
            FROM stock_batches
            WHERE warehouse_id=?
            AND remaining_qty > 0
        ) aging_rows
        GROUP BY range
        """,(warehouse_id,)).fetchall()

        aging_map = {"<30": 0, "30-90": 0, "90-180": 0, ">180": 0}

        for a in aging:
            aging_map[a["range"]] = a["total"]

        aging_data = list(aging_map.values())

        expiring = db.execute("""
        SELECT COUNT(*) as total
        FROM stock_batches
        WHERE warehouse_id=?
        AND expiry_date IS NOT NULL
        AND remaining_qty > 0
        AND (julianday(expiry_date) - julianday('now')) <= 30
        """,(warehouse_id,)).fetchone()["total"]

        distribution = db.execute("""
            SELECT w.name, COALESCE(SUM(s.qty),0) as total
            FROM warehouses w
            LEFT JOIN stock s ON w.id = s.warehouse_id
            GROUP BY w.id
        """).fetchall()

        dist_labels = [d["name"] for d in distribution]
        dist_values = [d["total"] for d in distribution]

        try:
            stats_in = db.execute("""
                SELECT strftime('%w', created_at) as day,
                       COALESCE(SUM(qty),0) as total
                FROM stock_movements
                WHERE type IN ('IN','TRANSFER_IN')
                AND warehouse_id=?
                AND created_at >= datetime('now', '-7 days')
                GROUP BY day
            """,(warehouse_id,)).fetchall()

            stats_out = db.execute("""
                SELECT strftime('%w', created_at) as day,
                       COALESCE(SUM(qty),0) as total
                FROM stock_movements
                WHERE type IN ('OUT','TRANSFER_OUT')
                AND warehouse_id=?
                AND created_at >= datetime('now', '-7 days')
                GROUP BY day
            """,(warehouse_id,)).fetchall()

            chart_in = normalize_week([dict(r) for r in stats_in])
            chart_out = normalize_week([dict(r) for r in stats_out])

        except:
            chart_in = [0,0,0,0,0,0,0]
            chart_out = [0,0,0,0,0,0,0]

        return {
            "total_product": total_product,
            "total_stock": total_stock,
            "stock_out": stock_out,
            "inventory_value": inventory_value,
            "expiring_alert": expiring,
            "chart_in": chart_in,
            "chart_out": chart_out,
            "dist_labels": dist_labels,
            "dist_values": dist_values,
            "aging": aging_data
        }

    except:
        return default_dashboard()


# ==========================
# STOCK LOG (FIXED)
# ==========================
def get_stock_log(warehouse_id, limit=20):

    db = get_db()

    rows = db.execute("""
    SELECT 
        sm.created_at as date,
        sm.type as action,
        p.name,
        p.sku,
        v.variant,
        w.name as warehouse,
        sm.qty
    FROM stock_movements sm
    LEFT JOIN products p ON sm.product_id = p.id
    LEFT JOIN product_variants v ON sm.variant_id = v.id
    LEFT JOIN warehouses w ON sm.warehouse_id = w.id
    WHERE sm.warehouse_id=?
    ORDER BY sm.created_at DESC
    LIMIT ?
    """, (warehouse_id, limit)).fetchall()

    return [dict(r) for r in rows]


# ==========================
# REQUEST PENDING
# ==========================
def get_pending_requests(warehouse_id):

    db = get_db()

    data = db.execute("""
    SELECT COUNT(*) as total
    FROM requests
    WHERE status='pending'
    AND to_warehouse=?
    """,(warehouse_id,)).fetchone()

    return data["total"] if data else 0
