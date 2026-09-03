"""Compact ncurses workbench for unit translation and relay-cost comparison.

The screen deliberately uses fixed rows instead of a widget layout engine. It
keeps the common conversion workflow visible on small terminals and leaves
configuration changes in memory until the user explicitly saves them.
"""

from __future__ import annotations

import curses
import unicodedata
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from unit_translator.infrastructure.config import Settings
from unit_translator.domain.conversion import (
    DEFAULT_USAGE,
    TokenPriceProfile,
    TokenUsage,
    _non_negative,
    _positive,
    format_decimal,
)
from unit_translator.infrastructure.catalog import validate_catalog_date
from unit_translator.infrastructure.settings import (
    SettingsDocument,
    load_settings_document,
    save_settings_document,
)
from unit_translator.adapters.tui.calculator import (
    CalculationDisplay,
    CalculatorInputs,
    calculate_display,
)
from unit_translator.adapters.tui.bc_calculator import CalculatorSession
from unit_translator.application import ConversionService


MODE_LABELS = {
    "multiplier": "固定倍率",
    "fen": "固定账号成本",
    "token_cost": "固定 1 亿实际支出",
}
MODE_HELP = {
    "multiplier": "输入中转站倍率，按当前 Token 用量计算成本",
    "fen": "输入账号每刀成本，反推倍率并计算当前 Token 用量成本",
    "token_cost": "输入用户自有 1 亿 Token 的实际支出（元）；用量配比会归一化到 1 亿",
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

CALCULATOR_PANEL_ROWS = 4
CALCULATOR_FOCUS_KEY = getattr(curses, "KEY_F6", 274)


class _PromptInputError(Exception):
    """Raised when the terminal cannot read a prompted value."""


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


def _right_display(text: str, width: int) -> str:
    """Right-align text by terminal cell width rather than Python character count."""
    return " " * max(0, width - display_width(text)) + text


def _edit_display(value: str, cursor: int, width: int) -> tuple[str, int]:
    """Return a visible slice of an ASCII numeric value and its local cursor."""
    if width <= 0:
        return "", 0
    if len(value) <= width:
        return value, max(0, min(len(value), cursor))
    position = max(0, min(len(value), cursor))
    start = max(0, min(position - width // 2, len(value) - width))
    return value[start : start + width], position - start


def _compact_tokens(value: object) -> str:
    """Format token counts compactly enough for the minimum main screen."""
    amount = Decimal(str(value))
    for divisor, suffix in (
        (Decimal("1000000000"), "B"),
        (Decimal("1000000"), "M"),
        (Decimal("1000"), "K"),
    ):
        if abs(amount) >= divisor:
            return f"{format_decimal(amount / divisor, max_places=2)}{suffix}"
    return format_decimal(amount, max_places=2)


def _compact_screen(width: int, height: int) -> bool:
    """Return whether the terminal needs the information-dense fallback layout."""
    return width < 80 or height < 24


def _draw_size_warning(screen: curses.window, error_color: int) -> bool:
    """Draw the hard minimum warning and report whether rendering should stop."""
    height, width = screen.getmaxyx()
    if height >= 20 and width >= 72:
        return False
    message = "终端窗口至少需要 72 x 20"
    _addstr(
        screen,
        height // 2,
        max(0, (width - display_width(message)) // 2),
        message,
        error_color,
    )
    screen.refresh()
    return True


def _draw_rule(screen: curses.window, row: int, label: str, attr: int = 0) -> None:
    """Draw a clipped section divider that remains safe on small terminals."""
    _, width = screen.getmaxyx()
    text = f"── {label} "
    remaining = max(0, width - 4 - display_width(text))
    _addstr(screen, row, 2, text + "─" * remaining, attr)


def _footer_text(width: int, page: str = "main") -> str:
    """Choose a grouped footer that fits while retaining the key exit hint."""
    if page == "channels":
        candidates = (
            "选择 ↑/↓ j/k",
            "操作 n 新建 e 编辑 d 删除",
            "文件 s 保存 r 还原",
            "返回 Esc/q",
        )
        fallback = (candidates[0], candidates[-1])
    elif page == "usage":
        candidates = ("编辑 Enter", "返回 Esc")
        fallback = candidates
    else:
        candidates = (
            "编辑 Tab/方向键",
            "模式 m",
            "页面 u 用量 c 渠道",
            "文件 s 保存 r 还原",
            "退出 q",
        )
        fallback = (candidates[0], candidates[1], candidates[-1])
    for indexes in (
        tuple(range(len(candidates))),
        tuple(index for index in range(len(candidates)) if index not in {len(candidates) - 2}),
        fallback,
    ):
        text = "  ".join(candidates[index] for index in indexes)
        if display_width(text) <= max(1, width - 4):
            return text
    return clip_display("  ".join(fallback), max(1, width - 4))


def _draw_footer(screen: curses.window, page: str = "main") -> None:
    """Render the page footer with grouped, width-aware keyboard hints."""
    height, _ = screen.getmaxyx()
    _addstr(screen, height - 1, 2, _footer_text(screen.getmaxyx()[1], page), curses.A_DIM)


def _calculator_panel_top(screen: curses.window) -> int:
    """Return the first row reserved for the persistent calculator panel."""
    return screen.getmaxyx()[0] - CALCULATOR_PANEL_ROWS - 1


def _draw_calculator_panel(
    screen: curses.window,
    session: CalculatorSession | None,
    colors: tuple[int, int, int, int],
) -> None:
    """Draw the fixed four-row calculator panel above the page footer."""
    if session is None:
        return
    height, width = screen.getmaxyx()
    top = _calculator_panel_top(screen)
    if top < 0 or width < 12:
        return
    accent, success, error_color, dim = colors
    inner = max(1, width - 4)
    title = "快速计算"
    state_text = "已聚焦" if session.focused else "F6 聚焦"
    top_text = f"┌─ {title} · {state_text} "
    _addstr(screen, top, 2, top_text + "─" * max(0, inner - display_width(top_text) - 1), accent)
    expression = session.expression or ""
    if session.focused:
        shown, position = _edit_display(expression, session.cursor, max(1, inner - 19))
        input_text = f"│ > {shown[:position]}|{shown[position:]}"
    else:
        input_text = f"│ > {expression or '（按 F6 输入算式）'}"
    if session.result and not session.error:
        input_text += f"  = {session.result}"
    _addstr(screen, top + 1, 2, clip_display(input_text, inner), curses.A_REVERSE if session.focused else 0)
    if session.error:
        status = f"│ ✗ {session.error}"
        status_attr = error_color
    elif session.history:
        entry = session.history[session.history_index] if session.history_index is not None else session.history[-1]
        marker = "✓" if entry.success else "✗"
        status = f"│ 历史 ↑↓ [{len(session.history)}/{session.max_history}] {marker} {entry.expression} = {entry.display_text}"
        status_attr = success if entry.success else error_color
    else:
        status = "│ 历史：暂无（Enter 计算后保留最近 20 条）"
        status_attr = dim
    _addstr(screen, top + 2, 2, clip_display(status, inner), status_attr)
    controls = "└─ Enter 计算 · ↑↓ 历史 · F6 聚焦/释放 · Esc 取消 "
    _addstr(screen, top + 3, 2, controls + "─" * max(0, inner - display_width(controls) - 1), dim)


def _handle_calculator_key(session: CalculatorSession | None, key: int | str) -> bool:
    """Consume a key when the shared calculator owns focus."""
    if session is None:
        return False
    if isinstance(key, str):
        if len(key) != 1:
            return False
        key = ord(key)
    if key == CALCULATOR_FOCUS_KEY:
        session.toggle_focus()
        return True
    if session.focused:
        session.handle_key(key)
        return True
    return False


def _read_editor_key(screen: curses.window) -> object:
    """Read a wide-character key when the curses backend supports it."""
    get_wch = getattr(screen, "get_wch", None)
    if get_wch is not None:
        try:
            return get_wch()
        except curses.error:
            pass
    return screen.getch()


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
    input_tokens: str = str(DEFAULT_USAGE.input_tokens)
    output_tokens: str = str(DEFAULT_USAGE.output_tokens)
    cached_tokens: str = str(DEFAULT_USAGE.cached_tokens)
    active_field: int = 0
    cursor: int = 0
    replace_on_type: bool = True
    message: str = ""
    error: str = ""
    calculation_error: str = ""
    _calculation_cache_key: object = field(default=None, init=False, repr=False, compare=False)
    _calculation_cache: CalculationDisplay | None = field(default=None, init=False, repr=False, compare=False)

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
            input_tokens=str(settings.usage.input_tokens),
            output_tokens=str(settings.usage.output_tokens),
            cached_tokens=str(settings.usage.cached_tokens),
        )

    def _field_value(self, name: str) -> str:
        return str(getattr(self, name))

    def _set_field_value(self, name: str, value: str) -> None:
        setattr(self, name, value)

    def field_values(self) -> tuple[str, ...]:
        return tuple(self._field_value(name) for name in FIELD_NAMES)

    def move_field(self, step: int) -> None:
        self.active_field = (self.active_field + step) % len(FIELD_NAMES)
        self.cursor = 0
        self.replace_on_type = True

    def set_mode(self, mode: str) -> None:
        if mode not in MODE_LABELS:
            return
        self.mode = mode
        self.value = MODE_DEFAULTS[mode]
        self.active_field = 0
        self.cursor = 0
        self.replace_on_type = True
        self.message = ""
        self.error = ""

    def cycle_mode(self, step: int = 1) -> None:
        modes = tuple(MODE_LABELS)
        self.set_mode(modes[(modes.index(self.mode) + step) % len(modes)])

    def edit(self, key: int) -> None:
        name = FIELD_NAMES[self.active_field]
        current = self._field_value(name)
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_HOME, curses.KEY_END):
            if self.replace_on_type:
                self.replace_on_type = False
                self.cursor = len(current)
            if key == curses.KEY_LEFT:
                self.cursor = max(0, self.cursor - 1)
            elif key == curses.KEY_RIGHT:
                self.cursor = min(len(current), self.cursor + 1)
            elif key == curses.KEY_HOME:
                self.cursor = 0
            else:
                self.cursor = len(current)
            return
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.replace_on_type:
                current = ""
                self.cursor = 0
            elif self.cursor > 0:
                current = current[: self.cursor - 1] + current[self.cursor :]
                self.cursor -= 1
            self._set_field_value(name, current)
            self.replace_on_type = False
            self.message = ""
            self.error = ""
            return
        if key == curses.KEY_DC:
            if self.replace_on_type:
                self.replace_on_type = False
                self.cursor = len(current)
            if self.cursor < len(current):
                self._set_field_value(name, current[: self.cursor] + current[self.cursor + 1 :])
            self.message = ""
            self.error = ""
            return
        if key == 21:  # Ctrl+U
            self._set_field_value(name, "")
            self.cursor = 0
            self.replace_on_type = False
            self.message = ""
            self.error = ""
            return
        if key < 0 or key > 255:
            return
        character = chr(key)
        if character not in "0123456789.-":
            return
        if self.replace_on_type:
            current = ""
            self.cursor = 0
        if character == "." and "." in current:
            return
        if character == "-" and current:
            return
        if character == "." and not current:
            current = "0"
            self.cursor = 1
        if len(current) < 24:
            current = current[: self.cursor] + character + current[self.cursor :]
            self._set_field_value(name, current)
            self.cursor += 1
            self.replace_on_type = False
            self.message = ""
            self.error = ""

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
        inputs = self.calculator_inputs()
        cache_key = (
            inputs,
            self.settings.usage,
            self.settings.chatgpt_profile,
            self.settings.comparison_profiles,
            self.settings.version,
        )
        if cache_key == self._calculation_cache_key and self._calculation_cache is not None:
            return self._calculation_cache
        display = calculate_display(inputs, self.settings, ConversionService())
        self._calculation_cache_key = cache_key
        self._calculation_cache = display
        return display

    def usage_from_fields(self) -> TokenUsage:
        return TokenUsage(
            self.input_tokens,
            self.output_tokens,
            self.cached_tokens,
        )

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
            usage=self.usage_from_fields(),
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
        self.input_tokens = str(self.settings.usage.input_tokens)
        self.output_tokens = str(self.settings.usage.output_tokens)
        self.cached_tokens = str(self.settings.usage.cached_tokens)
        self.value = MODE_DEFAULTS[self.mode]
        self.cursor = 0
        self.replace_on_type = True
        self.message = "已还原未保存修改"
        self.error = ""

def _addstr(screen: curses.window, row: int, col: int, text: str, attr: int = 0) -> None:
    height, width = screen.getmaxyx()
    if row < 0 or row >= height or col < 0 or col >= width:
        return
    try:
        available = max(0, width - col - 1)
        screen.addnstr(row, col, clip_display(text, available), available, attr)
    except curses.error:
        pass


def _init_colors() -> tuple[int, int, int, int]:
    try:
        if not curses.has_colors():
            raise curses.error("terminal has no color support")
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_RED, -1)
        return curses.color_pair(1), curses.color_pair(2), curses.color_pair(3), curses.A_DIM
    except curses.error:
        return curses.A_BOLD, curses.A_BOLD, curses.A_BOLD, curses.A_DIM


def _field(
    screen: curses.window,
    row: int,
    col: int,
    label: str,
    value: str,
    unit: str,
    active: bool,
    cursor: int | None = None,
    slot_width: int | None = None,
) -> None:
    _addstr(screen, row, col, label)
    value_col = col + max(9, display_width(label) + 1)
    _, screen_width = screen.getmaxyx()
    if slot_width is None:
        slot_width = max(3, screen_width - col - 2)
    unit_col = col + max(3, slot_width - display_width(unit))
    value_capacity = max(1, unit_col - value_col - 2)
    if active and cursor is not None:
        shown, position = _edit_display(value, cursor, max(1, value_capacity - 1))
        value_text = f" {shown[:position]}|{shown[position:]} "
    else:
        shown, _ = _edit_display(value, len(value), max(1, value_capacity))
        value_text = f" {shown or ' '} "
    attr = curses.A_REVERSE | curses.A_BOLD if active else curses.A_BOLD
    _addstr(screen, row, value_col, value_text, attr)
    _addstr(screen, row, unit_col, unit)


def _draw_main(
    screen: curses.window,
    state: CursesTuiState,
    colors: tuple[int, int, int, int],
    calculator: CalculatorSession | None = None,
) -> None:
    screen.erase()
    height, width = screen.getmaxyx()
    accent, success, error_color, dim = colors
    if _draw_size_warning(screen, error_color):
        return
    compact = _compact_screen(width, height)

    _addstr(screen, 0, 2, "Unit Translator", curses.A_BOLD | accent)
    status = "未保存" if state.is_dirty() else "已保存"
    _addstr(screen, 0, max(2, width - display_width(status) - 2), status, dim)
    _addstr(screen, 1, 2, clip_display(str(state.document.path), width - 4), dim)

    content_width = max(1, width - 4)
    column_width = max(24, (content_width - 3) // 2)
    left_col = 2
    right_col = left_col + column_width + 3
    mode_col = 2
    for mode, label in MODE_LABELS.items():
        mode_text = f"[{label}]" if mode == state.mode else f" {label} "
        mode_attr = curses.A_REVERSE | accent if mode == state.mode else 0
        _addstr(screen, 3, mode_col, mode_text, mode_attr)
        mode_col += display_width(mode_text) + (1 if compact else 2)
    _addstr(screen, 4, 2, clip_display(MODE_HELP[state.mode], width - 4), dim)
    _draw_rule(screen, 2, "模式", dim)
    _draw_rule(screen, 5, "参数", dim)
    value_label = "1 亿实际花费" if state.mode == "token_cost" else "换算值"
    value_unit = {
        "multiplier": "倍",
        "fen": "分/刀",
        "token_cost": "元/1亿 Token",
    }[state.mode]
    _field(
        screen, 6, left_col, value_label, state.value,
        value_unit,
        state.active_field == 0,
        state.cursor if state.active_field == 0 else None,
        column_width,
    )
    _field(
        screen, 6, right_col, "充值比例", state.balance_per_yuan, "刀/元",
        state.active_field == 1,
        state.cursor if state.active_field == 1 else None,
        column_width,
    )
    _field(
        screen, 8, left_col, "美元汇率", state.usd_cny_rate, "元/USD",
        state.active_field == 2,
        state.cursor if state.active_field == 2 else None,
        column_width,
    )
    _field(
        screen, 8, right_col, "输入价", state.input_price, "刀/1M",
        state.active_field == 3,
        state.cursor if state.active_field == 3 else None,
        column_width,
    )
    _field(
        screen, 10, left_col, "输出价", state.output_price, "刀/1M",
        state.active_field == 4,
        state.cursor if state.active_field == 4 else None,
        column_width,
    )
    _field(
        screen, 10, right_col, "缓存价", state.cached_price, "刀/1M",
        state.active_field == 5,
        state.cursor if state.active_field == 5 else None,
        column_width,
    )

    try:
        display = state.calculate()
    except ValueError as exc:
        display = None
        state.calculation_error = str(exc)
    else:
        state.calculation_error = ""
    _draw_rule(screen, 12, "结果", accent)
    if display is not None:
        usage = state.settings.usage
        usage_text = (
            f"用量配比 I/O/C {_compact_tokens(usage.input_tokens)}/"
            f"{_compact_tokens(usage.output_tokens)}/"
            f"{_compact_tokens(usage.cached_tokens)}"
        )
        cost_label = "1 亿实际支出" if state.mode == "token_cost" else "当前用量成本"
        if calculator is not None and compact:
            _addstr(
                screen,
                13,
                2,
                clip_display(
                    f"倍率 {display.multiplier} · 账号成本 {display.fen_per_dollar}",
                    width - 4,
                ),
                curses.A_BOLD | success,
            )
            _addstr(
                screen,
                14,
                2,
                clip_display(
                    f"{cost_label} {display.token_cost_yuan} · {usage_text}",
                    width - 4,
                ),
                dim,
            )
            comparison_title_row = None
        elif compact:
            _addstr(
                screen,
                13,
                2,
                f"倍率 {display.multiplier}  · 账号成本 {display.fen_per_dollar}",
                curses.A_BOLD | success,
            )
            _addstr(screen, 14, 2, usage_text, dim)
        else:
            _addstr(
                screen,
                13,
                2,
                f"倍率 {display.multiplier}  · 账号成本 {display.fen_per_dollar}",
                curses.A_BOLD | success,
            )
            _addstr(screen, 14, 2, usage_text, dim)
        cost_row = 15
        _addstr(
            screen,
            cost_row,
            2,
            f"{cost_label} {display.token_cost_yuan}  · 官方成本 {display.official_cost_usd}",
            curses.A_BOLD,
        )
        if calculator is not None and compact:
            comparison_title_row = None
            comparison_header_row = None
            comparison_limit = 0
        else:
            comparison_title_row = 17 if compact else 16
            comparison_header_row = comparison_title_row + 1
            comparison_limit = 0 if compact else max(0, height - comparison_header_row - 2)
            if calculator is not None:
                panel_top = _calculator_panel_top(screen)
                comparison_limit = max(
                    0,
                    min(comparison_limit, panel_top - comparison_header_row - 1),
                )
        comparison_total = len(display.comparison)
        if calculator is not None and compact:
            comparison_title = ""
        elif compact:
            comparison_title = f"渠道对比（{comparison_total} 个，按 c 查看全部）"
        else:
            comparison_title = "渠道对比"
            if comparison_total > comparison_limit:
                comparison_title += f"（显示 {comparison_limit}/{comparison_total}，按 c 查看全部）"
        if comparison_title_row is not None:
            _addstr(screen, comparison_title_row, 2, clip_display(comparison_title, width - 4), curses.A_BOLD | accent)
        if comparison_header_row is None:
            pass
        elif compact:
            _addstr(screen, comparison_header_row, 2, "渠道列表已折叠", dim)
        else:
            name_width = max(18, min(44, width - 34))
            _addstr(
                screen,
                comparison_header_row,
                2,
                f"{pad_display('渠道', name_width)}  {_right_display('CNY', 14)}  {_right_display('相对成本', 12)}",
                dim,
            )
        # Keep the footer row free so the last comparison entry is not
        # overwritten on the documented 80 x 24 terminal.
        for row_index, row in enumerate(
            display.comparison[:comparison_limit],
            start=(comparison_header_row + 1) if comparison_header_row is not None else 0,
        ):
            name = pad_display(clip_display(row.name, name_width), name_width)
            _addstr(
                screen,
                row_index,
                2,
                f"{name}  {_right_display(row.yuan, 14)}  {_right_display(row.relative_cost, 12)}",
            )
    visible_error = state.error or state.calculation_error
    if visible_error:
        _addstr(screen, 11, 2, clip_display(visible_error, width - 4), error_color)
    elif state.message:
        _addstr(screen, 11, 2, clip_display(state.message, width - 4), success)
    _draw_calculator_panel(screen, calculator, colors)
    _draw_footer(screen)
    screen.refresh()


def _confirm(screen: curses.window, prompt: str) -> bool:
    height, width = screen.getmaxyx()
    _addstr(screen, height - 2, 2, clip_display(f"{prompt} [y/N]", width - 4), curses.A_REVERSE)
    screen.refresh()
    key = screen.getch()
    return key in (ord("y"), ord("Y"))


def _prompt(screen: curses.window, row: int, label: str, default: str = "") -> str | None:
    """Read one bounded line while keeping curses rendering predictable."""
    height, width = screen.getmaxyx()
    if row >= height or width < 8:
        raise _PromptInputError("终端窗口太小，请放大后重试")
    prefix = f"{label} [{default}]: " if default else f"{label}: "
    col = 2
    _addstr(screen, row, col, prefix)
    screen.refresh()
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    curses.echo()
    try:
        available = max(1, width - col - display_width(prefix) - 2)
        raw = screen.getstr(row, min(width - 2, col + display_width(prefix)), available)
    except curses.error as exc:
        raise _PromptInputError("终端输入失败，请重试") from exc
    finally:
        curses.noecho()
        try:
            curses.curs_set(0)
        except curses.error:
            pass
    if b"\x1b" in raw:
        return None
    value = raw.decode("utf-8", errors="replace").strip()
    return value or default


def _prompt_channel_values(
    screen: curses.window,
    profile: TokenPriceProfile | None,
    values: dict[str, str] | None = None,
) -> dict[str, str] | None:
    fields = (
        ("name", 3, "名称", profile.name if profile else ""),
        ("provider", 4, "提供商", profile.provider if profile else "custom"),
        ("model", 5, "模型", profile.model if profile else ""),
        ("input_price", 7, "输入价", str(profile.input_price) if profile else ""),
        ("output_price", 8, "输出价", str(profile.output_price) if profile else ""),
        ("cached_price", 9, "缓存价", str(profile.cached_price) if profile else ""),
        ("effective_at", 11, "生效日期", profile.effective_at or "" if profile else ""),
        ("source", 12, "来源", profile.source or "" if profile else ""),
        ("version", 13, "版本", profile.version or "" if profile else ""),
    )
    previous = values or {}
    collected: dict[str, str] = {}
    for name, row, label, default in fields:
        value = _prompt(screen, row, label, previous.get(name, default))
        if value is None:
            return None
        collected[name] = value
    return collected


def _channel_from_values(
    values: dict[str, str],
    profile: TokenPriceProfile | None,
) -> TokenPriceProfile:
    if not values["name"]:
        raise ValueError("渠道名称不能为空")
    if not values["provider"]:
        raise ValueError("提供商不能为空")
    effective_at = values["effective_at"] or None
    if effective_at:
        effective_at = validate_catalog_date(effective_at, "生效日期")
    return TokenPriceProfile(
        values["name"],
        values["input_price"],
        values["output_price"],
        values["cached_price"],
        provider=values["provider"],
        model=values["model"],
        currency=profile.currency if profile else "USD",
        unit=profile.unit if profile else "1M tokens",
        effective_at=effective_at,
        source=values["source"] or None,
        version=values["version"] or None,
    )


def _channel_field_for_error(message: str) -> tuple[int, str, str] | None:
    fields = {
        "渠道名称": (3, "名称", "name"),
        "提供商": (4, "提供商", "provider"),
        "输入 Token": (7, "输入价", "input_price"),
        "输出 Token": (8, "输出价", "output_price"),
        "缓存 Token": (9, "缓存价", "cached_price"),
        "生效日期": (11, "生效日期", "effective_at"),
    }
    for marker, field_spec in fields.items():
        if marker in message:
            return field_spec
    return None


@dataclass
class _DraftEditor:
    """Small non-blocking line editor shared by usage and channel forms."""

    fields: tuple[tuple[str, str, bool], ...]
    values: dict[str, str]
    active: int = 0
    cursor: int = 0
    replace_on_type: bool = True

    def move(self, step: int) -> None:
        self.active = (self.active + step) % len(self.fields)
        self.cursor = 0
        self.replace_on_type = True

    def edit(self, key: object) -> None:
        name, _, numeric = self.fields[self.active]
        current = self.values[name]
        if isinstance(key, str):
            if len(key) != 1 or not key.isprintable() or (numeric and key not in "0123456789.-"):
                return
            character = key
            if self.replace_on_type:
                current, self.cursor = "", 0
            if numeric and character == "." and "." in current:
                return
            if numeric and character == "-" and current:
                return
            if len(current) >= 256:
                return
            self.values[name] = current[: self.cursor] + character + current[self.cursor :]
            self.cursor += 1
            self.replace_on_type = False
            return
        if key in (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_HOME, curses.KEY_END):
            if self.replace_on_type:
                self.replace_on_type = False
                self.cursor = len(current)
            if key == curses.KEY_LEFT:
                self.cursor = max(0, self.cursor - 1)
            elif key == curses.KEY_RIGHT:
                self.cursor = min(len(current), self.cursor + 1)
            elif key == curses.KEY_HOME:
                self.cursor = 0
            else:
                self.cursor = len(current)
            return
        if key in (curses.KEY_BACKSPACE, 8, 127):
            if self.replace_on_type:
                current, self.cursor = "", 0
            elif self.cursor:
                current = current[: self.cursor - 1] + current[self.cursor :]
                self.cursor -= 1
            self.values[name] = current
            self.replace_on_type = False
            return
        if key == curses.KEY_DC:
            if self.replace_on_type:
                self.replace_on_type = False
                self.cursor = len(current)
            if self.cursor < len(current):
                self.values[name] = current[: self.cursor] + current[self.cursor + 1 :]
            return
        if key == 21:
            self.values[name] = ""
            self.cursor = 0
            self.replace_on_type = False
            return
        if not (32 <= key <= 126):
            return
        character = chr(key)
        if numeric and character not in "0123456789.-":
            return
        if self.replace_on_type:
            current, self.cursor = "", 0
        if numeric and character == "." and "." in current:
            return
        if numeric and character == "-" and current:
            return
        if len(current) >= 256:
            return
        current = current[: self.cursor] + character + current[self.cursor :]
        self.values[name] = current
        self.cursor += 1
        self.replace_on_type = False


def _draw_draft_field(
    screen: curses.window,
    row: int,
    label: str,
    value: str,
    active: bool,
    cursor: int,
) -> None:
    _addstr(screen, row, 2, f"{label}: ")
    _, width = screen.getmaxyx()
    available = max(1, width - display_width(label) - 8)
    shown, position = _edit_display(value, cursor if active else len(value), available)
    if active:
        text = f"[{shown[:position]}|{shown[position:]}]"
        attr = curses.A_REVERSE | curses.A_BOLD
    else:
        text = f"[{shown or ' '}]"
        attr = curses.A_BOLD
    _addstr(screen, row, display_width(label) + 5, text, attr)


def _edit_channel_interactive(
    screen: curses.window,
    state: CursesTuiState,
    profile: TokenPriceProfile | None,
    calculator: CalculatorSession,
) -> TokenPriceProfile | None:
    fields = (
        ("name", "名称", False),
        ("provider", "提供商", False),
        ("model", "模型", False),
        ("input_price", "输入价", True),
        ("output_price", "输出价", True),
        ("cached_price", "缓存价", True),
        ("effective_at", "生效日期", False),
        ("source", "来源", False),
        ("version", "版本", False),
    )
    values = {
        "name": profile.name if profile else "",
        "provider": profile.provider if profile else "custom",
        "model": profile.model if profile else "",
        "input_price": str(profile.input_price) if profile else "",
        "output_price": str(profile.output_price) if profile else "",
        "cached_price": str(profile.cached_price) if profile else "",
        "effective_at": profile.effective_at or "" if profile else "",
        "source": profile.source or "" if profile else "",
        "version": profile.version or "" if profile else "",
    }
    editor = _DraftEditor(fields, values)
    error = ""
    panel_colors = _init_colors()
    while True:
        screen.erase()
        _, width = screen.getmaxyx()
        accent, _, error_color, dim = panel_colors
        _addstr(screen, 0, 2, "编辑渠道" if profile else "新建渠道", curses.A_BOLD | accent)
        _addstr(screen, 1, 2, "Enter 下一项/最后一项提交 · Esc 取消 · F6 计算器", dim)
        _draw_rule(screen, 2, "渠道字段", dim)
        for row, (name, label, _) in enumerate(fields, start=3):
            _draw_draft_field(screen, row, label, editor.values[name], editor.active == row - 3, editor.cursor)
        if error:
            _addstr(screen, max(3, _calculator_panel_top(screen) - 1), 2, clip_display(error, width - 4), error_color)
        _draw_calculator_panel(screen, calculator, (accent, curses.A_BOLD, error_color, dim))
        _draw_footer(screen, "channels")
        screen.refresh()
        key = _read_editor_key(screen)
        if _handle_calculator_key(calculator, key):
            continue
        if key == 27:
            return None
        if key in (9, curses.KEY_DOWN):
            editor.move(1)
        elif key in (curses.KEY_UP, getattr(curses, "KEY_BTAB", -999)):
            editor.move(-1)
        elif key in (10, 13, curses.KEY_ENTER):
            if editor.active < len(fields) - 1:
                editor.move(1)
                continue
            try:
                return _channel_from_values(editor.values, profile)
            except ValueError as exc:
                error = str(exc)
                field_spec = _channel_field_for_error(error)
                if field_spec:
                    editor.active = next(
                        (index for index, item in enumerate(fields) if item[0] == field_spec[2]),
                        editor.active,
                    )
        else:
            editor.edit(key)


def _run_usage_interactive(
    screen: curses.window,
    state: CursesTuiState,
    colors: tuple[int, int, int, int],
    calculator: CalculatorSession,
) -> None:
    accent, _, error_color, dim = colors
    fields = (
        ("input_tokens", "输入 Token", True),
        ("output_tokens", "输出 Token", True),
        ("cached_tokens", "缓存 Token", True),
    )
    values = {
        "input_tokens": state.input_tokens,
        "output_tokens": state.output_tokens,
        "cached_tokens": state.cached_tokens,
    }
    editor = _DraftEditor(fields, values)
    error = ""
    while True:
        screen.erase()
        _addstr(screen, 0, 2, "Token 用量配比（高级）", curses.A_BOLD | accent)
        _addstr(screen, 1, 2, "单位：Token 数量；F6 切换计算器，Esc 放弃草稿", dim)
        _draw_rule(screen, 3, "Token 配比", dim)
        for row, (name, label, _) in enumerate(fields, start=4):
            _draw_draft_field(screen, row, label, editor.values[name], editor.active == row - 4, editor.cursor)
        if error:
            _addstr(screen, 8, 2, clip_display(error, screen.getmaxyx()[1] - 4), error_color)
        _draw_calculator_panel(screen, calculator, colors)
        _draw_footer(screen, "usage")
        screen.refresh()
        key = _read_editor_key(screen)
        if _handle_calculator_key(calculator, key):
            continue
        if key == 27:
            return
        if key in (9, curses.KEY_DOWN):
            editor.move(1)
        elif key in (curses.KEY_UP, getattr(curses, "KEY_BTAB", -999)):
            editor.move(-1)
        elif key in (10, 13, curses.KEY_ENTER):
            if editor.active < len(fields) - 1:
                editor.move(1)
                continue
            try:
                usage = TokenUsage(
                    editor.values["input_tokens"],
                    editor.values["output_tokens"],
                    editor.values["cached_tokens"],
                )
            except ValueError as exc:
                error = str(exc)
                continue
            state.settings = replace(state.settings, usage=usage)
            state.input_tokens = str(usage.input_tokens)
            state.output_tokens = str(usage.output_tokens)
            state.cached_tokens = str(usage.cached_tokens)
            state.message, state.error = "用量已修改，按 s 保存", ""
            return
        else:
            editor.edit(key)


def _edit_channel(screen: curses.window, profile: TokenPriceProfile | None) -> TokenPriceProfile | None:
    """Edit one channel using fixed rows and blocking line input."""
    screen.erase()
    _addstr(screen, 1, 2, "新建渠道" if profile is None else "编辑渠道", curses.A_BOLD)
    values: dict[str, str] | None = None
    while True:
        if values is None:
            try:
                values = _prompt_channel_values(screen, profile)
            except _PromptInputError as exc:
                _addstr(screen, 15, 2, str(exc), curses.A_BOLD)
                _addstr(screen, 17, 2, "按任意键返回", curses.A_DIM)
                screen.refresh()
                screen.getch()
                return None
            if values is None:
                return None
        try:
            return _channel_from_values(values, profile)
        except ValueError as exc:
            message = str(exc)
            _addstr(screen, 15, 2, message, curses.A_BOLD)
            field_spec = _channel_field_for_error(message)
            if field_spec is None:
                _addstr(screen, 17, 2, "按任意键返回", curses.A_DIM)
                screen.refresh()
                screen.getch()
                return None
            row, label, field_name = field_spec
            try:
                value = _prompt(screen, row, label, values[field_name])
            except _PromptInputError as exc:
                _addstr(screen, 15, 2, str(exc), curses.A_BOLD)
                _addstr(screen, 17, 2, "按任意键返回", curses.A_DIM)
                screen.refresh()
                screen.getch()
                return None
            if value is None:
                return None
            values[field_name] = value


def _draw_channels(
    screen: curses.window,
    state: CursesTuiState,
    selected: int,
    colors: tuple[int, int, int, int],
    calculator: CalculatorSession | None = None,
) -> None:
    screen.erase()
    height, width = screen.getmaxyx()
    accent, _, error_color, dim = colors
    if _draw_size_warning(screen, error_color):
        return
    _addstr(screen, 0, 2, "渠道管理", curses.A_BOLD | accent)
    _addstr(screen, 1, 2, clip_display("↑/↓ 或 j/k 选择  n 新建  e 编辑  d 删除  Esc 返回", width - 4), dim)
    _draw_rule(screen, 2, "价格目录 · USD / 1M tokens", dim)
    profiles = state.settings.comparison_profiles
    if not profiles:
        _addstr(screen, 4, 2, "暂无渠道", dim)
    else:
        # Keep every core pricing field in the list; only optional metadata is
        # relegated to the selected-channel detail rows below.
        compact = _compact_screen(width, height)
        price_width = 8 if compact else 10
        name_width = max(12, min(18 if compact else 20, (width - (35 if compact else 43)) // 2))
        provider_width = max(12, width - name_width - (35 if compact else 43))
        header = (
            f"{pad_display('渠道', name_width)}  "
            f"{pad_display('提供商/模型', provider_width)}  "
            f"{pad_display('输入价', price_width)}  "
            f"{pad_display('输出价', price_width)}  "
            f"{pad_display('缓存价', price_width)}"
        )
        _addstr(screen, 3, 2, clip_display(header, width - 4), dim)
        detail_row = max(5, (_calculator_panel_top(screen) - 4) if calculator is not None else height - 5)
        visible = max(1, detail_row - 4)
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
        _addstr(screen, detail_row, 2, "选中渠道详情", dim)
        _addstr(
            screen,
            detail_row + 1,
            2,
            clip_display(
                f"计价 {profile.currency}/{profile.unit}  生效 {profile.effective_at or '--'}  版本 {profile.version or '--'}",
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
    message_row = (_calculator_panel_top(screen) - 1) if calculator is not None else height - 2
    if state.error:
        _addstr(screen, message_row, 2, clip_display(state.error, width - 4), error_color)
    elif state.message:
        _addstr(screen, message_row, 2, clip_display(state.message, width - 4), accent)
    _draw_calculator_panel(screen, calculator, colors)
    _draw_footer(screen, "channels")
    screen.refresh()


def _add_channel(
    screen: curses.window,
    state: CursesTuiState,
    profiles: tuple[TokenPriceProfile, ...],
    selected: int,
    calculator: CalculatorSession | None = None,
) -> int:
    profile = _edit_channel_interactive(screen, state, None, calculator) if calculator is not None else _edit_channel(screen, None)
    if profile is None:
        return selected
    state.settings = replace(state.settings, comparison_profiles=(*profiles, profile))
    state.message, state.error = "渠道已加入，按 s 保存", ""
    return len(state.settings.comparison_profiles) - 1


def _update_channel(
    screen: curses.window,
    state: CursesTuiState,
    profiles: tuple[TokenPriceProfile, ...],
    selected: int,
    calculator: CalculatorSession | None = None,
) -> int:
    profile = (
        _edit_channel_interactive(screen, state, profiles[selected], calculator)
        if calculator is not None
        else _edit_channel(screen, profiles[selected])
    )
    if profile is None:
        return selected
    updated = list(profiles)
    updated[selected] = profile
    state.settings = replace(state.settings, comparison_profiles=tuple(updated))
    state.message, state.error = "渠道已修改，按 s 保存", ""
    return selected


def _delete_channel(
    screen: curses.window,
    state: CursesTuiState,
    profiles: tuple[TokenPriceProfile, ...],
    selected: int,
) -> int:
    if not _confirm(screen, f"删除“{profiles[selected].name}”吗"):
        return selected
    updated = list(profiles)
    del updated[selected]
    state.settings = replace(state.settings, comparison_profiles=tuple(updated))
    state.message, state.error = "渠道已删除，按 s 保存", ""
    return min(selected, max(0, len(updated) - 1))


def _save_channels(state: CursesTuiState) -> None:
    try:
        state.save()
    except ValueError as exc:
        state.error, state.message = str(exc), ""


def _restore_channels(screen: curses.window, state: CursesTuiState) -> None:
    if state.is_dirty() and _confirm(screen, "还原未保存修改吗"):
        state.discard()


def _run_usage(
    screen: curses.window,
    state: CursesTuiState,
    colors: tuple[int, int, int, int],
    calculator: CalculatorSession | None = None,
) -> None:
    """Edit the token mix used by every calculation without adding it to the main grid."""
    accent, _, error_color, dim = colors
    if calculator is not None:
        _run_usage_interactive(screen, state, colors, calculator)
        return
    screen.erase()
    if _draw_size_warning(screen, error_color):
        return
    _addstr(screen, 0, 2, "Token 用量配比（高级）", curses.A_BOLD | accent)
    _addstr(
        screen,
        1,
        2,
        "单位：Token 数量；用于输入/输出/缓存配比",
        dim,
    )
    _addstr(
        screen,
        2,
        2,
        "固定 1 亿实际支出模式归一化到 1 亿；Enter 保留当前值，Esc 返回",
        dim,
    )
    _draw_rule(screen, 3, "Token 配比", dim)
    _draw_footer(screen, "usage")
    values = {
        "input_tokens": state.input_tokens,
        "output_tokens": state.output_tokens,
        "cached_tokens": state.cached_tokens,
    }
    fields = (
        ("input_tokens", 4, "输入 Token"),
        ("output_tokens", 5, "输出 Token"),
        ("cached_tokens", 6, "缓存 Token"),
    )
    while True:
        try:
            for name, row, label in fields:
                value = _prompt(screen, row, label, values[name])
                if value is None:
                    return
                values[name] = value
            usage = TokenUsage(
                values["input_tokens"],
                values["output_tokens"],
                values["cached_tokens"],
            )
        except _PromptInputError as exc:
            _addstr(screen, 8, 2, str(exc), error_color)
            _draw_footer(screen, "usage")
            screen.refresh()
            screen.getch()
            return
        except ValueError as exc:
            _addstr(screen, 8, 2, str(exc), error_color)
            _addstr(screen, 10, 2, "请重新输入，Esc 返回", dim)
            _draw_footer(screen, "usage")
            screen.refresh()
            continue
        state.settings = replace(state.settings, usage=usage)
        state.input_tokens = str(usage.input_tokens)
        state.output_tokens = str(usage.output_tokens)
        state.cached_tokens = str(usage.cached_tokens)
        state.message, state.error = "用量已修改，按 s 保存", ""
        return


def _run_channels(
    screen: curses.window,
    state: CursesTuiState,
    colors: tuple[int, int, int, int],
    calculator: CalculatorSession | None = None,
) -> None:
    selected = 0
    while True:
        profiles = state.settings.comparison_profiles
        selected = min(selected, max(0, len(profiles) - 1))
        _draw_channels(screen, state, selected, colors, calculator)
        key = screen.getch()
        if _handle_calculator_key(calculator, key):
            continue
        if key in (27, ord("q"), ord("Q")):
            if state.is_dirty() and not _confirm(screen, "存在未保存修改，返回吗"):
                continue
            return
        if key in (curses.KEY_UP, ord("k")) and profiles:
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")) and profiles:
            selected = min(len(profiles) - 1, selected + 1)
        elif key in (ord("n"), ord("N")):
            selected = _add_channel(screen, state, profiles, selected, calculator)
        elif key in (ord("e"), ord("E")) and profiles:
            selected = _update_channel(screen, state, profiles, selected, calculator)
        elif key in (ord("d"), ord("D")) and profiles:
            selected = _delete_channel(screen, state, profiles, selected)
        elif key in (ord("s"), ord("S"), 19):
            _save_channels(state)
        elif key in (ord("r"), ord("R"), 4):
            _restore_channels(screen, state)


def _handle_main_key(
    screen: curses.window,
    state: CursesTuiState,
    colors: tuple[int, int, int, int],
    key: int,
    calculator: CalculatorSession | None = None,
) -> bool:
    """Apply one main-screen key and report whether the TUI should exit."""
    if _handle_calculator_key(calculator, key):
        return False
    if key in (ord("q"), ord("Q"), 27, 17):
        return not state.is_dirty() or _confirm(screen, "存在未保存修改，退出吗")
    if key in (ord("m"), ord("M")):
        state.cycle_mode()
    elif key in (9, curses.KEY_DOWN, 10, 13, curses.KEY_ENTER):
        state.move_field(1)
    elif key in (curses.KEY_UP, getattr(curses, "KEY_BTAB", -999)):
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
        _run_channels(screen, state, colors, calculator)
    elif key in (ord("u"), ord("U")):
        _run_usage(screen, state, colors, calculator)
    elif key == curses.KEY_RESIZE:
        return False
    else:
        state.edit(key)
    return False


def _run_main(
    screen: curses.window,
    state: CursesTuiState,
    calculator: CalculatorSession | None = None,
) -> None:
    colors = _init_colors()
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.keypad(True)
    while True:
        _draw_main(screen, state, colors, calculator)
        if _handle_main_key(screen, state, colors, screen.getch(), calculator):
            return


def run_curses_tui(config_path: str | Path | None = None) -> int:
    document = load_settings_document(config_path)
    state = CursesTuiState.from_document(document)
    calculator = CalculatorSession()
    calculator.start()
    try:
        curses.wrapper(_run_main, state, calculator)
    finally:
        calculator.close()
    return 0


__all__ = ["CursesTuiState", "display_width", "run_curses_tui"]
