import unittest
from decimal import Decimal

from unit_converter import (
    TuiState,
    _result_for,
    fen_from_multiplier,
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
        self.assertEqual(token_cost_yuan("5", "2"), Decimal("10"))
        self.assertEqual(token_cost_yuan("3.5", "0.15"), Decimal("0.525"))

    def test_custom_token_count(self) -> None:
        self.assertEqual(token_cost_yuan("5", "2", "1000000"), Decimal("0.10"))

    def test_tui_state_mode_and_result(self) -> None:
        state = TuiState()
        self.assertEqual(
            _result_for(state), ("5 分/刀", "0.05 元/刀", "5 元", "")
        )
        state.toggle_mode()
        self.assertEqual(state.value, "5")
        self.assertEqual(_result_for(state), ("0.05x", "0.05 元/刀", "5 元", ""))

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


if __name__ == "__main__":
    unittest.main()
