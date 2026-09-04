"""Render a gallery with a long chat so we can eyeball whether action bars
stay visible instead of being covered by the next row's bubble."""

import os, sys, tempfile, asyncio
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

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

# One screenshot on disk
scratch = tempfile.mkdtemp()
Image.new("RGB", (600, 300), "#123456").save(os.path.join(scratch, "seed.png"))
from pathlib import Path
rec = scrs.import_existing(Path(scratch) / "seed.png")

history = ChatHistory(db)
chat = ChatController(history, lambda: AIProvider(settings.ai.base_url, model=settings.ai.model))

# Long-form conversation: several rounds, some multi-paragraph, plus code
short_q = "Quick question."
long_a = (
    "Sure — a longer paragraph so the bubble becomes tall.\n\n"
    "Second paragraph with more content. Here is a bulleted list:\n"
    "- point one\n- point two\n- point three\n\n"
    "```python\ndef hello():\n    print('hi from ExplainShot')\n```\n"
    "And a closing line that wraps for good measure."
)
for i in range(4):
    history.append_root(rec.id, "user", f"{short_q} (round {i+1})")
    history.append_root(rec.id, "assistant", long_a, model="m")

gw = GalleryWindow(
    settings=settings, signals=signals, db=db,
    screenshots=scrs, thumbnails=ThumbnailCache(size=settings.ui.thumbnail_px),
    presets=PresetManager(db, signals), history=history, chat=chat,
)
gw.resize(1400, 860)
gw.show()
gw.screenshots_panel.select(rec.id)

for _ in range(12):
    app.processEvents()
gw.grab().save("scratchpad/gallery_long.png", "PNG")
print("saved scratchpad/gallery_long.png")
