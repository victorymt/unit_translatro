"""Application boundary for running conversion use cases.

The domain module deliberately knows nothing about request defaults or public
mapping schemas.  This service is the single place where adapters join those
concerns before invoking the deterministic calculation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from unit_translator.domain.conversion import (
    ConversionRequest,
    ConversionResult,
    calculate_conversion,
)

from .requests import request_from_mapping


class RequestDefaults(Protocol):
    """A source of default values for public conversion request mappings."""

    def apply_defaults(self, data: Mapping[str, Any]) -> dict[str, Any]:
        """Return a new request mapping with missing values filled."""


@dataclass(frozen=True)
class ConversionService:
    """Run conversion requests with an optional configured default source.

    Entry points should call :meth:`convert_mapping` for externally supplied
    JSON/CSV data, or :meth:`convert` after building a typed domain request.
    This keeps validation and calculation behaviour identical across CLI,
    batch, TUI, and HTTP adapters.
    """

    defaults: RequestDefaults | None = None

    def convert(self, request: ConversionRequest) -> ConversionResult:
        """Execute an already-typed conversion request."""
        return calculate_conversion(request)

    def convert_mapping(self, data: Mapping[str, Any]) -> ConversionResult:
        """Apply configured defaults, parse the public schema, and calculate."""
        request_data = (
            self.defaults.apply_defaults(data) if self.defaults is not None else dict(data)
        )
        return self.convert(request_from_mapping(request_data))
