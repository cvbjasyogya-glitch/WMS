import unittest

from scripts.import_ipos4_dump import remember_product_cache_entry


class IposImportDumpTestCase(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
