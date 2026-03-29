import os
import tempfile
import unittest
from io import BytesIO
from uuid import uuid4

import init_db as init_db_module
from app import create_app
from config import Config
from database import get_db


class WmsRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_database.db")

        init_db_module.DB_PATH = self.db_path
        Config.DATABASE = self.db_path
        Config.SESSION_COOKIE_SECURE = False

        self.app = create_app()
        self.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def login(self, username="admin", password="admin123"):
        return self.client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def create_product(self, sku=None, qty=5, variants="M,L"):
        sku = sku or ("AUTO-" + uuid4().hex[:8].upper())

        response = self.client.post(
            "/products/add",
            data={
                "sku": sku,
                "name": "Produk Uji",
                "category_name": "Testing",
                "variants": variants,
                "qty": str(qty),
                "warehouse_id": "1",
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


if __name__ == "__main__":
    unittest.main()
