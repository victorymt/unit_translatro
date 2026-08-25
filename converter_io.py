"""Serialization and request parsing shared by CLI and HTTP adapters."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from converter_core import (
    ConversionValidationError,
    DEFAULT_CACHED_PRICE,
    DEFAULT_INPUT_PRICE,
    DEFAULT_OUTPUT_PRICE,
    DEFAULT_USAGE,
    DEFAULT_USD_CNY_RATE,
    DEEPSEEK_PRICE_PROFILES,
    ConversionRequest,
    ConversionResult,
    TokenPriceProfile,
    TokenUsage,
    calculate_conversion,
    profile_from_mapping,
)


def _value(data: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in data and data[name] is not None:
            return data[name]
    return default


def usage_from_mapping(data: Mapping[str, Any] | None) -> TokenUsage:
    if not data:
        return DEFAULT_USAGE
    if not isinstance(data, Mapping):
        raise ConversionValidationError("usage", "invalid_type", "usage 必须是 JSON 对象")
    return TokenUsage(
        _value(data, "input_tokens", "input", default=DEFAULT_USAGE.input_tokens),
        _value(data, "output_tokens", "output", default=DEFAULT_USAGE.output_tokens),
        _value(data, "cached_tokens", "cached", default=DEFAULT_USAGE.cached_tokens),
    )


def chatgpt_profile_from_mapping(data: Mapping[str, Any] | None) -> TokenPriceProfile:
    if data is not None and not isinstance(data, Mapping):
        raise ConversionValidationError("chatgpt_profile", "invalid_type", "chatgpt_profile 必须是 JSON 对象")
    if not data:
        return TokenPriceProfile(
            "ChatGPT 中转",
            DEFAULT_INPUT_PRICE,
            DEFAULT_OUTPUT_PRICE,
            DEFAULT_CACHED_PRICE,
            provider="ChatGPT relay",
            model="custom",
        )
    return profile_from_mapping(
        {
            "name": data.get("name", "ChatGPT 中转"),
            "provider": data.get("provider", "ChatGPT relay"),
            "model": data.get("model", "custom"),
            "input_price": _value(data, "input_price", "token_price", default=DEFAULT_INPUT_PRICE),
            "output_price": _value(data, "output_price", default=DEFAULT_OUTPUT_PRICE),
            "cached_price": _value(data, "cached_price", "cache_price", default=DEFAULT_CACHED_PRICE),
            "currency": data.get("currency", "USD"),
            "unit": data.get("unit", "1M tokens"),
            "source": data.get("source"),
            "version": data.get("version"),
        }
    )


def request_from_mapping(data: Mapping[str, Any]) -> ConversionRequest:
    """Parse the public request schema used by JSON and HTTP adapters."""
    profiles_data = (
        data["comparison_profiles"]
        if "comparison_profiles" in data
        else data.get("profiles")
    )
    if profiles_data is not None and not isinstance(profiles_data, (list, tuple)):
        raise ConversionValidationError(
            "comparison_profiles", "invalid_type", "comparison_profiles 必须是数组"
        )
    if profiles_data is not None and any(not isinstance(item, Mapping) for item in profiles_data):
        raise ConversionValidationError(
            "comparison_profiles", "invalid_profile", "comparison_profiles 中每项必须是对象"
        )
    profiles = (
        tuple(profile_from_mapping(item) for item in profiles_data)
        if profiles_data is not None
        else DEEPSEEK_PRICE_PROFILES
    )
    profile_data = (
        data["chatgpt_profile"]
        if "chatgpt_profile" in data
        else data.get("prices")
    )
    return ConversionRequest(
        mode=str(data.get("mode", "multiplier")),
        value=_value(data, "value", "multiplier", "fen", "token_cost", default="0"),
        balance_per_yuan=_value(data, "balance_per_yuan", "ratio", default="1"),
        usage=usage_from_mapping(data.get("usage")),
        chatgpt_profile=chatgpt_profile_from_mapping(profile_data),
        usd_cny_rate=_value(data, "usd_cny_rate", "exchange_rate", default=DEFAULT_USD_CNY_RATE),
        comparison_profiles=profiles,
    )


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
