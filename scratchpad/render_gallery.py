"""Render the new gallery + settings windows to PNGs so a human can review them."""

import sys, os, tempfile
sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())
# Use the native Windows platform so system fonts (Segoe UI) actually load.

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSize

app = QApplication.instance() or QApplication(sys.argv)

from explainshot.config.settings import load_settings
from explainshot.core.database import Database
from explainshot.core.signals import AppSignals
from explainshot.capture.screenshot import ScreenshotService
from explainshot.capture.thumbnails import ThumbnailCache
from explainshot.presets.manager import PresetManager
from explainshot.ai.history import ChatHistory
from explainshot.ai.provider import AIProvider
from explainshot.ui.theme import Theme, apply_theme
from explainshot.ui.gallery import GalleryWindow
from explainshot.ui.settings import SettingsWindow


def render(widget, out_path, size=None):
    if size:
        widget.resize(*size)
    widget.show()
    # Two-pass paint so async QSS + layout settle
    app.processEvents()
    app.processEvents()
    widget.grab().save(out_path, "PNG")
    print(f"saved {out_path}")


settings = load_settings()

for theme_name in ("dark", "light"):
    settings.ui.theme = theme_name
    apply_theme(app, Theme.resolve(theme_name, settings.ui.accent))

    # Seed some fake presets so the right column has content
    db = Database()
    signals = AppSignals()
    thumb = ThumbnailCache(size=settings.ui.thumbnail_px)
    screenshots = ScreenshotService(db, settings.screenshot, settings.resolved_screenshot_dir(), signals)
    presets = PresetManager(db, signals)
    history = ChatHistory(db)

    def make_provider():
        ai = settings.ai
        return AIProvider(ai.base_url, ai.api_key, ai.model, float(ai.timeout_seconds))

    gallery = GalleryWindow(
        settings=settings, signals=signals,
        screenshots=screenshots, thumbnails=thumb,
        presets=presets, history=history,
        provider_factory=make_provider,
    )
    render(gallery, f"scratchpad/gallery_{theme_name}.png", (1400, 860))
    gallery.close()

    settings_win = SettingsWindow(settings, signals)
    render(settings_win, f"scratchpad/settings_{theme_name}.png", (620, 560))
    settings_win.close()

print("done")
