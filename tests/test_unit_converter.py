import curses
import unittest
from decimal import Decimal
from unittest.mock import patch

from unit_converter import (
    TuiState,
    _curses_main,
    _result_for,
    fen_from_multiplier,
    fen_from_token_cost,
    format_decimal,
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

    def test_tui_state_mode_and_result(self) -> None:
        state = TuiState()
        self.assertEqual(
            _result_for(state),
            ("5 分/刀", "0.05 元/刀", "4.50678902 元", ""),
        )
        state.toggle_mode()
        self.assertEqual(state.value, "5")
        self.assertEqual(
            _result_for(state),
            ("0.05x", "0.05 元/刀", "4.50678902 元", ""),
        )
        state.toggle_mode()
        self.assertEqual(state.mode, "token_cost")
        self.assertEqual(
            _result_for(state),
            ("0.05547187x", "5.54718668 分/刀", "5 元", ""),
        )

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

        self.assertEqual(state.active_field, 4)
        self.assertTrue(state.replace_on_type)


if __name__ == "__main__":
    unittest.main()
