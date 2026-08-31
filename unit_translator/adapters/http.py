"""HTTP request parsing for the local conversion API.

The stdlib request handler owns responses and CORS.  This module owns the
transport-neutral part of HTTP input validation so it can be tested without a
running server and does not inflate the route handler.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, BinaryIO

from unit_translator.domain.conversion import ConversionValidationError


CONVERSION_PATHS = frozenset(
    {"/api/v1/convert", "/v1/convert", "/api/v1/compare", "/v1/compare"}
)
REQUEST_FIELDS = frozenset(
    {
        "mode",
        "value",
        "multiplier",
        "fen",
        "token_cost",
        "balance_per_yuan",
        "ratio",
        "usage",
        "chatgpt_profile",
        "prices",
        "usd_cny_rate",
        "exchange_rate",
        "comparison_profiles",
        "profiles",
    }
)


@dataclass(frozen=True)
class HttpRequestError(ValueError):
    """A client error whose HTTP representation is stable for API callers."""

    status: int
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def parse_conversion_payload(
    body: BinaryIO,
    content_length: str | None,
    *,
    max_body_bytes: int,
) -> dict[str, Any]:
    """Read and validate the public JSON request envelope.

    Domain validation remains in ``ConversionService``; this function only
    validates HTTP framing and the stable outer request schema.
    """

    if content_length is None:
        raise HttpRequestError(400, "missing_content_length", "请求体缺少 Content-Length")
    try:
        length = int(content_length)
    except ValueError as exc:
        raise HttpRequestError(400, "invalid_content_length", "Content-Length 无效") from exc
    if length < 0:
        raise HttpRequestError(400, "invalid_content_length", "Content-Length 不能为负数")
    if length > max_body_bytes:
        raise HttpRequestError(413, "body_too_large", "请求体过大")

    try:
        raw_body = body.read(length)
        if len(raw_body) != length:
            raise ValueError("请求体长度与 Content-Length 不一致")
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise HttpRequestError(422, "invalid_request", str(exc)) from exc
    if not isinstance(payload, Mapping):
        raise HttpRequestError(422, "invalid_request", "请求体必须是 JSON 对象")

    result = dict(payload)
    unknown = sorted(set(result) - REQUEST_FIELDS)
    if unknown:
        raise ConversionValidationError(
            unknown[0], "unknown_field", f"不支持的字段: {unknown[0]}"
        )
    if "value" not in result and not any(
        name in result for name in ("multiplier", "fen", "token_cost")
    ):
        raise ConversionValidationError("value", "missing_field", "缺少 value")
    if result.get("usage") == {}:
        raise ConversionValidationError("usage", "empty_usage", "usage 不能为空")
    return result
