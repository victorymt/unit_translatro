"""Compact ncurses workbench for unit translation and relay-cost comparison.

The screen deliberately uses fixed rows instead of a widget layout engine. It
keeps the common conversion workflow visible on small terminals and leaves
configuration changes in memory until the user explicitly saves them.
"""

from __future__ import annotations

import curses
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from app_config import Settings
from converter_core import TokenPriceProfile, _non_negative, _positive, format_decimal
from settings_store import (
    SettingsDocument,
    load_settings_document,
    save_settings_document,
)
from unit_translator.adapters.tui.calculator import (
    CalculationDisplay,
    CalculatorInputs,
    calculate_display,
)
from unit_translator.application import ConversionService


MODE_LABELS = {
    "multiplier": "固定倍率",
    "fen": "固定账号成本",
    "token_cost": "固定 1 亿成本",
}
MODE_DEFAULTS = {"multiplier": "0.05", "fen": "5", "token_cost": "5"}
FIELD_NAMES = (
    "value",
    "balance_per_yuan",
    "usd_cny_rate",
    "input_price",
    "output_price",
    "cached_price",
)


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def clip_display(text: str, width: int) -> str:
    result: list[str] = []
    used = 0
    for char in text:
        char_width = 2 if unicodedata.east_asian_width(char) in "WF" else 1
        if used + char_width > width:
            break
        result.append(char)
        used += char_width
    return "".join(result)


def pad_display(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


@dataclass
class CursesTuiState:
    """Editable ncurses state kept independent from terminal rendering."""

    document: SettingsDocument
    settings: Settings
    saved_settings: Settings
    mode: str = "multiplier"
    value: str = "0.05"
    balance_per_yuan: str = "1"
    usd_cny_rate: str = "7.2"
    input_price: str = "5"
    output_price: str = "30"
    cached_price: str = "0.5"
    active_field: int = 0
    replace_on_type: bool = True
    message: str = ""
    error: str = ""

    @classmethod
    def from_document(cls, document: SettingsDocument) -> "CursesTuiState":
        settings = document.settings
        profile = settings.chatgpt_profile
        return cls(
            document=document,
            settings=settings,
            saved_settings=settings,
            balance_per_yuan=str(settings.balance_per_yuan),
            usd_cny_rate=str(settings.usd_cny_rate),
            input_price=str(profile.input_price),
            output_price=str(profile.output_price),
            cached_price=str(profile.cached_price),
        )

    def _field_value(self, name: str) -> str:
        return str(getattr(self, name))

    def _set_field_value(self, name: str, value: str) -> None:
        setattr(self, name, value)

    def field_values(self) -> tuple[str, ...]:
        return tuple(self._field_value(name) for name in FIELD_NAMES)

    def move_field(self, step: int) -> None:
        self.active_field = (self.active_field + step) % len(FIELD_NAMES)
        self.replace_on_type = True

    def set_mode(self, mode: str) -> None:
        if mode not in MODE_LABELS:
            return
        self.mode = mode
        self.value = MODE_DEFAULTS[mode]
        self.active_field = 0
        self.replace_on_type = True
        self.error = ""

    def cycle_mode(self, step: int = 1) -> None:
        modes = tuple(MODE_LABELS)
        self.set_mode(modes[(modes.index(self.mode) + step) % len(modes)])

    def edit(self, key: int) -> None:
        name = FIELD_NAMES[self.active_field]
        current = self._field_value(name)
        if key in (curses.KEY_BACKSPACE, 127, 8):
            self._set_field_value(name, "" if self.replace_on_type else current[:-1])
            self.replace_on_type = False
            return
        if key == 21:  # Ctrl+U
            self._set_field_value(name, "")
            self.replace_on_type = False
            return
        if key < 0 or key > 255:
            return
        character = chr(key)
        if character not in "0123456789.-":
            return
        if self.replace_on_type:
            current = ""
        if character == "." and "." in current:
            return
        if character == "-" and current:
            return
        if character == "." and not current:
            current = "0"
        if len(current) < 24:
            self._set_field_value(name, current + character)
            self.replace_on_type = False

    def calculator_inputs(self) -> CalculatorInputs:
        return CalculatorInputs(
            mode=self.mode,
            value=self.value,
            balance_per_yuan=self.balance_per_yuan,
            input_price=self.input_price,
            output_price=self.output_price,
            cached_price=self.cached_price,
            usd_cny_rate=self.usd_cny_rate,
        )

    def calculate(self) -> CalculationDisplay:
        return calculate_display(self.calculator_inputs(), self.settings, ConversionService())

    def settings_from_fields(self) -> Settings:
        _positive(self.balance_per_yuan, "充值比例")
        _positive(self.usd_cny_rate, "美元兑人民币汇率")
        profile = self.settings.chatgpt_profile
        updated_profile = TokenPriceProfile(
            profile.name,
            _non_negative(self.input_price, "ChatGPT 输入 Token 官方价"),
            _non_negative(self.output_price, "ChatGPT 输出 Token 官方价"),
            _non_negative(self.cached_price, "ChatGPT 缓存 Token 官方价"),
            provider=profile.provider,
            model=profile.model,
            currency=profile.currency,
            unit=profile.unit,
            effective_at=profile.effective_at,
            source=profile.source,
            version=profile.version,
        )
        return replace(
            self.settings,
            balance_per_yuan=self.balance_per_yuan,
            chatgpt_profile=updated_profile,
            usd_cny_rate=self.usd_cny_rate,
        )

    def is_dirty(self) -> bool:
        try:
            current = self.settings_from_fields()
        except ValueError:
            return True
        return current != self.saved_settings

    def save(self) -> None:
        self.settings = self.settings_from_fields()
        self.document = save_settings_document(self.document, self.settings)
        self.saved_settings = self.settings
        self.message = "配置已保存"
        self.error = ""

    def discard(self) -> None:
        self.settings = self.saved_settings
        profile = self.settings.chatgpt_profile
        self.balance_per_yuan = str(self.settings.balance_per_yuan)
        self.usd_cny_rate = str(self.settings.usd_cny_rate)
        self.input_price = str(profile.input_price)
        self.output_price = str(profile.output_price)
        self.cached_price = str(profile.cached_price)
        self.value = MODE_DEFAULTS[self.mode]
        self.replace_on_type = True
        self.message = "已还原未保存修改"
        self.error = ""

def _addstr(screen: curses.window, row: int, col: int, text: str, attr: int = 0) -> None:
    height, width = screen.getmaxyx()
    if row < 0 or row >= height or col < 0 or col >= width:
        return
    try:
        screen.addnstr(row, col, text, max(0, width - col - 1), attr)
    except curses.error:
        pass


def _init_colors() -> tuple[int, int, int, int]:
    if not curses.has_colors():
        return curses.A_BOLD, curses.A_BOLD, curses.A_BOLD, curses.A_DIM
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    return curses.color_pair(1), curses.color_pair(2), curses.color_pair(3), curses.A_DIM


def _field(
    screen: curses.window,
    row: int,
    col: int,
    label: str,
    value: str,
    unit: str,
    active: bool,
) -> None:
    _addstr(screen, row, col, label)
    value_col = col + max(9, display_width(label) + 1)
    value_text = f" {value or ' '} "
    attr = curses.A_REVERSE | curses.A_BOLD if active else curses.A_BOLD
    _addstr(screen, row, value_col, value_text, attr)
    _addstr(screen, row, value_col + display_width(value_text) + 1, unit)


def _draw_main(screen: curses.window, state: CursesTuiState, colors: tuple[int, int, int, int]) -> None:
    screen.erase()
    height, width = screen.getmaxyx()
    accent, success, error_color, dim = colors
    if height < 20 or width < 72:
        message = "终端窗口至少需要 72 x 20"
        _addstr(screen, height // 2, max(0, (width - display_width(message)) // 2), message, error_color)
        screen.refresh()
        return

    _addstr(screen, 0, 2, "Unit Translator", curses.A_BOLD | accent)
    status = "未保存" if state.is_dirty() else "已保存"
    _addstr(screen, 0, max(2, width - display_width(status) - 2), status, dim)
    _addstr(screen, 1, 2, clip_display(str(state.document.path), width - 4), dim)

    mode_col = 2
    for mode, label in MODE_LABELS.items():
        mode_text = f"[{label}]" if mode == state.mode else f" {label} "
        mode_attr = curses.A_REVERSE | accent if mode == state.mode else 0
        _addstr(screen, 3, mode_col, mode_text, mode_attr)
        mode_col += display_width(mode_text) + 2
    _field(screen, 5, 2, "换算值", state.value, "倍" if state.mode == "multiplier" else "分/刀", state.active_field == 0)
    _field(screen, 5, 38, "充值比例", state.balance_per_yuan, "刀/元", state.active_field == 1)
    _field(screen, 7, 2, "美元汇率", state.usd_cny_rate, "元/USD", state.active_field == 2)
    _field(screen, 7, 38, "输入价", state.input_price, "刀/1M", state.active_field == 3)
    _field(screen, 9, 2, "输出价", state.output_price, "刀/1M", state.active_field == 4)
    _field(screen, 9, 38, "缓存价", state.cached_price, "刀/1M", state.active_field == 5)

    try:
        display = state.calculate()
    except ValueError as exc:
        display = None
        state.error = str(exc)
    else:
        state.error = ""
    _addstr(screen, 11, 2, "结果", curses.A_BOLD | accent)
    if display is not None:
        _addstr(screen, 12, 2, f"倍率 {display.multiplier}    账号成本 {display.fen_per_dollar}", curses.A_BOLD | success)
        _addstr(screen, 13, 2, f"1 亿成本 {display.token_cost_yuan}    官方成本 {display.official_cost_usd}", curses.A_BOLD)
        _addstr(screen, 15, 2, "渠道对比", curses.A_BOLD | accent)
        name_width = max(20, min(30, width - 49))
        _addstr(screen, 16, 2, f"{pad_display('渠道', name_width)} {'USD':>12} {'CNY':>14} {'相对成本':>10}", dim)
        for row_index, row in enumerate(display.comparison[: max(0, height - 17)], start=17):
            name = pad_display(clip_display(row.name, name_width), name_width)
            _addstr(screen, row_index, 2, f"{name} {row.usd:>12} {row.yuan:>14} {row.relative_cost:>10}")
    if state.error:
        _addstr(screen, 14, 2, clip_display(state.error, width - 4), error_color)
    elif state.message:
        _addstr(screen, 14, 2, clip_display(state.message, width - 4), success)
    _addstr(screen, height - 1, 2, "Tab/方向键 编辑  m 切换模式  c 渠道  s 保存  r 还原  q 退出", dim)
    screen.refresh()


def _confirm(screen: curses.window, prompt: str) -> bool:
    height, width = screen.getmaxyx()
    _addstr(screen, height - 2, 2, clip_display(f"{prompt} [y/N]", width - 4), curses.A_REVERSE)
    screen.refresh()
    key = screen.getch()
    return key in (ord("y"), ord("Y"))


def _prompt(screen: curses.window, row: int, label: str, default: str = "") -> str:
    """Read one bounded line while keeping curses rendering predictable."""
    height, width = screen.getmaxyx()
    if row >= height:
        return default
    prefix = f"{label} [{default}]: " if default else f"{label}: "
    col = 2
    _addstr(screen, row, col, prefix)
    screen.refresh()
    curses.echo()
    try:
        available = max(1, width - col - display_width(prefix) - 2)
        raw = screen.getstr(row, min(width - 2, col + display_width(prefix)), available)
    except curses.error:
        raw = b""
    finally:
        curses.noecho()
    value = raw.decode("utf-8", errors="replace").strip()
    return value or default


def _edit_channel(screen: curses.window, profile: TokenPriceProfile | None) -> TokenPriceProfile | None:
    """Edit one channel using fixed rows and blocking line input."""
    screen.erase()
    _addstr(screen, 1, 2, "新建渠道" if profile is None else "编辑渠道", curses.A_BOLD)
    values = {
        "name": _prompt(screen, 3, "名称", profile.name if profile else ""),
        "provider": _prompt(screen, 4, "提供商", profile.provider if profile else "custom"),
        "model": _prompt(screen, 5, "模型", profile.model if profile else ""),
        "input_price": _prompt(screen, 7, "输入价", str(profile.input_price) if profile else ""),
        "output_price": _prompt(screen, 8, "输出价", str(profile.output_price) if profile else ""),
        "cached_price": _prompt(screen, 9, "缓存价", str(profile.cached_price) if profile else ""),
        "effective_at": _prompt(screen, 11, "生效日期", profile.effective_at or "" if profile else ""),
        "source": _prompt(screen, 12, "来源", profile.source or "" if profile else ""),
        "version": _prompt(screen, 13, "版本", profile.version or "" if profile else ""),
    }
    try:
        if not values["name"]:
            raise ValueError("渠道名称不能为空")
        if not values["provider"]:
            raise ValueError("提供商不能为空")
        effective_at = values["effective_at"] or None
        if effective_at:
            from datetime import date

            date.fromisoformat(effective_at)
        return TokenPriceProfile(
            values["name"],
            values["input_price"],
            values["output_price"],
            values["cached_price"],
            provider=values["provider"],
            model=values["model"],
            effective_at=effective_at,
            source=values["source"] or None,
            version=values["version"] or None,
        )
    except ValueError as exc:
        _addstr(screen, 15, 2, str(exc), curses.A_BOLD)
        _addstr(screen, 17, 2, "按任意键返回", curses.A_DIM)
        screen.refresh()
        screen.getch()
        return None


def _draw_channels(
    screen: curses.window,
    state: CursesTuiState,
    selected: int,
    colors: tuple[int, int, int, int],
) -> None:
    screen.erase()
    height, width = screen.getmaxyx()
    accent, _, error_color, dim = colors
    _addstr(screen, 0, 2, "渠道管理", curses.A_BOLD | accent)
    _addstr(screen, 1, 2, "↑/↓ 选择  n 新建  e 编辑  d 删除  s 保存  Esc 返回", dim)
    _addstr(screen, 2, 2, "价格单位：USD / 1M tokens", dim)
    profiles = state.settings.comparison_profiles
    if not profiles:
        _addstr(screen, 4, 2, "暂无渠道", dim)
    else:
        # Keep every core pricing field in the list; only optional metadata is
        # relegated to the selected-channel detail rows below.
        price_width = 10
        name_width = max(14, min(20, (width - 43) // 2))
        provider_width = max(15, width - name_width - 43)
        header = (
            f"{pad_display('渠道', name_width)}  "
            f"{pad_display('提供商 / 模型', provider_width)}  "
            f"{pad_display('输入价', price_width)}  "
            f"{pad_display('输出价', price_width)}  "
            f"{pad_display('缓存价', price_width)}"
        )
        _addstr(screen, 3, 2, clip_display(header, width - 4), dim)
        visible = max(1, height - 11)
        start = min(max(0, selected - visible + 1), max(0, len(profiles) - visible))
        for row, index in enumerate(range(start, min(len(profiles), start + visible)), start=4):
            profile = profiles[index]
            marker = ">" if index == selected else " "
            name = pad_display(clip_display(profile.name, name_width - 2), name_width - 2)
            provider = pad_display(
                clip_display(f"{profile.provider} / {profile.model or '未标注'}", provider_width),
                provider_width,
            )
            text = (
                f"{marker} {name}  {provider}  "
                f"{format_decimal(profile.input_price):>{price_width}}  "
                f"{format_decimal(profile.output_price):>{price_width}}  "
                f"{format_decimal(profile.cached_price):>{price_width}}"
            )
            _addstr(screen, row, 2, clip_display(text, width - 4), curses.A_REVERSE if index == selected else 0)
        profile = profiles[selected]
        detail_row = max(5, height - 5)
        _addstr(screen, detail_row, 2, "选中渠道详情", dim)
        _addstr(
            screen,
            detail_row + 1,
            2,
            clip_display(
                f"生效 {profile.effective_at or '--'}  版本 {profile.version or '--'}",
                width - 4,
            ),
            dim,
        )
        _addstr(
            screen,
            detail_row + 2,
            2,
            clip_display(f"来源 {profile.source or '--'}", width - 4),
            dim,
        )
    if state.error:
        _addstr(screen, height - 2, 2, clip_display(state.error, width - 4), error_color)
    elif state.message:
        _addstr(screen, height - 2, 2, clip_display(state.message, width - 4), accent)
    screen.refresh()


def _run_channels(screen: curses.window, state: CursesTuiState, colors: tuple[int, int, int, int]) -> None:
    selected = 0
    while True:
        profiles = state.settings.comparison_profiles
        selected = min(selected, max(0, len(profiles) - 1))
        _draw_channels(screen, state, selected, colors)
        key = screen.getch()
        if key in (27, ord("q"), ord("Q")):
            return
        if key in (curses.KEY_UP, ord("k")) and profiles:
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")) and profiles:
            selected = min(len(profiles) - 1, selected + 1)
        elif key in (ord("n"), ord("N")):
            profile = _edit_channel(screen, None)
            if profile is not None:
                state.settings = replace(state.settings, comparison_profiles=(*profiles, profile))
                selected = len(state.settings.comparison_profiles) - 1
                state.message, state.error = "渠道已加入，按 s 保存", ""
        elif key in (ord("e"), ord("E")) and profiles:
            profile = _edit_channel(screen, profiles[selected])
            if profile is not None:
                updated = list(profiles)
                updated[selected] = profile
                state.settings = replace(state.settings, comparison_profiles=tuple(updated))
                state.message, state.error = "渠道已修改，按 s 保存", ""
        elif key in (ord("d"), ord("D")) and profiles:
            if _confirm(screen, f"删除“{profiles[selected].name}”吗"):
                updated = list(profiles)
                del updated[selected]
                state.settings = replace(state.settings, comparison_profiles=tuple(updated))
                selected = min(selected, max(0, len(updated) - 1))
                state.message, state.error = "渠道已删除，按 s 保存", ""
        elif key in (ord("s"), ord("S"), 19):
            try:
                state.save()
            except ValueError as exc:
                state.error, state.message = str(exc), ""
        elif key in (ord("r"), ord("R"), 4):
            if state.is_dirty() and _confirm(screen, "还原未保存修改吗"):
                state.discard()


def _run_main(screen: curses.window, state: CursesTuiState) -> None:
    colors = _init_colors()
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.keypad(True)
    while True:
        _draw_main(screen, state, colors)
        key = screen.getch()
        if key in (ord("q"), ord("Q"), 27, 17):
            if state.is_dirty() and not _confirm(screen, "存在未保存修改，退出吗"):
                continue
            return
        if key in (ord("m"), ord("M"), curses.KEY_LEFT, curses.KEY_RIGHT):
            state.cycle_mode(-1 if key == curses.KEY_LEFT else 1)
        elif key in (9, curses.KEY_DOWN, 10, 13, curses.KEY_ENTER):
            state.move_field(1)
        elif key == curses.KEY_UP:
            state.move_field(-1)
        elif key in (ord("s"), ord("S"), 19):
            try:
                state.save()
            except ValueError as exc:
                state.error = str(exc)
                state.message = ""
        elif key in (ord("r"), ord("R"), 4):
            if state.is_dirty() and _confirm(screen, "还原未保存修改吗"):
                state.discard()
        elif key in (ord("c"), ord("C")):
            _run_channels(screen, state, colors)
        elif key == curses.KEY_RESIZE:
            continue
        else:
            state.edit(key)


def run_curses_tui(config_path: str | Path | None = None) -> int:
    document = load_settings_document(config_path)
    state = CursesTuiState.from_document(document)
    curses.wrapper(_run_main, state)
    return 0


__all__ = ["CursesTuiState", "display_width", "run_curses_tui"]
