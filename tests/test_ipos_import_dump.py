import sqlite3
import unittest

from scripts.import_ipos4_dump import (
    ensure_import_tables,
    import_products,
    remember_product_cache_entry,
    resolve_existing_import_product_match,
)


class IposImportDumpTestCase(unittest.TestCase):
    def _build_import_products_conn(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE categories(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE products(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT,
                name TEXT NOT NULL,
                category_id INTEGER,
                unit_label TEXT,
                variant_mode TEXT DEFAULT 'non_variant'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE product_variants(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                variant TEXT NOT NULL,
                price_retail REAL DEFAULT 0,
                price_discount REAL DEFAULT 0,
                price_nett REAL DEFAULT 0,
                variant_code TEXT,
                color TEXT,
                gtin TEXT,
                no_gtin INTEGER DEFAULT 1
            )
            """
        )
        ensure_import_tables(conn)
        self.addCleanup(conn.close)
        return conn

    def test_remember_product_cache_entry_updates_only_target_product_keys(self):
        existing_row = {
            "id": 1,
            "sku": "OLD-SKU",
            "name": "Produk Lama",
            "category_id": 10,
            "unit_label": "pcs",
        }
        other_row = {
            "id": 2,
            "sku": "KEEP-SKU",
            "name": "Produk Tetap",
            "category_id": 11,
            "unit_label": "pcs",
        }
        product_cache_by_id = {
            1: dict(existing_row),
            2: dict(other_row),
        }
        product_cache_by_sku = {
            "OLD-SKU": dict(existing_row),
            "KEEP-SKU": dict(other_row),
        }
        product_cache_by_name = {
            "produklama": [dict(existing_row)],
            "produktetap": [dict(other_row)],
        }

        updated_row = remember_product_cache_entry(
            product_cache_by_id,
            product_cache_by_sku,
            product_cache_by_name,
            {
                "id": 1,
                "sku": "NEW-SKU",
                "name": "Produk Baru",
                "category_id": 10,
                "unit_label": "pcs",
            },
        )

        self.assertEqual(updated_row["sku"], "NEW-SKU")
        self.assertEqual(product_cache_by_id[1]["name"], "Produk Baru")
        self.assertNotIn("OLD-SKU", product_cache_by_sku)
        self.assertIn("NEW-SKU", product_cache_by_sku)
        self.assertIn("KEEP-SKU", product_cache_by_sku)
        self.assertNotIn("produklama", product_cache_by_name)
        self.assertIn("produkbaru", product_cache_by_name)
        self.assertIn("produktetap", product_cache_by_name)

    def test_resolve_existing_import_product_match_collapses_multiple_name_matches(self):
        first_row = {
            "id": 7,
            "sku": "OLD-007",
            "name": "Sepatu Lari",
            "category_id": 1,
            "unit_label": "pcs",
        }
        second_row = {
            "id": 11,
            "sku": "OLD-011",
            "name": "Sepatu   Lari",
            "category_id": 1,
            "unit_label": "pcs",
        }
        product_cache_by_id = {
            7: dict(first_row),
            11: dict(second_row),
        }
        product_cache_by_sku = {
            "OLD-007": dict(first_row),
            "OLD-011": dict(second_row),
        }
        product_cache_by_name = {
            "sepatulari": [dict(second_row), dict(first_row)],
        }

        existing, match_type, has_multiple_name_matches = resolve_existing_import_product_match(
            product_cache_by_id,
            product_cache_by_sku,
            product_cache_by_name,
            linked_products={},
            mapped_product_ids=set(),
            sku="IPOS-NEW-1",
            name="Sepatu Lari",
        )

        self.assertIsNotNone(existing)
        self.assertEqual(existing["id"], 7)
        self.assertEqual(match_type, "name")
        self.assertTrue(has_multiple_name_matches)

    def test_resolve_existing_import_product_match_skips_already_mapped_name_candidates(self):
        old_row = {
            "id": 21,
            "sku": "OLD-021",
            "name": "Tas Futsal",
            "category_id": 1,
            "unit_label": "pcs",
        }
        mapped_row = {
            "id": 22,
            "sku": "OLD-022",
            "name": "Tas Futsal",
            "category_id": 1,
            "unit_label": "pcs",
        }

        existing, match_type, has_multiple_name_matches = resolve_existing_import_product_match(
            {21: dict(old_row), 22: dict(mapped_row)},
            {"OLD-021": dict(old_row), "OLD-022": dict(mapped_row)},
            {"tasfutsal": [dict(mapped_row), dict(old_row)]},
            linked_products={"IPOS-MAPPED": {"product_id": 22}},
            mapped_product_ids={22},
            sku="IPOS-BARU",
            name="Tas Futsal",
        )

        self.assertIsNotNone(existing)
        self.assertEqual(existing["id"], 21)
        self.assertEqual(match_type, "name")
        self.assertFalse(has_multiple_name_matches)

    def test_import_products_merges_duplicate_name_candidates_into_canonical_product(self):
        conn = self._build_import_products_conn()
        category_id = conn.execute(
            "INSERT INTO categories(name) VALUES (?)",
            ("Sepatu",),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO products(id, sku, name, category_id, unit_label, variant_mode)
            VALUES (?,?,?,?,?,?)
            """,
            (7, "OLD-007", "Sepatu Lari", category_id, "pcs", "non_variant"),
        )
        conn.execute(
            """
            INSERT INTO products(id, sku, name, category_id, unit_label, variant_mode)
            VALUES (?,?,?,?,?,?)
            """,
            (11, "OLD-011", "Sepatu   Lari", category_id, "pcs", "non_variant"),
        )
        summary = {
            "products_created": 0,
            "products_updated": 0,
            "products_merged_by_name": 0,
            "products_name_conflicts": 0,
            "products_skipped_unmapped": 0,
        }

        product_map, variant_cache = import_products(
            conn,
            [
                {
                    "kodeitem": "IPOS-NEW-1",
                    "namaitem": "Sepatu Lari",
                    "jenis": "Sepatu",
                    "satuan": "pcs",
                    "hargajual1": "150000",
                    "hargapokok": "110000",
                }
            ],
            summary,
        )

        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM products").fetchone()[0],
            2,
        )
        mapped_row = conn.execute(
            """
            SELECT source_item_code, product_id
            FROM ipos_import_product_map
            WHERE source_item_code=?
            """,
            ("IPOS-NEW-1",),
        ).fetchone()
        self.assertIsNotNone(mapped_row)
        self.assertEqual(mapped_row["product_id"], 7)
        self.assertEqual(product_map["IPOS-NEW-1"]["product_id"], 7)
        self.assertIn(7, variant_cache)
        self.assertEqual(summary["products_created"], 0)
        self.assertEqual(summary["products_updated"], 1)
        self.assertEqual(summary["products_merged_by_name"], 1)
        self.assertEqual(summary["products_name_conflicts"], 0)


if __name__ == "__main__":
    unittest.main()
