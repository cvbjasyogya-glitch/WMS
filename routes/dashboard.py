from flask import Blueprint, render_template, session, request, jsonify, redirect, url_for
from database import get_db
from services.rbac import can_access_pos_terminal, has_permission, is_scoped_role, normalize_role
from services.hris_catalog import get_hris_navigation_modules, role_can_see_hris_navigation
from services.workspace_icons import (
    get_workspace_icon_asset,
    get_workspace_icon_class,
    get_workspace_icon_symbol,
    get_hris_workspace_icon_key,
)

dashboard_bp = Blueprint("dashboard", __name__)

BJAS_DRIVE_EXTERNAL_URL = "https://mataramsport.space"

WMS_ROUTE_ALIASES = {
    "dashboard": "/dashboard/",
    "barcode-stiker": "/stock/barcode",
    "input-item": "/stock/?workspace=products",
    "request-owner": "/request/owner",
    "request-gudang": "/request/",
    "stock-opname": "/so/",
    "transfers": "/transfers/",
    "outbound": "/outbound/",
    "inbound": "/inbound/",
    "stock-produk": "/stock/",
    "audit-operasional": "/audit/",
}


def _redirect_with_query(target):
    query_string = request.query_string.decode("utf-8", errors="ignore")
    if not query_string:
        return redirect(target)

    separator = "&" if "?" in target else "?"
    return redirect(f"{target}{separator}{query_string}")

MODULE_ITEM_REDIRECTS = {
    "report": {
        "laporan-staff-penjualan": "/kasir/staff-sales",
        "laporan-stok": "/stock/",
        "laporan-kehadiran": "/hris/attendance",
        "laporan-report-karyawan": "/hris/report",
    },
    "sales": {
        "sales-jalan": "/laporan-harian/",
        "customer-penawaran-barang": "/crm/?tab=contacts",
        "invoice-penjualan": "/kasir/invoice",
        "report": "/kasir/staff-sales",
    },
}


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


def _workspace_tile(label, href, summary, badge, accent, icon_key):
    return {
        "label": label,
        "href": href,
        "summary": summary,
        "badge": badge,
        "accent": accent,
        "icon_key": icon_key,
        "icon_asset": get_workspace_icon_asset(icon_key),
        "icon_class": get_workspace_icon_class(icon_key),
        "icon_symbol": get_workspace_icon_symbol(icon_key),
    }


def _portal_card(label, href, summary, badge, accent, icon_key, badge_tone="neutral", status_label="", status_tone="green"):
    return {
        "label": label,
        "href": href,
        "summary": summary,
        "badge": badge,
        "badge_tone": badge_tone,
        "status_label": status_label,
        "status_tone": status_tone,
        "accent": accent,
        "icon_asset": get_workspace_icon_asset(icon_key),
        "icon_class": get_workspace_icon_class(icon_key),
        "icon_symbol": get_workspace_icon_symbol(icon_key),
    }


def _hub_nav(label, slug, icon_key, note="", target=""):
    return {
        "label": label,
        "slug": slug,
        "icon_asset": get_workspace_icon_asset(icon_key),
        "icon_class": get_workspace_icon_class(icon_key),
        "icon_symbol": get_workspace_icon_symbol(icon_key),
        "note": note,
        "target": target,
    }


def _hub_card(scope, title, summary, badge="Buka", tone="blue", target=""):
    return {
        "scope": scope,
        "title": title,
        "summary": summary,
        "badge": badge,
        "tone": tone,
        "target": target,
    }


INTERNAL_MODULE_HUBS = {
    "hris": {
        "label": "BJAS HRIS",
        "eyebrow": "People Ops",
        "title": "Employee and Policy",
        "description": "Data karyawan, kontrak, payroll, KPI, THR, dan surat peringatan.",
        "permission": "hris",
        "nav": [
            _hub_nav("Dashboard", "dashboard", "hris-home", target="/modul/hris/"),
            _hub_nav("Kontrak", "kontrak", "hris-documents"),
            _hub_nav("Employee Data", "employee-data", "hris-employee", target="/hris/employee"),
            _hub_nav("Payroll", "payroll", "hris-payroll", target="/hris/payroll"),
            _hub_nav("KPI", "kpi", "hris-performance", target="/hris/pms"),
            _hub_nav("THR", "thr", "wms-request-owner"),
            _hub_nav("Warning Letter", "warning-letter", "hris-documents"),
        ],
        "cards": [
            _hub_card("Employee", "Employee Data", "Profil karyawan, posisi, homebase, dan data kerja aktif.", "Core", "green", "/hris/employee"),
            _hub_card("Payroll", "Payroll", "Struktur gaji, payroll, THR, dan komponen kompensasi.", "HRIS", "blue", "/hris/payroll"),
            _hub_card("KPI", "KPI", "Target kerja, penilaian, dan ringkasan performa staff.", "Target", "amber", "/hris/pms"),
            _hub_card("Dokumen", "Kontrak dan Warning Letter", "Arsip kontrak, policy HR, dan dokumen pembinaan.", "Dokumen", "blue", "/modul/hris/kontrak"),
        ],
    },
    "attendance": {
        "label": "BJAS Attendance",
        "eyebrow": "Kehadiran",
        "title": "Attendance Control",
        "description": "Jadwal kerja, absen foto, report, dan late overtime.",
        "permission": "access_attendance_portal",
        "nav": [
            _hub_nav("Dashboard", "dashboard", "hris-home", target="/modul/attendance/"),
            _hub_nav("Jadwal Kerja", "jadwal-kerja", "coordination-jadwal", target="/schedule/"),
            _hub_nav("Absen Foto", "absen-foto", "coordination-absen-foto", target="/absen/"),
            _hub_nav("Report", "report", "coordination-report-harian"),
            _hub_nav("Late & Overtime", "late-overtime", "coordination-absen-foto", target="/lembur/"),
        ],
        "cards": [
            _hub_card("Jadwal", "Jadwal Kerja", "Board jadwal dan shift tim per homebase.", "Planner", "blue", "/schedule/"),
            _hub_card("Absen", "Absen Foto", "Clock in, break, dan check out dengan foto.", "Daily", "green", "/absen/"),
            _hub_card("Report", "Report Kehadiran", "Ringkasan attendance dan laporan harian.", "Report", "blue", "/modul/attendance/report"),
            _hub_card("Overtime", "Late & Overtime", "Pengajuan lembur dan catatan keterlambatan.", "Review", "amber", "/lembur/"),
        ],
    },
    "pos": {
        "label": "BJAS POS",
        "eyebrow": "Kasir",
        "title": "POS Workspace",
        "description": "Kasir, transaksi, shift closing, log penjualan, dan cetak struk.",
        "permission": "pos",
        "nav": [
            _hub_nav("Dashboard", "dashboard", "hris-home", target="/kasir/"),
            _hub_nav("Cetak Struk", "cetak-struk", "hris-documents", target="/kasir/log"),
            _hub_nav("Rekapitulasi Shift", "rekapitulasi-shift", "coordination-report-harian", target="/kasir/staff-sales"),
            _hub_nav("Log Penjualan", "log-penjualan", "wms-audit-log", target="/kasir/log"),
            _hub_nav("Shift Closing", "shift-closing", "wms-approvals", target="/kasir/log#tutup-kasir"),
            _hub_nav("Transaksi", "transaksi", "wms-kasir", target="/kasir/"),
            _hub_nav("Cashier", "cashier", "wms-kasir", target="/kasir/"),
        ],
        "cards": [
            _hub_card("Kasir", "Cashier", "Masuk ke layar transaksi kasir harian.", "Buka", "green", "/kasir/"),
            _hub_card("Closing", "Shift Closing", "Tutup kasir dan rekap shift.", "Shift", "amber", "/kasir/log#tutup-kasir"),
            _hub_card("Log", "Log Penjualan", "Riwayat transaksi dan cetak ulang struk.", "Log", "blue", "/kasir/log"),
            _hub_card("Rekap", "Rekapitulasi Shift", "Laporan penjualan staff per periode.", "Report", "blue", "/kasir/staff-sales"),
        ],
    },
    "wms": {
        "label": "BJAS WMS",
        "eyebrow": "Gudang",
        "title": "Warehouse Control",
        "description": "Barcode, request, stock opname, transfer, inbound, outbound, dan stock produk.",
        "permission": "view_wms",
        "nav": [
            _hub_nav("Dashboard", "dashboard", "hris-home", target="/wms/dashboard"),
            _hub_nav("Barcode/Stiker", "barcode-stiker", "utility-generic", target="/wms/barcode-stiker"),
            _hub_nav("Barcode Mataram", "barcode-mataram", "utility-generic", target="/wms/barcode-stiker"),
            _hub_nav("Input Item", "input-item", "utility-generic", target="/wms/input-item"),
            _hub_nav("Request Owner", "request-owner", "wms-request-owner", target="/wms/request-owner"),
            _hub_nav("Request Gudang", "request-gudang", "wms-request-gudang", target="/wms/request-gudang"),
            _hub_nav("Stock Opname", "stock-opname", "wms-stock-opname", target="/wms/stock-opname"),
            _hub_nav("Transfers", "transfers", "wms-transfer", target="/wms/transfers"),
            _hub_nav("Outbound", "outbound", "wms-outbound", target="/wms/outbound"),
            _hub_nav("Inbound", "inbound", "wms-inbound", target="/wms/inbound"),
            _hub_nav("Stock & Produk", "stock-produk", "wms-stok-produk", target="/wms/stock-produk"),
            _hub_nav("Audit Operasional", "audit-operasional", "wms-audit-log", target="/wms/audit-operasional"),
        ],
        "cards": [
            _hub_card("Stock", "Stock & Produk", "Master produk, stok aktif, aging, dan nilai jual.", "Stock", "green", "/wms/stock-produk"),
            _hub_card("Transfer", "Transfers", "Perpindahan barang antar gudang.", "Flow", "blue", "/wms/transfers"),
            _hub_card("Request", "Request Gudang", "Permintaan barang dan approval antar gudang.", "Queue", "amber", "/wms/request-gudang"),
            _hub_card("Opname", "Stock Opname", "Kontrol stok fisik dan selisih operasional.", "Audit", "blue", "/wms/stock-opname"),
        ],
    },
    "finance": {
        "label": "BJAS Finance",
        "eyebrow": "Keuangan",
        "title": "Finance Workspace",
        "description": "Biaya operasional, supplier, cashflow, update produk, dan report keuangan.",
        "permission": "view_wms",
        "nav": [
            _hub_nav("Dashboard", "dashboard", "hris-home", target="/modul/finance/"),
            _hub_nav("Biaya Operasional", "biaya-operasional", "wms-request-owner"),
            _hub_nav("Permintaan Supplier", "permintaan-supplier", "wms-request-gudang"),
            _hub_nav("Cashflow Update Produk", "cashflow-update-produk", "wms-stok-produk"),
            _hub_nav("Report Keuangan", "report-keuangan", "hris-report"),
        ],
        "cards": [
            _hub_card("Biaya", "Biaya Operasional", "Kontrol request biaya dan kebutuhan toko.", "Finance", "amber", "/modul/finance/biaya-operasional"),
            _hub_card("Supplier", "Permintaan Supplier", "Permintaan pembelian dan follow up supplier.", "Supplier", "blue", "/modul/finance/permintaan-supplier"),
            _hub_card("Cashflow", "Cashflow Update Produk", "Pantau biaya, stok, dan perubahan produk.", "Cashflow", "green", "/modul/finance/cashflow-update-produk"),
            _hub_card("Report", "Report Keuangan", "Ringkasan keuangan dan dokumen pendukung.", "Report", "blue", "/modul/finance/report-keuangan"),
        ],
    },
    "sales": {
        "label": "BJAS Sales",
        "eyebrow": "Penjualan",
        "title": "Sales Workspace",
        "description": "Sales jalan, penawaran customer, invoice, dan laporan penjualan.",
        "permission": "access_daily_report_portal",
        "nav": [
            _hub_nav("Dashboard", "dashboard", "hris-home", target="/modul/sales/"),
            _hub_nav("Sales Jalan", "sales-jalan", "coordination-report-harian", target="/laporan-harian/"),
            _hub_nav("Customer Penawaran Barang", "customer-penawaran-barang", "coordination-crm", target="/crm/?tab=contacts"),
            _hub_nav("Invoice Penjualan", "invoice-penjualan", "hris-documents", target="/kasir/invoice"),
        ],
        "cards": [
            _hub_card("Sales", "Sales Jalan", "Laporan aktivitas sales dan follow up harian.", "Daily", "green", "/laporan-harian/"),
            _hub_card("Customer", "Customer Penawaran Barang", "Data customer dan kebutuhan penawaran.", "CRM", "blue", "/crm/?tab=contacts"),
            _hub_card("Invoice", "Invoice Penjualan", "Dokumen invoice dan transaksi penjualan.", "Invoice", "amber", "/kasir/invoice"),
            _hub_card("Report", "Report Penjualan", "Ringkasan penjualan dan aktivitas staff.", "Report", "blue", "/kasir/staff-sales"),
        ],
    },
    "crm": {
        "label": "BJAS CRM",
        "eyebrow": "Customer",
        "title": "CRM Workspace",
        "description": "Customer data, member senaran, customer history, dan campaign.",
        "permission": "view_crm",
        "nav": [
            _hub_nav("Dashboard", "dashboard", "hris-home", target="/modul/crm/"),
            _hub_nav("Customer Data", "customer-data", "coordination-crm", target="/crm/?tab=contacts"),
            _hub_nav("Member Senaran", "member-senaran", "coordination-crm", target="/crm/?tab=members"),
            _hub_nav("Customer History", "customer-history", "wms-audit-log", target="/crm/?tab=purchases"),
            _hub_nav("Campaign", "campaign", "coordination-pengumuman"),
        ],
        "cards": [
            _hub_card("Customer", "Customer Data", "Kontak, kebutuhan, dan data customer.", "Data", "blue", "/crm/?tab=contacts"),
            _hub_card("Member", "Member Senaran", "Daftar member dan segmentasi pelanggan.", "Member", "green", "/crm/?tab=members"),
            _hub_card("History", "Customer History", "Riwayat pembelian dan interaksi customer.", "History", "amber", "/crm/?tab=purchases"),
            _hub_card("Campaign", "Campaign", "Aktivitas campaign dan follow-up customer.", "Campaign", "blue", "/modul/crm/campaign"),
        ],
    },
    "drive": {
        "label": "BJAS Drive",
        "eyebrow": "Dokumen",
        "title": "Company Drive",
        "description": "Teams, my drive, company file, HR document, finance document, dan shared file.",
        "permission": "hris_documents",
        "nav": [
            _hub_nav("Dashboard", "dashboard", "hris-home", target="/hris/documents"),
            _hub_nav("Teams", "teams", "group-workspace", target="/hris/documents"),
            _hub_nav("My Drive", "my-drive", "hris-documents", target="/hris/documents"),
            _hub_nav("Company File", "company-file", "hris-documents", target="/hris/documents"),
            _hub_nav("HR Document", "hr-document", "hris-employee", target="/hris/documents"),
            _hub_nav("Finance Document", "finance-document", "wms-request-owner", target="/hris/documents"),
            _hub_nav("Shared File", "shared-file", "hris-documents", target="/hris/documents"),
        ],
        "cards": [
            _hub_card("Company", "Company File", "File perusahaan dan arsip operasional.", "File", "blue", "/hris/documents"),
            _hub_card("HR", "HR Document", "Dokumen HR, kontrak, policy, dan form internal.", "HR", "green", "/hris/documents"),
            _hub_card("Finance", "Finance Document", "Dokumen biaya, supplier, dan keuangan.", "Finance", "amber", "/hris/documents"),
            _hub_card("Shared", "Shared File", "File bersama lintas tim dan homebase.", "Shared", "blue", "/hris/documents"),
        ],
    },
    "report": {
        "label": "BJAS Report",
        "eyebrow": "Laporan",
        "title": "Report Workspace",
        "description": "Laporan staff penjualan, stok, kehadiran, dan report karyawan.",
        "permission": "report",
        "nav": [
            _hub_nav("Dashboard", "dashboard", "hris-home", target="/modul/report/"),
            _hub_nav("Laporan Staff Penjualan", "laporan-staff-penjualan", "coordination-report-harian", target="/kasir/staff-sales"),
            _hub_nav("Laporan Stok", "laporan-stok", "wms-stok-produk", target="/stock/"),
            _hub_nav("Laporan Kehadiran", "laporan-kehadiran", "coordination-absen-foto", target="/hris/attendance"),
            _hub_nav("Laporan Report Karyawan", "laporan-report-karyawan", "hris-report", target="/hris/report"),
        ],
        "cards": [
            _hub_card("Sales", "Laporan Staff Penjualan", "Rekap aktivitas dan penjualan staff.", "Sales", "green", "/kasir/staff-sales"),
            _hub_card("Stock", "Laporan Stok", "Stock aktif, aging, dan nilai barang.", "Stock", "blue", "/stock/"),
            _hub_card("Attendance", "Laporan Kehadiran", "Rekap absen dan kedisiplinan.", "Absen", "amber", "/hris/attendance"),
            _hub_card("Employee", "Laporan Report Karyawan", "Report people ops dan dokumen HR.", "HRIS", "blue", "/hris/report"),
        ],
    },
    "informasi": {
        "label": "BJAS Informasi",
        "eyebrow": "Standar Kerja",
        "title": "SOP and Policy",
        "description": "Standar operasional, aturan kerja, dan kebijakan perusahaan.",
        "permission": "view_announcements",
        "default_item": "sop-policy",
        "toast": "Dokumen SOP kasir sedang disiapkan.",
        "nav": [
            _hub_nav("Beranda", "beranda", "hris-home", target="/workspace/"),
            _hub_nav("BJAS News", "bjas-news", "hris-announcement", target="/modul/informasi/bjas-news"),
            _hub_nav("Memo Internal", "memo-internal", "hris-documents", target="/modul/informasi/memo-internal"),
            _hub_nav("SOP and Policy", "sop-policy", "hris-documents", target="/modul/informasi/sop-policy"),
            _hub_nav("Knowledge Base", "knowledge-base", "hris-report", "Panduan kerja", "/modul/informasi/knowledge-base"),
            _hub_nav("Announcement", "announcement", "coordination-pengumuman", target="/announcements/"),
        ],
        "cards": [
            _hub_card("POS", "SOP Transaksi Kasir dan Shift Closing", "Standar proses pembayaran, retur, closing shift, dan serah terima kas.", "Baru", "green", "/modul/informasi/sop-policy"),
            _hub_card("WMS", "Policy Transfer Barang Antar Cabang", "Aturan transfer produk, pencatatan gudang, dan validasi penerimaan barang.", "Panduan", "blue", "/modul/informasi/policy-transfer-barang"),
            _hub_card("CRM", "Panduan Pelayanan Customer B2C dan B2B", "Standar komunikasi, follow-up, dan pencatatan kebutuhan customer.", "Info", "blue", "/modul/informasi/panduan-pelayanan-customer"),
            _hub_card("HRIS", "Policy Kehadiran dan Kedisiplinan", "Kebijakan jam kerja, keterlambatan, lembur, izin, dan approval manager.", "Penting", "amber", "/modul/informasi/policy-kehadiran"),
        ],
    },
    "permission": {
        "label": "BJAS Permission",
        "eyebrow": "Approval",
        "title": "Permission and Approval",
        "description": "Request permission, libur, izin sakit, approval manager, dan log.",
        "permission": "permission",
        "nav": [
            _hub_nav("Dashboard", "dashboard", "hris-home", target="/modul/permission/"),
            _hub_nav("Request Permission", "request-permission", "wms-approvals", target="/hris/approval"),
            _hub_nav("Libur / Cuti", "libur-cuti", "coordination-libur", target="/libur/"),
            _hub_nav("Izin Sakit", "izin-sakit", "coordination-libur"),
            _hub_nav("Approval Manager", "approval-manager", "wms-approvals", target="/approvals/"),
            _hub_nav("Log", "log", "wms-audit-log", target="/audit/"),
        ],
        "cards": [
            _hub_card("Permission", "Request Permission", "Meja approval izin dan permission staff.", "Request", "blue", "/hris/approval"),
            _hub_card("Leave", "Libur / Cuti", "Pengajuan libur, cuti, dan izin sakit.", "Leave", "green", "/libur/"),
            _hub_card("Approval", "Approval Manager", "Approval operasional dari manager atau HR.", "Approval", "amber", "/approvals/"),
            _hub_card("Log", "Log", "Riwayat approval dan perubahan status.", "Trace", "blue", "/audit/"),
        ],
    },
    "setting": {
        "label": "BJAS Setting",
        "eyebrow": "System",
        "title": "Setting and Access",
        "description": "Department, user management, role access, branch store, dan audit log.",
        "permission": "view_admin",
        "nav": [
            _hub_nav("Dashboard", "dashboard", "hris-home", target="/admin/"),
            _hub_nav("Department", "department", "group-system", target="/admin/department"),
            _hub_nav("User Management", "user-management", "utility-account-settings", target="/admin/users"),
            _hub_nav("Role & Access", "role-access", "wms-approvals", target="/admin/permissions"),
            _hub_nav("Branch/Store", "branch-store", "group-workspace", target="/admin/warehouses"),
            _hub_nav("Audit Log", "audit-log", "wms-audit-log", target="/audit/"),
        ],
        "cards": [
            _hub_card("User", "User Management", "Kelola user dan akses aplikasi.", "User", "blue", "/admin/users"),
            _hub_card("Role", "Role & Access", "Pengaturan role, permission, dan scope.", "Access", "green", "/admin/permissions"),
            _hub_card("Branch", "Branch/Store", "Cabang, homebase, dan struktur outlet.", "Branch", "amber", "/admin/warehouses"),
            _hub_card("Audit", "Audit Log", "Jejak aktivitas dan perubahan sistem.", "Audit", "blue", "/audit/"),
        ],
    },
}


def _module_hub_allowed(module_key, role):
    module = INTERNAL_MODULE_HUBS.get(module_key)
    if not module:
        return False
    normalized_role = normalize_role(role)
    permission = module.get("permission")
    hris_modules = get_hris_navigation_modules(normalized_role)
    hris_module_slugs = {item["slug"] for item in hris_modules}

    if permission == "hris":
        return bool(hris_modules)
    if permission == "hris_documents":
        return "documents" in hris_module_slugs
    if permission == "report":
        return has_permission(normalized_role, "access_daily_report_portal") or "report" in hris_module_slugs
    if permission == "permission":
        return has_permission(normalized_role, "view_approvals") or "approval" in hris_module_slugs
    if permission == "pos":
        return can_access_pos_terminal(normalized_role)
    return has_permission(normalized_role, permission)


def _build_module_hub(module_key, item_slug=None):
    module = INTERNAL_MODULE_HUBS.get(module_key)
    if not module:
        return None

    default_slug = item_slug or module.get("default_item") or (module["nav"][0]["slug"] if module.get("nav") else "dashboard")
    selected_nav = next((item for item in module["nav"] if item["slug"] == default_slug), module["nav"][0])
    nav_items = []
    for item in module["nav"]:
        nav_item = dict(item)
        nav_item["active"] = item["slug"] == selected_nav["slug"]
        nav_item["href"] = item.get("target") or f"/modul/{module_key}/{item['slug']}"
        nav_items.append(nav_item)

    cards = [dict(card) for card in module.get("cards", [])]
    for card in cards:
        card.setdefault("target", "")

    return {
        "key": module_key,
        "label": module["label"],
        "eyebrow": module["eyebrow"],
        "title": selected_nav["label"] if selected_nav["slug"] not in {"dashboard", "sop-policy"} else module["title"],
        "description": module["description"],
        "selected": selected_nav,
        "nav": nav_items,
        "cards": cards,
        "toast": module.get("toast", ""),
    }


def _build_unavailable_module_context(module_key, item_slug=None):
    safe_key = str(module_key or "modul").strip().lower() or "modul"
    module = INTERNAL_MODULE_HUBS.get(safe_key)
    module_label = module["label"] if module else "Modul"
    module_eyebrow = module["eyebrow"] if module else "Fitur"
    unavailable_label = str(item_slug or safe_key).replace("-", " ").strip().title()
    if not item_slug and module:
        unavailable_label = module_label

    return {
        "key": safe_key,
        "label": module_label,
        "eyebrow": module_eyebrow,
        "title": unavailable_label,
        "description": "Halaman ini belum tersedia dan sedang dalam pengembangan.",
        "selected": {"label": unavailable_label, "target": ""},
        "nav": [],
        "cards": [],
        "toast": "",
        "unavailable": True,
        "unavailable_label": unavailable_label,
        "unavailable_path": request.path,
        "unavailable_message": "Halaman ini belum tersedia dan sedang dalam pengembangan.",
        "back_href": f"/modul/{safe_key}/" if module else "/workspace/",
    }


def _resolve_module_item_redirect(module_key, item_slug):
    safe_item_slug = str(item_slug or "").strip().lower()
    if not safe_item_slug:
        return ""

    explicit_redirect = MODULE_ITEM_REDIRECTS.get(module_key, {}).get(safe_item_slug)
    if explicit_redirect:
        return explicit_redirect

    module = INTERNAL_MODULE_HUBS.get(module_key)
    if not module:
        return ""

    nav_item = next((item for item in module.get("nav", []) if item.get("slug") == safe_item_slug), None)
    if not nav_item:
        return ""

    target = str(nav_item.get("target") or "").strip()
    if not target or target.startswith(f"/modul/{module_key}/"):
        return ""
    return target


def _module_item_should_show_unavailable(module_key, item_slug):
    safe_item_slug = str(item_slug or "").strip().lower()
    if not safe_item_slug:
        return False

    module = INTERNAL_MODULE_HUBS.get(module_key)
    if not module:
        return True

    nav_item = next((item for item in module.get("nav", []) if item.get("slug") == safe_item_slug), None)
    if not nav_item:
        return True

    target = str(nav_item.get("target") or "").strip()
    return not target or target.startswith(f"/modul/{module_key}/")


def _build_internal_portal_cards(role):
    normalized_role = normalize_role(role)
    hris_modules = get_hris_navigation_modules(normalized_role)
    hris_module_slugs = {module["slug"] for module in hris_modules}
    can_open_hris = bool(hris_modules)
    cards = []

    def add(allowed, *args, **kwargs):
        if allowed:
            cards.append(_portal_card(*args, **kwargs))

    add(
        can_open_hris,
        "BJAS HRIS",
        "/modul/hris/",
        "Data karyawan, kontrak, payroll, KPI",
        "Internal App",
        "lavender",
        "hris-employee",
    )
    add(
        has_permission(normalized_role, "access_attendance_portal"),
        "BJAS Attendance",
        "/modul/attendance/",
        "Absen, jadwal kerja, late & overtime",
        "Internal App",
        "cream",
        "coordination-absen-foto",
        status_label="3 pending",
    )
    add(
        can_access_pos_terminal(normalized_role),
        "BJAS POS",
        "/kasir/",
        "Kasir, transaksi, shift closing",
        "Internal App",
        "mint",
        "wms-kasir",
    )
    add(
        has_permission(normalized_role, "view_wms"),
        "BJAS WMS",
        "/modul/wms/",
        "Stok, produk, gudang, transfer barang",
        "Internal App",
        "sage",
        "wms-stok-produk",
        status_label="Stock alert",
        status_tone="amber",
    )
    add(
        has_permission(normalized_role, "view_wms"),
        "BJAS Finance",
        "/modul/finance/",
        "Cashflow, supplier, biaya operasional",
        "Internal App",
        "cream",
        "wms-request-owner",
        status_label="New report",
    )
    add(
        has_permission(normalized_role, "access_daily_report_portal"),
        "BJAS Sales",
        "/modul/sales/",
        "Invoice, surat penawaran, surat jalan",
        "Internal App",
        "mint",
        "coordination-report-harian",
    )
    add(
        has_permission(normalized_role, "view_crm"),
        "BJAS CRM",
        "/modul/crm/",
        "Customer, member, senaran, campaign",
        "Internal App",
        "lilac",
        "coordination-crm",
    )
    add(
        "documents" in hris_module_slugs,
        "BJAS Drive",
        BJAS_DRIVE_EXTERNAL_URL,
        "Dokumen internal, company file, shared file",
        "Internal App",
        "blue",
        "group-workspace",
    )
    add(
        has_permission(normalized_role, "access_daily_report_portal") or "report" in hris_module_slugs,
        "BJAS Report",
        "/modul/report/",
        "Laporan penjualan, stok, kehadiran",
        "Internal App",
        "mint",
        "hris-report",
    )
    add(
        has_permission(normalized_role, "view_announcements"),
        "BJAS Informasi",
        "/modul/informasi/",
        "Memo, SOP, policy, announcement",
        "Internal App",
        "cream",
        "coordination-pengumuman",
    )
    add(
        has_permission(normalized_role, "view_approvals") or "approval" in hris_module_slugs,
        "BJAS Permission",
        "/modul/permission/",
        "Izin, cuti, sakit, approval manager",
        "Internal App",
        "mint",
        "coordination-libur",
        status_label="2 approval",
    )
    add(
        has_permission(normalized_role, "view_admin"),
        "BJAS Setting",
        "/modul/setting/",
        "User, role, branch, department, audit log",
        "Internal App",
        "blue",
        "utility-admin",
    )

    if not cards:
        add(
            True,
            "BJAS Attendance",
            "/modul/attendance/",
            "Absen, jadwal kerja, late & overtime",
            "Daily",
            "cream",
            "coordination-absen-foto",
        )

    return cards


def _build_workspace_sections(role):
    normalized_role = normalize_role(role)
    sections = []

    coordination_items = []

    if has_permission(normalized_role, "view_announcements"):
        coordination_items.append(
            _workspace_tile(
                "Pengumuman",
                "/announcements/",
                "Broadcast operasional, update penting, dan perubahan jadwal terbaru.",
                "Info",
                "sky",
                "coordination-pengumuman",
            )
        )

    if has_permission(normalized_role, "access_attendance_portal"):
        coordination_items.append(
            _workspace_tile(
                "Absen Foto",
                "/absen/",
                "Clock in, break, dan check out dengan geotag dan foto langsung dari browser.",
                "Daily",
                "emerald",
                "coordination-absen-foto",
            )
        )

    if has_permission(normalized_role, "access_leave_portal"):
        coordination_items.append(
            _workspace_tile(
                "Libur",
                "/libur/",
                "Ajukan cuti dan lihat status approval bulanan dari satu portal sederhana.",
                "Leave",
                "amber",
                "coordination-libur",
            )
        )

    if has_permission(normalized_role, "access_overtime_portal"):
        coordination_items.append(
            _workspace_tile(
                "Lembur",
                "/lembur/",
                (
                    "Ajukan tambah atau kurangi saldo lembur, lalu pantau status approval HR dan Super Admin."
                    if normalized_role == "hr"
                    else "Ajukan pengurangan saldo lembur dan pantau status approval HR dan Super Admin."
                ),
                "Lembur",
                "teal",
                "coordination-absen-foto",
            )
        )

    if has_permission(normalized_role, "access_daily_report_portal"):
        coordination_items.append(
            _workspace_tile(
                "Report Harian",
                "/laporan-harian/",
                "Kirim update kerja, report live, dan lampiran bukti dari portal harian.",
                "Report",
                "rose",
                "coordination-report-harian",
            )
        )

    if has_permission(normalized_role, "access_kpi_portal"):
        coordination_items.append(
            _workspace_tile(
                "KPI Staff",
                "/kpi-staff/",
                "Isi KPI mingguan staff sesuai template warehouse dan pantau review HR dari portal terpisah.",
                "KPI",
                "indigo",
                "hris-performance",
            )
        )

    if has_permission(normalized_role, "view_schedule"):
        coordination_items.append(
            _workspace_tile(
                "Jadwal",
                "/schedule/",
                "Kelola board jadwal tim, live schedule, dan override operasional.",
                "Planner",
                "indigo",
                "coordination-jadwal",
            )
        )
        coordination_items.append(
            _workspace_tile(
                "Tukar Shift",
                "/schedule/swap-request",
                "Ajukan tuker shift manual dan pantau approval HR atau Super Admin dari halaman khusus.",
                "Planner",
                "indigo",
                "coordination-jadwal",
            )
        )

    if has_permission(normalized_role, "view_chat"):
        coordination_items.append(
            _workspace_tile(
                "Chat Operasional",
                "/chat/",
                "Buka komunikasi cepat, panggilan, dan notifikasi lintas tim.",
                "Chat",
                "cyan",
                "coordination-chat-operasional",
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
                "coordination-crm",
            )
        )

    if coordination_items:
        sections.append(
            {
                "title": "Koordinasi Harian",
                "summary": "Akses cepat untuk komunikasi, kehadiran, dan ritme kerja tim setiap hari.",
                "items": coordination_items,
            }
        )

    if has_permission(normalized_role, "view_wms"):
        wms_items = [
            _workspace_tile(
                "Dashboard WMS",
                "/dashboard/",
                "Masuk ke dashboard operasional gudang untuk monitor stok dan aktivitas terakhir.",
                "WMS",
                "blue",
                "wms-dashboard",
            ),
            _workspace_tile(
                "Info Produk",
                "/info-produk/",
                "Cari informasi SKU, harga, dan stok produk dengan lookup yang cepat.",
                "Lookup",
                "sky",
                "wms-info-produk",
            ),
            _workspace_tile(
                "Stok & Produk",
                "/stock/",
                "Monitor stok aktif, nilai jual, aging batch, dan kelola master produk dari workspace yang sama.",
                "Studio",
                "emerald",
                "wms-stok-produk",
            ),
        ]

        if can_access_pos_terminal(normalized_role):
            wms_items.append(
                _workspace_tile(
                    "Kasir Harian",
                    "/kasir/",
                    "Checkout cepat langsung terhubung ke stok gudang, histori customer CRM, dan menu akses log atau rekap penjualan.",
                    "POS Hub",
                    "violet",
                    "wms-kasir",
                )
            )

        wms_items.extend(
            [
                _workspace_tile(
                    "Inbound",
                    "/inbound/",
                    "Tambah batch barang masuk dengan panel kerja yang cepat dan rapi.",
                    "Flow",
                    "teal",
                    "wms-inbound",
                ),
            _workspace_tile(
                "Outbound",
                "/outbound/",
                "Kurangi stok keluar dengan validasi qty terhadap stok yang tersedia.",
                "Flow",
                "rose",
                "wms-outbound",
            ),
            _workspace_tile(
                "Transfer",
                "/transfers/",
                "Pindahkan stok antar gudang dengan lane transfer yang jelas.",
                "Flow",
                "indigo",
                "wms-transfer",
            ),
            _workspace_tile(
                "Request Gudang",
                "/request/",
                "Susun request antar gudang dan pantau approval-nya.",
                "Queue",
                "amber",
                "wms-request-gudang",
            ),
            _workspace_tile(
                "Request Owner",
                "/request/owner",
                "Kirim kebutuhan barang langsung ke owner melalui jalur request khusus.",
                "Owner",
                "orange",
                "wms-request-owner",
            ),
            _workspace_tile(
                "Stock Opname",
                "/so/",
                "Cocokkan stok fisik dan sistem untuk display maupun gudang.",
                "Control",
                "slate",
                "wms-stock-opname",
            ),
            ]
        )

        if has_permission(normalized_role, "view_approvals"):
            wms_items.append(
                _workspace_tile(
                    "Approvals",
                    "/approvals",
                    "Review inbound, outbound, dan adjustment yang menunggu persetujuan.",
                    "Approval",
                    "pink",
                    "wms-approvals",
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
                    "wms-audit-log",
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
                "hris-home",
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
                    get_hris_workspace_icon_key(module["slug"]),
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
            "utility-account-settings",
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
                "utility-admin",
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
            ) aging_rows
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
def portal_home():
    return redirect(url_for("dashboard.workspace_gateway"))


@dashboard_bp.route("/dashboard/")
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


@dashboard_bp.route("/workspace")
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
    portal_cards = _build_internal_portal_cards(role)
    total_modules = len(portal_cards)

    return render_template(
        "workspace_gateway.html",
        sections=sections,
        portal_cards=portal_cards,
        warehouse_name=warehouse_name,
        role_label=(role or "guest").replace("_", " ").title(),
        username=session.get("username", "guest"),
        total_modules=total_modules,
    )


@dashboard_bp.route("/wms")
@dashboard_bp.route("/wms/")
@dashboard_bp.route("/wms/<item_slug>")
def wms_route_alias(item_slug=None):
    safe_item_slug = str(item_slug or "stock-produk").strip().lower()
    redirect_target = WMS_ROUTE_ALIASES.get(safe_item_slug)
    if redirect_target:
        return _redirect_with_query(redirect_target)

    return _render_internal_module_hub("wms", safe_item_slug)


def _render_internal_module_hub(module_slug, item_slug=None):
    module_key = str(module_slug or "").strip().lower()
    if module_key == "pos":
        return redirect("/kasir/")
    if module_key == "drive":
        return redirect(BJAS_DRIVE_EXTERNAL_URL)
    if item_slug:
        redirect_target = _resolve_module_item_redirect(module_key, item_slug)
        if redirect_target:
            return redirect(redirect_target)

    if module_key not in INTERNAL_MODULE_HUBS:
        module = _build_unavailable_module_context(module_key, item_slug)
        return render_template(
            "internal_module.html",
            module=module,
            username=session.get("username", "guest"),
        )

    role = normalize_role(session.get("role"))
    if not _module_hub_allowed(module_key, role):
        return redirect(url_for("dashboard.workspace_gateway"))

    module = _build_module_hub(module_key, item_slug)
    if not module:
        return redirect(url_for("dashboard.workspace_gateway"))

    nav_slugs = {item.get("slug") for item in INTERNAL_MODULE_HUBS[module_key].get("nav", [])}
    unresolved_item = bool(item_slug) and str(item_slug).strip().lower() not in nav_slugs
    unavailable_item = _module_item_should_show_unavailable(module_key, item_slug)
    if unresolved_item or unavailable_item:
        unavailable_label = module.get("selected", {}).get("label") or module["label"]
        if unresolved_item:
            unavailable_label = str(item_slug or "").replace("-", " ").strip().title() or unavailable_label
        unavailable_path = request.path
        module = dict(module)
        module["unavailable"] = True
        module["unavailable_label"] = unavailable_label
        module["unavailable_path"] = unavailable_path
        module["unavailable_message"] = (
            "Halaman ini belum tersedia. Routing sub halaman sedang dalam pengembangan "
            "dan akan dibuka kalau fiturnya sudah siap."
        )
        module["back_href"] = "/informasi/" if module_key == "informasi" else f"/modul/{module_key}/"

    return render_template(
        "internal_module.html",
        module=module,
        username=session.get("username", "guest"),
    )


@dashboard_bp.route("/informasi")
@dashboard_bp.route("/informasi/")
def information_module():
    return _render_internal_module_hub("informasi", "sop-policy")


@dashboard_bp.route("/modul/<module_slug>")
@dashboard_bp.route("/modul/<module_slug>/")
@dashboard_bp.route("/modul/<module_slug>/<item_slug>")
def internal_module_hub(module_slug, item_slug=None):
    return _render_internal_module_hub(module_slug, item_slug)


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
