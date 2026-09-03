"""Session-scoped calculator support for the ncurses TUI.

The calculator deliberately lives outside the domain conversion module.  It
keeps a single ``bc -l`` process attached to a private pseudo terminal so
that bc variables and ``scale`` survive between expressions while the TUI
remains responsive and safe to shut down.
"""

from __future__ import annotations

import curses
import os
import re
import select
import subprocess
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol


MAX_EXPRESSION_LENGTH = 256
MAX_OUTPUT_BYTES = 65536
DEFAULT_TIMEOUT = 1.0
_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


class BcCalculatorError(RuntimeError):
    """Base error raised when the bc evaluator cannot produce a result."""

    def __init__(self, message: str, *, stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


class BcUnavailableError(BcCalculatorError):
    """The bc executable or a usable PTY is unavailable."""


class BcTimeoutError(BcCalculatorError):
    """An expression exceeded the evaluator deadline."""


class BcTransport(Protocol):
    def start(self) -> None: ...

    def evaluate(self, expression: str) -> str: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class HistoryEntry:
    """One submitted expression, including failed evaluations."""

    expression: str
    stdout: str = ""
    stderr: str = ""
    success: bool = True
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.success

    @property
    def failed(self) -> bool:
        return not self.success

    @property
    def display_text(self) -> str:
        value = self.error or self.stderr or self.stdout
        value = _clean_output(value).strip()
        return value.splitlines()[-1] if value.splitlines() else "（无输出）"

    @property
    def result_text(self) -> str:
        return _clean_output(self.stdout).strip()

    @property
    def error_text(self) -> str:
        return _clean_output(self.error or self.stderr).strip()


def _clean_output(value: str) -> str:
    value = _ANSI_RE.sub("", value).replace("\r\n", "\n").replace("\r", "\n")
    return "".join(char for char in value if char in "\n\t" or ord(char) >= 32)


def _validate_expression(expression: str) -> str:
    if not expression.strip():
        raise ValueError("请输入算式")
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"算式不能超过 {MAX_EXPRESSION_LENGTH} 个字符")
    if any(ord(char) < 32 or ord(char) == 127 for char in expression):
        raise ValueError("算式不能包含换行或控制字符")
    if any(ord(char) > 126 for char in expression):
        raise ValueError("算式仅支持 ASCII 字符")
    return expression


class BcEvaluator:
    """Evaluate expressions in a persistent, PTY-backed bc process."""

    def __init__(
        self,
        command: tuple[str, ...] = ("bc", "-l", "-q"),
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
        transport: BcTransport | None = None,
    ) -> None:
        self.command = command
        self.timeout = timeout
        self.max_output_bytes = max_output_bytes
        self.transport = transport
        self._process: subprocess.Popen[bytes] | None = None
        self._master_fd: int | None = None
        self._stderr_fd: int | None = None
        self._startup_error: str | None = None

    @property
    def available(self) -> bool:
        return self.transport is not None or (
            self._process is not None and self._process.poll() is None
        )

    @property
    def startup_error(self) -> str | None:
        return self._startup_error

    def start(self) -> None:
        if self.transport is not None:
            try:
                self.transport.start()
                self._startup_error = None
            except Exception as exc:  # pragma: no cover - injected transports
                self._startup_error = str(exc)
                raise BcUnavailableError(self._startup_error) from exc
            return
        if self._process is not None and self._process.poll() is None:
            return
        self.close()
        try:
            import pty
            import termios

            master_fd, slave_fd = pty.openpty()
            attrs = termios.tcgetattr(slave_fd)
            attrs[3] &= ~termios.ECHO
            termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
            environment = os.environ.copy()
            environment.update({"TERM": "dumb", "LC_ALL": "C"})
            process = subprocess.Popen(
                self.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=subprocess.PIPE,
                close_fds=True,
                env=environment,
            )
            os.close(slave_fd)
            self._process = process
            self._master_fd = master_fd
            self._stderr_fd = process.stderr.fileno() if process.stderr else None
            if self._stderr_fd is not None:
                os.set_blocking(self._stderr_fd, False)
            self._startup_error = None
        except (FileNotFoundError, OSError, ImportError) as exc:
            try:
                os.close(locals().get("master_fd", -1))
            except OSError:
                pass
            try:
                os.close(locals().get("slave_fd", -1))
            except OSError:
                pass
            self._startup_error = f"无法启动 bc -l：{exc}"
            self._process = None
            self._master_fd = None
            self._stderr_fd = None
            raise BcUnavailableError(self._startup_error) from exc

    def _read_available(self, fd: int) -> bytes:
        try:
            return os.read(fd, 8192)
        except (BlockingIOError, OSError):
            return b""

    def evaluate(self, expression: str) -> str:
        expression = _validate_expression(expression)
        if self.transport is not None:
            try:
                return self.transport.evaluate(expression)
            except BcCalculatorError:
                raise
            except Exception as exc:
                raise BcCalculatorError(str(exc)) from exc
        try:
            self.start()
        except BcUnavailableError:
            raise
        if self._master_fd is None or self._process is None:
            raise BcUnavailableError(self._startup_error or "bc -l 不可用")
        marker = f"__UNIT_TRANSLATOR_END_{uuid.uuid4().hex}__"
        payload = f'{expression}\rprint "{marker}\\n"\r'.encode("ascii")
        try:
            os.write(self._master_fd, payload)
        except OSError as exc:
            self._restart()
            raise BcCalculatorError("bc 进程已退出") from exc

        stdout = bytearray()
        stderr = bytearray()
        deadline = time.monotonic() + self.timeout
        descriptors: list[int] = [self._master_fd]
        if self._stderr_fd is not None:
            descriptors.append(self._stderr_fd)
        found_marker = False
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                ready, _, _ = select.select(descriptors, [], [], min(0.1, remaining))
            except (OSError, ValueError):
                ready = [self._master_fd] if self._master_fd is not None else []
            for fd in ready:
                chunk = self._read_available(fd)
                if fd == self._master_fd:
                    stdout.extend(chunk)
                    if marker.encode("ascii") in stdout:
                        found_marker = True
                else:
                    stderr.extend(chunk)
                if len(stdout) + len(stderr) > self.max_output_bytes:
                    self._restart()
                    raise BcCalculatorError("bc 输出超过大小限制")
            if found_marker:
                break
            if self._process.poll() is not None:
                break

        if not found_marker:
            was_running = self._process.poll() is None
            self._restart()
            if was_running:
                raise BcTimeoutError("bc 计算超时")
            raise BcCalculatorError("bc 进程提前退出")

        if self._stderr_fd is not None:
            stderr.extend(self._read_available(self._stderr_fd))
        output = stdout.decode("utf-8", errors="replace")
        marker_index = output.find(marker)
        output = output[:marker_index]
        error = stderr.decode("utf-8", errors="replace")
        if error.strip():
            raise BcCalculatorError(
                _clean_output(error).strip(),
                stdout=_clean_output(output),
                stderr=_clean_output(error),
            )
        return _clean_output(output).strip()

    def _restart(self) -> None:
        self.close()
        try:
            self.start()
        except BcUnavailableError:
            pass

    def close(self) -> None:
        if self.transport is not None:
            try:
                self.transport.close()
            finally:
                return
        process, master_fd = self._process, self._master_fd
        self._process = None
        self._master_fd = None
        self._stderr_fd = None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=0.2)
            if process.stderr is not None:
                process.stderr.close()
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass


@dataclass
class CalculatorSession:
    """Editable calculator state shared by all TUI pages."""

    evaluator: BcEvaluator = field(default_factory=BcEvaluator)
    max_history: int = 20
    expression: str = ""
    cursor: int = 0
    focused: bool = False
    result: str = ""
    error: str = ""
    history: deque[HistoryEntry] = field(default_factory=deque)
    history_index: int | None = None
    _history_draft: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        self.history = deque(self.history, maxlen=self.max_history)

    @property
    def last_result(self) -> str:
        return self.result

    def start(self) -> None:
        try:
            self.evaluator.start()
        except BcUnavailableError as exc:
            self.error = str(exc)

    def close(self) -> None:
        self.evaluator.close()

    def focus(self) -> str:
        self.focused = True
        return "focus"

    def blur(self) -> str:
        self.focused = False
        self.history_index = None
        return "blur"

    def toggle_focus(self) -> str:
        return self.blur() if self.focused else self.focus()

    def insert(self, text: str) -> None:
        if any(ord(char) < 32 or ord(char) > 126 for char in text):
            return
        if len(self.expression) + len(text) > MAX_EXPRESSION_LENGTH:
            self.error = f"算式不能超过 {MAX_EXPRESSION_LENGTH} 个字符"
            return
        self.expression = self.expression[: self.cursor] + text + self.expression[self.cursor :]
        self.cursor += len(text)
        self.history_index = None
        self.error = ""
        self.result = ""

    def backspace(self) -> None:
        if self.cursor:
            self.expression = self.expression[: self.cursor - 1] + self.expression[self.cursor :]
            self.cursor -= 1
            self.error = ""
            self.history_index = None
            self.result = ""

    def delete(self) -> None:
        if self.cursor < len(self.expression):
            self.expression = self.expression[: self.cursor] + self.expression[self.cursor + 1 :]
            self.error = ""
            self.history_index = None
            self.result = ""

    def move_cursor(self, step: int | str) -> None:
        if step == "home":
            self.cursor = 0
        elif step == "end":
            self.cursor = len(self.expression)
        else:
            self.cursor = max(0, min(len(self.expression), self.cursor + int(step)))

    def clear(self) -> None:
        self.expression = ""
        self.cursor = 0
        self.result = ""
        self.error = ""
        self.history_index = None

    def history_up(self) -> str:
        if not self.history:
            return "history"
        if self.history_index is None:
            self._history_draft = self.expression
            self.history_index = len(self.history) - 1
        elif self.history_index > 0:
            self.history_index -= 1
        self.expression = self.history[self.history_index].expression
        self.cursor = len(self.expression)
        self.result = ""
        self.error = ""
        return "history"

    def history_down(self) -> str:
        if self.history_index is None:
            return "history"
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.expression = self.history[self.history_index].expression
        else:
            self.history_index = None
            self.expression = self._history_draft
        self.cursor = len(self.expression)
        self.result = ""
        self.error = ""
        return "history"

    def submit(self) -> HistoryEntry | None:
        expression = self.expression.strip()
        if not expression:
            self.error = "请输入算式"
            return None
        try:
            stdout = self.evaluator.evaluate(expression)
        except Exception as exc:
            stderr = getattr(exc, "stderr", "") or ""
            entry = HistoryEntry(
                expression=expression,
                stdout=getattr(exc, "stdout", "") or "",
                stderr=stderr,
                success=False,
                error=str(exc),
            )
            self.error = entry.error_text or str(exc)
            self.result = ""
        else:
            entry = HistoryEntry(expression=expression, stdout=stdout, success=True)
            self.result = entry.display_text
            self.error = ""
            # Keep focus for a REPL-like flow and start the next expression
            # with an empty input line; the result now lives in history.
            self.expression = ""
            self.cursor = 0
        self.history.append(entry)
        self.history_index = None
        self._history_draft = ""
        return entry

    def handle_key(self, key: int | str) -> HistoryEntry | str | None:
        """Apply one curses key while focused and return a small action marker."""
        if isinstance(key, str):
            if len(key) != 1:
                return None
            key = ord(key)
        f6 = getattr(curses, "KEY_F6", -1006)
        if key == f6:
            return self.toggle_focus()
        if not self.focused:
            return None
        if key == 27:
            return self.blur()
        if key in (10, 13, getattr(curses, "KEY_ENTER", -1007)):
            return self.submit()
        if key == curses.KEY_UP:
            return self.history_up()
        if key == curses.KEY_DOWN:
            return self.history_down()
        if key == curses.KEY_LEFT:
            self.move_cursor(-1)
        elif key == curses.KEY_RIGHT:
            self.move_cursor(1)
        elif key == curses.KEY_HOME:
            self.move_cursor("home")
        elif key == curses.KEY_END:
            self.move_cursor("end")
        elif key in (curses.KEY_BACKSPACE, 8, 127):
            self.backspace()
        elif key == curses.KEY_DC:
            self.delete()
        elif key == 21:
            self.clear()
        elif 32 <= key <= 126:
            self.insert(chr(key))
        else:
            return None
        return "edited"

    process_key = handle_key


__all__ = [
    "BcCalculatorError",
    "BcEvaluator",
    "BcTimeoutError",
    "BcUnavailableError",
    "CalculatorSession",
    "HistoryEntry",
    "MAX_EXPRESSION_LENGTH",
]
