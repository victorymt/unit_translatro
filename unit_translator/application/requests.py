"""Public conversion request schema mapped onto typed domain requests.

This is an application input boundary, not an HTTP or CLI concern.  Keeping it
here lets every transport share aliases and validation without depending on a
different adapter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from unit_translator.domain.conversion import (
    ConversionRequest,
    ConversionValidationError,
    DEFAULT_CACHED_PRICE,
    DEFAULT_INPUT_PRICE,
    DEFAULT_OUTPUT_PRICE,
    DEFAULT_USAGE,
    DEFAULT_USD_CNY_RATE,
    DEEPSEEK_PRICE_PROFILES,
    TokenPriceProfile,
    TokenUsage,
    profile_from_mapping,
)


def value_from_mapping(data: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    """Return the first explicit alias from a public request mapping."""
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
        value_from_mapping(data, "input_tokens", "input", default=DEFAULT_USAGE.input_tokens),
        value_from_mapping(data, "output_tokens", "output", default=DEFAULT_USAGE.output_tokens),
        value_from_mapping(data, "cached_tokens", "cached", default=DEFAULT_USAGE.cached_tokens),
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
            "input_price": value_from_mapping(
                data, "input_price", "token_price", default=DEFAULT_INPUT_PRICE
            ),
            "output_price": value_from_mapping(
                data, "output_price", default=DEFAULT_OUTPUT_PRICE
            ),
            "cached_price": value_from_mapping(
                data, "cached_price", "cache_price", default=DEFAULT_CACHED_PRICE
            ),
            "currency": data.get("currency", "USD"),
            "unit": data.get("unit", "1M tokens"),
            "source": data.get("source"),
            "version": data.get("version"),
        }
    )


def request_from_mapping(
    data: Mapping[str, Any],
    *,
    default_profiles: Sequence[TokenPriceProfile] = DEEPSEEK_PRICE_PROFILES,
) -> ConversionRequest:
    """Parse the versioned public request schema into a domain request.

    A ``token_cost`` request treats its value as the user's actual RMB spend
    for 100,000,000 mixed tokens; the domain layer normalizes any supplied
    usage mix to that total before calculating the equivalent multiplier.
    """
    mode = str(data.get("mode", "multiplier"))
    if mode not in {"multiplier", "fen", "token_cost"}:
        raise ConversionValidationError(
            "mode", "invalid_mode", "mode 必须是 multiplier、fen 或 token_cost"
        )
    value_fields = tuple(
        name for name in ("value", "multiplier", "fen", "token_cost")
        if name in data and data[name] is not None
    )
    if len(value_fields) > 1:
        raise ConversionValidationError(
            "value", "ambiguous_value", "value、multiplier、fen、token_cost 只能提供一个"
        )
    selected_value = value_fields[0] if value_fields else None
    if selected_value not in {None, "value", mode}:
        raise ConversionValidationError(
            selected_value,
            "mode_value_mismatch",
            f"mode={mode} 时只能提供 value 或 {mode}",
        )
    profiles_data = (
        data["comparison_profiles"] if "comparison_profiles" in data else data.get("profiles")
    )
    if profiles_data is not None and not isinstance(profiles_data, (list, tuple)):
        raise ConversionValidationError(
            "comparison_profiles", "invalid_type", "comparison_profiles 必须是数组"
        )
    if profiles_data is not None and any(
        not isinstance(item, Mapping) for item in profiles_data
    ):
        raise ConversionValidationError(
            "comparison_profiles", "invalid_profile", "comparison_profiles 中每项必须是对象"
        )
    profiles = (
        tuple(profile_from_mapping(item) for item in profiles_data)
        if profiles_data is not None
        else tuple(default_profiles)
    )
    profile_data = (
        data["chatgpt_profile"] if "chatgpt_profile" in data else data.get("prices")
    )
    return ConversionRequest(
        mode=mode,
        value=data[selected_value] if selected_value is not None else "0",
        balance_per_yuan=value_from_mapping(data, "balance_per_yuan", "ratio", default="1"),
        usage=usage_from_mapping(data.get("usage")),
        chatgpt_profile=chatgpt_profile_from_mapping(profile_data),
        usd_cny_rate=value_from_mapping(
            data, "usd_cny_rate", "exchange_rate", default=DEFAULT_USD_CNY_RATE
        ),
        comparison_profiles=profiles,
    )
