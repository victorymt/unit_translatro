import tempfile
import unittest
from pathlib import Path

from textual.containers import VerticalScroll
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from settings_store import load_settings_document
from tui_app import ChannelEditorScreen, ConfirmScreen, UnitTranslatorApp


class TuiAppTests(unittest.IsolatedAsyncioTestCase):
    def _app_for(self, directory: str) -> tuple[UnitTranslatorApp, Path]:
        path = Path(directory) / "settings.toml"
        return UnitTranslatorApp(load_settings_document(path)), path

    async def test_calculator_reacts_to_value_and_mode_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self._app_for(directory)
            async with app.run_test(size=(120, 40)) as pilot:
                app.query_one("#calc-value", Input).value = "0.1"
                await pilot.pause()
                self.assertEqual(
                    str(app.query_one("#result-multiplier", Static).content), "0.1x"
                )
                self.assertEqual(
                    str(app.query_one("#result-fen", Static).content), "10 分/刀"
                )
                self.assertIn(
                    "9.01357804",
                    str(app.query_one("#result-token-cost", Static).content),
                )

    async def test_mode_change_resets_value_to_the_new_unit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self._app_for(directory)
            async with app.run_test(size=(120, 40)) as pilot:
                app.query_one("#calc-mode", Select).value = "token_cost"
                await pilot.pause()
                self.assertEqual(app.query_one("#calc-value", Input).value, "5")
                self.assertEqual(
                    str(app.query_one("#result-token-cost", Static).content), "5 元"
                )

    async def test_price_comparison_tab_shows_all_channels_on_narrow_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self._app_for(directory)
            async with app.run_test(size=(80, 24)) as pilot:
                app.query_one("#main-tabs", TabbedContent).active = "comparison"
                await pilot.pause()
                table = app.query_one("#comparison-table", DataTable)
                self.assertEqual(table.row_count, len(app.settings.comparison_profiles) + 1)
                self.assertLessEqual(table.region.bottom, app.size.height)
                self.assertIn("DeepSeek", str(table.get_row_at(1)[0]))
                original_relative_cost = str(table.get_row_at(1)[3])
                app.query_one("#calc-value", Input).value = "0.1"
                await pilot.pause()
                self.assertNotEqual(str(table.get_row_at(1)[3]), original_relative_cost)

    async def test_advanced_price_settings_are_visible_without_extra_interaction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self._app_for(directory)
            async with app.run_test(size=(120, 40)) as pilot:
                grid = app.query_one("#pricing-grid")
                self.assertGreater(grid.region.width, 0)
                for input_id in (
                    "balance-per-yuan",
                    "usd-cny-rate",
                    "chatgpt-input-price",
                    "chatgpt-output-price",
                    "chatgpt-cached-price",
                ):
                    self.assertEqual(len(app.query(f"#{input_id}")), 1)

    async def test_channel_crud_uses_editor_and_delete_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self._app_for(directory)
            original_count = len(app.settings.comparison_profiles)
            async with app.run_test(size=(120, 40)) as pilot:
                app.query_one("#main-tabs", TabbedContent).active = "channels"
                await pilot.pause()
                await pilot.click("#new-channel")
                await pilot.pause()
                self.assertIsInstance(app.screen, ChannelEditorScreen)
                editor = app.screen
                values = {
                    "channel-name": "Custom channel",
                    "channel-provider": "Example",
                    "channel-model": "demo-v1",
                    "channel-input-price": "1",
                    "channel-output-price": "2",
                    "channel-cached-price": "0.5",
                    "channel-effective-at": "2026-08-28",
                    "channel-source": "pricing page",
                    "channel-version": "v1",
                }
                for input_id, value in values.items():
                    editor.query_one(f"#{input_id}", Input).value = value
                await pilot.click("#channel-save")
                await pilot.pause()
                self.assertEqual(len(app.settings.comparison_profiles), original_count + 1)
                self.assertEqual(app.settings.comparison_profiles[-1].name, "Custom channel")

                await pilot.click("#edit-channel")
                await pilot.pause()
                self.assertIsInstance(app.screen, ChannelEditorScreen)
                app.screen.query_one("#channel-name", Input).value = "Edited channel"
                await pilot.click("#channel-save")
                await pilot.pause()
                self.assertEqual(app.settings.comparison_profiles[-1].name, "Edited channel")

                await pilot.click("#delete-channel")
                await pilot.pause()
                self.assertIsInstance(app.screen, ConfirmScreen)
                await pilot.click("#confirm-accept")
                await pilot.pause()
                self.assertEqual(len(app.settings.comparison_profiles), original_count)

    async def test_channel_editor_keeps_invalid_values_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self._app_for(directory)
            async with app.run_test(size=(100, 36)) as pilot:
                app.query_one("#main-tabs", TabbedContent).active = "channels"
                await pilot.pause()
                await pilot.click("#new-channel")
                await pilot.pause()
                await pilot.click("#channel-save")
                await pilot.pause()
                self.assertIsInstance(app.screen, ChannelEditorScreen)
                error = app.screen.query_one("#channel-editor-error", Static)
                self.assertIn("名称", str(error.content))

    async def test_channel_editor_scrolls_fields_and_keeps_actions_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self._app_for(directory)
            async with app.run_test(size=(80, 24)) as pilot:
                app.query_one("#main-tabs", TabbedContent).active = "channels"
                await pilot.pause()
                await pilot.click("#new-channel")
                await pilot.pause()

                editor = app.screen
                fields = editor.query_one("#channel-editor-fields", VerticalScroll)
                save_button = editor.query_one("#channel-save", Button)
                self.assertGreater(fields.max_scroll_y, 0)
                self.assertLessEqual(save_button.region.bottom, app.size.height)

                for _ in range(8):
                    await pilot.press("tab")
                await pilot.pause()
                self.assertGreater(fields.scroll_y, 0)

    async def test_narrow_channels_keep_actions_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self._app_for(directory)
            async with app.run_test(size=(80, 24)) as pilot:
                app.query_one("#main-tabs", TabbedContent).active = "channels"
                await pilot.pause()
                self.assertTrue(app.query_one("#channels", TabPane).has_class("compact"))
                for button_id in ("#edit-channel", "#delete-channel"):
                    self.assertLessEqual(
                        app.query_one(button_id, Button).region.bottom,
                        app.size.height,
                    )

    async def test_save_and_discard_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, path = self._app_for(directory)
            async with app.run_test(size=(120, 40)) as pilot:
                ratio = app.query_one("#balance-per-yuan", Input)
                ratio.value = "1.5"
                await pilot.pause()
                self.assertTrue(app._is_dirty())
                self.assertFalse(path.exists())

                await pilot.click("#discard-settings")
                await pilot.pause()
                self.assertIsInstance(app.screen, ConfirmScreen)
                await pilot.click("#confirm-accept")
                await pilot.pause()
                self.assertEqual(ratio.value, "1")
                self.assertFalse(app._is_dirty())
                self.assertFalse(path.exists())

                ratio.value = "1.5"
                await pilot.pause()
                await pilot.click("#save-settings")
                await pilot.pause()
                self.assertTrue(path.exists())
                self.assertFalse(app._is_dirty())
                self.assertEqual(load_settings_document(path).settings.balance_per_yuan, "1.5")

    async def test_unsaved_exit_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self._app_for(directory)
            async with app.run_test(size=(100, 36)) as pilot:
                app.query_one("#usd-cny-rate", Input).value = "7.1"
                await pilot.pause()
                app.action_quit()
                await pilot.pause()
                self.assertIsInstance(app.screen, ConfirmScreen)
                await pilot.click("#confirm-cancel")
                await pilot.pause()
                self.assertNotIsInstance(app.screen, ConfirmScreen)

    async def test_save_rejects_invalid_persistent_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, path = self._app_for(directory)
            async with app.run_test(size=(100, 36)) as pilot:
                app.query_one("#usd-cny-rate", Input).value = "0"
                await pilot.pause()
                await pilot.click("#save-settings")
                await pilot.pause()
                self.assertFalse(path.exists())
                self.assertTrue(app._is_dirty())

    async def test_narrow_terminal_uses_stacked_calculator_layout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app, _ = self._app_for(directory)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                self.assertTrue(app.query_one("#calculator-workspace").has_class("compact"))
                self.assertEqual(
                    str(app.query_one("#result-multiplier", Static).content), "0.05x"
                )
                self.assertIn(
                    "账号成本 5 分/刀",
                    str(app.query_one("#compact-result", Static).content),
                )
                self.assertIn(
                    "1 亿成本 4.50678902 元",
                    str(app.query_one("#compact-result", Static).content),
                )
                app.query_one("#calc-value", Input).value = "-1"
                await pilot.pause()
                self.assertIn(
                    "不能小于 0",
                    str(app.query_one("#compact-error", Static).content),
                )


if __name__ == "__main__":
    unittest.main()
