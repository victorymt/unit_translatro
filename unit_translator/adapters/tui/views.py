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
        yield Static(f"配置: {config_path}", id="config-path")
        yield Static("已保存", id="dirty-indicator")
        yield Button("保存", id="save-settings", variant="success")
        yield Button("还原", id="discard-settings")


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
    profile = settings.chatgpt_profile
    yield Static("ChatGPT 中转参数", classes="section-heading")
    with Horizontal(classes="form-field"):
        yield Label("换算模式")
        yield Select(MODE_OPTIONS, value="multiplier", allow_blank=False, id="calc-mode")
    yield from _compose_input_field(
        "换算值", "0.05", "calc-value", "", unit_id="calc-value-unit"
    )
    yield from _compose_input_field(
        "充值比例", str(settings.balance_per_yuan), "balance-per-yuan", "刀/元"
    )
    yield from _compose_input_field("输入价", str(profile.input_price), "chatgpt-input-price", "刀/1M")
    yield from _compose_input_field("输出价", str(profile.output_price), "chatgpt-output-price", "刀/1M")
    yield from _compose_input_field("缓存价", str(profile.cached_price), "chatgpt-cached-price", "刀/1M")
    yield from _compose_input_field("美元汇率", str(settings.usd_cny_rate), "usd-cny-rate", "元/USD")


def _compose_result_cell(label: str, result_id: str) -> ComposeResult:
    with Vertical(classes="result-cell"):
        yield Static(label, classes="result-name")
        yield Static("--", id=result_id, classes="result-value")


def _compose_calculator_output() -> ComposeResult:
    yield Static("换算结果", classes="section-heading")
    with Grid(id="result-grid"):
        yield from _compose_result_cell("倍率", "result-multiplier")
        yield from _compose_result_cell("账号成本", "result-fen")
        yield from _compose_result_cell("ChatGPT 1 亿成本", "result-token-cost")
        yield from _compose_result_cell("官方混合成本", "result-official-cost")
    yield Static("", id="calculation-error")
    yield Static("1 亿混合 Token 成本对比", classes="table-heading")
    yield DataTable(id="comparison-table", zebra_stripes=True)


def compose_calculator(settings: Settings) -> ComposeResult:
    """Build the calculator view while preserving its stable widget IDs."""
    with Horizontal(id="calculator-workspace"):
        with Vertical(id="calculator-form"):
            yield from _compose_calculator_form(settings)
        with Vertical(id="calculator-output"):
            yield from _compose_calculator_output()


def compose_channels() -> ComposeResult:
    """Build the channel-management view with stable action identifiers."""
    with Horizontal(id="channel-toolbar"):
        yield Static("比较渠道目录")
        yield Button("新建", id="new-channel", variant="primary")
    yield DataTable(id="channels-table", zebra_stripes=True, cursor_type="row")
    with Horizontal(id="channel-actions"):
        yield Button("编辑", id="edit-channel")
        yield Button("删除", id="delete-channel", variant="error")
