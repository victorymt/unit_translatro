import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from app_config import Settings
from pricing_catalog import PricingCatalog
from settings_store import (
    load_settings_document,
    resolve_tui_config_path,
    save_settings_document,
)


class SettingsStoreTests(unittest.TestCase):
    def test_missing_tui_document_is_seeded_without_creating_a_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "new-settings.toml"
            document = load_settings_document(path)
            self.assertFalse(document.exists)
            self.assertFalse(path.exists())
            self.assertGreater(len(document.settings.comparison_profiles), 0)

    def test_json_save_retains_unknown_top_level_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "balance_per_yuan": "1.1",
                        "comparison_profiles": [],
                        "custom_metadata": {"owner": "operator"},
                        "retained_null": None,
                    }
                ),
                encoding="utf-8",
            )
            document = load_settings_document(path)
            self.assertEqual(document.settings.comparison_profiles, ())
            saved = save_settings_document(
                document,
                Settings.from_mapping(
                    {
                        "balance_per_yuan": "1.2",
                        "comparison_profiles": [],
                    }
                ),
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(saved.exists)
            self.assertEqual(payload["balance_per_yuan"], "1.2")
            self.assertEqual(payload["comparison_profiles"], [])
            self.assertEqual(payload["custom_metadata"], {"owner": "operator"})
            self.assertIsNone(payload["retained_null"])

    def test_toml_round_trip_preserves_unknown_values_and_optional_profile_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.toml"
            path.write_text(
                'version = "custom-v1"\n'
                'balance_per_yuan = "1.2"\n'
                'custom_note = "retain me"\n'
                "\n"
                "[[comparison_profiles]]\n"
                'name = "Example"\n'
                'provider = "example"\n'
                'model = "v1"\n'
                'input_price = "1"\n'
                'output_price = "2"\n'
                'cached_price = "0.5"\n',
                encoding="utf-8",
            )
            document = load_settings_document(path)
            saved = save_settings_document(document, document.settings)
            with path.open("rb") as handle:
                payload = tomllib.load(handle)
            self.assertTrue(saved.exists)
            self.assertEqual(payload["custom_note"], "retain me")
            self.assertEqual(payload["comparison_profiles"][0]["name"], "Example")
            self.assertNotIn("source", payload["comparison_profiles"][0])

    def test_explicit_path_requires_json_or_toml_extension(self) -> None:
        with self.assertRaisesRegex(ValueError, "扩展名"):
            resolve_tui_config_path("settings.yaml")

    def test_empty_catalog_profiles_are_valid(self) -> None:
        catalog = PricingCatalog.from_mapping({"version": "empty", "profiles": []})
        self.assertEqual(catalog.version, "empty")
        self.assertEqual(catalog.profiles, ())

    def test_catalog_rejects_invalid_effective_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "effective_at.*YYYY-MM-DD"):
            PricingCatalog.from_mapping(
                {
                    "version": "custom",
                    "profiles": [
                        {
                            "name": "Invalid",
                            "input_price": "1",
                            "output_price": "1",
                            "cached_price": "1",
                            "effective_at": "2026-2-1",
                        }
                    ],
                }
            )

    def test_catalog_rejects_non_canonical_iso_effective_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "effective_at.*YYYY-MM-DD"):
            PricingCatalog.from_mapping(
                {
                    "version": "custom",
                    "profiles": [
                        {
                            "name": "Invalid",
                            "input_price": "1",
                            "output_price": "1",
                            "cached_price": "1",
                            "effective_at": "20260201",
                        }
                    ],
                }
            )

    def test_catalog_rejects_empty_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "version.*不能为空"):
            PricingCatalog.from_mapping({"version": "  ", "profiles": []})

    def test_settings_reject_invalid_catalog_metadata(self) -> None:
        profile = {
            "name": "Invalid",
            "input_price": "1",
            "output_price": "1",
            "cached_price": "1",
            "effective_at": "2026-2-1",
        }
        with self.assertRaisesRegex(ValueError, "effective_at.*YYYY-MM-DD"):
            Settings.from_mapping({"comparison_profiles": [profile]})
        with self.assertRaisesRegex(ValueError, "version.*不能为空"):
            Settings.from_mapping({"version": "", "comparison_profiles": []})


if __name__ == "__main__":
    unittest.main()
