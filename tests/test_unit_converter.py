import curses
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from unit_converter import (
    TuiState,
    _curses_main,
    _display_width,
    _draw_tui,
    _result_for,
    channel_cost_comparison,
    fen_from_multiplier,
    fen_from_token_cost,
    format_decimal,
    main,
    multiplier_from_fen,
    token_cost_yuan,
)


class ConversionTests(unittest.TestCase):
    def test_multiplier_to_fen_at_default_ratio(self) -> None:
        self.assertEqual(fen_from_multiplier("0.05"), Decimal("5.00"))

    def test_fen_to_multiplier_at_default_ratio(self) -> None:
        self.assertEqual(multiplier_from_fen("5"), Decimal("0.05"))

    def test_custom_recharge_ratio(self) -> None:
        self.assertEqual(fen_from_multiplier("0.12", "1.2"), Decimal("10"))
        self.assertEqual(multiplier_from_fen("10", "1.2"), Decimal("0.12"))

    def test_round_trip(self) -> None:
        multiplier = Decimal("0.0375")
        fen = fen_from_multiplier(multiplier, "1.25")
        self.assertEqual(multiplier_from_fen(fen, "1.25"), multiplier)

    def test_zero_cost_is_valid(self) -> None:
        self.assertEqual(fen_from_multiplier("0"), Decimal("0"))
        self.assertEqual(multiplier_from_fen("0"), Decimal("0"))

    def test_invalid_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "倍率不能小于"):
            fen_from_multiplier("-1")
        with self.assertRaisesRegex(ValueError, "充值比例必须大于"):
            multiplier_from_fen("5", "0")
        with self.assertRaisesRegex(ValueError, "有效数字"):
            fen_from_multiplier("abc")

    def test_decimal_formatting(self) -> None:
        self.assertEqual(format_decimal(Decimal("5.00000000")), "5")
        self.assertEqual(format_decimal(Decimal("0.0123456789")), "0.01234568")

    def test_one_hundred_million_token_cost(self) -> None:
        cost = token_cost_yuan(fen_per_dollar="5")
        self.assertEqual(format_decimal(cost), "4.50678902")

    def test_fen_from_one_hundred_million_token_cost(self) -> None:
        fen = fen_from_token_cost("5")
        self.assertEqual(format_decimal(fen), "5.54718668")
        self.assertEqual(format_decimal(token_cost_yuan(fen)), "5")

    def test_token_cost_requires_a_nonzero_official_price(self) -> None:
        with self.assertRaisesRegex(ValueError, "官方价不能全部为 0"):
            fen_from_token_cost(
                "5",
                "0",
                output_price_per_million="0",
                cached_price_per_million="0",
            )

    def test_equal_category_prices_match_flat_token_price(self) -> None:
        self.assertEqual(
            token_cost_yuan(
                "5",
                "2",
                output_price_per_million="2",
                cached_price_per_million="2",
            ),
            Decimal("10"),
        )

    def test_custom_token_count(self) -> None:
        cost = token_cost_yuan("5", token_count="1000000")
        self.assertEqual(format_decimal(cost), "0.04506789")

    def test_deepseek_official_cost_comparison(self) -> None:
        rows = channel_cost_comparison(token_cost_yuan("5"), "7.2")
        self.assertEqual(
            [row.name for row in rows],
            [
                "ChatGPT 中转",
                "DeepSeek V4 Flash 谷",
                "DeepSeek V4 Flash 峰",
                "DeepSeek V4 Pro 谷",
                "DeepSeek V4 Pro 峰",
            ],
        )
        self.assertEqual(
            [format_decimal(row.usd) for row in rows[1:] if row.usd is not None],
            ["2.43363269", "4.86726539", "7.39322063", "14.78644126"],
        )
        self.assertEqual(
            [format_decimal(row.yuan) for row in rows[1:]],
            ["17.5221554", "35.04431079", "53.23118854", "106.46237709"],
        )
        self.assertEqual(
            [
                format_decimal(row.relative_to_chatgpt)
                for row in rows[1:]
                if row.relative_to_chatgpt is not None
            ],
            ["3.88794668", "7.77589336", "11.8113336", "23.62266719"],
        )

    def test_deepseek_exchange_rate_and_zero_chatgpt_cost(self) -> None:
        rows = channel_cost_comparison("0", "7")
        self.assertEqual(format_decimal(rows[1].yuan), "17.03542886")
        self.assertTrue(all(row.relative_to_chatgpt is None for row in rows[1:]))
        with self.assertRaisesRegex(ValueError, "汇率必须大于 0"):
            channel_cost_comparison("5", "0")

    def test_cli_prints_channel_comparison(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["--multiplier", "0.05"])

        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("ChatGPT 官方单价（输入/输出/缓存）: 5/30/0.5", text)
        self.assertIn("DeepSeek 美元汇率: 7.2 元/USD", text)
        self.assertIn("DeepSeek V4 Flash 谷", text)
        self.assertIn("$2.43363269", text)
        self.assertIn("3.88794668x", text)

    def test_cli_rejects_invalid_exchange_rate(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["--fen", "5", "--usd-cny-rate", "0"])

        self.assertEqual(exit_code, 2)
        self.assertIn("美元兑人民币汇率必须大于 0", output.getvalue())

    def test_tui_state_mode_and_result(self) -> None:
        state = TuiState()
        primary, secondary, cost, comparison, error = _result_for(state)
        self.assertEqual(
            (primary, secondary, cost, error),
            ("5 分/刀", "0.05 元/刀", "4.50678902 元", ""),
        )
        self.assertEqual(len(comparison), 5)
        state.toggle_mode()
        self.assertEqual(state.value, "5")
        primary, secondary, cost, comparison, error = _result_for(state)
        self.assertEqual(
            (primary, secondary, cost, error),
            ("0.05x", "0.05 元/刀", "4.50678902 元", ""),
        )
        state.toggle_mode()
        self.assertEqual(state.mode, "token_cost")
        primary, secondary, cost, comparison, error = _result_for(state)
        self.assertEqual(
            (primary, secondary, cost, error),
            ("0.05547187x", "5.54718668 分/刀", "5 元", ""),
        )
        self.assertEqual(comparison[0].yuan, Decimal("5"))

    def test_tui_numeric_editing_replaces_selected_value(self) -> None:
        state = TuiState()
        state.edit(ord("1"))
        state.edit(ord("."))
        state.edit(ord("2"))
        self.assertEqual(state.value, "1.2")
        state.select_next_field()
        state.edit(ord("2"))
        self.assertEqual(state.ratio, "2")
        state.select_next_field()
        state.edit(ord("3"))
        self.assertEqual(state.token_price, "3")
        state.select_next_field()
        state.edit(ord("4"))
        self.assertEqual(state.output_price, "4")
        state.select_next_field()
        state.edit(ord("0"))
        state.edit(ord("."))
        state.edit(ord("2"))
        self.assertEqual(state.cached_price, "0.2")
        state.select_next_field()
        state.edit(ord("7"))
        self.assertEqual(state.usd_cny_rate, "7")

    def test_tui_up_selects_previous_field(self) -> None:
        class Screen:
            def __init__(self) -> None:
                self.keys = iter((curses.KEY_UP, ord("q")))

            def keypad(self, enabled: bool) -> None:
                pass

            def getch(self) -> int:
                return next(self.keys)

        state = TuiState()
        with (
            patch("unit_converter.TuiState", return_value=state),
            patch("unit_converter._draw_tui"),
            patch("unit_converter.curses.curs_set"),
        ):
            _curses_main(Screen())

        self.assertEqual(state.active_field, 5)
        self.assertTrue(state.replace_on_type)

    def test_tui_draws_channel_comparison_in_compact_and_full_layouts(self) -> None:
        class Screen:
            def __init__(self, height: int, width: int) -> None:
                self.height = height
                self.width = width
                self.text: list[tuple[int, int, str]] = []

            def erase(self) -> None:
                pass

            def getmaxyx(self) -> tuple[int, int]:
                return self.height, self.width

            def hline(self, y: int, x: int, character: int, count: int) -> None:
                pass

            def addnstr(
                self, y: int, x: int, text: str, count: int, attributes: int
            ) -> None:
                self.text.append((y, x, text[:count]))

            def refresh(self) -> None:
                pass

        for height, width in ((22, 60), (34, 80)):
            with self.subTest(height=height, width=width):
                screen = Screen(height, width)
                with (
                    patch("unit_converter._init_colors", return_value=(0, 0, 0)),
                    patch("unit_converter.curses.ACS_HLINE", 0, create=True),
                ):
                    _draw_tui(screen, TuiState())

                rendered = "\n".join(text for _, _, text in screen.text)
                self.assertIn("ChatGPT 中转", rendered)
                self.assertIn("DeepSeek", rendered)
                for y, x, text in screen.text:
                    self.assertTrue(0 <= y < height, (y, x, text))
                    self.assertTrue(0 <= x < width, (y, x, text))
                    self.assertLess(
                        x + _display_width(text), width, (y, x, text)
                    )
                for row in range(height):
                    spans = sorted(
                        (x, x + _display_width(text))
                        for y, x, text in screen.text
                        if y == row
                    )
                    self.assertTrue(
                        all(
                            end <= next_start
                            for (_, end), (next_start, _) in zip(
                                spans, spans[1:]
                            )
                        ),
                        (row, spans),
                    )


if __name__ == "__main__":
    unittest.main()
