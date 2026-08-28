"""Versioned price and exchange-rate registries.

The conversion domain remains deterministic: callers can inject a catalog or a
rate explicitly, while this module provides a file-backed default for adapters.
"""

from __future__ import annotations

import json
import sysconfig
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol, Sequence

from converter_core import DEEPSEEK_PRICE_PROFILES, TokenPriceProfile



def _default_catalog_path() -> Path:
    local_path = Path(__file__).with_name("config") / "default_profiles.json"
    if local_path.is_file():
        return local_path
    data_root = Path(sysconfig.get_path("data") or sysconfig.get_config_var("prefix"))
    return data_root / "config" / "default_profiles.json"


DEFAULT_CATALOG_PATH = _default_catalog_path()


@dataclass(frozen=True)
class PricingCatalog:
    profiles: tuple[TokenPriceProfile, ...]
    version: str = "builtin-2026-08-21"

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "PricingCatalog":
        raw_profiles = data.get("profiles")
        if not isinstance(raw_profiles, list):
            raise ValueError("价格目录的 profiles 必须是数组")
        profiles: list[TokenPriceProfile] = []
        for index, item in enumerate(raw_profiles):
            if not isinstance(item, dict):
                raise ValueError(f"价格目录第 {index + 1} 项必须是对象")
            profiles.append(
                TokenPriceProfile(
                    str(item.get("name", f"profile-{index + 1}")),
                    item.get("input_price", "0"),
                    item.get("output_price", "0"),
                    item.get("cached_price", "0"),
                    provider=str(item.get("provider", "custom")),
                    model=str(item.get("model", "")),
                    currency=str(item.get("currency", "USD")),
                    unit=str(item.get("unit", "1M tokens")),
                    effective_at=(None if item.get("effective_at") is None else str(item["effective_at"])),
                    source=(None if item.get("source") is None else str(item["source"])),
                    version=(None if item.get("version") is None else str(item["version"])),
                )
            )
        return cls(tuple(profiles), str(data.get("version", "custom")))

    @classmethod
    def from_file(cls, path: str | Path) -> "PricingCatalog":
        source = Path(path)
        try:
            with source.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError as exc:
            raise ValueError(f"价格目录不存在: {source}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"价格目录无法读取: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("价格目录根节点必须是对象")
        return cls.from_mapping(data)

    def list_profiles(self, as_of: str | None = None) -> tuple[TokenPriceProfile, ...]:
        if not as_of:
            return self.profiles
        return tuple(
            profile
            for profile in self.profiles
            if profile.effective_at is None or profile.effective_at <= as_of
        )

    def to_dict(self, *, as_of: str | None = None) -> dict[str, object]:
        return {
            "version": self.version,
            "profiles": [profile.to_dict() for profile in self.list_profiles(as_of)],
        }


def load_pricing_catalog(path: str | Path | None = None) -> PricingCatalog:
    """Load an explicit catalog, then the repository default, then fallback data."""
    if path is not None:
        return PricingCatalog.from_file(path)
    if DEFAULT_CATALOG_PATH.is_file():
        return PricingCatalog.from_file(DEFAULT_CATALOG_PATH)
    return PricingCatalog(DEEPSEEK_PRICE_PROFILES)


@dataclass(frozen=True)
class ExchangeRate:
    base: str
    quote: str
    value: Decimal
    effective_at: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "base": self.base,
            "quote": self.quote,
            "value": str(self.value),
            "effective_at": self.effective_at,
            "source": self.source,
        }


class ExchangeRateProvider(Protocol):
    def current(self) -> ExchangeRate:
        """Return the latest available rate without changing the calculation API."""


@dataclass(frozen=True)
class StaticExchangeRateProvider:
    value: str | Decimal
    source: str = "explicit"

    def current(self) -> ExchangeRate:
        try:
            value = Decimal(str(self.value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("汇率必须是有效数字") from exc
        if not value.is_finite() or value <= 0:
            raise ValueError("汇率必须大于 0")
        return ExchangeRate("USD", "CNY", value, source=self.source)
