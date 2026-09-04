"""Load app icons from resources/icons/."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image
from PyQt6.QtGui import QIcon, QPixmap

from ..config.paths import resources_dir


def _icons_dir() -> Path:
    return resources_dir() / "icons"


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    ico = _icons_dir() / "app.ico"
    if ico.exists():
        return QIcon(str(ico))
    png = _icons_dir() / "icon_idle.png"
    if png.exists():
        return QIcon(str(png))
    return QIcon()


def tray_pil_image() -> Image.Image:
    """Pystray needs a PIL Image, not a QIcon."""
    png = _icons_dir() / "icon_idle.png"
    if png.exists():
        return Image.open(png)
    # last-resort fallback
    fallback = Image.new("RGBA", (16, 16), (0, 103, 192, 255))
    return fallback


def app_pixmap(size: int = 128) -> QPixmap:
    icon = app_icon()
    return icon.pixmap(size, size)
