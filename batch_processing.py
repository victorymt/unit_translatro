"""Streaming JSONL/CSV batch conversion without optional dependencies."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, TYPE_CHECKING

from converter_core import DEFAULT_USAGE, ConversionResult
from converter_io import result_to_dict
from unit_translator.application import ConversionService

if TYPE_CHECKING:
    from app_config import Settings


def iter_records(path: str | Path) -> Iterator[dict[str, Any]]:
    source = Path(path)
    if source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle)
        return
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_number} 行不是有效 JSON: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"第 {line_number} 行必须是 JSON 对象")
            yield record


def _csv_record_to_request(
    record: Mapping[str, Any], settings: "Settings | None" = None
) -> dict[str, Any]:
    """Accept flat CSV columns while keeping the JSON schema as the canonical form."""
    result = dict(record)
    flat_usage_fields = {"input_tokens", "output_tokens", "cached_tokens"}
    if "usage" not in result and flat_usage_fields.intersection(result):
        defaults = settings.usage if settings is not None else DEFAULT_USAGE
        result["usage"] = {
            "input_tokens": result.pop("input_tokens", defaults.input_tokens),
            "output_tokens": result.pop("output_tokens", defaults.output_tokens),
            "cached_tokens": result.pop("cached_tokens", defaults.cached_tokens),
        }
    return result


def iter_results(path: str | Path, settings: "Settings | None" = None) -> Iterator[ConversionResult]:
    service = ConversionService(settings)
    for record in iter_records(path):
        request_data = _csv_record_to_request(record, settings)
        yield service.convert_mapping(request_data)


def batch_to_json(path: str | Path, settings: "Settings | None" = None) -> str:
    return json.dumps(
        [result_to_dict(result) for result in iter_results(path, settings)],
        ensure_ascii=False,
        indent=2,
    )


def batch_to_csv(path: str | Path, settings: "Settings | None" = None) -> str:
    rows = list(iter_results(path, settings))
    if not rows:
        return ""
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["record", "mode", "multiplier", "fen_per_dollar", "token_cost_yuan", "official_cost_usd"])
    for index, result in enumerate(rows, start=1):
        writer.writerow([
            index,
            result.mode,
            str(result.multiplier),
            str(result.fen_per_dollar),
            str(result.token_cost_yuan),
            str(result.official_cost_usd),
        ])
    return output.getvalue().rstrip("\r\n")
