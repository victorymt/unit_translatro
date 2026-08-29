"""Capture deterministic SVG screens for the Textual TUI.

Use this while iterating on layout instead of relying only on widget-state tests:

    uv run python scripts/capture_tui.py --output-dir /tmp/unit-translator-tui
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from settings_store import load_settings_document
from textual.widgets import TabbedContent

from tui_app import UnitTranslatorApp


VIEWPORTS: tuple[tuple[str, tuple[int, int]], ...] = (
    ("wide", (120, 40)),
    ("threshold", (96, 30)),
    ("narrow", (80, 24)),
)
SCREEN_NAMES = ("calculator", "channels", "channel-editor")


def _hide_export_artifacts(app: UnitTranslatorApp) -> None:
    """Hide the inactive comparison table while exporting the calculator view."""
    app.query_one("#comparison-table").display = False


async def _capture_screen(
    output_dir: Path,
    viewport_name: str,
    size: tuple[int, int],
    screen_name: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        config_path = Path(directory) / "settings.toml"
        app = UnitTranslatorApp(load_settings_document(config_path))
        async with app.run_test(size=size) as pilot:
            if screen_name == "channels":
                app.query_one("#main-tabs", TabbedContent).active = "channels"
            elif screen_name == "channel-editor":
                app.query_one("#main-tabs", TabbedContent).active = "channels"
                await pilot.pause()
                await pilot.click("#new-channel")
            await pilot.pause()
            if screen_name == "calculator":
                _hide_export_artifacts(app)
                await pilot.pause()
            svg = app.export_screenshot(
                title=f"Unit Translator — {screen_name} — {size[0]}x{size[1]}"
            )
        output_path = output_dir / f"{viewport_name}-{screen_name}.svg"
        output_path.write_text(svg, encoding="utf-8")


async def capture(output_dir: Path) -> None:
    """Export the key workflows at each supported viewport."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for viewport_name, size in VIEWPORTS:
        for screen_name in SCREEN_NAMES:
            await _capture_screen(output_dir, viewport_name, size, screen_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for generated SVG files (for example /tmp/unit-translator-tui).",
    )
    args = parser.parse_args()
    asyncio.run(capture(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
