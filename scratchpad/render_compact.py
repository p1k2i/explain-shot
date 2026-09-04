"""Render the gallery with a large conversation so the context gauge and
Compact button are visible."""

import os, sys, tempfile, asyncio
from datetime import datetime, timedelta
sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("APPDATA", tempfile.mkdtemp(prefix='es_compact_render_'))

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
db = Database(); signals = AppSignals()
scrs = ScreenshotService(db, settings.screenshot, settings.resolved_screenshot_dir(), signals)

scratch = tempfile.mkdtemp()
Image.new("RGB", (600, 300), "#123456").save(os.path.join(scratch, "seed.png"))
from pathlib import Path
rec = scrs.import_existing(Path(scratch) / "seed.png")

history = ChatHistory(db)
chat = ChatController(history, lambda: AIProvider(settings.ai.base_url, model=settings.ai.model),
                     context_chars_limit=2000)

# Build a big-enough conversation to push the gauge past 100%
long_a = "A very long answer that explains multiple things in detail. " * 8
for i in range(6):
    history.append_root(rec.id, "user", f"Question {i+1}?")
    history.append_root(rec.id, "assistant", long_a, model="m")

# Also seed one existing compact so the summary row shows in the transcript
history.compact_from_tip(rec.id, "Earlier in the chat the user asked about the app's architecture, and we discussed the ChatController and history model.")
history.append_root(rec.id, "user", "OK, one more question after compact.")
history.append_root(rec.id, "assistant", "Sure, happy to help.", model="m")

gw = GalleryWindow(
    settings=settings, signals=signals, db=db,
    screenshots=scrs, thumbnails=ThumbnailCache(size=settings.ui.thumbnail_px),
    presets=PresetManager(db, signals), history=history, chat=chat,
)
gw.resize(1400, 860)
gw.show()
gw.screenshots_panel.select(rec.id)

for _ in range(10):
    app.processEvents()
gw.grab().save("scratchpad/gallery_compact.png", "PNG")
print("saved scratchpad/gallery_compact.png")
