"""Composable Textual view fragments for the interactive workbench."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from app_config import Settings


MODE_OPTIONS = (
    ("固定倍率", "multiplier"),
    ("固定账号成本", "fen"),
    ("固定 1 亿 Token 成本", "token_cost"),
)


def compose_toolbar(config_path: Path) -> ComposeResult:
    with Horizontal(id="workbench-toolbar"):
        with Vertical(id="workspace-brand"):
            yield Static("Unit Translator", id="workspace-title")
        yield Static(config_path.name, id="config-path")
        yield Static("已保存", id="dirty-indicator")
        yield Button("保存", id="save-settings", variant="success")
        yield Button("还原", id="discard-settings")


def compose_footer() -> ComposeResult:
    """Keep the footer extension point without adding persistent chrome."""
    yield from ()


def _compose_input_field(
    label: str,
    value: str,
    input_id: str,
    unit: str,
    *,
    unit_id: str | None = None,
) -> ComposeResult:
    with Horizontal(classes="form-field"):
        yield Label(label)
        yield Input(value, id=input_id, type="number")
        yield Static(unit, id=unit_id, classes="form-unit")


def _compose_calculator_form(settings: Settings) -> ComposeResult:
    yield Static("快速换算", classes="section-heading")
    with Horizontal(classes="form-field"):
        yield Label("换算模式")
        yield Select(MODE_OPTIONS, value="multiplier", allow_blank=False, id="calc-mode")
    yield from _compose_input_field(
        "换算值", "0.05", "calc-value", "", unit_id="calc-value-unit"
    )
    yield Static("--", id="compact-result")
    yield Static("", id="compact-error")


def _compose_pricing_settings(settings: Settings) -> ComposeResult:
    """Keep persistent price settings visible alongside the quick calculator."""
    profile = settings.chatgpt_profile
    with Vertical(id="pricing-settings"):
        yield Static("高级计价参数", classes="section-heading")
        with Grid(id="pricing-grid"):
            yield from _compose_input_field(
                "充值比例", str(settings.balance_per_yuan), "balance-per-yuan", "刀/元"
            )
            yield from _compose_input_field(
                "美元汇率", str(settings.usd_cny_rate), "usd-cny-rate", "元/USD"
            )
            yield from _compose_input_field(
                "输入价", str(profile.input_price), "chatgpt-input-price", "刀/1M"
            )
            yield from _compose_input_field(
                "输出价", str(profile.output_price), "chatgpt-output-price", "刀/1M"
            )
            yield from _compose_input_field(
                "缓存价", str(profile.cached_price), "chatgpt-cached-price", "刀/1M"
            )


def _compose_result_cell(
    label: str, result_id: str, *, primary: bool = False
) -> ComposeResult:
    classes = "result-cell result-primary" if primary else "result-cell"
    with Vertical(classes=classes):
        yield Static(label, classes="result-name")
        yield Static("--", id=result_id, classes="result-value")


def _compose_calculator_output() -> ComposeResult:
    yield Static("结果", classes="section-heading")
    with Grid(id="result-grid"):
        yield from _compose_result_cell("账号成本", "result-fen", primary=True)
        yield from _compose_result_cell("中转倍率", "result-multiplier")
        yield from _compose_result_cell("ChatGPT 1 亿成本", "result-token-cost")
        yield from _compose_result_cell("官方混合成本", "result-official-cost")
    yield Static("", id="calculation-error")


def compose_comparison() -> ComposeResult:
    """Build the always-available channel cost comparison view."""
    with Vertical(id="comparison-workspace"):
        yield Static("价格对比", classes="section-heading")
        yield DataTable(id="comparison-table", zebra_stripes=False)


def compose_calculator(settings: Settings) -> ComposeResult:
    """Build the calculator view while preserving its stable widget IDs."""
    with Vertical(id="calculator-workspace"):
        with Horizontal(id="calculator-overview"):
            with Vertical(id="calculator-form"):
                yield from _compose_calculator_form(settings)
            with Vertical(id="calculator-output"):
                yield from _compose_calculator_output()
        yield from _compose_pricing_settings(settings)


def compose_channels() -> ComposeResult:
    """Build the channel-management view with stable action identifiers."""
    with Horizontal(id="channel-toolbar"):
        with Vertical(id="channel-copy"):
            yield Static("比较渠道", id="channel-title")
        yield Button("新建", id="new-channel", variant="primary")
    yield DataTable(id="channels-table", zebra_stripes=False, cursor_type="row")
    yield Static("选择一个渠道以查看详细信息。", id="channel-detail")
    with Horizontal(id="channel-actions"):
        yield Button("编辑", id="edit-channel")
        yield Button("删除", id="delete-channel", variant="error")
