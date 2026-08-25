"""Pure domain models and calculations for relay cost conversion.

This module deliberately has no terminal, HTTP, or file-system dependencies.  It
is the shared calculation boundary for the CLI, TUI, batch tooling, and web API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Mapping, Sequence


Number = Decimal | int | float | str


class ConversionValidationError(ValueError):
    """Stable validation error that adapters can expose without parsing prose."""

    def __init__(self, field: str, code: str, message: str) -> None:
        self.field = field
        self.code = code
        super().__init__(message)

ONE_HUNDRED = Decimal("100")
ONE_MILLION = Decimal("1000000")
ONE_HUNDRED_MILLION = Decimal("100000000")

DEFAULT_INPUT_PRICE = Decimal("5")
DEFAULT_OUTPUT_PRICE = Decimal("30")
DEFAULT_CACHED_PRICE = Decimal("0.5")
DEFAULT_USD_CNY_RATE = Decimal("7.2")

SAMPLE_INPUT_TOKENS = Decimal("12730000")
SAMPLE_OUTPUT_TOKENS = Decimal("381680")
SAMPLE_CACHED_TOKENS = Decimal("157670000")
SAMPLE_TOTAL_TOKENS = (
    SAMPLE_INPUT_TOKENS + SAMPLE_OUTPUT_TOKENS + SAMPLE_CACHED_TOKENS
)
DEFAULT_INPUT_TOKENS = SAMPLE_INPUT_TOKENS * ONE_HUNDRED_MILLION / SAMPLE_TOTAL_TOKENS
DEFAULT_OUTPUT_TOKENS = SAMPLE_OUTPUT_TOKENS * ONE_HUNDRED_MILLION / SAMPLE_TOTAL_TOKENS
DEFAULT_CACHED_TOKENS = SAMPLE_CACHED_TOKENS * ONE_HUNDRED_MILLION / SAMPLE_TOTAL_TOKENS


def _as_decimal(value: Number, name: str) -> Decimal:
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ConversionValidationError(name, "invalid_number", f"{name}必须是有效数字") from exc
    if not number.is_finite():
        raise ConversionValidationError(name, "not_finite", f"{name}必须是有限数字")
    return number


def _non_negative(value: Number, name: str) -> Decimal:
    number = _as_decimal(value, name)
    if number < 0:
        raise ConversionValidationError(name, "negative", f"{name}不能小于 0")
    return number


def _positive(value: Number, name: str) -> Decimal:
    number = _as_decimal(value, name)
    if number <= 0:
        raise ConversionValidationError(name, "not_positive", f"{name}必须大于 0")
    return number


@dataclass(frozen=True)
class TokenUsage:
    """A concrete input/output/cache token mix.

    The legacy sample mix remains the default so existing CLI behavior is
    unchanged, while callers can now provide real usage records.
    """

    input_tokens: Number = DEFAULT_INPUT_TOKENS
    output_tokens: Number = DEFAULT_OUTPUT_TOKENS
    cached_tokens: Number = DEFAULT_CACHED_TOKENS

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_tokens", _non_negative(self.input_tokens, "输入 Token 数量"))
        object.__setattr__(self, "output_tokens", _non_negative(self.output_tokens, "输出 Token 数量"))
        object.__setattr__(self, "cached_tokens", _non_negative(self.cached_tokens, "缓存 Token 数量"))
        if self.total_tokens <= 0:
            raise ConversionValidationError("usage", "empty_usage", "Token 总数必须大于 0")

    @property
    def total_tokens(self) -> Decimal:
        return self.input_tokens + self.output_tokens + self.cached_tokens

    def to_dict(self) -> dict[str, str]:
        return {
            "input_tokens": str(self.input_tokens),
            "output_tokens": str(self.output_tokens),
            "cached_tokens": str(self.cached_tokens),
            "total_tokens": str(self.total_tokens),
        }


@dataclass(frozen=True)
class TokenPriceProfile:
    name: str
    input_price: Number
    output_price: Number
    cached_price: Number
    provider: str = "DeepSeek"
    model: str = ""
    currency: str = "USD"
    unit: str = "1M tokens"
    effective_at: str | None = None
    source: str | None = None
    version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_price", _non_negative(self.input_price, "输入 Token 官方价"))
        object.__setattr__(self, "output_price", _non_negative(self.output_price, "输出 Token 官方价"))
        object.__setattr__(self, "cached_price", _non_negative(self.cached_price, "缓存 Token 官方价"))

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "provider": self.provider,
            "model": self.model,
            "currency": self.currency,
            "unit": self.unit,
            "input_price": str(self.input_price),
            "output_price": str(self.output_price),
            "cached_price": str(self.cached_price),
            "effective_at": self.effective_at,
            "source": self.source,
            "version": self.version,
        }


@dataclass(frozen=True)
class ChannelCost:
    name: str
    usd: Decimal | None
    yuan: Decimal
    relative_to_chatgpt: Decimal | None
    provider: str = ""
    model: str = ""

    def to_dict(self) -> dict[str, str | None]:
        return {
            "name": self.name,
            "provider": self.provider or None,
            "model": self.model or None,
            "usd": None if self.usd is None else str(self.usd),
            "yuan": str(self.yuan),
            "relative_to_chatgpt": (
                None
                if self.relative_to_chatgpt is None
                else str(self.relative_to_chatgpt)
            ),
        }


DEEPSEEK_PRICE_PROFILES: tuple[TokenPriceProfile, ...] = (
    TokenPriceProfile(
        "DeepSeek V4 Flash 谷", "0.22", "0.66", "0.007",
        model="V4 Flash", source="DeepSeek Models & Pricing", version="2026-08-21",
    ),
    TokenPriceProfile(
        "DeepSeek V4 Flash 峰", "0.44", "1.32", "0.014",
        model="V4 Flash", source="DeepSeek Models & Pricing", version="2026-08-21",
    ),
    TokenPriceProfile(
        "DeepSeek V4 Pro 谷", "0.66", "1.98", "0.022",
        model="V4 Pro", source="DeepSeek Models & Pricing", version="2026-08-21",
    ),
    TokenPriceProfile(
        "DeepSeek V4 Pro 峰", "1.32", "3.96", "0.044",
        model="V4 Pro", source="DeepSeek Models & Pricing", version="2026-08-21",
    ),
)

DEFAULT_USAGE = TokenUsage()
DEFAULT_CHATGPT_PROFILE = TokenPriceProfile(
    "ChatGPT 中转", DEFAULT_INPUT_PRICE, DEFAULT_OUTPUT_PRICE, DEFAULT_CACHED_PRICE,
    provider="ChatGPT relay", model="custom",
)


@dataclass(frozen=True)
class ConversionRequest:
    """Validated at calculation time to keep construction convenient for adapters."""

    mode: str
    value: Number
    balance_per_yuan: Number = Decimal("1")
    usage: TokenUsage = field(default_factory=lambda: DEFAULT_USAGE)
    chatgpt_profile: TokenPriceProfile = field(default_factory=lambda: DEFAULT_CHATGPT_PROFILE)
    usd_cny_rate: Number = DEFAULT_USD_CNY_RATE
    comparison_profiles: Sequence[TokenPriceProfile] = field(
        default_factory=lambda: DEEPSEEK_PRICE_PROFILES
    )


@dataclass(frozen=True)
class ConversionResult:
    mode: str
    multiplier: Decimal
    fen_per_dollar: Decimal
    token_cost_yuan: Decimal
    official_cost_usd: Decimal
    comparison: tuple[ChannelCost, ...]
    usage: TokenUsage
    chatgpt_profile: TokenPriceProfile
    usd_cny_rate: Decimal

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "multiplier": str(self.multiplier),
            "fen_per_dollar": str(self.fen_per_dollar),
            "token_cost_yuan": str(self.token_cost_yuan),
            "official_cost_usd": str(self.official_cost_usd),
            "usage": self.usage.to_dict(),
            "chatgpt_profile": self.chatgpt_profile.to_dict(),
            "usd_cny_rate": str(self.usd_cny_rate),
            "comparison": [row.to_dict() for row in self.comparison],
        }


def fen_from_multiplier(multiplier: Number, balance_per_yuan: Number = Decimal("1")) -> Decimal:
    """Return fen paid per official USD of usage."""
    return _non_negative(multiplier, "倍率") * ONE_HUNDRED / _positive(
        balance_per_yuan, "充值比例"
    )


def multiplier_from_fen(fen_per_dollar: Number, balance_per_yuan: Number = Decimal("1")) -> Decimal:
    """Return the relay multiplier represented by a fen-per-USD cost."""
    return _non_negative(fen_per_dollar, "每刀价格") * _positive(
        balance_per_yuan, "充值比例"
    ) / ONE_HUNDRED


def official_token_cost_usd_for_usage(
    usage: TokenUsage,
    profile: TokenPriceProfile,
) -> Decimal:
    """Calculate official USD cost for an arbitrary input/output/cache mix."""
    return (
        usage.input_tokens * profile.input_price
        + usage.output_tokens * profile.output_price
        + usage.cached_tokens * profile.cached_price
    ) / ONE_MILLION


def official_token_cost_usd(
    official_price_per_million: Number,
    token_count: Number = ONE_HUNDRED_MILLION,
    *,
    output_price_per_million: Number = DEFAULT_OUTPUT_PRICE,
    cached_price_per_million: Number = DEFAULT_CACHED_PRICE,
    usage: TokenUsage | None = None,
) -> Decimal:
    """Return official USD cost, preserving the legacy sample-mix signature."""
    input_price = _non_negative(official_price_per_million, "输入 Token 官方价")
    output_price = _non_negative(output_price_per_million, "输出 Token 官方价")
    cached_price = _non_negative(cached_price_per_million, "缓存 Token 官方价")
    if usage is None:
        tokens = _non_negative(token_count, "Token 数量")
        usage = TokenUsage(
            SAMPLE_INPUT_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
            SAMPLE_OUTPUT_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
            SAMPLE_CACHED_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
        )
    return official_token_cost_usd_for_usage(
        usage,
        TokenPriceProfile("custom", input_price, output_price, cached_price),
    )


def token_cost_yuan_for_usage(
    fen_per_dollar: Number,
    usage: TokenUsage,
    profile: TokenPriceProfile,
) -> Decimal:
    return (
        official_token_cost_usd_for_usage(usage, profile)
        * _non_negative(fen_per_dollar, "每刀价格")
        / ONE_HUNDRED
    )


def token_cost_yuan(
    fen_per_dollar: Number,
    official_price_per_million: Number = DEFAULT_INPUT_PRICE,
    token_count: Number = ONE_HUNDRED_MILLION,
    *,
    output_price_per_million: Number = DEFAULT_OUTPUT_PRICE,
    cached_price_per_million: Number = DEFAULT_CACHED_PRICE,
    usage: TokenUsage | None = None,
) -> Decimal:
    """Return account cost, preserving the legacy sample-mix signature."""
    if usage is None:
        tokens = _non_negative(token_count, "Token 数量")
        usage = TokenUsage(
            SAMPLE_INPUT_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
            SAMPLE_OUTPUT_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
            SAMPLE_CACHED_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
        )
    profile = TokenPriceProfile(
        "custom", official_price_per_million, output_price_per_million, cached_price_per_million
    )
    return token_cost_yuan_for_usage(fen_per_dollar, usage, profile)


def fen_from_token_cost_for_usage(
    cost_yuan: Number,
    usage: TokenUsage,
    profile: TokenPriceProfile,
) -> Decimal:
    cost = _non_negative(cost_yuan, "Token 成本")
    official_dollars = official_token_cost_usd_for_usage(usage, profile)
    if official_dollars == 0:
        raise ConversionValidationError("prices", "zero_price", "Token 官方价不能全部为 0")
    return cost * ONE_HUNDRED / official_dollars


def fen_from_token_cost(
    cost_yuan: Number,
    official_price_per_million: Number = DEFAULT_INPUT_PRICE,
    token_count: Number = ONE_HUNDRED_MILLION,
    *,
    output_price_per_million: Number = DEFAULT_OUTPUT_PRICE,
    cached_price_per_million: Number = DEFAULT_CACHED_PRICE,
    usage: TokenUsage | None = None,
) -> Decimal:
    if usage is None:
        tokens = _non_negative(token_count, "Token 数量")
        usage = TokenUsage(
            SAMPLE_INPUT_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
            SAMPLE_OUTPUT_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
            SAMPLE_CACHED_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
        )
    profile = TokenPriceProfile(
        "custom", official_price_per_million, output_price_per_million, cached_price_per_million
    )
    return fen_from_token_cost_for_usage(cost_yuan, usage, profile)


def channel_cost_comparison(
    chatgpt_cost_yuan: Number,
    usd_cny_rate: Number = DEFAULT_USD_CNY_RATE,
    token_count: Number = ONE_HUNDRED_MILLION,
    *,
    profiles: Sequence[TokenPriceProfile] | None = None,
    usage: TokenUsage | None = None,
) -> tuple[ChannelCost, ...]:
    """Compare a relay cost with injected official price profiles."""
    chatgpt_cost = _non_negative(chatgpt_cost_yuan, "ChatGPT 中转成本")
    exchange_rate = _positive(usd_cny_rate, "美元兑人民币汇率")
    if usage is None:
        tokens = _non_negative(token_count, "Token 数量")
        usage = TokenUsage(
            SAMPLE_INPUT_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
            SAMPLE_OUTPUT_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
            SAMPLE_CACHED_TOKENS * tokens / SAMPLE_TOTAL_TOKENS,
        )
    rows = [
        ChannelCost(
            "ChatGPT 中转", None, chatgpt_cost,
            Decimal("1") if chatgpt_cost else None,
            provider="ChatGPT relay", model="custom",
        )
    ]
    for profile in profiles or DEEPSEEK_PRICE_PROFILES:
        usd = official_token_cost_usd_for_usage(usage, profile)
        yuan = usd * exchange_rate
        relative = yuan / chatgpt_cost if chatgpt_cost else None
        rows.append(ChannelCost(profile.name, usd, yuan, relative, profile.provider, profile.model))
    return tuple(rows)


def calculate_conversion(request: ConversionRequest) -> ConversionResult:
    """Calculate all three equivalent values and the channel comparison."""
    if request.mode not in {"multiplier", "fen", "token_cost"}:
        raise ConversionValidationError("mode", "invalid_mode", "mode 必须是 multiplier、fen 或 token_cost")
    ratio = _positive(request.balance_per_yuan, "充值比例")
    rate = _positive(request.usd_cny_rate, "美元兑人民币汇率")
    usage = request.usage
    profile = request.chatgpt_profile
    if request.mode == "multiplier":
        multiplier = _non_negative(request.value, "倍率")
        fen = fen_from_multiplier(multiplier, ratio)
    elif request.mode == "fen":
        fen = _non_negative(request.value, "每刀价格")
        multiplier = multiplier_from_fen(fen, ratio)
    else:
        cost = _non_negative(request.value, "ChatGPT 中转 1 亿 Token 成本")
        fen = fen_from_token_cost_for_usage(cost, usage, profile)
        multiplier = multiplier_from_fen(fen, ratio)
    cost = token_cost_yuan_for_usage(fen, usage, profile)
    official_usd = official_token_cost_usd_for_usage(usage, profile)
    comparison = channel_cost_comparison(
        cost, rate, usage=usage, profiles=request.comparison_profiles
    )
    return ConversionResult(
        request.mode, multiplier, fen, cost, official_usd, comparison,
        usage, profile, rate,
    )


def format_decimal(value: Decimal, max_places: int = 8) -> str:
    """Format Decimal for human-facing output only."""
    quantum = Decimal(1).scaleb(-max_places)
    rounded = value.quantize(quantum)
    return format(rounded, "f").rstrip("0").rstrip(".") or "0"


def profile_from_mapping(data: Mapping[str, object]) -> TokenPriceProfile:
    """Build a profile from JSON/TOML-like data with strict numeric validation."""
    return TokenPriceProfile(
        str(data.get("name", "custom")),
        data.get("input_price", "0"),
        data.get("output_price", "0"),
        data.get("cached_price", "0"),
        provider=str(data.get("provider", "custom")),
        model=str(data.get("model", "")),
        currency=str(data.get("currency", "USD")),
        unit=str(data.get("unit", "1M tokens")),
        effective_at=(None if data.get("effective_at") is None else str(data["effective_at"])),
        source=(None if data.get("source") is None else str(data["source"])),
        version=(None if data.get("version") is None else str(data["version"])),
    )
