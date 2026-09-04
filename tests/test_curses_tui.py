import tempfile
import unittest
import curses
from unit_translator.adapters.tui import app as curses_tui
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from unit_translator.adapters.tui.app import (
    CursesTuiState,
    _calculator_panel_top,
    _draw_channels,
    _draw_calculator_panel,
    _draw_main,
    _edit_channel,
    _footer_text,
    _handle_main_key,
    _PromptInputError,
    _prompt,
    _run_usage,
    _run_channels,
    display_width,
    _handle_calculator_key,
    _run_usage_interactive,
)
from unit_translator.adapters.tui.bc_calculator import BcEvaluator, CalculatorSession
from unit_translator.domain.conversion import TokenPriceProfile, TokenUsage
from unit_translator.infrastructure.settings import load_settings_document
from unit_translator.commands.main import launch_tui


class CursesTuiStateTests(unittest.TestCase):
    def _state(self, directory: str) -> CursesTuiState:
        return CursesTuiState.from_document(
            load_settings_document(Path(directory) / "settings.toml")
        )

    def test_defaults_calculate_without_pending_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            display = state.calculate()
            self.assertFalse(state.is_dirty())
            self.assertEqual(display.multiplier, "0.05x")
            self.assertEqual(display.fen_per_dollar, "5 分/刀")
            self.assertEqual(display.token_cost_yuan, "4.50678902 元")
            self.assertEqual(len(display.comparison), 5)

    def test_mode_and_field_editing_are_local_and_immediate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            state.set_mode("token_cost")
            self.assertEqual(state.value, "5")
            state.active_field = 1
            state.edit(ord("2"))
            self.assertEqual(state.balance_per_yuan, "2")
            self.assertTrue(state.is_dirty())

    def test_fixed_cost_mode_shows_yuan_and_normalizes_usage_mix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            state.settings = replace(state.settings, usage=TokenUsage("10", "20", "30"))
            state.set_mode("token_cost")
            display = state.calculate()
            self.assertEqual(display.token_cost_yuan, "5 元")
            self.assertEqual(display.fen_per_dollar, "0.45112782 分/刀")
            screen = _RecordingScreen(height=20, width=100)
            _draw_main(screen, state, (1, 2, 3, 4))
            output = "\n".join(screen.lines.values())
            self.assertIn("元/1亿 Token", output)
            self.assertIn("用量配比会归一化到 1 亿", output)

    def test_numeric_editor_supports_cursor_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            state.edit(curses.KEY_END)
            state.edit(curses.KEY_LEFT)
            state.edit(ord("9"))
            self.assertEqual(state.value, "0.095")

    def test_main_navigation_keeps_mode_switch_on_m_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            screen = _RecordingScreen()
            _handle_main_key(screen, state, (1, 2, 3, 4), curses.KEY_RIGHT)
            self.assertEqual(state.mode, "multiplier")
            _handle_main_key(screen, state, (1, 2, 3, 4), ord("m"))
            self.assertEqual(state.mode, "fen")

    def test_main_help_shortcut_opens_contextual_help(self) -> None:
        class HelpScreen(_RecordingScreen):
            def getch(self) -> int:
                return ord("x")

        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            screen = HelpScreen(height=24, width=80)
            self.assertFalse(_handle_main_key(screen, state, (1, 2, 3, 4), ord("?")))
            output = "\n".join(screen.lines.values())
            self.assertIn("主屏快捷键", output)
            self.assertIn("c 打开渠道管理", output)

    def test_usage_edit_is_saved_with_the_other_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            state.input_tokens = "10"
            state.output_tokens = "20"
            state.cached_tokens = "30"
            state.save()
            self.assertEqual(state.settings.usage.total_tokens, 60)
            self.assertFalse(state.is_dirty())

    def test_calculation_is_cached_until_inputs_or_settings_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            with patch(
                "unit_translator.adapters.tui.app.calculate_display",
                wraps=curses_tui.calculate_display,
            ) as calculate:
                state.calculate()
                state.calculate()
                self.assertEqual(calculate.call_count, 1)
                state.edit(ord("2"))
                state.calculate()
                self.assertEqual(calculate.call_count, 2)

    def test_invalid_input_is_reported_by_shared_calculator(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            state.value = "-1"
            with self.assertRaisesRegex(ValueError, "不能小于 0"):
                state.calculate()

    def test_save_and_discard_round_trip_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            state.balance_per_yuan = "1.5"
            state.save()
            self.assertTrue(state.document.path.exists())
            self.assertFalse(state.is_dirty())
            state.balance_per_yuan = "2"
            self.assertTrue(state.is_dirty())
            state.discard()
            self.assertEqual(state.balance_per_yuan, "1.5")
            self.assertFalse(state.is_dirty())

    def test_display_width_handles_chinese_labels(self) -> None:
        self.assertEqual(display_width("渠道管理"), 8)

    def test_edit_clears_stale_success_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            state.message = "配置已保存"
            state.edit(ord("2"))
            self.assertEqual(state.message, "")

    def test_calculation_error_does_not_replace_save_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            state.error = "配置文件无法保存: denied"
            state.value = "-1"
            screen = _RecordingScreen()
            _draw_main(screen, state, (1, 2, 3, 4))
            self.assertIn("配置文件无法保存", screen.lines[11])
            self.assertIn("!换算值", screen.lines[6])

    def test_minimum_main_window_keeps_footer_below_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            screen = _RecordingScreen(height=20, width=72)
            _draw_main(screen, state, (1, 2, 3, 4))
            self.assertNotIn("Tab/方向键", screen.lines.get(18, ""))
            self.assertIn("Tab/方向键", screen.lines[19])

    def test_minimum_main_window_identifies_hidden_comparisons(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            screen = _RecordingScreen(height=20, width=72)
            _draw_main(screen, state, (1, 2, 3, 4))
            output = "\n".join(screen.lines.values())
            self.assertIn("渠道对比（5 个，按 c 查看全部）", output)
            self.assertIn("渠道列表已折叠", output)

    def test_long_numeric_field_keeps_its_unit_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            state.balance_per_yuan = "123456789012345678901234"
            state.active_field = 1
            state.cursor = len(state.balance_per_yuan)
            state.replace_on_type = False
            screen = _RecordingScreen(height=20, width=72)
            _draw_main(screen, state, (1, 2, 3, 4))
            self.assertIn("刀/元", screen.lines[6])

    def test_full_main_layout_prioritizes_cny_and_keeps_units_aligned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            screen = _RecordingScreen(height=24, width=80)
            _draw_main(screen, state, (1, 2, 3, 4))
            header = screen.lines[16]
            self.assertIn("CNY", header)
            self.assertIn("相对成本", header)
            self.assertNotIn("USD", header)
            self.assertIn("倍", screen.lines[6])
            self.assertIn("刀/元", screen.lines[6])
            self.assertIn("元/USD", screen.lines[7])
            self.assertIn("编辑 Tab/方向键", screen.lines[23])

    def test_grouped_footer_fits_full_and_compact_widths(self) -> None:
        for width in (72, 80, 100):
            footer = _footer_text(width)
            self.assertLessEqual(display_width(footer), width - 4)
            self.assertIn("帮助", footer)

    def test_main_parameters_are_rendered_without_blank_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            screen = _RecordingScreen(height=24, width=100)
            _draw_main(screen, state, (1, 2, 3, 4))
            self.assertIn("换算值", screen.lines[6])
            self.assertIn("充值比例", screen.lines[6])
            self.assertIn("美元汇率", screen.lines[7])
            self.assertIn("输入价", screen.lines[7])
            self.assertIn("输出价", screen.lines[8])
            self.assertIn("缓存价", screen.lines[8])

    def test_calculator_panel_is_visible_without_dirtying_settings(self) -> None:
        class FakeTransport:
            def start(self) -> None:
                return

            def evaluate(self, expression: str) -> str:
                return "3"

            def close(self) -> None:
                return

        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            session = CalculatorSession(BcEvaluator(transport=FakeTransport()))
            session.start()
            session.focus()
            session.insert("1+2")
            session.submit()
            screen = _RecordingScreen(height=20, width=72)
            _draw_main(screen, state, (1, 2, 3, 4), session)
            output = "\n".join(screen.lines.values())
            self.assertIn("快速计算", output)
            self.assertIn("1+2", output)
            self.assertIn("3", output)
            self.assertIn("当前用量成本", output)
            self.assertFalse(state.is_dirty())
            session.close()

    def test_calculator_panel_can_be_collapsed_without_dirtying_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            session = CalculatorSession()
            session.toggle_collapsed()
            screen = _RecordingScreen(height=24, width=80)
            _draw_calculator_panel(screen, session, (1, 2, 3, 4), 14)
            output = "\n".join(screen.lines.values())
            self.assertIn("快速计算 · 已折叠 · F7 展开", output)
            self.assertNotIn("历史：暂无", output)
            self.assertFalse(state.is_dirty())
            self.assertFalse(session.focused)
            _handle_calculator_key(session, curses_tui.CALCULATOR_FOCUS_KEY)
            self.assertFalse(session.collapsed)
            self.assertTrue(session.focused)

    def test_calculator_history_is_stacked_above_input_and_clipped_by_height(self) -> None:
        class FakeTransport:
            def start(self) -> None:
                return

            def evaluate(self, expression: str) -> str:
                return {"34*32": "1088", "23*5": "115"}[expression]

            def close(self) -> None:
                return

        session = CalculatorSession(BcEvaluator(transport=FakeTransport()))
        session.start()
        session.focus()
        for expression in ("34*32", "23*5"):
            session.expression = expression
            session.cursor = len(expression)
            session.submit()

        full = _RecordingScreen(height=24, width=80)
        _draw_calculator_panel(full, session, (1, 2, 3, 4), 14)
        top = _calculator_panel_top(full, session, 14)
        self.assertIn("34*32", full.lines[top + 1])
        self.assertIn("1088", full.lines[top + 2])
        self.assertIn("23*5", full.lines[top + 3])
        self.assertIn("115", full.lines[top + 4])
        self.assertIn("> |", full.lines[top + 5])

        compact = _RecordingScreen(height=20, width=72)
        _draw_calculator_panel(compact, session, (1, 2, 3, 4), 14)
        compact_output = "\n".join(compact.lines.values())
        self.assertNotIn("34*32", compact_output)
        self.assertIn("23*5", compact_output)
        session.close()

    def test_f6_focus_and_calculator_key_dispatch(self) -> None:
        class FakeTransport:
            def start(self) -> None:
                return

            def evaluate(self, expression: str) -> str:
                return "4"

            def close(self) -> None:
                return

        session = CalculatorSession(BcEvaluator(transport=FakeTransport()))
        self.assertTrue(_handle_calculator_key(session, curses_tui.CALCULATOR_FOCUS_KEY))
        self.assertTrue(session.focused)
        for key in map(ord, "2+2"):
            self.assertTrue(_handle_calculator_key(session, key))
        _handle_calculator_key(session, 10)
        self.assertEqual(session.result, "4")
        _handle_calculator_key(session, curses_tui.CALCULATOR_FOCUS_KEY)
        self.assertFalse(session.focused)
        session.close()

    def test_usage_form_can_switch_to_calculator_and_commit(self) -> None:
        class FakeTransport:
            def start(self) -> None:
                return

            def evaluate(self, expression: str) -> str:
                return "2"

            def close(self) -> None:
                return

        class KeyScreen(_RecordingScreen):
            def __init__(self) -> None:
                super().__init__(height=20, width=72)
                self.keys = [
                    curses_tui.CALCULATOR_FOCUS_KEY,
                    ord("1"),
                    curses_tui.CALCULATOR_FOCUS_KEY,
                    10,
                    10,
                    10,
                ]

            def getch(self) -> int:
                return self.keys.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            session = CalculatorSession(BcEvaluator(transport=FakeTransport()))
            _run_usage_interactive(KeyScreen(), state, (1, 2, 3, 4), session)
            self.assertFalse(state.is_dirty())
            self.assertEqual(session.expression, "1")
            self.assertFalse(session.focused)
            session.close()

    def test_usage_window_shows_size_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            screen = _RecordingScreen(height=19, width=72)
            _run_usage(screen, state, (1, 2, 3, 4))
            self.assertIn("终端窗口至少需要", "\n".join(screen.lines.values()))

    def test_channel_edit_can_be_cancelled_with_escape(self) -> None:
        class EscapeScreen(_RecordingScreen):
            def getstr(self, *args: object) -> bytes:
                return b"\x1b"

        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            profile = state.settings.comparison_profiles[0]
            with patch("unit_translator.adapters.tui.app.curses.echo"), patch(
                "unit_translator.adapters.tui.app.curses.noecho"
            ):
                self.assertIsNone(_edit_channel(EscapeScreen(), profile))

    def test_channel_edit_requires_canonical_date_and_keeps_values(self) -> None:
        class ValuesScreen(_RecordingScreen):
            def __init__(self) -> None:
                super().__init__(height=24, width=100)
                self.values = iter(
                    [
                        "demo",
                        "custom",
                        "model",
                        "1",
                        "2",
                        "0.1",
                        "20260201",
                        "source",
                        "v1",
                        "2026-02-01",
                    ]
                )

            def getstr(self, *args: object) -> bytes:
                return next(self.values).encode()

        with patch("unit_translator.adapters.tui.app.curses.echo"), patch(
            "unit_translator.adapters.tui.app.curses.noecho"
        ):
            profile = _edit_channel(ValuesScreen(), None)
        self.assertIsNotNone(profile)
        self.assertEqual(profile.effective_at, "2026-02-01")

    def test_prompt_input_errors_are_not_treated_as_defaults(self) -> None:
        class ErrorScreen(_RecordingScreen):
            def getstr(self, *args: object) -> bytes:
                raise curses.error("read failed")

        with patch("unit_translator.adapters.tui.app.curses.echo"), patch(
            "unit_translator.adapters.tui.app.curses.noecho"
        ):
            with self.assertRaises(_PromptInputError):
                _prompt(ErrorScreen(), 1, "名称", "default")

    def test_usage_screen_updates_state_without_saving_immediately(self) -> None:
        class ValuesScreen(_RecordingScreen):
            def __init__(self) -> None:
                super().__init__(height=24, width=100)
                self.values = iter(["10", "20", "30"])

            def getstr(self, *args: object) -> bytes:
                return next(self.values).encode()

        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            with patch("unit_translator.adapters.tui.app.curses.echo"), patch(
                "unit_translator.adapters.tui.app.curses.noecho"
            ):
                _run_usage(ValuesScreen(), state, (1, 2, 3, 4))
            self.assertEqual(state.settings.usage.total_tokens, 60)
            self.assertTrue(state.is_dirty())

    def test_usage_screen_is_marked_as_advanced_ratio_configuration(self) -> None:
        class ValuesScreen(_RecordingScreen):
            def __init__(self) -> None:
                super().__init__(height=24, width=100)
                self.values = iter([b"1", b"2", b"3"])

            def getstr(self, *args: object) -> bytes:
                return next(self.values)

        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            screen = ValuesScreen()
            with patch("unit_translator.adapters.tui.app.curses.echo"), patch(
                "unit_translator.adapters.tui.app.curses.noecho"
            ):
                _run_usage(screen, state, (1, 2, 3, 4))
            output = "\n".join(screen.lines.values())
            self.assertIn("Token 用量配比（高级）", output)
            self.assertIn("用于输入/输出/缓存配比", output)

    def test_channel_edit_preserves_non_default_metadata(self) -> None:
        class ValuesScreen(_RecordingScreen):
            def __init__(self) -> None:
                super().__init__(height=24, width=100)
                self.values = iter(["x", "p", "m", "1", "2", "3", "2026-01-01", "s", "v"])

            def getstr(self, *args: object) -> bytes:
                return next(self.values).encode()

        profile = TokenPriceProfile(
            "x", "1", "2", "3", provider="p", model="m", currency="EUR", unit="1K tokens",
            effective_at="2026-01-01", source="s", version="v",
        )
        with patch("unit_translator.adapters.tui.app.curses.echo"), patch(
            "unit_translator.adapters.tui.app.curses.noecho"
        ):
            updated = _edit_channel(ValuesScreen(), profile)
        self.assertEqual(updated.currency, "EUR")
        self.assertEqual(updated.unit, "1K tokens")


class _RecordingScreen:
    def __init__(self, height: int = 24, width: int = 80) -> None:
        self.height = height
        self.width = width
        self.lines: dict[int, str] = {}

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def erase(self) -> None:
        self.lines.clear()

    def addnstr(self, row: int, col: int, text: str, length: int, attr: int = 0) -> None:
        line = self.lines.get(row, " " * self.width)
        visible = text[:length]
        line = line[:col] + visible + line[col + len(visible) :]
        self.lines[row] = line

    def refresh(self) -> None:
        return


class CursesChannelViewTests(unittest.TestCase):
    def test_channel_page_shows_save_status_and_selection_position(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            screen = _RecordingScreen(height=24, width=80)
            _draw_channels(screen, state, 0, (1, 2, 3, 4))
            self.assertIn("已保存", screen.lines[0])
            self.assertIn("选中渠道详情 · 1/4", "\n".join(screen.lines.values()))

            state.input_price = "6"
            screen = _RecordingScreen(height=24, width=80)
            _draw_channels(screen, state, 0, (1, 2, 3, 4))
            self.assertIn("未保存", screen.lines[0])

    def test_help_screen_explains_page_actions(self) -> None:
        class HelpScreen(_RecordingScreen):
            def getch(self) -> int:
                return ord("x")

        screen = HelpScreen(height=24, width=80)
        curses_tui._show_help(screen, "channels", (1, 2, 3, 4))
        output = "\n".join(screen.lines.values())
        self.assertIn("渠道管理快捷键", output)
        self.assertIn("n 新建", output)
        self.assertIn("只读", output)
        self.assertIn("按任意键返回", output)

    def test_focused_calculator_footer_explains_how_to_release_focus(self) -> None:
        session = CalculatorSession()
        session.focused = True
        with tempfile.TemporaryDirectory() as directory:
            screen = _RecordingScreen(height=24, width=80)
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            _draw_channels(screen, state, 0, (1, 2, 3, 4), session)
            self.assertIn("F6 释放焦点", screen.lines[23])

    def test_channel_home_and_end_jump_to_first_and_last_profile(self) -> None:
        class KeyScreen(_RecordingScreen):
            def __init__(self) -> None:
                super().__init__(height=24, width=80)
                self.keys = [curses.KEY_END, ord("q")]

            def getch(self) -> int:
                return self.keys.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            screen = KeyScreen()
            _run_channels(screen, state, (1, 2, 3, 4))
            output = "\n".join(screen.lines.values())
            self.assertIn("> DeepSeek V4 Pro", output)
            self.assertIn("选中渠道详情 · 4/4", output)

    def test_channel_copy_creates_unique_profile_without_mutating_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            profiles = state.settings.comparison_profiles
            selected = curses_tui._add_channel(
                _RecordingScreen(), state, profiles, 0, copying=True
            )
            copied = state.settings.comparison_profiles[selected]
            self.assertEqual(copied.name, "DeepSeek V4 Flash 谷 副本")
            self.assertEqual(copied.provider, profiles[0].provider)
            self.assertEqual(copied.model, profiles[0].model)
            self.assertEqual(profiles[0].name, "DeepSeek V4 Flash 谷")

            profiles = state.settings.comparison_profiles
            selected = curses_tui._add_channel(
                _RecordingScreen(), state, profiles, 0, copying=True
            )
            self.assertEqual(
                state.settings.comparison_profiles[selected].name,
                "DeepSeek V4 Flash 谷 副本 2",
            )

    def test_channel_filter_shows_matching_profiles_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            screen = _RecordingScreen(height=24, width=100)
            _draw_channels(screen, state, 0, (1, 2, 3, 4), filter_text="Flash")
            output = "\n".join(screen.lines.values())
            self.assertIn("筛选“Flash”", output)
            self.assertIn("2/4 个可编辑渠道", output)
            self.assertGreaterEqual(output.count("DeepSeek V4 Flash"), 2)
            self.assertNotIn("DeepSeek V4 Pro", output)

    def test_channel_filter_shortcut_accepts_query_and_can_clear(self) -> None:
        class FilterScreen(_RecordingScreen):
            def __init__(self) -> None:
                super().__init__(height=24, width=100)
                self.keys = [ord("/"), ord("/"), ord("q")]
                self.values = iter([b"Pro", b""])

            def getch(self) -> int:
                return self.keys.pop(0)

            def getstr(self, *args: object) -> bytes:
                return next(self.values)

        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            screen = FilterScreen()
            with patch("unit_translator.adapters.tui.app.curses.echo"), patch(
                "unit_translator.adapters.tui.app.curses.noecho"
            ):
                _run_channels(screen, state, (1, 2, 3, 4))
            output = "\n".join(screen.lines.values())
            self.assertNotIn("筛选“Pro”", output)
            self.assertIn("4 个可编辑渠道", output)
            self.assertIn("DeepSeek V4 Flash", output)

    def test_wide_channel_table_includes_baseline_and_cost_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            screen = _RecordingScreen(height=24, width=140)
            _draw_channels(screen, state, 0, (1, 2, 3, 4), CalculatorSession())
            output = "\n".join(screen.lines.values())
            self.assertIn("当前 CNY", output)
            self.assertIn("相对 ChatGPT", output)
            self.assertIn("· ChatGPT 中转", output)
            self.assertIn("4.5068 元", output)
            self.assertIn("3.8879x", output)
            self.assertIn("精确成本 17.5221554 元", output)
            self.assertNotIn("> ChatGPT 中转", output)

    def test_narrow_channel_table_puts_cost_in_selected_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            screen = _RecordingScreen(height=24, width=80)
            _draw_channels(screen, state, 0, (1, 2, 3, 4), CalculatorSession())
            output = "\n".join(screen.lines.values())
            self.assertNotIn("当前 CNY", screen.lines[3])
            self.assertIn("当前 CNY 17.5221554 元", output)
            self.assertIn("相对 ChatGPT 3.88794668x", output)

    def test_channel_table_uses_current_chatgpt_price_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            state.input_price = "10"
            expected_yuan = state.calculate().comparison[0].yuan
            screen = _RecordingScreen(height=24, width=140)
            _draw_channels(screen, state, 0, (1, 2, 3, 4), CalculatorSession())
            self.assertIn("10", screen.lines[4])
            self.assertIn(curses_tui._compact_metric(expected_yuan), screen.lines[4])

    def test_channel_table_keeps_baseline_when_no_editable_channels_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            state.settings = replace(state.settings, comparison_profiles=())
            screen = _RecordingScreen(height=24, width=140)
            _draw_channels(screen, state, 0, (1, 2, 3, 4), CalculatorSession())
            output = "\n".join(screen.lines.values())
            self.assertIn("· ChatGPT 中转", output)
            self.assertIn("暂无可管理渠道，按 n 新建", output)

    def test_channel_table_reports_invalid_main_values_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            state.value = "-1"
            state.input_price = "10"
            screen = _RecordingScreen(height=24, width=140)
            _draw_channels(screen, state, 0, (1, 2, 3, 4), CalculatorSession())
            output = "\n".join(screen.lines.values())
            self.assertIn("不能小于 0", output)
            self.assertIn("相对 ChatGPT", output)
            self.assertIn("10", screen.lines[4])
            self.assertIn("--", screen.lines[4])

    def test_small_channel_window_shows_size_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            screen = _RecordingScreen(height=19, width=72)
            _draw_channels(screen, state, 0, (1, 2, 3, 4))
            self.assertIn("终端窗口至少需要", "\n".join(screen.lines.values()))

    def test_channel_table_includes_all_core_pricing_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            screen = _RecordingScreen()
            _draw_channels(screen, state, 0, (1, 2, 3, 4))
            output = "\n".join(screen.lines.values())
            self.assertIn("输入价", output)
            self.assertIn("输出价", output)
            self.assertIn("缓存价", output)
            self.assertIn("0.22", output)
            self.assertIn("0.66", output)
            self.assertIn("0.007", output)
            self.assertIn("DeepSeek Models & Pricing", output)

    def test_selected_channel_metadata_changes_with_selection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            state.settings = replace(
                state.settings,
                comparison_profiles=(
                    TokenPriceProfile(
                        "First", "1", "2", "0.1",
                        provider="one", model="m1", source="source-one", version="v1",
                    ),
                    TokenPriceProfile(
                        "Second", "3", "4", "0.2",
                        provider="two", model="m2", source="source-two", version="v2",
                    ),
                ),
            )
            first = _RecordingScreen()
            _draw_channels(first, state, 0, (1, 2, 3, 4))
            second = _RecordingScreen()
            _draw_channels(second, state, 1, (1, 2, 3, 4))
            self.assertIn("source-one", "\n".join(first.lines.values()))
            self.assertIn("source-two", "\n".join(second.lines.values()))

    def test_channel_exit_confirms_unsaved_changes(self) -> None:
        class ConfirmingScreen(_RecordingScreen):
            def __init__(self) -> None:
                super().__init__()
                self.keys = [ord("q"), ord("n"), ord("q"), ord("y")]

            def getch(self) -> int:
                return self.keys.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            state = CursesTuiState.from_document(
                load_settings_document(Path(directory) / "settings.toml")
            )
            state.settings = replace(state.settings, comparison_profiles=())
            _run_channels(ConfirmingScreen(), state, (1, 2, 3, 4))
            self.assertTrue(state.is_dirty())


class CursesTuiEntryPointTests(unittest.TestCase):
    def test_interactive_entry_uses_ncurses_runner(self) -> None:
        with patch("unit_translator.adapters.tui.app.run_curses_tui", return_value=0) as runner:
            self.assertEqual(launch_tui("settings.toml"), 0)
        runner.assert_called_once_with("settings.toml")


if __name__ == "__main__":
    unittest.main()
