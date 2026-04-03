from flask import Blueprint, render_template, session, request, jsonify
from database import get_db
from services.rbac import has_permission, is_scoped_role, normalize_role
from services.hris_catalog import get_hris_navigation_modules, role_can_see_hris_navigation

dashboard_bp = Blueprint("dashboard", __name__)


def _can_view_inventory_value():
    return normalize_role(session.get("role")) in {"owner", "super_admin"}


def default_dashboard():
    return {
        "total_product": 0,
        "total_stock": 0,
        "stock_out": 0,
        "inventory_value": 0,
        "expiring_alert": 0,
        "pending_requests": 0,
        "aging": [0, 0, 0, 0]
    }


def _workspace_tile(label, href, summary, badge, accent, icon):
    return {
        "label": label,
        "href": href,
        "summary": summary,
        "badge": badge,
        "accent": accent,
        "icon": icon,
    }


def _build_workspace_sections(role):
    normalized_role = normalize_role(role)
    sections = []

    coordination_items = [
        _workspace_tile(
            "Pengumuman",
            "/announcements/",
            "Broadcast operasional, update penting, dan perubahan jadwal terbaru.",
            "Info",
            "sky",
            "PG",
        ),
        _workspace_tile(
            "Meeting Live",
            "/meetings/",
            "Masuk room meeting browser yang ringan untuk koordinasi cepat tim.",
            "Live",
            "violet",
            "MT",
        ),
        _workspace_tile(
            "Absen Foto",
            "/absen/",
            "Clock in, break, dan check out dengan geotag dan foto langsung dari browser.",
            "Daily",
            "emerald",
            "AB",
        ),
        _workspace_tile(
            "Libur",
            "/libur/",
            "Ajukan cuti dan lihat status approval bulanan dari satu portal sederhana.",
            "Leave",
            "amber",
            "LV",
        ),
        _workspace_tile(
            "Report Harian",
            "/laporan-harian/",
            "Kirim update kerja, report live, dan lampiran bukti dari portal harian.",
            "Report",
            "rose",
            "RP",
        ),
    ]

    if has_permission(normalized_role, "view_schedule"):
        coordination_items.append(
            _workspace_tile(
                "Jadwal",
                "/schedule/",
                "Kelola board jadwal tim, live schedule, dan override operasional.",
                "Planner",
                "indigo",
                "JD",
            )
        )

    coordination_items.append(
        _workspace_tile(
            "Chat Operasional",
            "/chat/",
            "Buka komunikasi cepat, panggilan, dan notifikasi lintas tim.",
            "Chat",
            "cyan",
            "CT",
        )
    )

    if has_permission(normalized_role, "view_crm"):
        coordination_items.append(
            _workspace_tile(
                "CRM",
                "/crm/",
                "Kelola prospek, follow up, dan aktivitas pelanggan dalam satu panel.",
                "CRM",
                "orange",
                "CM",
            )
        )

    sections.append(
        {
            "title": "Koordinasi Harian",
            "summary": "Akses cepat untuk komunikasi, kehadiran, dan ritme kerja tim setiap hari.",
            "items": coordination_items,
        }
    )

    if normalized_role != "hr":
        wms_items = [
            _workspace_tile(
                "Dashboard WMS",
                "/",
                "Masuk ke dashboard operasional gudang untuk monitor stok dan aktivitas terakhir.",
                "WMS",
                "blue",
                "DB",
            ),
            _workspace_tile(
                "Info Produk",
                "/info-produk/",
                "Cari informasi SKU, harga, dan stok produk dengan lookup yang cepat.",
                "Lookup",
                "sky",
                "IF",
            ),
            _workspace_tile(
                "Stok & Produk",
                "/stock/",
                "Monitor stok aktif, nilai jual, aging batch, dan kelola master produk dari workspace yang sama.",
                "Studio",
                "emerald",
                "ST",
            ),
            _workspace_tile(
                "Inbound",
                "/inbound/",
                "Tambah batch barang masuk dengan panel kerja yang cepat dan rapi.",
                "Flow",
                "teal",
                "IN",
            ),
            _workspace_tile(
                "Outbound",
                "/outbound/",
                "Kurangi stok keluar dengan validasi qty terhadap stok yang tersedia.",
                "Flow",
                "rose",
                "OU",
            ),
            _workspace_tile(
                "Transfer",
                "/transfers/",
                "Pindahkan stok antar gudang dengan lane transfer yang jelas.",
                "Flow",
                "indigo",
                "TR",
            ),
            _workspace_tile(
                "Request Gudang",
                "/request/",
                "Susun request antar gudang dan pantau approval-nya.",
                "Queue",
                "amber",
                "RQ",
            ),
            _workspace_tile(
                "Request Owner",
                "/request/owner",
                "Kirim kebutuhan barang langsung ke owner melalui jalur request khusus.",
                "Owner",
                "orange",
                "RO",
            ),
            _workspace_tile(
                "Stock Opname",
                "/so/",
                "Cocokkan stok fisik dan sistem untuk display maupun gudang.",
                "Control",
                "slate",
                "SO",
            ),
        ]

        if has_permission(normalized_role, "view_approvals"):
            wms_items.append(
                _workspace_tile(
                    "Approvals",
                    "/approvals",
                    "Review inbound, outbound, dan adjustment yang menunggu persetujuan.",
                    "Approval",
                    "pink",
                    "AP",
                )
            )

        if has_permission(normalized_role, "view_audit"):
            wms_items.append(
                _workspace_tile(
                    "Audit Log",
                    "/audit/",
                    "Lacak histori perubahan dan transaksi operasional untuk investigasi cepat.",
                    "Trace",
                    "slate",
                    "AU",
                )
            )

        sections.append(
            {
                "title": "Operasional Gudang",
                "summary": "Panel kerja inti untuk transaksi barang, kontrol stok, dan pengawasan operasional.",
                "items": wms_items,
            }
        )

    if role_can_see_hris_navigation(normalized_role):
        hris_items = [
            _workspace_tile(
                "HRIS",
                "/hris/",
                "Masuk ke dashboard HRIS untuk employee, leave, geotag, dan modul people ops.",
                "People",
                "cyan",
                "HR",
            )
        ]

        for module in get_hris_navigation_modules(normalized_role)[:4]:
            hris_items.append(
                _workspace_tile(
                    module["label"],
                    f"/hris/{module['slug']}",
                    module["summary"],
                    module.get("status", "HRIS"),
                    "sky" if module["slug"] in {"dashboard", "announcement"} else "violet",
                    module["label"][:2].upper(),
                )
            )

        sections.append(
            {
                "title": "People & HRIS",
                "summary": "Akses cepat ke modul HRIS yang memang tersedia untuk role Anda.",
                "items": hris_items,
            }
        )

    utility_items = [
        _workspace_tile(
            "Pengaturan Akun",
            "/account/settings",
            "Atur profil, preferensi notifikasi, dan pengaturan akun pribadi.",
            "Account",
            "slate",
            "AK",
        )
    ]

    if has_permission(normalized_role, "view_admin"):
        utility_items.append(
            _workspace_tile(
                "Admin",
                "/admin",
                "Kelola user, gudang, dan pengaturan sistem tingkat lanjut.",
                "Admin",
                "indigo",
                "AD",
            )
        )

    sections.append(
        {
            "title": "Utilitas",
            "summary": "Shortcut cepat untuk pengaturan akun dan administrasi sistem.",
            "items": utility_items,
        }
    )

    return sections


def validate_warehouse(db, warehouse_id):
    exist = db.execute(
        "SELECT id FROM warehouses WHERE id=?",
        (warehouse_id,)
    ).fetchone()
    return warehouse_id if exist else 1


# ==========================
# DASHBOARD QUERY
# ==========================
def get_dashboard_safe(db, warehouse_id):

    data = default_dashboard()

    try:
        data["total_product"] = db.execute("""
            SELECT COUNT(*) FROM products
        """).fetchone()[0]

        data["total_stock"] = db.execute("""
            SELECT COALESCE(SUM(qty),0)
            FROM stock
            WHERE warehouse_id=?
        """, (warehouse_id,)).fetchone()[0]

        data["stock_out"] = db.execute("""
            SELECT COUNT(*) 
            FROM stock
            WHERE warehouse_id=? AND qty <= 0
        """, (warehouse_id,)).fetchone()[0]

        data["pending_requests"] = db.execute("""
            SELECT COUNT(*)
            FROM requests
            WHERE status='pending'
              AND (from_warehouse=? OR to_warehouse=?)
        """, (warehouse_id, warehouse_id)).fetchone()[0]

        data["inventory_value"] = db.execute("""
            SELECT COALESCE(SUM(
                s.qty * CASE
                    WHEN COALESCE(v.price_nett, 0) > 0 THEN v.price_nett
                    WHEN COALESCE(v.price_discount, 0) > 0 THEN v.price_discount
                    ELSE COALESCE(v.price_retail, 0)
                END
            ), 0)
            FROM stock s
            JOIN product_variants v ON v.id = s.variant_id
            WHERE s.warehouse_id=?
        """, (warehouse_id,)).fetchone()[0]

        data["expiring_alert"] = db.execute("""
            SELECT COUNT(*)
            FROM stock_batches
            WHERE warehouse_id=?
              AND remaining_qty > 0
              AND expiry_date IS NOT NULL
              AND date(expiry_date) <= date('now', '+30 day')
        """, (warehouse_id,)).fetchone()[0]

        aging = db.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN age_days <= 30 THEN 1 ELSE 0 END), 0) AS bucket_1,
                COALESCE(SUM(CASE WHEN age_days BETWEEN 31 AND 90 THEN 1 ELSE 0 END), 0) AS bucket_2,
                COALESCE(SUM(CASE WHEN age_days BETWEEN 91 AND 180 THEN 1 ELSE 0 END), 0) AS bucket_3,
                COALESCE(SUM(CASE WHEN age_days > 180 THEN 1 ELSE 0 END), 0) AS bucket_4
            FROM (
                SELECT CAST(julianday('now') - julianday(MIN(created_at)) AS INTEGER) AS age_days
                FROM stock_batches
                WHERE warehouse_id=? AND remaining_qty > 0
                GROUP BY product_id, variant_id
            )
        """, (warehouse_id,)).fetchone()

        if aging:
            data["aging"] = [
                aging["bucket_1"],
                aging["bucket_2"],
                aging["bucket_3"],
                aging["bucket_4"],
            ]

    except Exception as e:
        print("DASHBOARD QUERY ERROR:", e)
        pass

    return data


# ==========================
# DASHBOARD PAGE
# ==========================
@dashboard_bp.route("/")
def dashboard():

    db = get_db()

    warehouse_id = session.get("warehouse_id")
    if not warehouse_id:
        warehouse = db.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
        warehouse_id = warehouse["id"] if warehouse else 1
        session["warehouse_id"] = warehouse_id

    warehouse_id = validate_warehouse(db, warehouse_id)

    data = get_dashboard_safe(db, warehouse_id)
    can_view_inventory_value = _can_view_inventory_value()
    if not can_view_inventory_value:
        data["inventory_value"] = 0

    try:
        logs_raw = db.execute("""
            SELECT
                sm.created_at AS date,
                sm.type,
                sm.qty,
                p.name AS product_name,
                v.variant
            FROM stock_movements sm
            LEFT JOIN products p ON sm.product_id = p.id
            LEFT JOIN product_variants v ON sm.variant_id = v.id
            WHERE sm.warehouse_id=?
            ORDER BY datetime(sm.created_at) DESC
            LIMIT 20
        """, (warehouse_id,)).fetchall()

        logs = [dict(r) for r in logs_raw]

    except:
        logs = []

    warehouses = db.execute("""
        SELECT * FROM warehouses ORDER BY name
    """).fetchall()

    return render_template(
        "index.html",
        data=data,
        logs=logs,
        warehouses=warehouses,
        warehouse_id=warehouse_id,
        can_view_inventory_value=can_view_inventory_value,
    )


@dashboard_bp.route("/workspace/")
def workspace_gateway():
    db = get_db()

    warehouse_id = session.get("warehouse_id")
    if warehouse_id:
        warehouse_id = validate_warehouse(db, warehouse_id)
    else:
        warehouse = db.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
        warehouse_id = warehouse["id"] if warehouse else 1
        session["warehouse_id"] = warehouse_id

    warehouse = db.execute(
        "SELECT name FROM warehouses WHERE id=?",
        (warehouse_id,),
    ).fetchone()
    warehouse_name = warehouse["name"] if warehouse else f"Gudang {warehouse_id}"

    role = normalize_role(session.get("role"))
    sections = _build_workspace_sections(role)
    total_modules = sum(len(section["items"]) for section in sections)

    return render_template(
        "workspace_gateway.html",
        sections=sections,
        warehouse_name=warehouse_name,
        role_label=(role or "guest").replace("_", " ").title(),
        username=session.get("username", "guest"),
        total_modules=total_modules,
    )


# ==========================
# REALTIME API
# ==========================
@dashboard_bp.route("/api/realtime")
def dashboard_realtime():

    db = get_db()

    warehouse_id = session.get("warehouse_id")
    if not warehouse_id:
        warehouse = db.execute("SELECT id FROM warehouses LIMIT 1").fetchone()
        warehouse_id = warehouse["id"] if warehouse else 1
        session["warehouse_id"] = warehouse_id

    warehouse_id = validate_warehouse(db, warehouse_id)

    data = get_dashboard_safe(db, warehouse_id)
    if not _can_view_inventory_value():
        data["inventory_value"] = 0

    return jsonify(data)


# ==========================
# SET WAREHOUSE
# ==========================
@dashboard_bp.route("/set_warehouse", methods=["POST"])
def set_warehouse():

    try:
        db = get_db()
        warehouse_id = int(request.form.get("warehouse_id"))
        warehouse = db.execute(
            "SELECT id FROM warehouses WHERE id=?",
            (warehouse_id,),
        ).fetchone()
        if not warehouse:
            return jsonify({"status": "error", "message": "Gudang tidak valid"}), 400

        role = session.get("role")
        if is_scoped_role(role):
            allowed_warehouse = session.get("warehouse_id")
            session["warehouse_id"] = allowed_warehouse or warehouse_id
            return jsonify({"status": "ok", "warehouse_id": session["warehouse_id"]})

        session["warehouse_id"] = warehouse_id
        return jsonify({"status": "ok", "warehouse_id": warehouse_id})
    except:
        return jsonify({"status": "error"}), 400
