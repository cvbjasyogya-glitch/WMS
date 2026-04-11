import importlib.util
import logging
from pathlib import Path
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "desktop"
    / "windows_kasir"
    / "app.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("windows_kasir_app", MODULE_PATH)
windows_kasir_app = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC.loader is not None
MODULE_SPEC.loader.exec_module(windows_kasir_app)


class WindowsKasirAppTestCase(unittest.TestCase):
    def test_append_query_params_keeps_existing_query_and_adds_bridge(self):
        result = windows_kasir_app._append_query_params(
            "https://erp.test/kasir/?source=desktop-kasir",
            {"desktop_bridge": "http://127.0.0.1:17844"},
        )

        self.assertIn("source=desktop-kasir", result)
        self.assertIn("desktop_bridge=http%3A%2F%2F127.0.0.1%3A17844", result)

    def test_runtime_build_runtime_url_includes_source_and_bridge(self):
        runtime = windows_kasir_app.DesktopRuntime(
            config=dict(windows_kasir_app.DEFAULT_CONFIG),
            logger=logging.getLogger("windows_kasir_app_test"),
        )
        runtime.attach_bridge_base_url("http://127.0.0.1:17844")

        url = runtime.build_runtime_url("kasir")

        self.assertIn("/kasir/", url)
        self.assertIn("source=desktop-kasir", url)
        self.assertIn("desktop_bridge=http%3A%2F%2F127.0.0.1%3A17844", url)

    def test_resolve_preferred_printer_name_supports_partial_match(self):
        snapshot = {
            "ok": True,
            "default_printer": "Microsoft Print to PDF",
            "printers": [
                {"Name": "Xprinter XP-80C"},
                {"Name": "Microsoft Print to PDF"},
            ],
            "error": "",
        }

        matched = windows_kasir_app.resolve_preferred_printer_name(snapshot, "xprinter")

        self.assertEqual(matched, "Xprinter XP-80C")

    def test_build_thermal_receipt_text_compacts_store_copy(self):
        receipt_text = windows_kasir_app.build_thermal_receipt_text(
            {
                "receipt_copy": "store",
                "copy_label": "Copy Toko",
                "store_name": "Mataram Sports",
                "business_address": "Jl. Mataram No. 1, Cakranegara",
                "receipt_no": "POS-20260411-0001",
                "cashier_name": "Rio",
                "customer_name": "UMUM",
                "sale_datetime": "2026-04-11 19:50",
                "payment_method": "debit",
                "payment_method_label": "DEBIT",
                "total_items": 3,
                "subtotal_amount_label": "Rp 555.000",
                "discount_amount_label": "Rp 0",
                "tax_amount_label": "Rp 0",
                "total_amount_label": "Rp 555.000",
                "paid_amount_label": "Rp 555.000",
                "change_amount_label": "Rp 0",
                "store_copy_note": "Arsip kasir Mataram Sports. DEBIT | 3 item",
                "thank_you_text": "",
                "feedback_line": "",
                "social_label": "",
                "social_media_url": "",
                "items": [
                    {
                        "product_name": "Teidon 5 x 12 meter",
                        "variant_name": "default",
                        "sku": "999998",
                        "active_qty": 3,
                        "unit_price_label": "185.000",
                        "active_line_total_label": "555.000",
                        "void_qty": 0,
                        "void_amount_label": "Rp 0",
                    }
                ],
            },
            width=32,
        )

        self.assertIn("Mataram Sports", receipt_text)
        self.assertIn("Copy Toko", receipt_text)
        self.assertIn("Grand Total", receipt_text)
        self.assertIn("Metode DEBIT", receipt_text)
        self.assertNotIn("Jl. Mataram No. 1, Cakranegara", receipt_text)
        self.assertNotIn("Arsip kasir", receipt_text)
        self.assertLessEqual(len(receipt_text.splitlines()), 16)


if __name__ == "__main__":
    unittest.main()
