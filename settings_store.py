"""Editable JSON/TOML settings documents used by the interactive TUI."""

from __future__ import annotations

import json
import os
import tempfile
import tomllib
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import tomli_w
from platformdirs import user_config_path

from app_config import Settings


ConfigFormat = Literal["json", "toml"]
_FORMATS: dict[str, ConfigFormat] = {".json": "json", ".toml": "toml"}


@dataclass(frozen=True)
class SettingsDocument:
    """A settings snapshot plus the target file and retained unknown settings."""

    path: Path
    format: ConfigFormat
    settings: Settings
    raw_data: dict[str, Any]
    exists: bool


def default_tui_config_path() -> Path:
    """Return the per-user writable configuration target for the TUI."""
    return Path(user_config_path("unit-translator", appauthor=False)) / "settings.toml"


def resolve_tui_config_path(config_path: str | Path | None = None) -> Path:
    """Resolve the default or explicit TUI configuration path."""
    path = (
        Path(config_path).expanduser()
        if config_path is not None
        else default_tui_config_path()
    )
    if path.suffix.lower() not in _FORMATS:
        raise ValueError("TUI 配置文件扩展名必须为 .json 或 .toml")
    return path


def _format_for(path: Path) -> ConfigFormat:
    try:
        return _FORMATS[path.suffix.lower()]
    except KeyError as exc:
        raise ValueError("TUI 配置文件扩展名必须为 .json 或 .toml") from exc


def _read_mapping(path: Path, format: ConfigFormat) -> dict[str, Any]:
    try:
        if format == "toml":
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        else:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
    except FileNotFoundError as exc:
        raise ValueError(f"配置文件不存在: {path}") from exc
    except (OSError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"配置文件无法读取: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("配置文件根节点必须是对象")
    return data


def load_settings_document(
    config_path: str | Path | None = None,
) -> SettingsDocument:
    """Load an editable document, seeding defaults when its file does not exist."""
    path = resolve_tui_config_path(config_path)
    format = _format_for(path)
    if not path.exists():
        settings = Settings()
        return SettingsDocument(path, format, settings, settings.to_dict(), False)

    raw_data = _read_mapping(path, format)
    return SettingsDocument(
        path,
        format,
        Settings.from_mapping(raw_data),
        deepcopy(raw_data),
        True,
    )


def _without_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_none(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [_without_none(item) for item in value]
    if isinstance(value, tuple):
        return [_without_none(item) for item in value]
    return value


def _serialize(data: dict[str, Any], format: ConfigFormat) -> str:
    if format == "toml":
        return tomli_w.dumps(_without_none(data))
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary = Path(temporary_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise ValueError(f"配置文件无法保存: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def save_settings_document(
    document: SettingsDocument,
    settings: Settings,
) -> SettingsDocument:
    """Persist known settings while retaining unrelated top-level configuration."""
    raw_data = deepcopy(document.raw_data)
    raw_data.update(settings.to_dict())
    try:
        _atomic_write(document.path, _serialize(raw_data, document.format))
    except (TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("配置文件无法保存:"):
            raise
        raise ValueError(f"配置文件无法保存: {exc}") from exc
    return SettingsDocument(document.path, document.format, settings, raw_data, True)
