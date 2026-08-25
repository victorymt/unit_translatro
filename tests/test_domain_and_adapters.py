import json
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from io import StringIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app_config import Settings, load_settings
from batch_processing import batch_to_csv, batch_to_json
from converter_core import (
    ConversionRequest,
    TokenPriceProfile,
    TokenUsage,
    calculate_conversion,
)
from converter_io import request_from_mapping
from pricing_catalog import PricingCatalog, StaticExchangeRateProvider, load_pricing_catalog
from unit_converter import main
from web_api import create_server


class DomainAndAdapterTests(unittest.TestCase):
    def test_custom_usage_is_calculated_without_sample_scaling(self) -> None:
        usage = TokenUsage("1000000", "2000000", "3000000")
        profile = TokenPriceProfile("custom", "1", "2", "0.5", provider="test")
        result = calculate_conversion(
            ConversionRequest(
                mode="multiplier",
                value="0.1",
                usage=usage,
                chatgpt_profile=profile,
                comparison_profiles=(profile,),
            )
        )
        self.assertEqual(result.official_cost_usd, Decimal("6.5"))
        self.assertEqual(result.fen_per_dollar, Decimal("10"))
        self.assertEqual(result.token_cost_yuan, Decimal("0.65"))
        self.assertEqual(result.comparison[1].provider, "test")

    def test_request_schema_accepts_flat_aliases(self) -> None:
        request = request_from_mapping(
            {
                "mode": "fen",
                "value": "5",
                "ratio": "1.2",
                "usage": {"input": "10", "output": "20", "cached": "30"},
                "prices": {"input_price": "1", "output_price": "2", "cache_price": "0.5"},
            }
        )
        self.assertEqual(request.mode, "fen")
        self.assertEqual(request.usage.total_tokens, 60)
        self.assertEqual(request.chatgpt_profile.output_price, 2)

    def test_cli_json_output_is_structured(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["--multiplier", "0.05", "--format", "json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["mode"], "multiplier")
        self.assertEqual(payload["multiplier"], "0.05")
        self.assertTrue(payload["token_cost_yuan"].startswith("4.506789018"))
        self.assertIsInstance(payload["comparison"], list)

    def test_cli_batch_input_does_not_start_tui(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requests.jsonl"
            path.write_text('{"mode":"multiplier","value":"0.05"}\n', encoding="utf-8")
            output = StringIO()
            with redirect_stdout(output):
                exit_code = main(["--input-file", str(path), "--format", "json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["mode"], "multiplier")

    def test_batch_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requests.jsonl"
            path.write_text(
                '{"mode":"multiplier","value":"0.05"}\n'
                '{"mode":"fen","value":"5"}\n',
                encoding="utf-8",
            )
            payload = json.loads(batch_to_json(path))
        self.assertEqual(len(payload), 2)
        self.assertEqual(payload[1]["mode"], "fen")

    def test_batch_csv_accepts_flat_usage_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "requests.csv"
            path.write_text(
                "mode,value,input_tokens,output_tokens,cached_tokens\n"
                "multiplier,0.1,1000000,2000000,3000000\n",
                encoding="utf-8",
            )
            output = batch_to_csv(path)
        self.assertIn("multiplier", output)
        self.assertIn("6.65", output)

    def test_batch_uses_settings_for_records_without_explicit_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "settings.json"
            requests = Path(directory) / "requests.jsonl"
            config.write_text(
                json.dumps(
                    {
                        "usd_cny_rate": "6.8",
                        "usage": {
                            "input_tokens": "1",
                            "output_tokens": "2",
                            "cached_tokens": "3",
                        },
                        "comparison_profiles": [
                            {
                                "name": "Custom",
                                "provider": "test",
                                "model": "demo",
                                "input_price": "1",
                                "output_price": "1",
                                "cached_price": "1",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            requests.write_text('{"mode":"multiplier","value":"0.1"}\n', encoding="utf-8")
            payload = json.loads(batch_to_json(requests, load_settings(config)))
        self.assertEqual(payload[0]["usage"]["total_tokens"], "6")
        self.assertEqual(payload[0]["comparison"][1]["name"], "Custom")
        self.assertEqual(payload[0]["usd_cny_rate"], "6.8")

    def test_toml_settings_override_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.toml"
            path.write_text(
                'version = "test-v1"\n'
                'balance_per_yuan = "1.2"\n'
                'usd_cny_rate = "7"\n'
                '[chatgpt_profile]\n'
                'input_price = "2"\n'
                'output_price = "4"\n'
                'cached_price = "0.2"\n',
                encoding="utf-8",
            )
            settings = load_settings(path)
        self.assertEqual(settings.version, "test-v1")
        self.assertEqual(settings.balance_per_yuan, "1.2")
        self.assertEqual(settings.chatgpt_profile.input_price, 2)

    def test_settings_resolve_rate_provider_and_catalog_snapshot(self) -> None:
        settings = Settings(
            usd_cny_rate="6.9",
            version="settings-v1",
            comparison_profiles=(TokenPriceProfile("Configured", "1", "1", "1"),),
        )
        rate = settings.current_exchange_rate()
        self.assertEqual(rate.value, Decimal("6.9"))
        self.assertEqual(rate.source, "settings:settings-v1")
        self.assertEqual(settings.as_catalog().version, "settings-v1")
        self.assertEqual(settings.as_catalog().profiles[0].name, "Configured")

    def test_web_health_and_conversion(self) -> None:
        server = create_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(f"{base_url}/health") as response:
                health = json.loads(response.read())
            self.assertEqual(health["schema_version"], "1")
            self.assertEqual(health["status"], "ok")
            request = Request(
                f"{base_url}/api/v1/convert?source=test",
                data=json.dumps({"mode": "multiplier", "value": "0.05"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                payload = json.loads(response.read())
            self.assertEqual(payload["schema_version"], "1")
            self.assertEqual(payload["multiplier"], "0.05")
            invalid = Request(
                f"{base_url}/api/v1/convert",
                data=json.dumps({"mode": "unknown", "value": "0.05"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as context:
                urlopen(invalid)
            self.assertEqual(context.exception.code, 422)
            error_payload = json.loads(context.exception.read())
            self.assertEqual(error_payload["error"]["code"], "invalid_mode")
            self.assertEqual(error_payload["error"]["field"], "mode")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_web_rejects_missing_value_unknown_fields_and_empty_usage(self) -> None:
        server = create_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            for payload, field, code in (
                ({"mode": "multiplier"}, "value", "missing_field"),
                ({"mode": "multiplier", "value": "1", "unexpected": True}, "unexpected", "unknown_field"),
                ({"mode": "multiplier", "value": "1", "usage": {}}, "usage", "empty_usage"),
                ({"mode": "multiplier", "value": "1", "chatgpt_profile": []}, "chatgpt_profile", "invalid_type"),
            ):
                request = Request(
                    f"{base_url}/api/v1/convert",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as context:
                    urlopen(request)
                self.assertEqual(context.exception.code, 422)
                error_payload = json.loads(context.exception.read())
                self.assertEqual(error_payload["schema_version"], "1")
                self.assertEqual(error_payload["error"]["field"], field)
                self.assertEqual(error_payload["error"]["code"], code)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_web_cors_is_opt_in(self) -> None:
        server = create_server("127.0.0.1", 0, cors_origins={"http://localhost:3000"})
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            allowed = Request(f"{base_url}/health", headers={"Origin": "http://localhost:3000"})
            with urlopen(allowed) as response:
                self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://localhost:3000")
            default = Request(f"{base_url}/health", headers={"Origin": "http://example.test"})
            with urlopen(default) as response:
                self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_web_serves_static_frontend_and_rejects_unknown_assets(self) -> None:
        server = create_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(f"{base_url}/?from=test") as response:
                html = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn("Token 成本换算", html)
                self.assertIn("/assets/app.js", html)
            with urlopen(f"{base_url}/assets/app.js") as response:
                javascript = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn("/api/v1/convert", javascript)
            with self.assertRaises(HTTPError) as context:
                urlopen(f"{base_url}/assets/missing.css")
            self.assertEqual(context.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_pricing_catalog_loads_versioned_profiles(self) -> None:
        catalog = load_pricing_catalog()
        self.assertEqual(catalog.version, "pricing-2026-08-21")
        self.assertEqual(len(catalog.profiles), 4)
        self.assertEqual(catalog.profiles[0].effective_at, "2026-08-21")
        self.assertEqual(len(catalog.list_profiles(as_of="2026-08-20")), 0)
        rate = StaticExchangeRateProvider("7.1", source="test").current()
        self.assertEqual(rate.value, Decimal("7.1"))
        self.assertEqual(rate.source, "test")

    def test_web_uses_custom_pricing_catalog(self) -> None:
        profile = TokenPriceProfile(
            "Custom channel", "1", "1", "1", provider="custom", model="demo",
            effective_at="2026-01-01", version="custom-v1",
        )
        catalog = PricingCatalog((profile,), version="custom-v1")
        server = create_server("127.0.0.1", 0, pricing_catalog=catalog)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with urlopen(f"{base_url}/api/v1/profiles?as_of=2026-01-01") as response:
                profiles_payload = json.loads(response.read())
            self.assertEqual(profiles_payload["catalog_version"], "custom-v1")
            self.assertEqual(profiles_payload["profiles"][0]["name"], "Custom channel")
            request = Request(
                f"{base_url}/api/v1/convert",
                data=json.dumps({"mode": "multiplier", "value": "0.1"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                result = json.loads(response.read())
            self.assertEqual(result["comparison"][1]["name"], "Custom channel")
            self.assertEqual(result["comparison"][1]["provider"], "custom")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_web_uses_settings_defaults_for_conversion(self) -> None:
        profile = TokenPriceProfile(
            "Configured channel", "1", "2", "0.5", provider="configured", model="demo"
        )
        settings = Settings(
            balance_per_yuan="1.2",
            chatgpt_profile=profile,
            usage=TokenUsage("1", "2", "3"),
            usd_cny_rate="6.8",
            comparison_profiles=(profile,),
            version="settings-v1",
        )
        server = create_server("127.0.0.1", 0, settings=settings)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            request = Request(
                f"{base_url}/api/v1/convert",
                data=json.dumps({"mode": "multiplier", "value": "0.1"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                result = json.loads(response.read())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(result["usage"]["total_tokens"], "6")
        self.assertEqual(result["chatgpt_profile"]["input_price"], "1")
        self.assertEqual(result["usd_cny_rate"], "6.8")
        self.assertEqual(result["comparison"][1]["name"], "Configured channel")


if __name__ == "__main__":
    unittest.main()
