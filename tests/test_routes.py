import os
import shutil
import unittest
import json
import importlib
from datetime import date as date_cls, datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
import zipfile

import init_db as init_db_module
import services.notification_service as notification_service
import services.whatsapp_service as whatsapp_service
from app import create_app, repair_restored_data
from config import Config
from database import get_db
from routes.chat import _format_timestamp_label
from werkzeug.security import check_password_hash, generate_password_hash


class WmsRoutesTestCase(unittest.TestCase):
    def setUp(self):
        temp_root = os.path.join(os.path.dirname(__file__), ".tmp")
        os.makedirs(temp_root, exist_ok=True)
        self.db_path = os.path.join(temp_root, f"test_database_{uuid4().hex}.db")
        self.photo_upload_root = os.path.join(temp_root, f"uploads_{uuid4().hex}")
        self.daily_report_upload_root = os.path.join(temp_root, f"daily_reports_{uuid4().hex}")
        self.document_upload_root = os.path.join(temp_root, f"document_uploads_{uuid4().hex}")
        self.document_signature_root = os.path.join(temp_root, f"document_signatures_{uuid4().hex}")
        self.receipt_pdf_root = os.path.join(temp_root, f"receipt_pdfs_{uuid4().hex}")

        init_db_module.DB_PATH = self.db_path
        Config.DATABASE = self.db_path
        Config.SESSION_COOKIE_SECURE = False

        self.app = create_app()
        self.app.config.update(
            TESTING=True,
            SESSION_COOKIE_SECURE=False,
            BIOMETRIC_PHOTO_UPLOAD_FOLDER=self.photo_upload_root,
            BIOMETRIC_PHOTO_URL_PREFIX="/static/test-geotag",
            DAILY_LIVE_REPORT_UPLOAD_FOLDER=self.daily_report_upload_root,
            DAILY_LIVE_REPORT_UPLOAD_URL_PREFIX="/static/test-daily-reports",
            DAILY_LIVE_REPORT_ATTACHMENT_MAX_BYTES=10 * 1024 * 1024,
            DOCUMENT_RECORD_UPLOAD_FOLDER=self.document_upload_root,
            DOCUMENT_RECORD_UPLOAD_URL_PREFIX="/static/test-documents",
            DOCUMENT_RECORD_ATTACHMENT_MAX_BYTES=15 * 1024 * 1024,
            DOCUMENT_RECORD_SIGNATURE_FOLDER=self.document_signature_root,
            DOCUMENT_RECORD_SIGNATURE_URL_PREFIX="/static/test-document-signatures",
            DOCUMENT_RECORD_SIGNATURE_MAX_BYTES=2 * 1024 * 1024,
            POS_RECEIPT_PDF_FOLDER=self.receipt_pdf_root,
            POS_RECEIPT_PDF_URL_PREFIX="/static/test-pos-receipts",
            PUBLIC_BASE_URL="https://erp.test",
            SECRET_KEY="test-secret-key",
            LOGIN_THROTTLE_LIMIT=3,
            LOGIN_THROTTLE_WINDOW_SECONDS=300,
            PASSWORD_MIN_LENGTH=8,
            PASSWORD_RESET_TTL_MINUTES=15,
        )
        self.client = self.app.test_client()

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            db_file = self.db_path + suffix
            if os.path.exists(db_file):
                os.remove(db_file)
        if os.path.isdir(self.photo_upload_root):
            shutil.rmtree(self.photo_upload_root)
        if os.path.isdir(self.daily_report_upload_root):
            shutil.rmtree(self.daily_report_upload_root)
        if os.path.isdir(self.document_upload_root):
            shutil.rmtree(self.document_upload_root)
        if os.path.isdir(self.document_signature_root):
            shutil.rmtree(self.document_signature_root)
        if os.path.isdir(self.receipt_pdf_root):
            shutil.rmtree(self.receipt_pdf_root)

    def login(self, username="admin", password="admin123"):
        return self.client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def logout(self):
        return self.client.get("/logout", follow_redirects=False)

    def login_hr_user(self, username="hr_test_user", password="pass1234"):
        self.create_user(username, password, "hr")
        return self.login(username, password)

    def create_user(
        self,
        username,
        password,
        role,
        warehouse_id=None,
        employee_id=None,
        email=None,
        phone=None,
        notify_email=1,
        notify_whatsapp=0,
    ):
        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO users(
                    username,
                    password,
                    role,
                    warehouse_id,
                    employee_id,
                    email,
                    phone,
                    notify_email,
                    notify_whatsapp
                )
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    username,
                    generate_password_hash(password),
                    role,
                    warehouse_id,
                    employee_id,
                    email,
                    phone,
                    notify_email,
                    notify_whatsapp,
                ),
            )
            db.commit()

    def get_user_id(self, username):
        with self.app.app_context():
            db = get_db()
            user = db.execute(
                "SELECT id FROM users WHERE username=?",
                (username,),
            ).fetchone()
        return user["id"] if user else None

    def create_employee_record(
        self,
        employee_code=None,
        full_name="Karyawan Uji",
        warehouse_id=1,
        department="Warehouse",
        position="Staff",
        employment_status="active",
        work_location=None,
    ):
        employee_code = employee_code or ("EMP-" + uuid4().hex[:6].upper())
        work_location = work_location or ("Gudang Mataram" if warehouse_id == 1 else "Gudang Mega")

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO employees(
                    employee_code,
                    full_name,
                    warehouse_id,
                    department,
                    position,
                    employment_status,
                    work_location
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    employee_code,
                    full_name,
                    warehouse_id,
                    department,
                    position,
                    employment_status,
                    work_location,
                ),
            )
            db.commit()
            employee = db.execute(
                "SELECT id FROM employees WHERE employee_code=?",
                (employee_code,),
            ).fetchone()
        return employee["id"]

    def create_product(self, sku=None, qty=5, variants="M,L", warehouse_id="1"):
        sku = sku or ("AUTO-" + uuid4().hex[:8].upper())

        response = self.client.post(
            "/products/add",
            data={
                "sku": sku,
                "name": "Produk Uji",
                "category_name": "Testing",
                "variants": variants,
                "qty": str(qty),
                "warehouse_id": str(warehouse_id),
                "price_retail": "150000",
                "price_discount": "135000",
                "price_nett": "120000",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()
            variants_rows = db.execute(
                "SELECT id, variant FROM product_variants WHERE product_id=? ORDER BY id",
                (product["id"],),
            ).fetchall()

        return response, product["id"], variants_rows

    def build_camera_photo_data_url(self):
        return (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
            "/w8AAgMBgN6lNn0AAAAASUVORK5CYII="
        )

    def build_xlsx_bytes(self, rows):
        def column_label(index):
            label = ""
            while index:
                index, remainder = divmod(index - 1, 26)
                label = chr(65 + remainder) + label
            return label

        shared_strings = []
        shared_index = {}

        def shared_id(value):
            text = "" if value is None else str(value)
            if text not in shared_index:
                shared_index[text] = len(shared_strings)
                shared_strings.append(text)
            return shared_index[text]

        sheet_rows = []
        for row_idx, row in enumerate(rows, start=1):
            cells = []
            for col_idx, value in enumerate(row, start=1):
                if value in (None, ""):
                    continue
                ref = f"{column_label(col_idx)}{row_idx}"
                cells.append(f'<c r="{ref}" t="s"><v>{shared_id(value)}</v></c>')
            sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

        shared_xml = "".join(
            f"<si><t>{text}</t></si>" for text in shared_strings
        )

        workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

        workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>"""

        content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>"""

        root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

        sheet_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {''.join(sheet_rows)}
  </sheetData>
</worksheet>"""

        shared_strings_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">
  {shared_xml}
</sst>"""

        output = BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types)
            archive.writestr("_rels/.rels", root_rels)
            archive.writestr("xl/workbook.xml", workbook_xml)
            archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
            archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
            archive.writestr("xl/sharedStrings.xml", shared_strings_xml)

        output.seek(0)
        return output.getvalue()

    def test_login_and_protected_pages_render(self):
        login_response = self.login()
        self.assertEqual(login_response.status_code, 302)

        for path in [
            "/workspace/",
            "/",
            "/announcements/",
            "/meetings/",
            "/absen/",
            "/libur/",
            "/laporan-harian/",
            "/schedule/",
            "/crm/",
            "/chat/",
            "/info-produk/",
            "/stock/?workspace=products",
            "/stock/",
            "/kasir/",
            "/kasir/staff-sales",
            "/kasir/log",
            "/inbound/",
            "/outbound/",
            "/transfers/",
            "/request/",
            "/hris/",
            "/audit/",
            "/so/",
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn('name="viewport"', html)
                self.assertIn('mobile-nav', html)
                self.assertIn('data-app-mode="browser"', html)
                self.assertIn('@admin', html)
                self.assertIn('data-theme-toggle', html)
                self.assertIn('data-pwa-install-trigger', html)
                self.assertIn('/static/js/app_shell.js', html)
                self.assertNotIn('/static/js/manual_table_sort.js', html)
                self.assertIn('data-sidebar-icon-rail', html)
                self.assertIn('aria-label="Pusat Modul"', html)
                self.assertIn('aria-label="Pengumuman"', html)
                self.assertIn('aria-label="Meeting Live"', html)
                self.assertIn('aria-label="Absen"', html)
                self.assertIn('aria-label="Libur"', html)
                self.assertIn('aria-label="Report Harian"', html)
                self.assertIn('/static/icons/workspace/coordination-pengumuman.svg', html)
                self.assertIn('/static/icons/workspace/wms-dashboard.svg', html)
                self.assertIn('/static/icons/workspace/utility-account-settings.svg', html)
                if path == "/absen/":
                    self.assertNotIn('data-attendance-shortcut', html)
                else:
                    self.assertIn('data-attendance-shortcut', html)
                    self.assertIn('href="/absen/#foto-absen"', html)
                if path == "/chat/":
                    self.assertIn("Chat Operasional Live", html)
                else:
                    self.assertIn('data-chat-widget-launcher', html)

        admin_page = self.client.get("/admin/", follow_redirects=False)
        self.assertEqual(admin_page.status_code, 302)

    def test_workspace_gateway_marks_sidebar_and_mobile_home_active(self):
        self.login()

        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-sidebar-group="workspace-home"', html)
        self.assertIn('data-sidebar-main-trigger="workspace"', html)
        self.assertIn('data-sidebar-main-panel="workspace"', html)
        self.assertIn('href="/workspace/" class="sidebar-subtile active"', html)
        self.assertIn('aria-label="Pusat Modul"', html)
        self.assertIn('<a href="/workspace/" class="active">Home</a>', html)

    def test_workspace_gateway_uses_svg_launcher_icons_instead_of_text_initials(self):
        self.create_user("launcher_super", "pass1234", "super_admin", warehouse_id=1)
        self.login("launcher_super", "pass1234")

        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('class="workspace-app-icon-image"', html)
        self.assertIn('/static/icons/workspace/coordination-pengumuman.svg', html)
        self.assertIn('/static/icons/workspace/coordination-meeting-live.svg', html)
        self.assertIn('/static/icons/workspace/wms-dashboard.svg', html)
        self.assertIn('/static/icons/workspace/wms-kasir.svg', html)
        self.assertIn('/static/icons/workspace/hris-report.svg', html)
        self.assertNotIn('aria-label="Rekap Penjualan Staff"', html)
        self.assertNotIn('aria-label="Log Penjualan POS"', html)
        self.assertIn('/static/icons/workspace/hris-home.svg', html)
        self.assertIn('/static/icons/workspace/utility-account-settings.svg', html)
        self.assertNotIn('<span class="workspace-app-icon">PG</span>', html)
        self.assertNotIn('<span class="workspace-app-icon">MT</span>', html)

    def test_workspace_shell_keeps_request_gudang_visible_for_approval_roles(self):
        self.create_user("launcher_request_super", "pass1234", "super_admin", warehouse_id=1)
        self.login("launcher_request_super", "pass1234")

        response = self.client.get("/workspace/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('href="/request/" class="sidebar-subtile', html)
        self.assertIn('aria-label="Request Antar Gudang"', html)
        self.assertIn('aria-label="Approvals"', html)
        self.assertIn('href="/request"', html)

    def test_pos_page_can_be_opened_by_admin_and_denied_for_hr(self):
        self.create_user("staff_sales_option", "pass1234", "staff", warehouse_id=1)
        self.login()

        admin_response = self.client.get("/kasir/")
        self.assertEqual(admin_response.status_code, 200)
        admin_html = admin_response.get_data(as_text=True)
        self.assertIn("Checkout Kasir", admin_html)
        self.assertIn('aria-label="Kasir Harian"', admin_html)
        self.assertIn('/static/icons/workspace/wms-kasir.svg', admin_html)
        self.assertIn("data-has-app-shell=\"1\"", admin_html)
        self.assertIn('id="posCashierUserId"', admin_html)
        self.assertIn("staff_sales_option", admin_html)
        self.assertIn("Log Penjualan Hari Ini", admin_html)
        self.assertIn("Menu POS", admin_html)
        self.assertIn("/kasir/log?warehouse=1", admin_html)
        self.assertIn("/kasir/staff-sales?warehouse=1", admin_html)
        self.assertIn("/kasir/log", admin_html)

        self.logout()
        self.login_hr_user("hr_pos_denied", "pass1234")
        hr_response = self.client.get("/kasir/", follow_redirects=False)
        self.assertEqual(hr_response.status_code, 302)
        self.assertIn("/workspace/", hr_response.headers.get("Location", ""))

    def test_pos_sales_log_page_can_be_opened_by_admin_and_denied_for_hr(self):
        self.login()

        admin_response = self.client.get("/kasir/log?warehouse=1&date_from=2026-04-03&date_to=2026-04-03")
        self.assertEqual(admin_response.status_code, 200)
        admin_html = admin_response.get_data(as_text=True)
        self.assertIn("Log Penjualan POS", admin_html)
        self.assertIn("Log Penjualan", admin_html)
        self.assertIn("Tampilkan Log", admin_html)
        self.assertIn('aria-label="Kasir Harian"', admin_html)

        self.logout()
        self.login_hr_user("hr_pos_log_denied", "pass1234")
        hr_response = self.client.get("/kasir/log", follow_redirects=False)
        self.assertEqual(hr_response.status_code, 302)
        self.assertIn("/workspace/", hr_response.headers.get("Location", ""))

    def test_pos_staff_sales_report_can_be_opened_by_admin_and_denied_for_hr(self):
        self.login()

        admin_response = self.client.get("/kasir/staff-sales?warehouse=1&week_date=2026-04-16&month=2026-04")
        self.assertEqual(admin_response.status_code, 200)
        admin_html = admin_response.get_data(as_text=True)
        self.assertIn("Rekap Penjualan Staff", admin_html)
        self.assertIn("Rekap Penjualan Staff Mingguan", admin_html)
        self.assertIn("Rekap Penjualan Staff Bulanan", admin_html)
        self.assertIn('data-pos-sales-period="weekly"', admin_html)
        self.assertIn('data-pos-sales-period="monthly"', admin_html)

        self.logout()
        self.login_hr_user("hr_sales_report_denied", "pass1234")
        hr_response = self.client.get("/kasir/staff-sales", follow_redirects=False)
        self.assertEqual(hr_response.status_code, 302)
        self.assertIn("/workspace/", hr_response.headers.get("Location", ""))

    def test_staff_intern_cannot_access_pos_page(self):
        self.create_user("intern_pos_denied", "pass1234", "staff_intern", warehouse_id=1)
        self.login("intern_pos_denied", "pass1234")

        response = self.client.get("/kasir/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/workspace/", response.headers.get("Location", ""))

    def test_pos_checkout_syncs_to_stock_and_crm_purchase_records(self):
        self.create_user("staff_sales_checkout", "pass1234", "staff", warehouse_id=1)
        selected_cashier_user_id = self.get_user_id("staff_sales_checkout")
        self.login()
        response, product_id, variants_rows = self.create_product(
            sku="POS-ITEM-001",
            qty=5,
            variants="42",
            warehouse_id="1",
        )
        self.assertEqual(response.status_code, 302)
        variant_id = variants_rows[0]["id"]

        checkout = self.client.post(
            "/kasir/checkout",
            json={
                "warehouse_id": 1,
                "sale_date": "2026-04-03",
                "cashier_user_id": selected_cashier_user_id,
                "customer_name": "Customer Kasir Test",
                "customer_phone": "628120001111",
                "payment_method": "cash",
                "paid_amount": 260000,
                "note": "Transaksi uji kasir",
                "items": [
                    {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "qty": 2,
                        "unit_price": 125000,
                    }
                ],
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(checkout.status_code, 200)
        payload = checkout.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["total_items"], 2)
        self.assertEqual(payload["total_amount"], 250000.0)
        self.assertIn("receipt_no", payload)
        self.assertIn("receipt_print_url", payload)

        with self.app.app_context():
            db = get_db()
            stock_after = db.execute(
                """
                SELECT qty
                FROM stock
                WHERE product_id=? AND variant_id=? AND warehouse_id=1
                """,
                (product_id, variant_id),
            ).fetchone()

            customer = db.execute(
                """
                SELECT id
                FROM crm_customers
                WHERE warehouse_id=1 AND customer_name=?
                """,
                ("Customer Kasir Test",),
            ).fetchone()

            purchase = db.execute(
                """
                SELECT id, channel, items_count, total_amount
                FROM crm_purchase_records
                WHERE invoice_no=?
                """,
                (payload["receipt_no"],),
            ).fetchone()

            purchase_item = db.execute(
                """
                SELECT qty, unit_price, line_total
                FROM crm_purchase_items
                WHERE purchase_id=?
                """,
                (purchase["id"],),
            ).fetchone()

            pos_sale = db.execute(
                """
                SELECT
                    total_items,
                    subtotal_amount,
                    discount_amount,
                    tax_amount,
                    total_amount,
                    paid_amount,
                    change_amount,
                    payment_method,
                    cashier_user_id
                FROM pos_sales
                WHERE receipt_no=?
                """,
                (payload["receipt_no"],),
            ).fetchone()

        self.assertEqual(stock_after["qty"], 3)
        self.assertIsNotNone(customer)
        self.assertEqual(purchase["channel"], "pos")
        self.assertEqual(purchase["items_count"], 2)
        self.assertAlmostEqual(float(purchase["total_amount"]), 250000.0)
        self.assertEqual(purchase_item["qty"], 2)
        self.assertAlmostEqual(float(purchase_item["unit_price"]), 125000.0)
        self.assertAlmostEqual(float(purchase_item["line_total"]), 250000.0)
        self.assertEqual(pos_sale["total_items"], 2)
        self.assertAlmostEqual(float(pos_sale["subtotal_amount"]), 250000.0)
        self.assertAlmostEqual(float(pos_sale["discount_amount"]), 0.0)
        self.assertAlmostEqual(float(pos_sale["tax_amount"]), 0.0)
        self.assertAlmostEqual(float(pos_sale["total_amount"]), 250000.0)
        self.assertAlmostEqual(float(pos_sale["paid_amount"]), 260000.0)
        self.assertAlmostEqual(float(pos_sale["change_amount"]), 10000.0)
        self.assertEqual(pos_sale["payment_method"], "cash")
        self.assertEqual(pos_sale["cashier_user_id"], selected_cashier_user_id)

    def test_pos_checkout_supports_custom_discount_and_tax_rules(self):
        self.create_user("staff_sales_discount", "pass1234", "staff", warehouse_id=1)
        selected_cashier_user_id = self.get_user_id("staff_sales_discount")
        self.login()
        response, product_id, variants_rows = self.create_product(
            sku="POS-DISC-001",
            qty=6,
            variants="42",
            warehouse_id="1",
        )
        self.assertEqual(response.status_code, 302)
        variant_id = variants_rows[0]["id"]

        checkout = self.client.post(
            "/kasir/checkout",
            json={
                "warehouse_id": 1,
                "sale_date": "2026-04-03",
                "cashier_user_id": selected_cashier_user_id,
                "customer_name": "Customer Discount",
                "customer_phone": "628120009999",
                "payment_method": "cash",
                "discount_type": "percent",
                "discount_value": 10,
                "tax_type": "percent",
                "tax_value": 11,
                "paid_amount": 200000,
                "note": "Checkout dengan discount dan tax",
                "items": [
                    {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "qty": 2,
                        "unit_price": 100000,
                    }
                ],
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(checkout.status_code, 200)
        payload = checkout.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertAlmostEqual(payload["subtotal_amount"], 200000.0)
        self.assertAlmostEqual(payload["discount_amount"], 20000.0)
        self.assertAlmostEqual(payload["tax_amount"], 19800.0)
        self.assertAlmostEqual(payload["total_amount"], 199800.0)
        self.assertAlmostEqual(payload["change_amount"], 200.0)

        with self.app.app_context():
            db = get_db()
            pos_sale = db.execute(
                """
                SELECT
                    discount_type,
                    discount_value,
                    discount_amount,
                    tax_type,
                    tax_value,
                    tax_amount,
                    subtotal_amount,
                    total_amount
                FROM pos_sales
                WHERE receipt_no=?
                """,
                (payload["receipt_no"],),
            ).fetchone()
            purchase = db.execute(
                "SELECT total_amount FROM crm_purchase_records WHERE invoice_no=?",
                (payload["receipt_no"],),
            ).fetchone()

        self.assertEqual(pos_sale["discount_type"], "percent")
        self.assertAlmostEqual(float(pos_sale["discount_value"]), 10.0)
        self.assertAlmostEqual(float(pos_sale["discount_amount"]), 20000.0)
        self.assertEqual(pos_sale["tax_type"], "percent")
        self.assertAlmostEqual(float(pos_sale["tax_value"]), 11.0)
        self.assertAlmostEqual(float(pos_sale["tax_amount"]), 19800.0)
        self.assertAlmostEqual(float(pos_sale["subtotal_amount"]), 200000.0)
        self.assertAlmostEqual(float(pos_sale["total_amount"]), 199800.0)
        self.assertAlmostEqual(float(purchase["total_amount"]), 199800.0)

    def test_pos_sales_log_and_receipt_print_show_complete_sale_details(self):
        self.create_user("staff_sales_receipt", "pass1234", "staff", warehouse_id=1)
        selected_cashier_user_id = self.get_user_id("staff_sales_receipt")
        self.login()
        response, product_id, variants_rows = self.create_product(
            sku="POS-NOTA-001",
            qty=8,
            variants="42",
            warehouse_id="1",
        )
        self.assertEqual(response.status_code, 302)
        variant_id = variants_rows[0]["id"]

        checkout = self.client.post(
            "/kasir/checkout",
            json={
                "warehouse_id": 1,
                "sale_date": "2026-04-03",
                "cashier_user_id": selected_cashier_user_id,
                "customer_name": "Customer Nota",
                "customer_phone": "628120003333",
                "payment_method": "transfer",
                "paid_amount": 305000,
                "note": "Print nota kasir",
                "items": [
                    {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "qty": 2,
                        "unit_price": 150000,
                    }
                ],
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(checkout.status_code, 200)
        checkout_payload = checkout.get_json()
        receipt_no = checkout_payload["receipt_no"]

        pos_response = self.client.get("/kasir/?warehouse=1&sale_date=2026-04-03")
        self.assertEqual(pos_response.status_code, 200)
        pos_html = pos_response.get_data(as_text=True)
        self.assertIn("Log Penjualan Hari Ini", pos_html)
        self.assertIn(receipt_no, pos_html)
        self.assertIn("Customer Nota", pos_html)
        self.assertIn("Cetak PDF", pos_html)

        log_response = self.client.get("/kasir/log?warehouse=1&date_from=2026-04-03&date_to=2026-04-03&search=Customer+Nota")
        self.assertEqual(log_response.status_code, 200)
        log_html = log_response.get_data(as_text=True)
        self.assertIn(receipt_no, log_html)
        self.assertIn("Customer Nota", log_html)
        self.assertIn("staff_sales_receipt", log_html)
        self.assertIn("Print nota kasir", log_html)
        self.assertIn("POS-NOTA-001", log_html)
        self.assertIn("POSTED", log_html)
        self.assertIn("Void Barang", log_html)

        print_response = self.client.get(f"/kasir/receipt/{receipt_no}/print?autoprint=1")
        self.assertEqual(print_response.status_code, 200)
        print_html = print_response.get_data(as_text=True)
        self.assertIn("Nota Pembelian", print_html)
        self.assertIn("CV BERKAH JAYA ABADI SPORTS", print_html)
        self.assertIn(receipt_no, print_html)
        self.assertIn("Customer Nota", print_html)
        self.assertIn("POS-NOTA-001", print_html)
        self.assertIn("Subtotal", print_html)
        self.assertIn("Diskon", print_html)
        self.assertIn("Pajak", print_html)
        self.assertIn("Customer Service:", print_html)
        self.assertIn("Simpan sebagai PDF", print_html)
        self.assertIn("window.print()", print_html)

    def test_pos_checkout_generates_public_receipt_pdf_and_logs_failed_whatsapp_without_blocking_sale(self):
        self.create_user("staff_sales_kirimi", "pass1234", "staff", warehouse_id=1)
        selected_cashier_user_id = self.get_user_id("staff_sales_kirimi")
        self.login()
        response, product_id, variants_rows = self.create_product(
            sku="POS-KIRIMI-001",
            qty=5,
            variants="42",
            warehouse_id="1",
        )
        self.assertEqual(response.status_code, 302)
        variant_id = variants_rows[0]["id"]

        with patch(
            "routes.pos.send_whatsapp_document",
            return_value={
                "ok": False,
                "provider": "kirimi",
                "receiver": "628120008888",
                "error": "kirimi_http_500",
            },
        ) as mocked_send:
            checkout = self.client.post(
                "/kasir/checkout",
                json={
                    "warehouse_id": 1,
                    "sale_date": "2026-04-03",
                    "cashier_user_id": selected_cashier_user_id,
                    "customer_name": "Customer Kirimi",
                    "customer_phone": "08120008888",
                    "payment_method": "cash",
                    "paid_amount": 151000,
                    "note": "Checkout kirimi",
                    "items": [
                        {
                            "product_id": product_id,
                            "variant_id": variant_id,
                            "qty": 1,
                            "unit_price": 150000,
                        }
                    ],
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(checkout.status_code, 200)
        payload = checkout.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertTrue(payload["receipt_pdf_public_url"].startswith("https://erp.test/static/test-pos-receipts/"))
        self.assertEqual(payload["receipt_whatsapp_status"], "failed")
        mocked_send.assert_called_once()

        with self.app.app_context():
            db = get_db()
            sale = db.execute(
                """
                SELECT
                    id,
                    receipt_pdf_path,
                    receipt_pdf_url,
                    receipt_whatsapp_status,
                    receipt_whatsapp_error
                FROM pos_sales
                WHERE receipt_no=?
                """,
                (payload["receipt_no"],),
            ).fetchone()
            notification = db.execute(
                """
                SELECT channel, recipient, subject, status, message
                FROM notifications
                WHERE subject=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (f"Nota POS {payload['receipt_no']}",),
            ).fetchone()

        self.assertIsNotNone(sale)
        self.assertTrue(sale["receipt_pdf_path"])
        self.assertTrue(sale["receipt_pdf_url"].startswith("https://erp.test/static/test-pos-receipts/"))
        self.assertEqual(sale["receipt_whatsapp_status"], "failed")
        self.assertIn("kirimi_http_500", sale["receipt_whatsapp_error"])
        self.assertTrue(os.path.exists(os.path.join(self.receipt_pdf_root, sale["receipt_pdf_path"])))
        with open(os.path.join(self.receipt_pdf_root, sale["receipt_pdf_path"]), "rb") as file_handle:
            self.assertTrue(file_handle.read(8).startswith(b"%PDF-1."))
        self.assertIsNotNone(notification)
        self.assertEqual(notification["channel"], "wa_document")
        self.assertEqual(notification["recipient"], "628120008888")
        self.assertEqual(notification["status"], "failed")
        self.assertIn("kirimi_http_500", notification["message"])

    def test_pos_void_item_restores_stock_and_recalculates_sale_totals(self):
        self.create_user("staff_sales_void", "pass1234", "staff", warehouse_id=1)
        selected_cashier_user_id = self.get_user_id("staff_sales_void")
        self.login()
        response, product_id, variants_rows = self.create_product(
            sku="POS-VOID-001",
            qty=5,
            variants="42",
            warehouse_id="1",
        )
        self.assertEqual(response.status_code, 302)
        variant_id = variants_rows[0]["id"]

        checkout = self.client.post(
            "/kasir/checkout",
            json={
                "warehouse_id": 1,
                "sale_date": "2026-04-03",
                "cashier_user_id": selected_cashier_user_id,
                "customer_name": "Customer Void",
                "customer_phone": "628120005555",
                "payment_method": "cash",
                "discount_type": "amount",
                "discount_value": 10000,
                "tax_type": "percent",
                "tax_value": 10,
                "paid_amount": 260000,
                "note": "Uji void item",
                "items": [
                    {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "qty": 2,
                        "unit_price": 120000,
                    }
                ],
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(checkout.status_code, 200)
        receipt_no = checkout.get_json()["receipt_no"]

        with self.app.app_context():
            db = get_db()
            purchase = db.execute(
                "SELECT id FROM crm_purchase_records WHERE invoice_no=?",
                (receipt_no,),
            ).fetchone()
            sale_item = db.execute(
                """
                SELECT id
                FROM crm_purchase_items
                WHERE purchase_id=?
                ORDER BY id ASC
                LIMIT 1
                """,
                (purchase["id"],),
            ).fetchone()

        void_response = self.client.post(
            f"/kasir/sales-item/{sale_item['id']}/void",
            json={
                "void_qty": 1,
                "note": "Customer batal 1 pcs",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(void_response.status_code, 200)
        void_payload = void_response.get_json()
        self.assertEqual(void_payload["status"], "success")
        self.assertEqual(void_payload["status_label"], "PARTIAL VOID")
        self.assertEqual(void_payload["total_items"], 1)
        self.assertAlmostEqual(void_payload["subtotal_amount"], 120000.0)
        self.assertAlmostEqual(void_payload["discount_amount"], 10000.0)
        self.assertAlmostEqual(void_payload["tax_amount"], 11000.0)
        self.assertAlmostEqual(void_payload["total_amount"], 121000.0)

        with self.app.app_context():
            db = get_db()
            stock_after = db.execute(
                """
                SELECT qty
                FROM stock
                WHERE product_id=? AND variant_id=? AND warehouse_id=1
                """,
                (product_id, variant_id),
            ).fetchone()
            purchase_item = db.execute(
                """
                SELECT qty, void_qty, void_amount, void_note
                FROM crm_purchase_items
                WHERE id=?
                """,
                (sale_item["id"],),
            ).fetchone()
            pos_sale = db.execute(
                """
                SELECT total_items, subtotal_amount, discount_amount, tax_amount, total_amount, change_amount, status
                FROM pos_sales
                WHERE receipt_no=?
                """,
                (receipt_no,),
            ).fetchone()
            purchase_record = db.execute(
                "SELECT items_count, total_amount FROM crm_purchase_records WHERE invoice_no=?",
                (receipt_no,),
            ).fetchone()

        self.assertEqual(stock_after["qty"], 4)
        self.assertEqual(purchase_item["qty"], 2)
        self.assertEqual(purchase_item["void_qty"], 1)
        self.assertAlmostEqual(float(purchase_item["void_amount"]), 120000.0)
        self.assertEqual(purchase_item["void_note"], "Customer batal 1 pcs")
        self.assertEqual(pos_sale["total_items"], 1)
        self.assertAlmostEqual(float(pos_sale["subtotal_amount"]), 120000.0)
        self.assertAlmostEqual(float(pos_sale["discount_amount"]), 10000.0)
        self.assertAlmostEqual(float(pos_sale["tax_amount"]), 11000.0)
        self.assertAlmostEqual(float(pos_sale["total_amount"]), 121000.0)
        self.assertAlmostEqual(float(pos_sale["change_amount"]), 139000.0)
        self.assertEqual(pos_sale["status"], "partial_void")
        self.assertEqual(purchase_record["items_count"], 1)
        self.assertAlmostEqual(float(purchase_record["total_amount"]), 121000.0)

    def test_pos_staff_sales_report_aggregates_weekly_and_monthly_sales_from_pos(self):
        self.create_user("sales_week_report", "pass1234", "staff", warehouse_id=1)
        self.create_user("sales_month_report", "pass1234", "staff", warehouse_id=1)
        self.create_user("sales_old_report", "pass1234", "staff", warehouse_id=1)
        week_cashier_user_id = self.get_user_id("sales_week_report")
        month_cashier_user_id = self.get_user_id("sales_month_report")
        old_cashier_user_id = self.get_user_id("sales_old_report")

        self.login()
        response, product_id, variants_rows = self.create_product(
            sku="POS-REPORT-001",
            qty=20,
            variants="42",
            warehouse_id="1",
        )
        self.assertEqual(response.status_code, 302)
        variant_id = variants_rows[0]["id"]

        sale_payloads = [
            {
                "sale_date": "2026-04-14",
                "cashier_user_id": week_cashier_user_id,
                "customer_name": "Customer Week Report",
                "customer_phone": "628120001114",
                "paid_amount": 151000,
                "unit_price": 150000,
            },
            {
                "sale_date": "2026-04-02",
                "cashier_user_id": month_cashier_user_id,
                "customer_name": "Customer Month Report",
                "customer_phone": "628120001102",
                "paid_amount": 91000,
                "unit_price": 90000,
            },
            {
                "sale_date": "2026-03-28",
                "cashier_user_id": old_cashier_user_id,
                "customer_name": "Customer Old Report",
                "customer_phone": "628120001328",
                "paid_amount": 71000,
                "unit_price": 70000,
            },
        ]

        for payload in sale_payloads:
            checkout = self.client.post(
                "/kasir/checkout",
                json={
                    "warehouse_id": 1,
                    "sale_date": payload["sale_date"],
                    "cashier_user_id": payload["cashier_user_id"],
                    "customer_name": payload["customer_name"],
                    "customer_phone": payload["customer_phone"],
                    "payment_method": "cash",
                    "paid_amount": payload["paid_amount"],
                    "note": "Transaksi laporan staff",
                    "items": [
                        {
                            "product_id": product_id,
                            "variant_id": variant_id,
                            "qty": 1,
                            "unit_price": payload["unit_price"],
                        }
                    ],
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            self.assertEqual(checkout.status_code, 200)
            self.assertEqual(checkout.get_json()["status"], "success")

        report_response = self.client.get("/kasir/staff-sales?warehouse=1&week_date=2026-04-16&month=2026-04")
        self.assertEqual(report_response.status_code, 200)
        report_html = report_response.get_data(as_text=True)
        self.assertIn("sales_week_report", report_html)
        self.assertIn("sales_month_report", report_html)
        self.assertNotIn("sales_old_report", report_html)
        self.assertIn("Rp 150.000", report_html)
        self.assertIn("Rp 240.000", report_html)

    def test_role_based_whatsapp_notification_maps_event_to_owner_and_hr(self):
        self.create_user(
            "owner_wa_event",
            "pass1234",
            "owner",
            phone="081234567890",
            notify_whatsapp=1,
        )
        self.create_user(
            "hr_wa_event",
            "pass1234",
            "hr",
            phone="081299900011",
            notify_whatsapp=1,
        )
        self.create_user(
            "staff_wa_event",
            "pass1234",
            "staff",
            warehouse_id=1,
            phone="081277711122",
            notify_whatsapp=1,
        )

        with self.app.app_context():
            with patch(
                "services.whatsapp_service.send_whatsapp_text",
                return_value={
                    "ok": True,
                    "provider": "kirimi",
                    "receiver": "6281234567890",
                    "error": "",
                },
            ) as mocked_send:
                result = whatsapp_service.send_role_based_notification(
                    "attendance.activity",
                    {
                        "warehouse_id": 1,
                        "employee_name": "Portal Attendance Notify",
                        "warehouse_name": "Gudang Mataram",
                        "punch_label": "Check In",
                        "time_label": "07:58",
                        "location_label": "Gudang Mataram - Gerbang Timur",
                    },
                )
                db = get_db()
                rows = db.execute(
                    """
                    SELECT role, recipient, status
                    FROM notifications
                    WHERE channel='wa_role_event'
                    ORDER BY role ASC
                    """
                ).fetchall()

        self.assertEqual(len(result["deliveries"]), 2)
        self.assertEqual(mocked_send.call_count, 2)
        sent_recipients = {call.args[0] for call in mocked_send.call_args_list}
        self.assertEqual(sent_recipients, {"6281234567890", "6281299900011"})
        self.assertEqual(
            {(row["role"], row["recipient"], row["status"]) for row in rows},
            {
                ("hr", "6281299900011", "sent"),
                ("owner", "6281234567890", "sent"),
            },
        )

    def test_schedule_page_opens_coordination_sidebar_group(self):
        self.login()

        response = self.client.get("/schedule/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-sidebar-group="coordination" open', html)
        self.assertIn('href="/schedule/" class="active"', html)

    def test_request_owner_page_opens_wms_and_request_submenu(self):
        self.login()

        response = self.client.get("/request/owner")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-sidebar-group="wms" open', html)
        self.assertIn('data-sidebar-subgroup="request" open', html)
        self.assertIn('href="/request/owner" class="active"', html)

    def test_hr_role_hides_wms_sidebar_group(self):
        self.login_hr_user("hr_nav_only", "pass1234")

        response = self.client.get("/hris/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('>HRIS<', html)
        self.assertNotIn('>WMS<', html)

    def test_inventory_value_is_hidden_for_admin_but_visible_for_owner(self):
        self.login()

        dashboard_response = self.client.get("/")
        self.assertEqual(dashboard_response.status_code, 200)
        dashboard_html = dashboard_response.get_data(as_text=True)
        self.assertNotIn("Nilai Inventory", dashboard_html)

        stock_response = self.client.get("/stock/")
        self.assertEqual(stock_response.status_code, 200)
        stock_html = stock_response.get_data(as_text=True)
        self.assertNotIn("Nilai Inventori", stock_html)
        self.assertNotIn('data-stock-summary="inventory_value"', stock_html)

        realtime_response = self.client.get("/api/realtime")
        self.assertEqual(realtime_response.status_code, 200)
        self.assertEqual(realtime_response.get_json()["inventory_value"], 0)

        self.create_user("owner_inventory", "pass1234", "owner")
        self.login("owner_inventory", "pass1234")

        owner_dashboard = self.client.get("/")
        self.assertEqual(owner_dashboard.status_code, 200)
        owner_dashboard_html = owner_dashboard.get_data(as_text=True)
        self.assertIn("Nilai Jual Stok", owner_dashboard_html)

        owner_stock = self.client.get("/stock/")
        self.assertEqual(owner_stock.status_code, 200)
        owner_stock_html = owner_stock.get_data(as_text=True)
        self.assertIn("Nilai Jual Stok", owner_stock_html)
        self.assertIn('data-stock-summary="inventory_value"', owner_stock_html)

    def test_staff_can_open_quick_product_lookup_and_search_live_results(self):
        self.login()
        response, product_id, variants_rows = self.create_product(sku="LOOKUP-FAST-001", qty=7, variants="39")
        self.assertEqual(response.status_code, 302)
        variant_id = variants_rows[0]["id"]
        self.logout()

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO stock(product_id, variant_id, warehouse_id, qty)
                VALUES (?,?,?,?)
                """,
                (product_id, variant_id, 2, 3),
            )
            db.commit()

        self.create_user("staff_lookup", "pass1234", "staff", warehouse_id=1)
        self.login("staff_lookup", "pass1234")

        page_response = self.client.get("/info-produk/")
        self.assertEqual(page_response.status_code, 200)
        self.assertIn("Info Produk Cepat", page_response.get_data(as_text=True))

        search_response = self.client.get("/info-produk/search?q=LOOKUP-FAST-001")
        self.assertEqual(search_response.status_code, 200)
        payload = search_response.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["focus_warehouse_id"], 1)
        self.assertGreaterEqual(payload["count"], 1)
        self.assertEqual(payload["items"][0]["sku"], "LOOKUP-FAST-001")
        self.assertEqual(payload["items"][0]["focus_qty"], 7)
        warehouse_names = {warehouse["name"] for warehouse in payload["items"][0]["warehouses"]}
        self.assertIn("Gudang Mataram", warehouse_names)
        self.assertIn("Gudang Mega", warehouse_names)

    def test_meeting_portal_renders_for_logged_in_user(self):
        self.login()
        response = self.client.get("/meetings/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Meeting Live Browser", html)
        self.assertIn('data-signature-endpoint="/meetings/signature"', html)
        self.assertIn("Audio First", html)

    def test_meeting_signature_endpoint_returns_browser_room_config_without_secret(self):
        self.login()

        response = self.client.post(
            "/meetings/signature",
            json={
                "roomName": "Daily Gudang Mega",
                "displayName": "Rio",
                "email": "rio@example.com",
                "language": "id-ID",
                "profile": "audio-first",
                "topic": "Daily Gudang",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["provider"], "jitsi")
        self.assertEqual(payload["roomName"], "daily-gudang-mega")
        self.assertEqual(payload["profile"], "audio-first")
        expected_domain = self.app.config.get("JITSI_MEETING_DOMAIN") or "meet.jit.si"
        if self.app.config.get("JITSI_JAAS_APP_ID"):
            self.assertEqual(payload["embedRoomName"], f"{self.app.config['JITSI_JAAS_APP_ID']}/daily-gudang-mega")
            self.assertTrue(payload["roomUrl"].startswith(f"https://{expected_domain}/"))
            self.assertEqual(payload["backendLabel"], "8x8 JaaS")
            self.assertTrue(payload["usesJaas"])
            if self.app.config.get("JITSI_JAAS_KID") and self.app.config.get("JITSI_JAAS_PRIVATE_KEY_PATH"):
                self.assertTrue(payload["jwt"])
            else:
                self.assertEqual(payload["jwt"], "")
        else:
            self.assertEqual(payload["embedRoomName"], "daily-gudang-mega")
            self.assertEqual(payload["backendLabel"], "Browser Room")
            self.assertFalse(payload["usesJaas"])
        self.assertEqual(payload["domain"], expected_domain)
        self.assertTrue(payload["startAudioOnly"])
        self.assertTrue(payload["startWithVideoMuted"])

    def test_meeting_signature_endpoint_accepts_pasted_room_link(self):
        self.login()
        response = self.client.post(
            "/meetings/signature",
            json={
                "roomName": "https://meet.jit.si/ERP-Review-Harian",
                "displayName": "Rio",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["roomName"], "erp-review-harian")

    def test_config_accepts_zoom_client_id_and_client_secret_fallbacks(self):
        import config as config_module

        with patch.dict(
            os.environ,
            {
                "ZOOM_MEETING_SDK_KEY": "",
                "ZOOM_MEETING_SDK_SECRET": "",
                "CLIENT_ID": "client-id-demo",
                "CLIENT_SECRET": "client-secret-demo",
            },
            clear=False,
        ):
            config_module = importlib.reload(config_module)
            try:
                self.assertEqual(config_module.Config.ZOOM_MEETING_SDK_KEY, "client-id-demo")
                self.assertEqual(config_module.Config.ZOOM_MEETING_SDK_SECRET, "client-secret-demo")
            finally:
                importlib.reload(config_module)

    def test_meeting_session_page_renders_browser_room_assets(self):
        self.login()
        response = self.client.get("/meetings/session?state=demo-state")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Meeting Stage", html)
        expected_domain = self.app.config.get("JITSI_MEETING_DOMAIN") or "meet.jit.si"
        self.assertIn(f"{expected_domain}/external_api.js", html)
        self.assertIn('data-provider="jitsi"', html)

    def test_health_and_ready_endpoints_are_public_and_hardened(self):
        health_response = self.client.get("/health")
        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(health_response.get_json()["status"], "ok")
        self.assertIn("X-Request-ID", health_response.headers)
        self.assertEqual(health_response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("microphone=(self)", health_response.headers.get("Permissions-Policy", ""))
        self.assertIn("frame-ancestors 'self'", health_response.headers.get("Content-Security-Policy", ""))
        self.assertEqual(
            health_response.headers.get("Cross-Origin-Opener-Policy"),
            "same-origin-allow-popups",
        )
        self.assertEqual(health_response.headers.get("Origin-Agent-Cluster"), "?1")
        self.assertEqual(
            health_response.headers.get("X-Permitted-Cross-Domain-Policies"),
            "none",
        )

        ready_response = self.client.get("/ready")
        self.assertEqual(ready_response.status_code, 200)
        self.assertEqual(ready_response.get_json()["database"], "ok")
        self.assertIn("X-Request-ID", ready_response.headers)

        login_page = self.client.get("/login")
        self.assertEqual(login_page.status_code, 200)
        self.assertIn("no-store", login_page.headers.get("Cache-Control", ""))

    def test_login_page_renders_split_clean_shell_with_crowd_hero(self):
        response = self.client.get("/login")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('data-login-shell="split-clean"', html)
        self.assertIn('data-login-hero', html)
        self.assertIn('/static/brand/login-hero-crowd.jpeg', html)
        self.assertIn('Masuk ke Sistem', html)
        self.assertIn('name="username"', html)
        self.assertIn('name="password"', html)
        self.assertIn('data-login-theme-toggle', html)
        self.assertNotIn('login-hero-badge', html)
        self.assertNotIn('Operasional Harian yang Lebih Rapi', html)
        self.assertNotIn('Kontrol Stok Lebih Tajam', html)
        self.assertNotIn('Siap untuk Operasional Harian', html)
        self.assertNotIn('Visibilitas yang Konsisten', html)

    def test_https_login_sets_secure_cookie_and_hsts(self):
        self.create_user("secure_user", "pass1234", "super_admin")

        response = self.client.post(
            "/login",
            base_url="https://localhost",
            data={"username": "secure_user", "password": "pass1234"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("Secure", response.headers.get("Set-Cookie", ""))
        self.assertEqual(
            response.headers.get("Strict-Transport-Security"),
            "max-age=31536000; includeSubDomains",
        )

    def test_cross_site_post_is_rejected_when_origin_check_is_enabled(self):
        self.app.config["ENFORCE_SAME_ORIGIN_POSTS_DURING_TESTS"] = True

        response = self.client.post(
            "/login",
            data={"username": "admin", "password": "admin123"},
            headers={"Origin": "https://evil.example"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("lintas situs", response.get_data(as_text=True))

    def test_same_host_https_origin_is_allowed_for_login_behind_tls_proxy(self):
        self.app.config["ENFORCE_SAME_ORIGIN_POSTS_DURING_TESTS"] = True
        self.create_user("proxy_login_user", "pass1234", "super_admin")

        response = self.client.post(
            "/login",
            base_url="http://erp.cvbjasyogya.cloud",
            data={"username": "proxy_login_user", "password": "pass1234"},
            headers={"Origin": "https://erp.cvbjasyogya.cloud"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

    def test_host_allowlist_blocks_untrusted_host_when_configured(self):
        self.app.config["ALLOWED_HOSTS"] = ["localhost", "127.0.0.1"]

        response = self.client.get(
            "/login",
            base_url="http://evil.example",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Host tidak diizinkan", response.get_data(as_text=True))

    def test_canonical_host_redirects_get_requests_to_public_domain(self):
        self.app.config.update(
            CANONICAL_HOST="erp.cvbjasyogya.cloud",
            CANONICAL_SCHEME="https",
        )

        response = self.client.get(
            "/login?next=%2F",
            base_url="http://wms.cvbjas.biz.id",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 308)
        self.assertEqual(
            response.headers["Location"],
            "https://erp.cvbjasyogya.cloud/login?next=%2F",
        )

    def test_canonical_host_is_auto_allowed_when_allowlist_is_enabled(self):
        self.app.config.update(
            ALLOWED_HOSTS=["localhost", "127.0.0.1"],
            CANONICAL_HOST="erp.cvbjasyogya.cloud",
            CANONICAL_SCHEME="https",
        )

        response = self.client.get(
            "/login",
            base_url="https://erp.cvbjasyogya.cloud",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)

    def test_authenticated_html_pages_are_not_cacheable(self):
        self.login()

        response = self.client.get("/", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_login_defaults_to_workspace_gateway_when_no_next_is_present(self):
        response = self.login()

        self.assertEqual(response.status_code, 302)
        redirect_target = urlsplit(response.headers["Location"])
        self.assertEqual(redirect_target.path, "/workspace/")

        gateway_response = self.client.get("/workspace/", follow_redirects=False)
        self.assertEqual(gateway_response.status_code, 200)
        html = gateway_response.get_data(as_text=True)
        self.assertIn("Pilih Area Kerja", html)
        self.assertIn("Pusat Modul", html)
        self.assertIn("Koordinasi Harian", html)

    def test_authenticated_get_login_redirects_to_workspace_gateway(self):
        self.login()

        response = self.client.get("/login", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        redirect_target = urlsplit(response.headers["Location"])
        self.assertEqual(redirect_target.path, "/workspace/")

    def test_login_redirects_back_to_requested_page_with_query_string(self):
        self.create_user("next_user", "pass1234", "super_admin")

        gated_response = self.client.get("/stock/?warehouse=2", follow_redirects=False)
        self.assertEqual(gated_response.status_code, 302)
        redirect_target = urlsplit(gated_response.headers["Location"])
        self.assertEqual(redirect_target.path, "/login")
        self.assertEqual(
            parse_qs(redirect_target.query).get("next", [None])[0],
            "/stock/?warehouse=2",
        )

        login_response = self.client.post(
            "/login?next=%2Fstock%2F%3Fwarehouse%3D2",
            data={
                "username": "next_user",
                "password": "pass1234",
                "next": "/stock/?warehouse=2",
            },
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 302)
        self.assertTrue(login_response.headers["Location"].endswith("/stock/?warehouse=2"))

    def test_login_accepts_case_insensitive_username(self):
        self.create_user("CaseUser", "pass1234", "admin", warehouse_id=1)

        response = self.login("caseuser", "pass1234")
        self.assertEqual(response.status_code, 302)

        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("username"), "CaseUser")
            self.assertEqual(sess.get("role"), "admin")

    def test_service_worker_route_is_public(self):
        response = self.client.get("/service-worker.js")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('addEventListener("fetch"', body)
        self.assertIn('addEventListener("push"', body)
        self.assertIn("OFFLINE_FALLBACK_URL", body)
        self.assertIn("requireInteraction", body)
        self.assertIn("wms-app-shell-", body)
        self.assertIn("/static/css/dashboard.css?v=", body)
        self.assertIn("/static/icons/workspace/group-workspace.svg?v=", body)
        self.assertNotIn("__APP_VERSION__", body)
        self.assertNotIn("__APP_SHELL_ASSETS__", body)
        self.assertEqual(response.headers.get("Service-Worker-Allowed"), "/")

    def test_assetlinks_route_returns_android_app_binding_when_configured(self):
        self.app.config["ANDROID_APP_PACKAGE"] = "cloud.cvbjasyogya.erp"
        self.app.config["ANDROID_SHA256_CERT_FINGERPRINTS"] = [
            "AA:BB:CC:DD:EE:FF"
        ]

        response = self.client.get("/.well-known/assetlinks.json")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.get_data(as_text=True))
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["target"]["package_name"], "cloud.cvbjasyogya.erp")
        self.assertEqual(payload[0]["target"]["sha256_cert_fingerprints"], ["AA:BB:CC:DD:EE:FF"])
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache")

    def test_apple_app_site_association_route_returns_ios_bindings_when_configured(self):
        self.app.config["IOS_APP_IDS"] = [
            "TEAM123.cloud.cvbjasyogya.erpios"
        ]

        response = self.client.get("/.well-known/apple-app-site-association")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.get_data(as_text=True))
        self.assertIn("applinks", payload)
        self.assertEqual(payload["applinks"]["apps"], [])
        self.assertEqual(len(payload["applinks"]["details"]), 1)
        self.assertEqual(
            payload["applinks"]["details"][0]["appID"],
            "TEAM123.cloud.cvbjasyogya.erpios",
        )
        self.assertEqual(payload["applinks"]["details"][0]["paths"], ["*"])
        self.assertEqual(response.headers.get("Cache-Control"), "no-cache")

    def test_manifest_is_available_for_pwa_install(self):
        response = self.client.get("/static/manifest.webmanifest")
        try:
            self.assertEqual(response.status_code, 200)
            payload = json.loads(response.get_data(as_text=True))
            self.assertEqual(payload["id"], "/workspace/")
            self.assertEqual(payload["start_url"], "/workspace/?source=pwa")
            self.assertIn("standalone", payload["display_override"])
            self.assertTrue(any(item["name"] == "Kasir Harian" for item in payload["shortcuts"]))
        finally:
            response.close()

    def test_login_page_keeps_browser_mode_shell_defaults(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('minimal-shell', html)
        self.assertIn('browser-mode', html)
        self.assertIn('data-app-mode="browser"', html)
        self.assertIn('/static/js/app_shell.js', html)
        self.assertIn('/static/manifest.webmanifest', html)
        self.assertIn('/static/js/app_shell.js?v=', html)
        self.assertIn('/static/manifest.webmanifest?v=', html)

    def test_secret_key_persists_to_file_when_env_is_missing(self):
        import config as config_module

        temp_root = os.path.join(os.path.dirname(__file__), ".tmp")
        os.makedirs(temp_root, exist_ok=True)
        secret_path = os.path.join(temp_root, f"secret_key_{uuid4().hex}.txt")
        with patch.dict(
            os.environ,
            {
                "SECRET_KEY": "",
                "SECRET_KEY_PATH": secret_path,
            },
            clear=False,
        ):
            first_key = config_module._load_or_create_secret_key()
            second_key = config_module._load_or_create_secret_key()

        try:
            self.assertTrue(os.path.exists(secret_path))
            self.assertEqual(first_key, second_key)
            self.assertGreaterEqual(len(first_key), 32)
        finally:
            if os.path.exists(secret_path):
                os.remove(secret_path)

    def test_notify_roles_empty_list_is_hardened(self):
        with self.app.app_context():
            result = notification_service.notify_roles([], "Audit", "Tidak ada role")
            db = get_db()
            count = db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]

        self.assertEqual(result, {"email": [], "wa": []})
        self.assertEqual(count, 0)

    def test_schedule_route_renders_for_admin_view_only(self):
        self.login()
        employee_id = self.create_employee_record(
            employee_code="EMP-SCD-ADM",
            full_name="Ayu Mataram",
            warehouse_id=1,
            position="Leader",
        )

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO schedule_entries(employee_id, schedule_date, shift_code, note, updated_by)
                VALUES (?,?,?,?,?)
                """,
                (employee_id, "2026-03-30", "P", "Shift pagi reguler", 1),
            )
            db.commit()

        response = self.client.get("/schedule/?start=2026-03-30&days=7")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Jadwal Tim", html)
        self.assertIn("View Only", html)
        self.assertIn('name="warehouse" disabled', html)
        self.assertIn("Ayu", html)
        self.assertIn("Board 7 Hari", html)
        self.assertIn("Tanggal", html)
        self.assertIn("Jadwal Live", html)
        self.assertNotIn("Atur Jadwal Manual", html)
        self.assertNotIn("Master Shift", html)

    def test_schedule_route_supports_extended_day_range_options(self):
        self.login()

        response = self.client.get("/schedule/?start=2026-03-30&days=30")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('<option value="14"', html)
        self.assertIn('<option value="30" selected>', html)
        self.assertIn('<option value="60"', html)
        self.assertIn('<option value="90"', html)
        self.assertIn(">30 hari</option>", html)
        self.assertIn("2026-03-30 s/d 2026-04-28", html)
        self.assertIn("2026-04-28", html)

    def test_hr_role_can_manage_schedule_and_hris(self):
        self.create_user("hr_ops", "pass1234", "hr")
        self.login("hr_ops", "pass1234")

        schedule_response = self.client.get("/schedule/")
        self.assertEqual(schedule_response.status_code, 200)
        schedule_html = schedule_response.get_data(as_text=True)
        self.assertIn("Atur Jadwal Manual", schedule_html)
        self.assertIn("Atur Jadwal Live", schedule_html)
        self.assertIn("Master Shift", schedule_html)
        self.assertIn("Display Staf di Board", schedule_html)
        self.assertIn('>HRIS<', schedule_html)
        self.assertIn('href="/hris/leave"', schedule_html)
        self.assertIn('href="/libur/"', schedule_html)

        hris_response = self.client.get("/hris/employee")
        self.assertEqual(hris_response.status_code, 200)
        self.assertIn("Tambah Karyawan", hris_response.get_data(as_text=True))

    def test_hris_dashboard_root_shows_active_announcements_and_schedule_preview(self):
        self.create_user("hr_dashboard", "pass1234", "hr")
        employee_id = self.create_employee_record(
            employee_code="EMP-HRIS-DB",
            full_name="Ajeng Schedule",
            warehouse_id=1,
            position="HR Staff",
        )
        mega_employee_id = self.create_employee_record(
            employee_code="EMP-HRIS-MEGA",
            full_name="Caca Mega",
            warehouse_id=2,
            position="Marketing",
        )
        today = date_cls.today().isoformat()

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO announcement_posts(
                    warehouse_id,
                    title,
                    audience,
                    publish_date,
                    status,
                    channel,
                    message,
                    handled_by
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    1,
                    "Briefing Gudang Pagi",
                    "warehouse_team",
                    today,
                    "published",
                    "Dashboard Banner",
                    "Semua tim hadir briefing jam 08:00.",
                    1,
                ),
            )
            db.execute(
                """
                INSERT INTO schedule_entries(employee_id, schedule_date, shift_code, note, updated_by)
                VALUES (?,?,?,?,?)
                """,
                (employee_id, today, "P", "Opening shift", 1),
            )
            db.execute(
                """
                INSERT INTO schedule_entries(employee_id, schedule_date, shift_code, note, updated_by)
                VALUES (?,?,?,?,?)
                """,
                (mega_employee_id, today, "PM", "Host live sore", 1),
            )
            db.commit()

        self.login("hr_dashboard", "pass1234")
        response = self.client.get(f"/hris/?schedule_start={today}&days=7")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Dashboard HRIS", html)
        self.assertIn("Announcement Aktif", html)
        self.assertIn("Briefing Gudang Pagi", html)
        self.assertIn("Jadwal Tim", html)
        self.assertIn("Jadwal Gudang Mataram", html)
        self.assertIn("Jadwal Gudang Mega", html)
        self.assertIn("Ajeng", html)
        self.assertIn("Caca", html)
        self.assertIn("Opening shift", html)
        self.assertIn(f'href="/schedule/?start={today}&amp;days=7&amp;warehouse=1"', html)
        self.assertIn(f'href="/schedule/?start={today}&amp;days=7&amp;warehouse=2"', html)

    def test_announcement_center_renders_hris_announcements_and_schedule_changes(self):
        self.login()
        today = date_cls.today().isoformat()

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO announcement_posts(
                    warehouse_id,
                    title,
                    audience,
                    publish_date,
                    status,
                    channel,
                    message,
                    handled_by
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    1,
                    "Pengumuman Shift Pagi",
                    "all",
                    today,
                    "published",
                    "Portal HRIS",
                    "Briefing pagi dipindah ke area inbound.",
                    1,
                ),
            )
            db.execute(
                """
                INSERT INTO schedule_change_events(
                    warehouse_id,
                    audience,
                    event_kind,
                    title,
                    message,
                    start_date,
                    end_date,
                    created_by
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    1,
                    "all",
                    "entry_update",
                    "Rina - Pagi",
                    "Jadwal Rina untuk hari ini diubah ke shift Pagi.",
                    today,
                    today,
                    1,
                ),
            )
            db.commit()

        response = self.client.get("/announcements/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Pusat Pengumuman", html)
        self.assertIn("Pengumuman Shift Pagi", html)
        self.assertIn("Perubahan Jadwal", html)
        self.assertIn("Rina - Pagi", html)
        self.assertIn("Aktifkan Notif Perangkat", html)
        self.assertNotIn("Nonaktifkan", html)

    def test_published_announcement_broadcasts_notifications_and_appears_for_staff(self):
        self.create_user(
            "staff_pengumuman",
            "pass1234",
            "staff",
            warehouse_id=1,
            email="staff@example.com",
            notify_email=1,
        )
        self.login_hr_user("hr_pengumuman_broadcast", "pass1234")

        response = self.client.post(
            "/hris/announcement/add",
            data={
                "warehouse_id": "1",
                "title": "Info SOP Baru",
                "audience": "all",
                "publish_date": date_cls.today().isoformat(),
                "status": "published",
                "channel": "HRIS",
                "message": "SOP loading diperbarui mulai hari ini.",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        staff_user_id = self.get_user_id("staff_pengumuman")

        with self.app.app_context():
            db = get_db()
            notification = db.execute(
                """
                SELECT subject, message, status
                FROM notifications
                WHERE subject=?
                ORDER BY id DESC
                LIMIT 1
                """,
                ("Pengumuman baru: Info SOP Baru",),
            ).fetchone()
            web_notification = db.execute(
                """
                SELECT category, title, link_url, is_read
                FROM web_notifications
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (staff_user_id,),
            ).fetchone()

        self.assertIsNotNone(notification)
        self.assertIn("SOP loading diperbarui", notification["message"])
        self.assertIsNotNone(web_notification)
        self.assertEqual(web_notification["category"], "announcement")
        self.assertEqual(web_notification["title"], "Pengumuman baru: Info SOP Baru")
        self.assertEqual(web_notification["link_url"], "/announcements/")
        self.assertEqual(web_notification["is_read"], 0)

        self.logout()
        self.login("staff_pengumuman", "pass1234")
        page = self.client.get("/announcements/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Info SOP Baru", page.get_data(as_text=True))

        notification_page = self.client.get("/notifications/")
        self.assertEqual(notification_page.status_code, 200)
        notification_html = notification_page.get_data(as_text=True)
        self.assertIn("Semua Notifikasi", notification_html)
        self.assertIn("data-notification-page-list", notification_html)
        self.assertIn("Hapus Semua", notification_html)

        notification_api = self.client.get("/notifications/api?filter=all&limit=10")
        self.assertEqual(notification_api.status_code, 200)
        notification_payload = notification_api.get_json()
        self.assertEqual(notification_payload["status"], "ok")
        self.assertGreaterEqual(notification_payload["unread_count"], 1)
        self.assertTrue(
            any(item["title"] == "Pengumuman baru: Info SOP Baru" for item in notification_payload["items"])
        )

        mark_all = self.client.post("/notifications/api/mark-all-read")
        self.assertEqual(mark_all.status_code, 200)
        self.assertEqual(mark_all.get_json()["unread_count"], 0)

    def test_notifications_api_hides_items_after_mark_read(self):
        self.create_user("staff_notif_read", "pass1234", "staff", warehouse_id=1)
        self.login("staff_notif_read", "pass1234")
        user_id = self.get_user_id("staff_notif_read")

        with self.app.app_context():
            notification_service.create_web_notification(
                user_id,
                "Tes Notifikasi Read",
                "Notif ini harus hilang dari inbox setelah dibaca.",
                category="system",
                link_url="/notifications/",
                source_type="test_notification",
                source_id="read-hide-case",
            )

        list_before = self.client.get("/notifications/api?filter=all&limit=10")
        self.assertEqual(list_before.status_code, 200)
        before_payload = list_before.get_json()
        target_item = next(
            (item for item in before_payload["items"] if item["title"] == "Tes Notifikasi Read"),
            None,
        )
        self.assertIsNotNone(target_item)

        mark_read = self.client.post(f"/notifications/api/{target_item['id']}/read")
        self.assertEqual(mark_read.status_code, 200)
        self.assertEqual(mark_read.get_json()["unread_count"], 0)

        list_after = self.client.get("/notifications/api?filter=all&limit=10")
        self.assertEqual(list_after.status_code, 200)
        after_payload = list_after.get_json()
        self.assertFalse(
            any(item["title"] == "Tes Notifikasi Read" for item in after_payload["items"])
        )

        unread_after = self.client.get("/notifications/api?filter=unread&limit=10")
        self.assertEqual(unread_after.status_code, 200)
        unread_payload = unread_after.get_json()
        self.assertFalse(
            any(item["title"] == "Tes Notifikasi Read" for item in unread_payload["items"])
        )

    def test_notifications_api_supports_delete_single_and_delete_all(self):
        self.create_user("staff_notif_delete", "pass1234", "staff", warehouse_id=1)
        self.login("staff_notif_delete", "pass1234")
        user_id = self.get_user_id("staff_notif_delete")

        with self.app.app_context():
            notification_service.create_web_notification(
                user_id,
                "Tes Hapus Satu",
                "Notif pertama untuk delete single.",
                category="system",
                link_url="/notifications/",
                source_type="test_notification",
                source_id="delete-one-case",
            )
            notification_service.create_web_notification(
                user_id,
                "Tes Hapus Semua",
                "Notif kedua untuk delete all.",
                category="system",
                link_url="/notifications/",
                source_type="test_notification",
                source_id="delete-all-case",
            )

        list_before = self.client.get("/notifications/api?filter=all&limit=10")
        self.assertEqual(list_before.status_code, 200)
        before_payload = list_before.get_json()
        self.assertEqual(len(before_payload["items"]), 2)
        self.assertEqual(before_payload["total_count"], 2)

        delete_target = next(
            (item for item in before_payload["items"] if item["title"] == "Tes Hapus Satu"),
            None,
        )
        self.assertIsNotNone(delete_target)

        delete_one = self.client.post(f"/notifications/api/{delete_target['id']}/delete")
        self.assertEqual(delete_one.status_code, 200)
        delete_one_payload = delete_one.get_json()
        self.assertTrue(delete_one_payload["deleted"])
        self.assertEqual(delete_one_payload["total_count"], 1)

        list_after_one = self.client.get("/notifications/api?filter=all&limit=10")
        self.assertEqual(list_after_one.status_code, 200)
        after_one_payload = list_after_one.get_json()
        self.assertEqual(after_one_payload["total_count"], 1)
        self.assertFalse(
            any(item["title"] == "Tes Hapus Satu" for item in after_one_payload["items"])
        )
        self.assertTrue(
            any(item["title"] == "Tes Hapus Semua" for item in after_one_payload["items"])
        )

        delete_all = self.client.post("/notifications/api/delete-all")
        self.assertEqual(delete_all.status_code, 200)
        delete_all_payload = delete_all.get_json()
        self.assertEqual(delete_all_payload["deleted"], 1)
        self.assertEqual(delete_all_payload["total_count"], 0)
        self.assertEqual(delete_all_payload["unread_count"], 0)

        list_after_all = self.client.get("/notifications/api?filter=all&limit=10")
        self.assertEqual(list_after_all.status_code, 200)
        after_all_payload = list_after_all.get_json()
        self.assertEqual(after_all_payload["total_count"], 0)
        self.assertEqual(after_all_payload["items"], [])

    def test_schedule_changes_are_logged_and_visible_in_announcement_center(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ANN-SCH",
            full_name="Dian Schedule",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user(
            "staff_schedule_alert",
            "pass1234",
            "staff",
            warehouse_id=1,
            email="schedule@example.com",
            notify_email=1,
        )
        self.login_hr_user("hr_schedule_alert", "pass1234")

        response = self.client.post(
            "/schedule/entry/save",
            data={
                "employee_id": str(employee_id),
                "shift_code": "P",
                "entry_start_date": "2026-03-30",
                "entry_end_date": "2026-03-30",
                "note": "Tukar shift karena briefing",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            event = db.execute(
                """
                SELECT title, message
                FROM schedule_change_events
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            notification = db.execute(
                """
                SELECT subject
                FROM notifications
                WHERE subject LIKE 'Perubahan jadwal:%'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        self.assertIsNotNone(event)
        self.assertIn("Dian Schedule", event["title"])
        self.assertIn("Tukar shift karena briefing", event["message"])
        self.assertIsNotNone(notification)

        self.logout()
        self.login("staff_schedule_alert", "pass1234")
        page = self.client.get("/announcements/")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Dian Schedule", html)
        self.assertIn("Tukar shift karena briefing", html)

    def test_announcement_center_limits_schedule_changes_to_five_cards(self):
        self.login()
        today = date_cls.today().isoformat()

        with self.app.app_context():
            db = get_db()
            for index in range(6):
                db.execute(
                    """
                    INSERT INTO schedule_change_events(
                        warehouse_id,
                        audience,
                        event_kind,
                        title,
                        message,
                        start_date,
                        end_date,
                        created_by,
                        created_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        1,
                        "all",
                        "entry_update",
                        f"Live {index:02d}:00 - Staff {index}",
                        f"Perubahan jadwal ke-{index}",
                        today,
                        today,
                        1,
                        f"{today}T{18 - index:02d}:00:00",
                    ),
                )
            db.commit()

        response = self.client.get("/announcements/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(html.count("announcement-event-card-schedule"), 5)
        self.assertIn("Live 00:00 - Staff 0", html)
        self.assertIn("Live 04:00 - Staff 4", html)
        self.assertNotIn("Live 05:00 - Staff 5", html)

    def test_staff_can_open_global_hris_dashboard_with_split_warehouse_preview(self):
        own_employee_id = self.create_employee_record(
            employee_code="EMP-STAFF-DB",
            full_name="Staff Dashboard",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        mataram_employee_id = self.create_employee_record(
            employee_code="EMP-DB-MTR",
            full_name="Nopal Mataram",
            warehouse_id=1,
            position="Leader",
        )
        mega_employee_id = self.create_employee_record(
            employee_code="EMP-DB-MGA",
            full_name="Lifia Mega",
            warehouse_id=2,
            position="Marketing",
        )
        self.create_user("staff_dashboard_view", "pass1234", "staff", warehouse_id=1, employee_id=own_employee_id)
        today = date_cls.today().isoformat()

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO schedule_entries(employee_id, schedule_date, shift_code, note, updated_by)
                VALUES (?,?,?,?,?)
                """,
                (mataram_employee_id, today, "P", "Shift Mataram", 1),
            )
            db.execute(
                """
                INSERT INTO schedule_entries(employee_id, schedule_date, shift_code, note, updated_by)
                VALUES (?,?,?,?,?)
                """,
                (mega_employee_id, today, "S", "Shift Mega", 1),
            )
            db.commit()

        self.login("staff_dashboard_view", "pass1234")
        response = self.client.get(f"/hris/?schedule_start={today}&days=7")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Dashboard HRIS", html)
        self.assertIn("Jadwal Gudang Mataram", html)
        self.assertIn("Jadwal Gudang Mega", html)
        self.assertIn("Nopal", html)
        self.assertIn("Lifia", html)
        self.assertNotIn("Kelola Announcement", html)
        self.assertNotIn('name="warehouse" disabled', html)

    def test_hr_can_save_schedule_profile_and_entry(self):
        self.create_user("hr_scheduler", "pass1234", "hr")
        employee_id = self.create_employee_record(
            employee_code="EMP-SCD-HR",
            full_name="Ajeng Planner",
            warehouse_id=2,
            position="HR Coordinator",
        )

        self.login("hr_scheduler", "pass1234")

        profile_response = self.client.post(
            f"/schedule/profile/save/{employee_id}",
            data={
                "custom_name": "Ajeng",
                "display_group": "HR",
                "location_label": "Mega",
                "display_order": "5",
                "include_in_schedule": "on",
                "profile_note": "PIC schedule mingguan",
                "start": "2026-03-30",
                "days": "7",
            },
            follow_redirects=False,
        )
        self.assertEqual(profile_response.status_code, 302)

        entry_response = self.client.post(
            "/schedule/entry/save",
            data={
                "employee_id": str(employee_id),
                "shift_code": "P",
                "entry_start_date": "2026-03-30",
                "entry_end_date": "2026-04-01",
                "note": "Kickoff minggu baru",
                "start": "2026-03-30",
                "days": "7",
            },
            follow_redirects=False,
        )
        self.assertEqual(entry_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            profile = db.execute(
                """
                SELECT custom_name, display_group, location_label, display_order, include_in_schedule, note
                FROM schedule_employee_profiles
                WHERE employee_id=?
                """,
                (employee_id,),
            ).fetchone()
            entry_count = db.execute(
                """
                SELECT COUNT(*)
                FROM schedule_entries
                WHERE employee_id=?
                  AND schedule_date BETWEEN '2026-03-30' AND '2026-04-01'
                """,
                (employee_id,),
            ).fetchone()[0]

        self.assertIsNotNone(profile)
        self.assertEqual(profile["custom_name"], "Ajeng")
        self.assertEqual(profile["display_group"], "HR")
        self.assertEqual(profile["location_label"], "Mega")
        self.assertEqual(profile["display_order"], 5)
        self.assertEqual(profile["include_in_schedule"], 1)
        self.assertEqual(entry_count, 3)

        board_response = self.client.get("/schedule/?start=2026-03-30&days=7")
        self.assertEqual(board_response.status_code, 200)
        board_html = board_response.get_data(as_text=True)
        self.assertIn("Ajeng", board_html)

    def test_hr_can_save_live_schedule_entry_and_render_live_board(self):
        self.create_user("hr_live", "pass1234", "hr")
        employee_id = self.create_employee_record(
            employee_code="EMP-SCD-LIVE",
            full_name="Caca Live",
            warehouse_id=1,
            position="Marketplace Host",
        )

        self.login("hr_live", "pass1234")

        live_response = self.client.post(
            "/schedule/live/save",
            data={
                "live_warehouse_id": "1",
                "live_schedule_date": "2026-03-31",
                "slot_key": "13:00",
                "employee_id": str(employee_id),
                "channel_label": "Shopee Mega + IG",
                "note": "Host takeover promo",
                "start": "2026-03-30",
                "days": "7",
                "warehouse": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(live_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            live_entry = db.execute(
                """
                SELECT warehouse_id, schedule_date, slot_key, employee_id, channel_label, note
                FROM schedule_live_entries
                WHERE warehouse_id=1 AND schedule_date='2026-03-31' AND slot_key='13:00'
                """
            ).fetchone()

        self.assertIsNotNone(live_entry)
        self.assertEqual(live_entry["employee_id"], employee_id)
        self.assertEqual(live_entry["channel_label"], "Shopee Mega + IG")
        self.assertEqual(live_entry["note"], "Host takeover promo")

        board_response = self.client.get("/schedule/?start=2026-03-30&days=7&warehouse=1")
        self.assertEqual(board_response.status_code, 200)
        board_html = board_response.get_data(as_text=True)
        self.assertIn("Jadwal Live Gudang Mataram", board_html)
        self.assertIn("Shopee Mega + IG", board_html)
        self.assertIn("Caca", board_html)

    def test_hr_can_save_live_schedule_entry_for_date_range(self):
        self.create_user("hr_live_range", "pass1234", "hr")
        employee_id = self.create_employee_record(
            employee_code="EMP-SCD-LIVE-RANGE",
            full_name="Dina Range",
            warehouse_id=1,
            position="Live Host",
        )

        self.login("hr_live_range", "pass1234")

        response = self.client.post(
            "/schedule/live/save",
            data={
                "live_warehouse_id": "1",
                "live_schedule_start": "2026-03-31",
                "live_schedule_end": "2026-04-02",
                "slot_key": "13:00",
                "employee_id": str(employee_id),
                "channel_label": "TikTok Live",
                "note": "Jadwal seminggu promo",
                "start": "2026-03-30",
                "days": "7",
                "warehouse": "1",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Jadwal live berhasil disimpan untuk 3 hari.", response.get_data(as_text=True))

        with self.app.app_context():
            db = get_db()
            rows = db.execute(
                """
                SELECT schedule_date, employee_id, channel_label
                FROM schedule_live_entries
                WHERE warehouse_id=1
                  AND slot_key='13:00'
                  AND schedule_date BETWEEN '2026-03-31' AND '2026-04-02'
                ORDER BY schedule_date
                """
            ).fetchall()

        self.assertEqual([row["schedule_date"] for row in rows], ["2026-03-31", "2026-04-01", "2026-04-02"])
        self.assertTrue(all(row["employee_id"] == employee_id for row in rows))
        self.assertTrue(all(row["channel_label"] == "TikTok Live" for row in rows))

    def test_hr_can_save_schedule_entry_for_ninety_day_range(self):
        self.create_user("hr_schedule_90", "pass1234", "hr")
        employee_id = self.create_employee_record(
            employee_code="EMP-SCD-90",
            full_name="Ninety Day Planner",
            warehouse_id=1,
            position="Warehouse Staff",
        )

        self.login("hr_schedule_90", "pass1234")
        start_date = date_cls.fromisoformat("2026-03-30")
        end_date = start_date + timedelta(days=89)

        response = self.client.post(
            "/schedule/entry/save",
            data={
                "employee_id": str(employee_id),
                "shift_code": "P",
                "entry_start_date": start_date.isoformat(),
                "entry_end_date": end_date.isoformat(),
                "note": "Board panjang 90 hari",
                "start": start_date.isoformat(),
                "days": "90",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Jadwal manual berhasil diterapkan.", response.get_data(as_text=True))

        with self.app.app_context():
            db = get_db()
            entry_count = db.execute(
                """
                SELECT COUNT(*)
                FROM schedule_entries
                WHERE employee_id=?
                  AND schedule_date BETWEEN ? AND ?
                """,
                (employee_id, start_date.isoformat(), end_date.isoformat()),
            ).fetchone()[0]

        self.assertEqual(entry_count, 90)

    def test_admin_can_manage_crm_contacts_purchases_and_members(self):
        self.login()
        response, product_id, variants_rows = self.create_product(
            sku="CRM-PRD-001",
            qty=12,
            variants="40,41",
            warehouse_id="1",
        )
        self.assertEqual(response.status_code, 302)

        add_customer = self.client.post(
            "/crm/customers/add",
            data={
                "warehouse_id": "1",
                "customer_name": "Toko CRM",
                "contact_person": "Rian",
                "phone": "628111111111",
                "email": "rian@crm.test",
                "city": "Mataram",
                "instagram_handle": "@tokocrm",
                "customer_type": "member",
                "marketing_channel": "Repeat Order",
                "note": "Pelanggan setia raket premium",
            },
            follow_redirects=False,
        )
        self.assertEqual(add_customer.status_code, 302)

        with self.app.app_context():
            db = get_db()
            customer = db.execute(
                "SELECT id FROM crm_customers WHERE customer_name='Toko CRM'"
            ).fetchone()
        self.assertIsNotNone(customer)

        add_member = self.client.post(
            "/crm/members/add",
            data={
                "customer_id": str(customer["id"]),
                "member_code": "MBR-CRM-001",
                "tier": "gold",
                "status": "active",
                "join_date": "2026-03-30",
                "expiry_date": "2027-03-30",
                "points": "12",
                "benefit_note": "Diskon komunitas",
                "note": "Masuk loyalty badminton",
            },
            follow_redirects=False,
        )
        self.assertEqual(add_member.status_code, 302)

        with self.app.app_context():
            db = get_db()
            member = db.execute(
                "SELECT id FROM crm_memberships WHERE member_code='MBR-CRM-001'"
            ).fetchone()
        self.assertIsNotNone(member)

        add_purchase = self.client.post(
            "/crm/purchases/add",
            data={
                "warehouse_id": "1",
                "customer_id": str(customer["id"]),
                "member_id": str(member["id"]),
                "purchase_date": "2026-03-30",
                "invoice_no": "INV-CRM-001",
                "channel": "store",
                "note": "Order pembuka untuk stok toko",
                "items_json": json.dumps(
                    [
                        {
                            "product_id": product_id,
                            "variant_id": variants_rows[0]["id"],
                            "qty": 2,
                            "unit_price": 150000,
                            "display_name": "CRM-PRD-001 - Produk Uji",
                        },
                        {
                            "product_id": product_id,
                            "variant_id": variants_rows[1]["id"],
                            "qty": 1,
                            "unit_price": 175000,
                            "display_name": "CRM-PRD-001 - Produk Uji",
                        },
                    ]
                ),
            },
            follow_redirects=False,
        )
        self.assertEqual(add_purchase.status_code, 302)

        add_member_record = self.client.post(
            "/crm/member-records/add",
            data={
                "member_id": str(member["id"]),
                "record_date": "2026-03-31",
                "record_type": "point_adjustment",
                "reference_no": "PROMO-APRIL",
                "amount": "0",
                "points_delta": "25",
                "note": "Bonus poin pembukaan akun",
            },
            follow_redirects=False,
        )
        self.assertEqual(add_member_record.status_code, 302)

        with self.app.app_context():
            db = get_db()
            purchase = db.execute(
                """
                SELECT total_amount, items_count, channel
                FROM crm_purchase_records
                WHERE invoice_no='INV-CRM-001'
                """
            ).fetchone()
            purchase_items_count = db.execute(
                "SELECT COUNT(*) FROM crm_purchase_items"
            ).fetchone()[0]
            member_records = db.execute(
                """
                SELECT record_type, points_delta, amount
                FROM crm_member_records
                WHERE member_id=?
                ORDER BY id
                """,
                (member["id"],),
            ).fetchall()

        self.assertIsNotNone(purchase)
        self.assertEqual(purchase["total_amount"], 475000)
        self.assertEqual(purchase["items_count"], 3)
        self.assertEqual(purchase["channel"], "store")
        self.assertEqual(purchase_items_count, 2)
        self.assertEqual(len(member_records), 2)
        self.assertEqual(member_records[0]["record_type"], "purchase")
        self.assertEqual(member_records[0]["amount"], 475000)
        self.assertEqual(member_records[1]["record_type"], "point_adjustment")
        self.assertEqual(member_records[1]["points_delta"], 25)

        crm_response = self.client.get("/crm/?tab=contacts")
        self.assertEqual(crm_response.status_code, 200)
        crm_html = crm_response.get_data(as_text=True)
        self.assertIn("Toko CRM", crm_html)
        self.assertIn("MBR-CRM-001", crm_html)
        self.assertIn("Produk Uji / 40", crm_html)

    def test_chat_module_supports_direct_messages_and_realtime_unread(self):
        self.create_user("leader_chat", "pass1234", "leader", warehouse_id=1)
        self.create_user("staff_chat", "pass1234", "staff", warehouse_id=1)

        leader_user_id = self.get_user_id("leader_chat")
        self.assertIsNotNone(leader_user_id)

        self.login("staff_chat", "pass1234")

        chat_page = self.client.get("/chat/")
        self.assertEqual(chat_page.status_code, 200)
        chat_html = chat_page.get_data(as_text=True)
        self.assertIn("Chat Operasional Live", chat_html)
        self.assertIn("/static/notif.mp3", chat_html)
        self.assertIn("/static/js/chat_realtime.js", chat_html)

        start_thread = self.client.post(
            "/chat/thread/start",
            json={"target_user_id": leader_user_id},
            follow_redirects=False,
        )
        self.assertEqual(start_thread.status_code, 200)
        start_payload = start_thread.get_json()
        self.assertEqual(start_payload["status"], "ok")
        thread_id = start_payload["thread_id"]

        send_message = self.client.post(
            f"/chat/thread/{thread_id}/send",
            json={"message": "Leader tolong cek request masuk hari ini."},
            follow_redirects=False,
        )
        self.assertEqual(send_message.status_code, 200)
        send_payload = send_message.get_json()
        self.assertEqual(send_payload["status"], "ok")
        self.assertEqual(send_payload["message"]["body"], "Leader tolong cek request masuk hari ini.")

        with self.app.app_context():
            db = get_db()
            stored_message = db.execute(
                """
                SELECT body
                FROM chat_messages
                WHERE thread_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (thread_id,),
            ).fetchone()
            notification_row = db.execute(
                """
                SELECT channel, recipient
                FROM notifications
                WHERE channel='chat'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            web_notification_row = db.execute(
                """
                SELECT category, title, message, link_url
                FROM web_notifications
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (leader_user_id,),
            ).fetchone()

        self.assertIsNotNone(stored_message)
        self.assertEqual(stored_message["body"], "Leader tolong cek request masuk hari ini.")
        self.assertIsNotNone(notification_row)
        self.assertEqual(notification_row["channel"], "chat")
        self.assertEqual(notification_row["recipient"], "leader_chat")
        self.assertIsNotNone(web_notification_row)
        self.assertEqual(web_notification_row["category"], "chat")
        self.assertEqual(web_notification_row["link_url"], f"/chat/?thread={thread_id}")
        self.assertIn("Leader tolong cek request masuk hari ini.", web_notification_row["message"])

        self.logout()
        self.login("leader_chat", "pass1234")

        web_notification_api = self.client.get("/notifications/api?filter=all&limit=10")
        self.assertEqual(web_notification_api.status_code, 200)
        web_notification_payload = web_notification_api.get_json()
        self.assertTrue(any(item["category"] == "chat" for item in web_notification_payload["items"]))

        realtime_before_open = self.client.get(
            "/chat/realtime?since_message_id=0&include_threads=1",
            follow_redirects=False,
        )
        self.assertEqual(realtime_before_open.status_code, 200)
        realtime_before_payload = realtime_before_open.get_json()
        self.assertEqual(realtime_before_payload["status"], "ok")
        self.assertEqual(realtime_before_payload["unread_total"], 1)
        self.assertEqual(len(realtime_before_payload["incoming"]), 1)
        self.assertEqual(realtime_before_payload["threads"][0]["partner_name"], "staff_chat")

        open_thread = self.client.get(f"/chat/?thread={thread_id}")
        self.assertEqual(open_thread.status_code, 200)
        self.assertIn("staff_chat", open_thread.get_data(as_text=True))

        realtime_after_open = self.client.get(
            "/chat/realtime?since_message_id=0&include_threads=1",
            follow_redirects=False,
        )
        self.assertEqual(realtime_after_open.status_code, 200)
        realtime_after_payload = realtime_after_open.get_json()
        self.assertEqual(realtime_after_payload["status"], "ok")
        self.assertEqual(realtime_after_payload["unread_total"], 0)
        self.assertEqual(realtime_after_payload["incoming"], [])
        self.assertEqual(realtime_after_payload["threads"][0]["unread_count"], 0)

    def test_chat_widget_launcher_and_bootstrap_render_for_chat_users(self):
        self.create_user("leader_widget", "pass1234", "leader", warehouse_id=1)
        self.login("leader_widget", "pass1234")

        dashboard_response = self.client.get("/")
        self.assertEqual(dashboard_response.status_code, 200)
        dashboard_html = dashboard_response.get_data(as_text=True)
        self.assertIn("data-chat-widget-launcher", dashboard_html)
        self.assertIn("Live Chat", dashboard_html)
        self.assertIn('id="chatIncomingBanner"', dashboard_html)
        self.assertIn('id="wmsChatRealtimeConfigData"', dashboard_html)
        self.assertIn('"callPollUrl": "/chat/call/poll"', dashboard_html)
        self.assertIn('"callRingtoneUrl": "/static/audio/chat-call-ringtone.mp3', dashboard_html)
        self.assertNotIn('id="chatSidebarUnread"', dashboard_html)

        bootstrap_response = self.client.get("/chat/widget/bootstrap")
        self.assertEqual(bootstrap_response.status_code, 200)
        bootstrap_payload = bootstrap_response.get_json()
        self.assertEqual(bootstrap_payload["status"], "ok")
        self.assertIn("threads", bootstrap_payload)
        self.assertIn("contacts", bootstrap_payload)
        self.assertIn("stickers", bootstrap_payload)
        self.assertIn("attachment_max_bytes", bootstrap_payload)

    def test_chat_message_pushes_notification_to_subscribed_recipient(self):
        self.create_user("staff_chat_push", "pass1234", "staff", warehouse_id=1)
        self.create_user("leader_chat_push", "pass1234", "leader", warehouse_id=1)
        leader_user_id = self.get_user_id("leader_chat_push")

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO push_subscriptions(user_id, endpoint, p256dh_key, auth_key, user_agent, is_active)
                VALUES (?,?,?,?,?,1)
                """,
                (
                    leader_user_id,
                    "https://push.example.test/chat-message",
                    "p256dh-chat-message",
                    "auth-chat-message",
                    "pytest",
                ),
            )
            db.commit()

        self.login("staff_chat_push", "pass1234")
        start_thread = self.client.post(
            "/chat/thread/start",
            json={"target_user_id": leader_user_id},
            follow_redirects=False,
        )
        self.assertEqual(start_thread.status_code, 200)
        thread_id = start_thread.get_json()["thread_id"]

        with patch("services.notification_service._send_web_push", return_value=True) as push_mock:
            send_message = self.client.post(
                f"/chat/thread/{thread_id}/send",
                json={"message": "Ada update inbound yang perlu dicek sekarang."},
                follow_redirects=False,
            )

        self.assertEqual(send_message.status_code, 200)
        self.assertTrue(push_mock.called)
        push_payload = push_mock.call_args[0][2]
        self.assertEqual(push_payload["url"], f"/chat/?thread={thread_id}")
        self.assertIn("Ada update inbound", push_payload["body"])
        self.assertIn(f"chat-thread-{thread_id}-message-", push_payload["tag"])

        with self.app.app_context():
            db = get_db()
            push_notification = db.execute(
                """
                SELECT channel, recipient, subject
                FROM notifications
                WHERE channel='push'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        self.assertIsNotNone(push_notification)
        self.assertEqual(push_notification["recipient"], "https://push.example.test/chat-message")

    def test_chat_call_pushes_incoming_call_notification_to_subscribed_recipient(self):
        self.create_user("caller_push", "pass1234", "admin", warehouse_id=1)
        self.create_user("callee_push", "pass1234", "leader", warehouse_id=1)
        callee_user_id = self.get_user_id("callee_push")

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO push_subscriptions(user_id, endpoint, p256dh_key, auth_key, user_agent, is_active)
                VALUES (?,?,?,?,?,1)
                """,
                (
                    callee_user_id,
                    "https://push.example.test/chat-call",
                    "p256dh-chat-call",
                    "auth-chat-call",
                    "pytest",
                ),
            )
            db.commit()

        self.login("caller_push", "pass1234")
        start_thread = self.client.post(
            "/chat/thread/start",
            json={"target_user_id": callee_user_id},
            follow_redirects=False,
        )
        self.assertEqual(start_thread.status_code, 200)
        thread_id = start_thread.get_json()["thread_id"]

        with patch("services.notification_service._send_web_push", return_value=True) as push_mock:
            start_call = self.client.post(
                f"/chat/thread/{thread_id}/call/start",
                json={"mode": "video"},
                follow_redirects=False,
            )

        self.assertEqual(start_call.status_code, 200)
        self.assertTrue(push_mock.called)
        push_payload = push_mock.call_args[0][2]
        call_id = start_call.get_json()["call"]["id"]
        self.assertEqual(push_payload["url"], f"/chat/?thread={thread_id}&pickup_call={call_id}")
        self.assertTrue(push_payload["requireInteraction"])
        self.assertTrue(push_payload["renotify"])
        self.assertEqual(push_payload["tag"], f"chat-call-{call_id}")
        self.assertIn("menelepon", push_payload["body"])
        self.assertEqual(push_payload["actions"][0]["action"], "open")

        with self.app.app_context():
            db = get_db()
            push_notification = db.execute(
                """
                SELECT channel, recipient, subject
                FROM notifications
                WHERE channel='push'
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()

        self.assertIsNotNone(push_notification)
        self.assertEqual(push_notification["recipient"], "https://push.example.test/chat-call")

    def test_chat_presence_updates_user_presence_and_ignores_invalid_thread(self):
        self.create_user("leader_presence", "pass1234", "leader", warehouse_id=1)
        self.create_user("staff_presence", "pass1234", "staff", warehouse_id=1)

        leader_user_id = self.get_user_id("leader_presence")
        self.assertIsNotNone(leader_user_id)

        self.login("staff_presence", "pass1234")
        start_thread = self.client.post(
            "/chat/thread/start",
            json={"target_user_id": leader_user_id},
            follow_redirects=False,
        )
        self.assertEqual(start_thread.status_code, 200)
        thread_id = start_thread.get_json()["thread_id"]

        presence_response = self.client.post(
            "/chat/presence",
            json={"path": "/hris/biometric", "thread_id": thread_id},
            follow_redirects=False,
        )
        self.assertEqual(presence_response.status_code, 200)
        self.assertEqual(presence_response.get_json()["status"], "ok")

        with self.app.app_context():
            db = get_db()
            current_user_id = self.get_user_id("staff_presence")
            presence_row = db.execute(
                """
                SELECT current_path, active_thread_id
                FROM user_presence
                WHERE user_id=?
                """,
                (current_user_id,),
            ).fetchone()

        self.assertIsNotNone(presence_row)
        self.assertEqual(presence_row["current_path"], "/hris/biometric")
        self.assertEqual(presence_row["active_thread_id"], thread_id)

        invalid_presence_response = self.client.post(
            "/chat/presence",
            json={"path": "/info-produk/", "thread_id": 999999},
            follow_redirects=False,
        )
        self.assertEqual(invalid_presence_response.status_code, 200)
        self.assertEqual(invalid_presence_response.get_json()["status"], "ok")

        with self.app.app_context():
            db = get_db()
            current_user_id = self.get_user_id("staff_presence")
            invalid_presence_row = db.execute(
                """
                SELECT current_path, active_thread_id
                FROM user_presence
                WHERE user_id=?
                """,
                (current_user_id,),
            ).fetchone()

        self.assertIsNotNone(invalid_presence_row)
        self.assertEqual(invalid_presence_row["current_path"], "/info-produk/")
        self.assertIsNone(invalid_presence_row["active_thread_id"])

    def test_chat_timestamp_label_uses_local_offset(self):
        current_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0, tzinfo=None)
        raw_timestamp = current_utc.strftime("%Y-%m-%d %H:%M:%S")
        expected_label = (current_utc + timedelta(hours=7)).strftime("%H:%M")
        self.assertEqual(_format_timestamp_label(raw_timestamp), expected_label)

    def test_chat_supports_group_attachment_sticker_and_call_request(self):
        self.create_user("group_admin", "pass1234", "admin", warehouse_id=1)
        self.create_user("group_leader", "pass1234", "leader", warehouse_id=1)
        self.create_user("group_staff", "pass1234", "staff", warehouse_id=1)

        leader_user_id = self.get_user_id("group_leader")
        staff_user_id = self.get_user_id("group_staff")

        self.login("group_admin", "pass1234")

        create_group = self.client.post(
            "/chat/group/create",
            json={
                "group_name": "Koordinasi Live",
                "group_description": "Follow up inbound dan konten",
                "member_ids": [leader_user_id, staff_user_id],
            },
            follow_redirects=False,
        )
        self.assertEqual(create_group.status_code, 200)
        group_payload = create_group.get_json()
        self.assertEqual(group_payload["status"], "ok")
        thread_id = group_payload["thread_id"]

        sticker_send = self.client.post(
            f"/chat/thread/{thread_id}/send",
            json={"sticker_code": "ok"},
            follow_redirects=False,
        )
        self.assertEqual(sticker_send.status_code, 200)
        self.assertEqual(sticker_send.get_json()["message"]["message_type"], "sticker")

        call_send = self.client.post(
            f"/chat/thread/{thread_id}/send",
            json={"call_mode": "video"},
            follow_redirects=False,
        )
        self.assertEqual(call_send.status_code, 200)
        self.assertEqual(call_send.get_json()["message"]["message_type"], "call")

        attachment_send = self.client.post(
            f"/chat/thread/{thread_id}/send",
            data={
                "message": "Draft revisi terlampir",
                "attachment": (BytesIO(b"chat attachment"), "brief.txt"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(attachment_send.status_code, 200)
        attachment_payload = attachment_send.get_json()
        self.assertEqual(attachment_payload["message"]["message_type"], "attachment")
        self.assertEqual(attachment_payload["message"]["attachment_name"], "brief.txt")

        page = self.client.get(f"/chat/?thread={thread_id}")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Koordinasi Live", html)
        self.assertIn("Attach File", html)
        self.assertIn("Video Call", html)
        self.assertIn("Sticker", html)

        with self.app.app_context():
            db = get_db()
            thread_row = db.execute(
                "SELECT thread_type, group_name FROM chat_threads WHERE id=?",
                (thread_id,),
            ).fetchone()
            member_count = db.execute(
                "SELECT COUNT(*) FROM chat_thread_members WHERE thread_id=?",
                (thread_id,),
            ).fetchone()[0]
            message_types = db.execute(
                """
                SELECT message_type
                FROM chat_messages
                WHERE thread_id=?
                ORDER BY id DESC
                LIMIT 4
                """,
                (thread_id,),
            ).fetchall()

        self.assertEqual(thread_row["thread_type"], "group")
        self.assertEqual(thread_row["group_name"], "Koordinasi Live")
        self.assertEqual(member_count, 3)
        self.assertIn("attachment", [row["message_type"] for row in message_types])
        self.assertIn("call", [row["message_type"] for row in message_types])
        self.assertIn("sticker", [row["message_type"] for row in message_types])

    def test_chat_supports_uploaded_image_sticker(self):
        self.create_user("sticker_admin", "pass1234", "admin", warehouse_id=1)
        self.create_user("sticker_leader", "pass1234", "leader", warehouse_id=1)

        leader_user_id = self.get_user_id("sticker_leader")

        self.login("sticker_admin", "pass1234")

        start_thread = self.client.post(
            "/chat/thread/start",
            json={"target_user_id": leader_user_id},
            follow_redirects=False,
        )
        self.assertEqual(start_thread.status_code, 200)
        thread_id = start_thread.get_json()["thread_id"]

        sticker_send = self.client.post(
            f"/chat/thread/{thread_id}/send",
            data={
                "sticker_image": (BytesIO(b"fake-webp-binary"), "promo.webp"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(sticker_send.status_code, 200)
        sticker_payload = sticker_send.get_json()
        self.assertEqual(sticker_payload["message"]["message_type"], "sticker")
        self.assertEqual(sticker_payload["message"]["attachment_name"], "promo.webp")
        self.assertTrue(sticker_payload["message"]["attachment_url"].startswith("/static/uploads/chat/"))
        self.assertTrue(sticker_payload["message"]["sticker"]["is_custom"])

        page = self.client.get(f"/chat/?thread={thread_id}")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("Upload Sticker", html)
        self.assertIn("/static/uploads/chat/", html)

        with self.app.app_context():
            db = get_db()
            sticker_row = db.execute(
                """
                SELECT message_type, attachment_name, attachment_path, sticker_code
                FROM chat_messages
                WHERE thread_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (thread_id,),
            ).fetchone()

        self.assertEqual(sticker_row["message_type"], "sticker")
        self.assertEqual(sticker_row["attachment_name"], "promo.webp")
        self.assertIsNotNone(sticker_row["attachment_path"])
        self.assertIsNone(sticker_row["sticker_code"])

    def test_chat_webrtc_call_flow_supports_start_signal_accept_and_end(self):
        self.create_user("call_admin", "pass1234", "admin", warehouse_id=1)
        self.create_user("call_leader", "pass1234", "leader", warehouse_id=1)

        leader_user_id = self.get_user_id("call_leader")
        caller_user_id = self.get_user_id("call_admin")

        self.login("call_admin", "pass1234")
        start_thread = self.client.post(
            "/chat/thread/start",
            json={"target_user_id": leader_user_id},
            follow_redirects=False,
        )
        self.assertEqual(start_thread.status_code, 200)
        thread_id = start_thread.get_json()["thread_id"]

        chat_page = self.client.get(f"/chat/?thread={thread_id}")
        self.assertEqual(chat_page.status_code, 200)
        chat_html = chat_page.get_data(as_text=True)
        self.assertIn("/static/js/chat_call.js", chat_html)
        self.assertIn('id="chatCallLayer"', chat_html)

        start_call = self.client.post(
            f"/chat/thread/{thread_id}/call/start",
            json={"mode": "voice"},
            follow_redirects=False,
        )
        self.assertEqual(start_call.status_code, 200)
        start_payload = start_call.get_json()
        self.assertEqual(start_payload["status"], "ok")
        self.assertEqual(start_payload["call"]["status"], "ringing")
        call_id = start_payload["call"]["id"]

        with self.app.app_context():
            db = get_db()
            call_message = db.execute(
                """
                SELECT message_type, call_mode
                FROM chat_messages
                WHERE thread_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (thread_id,),
            ).fetchone()

        self.assertIsNotNone(call_message)
        self.assertEqual(call_message["message_type"], "call")
        self.assertEqual(call_message["call_mode"], "voice")

        self.logout()
        self.login("call_leader", "pass1234")

        pickup_page = self.client.get(f"/chat/?thread={thread_id}&pickup_call={call_id}")
        self.assertEqual(pickup_page.status_code, 200)
        self.assertIn(f'"auto_pickup_call_id": {call_id}', pickup_page.get_data(as_text=True))

        callee_poll = self.client.get("/chat/call/poll?after_signal_id=0", follow_redirects=False)
        self.assertEqual(callee_poll.status_code, 200)
        callee_poll_payload = callee_poll.get_json()
        self.assertEqual(callee_poll_payload["status"], "ok")
        self.assertTrue(any(item["id"] == call_id and item["can_accept"] for item in callee_poll_payload["calls"]))
        self.assertIn("invite", [item["signal_type"] for item in callee_poll_payload["signals"]])

        accept_call = self.client.post(
            f"/chat/call/{call_id}/accept",
            json={},
            follow_redirects=False,
        )
        self.assertEqual(accept_call.status_code, 200)
        accept_payload = accept_call.get_json()
        self.assertEqual(accept_payload["call"]["status"], "connecting")

        self.logout()
        self.login("call_admin", "pass1234")

        caller_poll = self.client.get("/chat/call/poll?after_signal_id=0", follow_redirects=False)
        self.assertEqual(caller_poll.status_code, 200)
        caller_poll_payload = caller_poll.get_json()
        self.assertEqual(caller_poll_payload["status"], "ok")
        self.assertIn("accept", [item["signal_type"] for item in caller_poll_payload["signals"]])

        offer_signal = self.client.post(
            f"/chat/call/{call_id}/signal",
            json={
                "signal_type": "offer",
                "payload": {
                    "sdp": {
                        "type": "offer",
                        "sdp": "fake-offer-sdp",
                    }
                },
            },
            follow_redirects=False,
        )
        self.assertEqual(offer_signal.status_code, 200)
        self.assertEqual(offer_signal.get_json()["call"]["status"], "connecting")

        self.logout()
        self.login("call_leader", "pass1234")

        callee_offer_poll = self.client.get("/chat/call/poll?after_signal_id=0", follow_redirects=False)
        self.assertEqual(callee_offer_poll.status_code, 200)
        callee_offer_payload = callee_offer_poll.get_json()
        self.assertIn("offer", [item["signal_type"] for item in callee_offer_payload["signals"]])

        answer_signal = self.client.post(
            f"/chat/call/{call_id}/signal",
            json={
                "signal_type": "answer",
                "payload": {
                    "sdp": {
                        "type": "answer",
                        "sdp": "fake-answer-sdp",
                    }
                },
            },
            follow_redirects=False,
        )
        self.assertEqual(answer_signal.status_code, 200)
        self.assertEqual(answer_signal.get_json()["call"]["status"], "active")

        self.logout()
        self.login("call_admin", "pass1234")

        caller_answer_poll = self.client.get("/chat/call/poll?after_signal_id=0", follow_redirects=False)
        self.assertEqual(caller_answer_poll.status_code, 200)
        caller_answer_payload = caller_answer_poll.get_json()
        self.assertIn("answer", [item["signal_type"] for item in caller_answer_payload["signals"]])

        end_call = self.client.post(
            f"/chat/call/{call_id}/end",
            json={},
            follow_redirects=False,
        )
        self.assertEqual(end_call.status_code, 200)
        self.assertEqual(end_call.get_json()["call"]["status"], "ended")

        with self.app.app_context():
            db = get_db()
            call_row = db.execute(
                """
                SELECT status, ended_by
                FROM chat_call_sessions
                WHERE id=?
                """,
                (call_id,),
            ).fetchone()

        self.assertIsNotNone(call_row)
        self.assertEqual(call_row["status"], "ended")
        self.assertEqual(call_row["ended_by"], caller_user_id)

    def test_chat_real_call_rejects_group_threads(self):
        self.create_user("group_call_admin", "pass1234", "admin", warehouse_id=1)
        self.create_user("group_call_leader", "pass1234", "leader", warehouse_id=1)
        self.create_user("group_call_staff", "pass1234", "staff", warehouse_id=1)

        leader_user_id = self.get_user_id("group_call_leader")
        staff_user_id = self.get_user_id("group_call_staff")

        self.login("group_call_admin", "pass1234")
        create_group = self.client.post(
            "/chat/group/create",
            json={
                "group_name": "Call Grup Test",
                "group_description": "Validasi pembatasan call grup",
                "member_ids": [leader_user_id, staff_user_id],
            },
            follow_redirects=False,
        )
        self.assertEqual(create_group.status_code, 200)
        thread_id = create_group.get_json()["thread_id"]

        start_call = self.client.post(
            f"/chat/thread/{thread_id}/call/start",
            json={"mode": "voice"},
            follow_redirects=False,
        )
        self.assertEqual(start_call.status_code, 400)
        self.assertIn("direct", start_call.get_json()["message"].lower())

    def test_chat_rejects_attachment_over_10mb(self):
        self.create_user("chat_limit_admin", "pass1234", "admin", warehouse_id=1)
        self.create_user("chat_limit_leader", "pass1234", "leader", warehouse_id=1)

        leader_user_id = self.get_user_id("chat_limit_leader")

        self.login("chat_limit_admin", "pass1234")
        start_thread = self.client.post(
            "/chat/thread/start",
            json={"target_user_id": leader_user_id},
            follow_redirects=False,
        )
        self.assertEqual(start_thread.status_code, 200)
        thread_id = start_thread.get_json()["thread_id"]

        oversized_file = BytesIO(b"x" * ((10 * 1024 * 1024) + 1))
        response = self.client.post(
            f"/chat/thread/{thread_id}/send",
            data={
                "message": "Lampiran besar",
                "attachment": (oversized_file, "oversized.zip"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertEqual(payload["status"], "error")
        self.assertIn("10.0 MB", payload["message"])

    def test_staff_cannot_access_crm_page(self):
        self.create_user("staff_crm", "pass1234", "staff", warehouse_id=1)
        self.login("staff_crm", "pass1234")

        response = self.client.get("/crm/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/schedule/", response.headers["Location"])

        dashboard_response = self.client.get("/")
        dashboard_html = dashboard_response.get_data(as_text=True)
        self.assertNotIn('>CRM<', dashboard_html)

    def test_staff_can_open_chat_but_still_cannot_open_crm(self):
        self.create_user("staff_chat_only", "pass1234", "staff", warehouse_id=1)
        self.login("staff_chat_only", "pass1234")

        chat_response = self.client.get("/chat/")
        self.assertEqual(chat_response.status_code, 200)
        self.assertIn("Chat Operasional Live", chat_response.get_data(as_text=True))

        crm_response = self.client.get("/crm/", follow_redirects=False)
        self.assertEqual(crm_response.status_code, 302)
        self.assertIn("/schedule/", crm_response.headers["Location"])

    def test_hr_can_rename_shift_code_without_breaking_existing_entries(self):
        self.create_user("hr_shift", "pass1234", "hr")
        employee_id = self.create_employee_record(
            employee_code="EMP-SCD-RNM",
            full_name="Rina Shift",
            warehouse_id=1,
            position="Scheduler",
        )

        self.login("hr_shift", "pass1234")

        entry_response = self.client.post(
            "/schedule/entry/save",
            data={
                "employee_id": str(employee_id),
                "shift_code": "P",
                "entry_start_date": "2026-03-30",
                "entry_end_date": "2026-03-30",
                "note": "Shift awal",
                "start": "2026-03-30",
                "days": "7",
            },
            follow_redirects=False,
        )
        self.assertEqual(entry_response.status_code, 302)

        rename_response = self.client.post(
            "/schedule/shift-code/save",
            data={
                "original_code": "P",
                "code": "P1",
                "label": "Pagi 1",
                "bg_color": "#c6e5ab",
                "text_color": "#17351a",
                "sort_order": "10",
                "is_active": "on",
                "start": "2026-03-30",
                "days": "7",
            },
            follow_redirects=False,
        )
        self.assertEqual(rename_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            renamed_shift = db.execute(
                "SELECT code, label FROM schedule_shift_codes WHERE code='P1'"
            ).fetchone()
            removed_shift = db.execute(
                "SELECT code FROM schedule_shift_codes WHERE code='P'"
            ).fetchone()
            schedule_entry = db.execute(
                """
                SELECT shift_code
                FROM schedule_entries
                WHERE employee_id=? AND schedule_date='2026-03-30'
                """,
                (employee_id,),
            ).fetchone()

        self.assertIsNotNone(renamed_shift)
        self.assertEqual(renamed_shift["label"], "Pagi 1")
        self.assertIsNone(removed_shift)
        self.assertEqual(schedule_entry["shift_code"], "P1")

    def test_schedule_board_applies_leave_and_offboarding_overrides(self):
        self.login()
        leave_employee_id = self.create_employee_record(
            employee_code="EMP-SCD-LV",
            full_name="Nina Leave",
            warehouse_id=1,
            position="Marketing",
        )
        offboarding_employee_id = self.create_employee_record(
            employee_code="EMP-SCD-OF",
            full_name="Dio Offboarding",
            warehouse_id=1,
            position="Host Live",
        )

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO schedule_entries(employee_id, schedule_date, shift_code, note, updated_by)
                VALUES (?,?,?,?,?)
                """,
                (leave_employee_id, "2026-03-30", "P", "Harus tertimpa cuti", 1),
            )
            db.execute(
                """
                INSERT INTO leave_requests(
                    employee_id,
                    warehouse_id,
                    leave_type,
                    start_date,
                    end_date,
                    total_days,
                    status,
                    reason,
                    handled_by
                )
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    leave_employee_id,
                    1,
                    "annual",
                    "2026-03-30",
                    "2026-03-30",
                    1,
                    "approved",
                    "Cuti keluarga",
                    1,
                ),
            )
            db.execute(
                """
                INSERT INTO offboarding_records(
                    employee_id,
                    warehouse_id,
                    notice_date,
                    last_working_date,
                    stage,
                    status,
                    handled_by
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    offboarding_employee_id,
                    1,
                    "2026-03-28",
                    "2026-03-30",
                    "handover",
                    "in_progress",
                    1,
                ),
            )
            db.commit()

        response = self.client.get("/schedule/?start=2026-03-30&days=7")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("CUTI", html)
        self.assertIn("OFFBD", html)

    def test_hris_attendance_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/attendance", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/hris/biometric", response.headers["Location"])

        html = self.client.get(response.headers["Location"]).get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Attendance Geotag", html)
        self.assertIn("Rekap Absensi Geotag", html)
        self.assertNotIn("Log Kehadiran", html)
        self.assertNotIn("Tambah Attendance", html)

    def test_hris_leave_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/leave")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Leave", html)
        self.assertIn("Leave Tracker", html)
        self.assertIn("Tambah Leave", html)

    def test_hris_approval_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/approval")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Approval", html)
        self.assertIn("Antrian Approval HR", html)
        self.assertIn("Riwayat Keputusan Terbaru", html)

    def test_hris_approval_route_lists_pending_leave_requests(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-APR-001",
            full_name="Alya Approval",
            warehouse_id=1,
            position="Staff Gudang",
        )
        self.login_hr_user()

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO leave_requests(
                    employee_id,
                    warehouse_id,
                    leave_type,
                    start_date,
                    end_date,
                    total_days,
                    status,
                    reason,
                    note
                )
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "annual",
                    "2026-09-14",
                    "2026-09-15",
                    2,
                    "pending",
                    "Keperluan keluarga",
                    "Perlu approval HR segera",
                ),
            )
            db.commit()

        response = self.client.get("/hris/approval")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Alya Approval", html)
        self.assertIn("Keperluan keluarga", html)
        self.assertIn("Setujui", html)
        self.assertIn("Tolak", html)

    def test_hris_payroll_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/payroll")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Payroll", html)
        self.assertIn("Payroll Register", html)
        self.assertIn("Tambah Payroll", html)

    def test_hris_recruitment_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/recruitment")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Recruitment", html)
        self.assertIn("Hiring Pipeline", html)
        self.assertIn("Tambah Kandidat", html)

    def test_hris_onboarding_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/onboarding")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Onboarding", html)
        self.assertIn("Onboarding Tracker", html)
        self.assertIn("Tambah Onboarding", html)

    def test_hris_offboarding_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/offboarding")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Offboarding", html)
        self.assertIn("Offboarding Tracker", html)
        self.assertIn("Tambah Offboarding", html)

    def test_hris_performance_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/pms")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Performance", html)
        self.assertIn("Performance Review", html)
        self.assertIn("Tambah Review", html)

    def test_hris_helpdesk_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/helpdesk")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Helpdesk", html)
        self.assertIn("Ticket Helpdesk", html)
        self.assertIn("Tambah Ticket", html)

    def test_hris_asset_route_redirects_to_approval_module(self):
        self.login_hr_user()
        response = self.client.get("/hris/asset", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/hris/approval", response.headers["Location"])

    def test_hris_project_route_redirects_to_approval_module(self):
        self.login_hr_user()
        response = self.client.get("/hris/project", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/hris/approval", response.headers["Location"])

    def test_hris_report_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/report")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Report", html)
        self.assertNotIn("HR Analytics Report", html)
        self.assertNotIn("Workforce Snapshot", html)
        self.assertNotIn("Service Health", html)
        self.assertIn("Daily & Live Report Log", html)
        self.assertIn("Log Report Harian", html)
        self.assertIn("Log Live Report", html)

    def test_hris_biometric_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/biometric")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Attendance Geotag", html)
        self.assertIn("Rekap Absensi Geotag", html)
        self.assertIn("Tampilkan Hari", html)
        self.assertIn(
            "HR dan Super Admin bisa mengubah status Present/Late dan jam masuk/pulang langsung dari rekap ini.",
            html,
        )
        self.assertNotIn("Log Geotag Absensi", html)
        self.assertNotIn("Tambah Absen Geotag", html)
        self.assertNotIn('href="/hris/attendance"', html)

    def test_hris_biometric_recap_shows_inline_attendance_status_form_for_hr(self):
        self.login_hr_user("hr_bio_form", "pass1234")
        employee_id = self.create_employee_record(
            employee_code="EMP-BIO-FORM",
            full_name="Biometric Inline Form",
            warehouse_id=1,
        )

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id, warehouse_id, device_name, punch_time, punch_type,
                    sync_status, location_label, latitude, longitude, accuracy_m, note
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "Attendance Photo Portal",
                    "2026-09-03T08:45",
                    "check_in",
                    "synced",
                    "Gudang Mataram - Depan Kantor",
                    -8.58314,
                    116.116798,
                    6.0,
                    "Masuk telat",
                ),
            )
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id, warehouse_id, attendance_date, check_in, status, note, updated_at
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "2026-09-03",
                    "08:45",
                    "late",
                    "Synced from geotag",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        response = self.client.get("/hris/biometric?date_from=2026-09-03&date_to=2026-09-03")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("/hris/biometric/attendance-status", html)
        self.assertIn("biometric-attendance-status-select", html)
        self.assertIn("requestSubmit", html)
        self.assertIn("Present", html)
        self.assertIn("Late", html)

    def test_hris_biometric_recap_shows_shift_and_inline_shift_editor_for_hr(self):
        self.login_hr_user("hr_bio_shift_view", "pass1234")
        employee_id = self.create_employee_record(
            employee_code="EMP-BIO-SHIFT-001",
            full_name="Biometric Shift View",
            warehouse_id=1,
        )

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id, warehouse_id, device_name, punch_time, punch_type,
                    sync_status, location_label, latitude, longitude, accuracy_m,
                    shift_code, shift_label, note
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "Attendance Photo Portal",
                    "2026-09-03T08:05",
                    "check_in",
                    "synced",
                    "Gudang Mataram - Depan Kantor",
                    -8.58314,
                    116.116798,
                    6.0,
                    "pagi",
                    "Shift Pagi | 08.00 - 16.00",
                    "Masuk normal",
                ),
            )
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id, warehouse_id, attendance_date, check_in, status,
                    shift_code, shift_label, note, updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "2026-09-03",
                    "08:05",
                    "present",
                    "pagi",
                    "Shift Pagi | 08.00 - 16.00",
                    "Synced from geotag",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        response = self.client.get("/hris/biometric?date_from=2026-09-03&date_to=2026-09-03")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("/hris/biometric/attendance-shift", html)
        self.assertIn('aria-label="Ubah shift Biometric Shift View"', html)
        self.assertIn("Shift Pagi | 08.00 - 16.00", html)
        self.assertIn("Shift Siang | 13.00 - 21.00", html)

    def test_hr_can_update_biometric_shift_and_resync_attendance_status(self):
        self.login_hr_user("hr_bio_shift_fix", "pass1234")
        employee_id = self.create_employee_record(
            employee_code="EMP-BIO-SHIFT-002",
            full_name="Biometric Shift Fix",
            warehouse_id=1,
        )

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id, warehouse_id, device_name, punch_time, punch_type,
                    sync_status, location_label, latitude, longitude, accuracy_m,
                    shift_code, shift_label, note
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "Attendance Photo Portal",
                    "2026-09-03T08:45",
                    "check_in",
                    "synced",
                    "Gudang Mataram - Depan Kantor",
                    -8.58314,
                    116.116798,
                    6.0,
                    "siang",
                    "Shift Siang | 13.00 - 21.00",
                    "Masuk geotag",
                ),
            )
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id, warehouse_id, attendance_date, check_in, status,
                    shift_code, shift_label, note, updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "2026-09-03",
                    "08:45",
                    "present",
                    "siang",
                    "Shift Siang | 13.00 - 21.00",
                    "Synced from geotag",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        update_response = self.client.post(
            "/hris/biometric/attendance-shift",
            data={
                "employee_id": str(employee_id),
                "attendance_date": "2026-09-03",
                "shift_code": "pagi",
                "return_to": "/hris/biometric?date_from=2026-09-03&date_to=2026-09-03",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric = db.execute(
                """
                SELECT shift_code, shift_label, sync_status
                FROM biometric_logs
                WHERE employee_id=? AND substr(punch_time, 1, 10)=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, "2026-09-03"),
            ).fetchone()
            attendance = db.execute(
                """
                SELECT status, shift_code, shift_label
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, "2026-09-03"),
            ).fetchone()

        self.assertEqual(biometric["shift_code"], "pagi")
        self.assertEqual(biometric["shift_label"], "Shift Pagi | 08.00 - 16.00")
        self.assertEqual(biometric["sync_status"], "manual")
        self.assertEqual(attendance["shift_code"], "pagi")
        self.assertEqual(attendance["shift_label"], "Shift Pagi | 08.00 - 16.00")
        self.assertEqual(attendance["status"], "late")

    def test_non_hr_cannot_update_biometric_shift(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-BIO-SHIFT-003",
            full_name="Biometric Shift Denied",
            warehouse_id=1,
        )
        self.create_user("staff_bio_shift_fix", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("staff_bio_shift_fix", "pass1234")

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id, warehouse_id, device_name, punch_time, punch_type,
                    sync_status, location_label, latitude, longitude, accuracy_m,
                    shift_code, shift_label, note
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "Attendance Photo Portal",
                    "2026-09-03T08:05",
                    "check_in",
                    "synced",
                    "Gudang Mataram - Depan Kantor",
                    -8.58314,
                    116.116798,
                    6.0,
                    "pagi",
                    "Shift Pagi | 08.00 - 16.00",
                    "Masuk geotag",
                ),
            )
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id, warehouse_id, attendance_date, check_in, status,
                    shift_code, shift_label, note, updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "2026-09-03",
                    "08:05",
                    "present",
                    "pagi",
                    "Shift Pagi | 08.00 - 16.00",
                    "Synced from geotag",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        denied_response = self.client.post(
            "/hris/biometric/attendance-shift",
            data={
                "employee_id": str(employee_id),
                "attendance_date": "2026-09-03",
                "shift_code": "siang",
                "return_to": "/hris/biometric?date_from=2026-09-03&date_to=2026-09-03",
            },
            follow_redirects=False,
        )
        self.assertEqual(denied_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric = db.execute(
                """
                SELECT shift_code, shift_label
                FROM biometric_logs
                WHERE employee_id=? AND substr(punch_time, 1, 10)=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, "2026-09-03"),
            ).fetchone()

        self.assertEqual(biometric["shift_code"], "pagi")
        self.assertEqual(biometric["shift_label"], "Shift Pagi | 08.00 - 16.00")

    def test_hris_biometric_route_handles_legacy_attendance_schema_without_status_override(self):
        self.login_hr_user("hr_bio_legacy_schema", "pass1234")
        employee_id = self.create_employee_record(
            employee_code="EMP-BIO-LEGACY",
            full_name="Biometric Legacy Schema",
            warehouse_id=1,
        )

        with self.app.app_context():
            db = get_db()
            db.execute("ALTER TABLE attendance_records RENAME TO attendance_records_new")
            db.execute(
                """
                CREATE TABLE attendance_records(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_id INTEGER,
                    warehouse_id INTEGER,
                    attendance_date TEXT,
                    check_in TEXT,
                    check_out TEXT,
                    status TEXT DEFAULT 'present',
                    note TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            db.execute("DROP TABLE attendance_records_new")
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id, warehouse_id, device_name, punch_time, punch_type,
                    sync_status, location_label, latitude, longitude, accuracy_m, note
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "Attendance Photo Portal",
                    "2026-09-03T08:40",
                    "check_in",
                    "synced",
                    "Gudang Mataram - Pintu Masuk",
                    -8.58314,
                    116.116798,
                    7.5,
                    "Masuk normal",
                ),
            )
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id, warehouse_id, attendance_date, check_in, status, note, updated_at
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "2026-09-03",
                    "08:40",
                    "present",
                    "Synced from geotag",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        response = self.client.get("/hris/biometric?date_from=2026-09-03&date_to=2026-09-03")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Biometric Legacy Schema", html)
        self.assertIn("/hris/biometric/attendance-time", html)

    def test_owner_can_access_hris_biometric_module(self):
        self.create_user("owner_biometric", "pass1234", "owner")
        self.login("owner_biometric", "pass1234")

        response = self.client.get("/hris/biometric")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Attendance Geotag", html)
        self.assertIn("Rekap Absensi Geotag", html)
        self.assertIn('href="/hris/biometric"', html)

        attendance_redirect = self.client.get("/hris/attendance", follow_redirects=False)
        self.assertEqual(attendance_redirect.status_code, 302)
        self.assertIn("/hris/biometric", attendance_redirect.headers["Location"])

    def test_super_admin_can_access_hris_approval_module(self):
        self.create_user("super_hr_approval", "pass1234", "super_admin")
        self.login("super_hr_approval", "pass1234")

        response = self.client.get("/hris/approval")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Antrian Approval HR", html)
        self.assertNotIn("Asset Register", html)
        self.assertNotIn("Project Register", html)

    def test_biometric_route_defaults_to_today_only(self):
        today = date_cls.today().isoformat()
        yesterday = (date_cls.today() - timedelta(days=1)).isoformat()
        today_employee_id = self.create_employee_record(
            employee_code="EMP-BIO-TODAY",
            full_name="Biometric Today Only",
            warehouse_id=1,
        )
        old_employee_id = self.create_employee_record(
            employee_code="EMP-BIO-OLD",
            full_name="Biometric Old Record",
            warehouse_id=1,
        )

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id, warehouse_id, device_name, punch_time, punch_type,
                    sync_status, location_label, latitude, longitude, accuracy_m, note
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    today_employee_id,
                    1,
                    "Attendance Photo Portal",
                    f"{today}T07:55",
                    "check_in",
                    "synced",
                    "Gudang Mataram - Hari Ini",
                    -8.58314,
                    116.116798,
                    7.5,
                    "Masuk hari ini",
                ),
            )
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id, warehouse_id, attendance_date, check_in, status, note, updated_at
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    today_employee_id,
                    1,
                    today,
                    "07:55",
                    "present",
                    "Synced from geotag",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id, warehouse_id, device_name, punch_time, punch_type,
                    sync_status, location_label, latitude, longitude, accuracy_m, note
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    old_employee_id,
                    1,
                    "Attendance Photo Portal",
                    f"{yesterday}T08:35",
                    "check_in",
                    "synced",
                    "Gudang Mataram - Kemarin",
                    -8.58314,
                    116.116798,
                    9.0,
                    "Masuk kemarin",
                ),
            )
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id, warehouse_id, attendance_date, check_in, status, note, updated_at
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    old_employee_id,
                    1,
                    yesterday,
                    "08:35",
                    "late",
                    "Synced from geotag",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        self.login_hr_user("hr_today_filter", "pass1234")
        response = self.client.get("/hris/biometric")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Biometric Today Only", html)
        self.assertNotIn("Biometric Old Record", html)
        self.assertIn(f'name="date_from" value="{today}"', html)
        self.assertIn(f'name="date_to" value="{today}"', html)

    def test_biometric_recap_shows_only_overtime_that_reaches_one_hour(self):
        self.login_hr_user("hr_bio_overtime", "pass1234")
        date_value = "2026-09-05"
        exact_employee_id = self.create_employee_record(
            employee_code="EMP-BIO-OT-OK",
            full_name="Biometric Overtime Exact",
            warehouse_id=1,
        )
        short_employee_id = self.create_employee_record(
            employee_code="EMP-BIO-OT-SHORT",
            full_name="Biometric Overtime Short",
            warehouse_id=1,
        )

        with self.app.app_context():
            db = get_db()
            for employee_id, location_label, check_in_time, check_out_time in [
                (
                    exact_employee_id,
                    "Gudang Mataram - Lembur Satu Jam",
                    "08:00",
                    "17:00",
                ),
                (
                    short_employee_id,
                    "Gudang Mataram - Lembur Pendek",
                    "08:05",
                    "16:45",
                ),
            ]:
                db.execute(
                    """
                    INSERT INTO biometric_logs(
                        employee_id, warehouse_id, device_name, punch_time, punch_type,
                        sync_status, location_label, latitude, longitude, accuracy_m, note
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        employee_id,
                        1,
                        "Attendance Photo Portal",
                        f"{date_value}T{check_in_time}",
                        "check_in",
                        "synced",
                        location_label,
                        -8.58314,
                        116.116798,
                        6.0,
                        "Masuk kerja",
                    ),
                )
                db.execute(
                    """
                    INSERT INTO biometric_logs(
                        employee_id, warehouse_id, device_name, punch_time, punch_type,
                        sync_status, location_label, latitude, longitude, accuracy_m, note
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        employee_id,
                        1,
                        "Attendance Photo Portal",
                        f"{date_value}T{check_out_time}",
                        "check_out",
                        "synced",
                        location_label,
                        -8.58314,
                        116.116798,
                        6.0,
                        "Pulang kerja",
                    ),
                )
                db.execute(
                    """
                    INSERT INTO attendance_records(
                        employee_id, warehouse_id, attendance_date, check_in, check_out,
                        status, shift_code, shift_label, note, updated_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        employee_id,
                        1,
                        date_value,
                        check_in_time,
                        check_out_time,
                        "present",
                        "pagi",
                        "Shift Pagi | 08.00 - 16.00",
                        "Synced from geotag",
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
            db.commit()

        response = self.client.get(f"/hris/biometric?date_from={date_value}&date_to={date_value}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Biometric Overtime Exact", html)
        self.assertIn("Biometric Overtime Short", html)
        self.assertIn("1j 00m", html)
        self.assertNotIn("45 mnt", html)

    def test_biometric_page_shows_staff_overtime_balance_recap_and_usage_history(self):
        self.login_hr_user("hr_overtime_recap", "pass1234")
        hr_user_id = self.get_user_id("hr_overtime_recap")
        date_value = "2026-09-06"
        first_employee_id = self.create_employee_record(
            employee_code="EMP-OT-BAL-1",
            full_name="Saldo Lembur Satu",
            warehouse_id=1,
        )
        second_employee_id = self.create_employee_record(
            employee_code="EMP-OT-BAL-2",
            full_name="Saldo Lembur Dua",
            warehouse_id=1,
        )

        with self.app.app_context():
            db = get_db()
            for employee_id, check_out_time in [
                (first_employee_id, "18:00"),
                (second_employee_id, "17:00"),
            ]:
                db.execute(
                    """
                    INSERT INTO attendance_records(
                        employee_id, warehouse_id, attendance_date, check_in, check_out,
                        status, shift_code, shift_label, note, updated_at
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        employee_id,
                        1,
                        date_value,
                        "08:00",
                        check_out_time,
                        "present",
                        "pagi",
                        "Shift Pagi | 08.00 - 16.00",
                        "Synced from geotag",
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )

            db.execute(
                """
                INSERT INTO overtime_usage_records(
                    employee_id, warehouse_id, usage_date, minutes_used, note, handled_by, updated_at
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    first_employee_id,
                    1,
                    date_value,
                    30,
                    "Dipakai pulang lebih awal",
                    hr_user_id,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            db.commit()

        response = self.client.get(f"/hris/biometric?date_from={date_value}&date_to={date_value}")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Rekap Saldo Lembur Staff", html)
        self.assertIn("Histori Pemakaian Lembur", html)
        self.assertIn("Saldo Lembur Satu", html)
        self.assertIn("Saldo Lembur Dua", html)
        self.assertIn("1j 30m", html)
        self.assertIn("Dipakai pulang lebih awal", html)

    def test_hr_can_use_overtime_balance_and_reject_request_above_available_minutes(self):
        self.login_hr_user("hr_overtime_use", "pass1234")
        date_value = "2026-09-07"
        employee_id = self.create_employee_record(
            employee_code="EMP-OT-USE",
            full_name="Staff Pakai Lembur",
            warehouse_id=1,
        )

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id, warehouse_id, attendance_date, check_in, check_out,
                    status, shift_code, shift_label, note, updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    date_value,
                    "08:00",
                    "17:00",
                    "present",
                    "pagi",
                    "Shift Pagi | 08.00 - 16.00",
                    "Synced from geotag",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        success_response = self.client.post(
            "/hris/biometric/overtime/use",
            data={
                "employee_id": str(employee_id),
                "usage_date": date_value,
                "minutes_used": "30",
                "note": "Dipakai izin setengah jam",
                "return_to": f"/hris/biometric?date_from={date_value}&date_to={date_value}",
            },
            follow_redirects=False,
        )
        self.assertEqual(success_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            usage_rows = db.execute(
                """
                SELECT minutes_used, note
                FROM overtime_usage_records
                WHERE employee_id=?
                ORDER BY id ASC
                """,
                (employee_id,),
            ).fetchall()
        self.assertEqual(len(usage_rows), 1)
        self.assertEqual(usage_rows[0]["minutes_used"], 30)
        self.assertEqual(usage_rows[0]["note"], "Dipakai izin setengah jam")

        failed_response = self.client.post(
            "/hris/biometric/overtime/use",
            data={
                "employee_id": str(employee_id),
                "usage_date": date_value,
                "minutes_used": "45",
                "note": "Melebihi saldo",
                "return_to": f"/hris/biometric?date_from={date_value}&date_to={date_value}",
            },
            follow_redirects=True,
        )
        self.assertEqual(failed_response.status_code, 200)
        failed_html = failed_response.get_data(as_text=True)
        self.assertIn("Saldo lembur staff ini tidak cukup", failed_html)

        with self.app.app_context():
            db = get_db()
            usage_count = db.execute(
                "SELECT COUNT(*) FROM overtime_usage_records WHERE employee_id=?",
                (employee_id,),
            ).fetchone()[0]
        self.assertEqual(usage_count, 1)

    def test_hr_can_override_biometric_late_status_and_preserve_it_after_resync(self):
        self.login_hr_user("hr_bio_override", "pass1234")
        employee_id = self.create_employee_record(
            employee_code="EMP-BIO-OVERRIDE-HR",
            full_name="Biometric Override HR",
            warehouse_id=1,
        )

        create_response = self.client.post(
            "/hris/biometric/add",
            data={
                "employee_id": str(employee_id),
                "location_label": "Gudang Mataram - Pintu Masuk",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "12.5",
                "punch_time": "2026-09-01T08:40",
                "punch_type": "check_in",
                "sync_status": "synced",
                "note": "Check in telat",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        override_response = self.client.post(
            "/hris/biometric/attendance-status",
            data={
                "employee_id": str(employee_id),
                "attendance_date": "2026-09-01",
                "status": "present",
                "return_to": "/hris/biometric?date_from=2026-09-01&date_to=2026-09-01",
            },
            follow_redirects=False,
        )
        self.assertEqual(override_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance = db.execute(
                """
                SELECT status, status_override
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, "2026-09-01"),
            ).fetchone()

        self.assertEqual(attendance["status"], "present")
        self.assertEqual(attendance["status_override"], "present")

        check_out_response = self.client.post(
            "/hris/biometric/add",
            data={
                "employee_id": str(employee_id),
                "location_label": "Gudang Mataram - Pintu Pulang",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "10.0",
                "punch_time": "2026-09-01T17:05",
                "punch_type": "check_out",
                "sync_status": "synced",
                "note": "Pulang kerja",
            },
            follow_redirects=False,
        )
        self.assertEqual(check_out_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance_after = db.execute(
                """
                SELECT check_out, status, status_override
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, "2026-09-01"),
            ).fetchone()

        self.assertEqual(attendance_after["check_out"], "17:05")
        self.assertEqual(attendance_after["status"], "present")
        self.assertEqual(attendance_after["status_override"], "present")

    def test_super_admin_can_override_biometric_late_status(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-BIO-OVERRIDE-SA",
            full_name="Biometric Override Super Admin",
            warehouse_id=1,
        )

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id, warehouse_id, device_name, punch_time, punch_type,
                    sync_status, location_label, latitude, longitude, accuracy_m, note
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "Attendance Photo Portal",
                    "2026-09-02T08:45",
                    "check_in",
                    "synced",
                    "Gudang Mataram - Pintu Masuk",
                    -8.58314,
                    116.116798,
                    8.0,
                    "Masuk telat",
                ),
            )
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id, warehouse_id, attendance_date, check_in, status, note, updated_at
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "2026-09-02",
                    "08:45",
                    "late",
                    "Synced from geotag",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        self.create_user("super_bio_override", "pass1234", "super_admin")
        self.login("super_bio_override", "pass1234")
        response = self.client.post(
            "/hris/biometric/attendance-status",
            data={
                "employee_id": str(employee_id),
                "attendance_date": "2026-09-02",
                "status": "present",
                "return_to": "/hris/biometric?date_from=2026-09-02&date_to=2026-09-02",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance = db.execute(
                """
                SELECT status, status_override, status_override_by
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, "2026-09-02"),
            ).fetchone()

        self.assertEqual(attendance["status"], "present")
        self.assertEqual(attendance["status_override"], "present")
        self.assertIsNotNone(attendance["status_override_by"])

    def test_legacy_superadmin_role_can_adjust_biometric_status(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-BIO-LEGACY-SA",
            full_name="Biometric Legacy Superadmin",
            warehouse_id=1,
        )

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id, warehouse_id, device_name, punch_time, punch_type,
                    sync_status, location_label, latitude, longitude, accuracy_m, note
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "Attendance Photo Portal",
                    "2026-09-04T08:45",
                    "check_in",
                    "synced",
                    "Gudang Mataram - Pintu Masuk",
                    -8.58314,
                    116.116798,
                    8.0,
                    "Masuk telat",
                ),
            )
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id, warehouse_id, attendance_date, check_in, status, note, updated_at
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "2026-09-04",
                    "08:45",
                    "late",
                    "Synced from geotag",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        self.create_user("legacy_superadmin", "pass1234", "superadmin")
        self.login("legacy_superadmin", "pass1234")

        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("role"), "super_admin")

        response = self.client.get("/hris/biometric?date_from=2026-09-04&date_to=2026-09-04")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("biometric-attendance-status-select", html)

        update_response = self.client.post(
            "/hris/biometric/attendance-status",
            data={
                "employee_id": str(employee_id),
                "attendance_date": "2026-09-04",
                "status": "present",
                "return_to": "/hris/biometric?date_from=2026-09-04&date_to=2026-09-04",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance = db.execute(
                """
                SELECT status, status_override
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, "2026-09-04"),
            ).fetchone()

        self.assertEqual(attendance["status"], "present")
        self.assertEqual(attendance["status_override"], "present")

    def test_attendance_portal_renders_for_logged_in_user(self):
        self.login()
        response = self.client.get("/absen/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Absen Foto", html)
        self.assertIn("Mode Hari Ini", html)
        self.assertNotIn('href="#foto-absen"', html)
        self.assertNotIn("Riwayat Absen Sebelumnya", html)
        self.assertIn("belum ditautkan ke data karyawan", html.lower())

    def test_attendance_portal_renders_location_scope_dropdown_for_linked_user(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-LOC-001",
            full_name="Portal Location Scope",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_scope", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_scope", "pass1234")

        response = self.client.get("/absen/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="location_scope"', html)
        self.assertIn('id="foto-absen"', html)
        self.assertIn("Gudang Mataram", html)
        self.assertIn("Gudang Mega", html)
        self.assertIn("Event", html)
        self.assertIn("Lainnya", html)

    def test_attendance_portal_redirects_back_when_photo_payload_too_large(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-LIMIT",
            full_name="Portal Limit",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_limit", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_limit", "pass1234")
        today = date_cls.today().isoformat()
        original_limit = self.app.config["MAX_CONTENT_LENGTH"]
        self.app.config["MAX_CONTENT_LENGTH"] = 1024

        try:
            response = self.client.post(
                "/absen/submit",
                data={
                    "shift_code": "pagi",
                    "location_label": "Gudang Mataram - Pintu Utama",
                    "latitude": "-8.583140",
                    "longitude": "116.116798",
                    "accuracy_m": "7.5",
                    "punch_time": f"{today}T07:58",
                    "punch_type": "check_in",
                    "note": "Masuk shift pagi",
                    "photo_data_url": "data:image/jpeg;base64," + ("A" * 5000),
                },
                follow_redirects=True,
            )
        finally:
            self.app.config["MAX_CONTENT_LENGTH"] = original_limit

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Ukuran foto absen terlalu besar", html)
        self.assertIn("Foto Absen", html)

        with self.app.app_context():
            db = get_db()
            biometric_count = db.execute(
                "SELECT COUNT(*) FROM biometric_logs WHERE employee_id=?",
                (employee_id,),
            ).fetchone()[0]

        self.assertEqual(biometric_count, 0)

    def test_account_settings_updates_chat_volume_and_contact_preferences(self):
        self.create_user(
            "account_pref_user",
            "pass1234",
            "staff",
            warehouse_id=1,
            email="old@example.com",
            phone="08123",
        )
        self.login("account_pref_user", "pass1234")

        page = self.client.get("/account/settings")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Pengaturan Akun", page.get_data(as_text=True))

        save_response = self.client.post(
            "/account/settings",
            data={
                "email": "new@example.com",
                "phone": "628111111111",
                "notify_email": "on",
                "chat_sound_volume": "35",
            },
            follow_redirects=False,
        )
        self.assertEqual(save_response.status_code, 302)
        self.assertIn("/account/settings", save_response.headers["Location"])

        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("chat_sound_volume"), 0.35)

        with self.app.app_context():
            db = get_db()
            user = db.execute(
                """
                SELECT email, phone, notify_email, notify_whatsapp, chat_sound_volume
                FROM users
                WHERE username=?
                """,
                ("account_pref_user",),
            ).fetchone()

        self.assertEqual(user["email"], "new@example.com")
        self.assertEqual(user["phone"], "628111111111")
        self.assertEqual(user["notify_email"], 1)
        self.assertEqual(user["notify_whatsapp"], 0)
        self.assertEqual(user["chat_sound_volume"], 0.35)

    def test_leave_portal_renders_for_logged_in_user(self):
        self.login()
        response = self.client.get("/libur/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Form Libur / Cuti / Sakit", html)
        self.assertIn("HR / Super Admin", html)
        self.assertIn("belum ditautkan ke data karyawan", html.lower())

    def test_hris_announcement_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/announcement")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Announcement", html)
        self.assertIn("Announcement Board", html)
        self.assertIn("Tambah Announcement", html)

    def test_hris_documents_route_renders_operational_view(self):
        self.login_hr_user()
        response = self.client.get("/hris/documents")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("HRIS Integration Hub", html)
        self.assertIn("Documents", html)
        self.assertIn("Document Register", html)
        self.assertIn("Tambah Document", html)

    def test_admin_can_manage_employee_records_in_hris(self):
        self.login_hr_user()

        create_response = self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-001",
                "full_name": "Budi Santoso",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Stock Controller",
                "employment_status": "active",
                "phone": "628123456789",
                "email": "budi@example.com",
                "join_date": "2026-03-01",
                "work_location": "Gudang Mega",
                "notes": "Lead picker zone A",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, employee_code, full_name, warehouse_id, department, position, employment_status
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["full_name"], "Budi Santoso")
        self.assertEqual(employee["warehouse_id"], 2)
        self.assertEqual(employee["employment_status"], "active")

        update_response = self.client.post(
            f"/hris/employee/update/{employee['id']}",
            data={
                "employee_code": "EMP-001",
                "full_name": "Budi Santoso Update",
                "warehouse_id": "2",
                "department": "Warehouse Support",
                "position": "Inventory Analyst",
                "employment_status": "probation",
                "phone": "628123456789",
                "email": "budi@example.com",
                "join_date": "2026-03-01",
                "work_location": "Gudang Mataram",
                "notes": "Updated note",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            employee_after = db.execute(
                """
                SELECT full_name, warehouse_id, department, position, employment_status, work_location
                FROM employees
                WHERE id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertEqual(employee_after["full_name"], "Budi Santoso Update")
        self.assertEqual(employee_after["warehouse_id"], 2)
        self.assertEqual(employee_after["department"], "Warehouse Support")
        self.assertEqual(employee_after["position"], "Inventory Analyst")
        self.assertEqual(employee_after["employment_status"], "probation")
        self.assertEqual(employee_after["work_location"], "Gudang Mataram")

        delete_response = self.client.post(
            f"/hris/employee/delete/{employee['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            employee_count = db.execute(
                "SELECT COUNT(*) FROM employees"
            ).fetchone()[0]

        self.assertEqual(employee_count, 0)

    def test_admin_can_manage_attendance_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-ATT-001",
                "full_name": "Sinta Presensi",
                "warehouse_id": "2",
                "department": "People Operation",
                "position": "Admin HR",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-ATT-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/attendance/add",
            data={
                "employee_id": str(employee["id"]),
                "attendance_date": "2026-03-30",
                "check_in": "08:15",
                "check_out": "17:05",
                "status": "present",
                "note": "Shift pagi normal",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance = db.execute(
                """
                SELECT id, employee_id, warehouse_id, attendance_date, check_in, check_out, status, note
                FROM attendance_records
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(attendance)
        self.assertEqual(attendance["warehouse_id"], 2)
        self.assertEqual(attendance["attendance_date"], "2026-03-30")
        self.assertEqual(attendance["check_in"], "08:15")
        self.assertEqual(attendance["check_out"], "17:05")
        self.assertEqual(attendance["status"], "present")

        update_response = self.client.post(
            f"/hris/attendance/update/{attendance['id']}",
            data={
                "employee_id": str(employee["id"]),
                "attendance_date": "2026-03-30",
                "check_in": "08:35",
                "check_out": "17:30",
                "status": "late",
                "note": "Terlambat karena meeting vendor",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance_after = db.execute(
                """
                SELECT check_in, check_out, status, note
                FROM attendance_records
                WHERE id=?
                """,
                (attendance["id"],),
            ).fetchone()

        self.assertEqual(attendance_after["check_in"], "08:35")
        self.assertEqual(attendance_after["check_out"], "17:30")
        self.assertEqual(attendance_after["status"], "late")
        self.assertEqual(attendance_after["note"], "Terlambat karena meeting vendor")

        delete_response = self.client.post(
            f"/hris/attendance/delete/{attendance['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance_count = db.execute(
                "SELECT COUNT(*) FROM attendance_records"
            ).fetchone()[0]

        self.assertEqual(attendance_count, 0)

    def test_admin_can_manage_leave_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-LV-001",
                "full_name": "Rina Cuti",
                "warehouse_id": "2",
                "department": "HR Support",
                "position": "People Admin",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-LV-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/leave/add",
            data={
                "employee_id": str(employee["id"]),
                "leave_type": "annual",
                "start_date": "2026-04-10",
                "end_date": "2026-04-12",
                "status": "pending",
                "reason": "Cuti keluarga",
                "note": "Handover ke tim inventory",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            leave_request = db.execute(
                """
                SELECT id, employee_id, warehouse_id, leave_type, start_date, end_date, total_days, status, reason, note
                FROM leave_requests
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(leave_request)
        self.assertEqual(leave_request["warehouse_id"], 2)
        self.assertEqual(leave_request["leave_type"], "annual")
        self.assertEqual(leave_request["total_days"], 3)
        self.assertEqual(leave_request["status"], "pending")
        self.assertEqual(leave_request["reason"], "Cuti keluarga")

        update_response = self.client.post(
            f"/hris/leave/update/{leave_request['id']}",
            data={
                "employee_id": str(employee["id"]),
                "leave_type": "sick",
                "start_date": "2026-04-10",
                "end_date": "2026-04-11",
                "status": "approved",
                "reason": "Istirahat dokter",
                "note": "Disetujui supervisor",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            leave_after = db.execute(
                """
                SELECT leave_type, start_date, end_date, total_days, status, reason, note, handled_by
                FROM leave_requests
                WHERE id=?
                """,
                (leave_request["id"],),
            ).fetchone()

        self.assertEqual(leave_after["leave_type"], "sick")
        self.assertEqual(leave_after["end_date"], "2026-04-11")
        self.assertEqual(leave_after["total_days"], 2)
        self.assertEqual(leave_after["status"], "approved")
        self.assertEqual(leave_after["reason"], "Istirahat dokter")
        self.assertIsNotNone(leave_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/leave/delete/{leave_request['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            leave_count = db.execute(
                "SELECT COUNT(*) FROM leave_requests"
            ).fetchone()[0]

        self.assertEqual(leave_count, 0)

    def test_admin_can_manage_payroll_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-PY-001",
                "full_name": "Dani Payroll",
                "warehouse_id": "2",
                "department": "Finance",
                "position": "Payroll Admin",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-PY-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/payroll/add",
            data={
                "employee_id": str(employee["id"]),
                "period_month": "4",
                "period_year": "2026",
                "base_salary": "5500000",
                "allowance": "350000",
                "overtime_pay": "150000",
                "deduction": "100000",
                "leave_deduction": "50000",
                "status": "draft",
                "note": "Payroll April draft",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            payroll = db.execute(
                """
                SELECT id, employee_id, warehouse_id, period_month, period_year, base_salary, allowance,
                       overtime_pay, deduction, leave_deduction, net_pay, status, note
                FROM payroll_runs
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(payroll)
        self.assertEqual(payroll["warehouse_id"], 2)
        self.assertEqual(payroll["period_month"], 4)
        self.assertEqual(payroll["period_year"], 2026)
        self.assertEqual(payroll["net_pay"], 5850000)
        self.assertEqual(payroll["status"], "draft")

        update_response = self.client.post(
            f"/hris/payroll/update/{payroll['id']}",
            data={
                "employee_id": str(employee["id"]),
                "period_month": "4",
                "period_year": "2026",
                "base_salary": "5600000",
                "allowance": "400000",
                "overtime_pay": "200000",
                "deduction": "120000",
                "leave_deduction": "30000",
                "status": "paid",
                "note": "Payroll April final",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            payroll_after = db.execute(
                """
                SELECT base_salary, allowance, overtime_pay, deduction, leave_deduction, net_pay, status, note, handled_by
                FROM payroll_runs
                WHERE id=?
                """,
                (payroll["id"],),
            ).fetchone()

        self.assertEqual(payroll_after["base_salary"], 5600000)
        self.assertEqual(payroll_after["allowance"], 400000)
        self.assertEqual(payroll_after["overtime_pay"], 200000)
        self.assertEqual(payroll_after["deduction"], 120000)
        self.assertEqual(payroll_after["leave_deduction"], 30000)
        self.assertEqual(payroll_after["net_pay"], 6050000)
        self.assertEqual(payroll_after["status"], "paid")
        self.assertEqual(payroll_after["note"], "Payroll April final")
        self.assertIsNotNone(payroll_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/payroll/delete/{payroll['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            payroll_count = db.execute(
                "SELECT COUNT(*) FROM payroll_runs"
            ).fetchone()[0]

        self.assertEqual(payroll_count, 0)

    def test_admin_can_manage_recruitment_records_in_hris(self):
        self.login_hr_user()

        create_response = self.client.post(
            "/hris/recruitment/add",
            data={
                "candidate_name": "Farhan Nugraha",
                "position_title": "Warehouse Supervisor",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "stage": "interview",
                "status": "active",
                "source": "Referral",
                "phone": "628111111111",
                "email": "farhan@example.com",
                "expected_join_date": "2026-05-01",
                "note": "Kandidat kuat untuk shift utama",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            candidate = db.execute(
                """
                SELECT id, candidate_name, warehouse_id, position_title, stage, status, source
                FROM recruitment_candidates
                WHERE candidate_name=?
                """,
                ("Farhan Nugraha",),
            ).fetchone()

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["warehouse_id"], 2)
        self.assertEqual(candidate["stage"], "interview")
        self.assertEqual(candidate["status"], "active")

        update_response = self.client.post(
            f"/hris/recruitment/update/{candidate['id']}",
            data={
                "candidate_name": "Farhan Nugraha Update",
                "position_title": "Warehouse Lead",
                "warehouse_id": "2",
                "department": "Warehouse Support",
                "stage": "offer",
                "status": "closed",
                "source": "Job Portal",
                "phone": "628122222222",
                "email": "farhan.update@example.com",
                "expected_join_date": "2026-05-10",
                "note": "Offer final approved",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            candidate_after = db.execute(
                """
                SELECT candidate_name, warehouse_id, position_title, stage, status, source, handled_by
                FROM recruitment_candidates
                WHERE id=?
                """,
                (candidate["id"],),
            ).fetchone()

        self.assertEqual(candidate_after["candidate_name"], "Farhan Nugraha Update")
        self.assertEqual(candidate_after["warehouse_id"], 2)
        self.assertEqual(candidate_after["position_title"], "Warehouse Lead")
        self.assertEqual(candidate_after["stage"], "offer")
        self.assertEqual(candidate_after["status"], "closed")
        self.assertEqual(candidate_after["source"], "Job Portal")
        self.assertIsNotNone(candidate_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/recruitment/delete/{candidate['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            candidate_count = db.execute(
                "SELECT COUNT(*) FROM recruitment_candidates"
            ).fetchone()[0]

        self.assertEqual(candidate_count, 0)

    def test_admin_can_manage_onboarding_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-ONB-001",
                "full_name": "Ayu Onboarding",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Picker",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-ONB-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/onboarding/add",
            data={
                "employee_id": str(employee["id"]),
                "start_date": "2026-05-01",
                "target_date": "2026-05-07",
                "stage": "orientation",
                "status": "in_progress",
                "buddy_name": "Leader Andi",
                "note": "Sudah briefing awal",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            onboarding = db.execute(
                """
                SELECT id, employee_id, warehouse_id, start_date, target_date, stage, status, buddy_name, note
                FROM onboarding_records
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(onboarding)
        self.assertEqual(onboarding["warehouse_id"], 2)
        self.assertEqual(onboarding["stage"], "orientation")
        self.assertEqual(onboarding["status"], "in_progress")
        self.assertEqual(onboarding["buddy_name"], "Leader Andi")

        update_response = self.client.post(
            f"/hris/onboarding/update/{onboarding['id']}",
            data={
                "employee_id": str(employee["id"]),
                "start_date": "2026-05-01",
                "target_date": "2026-05-05",
                "stage": "go_live",
                "status": "completed",
                "buddy_name": "Leader Budi",
                "note": "Sudah siap operasional penuh",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            onboarding_after = db.execute(
                """
                SELECT target_date, stage, status, buddy_name, note, handled_by
                FROM onboarding_records
                WHERE id=?
                """,
                (onboarding["id"],),
            ).fetchone()

        self.assertEqual(onboarding_after["target_date"], "2026-05-05")
        self.assertEqual(onboarding_after["stage"], "go_live")
        self.assertEqual(onboarding_after["status"], "completed")
        self.assertEqual(onboarding_after["buddy_name"], "Leader Budi")
        self.assertEqual(onboarding_after["note"], "Sudah siap operasional penuh")
        self.assertIsNotNone(onboarding_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/onboarding/delete/{onboarding['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            onboarding_count = db.execute(
                "SELECT COUNT(*) FROM onboarding_records"
            ).fetchone()[0]

        self.assertEqual(onboarding_count, 0)

    def test_admin_can_manage_offboarding_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-OFF-001",
                "full_name": "Bayu Exit",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Inbound Staff",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-OFF-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/offboarding/add",
            data={
                "employee_id": str(employee["id"]),
                "notice_date": "2026-06-01",
                "last_working_date": "2026-06-15",
                "stage": "handover",
                "status": "in_progress",
                "exit_reason": "Relokasi keluarga",
                "handover_pic": "Leader Sinta",
                "note": "Perlu handover area inbound",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            offboarding = db.execute(
                """
                SELECT id, employee_id, warehouse_id, notice_date, last_working_date, stage,
                       status, exit_reason, handover_pic, note, handled_by
                FROM offboarding_records
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(offboarding)
        self.assertEqual(offboarding["warehouse_id"], 2)
        self.assertEqual(offboarding["notice_date"], "2026-06-01")
        self.assertEqual(offboarding["last_working_date"], "2026-06-15")
        self.assertEqual(offboarding["stage"], "handover")
        self.assertEqual(offboarding["status"], "in_progress")
        self.assertEqual(offboarding["exit_reason"], "Relokasi keluarga")
        self.assertEqual(offboarding["handover_pic"], "Leader Sinta")
        self.assertEqual(offboarding["note"], "Perlu handover area inbound")
        self.assertIsNotNone(offboarding["handled_by"])

        update_response = self.client.post(
            f"/hris/offboarding/update/{offboarding['id']}",
            data={
                "employee_id": str(employee["id"]),
                "notice_date": "2026-06-01",
                "last_working_date": "2026-06-18",
                "stage": "exit_complete",
                "status": "completed",
                "exit_reason": "Relokasi keluarga selesai",
                "handover_pic": "Leader Wati",
                "note": "Semua akses dan asset sudah ditutup",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            offboarding_after = db.execute(
                """
                SELECT last_working_date, stage, status, exit_reason, handover_pic, note, handled_by
                FROM offboarding_records
                WHERE id=?
                """,
                (offboarding["id"],),
            ).fetchone()

        self.assertEqual(offboarding_after["last_working_date"], "2026-06-18")
        self.assertEqual(offboarding_after["stage"], "exit_complete")
        self.assertEqual(offboarding_after["status"], "completed")
        self.assertEqual(offboarding_after["exit_reason"], "Relokasi keluarga selesai")
        self.assertEqual(offboarding_after["handover_pic"], "Leader Wati")
        self.assertEqual(offboarding_after["note"], "Semua akses dan asset sudah ditutup")
        self.assertIsNotNone(offboarding_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/offboarding/delete/{offboarding['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            offboarding_count = db.execute(
                "SELECT COUNT(*) FROM offboarding_records"
            ).fetchone()[0]

        self.assertEqual(offboarding_count, 0)

    def test_admin_can_manage_performance_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-PMS-001",
                "full_name": "Lina Review",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Stock Controller",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-PMS-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/performance/add",
            data={
                "employee_id": str(employee["id"]),
                "review_period": "2026-Q2",
                "goal_score": "88",
                "discipline_score": "90",
                "teamwork_score": "84",
                "status": "reviewed",
                "reviewer_name": "Manager Operasional",
                "note": "Konsisten dan siap naik tanggung jawab",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            review = db.execute(
                """
                SELECT id, employee_id, warehouse_id, review_period, goal_score, discipline_score,
                       teamwork_score, final_score, rating, status, reviewer_name, note, handled_by
                FROM performance_reviews
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(review)
        self.assertEqual(review["warehouse_id"], 2)
        self.assertEqual(review["review_period"], "2026-Q2")
        self.assertEqual(review["status"], "reviewed")
        self.assertEqual(review["reviewer_name"], "Manager Operasional")
        self.assertEqual(review["note"], "Konsisten dan siap naik tanggung jawab")
        self.assertAlmostEqual(review["final_score"], 87.33, places=2)
        self.assertEqual(review["rating"], "good")
        self.assertIsNotNone(review["handled_by"])

        update_response = self.client.post(
            f"/hris/performance/update/{review['id']}",
            data={
                "employee_id": str(employee["id"]),
                "review_period": "2026-Q2",
                "goal_score": "92",
                "discipline_score": "91",
                "teamwork_score": "90",
                "status": "acknowledged",
                "reviewer_name": "Head Operasional",
                "note": "Naik level dan siap pegang area lebih besar",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            review_after = db.execute(
                """
                SELECT goal_score, discipline_score, teamwork_score, final_score, rating, status,
                       reviewer_name, note, handled_by
                FROM performance_reviews
                WHERE id=?
                """,
                (review["id"],),
            ).fetchone()

        self.assertEqual(review_after["goal_score"], 92)
        self.assertEqual(review_after["discipline_score"], 91)
        self.assertEqual(review_after["teamwork_score"], 90)
        self.assertAlmostEqual(review_after["final_score"], 91.0, places=2)
        self.assertEqual(review_after["rating"], "excellent")
        self.assertEqual(review_after["status"], "acknowledged")
        self.assertEqual(review_after["reviewer_name"], "Head Operasional")
        self.assertEqual(review_after["note"], "Naik level dan siap pegang area lebih besar")
        self.assertIsNotNone(review_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/performance/delete/{review['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            performance_count = db.execute(
                "SELECT COUNT(*) FROM performance_reviews"
            ).fetchone()[0]

        self.assertEqual(performance_count, 0)

    def test_admin_can_manage_helpdesk_records_in_hris(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-HLP-001",
                "full_name": "Novi Support",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Checker",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-HLP-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/helpdesk/add",
            data={
                "employee_id": str(employee["id"]),
                "ticket_title": "Scanner picking bermasalah",
                "category": "asset",
                "priority": "urgent",
                "status": "in_progress",
                "channel": "WhatsApp",
                "assigned_to": "IT Support",
                "note": "Perlu reset device area picking",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            ticket = db.execute(
                """
                SELECT id, employee_id, warehouse_id, ticket_title, category, priority,
                       status, channel, assigned_to, note, handled_by
                FROM helpdesk_tickets
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()

        self.assertIsNotNone(ticket)
        self.assertEqual(ticket["warehouse_id"], 2)
        self.assertEqual(ticket["ticket_title"], "Scanner picking bermasalah")
        self.assertEqual(ticket["category"], "asset")
        self.assertEqual(ticket["priority"], "urgent")
        self.assertEqual(ticket["status"], "in_progress")
        self.assertEqual(ticket["channel"], "WhatsApp")
        self.assertEqual(ticket["assigned_to"], "IT Support")
        self.assertEqual(ticket["note"], "Perlu reset device area picking")
        self.assertIsNotNone(ticket["handled_by"])

        update_response = self.client.post(
            f"/hris/helpdesk/update/{ticket['id']}",
            data={
                "employee_id": str(employee["id"]),
                "ticket_title": "Scanner picking selesai ditangani",
                "category": "asset",
                "priority": "high",
                "status": "resolved",
                "channel": "Onsite",
                "assigned_to": "IT Lead",
                "note": "Firmware berhasil diperbarui",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            ticket_after = db.execute(
                """
                SELECT ticket_title, priority, status, channel, assigned_to, note, handled_by
                FROM helpdesk_tickets
                WHERE id=?
                """,
                (ticket["id"],),
            ).fetchone()

        self.assertEqual(ticket_after["ticket_title"], "Scanner picking selesai ditangani")
        self.assertEqual(ticket_after["priority"], "high")
        self.assertEqual(ticket_after["status"], "resolved")
        self.assertEqual(ticket_after["channel"], "Onsite")
        self.assertEqual(ticket_after["assigned_to"], "IT Lead")
        self.assertEqual(ticket_after["note"], "Firmware berhasil diperbarui")
        self.assertIsNotNone(ticket_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/helpdesk/delete/{ticket['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            ticket_count = db.execute(
                "SELECT COUNT(*) FROM helpdesk_tickets"
            ).fetchone()[0]

        self.assertEqual(ticket_count, 0)

    def test_legacy_asset_management_routes_are_disabled_in_favor_of_approval(self):
        self.login_hr_user()
        employee_id = self.create_employee_record(
            employee_code="EMP-AST-001",
            full_name="Rafi Asset",
            warehouse_id=2,
            department="Warehouse Operation",
            position="Picker",
        )

        create_response = self.client.post(
            "/hris/asset/add",
            data={
                "employee_id": str(employee_id),
                "asset_name": "Handheld Scanner",
                "asset_code": "AST-001",
                "serial_number": "SN-7788",
                "category": "Device",
                "asset_status": "allocated",
                "condition_status": "good",
                "assigned_date": "2026-07-01",
                "return_date": "",
                "note": "Dipakai area picking",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)
        self.assertIn("/hris/asset", create_response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            asset_count = db.execute(
                "SELECT COUNT(*) FROM asset_records"
            ).fetchone()[0]

        self.assertEqual(asset_count, 0)

        legacy_redirect = self.client.get("/hris/asset", follow_redirects=False)
        self.assertEqual(legacy_redirect.status_code, 302)
        self.assertIn("/hris/approval", legacy_redirect.headers["Location"])

    def test_legacy_project_management_routes_are_disabled_in_favor_of_approval(self):
        self.login_hr_user()
        employee_id = self.create_employee_record(
            employee_code="EMP-PRJ-001",
            full_name="Tio Project",
            warehouse_id=2,
            department="Warehouse Operation",
            position="Leader",
        )

        create_response = self.client.post(
            "/hris/project/add",
            data={
                "employee_id": str(employee_id),
                "project_name": "Rollout SOP Stock Audit",
                "project_code": "PRJ-001",
                "priority": "critical",
                "status": "active",
                "start_date": "2026-08-01",
                "due_date": "2026-08-20",
                "progress_percent": "35",
                "owner_name": "Leader Project",
                "note": "Butuh koordinasi lintas shift",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)
        self.assertIn("/hris/project", create_response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            project_count = db.execute(
                "SELECT COUNT(*) FROM project_records"
            ).fetchone()[0]

        self.assertEqual(project_count, 0)

        legacy_redirect = self.client.get("/hris/project", follow_redirects=False)
        self.assertEqual(legacy_redirect.status_code, 302)
        self.assertIn("/hris/approval", legacy_redirect.headers["Location"])

    def test_admin_can_manage_biometric_records_in_hris_and_sync_attendance(self):
        self.login_hr_user()

        self.client.post(
            "/hris/employee/add",
            data={
                "employee_code": "EMP-BIO-001",
                "full_name": "Dina Biometric",
                "warehouse_id": "2",
                "department": "Warehouse Operation",
                "position": "Checker",
                "employment_status": "active",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            employee = db.execute(
                """
                SELECT id, warehouse_id
                FROM employees
                WHERE employee_code=?
                """,
                ("EMP-BIO-001",),
            ).fetchone()

        self.assertIsNotNone(employee)
        self.assertEqual(employee["warehouse_id"], 2)

        create_response = self.client.post(
            "/hris/biometric/add",
            data={
                "employee_id": str(employee["id"]),
                "location_label": "Gudang Mataram - Depan Kantor",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "12.5",
                "punch_time": "2026-09-01T08:05",
                "punch_type": "check_in",
                "sync_status": "synced",
                "note": "Check in geotag pagi",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric = db.execute(
                """
                SELECT id, employee_id, warehouse_id, device_name, location_label, latitude, longitude, accuracy_m,
                       punch_time, punch_type, sync_status, note, handled_by
                FROM biometric_logs
                WHERE employee_id=?
                """,
                (employee["id"],),
            ).fetchone()
            attendance = db.execute(
                """
                SELECT attendance_date, check_in, check_out, status, note
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee["id"], "2026-09-01"),
            ).fetchone()

        self.assertIsNotNone(biometric)
        self.assertEqual(biometric["warehouse_id"], 2)
        self.assertEqual(biometric["device_name"], "Mobile Geotag")
        self.assertEqual(biometric["location_label"], "Gudang Mataram - Depan Kantor")
        self.assertEqual(biometric["latitude"], -8.58314)
        self.assertEqual(biometric["longitude"], 116.116798)
        self.assertEqual(biometric["accuracy_m"], 12.5)
        self.assertEqual(biometric["punch_type"], "check_in")
        self.assertEqual(biometric["sync_status"], "synced")
        self.assertEqual(biometric["note"], "Check in geotag pagi")
        self.assertIsNotNone(biometric["handled_by"])
        self.assertIsNotNone(attendance)
        self.assertEqual(attendance["attendance_date"], "2026-09-01")
        self.assertEqual(attendance["check_in"], "08:05")
        self.assertIsNone(attendance["check_out"])
        self.assertEqual(attendance["status"], "present")
        self.assertEqual(attendance["note"], "Synced from geotag")

        update_response = self.client.post(
            f"/hris/biometric/update/{biometric['id']}",
            data={
                "employee_id": str(employee["id"]),
                "location_label": "Gudang Mataram - Area Kasir",
                "latitude": "-8.583500",
                "longitude": "116.117222",
                "accuracy_m": "8.0",
                "punch_time": "2026-09-01T08:40",
                "punch_type": "check_in",
                "sync_status": "manual",
                "note": "Disesuaikan setelah audit lokasi",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric_after = db.execute(
                """
                SELECT device_name, location_label, latitude, longitude, accuracy_m, punch_time, sync_status, note, handled_by
                FROM biometric_logs
                WHERE id=?
                """,
                (biometric["id"],),
            ).fetchone()
            attendance_after = db.execute(
                """
                SELECT check_in, status, note
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee["id"], "2026-09-01"),
            ).fetchone()

        self.assertEqual(biometric_after["device_name"], "Mobile Geotag")
        self.assertEqual(biometric_after["location_label"], "Gudang Mataram - Area Kasir")
        self.assertEqual(biometric_after["latitude"], -8.5835)
        self.assertEqual(biometric_after["longitude"], 116.117222)
        self.assertEqual(biometric_after["accuracy_m"], 8.0)
        self.assertEqual(biometric_after["sync_status"], "manual")
        self.assertEqual(biometric_after["note"], "Disesuaikan setelah audit lokasi")
        self.assertIsNotNone(biometric_after["handled_by"])
        self.assertEqual(attendance_after["check_in"], "08:40")
        self.assertEqual(attendance_after["status"], "late")
        self.assertEqual(attendance_after["note"], "Synced from geotag")

        recap_response = self.client.get("/hris/biometric?date_from=2026-09-01&date_to=2026-09-01")
        self.assertEqual(recap_response.status_code, 200)
        recap_html = recap_response.get_data(as_text=True)
        self.assertIn("Rekap Absensi Geotag", recap_html)
        self.assertIn("Gudang Mataram - Area Kasir", recap_html)
        self.assertIn("08:40", recap_html)

        delete_response = self.client.post(
            f"/hris/biometric/delete/{biometric['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric_count = db.execute(
                "SELECT COUNT(*) FROM biometric_logs"
            ).fetchone()[0]
            attendance_count = db.execute(
                """
                SELECT COUNT(*)
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                """,
                (employee["id"], "2026-09-01"),
            ).fetchone()[0]

        self.assertEqual(biometric_count, 0)
        self.assertEqual(attendance_count, 0)

    def test_attendance_portal_submits_photo_geotag_and_syncs_hris_log(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-001",
            full_name="Portal Attendance",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_staff", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_staff", "pass1234")
        today = date_cls.today().isoformat()

        submit_response = self.client.post(
            "/absen/submit",
            data={
                "shift_code": "pagi",
                "location_label": "Gudang Mataram - Pintu Utama",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": f"{today}T07:58",
                "punch_type": "check_in",
                "note": "Masuk shift pagi",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)
        self.assertIn("/absen/", submit_response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            biometric = db.execute(
                """
                SELECT employee_id, warehouse_id, device_name, device_user_id, location_label, punch_type,
                       sync_status, shift_code, shift_label, note, photo_path
                FROM biometric_logs
                WHERE employee_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id,),
            ).fetchone()
            attendance = db.execute(
                """
                SELECT attendance_date, check_in, status, shift_code, shift_label, note
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, today),
            ).fetchone()

        self.assertIsNotNone(biometric)
        self.assertEqual(biometric["warehouse_id"], 1)
        self.assertEqual(biometric["device_name"], "Attendance Photo Portal")
        self.assertEqual(biometric["device_user_id"], "portal_staff")
        self.assertEqual(biometric["location_label"], "Gudang Mataram - Pintu Utama")
        self.assertEqual(biometric["punch_type"], "check_in")
        self.assertEqual(biometric["sync_status"], "synced")
        self.assertEqual(biometric["shift_code"], "pagi")
        self.assertIn("08.00 - 16.00", biometric["shift_label"])
        self.assertIn("Attendance portal check in", biometric["note"])
        self.assertTrue(biometric["photo_path"])
        self.assertTrue(os.path.exists(os.path.join(self.photo_upload_root, biometric["photo_path"])))
        self.assertIsNotNone(attendance)
        self.assertEqual(attendance["attendance_date"], today)
        self.assertEqual(attendance["check_in"], "07:58")
        self.assertEqual(attendance["status"], "present")
        self.assertEqual(attendance["shift_code"], "pagi")
        self.assertIn("08.00 - 16.00", attendance["shift_label"])
        self.assertEqual(attendance["note"], "Synced from geotag")

        portal_page = self.client.get("/absen/")
        self.assertEqual(portal_page.status_code, 200)
        portal_html = portal_page.get_data(as_text=True)
        self.assertIn("Portal Attendance", portal_html)
        self.assertIn("Riwayat Absen Sebelumnya", portal_html)
        self.assertIn("Lihat Log Hari Itu", portal_html)

        hris_page = self.client.get("/hris/biometric", follow_redirects=False)
        self.assertEqual(hris_page.status_code, 302)
        self.assertIn("/absen/", hris_page.headers["Location"])

    def test_attendance_portal_submission_appears_in_notification_center(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-NOTIFY",
            full_name="Portal Attendance Notify",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("owner_activity", "pass1234", "owner")
        self.create_user("portal_notify", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_notify", "pass1234")
        today = date_cls.today().isoformat()

        submit_response = self.client.post(
            "/absen/submit",
            data={
                "shift_code": "pagi",
                "location_label": "Gudang Mataram - Gerbang Timur",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.5",
                "punch_time": f"{today}T07:57",
                "punch_type": "check_in",
                "note": "Masuk kerja",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)

        actor_notifications = self.client.get("/notifications/api?filter=all&limit=10")
        self.assertEqual(actor_notifications.status_code, 200)
        actor_payload = actor_notifications.get_json()
        self.assertTrue(
            any(
                item["category"] == "attendance"
                and item["title"] == "Absensi Check In: Portal Attendance Notify"
                and item["link_url"] == "/absen/"
                for item in actor_payload["items"]
            )
        )

        self.logout()
        self.login("owner_activity", "pass1234")
        owner_notifications = self.client.get("/notifications/api?filter=all&limit=10")
        self.assertEqual(owner_notifications.status_code, 200)
        owner_payload = owner_notifications.get_json()
        self.assertTrue(
            any(
                item["category"] == "attendance"
                and item["title"] == "Absensi Check In: Portal Attendance Notify"
                for item in owner_payload["items"]
            )
        )

    def test_attendance_portal_submission_triggers_role_based_whatsapp_notification(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-WA",
            full_name="Portal Attendance WA",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_staff_wa", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_staff_wa", "pass1234")
        today = date_cls.today().isoformat()

        with patch("routes.attendance_portal.send_role_based_notification") as mocked_role_notify:
            submit_response = self.client.post(
                "/absen/submit",
                data={
                    "shift_code": "pagi",
                    "location_label": "Gudang Mataram - Pintu Barat",
                    "latitude": "-8.583140",
                    "longitude": "116.116798",
                    "accuracy_m": "7.5",
                    "punch_time": f"{today}T07:58",
                    "punch_type": "check_in",
                    "note": "Masuk shift pagi",
                    "photo_data_url": self.build_camera_photo_data_url(),
                },
                follow_redirects=False,
            )

        self.assertEqual(submit_response.status_code, 302)
        mocked_role_notify.assert_called_once()
        self.assertEqual(mocked_role_notify.call_args.args[0], "attendance.activity")
        self.assertEqual(mocked_role_notify.call_args.args[1]["warehouse_id"], 1)
        self.assertEqual(mocked_role_notify.call_args.args[1]["employee_name"], "Portal Attendance WA")
        self.assertEqual(mocked_role_notify.call_args.args[1]["link_url"], "/absen/")

    def test_attendance_portal_requires_detail_when_location_scope_is_other(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-OTHER",
            full_name="Portal Other Scope",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_other", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_other", "pass1234")
        today = date_cls.today().isoformat()

        submit_response = self.client.post(
            "/absen/submit",
            data={
                "shift_code": "pagi",
                "location_scope": "other",
                "location_other_detail": "",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": f"{today}T07:58",
                "punch_type": "check_in",
                "note": "Masuk shift pagi",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)
        self.assertIn("/absen/", submit_response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            biometric_count = db.execute(
                "SELECT COUNT(*) FROM biometric_logs WHERE employee_id=?",
                (employee_id,),
            ).fetchone()[0]

        self.assertEqual(biometric_count, 0)

    def test_attendance_portal_auto_switches_to_check_out_and_locks_after_complete(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-AUTO",
            full_name="Portal Auto",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_auto", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_auto", "pass1234")
        today = date_cls.today().isoformat()

        first_submit = self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Pagi",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": f"{today}T07:55",
                "note": "Masuk shift pagi",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(first_submit.status_code, 302)

        second_submit = self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Sore",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.5",
                "punch_time": f"{today}T17:12",
                "note": "Pulang shift",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(second_submit.status_code, 302)

        third_submit = self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Extra",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "5.0",
                "punch_time": f"{today}T19:15",
                "note": "Tidak boleh masuk lagi",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(third_submit.status_code, 302)

        with self.app.app_context():
            db = get_db()
            logs = db.execute(
                """
                SELECT punch_type, punch_time, shift_code, shift_label
                FROM biometric_logs
                WHERE employee_id=?
                ORDER BY id ASC
                """,
                (employee_id,),
            ).fetchall()
            attendance = db.execute(
                """
                SELECT check_in, check_out, status, shift_code, shift_label
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, today),
            ).fetchone()

        self.assertEqual([row["punch_type"] for row in logs], ["check_in", "check_out"])
        self.assertEqual({row["shift_code"] for row in logs}, {"pagi"})
        self.assertEqual(attendance["check_in"], "07:55")
        self.assertEqual(attendance["check_out"], "17:12")
        self.assertEqual(attendance["status"], "present")
        self.assertEqual(attendance["shift_code"], "pagi")
        self.assertIn("08.00 - 16.00", attendance["shift_label"])

        portal_page = self.client.get("/absen/")
        self.assertEqual(portal_page.status_code, 200)
        portal_html = portal_page.get_data(as_text=True)
        self.assertIn("Sudah Lengkap", portal_html)
        self.assertIn("Absensi Hari Ini Lengkap", portal_html)

    def test_attendance_portal_shows_recent_history_with_daily_logs(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-HISTORY",
            full_name="Portal History",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_history", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_history", "pass1234")

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id, warehouse_id, attendance_date, check_in, check_out, status, shift_code, shift_label, note, updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "2026-03-30",
                    "08:02",
                    "17:05",
                    "present",
                    "pagi",
                    "Shift Pagi | 08.00 - 16.00",
                    "Synced from geotag",
                    "2026-03-30 17:05:00",
                ),
            )
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id, warehouse_id, device_name, device_user_id, punch_time, punch_type, sync_status,
                    location_label, latitude, longitude, accuracy_m, note, shift_code, shift_label
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "Attendance Photo Portal",
                    "portal_history",
                    "2026-03-30 08:02:00",
                    "check_in",
                    "synced",
                    "Gudang Mataram - Pintu Depan",
                    -8.58314,
                    116.116798,
                    7.5,
                    "Attendance portal check in",
                    "pagi",
                    "Shift Pagi | 08.00 - 16.00",
                ),
            )
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id, warehouse_id, device_name, device_user_id, punch_time, punch_type, sync_status,
                    location_label, latitude, longitude, accuracy_m, note, shift_code, shift_label
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    "Attendance Photo Portal",
                    "portal_history",
                    "2026-03-30 17:05:00",
                    "check_out",
                    "synced",
                    "Gudang Mataram - Pintu Depan",
                    -8.58314,
                    116.116798,
                    6.5,
                    "Attendance portal check out",
                    "pagi",
                    "Shift Pagi | 08.00 - 16.00",
                ),
            )
            db.commit()

        response = self.client.get("/absen/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Riwayat Absen Sebelumnya", html)
        self.assertIn("Lihat Log Hari Itu", html)
        self.assertIn("Log ini hanya bisa dikoreksi oleh HR atau Super Admin.", html)
        self.assertNotIn("Perbaiki Log Terakhir", html)
        self.assertIn("2026-03-30", html)
        self.assertIn("17:05", html)

    def test_hr_can_edit_attendance_portal_check_out_and_resync_attendance(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-EDIT-OUT",
            full_name="Portal Edit Out",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("hr_edit_out", "pass1234", "hr", warehouse_id=1, employee_id=employee_id)
        self.login("hr_edit_out", "pass1234")
        today = date_cls.today().isoformat()

        self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Masuk",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": f"{today}T07:55",
                "punch_type": "check_in",
                "note": "Masuk pagi",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Pulang",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.0",
                "punch_time": f"{today}T17:05",
                "punch_type": "check_out",
                "note": "Pulang awalnya",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            checkout_log = db.execute(
                """
                SELECT id
                FROM biometric_logs
                WHERE employee_id=? AND punch_type='check_out'
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id,),
            ).fetchone()

        self.assertIsNotNone(checkout_log)

        response = self.client.post(
            f"/absen/log/{checkout_log['id']}/edit",
            data={
                "punch_type": "check_out",
                "punch_time": f"{today}T17:30",
                "note": "Tadi salah klik jam pulang",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/absen/#riwayat-absen", response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            checkout_after = db.execute(
                """
                SELECT punch_time, sync_status, note
                FROM biometric_logs
                WHERE id=?
                """,
                (checkout_log["id"],),
            ).fetchone()
            attendance_after = db.execute(
                """
                SELECT check_in, check_out, status, note
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, today),
            ).fetchone()

        self.assertEqual(checkout_after["punch_time"][11:16], "17:30")
        self.assertEqual(checkout_after["sync_status"], "manual")
        self.assertIn("Koreksi log portal:", checkout_after["note"])
        self.assertEqual(attendance_after["check_in"], "07:55")
        self.assertEqual(attendance_after["check_out"], "17:30")
        self.assertEqual(attendance_after["status"], "present")
        self.assertEqual(attendance_after["note"], "Synced from geotag")

    def test_hr_can_change_wrong_check_out_to_break_start(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-FIX-BREAK",
            full_name="Portal Fix Break",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("hr_fix_break", "pass1234", "hr", warehouse_id=1, employee_id=employee_id)
        self.login("hr_fix_break", "pass1234")
        today = date_cls.today().isoformat()

        self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Masuk",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": f"{today}T07:55",
                "punch_type": "check_in",
                "note": "Masuk pagi",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Istirahat",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.0",
                "punch_time": f"{today}T12:00",
                "punch_type": "check_out",
                "note": "Salah klik harusnya break",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            checkout_log = db.execute(
                """
                SELECT id
                FROM biometric_logs
                WHERE employee_id=? AND punch_type='check_out'
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id,),
            ).fetchone()

        self.assertIsNotNone(checkout_log)

        response = self.client.post(
            f"/absen/log/{checkout_log['id']}/edit",
            data={
                "punch_type": "break_start",
                "punch_time": f"{today}T12:00",
                "note": "Harusnya mulai istirahat",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/absen/#riwayat-absen", response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            corrected_log = db.execute(
                """
                SELECT punch_type, punch_time, sync_status, note
                FROM biometric_logs
                WHERE id=?
                """,
                (checkout_log["id"],),
            ).fetchone()
            attendance_after = db.execute(
                """
                SELECT check_in, check_out, status
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, today),
            ).fetchone()

        self.assertEqual(corrected_log["punch_type"], "break_start")
        self.assertEqual(corrected_log["punch_time"][11:16], "12:00")
        self.assertEqual(corrected_log["sync_status"], "manual")
        self.assertIn("Koreksi log portal:", corrected_log["note"])
        self.assertEqual(attendance_after["check_in"], "07:55")
        self.assertIsNone(attendance_after["check_out"])
        self.assertEqual(attendance_after["status"], "present")

        portal_page = self.client.get("/absen/")
        self.assertEqual(portal_page.status_code, 200)
        portal_html = portal_page.get_data(as_text=True)
        self.assertIn("Break Finish", portal_html)
        self.assertNotIn("Absensi Hari Ini Lengkap", portal_html)

    def test_staff_cannot_edit_attendance_portal_punch_log(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-NO-EDIT",
            full_name="Portal No Edit",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_no_edit", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_no_edit", "pass1234")
        today = date_cls.today().isoformat()

        self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Masuk",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": f"{today}T07:55",
                "punch_type": "check_in",
                "note": "Masuk pagi",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Pulang",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.0",
                "punch_time": f"{today}T17:05",
                "punch_type": "check_out",
                "note": "Pulang awalnya",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            checkout_log = db.execute(
                """
                SELECT id
                FROM biometric_logs
                WHERE employee_id=? AND punch_type='check_out'
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id,),
            ).fetchone()

        self.assertIsNotNone(checkout_log)

        response = self.client.post(
            f"/absen/log/{checkout_log['id']}/edit",
            data={
                "punch_type": "break_start",
                "punch_time": f"{today}T12:00",
                "note": "Tidak boleh bisa diubah staff",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/absen/#riwayat-absen", response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            corrected_log = db.execute(
                """
                SELECT punch_type, punch_time, sync_status
                FROM biometric_logs
                WHERE id=?
                """,
                (checkout_log["id"],),
            ).fetchone()

        self.assertEqual(corrected_log["punch_type"], "check_out")
        self.assertEqual(corrected_log["punch_time"][11:16], "17:05")
        self.assertEqual(corrected_log["sync_status"], "synced")

        portal_page = self.client.get("/absen/")
        self.assertEqual(portal_page.status_code, 200)
        portal_html = portal_page.get_data(as_text=True)
        self.assertIn("Log ini hanya bisa dikoreksi oleh HR atau Super Admin.", portal_html)
        self.assertNotIn("Perbaiki Log Terakhir", portal_html)

    def test_attendance_portal_uses_mega_shift_schedule_labels(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-MEGA",
            full_name="Portal Mega",
            warehouse_id=2,
            position="Warehouse Staff",
        )
        self.create_user("portal_mega", "pass1234", "staff", warehouse_id=2, employee_id=employee_id)
        self.login("portal_mega", "pass1234")

        response = self.client.get("/absen/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Shift Pagi | 09.00 - 17.00", html)
        self.assertIn("Shift Siang | 13.00 - 21.00", html)

    def test_attendance_portal_uses_special_shift_for_bu_ika(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-BUIKA",
            full_name="Bu Ika Suryani",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_bu_ika", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_bu_ika", "pass1234")
        today = date_cls.today().isoformat()

        response = self.client.get("/absen/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Shift Khusus Bu Ika | 11.30 - 21.00", html)
        self.assertIn("Jam khusus Bu Ika: 11.30 - 21.00.", html)
        self.assertNotIn("Shift Pagi | 08.00 - 16.00", html)

        submit_response = self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Area Admin",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.0",
                "punch_time": f"{today}T11:40",
                "punch_type": "check_in",
                "note": "Masuk shift khusus Bu Ika",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric = db.execute(
                """
                SELECT punch_time, shift_code, shift_label
                FROM biometric_logs
                WHERE employee_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id,),
            ).fetchone()
            attendance = db.execute(
                """
                SELECT check_in, status, shift_code, shift_label
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, today),
            ).fetchone()

        self.assertIsNotNone(biometric)
        self.assertEqual(biometric["shift_code"], "bu_ika")
        self.assertIn("11.30 - 21.00", biometric["shift_label"])
        self.assertEqual(biometric["punch_time"][11:16], "11:40")
        self.assertIsNotNone(attendance)
        self.assertEqual(attendance["check_in"], "11:40")
        self.assertEqual(attendance["status"], "present")
        self.assertEqual(attendance["shift_code"], "bu_ika")
        self.assertIn("11.30 - 21.00", attendance["shift_label"])

    def test_attendance_portal_marks_bu_ika_special_shift_late_after_eleven_minutes(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-BUIKA-LATE",
            full_name="Bu Ika Lestari",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_bu_ika_late", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_bu_ika_late", "pass1234")
        today = date_cls.today().isoformat()

        submit_response = self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Area Kasir",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.4",
                "punch_time": f"{today}T11:41",
                "punch_type": "check_in",
                "note": "Masuk lewat batas toleransi Bu Ika",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance = db.execute(
                """
                SELECT check_in, status, shift_code, shift_label
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, today),
            ).fetchone()

        self.assertIsNotNone(attendance)
        self.assertEqual(attendance["check_in"], "11:41")
        self.assertEqual(attendance["status"], "late")
        self.assertEqual(attendance["shift_code"], "bu_ika")
        self.assertIn("11.30 - 21.00", attendance["shift_label"])

    def test_attendance_portal_hr_can_choose_mataram_or_mega_shift_profile(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-HR-PROFILE",
            full_name="Portal HR Profile",
            warehouse_id=1,
            position="HR Staff",
        )
        self.create_user("portal_hr_profile", "pass1234", "hr", employee_id=employee_id)
        self.login("portal_hr_profile", "pass1234")
        today = date_cls.today().isoformat()

        response = self.client.get("/absen/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="shift_profile_key"', html)
        self.assertIn("Profil Jam Gudang", html)
        self.assertIn("Gudang Mataram", html)
        self.assertIn("Gudang Mega", html)

        submit_response = self.client.post(
            "/absen/submit",
            data={
                "shift_profile_key": "mega",
                "shift_code": "pagi",
                "location_label": "Gudang Mataram - Area HR",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": f"{today}T08:55",
                "punch_type": "check_in",
                "note": "HR pilih jam Mega",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            biometric = db.execute(
                """
                SELECT shift_code, shift_label
                FROM biometric_logs
                WHERE employee_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id,),
            ).fetchone()
            attendance = db.execute(
                """
                SELECT shift_code, shift_label
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, today),
            ).fetchone()

        self.assertIsNotNone(biometric)
        self.assertEqual(biometric["shift_code"], "pagi")
        self.assertIn("09.00 - 17.00", biometric["shift_label"])
        self.assertIsNotNone(attendance)
        self.assertEqual(attendance["shift_code"], "pagi")
        self.assertIn("09.00 - 17.00", attendance["shift_label"])

    def test_attendance_portal_supports_break_flow_before_check_out(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-BREAK",
            full_name="Portal Break",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_break", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_break", "pass1234")
        today = date_cls.today().isoformat()

        self.client.post(
            "/absen/submit",
            data={
                "punch_type": "check_in",
                "location_label": "Gudang Mataram - Masuk",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": f"{today}T07:50",
                "note": "Mulai kerja",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )

        portal_page = self.client.get("/absen/")
        portal_html = portal_page.get_data(as_text=True)
        self.assertIn("Break Start", portal_html)
        self.assertIn("Check Out", portal_html)

        self.client.post(
            "/absen/submit",
            data={
                "punch_type": "break_start",
                "location_label": "Gudang Mataram - Istirahat",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.5",
                "punch_time": f"{today}T12:00",
                "note": "Mulai istirahat",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )

        break_page = self.client.get("/absen/")
        break_html = break_page.get_data(as_text=True)
        self.assertIn("Break Finish", break_html)
        self.assertIn("Check Out", break_html)

        self.client.post(
            "/absen/submit",
            data={
                "punch_type": "break_finish",
                "location_label": "Gudang Mataram - Kembali",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.2",
                "punch_time": f"{today}T12:30",
                "note": "Selesai istirahat",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )

        self.client.post(
            "/absen/submit",
            data={
                "punch_type": "check_out",
                "location_label": "Gudang Mataram - Pulang",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "5.4",
                "punch_time": f"{today}T17:10",
                "note": "Selesai kerja",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            logs = db.execute(
                """
                SELECT punch_type
                FROM biometric_logs
                WHERE employee_id=?
                ORDER BY id ASC
                """,
                (employee_id,),
            ).fetchall()
            attendance = db.execute(
                """
                SELECT check_in, check_out, status
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, today),
            ).fetchone()

        self.assertEqual(
            [row["punch_type"] for row in logs],
            ["check_in", "break_start", "break_finish", "check_out"],
        )
        self.assertEqual(attendance["check_in"], "07:50")
        self.assertEqual(attendance["check_out"], "17:10")
        self.assertEqual(attendance["status"], "present")

    def test_attendance_portal_treats_exactly_ten_minutes_after_shift_start_as_present(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-10MIN",
            full_name="Portal Ten Minute",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_ten", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_ten", "pass1234")
        today = date_cls.today().isoformat()

        submit_response = self.client.post(
            "/absen/submit",
            data={
                "shift_code": "pagi",
                "location_label": "Gudang Mataram - Toleransi",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.0",
                "punch_time": f"{today}T08:10",
                "punch_type": "check_in",
                "note": "Masuk di batas toleransi",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance = db.execute(
                """
                SELECT check_in, status, shift_label
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, today),
            ).fetchone()

        self.assertEqual(attendance["check_in"], "08:10")
        self.assertEqual(attendance["status"], "present")
        self.assertIn("08.00 - 16.00", attendance["shift_label"])

    def test_attendance_portal_marks_mega_morning_shift_late_after_eleven_minutes(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-MEGA-LATE",
            full_name="Portal Mega Late",
            warehouse_id=2,
            position="Warehouse Staff",
        )
        self.create_user("portal_mega_late", "pass1234", "staff", warehouse_id=2, employee_id=employee_id)
        self.login("portal_mega_late", "pass1234")
        today = date_cls.today().isoformat()

        submit_response = self.client.post(
            "/absen/submit",
            data={
                "shift_code": "pagi",
                "location_label": "Gudang Mega - Telat",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.0",
                "punch_time": f"{today}T09:11",
                "punch_type": "check_in",
                "note": "Masuk lebih dari 10 menit",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            attendance = db.execute(
                """
                SELECT check_in, status, shift_label
                FROM attendance_records
                WHERE employee_id=? AND attendance_date=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id, today),
            ).fetchone()

        self.assertEqual(attendance["check_in"], "09:11")
        self.assertEqual(attendance["status"], "late")
        self.assertIn("09.00 - 17.00", attendance["shift_label"])

    def test_biometric_recap_shows_baru_mulai_for_open_break(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-OPEN-BREAK",
            full_name="Portal Open Break",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_open_break", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_open_break", "pass1234")
        current_stamp = datetime.now().replace(second=0, microsecond=0)
        today = current_stamp.date().isoformat()
        check_in_stamp = (current_stamp - timedelta(minutes=20)).isoformat(timespec="minutes")
        break_start_stamp = (current_stamp - timedelta(minutes=15)).isoformat(timespec="minutes")

        self.client.post(
            "/absen/submit",
            data={
                "punch_type": "check_in",
                "shift_code": "pagi",
                "location_label": "Gudang Mataram - Masuk",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": check_in_stamp,
                "note": "Mulai kerja",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.client.post(
            "/absen/submit",
            data={
                "punch_type": "break_start",
                "location_label": "Gudang Mataram - Istirahat",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.5",
                "punch_time": break_start_stamp,
                "note": "Mulai istirahat",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )

        self.create_user("hr_break_view", "pass1234", "hr")
        self.login("hr_break_view", "pass1234")
        recap_response = self.client.get(f"/hris/biometric?date_from={today}&date_to={today}")
        self.assertEqual(recap_response.status_code, 200)
        recap_html = recap_response.get_data(as_text=True)
        self.assertIn("Status Istirahat", recap_html)
        self.assertIn("Durasi Istirahat", recap_html)
        self.assertIn("Present", recap_html)
        self.assertIn("Baru Mulai", recap_html)
        self.assertIn("15 mnt", recap_html)
        self.assertIn("data-break-timer", recap_html)
        self.assertIn("Timer aktif", recap_html)

    def test_workspace_shell_shows_break_countdown_when_break_is_open(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-SHELL-BREAK",
            full_name="Portal Shell Break",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_shell_break", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_shell_break", "pass1234")
        current_stamp = datetime.now().replace(second=0, microsecond=0)
        check_in_stamp = (current_stamp - timedelta(minutes=18)).isoformat(timespec="minutes")
        break_start_stamp = (current_stamp - timedelta(minutes=12)).isoformat(timespec="minutes")

        self.client.post(
            "/absen/submit",
            data={
                "punch_type": "check_in",
                "shift_code": "pagi",
                "location_label": "Gudang Mataram - Masuk",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": check_in_stamp,
                "note": "Mulai kerja",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.client.post(
            "/absen/submit",
            data={
                "punch_type": "break_start",
                "location_label": "Gudang Mataram - Istirahat",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.5",
                "punch_time": break_start_stamp,
                "note": "Mulai istirahat",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )

        response = self.client.get("/workspace/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("data-shell-break-timer", html)
        self.assertIn('data-break-limit-seconds="3600"', html)
        self.assertIn("Istirahat Aktif", html)
        self.assertIn("Sisa istirahat", html)

    def test_biometric_recap_shows_selesai_for_finished_break(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-FINISH-BREAK",
            full_name="Portal Finished Break",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_finish_break", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_finish_break", "pass1234")
        today = date_cls.today().isoformat()

        self.client.post(
            "/absen/submit",
            data={
                "punch_type": "check_in",
                "shift_code": "pagi",
                "location_label": "Gudang Mataram - Masuk",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": f"{today}T07:55",
                "note": "Mulai kerja",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.client.post(
            "/absen/submit",
            data={
                "punch_type": "break_start",
                "location_label": "Gudang Mataram - Istirahat",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.5",
                "punch_time": f"{today}T12:00",
                "note": "Mulai istirahat",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.client.post(
            "/absen/submit",
            data={
                "punch_type": "break_finish",
                "location_label": "Gudang Mataram - Kembali",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.0",
                "punch_time": f"{today}T12:25",
                "note": "Selesai istirahat",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )

        self.create_user("hr_finish_break_view", "pass1234", "hr")
        self.login("hr_finish_break_view", "pass1234")
        recap_response = self.client.get(f"/hris/biometric?date_from={today}&date_to={today}")
        self.assertEqual(recap_response.status_code, 200)
        recap_html = recap_response.get_data(as_text=True)
        self.assertIn("Status Istirahat", recap_html)
        self.assertIn("Selesai", recap_html)
        self.assertIn("25 mnt", recap_html)
        self.assertIn("Total istirahat", recap_html)

    def test_biometric_recap_only_shows_days_with_actual_attendance(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-RECAP-ONLY",
            full_name="Portal Recap Only Attendance",
            warehouse_id=1,
            position="Warehouse Staff",
        )

        orphan_date = "2026-04-02"
        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO biometric_logs(
                    employee_id,
                    warehouse_id,
                    punch_time,
                    punch_type,
                    latitude,
                    longitude,
                    accuracy_m,
                    location_label,
                    sync_status,
                    device_name,
                    note
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    f"{orphan_date}T12:15",
                    "break_start",
                    -8.583140,
                    116.116798,
                    6.0,
                    "Gudang Mataram - Istirahat",
                    "synced",
                    "Mobile Geotag",
                    "Break tanpa check in",
                ),
            )
            db.execute(
                """
                INSERT INTO attendance_records(
                    employee_id,
                    warehouse_id,
                    attendance_date,
                    check_in,
                    check_out,
                    status,
                    note,
                    updated_at
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id,
                    1,
                    orphan_date,
                    None,
                    None,
                    "absent",
                    "Synced from geotag",
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
            db.commit()

        self.create_user("hr_recap_filter", "pass1234", "hr")
        self.login("hr_recap_filter", "pass1234")
        recap_response = self.client.get(f"/hris/biometric?date_from={orphan_date}&date_to={orphan_date}")
        self.assertEqual(recap_response.status_code, 200)
        recap_html = recap_response.get_data(as_text=True)
        self.assertNotIn("Portal Recap Only Attendance", recap_html)
        self.assertIn("Belum ada rekap geotag pada filter yang dipilih.", recap_html)

    def test_attendance_portal_rejects_punch_time_that_moves_backwards(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-ABS-BACKWARD",
            full_name="Portal Backward Time",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_backward", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_backward", "pass1234")
        today = date_cls.today().isoformat()

        first_submit = self.client.post(
            "/absen/submit",
            data={
                "punch_type": "check_in",
                "shift_code": "pagi",
                "location_label": "Gudang Mataram - Masuk",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "7.5",
                "punch_time": f"{today}T08:30",
                "note": "Masuk kerja",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(first_submit.status_code, 302)

        second_submit = self.client.post(
            "/absen/submit",
            data={
                "punch_type": "break_start",
                "location_label": "Gudang Mataram - Istirahat",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "6.5",
                "punch_time": f"{today}T08:10",
                "note": "Jam mundur",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(second_submit.status_code, 302)

        with self.app.app_context():
            db = get_db()
            logs = db.execute(
                """
                SELECT punch_type, punch_time
                FROM biometric_logs
                WHERE employee_id=?
                ORDER BY id ASC
                """,
                (employee_id,),
            ).fetchall()

        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["punch_type"], "check_in")
        self.assertEqual(logs[0]["punch_time"][11:16], "08:30")

    def test_leave_portal_submits_pending_request_without_status_field(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-LVE-001",
            full_name="Portal Leave",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_leave", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_leave", "pass1234")

        submit_response = self.client.post(
            "/libur/submit",
            data={
                "leave_type": "sick",
                "start_date": "2026-09-03",
                "end_date": "2026-09-04",
                "reason": "Butuh istirahat dan kontrol kesehatan",
                "note": "Sudah koordinasi dengan leader",
            },
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)
        self.assertIn("/libur/", submit_response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            leave_request = db.execute(
                """
                SELECT employee_id, leave_type, total_days, status, reason, note, handled_by
                FROM leave_requests
                WHERE employee_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id,),
            ).fetchone()

        self.assertIsNotNone(leave_request)
        self.assertEqual(leave_request["employee_id"], employee_id)
        self.assertEqual(leave_request["leave_type"], "sick")
        self.assertEqual(leave_request["total_days"], 2)
        self.assertEqual(leave_request["status"], "pending")
        self.assertEqual(leave_request["reason"], "Butuh istirahat dan kontrol kesehatan")
        self.assertEqual(leave_request["note"], "Sudah koordinasi dengan leader")
        self.assertIsNone(leave_request["handled_by"])

        hris_leave = self.client.get("/hris/leave", follow_redirects=False)
        self.assertEqual(hris_leave.status_code, 302)
        self.assertIn("/libur/", hris_leave.headers["Location"])

    def test_leave_portal_submission_appears_in_hris_dashboard_alerts(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-LVE-ALERT",
            full_name="Portal Leave Alert",
            warehouse_id=1,
            position="Admin Gudang",
        )
        self.create_user("portal_leave_alert", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_leave_alert", "pass1234")

        self.client.post(
            "/libur/submit",
            data={
                "leave_type": "sick",
                "start_date": "2026-09-10",
                "end_date": "2026-09-10",
                "reason": "Demam dan perlu istirahat",
                "note": "Sudah kabari leader shift pagi",
            },
            follow_redirects=False,
        )

        self.logout()
        self.login_hr_user("hr_dashboard_leave", "pass1234")
        response = self.client.get("/hris/?warehouse=1&schedule_start=2026-09-10")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Notifikasi Pengajuan Libur", html)
        self.assertIn("Portal Leave Alert", html)
        self.assertIn("Demam dan perlu istirahat", html)
        self.assertIn("Sakit", html)

    def test_leave_portal_shows_monthly_history_log(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-LVE-HISTORY",
            full_name="Portal Leave History",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_leave_history", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)

        current_month = date_cls.today().replace(day=1)
        if current_month.month == 12:
            next_month = date_cls(current_month.year + 1, 1, 1)
        else:
            next_month = date_cls(current_month.year, current_month.month + 1, 1)

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO leave_requests(
                    employee_id,
                    warehouse_id,
                    leave_type,
                    start_date,
                    end_date,
                    total_days,
                    status,
                    reason,
                    note,
                    updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    employee_id,
                    1,
                    "annual",
                    current_month.replace(day=5).isoformat(),
                    current_month.replace(day=6).isoformat(),
                    2,
                    "approved",
                    "Libur bulan berjalan",
                    "Catatan bulan berjalan",
                ),
            )
            db.execute(
                """
                INSERT INTO leave_requests(
                    employee_id,
                    warehouse_id,
                    leave_type,
                    start_date,
                    end_date,
                    total_days,
                    status,
                    reason,
                    note,
                    updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    employee_id,
                    1,
                    "sick",
                    next_month.replace(day=3).isoformat(),
                    next_month.replace(day=3).isoformat(),
                    1,
                    "pending",
                    "Libur bulan depan",
                    "Catatan bulan depan",
                ),
            )
            db.commit()

        self.login("portal_leave_history", "pass1234")
        response = self.client.get("/libur/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Log Pengajuan", html)
        self.assertIn('type="month" name="month"', html)
        self.assertIn(f'value="{current_month.strftime("%Y-%m")}"', html)
        self.assertIn("Libur bulan berjalan", html)
        self.assertNotIn("Libur bulan depan", html)

    def test_leave_approval_notifies_requester_in_notification_center(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-LVE-NOTIFY",
            full_name="Portal Leave Notify",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("portal_leave_notify", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)
        self.login("portal_leave_notify", "pass1234")

        self.client.post(
            "/libur/submit",
            data={
                "leave_type": "annual",
                "start_date": "2026-09-12",
                "end_date": "2026-09-13",
                "reason": "Keperluan keluarga",
                "note": "Mohon approve",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            leave_request = db.execute(
                """
                SELECT id
                FROM leave_requests
                WHERE employee_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (employee_id,),
            ).fetchone()

        self.logout()
        self.login_hr_user("hr_leave_notify", "pass1234")
        update_response = self.client.post(
            f"/hris/leave/update/{leave_request['id']}",
            data={
                "employee_id": str(employee_id),
                "leave_type": "annual",
                "start_date": "2026-09-12",
                "end_date": "2026-09-13",
                "status": "approved",
                "reason": "Keperluan keluarga",
                "note": "Disetujui",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            requester_id = self.get_user_id("portal_leave_notify")
            web_notification = db.execute(
                """
                SELECT category, title, message, link_url
                FROM web_notifications
                WHERE user_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (requester_id,),
            ).fetchone()

        self.assertIsNotNone(web_notification)
        self.assertEqual(web_notification["category"], "leave")
        self.assertEqual(web_notification["link_url"], "/libur/")
        self.assertIn("disetujui", web_notification["title"].lower())
        self.assertIn("2026-09-12 s/d 2026-09-13", web_notification["message"])

    def test_hr_dashboard_reminders_are_visible_and_manageable_only_for_hr(self):
        self.login_hr_user("hr_dashboard_note", "pass1234")

        add_response = self.client.post(
            "/hris/dashboard/reminder/add",
            data={
                "reminder_date": "2026-09-11",
                "warehouse_id": "1",
                "title": "Follow up libur shift siang",
                "note": "Pastikan approval libur dan backup jadwal sore sudah beres.",
                "return_to": "/hris/?warehouse=1&schedule_start=2026-09-11",
            },
            follow_redirects=False,
        )
        self.assertEqual(add_response.status_code, 302)
        self.assertIn("/hris/?warehouse=1&schedule_start=2026-09-11", add_response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            reminder = db.execute(
                """
                SELECT id, warehouse_id, reminder_date, title, note, status
                FROM dashboard_reminders
                WHERE title=?
                """,
                ("Follow up libur shift siang",),
            ).fetchone()

        self.assertIsNotNone(reminder)
        self.assertEqual(reminder["warehouse_id"], 1)
        self.assertEqual(reminder["reminder_date"], "2026-09-11")
        self.assertEqual(reminder["status"], "open")

        dashboard_response = self.client.get("/hris/?warehouse=1&schedule_start=2026-09-11")
        self.assertEqual(dashboard_response.status_code, 200)
        dashboard_html = dashboard_response.get_data(as_text=True)
        self.assertIn("Pengingat Harian", dashboard_html)
        self.assertIn("Follow up libur shift siang", dashboard_html)

        toggle_response = self.client.post(
            f"/hris/dashboard/reminder/toggle/{reminder['id']}",
            data={
                "status": "done",
                "return_to": "/hris/?warehouse=1&schedule_start=2026-09-11",
            },
            follow_redirects=False,
        )
        self.assertEqual(toggle_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            updated = db.execute(
                "SELECT status FROM dashboard_reminders WHERE id=?",
                (reminder["id"],),
            ).fetchone()
        self.assertEqual(updated["status"], "done")

        self.logout()
        self.create_user("staff_dashboard_note", "pass1234", "staff", warehouse_id=1)
        self.login("staff_dashboard_note", "pass1234")

        staff_response = self.client.get("/hris/?warehouse=1&schedule_start=2026-09-11")
        self.assertEqual(staff_response.status_code, 200)
        staff_html = staff_response.get_data(as_text=True)
        self.assertNotIn("Pengingat Harian", staff_html)
        self.assertNotIn("Follow up libur shift siang", staff_html)

        denied_response = self.client.post(
            "/hris/dashboard/reminder/add",
            data={
                "reminder_date": "2026-09-11",
                "warehouse_id": "1",
                "title": "Reminder staff tidak boleh simpan",
                "return_to": "/hris/?warehouse=1&schedule_start=2026-09-11",
            },
            follow_redirects=False,
        )
        self.assertEqual(denied_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            denied_note = db.execute(
                "SELECT id FROM dashboard_reminders WHERE title=?",
                ("Reminder staff tidak boleh simpan",),
            ).fetchone()
        self.assertIsNone(denied_note)

        self.logout()
        self.create_user("super_dashboard_note", "pass1234", "super_admin")
        self.login("super_dashboard_note", "pass1234")

        super_response = self.client.get("/hris/?warehouse=1&schedule_start=2026-09-11")
        self.assertEqual(super_response.status_code, 200)
        super_html = super_response.get_data(as_text=True)
        self.assertNotIn("Pengingat Harian", super_html)

        super_denied = self.client.post(
            "/hris/dashboard/reminder/add",
            data={
                "reminder_date": "2026-09-11",
                "warehouse_id": "1",
                "title": "Reminder super admin tidak boleh simpan",
                "return_to": "/hris/?warehouse=1&schedule_start=2026-09-11",
            },
            follow_redirects=False,
        )
        self.assertEqual(super_denied.status_code, 302)

        with self.app.app_context():
            db = get_db()
            denied_super_note = db.execute(
                "SELECT id FROM dashboard_reminders WHERE title=?",
                ("Reminder super admin tidak boleh simpan",),
            ).fetchone()
        self.assertIsNone(denied_super_note)

    def test_daily_report_portal_is_available_to_all_users_and_submits_to_hris_report(self):
        today = date_cls.today().isoformat()
        self.create_user("ops_daily", "pass1234", "staff", warehouse_id=1)
        self.login("ops_daily", "pass1234")

        page_response = self.client.get("/laporan-harian/")
        self.assertEqual(page_response.status_code, 200)
        page_html = page_response.get_data(as_text=True)
        self.assertIn("Form Report Harian &amp; Live", page_html)
        self.assertIn('name="attachment"', page_html)

        submit_response = self.client.post(
            "/laporan-harian/submit",
            data={
                "report_type": "live",
                "report_date": today,
                "title": "Live promo toko Mega",
                "summary": "Promo berjalan normal dan traffic naik saat sesi kedua.",
                "blocker_note": "Banner depan sempat terlambat dipasang.",
                "follow_up_note": "Besok perlu cek ulang materi promo pagi.",
                "attachment": (BytesIO(b"%PDF-1.4 bukti live report"), "bukti-live.pdf"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(submit_response.status_code, 302)
        self.assertIn("/laporan-harian/", submit_response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            report = db.execute(
                """
                SELECT report_type, report_date, title, summary, blocker_note, follow_up_note, status,
                       warehouse_id, attachment_name, attachment_path, attachment_mime, attachment_size
                FROM daily_live_reports
                WHERE title=?
                """,
                ("Live promo toko Mega",),
            ).fetchone()

        self.assertIsNotNone(report)
        self.assertEqual(report["report_type"], "live")
        self.assertEqual(report["report_date"], today)
        self.assertEqual(report["status"], "submitted")
        self.assertEqual(report["warehouse_id"], 1)
        self.assertEqual(report["attachment_name"], "bukti-live.pdf")
        self.assertTrue(report["attachment_path"])
        self.assertEqual(report["attachment_mime"], "application/pdf")
        self.assertGreater(report["attachment_size"], 0)
        self.assertTrue(os.path.exists(os.path.join(self.daily_report_upload_root, report["attachment_path"])))

        portal_after_submit = self.client.get("/laporan-harian/")
        self.assertEqual(portal_after_submit.status_code, 200)
        portal_after_html = portal_after_submit.get_data(as_text=True)
        self.assertIn("bukti-live.pdf", portal_after_html)
        self.assertIn("/static/test-daily-reports/", portal_after_html)

        self.logout()
        self.login_hr_user("hr_report_view", "pass1234")
        hris_report_response = self.client.get("/hris/report")
        self.assertEqual(hris_report_response.status_code, 200)
        hris_html = hris_report_response.get_data(as_text=True)
        self.assertIn("Daily & Live Report Log", hris_html)
        self.assertIn("Log Report Harian", hris_html)
        self.assertIn("Log Live Report", hris_html)
        self.assertIn(f'name="daily_date_from" value="{today}"', hris_html)
        self.assertIn(f'name="daily_date_to" value="{today}"', hris_html)
        self.assertIn("Belum ada report harian pada filter yang dipilih.", hris_html)
        self.assertIn("Live promo toko Mega", hris_html)
        self.assertIn("bukti-live.pdf", hris_html)

    def test_daily_report_submit_triggers_role_based_whatsapp_notification(self):
        today = date_cls.today().isoformat()
        self.create_user("ops_daily_wa", "pass1234", "staff", warehouse_id=1)
        self.login("ops_daily_wa", "pass1234")

        with patch("routes.daily_report_portal.send_role_based_notification") as mocked_role_notify:
            submit_response = self.client.post(
                "/laporan-harian/submit",
                data={
                    "report_type": "live",
                    "report_date": today,
                    "title": "Live test whatsapp",
                    "summary": "Traffic aman.",
                    "blocker_note": "",
                    "follow_up_note": "",
                    "attachment": (BytesIO(b"%PDF-1.4 bukti live report"), "bukti-live.pdf"),
                },
                content_type="multipart/form-data",
                follow_redirects=False,
            )

        self.assertEqual(submit_response.status_code, 302)
        mocked_role_notify.assert_called_once()
        self.assertEqual(mocked_role_notify.call_args.args[0], "report.live_submitted")
        self.assertEqual(mocked_role_notify.call_args.args[1]["warehouse_id"], 1)
        self.assertEqual(mocked_role_notify.call_args.args[1]["title"], "Live test whatsapp")
        self.assertEqual(mocked_role_notify.call_args.args[1]["link_url"], "/hris/report")

    def test_hris_report_marks_live_report_time_against_scheduled_live_slot(self):
        employee_id = self.create_employee_record(
            employee_code="EMP-LIVE-MATCH",
            full_name="Live Match Staff",
            warehouse_id=1,
            position="Marketplace Host",
        )
        self.create_user("live_match_staff", "pass1234", "staff", warehouse_id=1, employee_id=employee_id)

        with self.app.app_context():
            db = get_db()
            staff_user = db.execute(
                "SELECT id FROM users WHERE username=?",
                ("live_match_staff",),
            ).fetchone()
            db.execute(
                """
                INSERT INTO schedule_live_entries(
                    warehouse_id,
                    schedule_date,
                    slot_key,
                    employee_id,
                    channel_label,
                    note,
                    updated_by
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (
                    1,
                    "2026-09-06",
                    "13:00",
                    employee_id,
                    "Shopee Mega + IG",
                    "Host promo siang",
                    1,
                ),
            )
            db.execute(
                """
                INSERT INTO daily_live_reports(
                    user_id,
                    employee_id,
                    warehouse_id,
                    report_type,
                    report_date,
                    title,
                    summary,
                    blocker_note,
                    follow_up_note,
                    status,
                    hr_note,
                    handled_by,
                    handled_at,
                    created_at,
                    updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    staff_user["id"],
                    employee_id,
                    1,
                    "live",
                    "2026-09-06",
                    "Live cocok jadwal",
                    "Live siang berjalan sesuai rundown promo.",
                    None,
                    None,
                    "submitted",
                    None,
                    None,
                    None,
                    "2026-09-06 13:15:00",
                    "2026-09-06 13:15:00",
                ),
            )
            db.commit()

        self.login_hr_user("hr_live_report_match", "pass1234")
        response = self.client.get("/hris/report?daily_type=live&daily_date_from=2026-09-06&daily_date_to=2026-09-06")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Live cocok jadwal", html)
        self.assertIn("Jam Live Terkirim", html)
        self.assertIn("Kecocokan Jadwal Live", html)
        self.assertIn("Sesuai Jadwal", html)
        self.assertIn("13:15", html)
        self.assertIn("13:00 (Shopee Mega + IG)", html)

    def test_only_hr_or_super_admin_can_update_daily_report_status(self):
        self.create_user("staff_report_owner", "pass1234", "staff", warehouse_id=1)
        self.login("staff_report_owner", "pass1234")
        self.client.post(
            "/laporan-harian/submit",
            data={
                "report_type": "daily",
                "report_date": "2026-09-06",
                "title": "Closing stok sore",
                "summary": "Semua rak utama sudah dirapikan dan stok display dicek.",
            },
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            report = db.execute(
                "SELECT id, status FROM daily_live_reports WHERE title=?",
                ("Closing stok sore",),
            ).fetchone()

        denied_response = self.client.post(
            f"/hris/report/daily-live/update/{report['id']}",
            data={"status": "reviewed", "hr_note": "Sudah dicek"},
            follow_redirects=False,
        )
        self.assertEqual(denied_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            unchanged = db.execute(
                "SELECT status, hr_note FROM daily_live_reports WHERE id=?",
                (report["id"],),
            ).fetchone()

        self.assertEqual(unchanged["status"], "submitted")
        self.assertIsNone(unchanged["hr_note"])

        self.logout()
        self.login_hr_user("hr_report_update", "pass1234")
        approve_response = self.client.post(
            f"/hris/report/daily-live/update/{report['id']}",
            data={"status": "follow_up", "hr_note": "Lengkapi detail manpower shift berikutnya."},
            follow_redirects=False,
        )
        self.assertEqual(approve_response.status_code, 302)
        self.assertIn("/hris/report", approve_response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            updated = db.execute(
                "SELECT status, hr_note, handled_by FROM daily_live_reports WHERE id=?",
                (report["id"],),
            ).fetchone()

        self.assertEqual(updated["status"], "follow_up")
        self.assertEqual(updated["hr_note"], "Lengkapi detail manpower shift berikutnya.")
        self.assertIsNotNone(updated["handled_by"])

    def test_daily_report_portal_rejects_attachment_for_non_live_report(self):
        self.create_user("ops_daily_plain", "pass1234", "staff", warehouse_id=1)
        self.login("ops_daily_plain", "pass1234")

        submit_response = self.client.post(
            "/laporan-harian/submit",
            data={
                "report_type": "daily",
                "report_date": "2026-09-06",
                "title": "Report harian biasa",
                "summary": "Tidak boleh pakai lampiran bukti karena bukan report live.",
                "attachment": (BytesIO(b"fake-image"), "bukti.png"),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(submit_response.status_code, 200)
        submit_html = submit_response.get_data(as_text=True)
        self.assertIn("Lampiran bukti hanya tersedia untuk report live.", submit_html)

        with self.app.app_context():
            db = get_db()
            report = db.execute(
                "SELECT id FROM daily_live_reports WHERE title=?",
                ("Report harian biasa",),
            ).fetchone()

        self.assertIsNone(report)

    def test_daily_report_feed_defaults_to_active_and_supports_archive_date_filter(self):
        today = date_cls.today().isoformat()
        yesterday = (date_cls.today() - timedelta(days=1)).isoformat()
        two_days_ago = (date_cls.today() - timedelta(days=2)).isoformat()
        self.create_user("report_ops_filter", "pass1234", "staff", warehouse_id=1)

        with self.app.app_context():
            db = get_db()
            ops_user = db.execute(
                "SELECT id FROM users WHERE username=?",
                ("report_ops_filter",),
            ).fetchone()

            db.executemany(
                """
                INSERT INTO daily_live_reports(
                    user_id,
                    employee_id,
                    warehouse_id,
                    report_type,
                    report_date,
                    title,
                    summary,
                    blocker_note,
                    follow_up_note,
                    status,
                    hr_note,
                    handled_by,
                    handled_at,
                    updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        ops_user["id"],
                        None,
                        1,
                        "daily",
                        today,
                        "Report aktif pagi",
                        "Masih menunggu review HR.",
                        None,
                        None,
                        "submitted",
                        None,
                        None,
                        None,
                        "2026-09-08 09:00:00",
                    ),
                    (
                        ops_user["id"],
                        None,
                        1,
                        "live",
                        yesterday,
                        "Report arsip reviewed",
                        "Sudah selesai ditinjau.",
                        None,
                        None,
                        "reviewed",
                        "Sudah dicek",
                        1,
                        "2026-09-07 19:00:00",
                        "2026-09-07 19:00:00",
                    ),
                    (
                        ops_user["id"],
                        None,
                        1,
                        "daily",
                        two_days_ago,
                        "Report arsip lama",
                        "Sudah closed minggu lalu.",
                        None,
                        None,
                        "closed",
                        "Arsip lama",
                        1,
                        "2026-08-29 18:00:00",
                        "2026-08-29 18:00:00",
                    ),
                ],
            )
            db.commit()

        self.login_hr_user("hr_report_archive", "pass1234")

        active_response = self.client.get("/hris/report")
        self.assertEqual(active_response.status_code, 200)
        active_html = active_response.get_data(as_text=True)
        self.assertIn("Report aktif pagi", active_html)
        self.assertNotIn("Report arsip reviewed", active_html)
        self.assertNotIn("Report arsip lama", active_html)
        self.assertIn("Feed Aktif", active_html)
        self.assertIn(f'name="daily_date_from" value="{today}"', active_html)
        self.assertIn(f'name="daily_date_to" value="{today}"', active_html)
        self.assertIn("Belum ada live report pada filter yang dipilih.", active_html)

        archive_response = self.client.get(
            f"/hris/report?daily_status=archived&daily_date_from={yesterday}&daily_date_to={yesterday}"
        )
        self.assertEqual(archive_response.status_code, 200)
        archive_html = archive_response.get_data(as_text=True)
        self.assertIn("Report arsip reviewed", archive_html)
        self.assertNotIn("Report aktif pagi", archive_html)
        self.assertNotIn("Report arsip lama", archive_html)

    def test_daily_report_review_redirect_preserves_active_filter(self):
        self.create_user("report_ops_return", "pass1234", "staff", warehouse_id=1)

        with self.app.app_context():
            db = get_db()
            ops_user = db.execute(
                "SELECT id FROM users WHERE username=?",
                ("report_ops_return",),
            ).fetchone()
            db.execute(
                """
                INSERT INTO daily_live_reports(
                    user_id,
                    employee_id,
                    warehouse_id,
                    report_type,
                    report_date,
                    title,
                    summary,
                    blocker_note,
                    follow_up_note,
                    status,
                    hr_note,
                    handled_by,
                    handled_at,
                    updated_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    ops_user["id"],
                    None,
                    1,
                    "daily",
                    "2026-09-09",
                    "Perlu review cepat",
                    "Butuh approval agar hilang dari feed aktif.",
                    None,
                    None,
                    "submitted",
                    None,
                    None,
                    None,
                    "2026-09-09 08:30:00",
                ),
            )
            db.commit()
            report = db.execute(
                "SELECT id FROM daily_live_reports WHERE title=?",
                ("Perlu review cepat",),
            ).fetchone()

        self.login_hr_user("hr_report_return", "pass1234")
        update_response = self.client.post(
            f"/hris/report/daily-live/update/{report['id']}",
            data={
                "status": "reviewed",
                "hr_note": "Sudah beres",
                "return_to": "/hris/report?daily_status=active&daily_date_from=2026-09-01&daily_date_to=2026-09-30",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)
        self.assertIn("/hris/report?daily_status=active", update_response.headers["Location"])

        filtered_response = self.client.get(update_response.headers["Location"])
        self.assertEqual(filtered_response.status_code, 200)
        filtered_html = filtered_response.get_data(as_text=True)
        self.assertNotIn("Perlu review cepat", filtered_html)

    def test_admin_can_manage_announcement_records_in_hris(self):
        self.login_hr_user()

        create_response = self.client.post(
            "/hris/announcement/add",
            data={
                "warehouse_id": "2",
                "title": "Briefing Audit Mingguan",
                "audience": "warehouse_team",
                "publish_date": "2026-10-01",
                "expires_at": "2026-10-07",
                "status": "published",
                "channel": "Dashboard Banner",
                "message": "Semua tim wajib ikut briefing audit jam 08:00.",
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            announcement = db.execute(
                """
                SELECT id, warehouse_id, title, audience, publish_date, expires_at,
                       status, channel, message, handled_by
                FROM announcement_posts
                WHERE title=?
                """,
                ("Briefing Audit Mingguan",),
            ).fetchone()

        self.assertIsNotNone(announcement)
        self.assertEqual(announcement["warehouse_id"], 2)
        self.assertEqual(announcement["audience"], "warehouse_team")
        self.assertEqual(announcement["status"], "published")
        self.assertEqual(announcement["channel"], "Dashboard Banner")
        self.assertEqual(announcement["message"], "Semua tim wajib ikut briefing audit jam 08:00.")
        self.assertIsNotNone(announcement["handled_by"])

        update_response = self.client.post(
            f"/hris/announcement/update/{announcement['id']}",
            data={
                "warehouse_id": "2",
                "title": "Briefing Audit Final",
                "audience": "leaders",
                "publish_date": "2026-10-02",
                "expires_at": "2026-10-09",
                "status": "archived",
                "channel": "Morning Briefing",
                "message": "Briefing final dipindah ke jam 09:00.",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            announcement_after = db.execute(
                """
                SELECT warehouse_id, title, audience, publish_date, expires_at,
                       status, channel, message, handled_by
                FROM announcement_posts
                WHERE id=?
                """,
                (announcement["id"],),
            ).fetchone()

        self.assertEqual(announcement_after["warehouse_id"], 2)
        self.assertEqual(announcement_after["title"], "Briefing Audit Final")
        self.assertEqual(announcement_after["audience"], "leaders")
        self.assertEqual(announcement_after["publish_date"], "2026-10-02")
        self.assertEqual(announcement_after["expires_at"], "2026-10-09")
        self.assertEqual(announcement_after["status"], "archived")
        self.assertEqual(announcement_after["channel"], "Morning Briefing")
        self.assertEqual(announcement_after["message"], "Briefing final dipindah ke jam 09:00.")
        self.assertIsNotNone(announcement_after["handled_by"])

        delete_response = self.client.post(
            f"/hris/announcement/delete/{announcement['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            announcement_count = db.execute(
                "SELECT COUNT(*) FROM announcement_posts"
            ).fetchone()[0]

        self.assertEqual(announcement_count, 0)

    def test_admin_can_manage_document_records_in_hris(self):
        self.login_hr_user()

        create_response = self.client.post(
            "/hris/documents/add",
            data={
                "warehouse_id": "2",
                "document_title": "SOP Cycle Count",
                "document_code": "DOC-001",
                "document_type": "sop",
                "status": "active",
                "effective_date": "2026-10-05",
                "review_date": "2026-12-01",
                "owner_name": "Ops Manager",
                "note": "Versi revisi untuk audit Q4",
                "attachment": (BytesIO(b"%PDF-1.4 contoh lampiran SOP"), "sop-cycle-count.pdf"),
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            document = db.execute(
                """
                SELECT id, warehouse_id, document_title, document_code, document_type,
                       status, effective_date, review_date, owner_name, note, handled_by,
                       attachment_name, attachment_path, attachment_mime, attachment_size,
                       signature_path, signed_by, signed_at
                FROM document_records
                WHERE document_code=?
                """,
                ("DOC-001",),
            ).fetchone()

        self.assertIsNotNone(document)
        self.assertEqual(document["warehouse_id"], 2)
        self.assertEqual(document["document_title"], "SOP Cycle Count")
        self.assertEqual(document["document_type"], "sop")
        self.assertEqual(document["status"], "active")
        self.assertEqual(document["review_date"], "2026-12-01")
        self.assertEqual(document["owner_name"], "Ops Manager")
        self.assertEqual(document["note"], "Versi revisi untuk audit Q4")
        self.assertIsNotNone(document["handled_by"])
        self.assertEqual(document["attachment_name"], "sop-cycle-count.pdf")
        self.assertTrue((document["attachment_path"] or "").startswith("document_"))
        self.assertEqual(document["attachment_mime"], "application/pdf")
        self.assertGreater(document["attachment_size"], 0)
        self.assertIsNone(document["signature_path"])

        list_response = self.client.get("/hris/documents")
        self.assertEqual(list_response.status_code, 200)
        list_html = list_response.get_data(as_text=True)
        self.assertIn("Halaman Pengesahan Dokumen", list_html)
        self.assertIn("sop-cycle-count.pdf", list_html)
        self.assertIn('data-document-signature-root', list_html)

        signature_data = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+X2X8AAAAASUVORK5CYII="
        )
        sign_response = self.client.post(
            f"/hris/documents/sign/{document['id']}",
            data={"signature_data": signature_data},
            follow_redirects=False,
        )
        self.assertEqual(sign_response.status_code, 302)

        update_response = self.client.post(
            f"/hris/documents/update/{document['id']}",
            data={
                "warehouse_id": "2",
                "document_title": "SOP Cycle Count Revisi",
                "document_code": "DOC-001",
                "document_type": "policy",
                "status": "archived",
                "effective_date": "2026-10-06",
                "review_date": "2027-01-15",
                "owner_name": "Senior Ops Manager",
                "note": "Dokumen diarsipkan setelah revisi final.",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            document_after = db.execute(
                """
                SELECT warehouse_id, document_title, document_code, document_type, status,
                       effective_date, review_date, owner_name, note, handled_by,
                       attachment_name, attachment_path, signature_path, signed_by, signed_at
                FROM document_records
                WHERE id=?
                """,
                (document["id"],),
            ).fetchone()

        self.assertEqual(document_after["warehouse_id"], 2)
        self.assertEqual(document_after["document_title"], "SOP Cycle Count Revisi")
        self.assertEqual(document_after["document_code"], "DOC-001")
        self.assertEqual(document_after["document_type"], "policy")
        self.assertEqual(document_after["status"], "archived")
        self.assertEqual(document_after["effective_date"], "2026-10-06")
        self.assertEqual(document_after["review_date"], "2027-01-15")
        self.assertEqual(document_after["owner_name"], "Senior Ops Manager")
        self.assertEqual(document_after["note"], "Dokumen diarsipkan setelah revisi final.")
        self.assertIsNotNone(document_after["handled_by"])
        self.assertEqual(document_after["attachment_name"], "sop-cycle-count.pdf")
        self.assertEqual(document_after["attachment_path"], document["attachment_path"])
        self.assertTrue((document_after["signature_path"] or "").startswith("document_signature_"))
        self.assertIsNotNone(document_after["signed_by"])
        self.assertIsNotNone(document_after["signed_at"])

        delete_response = self.client.post(
            f"/hris/documents/delete/{document['id']}",
            follow_redirects=False,
        )
        self.assertEqual(delete_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            document_count = db.execute(
                "SELECT COUNT(*) FROM document_records"
            ).fetchone()[0]

        self.assertEqual(document_count, 0)

    def test_add_product_and_get_variants(self):
        self.login()
        response, product_id, variants_rows = self.create_product()

        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(product_id)
        self.assertEqual(len(variants_rows), 2)

        variants_response = self.client.get(f"/products/get_variants/{product_id}")
        self.assertEqual(variants_response.status_code, 200)
        self.assertEqual(len(variants_response.get_json()), 2)

    def test_add_product_supports_manual_variant_matrix(self):
        self.login()
        sku = "MANUAL-" + uuid4().hex[:6].upper()
        response = self.client.post(
            "/products/add",
            data={
                "sku": sku,
                "name": "Produk Matrix",
                "category_name": "Testing",
                "warehouse_id": "1",
                "variant_rows_json": json.dumps([
                    {
                        "variant": "39",
                        "color": "Hitam",
                        "price_retail": "649900",
                        "price_discount": "552415",
                        "price_nett": "500000",
                        "qty": "1",
                        "variant_code": "BED-39",
                        "gtin": "899990000039",
                        "no_gtin": False,
                    },
                    {
                        "variant": "40",
                        "color": "Putih",
                        "price_retail": "649900",
                        "price_discount": "552415",
                        "price_nett": "500000",
                        "qty": "0",
                        "variant_code": "BED-40",
                        "gtin": "",
                        "no_gtin": True,
                    },
                ]),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()
            variants_rows = db.execute(
                """
                SELECT variant, color, qty.qty, variant_code, gtin, no_gtin
                FROM product_variants pv
                LEFT JOIN (
                    SELECT variant_id, SUM(qty) AS qty
                    FROM stock
                    GROUP BY variant_id
                ) qty ON qty.variant_id = pv.id
                WHERE product_id=?
                ORDER BY variant
                """,
                (product["id"],),
            ).fetchall()

        self.assertEqual(len(variants_rows), 2)
        self.assertEqual(variants_rows[0]["variant"], "39 / Hitam")
        self.assertEqual(variants_rows[0]["color"], "Hitam")
        self.assertEqual(variants_rows[0]["qty"], 1)
        self.assertEqual(variants_rows[0]["variant_code"], "BED-39")
        self.assertEqual(variants_rows[0]["gtin"], "899990000039")
        self.assertEqual(variants_rows[0]["no_gtin"], 0)
        self.assertEqual(variants_rows[1]["variant"], "40 / Putih")
        self.assertEqual(variants_rows[1]["color"], "Putih")
        self.assertIsNone(variants_rows[1]["qty"])
        self.assertEqual(variants_rows[1]["variant_code"], "BED-40")
        self.assertEqual(variants_rows[1]["gtin"], "")
        self.assertEqual(variants_rows[1]["no_gtin"], 1)

    def test_add_product_supports_same_size_with_different_colors(self):
        self.login()
        sku = "COLOR-" + uuid4().hex[:6].upper()
        response = self.client.post(
            "/products/add",
            data={
                "sku": sku,
                "name": "Produk Warna",
                "category_name": "Testing",
                "warehouse_id": "1",
                "variant_rows_json": json.dumps([
                    {
                        "variant": "39",
                        "color": "Hitam",
                        "price_retail": "300000",
                        "qty": "1",
                        "variant_code": "CLR-39-BLK",
                    },
                    {
                        "variant": "39",
                        "color": "Putih",
                        "price_retail": "300000",
                        "qty": "2",
                        "variant_code": "CLR-39-WHT",
                    },
                ]),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()
            variants_rows = db.execute(
                """
                SELECT variant, color
                FROM product_variants
                WHERE product_id=?
                ORDER BY variant
                """,
                (product["id"],),
            ).fetchall()

        self.assertEqual([row["variant"] for row in variants_rows], ["39 / Hitam", "39 / Putih"])
        self.assertEqual([row["color"] for row in variants_rows], ["Hitam", "Putih"])

    def test_add_product_supports_ajax_without_page_redirect(self):
        self.login()
        sku = "AJAX-" + uuid4().hex[:6].upper()
        response = self.client.post(
            "/products/add",
            data={
                "sku": sku,
                "name": "Produk Ajax",
                "category_name": "Testing",
                "warehouse_id": "1",
                "variant_rows_json": json.dumps([
                    {
                        "variant": "44",
                        "price_retail": "350000",
                        "price_discount": "300000",
                        "price_nett": "275000",
                        "qty": "2",
                        "variant_code": "AJX-44",
                        "gtin": "899990000044",
                    }
                ]),
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["sku"], sku)
        self.assertIn("Produk berhasil ditambahkan", payload["message"])

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()

        self.assertIsNotNone(product)

    def test_products_page_uses_10_item_pagination(self):
        self.login()
        for index in range(12):
            response, _, _ = self.create_product(
                sku=f"PAG-{index:02d}-{uuid4().hex[:4].upper()}",
                variants=f"V{index}",
            )
            self.assertEqual(response.status_code, 302)

        page_one = self.client.get("/stock/?workspace=products")
        page_one_html = page_one.get_data(as_text=True)
        self.assertEqual(page_one.status_code, 200)
        self.assertEqual(page_one_html.count('class="product-row-check"'), 10)
        self.assertIn("Page 1 / 2", page_one_html)

        page_two = self.client.get("/stock/?workspace=products&product_page=2")
        page_two_html = page_two.get_data(as_text=True)
        self.assertEqual(page_two.status_code, 200)
        self.assertEqual(page_two_html.count('class="product-row-check"'), 2)
        self.assertIn("Page 2 / 2", page_two_html)

    def test_product_picker_uses_20_item_pagination(self):
        self.login()
        for index in range(21):
            response, _, _ = self.create_product(
                sku=f"PICK-{index:02d}-{uuid4().hex[:4].upper()}",
                variants=f"V{index}",
            )
            self.assertEqual(response.status_code, 302)

        page_one = self.client.get("/products/picker?warehouse_id=1&page=1")
        self.assertEqual(page_one.status_code, 200)
        payload_one = page_one.get_json()

        self.assertEqual(payload_one["page_size"], 20)
        self.assertEqual(payload_one["page"], 1)
        self.assertEqual(len(payload_one["items"]), 20)
        self.assertGreaterEqual(payload_one["total_items"], 21)
        self.assertGreaterEqual(payload_one["total_pages"], 2)

        page_two = self.client.get("/products/picker?warehouse_id=1&page=2")
        self.assertEqual(page_two.status_code, 200)
        payload_two = page_two.get_json()

        self.assertEqual(payload_two["page"], 2)
        self.assertGreaterEqual(len(payload_two["items"]), 1)

    def test_product_picker_smart_search_prioritizes_exact_sku_match(self):
        self.login()
        exact_sku = f"SMART-EXACT-{uuid4().hex[:4].upper()}"
        loose_sku = f"X-{exact_sku}"

        response_exact, exact_product_id, exact_variants = self.create_product(
            sku=exact_sku,
            qty=9,
            variants="MATCH",
        )
        response_loose, loose_product_id, loose_variants = self.create_product(
            sku=loose_sku,
            qty=3,
            variants="MATCH",
        )
        self.assertEqual(response_exact.status_code, 302)
        self.assertEqual(response_loose.status_code, 302)

        with self.app.app_context():
            db = get_db()
            db.execute(
                "UPDATE products SET name=?, category_id=(SELECT id FROM categories WHERE name='Testing' LIMIT 1) WHERE id=?",
                ("Produk Smart Exact", exact_product_id),
            )
            db.execute(
                "UPDATE products SET name=?, category_id=(SELECT id FROM categories WHERE name='Testing' LIMIT 1) WHERE id=?",
                ("Produk Prefix Smart", loose_product_id),
            )
            db.execute(
                "UPDATE product_variants SET variant_code=?, gtin=?, color=? WHERE id=?",
                ("SMART-CODE-EXACT", "899910001111", "Hitam", exact_variants[0]["id"]),
            )
            db.execute(
                "UPDATE product_variants SET variant_code=?, gtin=?, color=? WHERE id=?",
                ("SMART-CODE-LOOSE", "899910001112", "Putih", loose_variants[0]["id"]),
            )
            db.commit()

        response = self.client.get(f"/products/picker?warehouse_id=1&q={exact_sku}")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertGreaterEqual(payload["total_items"], 2)
        self.assertEqual(payload["items"][0]["sku"], exact_sku)

    def test_product_picker_smart_search_supports_multi_term_query(self):
        self.login()
        response, product_id, variants_rows = self.create_product(
            sku=f"SMART-MULTI-{uuid4().hex[:4].upper()}",
            qty=11,
            variants="NAVY RED",
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            db.execute(
                "UPDATE products SET name=? WHERE id=?",
                ("Speed Runner Pro", product_id),
            )
            db.execute(
                "UPDATE product_variants SET color=?, variant_code=?, gtin=? WHERE id=?",
                ("Navy Red", "SPD-NR-01", "899920001111", variants_rows[0]["id"]),
            )
            db.commit()

        response = self.client.get("/products/picker?warehouse_id=1&q=runner navy testing")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertGreaterEqual(payload["total_items"], 1)
        self.assertEqual(payload["items"][0]["product_id"], product_id)
        self.assertEqual(payload["items"][0]["variant_label"], "NAVY RED")

    def test_stock_page_uses_10_item_pagination(self):
        self.login()
        for index in range(12):
            response, product_id, _ = self.create_product(
                sku=f"STKPAG-{index:02d}-{uuid4().hex[:4].upper()}",
                qty=1,
                variants=f"SV{index}",
            )
            self.assertEqual(response.status_code, 302)
            with self.app.app_context():
                db = get_db()
                db.execute(
                    "UPDATE products SET name=? WHERE id=?",
                    (f"Stock Pagination {index:02d}", product_id),
                )
                db.commit()

        page_one = self.client.get("/stock/?q=STKPAG-")
        page_one_html = page_one.get_data(as_text=True)
        self.assertEqual(page_one.status_code, 200)
        self.assertEqual(page_one_html.count('class="stock-adjust-button"'), 10)
        self.assertIn("Page 1 / 2", page_one_html)

        page_two = self.client.get("/stock/?q=STKPAG-&page=2")
        page_two_html = page_two.get_data(as_text=True)
        self.assertEqual(page_two.status_code, 200)
        self.assertEqual(page_two_html.count('class="stock-adjust-button"'), 2)
        self.assertIn("Page 2 / 2", page_two_html)

    def test_stock_page_paginates_by_product_name_but_keeps_all_group_variants_visible(self):
        self.login()
        response, product_id, _ = self.create_product(
            sku=f"STKGRP-MULTI-{uuid4().hex[:4].upper()}",
            qty=1,
            variants=",".join(f"VAR-{index:02d}" for index in range(12)),
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            db.execute(
                "UPDATE products SET name=? WHERE id=?",
                ("A PAGINATION GROUP", product_id),
            )
            db.commit()

        for index in range(10):
            response, product_id, _ = self.create_product(
                sku=f"STKGRP-SINGLE-{index:02d}-{uuid4().hex[:4].upper()}",
                qty=1,
                variants=f"SINGLE-{index:02d}",
            )
            self.assertEqual(response.status_code, 302)
            with self.app.app_context():
                db = get_db()
                db.execute(
                    "UPDATE products SET name=? WHERE id=?",
                    (f"B Pagination Single {index:02d}", product_id),
                )
                db.commit()

        page_one = self.client.get("/stock/?q=STKGRP-")
        self.assertEqual(page_one.status_code, 200)
        page_one_html = page_one.get_data(as_text=True)

        self.assertIn("12 varian", page_one_html)
        self.assertIn("VAR-00", page_one_html)
        self.assertIn("VAR-11", page_one_html)
        self.assertIn("Page 1 / 2", page_one_html)
        self.assertEqual(page_one_html.count('class="stock-adjust-button"'), 21)

        page_two = self.client.get("/stock/?q=STKGRP-&page=2")
        self.assertEqual(page_two.status_code, 200)
        page_two_html = page_two.get_data(as_text=True)

        self.assertNotIn("12 varian", page_two_html)
        self.assertNotIn("VAR-00", page_two_html)
        self.assertNotIn("VAR-11", page_two_html)
        self.assertIn("B Pagination Single 09", page_two_html)
        self.assertIn("Page 2 / 2", page_two_html)
        self.assertEqual(page_two_html.count('class="stock-adjust-button"'), 1)

    def test_stock_page_groups_same_product_variants_into_dropdown(self):
        self.login()
        response, product_id, _ = self.create_product(
            sku="AERO-COMFORT-4",
            qty=2,
            variants="black red-33,black red-34,black red-35",
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            db.execute(
                "UPDATE products SET name=? WHERE id=?",
                ("AERO COMFORT 4", product_id),
            )
            db.commit()

        page = self.client.get("/stock/?q=AERO-COMFORT-4", follow_redirects=False)
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        self.assertIn('class="stock-variant-disclosure"', html)
        self.assertIn("3 varian", html)
        self.assertIn("black red-33", html)
        self.assertIn("black red-34", html)
        self.assertIn("black red-35", html)
        self.assertEqual(html.count('value="AERO COMFORT 4"'), 1)

    def test_stock_page_groups_same_name_across_multiple_product_records(self):
        self.login()
        response_one, product_one_id, _ = self.create_product(
            sku="AERO-33",
            qty=2,
            variants="black red-33",
        )
        response_two, product_two_id, _ = self.create_product(
            sku="AERO-34",
            qty=3,
            variants="black red-34",
        )
        self.assertEqual(response_one.status_code, 302)
        self.assertEqual(response_two.status_code, 302)

        with self.app.app_context():
            db = get_db()
            db.execute(
                "UPDATE products SET name=? WHERE id IN (?, ?)",
                ("AERO COMFORT 4", product_one_id, product_two_id),
            )
            db.commit()

        page = self.client.get("/stock/?q=AERO COMFORT 4", follow_redirects=False)
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        self.assertIn('class="stock-variant-disclosure"', html)
        self.assertIn("2 varian", html)
        self.assertIn("2 SKU", html)
        self.assertIn('value="AERO-33"', html)
        self.assertIn('value="AERO-34"', html)
        self.assertIn("<strong>AERO COMFORT 4</strong>", html)
        self.assertNotIn('data-field="name" data-product', html)

    def test_leader_can_process_bulk_inbound_directly(self):
        self.create_user("leader_inbound", "pass1234", "leader", warehouse_id=1)
        self.login()
        response, product_id, variants_rows = self.create_product(qty=0, variants="41,42")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login("leader_inbound", "pass1234")
        inbound_response = self.client.post(
            "/inbound/",
            data={
                "warehouse_id": "1",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 3,
                        "note": "Restock size 41",
                        "cost": 245000,
                        "custom_date": "2026-03-30",
                    },
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[1]["id"],
                        "qty": 4,
                        "note": "Restock size 42",
                        "cost": 255000,
                        "custom_date": "2026-03-30",
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(inbound_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            stock_rows = db.execute(
                """
                SELECT variant_id, qty
                FROM stock
                WHERE product_id=? AND warehouse_id=1
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()

        self.assertEqual(len(stock_rows), 2)
        self.assertEqual(stock_rows[0]["qty"], 3)
        self.assertEqual(stock_rows[1]["qty"], 4)

    def test_leader_can_process_bulk_outbound_directly(self):
        self.create_user("leader_outbound", "pass1234", "leader", warehouse_id=1)
        self.login()
        response, product_id, variants_rows = self.create_product(qty=10, variants="41,42")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login("leader_outbound", "pass1234")
        outbound_response = self.client.post(
            "/outbound/",
            data={
                "warehouse_id": "1",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 2,
                        "note": "Order size 41",
                    },
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[1]["id"],
                        "qty": 3,
                        "note": "Order size 42",
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(outbound_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            stock_rows = db.execute(
                """
                SELECT variant_id, qty
                FROM stock
                WHERE product_id=? AND warehouse_id=1
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()

        self.assertEqual(len(stock_rows), 2)
        self.assertEqual(stock_rows[0]["qty"], 8)
        self.assertEqual(stock_rows[1]["qty"], 7)

    def test_inbound_request_triggers_role_based_whatsapp_notification(self):
        self.create_user("admin_inbound_wa", "pass1234", "admin", warehouse_id=1)
        self.login("admin_inbound_wa", "pass1234")
        response, product_id, variants_rows = self.create_product(qty=0, variants="41")
        self.assertEqual(response.status_code, 302)

        with patch("routes.inbound.send_role_based_notification") as mocked_role_notify:
            inbound_response = self.client.post(
                "/inbound/",
                data={
                    "warehouse_id": "1",
                    "items_json": json.dumps(
                        [
                            {
                                "product_id": product_id,
                                "variant_id": variants_rows[0]["id"],
                                "qty": 2,
                                "note": "Request inbound WA",
                                "cost": 220000,
                            }
                        ]
                    ),
                },
                follow_redirects=False,
            )

        self.assertEqual(inbound_response.status_code, 302)
        mocked_role_notify.assert_called_once()
        self.assertEqual(mocked_role_notify.call_args.args[0], "inventory.inbound_approval_requested")
        self.assertEqual(mocked_role_notify.call_args.args[1]["warehouse_id"], 1)
        self.assertEqual(mocked_role_notify.call_args.args[1]["item_count"], 1)
        self.assertEqual(mocked_role_notify.call_args.args[1]["link_url"], "/approvals")

    def test_outbound_request_triggers_role_based_whatsapp_notification(self):
        self.create_user("admin_outbound_wa", "pass1234", "admin", warehouse_id=1)
        self.login("admin_outbound_wa", "pass1234")
        response, product_id, variants_rows = self.create_product(qty=6, variants="41")
        self.assertEqual(response.status_code, 302)

        with patch("routes.outbound.send_role_based_notification") as mocked_role_notify:
            outbound_response = self.client.post(
                "/outbound/",
                data={
                    "warehouse_id": "1",
                    "items_json": json.dumps(
                        [
                            {
                                "product_id": product_id,
                                "variant_id": variants_rows[0]["id"],
                                "qty": 2,
                                "note": "Request outbound WA",
                            }
                        ]
                    ),
                },
                follow_redirects=False,
            )

        self.assertEqual(outbound_response.status_code, 302)
        mocked_role_notify.assert_called_once()
        self.assertEqual(mocked_role_notify.call_args.args[0], "inventory.outbound_approval_requested")
        self.assertEqual(mocked_role_notify.call_args.args[1]["warehouse_id"], 1)
        self.assertEqual(mocked_role_notify.call_args.args[1]["item_count"], 1)
        self.assertEqual(mocked_role_notify.call_args.args[1]["link_url"], "/approvals")

    def test_adjust_request_triggers_role_based_whatsapp_notification(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="ADJWA")
        variant_id = variants_rows[0]["id"]

        with patch("routes.stock.send_role_based_notification") as mocked_role_notify:
            adjust_response = self.client.post(
                "/stock/adjust",
                data={
                    "product_id": str(product_id),
                    "variant_id": str(variant_id),
                    "warehouse_id": "1",
                    "qty": "-1",
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
                follow_redirects=False,
            )

        self.assertEqual(adjust_response.status_code, 200)
        self.assertEqual(adjust_response.get_json()["status"], "pending")
        mocked_role_notify.assert_called_once()
        self.assertEqual(mocked_role_notify.call_args.args[0], "inventory.adjust_approval_requested")
        self.assertEqual(mocked_role_notify.call_args.args[1]["warehouse_id"], 1)
        self.assertEqual(mocked_role_notify.call_args.args[1]["item_count"], 1)
        self.assertEqual(mocked_role_notify.call_args.args[1]["link_url"], "/approvals")

    def test_inventory_activity_notifications_reach_monitoring_roles(self):
        self.create_user("owner_inventory_monitor", "pass1234", "owner")
        self.create_user("leader_inventory_notify", "pass1234", "leader", warehouse_id=1)

        self.login()
        response, product_id, variants_rows = self.create_product(qty=10, variants="41")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login("leader_inventory_notify", "pass1234")
        inbound_response = self.client.post(
            "/inbound/",
            data={
                "warehouse_id": "1",
                "items_json": json.dumps(
                    [
                        {
                            "product_id": product_id,
                            "variant_id": variants_rows[0]["id"],
                            "qty": 3,
                            "note": "Restock notifikasi",
                            "cost": 245000,
                            "custom_date": "2026-03-30",
                        }
                    ]
                ),
            },
            follow_redirects=False,
        )
        self.assertEqual(inbound_response.status_code, 302)

        outbound_response = self.client.post(
            "/outbound/",
            data={
                "warehouse_id": "1",
                "items_json": json.dumps(
                    [
                        {
                            "product_id": product_id,
                            "variant_id": variants_rows[0]["id"],
                            "qty": 2,
                            "note": "Order notifikasi",
                        }
                    ]
                ),
            },
            follow_redirects=False,
        )
        self.assertEqual(outbound_response.status_code, 302)
        self.logout()

        self.login("owner_inventory_monitor", "pass1234")
        notification_response = self.client.get("/notifications/api?filter=all&limit=10")
        self.assertEqual(notification_response.status_code, 200)
        payload = notification_response.get_json()
        items = payload["items"]

        self.assertTrue(
            any(
                item["category"] == "inventory"
                and item["title"] == "Inbound selesai: 1 item"
                and item["link_url"] == "/inbound/"
                for item in items
            )
        )
        self.assertTrue(
            any(
                item["category"] == "inventory"
                and item["title"] == "Outbound selesai: 1 item"
                and item["link_url"] == "/outbound/"
                for item in items
            )
        )

    def test_admin_can_create_bulk_request_batch(self):
        self.create_user("super_req_batch", "pass1234", "super_admin")
        self.login("super_req_batch", "pass1234")
        response, product_id, variants_rows = self.create_product(qty=10, variants="41,42", warehouse_id="2")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login()

        request_response = self.client.post(
            "/request/",
            data={
                "from_warehouse": "1",
                "to_warehouse": "2",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 2,
                    },
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[1]["id"],
                        "qty": 3,
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_rows = db.execute(
                """
                SELECT variant_id, from_warehouse, to_warehouse, qty, status
                FROM requests
                WHERE product_id=?
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()

        self.assertEqual(len(request_rows), 2)
        self.assertEqual(request_rows[0]["from_warehouse"], 2)
        self.assertEqual(request_rows[0]["to_warehouse"], 1)
        self.assertEqual(request_rows[0]["qty"], 2)
        self.assertEqual(request_rows[0]["status"], "pending")
        self.assertEqual(request_rows[1]["from_warehouse"], 2)
        self.assertEqual(request_rows[1]["to_warehouse"], 1)
        self.assertEqual(request_rows[1]["qty"], 3)
        self.assertEqual(request_rows[1]["status"], "pending")

    def test_source_leader_can_reject_request_and_notify_requester(self):
        self.create_user("leader_request_reject", "pass1234", "leader", warehouse_id=2)
        self.create_user("super_req_reject", "pass1234", "super_admin")
        self.login("super_req_reject", "pass1234")
        response, product_id, variants_rows = self.create_product(qty=10, variants="44", warehouse_id="2")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login()
        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                UPDATE users
                SET email=?, notify_email=1
                WHERE username=?
                """,
                ("admin_requester@example.com", "admin"),
            )
            db.commit()

        request_response = self.client.post(
            "/request/",
            data={
                "product_id": str(product_id),
                "variant_id": str(variants_rows[0]["id"]),
                "from_warehouse": "1",
                "to_warehouse": "2",
                "qty": "2",
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_row = db.execute(
                """
                SELECT id, status
                FROM requests
                WHERE product_id=? AND variant_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (product_id, variants_rows[0]["id"]),
            ).fetchone()

        self.assertIsNotNone(request_row)
        self.assertEqual(request_row["status"], "pending")

        self.logout()
        self.login("leader_request_reject", "pass1234")

        reject_response = self.client.post(
            f"/request/reject/{request_row['id']}",
            data={"reason": "Stok dialokasikan untuk prioritas lain"},
            follow_redirects=False,
        )
        self.assertEqual(reject_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_after = db.execute(
                """
                SELECT status, reason, approved_by
                FROM requests
                WHERE id=?
                """,
                (request_row["id"],),
            ).fetchone()
            notification = db.execute(
                """
                SELECT recipient, subject, message
                FROM notifications
                WHERE recipient=?
                  AND subject LIKE ?
                ORDER BY id DESC
                LIMIT 1
                """,
                ("admin_requester@example.com", f"Request antar gudang #{request_row['id']}%"),
            ).fetchone()

        self.assertIsNotNone(request_after)
        self.assertEqual(request_after["status"], "rejected")
        self.assertEqual(request_after["reason"], "Stok dialokasikan untuk prioritas lain")
        self.assertEqual(request_after["approved_by"], self.get_user_id("leader_request_reject"))
        self.assertIsNotNone(notification)
        self.assertIn("ditolak", notification["subject"])
        self.assertIn("Stok dialokasikan untuk prioritas lain", notification["message"])

    def test_request_notifications_only_target_source_leader_owner_and_super_admin(self):
        self.create_user(
            "leader_mataram_notify",
            "pass1234",
            "leader",
            warehouse_id=1,
            email="leader_mataram@example.com",
            notify_email=1,
        )
        self.create_user(
            "leader_mega_notify",
            "pass1234",
            "leader",
            warehouse_id=2,
            email="leader_mega@example.com",
            notify_email=1,
        )
        self.create_user(
            "owner_request_notify",
            "pass1234",
            "owner",
            email="owner_request@example.com",
            notify_email=1,
        )
        self.create_user(
            "super_request_notify",
            "pass1234",
            "super_admin",
            email="super_request@example.com",
            notify_email=1,
        )
        self.create_user(
            "admin_mega_notify",
            "pass1234",
            "admin",
            warehouse_id=2,
            email="admin_mega@example.com",
            notify_email=1,
        )

        self.create_user("super_req_notify", "pass1234", "super_admin")
        self.login("super_req_notify", "pass1234")
        response, product_id, variants_rows = self.create_product(qty=10, variants="43", warehouse_id="2")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login()

        request_response = self.client.post(
            "/request/",
            data={
                "product_id": str(product_id),
                "variant_id": str(variants_rows[0]["id"]),
                "from_warehouse": "1",
                "to_warehouse": "2",
                "qty": "2",
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            notifications = db.execute(
                """
                SELECT role, recipient
                FROM notifications
                WHERE subject LIKE 'Request Baru:%'
                ORDER BY recipient
                """
            ).fetchall()

        recipients = {(row["role"], row["recipient"]) for row in notifications}
        self.assertEqual(
            recipients,
            {
                ("leader", "leader_mega@example.com"),
                ("owner", "owner_request@example.com"),
                ("super_admin", "super_request@example.com"),
            },
        )

    def test_admin_can_create_owner_request_batch_and_notify_owner(self):
        self.create_user(
            "owner_notify",
            "pass1234",
            "owner",
            email="owner_notify@example.com",
            notify_email=1,
        )
        self.login()
        response, product_id, variants_rows = self.create_product(qty=10, variants="41,42")
        self.assertEqual(response.status_code, 302)

        owner_page = self.client.get("/request/owner")
        self.assertEqual(owner_page.status_code, 200)
        owner_html = owner_page.get_data(as_text=True)
        self.assertIn('href="/request/"', owner_html)
        self.assertIn('href="/request/owner"', owner_html)
        self.assertIn("Kirim ke Owner", owner_html)

        request_response = self.client.post(
            "/request/owner",
            data={
                "warehouse_id": "1",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 2,
                        "note": "Restock cepat",
                    },
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[1]["id"],
                        "qty": 3,
                        "note": "Display menipis",
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_rows = db.execute(
                """
                SELECT variant_id, warehouse_id, qty, note, status
                FROM owner_requests
                WHERE product_id=?
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()
            notifications = db.execute(
                """
                SELECT role, recipient, subject, status
                FROM notifications
                WHERE subject LIKE 'Request Khusus ke Owner:%'
                ORDER BY id
                """,
            ).fetchall()

        self.assertEqual(len(request_rows), 2)
        self.assertEqual(request_rows[0]["warehouse_id"], 1)
        self.assertEqual(request_rows[0]["qty"], 2)
        self.assertEqual(request_rows[0]["note"], "Restock cepat")
        self.assertEqual(request_rows[0]["status"], "pending")
        self.assertEqual(request_rows[1]["qty"], 3)
        self.assertEqual(request_rows[1]["note"], "Display menipis")
        self.assertEqual(request_rows[1]["status"], "pending")
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["role"], "owner")
        self.assertEqual(notifications[0]["recipient"], "owner_notify@example.com")

    def test_bulk_delete_product_cleans_related_wms_records(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="DEL")
        variant_id = variants_rows[0]["id"]

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO requests(
                    product_id,
                    variant_id,
                    from_warehouse,
                    to_warehouse,
                    qty,
                    status,
                    requested_by
                )
                VALUES (?,?,?,?,?,?,?)
                """,
                (product_id, variant_id, 1, 2, 2, "pending", 1),
            )
            db.execute(
                """
                INSERT INTO approvals(
                    type,
                    product_id,
                    variant_id,
                    warehouse_id,
                    qty,
                    note,
                    status,
                    requested_by
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                ("ADJUST", product_id, variant_id, 1, -1, "Cleanup test", "pending", 1),
            )
            db.commit()

        response = self.client.post(
            "/products/bulk-delete",
            json={"ids": [product_id]},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "success")

        with self.app.app_context():
            db = get_db()
            product_count = db.execute(
                "SELECT COUNT(*) FROM products WHERE id=?",
                (product_id,),
            ).fetchone()[0]
            request_count = db.execute(
                "SELECT COUNT(*) FROM requests WHERE product_id=?",
                (product_id,),
            ).fetchone()[0]
            approval_count = db.execute(
                "SELECT COUNT(*) FROM approvals WHERE product_id=?",
                (product_id,),
            ).fetchone()[0]

        self.assertEqual(product_count, 0)
        self.assertEqual(request_count, 0)
        self.assertEqual(approval_count, 0)

    def test_owner_can_update_owner_request_status_and_notify_requester(self):
        self.create_user("owner_manager", "pass1234", "owner")
        self.login()
        response, product_id, variants_rows = self.create_product(qty=10, variants="41")
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                UPDATE users
                SET email=?, notify_email=1
                WHERE username=?
                """,
                ("admin_notify@example.com", "admin"),
            )
            db.commit()

        request_response = self.client.post(
            "/request/owner",
            data={
                "warehouse_id": "1",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 2,
                        "note": "Owner approval needed",
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            owner_request = db.execute(
                """
                SELECT id, requested_by, status
                FROM owner_requests
                WHERE product_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (product_id,),
            ).fetchone()

        self.assertEqual(owner_request["status"], "pending")

        self.logout()
        self.login("owner_manager", "pass1234")

        owner_queue = self.client.get("/request/owner")
        self.assertEqual(owner_queue.status_code, 200)
        self.assertIn("Proses", owner_queue.get_data(as_text=True))

        update_response = self.client.post(
            f"/request/owner/update/{owner_request['id']}",
            data={"status": "in_progress"},
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            owner_request_after = db.execute(
                "SELECT status, handled_by FROM owner_requests WHERE id=?",
                (owner_request["id"],),
            ).fetchone()
            requester_notification = db.execute(
                """
                SELECT recipient, subject, status
                FROM notifications
                WHERE recipient=?
                  AND subject LIKE ?
                ORDER BY id DESC
                LIMIT 1
                """,
                ("admin_notify@example.com", f"Request ke owner #{owner_request['id']}%"),
            ).fetchone()

        self.assertEqual(owner_request_after["status"], "in_progress")
        self.assertIsNotNone(owner_request_after["handled_by"])
        self.assertIsNotNone(requester_notification)
        self.assertIn("Diproses", requester_notification["subject"])

    def test_leader_can_process_bulk_transfer_directly(self):
        self.create_user("leader_transfer", "pass1234", "leader", warehouse_id=1)
        self.login()
        response, product_id, variants_rows = self.create_product(qty=10, variants="41,42")
        self.assertEqual(response.status_code, 302)
        self.logout()

        self.login("leader_transfer", "pass1234")
        transfer_response = self.client.post(
            "/transfers/",
            data={
                "from_warehouse": "1",
                "to_warehouse": "2",
                "items_json": json.dumps([
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[0]["id"],
                        "qty": 2,
                    },
                    {
                        "product_id": product_id,
                        "variant_id": variants_rows[1]["id"],
                        "qty": 3,
                    },
                ]),
            },
            follow_redirects=False,
        )
        self.assertEqual(transfer_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            stock_from = db.execute(
                """
                SELECT variant_id, qty
                FROM stock
                WHERE product_id=? AND warehouse_id=1
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()
            stock_to = db.execute(
                """
                SELECT variant_id, qty
                FROM stock
                WHERE product_id=? AND warehouse_id=2
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()
            request_rows = db.execute(
                """
                SELECT variant_id, qty, status
                FROM requests
                WHERE product_id=?
                ORDER BY variant_id
                """,
                (product_id,),
            ).fetchall()

        self.assertEqual(len(stock_from), 2)
        self.assertEqual(stock_from[0]["qty"], 8)
        self.assertEqual(stock_from[1]["qty"], 7)
        self.assertEqual(len(stock_to), 2)
        self.assertEqual(stock_to[0]["qty"], 2)
        self.assertEqual(stock_to[1]["qty"], 3)
        self.assertEqual(len(request_rows), 2)
        self.assertEqual(request_rows[0]["status"], "approved")
        self.assertEqual(request_rows[1]["status"], "approved")

    def test_request_approval_updates_stock(self):
        self.create_user("leader_request", "pass1234", "leader", warehouse_id=2)
        self.create_user("super_req_approve", "pass1234", "super_admin")
        self.login("super_req_approve", "pass1234")
        _, product_id, variants_rows = self.create_product(variants="XL", warehouse_id="2")
        variant_id = variants_rows[0]["id"]
        self.logout()

        self.login()

        request_response = self.client.post(
            "/request/",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "from_warehouse": "1",
                "to_warehouse": "2",
                "qty": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_row = db.execute(
                "SELECT id, from_warehouse, to_warehouse, status FROM requests WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()

        self.assertEqual(request_row["status"], "pending")
        self.assertEqual(request_row["from_warehouse"], 2)
        self.assertEqual(request_row["to_warehouse"], 1)

        self.logout()
        self.login("leader_request", "pass1234")
        approve_response = self.client.post(
            f"/request/approve/{request_row['id']}",
            follow_redirects=False,
        )
        self.assertEqual(approve_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_after = db.execute(
                "SELECT status FROM requests WHERE id=?",
                (request_row["id"],),
            ).fetchone()
            stock_from = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=2",
                (product_id, variant_id),
            ).fetchone()
            stock_to = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product_id, variant_id),
            ).fetchone()

        self.assertEqual(request_after["status"], "approved")
        self.assertEqual(stock_from["qty"], 4)
        self.assertEqual(stock_to["qty"], 1)

    def test_destination_leader_cannot_approve_request(self):
        self.create_user("leader_dest_only", "pass1234", "leader", warehouse_id=1)
        self.create_user("super_req_dest", "pass1234", "super_admin")
        self.login("super_req_dest", "pass1234")
        _, product_id, variants_rows = self.create_product(variants="APR2", warehouse_id="2")
        variant_id = variants_rows[0]["id"]
        self.logout()

        self.login()

        request_response = self.client.post(
            "/request/",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "from_warehouse": "1",
                "to_warehouse": "2",
                "qty": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_row = db.execute(
                "SELECT id, from_warehouse, to_warehouse, status FROM requests WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()

        self.assertEqual(request_row["from_warehouse"], 2)
        self.assertEqual(request_row["to_warehouse"], 1)
        self.assertEqual(request_row["status"], "pending")

        self.logout()
        self.login("leader_dest_only", "pass1234")

        queue_response = self.client.get("/request/")
        self.assertEqual(queue_response.status_code, 200)
        self.assertNotIn(f'/request/approve/{request_row["id"]}', queue_response.get_data(as_text=True))

        approve_response = self.client.post(
            f"/request/approve/{request_row['id']}",
            follow_redirects=False,
        )
        self.assertEqual(approve_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_after = db.execute(
                "SELECT status FROM requests WHERE id=?",
                (request_row["id"],),
            ).fetchone()

        self.assertEqual(request_after["status"], "pending")

    def test_admin_cannot_approve_request(self):
        self.create_user("super_req_admin", "pass1234", "super_admin")
        self.login("super_req_admin", "pass1234")
        _, product_id, variants_rows = self.create_product(variants="APR", warehouse_id="2")
        variant_id = variants_rows[0]["id"]
        self.logout()

        self.login()

        request_response = self.client.post(
            "/request/",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "from_warehouse": "1",
                "to_warehouse": "2",
                "qty": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(request_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            request_row = db.execute(
                "SELECT id, status FROM requests WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()

        response = self.client.post(
            f"/request/approve/{request_row['id']}",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        request_page = self.client.get("/request/")
        html = request_page.get_data(as_text=True)
        self.assertNotIn(f'/request/approve/{request_row["id"]}', html)

        with self.app.app_context():
            db = get_db()
            request_after = db.execute(
                "SELECT status FROM requests WHERE id=?",
                (request_row["id"],),
            ).fetchone()

        self.assertEqual(request_after["status"], "pending")

    def test_import_preview_and_import_progress(self):
        self.login()
        sku = "IMP-" + uuid4().hex[:6].upper()
        csv_bytes = (
            "sku,name,category,variant,qty,price_retail,price_discount,price_nett\n"
            f"{sku},Produk Import Test,Testing,42,3,200000,180000,150000\n"
        ).encode()

        preview_response = self.client.post(
            "/products/import/preview",
            data={"file": (BytesIO(csv_bytes), "sample.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.get_json()["rows"][0]["sku"], sku)

        import_response = self.client.post(
            "/products/import",
            data={"file": (BytesIO(csv_bytes), "sample.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(import_response.status_code, 200)
        job_id = import_response.get_json()["job_id"]
        self.assertTrue(job_id)

        progress_response = self.client.get(f"/products/import/progress/{job_id}")
        self.assertEqual(progress_response.status_code, 200)
        self.assertEqual(progress_response.get_json()["status"], "done")

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()

        self.assertIsNotNone(product)

    def test_import_xlsx_template_works_without_openpyxl_dependency(self):
        self.login()
        sku = "BED PP-POWERSPIN-00001"
        xlsx_bytes = self.build_xlsx_bytes(
            [
                ["sku", "name", "category", "variant", "qty", "warehouse_id", "price_retail", "price_discount", "price_nett"],
                [sku, "POWERSPIN 0001", "POWERSPIN", "-", "1.0", "1.0", "0.0", "0.0", "0.0"],
            ]
        )

        preview_response = self.client.post(
            "/products/import/preview",
            data={"file": (BytesIO(xlsx_bytes), "template.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.get_json()["rows"][0]["sku"], sku)

        import_response = self.client.post(
            "/products/import",
            data={"file": (BytesIO(xlsx_bytes), "template.xlsx")},
            content_type="multipart/form-data",
        )
        self.assertEqual(import_response.status_code, 200)

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()
            variant = db.execute(
                "SELECT id, variant FROM product_variants WHERE product_id=?",
                (product["id"],),
            ).fetchone()
            stock = db.execute(
                """
                SELECT qty
                FROM stock
                WHERE product_id=? AND variant_id=? AND warehouse_id=1
                """,
                (product["id"], variant["id"]),
            ).fetchone()

        self.assertIsNotNone(product)
        self.assertEqual(variant["variant"], "default")
        self.assertEqual(stock["qty"], 1)

    def test_import_csv_with_semicolon_delimiter_is_supported(self):
        self.login()
        sku = "IMP-SC-" + uuid4().hex[:6].upper()
        csv_bytes = (
            "sku;name;category;variant;qty;price_retail;price_discount;price_nett\n"
            f"{sku};Produk CSV Excel;Testing;43;2;210000;190000;160000\n"
        ).encode()

        preview_response = self.client.post(
            "/products/import/preview",
            data={"file": (BytesIO(csv_bytes), "sample-semicolon.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(preview_response.status_code, 200)
        self.assertEqual(preview_response.get_json()["rows"][0]["sku"], sku)

        import_response = self.client.post(
            "/products/import",
            data={"file": (BytesIO(csv_bytes), "sample-semicolon.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(import_response.status_code, 200)

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()

        self.assertIsNotNone(product)

    def test_import_allows_zero_qty_to_create_product_master_without_stock(self):
        self.login()
        sku = "IMP-ZERO-" + uuid4().hex[:6].upper()
        csv_bytes = (
            "sku,name,category,variant,qty,price_retail,price_discount,price_nett\n"
            f"{sku},Produk Zero Stock,Testing,44,0,220000,0,0\n"
        ).encode()

        import_response = self.client.post(
            "/products/import",
            data={"file": (BytesIO(csv_bytes), "sample-zero.csv")},
            content_type="multipart/form-data",
        )
        self.assertEqual(import_response.status_code, 200)

        with self.app.app_context():
            db = get_db()
            product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                (sku,),
            ).fetchone()
            variant = db.execute(
                "SELECT id, variant FROM product_variants WHERE product_id=?",
                (product["id"],),
            ).fetchone()
            stock = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product["id"], variant["id"]),
            ).fetchone()

        self.assertIsNotNone(product)
        self.assertEqual(variant["variant"], "44")
        self.assertIsNone(stock)

    def test_forgot_password_creates_reset_code_without_error(self):
        self.create_user(
            "reset_user",
            "pass1234",
            "admin",
            warehouse_id=1,
            email="reset@example.test",
            notify_email=1,
        )

        response = self.client.post(
            "/forgot",
            data={"identifier": "reset@example.test"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            reset_row = db.execute(
                """
                SELECT pr.code
                FROM password_resets pr
                JOIN users u ON u.id = pr.user_id
                WHERE u.username=?
                ORDER BY pr.id DESC
                LIMIT 1
                """,
                ("reset_user",),
            ).fetchone()

        self.assertIsNotNone(reset_row)
        self.assertEqual(len(reset_row["code"]), 6)

    def test_forgot_password_invalidates_previous_reset_codes(self):
        self.create_user(
            "reset_rotate",
            "pass1234",
            "admin",
            warehouse_id=1,
            email="rotate@example.test",
            notify_email=1,
        )

        first = self.client.post(
            "/forgot",
            data={"identifier": "rotate@example.test"},
            follow_redirects=False,
        )
        second = self.client.post(
            "/forgot",
            data={"identifier": "rotate@example.test"},
            follow_redirects=False,
        )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)

        with self.app.app_context():
            db = get_db()
            rows = db.execute(
                """
                SELECT pr.code, pr.used
                FROM password_resets pr
                JOIN users u ON u.id = pr.user_id
                WHERE u.username=?
                ORDER BY pr.id DESC
                """,
                ("reset_rotate",),
            ).fetchall()

        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[0]["used"], 0)
        self.assertEqual(rows[1]["used"], 1)

    def test_reset_password_enforces_minimum_length(self):
        self.create_user(
            "reset_policy",
            "pass1234",
            "admin",
            warehouse_id=1,
            email="policy@example.test",
            notify_email=1,
        )

        self.client.post(
            "/forgot",
            data={"identifier": "policy@example.test"},
            follow_redirects=False,
        )

        with self.app.app_context():
            db = get_db()
            code = db.execute(
                """
                SELECT pr.code
                FROM password_resets pr
                JOIN users u ON u.id = pr.user_id
                WHERE u.username=?
                ORDER BY pr.id DESC
                LIMIT 1
                """,
                ("reset_policy",),
            ).fetchone()["code"]

        short_reset = self.client.post(
            "/reset",
            data={
                "username": "reset_policy",
                "code": code,
                "password": "123",
            },
            follow_redirects=True,
        )
        self.assertEqual(short_reset.status_code, 200)
        self.assertIn("Password minimal 8 karakter", short_reset.get_data(as_text=True))

        bad_login = self.login("reset_policy", "123")
        self.assertEqual(bad_login.status_code, 302)
        good_login = self.login("reset_policy", "pass1234")
        self.assertEqual(good_login.status_code, 302)

    def test_login_rate_limit_blocks_repeated_failures(self):
        self.create_user("throttle_user", "pass1234", "admin", warehouse_id=1)

        for _ in range(3):
            response = self.client.post(
                "/login",
                data={"username": "throttle_user", "password": "salah"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 302)

        blocked = self.client.post(
            "/login",
            data={"username": "throttle_user", "password": "pass1234"},
            follow_redirects=True,
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertIn("Terlalu banyak percobaan login", blocked.get_data(as_text=True))

        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get("user_id"))

        with self.app.app_context():
            db = get_db()
            attempts = db.execute(
                """
                SELECT COUNT(*)
                FROM login_attempts
                WHERE identifier=?
                """,
                ("throttle_user",),
            ).fetchone()[0]

        self.assertEqual(attempts, 3)

    def test_send_whatsapp_marks_http_failure(self):
        if notification_service.http_requests is None:
            self.skipTest("requests library unavailable")

        class FakeResponse:
            ok = False
            status_code = 500
            headers = {"Content-Type": "application/json"}

            @staticmethod
            def json():
                return {"status": False}

        with patch.dict(os.environ, {"FONNTE_API_KEY": "test-key"}, clear=False):
            with patch.object(notification_service.http_requests, "post", return_value=FakeResponse()):
                result = notification_service.send_whatsapp("628123456789", "Halo")

        self.assertFalse(result)

    def test_products_page_respects_selected_warehouse_for_super_admin(self):
        self.create_user("superboss", "admin123", "super_admin")
        self.login("superboss", "admin123")
        response, _, _ = self.create_product(variants="WH2", warehouse_id="2")
        self.assertEqual(response.status_code, 302)

        page = self.client.get("/stock/?workspace=products&warehouse=2")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        self.assertIn('<option value="2" selected>', html)

    def test_products_route_redirects_to_stock_workspace_products(self):
        self.create_user("redirect_superboss", "pass1234", "super_admin")
        self.login("redirect_superboss", "pass1234")

        response = self.client.get(
            "/products/?warehouse=2&search=AERO&page=3",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        redirect_target = urlsplit(response.headers["Location"])
        self.assertEqual(redirect_target.path, "/stock/")
        query = parse_qs(redirect_target.query)
        self.assertEqual(query.get("workspace"), ["products"])
        self.assertEqual(query.get("warehouse"), ["2"])
        self.assertEqual(query.get("product_search"), ["AERO"])
        self.assertEqual(query.get("product_page"), ["3"])

    def test_set_warehouse_respects_global_and_scoped_roles(self):
        self.create_user("warehouse_super", "pass1234", "super_admin")
        self.login("warehouse_super", "pass1234")

        super_response = self.client.post(
            "/set_warehouse",
            data={"warehouse_id": "2"},
            follow_redirects=False,
        )
        self.assertEqual(super_response.status_code, 200)
        self.assertEqual(super_response.get_json()["warehouse_id"], 2)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("warehouse_id"), 2)

        self.logout()

        scoped_employee_id = self.create_employee_record(
            employee_code="EMP-ADM-WH",
            full_name="Admin Scoped Warehouse",
            warehouse_id=1,
            position="Admin",
        )
        self.create_user("warehouse_admin", "pass1234", "admin", warehouse_id=1, employee_id=scoped_employee_id)
        self.login("warehouse_admin", "pass1234")

        scoped_response = self.client.post(
            "/set_warehouse",
            data={"warehouse_id": "2"},
            follow_redirects=False,
        )
        self.assertEqual(scoped_response.status_code, 200)
        self.assertEqual(scoped_response.get_json()["warehouse_id"], 1)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("warehouse_id"), 1)

    def test_admin_adjust_requires_approval_and_leader_can_approve(self):
        self.create_user("leader_test", "pass1234", "leader", warehouse_id=1)
        self.login()
        _, product_id, variants_rows = self.create_product(variants="ADJ")
        variant_id = variants_rows[0]["id"]

        adjust_response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "-2",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(adjust_response.status_code, 200)
        self.assertEqual(adjust_response.get_json()["status"], "pending")

        with self.app.app_context():
            db = get_db()
            approval = db.execute(
                "SELECT id, status, type FROM approvals WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()

        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["type"], "ADJUST")

        self.logout()
        self.login("leader_test", "pass1234")
        with patch("routes.approvals.send_role_based_notification") as mocked_role_notify:
            approve_response = self.client.post(
                f"/approvals/approve/{approval['id']}",
                follow_redirects=False,
            )
        self.assertEqual(approve_response.status_code, 302)
        mocked_role_notify.assert_called_once()
        self.assertEqual(mocked_role_notify.call_args.args[0], "inventory.approval_approved")

        with self.app.app_context():
            db = get_db()
            approval_after = db.execute(
                "SELECT status FROM approvals WHERE id=?",
                (approval["id"],),
            ).fetchone()
            stock_after = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product_id, variant_id),
            ).fetchone()

        self.assertEqual(approval_after["status"], "approved")
        self.assertEqual(stock_after["qty"], 3)

    def test_approved_approval_notifies_requester(self):
        self.create_user("leader_notify_requester", "pass1234", "leader", warehouse_id=1)
        self.create_user(
            "requester_approval_wa",
            "pass1234",
            "admin",
            warehouse_id=1,
            phone="081234567890",
            notify_whatsapp=1,
        )

        self.login("requester_approval_wa", "pass1234")
        _, product_id, variants_rows = self.create_product(variants="REQAPP")
        variant_id = variants_rows[0]["id"]

        adjust_response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "-1",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(adjust_response.status_code, 200)

        with self.app.app_context():
            db = get_db()
            approval = db.execute(
                "SELECT id, requested_by FROM approvals WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()

        self.logout()
        self.login("leader_notify_requester", "pass1234")
        with patch("routes.approvals.notify_user") as mocked_notify_user:
            approve_response = self.client.post(
                f"/approvals/approve/{approval['id']}",
                follow_redirects=False,
            )

        self.assertEqual(approve_response.status_code, 302)
        mocked_notify_user.assert_called_once()
        self.assertEqual(mocked_notify_user.call_args.args[0], approval["requested_by"])
        self.assertIn("disetujui", mocked_notify_user.call_args.args[1].lower())
        self.assertIn("disetujui", mocked_notify_user.call_args.args[2].lower())


    def test_reject_approval_triggers_role_based_whatsapp_notification(self):
        self.create_user("leader_reject_test", "pass1234", "leader", warehouse_id=1)
        self.login()
        _, product_id, variants_rows = self.create_product(variants="REJWA")
        variant_id = variants_rows[0]["id"]

        adjust_response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "-2",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(adjust_response.status_code, 200)
        self.assertEqual(adjust_response.get_json()["status"], "pending")

        with self.app.app_context():
            db = get_db()
            approval = db.execute(
                "SELECT id, status FROM approvals WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()

        self.logout()
        self.login("leader_reject_test", "pass1234")
        with patch("routes.approvals.send_role_based_notification") as mocked_role_notify:
            reject_response = self.client.post(
                f"/approvals/reject/{approval['id']}",
                data={"reason": "stok tidak sesuai"},
                follow_redirects=False,
            )

        self.assertEqual(reject_response.status_code, 302)
        mocked_role_notify.assert_called_once()
        self.assertEqual(mocked_role_notify.call_args.args[0], "inventory.approval_rejected")
        self.assertIn("stok tidak sesuai", mocked_role_notify.call_args.args[1]["reason"])

    def test_rejected_approval_notifies_requester(self):
        self.create_user("leader_reject_requester", "pass1234", "leader", warehouse_id=1)
        self.create_user(
            "requester_reject_wa",
            "pass1234",
            "admin",
            warehouse_id=1,
            phone="081277766655",
            notify_whatsapp=1,
        )

        self.login("requester_reject_wa", "pass1234")
        _, product_id, variants_rows = self.create_product(variants="REJUSR")
        variant_id = variants_rows[0]["id"]

        adjust_response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "-2",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(adjust_response.status_code, 200)

        with self.app.app_context():
            db = get_db()
            approval = db.execute(
                "SELECT id, requested_by FROM approvals WHERE product_id=? ORDER BY id DESC LIMIT 1",
                (product_id,),
            ).fetchone()

        self.logout()
        self.login("leader_reject_requester", "pass1234")
        with patch("routes.approvals.notify_user") as mocked_notify_user:
            reject_response = self.client.post(
                f"/approvals/reject/{approval['id']}",
                data={"reason": "stok tidak sesuai"},
                follow_redirects=False,
            )

        self.assertEqual(reject_response.status_code, 302)
        mocked_notify_user.assert_called_once()
        self.assertEqual(mocked_notify_user.call_args.args[0], approval["requested_by"])
        self.assertIn("ditolak", mocked_notify_user.call_args.args[1].lower())
        self.assertIn("stok tidak sesuai", mocked_notify_user.call_args.args[2].lower())

    def test_role_event_mapping_includes_super_admin_for_attendance_and_approval_events(self):
        self.assertIn("super_admin", whatsapp_service.ROLE_EVENT_RECIPIENTS["attendance.activity"])
        self.assertIn("super_admin", whatsapp_service.ROLE_EVENT_RECIPIENTS["inventory.inbound_approval_requested"])
        self.assertIn("super_admin", whatsapp_service.ROLE_EVENT_RECIPIENTS["inventory.outbound_approval_requested"])
        self.assertIn("super_admin", whatsapp_service.ROLE_EVENT_RECIPIENTS["inventory.adjust_approval_requested"])
        self.assertIn("super_admin", whatsapp_service.ROLE_EVENT_RECIPIENTS["inventory.approval_approved"])
        self.assertIn("super_admin", whatsapp_service.ROLE_EVENT_RECIPIENTS["inventory.approval_rejected"])

    def test_leader_bulk_adjust_rejects_zero_qty(self):
        self.create_user("leader_zero", "pass1234", "leader", warehouse_id=1)
        self.login("leader_zero", "pass1234")
        _, product_id, variants_rows = self.create_product(variants="ZERO")
        variant_id = variants_rows[0]["id"]

        response = self.client.post(
            "/stock/bulk-adjust",
            json={
                "items": [
                    {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "warehouse_id": 1,
                        "qty": 0,
                    }
                ]
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "error")

    def test_leader_ajax_adjust_returns_updated_qty_payload(self):
        self.create_user("leader_qty_payload", "pass1234", "leader", warehouse_id=1)
        self.login("leader_qty_payload", "pass1234")
        _, product_id, variants_rows = self.create_product(variants="QTYAJX")
        variant_id = variants_rows[0]["id"]

        response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "2",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["qty"], 7)

    def test_scoped_role_pages_lock_warehouse_inputs(self):
        for username, role in [
            ("admin_scope", "admin"),
            ("leader_scope", "leader"),
            ("staff_scope", "staff"),
        ]:
            employee_id = self.create_employee_record(
                employee_code=f"EMP-{role[:3].upper()}-SCOPE",
                full_name=f"{role.title()} Scope",
                warehouse_id=1,
                position=role.title(),
            )
            self.create_user(username, "pass1234", role, warehouse_id=1, employee_id=employee_id)
            self.login(username, "pass1234")

            for path, marker in [
                ("/schedule/", 'name="warehouse" disabled'),
                ("/stock/?workspace=products", 'name="warehouse" disabled'),
                ("/request/", 'name="from_warehouse" required disabled'),
                ("/request/owner", 'name="warehouse_id" required disabled'),
                ("/inbound/", 'name="warehouse_id" required disabled'),
                ("/outbound/", 'name="warehouse_id" required disabled'),
                ("/transfers/", 'name="from_warehouse" required disabled'),
                ("/", 'id="warehouseSelect" class="pill-select" disabled'),
            ]:
                with self.subTest(role=role, path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(marker, response.get_data(as_text=True))

            schedule_response = self.client.get("/schedule/")
            self.assertEqual(schedule_response.status_code, 200)
            schedule_html = schedule_response.get_data(as_text=True)
            self.assertIn("View Only", schedule_html)
            self.assertNotIn("Atur Jadwal Manual", schedule_html)

            request_response = self.client.get("/request/")
            self.assertEqual(request_response.status_code, 200)
            request_html = request_response.get_data(as_text=True)
            self.assertIn('name="to_warehouse" required disabled', request_html)

            if role in {"leader", "admin"}:
                crm_response = self.client.get("/crm/")
                self.assertEqual(crm_response.status_code, 200)
                crm_html = crm_response.get_data(as_text=True)
                self.assertIn('name="warehouse" disabled', crm_html)
                self.assertIn('name="warehouse_id" required disabled', crm_html)

                leave_response = self.client.get("/libur/")
                self.assertEqual(leave_response.status_code, 200)
                leave_html = leave_response.get_data(as_text=True)
                self.assertIn("Ajukan Libur", leave_html)
                self.assertNotIn('name="status"', leave_html)

                helpdesk_response = self.client.get("/hris/helpdesk")
                self.assertEqual(helpdesk_response.status_code, 200)
                helpdesk_html = helpdesk_response.get_data(as_text=True)
                self.assertIn('name="warehouse" disabled', helpdesk_html)
                self.assertIn(f'value="{employee_id}"', helpdesk_html)

                biometric_response = self.client.get("/absen/")
                self.assertEqual(biometric_response.status_code, 200)
                biometric_html = biometric_response.get_data(as_text=True)
                self.assertIn("Foto Absen", biometric_html)
                self.assertIn("Riwayat Absen Sebelumnya", biometric_html)

                for blocked_path in [
                    "/hris/leave",
                    "/hris/approval",
                    "/hris/biometric",
                    "/hris/employee",
                    "/hris/attendance",
                    "/hris/payroll",
                    "/hris/recruitment",
                    "/hris/onboarding",
                    "/hris/offboarding",
                    "/hris/pms",
                    "/hris/asset",
                    "/hris/project",
                    "/hris/announcement",
                    "/hris/documents",
                    "/hris/report",
                ]:
                    blocked_response = self.client.get(blocked_path, follow_redirects=False)
                    self.assertEqual(blocked_response.status_code, 302)
                    expected_target = (
                        "/libur/"
                        if blocked_path == "/hris/leave"
                        else "/absen/"
                        if blocked_path in {"/hris/biometric", "/hris/attendance"}
                        else "/hris/helpdesk"
                    )
                    self.assertIn(expected_target, blocked_response.headers["Location"])
            else:
                dashboard_response = self.client.get("/")
                dashboard_html = dashboard_response.get_data(as_text=True)
                self.assertIn('/libur/', dashboard_html)
                self.assertNotIn('>CRM<', dashboard_html)
                self.assertNotIn('>HRIS<', dashboard_html)

                staff_hris_root = self.client.get("/hris/", follow_redirects=False)
                self.assertEqual(staff_hris_root.status_code, 200)

                leave_response = self.client.get("/libur/")
                self.assertEqual(leave_response.status_code, 200)
                self.assertIn("Ajukan Libur", leave_response.get_data(as_text=True))

                helpdesk_response = self.client.get("/hris/helpdesk")
                self.assertEqual(helpdesk_response.status_code, 200)
                self.assertIn(f'value="{employee_id}"', helpdesk_response.get_data(as_text=True))

                biometric_response = self.client.get("/absen/")
                self.assertEqual(biometric_response.status_code, 200)
                self.assertIn("Foto Absen", biometric_response.get_data(as_text=True))

                staff_hris_module = self.client.get("/hris/employee", follow_redirects=False)
                self.assertEqual(staff_hris_module.status_code, 302)
                self.assertIn("/hris/helpdesk", staff_hris_module.headers["Location"])

                staff_leave_module = self.client.get("/hris/leave", follow_redirects=False)
                self.assertEqual(staff_leave_module.status_code, 302)
                self.assertIn("/libur/", staff_leave_module.headers["Location"])

                staff_biometric_module = self.client.get("/hris/biometric", follow_redirects=False)
                self.assertEqual(staff_biometric_module.status_code, 302)
                self.assertIn("/absen/", staff_biometric_module.headers["Location"])

                staff_crm_root = self.client.get("/crm/", follow_redirects=False)
                self.assertEqual(staff_crm_root.status_code, 302)
                self.assertIn("/schedule/", staff_crm_root.headers["Location"])
                self.assertIn("/libur/", schedule_html)
                self.assertNotIn("/hris/offboarding", schedule_html)

            self.logout()

    def test_scoped_hris_roles_are_limited_to_self_service_modules_and_own_employee(self):
        own_employee_id = self.create_employee_record(
            employee_code="EMP-STF-HRIS",
            full_name="Staff Self Service",
            warehouse_id=1,
            position="Warehouse Staff",
        )
        self.create_user("staff_hris_self", "pass1234", "staff", warehouse_id=1, employee_id=own_employee_id)
        self.login("staff_hris_self", "pass1234")

        blocked_response = self.client.get("/hris/payroll", follow_redirects=False)
        self.assertEqual(blocked_response.status_code, 302)
        self.assertIn("/hris/helpdesk", blocked_response.headers["Location"])

        leave_response = self.client.post(
            "/libur/submit",
            data={
                "leave_type": "sick",
                "start_date": "2026-04-10",
                "end_date": "2026-04-10",
                "reason": "Tes pembatasan",
                "note": "Tidak boleh untuk employee lain",
            },
            follow_redirects=False,
        )
        self.assertEqual(leave_response.status_code, 302)

        helpdesk_response = self.client.post(
            "/hris/helpdesk/add",
            data={
                "employee_id": str(own_employee_id),
                "ticket_title": "Scanner error",
                "category": "system",
                "priority": "medium",
                "status": "open",
                "channel": "WA",
                "assigned_to": "IT Support",
                "note": "Perlu dicek",
            },
            follow_redirects=False,
        )
        self.assertEqual(helpdesk_response.status_code, 302)

        biometric_response = self.client.post(
            "/absen/submit",
            data={
                "location_label": "Gudang Mataram - Self Service",
                "latitude": "-8.583140",
                "longitude": "116.116798",
                "accuracy_m": "10",
                "punch_time": "2026-09-01T08:10",
                "punch_type": "check_in",
                "note": "Check in staff",
                "photo_data_url": self.build_camera_photo_data_url(),
            },
            follow_redirects=False,
        )
        self.assertEqual(biometric_response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            leave_request = db.execute(
                "SELECT employee_id, status, reason FROM leave_requests ORDER BY id DESC LIMIT 1"
            ).fetchone()
            helpdesk = db.execute(
                "SELECT employee_id, ticket_title FROM helpdesk_tickets ORDER BY id DESC LIMIT 1"
            ).fetchone()
            biometric = db.execute(
                "SELECT employee_id, location_label FROM biometric_logs ORDER BY id DESC LIMIT 1"
            ).fetchone()

        self.assertIsNotNone(leave_request)
        self.assertEqual(leave_request["employee_id"], own_employee_id)
        self.assertEqual(leave_request["status"], "pending")
        self.assertEqual(leave_request["reason"], "Tes pembatasan")
        self.assertIsNotNone(helpdesk)
        self.assertEqual(helpdesk["employee_id"], own_employee_id)
        self.assertEqual(helpdesk["ticket_title"], "Scanner error")
        self.assertIsNotNone(biometric)
        self.assertEqual(biometric["employee_id"], own_employee_id)
        self.assertEqual(biometric["location_label"], "Gudang Mataram - Self Service")

    def test_staff_only_can_view_schedule_and_cannot_customize(self):
        self.create_user("staff_schedule_only", "pass1234", "staff", warehouse_id=1)
        employee_id = self.create_employee_record(
            employee_code="EMP-STF-SCH",
            full_name="Staff Jadwal",
            warehouse_id=1,
            position="Warehouse Staff",
        )

        self.login("staff_schedule_only", "pass1234")

        response = self.client.post(
            "/schedule/entry/save",
            data={
                "employee_id": str(employee_id),
                "shift_code": "P",
                "entry_start_date": "2026-03-30",
                "entry_end_date": "2026-03-30",
                "note": "Tidak boleh lolos",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/schedule/", response.headers["Location"])

        with self.app.app_context():
            db = get_db()
            entry_count = db.execute(
                """
                SELECT COUNT(*)
                FROM schedule_entries
                WHERE employee_id=? AND schedule_date='2026-03-30'
                """,
                (employee_id,),
            ).fetchone()[0]

        self.assertEqual(entry_count, 0)

    def test_staff_cannot_access_admin_surfaces_and_adjust_creates_approval(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="STF")
        variant_id = variants_rows[0]["id"]
        self.logout()

        self.create_user("staff_ops", "pass1234", "staff", warehouse_id=1)
        self.login("staff_ops", "pass1234")

        for path in ["/admin/", "/admin/warehouses", "/audit/", "/approvals/"]:
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)

        stock_page = self.client.get("/stock/")
        self.assertEqual(stock_page.status_code, 200)
        stock_html = stock_page.get_data(as_text=True)
        self.assertNotIn('class="adjust-input"', stock_html)
        self.assertNotIn("Adjust Terpilih", stock_html)

        adjust_response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "-1",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(adjust_response.status_code, 200)
        self.assertEqual(adjust_response.get_json()["status"], "pending")

        with self.app.app_context():
            db = get_db()
            approval = db.execute(
                """
                SELECT status, type
                FROM approvals
                WHERE product_id=? AND variant_id=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (product_id, variant_id),
            ).fetchone()

        self.assertIsNotNone(approval)
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["type"], "ADJUST")

    def test_staff_cannot_manage_product_master(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="LOCK")
        variant_id = variants_rows[0]["id"]
        self.logout()

        self.create_user("staff_master_lock", "pass1234", "staff", warehouse_id=1)
        self.login("staff_master_lock", "pass1234")

        products_page = self.client.get("/stock/?workspace=products")
        self.assertEqual(products_page.status_code, 200)
        products_html = products_page.get_data(as_text=True)
        self.assertNotIn("Tambah Produk", products_html)
        self.assertNotIn("Hapus Terpilih", products_html)

        add_response = self.client.post(
            "/products/add",
            data={
                "sku": "STAFF-BLOCKED",
                "name": "Produk Staff",
                "category_name": "Testing",
                "warehouse_id": "1",
                "variants": "S",
                "qty": "1",
            },
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
            },
            follow_redirects=False,
        )
        self.assertEqual(add_response.status_code, 403)
        self.assertEqual(add_response.get_json()["status"], "error")

        update_response = self.client.post(
            "/stock/update-field",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "field": "name",
                "value": "Tidak boleh diubah",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(update_response.get_json()["status"], "error")

        preview_response = self.client.post(
            "/products/import/preview",
            data={
                "file": (BytesIO(b"sku,name,category,qty\nA-1,Produk,Cat,1\n"), "products.csv"),
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        self.assertEqual(preview_response.status_code, 403)
        self.assertEqual(preview_response.get_json()["status"], "error")

        bulk_delete_response = self.client.post(
            "/products/bulk-delete",
            json={"ids": [product_id]},
            follow_redirects=False,
        )
        self.assertEqual(bulk_delete_response.status_code, 403)
        self.assertEqual(bulk_delete_response.get_json()["status"], "error")

        update_detail_response = self.client.post(
            "/stock/update-detail",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "sku": "STAFF-DETAIL",
                "name": "Produk Staff Detail",
                "category_name": "Testing",
                "variant": "LOCK",
                "price_retail": "100000",
                "price_discount": "90000",
                "price_nett": "85000",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(update_detail_response.status_code, 403)
        self.assertEqual(update_detail_response.get_json()["status"], "error")

    def test_manage_product_master_can_update_detail_from_stock_context(self):
        self.login()
        response, product_id, variants_rows = self.create_product(
            sku="CTX-EDIT-001",
            variants="CTX-42",
            qty=2,
        )
        self.assertEqual(response.status_code, 302)
        variant_id = variants_rows[0]["id"]

        update_response = self.client.post(
            "/stock/update-detail",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "sku": "CTX-EDIT-UPDATED",
                "name": "Produk Context Update",
                "category_name": "Sepatu Premium",
                "variant": "CTX-43",
                "price_retail": "250000",
                "price_discount": "220000",
                "price_nett": "199000",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )

        self.assertEqual(update_response.status_code, 200)
        payload = update_response.get_json()
        self.assertEqual(payload["status"], "success")

        with self.app.app_context():
            db = get_db()
            updated_row = db.execute(
                """
                SELECT
                    p.sku,
                    p.name,
                    c.name AS category_name,
                    v.variant,
                    v.price_retail,
                    v.price_discount,
                    v.price_nett
                FROM products p
                LEFT JOIN categories c ON c.id = p.category_id
                LEFT JOIN product_variants v ON v.product_id = p.id
                WHERE p.id=? AND v.id=?
                """,
                (product_id, variant_id),
            ).fetchone()

        self.assertEqual(updated_row["sku"], "CTX-EDIT-UPDATED")
        self.assertEqual(updated_row["name"], "Produk Context Update")
        self.assertEqual(updated_row["category_name"], "Sepatu Premium")
        self.assertEqual(updated_row["variant"], "CTX-43")
        self.assertEqual(updated_row["price_retail"], 250000)
        self.assertEqual(updated_row["price_discount"], 220000)
        self.assertEqual(updated_row["price_nett"], 199000)

    def test_request_check_new_ignores_restored_pending_requests(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="REQ")
        variant_id = variants_rows[0]["id"]
        self.logout()

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO requests(
                    product_id,
                    variant_id,
                    from_warehouse,
                    to_warehouse,
                    qty,
                    status
                )
                VALUES (?,?,?,?,?,?)
                """,
                (product_id, variant_id, 1, 2, 1, "pending"),
            )
            db.commit()

        self.create_user("leader_notify", "pass1234", "leader", warehouse_id=1)
        self.login("leader_notify", "pass1234")

        first_check = self.client.get("/request/check_new?last_id=0")
        self.assertEqual(first_check.status_code, 200)
        self.assertEqual(first_check.get_json()["status"], "no")

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                INSERT INTO requests(
                    product_id,
                    variant_id,
                    from_warehouse,
                    to_warehouse,
                    qty,
                    status
                )
                VALUES (?,?,?,?,?,?)
                """,
                (product_id, variant_id, 1, 2, 2, "pending"),
            )
            db.commit()

        second_check = self.client.get("/request/check_new?last_id=0")
        self.assertEqual(second_check.status_code, 200)
        self.assertEqual(second_check.get_json()["status"], "yes")

    def test_restore_repair_creates_batches_for_legacy_stock(self):
        self.create_user("restore_super", "admin123", "super_admin")
        self.login("restore_super", "admin123")
        _, product_id, variants_rows = self.create_product(variants="LEGACY")
        variant_id = variants_rows[0]["id"]

        with self.app.app_context():
            db = get_db()
            db.execute(
                "DELETE FROM stock_batches WHERE product_id=? AND variant_id=? AND warehouse_id=?",
                (product_id, variant_id, 1),
            )
            db.execute(
                """
                UPDATE stock
                SET qty=?
                WHERE product_id=? AND variant_id=? AND warehouse_id=?
                """,
                (7, product_id, variant_id, 1),
            )
            db.commit()

        repair_restored_data(self.app)

        with self.app.app_context():
            db = get_db()
            batch = db.execute(
                """
                SELECT qty, remaining_qty
                FROM stock_batches
                WHERE product_id=? AND variant_id=? AND warehouse_id=?
                """,
                (product_id, variant_id, 1),
            ).fetchone()

        self.assertIsNotNone(batch)
        self.assertEqual(batch["qty"], 7)
        self.assertEqual(batch["remaining_qty"], 7)

        adjust_response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "-2",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(adjust_response.status_code, 200)
        self.assertEqual(adjust_response.get_json()["status"], "success")

    def test_restore_repair_promotes_rio_to_super_admin(self):
        self.create_user("Rio", "admin123", "admin", warehouse_id=1)

        repair_restored_data(self.app)

        with self.app.app_context():
            db = get_db()
            rio = db.execute(
                "SELECT role, warehouse_id FROM users WHERE username=?",
                ("Rio",),
            ).fetchone()

        self.assertIsNotNone(rio)
        self.assertEqual(rio["role"], "super_admin")
        self.assertIsNone(rio["warehouse_id"])

    def test_restore_repair_uses_configurable_bootstrap_accounts(self):
        self.app.config["RESTORE_SUPER_ADMINS"] = ["customroot"]
        self.app.config["RESTORE_BOOTSTRAP_ADMINS"] = ["opsadmin"]
        self.app.config["RESTORE_BOOTSTRAP_LEADERS"] = ["opsleader"]

        self.create_user("customroot", "admin123", "staff", warehouse_id=1)
        self.create_user("opsadmin", "admin123", "staff", warehouse_id=2)
        self.create_user("opsleader", "admin123", "staff", warehouse_id=2)

        repair_restored_data(self.app)

        with self.app.app_context():
            db = get_db()
            root_user = db.execute(
                "SELECT role, warehouse_id FROM users WHERE username=?",
                ("customroot",),
            ).fetchone()
            admin_user = db.execute(
                "SELECT role, warehouse_id FROM users WHERE username=?",
                ("opsadmin",),
            ).fetchone()
            leader_user = db.execute(
                "SELECT role, warehouse_id FROM users WHERE username=?",
                ("opsleader",),
            ).fetchone()

        self.assertEqual(root_user["role"], "super_admin")
        self.assertIsNone(root_user["warehouse_id"])
        self.assertEqual(admin_user["role"], "admin")
        self.assertEqual(admin_user["warehouse_id"], 1)
        self.assertEqual(leader_user["role"], "leader")
        self.assertEqual(leader_user["warehouse_id"], 1)

    def test_stock_page_renders_rupiah_prefix_and_export(self):
        self.login()
        response, _, _ = self.create_product(variants="PRC")
        self.assertEqual(response.status_code, 302)

        page = self.client.get("/stock/")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("money-input", html)
        self.assertIn(">Rp<", html)

        export = self.client.get("/stock/export")
        self.assertEqual(export.status_code, 200)
        self.assertIn("text/csv", export.content_type)
        self.assertIn("Harga Retail", export.get_data(as_text=True))

    def test_stock_page_supports_clickable_header_sorting(self):
        self.login()
        response, _, _ = self.create_product(sku="SORT-ZZZ", qty=1, variants="VZ")
        self.assertEqual(response.status_code, 302)
        response, _, _ = self.create_product(sku="SORT-AAA", qty=1, variants="VA")
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            db = get_db()
            older_product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                ("SORT-ZZZ",),
            ).fetchone()["id"]
            newer_product = db.execute(
                "SELECT id FROM products WHERE sku=?",
                ("SORT-AAA",),
            ).fetchone()["id"]
            db.execute(
                "UPDATE stock_batches SET created_at=? WHERE product_id=?",
                ("2024-01-01 00:00:00", older_product),
            )
            db.execute(
                "UPDATE stock_batches SET created_at=? WHERE product_id=?",
                ("2026-01-01 00:00:00", newer_product),
            )
            db.commit()

        stock_sku_asc = self.client.get("/stock/?sort=sku_asc")
        self.assertEqual(stock_sku_asc.status_code, 200)
        html_sku_asc = stock_sku_asc.get_data(as_text=True)
        self.assertIn("sort=sku_desc", html_sku_asc)
        self.assertLess(html_sku_asc.find('value="SORT-AAA"'), html_sku_asc.find('value="SORT-ZZZ"'))

        stock_sku_desc = self.client.get("/stock/?sort=sku_desc")
        self.assertEqual(stock_sku_desc.status_code, 200)
        html_sku_desc = stock_sku_desc.get_data(as_text=True)
        self.assertLess(html_sku_desc.find('value="SORT-ZZZ"'), html_sku_desc.find('value="SORT-AAA"'))

        stock_age_desc = self.client.get("/stock/?sort=age_desc")
        self.assertEqual(stock_age_desc.status_code, 200)
        html_age_desc = stock_age_desc.get_data(as_text=True)
        self.assertIn("sort=age_asc", html_age_desc)
        self.assertLess(html_age_desc.find('value="SORT-ZZZ"'), html_age_desc.find('value="SORT-AAA"'))

        stock_age_asc = self.client.get("/stock/?sort=age_asc")
        self.assertEqual(stock_age_asc.status_code, 200)
        html_age_asc = stock_age_asc.get_data(as_text=True)
        self.assertLess(html_age_asc.find('value="SORT-AAA"'), html_age_asc.find('value="SORT-ZZZ"'))

    def test_owner_can_access_admin_page(self):
        self.create_user("owner_user", "pass1234", "owner")
        self.login("owner_user", "pass1234")
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_owner_admin_page_focuses_on_access_and_roles(self):
        self.create_user("owner_access", "pass1234", "owner")
        self.login("owner_access", "pass1234")
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Admin Access Center", html)
        self.assertIn("Role Guide", html)
        self.assertIn("Tambah User", html)
        self.assertNotIn("Tambah Gudang", html)
        self.assertNotIn("Daftar Gudang", html)

    def test_owner_can_access_admin_warehouse_page(self):
        self.create_user("owner_wh", "pass1234", "owner")
        self.login("owner_wh", "pass1234")
        response = self.client.get("/admin/warehouses")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Warehouse System Control", html)
        self.assertIn("Tambah Gudang", html)
        self.assertIn("Daftar Gudang", html)
        self.assertNotIn("Tambah User", html)

    def test_admin_cannot_access_admin_page(self):
        self.login()
        response = self.client.get("/admin/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_admin_cannot_access_admin_warehouse_page(self):
        self.login()
        response = self.client.get("/admin/warehouses", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_owner_can_access_audit_page(self):
        self.create_user("owner_audit", "pass1234", "owner")
        self.login("owner_audit", "pass1234")
        response = self.client.get("/audit/")
        self.assertEqual(response.status_code, 200)

    def test_audit_page_groups_import_rows_by_series_with_variant_dropdown(self):
        self.create_user("owner_audit_group", "pass1234", "owner")

        with self.app.app_context():
            db = get_db()
            warehouse = db.execute("SELECT id FROM warehouses ORDER BY id LIMIT 1").fetchone()
            warehouse_id = warehouse["id"]

            db.execute(
                "INSERT INTO products(sku, name, category_id) VALUES (?,?,NULL)",
                ("B/S-ADIDAS-00003", "B/S EPP CLB"),
            )
            product_one = db.execute(
                "SELECT id FROM products WHERE sku=?",
                ("B/S-ADIDAS-00003",),
            ).fetchone()
            db.execute(
                "INSERT INTO product_variants(product_id, variant) VALUES (?,?)",
                (product_one["id"], "PINK"),
            )
            variant_one = db.execute(
                "SELECT id FROM product_variants WHERE product_id=? AND variant=?",
                (product_one["id"], "PINK"),
            ).fetchone()

            db.execute(
                "INSERT INTO products(sku, name, category_id) VALUES (?,?,NULL)",
                ("B/S-ADIDAS-00004", "B/S EPP CLB"),
            )
            product_two = db.execute(
                "SELECT id FROM products WHERE sku=?",
                ("B/S-ADIDAS-00004",),
            ).fetchone()
            db.execute(
                "INSERT INTO product_variants(product_id, variant) VALUES (?,?)",
                (product_two["id"], "BIRU"),
            )
            variant_two = db.execute(
                "SELECT id FROM product_variants WHERE product_id=? AND variant=?",
                (product_two["id"], "BIRU"),
            ).fetchone()

            user = db.execute(
                "SELECT id FROM users WHERE username=?",
                ("owner_audit_group",),
            ).fetchone()

            for product_id, variant_id, qty in (
                (product_one["id"], variant_one["id"], 4),
                (product_two["id"], variant_two["id"], 6),
            ):
                db.execute(
                    """
                    INSERT INTO stock_history(
                        product_id,
                        variant_id,
                        warehouse_id,
                        action,
                        type,
                        qty,
                        note,
                        user_id,
                        ip_address,
                        user_agent,
                        date
                    )
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        product_id,
                        variant_id,
                        warehouse_id,
                        "IMPORT",
                        "IN",
                        qty,
                        "Bulk Import",
                        user["id"],
                        "127.0.0.1",
                        "pytest",
                        "2026-03-31 13:15:47",
                    ),
                )
            db.commit()

        self.login("owner_audit_group", "pass1234")
        response = self.client.get("/audit/?action=IMPORT")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("2 varian", html)
        self.assertIn("Kategori Warna", html)
        self.assertIn("PINK", html)
        self.assertIn("BIRU", html)
        self.assertIn("B/S EPP CLB", html)

    def test_stock_opname_page_supports_selected_warehouses_and_exports(self):
        self.login()
        response = self.client.get("/so/?display_id=1&gudang_id=2")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="display_id"', html)
        self.assertIn('name="gudang_id"', html)
        self.assertIn("/so/export?display_id=1&gudang_id=2", html)
        self.assertIn("Simpan Hasil SO", html)

        export = self.client.get("/so/export?display_id=1&gudang_id=2")
        self.assertEqual(export.status_code, 200)
        self.assertIn("Display System Qty", export.get_data(as_text=True))

    def test_stock_opname_summary_counts_all_filtered_rows_not_just_current_page(self):
        self.login()

        for index in range(21):
            response, _, _ = self.create_product(
                sku=f"SO-SUM-{index:02d}",
                qty=1,
                variants=f"VAR{index}",
                warehouse_id="1",
            )
            self.assertEqual(response.status_code, 302)

        response = self.client.get(
            "/so/?display_id=1&gudang_id=2",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertEqual(len(payload["data"]), 20)
        self.assertEqual(payload["summary"]["items"], 21)
        self.assertEqual(payload["summary"]["display_qty"], 21)
        self.assertEqual(payload["summary"]["gudang_qty"], 0)
        self.assertEqual(payload["total_pages"], 2)

    def test_role_refresh_allows_promoted_user_to_adjust_directly(self):
        self.create_user("Rio", "admin123", "admin", warehouse_id=1)
        self.login("Rio", "admin123")
        _, product_id, variants_rows = self.create_product(variants="RIO")
        variant_id = variants_rows[0]["id"]

        with self.app.app_context():
            db = get_db()
            db.execute(
                "UPDATE users SET role=? WHERE username=?",
                ("super_admin", "Rio"),
            )
            db.commit()

        stock_page = self.client.get("/stock/", follow_redirects=False)
        self.assertEqual(stock_page.status_code, 200)

        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("role"), "super_admin")

        adjust_response = self.client.post(
            "/stock/adjust",
            data={
                "product_id": str(product_id),
                "variant_id": str(variant_id),
                "warehouse_id": "1",
                "qty": "-2",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
            follow_redirects=False,
        )
        self.assertEqual(adjust_response.status_code, 200)
        self.assertEqual(adjust_response.get_json()["status"], "success")

        with self.app.app_context():
            db = get_db()
            approvals = db.execute(
                "SELECT COUNT(*) FROM approvals WHERE product_id=?",
                (product_id,),
            ).fetchone()[0]
            stock_after = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product_id, variant_id),
            ).fetchone()

        self.assertEqual(approvals, 0)
        self.assertEqual(stock_after["qty"], 3)

    def test_stock_opname_submit_updates_stock_and_history(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="SO")
        variant_id = variants_rows[0]["id"]

        response = self.client.post(
            "/so/submit",
            json={
                "display_id": 1,
                "gudang_id": 2,
                "items": [
                    {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "display_system": 5,
                        "display_physical": 3,
                        "gudang_system": 0,
                        "gudang_physical": 2,
                    }
                ],
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            db = get_db()
            display_stock = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product_id, variant_id),
            ).fetchone()
            gudang_stock = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=2",
                (product_id, variant_id),
            ).fetchone()
            so_rows = db.execute(
                "SELECT COUNT(*) FROM stock_opname_results WHERE product_id=? AND variant_id=?",
                (product_id, variant_id),
            ).fetchone()[0]
            history_rows = db.execute(
                "SELECT COUNT(*) FROM stock_history WHERE product_id=? AND variant_id=? AND action='STOCK_OPNAME'",
                (product_id, variant_id),
            ).fetchone()[0]

        self.assertEqual(display_stock["qty"], 3)
        self.assertEqual(gudang_stock["qty"], 2)
        self.assertEqual(so_rows, 2)
        self.assertEqual(history_rows, 2)

    def test_stock_opname_submit_uses_latest_server_stock_and_returns_refresh_payload(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="SOREF")
        variant_id = variants_rows[0]["id"]

        with self.app.app_context():
            db = get_db()
            db.execute(
                """
                UPDATE stock
                SET qty=?
                WHERE product_id=? AND variant_id=? AND warehouse_id=1
                """,
                (8, product_id, variant_id),
            )
            db.commit()

        response = self.client.post(
            "/so/submit",
            json={
                "display_id": 1,
                "gudang_id": 2,
                "page": 1,
                "q": "",
                "items": [
                    {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "display_system": 5,
                        "display_physical": 6,
                        "gudang_system": 0,
                        "gudang_physical": 0,
                    }
                ],
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["processed"], 1)
        self.assertIn("summary", payload)
        self.assertIn("data", payload)

        with self.app.app_context():
            db = get_db()
            so_row = db.execute(
                """
                SELECT system_qty, physical_qty, diff_qty
                FROM stock_opname_results
                WHERE product_id=? AND variant_id=? AND warehouse_id=1
                ORDER BY id DESC
                LIMIT 1
                """,
                (product_id, variant_id),
            ).fetchone()
            display_stock = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product_id, variant_id),
            ).fetchone()

        self.assertIsNotNone(so_row)
        self.assertEqual(so_row["system_qty"], 8)
        self.assertEqual(so_row["physical_qty"], 6)
        self.assertEqual(so_row["diff_qty"], -2)
        self.assertEqual(display_stock["qty"], 6)

    def test_stock_opname_submit_returns_success_when_stock_already_synced(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="SOSYNC")
        variant_id = variants_rows[0]["id"]

        response = self.client.post(
            "/so/submit",
            json={
                "display_id": 1,
                "gudang_id": 2,
                "page": 1,
                "q": "",
                "items": [
                    {
                        "product_id": product_id,
                        "variant_id": variant_id,
                        "display_system": 1,
                        "display_physical": 5,
                        "gudang_system": 0,
                        "gudang_physical": 0,
                    }
                ],
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["processed"], 0)
        self.assertIn("stok sudah sinkron", payload["message"].lower())


if __name__ == "__main__":
    unittest.main()
