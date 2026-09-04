"""Render every window in the new UI to PNGs so a human can review."""

import sys, os, tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QColor, QPainter, QFont

app = QApplication.instance() or QApplication(sys.argv)

from explainshot.config.settings import load_settings
from explainshot.core.database import Database
from explainshot.core.signals import AppSignals
from explainshot.capture.screenshot import ScreenshotService
from explainshot.capture.thumbnails import ThumbnailCache
from explainshot.presets.manager import PresetManager
from explainshot.ai.history import ChatHistory, MessageNode
from explainshot.ai.provider import AIProvider
from explainshot.ui.theme import Theme, apply_theme
from explainshot.ui.gallery import GalleryWindow
from explainshot.ui.settings import SettingsWindow
from explainshot.ui.overlay import CaptureOverlay


def render(widget, out_path, size=None):
    if size:
        widget.resize(*size)
    widget.show()
    for _ in range(4):
        app.processEvents()
    widget.grab().save(out_path, "PNG")
    print(f"saved {out_path}")


def synthetic_pixmap() -> QPixmap:
    """Something to show in the CaptureEditor screenshot."""
    pixmap = QPixmap(700, 420)
    pixmap.fill(QColor("#1e3a52"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("#f5f5f5"))
    font = QFont("Segoe UI", 32, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), 0x0004 | 0x0080, "screen region\ncaptured here")
    painter.end()
    return pixmap


for theme_name in ("dark", "light"):
    settings = load_settings()
    settings.ui.theme = theme_name
    apply_theme(app, Theme.resolve(theme_name, settings.ui.accent))

    db = Database()
    signals = AppSignals()
    thumb = ThumbnailCache(size=settings.ui.thumbnail_px)
    screenshots = ScreenshotService(db, settings.screenshot, settings.resolved_screenshot_dir(), signals)

    # Seed a couple of fake screenshots so the panel is non-empty.
    from PIL import Image, ImageDraw
    scratch = os.path.join(tempfile.mkdtemp(), "seed")
    os.makedirs(scratch, exist_ok=True)
    for i, colour in enumerate([("#0067c0", "Dashboard"), ("#c94040", "Error log"), ("#4dd0e1", "Chart")]):
        img = Image.new("RGB", (640, 400), colour[0])
        draw = ImageDraw.Draw(img)
        draw.text((240, 180), colour[1], fill="white")
        path = os.path.join(scratch, f"seed_{i}.png")
        img.save(path)
        from pathlib import Path
        screenshots.import_existing(Path(path))
    presets = PresetManager(db, signals)
    history = ChatHistory(db)

    def make_provider():
        return AIProvider(settings.ai.base_url, model=settings.ai.model)

    gallery = GalleryWindow(
        settings=settings, signals=signals, db=db,
        screenshots=screenshots, thumbnails=thumb,
        presets=presets, history=history,
        provider_factory=make_provider,
    )
    gallery.chat_panel.set_enabled(True)

    # Force a selection state on the first screenshot card so the render
    # captures its selected styling (accent border), plus fake a hover state
    # on the first preset card so its hover styling shows.
    def _promote_states():
        cards = list(gallery.screenshots_panel._cards.values())
        if cards:
            cards[0].set_selected(True, instant=True)
        list_layout = gallery.presets_panel._list
        for i in range(list_layout.count()):
            item = list_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                # HoverAnimator is stored as a child QObject of the widget.
                for child in widget.children():
                    if child.__class__.__name__ == "HoverAnimator":
                        child._hovered = True
                        child._transition(instant=True)
                        break
                break
    _promote_states()
    for _ in range(3):
        app.processEvents()
    now = datetime.now()

    conversation = [
        MessageNode(id=1, parent_id=None, role="user",
                    content="What library is being used in this codebase?",
                    model=None, created_at=now - timedelta(minutes=3),
                    siblings=[1], index_in_siblings=0),
        MessageNode(id=2, parent_id=1, role="assistant",
                    content=(
                        "Looks like **PyQt6** — I can see:\n"
                        "- `QApplication` in the imports\n"
                        "- `pyqtSignal` in the class body\n"
                        "- The typical `super().__init__(parent)` pattern in the widget\n\n"
                        "```python\n"
                        "app = QApplication(sys.argv)\n"
                        "```\n"
                    ),
                    model="gpt-4o", created_at=now - timedelta(minutes=3),
                    siblings=[2, 5], index_in_siblings=0),
        MessageNode(id=3, parent_id=2, role="user",
                    content="How can I add a dark title bar on Windows?",
                    model=None, created_at=now - timedelta(minutes=2),
                    siblings=[3], index_in_siblings=0),
        MessageNode(id=4, parent_id=3, role="assistant",
                    content=(
                        "Call `DwmSetWindowAttribute` with attribute 20 "
                        "(`DWMWA_USE_IMMERSIVE_DARK_MODE`) on the window's HWND — "
                        "that flips the caption to the dark theme."
                    ),
                    model="gpt-4o", created_at=now - timedelta(minutes=1),
                    siblings=[4], index_in_siblings=0),
    ]
    gallery.chat_panel.render(conversation)
    render(gallery, f"scratchpad/gallery2_{theme_name}.png", (1400, 860))
    gallery.close()

    settings_win = SettingsWindow(settings, signals)
    render(settings_win, f"scratchpad/settings2_{theme_name}.png", (640, 580))
    settings_win.close()

    if theme_name == "dark":
        overlay = CaptureOverlay(synthetic_pixmap(), accent=settings.ui.accent)
        overlay.resize(900, 620)
        from PyQt6.QtCore import QRect
        overlay._selection = QRect(80, 100, 700, 400)
        overlay._enter_editing()
        render(overlay, "scratchpad/overlay_dark.png", (900, 620))
        overlay.close()

print("done")
