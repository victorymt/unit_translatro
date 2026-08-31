import io
import json
import unittest
from decimal import Decimal

from unit_translator.infrastructure.config import Settings
from unit_translator.domain.conversion import (
    ConversionRequest,
    ConversionValidationError,
    TokenPriceProfile,
    TokenUsage,
)
from unit_translator.adapters.http import HttpRequestError, parse_conversion_payload
from unit_translator.application import ConversionService


class ConversionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        profile = TokenPriceProfile("Configured", "1", "2", "0.5")
        self.settings = Settings(
            balance_per_yuan="1.25",
            chatgpt_profile=profile,
            usage=TokenUsage("1", "2", "3"),
            usd_cny_rate="6.8",
            comparison_profiles=(profile,),
            version="test-v1",
        )
        self.service = ConversionService(self.settings)

    def test_mapping_uses_configured_defaults(self) -> None:
        result = self.service.convert_mapping({"mode": "multiplier", "value": "0.2"})

        self.assertEqual(str(result.fen_per_dollar), "16")
        self.assertEqual(str(result.usage.total_tokens), "6")
        self.assertEqual(str(result.usd_cny_rate), "6.8")
        self.assertEqual(result.comparison[1].name, "Configured")

    def test_mapping_keeps_explicit_values(self) -> None:
        result = self.service.convert_mapping(
            {
                "mode": "multiplier",
                "value": "0.2",
                "balance_per_yuan": "2",
                "usage": {"input_tokens": "2", "output_tokens": "3", "cached_tokens": "4"},
            }
        )

        self.assertEqual(result.fen_per_dollar, Decimal("10"))
        self.assertEqual(str(result.usage.total_tokens), "9")

    def test_typed_request_uses_the_same_calculation_boundary(self) -> None:
        request = ConversionRequest(mode="fen", value="5")

        result = ConversionService().convert(request)

        self.assertEqual(result.mode, "fen")
        self.assertEqual(str(result.multiplier), "0.05")


class HttpPayloadTests(unittest.TestCase):
    def test_accepts_the_public_request_schema(self) -> None:
        body = json.dumps({"mode": "multiplier", "value": "0.05"}).encode()
        payload = parse_conversion_payload(
            io.BytesIO(body),
            str(len(body)),
            max_body_bytes=1024,
        )

        self.assertEqual(payload, {"mode": "multiplier", "value": "0.05"})

    def test_reports_http_framing_errors_separately(self) -> None:
        with self.assertRaises(HttpRequestError) as context:
            parse_conversion_payload(io.BytesIO(), None, max_body_bytes=1024)

        self.assertEqual(context.exception.status, 400)
        self.assertEqual(context.exception.code, "missing_content_length")

    def test_keeps_domain_schema_errors_structured(self) -> None:
        payload = json.dumps({"mode": "multiplier", "value": "0.05", "extra": True}).encode()

        with self.assertRaises(ConversionValidationError) as context:
            parse_conversion_payload(
                io.BytesIO(payload),
                str(len(payload)),
                max_body_bytes=1024,
            )

        self.assertEqual(context.exception.field, "extra")
        self.assertEqual(context.exception.code, "unknown_field")


if __name__ == "__main__":
    unittest.main()
