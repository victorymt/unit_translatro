"""Local price-catalog validation and inspection command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from unit_translator.infrastructure.catalog import DEFAULT_CATALOG_PATH, PricingCatalog


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验并查看 unit-translator 的本地价格目录。"
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=str(DEFAULT_CATALOG_PATH),
        help="价格目录 JSON 路径，默认使用内置目录",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--summary",
        action="store_true",
        help="打印每个渠道的摘要",
    )
    output.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="以 JSON 输出校验摘要",
    )
    parser.add_argument(
        "--as-of",
        help="只统计不晚于 YYYY-MM-DD 生效的渠道",
    )
    return parser


def catalog_summary(
    catalog: PricingCatalog,
    path: str | Path,
    *,
    as_of: str | None = None,
) -> dict[str, object]:
    profiles = catalog.list_profiles(as_of=as_of)
    return {
        "path": str(path),
        "version": catalog.version,
        "profile_count": len(catalog.profiles),
        "active_profile_count": len(profiles),
        "profiles": [
            {
                "name": profile.name,
                "provider": profile.provider,
                "model": profile.model,
                "effective_at": profile.effective_at,
                "input_price": str(profile.input_price),
                "output_price": str(profile.output_price),
                "cached_price": str(profile.cached_price),
            }
            for profile in profiles
        ],
    }


def _print_text_summary(summary: dict[str, object], *, detailed: bool) -> None:
    print(f"价格目录有效: {summary['path']}")
    print(f"版本: {summary['version']}")
    print(
        f"渠道: {summary['active_profile_count']}/{summary['profile_count']} 个当前生效"
    )
    if not detailed:
        return
    for profile in summary["profiles"]:
        assert isinstance(profile, dict)
        effective_at = profile["effective_at"] or "始终"
        print(
            f"- {profile['name']} ({profile['provider']}/{profile['model']}): "
            f"输入 {profile['input_price']} / 输出 {profile['output_price']} / "
            f"缓存 {profile['cached_price']}，生效 {effective_at}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        catalog = PricingCatalog.from_file(args.path)
        summary = catalog_summary(catalog, args.path, as_of=args.as_of)
    except ValueError as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(summary, ensure_ascii=False, separators=(",", ":")))
    else:
        _print_text_summary(summary, detailed=args.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
