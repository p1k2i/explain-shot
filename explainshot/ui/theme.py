"""Fluent Design 2 tokens and QSS templating.

The old code had 13 CSS files split across gallery/settings/overlay/dark/light
with hover-state/selection-state/component subfolders — that layering was
premature abstraction, most files were <2KB. Here we keep one QSS template
per theme and interpolate tokens at load time. Solid backgrounds throughout
(no WA_TranslucentBackground) — that was the source of the gallery's
slowness on translucent windows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from ..config.paths import resources_dir


@dataclass(frozen=True)
class Palette:
    # Surfaces
    bg_base: str
    bg_layer: str
    bg_layer_alt: str
    bg_elevated: str
    # Text
    text_primary: str
    text_secondary: str
    text_disabled: str
    # Strokes & separators
    stroke: str
    stroke_strong: str
    # Interactive
    accent: str
    accent_pressed: str
    accent_text: str
    # Semantic
    danger: str


DARK = Palette(
    bg_base="#202020",
    bg_layer="#2b2b2b",
    bg_layer_alt="#323232",
    bg_elevated="#3a3a3a",
    text_primary="#ffffff",
    text_secondary="#b3b3b3",
    text_disabled="#6f6f6f",
    stroke="#3d3d3d",
    stroke_strong="#5a5a5a",
    accent="#0067c0",
    accent_pressed="#005ba1",
    accent_text="#ffffff",
    danger="#c94040",
)

LIGHT = Palette(
    bg_base="#f3f3f3",
    bg_layer="#ffffff",
    bg_layer_alt="#f9f9f9",
    bg_elevated="#ffffff",
    text_primary="#1b1b1b",
    text_secondary="#5c5c5c",
    text_disabled="#a0a0a0",
    stroke="#e6e6e6",
    stroke_strong="#cfcfcf",
    accent="#0067c0",
    accent_pressed="#005ba1",
    accent_text="#ffffff",
    danger="#c94040",
)


@dataclass
class Theme:
    name: str
    palette: Palette
    accent_override: str | None = None

    @classmethod
    def resolve(cls, name: str, accent_override: str | None = None) -> "Theme":
        palette = DARK if name == "dark" else LIGHT
        return cls(name=name, palette=palette, accent_override=accent_override)

    @property
    def effective_accent(self) -> str:
        return self.accent_override or self.palette.accent


def _theme_css_path() -> Path:
    return resources_dir() / "ui" / "theme.qss"


_TOKEN_RE = re.compile(r"@([a-z][a-z0-9_]*)")


def _read_template() -> str:
    path = _theme_css_path()
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def render_stylesheet(theme: Theme) -> str:
    template = _read_template()
    p = theme.palette
    accent = theme.effective_accent
    tokens = {
        "bg_base": p.bg_base,
        "bg_layer": p.bg_layer,
        "bg_layer_alt": p.bg_layer_alt,
        "bg_elevated": p.bg_elevated,
        "text_primary": p.text_primary,
        "text_secondary": p.text_secondary,
        "text_disabled": p.text_disabled,
        "stroke": p.stroke,
        "stroke_strong": p.stroke_strong,
        "accent": accent,
        "accent_pressed": p.accent_pressed,
        "accent_text": p.accent_text,
        "danger": p.danger,
    }
    # Match a whole token — `\b` around the alphabetical part so `@bg_layer`
    # never eats the prefix of `@bg_layer_alt`. Naive str.replace ordered by
    # length is another option; the regex reads more clearly.
    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        return tokens.get(key, match.group(0))
    return _TOKEN_RE.sub(_sub, template)


def apply_theme(app: QApplication, theme: Theme) -> None:
    app.setStyleSheet(render_stylesheet(theme))
