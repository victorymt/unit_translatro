import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from curses_tui import (
    CursesTuiState,
    _draw_channels,
    _draw_main,
    _edit_channel,
    _run_channels,
    display_width,
)
from converter_core import TokenPriceProfile
from settings_store import load_settings_document
from unit_converter import launch_tui


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
            self.assertIn("配置文件无法保存", screen.lines[14])

    def test_minimum_main_window_keeps_footer_below_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            screen = _RecordingScreen(height=20, width=72)
            _draw_main(screen, state, (1, 2, 3, 4))
            self.assertNotIn("Tab/方向键", screen.lines.get(18, ""))
            self.assertIn("Tab/方向键", screen.lines[19])

    def test_channel_edit_can_be_cancelled_with_escape(self) -> None:
        class EscapeScreen(_RecordingScreen):
            def getstr(self, *args: object) -> bytes:
                return b"\x1b"

        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory)
            profile = state.settings.comparison_profiles[0]
            with patch("curses_tui.curses.echo"), patch("curses_tui.curses.noecho"):
                self.assertIsNone(_edit_channel(EscapeScreen(), profile))


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
        self.lines[row] = text[:length]

    def refresh(self) -> None:
        return


class CursesChannelViewTests(unittest.TestCase):
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
        with patch("curses_tui.run_curses_tui", return_value=0) as runner:
            self.assertEqual(launch_tui("settings.toml"), 0)
        runner.assert_called_once_with("settings.toml")


if __name__ == "__main__":
    unittest.main()
