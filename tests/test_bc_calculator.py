import shutil
import unittest

import curses

from unit_translator.adapters.tui.bc_calculator import (
    BcCalculatorError,
    BcEvaluator,
    BcUnavailableError,
    BcTimeoutError,
    CalculatorSession,
    HistoryEntry,
    MAX_EXPRESSION_LENGTH,
)


class _FakeTransport:
    def __init__(self) -> None:
        self.started = 0
        self.closed = 0
        self.values: list[str] = []

    def start(self) -> None:
        self.started += 1

    def evaluate(self, expression: str) -> str:
        self.values.append(expression)
        if expression == "bad":
            raise BcCalculatorError("语法错误")
        return {"1+2": "3", "4/2": "2"}.get(expression, expression)

    def close(self) -> None:
        self.closed += 1


class CalculatorSessionTests(unittest.TestCase):
    def _session(self) -> tuple[CalculatorSession, _FakeTransport]:
        transport = _FakeTransport()
        session = CalculatorSession(BcEvaluator(transport=transport))
        session.start()
        session.focus()
        return session, transport

    def test_submit_records_success_and_error_history(self) -> None:
        session, transport = self._session()
        session.insert("1+2")
        entry = session.submit()
        self.assertIsInstance(entry, HistoryEntry)
        self.assertEqual(session.result, "3")
        session.expression = "bad"
        session.cursor = 3
        failed = session.submit()
        self.assertIsNotNone(failed)
        self.assertFalse(failed.success)
        self.assertEqual(len(session.history), 2)
        self.assertEqual(transport.values, ["1+2", "bad"])

    def test_history_navigation_restores_draft(self) -> None:
        session, _ = self._session()
        session.insert("1+2")
        session.submit()
        session.expression = "draft"
        session.cursor = len(session.expression)
        session.history_up()
        self.assertEqual(session.expression, "1+2")
        session.history_down()
        self.assertEqual(session.expression, "draft")

    def test_history_is_capped_and_keyboard_editing_works(self) -> None:
        session, _ = self._session()
        for index in range(21):
            session.expression = str(index)
            session.cursor = len(session.expression)
            session.submit()
        self.assertEqual(len(session.history), 20)
        self.assertEqual(session.history[0].expression, "1")
        session.expression = "12"
        session.cursor = 2
        session.handle_key(curses.KEY_LEFT)
        session.handle_key(curses.KEY_BACKSPACE)
        self.assertEqual(session.expression, "2")

    def test_input_limits_and_focus_toggle(self) -> None:
        session, _ = self._session()
        session.insert("x" * (MAX_EXPRESSION_LENGTH + 1))
        self.assertEqual(len(session.expression), 0)
        self.assertTrue(session.error)
        self.assertEqual(session.handle_key(getattr(curses, "KEY_F6", 274)), "blur")
        self.assertFalse(session.focused)

    def test_close_closes_injected_transport(self) -> None:
        session, transport = self._session()
        session.close()
        self.assertEqual(transport.closed, 1)

    def test_missing_bc_is_reported_without_crashing_session(self) -> None:
        session = CalculatorSession(BcEvaluator(command=("unit-translator-bc-missing",)))
        session.start()
        session.focus()
        session.expression = "1+1"
        session.cursor = 3
        entry = session.submit()
        self.assertFalse(entry.success)
        self.assertIn("bc", session.error)
        session.close()

    def test_evaluator_errors_are_kept_in_history(self) -> None:
        class TimeoutTransport(_FakeTransport):
            def evaluate(self, expression: str) -> str:
                raise BcTimeoutError("bc 计算超时")

        session = CalculatorSession(BcEvaluator(transport=TimeoutTransport()))
        session.start()
        session.focus()
        session.expression = "while(1)1"
        session.cursor = len(session.expression)
        entry = session.submit()
        self.assertFalse(entry.success)
        self.assertEqual(entry.error, "bc 计算超时")


@unittest.skipUnless(shutil.which("bc"), "bc is not installed")
class BcEvaluatorIntegrationTests(unittest.TestCase):
    def test_persistent_process_keeps_scale_and_variables(self) -> None:
        evaluator = BcEvaluator(timeout=2)
        try:
            evaluator.start()
            self.assertEqual(evaluator.evaluate("scale=5;1/3"), ".33333")
            self.assertEqual(evaluator.evaluate("x=4"), "")
            self.assertEqual(evaluator.evaluate("x^2"), "16")
        finally:
            evaluator.close()


if __name__ == "__main__":
    unittest.main()
