import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from catalog_tool import main


class CatalogToolTests(unittest.TestCase):
    def _write_catalog(self, directory: str, payload: object) -> Path:
        path = Path(directory) / "profiles.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_validates_catalog_and_prints_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_catalog(
                directory,
                {
                    "version": "test-v1",
                    "profiles": [
                        {
                            "name": "Current",
                            "provider": "test",
                            "model": "demo",
                            "input_price": "1",
                            "output_price": "2",
                            "cached_price": "0.5",
                            "effective_at": "2026-08-01",
                        }
                    ],
                },
            )
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main([str(path), "--summary"])
        self.assertEqual(exit_code, 0)
        self.assertIn("价格目录有效", output.getvalue())
        self.assertIn("Current", output.getvalue())

    def test_json_summary_can_filter_by_effective_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_catalog(
                directory,
                {
                    "version": "test-v1",
                    "profiles": [
                        {"name": "Old", "effective_at": "2026-01-01"},
                        {"name": "New", "effective_at": "2026-09-01"},
                    ],
                },
            )
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main([str(path), "--json", "--as-of", "2026-08-28"])
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["active_profile_count"], 1)
        self.assertEqual(payload["profiles"][0]["name"], "Old")

    def test_invalid_catalog_returns_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_catalog(
                directory,
                {
                    "version": "test-v1",
                    "profiles": [{"name": "Bad", "input_price": "-1"}],
                },
            )
            output = StringIO()
            with redirect_stderr(output):
                exit_code = main([str(path)])
        self.assertEqual(exit_code, 2)
        self.assertIn("输入 Token 官方价不能小于 0", output.getvalue())

    def test_missing_catalog_returns_user_error(self) -> None:
        output = StringIO()
        with redirect_stderr(output):
            exit_code = main(["/tmp/unit-translator-catalog-does-not-exist.json"])
        self.assertEqual(exit_code, 2)
        self.assertIn("价格目录不存在", output.getvalue())


if __name__ == "__main__":
    unittest.main()
