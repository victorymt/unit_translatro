"""Textual workbench for interactive relay-price conversion and channels.

The TUI owns interactive configuration editing while the calculation and file
formats stay in their existing domain/adaptor modules.  A missing TUI config is
intentional: :mod:`settings_store` supplies a seeded document and this module
only writes it after the user explicitly saves.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Callable

from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Collapsible,
    DataTable,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from app_config import Settings
from converter_core import (
    TokenPriceProfile,
    _positive,
    format_decimal,
)
from settings_store import (
    SettingsDocument,
    load_settings_document,
    save_settings_document,
)
from unit_translator.application import ConversionService
from unit_translator.adapters.tui.calculator import (
    CalculationDisplay,
    CalculatorInputs,
    calculate_display,
)
from unit_translator.adapters.tui.views import (
    compose_calculator,
    compose_channels,
    compose_comparison,
    compose_footer,
    compose_toolbar,
)


class ConfirmScreen(ModalScreen[bool]):
    """Small reusable confirmation dialog for destructive in-memory actions."""

    BINDINGS = [Binding("escape", "cancel", "取消", show=False)]

    def __init__(self, title: str, message: str, accept_label: str) -> None:
        super().__init__()
        self.dialog_title = title
        self.message = message
        self.accept_label = accept_label

    def compose(self) -> ComposeResult:
        with Container(classes="confirm-dialog"):
            yield Label(self.dialog_title, classes="dialog-title")
            yield Static(self.message, classes="dialog-message")
            with Horizontal(classes="dialog-actions"):
                yield Button("取消", id="confirm-cancel")
                yield Button(self.accept_label, id="confirm-accept", variant="warning")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-accept")

    def action_cancel(self) -> None:
        self.dismiss(False)


class ChannelEditorScreen(ModalScreen[TokenPriceProfile | None]):
    """Create or edit one comparison channel without mutating the app yet."""

    BINDINGS = [Binding("escape", "cancel", "取消", show=False)]

    def __init__(self, profile: TokenPriceProfile | None = None) -> None:
        super().__init__()
        self.profile = profile

    def compose(self) -> ComposeResult:
        profile = self.profile
        title = "编辑比较渠道" if profile is not None else "新建比较渠道"
        with Container(id="channel-editor-dialog"):
            yield Label(title, classes="dialog-title")
            yield Static("价格单位：USD / 1M tokens", classes="channel-unit")
            with VerticalScroll(id="channel-editor-fields"):
                yield Static("基础信息", classes="editor-section-heading")
                yield Label("名称")
                yield Input(profile.name if profile else "", id="channel-name")
                yield Label("提供商")
                yield Input(profile.provider if profile else "custom", id="channel-provider")
                yield Label("模型")
                yield Input(profile.model if profile else "", id="channel-model")
                yield Static("计价", classes="editor-section-heading")
                yield Label("输入价")
                yield Input(
                    str(profile.input_price) if profile else "",
                    id="channel-input-price",
                    type="number",
                )
                yield Label("输出价")
                yield Input(
                    str(profile.output_price) if profile else "",
                    id="channel-output-price",
                    type="number",
                )
                yield Label("缓存价")
                yield Input(
                    str(profile.cached_price) if profile else "",
                    id="channel-cached-price",
                    type="number",
                )
                with Collapsible(
                    title="来源与版本（可选）",
                    collapsed=True,
                    id="channel-source-settings",
                ):
                    yield Label("生效日期")
                    yield Input(
                        profile.effective_at or "" if profile else "",
                        id="channel-effective-at",
                    )
                    yield Label("来源")
                    yield Input(profile.source or "" if profile else "", id="channel-source")
                    yield Label("版本")
                    yield Input(profile.version or "" if profile else "", id="channel-version")
            yield Static("", id="channel-editor-error")
            with Horizontal(classes="dialog-actions"):
                yield Button("取消", id="channel-cancel")
                yield Button("保存渠道", id="channel-save", variant="success")

    def _value(self, input_id: str) -> str:
        return self.query_one(f"#{input_id}", Input).value.strip()

    def _build_profile(self) -> TokenPriceProfile:
        name = self._value("channel-name")
        provider = self._value("channel-provider")
        effective_at = self._value("channel-effective-at") or None
        if not name:
            raise ValueError("渠道名称不能为空")
        if not provider:
            raise ValueError("提供商不能为空")
        if effective_at is not None:
            try:
                date.fromisoformat(effective_at)
            except ValueError as exc:
                raise ValueError("生效日期必须是 YYYY-MM-DD") from exc
        return TokenPriceProfile(
            name=name,
            provider=provider,
            model=self._value("channel-model"),
            input_price=self._value("channel-input-price"),
            output_price=self._value("channel-output-price"),
            cached_price=self._value("channel-cached-price"),
            effective_at=effective_at,
            source=self._value("channel-source") or None,
            version=self._value("channel-version") or None,
        )

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "channel-cancel":
            self.dismiss(None)
            return
        if event.button.id != "channel-save":
            return
        try:
            self.dismiss(self._build_profile())
        except ValueError as exc:
            self.query_one("#channel-editor-error", Static).update(str(exc))

    def action_cancel(self) -> None:
        self.dismiss(None)


class UnitTranslatorApp(App[None]):
    """Focused TUI for quick conversion and secondary channel management."""

    TITLE = "Unit Translator"
    SUB_TITLE = "成本换算工作台"
    BINDINGS = [
        Binding("ctrl+s", "save", "保存"),
        Binding("ctrl+d", "discard", "还原"),
        Binding("n", "new_channel", "新建渠道", show=False),
        Binding("e", "edit_channel", "编辑渠道", show=False),
        Binding("delete", "delete_channel", "删除渠道", show=False),
        Binding("ctrl+q", "quit", "退出"),
    ]
    _CALC_VALUE_DEFAULTS = {
        "multiplier": "0.05",
        "fen": "5",
        "token_cost": "5",
    }

    CSS = """
    Screen {
        background: #0b1118;
        color: #e7f0f3;
    }

    #workbench-toolbar {
        height: 3;
        padding: 0 2;
        background: #11212c;
    }

    #workspace-brand {
        width: 22;
        height: 3;
    }

    #workspace-title {
        color: #effbfc;
        text-style: bold;
    }

    #workspace-subtitle {
        color: #89a5b0;
    }

    #config-path {
        width: 1fr;
        content-align: right middle;
        color: #9db2bd;
        overflow: hidden;
    }

    #dirty-indicator {
        width: 8;
        content-align: center middle;
        color: #69d3c5;
    }

    #dirty-indicator.dirty {
        color: #ffd166;
    }

    Button {
        min-width: 8;
        background: #243c4b;
        color: #e7f0f3;
        border: none;
    }

    Button:focus {
        background: #317b7e;
        color: #f7ffff;
        text-style: bold;
    }

    Button.-primary {
        background: #216d78;
    }

    Button.-success {
        background: #236954;
    }

    Button.-error {
        background: #783746;
    }

    #workbench-toolbar Button {
        margin-left: 1;
    }

    #shortcut-bar {
        height: 1;
        padding: 0 2;
        background: #0e1a23;
        color: #88a2ac;
    }

    #shortcut-bar Static {
        width: 1fr;
    }

    #shortcut-hint {
        width: 30;
        content-align: right middle;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 1 2;
        overflow-y: auto;
    }

    #calculator-workspace {
        layout: vertical;
        height: auto;
    }

    #calculator-overview {
        layout: horizontal;
        height: auto;
    }

    #calculator-workspace.compact #calculator-overview {
        layout: vertical;
    }

    #calculator-form {
        width: 38;
        min-width: 30;
        height: auto;
        padding: 1;
        background: #12212c;
        border: round #294555;
    }

    #calculator-workspace.compact #calculator-form {
        width: 1fr;
    }

    #calculator-output {
        width: 1fr;
        min-width: 36;
        height: auto;
        margin-left: 1;
        padding: 1;
        background: #12212c;
        border: round #294555;
    }

    #calculator-workspace.compact #calculator-output {
        display: none;
    }

    .section-heading {
        height: 1;
        margin-bottom: 1;
        color: #72d8c9;
        text-style: bold;
    }

    .section-copy {
        height: auto;
        margin-bottom: 1;
        color: #94aab3;
    }

    .form-field {
        height: 3;
        align: left middle;
    }

    .form-field Label {
        width: 11;
        color: #c3d2d8;
    }

    .form-field Input, .form-field Select {
        width: 1fr;
    }

    .form-unit {
        width: 9;
        padding-left: 1;
        color: #78919d;
    }

    #compact-result {
        display: none;
    }

    #compact-error {
        display: none;
    }

    #calculator-workspace.compact #calculator-form .section-copy {
        display: none;
    }

    #calculator-workspace.compact #compact-result {
        display: block;
        height: auto;
        min-height: 5;
        margin-top: 1;
        padding: 0 1;
        background: #164146;
        border: round #4da99e;
        color: #edfdf8;
        text-style: bold;
        content-align: left middle;
    }

    #calculator-workspace.compact #compact-error {
        display: block;
        height: auto;
        min-height: 1;
        margin-top: 1;
        color: #ff9a91;
    }

    #pricing-settings {
        margin-top: 1;
        padding: 0 1;
        background: #101c25;
        border: round #294555;
    }

    #comparison-workspace {
        height: 1fr;
        padding: 1;
        background: #101c25;
        border: round #294555;
    }

    #pricing-grid {
        grid-size: 2;
        grid-columns: 1fr 1fr;
        grid-gutter: 1;
        padding: 0 1 1 1;
    }

    #calculator-workspace.compact #pricing-grid {
        grid-size: 1;
        grid-columns: 1fr;
    }

    #result-grid {
        grid-size: 2;
        grid-columns: 1fr 1fr;
        grid-gutter: 1;
        height: 9;
    }

    .result-cell {
        height: 4;
        padding: 0 1;
        background: #19303d;
        border: round #315566;
    }

    .result-cell.result-primary {
        background: #164146;
        border: round #4da99e;
    }

    .result-name {
        color: #a8bec7;
    }

    .result-value {
        color: #edfdf8;
        text-style: bold;
    }

    #calculation-error, #channel-editor-error {
        min-height: 1;
        color: #ff9a91;
        margin-top: 1;
    }

    DataTable {
        height: 10;
        border: round #294555;
        background: #101d27;
    }

    #comparison-table {
        height: 1fr;
        min-height: 5;
    }

    #channels-table {
        height: 1fr;
        min-height: 5;
    }

    #channels.compact #channel-toolbar {
        height: 3;
    }

    #channels.compact #channels-table {
        height: 6;
        min-height: 5;
    }

    #channels.compact #channel-detail {
        height: 3;
    }

    #channel-toolbar {
        height: 4;
        margin-bottom: 1;
    }

    #channel-copy {
        width: 1fr;
        height: 3;
    }

    #channel-title {
        color: #72d8c9;
        text-style: bold;
    }

    #channel-subtitle {
        color: #94aab3;
    }

    #channel-toolbar Button, #channel-actions Button {
        min-width: 10;
        margin-right: 1;
    }

    #channel-detail {
        height: 4;
        margin-top: 1;
        padding: 0 1;
        background: #12212c;
        border: round #294555;
        color: #b9cbd1;
    }

    #channel-actions {
        height: 3;
        margin-top: 1;
    }

    .confirm-dialog {
        width: 72;
        max-width: 92%;
        height: auto;
        max-height: 92%;
        padding: 1 2;
        background: #12212c;
        border: round #4da99e;
        overflow-y: auto;
    }

    #channel-editor-dialog {
        width: 72;
        max-width: 92%;
        height: 32;
        max-height: 92%;
        padding: 1 2;
        layout: vertical;
        background: #12212c;
        border: round #4da99e;
        overflow: hidden;
    }

    ConfirmScreen, ChannelEditorScreen {
        align: center middle;
        background: #000000 62%;
    }

    .dialog-title {
        margin-bottom: 1;
        color: #effbfc;
        text-style: bold;
    }

    .dialog-message, .channel-unit {
        color: #a9bdc5;
    }

    .editor-section-heading {
        height: 1;
        margin-top: 1;
        color: #72d8c9;
        text-style: bold;
    }

    #channel-editor-fields {
        height: 1fr;
        margin-top: 1;
    }

    #channel-editor-fields Label {
        color: #c3d2d8;
        margin-top: 1;
    }

    #channel-editor-fields Input {
        width: 1fr;
    }

    #channel-source-settings {
        margin-top: 1;
        padding: 0 1;
        border: round #294555;
    }

    .dialog-actions {
        height: 3;
        align: right middle;
        margin-top: 1;
    }

    .dialog-actions Button {
        min-width: 10;
        margin-left: 1;
    }
    """

    _PERSISTENT_INPUT_IDS = frozenset(
        {
            "balance-per-yuan",
            "chatgpt-input-price",
            "chatgpt-output-price",
            "chatgpt-cached-price",
            "usd-cny-rate",
        }
    )

    def __init__(self, document: SettingsDocument) -> None:
        super().__init__()
        self.document = document
        self.settings = document.settings
        self._saved_settings = document.settings
        self._selected_channel_index: int | None = None
        self._suppress_input_events = False
        self.conversion_service = ConversionService()

    def compose(self) -> ComposeResult:
        yield from compose_toolbar(self.document.path)
        with TabbedContent(initial="calculator", id="main-tabs"):
            with TabPane("快速换算", id="calculator"):
                yield from compose_calculator(self.settings)
            with TabPane("价格对比", id="comparison"):
                yield from compose_comparison()
            with TabPane("渠道管理", id="channels"):
                yield from compose_channels()
        yield from compose_footer()

    def on_mount(self) -> None:
        comparison = self.query_one("#comparison-table", DataTable)
        comparison.add_columns("渠道", "USD", "CNY", "相对成本")
        channels = self.query_one("#channels-table", DataTable)
        channels.add_columns("渠道", "模型", "输入", "输出")
        self._apply_compact_layout()
        self._refresh_channel_tables()
        self._refresh_calculation()
        self._refresh_dirty_state()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_compact_layout(event.size.width)

    def _apply_compact_layout(self, width: int | None = None) -> None:
        if not self.is_mounted:
            return
        compact = (width if width is not None else self.size.width) < 96
        self.query_one("#calculator-workspace").set_class(compact, "compact")
        self.query_one("#channels", TabPane).set_class(compact, "compact")

    def _input_value(self, input_id: str) -> str:
        return self.query_one(f"#{input_id}", Input).value.strip()

    def _settings_input_values(self, settings: Settings | None = None) -> dict[str, str]:
        current = settings or self.settings
        profile = current.chatgpt_profile
        return {
            "balance-per-yuan": str(current.balance_per_yuan),
            "chatgpt-input-price": str(profile.input_price),
            "chatgpt-output-price": str(profile.output_price),
            "chatgpt-cached-price": str(profile.cached_price),
            "usd-cny-rate": str(current.usd_cny_rate),
        }

    def _settings_from_calculator(self) -> Settings:
        current_profile = self.settings.chatgpt_profile
        balance_per_yuan = self._input_value("balance-per-yuan")
        usd_cny_rate = self._input_value("usd-cny-rate")
        _positive(balance_per_yuan, "充值比例")
        _positive(usd_cny_rate, "美元兑人民币汇率")
        profile = TokenPriceProfile(
            current_profile.name,
            self._input_value("chatgpt-input-price"),
            self._input_value("chatgpt-output-price"),
            self._input_value("chatgpt-cached-price"),
            provider=current_profile.provider,
            model=current_profile.model,
            currency=current_profile.currency,
            unit=current_profile.unit,
            effective_at=current_profile.effective_at,
            source=current_profile.source,
            version=current_profile.version,
        )
        return replace(
            self.settings,
            balance_per_yuan=balance_per_yuan,
            chatgpt_profile=profile,
            usd_cny_rate=usd_cny_rate,
        )

    def _calculator_inputs_match_settings(self) -> bool:
        expected = self._settings_input_values()
        return all(self._input_value(key) == value for key, value in expected.items())

    def _is_dirty(self) -> bool:
        return self.settings != self._saved_settings or not self._calculator_inputs_match_settings()

    def _refresh_dirty_state(self) -> None:
        dirty = self._is_dirty()
        indicator = self.query_one("#dirty-indicator", Static)
        indicator.update("未保存" if dirty else "已保存")
        indicator.set_class(dirty, "dirty")
        self.query_one("#discard-settings", Button).disabled = not dirty

    def _set_calc_value_unit(self) -> None:
        mode = self.query_one("#calc-mode", Select).value
        unit = {
            "multiplier": "倍",
            "fen": "分/刀",
            "token_cost": "元",
        }.get(str(mode), "")
        self.query_one("#calc-value-unit", Static).update(unit)

    def _calculator_inputs(self) -> CalculatorInputs:
        return CalculatorInputs(
            mode=str(self.query_one("#calc-mode", Select).value),
            value=self._input_value("calc-value"),
            balance_per_yuan=self._input_value("balance-per-yuan"),
            input_price=self._input_value("chatgpt-input-price"),
            output_price=self._input_value("chatgpt-output-price"),
            cached_price=self._input_value("chatgpt-cached-price"),
            usd_cny_rate=self._input_value("usd-cny-rate"),
        )

    def _clear_calculation(self, message: str) -> None:
        self.query_one("#calculation-error", Static).update(message)
        self.query_one("#compact-error", Static).update(message)
        for result_id in (
            "result-multiplier",
            "result-fen",
            "result-token-cost",
            "result-official-cost",
        ):
            self.query_one(f"#{result_id}", Static).update("--")
        self.query_one("#compact-result", Static).update("--")
        self.query_one("#comparison-table", DataTable).clear()

    def _render_calculation(self, display: CalculationDisplay) -> None:
        self.query_one("#calculation-error", Static).update("")
        self.query_one("#compact-error", Static).update("")
        self.query_one("#result-multiplier", Static).update(display.multiplier)
        self.query_one("#result-fen", Static).update(display.fen_per_dollar)
        self.query_one("#result-token-cost", Static).update(display.token_cost_yuan)
        self.query_one("#result-official-cost", Static).update(display.official_cost_usd)
        self.query_one("#compact-result", Static).update(
            f"账号成本 {display.fen_per_dollar}  ·  中转倍率 {display.multiplier}\n"
            f"1 亿成本 {display.token_cost_yuan}  ·  官方成本 {display.official_cost_usd}"
        )
        table = self.query_one("#comparison-table", DataTable)
        table.clear()
        for row in display.comparison:
            table.add_row(row.name, row.usd, row.yuan, row.relative_cost)

    def _refresh_calculation(self) -> None:
        self._set_calc_value_unit()
        try:
            display = calculate_display(
                self._calculator_inputs(), self.settings, self.conversion_service
            )
        except ValueError as exc:
            self._clear_calculation(str(exc))
            return
        self._render_calculation(display)

    def _refresh_channel_tables(self) -> None:
        table = self.query_one("#channels-table", DataTable)
        table.clear()
        profiles = self.settings.comparison_profiles
        for index, profile in enumerate(profiles):
            table.add_row(
                profile.name,
                f"{profile.provider} · {profile.model or '未标注'}",
                format_decimal(profile.input_price),
                format_decimal(profile.output_price),
                key=f"channel-{index}",
            )
        if profiles:
            selected = min(self._selected_channel_index or 0, len(profiles) - 1)
            self._selected_channel_index = selected
            table.move_cursor(row=selected, animate=False)
        else:
            self._selected_channel_index = None
        self._set_channel_action_state()
        self._render_channel_detail()

    def _render_channel_detail(self) -> None:
        detail = self.query_one("#channel-detail", Static)
        profile = self._selected_profile()
        if profile is None:
            detail.update("暂无比较渠道。新建一个渠道即可开始对比。")
            return
        detail.update(
            f"{profile.provider} · {profile.model or '未标注模型'}  |  "
            f"缓存 {format_decimal(profile.cached_price)} USD / 1M\n"
            f"生效 {profile.effective_at or '--'} · "
            f"版本 {profile.version or '未标注'} · "
            f"来源 {profile.source or '未记录'}"
        )

    def _set_channel_action_state(self) -> None:
        has_selection = self._selected_channel_index is not None
        self.query_one("#edit-channel", Button).disabled = not has_selection
        self.query_one("#delete-channel", Button).disabled = not has_selection

    def _replace_profile(self, index: int, profile: TokenPriceProfile) -> None:
        profiles = list(self.settings.comparison_profiles)
        profiles[index] = profile
        self.settings = replace(self.settings, comparison_profiles=tuple(profiles))
        self._selected_channel_index = index
        self._refresh_channel_tables()
        self._refresh_calculation()
        self._refresh_dirty_state()

    def _add_profile(self, profile: TokenPriceProfile) -> None:
        self.settings = replace(
            self.settings,
            comparison_profiles=(*self.settings.comparison_profiles, profile),
        )
        self._selected_channel_index = len(self.settings.comparison_profiles) - 1
        self._refresh_channel_tables()
        self._refresh_calculation()
        self._refresh_dirty_state()

    def _selected_profile(self) -> TokenPriceProfile | None:
        if self._selected_channel_index is None:
            return None
        profiles = self.settings.comparison_profiles
        if self._selected_channel_index >= len(profiles):
            return None
        return profiles[self._selected_channel_index]

    def _open_new_channel(self) -> None:
        self.push_screen(ChannelEditorScreen(), self._new_channel_closed)

    def _new_channel_closed(self, profile: TokenPriceProfile | None) -> None:
        if profile is not None:
            self._add_profile(profile)

    def _open_edit_channel(self) -> None:
        profile = self._selected_profile()
        index = self._selected_channel_index
        if profile is None or index is None:
            self.notify("请先选择一个渠道", severity="warning")
            return
        self.push_screen(
            ChannelEditorScreen(profile),
            lambda updated: self._edit_channel_closed(index, updated),
        )

    def _edit_channel_closed(
        self, index: int, profile: TokenPriceProfile | None
    ) -> None:
        if profile is not None and index < len(self.settings.comparison_profiles):
            self._replace_profile(index, profile)

    def _delete_selected_channel(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            self.notify("请先选择一个渠道", severity="warning")
            return
        self.push_screen(
            ConfirmScreen("删除比较渠道", f"确定删除“{profile.name}”吗？", "删除"),
            self._delete_channel_confirmed,
        )

    def _delete_channel_confirmed(self, accepted: bool) -> None:
        index = self._selected_channel_index
        if not accepted or index is None:
            return
        profiles = list(self.settings.comparison_profiles)
        if index >= len(profiles):
            return
        del profiles[index]
        self.settings = replace(self.settings, comparison_profiles=tuple(profiles))
        self._selected_channel_index = min(index, len(profiles) - 1) if profiles else None
        self._refresh_channel_tables()
        self._refresh_calculation()
        self._refresh_dirty_state()

    def _apply_saved_settings(self) -> None:
        self.settings = self._saved_settings
        self._suppress_input_events = True
        try:
            for input_id, value in self._settings_input_values().items():
                self.query_one(f"#{input_id}", Input).value = value
        finally:
            self._suppress_input_events = False
        self._refresh_channel_tables()
        self._refresh_calculation()
        self._refresh_dirty_state()

    def _save(self) -> None:
        try:
            self.settings = self._settings_from_calculator()
            self._refresh_calculation()
            self.document = save_settings_document(self.document, self.settings)
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            self._refresh_dirty_state()
            return
        self._saved_settings = self.settings
        self.query_one("#config-path", Static).update(
            f"配置 · {self.document.path.name}"
        )
        self._refresh_dirty_state()
        self.notify("配置已保存", severity="information")

    def _discard(self) -> None:
        if not self._is_dirty():
            return
        self.push_screen(
            ConfirmScreen("还原未保存修改", "这会恢复上次保存的配置。", "还原"),
            self._discard_confirmed,
        )

    def _discard_confirmed(self, accepted: bool) -> None:
        if accepted:
            self._apply_saved_settings()

    def _quit_confirmed(self, accepted: bool) -> None:
        if accepted:
            self.exit()

    @on(Input.Changed)
    def on_input_changed(self, event: Input.Changed) -> None:
        if self._suppress_input_events:
            return
        if event.input.id in self._PERSISTENT_INPUT_IDS:
            try:
                self.settings = self._settings_from_calculator()
            except ValueError:
                pass
            self._refresh_dirty_state()
        if event.input.id == "calc-value" or event.input.id in self._PERSISTENT_INPUT_IDS:
            self._refresh_calculation()

    @on(Select.Changed, "#calc-mode")
    def on_mode_changed(self, event: Select.Changed) -> None:
        mode = str(event.value)
        default = self._CALC_VALUE_DEFAULTS.get(mode)
        if default is not None:
            self.query_one("#calc-value", Input).value = default
        self._refresh_calculation()

    @on(DataTable.RowHighlighted, "#channels-table")
    def on_channel_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = str(event.row_key.value)
        if key.startswith("channel-"):
            self._selected_channel_index = int(key.removeprefix("channel-"))
            self._set_channel_action_state()
            self._render_channel_detail()

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions: dict[str, Callable[[], None]] = {
            "save-settings": self._save,
            "discard-settings": self._discard,
            "new-channel": self._open_new_channel,
            "edit-channel": self._open_edit_channel,
            "delete-channel": self._delete_selected_channel,
        }
        action = actions.get(event.button.id or "")
        if action is not None:
            action()

    def action_save(self) -> None:
        self._save()

    def action_discard(self) -> None:
        self._discard()

    def action_new_channel(self) -> None:
        self._open_new_channel()

    def action_edit_channel(self) -> None:
        self._open_edit_channel()

    def action_delete_channel(self) -> None:
        self._delete_selected_channel()

    def action_quit(self) -> None:
        if self._is_dirty():
            self.push_screen(
                ConfirmScreen("退出工作台", "存在未保存的配置修改，确定退出吗？", "退出"),
                self._quit_confirmed,
            )
            return
        self.exit()


TuiApp = UnitTranslatorApp


def launch_tui(config_path: str | Path | None = None) -> int:
    """Run the editable TUI, creating a config file only after Save."""
    UnitTranslatorApp(load_settings_document(config_path)).run()
    return 0
