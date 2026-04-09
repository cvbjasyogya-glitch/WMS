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


if __name__ == "__main__":
    unittest.main()
