#!/usr/bin/env python3
"""CLI compatibility facade for relay-cost conversion.

Calculation stays in :mod:`converter_core`; interactive use is provided by the
Textual application in :mod:`tui_app`. Importing this module remains safe for
batch and web callers because Textual is imported only when the TUI starts.
"""

from __future__ import annotations

import argparse
import unicodedata
from pathlib import Path
from typing import Sequence

# Keep historical unit_converter exports available for scripts and existing
# tests while the implementation lives in the dependency-free domain module.
from converter_core import (  # noqa: F401
    DEFAULT_CACHED_PRICE,
    DEFAULT_INPUT_PRICE,
    DEFAULT_OUTPUT_PRICE,
    DEFAULT_USAGE,
    DEFAULT_USD_CNY_RATE,
    DEEPSEEK_PRICE_PROFILES,
    ONE_HUNDRED,
    ONE_HUNDRED_MILLION,
    ONE_MILLION,
    SAMPLE_CACHED_TOKENS,
    SAMPLE_INPUT_TOKENS,
    SAMPLE_OUTPUT_TOKENS,
    SAMPLE_TOTAL_TOKENS,
    ChannelCost,
    ConversionRequest,
    ConversionResult,
    ConversionValidationError,
    TokenPriceProfile,
    TokenUsage,
    _as_decimal,
    _non_negative,
    _positive,
    calculate_conversion,
    channel_cost_comparison,
    fen_from_multiplier,
    fen_from_token_cost,
    fen_from_token_cost_for_usage,
    format_decimal,
    multiplier_from_fen,
    official_token_cost_usd,
    official_token_cost_usd_for_usage,
    profile_from_mapping,
    token_cost_yuan,
    token_cost_yuan_for_usage,
)
from app_config import load_settings
from batch_processing import batch_to_csv, batch_to_json
from converter_io import render_result
from unit_translator.application import ConversionService


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def _pad_display(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _format_channel_cost(row: ChannelCost, total_width: int | None = None) -> str:
    usd = "--" if row.usd is None else f"${format_decimal(row.usd)}"
    yuan = f"{format_decimal(row.yuan)} 元"
    if row.usd is None:
        relative = "基准"
    elif row.relative_to_chatgpt is None:
        relative = "--"
    else:
        relative = f"{format_decimal(row.relative_to_chatgpt)}x"
    name_width = max(22, (total_width - 43) if total_width is not None else 22)
    return (
        f"{_pad_display(row.name, name_width)} "
        f"{usd:>12} {yuan:>16} {relative:>12}"
    )


def _print_channel_comparison(rows: tuple[ChannelCost, ...]) -> None:
    print("1 亿混合 Token 渠道对比:")
    print(f"{_pad_display('渠道', 22)} {'USD':>12} {'CNY':>16} {'相对成本倍数':>12}")
    for row in rows:
        print(_format_channel_cost(row))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="换算 ChatGPT 中转成本，并与配置的官方 API 渠道成本对比；不传换算参数时打开终端工作台。"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("-m", "--multiplier", help="中转站倍率，例如 0.05")
    source.add_argument("-f", "--fen", help="账号成本（分/刀），例如 5")
    source.add_argument(
        "-t",
        "--token-cost",
        help="ChatGPT 中转 1 亿混合 Token 的实付成本（元），例如 5",
    )
    parser.add_argument(
        "-r",
        "--ratio",
        default=None,
        help="每 1 元充值获得的站内刀数，默认 1",
    )
    parser.add_argument(
        "-p",
        "--token-price",
        "--input-price",
        dest="token_price",
        default=None,
        help="每百万 ChatGPT 输入 Token 的官方价格（刀），默认 5",
    )
    parser.add_argument(
        "--output-price",
        default=None,
        help="每百万 ChatGPT 输出 Token 的官方价格（刀），默认 30",
    )
    parser.add_argument(
        "--cache-price",
        default=None,
        help="每百万 ChatGPT 缓存 Token 的官方价格（刀），默认 0.5",
    )
    parser.add_argument(
        "--usd-cny-rate",
        default=None,
        help="DeepSeek 官方美元价折算人民币的汇率，默认 7.2",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "csv"),
        default="text",
        dest="output_format",
        help="输出格式，默认 text；JSON/CSV 可供脚本和 Web 集成使用",
    )
    parser.add_argument(
        "--input-file",
        help="批量读取 JSONL 或 CSV 文件；每条记录遵循 /api/v1/convert 请求格式",
    )
    parser.add_argument(
        "--config",
        help="读取 JSON/TOML 配置文件，命令行参数优先于配置文件",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="启动零依赖 Web API（默认监听 127.0.0.1:8787）",
    )
    parser.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=8787, help=argparse.SUPPRESS)
    return parser


def _request_from_args(args: argparse.Namespace, settings: object) -> ConversionRequest:
    """Translate command-line flags into the typed application request."""
    ratio = _positive(
        args.ratio if args.ratio is not None else settings.balance_per_yuan,
        "充值比例",
    )
    input_price = _non_negative(
        args.token_price if args.token_price is not None else settings.chatgpt_profile.input_price,
        "ChatGPT 输入 Token 官方价",
    )
    output_price = _non_negative(
        args.output_price
        if args.output_price is not None
        else settings.chatgpt_profile.output_price,
        "ChatGPT 输出 Token 官方价",
    )
    cached_price = _non_negative(
        args.cache_price
        if args.cache_price is not None
        else settings.chatgpt_profile.cached_price,
        "ChatGPT 缓存 Token 官方价",
    )
    usd_cny_rate = _positive(
        args.usd_cny_rate if args.usd_cny_rate is not None else settings.usd_cny_rate,
        "美元兑人民币汇率",
    )
    if args.token_cost is not None:
        mode, value = "token_cost", args.token_cost
    elif args.multiplier is not None:
        mode, value = "multiplier", args.multiplier
    else:
        mode, value = "fen", args.fen
    return ConversionRequest(
        mode=mode,
        value=value,
        balance_per_yuan=ratio,
        chatgpt_profile=TokenPriceProfile(
            "ChatGPT 中转",
            input_price,
            output_price,
            cached_price,
            provider="ChatGPT relay",
            model="custom",
        ),
        usd_cny_rate=usd_cny_rate,
        usage=settings.usage,
        comparison_profiles=settings.comparison_profiles,
    )


def _print_text_result(result: ConversionResult, balance_per_yuan: object) -> None:
    """Render the human-oriented CLI output without application decisions."""
    if result.mode == "token_cost":
        print("换算口径: 固定 ChatGPT 1 亿混合 Token 实付成本，反推倍率")
        print(f"ChatGPT 中转 1 亿混合 Token 实付: {format_decimal(result.token_cost_yuan)} 元")
        print(f"等价账号成本: {format_decimal(result.fen_per_dollar)} 分/刀")
        print(f"等价倍率: {format_decimal(result.multiplier)}x")
    elif result.mode == "multiplier":
        print("换算口径: 固定中转站倍率，按官方价格计算 Token 成本")
        yuan = result.fen_per_dollar / ONE_HUNDRED
        print(f"倍率: {format_decimal(result.multiplier)}x")
        print(
            f"等价成本: {format_decimal(result.fen_per_dollar)} 分/刀 "
            f"({format_decimal(yuan)} 元/刀)"
        )
    else:
        print("换算口径: 固定账号成本（分/刀），反推中转站倍率")
        print(f"账号成本: {format_decimal(result.fen_per_dollar)} 分/刀")
        print(f"等价倍率: {format_decimal(result.multiplier)}x")
    print(f"充值比例: {format_decimal(balance_per_yuan)} 刀/元")
    print("原始用量样本（已按比例归一化到 1 亿 Token）: 输入 12.73M / 输出 381.68K / 缓存 157.67M")
    profile = result.chatgpt_profile
    print(
        "ChatGPT 官方单价（输入/输出/缓存）: "
        f"{format_decimal(profile.input_price)}/{format_decimal(profile.output_price)}/"
        f"{format_decimal(profile.cached_price)} 刀/百万 Token"
    )
    print(f"DeepSeek 美元汇率: {format_decimal(result.usd_cny_rate)} 元/USD")
    _print_channel_comparison(result.comparison)


def _run_cli(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(args.config)
        if args.input_file:
            if args.output_format == "json":
                print(batch_to_json(args.input_file, settings))
            elif args.output_format == "csv":
                print(batch_to_csv(args.input_file, settings))
            else:
                print("批处理默认输出 JSON；请使用 --format json 或 --format csv")
                return 2
            return 0
        request = _request_from_args(args, settings)
        result = ConversionService().convert(request)
        if args.output_format != "text":
            print(render_result(result, args.output_format))
            return 0
        _print_text_result(result, request.balance_per_yuan)
    except ValueError as exc:
        print(f"错误: {exc}")
        return 2
    return 0


def launch_tui(config_path: str | Path | None = None) -> int:
    """Launch the Textual workbench with a default or explicit editable config."""
    from tui_app import launch_tui as run_textual_tui

    return run_textual_tui(config_path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.serve:
        try:
            from web_api import run_server

            run_server(args.host, args.port, settings_path=args.config)
            return 0
        except ValueError as exc:
            print(f"错误: {exc}")
            return 2
    if args.input_file or any(
        value is not None for value in (args.multiplier, args.fen, args.token_cost)
    ):
        return _run_cli(args)
    try:
        return launch_tui(args.config)
    except (ValueError, OSError) as exc:
        parser.error(f"无法启动终端界面: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
