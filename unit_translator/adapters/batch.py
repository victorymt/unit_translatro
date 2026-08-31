"""Streaming JSONL/CSV batch conversion without optional dependencies."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, TextIO, TYPE_CHECKING

from unit_translator.domain.conversion import DEFAULT_USAGE, ConversionResult
from unit_translator.adapters.serialization import result_to_dict
from unit_translator.application import ConversionService

if TYPE_CHECKING:
    from unit_translator.infrastructure.config import Settings


def iter_records(path: str | Path) -> Iterator[dict[str, Any]]:
    source = Path(path)
    try:
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
    except FileNotFoundError as exc:
        raise ValueError(f"批处理文件不存在: {source}") from exc
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"批处理文件无法读取: {source}: {exc}") from exc


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
    import io

    output = io.StringIO()
    write_batch_json(path, output, settings)
    return output.getvalue()


def write_batch_json(
    path: str | Path, output: TextIO, settings: "Settings | None" = None
) -> None:
    """Write JSON results incrementally without retaining the full batch."""
    output.write("[")
    first = True
    for result in iter_results(path, settings):
        rendered = json.dumps(result_to_dict(result), ensure_ascii=False, indent=2)
        output.write("\n" if first else ",\n")
        output.write("\n".join(f"  {line}" for line in rendered.splitlines()))
        first = False
    if not first:
        output.write("\n")
    output.write("]")


def batch_to_csv(path: str | Path, settings: "Settings | None" = None) -> str:
    import io

    output = io.StringIO()
    write_batch_csv(path, output, settings)
    return output.getvalue().rstrip("\r\n")


def write_batch_csv(
    path: str | Path, output: TextIO, settings: "Settings | None" = None
) -> None:
    """Write CSV results incrementally without retaining the full batch."""
    writer = csv.writer(output)
    wrote_header = False
    for index, result in enumerate(iter_results(path, settings), start=1):
        if not wrote_header:
            writer.writerow(
                [
                    "record",
                    "mode",
                    "multiplier",
                    "fen_per_dollar",
                    "token_cost_yuan",
                    "official_cost_usd",
                ]
            )
            wrote_header = True
        writer.writerow(
            [
                index,
                result.mode,
                str(result.multiplier),
                str(result.fen_per_dollar),
                str(result.token_cost_yuan),
                str(result.official_cost_usd),
            ]
        )
