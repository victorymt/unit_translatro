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
from textual.containers import Container, Grid, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from app_config import Settings
from converter_core import (
    ConversionRequest,
    TokenPriceProfile,
    _positive,
    calculate_conversion,
    format_decimal,
)
from settings_store import (
    SettingsDocument,
    load_settings_document,
    save_settings_document,
)


MODE_OPTIONS = (
    ("固定倍率", "multiplier"),
    ("固定账号成本", "fen"),
    ("固定 1 亿 Token 成本", "token_cost"),
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
            yield Static("USD / 1M tokens", classes="channel-unit")
            with Vertical(id="channel-editor-fields"):
                yield Label("名称")
                yield Input(profile.name if profile else "", id="channel-name")
                yield Label("提供商")
                yield Input(profile.provider if profile else "custom", id="channel-provider")
                yield Label("模型")
                yield Input(profile.model if profile else "", id="channel-model")
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
                yield Label("生效日期")
                yield Input(profile.effective_at or "" if profile else "", id="channel-effective-at")
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
    """Dense two-view TUI for calculation and comparison channel management."""

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

    CSS = """
    Screen {
        background: #101820;
        color: #e8edf2;
    }

    Header {
        background: #152737;
        color: #f4f8fb;
    }

    Footer {
        background: #152737;
    }

    #workbench-toolbar {
        height: 3;
        padding: 0 1;
        background: #17212b;
    }

    #config-path {
        width: 1fr;
        content-align: left middle;
        color: #afc0cd;
        overflow: hidden;
    }

    #dirty-indicator {
        width: 8;
        content-align: center middle;
        color: #80cbc4;
    }

    #dirty-indicator.dirty {
        color: #ffd166;
    }

    #workbench-toolbar Button {
        min-width: 8;
        margin-left: 1;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 1 2;
        overflow-y: auto;
    }

    #calculator-workspace {
        layout: horizontal;
        height: auto;
    }

    #calculator-workspace.compact {
        layout: vertical;
    }

    #calculator-form {
        width: 42;
        min-width: 34;
        height: auto;
        padding: 1;
        background: #17212b;
        border: round #365064;
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
        background: #17212b;
        border: round #365064;
    }

    #calculator-workspace.compact #calculator-output {
        width: 1fr;
        margin-left: 0;
        margin-top: 1;
    }

    .section-heading {
        height: 1;
        margin-bottom: 1;
        color: #80cbc4;
        text-style: bold;
    }

    .form-field {
        height: 3;
        align: left middle;
    }

    .form-field Label {
        width: 15;
        color: #b6c7d4;
    }

    .form-field Input, .form-field Select {
        width: 1fr;
    }

    .form-unit {
        width: 10;
        padding-left: 1;
        color: #8497a6;
    }

    #result-grid {
        grid-size: 2;
        grid-columns: 1fr 1fr;
        grid-gutter: 1;
        height: 7;
    }

    .result-cell {
        height: 3;
        padding: 0 1;
        background: #1f3341;
        border: tall #315064;
    }

    .result-name {
        color: #9cb0bd;
    }

    .result-value {
        color: #e7f6ed;
        text-style: bold;
    }

    #calculation-error, #channel-editor-error {
        min-height: 1;
        color: #ff8a80;
        margin-top: 1;
    }

    .table-heading {
        height: 1;
        margin-top: 1;
        margin-bottom: 1;
        color: #b6c7d4;
    }

    DataTable {
        height: 12;
        border: round #365064;
        background: #14232d;
    }

    #channels-table {
        height: 1fr;
        min-height: 12;
    }

    #channel-toolbar {
        height: 3;
        margin-bottom: 1;
    }

    #channel-toolbar Static {
        width: 1fr;
        content-align: left middle;
        color: #80cbc4;
        text-style: bold;
    }

    #channel-actions {
        height: 3;
        margin-top: 1;
    }

    #channel-actions Button, #channel-toolbar Button {
        min-width: 10;
        margin-right: 1;
    }

    .confirm-dialog, #channel-editor-dialog {
        width: 72;
        max-width: 92%;
        height: auto;
        max-height: 92%;
        padding: 1 2;
        background: #17212b;
        border: round #80cbc4;
        overflow-y: auto;
    }

    ConfirmScreen, ChannelEditorScreen {
        align: center middle;
        background: #000000 58%;
    }

    .dialog-title {
        margin-bottom: 1;
        color: #f4f8fb;
        text-style: bold;
    }

    .dialog-message, .channel-unit {
        color: #b6c7d4;
    }

    #channel-editor-fields {
        margin-top: 1;
    }

    #channel-editor-fields Label {
        color: #b6c7d4;
        margin-top: 1;
    }

    #channel-editor-fields Input {
        width: 1fr;
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

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="workbench-toolbar"):
            yield Static(f"配置: {self.document.path}", id="config-path")
            yield Static("已保存", id="dirty-indicator")
            yield Button("保存", id="save-settings", variant="success")
            yield Button("还原", id="discard-settings")
        with TabbedContent(initial="calculator", id="main-tabs"):
            with TabPane("换算", id="calculator"):
                with Horizontal(id="calculator-workspace"):
                    with Vertical(id="calculator-form"):
                        yield Static("ChatGPT 中转参数", classes="section-heading")
                        with Horizontal(classes="form-field"):
                            yield Label("换算模式")
                            yield Select(
                                MODE_OPTIONS,
                                value="multiplier",
                                allow_blank=False,
                                id="calc-mode",
                            )
                        with Horizontal(classes="form-field"):
                            yield Label("换算值")
                            yield Input("0.05", id="calc-value", type="number")
                            yield Static("", id="calc-value-unit", classes="form-unit")
                        with Horizontal(classes="form-field"):
                            yield Label("充值比例")
                            yield Input(
                                str(self.settings.balance_per_yuan),
                                id="balance-per-yuan",
                                type="number",
                            )
                            yield Static("刀/元", classes="form-unit")
                        with Horizontal(classes="form-field"):
                            yield Label("输入价")
                            yield Input(
                                str(self.settings.chatgpt_profile.input_price),
                                id="chatgpt-input-price",
                                type="number",
                            )
                            yield Static("刀/1M", classes="form-unit")
                        with Horizontal(classes="form-field"):
                            yield Label("输出价")
                            yield Input(
                                str(self.settings.chatgpt_profile.output_price),
                                id="chatgpt-output-price",
                                type="number",
                            )
                            yield Static("刀/1M", classes="form-unit")
                        with Horizontal(classes="form-field"):
                            yield Label("缓存价")
                            yield Input(
                                str(self.settings.chatgpt_profile.cached_price),
                                id="chatgpt-cached-price",
                                type="number",
                            )
                            yield Static("刀/1M", classes="form-unit")
                        with Horizontal(classes="form-field"):
                            yield Label("美元汇率")
                            yield Input(
                                str(self.settings.usd_cny_rate),
                                id="usd-cny-rate",
                                type="number",
                            )
                            yield Static("元/USD", classes="form-unit")
                    with Vertical(id="calculator-output"):
                        yield Static("换算结果", classes="section-heading")
                        with Grid(id="result-grid"):
                            with Vertical(classes="result-cell"):
                                yield Static("倍率", classes="result-name")
                                yield Static("--", id="result-multiplier", classes="result-value")
                            with Vertical(classes="result-cell"):
                                yield Static("账号成本", classes="result-name")
                                yield Static("--", id="result-fen", classes="result-value")
                            with Vertical(classes="result-cell"):
                                yield Static("ChatGPT 1 亿成本", classes="result-name")
                                yield Static("--", id="result-token-cost", classes="result-value")
                            with Vertical(classes="result-cell"):
                                yield Static("官方混合成本", classes="result-name")
                                yield Static("--", id="result-official-cost", classes="result-value")
                        yield Static("", id="calculation-error")
                        yield Static("1 亿混合 Token 成本对比", classes="table-heading")
                        yield DataTable(id="comparison-table", zebra_stripes=True)
            with TabPane("渠道", id="channels"):
                with Horizontal(id="channel-toolbar"):
                    yield Static("比较渠道目录")
                    yield Button("新建", id="new-channel", variant="primary")
                yield DataTable(id="channels-table", zebra_stripes=True, cursor_type="row")
                with Horizontal(id="channel-actions"):
                    yield Button("编辑", id="edit-channel")
                    yield Button("删除", id="delete-channel", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        comparison = self.query_one("#comparison-table", DataTable)
        comparison.add_columns("渠道", "USD", "CNY", "相对成本")
        channels = self.query_one("#channels-table", DataTable)
        channels.add_columns("名称", "提供商", "模型", "输入", "输出", "缓存", "生效", "版本")
        self._apply_compact_layout()
        self._refresh_channel_tables()
        self._refresh_calculation()
        self._refresh_dirty_state()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_compact_layout(event.size.width)

    def _apply_compact_layout(self, width: int | None = None) -> None:
        if not self.is_mounted:
            return
        workspace = self.query_one("#calculator-workspace", Horizontal)
        workspace.set_class((width if width is not None else self.size.width) < 96, "compact")

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

    def _refresh_calculation(self) -> None:
        self._set_calc_value_unit()
        try:
            request = ConversionRequest(
                mode=str(self.query_one("#calc-mode", Select).value),
                value=self._input_value("calc-value"),
                balance_per_yuan=self._input_value("balance-per-yuan"),
                chatgpt_profile=TokenPriceProfile(
                    self.settings.chatgpt_profile.name,
                    self._input_value("chatgpt-input-price"),
                    self._input_value("chatgpt-output-price"),
                    self._input_value("chatgpt-cached-price"),
                    provider=self.settings.chatgpt_profile.provider,
                    model=self.settings.chatgpt_profile.model,
                ),
                usd_cny_rate=self._input_value("usd-cny-rate"),
                usage=self.settings.usage,
                comparison_profiles=self.settings.comparison_profiles,
            )
            result = calculate_conversion(request)
        except ValueError as exc:
            self.query_one("#calculation-error", Static).update(str(exc))
            for result_id in (
                "result-multiplier",
                "result-fen",
                "result-token-cost",
                "result-official-cost",
            ):
                self.query_one(f"#{result_id}", Static).update("--")
            self.query_one("#comparison-table", DataTable).clear()
            return

        self.query_one("#calculation-error", Static).update("")
        self.query_one("#result-multiplier", Static).update(
            f"{format_decimal(result.multiplier)}x"
        )
        self.query_one("#result-fen", Static).update(
            f"{format_decimal(result.fen_per_dollar)} 分/刀"
        )
        self.query_one("#result-token-cost", Static).update(
            f"{format_decimal(result.token_cost_yuan)} 元"
        )
        self.query_one("#result-official-cost", Static).update(
            f"${format_decimal(result.official_cost_usd)}"
        )
        table = self.query_one("#comparison-table", DataTable)
        table.clear()
        for row in result.comparison:
            table.add_row(
                row.name,
                "--" if row.usd is None else f"${format_decimal(row.usd)}",
                f"{format_decimal(row.yuan)} 元",
                "基准"
                if row.usd is None
                else "--"
                if row.relative_to_chatgpt is None
                else f"{format_decimal(row.relative_to_chatgpt)}x",
            )

    def _refresh_channel_tables(self) -> None:
        table = self.query_one("#channels-table", DataTable)
        table.clear()
        profiles = self.settings.comparison_profiles
        for index, profile in enumerate(profiles):
            table.add_row(
                profile.name,
                profile.provider,
                profile.model,
                format_decimal(profile.input_price),
                format_decimal(profile.output_price),
                format_decimal(profile.cached_price),
                profile.effective_at or "--",
                profile.version or "--",
                key=f"channel-{index}",
            )
        if profiles:
            selected = min(self._selected_channel_index or 0, len(profiles) - 1)
            self._selected_channel_index = selected
            table.move_cursor(row=selected, animate=False)
        else:
            self._selected_channel_index = None
        self._set_channel_action_state()

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
        self.query_one("#config-path", Static).update(f"配置: {self.document.path}")
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
        self._refresh_calculation()

    @on(DataTable.RowHighlighted, "#channels-table")
    def on_channel_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = str(event.row_key.value)
        if key.startswith("channel-"):
            self._selected_channel_index = int(key.removeprefix("channel-"))
            self._set_channel_action_state()

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
