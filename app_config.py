"""Versioned, file-backed application settings.

JSON is accepted everywhere. TOML is also supported on Python 3.11+ through
the standard library so price changes do not require editing source code.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping
from typing import Any

from converter_core import (
    DEFAULT_USAGE,
    DEFAULT_USD_CNY_RATE,
    TokenPriceProfile,
    TokenUsage,
)
from converter_io import chatgpt_profile_from_mapping, usage_from_mapping
from converter_core import profile_from_mapping
from pricing_catalog import (
    ExchangeRate,
    ExchangeRateProvider,
    PricingCatalog,
    StaticExchangeRateProvider,
    load_pricing_catalog,
)


@dataclass(frozen=True)
class Settings:
    balance_per_yuan: str = "1"
    chatgpt_profile: TokenPriceProfile = field(
        default_factory=lambda: chatgpt_profile_from_mapping(None)
    )
    usage: TokenUsage = field(default_factory=lambda: DEFAULT_USAGE)
    usd_cny_rate: str = str(DEFAULT_USD_CNY_RATE)
    comparison_profiles: tuple[TokenPriceProfile, ...] = field(
        default_factory=lambda: load_pricing_catalog().profiles
    )
    version: str = field(default_factory=lambda: load_pricing_catalog().version)
    exchange_rate_provider: ExchangeRateProvider | None = field(
        default=None, repr=False, compare=False
    )

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "Settings":
        if "comparison_profiles" in data:
            profiles_data = data["comparison_profiles"]
        elif "profiles" in data:
            profiles_data = data["profiles"]
        else:
            profiles_data = None
        catalog = load_pricing_catalog()
        if profiles_data is None:
            profiles = catalog.profiles
        else:
            if not isinstance(profiles_data, (list, tuple)):
                raise ValueError("comparison_profiles 必须是数组")
            if any(not isinstance(item, Mapping) for item in profiles_data):
                raise ValueError("comparison_profiles 中每项必须是对象")
            profiles = tuple(profile_from_mapping(item) for item in profiles_data)
        return cls(
            balance_per_yuan=str(data.get("balance_per_yuan", data.get("ratio", "1"))),
            chatgpt_profile=chatgpt_profile_from_mapping(
                data.get("chatgpt_profile") or data.get("prices")
            ),
            usage=usage_from_mapping(data.get("usage")),
            usd_cny_rate=str(data.get("usd_cny_rate", DEFAULT_USD_CNY_RATE)),
            comparison_profiles=profiles,
            version=str(data.get("version", catalog.version)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "balance_per_yuan": self.balance_per_yuan,
            "usd_cny_rate": self.usd_cny_rate,
            "usage": self.usage.to_dict(),
            "chatgpt_profile": self.chatgpt_profile.to_dict(),
            "comparison_profiles": [profile.to_dict() for profile in self.comparison_profiles],
        }

    def as_catalog(self) -> PricingCatalog:
        """Return the profile snapshot used by this settings instance."""
        return PricingCatalog(self.comparison_profiles, version=self.version)

    def current_exchange_rate(self) -> ExchangeRate:
        """Resolve the configured rate through the provider boundary."""
        provider = self.exchange_rate_provider or StaticExchangeRateProvider(
            self.usd_cny_rate,
            source=f"settings:{self.version}",
        )
        return provider.current()

    def apply_defaults(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Fill adapter request defaults while preserving explicit request values."""
        result = dict(data)
        result.setdefault("balance_per_yuan", self.balance_per_yuan)
        result.setdefault("usd_cny_rate", str(self.current_exchange_rate().value))
        result.setdefault("usage", self.usage.to_dict())
        result.setdefault("chatgpt_profile", self.chatgpt_profile.to_dict())
        if "comparison_profiles" not in result and "profiles" not in result:
            result["comparison_profiles"] = [
                profile.to_dict() for profile in self.comparison_profiles
            ]
        return result


def load_settings(path: str | Path | None) -> Settings:
    if path is None:
        return Settings()
    source = Path(path)
    try:
        if source.suffix.lower() == ".toml":
            with source.open("rb") as handle:
                data = tomllib.load(handle)
        else:
            with source.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"配置文件不存在: {source}") from exc
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"配置文件无法读取: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("配置文件根节点必须是对象")
    return Settings.from_mapping(data)
