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
    official_price_per_million: Decimal | int | float | str,
    token_count: Decimal | int | float | str = ONE_HUNDRED_MILLION,
) -> Decimal:
    """Return the account cost in yuan for the requested number of tokens."""
    fen_value = _non_negative(fen_per_dollar, "每刀价格")
    official_price = _non_negative(official_price_per_million, "Token 官方价")
    tokens = _non_negative(token_count, "Token 数量")
    official_dollars = tokens / ONE_MILLION * official_price
    return official_dollars * fen_value / ONE_HUNDRED


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
    parser.add_argument(
        "-r",
        "--ratio",
        default="1",
        help="每 1 元充值获得的站内刀数，默认 1",
    )
    parser.add_argument(
        "-p",
        "--token-price",
        default="1",
        help="每百万 Token 的官方价格（刀），默认 1",
    )
    return parser


def _run_cli(args: argparse.Namespace) -> int:
    try:
        ratio = _positive(args.ratio, "充值比例")
        token_price = _non_negative(args.token_price, "Token 官方价")
        ratio_text = format_decimal(ratio)
        if args.multiplier is not None:
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
        cost = token_cost_yuan(fen, token_price)
        print(
            f"1 亿 Token: {format_decimal(cost)} 元 "
            f"(官方价 {format_decimal(token_price)} 刀/百万 Token)"
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
    token_price: str = "1"
    active_field: int = 0
    replace_on_type: bool = True

    def toggle_mode(self) -> None:
        self.mode = "fen" if self.mode == "multiplier" else "multiplier"
        self.value = "5" if self.mode == "fen" else "0.05"
        self.active_field = 0
        self.replace_on_type = True

    def select_next_field(self) -> None:
        self.active_field = (self.active_field + 1) % 3
        self.replace_on_type = True

    def edit(self, key: int) -> None:
        field = ("value", "ratio", "token_price")[self.active_field]
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
    if not state.value or not state.ratio or not state.token_price:
        return "--", "", "", ""
    try:
        ratio = _positive(state.ratio, "充值比例")
        token_price = _non_negative(state.token_price, "Token 官方价")
        if state.mode == "multiplier":
            multiplier = _non_negative(state.value, "倍率")
            fen = fen_from_multiplier(multiplier, ratio)
            primary = f"{format_decimal(fen)} 分/刀"
        else:
            fen = _non_negative(state.value, "每刀价格")
            multiplier = multiplier_from_fen(fen, ratio)
            primary = f"{format_decimal(multiplier)}x"
        hundred_million_cost = token_cost_yuan(fen, token_price)
        return (
            primary,
            f"{format_decimal(fen / ONE_HUNDRED)} 元/刀",
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

    if height < 20 or width < 60:
        message = "终端窗口至少需要 60 x 20"
        _addstr(screen, height // 2, _centered_x(width, message), message, error_color)
        screen.refresh()
        return

    panel_width = min(70, width - 4)
    left = (width - panel_width) // 2

    title = "倍率换算器"
    _addstr(screen, 2, _centered_x(width, title), title, curses.A_BOLD | accent)
    subtitle = "GPT 账号成本 / 中转站倍率"
    _addstr(screen, 4, _centered_x(width, subtitle), subtitle, curses.A_DIM)

    forward = " 倍率 -> 几分/刀 "
    reverse = " 几分/刀 -> 倍率 "
    modes_width = _display_width(forward) + _display_width(reverse) + 3
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

    try:
        screen.hline(8, left, curses.ACS_HLINE, panel_width)
    except curses.error:
        pass

    label = "中转站倍率" if state.mode == "multiplier" else "账号成本"
    unit = "x" if state.mode == "multiplier" else "分/刀"
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

    token_price_label = "官方价/百万 Token"
    _addstr(screen, 14, left + 2, token_price_label)
    token_price_attr = (
        curses.A_REVERSE | curses.A_BOLD
        if state.active_field == 2
        else curses.A_BOLD
    )
    token_price_field = f" {state.token_price or ' '} "
    _addstr(screen, 14, field_x, token_price_field, token_price_attr)
    _addstr(
        screen,
        14,
        field_x + _display_width(token_price_field) + 1,
        "刀",
    )

    result, secondary, hundred_million_cost, error = _result_for(state)
    result_label = "换算结果"
    _addstr(screen, 16, left + 2, result_label, curses.A_DIM)
    _addstr(screen, 16, field_x, result, curses.A_BOLD | success)
    if secondary:
        _addstr(screen, 17, field_x, secondary, curses.A_DIM)
    if hundred_million_cost:
        _addstr(screen, 18, left + 2, "1 亿 Token", curses.A_DIM)
        _addstr(screen, 18, field_x, hundred_million_cost, curses.A_BOLD | success)
    if error:
        _addstr(screen, 18, left + 2, error, error_color)

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
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, ord("m"), ord("M")):
            state.toggle_mode()
        elif key in (9, curses.KEY_UP, curses.KEY_DOWN):
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
        print(f"1 亿 Token: {hundred_million_cost}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.multiplier is not None or args.fen is not None:
        return _run_cli(args)
    try:
        return launch_tui()
    except (curses.error, OSError) as exc:
        parser.error(f"无法启动终端界面: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
