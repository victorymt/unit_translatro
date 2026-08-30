"""UI-independent calculator input and presentation models for the TUI."""

from __future__ import annotations

from dataclasses import dataclass

from app_config import Settings
from converter_core import ConversionRequest, TokenPriceProfile, format_decimal
from unit_translator.application import ConversionService


@dataclass(frozen=True)
class CalculatorInputs:
    """The editable calculator fields, independent from terminal rendering.

    In ``token_cost`` mode, ``value`` is the user's actual RMB spend for
    100,000,000 mixed tokens.  The supplied usage is treated as a category mix
    and normalized by the domain calculation.
    """

    mode: str
    value: str
    balance_per_yuan: str
    input_price: str
    output_price: str
    cached_price: str
    usd_cny_rate: str

    def to_request(self, settings: Settings) -> ConversionRequest:
        profile = settings.chatgpt_profile
        return ConversionRequest(
            mode=self.mode,
            value=self.value,
            balance_per_yuan=self.balance_per_yuan,
            chatgpt_profile=TokenPriceProfile(
                profile.name,
                self.input_price,
                self.output_price,
                self.cached_price,
                provider=profile.provider,
                model=profile.model,
            ),
            usd_cny_rate=self.usd_cny_rate,
            usage=settings.usage,
            comparison_profiles=settings.comparison_profiles,
        )


@dataclass(frozen=True)
class ComparisonDisplayRow:
    """One presentation-ready comparison row."""

    name: str
    usd: str
    yuan: str
    relative_cost: str


@dataclass(frozen=True)
class CalculationDisplay:
    """Formatted calculation output that a view can render directly."""

    multiplier: str
    fen_per_dollar: str
    token_cost_yuan: str
    official_cost_usd: str
    comparison: tuple[ComparisonDisplayRow, ...]


def calculate_display(
    inputs: CalculatorInputs,
    settings: Settings,
    service: ConversionService,
) -> CalculationDisplay:
    """Run the application use case and turn its result into display values."""
    result = service.convert(inputs.to_request(settings))
    comparison = tuple(
        ComparisonDisplayRow(
            name=row.name,
            usd="--" if row.usd is None else f"${format_decimal(row.usd)}",
            yuan=f"{format_decimal(row.yuan)} 元",
            relative_cost=(
                "基准"
                if row.usd is None
                else "--"
                if row.relative_to_chatgpt is None
                else f"{format_decimal(row.relative_to_chatgpt)}x"
            ),
        )
        for row in result.comparison
    )
    return CalculationDisplay(
        multiplier=f"{format_decimal(result.multiplier)}x",
        fen_per_dollar=f"{format_decimal(result.fen_per_dollar)} 分/刀",
        token_cost_yuan=f"{format_decimal(result.token_cost_yuan)} 元",
        official_cost_usd=f"${format_decimal(result.official_cost_usd)}",
        comparison=comparison,
    )
