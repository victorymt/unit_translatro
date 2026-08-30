import unittest
import curses
from contextlib import redirect_stdout
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from converter_core import TokenPriceProfile, channel_cost_comparison
from unit_converter import (
    _display_width,
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

    def test_decimal_formatting_handles_large_values(self) -> None:
        self.assertEqual(format_decimal(Decimal("1e100")), "1e+100")
        self.assertEqual(format_decimal(Decimal("1.23456789e1000")), "1.23456789e+1000")

    def test_cli_handles_large_values_without_a_traceback(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["--multiplier", "1e100"])
        self.assertEqual(exit_code, 0)
        self.assertIn("倍率: 1e+100x", output.getvalue())

    def test_one_hundred_million_token_cost(self) -> None:
        self.assertEqual(format_decimal(token_cost_yuan(fen_per_dollar="5")), "4.50678902")

    def test_fen_from_one_hundred_million_token_cost(self) -> None:
        fen = fen_from_token_cost("5")
        self.assertEqual(format_decimal(fen), "5.54718668")
        self.assertEqual(format_decimal(token_cost_yuan(fen)), "5")

    def test_cli_token_cost_describes_user_actual_spend(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["--token-cost", "5"])
        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("固定用户自有 1 亿混合 Token 实际支出", text)
        self.assertIn("用户自有 1 亿混合 Token 实际支出: 5 元", text)
        self.assertIn("Token 用量配比（已按比例归一化到 1 亿 Token）", text)

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
        self.assertEqual(format_decimal(token_cost_yuan("5", token_count="1000000")), "0.04506789")

    def test_channel_comparison_uses_default_profiles_only_when_omitted(self) -> None:
        default_rows = channel_cost_comparison(token_cost_yuan("5"), "7.2")
        self.assertEqual(len(default_rows), 5)
        empty_rows = channel_cost_comparison(token_cost_yuan("5"), "7.2", profiles=())
        self.assertEqual([row.name for row in empty_rows], ["ChatGPT 中转"])

    def test_channel_comparison_with_custom_profile(self) -> None:
        profile = TokenPriceProfile("Custom", "1", "2", "0.5", provider="test")
        rows = channel_cost_comparison(token_cost_yuan("5"), "7.2", profiles=(profile,))
        self.assertEqual([row.name for row in rows], ["ChatGPT 中转", "Custom"])
        self.assertEqual(rows[1].provider, "test")

    def test_cli_prints_channel_comparison(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["--multiplier", "0.05"])
        self.assertEqual(exit_code, 0)
        text = output.getvalue()
        self.assertIn("换算口径: 固定中转站倍率", text)
        self.assertIn("ChatGPT 官方单价（输入/输出/缓存）: 5/30/0.5", text)
        self.assertIn("Token 用量配比（当前总量 100000000 Token）", text)
        self.assertIn("DeepSeek 美元汇率: 7.2 元/USD", text)
        self.assertIn("相对成本倍数", text)
        self.assertIn("DeepSeek V4 Flash 谷", text)
        self.assertIn("$2.43363269", text)
        self.assertIn("3.88794668x", text)

    def test_cli_rejects_invalid_exchange_rate(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            exit_code = main(["--fen", "5", "--usd-cny-rate", "0"])
        self.assertEqual(exit_code, 2)
        self.assertIn("美元兑人民币汇率必须大于 0", output.getvalue())

    def test_serve_rejects_conversion_and_batch_arguments(self) -> None:
        with self.assertRaises(SystemExit) as context:
            main(["--serve", "--multiplier", "0.05"])
        self.assertEqual(context.exception.code, 2)
        with self.assertRaises(SystemExit) as context:
            main(["--serve", "--input-file", "requests.jsonl"])
        self.assertEqual(context.exception.code, 2)

    def test_interactive_mode_passes_raw_config_path_to_ncurses_launcher(self) -> None:
        with patch("unit_converter.launch_tui", return_value=0) as launcher:
            self.assertEqual(main(["--config", "missing.toml"]), 0)
        launcher.assert_called_once_with("missing.toml")

    def test_interactive_mode_reports_ncurses_startup_errors(self) -> None:
        with patch("unit_converter.launch_tui", side_effect=curses.error("setupterm failed")):
            with self.assertRaises(SystemExit) as context:
                main([])
        self.assertEqual(context.exception.code, 2)

    def test_display_width_handles_wide_characters(self) -> None:
        self.assertEqual(_display_width("DeepSeek 渠道"), 13)


if __name__ == "__main__":
    unittest.main()
