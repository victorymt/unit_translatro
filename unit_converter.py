#!/usr/bin/env python3
"""Convert relay-station multipliers and account costs."""

from __future__ import annotations

import argparse
import curses
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence


ONE_HUNDRED = Decimal("100")
ONE_MILLION = Decimal("1000000")
ONE_HUNDRED_MILLION = Decimal("100000000")
SAMPLE_INPUT_TOKENS = Decimal("12730000")
SAMPLE_OUTPUT_TOKENS = Decimal("381680")
SAMPLE_CACHED_TOKENS = Decimal("157670000")
SAMPLE_TOTAL_TOKENS = (
    SAMPLE_INPUT_TOKENS + SAMPLE_OUTPUT_TOKENS + SAMPLE_CACHED_TOKENS
)
DEFAULT_INPUT_PRICE = Decimal("5")
DEFAULT_OUTPUT_PRICE = Decimal("30")
DEFAULT_CACHED_PRICE = Decimal("0.5")


def _as_decimal(value: Decimal | int | float | str, name: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name}必须是有效数字") from exc
    if not number.is_finite():
        raise ValueError(f"{name}必须是有限数字")
    return number


def _non_negative(value: Decimal | int | float | str, name: str) -> Decimal:
    number = _as_decimal(value, name)
    if number < 0:
        raise ValueError(f"{name}不能小于 0")
    return number


def _positive(value: Decimal | int | float | str, name: str) -> Decimal:
    number = _as_decimal(value, name)
    if number <= 0:
        raise ValueError(f"{name}必须大于 0")
    return number


def fen_from_multiplier(
    multiplier: Decimal | int | float | str,
    balance_per_yuan: Decimal | int | float | str = Decimal("1"),
) -> Decimal:
    """Return fen paid per official USD of usage."""
    multiplier_value = _non_negative(multiplier, "倍率")
    recharge_ratio = _positive(balance_per_yuan, "充值比例")
    return multiplier_value * ONE_HUNDRED / recharge_ratio


def multiplier_from_fen(
    fen_per_dollar: Decimal | int | float | str,
    balance_per_yuan: Decimal | int | float | str = Decimal("1"),
) -> Decimal:
    """Return the relay multiplier represented by a fen-per-USD cost."""
    fen_value = _non_negative(fen_per_dollar, "每刀价格")
    recharge_ratio = _positive(balance_per_yuan, "充值比例")
    return fen_value * recharge_ratio / ONE_HUNDRED


def token_cost_yuan(
    fen_per_dollar: Decimal | int | float | str,
    official_price_per_million: Decimal | int | float | str = DEFAULT_INPUT_PRICE,
    token_count: Decimal | int | float | str = ONE_HUNDRED_MILLION,
    *,
    output_price_per_million: Decimal | int | float | str = DEFAULT_OUTPUT_PRICE,
    cached_price_per_million: Decimal | int | float | str = DEFAULT_CACHED_PRICE,
) -> Decimal:
    """Return the account cost for tokens distributed like the usage sample."""
    fen_value = _non_negative(fen_per_dollar, "每刀价格")
    input_price = _non_negative(official_price_per_million, "输入 Token 官方价")
    output_price = _non_negative(output_price_per_million, "输出 Token 官方价")
    cached_price = _non_negative(cached_price_per_million, "缓存 Token 官方价")
    tokens = _non_negative(token_count, "Token 数量")
    scale = tokens / SAMPLE_TOTAL_TOKENS
    official_dollars = (
        SAMPLE_INPUT_TOKENS * scale * input_price
        + SAMPLE_OUTPUT_TOKENS * scale * output_price
        + SAMPLE_CACHED_TOKENS * scale * cached_price
    ) / ONE_MILLION
    return official_dollars * fen_value / ONE_HUNDRED


def fen_from_token_cost(
    cost_yuan: Decimal | int | float | str,
    official_price_per_million: Decimal | int | float | str = DEFAULT_INPUT_PRICE,
    token_count: Decimal | int | float | str = ONE_HUNDRED_MILLION,
    *,
    output_price_per_million: Decimal | int | float | str = DEFAULT_OUTPUT_PRICE,
    cached_price_per_million: Decimal | int | float | str = DEFAULT_CACHED_PRICE,
) -> Decimal:
    """Return fen per official dollar represented by a mixed-token cost."""
    cost = _non_negative(cost_yuan, "Token 成本")
    official_dollars = token_cost_yuan(
        ONE_HUNDRED,
        official_price_per_million,
        token_count,
        output_price_per_million=output_price_per_million,
        cached_price_per_million=cached_price_per_million,
    )
    if official_dollars == 0:
        raise ValueError("Token 官方价不能全部为 0")
    return cost * ONE_HUNDRED / official_dollars


def format_decimal(value: Decimal, max_places: int = 8) -> str:
    """Format Decimal without scientific notation or noisy trailing zeroes."""
    quantum = Decimal(1).scaleb(-max_places)
    rounded = value.quantize(quantum)
    return format(rounded, "f").rstrip("0").rstrip(".") or "0"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="换算 GPT 账号的几分一刀成本与中转站倍率；不传换算参数时打开终端界面。"
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("-m", "--multiplier", help="中转站倍率，例如 0.05")
    source.add_argument("-f", "--fen", help="账号成本（分/刀），例如 5")
    source.add_argument(
        "-t",
        "--token-cost",
        help="1 亿混合 Token 的实付成本（元），例如 5",
    )
    parser.add_argument(
        "-r",
        "--ratio",
        default="1",
        help="每 1 元充值获得的站内刀数，默认 1",
    )
    parser.add_argument(
        "-p",
        "--token-price",
        "--input-price",
        dest="token_price",
        default="5",
        help="每百万输入 Token 的官方价格（刀），默认 5",
    )
    parser.add_argument(
        "--output-price",
        default="30",
        help="每百万输出 Token 的官方价格（刀），默认 30",
    )
    parser.add_argument(
        "--cache-price",
        default="0.5",
        help="每百万缓存 Token 的官方价格（刀），默认 0.5",
    )
    return parser


def _run_cli(args: argparse.Namespace) -> int:
    try:
        ratio = _positive(args.ratio, "充值比例")
        input_price = _non_negative(args.token_price, "输入 Token 官方价")
        output_price = _non_negative(args.output_price, "输出 Token 官方价")
        cached_price = _non_negative(args.cache_price, "缓存 Token 官方价")
        ratio_text = format_decimal(ratio)
        if args.token_cost is not None:
            requested_cost = _non_negative(args.token_cost, "1 亿 Token 成本")
            fen = fen_from_token_cost(
                requested_cost,
                input_price,
                output_price_per_million=output_price,
                cached_price_per_million=cached_price,
            )
            multiplier = multiplier_from_fen(fen, ratio)
            print(f"1 亿混合 Token 实付: {format_decimal(requested_cost)} 元")
            print(f"等价账号成本: {format_decimal(fen)} 分/刀")
            print(f"等价倍率: {format_decimal(multiplier)}x")
        elif args.multiplier is not None:
            multiplier = _non_negative(args.multiplier, "倍率")
            fen = fen_from_multiplier(multiplier, ratio)
            yuan = fen / ONE_HUNDRED
            print(f"倍率: {format_decimal(multiplier)}x")
            print(
                f"等价成本: {format_decimal(fen)} 分/刀 "
                f"({format_decimal(yuan)} 元/刀)"
            )
        else:
            fen = _non_negative(args.fen, "每刀价格")
            multiplier = multiplier_from_fen(fen, ratio)
            print(f"账号成本: {format_decimal(fen)} 分/刀")
            print(f"等价倍率: {format_decimal(multiplier)}x")
        print(f"充值比例: {ratio_text} 刀/元")
        print("用量配比: 输入 12.73M / 输出 381.68K / 缓存 157.67M")
        cost = token_cost_yuan(
            fen,
            input_price,
            output_price_per_million=output_price,
            cached_price_per_million=cached_price,
        )
        print(
            f"1 亿混合 Token: {format_decimal(cost)} 元 "
            f"(输入/输出/缓存单价 "
            f"{format_decimal(input_price)}/{format_decimal(output_price)}/"
            f"{format_decimal(cached_price)} 刀/百万 Token)"
        )
    except ValueError as exc:
        print(f"错误: {exc}")
        return 2
    return 0


@dataclass
class TuiState:
    mode: str = "multiplier"
    value: str = "0.05"
    ratio: str = "1"
    token_price: str = "5"
    output_price: str = "30"
    cached_price: str = "0.5"
    active_field: int = 0
    replace_on_type: bool = True

    def toggle_mode(self, direction: int = 1) -> None:
        modes = ("multiplier", "fen", "token_cost")
        defaults = ("0.05", "5", "5")
        index = (modes.index(self.mode) + direction) % len(modes)
        self.mode = modes[index]
        self.value = defaults[index]
        self.active_field = 0
        self.replace_on_type = True

    def select_next_field(self) -> None:
        self.active_field = (self.active_field + 1) % 5
        self.replace_on_type = True

    def select_previous_field(self) -> None:
        self.active_field = (self.active_field - 1) % 5
        self.replace_on_type = True

    def edit(self, key: int) -> None:
        field = (
            "value",
            "ratio",
            "token_price",
            "output_price",
            "cached_price",
        )[self.active_field]
        current = getattr(self, field)
        if key in (curses.KEY_BACKSPACE, 127, 8):
            setattr(self, field, "" if self.replace_on_type else current[:-1])
            self.replace_on_type = False
            return
        if key == 21:  # Ctrl+U
            setattr(self, field, "")
            self.replace_on_type = False
            return
        if 0 <= key <= 255 and chr(key) in "0123456789.":
            character = chr(key)
            if self.replace_on_type:
                current = ""
            if character == "." and "." in current:
                return
            if character == "." and not current:
                current = "0"
            if len(current) < 18:
                setattr(self, field, current + character)
                self.replace_on_type = False


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def _centered_x(width: int, text: str) -> int:
    return max(0, (width - _display_width(text)) // 2)


def _result_for(state: TuiState) -> tuple[str, str, str, str]:
    if not all(
        (
            state.value,
            state.ratio,
            state.token_price,
            state.output_price,
            state.cached_price,
        )
    ):
        return "--", "", "", ""
    try:
        ratio = _positive(state.ratio, "充值比例")
        input_price = _non_negative(state.token_price, "输入 Token 官方价")
        output_price = _non_negative(state.output_price, "输出 Token 官方价")
        cached_price = _non_negative(state.cached_price, "缓存 Token 官方价")
        if state.mode == "token_cost":
            requested_cost = _non_negative(state.value, "1 亿 Token 成本")
            fen = fen_from_token_cost(
                requested_cost,
                input_price,
                output_price_per_million=output_price,
                cached_price_per_million=cached_price,
            )
            multiplier = multiplier_from_fen(fen, ratio)
            primary = f"{format_decimal(multiplier)}x"
        elif state.mode == "multiplier":
            multiplier = _non_negative(state.value, "倍率")
            fen = fen_from_multiplier(multiplier, ratio)
            primary = f"{format_decimal(fen)} 分/刀"
        else:
            fen = _non_negative(state.value, "每刀价格")
            multiplier = multiplier_from_fen(fen, ratio)
            primary = f"{format_decimal(multiplier)}x"
        hundred_million_cost = token_cost_yuan(
            fen,
            input_price,
            output_price_per_million=output_price,
            cached_price_per_million=cached_price,
        )
        secondary = (
            f"{format_decimal(fen)} 分/刀"
            if state.mode == "token_cost"
            else f"{format_decimal(fen / ONE_HUNDRED)} 元/刀"
        )
        return (
            primary,
            secondary,
            f"{format_decimal(hundred_million_cost)} 元",
            "",
        )
    except ValueError as exc:
        return "--", "", "", str(exc)


def _addstr(
    screen: curses.window, y: int, x: int, text: str, attributes: int = 0
) -> None:
    height, width = screen.getmaxyx()
    if y < 0 or y >= height or x < 0 or x >= width - 1:
        return
    try:
        screen.addnstr(y, x, text, max(0, width - x - 1), attributes)
    except curses.error:
        pass


def _init_colors() -> tuple[int, int, int]:
    if not curses.has_colors():
        return curses.A_BOLD, curses.A_BOLD, curses.A_BOLD
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    return curses.color_pair(1), curses.color_pair(2), curses.color_pair(3)


def _draw_tui(screen: curses.window, state: TuiState) -> None:
    screen.erase()
    height, width = screen.getmaxyx()
    accent, success, error_color = _init_colors()

    if height < 26 or width < 60:
        message = "终端窗口至少需要 60 x 26"
        _addstr(screen, height // 2, _centered_x(width, message), message, error_color)
        screen.refresh()
        return

    panel_width = min(70, width - 4)
    left = (width - panel_width) // 2

    title = "倍率换算器"
    _addstr(screen, 2, _centered_x(width, title), title, curses.A_BOLD | accent)
    subtitle = "GPT 账号成本 / 中转站倍率 / Token 预算"
    _addstr(screen, 4, _centered_x(width, subtitle), subtitle, curses.A_DIM)

    forward = " 倍率->几分 "
    reverse = " 几分->倍率 "
    token_cost_mode = " 1亿成本->两者 "
    modes_width = sum(
        _display_width(mode) for mode in (forward, reverse, token_cost_mode)
    ) + 6
    modes_left = (width - modes_width) // 2
    forward_attr = curses.A_REVERSE if state.mode == "multiplier" else curses.A_NORMAL
    reverse_attr = curses.A_REVERSE if state.mode == "fen" else curses.A_NORMAL
    _addstr(screen, 6, modes_left, forward, forward_attr)
    _addstr(
        screen,
        6,
        modes_left + _display_width(forward) + 3,
        reverse,
        reverse_attr,
    )
    token_cost_attr = (
        curses.A_REVERSE if state.mode == "token_cost" else curses.A_NORMAL
    )
    _addstr(
        screen,
        6,
        modes_left + _display_width(forward) + _display_width(reverse) + 6,
        token_cost_mode,
        token_cost_attr,
    )

    try:
        screen.hline(8, left, curses.ACS_HLINE, panel_width)
    except curses.error:
        pass

    field_options = {
        "multiplier": ("中转站倍率", "x"),
        "fen": ("账号成本", "分/刀"),
        "token_cost": ("1 亿 Token 实付", "元"),
    }
    label, unit = field_options[state.mode]
    _addstr(screen, 10, left + 2, label)
    value_attr = curses.A_REVERSE | curses.A_BOLD if state.active_field == 0 else curses.A_BOLD
    value_field = f" {state.value or ' '} "
    field_x = left + 23
    _addstr(screen, 10, field_x, value_field, value_attr)
    _addstr(screen, 10, field_x + _display_width(value_field) + 1, unit)

    ratio_label = "1 元充值获得"
    _addstr(screen, 12, left + 2, ratio_label)
    ratio_attr = curses.A_REVERSE | curses.A_BOLD if state.active_field == 1 else curses.A_BOLD
    ratio_field = f" {state.ratio or ' '} "
    _addstr(screen, 12, field_x, ratio_field, ratio_attr)
    _addstr(screen, 12, field_x + _display_width(ratio_field) + 1, "刀额度")

    price_fields = (
        (14, "输入价/百万 Token", state.token_price),
        (16, "输出价/百万 Token", state.output_price),
        (18, "缓存价/百万 Token", state.cached_price),
    )
    for index, (row, price_label, price) in enumerate(price_fields, start=2):
        _addstr(screen, row, left + 2, price_label)
        price_attr = (
            curses.A_REVERSE | curses.A_BOLD
            if state.active_field == index
            else curses.A_BOLD
        )
        price_field = f" {price or ' '} "
        _addstr(screen, row, field_x, price_field, price_attr)
        _addstr(
            screen,
            row,
            field_x + _display_width(price_field) + 1,
            "刀",
        )

    mix = "配比: 输入 12.73M / 输出 381.68K / 缓存 157.67M"
    _addstr(screen, 20, left + 2, mix, curses.A_DIM)

    result, secondary, hundred_million_cost, error = _result_for(state)
    result_label = "换算结果"
    _addstr(screen, 22, left + 2, result_label, curses.A_DIM)
    _addstr(screen, 22, field_x, result, curses.A_BOLD | success)
    if secondary:
        _addstr(screen, 23, field_x, secondary, curses.A_DIM)
    if hundred_million_cost:
        _addstr(screen, 24, left + 2, "1 亿混合 Token", curses.A_DIM)
        _addstr(screen, 24, field_x, hundred_million_cost, curses.A_BOLD | success)
    if error:
        _addstr(screen, 24, left + 2, error, error_color)

    screen.refresh()


def _curses_main(screen: curses.window) -> tuple[str, str, str] | None:
    state = TuiState()
    curses.curs_set(0)
    screen.keypad(True)

    while True:
        _draw_tui(screen, state)
        key = screen.getch()
        if key in (ord("q"), ord("Q"), 27):
            return None
        if key == curses.KEY_LEFT:
            state.toggle_mode(-1)
        elif key in (curses.KEY_RIGHT, ord("m"), ord("M")):
            state.toggle_mode()
        elif key == curses.KEY_UP:
            state.select_previous_field()
        elif key in (9, curses.KEY_DOWN):
            state.select_next_field()
        elif key in (10, 13, curses.KEY_ENTER):
            result, secondary, hundred_million_cost, error = _result_for(state)
            if not error and result != "--":
                return result, secondary, hundred_million_cost
        else:
            state.edit(key)


def launch_tui() -> int:
    result = curses.wrapper(_curses_main)
    if result is not None:
        primary, secondary, hundred_million_cost = result
        print(f"换算结果: {primary}")
        if secondary:
            print(f"等价成本: {secondary}")
        print(f"1 亿混合 Token: {hundred_million_cost}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if any(
        value is not None for value in (args.multiplier, args.fen, args.token_cost)
    ):
        return _run_cli(args)
    try:
        return launch_tui()
    except (curses.error, OSError) as exc:
        parser.error(f"无法启动终端界面: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
