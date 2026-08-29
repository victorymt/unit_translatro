import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from curses_tui import CursesTuiState, display_width
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


class CursesTuiEntryPointTests(unittest.TestCase):
    def test_interactive_entry_uses_ncurses_runner(self) -> None:
        with patch("curses_tui.run_curses_tui", return_value=0) as runner:
            self.assertEqual(launch_tui("settings.toml"), 0)
        runner.assert_called_once_with("settings.toml")


if __name__ == "__main__":
    unittest.main()
