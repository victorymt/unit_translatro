import unittest

from app_config import Settings
from converter_core import TokenPriceProfile, TokenUsage
from unit_translator.adapters.tui.calculator import CalculatorInputs, calculate_display
from unit_translator.application import ConversionService


class TuiCalculatorTests(unittest.TestCase):
    def test_calculator_inputs_build_the_configured_request(self) -> None:
        settings = Settings(
            balance_per_yuan="1.5",
            chatgpt_profile=TokenPriceProfile("Relay", "1", "2", "0.5"),
            usage=TokenUsage("1", "2", "3"),
            usd_cny_rate="6.8",
            comparison_profiles=(TokenPriceProfile("Other", "1", "1", "1"),),
        )
        inputs = CalculatorInputs(
            mode="multiplier",
            value="0.15",
            balance_per_yuan="2",
            input_price="3",
            output_price="4",
            cached_price="0.2",
            usd_cny_rate="7",
        )

        request = inputs.to_request(settings)

        self.assertEqual(request.mode, "multiplier")
        self.assertEqual(str(request.balance_per_yuan), "2")
        self.assertEqual(str(request.chatgpt_profile.input_price), "3")
        self.assertEqual(str(request.usage.total_tokens), "6")
        self.assertEqual(str(request.usd_cny_rate), "7")

    def test_display_formats_the_application_result(self) -> None:
        settings = Settings(
            usage=TokenUsage("1000000", "0", "0"),
            comparison_profiles=(TokenPriceProfile("Other", "1", "1", "1"),),
        )
        inputs = CalculatorInputs(
            mode="fen",
            value="5",
            balance_per_yuan="1",
            input_price="2",
            output_price="3",
            cached_price="0.1",
            usd_cny_rate="7",
        )

        display = calculate_display(inputs, settings, ConversionService())

        self.assertEqual(display.multiplier, "0.05x")
        self.assertEqual(display.fen_per_dollar, "5 分/刀")
        self.assertEqual(display.token_cost_yuan, "0.1 元")
        self.assertEqual(display.comparison[0].relative_cost, "基准")
        self.assertEqual(display.comparison[1].name, "Other")


if __name__ == "__main__":
    unittest.main()
