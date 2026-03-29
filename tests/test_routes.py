import os
import unittest
from io import BytesIO
from uuid import uuid4
import zipfile

import init_db as init_db_module
from app import create_app, repair_restored_data
from config import Config
from database import get_db
from werkzeug.security import generate_password_hash


class WmsRoutesTestCase(unittest.TestCase):
    def setUp(self):
        temp_root = os.path.join(os.path.dirname(__file__), ".tmp")
        os.makedirs(temp_root, exist_ok=True)
        self.db_path = os.path.join(temp_root, f"test_database_{uuid4().hex}.db")

        init_db_module.DB_PATH = self.db_path
        Config.DATABASE = self.db_path
        Config.SESSION_COOKIE_SECURE = False

        self.app = create_app()
        self.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = self.app.test_client()

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            db_file = self.db_path + suffix
            if os.path.exists(db_file):
                os.remove(db_file)

    def login(self, username="admin", password="admin123"):
        return self.client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def logout(self):
        return self.client.get("/logout", follow_redirects=False)

    def create_user(
        self,
        username,
        password,
        role,
        warehouse_id=None,
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
                    email,
                    phone,
                    notify_email,
                    notify_whatsapp
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    username,
                    generate_password_hash(password),
                    role,
                    warehouse_id,
                    email,
                    phone,
                    notify_email,
                    notify_whatsapp,
                ),
            )
            db.commit()

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
            "/",
            "/products/",
            "/stock/",
            "/inbound/",
            "/outbound/",
            "/transfers/",
            "/request/",
            "/audit/",
            "/so/",
            "/admin/",
        ]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn('name="viewport"', html)
                self.assertIn('mobile-nav', html)

    def test_add_product_and_get_variants(self):
        self.login()
        response, product_id, variants_rows = self.create_product()

        self.assertEqual(response.status_code, 302)
        self.assertIsNotNone(product_id)
        self.assertEqual(len(variants_rows), 2)

        variants_response = self.client.get(f"/products/get_variants/{product_id}")
        self.assertEqual(variants_response.status_code, 200)
        self.assertEqual(len(variants_response.get_json()), 2)

    def test_request_approval_updates_stock(self):
        self.create_user("leader_request", "pass1234", "leader", warehouse_id=1)
        self.login()
        _, product_id, variants_rows = self.create_product(variants="XL")
        variant_id = variants_rows[0]["id"]

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

        self.assertEqual(request_row["status"], "pending")

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
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=1",
                (product_id, variant_id),
            ).fetchone()
            stock_to = db.execute(
                "SELECT qty FROM stock WHERE product_id=? AND variant_id=? AND warehouse_id=2",
                (product_id, variant_id),
            ).fetchone()

        self.assertEqual(request_after["status"], "approved")
        self.assertEqual(stock_from["qty"], 4)
        self.assertEqual(stock_to["qty"], 1)

    def test_admin_cannot_approve_request(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="APR")
        variant_id = variants_rows[0]["id"]

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

    def test_products_page_respects_selected_warehouse_for_super_admin(self):
        self.create_user("superboss", "admin123", "super_admin")
        self.login("superboss", "admin123")
        response, _, _ = self.create_product(variants="WH2", warehouse_id="2")
        self.assertEqual(response.status_code, 302)

        page = self.client.get("/products/?warehouse=2")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)

        self.assertIn('<option value="2" selected>', html)

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
        approve_response = self.client.post(
            f"/approvals/approve/{approval['id']}",
            follow_redirects=False,
        )
        self.assertEqual(approve_response.status_code, 302)

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

    def test_scoped_role_pages_lock_warehouse_inputs(self):
        for username, role in [
            ("leader_scope", "leader"),
            ("staff_scope", "staff"),
        ]:
            self.create_user(username, "pass1234", role, warehouse_id=1)
            self.login(username, "pass1234")

            for path, marker in [
                ("/products/", 'name="warehouse" disabled'),
                ("/request/", 'name="from_warehouse" required disabled'),
                ("/inbound/", 'name="warehouse_id" required disabled'),
                ("/outbound/", 'name="warehouse_id" required disabled'),
                ("/transfers/", 'name="from_warehouse" required disabled'),
                ("/", 'id="warehouseSelect" class="pill-select" disabled'),
            ]:
                with self.subTest(role=role, path=path):
                    response = self.client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(marker, response.get_data(as_text=True))

            self.logout()

    def test_staff_cannot_access_admin_surfaces_and_adjust_creates_approval(self):
        self.login()
        _, product_id, variants_rows = self.create_product(variants="STF")
        variant_id = variants_rows[0]["id"]
        self.logout()

        self.create_user("staff_ops", "pass1234", "staff", warehouse_id=1)
        self.login("staff_ops", "pass1234")

        for path in ["/admin/", "/audit/", "/approvals/"]:
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 302)

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

    def test_owner_can_access_admin_page(self):
        self.create_user("owner_user", "pass1234", "owner")
        self.login("owner_user", "pass1234")
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_owner_can_access_audit_page(self):
        self.create_user("owner_audit", "pass1234", "owner")
        self.login("owner_audit", "pass1234")
        response = self.client.get("/audit/")
        self.assertEqual(response.status_code, 200)

    def test_stock_opname_page_supports_selected_warehouses_and_exports(self):
        self.login()
        response = self.client.get("/so/?display_id=1&gudang_id=2")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('name="display_id"', html)
        self.assertIn('name="gudang_id"', html)
        self.assertIn("/so/export?display_id=1&gudang_id=2", html)

        export = self.client.get("/so/export?display_id=1&gudang_id=2")
        self.assertEqual(export.status_code, 200)
        self.assertIn("Display System Qty", export.get_data(as_text=True))

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


if __name__ == "__main__":
    unittest.main()
