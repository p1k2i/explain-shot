"""Application settings — one flat table in SQLite, dot-notation keys.

The old code had seven config dataclasses with roughly forty settings, many unused
or overlapping (both ui.opacity and ui.gallery_opacity, ChatConfig with
retention/backup/scan_interval that never ran, an OptimizationConfig that mostly
duplicated cache defaults). This model keeps only the settings the app actually
reads at runtime.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any

from .paths import database_path, screenshots_dir


@dataclass
class HotkeyConfig:
    capture_region: str = "ctrl+shift+s"
    toggle_gallery: str = "ctrl+shift+g"
    open_settings: str = "ctrl+shift+p"


@dataclass
class AIConfig:
    """OpenAI-compatible AI provider. Ollama's /v1 endpoint fits here."""
    base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    model: str = "llama3.2-vision"
    timeout_seconds: int = 120


@dataclass
class ScreenshotConfig:
    directory: str = ""  # empty -> screenshots_dir() default at read time
    image_format: str = "PNG"  # PNG or JPEG
    jpeg_quality: int = 92


@dataclass
class UIConfig:
    theme: str = "dark"        # "dark" | "light"
    accent: str = "#0067c0"    # Windows 11 default accent
    thumbnail_px: int = 160


@dataclass
class Settings:
    hotkeys: HotkeyConfig = field(default_factory=HotkeyConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    screenshot: ScreenshotConfig = field(default_factory=ScreenshotConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    autostart: bool = False

    def resolved_screenshot_dir(self) -> str:
        return self.screenshot.directory or str(screenshots_dir())


# --- persistence --------------------------------------------------------------

_TABLE = "settings"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(database_path()))
    conn.execute(f"CREATE TABLE IF NOT EXISTS {_TABLE} (key TEXT PRIMARY KEY, value TEXT)")
    return conn


def _flatten(prefix: str, obj: Any, out: dict[str, Any]) -> None:
    if is_dataclass(obj) and not isinstance(obj, type):
        for f in fields(obj):
            _flatten(f"{prefix}.{f.name}" if prefix else f.name, getattr(obj, f.name), out)
    else:
        out[prefix] = obj


def _assign(target: Any, key: str, value: Any) -> None:
    parts = key.split(".")
    node = target
    for p in parts[:-1]:
        if not hasattr(node, p):
            return
        node = getattr(node, p)
    leaf = parts[-1]
    if not hasattr(node, leaf):
        return
    # coerce to the declared type where sensible
    current = getattr(node, leaf)
    if isinstance(current, bool) and not isinstance(value, bool):
        value = str(value).lower() in ("1", "true", "yes")
    elif isinstance(current, int) and not isinstance(value, bool):
        try:
            value = int(value)
        except (TypeError, ValueError):
            return
    elif isinstance(current, float):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return
    setattr(node, leaf, value)


def load_settings() -> Settings:
    settings = Settings()
    with _connect() as conn:
        rows = conn.execute(f"SELECT key, value FROM {_TABLE}").fetchall()
    for key, raw in rows:
        try:
            value = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            value = raw
        _assign(settings, key, value)
    return settings


def save_settings(settings: Settings) -> None:
    flat: dict[str, Any] = {}
    _flatten("", settings, flat)
    with _connect() as conn:
        conn.executemany(
            f"INSERT OR REPLACE INTO {_TABLE} (key, value) VALUES (?, ?)",
            [(k, json.dumps(v)) for k, v in flat.items()],
        )
        conn.commit()


def update_setting(key: str, value: Any) -> None:
    """Write a single key. Cheaper than save_settings() when just one field changed."""
    with _connect() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO {_TABLE} (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
        conn.commit()


def as_dict(settings: Settings) -> dict[str, Any]:
    return asdict(settings)
