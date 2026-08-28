"""Serialization and request parsing shared by CLI and HTTP adapters."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from converter_core import ConversionRequest, ConversionResult, TokenPriceProfile, TokenUsage
from pricing_catalog import load_pricing_catalog
from unit_translator.application.requests import (
    chatgpt_profile_from_mapping,
    request_from_mapping as _request_from_mapping,
    usage_from_mapping,
)


def request_from_mapping(data: Mapping[str, Any]) -> ConversionRequest:
    """Compatibility facade for the legacy mapping module.

    The legacy function keeps the file-backed catalog fallback.  New adapters
    use the application service, whose settings defaults provide the catalog.
    """
    return _request_from_mapping(data, default_profiles=load_pricing_catalog().profiles)


def result_to_dict(result: ConversionResult) -> dict[str, object]:
    return result.to_dict()


def result_to_json(result: ConversionResult, *, pretty: bool = True) -> str:
    return json.dumps(
        result_to_dict(result),
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )


def result_to_csv(result: ConversionResult) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "mode",
            "multiplier",
            "fen_per_dollar",
            "token_cost_yuan",
            "official_cost_usd",
            "channel",
            "provider",
            "model",
            "channel_usd",
            "channel_yuan",
            "relative_to_chatgpt",
        ]
    )
    for row in result.comparison:
        writer.writerow(
            [
                result.mode,
                str(result.multiplier),
                str(result.fen_per_dollar),
                str(result.token_cost_yuan),
                str(result.official_cost_usd),
                row.name,
                row.provider,
                row.model,
                "" if row.usd is None else str(row.usd),
                str(row.yuan),
                "" if row.relative_to_chatgpt is None else str(row.relative_to_chatgpt),
            ]
        )
    return output.getvalue().rstrip("\r\n")


def render_result(result: ConversionResult, output_format: str) -> str:
    if output_format == "json":
        return result_to_json(result)
    if output_format == "csv":
        return result_to_csv(result)
    raise ValueError(f"不支持的输出格式: {output_format}")


def parse_decimal_fields(data: Mapping[str, Any]) -> dict[str, Decimal]:
    """Useful for callers that need a validated numeric snapshot."""
    return {key: Decimal(str(value)) for key, value in data.items()}
