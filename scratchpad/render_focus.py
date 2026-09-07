"""Render startup focus (card, no slider ring) and slider-focused state."""
import os, sys, tempfile, asyncio
sys.path.insert(0, os.path.abspath("."))
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="es_focusr_")

from pathlib import Path
from PIL import Image
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
import qasync
loop = qasync.QEventLoop(app); asyncio.set_event_loop(loop)

from explainshot.config.settings import load_settings
from explainshot.core.database import Database
from explainshot.core.signals import AppSignals
from explainshot.capture.screenshot import ScreenshotService
from explainshot.capture.thumbnails import ThumbnailCache
from explainshot.presets.manager import PresetManager
from explainshot.ai.history import ChatHistory
from explainshot.ai.controller import ChatController
from explainshot.ai.provider import AIProvider
from explainshot.ui.theme import Theme, apply_theme
from explainshot.ui.gallery import GalleryWindow

settings = load_settings()
apply_theme(app, Theme.resolve(settings.ui.theme, settings.ui.accent))
db = Database(); sig = AppSignals()
scrs = ScreenshotService(db, settings.screenshot, settings.resolved_screenshot_dir(), sig)
scratch = tempfile.mkdtemp()
for i, c in enumerate(["#8a2f2f", "#2f8a4f", "#2f4f8a", "#8a7f2f", "#2f8a8a", "#7a2f8a"]):
    Image.new("RGB", (600 + i * 8, 340 + i * 6), c).save(os.path.join(scratch, f"cap_{i}.png"))
    scrs.import_existing(Path(scratch) / f"cap_{i}.png")
history = ChatHistory(db)
chat = ChatController(history, lambda: AIProvider(settings.ai.base_url, model=settings.ai.model))
gw = GalleryWindow(settings=settings, signals=sig, db=db, screenshots=scrs,
                   thumbnails=ThumbnailCache(size=settings.ui.thumbnail_px),
                   presets=PresetManager(db, sig), history=history, chat=chat)
gw.resize(1200, 780); gw.show(); gw.activateWindow()
for _ in range(16):
    app.processEvents()

# Startup: the singleShot(_focus_initial) has run -> a card is focused.
gw.grab().save("scratchpad/focus_startup.png", "PNG")
print("startup focus:", type(QApplication.focusWidget()).__name__)

# Navigate to the slider and grab (should show its focus ring, card keeps selection).
sp = gw.screenshots_panel
sp._size_slider.setFocus()
for _ in range(6):
    app.processEvents()
gw.grab().save("scratchpad/focus_slider.png", "PNG")
print("saved focus_startup.png + focus_slider.png")
